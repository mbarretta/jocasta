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
3. The entry's ``owner`` is read from the default branch. An owner of ``~``
   (released) means no owner. An entry that is not on the default branch is
   a new entry, which only its owner may add by direct commit: not merged.
4. The change itself must be one of the two shapes a consensus PR carries
   (both sides are parsed, not diffed as text):

   - a **deprecation**: ``status`` goes ``active`` -> ``deprecated`` and a
     ``deprecated`` block appears whose ``route`` is ``owner``, ``consensus``,
     or ``stale-source`` (the sweep's PRs carry the last); every other field
     is unchanged and the body is unchanged or only appended to;
   - a **claim**: ``owner`` becomes the PR author's login and nothing else
     changes.

   Anything else (``install``, ``source``, ``kind``, a rewritten body, a
   claim naming someone other than the author) gets one comment and no
   merge, whatever the votes say. ``install`` is the line teammates copy and
   run, so two votes must not be able to change it.
5. Only reviews from repository insiders count: ``author_association`` is
   ``OWNER``, ``MEMBER``, or ``COLLABORATOR``. ``[bot]`` accounts and, on a
   public instance, outside accounts are ignored. The PR author is a voice
   only under the same test.
6. Each reviewer's *latest* ``APPROVED``, ``CHANGES_REQUESTED``, or
   ``DISMISSED`` review is what counts (a dismissed approval is gone; a later
   ``COMMENTED`` or ``PENDING`` review changes nothing). Logins are compared
   the way GitHub does, without regard to case. Then:

   - the owner's latest review is ``APPROVED``           -> merge, route ``owner``
   - the owner's latest review is ``CHANGES_REQUESTED``  -> comment once, no merge
   - otherwise count distinct non-owner voices: the PR author (when they are
     not the owner) plus every non-owner, non-author reviewer whose latest
     review is ``APPROVED``. Two or more -> merge, route ``consensus``.
     Fewer -> print how many are still needed and exit 0.

7. Merges use ``gh pr merge --squash`` with a subject naming the route.

Exit status: 0 whenever a decision was reached (merged or not), 1 when ``gh``
is missing or a GitHub call fails, 2 on a usage error. Only the standard
library and PyYAML (via ``jocasta_common``) are used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field

import jocasta_common as jc

PAGE_SIZE = 100
VOICES_REQUIRED = 2
ENTRY_PATH_RE = re.compile(r"^entries/([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")

# ``author_association`` values (on a PR or a review) that make an account a
# repository insider. Anything else (NONE, CONTRIBUTOR, FIRST_TIMER, ...) is an
# outside account, which on a public instance is anyone with a GitHub login.
VOICE_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# Review states that replace a reviewer's recorded state. COMMENTED and PENDING
# say nothing about approval, so they must not overwrite a veto or an approval.
COUNTED_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})

# ``deprecated.route`` values a PR may carry: every route the schema knows. A
# person's PR writes ``owner`` or ``consensus``; the stale sweep's PRs write
# ``stale-source`` and are merged by this script like any other deprecation.
PR_DEPRECATION_ROUTES = frozenset(jc.ROUTES)
# The same routes as the scope-refusal comment lists them: "`a`, `b`, or `c`".
_ROUTE_LIST = ", ".join(f"`{route}`" for route in jc.ROUTES[:-1]) + f", or `{jc.ROUTES[-1]}`"

# Stands in for a frontmatter key one side of a PR lacks, so "absent" and
# "present with the value None" (``owner: ~``) compare as different.
_ABSENT = object()

# Every comment this script posts opens with a marker naming the situation it
# explains, so a re-run stays quiet about a situation it already explained but
# still speaks up when the situation changes (the workflow fires on every
# review and push).
COMMENT_MARKER = "<!-- jocasta consensus-merge: {kind} -->"

# PR label -> verb for the merge commit subject. The skill applies exactly one
# of these when it opens the PR (references/write-paths.md).
LABEL_VERBS = {"deprecation": "deprecate", "ownership": "claim"}
DEFAULT_VERB = "update"


@dataclass
class Decision:
    """What to do with the PR and why, from the review state alone."""

    action: str  # "merge" | "blocked" | "wait"
    route: str | None = None  # "owner" | "consensus" when action == "merge"
    voices: list[str] = field(default_factory=list)
    reason: str = ""


# --- gh ----------------------------------------------------------------------

# ``gh`` and ``gh_ok`` live in jocasta_common (stale_sweep.py shares them);
# ``GhError`` is re-exported so ``run`` can catch it by its local name.
GhError = jc.GhError


def gh_json(endpoint: str):
    return json.loads(jc.gh_ok(["api", endpoint]).stdout)


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


def fetch_entry_text(repo: str, path: str, ref: str) -> str | None:
    """Raw text of ``path`` at ``ref`` (a branch or a commit SHA), or ``None`` when it is not there."""
    result = jc.gh(["api", "-H", "Accept: application/vnd.github.raw+json", f"repos/{repo}/contents/{path}?ref={ref}"])
    if result.returncode == 0:
        return result.stdout
    if "HTTP 404" in result.stderr:
        return None
    raise GhError(f"gh api repos/{repo}/contents/{path} failed: {jc.failure_detail(result)}")


def comment_once(repo: str, pr: int, kind: str, body: str) -> bool:
    """Post ``body`` unless this script already explained ``kind`` on this PR.

    ``kind`` names the situation (``files``, ``frontmatter``, ``scope``,
    ``blocked``).
    Each is stable until a human acts, so one comment per situation is enough;
    a new situation on the same PR still gets its own comment.
    """
    marker = COMMENT_MARKER.format(kind=kind)
    existing = gh_list(f"repos/{repo}/issues/{pr}/comments")
    if any(marker in (c.get("body") or "") for c in existing):
        return False
    jc.gh_ok(["api", "--method", "POST", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={marker}\n{body}"])
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
    """Map each insider reviewer to their most recent counted review state.

    Bots, outside accounts (``author_association`` not in
    ``VOICE_ASSOCIATIONS``), and reviews whose state is not in
    ``COUNTED_REVIEW_STATES`` are skipped. Two spellings of one login are one
    reviewer; the key is the login as GitHub last reported it.
    """
    ordered = sorted(reviews, key=lambda r: r.get("submitted_at") or "")
    latest: dict[str, tuple[str, str]] = {}  # casefolded login -> (login, state)
    for review in ordered:
        login = (review.get("user") or {}).get("login")
        if not login or login.endswith("[bot]"):
            continue
        if review.get("author_association") not in VOICE_ASSOCIATIONS:
            continue
        state = review.get("state", "")
        if state not in COUNTED_REVIEW_STATES:
            continue
        latest[login.casefold()] = (login, state)
    return dict(latest.values())


def decide(*, owner: str | None, author: str, author_association: str | None, latest_reviews: dict[str, str]) -> Decision:
    """Apply the R-5 rules to the review state. Pure: no I/O.

    ``latest_reviews`` is ``latest_review_states``' output. Every login
    comparison is case-insensitive (``jocasta_common.same_login``); the author
    is a voice only when ``author_association`` marks them an insider.
    """
    if owner is not None:
        owner_state = next((state for login, state in latest_reviews.items() if jc.same_login(login, owner)), None)
        if owner_state == "APPROVED":
            return Decision("merge", route=jc.ROUTE_OWNER, voices=[owner], reason=f"owner {owner} approved")
        if owner_state == "CHANGES_REQUESTED":
            return Decision("blocked", reason=f"owner {owner} requested changes")

    voices: list[str] = []
    if author_association in VOICE_ASSOCIATIONS and not jc.same_login(author, owner) and not author.endswith("[bot]"):
        voices.append(author)
    for login in sorted(latest_reviews):
        if latest_reviews[login] == "APPROVED" and not jc.same_login(login, owner) and not jc.same_login(login, author):
            voices.append(login)

    if len(voices) >= VOICES_REQUIRED:
        return Decision("merge", route=jc.ROUTE_CONSENSUS, voices=voices, reason=f"{len(voices)} non-owner voices: {', '.join(voices)}")
    return Decision(
        "wait",
        voices=voices,
        reason=f"{len(voices)} of {VOICES_REQUIRED} non-owner voices" + (f" ({', '.join(voices)})" if voices else ""),
    )


def owner_from_entry_text(text: str) -> str | None:
    """The ``owner`` field of an entry's frontmatter; ``None`` for ``~``.

    Raises ``jocasta_common.EntryError`` when the text is not an entry.
    """
    frontmatter, _ = jc.parse_entry_text(text)
    return jc.entry_owner(frontmatter)


def change_in_scope(*, base_text: str | None, head_text: str | None, author: str) -> tuple[str | None, str]:
    """Return ``(shape, "")`` when the PR's edit is one a consensus PR may carry, else ``(None, why)``.

    ``shape`` is ``"deprecation"`` or ``"claim"`` (module docstring, rule 4).
    Both sides are parsed with ``jocasta_common.parse_entry_text`` and compared
    as values, so YAML quoting and trailing whitespace do not matter but every
    field and the body do. Pure: no I/O.
    """
    if base_text is None:
        return None, "it adds a new entry; a new entry is registered by its owner with a direct commit, and a PR can only deprecate or claim an entry that is already on the default branch"
    if head_text is None:
        return None, "the entry is missing at the head of the PR"
    try:
        base_fm, base_body = jc.parse_entry_text(base_text)
        head_fm, head_body = jc.parse_entry_text(head_text)
    except jc.EntryError as exc:
        return None, f"its frontmatter cannot be read ({exc})"

    changed = sorted(key for key in base_fm.keys() | head_fm.keys() if base_fm.get(key, _ABSENT) != head_fm.get(key, _ABSENT))
    body_changed = head_body != base_body

    if changed == ["deprecated", "status"] and _is_deprecation(base_fm, head_fm) and head_body.startswith(base_body):
        return "deprecation", ""
    if changed == ["owner"] and jc.same_login(head_fm.get("owner"), author) and not body_changed:
        return "claim", ""

    what = [f"`{key}`" for key in changed] + (["the body"] if body_changed else [])
    if not what:
        return None, "it changes nothing in the entry"
    return None, (
        f"it changes {', '.join(what)}; a consensus PR may only set `status: deprecated` with a `deprecated` block "
        f"(route {_ROUTE_LIST}) and append to the body, or set `owner` to its author (`{author}`) with nothing else changed"
    )


def _is_deprecation(base_fm: dict, head_fm: dict) -> bool:
    """``status`` went ``active`` -> ``deprecated`` and a well-routed block appeared where there was none."""
    block = head_fm.get("deprecated")
    return (
        base_fm.get("status") == jc.STATUS_ACTIVE
        and head_fm.get("status") == jc.STATUS_DEPRECATED
        and "deprecated" not in base_fm
        and isinstance(block, dict)
        and block.get("route") in PR_DEPRECATION_ROUTES
    )


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

        path = files[0]["filename"]
        default_branch = pr["base"].get("repo", {}).get("default_branch") or pr["base"]["ref"]
        base_text = fetch_entry_text(repo, path, default_branch)
        if base_text is None:
            owner = None
        else:
            try:
                owner = owner_from_entry_text(base_text)
            except jc.EntryError as exc:
                posted = comment_once(repo, pr_number, "frontmatter", f"Not merged: `{path}` on `{default_branch}` has unreadable frontmatter ({exc}), so its owner cannot be determined. Fix the entry on `{default_branch}` first.")
                print(f"{tag}: not merged: default-branch frontmatter unreadable: {exc}" + ("" if posted else " (already commented)"))
                return 0

        author = pr["user"]["login"]
        head_text = fetch_entry_text(repo, path, pr["head"]["sha"])
        shape, why = change_in_scope(base_text=base_text, head_text=head_text, author=author)
        if shape is None:
            posted = comment_once(repo, pr_number, "scope", f"Not merged: {why}. A consensus PR carries exactly one of those two changes; everything else about `{name}` is its owner's to write by direct commit. This PR stays open; push a version that fits, or close it.")
            print(f"{tag}: not merged: {why}" + ("" if posted else " (already commented)"))
            return 0

        reviews = gh_list(f"repos/{repo}/pulls/{pr_number}/reviews")
        decision = decide(owner=owner, author=author, author_association=pr.get("author_association"), latest_reviews=latest_review_states(reviews))

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
        jc.gh_ok(["pr", "merge", str(pr_number), "--repo", repo, "--squash", "--subject", subject, "--body", body])
        print(f"{tag}: merged (route: {decision.route}; {decision.reason})")
        return 0
    except GhError as exc:
        print(f"{tag}: {exc}", file=sys.stderr)
        return 1


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge a jocasta deprecation or ownership PR once it has the votes.")
    parser.add_argument("--repo", required=True, type=jc.repo_arg, help="registry repository as OWNER/REPO")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    args = parser.parse_args(argv)
    return run(args.repo, args.pr)


if __name__ == "__main__":
    sys.exit(main())
