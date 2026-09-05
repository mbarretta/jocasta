#!/usr/bin/env python3
"""Propose deprecation, by pull request, for active entries whose source is gone.

Usage::

    stale_sweep.py --root DIR --repo OWNER/REPO [--dry-run] [--pause SECONDS]

Run weekly by the instance's ``stale-sweep`` workflow from a checkout of the
registry's default branch (``--root``), with ``GH_TOKEN`` set and a git
identity configured. This is the third deprecation route (charter R-5): the
first two are a person's call, this one is the machinery noticing that a
tool's only pointer to the real thing no longer answers, so a dead tool never
sits in the archive looking alive (P-1). The sweep only *proposes*; people
merge or close (P-4, P-5).

For every entry:

1. ``status: deprecated`` is skipped with a notice. An entry whose frontmatter
   cannot be read, or has no usable ``source``/``status``, is skipped too; the
   validator, not the sweep, reports those.
2. The source is checked with ``jocasta_common.is_reachable``. If it fails,
   the check is repeated after a short pause, and the entry is stale only when
   both attempts fail. One flaky answer is not a dead tool.
3. A stale entry that already has an open PR labeled ``stale-source`` whose
   title names it (or whose head is its ``jocasta/stale-<name>`` branch) is
   skipped with the PR's URL, so a proposal that is still being decided is
   never duplicated.
4. Otherwise the sweep creates branch ``jocasta/stale-<name>`` from the
   checked-out commit, rewrites the entry's ``status: active`` line to
   ``status: deprecated`` plus a ``deprecated`` block (``route:
   stale-source``, today's date, a ``note`` carrying the unreachable reason),
   commits exactly that one file, force-pushes the branch (the ``jocasta/``
   namespace belongs to the machinery, and a proposal closed without a fix is
   replaced by the next one), and opens a PR labeled ``stale-source`` and
   ``deprecation`` whose body says how to dismiss it: fix the source and close.

``--dry-run`` reports what would be opened and touches nothing: no branch, no
commit, no label, no PR. Reads (the registry, reachability, the open-PR list)
still happen, so the report is accurate.

Exit status: 0 when the sweep finished (whether or not anything was stale), 1
when git or ``gh`` failed for at least one entry (the rest are still swept),
2 on a usage error. Only the standard library and PyYAML (via
``jocasta_common``) are used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import jocasta_common as jc

RETRY_PAUSE = 5.0
ROUTE = jc.ROUTE_STALE_SOURCE
BRANCH_PREFIX = "jocasta/stale-"
PR_LIST_LIMIT = 500
# Label -> description, created if absent (the template ships no labels and
# ``gh pr create --label`` fails on an unknown one). The wording matches
# references/write-paths.md.
LABELS = {
    "stale-source": "Opened by the stale sweep: the entry's source did not answer",
    "deprecation": "Proposes retiring an entry",
}
_STATUS_ACTIVE_RE = re.compile(rf"""^status\s*:\s*['"]?{re.escape(jc.STATUS_ACTIVE)}['"]?\s*$""")

Reachability = Callable[[str], tuple[bool, str]]
Sleep = Callable[[float], object]


class SweepError(RuntimeError):
    """An entry the sweep found stale but cannot rewrite safely."""


@dataclass
class Probe:
    """The outcome of up to two reachability attempts on one source."""

    stale: bool
    attempts: int
    detail: str  # the reason(s) is_reachable gave, one line


@dataclass
class Decision:
    """What the sweep concluded about one entry, before any write."""

    name: str
    action: str  # "skip" | "reachable" | "exists" | "propose"
    detail: str  # why it was skipped, or the probe's detail
    rel: str = ""  # entries/<name>.md, relative to --root
    attempts: int = 0  # reachability attempts made, when the source was probed
    owner: str | None = None
    source: str = ""


# --- pure pieces -------------------------------------------------------------


def probe(source: str, *, reachability: Reachability, sleep: Sleep, pause: float = RETRY_PAUSE) -> Probe:
    """Check ``source`` up to twice, ``pause`` seconds apart.

    The second attempt only happens when the first fails; a source that
    answers on either attempt is not stale.
    """
    ok, first = reachability(source)
    if ok:
        return Probe(stale=False, attempts=1, detail=first)
    sleep(pause)
    ok, second = reachability(source)
    if ok:
        return Probe(stale=False, attempts=2, detail=f"{second} (first attempt: {first})")
    if second == first:
        return Probe(stale=True, attempts=2, detail=f"unreachable twice: {first}")
    return Probe(stale=True, attempts=2, detail=f"unreachable twice: {first}; then {second}")


def find_open_pr(name: str, prs: list[dict]) -> dict | None:
    """The first open PR whose title names ``name`` as a word, or whose head is its sweep branch."""
    word = re.compile(rf"(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])", re.IGNORECASE)
    for pr in prs:
        if pr.get("headRefName") == BRANCH_PREFIX + name or word.search(str(pr.get("title", ""))):
            return pr
    return None


def deprecated_lines(today: dt.date, reason: str) -> list[str]:
    """The frontmatter lines that replace ``status: active``; each matches schema.md."""
    note = f"Source did not answer on the stale sweep of {today.isoformat()} ({jc.one_line(reason)})."
    # JSON's double-quoted string is a valid YAML scalar, so a reason holding
    # ": ", "#", or quotes cannot be misread when the entry is parsed back.
    return [
        f"status: {jc.STATUS_DEPRECATED}",
        "deprecated:",
        f"  route: {ROUTE}",
        f"  date: {today.isoformat()}",
        f"  note: {json.dumps(note, ensure_ascii=False)}",
    ]


def deprecate_text(text: str, *, today: dt.date, reason: str) -> str:
    """``text`` with its one ``status: active`` frontmatter line replaced by the deprecated block.

    Everything else (key order, quoting, the body) is left byte for byte, so
    the PR diff is exactly the deprecation. Raises ``SweepError`` when the
    frontmatter does not hold exactly one such line.
    """
    lines = text.splitlines()
    fences = [i for i, line in enumerate(lines) if line.strip() == "---"]
    if len(fences) < 2 or fences[0] != 0:
        raise SweepError("entry has no frontmatter block to rewrite")
    close = fences[1]
    hits = [i for i in range(1, close) if _STATUS_ACTIVE_RE.match(lines[i])]
    if len(hits) != 1:
        raise SweepError(f"expected exactly one 'status: active' line in the frontmatter, found {len(hits)}")
    out = lines[: hits[0]] + deprecated_lines(today, reason) + lines[hits[0] + 1 :]
    return "\n".join(out) + "\n"


def pr_title(name: str) -> str:
    return f"deprecate {name} (stale source)"


def pr_body(decision: Decision, today: dt.date) -> str:
    who = f"`{decision.owner}`, its owner" if decision.owner else "nobody in particular: the entry is unowned (`owner: ~`)"
    return (
        f"**Why:** the source of `{decision.name}`, <{decision.source}>, did not answer on two attempts "
        f"during the stale sweep of {today.isoformat()} ({decision.detail}). A tool whose source is gone "
        f"should not sit in the archive looking alive, so this proposes marking the entry deprecated "
        f"with route `{ROUTE}`. The entry stays in the archive and stays searchable; nothing is deleted.\n"
        "\n"
        f"Opened by the `stale-sweep` workflow. This concerns {who}. The `consensus-merge` workflow merges "
        "it when the owner approves, or when two non-owner voices support it; the account that opened this "
        "PR counts as one of those voices unless it is the owner. It is never merged or closed by the sweep "
        "itself.\n"
        "\n"
        "**To dismiss this proposal:** make the source answer again (bring the repository or page back, "
        "or update the entry's `source` on the default branch to where the tool now lives), then close this "
        "pull request. The next sweep will find the source reachable and leave the entry alone. Closing "
        "without fixing the source only postpones it: the next sweep opens the proposal again.\n"
    )


def decide(entry: jc.Entry, *, probe_source: Callable[[str], Probe], open_prs: list[dict]) -> Decision:
    """Classify one entry. ``probe_source`` is only called for active entries."""
    rel = f"{jc.ENTRIES_DIR}/{entry.path.name}"
    name = entry.path.stem
    fm = entry.frontmatter
    if fm is None:
        return Decision(name, "skip", entry.error or "frontmatter could not be parsed", rel)
    if not jc.is_kebab(name):
        return Decision(name, "skip", f"{name!r} is not a kebab-case entry name; the validator reports this", rel)

    status = fm.get("status")
    if status == jc.STATUS_DEPRECATED:
        block = fm.get("deprecated") if isinstance(fm.get("deprecated"), dict) else {}
        route, date = block.get("route", "?"), block.get("date", "?")
        return Decision(name, "skip", f"already deprecated (route {route}, {date})", rel)
    if status != jc.STATUS_ACTIVE:
        return Decision(name, "skip", f"status {status!r} is not active or deprecated; the validator reports this", rel)

    source = fm.get("source")
    if not jc.is_http_url(source):
        return Decision(name, "skip", f"source {source!r} is not an http(s) URL; the validator reports this", rel)

    result = probe_source(source)
    common = dict(rel=rel, attempts=result.attempts, owner=jc.entry_owner(fm), source=source)
    if not result.stale:
        return Decision(name, "reachable", result.detail, **common)

    existing = find_open_pr(name, open_prs)
    if existing is not None:
        url = existing.get("url") or f"#{existing.get('number')}"
        return Decision(name, "exists", f"open stale-source PR exists: {url}", **common)
    return Decision(name, "propose", result.detail, **common)


# --- gh and git I/O ----------------------------------------------------------


def list_stale_prs(repo: str) -> list[dict]:
    """Open PRs carrying the ``stale-source`` label, as ``gh pr list --json`` reports them."""
    result = jc.gh_ok(
        [
            "pr", "list", "--repo", repo, "--state", "open", "--label", "stale-source",
            "--limit", str(PR_LIST_LIMIT), "--json", "number,title,url,headRefName",
        ]
    )
    prs = json.loads(result.stdout or "[]")
    if not isinstance(prs, list):
        raise jc.GhError("gh pr list did not return a JSON list")
    return prs


def default_branch(repo: str) -> str:
    data = json.loads(jc.gh_ok(["api", f"repos/{repo}"]).stdout)
    branch = data.get("default_branch") if isinstance(data, dict) else None
    if not isinstance(branch, str) or not branch:
        raise jc.GhError(f"gh api repos/{repo} did not report a default_branch")
    return branch


def ensure_label(repo: str, name: str, description: str) -> None:
    """Create ``name`` unless it already exists; any other failure is a ``GhError``."""
    result = jc.gh(["label", "create", name, "--repo", repo, "--description", description])
    if result.returncode != 0 and "already exists" not in result.stderr:
        raise jc.GhError(f"gh label create {name} failed: {jc.failure_detail(result)}")


@dataclass
class Checkout:
    """Where the sweep started, so every proposal branches from it and returns to it."""

    root: Path
    base_sha: str
    original: str  # branch name, or the commit when HEAD was detached

    @classmethod
    def read(cls, root: Path) -> Checkout:
        base_sha = jc.git_output(root, ["rev-parse", "--verify", "HEAD"]).strip()
        symbolic = jc.run_git(root, ["symbolic-ref", "-q", "--short", "HEAD"])
        original = symbolic.stdout.strip() if symbolic.returncode == 0 and symbolic.stdout.strip() else base_sha
        return cls(root, base_sha, original)


def push_proposal(checkout: Checkout, decision: Decision, new_text: str) -> str:
    """Commit ``new_text`` for the entry on its sweep branch and push it; return the branch name.

    The working tree is on the branch only for as long as the one-file commit
    takes and is returned to ``checkout.original`` before the push, so a
    failure anywhere leaves the checkout where the sweep found it.
    """
    root = checkout.root
    branch = BRANCH_PREFIX + decision.name
    jc.git_output(root, ["checkout", "-q", "-B", branch, checkout.base_sha])
    committed = False
    try:
        (root / decision.rel).write_text(new_text, encoding="utf-8")
        jc.git_output(root, ["add", "--", decision.rel])
        jc.git_output(root, ["commit", "-q", "-m", pr_title(decision.name)])
        committed = True
    finally:
        if not committed:
            jc.run_git(root, ["checkout", "-q", "HEAD", "--", decision.rel])
        jc.git_output(root, ["checkout", "-q", checkout.original])
    jc.git_output(root, ["push", "-q", "--force", "origin", f"{branch}:refs/heads/{branch}"], timeout=120.0)
    return branch


def open_pr(repo: str, base: str, branch: str, decision: Decision, today: dt.date) -> str:
    result = jc.gh_ok(
        [
            "pr", "create", "--repo", repo, "--base", base, "--head", branch,
            "--title", pr_title(decision.name),
            "--label", "stale-source", "--label", "deprecation",
            "--body", pr_body(decision, today),
        ]
    )
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(gh printed no URL)"


# --- the run -----------------------------------------------------------------


def run(
    root: Path | str,
    repo: str,
    *,
    dry_run: bool = False,
    pause: float = RETRY_PAUSE,
    reachability: Reachability = jc.is_reachable,
    sleep: Sleep = time.sleep,
    today: dt.date | None = None,
) -> int:
    """Sweep the registry at ``root`` and open one PR per newly stale entry."""
    root = Path(root)
    today = today or dt.date.today()
    registry = jc.load_registry(root)
    for file, detail in registry.problems:
        print(f"{file}: notice; {detail}")

    try:
        open_prs = list_stale_prs(repo)
    except jc.GhError as exc:
        print(f"stale-sweep: cannot list open pull requests: {exc}", file=sys.stderr)
        return 1

    def probe_source(source: str) -> Probe:
        return probe(source, reachability=reachability, sleep=sleep, pause=pause)

    checked = stale = proposed = skipped = failed = 0
    checkout: Checkout | None = None
    base: str | None = None
    labels_ready = False

    for entry in registry.entries:
        decision = decide(entry, probe_source=probe_source, open_prs=open_prs)
        label = decision.rel if decision.action == "skip" and entry.frontmatter is None else decision.name

        if decision.action == "skip":
            skipped += 1
            print(f"{label}: skipped; {decision.detail}")
            continue
        checked += 1
        if decision.action == "reachable":
            if decision.attempts > 1:
                print(f"{decision.name}: reachable on the second attempt ({decision.detail})")
            else:
                print(f"{decision.name}: reachable")
            continue
        stale += 1
        if decision.action == "exists":
            skipped += 1
            print(f"{decision.name}: skipped; {decision.detail}")
            continue

        branch = BRANCH_PREFIX + decision.name
        if dry_run:
            proposed += 1
            print(f"{decision.name}: stale ({decision.detail}); dry run, would open PR {pr_title(decision.name)!r} from branch {branch}")
            continue

        try:
            new_text = deprecate_text((root / decision.rel).read_text(encoding="utf-8"), today=today, reason=decision.detail)
            if checkout is None:
                checkout = Checkout.read(root)
            if base is None:
                base = default_branch(repo)
            push_proposal(checkout, decision, new_text)
            if not labels_ready:
                for name, description in LABELS.items():
                    ensure_label(repo, name, description)
                labels_ready = True
            url = open_pr(repo, base, branch, decision, today)
        except (SweepError, jc.GitError, jc.GhError) as exc:
            failed += 1
            print(f"{decision.name}: stale ({decision.detail}); could not open a proposal: {exc}", file=sys.stderr)
            continue
        proposed += 1
        print(f"{decision.name}: stale ({decision.detail}); opened {url}")

    verb = "would be opened" if dry_run else "opened"
    tail = f", {failed} failed" if failed else ""
    print(f"sweep: {checked} active entries checked, {stale} stale, {proposed} PRs {verb}, {skipped} skipped{tail}")
    return 1 if failed else 0


# --- CLI ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stale_sweep.py",
        description="Open a deprecation pull request for every active entry whose source no longer answers.",
    )
    parser.add_argument("--root", required=True, type=Path, help="registry checkout (the instance's default branch)")
    parser.add_argument("--repo", required=True, type=jc.repo_arg, help="registry repository as OWNER/REPO")
    parser.add_argument("--dry-run", action="store_true", help="report stale entries without pushing branches or opening pull requests")
    parser.add_argument(
        "--pause",
        type=float,
        default=RETRY_PAUSE,
        metavar="SECONDS",
        help=f"wait between the two reachability attempts (default {RETRY_PAUSE:g})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"stale_sweep.py: --root {args.root} is not a directory", file=sys.stderr)
        return 2
    if args.pause < 0:
        parser.error("--pause must not be negative")
    return run(args.root, args.repo, dry_run=args.dry_run, pause=args.pause)


if __name__ == "__main__":
    sys.exit(main())
