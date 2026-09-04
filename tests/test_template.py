"""The instance template and the composite actions it calls.

``template/`` is copied verbatim by ``init`` to become a team's registry repo,
and its thin workflows call the composite actions under ``.github/actions/``
at a pinned tag. Nothing here is executable locally, so these tests pin the
shape the plan fixes instead: the file set, the single placeholder, the
triggers and permissions of each workflow, and the CLI contract each action
invokes. A parse failure or a drifted flag here is a broken instance in the
field, where nobody runs pytest.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "template"
TEMPLATE_WORKFLOWS = TEMPLATE / ".github" / "workflows"
MACHINERY_GITHUB = REPO_ROOT / ".github"
ACTIONS = MACHINERY_GITHUB / "actions"

MACHINERY = "mbarretta/jocasta"
PINNED_REF = "v1"

# Assembled from parts, as tests/test_validate.py does at its N-6 guard, so
# this file does not itself contain the org name and the case-insensitive
# repo-wide guard over tests/ stays clean.
FORBIDDEN_ORG_NAMES = ("click" + "house",)

EXPECTED_YAML = [
    TEMPLATE / "jocasta.yaml",
    TEMPLATE / "adoption.yaml",
    TEMPLATE_WORKFLOWS / "validate.yml",
    TEMPLATE_WORKFLOWS / "consensus-merge.yml",
    TEMPLATE_WORKFLOWS / "stale-sweep.yml",
    ACTIONS / "validate" / "action.yml",
    ACTIONS / "consensus-merge" / "action.yml",
    ACTIONS / "stale-sweep" / "action.yml",
    MACHINERY_GITHUB / "workflows" / "ci.yml",
]


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load(path: Path):
    return yaml.safe_load(path.read_text())


def triggers(workflow: dict) -> dict:
    # YAML 1.1 reads the bare key ``on`` as the boolean True.
    return workflow.get("on", workflow.get(True))


def steps(doc: dict) -> list:
    if "runs" in doc:  # composite action
        return doc["runs"]["steps"]
    return [step for job in doc["jobs"].values() for step in job["steps"]]


def uses_step(doc: dict, prefix: str) -> dict:
    matches = [s for s in steps(doc) if str(s.get("uses", "")).startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one step using {prefix}, got {matches}"
    return matches[0]


def run_text(doc: dict) -> str:
    return "\n".join(s.get("run", "") for s in steps(doc))


def text_under(*roots: Path) -> dict:
    return {
        rel(p): p.read_text()
        for root in roots
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --- file set and parseability -------------------------------------------


def test_the_yaml_file_set_is_exactly_what_the_plan_names():
    found = sorted(
        p for root in (TEMPLATE, MACHINERY_GITHUB) for p in root.rglob("*.y*ml")
    )
    assert found == sorted(EXPECTED_YAML)


@pytest.mark.parametrize("path", EXPECTED_YAML, ids=rel)
def test_every_workflow_and_action_yaml_parses_to_a_mapping(path):
    assert isinstance(load(path), dict), rel(path)


# --- template data files -------------------------------------------------


def test_jocasta_yaml_carries_only_the_three_config_keys():
    assert load(TEMPLATE / "jocasta.yaml") == {
        "schema_version": 1,
        "team": "PLACEHOLDER_TEAM",
        "machinery_ref": PINNED_REF,
    }


def test_adoption_yaml_is_an_empty_mapping():
    assert load(TEMPLATE / "adoption.yaml") == {}


def test_no_entries_ship_and_entries_readme_links_to_the_schema():
    entries = sorted(p.name for p in (TEMPLATE / "entries").iterdir())
    assert entries == ["README.md"]
    readme = (TEMPLATE / "entries" / "README.md").read_text()
    assert f"github.com/{MACHINERY}" in readme
    assert "skills/jocasta/references/schema.md" in readme
    # One paragraph: no blank line separates two blocks of prose.
    assert len([b for b in readme.strip().split("\n\n") if b.strip()]) == 1


def test_template_readme_explains_the_registry_the_plugin_and_the_rule():
    readme = (TEMPLATE / "README.md").read_text().lower()
    assert "search before you build" in readme
    assert "plugin" in readme and f"github.com/{MACHINERY}" in readme


def test_placeholder_team_is_the_only_placeholder():
    hits = {
        m for text in text_under(TEMPLATE).values() for m in re.findall(r"PLACEHOLDER_\w+", text)
    }
    assert hits == {"PLACEHOLDER_TEAM"}


# --- instance workflows --------------------------------------------------


def test_validate_workflow_runs_read_only_on_default_branch_pushes_and_prs():
    wf = load(TEMPLATE_WORKFLOWS / "validate.yml")
    on = triggers(wf)
    assert "push" in on and "pull_request" in on
    assert wf["permissions"] == {"contents": "read"}

    (job,) = wf["jobs"].values()
    # Pushes to any other branch are skipped; the default branch is read from
    # the event so the template works whatever a team calls that branch.
    assert "default_branch" in job["if"] and "pull_request" in job["if"]

    checkout = uses_step(wf, "actions/checkout@")
    assert checkout["with"]["fetch-depth"] == 0

    validate = uses_step(wf, f"{MACHINERY}/.github/actions/validate@")
    assert validate["uses"].endswith(f"@{PINNED_REF}")
    assert validate["with"]["actor"] == "${{ github.actor }}"
    assert (
        validate["with"]["base-ref"]
        == "${{ github.event.before || github.event.pull_request.base.sha }}"
    )
    # sec1: the validator only skips merge commits it knows came from a PR.
    assert validate["with"]["event"] == "${{ github.event_name }}"


def test_consensus_merge_workflow_reacts_to_pr_and_review_events_with_write_scope():
    wf = load(TEMPLATE_WORKFLOWS / "consensus-merge.yml")
    on = triggers(wf)
    assert on["pull_request"]["types"] == ["opened", "labeled", "synchronize"]
    assert on["pull_request_review"]["types"] == ["submitted"]
    assert wf["permissions"] == {"contents": "write", "pull-requests": "write"}

    merge = uses_step(wf, f"{MACHINERY}/.github/actions/consensus-merge@")
    assert merge["uses"].endswith(f"@{PINNED_REF}")
    assert merge["with"]["repo"] == "${{ github.repository }}"
    assert merge["with"]["pr"] == "${{ github.event.pull_request.number }}"


def test_stale_sweep_workflow_runs_weekly_and_on_demand_with_write_scope():
    wf = load(TEMPLATE_WORKFLOWS / "stale-sweep.yml")
    on = triggers(wf)
    assert "workflow_dispatch" in on
    (schedule,) = on["schedule"]
    fields = schedule["cron"].split()
    assert len(fields) == 5
    assert fields[2] == "*" and fields[3] == "*" and fields[4] != "*", "weekly means one weekday"
    assert wf["permissions"] == {"contents": "write", "pull-requests": "write"}

    sweep = uses_step(wf, f"{MACHINERY}/.github/actions/stale-sweep@")
    assert sweep["uses"].endswith(f"@{PINNED_REF}")
    assert sweep["with"]["repo"] == "${{ github.repository }}"


# --- composite actions ---------------------------------------------------


@pytest.mark.parametrize("name", ["validate", "consensus-merge", "stale-sweep"])
def test_each_action_bootstraps_the_machinery_the_same_way(name):
    action = load(ACTIONS / name / "action.yml")
    assert action["runs"]["using"] == "composite"

    checkout = uses_step(action, "actions/checkout@")
    assert checkout["with"]["repository"] == MACHINERY
    assert checkout["with"]["ref"] == "${{ github.action_ref }}"
    assert checkout["with"]["path"] not in ("", ".", None), "machinery goes in a subdirectory"

    python = uses_step(action, "actions/setup-python@")
    assert str(python["with"]["python-version"]) == "3.12"

    assert "pip install pyyaml" in run_text(action)

    assert action["inputs"]["token"]["default"] == "${{ github.token }}"
    script_steps = [s for s in steps(action) if "scripts/" in s.get("run", "")]
    assert script_steps, "no step invokes a machinery script"
    for step in script_steps:
        assert step["env"]["GH_TOKEN"] == "${{ inputs.token }}"
        assert step["shell"] == "bash"


def test_validate_action_invokes_the_documented_cli_contract():
    text = run_text(load(ACTIONS / "validate" / "action.yml"))
    assert "scripts/validate.py" in text
    assert re.search(r'--root\s+"?\$(\{)?GITHUB_WORKSPACE', text), text
    assert "--changed-only" in text and "--actor" in text
    assert "--event" in text
    assert "--offline" not in text


def test_validate_action_defaults_event_so_older_instance_workflows_stay_gated():
    # An instance whose validate.yml predates the `event` input still gets the
    # merge-commit check on pushes: the action reads the event itself.
    event = load(ACTIONS / "validate" / "action.yml")["inputs"]["event"]
    assert event.get("required", False) is False
    assert event["default"] == "${{ github.event_name }}"


def test_consensus_merge_action_invokes_the_documented_cli_contract():
    text = run_text(load(ACTIONS / "consensus-merge" / "action.yml"))
    assert "scripts/consensus_merge.py" in text
    assert "--repo" in text and "--pr" in text


def test_stale_sweep_action_invokes_the_documented_cli_contract():
    text = run_text(load(ACTIONS / "stale-sweep" / "action.yml"))
    assert "scripts/stale_sweep.py" in text
    assert re.search(r'--root\s+"?\$(\{)?GITHUB_WORKSPACE', text), text
    assert "--repo" in text
    assert "--dry-run" in text, "dry-run is part of the CLI contract and reachable from workflow_dispatch"


def test_action_inputs_never_reach_a_shell_unescaped():
    # Inputs flow through env vars, never inline `${{ inputs.* }}` inside `run:`.
    for name in ("validate", "consensus-merge", "stale-sweep"):
        text = run_text(load(ACTIONS / name / "action.yml"))
        assert "${{ inputs." not in text, name


# --- machinery CI --------------------------------------------------------


def test_machinery_ci_tests_the_repo_and_validates_the_template():
    wf = load(MACHINERY_GITHUB / "workflows" / "ci.yml")
    on = triggers(wf)
    assert "push" in on and "pull_request" in on
    uses_step(wf, "astral-sh/setup-uv@")
    text = run_text(wf)
    assert "uv run pytest -q" in text
    assert "uv run python scripts/validate.py --root template --offline" in text


# --- charter N-6: no org named anywhere in template/ or .github/ ---------


def test_nothing_in_template_or_github_names_an_organization():
    for path, text in text_under(TEMPLATE, MACHINERY_GITHUB).items():
        for name in FORBIDDEN_ORG_NAMES:
            assert name not in text.lower(), f"{path} names {name}"
