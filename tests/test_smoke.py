"""Smoke tests: the test harness itself is wired correctly."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pyyaml_imports_and_round_trips():
    import yaml

    doc = {"name": "example-cli", "kind": "cli", "adopters": ["alice", "bob"]}
    assert yaml.safe_load(yaml.safe_dump(doc)) == doc


def test_conftest_puts_scripts_dir_on_sys_path():
    assert str(REPO_ROOT / "scripts") in sys.path


def test_repo_root_is_the_checkout():
    assert (REPO_ROOT / "CHARTER.md").is_file()
    assert (REPO_ROOT / "pyproject.toml").is_file()
