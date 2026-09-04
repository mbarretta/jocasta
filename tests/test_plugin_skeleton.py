"""Structural checks on the plugin manifest and the skill frame.

These pin the contract that wave-3 tasks build against: the mode table in
SKILL.md names every mode, its reference file, and its write path; the manifest
is valid JSON with the fields a marketplace reads; and the skill text keeps the
archive wording rule.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
SKILL_DIR = REPO_ROOT / "skills" / "jocasta"
SKILL_MD = SKILL_DIR / "SKILL.md"

EXPECTED_MODES = [
    "search",
    "show",
    "register",
    "deprecate",
    "transfer",
    "release",
    "claim",
    "adopt",
    "unadopt",
    "init",
    "connect",
]
WRITE_PATHS = ("none", "direct commit", "PR")
TRIGGER_PHRASES = [
    "is there a tool for",
    "register a tool",
    "jocasta",
    "what do we have for",
    "retire",
    "deprecate a tool",
    "set up a registry",
]


def _frontmatter(text: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must open with a YAML frontmatter block"
    import yaml

    return yaml.safe_load(match.group(1))


def _mode_table_rows(text: str) -> list[list[str]]:
    """Return the cells of every body row of the first table whose header starts with 'Mode'."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and line.strip("| ").lower().startswith("mode"):
            rows = []
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return rows
    raise AssertionError("SKILL.md has no table whose first column is 'Mode'")


def test_plugin_json_is_valid_and_complete():
    data = json.loads(PLUGIN_JSON.read_text())
    assert data["name"] == "jocasta"
    assert data["version"] == "0.1.0"
    assert data["description"].strip()
    assert data["author"]["name"] == "Michael Barretta"
    assert data["homepage"] == "https://github.com/mbarretta/jocasta"
    assert data["repository"] == "https://github.com/mbarretta/jocasta"
    assert data["license"] == "MIT"
    assert isinstance(data["keywords"], list) and data["keywords"]


def test_skill_frontmatter_names_skill_and_triggers():
    fm = _frontmatter(SKILL_MD.read_text())
    assert fm["name"] == "jocasta"
    description = fm["description"].lower()
    for phrase in TRIGGER_PHRASES:
        assert phrase in description, f"description does not trigger on {phrase!r}"


def test_mode_table_lists_exactly_the_modes_with_reference_and_write_path():
    rows = _mode_table_rows(SKILL_MD.read_text())
    modes = [re.sub(r"[`*]", "", row[0]).split()[0] for row in rows]
    assert modes == EXPECTED_MODES
    for row in rows:
        reference, write_path = row[-2], row[-1]
        assert re.search(r"references/[a-z-]+\.md", reference), f"row lacks a reference file: {row[0]}"
        assert any(wp in write_path for wp in WRITE_PATHS), f"row lacks a write path: {row[0]}"


def test_skill_md_stays_within_line_budget():
    assert len(SKILL_MD.read_text().splitlines()) <= 250


def test_skill_text_never_says_does_not_exist_except_to_forbid_it():
    for path in SKILL_DIR.rglob("*.md"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "does not exist" in line.lower():
                assert re.search(r"forbid|never|banned|not allowed", line, re.IGNORECASE), (
                    f"{path.relative_to(REPO_ROOT)}:{n} uses the forbidden phrase without marking it forbidden"
                )


def test_reference_files_written_by_this_wave_exist():
    for name in ("voice.md", "init-connect.md"):
        assert (SKILL_DIR / "references" / name).is_file()


MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"


def test_marketplace_json_serves_this_repo_as_a_single_plugin_marketplace():
    """`/plugin marketplace add mbarretta/jocasta` then `/plugin install jocasta@jocasta`
    only works if the repo carries a marketplace manifest whose one plugin is the
    repo root. Both READMEs give exactly those two commands."""
    data = json.loads(MARKETPLACE_JSON.read_text())
    plugin = json.loads(PLUGIN_JSON.read_text())
    assert data["name"] == "jocasta"
    assert data["owner"]["name"] == plugin["author"]["name"]
    (entry,) = data["plugins"]
    assert entry["name"] == plugin["name"]
    assert entry["source"] in ("./", "."), "the plugin is the repo root, so init can find template/"
    for readme in (REPO_ROOT / "README.md", REPO_ROOT / "template" / "README.md"):
        text = readme.read_text()
        assert "/plugin marketplace add mbarretta/jocasta" in text, readme
        assert "/plugin install jocasta@jocasta" in text, readme


def test_skill_md_names_every_reference_file_and_every_named_file_exists():
    text = SKILL_MD.read_text()
    named = set(re.findall(r"references/([a-z-]+\.md)", text))
    on_disk = {p.name for p in (SKILL_DIR / "references").glob("*.md")}
    assert named == on_disk, f"named but missing: {named - on_disk}; on disk but unnamed: {on_disk - named}"


def test_mode_table_write_paths_agree_with_write_paths_reference():
    """write-paths.md is the D-3 decision table; the mode table may only summarize it."""
    write_paths = (SKILL_DIR / "references" / "write-paths.md").read_text()
    expected = {
        "search": "none",
        "show": "none",
        "register": "direct commit",
        "deprecate": "direct commit (owner) or PR (non-owner)",
        "transfer": "direct commit (owner only)",
        "release": "direct commit (owner only)",
        "claim": "PR",
        "adopt": "direct commit",
        "unadopt": "direct commit",
        "init": "direct commit (to the new repo)",
        "connect": "none",
    }
    rows = _mode_table_rows(SKILL_MD.read_text())
    actual = {re.sub(r"[`*]", "", row[0]).split()[0]: row[-1] for row in rows}
    assert actual == expected
    # Every mode the table says writes to the registry has a row in the decision
    # table (adopt and unadopt share one row, so match anywhere in the first cell).
    for mode in ("register", "deprecate", "transfer", "release", "claim", "adopt", "unadopt"):
        assert re.search(rf"^\|[^|\n]*`{mode}\b", write_paths, re.MULTILINE), f"write-paths.md has no row for {mode}"
    # And the modes outside the table are named there as outside it.
    for mode in ("init", "connect", "search", "show"):
        assert f"`{mode}`" in write_paths, f"write-paths.md does not account for {mode}"
