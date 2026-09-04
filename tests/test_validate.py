"""Tests for scripts/validate.py against the fixture registries."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
VALID = FIXTURES / "valid-registry"
INVALID = FIXTURES / "invalid"
SCRIPT = REPO_ROOT / "scripts" / "validate.py"

LINE_RE = re.compile(r"^(entries/[^:]+\.md|adoption\.yaml|jocasta\.yaml): ([a-z-]+): .+$")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
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


def test_adoption_yaml_is_optional(tmp_path):
    (tmp_path / "jocasta.yaml").write_text("schema_version: 1\n")
    assert validate.validate_registry(tmp_path, offline=True) == []


# --- --changed-only / --actor placeholders (task 8 fills in the behavior) -----


def test_changed_only_flags_parse_and_print_notice():
    result = run_cli("--root", str(VALID), "--offline", "--changed-only", "abc123", "--actor", "alice")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("authorization checks not yet implemented") == 1


def test_changed_only_flags_do_not_mask_other_failures():
    result = run_cli("--root", str(INVALID / "kind-invalid"), "--offline", "--changed-only", "abc123", "--actor", "alice")
    assert result.returncode == 1
    assert "entries/web-tool.md: kind: " in result.stdout


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
