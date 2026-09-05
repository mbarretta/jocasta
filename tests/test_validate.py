"""Tests for scripts/validate.py against the fixture registries."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import jocasta_common as jc
import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
VALID = FIXTURES / "valid-registry"
INVALID = FIXTURES / "invalid"
SCRIPT = REPO_ROOT / "scripts" / "validate.py"

LINE_RE = re.compile(r"^(entries/[^:]+\.md|adoption\.yaml|jocasta\.yaml): ([a-z-]+): .+$")


def run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )


# --- valid registry ----------------------------------------------------------


def test_valid_registry_passes_offline():
    assert validate.validate_registry(VALID, offline=True) == []


def test_valid_registry_passes_via_cli_under_plain_python():
    result = run_cli("--root", str(VALID), "--offline")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "authorization" not in result.stdout


def test_valid_registry_has_a_deprecated_and_a_released_entry():
    """Guards the fixture itself: R-5 says deprecated entries stay valid, and a
    released (owner ~) entry is legal."""
    import jocasta_common as jc

    reg = jc.load_registry(VALID)
    statuses = {e.frontmatter["name"]: e.frontmatter["status"] for e in reg.entries}
    assert statuses["legacy-script"] == "deprecated"
    assert any(e.frontmatter["owner"] is None for e in reg.entries)
    assert len(reg.entries) >= 2


def test_valid_registry_with_reachability_stub_passes():
    calls = []

    def reachable(url, timeout=10.0):
        calls.append(url)
        return True, "stubbed"

    assert validate.validate_registry(VALID, offline=False, reachability=reachable) == []
    assert len(calls) == 3


def test_empty_registry_passes(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\nteam: t\nmachinery_ref: v1\n")
    (tmp_path / "adoption.yaml").write_text("{}\n")
    (tmp_path / "entries").mkdir()
    (tmp_path / "entries" / "README.md").write_text("# Entries\n")
    assert validate.validate_registry(tmp_path, offline=True) == []


# --- invalid registries: one per rule ----------------------------------------

# (fixture dir, rule name every failure line must carry, fragment that must appear in some line)
INVALID_CASES = [
    ("frontmatter-malformed", "frontmatter", "YAML"),
    ("unknown-key", "unknown-key", "homepage"),
    ("name-mismatch", "name", "filename"),
    ("name-not-kebab", "name", "kebab"),
    ("name-duplicate", "name", "duplicate"),
    ("owner-missing", "owner", "missing"),
    ("source-invalid", "source", "http"),
    ("kind-invalid", "kind", "webapp"),
    ("status-invalid", "status", "retired"),
    ("deprecated-missing", "deprecated", "required"),
    ("deprecated-on-active", "deprecated", "active"),
    ("deprecated-route-invalid", "deprecated", "route"),
    ("deprecated-date-invalid", "deprecated", "date"),
    ("registered-invalid", "registered", "ISO"),
    ("body-empty", "body", "paragraph"),
    ("adoption-unknown-tool", "adoption", "phantom-tool"),
    ("adoption-not-list", "adoption", "list"),
    ("adoption-empty-login", "adoption", "non-empty"),
    ("schema-version-mismatch", "schema-version", "2"),
    ("config-missing", "config", "jocasta.yaml"),
]


@pytest.mark.parametrize("fixture, rule, fragment", INVALID_CASES, ids=[c[0] for c in INVALID_CASES])
def test_invalid_fixture_fails_naming_the_rule(fixture, rule, fragment):
    failures = validate.validate_registry(INVALID / fixture, offline=True)
    assert failures, f"{fixture} should fail"
    for line in failures:
        assert LINE_RE.match(line), f"bad failure format: {line!r}"
        assert f": {rule}: " in line, f"{fixture} produced a failure outside rule {rule!r}: {line!r}"
    assert any(fragment in line for line in failures), failures


def test_every_invalid_fixture_dir_is_covered():
    on_disk = sorted(p.name for p in INVALID.iterdir() if p.is_dir())
    covered = sorted(c[0] for c in INVALID_CASES) + ["source-unreachable"]
    assert on_disk == sorted(covered)


def test_source_unreachable_fails_unless_offline():
    root = INVALID / "source-unreachable"

    def unreachable(url, timeout=10.0):
        return False, "HTTP 404"

    failures = validate.validate_registry(root, offline=False, reachability=unreachable)
    assert failures == ["entries/gone-tool.md: source: unreachable (HTTP 404): https://github.com/example-org/gone-tool"]
    assert validate.validate_registry(root, offline=True) == []


def test_schema_version_mismatch_names_both_versions():
    failures = validate.validate_registry(INVALID / "schema-version-mismatch", offline=True)
    assert len(failures) == 1
    line = failures[0]
    assert line.startswith("jocasta.yaml: schema-version: ")
    assert "2" in line and str(validate.SCHEMA_VERSION) in line


def test_name_duplicate_reports_the_other_file():
    failures = validate.validate_registry(INVALID / "name-duplicate", offline=True)
    assert any("entries/b-tool.md: name: duplicate" in line and "a-tool.md" in line for line in failures)


def test_invalid_fixture_via_cli_exits_1_with_plain_lines():
    result = run_cli("--root", str(INVALID / "unknown-key"), "--offline")
    assert result.returncode == 1
    lines = result.stdout.strip().splitlines()
    assert lines == ["entries/extra-tool.md: unknown-key: 'homepage' is not a schema field"]


def test_non_mapping_adoption_yaml_fails_under_adoption_rule(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\n")
    (tmp_path / "adoption.yaml").write_text("- alice\n")
    failures = validate.validate_registry(tmp_path, offline=True)
    assert len(failures) == 1
    assert failures[0].startswith("adoption.yaml: adoption: ")


def test_adoption_duplicate_login_fails_under_adoption_rule(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\n")
    (tmp_path / "entries").mkdir()
    (tmp_path / "entries" / "real-tool.md").write_text(entry_text("real-tool", "alice"))
    (tmp_path / "adoption.yaml").write_text("real-tool: [alice, bob, Alice]\n")
    failures = validate.validate_registry(tmp_path, offline=True)
    assert failures == ["adoption.yaml: adoption: 'real-tool' lists 'Alice' more than once"]


def test_adoption_yaml_is_optional(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\n")
    assert validate.validate_registry(tmp_path, offline=True) == []


# --- --changed-only / --actor: push authorization ----------------------------

# Every temporary repository below is hermetic: the developer's global and
# system git config (commit signing, hooks, default branch) must not reach it,
# and the author identity comes from the environment, not from any config file.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}
ZEROS = "0" * 40
AUTH_LINE_RE = re.compile(r"^(entries/[^:]+\.md|adoption\.yaml): authorization: .+; open a PR instead$")
BODY = "Does one small thing well. Use it when you need that thing done."


def entry_text(name, owner, *, status="active", body=BODY):
    lines = [
        f"name: {name}",
        "owner: ~" if owner is None else f"owner: {owner}",
        f"source: https://github.com/example-org/{name}",
        "kind: cli",
        "registered: 2026-09-01",
        f"status: {status}",
    ]
    if status == "deprecated":
        lines += ["deprecated:", "  route: owner", "  date: 2026-09-02"]
    return "---\n" + "\n".join(lines) + "\n---\n" + body + "\n"


class TempRegistry:
    """A registry instance inside a throwaway git repository."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.base = None

    def git(self, *args) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, env=GIT_ENV, check=True
        )
        return result.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def remove(self, rel: str) -> None:
        (self.root / rel).unlink()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def authorize(self, ref, actor, event=None):
        return validate.check_authorization(self.root, ref, actor, event=event)


@pytest.fixture
def registry(tmp_path):
    reg = TempRegistry(tmp_path / "registry")
    reg.write("jocasta.yaml", "schema_version: 1\nteam: example-team\nmachinery_ref: v1\n")
    reg.write("adoption.yaml", "alice-tool: [alice, bob]\nbob-tool: [carol]\n")
    reg.write("entries/README.md", "# Entries\n")
    reg.write("entries/alice-tool.md", entry_text("alice-tool", "alice"))
    reg.write("entries/bob-tool.md", entry_text("bob-tool", "bob"))
    reg.write("entries/free-tool.md", entry_text("free-tool", None))
    reg.base = reg.commit("seed")
    return reg


def assert_authorization_lines(failures, *files):
    assert [f.split(":")[0] for f in failures] == list(files), failures
    for line in failures:
        assert LINE_RE.match(line), line
        assert AUTH_LINE_RE.match(line), line


# ac1: entries/*.md


def test_added_entry_owned_by_actor_passes(registry):
    registry.write("entries/new-tool.md", entry_text("new-tool", "alice"))
    registry.commit("register new-tool")
    failures, notices = registry.authorize(registry.base, "alice")
    assert failures == []
    assert any("1 changed" in n and "alice" in n for n in notices), notices


def test_added_entry_owned_by_someone_else_fails(registry):
    registry.write("entries/new-tool.md", entry_text("new-tool", "bob"))
    registry.commit("register new-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/new-tool.md")
    assert "bob" in failures[0] and "alice" in failures[0]


def test_added_entry_without_owner_fails(registry):
    registry.write("entries/new-tool.md", entry_text("new-tool", None))
    registry.commit("register new-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/new-tool.md")
    assert "~" in failures[0]


def test_owner_login_comparison_ignores_case(registry):
    registry.write("entries/new-tool.md", entry_text("new-tool", "Alice"))
    registry.commit("register new-tool")
    assert registry.authorize(registry.base, "alice")[0] == []


def test_login_comparison_goes_through_the_shared_helper():
    """validate.py compares logins with jocasta_common.same_login, not a private copy."""
    assert not hasattr(validate, "_same_login")
    assert "jc.same_login(" in Path(validate.__file__).read_text(encoding="utf-8")


def test_modified_own_entry_passes(registry):
    registry.write("entries/alice-tool.md", entry_text("alice-tool", "alice", body="A longer description.\n\nMore."))
    registry.commit("edit alice-tool")
    assert registry.authorize(registry.base, "alice")[0] == []


def test_modified_someone_elses_entry_fails_naming_the_owner_at_ref(registry):
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "bob", body="Alice rewrote this."))
    registry.commit("edit bob-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/bob-tool.md")
    assert "bob" in failures[0]


def test_owner_may_transfer_and_release(registry):
    registry.write("entries/alice-tool.md", entry_text("alice-tool", "carol"))
    registry.write("entries/bob-tool.md", entry_text("bob-tool", None))
    registry.commit("transfer alice-tool; release bob-tool")
    assert registry.authorize(registry.base, "alice")[0] == ["entries/bob-tool.md: authorization: owned by bob at REF, pushed by alice; open a PR instead"]
    assert registry.authorize(registry.base, "bob")[0] == ["entries/alice-tool.md: authorization: owned by alice at REF, pushed by bob; open a PR instead"]


def test_owner_may_deprecate_own_entry(registry):
    registry.write("entries/alice-tool.md", entry_text("alice-tool", "alice", status="deprecated"))
    registry.commit("deprecate alice-tool")
    assert registry.authorize(registry.base, "alice")[0] == []


def test_non_owner_cannot_take_ownership_by_direct_push(registry):
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "alice"))
    registry.commit("steal bob-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/bob-tool.md")


def test_unowned_entry_is_claimed_by_pr_not_by_push(registry):
    registry.write("entries/free-tool.md", entry_text("free-tool", "dave"))
    registry.commit("claim free-tool")
    failures, _ = registry.authorize(registry.base, "dave")
    assert_authorization_lines(failures, "entries/free-tool.md")
    assert "unowned" in failures[0] and "claim" in failures[0]


def test_deleted_entry_is_an_error(registry):
    registry.remove("entries/alice-tool.md")
    registry.commit("delete alice-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/alice-tool.md")
    assert "entries are deprecated, not deleted" in failures[0]


def test_renamed_entry_is_a_deletion_plus_an_addition(registry):
    registry.remove("entries/alice-tool.md")
    registry.write("entries/alice-tool-2.md", entry_text("alice-tool-2", "alice"))
    registry.commit("rename alice-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/alice-tool.md")
    assert "not deleted" in failures[0]


def test_unreadable_frontmatter_fails_closed(registry):
    registry.write("entries/new-tool.md", "name: new-tool\nowner: alice\n")
    registry.commit("broken new-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/new-tool.md")
    assert "could not be read" in failures[0]


def test_readme_config_and_workflow_changes_are_not_authorization_matters(registry):
    registry.write("entries/README.md", "# Entries\n\nRewritten.\n")
    registry.write("jocasta.yaml", "schema_version: 1\nteam: renamed-team\nmachinery_ref: v1\n")
    registry.write(".github/workflows/validate.yml", "name: validate\n")
    registry.commit("housekeeping")
    failures, notices = registry.authorize(registry.base, "nobody")
    assert failures == []
    assert any("0 changed" in n for n in notices), notices


def test_several_violations_are_all_reported_in_path_order(registry):
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "bob", body="edited by alice"))
    registry.write("entries/zed-tool.md", entry_text("zed-tool", "zed"))
    registry.remove("entries/free-tool.md")
    registry.commit("several")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/bob-tool.md", "entries/free-tool.md", "entries/zed-tool.md")


def test_root_may_be_a_subdirectory_of_the_repository(tmp_path):
    outer = TempRegistry(tmp_path / "outer")
    outer.write("registry/jocasta.yaml", "schema_version: 1\n")
    outer.write("registry/entries/alice-tool.md", entry_text("alice-tool", "alice"))
    outer.write("unrelated/entries/x.md", "not an entry\n")
    base = outer.commit("seed")
    outer.write("registry/entries/bob-tool.md", entry_text("bob-tool", "bob"))
    outer.write("unrelated/entries/x.md", "still not an entry\n")
    outer.commit("changes")
    failures, _ = validate.check_authorization(outer.root / "registry", base, "alice")
    assert_authorization_lines(failures, "entries/bob-tool.md")


# ac2: adoption.yaml


def test_adding_and_removing_your_own_login_passes(registry):
    registry.write("adoption.yaml", "alice-tool: [bob]\nbob-tool: [alice, carol]\nfree-tool: [alice]\n")
    registry.commit("adoption")
    assert registry.authorize(registry.base, "alice")[0] == []


def test_removing_a_key_that_held_only_your_login_passes(registry):
    registry.write("adoption.yaml", "alice-tool: [alice, bob]\n")
    registry.commit("unadopt bob-tool")
    assert registry.authorize(registry.base, "carol")[0] == []


def test_adding_someone_elses_login_fails(registry):
    registry.write("adoption.yaml", "alice-tool: [alice, bob, carol]\nbob-tool: [carol]\n")
    registry.commit("adopt for carol")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "adoption.yaml")
    assert "carol" in failures[0] and "alice-tool" in failures[0]


def test_removing_someone_elses_login_fails(registry):
    registry.write("adoption.yaml", "alice-tool: [alice]\nbob-tool: [carol]\n")
    registry.commit("drop bob")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "adoption.yaml")
    assert "bob" in failures[0]


def test_adoption_login_comparison_ignores_case(registry):
    registry.write("adoption.yaml", "alice-tool: [alice, bob]\nbob-tool: [carol, Dave]\n")
    registry.commit("adopt")
    assert registry.authorize(registry.base, "dave")[0] == []


def test_reordering_logins_changes_nothing(registry):
    registry.write("adoption.yaml", "bob-tool: [carol]\nalice-tool: [bob, alice]\n")
    registry.commit("reorder")
    assert registry.authorize(registry.base, "nobody")[0] == []


def test_new_adoption_file_may_hold_only_your_login(tmp_path):
    reg = TempRegistry(tmp_path / "registry")
    reg.write("jocasta.yaml", "schema_version: 1\n")
    reg.write("entries/alice-tool.md", entry_text("alice-tool", "alice"))
    base = reg.commit("seed")
    reg.write("adoption.yaml", "alice-tool: [alice, bob]\n")
    reg.commit("adoption")
    failures, _ = reg.authorize(base, "alice")
    assert_authorization_lines(failures, "adoption.yaml")
    assert "bob" in failures[0]
    reg.write("adoption.yaml", "alice-tool: [alice]\n")
    reg.commit("adoption fixed")
    assert reg.authorize(base, "alice")[0] == []


def test_deleting_adoption_file_removes_everyones_logins(registry):
    registry.remove("adoption.yaml")
    registry.commit("delete adoption")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "adoption.yaml", "adoption.yaml")
    assert any("bob" in f for f in failures) and any("carol" in f for f in failures)


def test_unreadable_adoption_yaml_fails_closed(registry):
    registry.write("adoption.yaml", "- alice\n")
    registry.commit("bad adoption")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "adoption.yaml")


# ac3: first push, unknown ref, workflow actor, merge commits; sec1: --event


def merge_foreign_edit_on_main(registry):
    """A ``--no-ff`` merge onto main whose side branch takes bob's entry as alice.

    Returns the tip of main before the merge, which is what GitHub sends as
    ``github.event.before`` for the push of the merge commit.
    """
    registry.git("checkout", "-q", "-b", "jocasta/claim-bob-tool-alice")
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "alice"))
    registry.commit("claim bob-tool")
    registry.git("checkout", "-q", "main")
    registry.write("entries/alice-tool.md", entry_text("alice-tool", "alice", body="edited on main"))
    before = registry.commit("edit alice-tool")
    registry.git("merge", "-q", "--no-ff", "-m", "Merge claim", "jocasta/claim-bob-tool-alice")
    return before


@pytest.mark.parametrize("ref", [ZEROS, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "no-such-branch"])
def test_unknown_ref_treats_every_file_as_added(registry, ref):
    failures, notices = registry.authorize(ref, "alice")
    # bob and carol are foreign logins in a now-"new" adoption.yaml; bob-tool is
    # bob's and free-tool is unowned, so neither may be pushed by alice.
    assert_authorization_lines(failures, "adoption.yaml", "adoption.yaml", "entries/bob-tool.md", "entries/free-tool.md")
    assert any("every file as added" in n for n in notices), notices


def test_first_push_of_a_fresh_instance_passes(tmp_path):
    reg = TempRegistry(tmp_path / "registry")
    reg.write("jocasta.yaml", "schema_version: 1\nteam: t\nmachinery_ref: v1\n")
    reg.write("adoption.yaml", "{}\n")
    reg.write("entries/README.md", "# Entries\n")
    reg.commit("Initialize jocasta registry")
    failures, notices = reg.authorize(ZEROS, "alice")
    assert failures == []
    assert any("every file as added" in n for n in notices), notices


def test_workflow_actor_is_skipped_with_a_notice(registry):
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "alice"))
    registry.commit("merged by the workflow")
    failures, notices = registry.authorize(registry.base, "github-actions[bot]")
    assert failures == []
    assert len(notices) == 1 and "skipped" in notices[0] and "github-actions[bot]" in notices[0]


def test_merge_commit_without_event_is_checked(registry):
    # sec1: counting HEAD's parents is not a skip. A caller that does not say
    # which event it is on is checked like a push; only --event pull_request
    # and the workflow actor are skipped.
    before = merge_foreign_edit_on_main(registry)
    failures, notices = registry.authorize(before, "alice")
    assert_authorization_lines(failures, "entries/bob-tool.md")
    assert notices == ["authorization: 1 changed registry file(s) checked for alice"]


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_merge_commit_on_any_event_but_pull_request_is_checked(registry, event):
    # sec1: a local `git merge --no-ff`, or clicking Merge on one's own PR, is a
    # push whose HEAD has two parents. It is checked like any other push.
    before = merge_foreign_edit_on_main(registry)
    failures, notices = registry.authorize(before, "alice", event=event)
    assert_authorization_lines(failures, "entries/bob-tool.md")
    assert notices == ["authorization: 1 changed registry file(s) checked for alice"]


def test_pull_request_event_is_skipped_with_a_notice(registry):
    before = merge_foreign_edit_on_main(registry)
    failures, notices = registry.authorize(before, "alice", event="pull_request")
    assert failures == []
    assert len(notices) == 1 and "skipped" in notices[0] and "pull_request" in notices[0]


def test_pull_request_event_is_skipped_whatever_the_checkout_looks_like(registry):
    # The skip is decided by the event, not by counting HEAD's parents.
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "alice"))
    registry.commit("take bob-tool")
    failures, notices = registry.authorize(registry.base, "alice", event="pull_request")
    assert failures == []
    assert len(notices) == 1 and "skipped" in notices[0] and "pull_request" in notices[0]


def test_workflow_actor_is_skipped_on_a_push_event(registry):
    # A consensus merge is a push of a merge commit by the instance's own workflow.
    before = merge_foreign_edit_on_main(registry)
    failures, notices = registry.authorize(before, "github-actions[bot]", event="push")
    assert failures == []
    assert len(notices) == 1 and "skipped" in notices[0] and "github-actions[bot]" in notices[0]


def test_ordinary_commit_after_a_merge_is_still_checked(registry):
    registry.git("checkout", "-q", "-b", "side")
    registry.write("entries/side-tool.md", entry_text("side-tool", "alice"))
    registry.commit("side")
    registry.git("checkout", "-q", "main")
    registry.git("merge", "-q", "--no-ff", "-m", "Merge side", "side")
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "alice"))
    registry.commit("take bob-tool")
    failures, _ = registry.authorize(registry.base, "alice")
    assert_authorization_lines(failures, "entries/bob-tool.md")


# CLI


def test_cli_authorization_failure_exits_1_and_prints_the_line(registry):
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "alice"))
    registry.commit("take bob-tool")
    result = run_cli("--root", str(registry.root), "--offline", "--changed-only", registry.base, "--actor", "alice")
    assert result.returncode == 1, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    # Notices first (what was checked), then the failure lines, and no ok line.
    assert lines[0].startswith("authorization: 1 changed")
    assert lines[1].startswith("entries/bob-tool.md: authorization: ")
    assert not lines[-1].startswith("ok:")
    assert "not yet implemented" not in result.stdout


def test_cli_clean_push_exits_0_with_notice_and_ok_line(registry):
    registry.write("entries/new-tool.md", entry_text("new-tool", "alice"))
    registry.commit("register new-tool")
    result = run_cli("--root", str(registry.root), "--offline", "--changed-only", registry.base, "--actor", "alice")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("authorization: ") and lines[-1] == "ok: 4 entries validated"


def test_cli_schema_and_authorization_failures_are_both_reported(registry):
    registry.write("entries/bob-tool.md", entry_text("bob-tool", "bob").replace("kind: cli", "kind: webapp"))
    registry.commit("break bob-tool")
    result = run_cli("--root", str(registry.root), "--offline", "--changed-only", registry.base, "--actor", "alice")
    assert result.returncode == 1
    assert "entries/bob-tool.md: kind: " in result.stdout
    assert "entries/bob-tool.md: authorization: " in result.stdout


def test_cli_push_event_merge_commit_exits_1_and_prints_the_line(registry):
    before = merge_foreign_edit_on_main(registry)
    result = run_cli(
        "--root", str(registry.root), "--offline", "--changed-only", before, "--actor", "alice", "--event", "push"
    )
    assert result.returncode == 1, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("authorization: 1 changed")
    assert lines[1].startswith("entries/bob-tool.md: authorization: ")
    assert not lines[-1].startswith("ok:")


def test_cli_without_event_checks_the_merge_commit(registry):
    # --event stays optional, but leaving it out never widens the skip: a
    # two-parent HEAD is checked exactly as it is on a push event.
    before = merge_foreign_edit_on_main(registry)
    result = run_cli("--root", str(registry.root), "--offline", "--changed-only", before, "--actor", "alice")
    assert result.returncode == 1, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("authorization: 1 changed")
    assert lines[1].startswith("entries/bob-tool.md: authorization: ")
    assert not lines[-1].startswith("ok:")


def test_cli_event_needs_changed_only():
    result = run_cli("--root", str(VALID), "--offline", "--event", "push")
    assert result.returncode == 2
    assert "--event" in result.stderr and "--changed-only" in result.stderr


def test_cli_event_must_not_be_blank(registry):
    result = run_cli(
        "--root", str(registry.root), "--offline", "--changed-only", registry.base, "--actor", "alice", "--event", " "
    )
    assert result.returncode == 2
    assert "--event" in result.stderr


def test_cli_changed_only_and_actor_must_be_given_together():
    for args in (("--changed-only", "abc"), ("--actor", "alice")):
        result = run_cli("--root", str(VALID), "--offline", *args)
        assert result.returncode == 2, args
        assert "--changed-only" in result.stderr and "--actor" in result.stderr


def test_cli_root_outside_a_git_repository_exits_2(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\n")
    # The ceiling stops git from discovering a repository above the temp dir,
    # so the test does not depend on where pytest keeps its temp files.
    env = {**GIT_ENV, "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)}
    result = run_cli("--root", str(tmp_path), "--offline", "--changed-only", ZEROS, "--actor", "alice", env=env)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "git" in result.stderr


def test_cli_without_changed_only_never_mentions_authorization():
    result = run_cli("--root", str(VALID), "--offline")
    assert result.returncode == 0
    assert "authorization" not in result.stdout


def test_root_is_required():
    result = run_cli("--offline")
    assert result.returncode == 2
    assert "--root" in result.stderr


# --- charter N-6 guard --------------------------------------------------------


def test_machinery_and_fixtures_never_name_a_specific_org():
    # Assembled from parts so this file does not itself contain the name.
    needle = "click" + "house"
    roots = [REPO_ROOT / "scripts", REPO_ROOT / "tests", REPO_ROOT / "skills"]
    offenders = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml"}:
                if needle in path.read_text(encoding="utf-8").lower():
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


# --- shared vocabulary -------------------------------------------------------


def test_schema_vocabulary_is_the_shared_definition():
    """validate.py keeps its module-level names, but jocasta_common is the one place the vocabulary is written."""
    for name in ("KINDS", "STATUSES", "ROUTES", "KNOWN_KEYS", "DEPRECATED_KEYS"):
        assert getattr(validate, name) is getattr(jc, name), name
