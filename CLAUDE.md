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
The validators must also run under plain `python3` with PyYAML installed,
because GitHub Actions in registry instances invoke them that way.

## Repo layout

This repo is the **machinery**: the reusable half every team shares. The table
below is the target layout; the repo is built up toward it over several
cycles, so a directory listed here may not exist yet in a given checkout.

| Path | What it is |
|---|---|
| `CHARTER.md` | Project charter. Cite its IDs (R-n, N-n, P-n, D-n) in plans and reviews. |
| `pyproject.toml`, `uv.lock` | Python project and pinned lockfile. Tracked. |
| `scripts/` | Deterministic layer: `validate.py`, `consensus_merge.py`, `stale_sweep.py`, shared helpers. Python 3 + PyYAML, nothing else. |
| `skills/jocasta/` | The Claude Code skill (`SKILL.md` plus `references/*.md`). The only user interface. |
| `.claude-plugin/` | Plugin manifest. |
| `.github/actions/` | Composite actions that registry instances call at a pinned tag (`@v1`). |
| `.github/workflows/` | CI for this repo. |
| `template/` | The **instance** template: what `init` copies verbatim to create a team's registry repo. Its thin workflows call this repo's actions; it carries no logic of its own. |
| `tests/` | pytest suite. `conftest.py` puts `scripts/` on `sys.path` so tests `import validate` directly. |

Machinery vs template is the line to keep sharp: anything a team's registry
needs at runtime is a script or action here, referenced from the template at a
pinned ref. The template is data plus glue.

## Rules that bind every change

- **No org-specific assumptions in the machinery** (charter N-6). Nothing under
  `scripts/`, `template/`, `skills/`, or `.github/` may name any one
  organization, team, or company, or encode its habits. Example content uses
  neutral names. The first team to run an instance is not special here.
- **Mechanism gates, the model advises** (charter P-4). Schema, reachability,
  uniqueness, permissions, and merges are decided by scripts and GitHub
  Actions, never by prompt text.
- **No server, database, hosted service, web UI, or generated site** (charter
  N-1, N-2). If it cannot be done with git and the GitHub API, it does not
  happen.
- **Entry schema is exactly what `skills/jocasta/references/schema.md`
  documents** (charter N-7, P-2). Unknown keys are rejected; no field is added
  to serve a downstream consumer.
- **Archive wording** (charter R-8, D-7). Skill text never says a tool "does
  not exist"; it says the tool "does not appear in the archive".
