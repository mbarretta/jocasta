"""The instance template and the composite actions it calls.

``template/`` is copied verbatim by ``init`` to become a team's registry repo,
and its thin workflows call the composite actions under ``.github/actions/``
at a pinned tag. Nothing here is executable locally, so these tests pin the
shape the plan fixes instead: the file set, the two placeholders, the
triggers and permissions of each workflow, the OctoSTS trust policy and the
exchange step that uses it (charter D-10), the CLI contract each action
invokes, and the commit-SHA pins on every third-party action. A parse failure
or a drifted flag here is a broken instance in the field, where nobody runs
pytest.
"""

import re
import tomllib
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
# The env var each composite action writes its own `github.action_ref` into
# before the nested checkout reads it (D1 in docs/e2e-report.md).
MACHINERY_REF_ENV = "JOCASTA_MACHINERY_REF"

# Third-party actions are pinned to a full commit SHA with a `# vX.Y.Z` comment
# naming the release, never to a moving tag: the composite actions run with
# write tokens in every instance (audit finding sec5). yaml.safe_load drops
# the comment, so the pin shape is checked on the raw text.
USES_LINE = re.compile(r"^\s*-?\s*uses:\s*(?P<target>\S+)(?P<trailer>.*)$", re.MULTILINE)
SHA_PIN = re.compile(r"[^@\s]+@[0-9a-f]{40}")
VERSION_COMMENT = re.compile(r" # v\d+\.\d+\.\d+")

# Assembled from parts, as tests/test_validate.py does at its N-6 guard, so
# this file does not itself contain the org name and the case-insensitive
# repo-wide guard over tests/ stays clean.
FORBIDDEN_ORG_NAMES = ("click" + "house",)

# Charter D-10: when a workflow needs more than the per-job token it exchanges
# its OIDC identity for a minutes-lived GitHub App token through OctoSTS,
# governed by this trust policy in the instance repo. The action is
# octo-sts/action (chainguard-dev/octo-sts-action is a stub whose README
# points there); its inputs are `scope` and `identity`, its output `token`.
STS_ACTION = "octo-sts/action"
STS_IDENTITY = "jocasta"
STS_POLICY = TEMPLATE / ".github" / "chainguard" / f"{STS_IDENTITY}.sts.yaml"
STS_STEP_ID = "octo-sts"
# Every instance workflow that asks for an elevated token falls back to the
# per-job token when the exchange fails (App not installed, branch renamed).
STS_TOKEN_EXPR = f"${{{{ steps.{STS_STEP_ID}.outputs.token || github.token }}}}"
# The standing credential D-10 rejects. It must not be documented as a route
# anywhere a team reads: the template, the actions, the skill, or the README.
RETIRED_SECRET = "JOCASTA_" + "TOKEN"

EXPECTED_YAML = [
    TEMPLATE / "jocasta.yaml",
    TEMPLATE / "adoption.yaml",
    STS_POLICY,
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


def third_party_uses() -> list:
    """Every ``uses:`` line that does not call the machinery itself, as
    ``(file, target, trailing text)``; the machinery is pinned to a release
    tag on purpose so instances pick up patch releases."""
    return [
        (rel(path), m["target"], m["trailer"])
        for path in EXPECTED_YAML
        for m in USES_LINE.finditer(path.read_text())
        if not m["target"].startswith(f"{MACHINERY}/")
    ]


def locked_version(package: str) -> str:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    (found,) = [p for p in lock["package"] if p["name"] == package]
    return found["version"]


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


def test_the_team_and_repo_placeholders_are_the_only_placeholders():
    hits = {
        m for text in text_under(TEMPLATE).values() for m in re.findall(r"PLACEHOLDER_\w+", text)
    }
    assert hits == {"PLACEHOLDER_TEAM", "PLACEHOLDER_REPO"}


@pytest.mark.parametrize(
    "marker, expected_line",
    [
        ("PLACEHOLDER_TEAM", "team: PLACEHOLDER_TEAM"),
        ("PLACEHOLDER_REPO", "subject: repo:PLACEHOLDER_REPO:ref:refs/heads/main"),
    ],
)
def test_each_placeholder_appears_once_so_init_can_replace_it_literally(marker, expected_line):
    # D2 (docs/e2e-report.md): init substitutes each marker literally and then
    # greps the checkout for leftovers, so a second occurrence anywhere in the
    # template (the header comment once named it) is either rewritten into
    # nonsense or fails init's own check.
    lines = [
        line
        for text in text_under(TEMPLATE).values()
        for line in text.splitlines()
        if marker in line
    ]
    assert lines == [expected_line]


# --- OctoSTS trust policy (charter D-10) ---------------------------------


def test_trust_policy_binds_the_instance_default_branch_to_exactly_two_write_permissions():
    # Field names are the upstream TrustPolicy schema's (octo-sts/app,
    # pkg/octosts/octosts.TrustPolicy.json): `issuer` and `subject` are exact
    # matches, `permissions` keys are GitHub App installation permissions, and
    # the schema forbids unknown keys.
    policy = load(STS_POLICY)
    assert set(policy) == {"issuer", "subject", "permissions"}
    assert policy["issuer"] == "https://token.actions.githubusercontent.com"
    # init creates `main` explicitly (init-connect.md step 3), so the exact
    # subject is preferred over a pattern, as upstream recommends.
    assert policy["subject"] == "repo:PLACEHOLDER_REPO:ref:refs/heads/main"
    assert policy["permissions"] == {"contents": "write", "pull_requests": "write"}


def sts_step(workflow: dict) -> dict:
    step = uses_step(workflow, f"{STS_ACTION}@")
    assert step["id"] == STS_STEP_ID
    # ac5: without the App installed the exchange fails and the workflow must
    # still succeed on the per-job token.
    assert step["continue-on-error"] is True
    assert step["with"] == {"scope": "${{ github.repository }}", "identity": STS_IDENTITY}
    return step


@pytest.mark.parametrize("name", ["validate", "stale-sweep"])
def test_elevated_workflows_exchange_their_identity_and_fall_back_to_the_workflow_token(name):
    wf = load(TEMPLATE_WORKFLOWS / f"{name}.yml")
    assert wf["permissions"]["id-token"] == "write", "the OIDC exchange needs id-token: write"
    all_steps = steps(wf)
    sts = sts_step(wf)
    action = uses_step(wf, f"{MACHINERY}/.github/actions/{name}@")
    assert all_steps.index(sts) < all_steps.index(action)
    assert action["with"]["token"] == STS_TOKEN_EXPR
    # The fallback is documented where the next reader will look.
    text = (TEMPLATE_WORKFLOWS / f"{name}.yml").read_text()
    assert "github.token" in text and re.search(r"App.*?installed", text, re.DOTALL), text


def test_consensus_merge_does_not_exchange_tokens():
    # The workflow token is enough to merge; least privilege says no exchange.
    wf = load(TEMPLATE_WORKFLOWS / "consensus-merge.yml")
    assert not [s for s in steps(wf) if str(s.get("uses", "")).startswith(STS_ACTION)]
    assert "id-token" not in wf["permissions"]


def test_no_standing_credential_is_documented_anywhere_a_team_reads():
    roots = (TEMPLATE, MACHINERY_GITHUB, REPO_ROOT / "skills")
    offenders = [path for path, text in text_under(*roots).items() if RETIRED_SECRET in text]
    if RETIRED_SECRET in (REPO_ROOT / "README.md").read_text():
        offenders.append("README.md")
    assert offenders == []
    assert "secrets." not in "".join(text_under(TEMPLATE_WORKFLOWS).values())


# --- instance workflows --------------------------------------------------


def test_validate_workflow_runs_read_only_on_default_branch_pushes_and_prs():
    wf = load(TEMPLATE_WORKFLOWS / "validate.yml")
    on = triggers(wf)
    assert "push" in on and "pull_request" in on
    assert wf["permissions"] == {"contents": "read", "id-token": "write"}

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
    assert wf["permissions"] == {"contents": "write", "pull-requests": "write", "id-token": "write"}

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
    assert checkout["with"]["ref"] == f"${{{{ env.{MACHINERY_REF_ENV} }}}}"
    assert checkout["with"]["path"] not in ("", ".", None), "machinery goes in a subdirectory"

    python = uses_step(action, "actions/setup-python@")
    assert str(python["with"]["python-version"]) == "3.12"

    # The only dependency is pinned to the version uv.lock tests against.
    assert f'python -m pip install "pyyaml=={locked_version("pyyaml")}"' in run_text(action)

    assert action["inputs"]["token"]["default"] == "${{ github.token }}"
    script_steps = [s for s in steps(action) if "scripts/" in s.get("run", "")]
    assert script_steps, "no step invokes a machinery script"
    for step in script_steps:
        assert step["env"]["GH_TOKEN"] == "${{ inputs.token }}"
        assert step["shell"] == "bash"


@pytest.mark.parametrize("name", ["validate", "consensus-merge", "stale-sweep"])
def test_each_action_captures_its_own_ref_before_the_nested_checkout(name):
    # D1 (docs/e2e-report.md): `${{ github.action_ref }}` evaluated inside a
    # nested `uses:` step's `with:` block names the nested action's ref (the
    # checkout action's own tag), not the tag the instance called this action
    # at, so every instance workflow at `@v1` failed at the machinery checkout.
    # The value is correct in a `run:` step, so the step just before the
    # checkout captures it into $GITHUB_ENV and the checkout reads it back.
    action = load(ACTIONS / name / "action.yml")
    all_steps = steps(action)
    checkout = uses_step(action, "actions/checkout@")
    capture = all_steps[all_steps.index(checkout) - 1]

    assert "uses" not in capture and capture["shell"] == "bash", capture
    seen_by_capture = "\n".join([capture["run"], *capture.get("env", {}).values()])
    assert "${{ github.action_ref }}" in seen_by_capture, capture
    assert re.search(rf'{MACHINERY_REF_ENV}=.*>>\s*"?\$GITHUB_ENV', capture["run"]), capture["run"]

    assert checkout["with"]["ref"] == f"${{{{ env.{MACHINERY_REF_ENV} }}}}"
    assert "github.action_ref" not in str(checkout["with"]), "the with: block must not evaluate github.action_ref"


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


# --- third-party action pins (audit finding sec5) -----------------------


def test_every_third_party_action_is_pinned_to_a_commit_sha_with_a_version_comment():
    found = third_party_uses()
    assert {t.split("@")[0] for _, t, _ in found} >= {"actions/checkout", "actions/setup-python", STS_ACTION}
    for path, target, trailer in found:
        assert SHA_PIN.fullmatch(target), f"{path}: {target} is not pinned to a 40-hex commit SHA"
        assert VERSION_COMMENT.fullmatch(trailer), f"{path}: {target} lacks a trailing # vX.Y.Z comment"


def test_each_third_party_action_is_pinned_identically_everywhere():
    # One SHA and one release per action across the actions, the template
    # workflows, and ci.yml, so a bump cannot leave a file behind.
    pins = {}
    for _, target, trailer in third_party_uses():
        action, _, sha = target.partition("@")
        pins.setdefault(action, set()).add((sha, trailer.strip()))
    for action, seen in pins.items():
        assert len(seen) == 1, f"{action} is pinned inconsistently: {sorted(seen)}"


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
