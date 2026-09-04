#!/usr/bin/env python3
"""Validate a jocasta registry instance.

Usage::

    validate.py --root DIR [--offline] [--changed-only REF --actor LOGIN [--event NAME]]

Exit status 0 when the registry is clean, 1 when any rule fails, 2 on a usage
error. Every failure is one plain line on stdout::

    entries/<file>.md: <rule>: <detail>
    adoption.yaml: adoption: <detail>
    jocasta.yaml: schema-version: <detail>

Rules, by name (the middle field of each line):

- ``frontmatter``    the file opens with a ``---`` YAML mapping fenced by ``---``
- ``unknown-key``    every frontmatter key is one documented in schema.md
- ``name``           equals the filename stem, is kebab-case, and is unique
- ``owner``          present and a GitHub login, or ``~`` for a released entry
- ``source``         an http(s) URL that answers (skipped with ``--offline``)
- ``kind``           one of ``cli``, ``script``, ``skill``
- ``install``        when present, a non-empty one-line string
- ``registered``     an ISO calendar date
- ``status``         one of ``active``, ``deprecated``
- ``deprecated``     block present iff status is deprecated, with a valid
                     ``route`` and ISO ``date``; ``note`` optional
- ``body``           at least one non-empty paragraph of prose
- ``adoption``       adoption.yaml is a mapping whose keys name entries and
                     whose values are lists of distinct logins
- ``config``         jocasta.yaml is present and a YAML mapping
- ``schema-version`` jocasta.yaml's ``schema_version`` equals SCHEMA_VERSION
- ``authorization``  with ``--changed-only REF --actor LOGIN``: every file the
                     push changed is one the actor may change directly (below)

The schema this file enforces is documented, field by field, in
``skills/jocasta/references/schema.md``; the two must agree.

Push authorization (``--changed-only REF --actor LOGIN [--event NAME]``)
-----------------------------------------------------------------------

The schema rules say whether the registry is well formed; the authorization
rule says whether *this push* was the actor's to make (charter D-3: your own
entries and your own adoption line commit directly, everything else is a PR).
It runs ``git diff --name-status REF...HEAD`` inside ``--root`` and reads both
sides of every change from git, so it needs a checkout with history
(``fetch-depth: 0``). Logins are compared case-insensitively, as GitHub does.

- ``entries/<name>.md`` added: its ``owner`` must be the actor.
- ``entries/<name>.md`` modified: its ``owner`` *at REF* must be the actor. A
  transfer or a release is therefore the previous owner's to make, and a claim
  of an unowned entry is not a direct push.
- ``entries/<name>.md`` deleted: always an error; entries are deprecated.
- ``adoption.yaml``: between REF and HEAD, under every tool key, the only login
  that may appear or disappear is the actor's own.
- Anything else (``entries/README.md``, ``jocasta.yaml``, workflows) is not
  the validator's concern; repository permissions govern those files.

A violation prints ``<file>: authorization: <detail>; open a PR instead``. When
REF is the all-zeros SHA GitHub sends for a first push, or is not a commit in
the checkout, every registry file is treated as added and the rules above
still apply.

The check is skipped, with a printed notice, when the actor is
``github-actions[bot]`` (a consensus merge, which the PR path already gated)
or when ``--event`` is ``pull_request`` (the workflow's checkout is GitHub's
synthetic merge commit of the PR, gated the same way). ``--event`` is
``github.event_name``, passed by the composite action. On every other event
(``push``), and when ``--event`` is not given at all, HEAD is checked whether
or not it is a merge commit, so a local ``git merge --no-ff`` of someone
else's entry, or a collaborator clicking Merge on their own PR, turns the run
red for the person who pushed it. Counting HEAD's parents is never a skip:
that is a shape test a local merge passes.

Only the standard library and PyYAML are used, so the script runs under a
plain ``python3`` with ``pip install pyyaml`` as well as under ``uv run``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

import jocasta_common as jc

SCHEMA_VERSION = 1

KNOWN_KEYS = ("name", "owner", "source", "kind", "install", "registered", "status", "deprecated")
REQUIRED_KEYS = ("name", "owner", "source", "kind", "registered", "status")
KINDS = ("cli", "script", "skill")
STATUSES = ("active", "deprecated")
ROUTES = ("owner", "consensus", "stale-source")
DEPRECATED_KEYS = ("route", "date", "note")
DEPRECATED_REQUIRED = ("route", "date")

# GitHub's login rules: alphanumerics and single hyphens, no leading or
# trailing hyphen, at most 39 characters.
_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")

# What GitHub sends as `github.event.before` when a push creates the branch.
FIRST_PUSH_SHA = "0" * 40
# The actor of a push made by the instance's own workflows (a consensus merge).
WORKFLOW_ACTOR = "github-actions[bot]"
# The GitHub event whose checkout is the synthetic merge commit of a pull request.
PULL_REQUEST_EVENT = "pull_request"
AUTHORIZATION_RULE = "authorization"
_OPEN_A_PR = "open a PR instead"

Reachability = Callable[..., tuple[bool, str]]


def validate_registry(
    root: Path | str,
    *,
    offline: bool = False,
    reachability: Reachability = jc.is_reachable,
) -> list[str]:
    """Return every failure line for the registry at ``root``; empty means clean."""
    return check_registry(jc.load_registry(root), offline=offline, reachability=reachability)


def check_registry(
    registry: jc.Registry,
    *,
    offline: bool = False,
    reachability: Reachability = jc.is_reachable,
) -> list[str]:
    """Return every failure line for an already-loaded registry; empty means clean."""
    failures: list[str] = []

    for file, detail in registry.problems:
        rule = "adoption" if file == jc.ADOPTION_FILE else "config"
        failures.append(_line(file, rule, detail))
    if registry.config is not None:
        failures.extend(_check_schema_version(registry.config))

    names_seen: dict[str, str] = {}
    valid_names: set[str] = set()
    for entry in registry.entries:
        rel = f"{jc.ENTRIES_DIR}/{entry.path.name}"
        if entry.frontmatter is None:
            failures.append(_line(rel, "frontmatter", entry.error or "could not be parsed"))
            continue
        failures.extend(_check_entry(rel, entry, names_seen, offline=offline, reachability=reachability))
        name = entry.frontmatter.get("name")
        if isinstance(name, str):
            valid_names.add(name)

    failures.extend(_check_adoption(registry.adoption, valid_names))
    return failures


def _line(file: str, rule: str, detail: str) -> str:
    return f"{file}: {rule}: {detail}"


# --- jocasta.yaml ------------------------------------------------------------


def _check_schema_version(config: dict) -> list[str]:
    found = config.get("schema_version")
    if found is None:
        return [_line(jc.CONFIG_FILE, "schema-version", f"schema_version is missing (this validator supports {SCHEMA_VERSION})")]
    if found != SCHEMA_VERSION:
        return [
            _line(
                jc.CONFIG_FILE,
                "schema-version",
                f"registry declares schema_version {found!r} but this validator supports {SCHEMA_VERSION}",
            )
        ]
    return []


# --- entries -----------------------------------------------------------------


def _check_entry(
    rel: str,
    entry: jc.Entry,
    names_seen: dict[str, str],
    *,
    offline: bool,
    reachability: Reachability,
) -> list[str]:
    fm = entry.frontmatter
    assert fm is not None
    out: list[str] = []

    for key in fm:
        if key not in KNOWN_KEYS:
            out.append(_line(rel, "unknown-key", f"{key!r} is not a schema field"))

    for key in REQUIRED_KEYS:
        if key not in fm:
            hint = " (use ~ for a released entry)" if key == "owner" else ""
            out.append(_line(rel, key, f"missing{hint}"))

    if "name" in fm:
        out.extend(_check_name(rel, entry.path.stem, fm["name"], names_seen))
    if "owner" in fm:
        out.extend(_check_owner(rel, fm["owner"]))
    if "source" in fm:
        out.extend(_check_source(rel, fm["source"], offline=offline, reachability=reachability))
    if "kind" in fm and fm["kind"] not in KINDS:
        out.append(_line(rel, "kind", f"{fm['kind']!r} is not one of {', '.join(KINDS)}"))
    if "install" in fm and not _non_empty_str(fm["install"]):
        out.append(_line(rel, "install", "must be a non-empty one-line string when present"))
    if "registered" in fm and not jc.is_iso_date(fm["registered"]):
        out.append(_line(rel, "registered", f"{fm['registered']!r} is not an ISO date (YYYY-MM-DD)"))

    status = fm.get("status")
    if "status" in fm and status not in STATUSES:
        out.append(_line(rel, "status", f"{status!r} is not one of {', '.join(STATUSES)}"))
    elif status in STATUSES:
        out.extend(_check_deprecated(rel, status, fm))

    if not entry.body:
        out.append(_line(rel, "body", "at least one non-empty paragraph of prose is required after the frontmatter"))
    return out


def _check_name(rel: str, stem: str, name: object, names_seen: dict[str, str]) -> list[str]:
    out: list[str] = []
    if not _non_empty_str(name):
        return [_line(rel, "name", "must be a non-empty string")]
    if name != stem:
        out.append(_line(rel, "name", f"{name!r} must equal the filename stem {stem!r}"))
    if not jc.is_kebab(name):
        out.append(_line(rel, "name", f"{name!r} is not kebab-case (lower-case words joined by single hyphens)"))
    if name in names_seen:
        out.append(_line(rel, "name", f"duplicate of {names_seen[name]}"))
    else:
        names_seen[name] = rel
    return out


def _check_owner(rel: str, owner: object) -> list[str]:
    if owner is None:  # YAML `~`: a released entry awaiting a claim
        return []
    if not isinstance(owner, str) or not _LOGIN_RE.match(owner):
        return [_line(rel, "owner", f"{owner!r} is not a GitHub login (use ~ for a released entry)")]
    return []


def _check_source(rel: str, source: object, *, offline: bool, reachability: Reachability) -> list[str]:
    if not jc.is_http_url(source):
        return [_line(rel, "source", f"{source!r} is not an http(s) URL")]
    if offline:
        return []
    ok, reason = reachability(source)
    if not ok:
        return [_line(rel, "source", f"unreachable ({reason}): {source}")]
    return []


def _check_deprecated(rel: str, status: str, fm: dict) -> list[str]:
    block = fm.get("deprecated")
    if status == "active":
        if "deprecated" in fm:
            return [_line(rel, "deprecated", "block is present but status is active")]
        return []

    if "deprecated" not in fm:
        return [_line(rel, "deprecated", "block is required when status is deprecated")]
    if not isinstance(block, dict):
        return [_line(rel, "deprecated", "must be a mapping with route and date")]

    out: list[str] = []
    for key in block:
        if key not in DEPRECATED_KEYS:
            out.append(_line(rel, "deprecated", f"unknown key {key!r} (allowed: {', '.join(DEPRECATED_KEYS)})"))
    for key in DEPRECATED_REQUIRED:
        if key not in block:
            out.append(_line(rel, "deprecated", f"{key} is missing"))
    if "route" in block and block["route"] not in ROUTES:
        out.append(_line(rel, "deprecated", f"route {block['route']!r} is not one of {', '.join(ROUTES)}"))
    if "date" in block and not jc.is_iso_date(block["date"]):
        out.append(_line(rel, "deprecated", f"date {block['date']!r} is not an ISO date (YYYY-MM-DD)"))
    if "note" in block and not _non_empty_str(block["note"]):
        out.append(_line(rel, "deprecated", "note must be a non-empty string when present"))
    return out


# --- adoption.yaml -----------------------------------------------------------


def _check_adoption(adoption: dict, valid_names: set[str]) -> list[str]:
    out: list[str] = []
    for tool, logins in adoption.items():
        if not isinstance(tool, str) or tool not in valid_names:
            out.append(_line(jc.ADOPTION_FILE, "adoption", f"{tool!r} does not appear in {jc.ENTRIES_DIR}/"))
        if not isinstance(logins, list):
            out.append(_line(jc.ADOPTION_FILE, "adoption", f"{tool!r} must map to a list of GitHub logins"))
            continue
        seen: set[str] = set()
        for login in logins:
            if not _non_empty_str(login):
                out.append(_line(jc.ADOPTION_FILE, "adoption", f"{tool!r} has a login that is not a non-empty string: {login!r}"))
            elif login.casefold() in seen:
                out.append(_line(jc.ADOPTION_FILE, "adoption", f"{tool!r} lists {login!r} more than once"))
            else:
                seen.add(login.casefold())
    return out


# --- push authorization (--changed-only) -------------------------------------


def check_authorization(
    root: Path | str, ref: str, actor: str, event: str | None = None
) -> tuple[list[str], list[str]]:
    """Return ``(failures, notices)`` for the push that took ``root`` from ``ref`` to HEAD.

    ``event`` is the GitHub event name behind the checkout. ``pull_request``
    is skipped (the checkout is GitHub's synthetic merge, gated by the PR
    path); any other event, and ``None`` (the caller did not say), is checked
    even when HEAD is a merge commit. The only other skip is the instance's
    own workflow actor.

    Failures use the same one-line format as the schema rules, under the rule
    name ``authorization``. Notices are informational lines for the log: what
    was skipped and why, or how many files were checked. Raises
    ``jc.GitError`` when git itself cannot answer (no repository, no HEAD).
    """
    root = Path(root)
    if _same_login(actor, WORKFLOW_ACTOR):
        return [], [f"{AUTHORIZATION_RULE}: skipped; {actor} is the instance's own workflow and the PR path already gated this push"]
    if event == PULL_REQUEST_EVENT:
        return [], [f"{AUTHORIZATION_RULE}: skipped; a {event} event checks out GitHub's synthetic merge commit and the PR path gates it"]

    notices: list[str] = []
    base, changes = _changed_registry_files(root, ref, notices)
    failures: list[str] = []
    for status, path in changes:
        if path == jc.ADOPTION_FILE:
            failures.extend(_authorize_adoption(root, base, status, actor))
        else:
            failures.extend(_authorize_entry(root, base, status, path, actor))
    notices.append(f"{AUTHORIZATION_RULE}: {len(changes)} changed registry file(s) checked for {actor}")
    return failures, notices


def _changed_registry_files(root: Path, ref: str, notices: list[str]) -> tuple[str | None, list[tuple[str, str]]]:
    """``(base, [(status, path), ...])`` for the registry files that changed since ``ref``.

    ``base`` is ``None`` when ``ref`` cannot serve as one (first push, unknown
    commit, no common history); every registry file at HEAD is then reported
    as added. Paths are relative to ``root``, which may be a subdirectory of
    the repository, and only ``entries/*.md`` (not the README) and
    ``adoption.yaml`` are returned.
    """
    if ref == FIRST_PUSH_SHA:
        reason = f"{ref} is the first-push marker"
    elif jc.run_git(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).returncode != 0:
        reason = f"{ref} is not a commit in this repository"
    else:
        diff = jc.run_git(root, ["diff", "--name-status", "--no-renames", "--relative", "-z", f"{ref}...HEAD"])
        if diff.returncode == 0:
            fields = diff.stdout.split("\0")
            pairs = [(fields[i], fields[i + 1]) for i in range(0, len(fields) - 1, 2)]
            return ref, [(status, path) for status, path in pairs if _is_registry_file(path)]
        reason = f"git diff {ref}...HEAD failed ({jc.one_line(diff.stderr) or 'no common history'})"

    notices.append(f"{AUTHORIZATION_RULE}: {reason}; treating every file as added")
    listing = jc.git_output(root, ["ls-tree", "-r", "--name-only", "-z", "HEAD"])
    return None, [("A", path) for path in listing.split("\0") if _is_registry_file(path)]


def _is_registry_file(path: str) -> bool:
    if path == jc.ADOPTION_FILE:
        return True
    parts = Path(path).parts
    return (
        len(parts) == 2
        and parts[0] == jc.ENTRIES_DIR
        and parts[1].endswith(".md")
        and parts[1].lower() != jc.ENTRIES_README.lower()
    )


def _authorize_entry(root: Path, base: str | None, status: str, path: str, actor: str) -> list[str]:
    def refuse(detail: str) -> list[str]:
        return [_line(path, AUTHORIZATION_RULE, f"{detail}; {_OPEN_A_PR}")]

    if status == "D":
        return refuse("entries are deprecated, not deleted (set status: deprecated)")
    if status == "A" or base is None:
        owner, error = _owner_at(root, "HEAD", path)
        if error:
            return refuse(f"owner could not be read: {error}")
        if owner is None:
            return refuse(f"new entry has no owner (~) but was pushed by {actor}")
        if not _same_login(owner, actor):
            return refuse(f"new entry names owner {owner!r} but was pushed by {actor}")
        return []
    if status == "M":
        owner, error = _owner_at(root, base, path)
        if error:
            return refuse(f"owner at REF could not be read: {error}")
        if owner is None:
            return refuse("unowned (~) at REF; only a claim PR may set its owner")
        if not _same_login(owner, actor):
            return refuse(f"owned by {owner} at REF, pushed by {actor}")
        return []
    return refuse(f"unsupported change type {status!r}")


def _owner_at(root: Path, rev: str, path: str) -> tuple[object, str | None]:
    """``(owner, None)`` from the entry's frontmatter at ``rev``, or ``(None, reason)``."""
    try:
        frontmatter, _ = jc.parse_entry_text(_show(root, rev, path))
    except (jc.GitError, jc.EntryError) as exc:
        return None, str(exc)
    if "owner" not in frontmatter:
        return None, "frontmatter has no owner field"
    return frontmatter["owner"], None


def _authorize_adoption(root: Path, base: str | None, status: str, actor: str) -> list[str]:
    """Only the actor's own login may be added to or removed from any tool's adopters."""
    out: list[str] = []
    before: dict[str, dict[str, str]] = {}
    if base is not None and status != "A":
        before = _adopters_at(root, base, "REF", out)
    after: dict[str, dict[str, str]] = {}
    if status != "D":
        after = _adopters_at(root, "HEAD", "HEAD", out)
    if out:
        return out

    me = actor.casefold()
    for tool in sorted(set(before) | set(after), key=str):
        old, new = before.get(tool, {}), after.get(tool, {})
        for key in sorted(set(new) - set(old)):
            if key != me:
                detail = f"{new[key]} added under {tool!r} by {actor}, who may only add their own login"
                out.append(_line(jc.ADOPTION_FILE, AUTHORIZATION_RULE, f"{detail}; {_OPEN_A_PR}"))
        for key in sorted(set(old) - set(new)):
            if key != me:
                detail = f"{old[key]} removed from {tool!r} by {actor}, who may only remove their own login"
                out.append(_line(jc.ADOPTION_FILE, AUTHORIZATION_RULE, f"{detail}; {_OPEN_A_PR}"))
    return out


def _adopters_at(root: Path, rev: str, label: str, out: list[str]) -> dict[str, dict[str, str]]:
    """``{tool: {casefolded login: login as written}}`` from adoption.yaml at ``rev``.

    Anything that is not a mapping of lists is reported into ``out`` and
    treated as unreadable: the check fails closed rather than guessing.
    """
    def refuse(detail: str) -> dict:
        out.append(_line(jc.ADOPTION_FILE, AUTHORIZATION_RULE, f"{detail}; {_OPEN_A_PR}"))
        return {}

    try:
        data = yaml.safe_load(_show(root, rev, jc.ADOPTION_FILE))
    except jc.GitError as exc:
        return refuse(f"could not be read at {label}: {exc}")
    except yaml.YAMLError as exc:
        return refuse(f"is not valid YAML at {label}: {jc.one_line(exc)}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        return refuse(f"is not a mapping at {label}, so adopters cannot be compared")
    adopters: dict[str, dict[str, str]] = {}
    for tool, logins in data.items():
        if not isinstance(logins, list):
            return refuse(f"{tool!r} is not a list of logins at {label}, so adopters cannot be compared")
        adopters[str(tool)] = {str(login).casefold(): str(login) for login in logins}
    return adopters


def _show(root: Path, rev: str, path: str) -> str:
    # `./` makes the path relative to the -C directory rather than the repository root.
    return jc.git_output(root, ["show", f"{rev}:./{path}"])


def _same_login(a: object, b: object) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.casefold() == b.casefold()


# --- helpers -----------------------------------------------------------------


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# --- CLI ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate.py",
        description="Validate a jocasta registry instance: entries/, adoption.yaml, jocasta.yaml.",
    )
    parser.add_argument("--root", required=True, type=Path, help="registry instance directory")
    parser.add_argument("--offline", action="store_true", help="skip source reachability checks")
    parser.add_argument(
        "--changed-only",
        metavar="REF",
        help="also check that every file changed between REF and HEAD was the actor's to change directly (needs --actor)",
    )
    parser.add_argument("--actor", metavar="LOGIN", help="GitHub login whose push is being checked (needs --changed-only)")
    parser.add_argument(
        "--event",
        metavar="NAME",
        help=(
            "GitHub event behind the checkout (github.event_name): pull_request skips the authorization check; "
            "any other event, or no --event at all, checks HEAD even when it is a merge commit (needs --changed-only)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.changed_only is None) != (args.actor is None):
        parser.error("--changed-only and --actor must be given together")
    if args.actor is not None and not args.actor.strip():
        parser.error("--actor must be a GitHub login")
    if args.event is not None and args.changed_only is None:
        parser.error("--event needs --changed-only")
    if args.event is not None and not args.event.strip():
        parser.error("--event must be a GitHub event name")
    if not args.root.is_dir():
        print(f"validate.py: --root {args.root} is not a directory", file=sys.stderr)
        return 2

    registry = jc.load_registry(args.root)
    failures = check_registry(registry, offline=args.offline)

    notices: list[str] = []
    if args.changed_only is not None:
        try:
            auth_failures, notices = check_authorization(args.root, args.changed_only, args.actor, event=args.event)
        except jc.GitError as exc:
            print(f"validate.py: --changed-only: {exc}", file=sys.stderr)
            return 2
        failures.extend(auth_failures)

    for line in notices:
        print(line)
    for line in failures:
        print(line)
    if failures:
        return 1
    print(f"ok: {len(registry.entries)} entries validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
