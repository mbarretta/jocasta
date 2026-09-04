"""Shared helpers for the jocasta deterministic layer.

Everything here depends on the Python 3.11+ standard library plus PyYAML, so
it runs the same under ``uv run`` locally and under ``pip install pyyaml`` in
a GitHub Actions job. The three public building blocks:

- ``parse_entry(path)``: split an ``entries/<name>.md`` file into its YAML
  frontmatter and prose body, raising ``EntryError`` on anything malformed.
- ``load_registry(root)``: read an instance directory (``jocasta.yaml``,
  ``adoption.yaml``, ``entries/*.md``) into a ``Registry`` without raising, so
  a validator can report every problem instead of stopping at the first.
- ``is_reachable(url)``: decide whether a tool's ``source`` URL answers,
  using ``gh api`` for github.com (works for private repos the caller can
  see) and an HTTP request for anything else.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import urlopen

import yaml

CONFIG_FILE = "jocasta.yaml"
ADOPTION_FILE = "adoption.yaml"
ENTRIES_DIR = "entries"
ENTRIES_README = "README.md"

_FENCE = "---"
_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GITHUB_HOSTS = {"github.com", "www.github.com"}


class EntryError(ValueError):
    """An entry file whose frontmatter cannot be read as a YAML mapping."""


@dataclass
class Entry:
    """One ``entries/*.md`` file, parsed if possible.

    ``frontmatter`` is ``None`` and ``error`` is set when the file could not be
    parsed; callers report ``error`` under the ``frontmatter`` rule.
    """

    path: Path
    frontmatter: dict | None
    body: str
    error: str | None = None


@dataclass
class Registry:
    """An instance directory as loaded from disk.

    ``config`` is ``None`` when ``jocasta.yaml`` is missing or unreadable;
    ``problems`` holds ``(relative file, detail)`` pairs for anything at the
    registry level that could not be loaded, so nothing is silently dropped.
    """

    root: Path
    config: dict | None
    adoption: dict
    entries: list[Entry]
    problems: list[tuple[str, str]] = field(default_factory=list)


# --- entries -----------------------------------------------------------------


def parse_entry(path: Path | str) -> tuple[dict, str]:
    """Return ``(frontmatter, body)`` for an entry file.

    The file must begin with a ``---`` line, contain a YAML mapping, and close
    that mapping with another ``---`` line. The first ``---`` line after the
    opener is the closing fence, so no frontmatter line may consist of ``---``
    on its own (a block scalar containing one would be cut short). The body is
    everything after the closing fence with surrounding whitespace stripped;
    it may be empty here (the validator decides whether that is acceptable).
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise EntryError("file must start with a '---' frontmatter block")

    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            close = i
            break
    if close is None:
        raise EntryError("frontmatter has no closing '---' line")

    raw = "\n".join(lines[1:close])
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise EntryError(f"frontmatter is not valid YAML: {_one_line(exc)}") from exc

    if data is None:
        raise EntryError("frontmatter is empty")
    if not isinstance(data, dict):
        raise EntryError(f"frontmatter must be a YAML mapping, not {type(data).__name__}")

    body = "\n".join(lines[close + 1 :]).strip()
    return data, body


def _one_line(exc: BaseException) -> str:
    return " ".join(str(exc).split())


# --- registry ----------------------------------------------------------------


def load_registry(root: Path | str) -> Registry:
    """Load ``root`` as a registry instance. Never raises for bad content."""
    root = Path(root)
    problems: list[tuple[str, str]] = []

    config = _load_yaml_mapping(root / CONFIG_FILE, problems, required=True)

    adoption = _load_yaml_mapping(root / ADOPTION_FILE, problems, required=False)
    if adoption is None:
        adoption = {}

    entries: list[Entry] = []
    entries_dir = root / ENTRIES_DIR
    if entries_dir.is_dir():
        for path in sorted(entries_dir.glob("*.md")):
            if path.name.lower() == ENTRIES_README.lower():
                continue
            try:
                fm, body = parse_entry(path)
                entries.append(Entry(path=path, frontmatter=fm, body=body))
            except EntryError as exc:
                entries.append(Entry(path=path, frontmatter=None, body="", error=str(exc)))

    return Registry(root=root, config=config, adoption=adoption, entries=entries, problems=problems)


def _load_yaml_mapping(path: Path, problems: list[tuple[str, str]], *, required: bool) -> dict | None:
    """Read a top-level YAML mapping; an empty file is an empty mapping."""
    if not path.is_file():
        if required:
            problems.append((path.name, f"{path.name} is missing"))
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        problems.append((path.name, f"not valid YAML: {_one_line(exc)}"))
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        problems.append((path.name, f"expected a YAML mapping at the top level, not {type(data).__name__}"))
        return None
    return data


# --- small predicates --------------------------------------------------------


def is_kebab(name: object) -> bool:
    """Lower-case words of ``[a-z0-9]`` joined by single hyphens."""
    return isinstance(name, str) and bool(_KEBAB_RE.match(name))


def is_iso_date(value: object) -> bool:
    """A calendar date, either as PyYAML's parsed ``date`` or as ``YYYY-MM-DD``.

    A ``datetime`` is rejected on purpose: the schema wants a day, not an
    instant, and a timestamp in the file is a sign the field was not written
    by hand or by the skill.
    """
    if isinstance(value, dt.datetime):
        return False
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_http_url(value: object) -> bool:
    """A non-empty string that parses as an http(s) URL with a host."""
    if not isinstance(value, str) or not value.strip():
        return False
    parts = urllib.parse.urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def github_repo_from_url(url: object) -> tuple[str, str] | None:
    """``(owner, repo)`` for a github.com URL, else ``None``."""
    if not isinstance(url, str):
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.hostname not in _GITHUB_HOSTS:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        return None
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not owner or not repo:
        return None
    return owner, repo


# --- reachability ------------------------------------------------------------


def run_gh(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run ``gh`` with ``args``. Thin so tests can monkeypatch it.

    Raises ``FileNotFoundError`` when ``gh`` is not installed and
    ``subprocess.TimeoutExpired`` when it hangs; callers turn both into
    reasons rather than crashes.
    """
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def is_reachable(url: object, timeout: float = 10.0) -> tuple[bool, str]:
    """Return ``(reachable, reason)`` for a tool's source URL.

    github.com URLs go through ``gh api repos/{owner}/{repo}`` so private
    repositories the caller can see count as reachable. Every other http(s)
    URL gets a HEAD request, falling back to GET when the server refuses HEAD.
    Anything that is not an http(s) URL is unreachable by definition.
    """
    if not is_http_url(url):
        return False, "source must be an http(s) URL"

    if urllib.parse.urlsplit(url).hostname in _GITHUB_HOSTS:
        repo = github_repo_from_url(url)
        if repo is None:
            return False, "github.com URL does not name a repository (expected github.com/<owner>/<repo>)"
        return _github_reachable(*repo, timeout=timeout)
    return _http_reachable(url, timeout=timeout)


def _github_reachable(owner: str, repo: str, *, timeout: float) -> tuple[bool, str]:
    endpoint = f"repos/{owner}/{repo}"
    try:
        result = run_gh(["api", endpoint], timeout=timeout)
    except FileNotFoundError:
        return False, "gh not found"
    except subprocess.TimeoutExpired:
        return False, f"gh api {endpoint} timed out after {timeout:g}s"
    if result.returncode == 0:
        return True, f"gh api {endpoint} succeeded"
    detail = _one_line(result.stderr) or f"exit status {result.returncode}"
    return False, f"gh api {endpoint} failed: {detail}"


def _http_reachable(url: str, *, timeout: float) -> tuple[bool, str]:
    status, reason = _http_status(url, "HEAD", timeout)
    if status is None and reason in ("HTTP 405", "HTTP 403", "HTTP 501"):
        status, reason = _http_status(url, "GET", timeout)
    if status is not None:
        return True, f"HTTP {status}"
    return False, reason


def _http_status(url: str, method: str, timeout: float) -> tuple[int | None, str]:
    request = urllib.request.Request(url, method=method, headers={"User-Agent": "jocasta-validate"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return None, f"timed out after {timeout:g}s"
        return None, f"connection failed: {_one_line(reason)}"
    except TimeoutError:
        return None, f"timed out after {timeout:g}s"
    except (OSError, ValueError) as exc:
        return None, f"request failed: {_one_line(exc)}"
