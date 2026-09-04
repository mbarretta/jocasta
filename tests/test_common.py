"""Tests for scripts/jocasta_common.py: entry parsing, registry loading, reachability."""

import datetime as dt
import subprocess
import urllib.error
from pathlib import Path

import pytest

import jocasta_common as jc

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VALID = FIXTURES / "valid-registry"


# --- parse_entry ------------------------------------------------------------


def test_parse_entry_returns_frontmatter_and_body():
    fm, body = jc.parse_entry(VALID / "entries" / "example-cli.md")
    assert fm["name"] == "example-cli"
    assert fm["owner"] == "alice"
    assert fm["kind"] == "cli"
    assert fm["registered"] == dt.date(2026, 9, 1)
    assert body.startswith("Lists the files in a directory tree")
    assert "It is not a diff viewer" in body


def test_parse_entry_released_owner_is_none():
    fm, _ = jc.parse_entry(VALID / "entries" / "notes-skill.md")
    assert "owner" in fm
    assert fm["owner"] is None


def test_parse_entry_body_may_be_empty(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\nname: x\n---\n")
    fm, body = jc.parse_entry(p)
    assert fm == {"name": "x"}
    assert body == ""


def test_parse_entry_closing_fence_at_eof_without_newline(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\nname: x\n---")
    fm, body = jc.parse_entry(p)
    assert fm == {"name": "x"}
    assert body == ""


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("name: x\n", "start with"),
        ("---\nname: x\n", "closing"),
        ("---\nname: [unterminated\n---\nbody\n", "YAML"),
        ("---\n- a\n- b\n---\nbody\n", "mapping"),
        ("---\njust a scalar\n---\nbody\n", "mapping"),
        ("---\n---\nbody\n", "empty"),
    ],
)
def test_parse_entry_rejects_malformed_frontmatter(tmp_path, text, fragment):
    p = tmp_path / "bad.md"
    p.write_text(text)
    with pytest.raises(jc.EntryError) as exc:
        jc.parse_entry(p)
    assert fragment in str(exc.value)


# --- load_registry ----------------------------------------------------------


def test_load_registry_reads_config_adoption_and_entries():
    reg = jc.load_registry(VALID)
    assert reg.config == {"schema_version": 1, "team": "example-team", "machinery_ref": "v1"}
    assert reg.adoption == {"example-cli": ["alice", "bob"], "legacy-script": ["carol"]}
    names = sorted(e.frontmatter["name"] for e in reg.entries)
    assert names == ["example-cli", "legacy-script", "notes-skill"]
    assert reg.problems == []


def test_load_registry_ignores_entries_readme():
    reg = jc.load_registry(VALID)
    assert (VALID / "entries" / "README.md").is_file()
    assert all(e.path.name != "README.md" for e in reg.entries)


def test_load_registry_records_parse_errors_per_entry():
    reg = jc.load_registry(FIXTURES / "invalid" / "frontmatter-malformed")
    assert len(reg.entries) == 1
    entry = reg.entries[0]
    assert entry.frontmatter is None
    assert entry.error and "YAML" in entry.error


def test_load_registry_missing_files_are_reported_not_raised(tmp_path):
    reg = jc.load_registry(tmp_path)
    assert reg.entries == []
    assert reg.adoption == {}
    assert reg.config is None
    assert any(f == "jocasta.yaml" for f, _ in reg.problems)


def test_load_registry_empty_adoption_file_is_empty_mapping(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\n")
    (tmp_path / "adoption.yaml").write_text("")
    reg = jc.load_registry(tmp_path)
    assert reg.adoption == {}
    assert reg.problems == []


def test_load_registry_non_mapping_adoption_is_a_problem(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\n")
    (tmp_path / "adoption.yaml").write_text("- alice\n")
    reg = jc.load_registry(tmp_path)
    assert reg.adoption == {}
    assert any(f == "adoption.yaml" for f, _ in reg.problems)


# --- helpers -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["a", "a-b", "tool2", "my-tool-3"])
def test_is_kebab_accepts(name):
    assert jc.is_kebab(name)


@pytest.mark.parametrize("name", ["", "A", "a_b", "-a", "a-", "a--b", "a b", "a.b"])
def test_is_kebab_rejects(name):
    assert not jc.is_kebab(name)


@pytest.mark.parametrize("value", [dt.date(2026, 9, 4), "2026-09-04"])
def test_is_iso_date_accepts(value):
    assert jc.is_iso_date(value)


@pytest.mark.parametrize(
    "value",
    [None, "", "20260904", "2026-9-4", "September 4", "2026-13-01", dt.datetime(2026, 9, 4, 1), 20260904],
)
def test_is_iso_date_rejects(value):
    assert not jc.is_iso_date(value)


@pytest.mark.parametrize("value", ["https://example.com", "http://example.com/x?y=1", "https://github.com/o/r"])
def test_is_http_url_accepts(value):
    assert jc.is_http_url(value)


@pytest.mark.parametrize("value", [None, "", "  ", "not a url", "ftp://example.com/x", "https://", "example.com/x", 42])
def test_is_http_url_rejects(value):
    assert not jc.is_http_url(value)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/example-org/tool", ("example-org", "tool")),
        ("https://github.com/example-org/tool.git", ("example-org", "tool")),
        ("https://github.com/example-org/tool/tree/main/sub", ("example-org", "tool")),
        ("https://www.github.com/example-org/tool", ("example-org", "tool")),
        ("https://github.com/example-org", None),
        ("https://example.com/example-org/tool", None),
    ],
)
def test_github_repo_from_url(url, expected):
    assert jc.github_repo_from_url(url) == expected


# --- is_reachable -----------------------------------------------------------


def _completed(returncode, stderr=""):
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout="", stderr=stderr)


def test_is_reachable_github_uses_gh_api(monkeypatch):
    calls = []

    def fake_run_gh(args, timeout):
        calls.append(args)
        return _completed(0)

    monkeypatch.setattr(jc, "run_gh", fake_run_gh)
    ok, reason = jc.is_reachable("https://github.com/example-org/tool.git")
    assert ok is True
    assert calls == [["api", "repos/example-org/tool"]]
    assert "gh api" in reason


def test_is_reachable_github_failure_reports_gh_stderr(monkeypatch):
    monkeypatch.setattr(jc, "run_gh", lambda args, timeout: _completed(1, "gh: Not Found (HTTP 404)"))
    ok, reason = jc.is_reachable("https://github.com/example-org/tool")
    assert ok is False
    assert "Not Found" in reason


def test_is_reachable_github_without_gh_degrades_gracefully(monkeypatch):
    def missing(args, timeout):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(jc, "run_gh", missing)
    ok, reason = jc.is_reachable("https://github.com/example-org/tool")
    assert ok is False
    assert reason == "gh not found"


def test_is_reachable_github_timeout(monkeypatch):
    def slow(args, timeout):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=timeout)

    monkeypatch.setattr(jc, "run_gh", slow)
    ok, reason = jc.is_reachable("https://github.com/example-org/tool", timeout=3)
    assert ok is False
    assert "timed out" in reason and "3" in reason


def test_is_reachable_github_url_without_repo():
    ok, reason = jc.is_reachable("https://github.com/example-org")
    assert ok is False
    assert "repository" in reason


class _FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_is_reachable_http_head_success(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout):
        seen.append((req.get_method(), req.full_url, timeout))
        return _FakeResponse(200)

    monkeypatch.setattr(jc, "urlopen", fake_urlopen)
    ok, reason = jc.is_reachable("https://example.com/tools/thing")
    assert ok is True
    assert seen == [("HEAD", "https://example.com/tools/thing", 10.0)]
    assert "200" in reason


def test_is_reachable_http_falls_back_to_get_when_head_refused(monkeypatch):
    methods = []

    def fake_urlopen(req, timeout):
        methods.append(req.get_method())
        if req.get_method() == "HEAD":
            raise urllib.error.HTTPError(req.full_url, 405, "Method Not Allowed", {}, None)
        return _FakeResponse(200)

    monkeypatch.setattr(jc, "urlopen", fake_urlopen)
    ok, _ = jc.is_reachable("https://example.com/x")
    assert ok is True
    assert methods == ["HEAD", "GET"]


def test_is_reachable_http_error_status(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(jc, "urlopen", fake_urlopen)
    ok, reason = jc.is_reachable("https://example.com/x")
    assert ok is False
    assert "404" in reason


def test_is_reachable_http_connection_error(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("nodename nor servname provided")

    monkeypatch.setattr(jc, "urlopen", fake_urlopen)
    ok, reason = jc.is_reachable("https://nowhere.invalid/x")
    assert ok is False
    assert "nodename" in reason


def test_is_reachable_http_timeout(monkeypatch):
    def fake_urlopen(req, timeout):
        raise TimeoutError()

    monkeypatch.setattr(jc, "urlopen", fake_urlopen)
    ok, reason = jc.is_reachable("https://example.com/x", timeout=2)
    assert ok is False
    assert "timed out" in reason


@pytest.mark.parametrize("url", ["", "not a url", "ftp://example.com/x", "file:///etc/hosts", None])
def test_is_reachable_rejects_non_http_urls(url):
    ok, reason = jc.is_reachable(url)
    assert ok is False
    assert "http" in reason.lower()
