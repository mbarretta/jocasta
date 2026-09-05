"""Tests for scripts/stale_sweep.py.

Reachability and every ``gh`` call are faked (no network). Git is real: each
test gets a registry instance cloned against a local bare ``origin`` so the
branch the sweep pushes, and the commit on it, can be inspected exactly as the
``consensus-merge`` workflow would see them.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import jocasta_common as jc
import stale_sweep as ss

REPO_ROOT = Path(__file__).resolve().parent.parent
VALID_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "valid-registry"
VALIDATE = REPO_ROOT / "scripts" / "validate.py"
SWEEP = REPO_ROOT / "scripts" / "stale_sweep.py"

REPO = "example-org/registry"
TODAY = dt.date(2026, 9, 4)
DOWN = (False, "gh api repos/example-org/dead-tool failed: HTTP 404: Not Found")
UP = (True, "gh api repos/example-org/live-tool succeeded")

# Hermetic git: the developer's global config (signing, hooks) must never reach
# the commits the sweep makes, and the identity must not depend on the machine.
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "github-actions[bot]",
    "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "github-actions[bot]",
    "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
}

BODY = "Does one small thing well. Use it when you need that thing done.\n"


def entry_text(name: str, owner: str | None = "alice", *, status: str = "active", source: str | None = None) -> str:
    lines = [
        f"name: {name}",
        "owner: ~" if owner is None else f"owner: {owner}",
        f"source: {source or f'https://github.com/example-org/{name}'}",
        "kind: cli",
        "registered: 2026-09-01",
        f"status: {status}",
    ]
    if status == "deprecated":
        lines += ["deprecated:", "  route: owner", "  date: 2026-08-15"]
    return "---\n" + "\n".join(lines) + "\n---\n" + BODY


# --- fixtures ----------------------------------------------------------------


class Instance:
    """A registry checkout on ``main`` with a bare ``origin`` next to it."""

    def __init__(self, tmp_path: Path):
        self.origin = tmp_path / "origin.git"
        self.root = tmp_path / "instance"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True, env=self._env())
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", str(self.origin))
        (self.root / jc.CONFIG_FILE).write_text("schema_version: 1\nteam: example-team\nmachinery_ref: v1\n")
        (self.root / jc.ADOPTION_FILE).write_text("{}\n")
        (self.root / jc.ENTRIES_DIR).mkdir()
        (self.root / jc.ENTRIES_DIR / "README.md").write_text("Entries live here.\n")

    @staticmethod
    def _env() -> dict[str, str]:
        return {**os.environ, **GIT_ENV}

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, env=self._env(), check=True
        )
        return result.stdout.strip()

    def write_entry(self, name: str, text: str) -> Path:
        path = self.root / jc.ENTRIES_DIR / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        return path

    def commit_and_push(self, message: str = "seed") -> str:
        self.git("add", "--", jc.CONFIG_FILE, jc.ADOPTION_FILE, jc.ENTRIES_DIR)
        self.git("commit", "-q", "-m", message)
        self.git("push", "-q", "-u", "origin", "main")
        return self.git("rev-parse", "HEAD")

    def remote_branches(self) -> list[str]:
        out = subprocess.run(
            ["git", "-C", str(self.origin), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
            capture_output=True,
            text=True,
            check=True,
            env=self._env(),
        ).stdout
        return sorted(out.split())

    def remote_show(self, ref: str, path: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.origin), "show", f"{ref}:{path}"],
            capture_output=True,
            text=True,
            check=True,
            env=self._env(),
        ).stdout

    def remote_parent(self, ref: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.origin), "rev-parse", f"{ref}^"],
            capture_output=True,
            text=True,
            check=True,
            env=self._env(),
        ).stdout.strip()


@pytest.fixture
def instance(tmp_path, monkeypatch) -> Instance:
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    return Instance(tmp_path)


class FakeReachability:
    """Scripted reachability: ``results[url]`` is consumed one call at a time."""

    def __init__(self, results: dict[str, list[tuple[bool, str]]]):
        self.results = {url: list(seq) for url, seq in results.items()}
        self.calls: list[str] = []

    def __call__(self, url: str) -> tuple[bool, str]:
        self.calls.append(url)
        seq = self.results[url]
        return seq.pop(0) if len(seq) > 1 else seq[0]


class FakeGh:
    """Routes ``gh`` calls by subcommand and records every call made."""

    def __init__(self, open_prs: list[dict] | None = None, *, existing_labels: tuple[str, ...] = (), pr_create_rc: int = 0):
        self.open_prs = list(open_prs or [])
        self.existing_labels = set(existing_labels)
        self.pr_create_rc = pr_create_rc
        self.calls: list[list[str]] = []
        self.created: list[dict[str, str]] = []

    def __call__(self, args: list[str], timeout: float) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            assert _flag(args, "--repo") == REPO and _flag(args, "--label") == "stale-source" and _flag(args, "--state") == "open", args
            return _completed(0, json.dumps(self.open_prs))
        if args[:2] == ["api", f"repos/{REPO}"]:
            return _completed(0, json.dumps({"default_branch": "main"}))
        if args[:2] == ["label", "create"]:
            if args[2] in self.existing_labels:
                return _completed(1, stderr=f"label with name \"{args[2]}\" already exists")
            self.existing_labels.add(args[2])
            return _completed(0)
        if args[:2] == ["pr", "create"]:
            if self.pr_create_rc:
                return _completed(self.pr_create_rc, stderr="GraphQL: something went wrong")
            pr = {
                "repo": _flag(args, "--repo"),
                "base": _flag(args, "--base"),
                "head": _flag(args, "--head"),
                "title": _flag(args, "--title"),
                "body": _flag(args, "--body"),
                "labels": [args[i + 1] for i, a in enumerate(args) if a == "--label"],
            }
            self.created.append(pr)
            return _completed(0, f"https://github.com/{REPO}/pull/{len(self.created)}\n")
        raise AssertionError(f"unexpected gh call: {args}")

    @property
    def writes(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] in (["pr", "create"], ["label", "create"])]


def _flag(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


def _completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=rc, stdout=stdout, stderr=stderr)


@pytest.fixture
def use_gh(monkeypatch):
    def install(fake: FakeGh) -> FakeGh:
        monkeypatch.setattr(jc, "run_gh", fake)
        return fake

    return install


def open_pr(title: str, head: str = "jocasta/stale-other-tool", number: int = 41) -> dict:
    return {"number": number, "title": title, "url": f"https://github.com/{REPO}/pull/{number}", "headRefName": head}


def sweep(instance: Instance, probe: FakeReachability, *, dry_run: bool = False) -> tuple[int, list[float]]:
    sleeps: list[float] = []
    rc = ss.run(instance.root, REPO, dry_run=dry_run, reachability=probe, sleep=sleeps.append, today=TODAY)
    return rc, sleeps


def source(name: str) -> str:
    return f"https://github.com/example-org/{name}"


# --- the sweep ---------------------------------------------------------------


def test_reachable_entry_is_left_alone(instance, use_gh, capsys):
    instance.write_entry("live-tool", entry_text("live-tool"))
    instance.commit_and_push()
    gh = use_gh(FakeGh())
    probe = FakeReachability({source("live-tool"): [UP]})

    rc, sleeps = sweep(instance, probe)

    assert rc == 0
    assert probe.calls == [source("live-tool")]
    assert sleeps == []
    assert gh.writes == []
    assert instance.remote_branches() == ["main"]
    assert instance.git("status", "--porcelain") == ""
    assert "live-tool: reachable" in capsys.readouterr().out


def test_unreachable_twice_opens_exactly_one_pr(instance, use_gh, capsys):
    instance.write_entry("dead-tool", entry_text("dead-tool"))
    instance.write_entry("live-tool", entry_text("live-tool", owner="bob"))
    base = instance.commit_and_push()
    original = (instance.root / "entries" / "dead-tool.md").read_text()
    gh = use_gh(FakeGh())
    probe = FakeReachability({source("dead-tool"): [DOWN], source("live-tool"): [UP]})

    rc, sleeps = sweep(instance, probe)

    assert rc == 0
    assert probe.calls.count(source("dead-tool")) == 2
    assert sleeps == [ss.RETRY_PAUSE]

    # One PR, labeled both ways, from the documented branch onto the default branch.
    assert len(gh.created) == 1
    pr = gh.created[0]
    assert pr["repo"] == REPO
    assert pr["head"] == "jocasta/stale-dead-tool"
    assert pr["base"] == "main"
    assert sorted(pr["labels"]) == ["deprecation", "stale-source"]
    assert "dead-tool" in pr["title"]
    body = pr["body"]
    assert DOWN[1] in body
    assert "close" in body.lower() and "source" in body.lower(), "body must say how to dismiss: fix the source and close"
    assert "alice" in body

    # Both labels were created before the PR that uses them.
    label_calls = [c for c in gh.calls if c[:2] == ["label", "create"]]
    assert sorted(c[2] for c in label_calls) == ["deprecation", "stale-source"]
    assert gh.calls.index(label_calls[-1]) < gh.calls.index(next(c for c in gh.calls if c[:2] == ["pr", "create"]))

    # The branch is on the remote, one commit on top of main, holding the deprecated block.
    assert instance.remote_branches() == ["jocasta/stale-dead-tool", "main"]
    assert instance.remote_parent("jocasta/stale-dead-tool") == base
    fm, prose = jc.parse_entry_text(instance.remote_show("jocasta/stale-dead-tool", "entries/dead-tool.md"))
    assert fm["status"] == "deprecated"
    assert fm["deprecated"]["route"] == "stale-source"
    assert fm["deprecated"]["date"] == TODAY
    assert DOWN[1] in fm["deprecated"]["note"]
    assert fm["owner"] == "alice" and fm["name"] == "dead-tool"
    assert prose == BODY.strip()
    # The untouched entry is not on the branch's commit.
    assert instance.remote_show("jocasta/stale-dead-tool", "entries/live-tool.md") == entry_text("live-tool", owner="bob")

    # The checkout is back where it started, clean, with the original file.
    assert instance.git("rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert instance.git("rev-parse", "HEAD") == base
    assert instance.git("status", "--porcelain") == ""
    assert (instance.root / "entries" / "dead-tool.md").read_text() == original

    out = capsys.readouterr().out
    assert f"dead-tool: stale (unreachable twice: {DOWN[1]}); opened https://github.com/{REPO}/pull/1" in out
    assert "live-tool: reachable" in out


def test_unreachable_once_then_reachable_is_not_flagged(instance, use_gh, capsys):
    instance.write_entry("flaky-tool", entry_text("flaky-tool"))
    instance.commit_and_push()
    gh = use_gh(FakeGh())
    probe = FakeReachability({source("flaky-tool"): [DOWN, UP]})

    rc, sleeps = sweep(instance, probe)

    assert rc == 0
    assert probe.calls == [source("flaky-tool"), source("flaky-tool")]
    assert sleeps == [ss.RETRY_PAUSE]
    assert gh.writes == []
    assert instance.remote_branches() == ["main"]
    assert "flaky-tool: reachable on the second attempt" in capsys.readouterr().out


def test_existing_open_stale_source_pr_is_not_duplicated(instance, use_gh, capsys):
    instance.write_entry("dead-tool", entry_text("dead-tool"))
    instance.commit_and_push()
    existing = open_pr("deprecate dead-tool (stale source)", head="jocasta/stale-dead-tool")
    gh = use_gh(FakeGh([existing]))
    probe = FakeReachability({source("dead-tool"): [DOWN]})

    rc, _ = sweep(instance, probe)

    assert rc == 0
    assert gh.writes == []
    assert instance.remote_branches() == ["main"]
    out = capsys.readouterr().out
    assert "dead-tool: skipped; open stale-source PR exists" in out
    assert existing["url"] in out


def test_open_pr_for_a_different_entry_does_not_count(instance, use_gh):
    instance.write_entry("dead-tool", entry_text("dead-tool"))
    instance.commit_and_push()
    # "dead-tool-two" contains "dead-tool" as a substring but names another entry.
    gh = use_gh(FakeGh([open_pr("deprecate dead-tool-two (stale source)", head="jocasta/stale-dead-tool-two")]))

    rc, _ = sweep(instance, FakeReachability({source("dead-tool"): [DOWN]}))

    assert rc == 0
    assert len(gh.created) == 1
    assert gh.created[0]["head"] == "jocasta/stale-dead-tool"


def test_deprecated_entries_are_skipped_without_probing(instance, use_gh, capsys):
    instance.write_entry("old-tool", entry_text("old-tool", status="deprecated"))
    instance.write_entry("live-tool", entry_text("live-tool"))
    instance.commit_and_push()
    gh = use_gh(FakeGh())
    probe = FakeReachability({source("live-tool"): [UP]})

    rc, _ = sweep(instance, probe)

    assert rc == 0
    assert probe.calls == [source("live-tool")]
    assert gh.writes == []
    assert "old-tool: skipped; already deprecated (route owner, 2026-08-15)" in capsys.readouterr().out


def test_dry_run_reports_and_touches_nothing(instance, use_gh, capsys):
    instance.write_entry("dead-tool", entry_text("dead-tool"))
    instance.write_entry("flagged-tool", entry_text("flagged-tool"))
    base = instance.commit_and_push()
    before = (instance.root / "entries" / "dead-tool.md").read_text()
    existing = open_pr("deprecate flagged-tool (stale source)", head="jocasta/stale-flagged-tool")
    gh = use_gh(FakeGh([existing]))
    probe = FakeReachability({source("dead-tool"): [DOWN], source("flagged-tool"): [DOWN]})

    rc, _ = sweep(instance, probe, dry_run=True)

    assert rc == 0
    assert gh.writes == [], "dry run must not create labels or PRs"
    assert all(c[:2] != ["api", f"repos/{REPO}"] for c in gh.calls)
    assert instance.remote_branches() == ["main"]
    assert instance.git("rev-parse", "HEAD") == base
    assert instance.git("status", "--porcelain") == ""
    assert instance.git("branch", "--list", "jocasta/*") == ""
    assert (instance.root / "entries" / "dead-tool.md").read_text() == before
    out = capsys.readouterr().out
    assert "dead-tool: stale" in out and "would open" in out and "jocasta/stale-dead-tool" in out
    assert "flagged-tool: skipped; open stale-source PR exists" in out


def test_each_stale_entry_gets_its_own_branch_from_the_same_base(instance, use_gh):
    instance.write_entry("dead-a", entry_text("dead-a"))
    instance.write_entry("dead-b", entry_text("dead-b", owner=None))
    base = instance.commit_and_push()
    gh = use_gh(FakeGh())

    rc, _ = sweep(instance, FakeReachability({source("dead-a"): [DOWN], source("dead-b"): [DOWN]}))

    assert rc == 0
    assert [pr["head"] for pr in gh.created] == ["jocasta/stale-dead-a", "jocasta/stale-dead-b"]
    assert instance.remote_branches() == ["jocasta/stale-dead-a", "jocasta/stale-dead-b", "main"]
    for branch in ("jocasta/stale-dead-a", "jocasta/stale-dead-b"):
        assert instance.remote_parent(branch) == base
    # A branch carries only its own entry's change.
    assert instance.remote_show("jocasta/stale-dead-a", "entries/dead-b.md") == entry_text("dead-b", owner=None)
    assert "unowned" in gh.created[1]["body"]
    # Labels are created once, not once per PR.
    assert len([c for c in gh.calls if c[:2] == ["label", "create"]]) == 2


def test_existing_labels_are_fine(instance, use_gh):
    instance.write_entry("dead-tool", entry_text("dead-tool"))
    instance.commit_and_push()
    gh = use_gh(FakeGh(existing_labels=("stale-source", "deprecation")))

    rc, _ = sweep(instance, FakeReachability({source("dead-tool"): [DOWN]}))

    assert rc == 0
    assert len(gh.created) == 1


def test_unreadable_entry_is_skipped_with_a_notice(instance, use_gh, capsys):
    instance.write_entry("broken", "no frontmatter here\n")
    instance.write_entry("live-tool", entry_text("live-tool"))
    instance.commit_and_push()
    gh = use_gh(FakeGh())

    rc, _ = sweep(instance, FakeReachability({source("live-tool"): [UP]}))

    assert rc == 0
    assert gh.writes == []
    assert "entries/broken.md: skipped; " in capsys.readouterr().out


def test_pr_create_failure_is_reported_and_leaves_the_checkout_clean(instance, use_gh, capsys):
    instance.write_entry("dead-tool", entry_text("dead-tool"))
    base = instance.commit_and_push()
    use_gh(FakeGh(pr_create_rc=1))

    rc, _ = sweep(instance, FakeReachability({source("dead-tool"): [DOWN]}))

    assert rc == 1
    err = capsys.readouterr().err
    assert "dead-tool" in err and "gh pr create failed" in err
    # The branch was pushed before the PR failed; the checkout is back on main.
    assert instance.remote_branches() == ["jocasta/stale-dead-tool", "main"]
    assert instance.git("rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert instance.git("rev-parse", "HEAD") == base
    assert instance.git("status", "--porcelain") == ""


def test_reflagging_after_a_closed_pr_replaces_the_old_branch(instance, use_gh):
    # A previous sweep pushed jocasta/stale-dead-tool from an older main; the
    # PR was closed without fixing the source, main moved on, and the source is
    # still down: the new proposal must land on top of today's main.
    instance.write_entry("dead-tool", entry_text("dead-tool"))
    instance.commit_and_push()
    instance.git("branch", "jocasta/stale-dead-tool")
    instance.git("push", "-q", "origin", "jocasta/stale-dead-tool")
    instance.git("branch", "-D", "jocasta/stale-dead-tool")
    instance.write_entry("live-tool", entry_text("live-tool"))
    base = instance.commit_and_push("register live-tool")
    gh = use_gh(FakeGh())

    rc, _ = sweep(instance, FakeReachability({source("dead-tool"): [DOWN], source("live-tool"): [UP]}))

    assert rc == 0
    assert len(gh.created) == 1
    assert instance.remote_parent("jocasta/stale-dead-tool") == base


# --- the block it writes validates -------------------------------------------


def test_proposed_entry_validates_offline(instance, use_gh):
    # Seed the instance with the valid fixture registry, flag example-cli, then
    # run validate.py --offline over the branch exactly as the instance's
    # validate workflow would on the PR.
    for path in VALID_FIXTURE.iterdir():
        target = instance.root / path.name
        if path.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(path, target)
        else:
            shutil.copy(path, target)
    instance.commit_and_push()
    use_gh(FakeGh())
    live = {jc.parse_entry(p)[0]["source"]: [UP] for p in (instance.root / "entries").glob("*.md") if p.name != "README.md"}
    live[source("example-cli")] = [DOWN]

    rc, _ = sweep(instance, FakeReachability(live))

    assert rc == 0
    instance.git("checkout", "-q", "jocasta/stale-example-cli")
    result = subprocess.run(
        [sys.executable, str(VALIDATE), "--root", str(instance.root), "--offline"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok: 3 entries validated" in result.stdout


def test_deprecate_text_rewrites_only_the_status_line():
    text = (VALID_FIXTURE / "entries" / "example-cli.md").read_text()
    reason = "gh api repos/example-org/example-cli failed: HTTP 404: Not Found"

    new = ss.deprecate_text(text, today=TODAY, reason=reason)

    fm, body = jc.parse_entry_text(new)
    old_fm, old_body = jc.parse_entry_text(text)
    assert body == old_body
    assert fm["status"] == "deprecated"
    assert fm["deprecated"]["route"] == "stale-source"
    assert fm["deprecated"]["date"] == TODAY
    assert reason in fm["deprecated"]["note"]
    assert {k: v for k, v in fm.items() if k not in ("status", "deprecated")} == {k: v for k, v in old_fm.items() if k != "status"}
    # Every original line other than the status line is still there, verbatim.
    assert [line for line in text.splitlines() if line != "status: active"] == [
        line for line in new.splitlines() if line not in ss.deprecated_lines(TODAY, reason) and line != "status: deprecated"
    ]
    assert new.endswith(body + "\n")


def test_deprecate_text_quotes_a_note_that_yaml_would_misread():
    text = entry_text("dead-tool")
    reason = 'connection failed: [Errno 8] nodename nor servname: "x" #not a comment'
    fm, _ = jc.parse_entry_text(ss.deprecate_text(text, today=TODAY, reason=reason))
    assert reason in fm["deprecated"]["note"]


def test_deprecate_text_refuses_when_no_single_active_status_line():
    with pytest.raises(ss.SweepError):
        ss.deprecate_text(entry_text("old-tool", status="deprecated"), today=TODAY, reason="x")
    two_in_frontmatter = entry_text("dead-tool").replace("kind: cli", "kind: cli\nstatus: active")
    with pytest.raises(ss.SweepError):
        ss.deprecate_text(two_in_frontmatter, today=TODAY, reason="x")
    # A "status: active" line in the body is prose, not frontmatter, and is left alone.
    fm, body = jc.parse_entry_text(ss.deprecate_text(entry_text("dead-tool") + "status: active\n", today=TODAY, reason="x"))
    assert fm["status"] == "deprecated" and body.endswith("status: active")


# --- pure pieces -------------------------------------------------------------


def test_route_is_one_the_schema_and_the_consensus_gate_accept():
    """The sweep's PRs carry the third R-5 route; it must be a route validate.py and consensus_merge.py both know."""
    assert ss.ROUTE == "stale-source"
    assert ss.ROUTE in jc.ROUTES


def test_probe_retries_only_after_a_failure():
    probe = FakeReachability({"https://example.com/a": [UP], "https://example.com/b": [DOWN, DOWN], "https://example.com/c": [DOWN, UP]})
    sleeps: list[float] = []

    assert ss.probe("https://example.com/a", reachability=probe, sleep=sleeps.append) == ss.Probe(False, 1, UP[1])
    assert sleeps == []
    result = ss.probe("https://example.com/b", reachability=probe, sleep=sleeps.append)
    assert result.stale and result.attempts == 2 and DOWN[1] in result.detail
    assert sleeps == [ss.RETRY_PAUSE]
    result = ss.probe("https://example.com/c", reachability=probe, sleep=sleeps.append)
    assert not result.stale and result.attempts == 2 and DOWN[1] in result.detail
    assert probe.calls == ["https://example.com/a"] + ["https://example.com/b"] * 2 + ["https://example.com/c"] * 2


@pytest.mark.parametrize(
    "title, head, expected",
    [
        ("deprecate dead-tool (stale source)", "jocasta/stale-dead-tool", True),
        ("Deprecate dead-tool: source is gone", "someone/else", True),
        ("deprecate dead-tool-two (stale source)", "jocasta/stale-dead-tool-two", False),
        ("deprecate my-dead-tool", "x", False),
        ("retire something", "jocasta/stale-dead-tool", True),
        ("unrelated", "unrelated", False),
    ],
)
def test_find_open_pr_matches_by_title_word_or_branch(title, head, expected):
    prs = [open_pr(title, head=head)]
    assert (ss.find_open_pr("dead-tool", prs) is not None) is expected


# --- CLI ---------------------------------------------------------------------


def run_cli(*args, env=None):
    return subprocess.run([sys.executable, str(SWEEP), *args], capture_output=True, text=True, cwd=REPO_ROOT, env=env)


def test_cli_rejects_a_bad_repo_and_a_missing_root(tmp_path):
    result = run_cli("--root", str(tmp_path), "--repo", "not-a-repo")
    assert result.returncode == 2
    assert "OWNER/REPO" in result.stderr
    result = run_cli("--root", str(tmp_path / "missing"), "--repo", REPO)
    assert result.returncode == 2
    assert "not a directory" in result.stderr


def test_cli_dry_run_end_to_end(instance):
    # No network: the only entry's source is a port on the loopback interface
    # that nothing listens on, so the real is_reachable gets an immediate
    # connection refusal, and dry-run makes no gh write. Listing PRs still
    # needs gh, so route it to a stub that reports none.
    instance.write_entry("dead-tool", entry_text("dead-tool", source="http://127.0.0.1:9/dead-tool"))
    instance.commit_and_push()
    stub = instance.root.parent / "bin"
    stub.mkdir()
    (stub / "gh").write_text("#!/bin/sh\necho '[]'\n")
    (stub / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}"}

    result = run_cli("--root", str(instance.root), "--repo", REPO, "--dry-run", "--pause", "0", env=env)

    assert result.returncode == 0, result.stderr
    assert "dead-tool: stale" in result.stdout and "would open" in result.stdout
    assert instance.remote_branches() == ["main"]
