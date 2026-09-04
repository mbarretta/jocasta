#!/usr/bin/env python3
"""Validate a jocasta registry instance.

Usage::

    validate.py --root DIR [--offline] [--changed-only REF --actor LOGIN]

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
                     whose values are lists of logins
- ``config``         jocasta.yaml is present and a YAML mapping
- ``schema-version`` jocasta.yaml's ``schema_version`` equals SCHEMA_VERSION

The schema this file enforces is documented, field by field, in
``skills/jocasta/references/schema.md``; the two must agree.

Only the standard library and PyYAML are used, so the script runs under a
plain ``python3`` with ``pip install pyyaml`` as well as under ``uv run``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

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
        for login in logins:
            if not _non_empty_str(login):
                out.append(_line(jc.ADOPTION_FILE, "adoption", f"{tool!r} has a login that is not a non-empty string: {login!r}"))
    return out


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
        help="only authorize files changed since REF (authorization rules land in a later release)",
    )
    parser.add_argument("--actor", metavar="LOGIN", help="GitHub login performing the push")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.root.is_dir():
        print(f"validate.py: --root {args.root} is not a directory", file=sys.stderr)
        return 2

    registry = jc.load_registry(args.root)
    failures = check_registry(registry, offline=args.offline)
    for line in failures:
        print(line)

    if args.changed_only is not None or args.actor is not None:
        print("authorization checks not yet implemented; --changed-only/--actor were parsed and ignored")

    if failures:
        return 1
    print(f"ok: {len(registry.entries)} entries validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
