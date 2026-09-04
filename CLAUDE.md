# Jocasta — working notes for Claude Code

Jocasta is a team tool registry that is only a GitHub repo plus a Claude Code
skill. What the project is *supposed* to be — north star, requirements,
non-goals, invariants, and the decision log — lives in `CHARTER.md`. Read it
before changing behavior; it is the source of truth and is edited only through
the `/charter` skill, never by hand.

## Verification

```
uv run pytest -q
```

Run it before every commit. It must exit 0 from a fresh clone. Runtime code
depends on Python >= 3.11 and PyYAML only; pytest is a `dev` dependency group.
The scripts must also run under plain `python3` with PyYAML installed, because
the composite actions invoke them that way (`pip install pyyaml`, then
`python scripts/<name>.py`).

Machinery CI (`.github/workflows/ci.yml`) runs the suite and then
`uv run python scripts/validate.py --root template --offline`, so the instance
template must always validate clean with zero entries.

## Repo layout

This repo is the **machinery**: the reusable half every team shares.

| Path | What it is |
|---|---|
| `CHARTER.md` | Project charter. Cite its IDs (R-n, N-n, P-n, D-n) in plans and reviews. Edited only via `/charter`. |
| `pyproject.toml`, `uv.lock` | Python project and pinned lockfile. Tracked. |
| `scripts/` | Deterministic layer: `validate.py`, `consensus_merge.py`, `stale_sweep.py`, and `jocasta_common.py` (entry parsing, registry loading, reachability, git and `gh` wrappers). Python 3 + PyYAML, nothing else. |
| `skills/jocasta/SKILL.md` | The skill frame: mode table, config discovery, snapshot, identity, local validator, voice rules, boundaries. Under 250 lines; protocols live in the references. |
| `skills/jocasta/references/` | One file per protocol: `search.md`, `register.md`, `ownership.md`, `write-paths.md`, `adoption.md`, `init-connect.md`; plus `schema.md` (the entry format the validator enforces) and `voice.md` (worked examples). |
| `.claude-plugin/` | `plugin.json` (plugin manifest) and `marketplace.json` (this repo as a single-plugin marketplace, so `/plugin marketplace add mbarretta/jocasta` works). |
| `.github/actions/` | Composite actions (`validate`, `consensus-merge`, `stale-sweep`) that registry instances call at a pinned tag (`@v1`). Each checks this repo out at `github.action_ref`, installs PyYAML, and runs the matching script. |
| `.github/workflows/ci.yml` | CI for this repo. |
| `template/` | The **instance** template: what `init` copies verbatim to create a team's registry repo (`jocasta.yaml`, `adoption.yaml`, `entries/README.md`, `README.md`, three thin workflows). It carries no logic of its own; `PLACEHOLDER_TEAM` is its only placeholder. |
| `tests/` | pytest suite. `conftest.py` puts `scripts/` on `sys.path` so tests `import validate` directly. Fixtures under `tests/fixtures/` are complete minimal instances, one per validator rule. |
| `.claude/plans/` | Harness plan JSONs. Tracked on purpose. |

Machinery vs template is the line to keep sharp: anything a team's registry
needs at runtime is a script or action here, referenced from the template at a
pinned ref. The template is data plus glue.

## Running each script locally

All three scripts take `--help`. From the repo root, with `uv`:

```
# Schema and reachability over an instance checkout; --offline skips the network.
uv run python scripts/validate.py --root <instance> [--offline]

# The push-authorization rule, as the instance's validate.yml runs it.
uv run python scripts/validate.py --root <instance> --changed-only <base-sha> --actor <login> [--event NAME]

# Merge decision for one PR. Talks to GitHub through `gh` and merges for real
# when the rule is met; point it at a sandbox instance, never at a team's.
uv run python scripts/consensus_merge.py --repo OWNER/REPO --pr N

# Stale-source sweep over a checkout of the instance's default branch.
# --dry-run reports without branching or opening PRs; --pause 0 skips the wait
# between the two reachability attempts.
uv run python scripts/stale_sweep.py --root <instance> --repo OWNER/REPO --dry-run --pause 0
```

Without `uv`, replace `uv run python` with `python3` (PyYAML installed). The
scripts use `gh` for github.com reachability and for every GitHub API call, so
`gh auth status` must succeed (or `GH_TOKEN` be set) for anything beyond
`validate.py --offline`. The tests never reach the network: `gh`, reachability,
and remotes are faked or replaced by local bare repos.

To check the plugin manifests the way Claude Code will:
`claude plugin validate .` (the CLAUDE.md warning it prints is expected; this
file is for developing the repo, not plugin context).

## Rules that bind every change

- **`CHARTER.md` is edited only through `/charter`.** Record decisions there
  as amendments, never by hand-editing the file, so the decision log stays a
  log.
- **No org-specific assumptions in the machinery** (charter N-6). Nothing under
  `scripts/`, `template/`, `skills/`, or `.github/` may name any one
  organization, team, or company, or encode its habits. Example content uses
  neutral names. A guard test greps for the name; tests that must mention it
  assemble it from parts so the guard stays clean.
- **Mechanism gates, the model advises** (charter P-4). Schema, reachability,
  uniqueness, permissions, and merges are decided by scripts and GitHub
  Actions, never by prompt text.
- **No server, database, hosted service, web UI, or generated site** (charter
  N-1, N-2). If it cannot be done with git and the GitHub API, it does not
  happen.
- **Entry schema is exactly what `skills/jocasta/references/schema.md`
  documents** (charter N-7, P-2). Unknown keys are rejected; no field is added
  to serve a downstream consumer. `SCHEMA_VERSION` in `validate.py` and the
  template's `schema_version` move together.
- **Archive wording** (charter R-8, D-7). Skill text never says a tool "does
  not exist"; it says the tool "does not appear in the archive". A test scans
  `skills/` for the forbidden phrase outside lines that forbid it.
- **CLI contracts are fixed** because the composite actions call them:
  `validate.py --root DIR [--offline] [--changed-only REF --actor LOGIN [--event NAME]]`,
  `consensus_merge.py --repo OWNER/REPO --pr N`,
  `stale_sweep.py --root DIR --repo OWNER/REPO [--dry-run]`. Add flags; never
  rename or remove these.
- **Structural tests pin the docs.** `tests/test_plugin_skeleton.py`,
  `test_search_reference.py`, `test_register_reference.py`, and
  `test_template.py` assert the SKILL.md mode table, reference wording, and
  template shape. Update a test only when the doc change it pins is the
  deliberate one; never loosen it to get green.
