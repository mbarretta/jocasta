#!/usr/bin/env python3
"""Decide whether a deprecation or ownership pull request has the votes, and merge it.

Usage::

    consensus_merge.py --repo OWNER/REPO --pr N

Run by the instance's ``consensus-merge`` workflow on every PR open, label,
synchronize, and review event. All state comes from the GitHub API through
``gh``; the script holds no state of its own, so re-running it is always safe.

Rules, in the order they are applied (charter R-5, D-3, P-4, P-5):

1. A PR that is already merged, or closed without merging, is left alone with
   a notice. This script never closes, reopens, or comments on a closed PR.
2. The PR must change exactly one file, and that file must be
   ``entries/<name>.md`` (not ``entries/README.md``, not a deletion, not a
   rename). Anything else gets one explanatory comment and no merge.
3. The entry's ``owner`` is read from the default branch. An entry that is
   absent there, or whose owner is ``~`` (released), has no owner.
4. Each reviewer's *latest* review is what counts (a dismissed approval is
   gone). Then:

   - the owner's latest review is ``APPROVED``           -> merge, route ``owner``
   - the owner's latest review is ``CHANGES_REQUESTED``  -> comment once, no merge
   - otherwise count distinct non-owner voices: the PR author (when they are
     not the owner) plus every non-owner, non-author reviewer whose latest
     review is ``APPROVED``. Two or more -> merge, route ``consensus``.
     Fewer -> print how many are still needed and exit 0.

5. Merges use ``gh pr merge --squash`` with a subject naming the route.

Exit status: 0 whenever a decision was reached (merged or not), 1 when ``gh``
is missing or a GitHub call fails, 2 on a usage error. Only the standard
library and PyYAML (via ``jocasta_common``) are used.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import jocasta_common as jc

GH_TIMEOUT = 30.0
PAGE_SIZE = 100
VOICES_REQUIRED = 2
ENTRY_PATH_RE = re.compile(r"^entries/([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")

# Every comment this script posts opens with a marker naming the situation it
# explains, so a re-run stays quiet about a situation it already explained but
# still speaks up when the situation changes (the workflow fires on every
# review and push).
COMMENT_MARKER = "<!-- jocasta consensus-merge: {kind} -->"

# PR label -> verb for the merge commit subject. The skill applies exactly one
# of these when it opens the PR (references/write-paths.md).
LABEL_VERBS = {"deprecation": "deprecate", "ownership": "claim"}
DEFAULT_VERB = "update"


class GhError(RuntimeError):
    """A ``gh`` invocation that could not be completed."""


@dataclass
class Decision:
    """What to do with the PR and why, from the review state alone."""

    action: str  # "merge" | "blocked" | "wait"
    route: str | None = None  # "owner" | "consensus" when action == "merge"
    voices: list[str] = field(default_factory=list)
    reason: str = ""


# --- gh ----------------------------------------------------------------------


def gh(args: list[str]) -> subprocess.CompletedProcess:
    """Run ``gh`` through ``jocasta_common.run_gh`` (tests monkeypatch that)."""
    try:
        return jc.run_gh(args, timeout=GH_TIMEOUT)
    except FileNotFoundError as exc:
        raise GhError("gh not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError(f"gh {' '.join(args[:2])} timed out after {GH_TIMEOUT:g}s") from exc


def gh_ok(args: list[str]) -> subprocess.CompletedProcess:
    """Run ``gh`` and raise ``GhError`` unless it exited 0."""
    result = gh(args)
    if result.returncode != 0:
        detail = " ".join(result.stderr.split()) or f"exit status {result.returncode}"
        raise GhError(f"gh {' '.join(args[:2])} failed: {detail}")
    return result


def gh_json(endpoint: str):
    return json.loads(gh_ok(["api", endpoint]).stdout)


def gh_list(endpoint: str) -> list:
    """Fetch every page of a list endpoint, ``PAGE_SIZE`` items at a time."""
    items: list = []
    page = 1
    while True:
        chunk = gh_json(f"{endpoint}?per_page={PAGE_SIZE}&page={page}")
        items.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            return items
        page += 1


def fetch_default_branch_entry(repo: str, path: str, ref: str) -> str | None:
    """Raw text of ``path`` at ``ref``, or ``None`` when it is not there."""
    result = gh(["api", "-H", "Accept: application/vnd.github.raw+json", f"repos/{repo}/contents/{path}?ref={ref}"])
    if result.returncode == 0:
        return result.stdout
    if "HTTP 404" in result.stderr:
        return None
    detail = " ".join(result.stderr.split()) or f"exit status {result.returncode}"
    raise GhError(f"gh api repos/{repo}/contents/{path} failed: {detail}")


def comment_once(repo: str, pr: int, kind: str, body: str) -> bool:
    """Post ``body`` unless this script already explained ``kind`` on this PR.

    ``kind`` names the situation (``files``, ``frontmatter``, ``blocked``).
    Each is stable until a human acts, so one comment per situation is enough;
    a new situation on the same PR still gets its own comment.
    """
    marker = COMMENT_MARKER.format(kind=kind)
    existing = gh_list(f"repos/{repo}/issues/{pr}/comments")
    if any(marker in (c.get("body") or "") for c in existing):
        return False
    gh_ok(["api", "--method", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={marker}\n{body}"])
    return True


# --- pure decisions -----------------------------------------------------------


def the_one_entry(files: list[dict]) -> tuple[str | None, str]:
    """Return ``(entry name, "")`` when the PR changes exactly one entry file, else ``(None, why)``."""
    if len(files) != 1:
        names = ", ".join(f"`{f['filename']}`" for f in files) or "none"
        return None, f"it changes {len(files)} files ({names}); a deprecation or ownership PR changes exactly one `entries/<name>.md`"
    changed = files[0]
    filename = changed["filename"]
    status = changed.get("status", "modified")
    if status == "removed":
        return None, f"it deletes `{filename}`; entries are deprecated, not deleted"
    if status == "renamed":
        return None, f"`{filename}` is renamed from `{changed.get('previous_filename', '?')}`; an entry keeps its name for life"
    match = ENTRY_PATH_RE.match(filename)
    if match is None:
        return None, f"it changes `{filename}`, which is not an `entries/<name>.md` file"
    return match.group(1), ""


def latest_review_states(reviews: list[dict]) -> dict[str, str]:
    """Map each reviewer to the state of their most recent review, bots excluded."""
    ordered = sorted(reviews, key=lambda r: r.get("submitted_at") or "")
    latest: dict[str, str] = {}
    for review in ordered:
        login = (review.get("user") or {}).get("login")
        if not login or login.endswith("[bot]"):
            continue
        latest[login] = review.get("state", "")
    return latest


def decide(*, owner: str | None, author: str, latest_reviews: dict[str, str]) -> Decision:
    """Apply the R-5 rules to the review state. Pure: no I/O."""
    if owner is not None:
        owner_state = latest_reviews.get(owner)
        if owner_state == "APPROVED":
            return Decision("merge", route="owner", voices=[owner], reason=f"owner {owner} approved")
        if owner_state == "CHANGES_REQUESTED":
            return Decision("blocked", reason=f"owner {owner} requested changes")

    voices: list[str] = []
    if author != owner and not author.endswith("[bot]"):
        voices.append(author)
    for login in sorted(latest_reviews):
        if latest_reviews[login] == "APPROVED" and login not in (owner, author):
            voices.append(login)

    if len(voices) >= VOICES_REQUIRED:
        return Decision("merge", route="consensus", voices=voices, reason=f"{len(voices)} non-owner voices: {', '.join(voices)}")
    return Decision(
        "wait",
        voices=voices,
        reason=f"{len(voices)} of {VOICES_REQUIRED} non-owner voices" + (f" ({', '.join(voices)})" if voices else ""),
    )


def owner_from_entry_text(text: str) -> str | None:
    """The ``owner`` field of an entry's frontmatter; ``None`` for ``~``.

    Raises ``jocasta_common.EntryError`` when the text is not an entry.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    try:
        frontmatter, _ = jc.parse_entry(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    owner = frontmatter.get("owner")
    return owner if isinstance(owner, str) and owner.strip() else None


def merge_subject(verb: str, name: str, route: str) -> str:
    return f"{verb} {name} (route: {route})"


# --- the run -----------------------------------------------------------------


def run(repo: str, pr_number: int) -> int:
    """Evaluate PR ``pr_number`` of ``repo`` and merge it if the rules allow."""
    tag = f"pr #{pr_number}"
    try:
        pr = gh_json(f"repos/{repo}/pulls/{pr_number}")
        if pr.get("merged"):
            print(f"{tag}: already merged; nothing to do")
            return 0
        if pr.get("state") != "open":
            print(f"{tag}: closed without merging; nothing to do (this script never closes or reopens a PR)")
            return 0

        files = gh_list(f"repos/{repo}/pulls/{pr_number}/files")
        name, why = the_one_entry(files)
        if name is None:
            posted = comment_once(repo, pr_number, "files", f"Not merged: {why}. Split the change so this PR touches only the one entry, or handle the other files by direct commit if you own them.")
            print(f"{tag}: not merged: {why}" + ("" if posted else " (already commented)"))
            return 0

        default_branch = pr["base"].get("repo", {}).get("default_branch") or pr["base"]["ref"]
        entry_text = fetch_default_branch_entry(repo, files[0]["filename"], default_branch)
        if entry_text is None:
            owner = None
        else:
            try:
                owner = owner_from_entry_text(entry_text)
            except jc.EntryError as exc:
                posted = comment_once(repo, pr_number, "frontmatter", f"Not merged: `{files[0]['filename']}` on `{default_branch}` has unreadable frontmatter ({exc}), so its owner cannot be determined. Fix the entry on `{default_branch}` first.")
                print(f"{tag}: not merged: default-branch frontmatter unreadable: {exc}" + ("" if posted else " (already commented)"))
                return 0

        author = pr["user"]["login"]
        reviews = gh_list(f"repos/{repo}/pulls/{pr_number}/reviews")
        decision = decide(owner=owner, author=author, latest_reviews=latest_review_states(reviews))

        if decision.action == "blocked":
            posted = comment_once(repo, pr_number, "blocked", f"Not merged: `{owner}` owns `{name}` and has requested changes. This PR stays open for discussion; the owner can approve it, or it can be closed by hand.")
            print(f"{tag}: not merged: {decision.reason}" + ("" if posted else " (already commented)"))
            return 0
        if decision.action == "wait":
            print(f"{tag}: waiting: {decision.reason}")
            return 0

        verb = next((LABEL_VERBS[label["name"]] for label in pr.get("labels", []) if label.get("name") in LABEL_VERBS), DEFAULT_VERB)
        subject = merge_subject(verb, name, decision.route)
        body = f"Merged by jocasta consensus-merge: {decision.reason}."
        gh_ok(["pr", "merge", str(pr_number), "--repo", repo, "--squash", "--subject", subject, "--body", body])
        print(f"{tag}: merged (route: {decision.route}; {decision.reason})")
        return 0
    except GhError as exc:
        print(f"{tag}: {exc}", file=sys.stderr)
        return 1


# --- CLI ---------------------------------------------------------------------


def _repo_arg(value: str) -> str:
    owner, _, name = value.partition("/")
    if not owner or not name or "/" in name:
        raise argparse.ArgumentTypeError(f"expected OWNER/REPO, got {value!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge a jocasta deprecation or ownership PR once it has the votes.")
    parser.add_argument("--repo", required=True, type=_repo_arg, help="registry repository as OWNER/REPO")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    args = parser.parse_args(argv)
    return run(args.repo, args.pr)


if __name__ == "__main__":
    sys.exit(main())
