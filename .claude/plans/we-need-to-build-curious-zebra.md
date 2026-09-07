# Jocasta v1 — implementation plan

## Context

The repo holds only `CHARTER.md` (v1.0, 2026-09-04). Jocasta is a team tool registry that is
nothing but a GitHub repo plus a Claude Code skill: describe a need in prose, learn what already
answers to it, who owns it, and whether it is alive. The charter fixes the shape (R-1..R-9,
N-1..N-7, P-1..P-6, D-1..D-7); this plan turns it into a buildable v1 and is written to be fed to
`/harness`, so every task cites the charter IDs it serves.

Decisions made with the user during planning (each needs a `/charter amend` entry, listed at the end):

- Template ships as `template/` **inside this repo**; instance CI pins composite actions from this repo (`mbarretta/jocasta/.github/actions/*@v1`).
- Deterministic layer is **Python 3 + PyYAML** (matches forge; runs identically locally and in Actions).
- Adoption (R-7 / T-2) ships in v1 as **one `adoption.yaml`** in the instance: `tool-name: [github-login, ...]`. Editing your own login is a direct commit.
- Implementation runs through `/harness`.

Conventions borrowed from `~/workspace/github/mbarretta/mab-agent-skills`: plugin = `.claude-plugin/plugin.json` + `skills/<name>/SKILL.md` + `references/*.md`; modes documented in a table in SKILL.md (see `mab-harness/skills/charter/SKILL.md`).

## Architecture

Two kinds of repo (D-1):

1. **Machinery** — this repo, public: the plugin/skill, schema, validators, composite GitHub Actions, and `template/`.
2. **Instance** — one per team, created by `init`, public or private: `jocasta.yaml`, `entries/*.md`, `adoption.yaml`, thin workflows that call the machinery's actions at a pinned tag.

All state is files in the instance (D-2). Model judgment (search ranking, overlap detection, prose drafting) lives in SKILL.md; gates (schema, reachability, uniqueness, consensus merge, stale sweep) are Python run by Actions and by the skill before it writes (P-4).

### Machinery repo layout

```
.claude-plugin/plugin.json          name "jocasta", version 0.1.0
skills/jocasta/SKILL.md             modes, protocol, voice rule, config discovery
skills/jocasta/references/
  schema.md                         the entry format, field by field, with the P-2 justification for each
  voice.md                          Jocasta Nu register: examples of good/bad, the inverted rule (D-7)
  write-paths.md                    direct-commit vs PR decision table (D-3), conflict/retry recipe
  search.md                         fetch → rank → present protocol, output template
scripts/
  validate.py                       entries + adoption.yaml validator (CLI contract below)
  consensus_merge.py                decides/merges contested PRs (R-5, D-3)
  stale_sweep.py                    opens stale-source deprecation PRs (R-5)
  jocasta_common.py                 frontmatter parsing, GitHub URL → API reachability, shared helpers
tests/                              pytest; fixtures under tests/fixtures/{valid,invalid}-registry/
.github/actions/validate/action.yml           composite: setup-python, pip pyyaml, run validate.py
.github/actions/consensus-merge/action.yml
.github/actions/stale-sweep/action.yml
.github/workflows/ci.yml            pytest + validate.py against template/ and fixtures
template/                           copied verbatim by `init` (see below)
README.md, CLAUDE.md, LICENSE (MIT), CHARTER.md
```

### Instance repo layout (`template/`)

```
jocasta.yaml                 schema_version: 1, team: <name>, machinery_ref: v1
README.md                    what this is, how to install the skill, "search before you build"
entries/README.md            one paragraph + link to schema; no entries ship
adoption.yaml                {}   (tool-name → [logins])
.github/workflows/validate.yml          on push to default + pull_request → uses machinery validate@v1
.github/workflows/consensus-merge.yml   on pull_request_review submitted, pull_request opened/labeled → consensus-merge@v1
.github/workflows/stale-sweep.yml       weekly schedule + workflow_dispatch → stale-sweep@v1
```

Instances never carry validator code (no vendoring); a version skew shows up as `validate.py` refusing a `schema_version` it does not know (D-1 tradeoff, made loud).

### Entry format (R-2, P-2, P-3, D-4, D-6)

One Markdown file per entry, `entries/<name>.md`. Frontmatter is the mechanical part; the body is prose the model searches. Every field below is load-bearing; nothing else is allowed (validator rejects unknown keys so the schema cannot creep to serve a consumer, N-7).

```yaml
---
name: apk-find                 # == filename stem, kebab-case, unique
owner: mbarretta               # exactly one GitHub login (R-4, D-5); "~" only after release
source: https://github.com/mbarretta/apk-find   # must be reachable (R-6)
kind: cli | script | skill     # the D-4 boundary, enforced as an enum
install: brew install ...      # optional one-liner; a found tool is installed by hand in v1 (D-6)
registered: 2026-09-04
status: active | deprecated
deprecated:                    # required iff status: deprecated
  route: owner | consensus | stale-source
  date: 2026-09-04
  note: optional free text
---
First paragraph: what it does, in the words someone with the need would use.
Then: when you would reach for it, and what it is not.
```

`adoption.yaml`:

```yaml
apk-find: [mbarretta, someone-else]
```

### Skill modes (SKILL.md)

Config discovery: `~/.config/jocasta/config.yaml` → `registry: org/repo` (written by `init`/`connect`); a `jocasta.yaml` in the cwd wins if present. Snapshot: shallow clone to `~/.cache/jocasta/<org>/<repo>`, `git pull --ff-only` before every read (D-2: search is a fetch, not an index). Identity: `gh api user --jq .login` (N-5).

| Mode | What it does | Write path (D-3) | Serves |
|---|---|---|---|
| `search <prose>` | Refresh snapshot, read every entry + adoption.yaml, rank candidates by fit to the need, then by adopter count and status. Present name, one-line what, owner, status, adopters, source. Deprecated entries shown, marked. | none | R-1, R-7, R-8 |
| `register` | Interview: source URL first (read its README via `gh api` to draft prose), then name, kind, install; owner defaults to the caller. Run the overlap check against all entries and **report before writing** (R-3). Run `validate.py`. Commit to default branch, push; on rejection `pull --rebase` and retry once. | direct | R-2, R-3, R-6 |
| `show <name>` | Print the entry and its adopters. | none | R-1 |
| `deprecate <name>` | Caller is owner → direct commit (`route: owner`). Otherwise branch + PR labeled `deprecation`, body states why; the consensus action merges it (see below). | direct / PR | R-5, P-5 |
| `transfer <name> <login>` / `release <name>` | Owner only, direct commit. Release sets `owner: ~`; the entry stays active and search shows "unowned". | direct | R-4 |
| `claim <name>` | Non-owner asks for ownership (typically of an unowned entry) → PR labeled `ownership`. | PR | R-4, P-5 |
| `adopt <name>` / `unadopt <name>` | Add/remove the caller's own login under the tool in `adoption.yaml`. | direct | R-7 |
| `init <org>/<name> [--public]` | `gh repo create`, copy `template/`, fill `jocasta.yaml`, commit, push, write user config. Nothing to deploy (U-4). | n/a | R-9 |
| `connect <org>/<repo>` | Point config at an existing registry. | n/a | U-4 |

Voice (R-8, D-7): SKILL.md carries the persona and one hard rule. Every response that changed the repo begins with a plain statement of exactly what was written or opened (file, branch, PR link) before any character text. The phrase "does not exist" is banned; the model says "does not appear in the archive". `references/voice.md` holds worked examples, including an empty search result.

### Deterministic layer

`scripts/validate.py --root <instance-dir> [--offline] [--changed-only <base-ref>] [--actor <login>]` — exit 0/1, one plain line per failure:

- frontmatter parses; only known keys; `name` == filename stem, kebab-case, unique
- `owner` present on any entry whose file is new in the diff (R-6); `~` allowed only on existing entries
- `source` reachable: GitHub URLs via `gh api repos/{o}/{r}` (works for private repos the actor can see), others via HTTP HEAD; skipped with `--offline`
- `kind` in enum; `deprecated` block present iff status deprecated; dates ISO
- `adoption.yaml`: every key is an existing entry; values are lists of logins
- with `--actor` and `--changed-only`: a push that edits `adoption.yaml` may only add/remove that actor's own login; a push that edits an entry must be by its owner or be creating it (otherwise: "open a PR")
- `schema_version` in `jocasta.yaml` must equal the version this script supports

`scripts/consensus_merge.py --pr <n>` (run by the action on review/open events):

- PR must touch exactly one entry file (plus nothing else); otherwise comment and stop
- read the entry's current owner from the default branch
- owner approved → merge (`route: owner` recorded by the PR body already)
- else count distinct non-owner voices = PR author (if not owner) + approving reviewers who are not owner and not author; ≥ 2 → merge (R-5 "two non-owners")
- owner requested changes → comment, do not merge; never auto-close
- merge with `gh pr merge --squash`; the commit message names the route

`scripts/stale_sweep.py --root <dir>` (weekly): for each `status: active` entry, check `source` twice with a pause; if unreachable both times and no open PR labeled `stale-source` exists for that entry, open a PR setting `status: deprecated`, `route: stale-source`. Owner closes it after fixing the source, or consensus merges it. Mechanism proposes, people gate (P-4, P-5).

Composite actions wrap these with `actions/setup-python`, `pip install pyyaml`, and a checkout of the machinery repo at the calling ref; permissions `contents: write`, `pull-requests: write` documented in the template workflows.

## Tasks for the harness

Wave 1 — foundations (independent):

1. **Schema + validator** — `skills/jocasta/references/schema.md`, `scripts/jocasta_common.py`, `scripts/validate.py`, pytest fixtures with one valid registry and one invalid case per rule. [R-2, R-6, P-2, P-3, N-7, D-4]
2. **Template + actions** — `template/` as specified, three composite actions, machinery `ci.yml` that runs pytest and validates `template/`. Interface contract with task 1 is the `validate.py` CLI above. [R-9, D-1, N-1]
3. **Plugin skeleton + init/connect** — `plugin.json`, `SKILL.md` frame (config discovery, snapshot refresh, identity, mode table, voice section), `references/voice.md`, `init` and `connect` protocols. [R-8, R-9, U-4, D-7]

Wave 2 — the modes (depend on wave 1):

4. **search + show** — `references/search.md`: fetch, rank (fit, then adopters, then status), output template, the empty-result wording. [R-1, R-7, R-8]
5. **register** — interview order, README-assisted prose draft, overlap report gate, local validate, direct commit with rebase-retry. [R-2, R-3, R-6, D-3]
6. **ownership + deprecation** — `deprecate`/`transfer`/`release`/`claim` protocols, `references/write-paths.md`, `scripts/consensus_merge.py` + tests with mocked `gh` output. [R-4, R-5, D-3, D-5, P-5]
7. **adoption** — `adopt`/`unadopt`, `adoption.yaml` rules in validator (own-login-only), search ranking hook. [R-7, T-2]

Wave 3 — closing (depends on wave 2):

8. **stale sweep** — `scripts/stale_sweep.py` + tests, wired into the template workflow. [R-5]
9. **Docs + release** — `README.md` (both audiences: team lead running `init`, engineer running `search`), `CLAUDE.md`, tag `v1` so template workflows resolve; end-to-end run below.

## Verification

- `pytest` green in the machinery repo; `validate.py --root template --offline` passes; every invalid fixture fails with a single plain line naming the rule.
- Create a real private instance `mbarretta/jocasta-sandbox` with `init`; confirm the three workflows appear and `validate.yml` passes on the empty registry.
- `register` two tools, the second overlapping the first: overlap is reported before any write; both land as direct commits; CI green.
- `search` with a prose need finds them ranked; a search for something absent yields "does not appear in the archive" and never "does not exist".
- `adopt` from the sandbox account; `search` shows the adopter count.
- `deprecate` as owner → direct commit. `deprecate` from a second GitHub account → PR; approve from a third → `consensus-merge` merges; deprecated entry still appears in `search`, marked.
- `release` then `claim` from another account → PR → merge; entry shows new owner.
- Break a `source` URL, run `stale-sweep.yml` via dispatch → PR opened with `route: stale-source`; close it after fixing → next run opens nothing.
- Edit `adoption.yaml` to add someone else's login and push → `validate.yml` fails with the own-login rule.
- Delete the sandbox afterwards.

## Harness plan echo (`/harness plan` → `.claude/plans/feat-jocasta-v1.json`)

**Slug** `feat-jocasta-v1` · kind `feature` · mode `dev` · parallelism `auto` · verification `uv run pytest -q`

**Charter check**: advances R-1..R-9; no hard tensions. Advisory: `adoption.yaml` is a shared file non-owners edit by direct commit. It is not an entry, so D-3 is not reversed; propose D-8 at reconciliation.

**Constraints** (evaluator FAILs any task that crosses one):
1. No server, database, hosted service, web UI, or generated site. Every behavior is files in a git repo plus the GitHub API (charter N-1, N-2).
2. Nothing under `scripts/`, `template/`, `skills/`, or `.github/` names ClickHouse or any one org's habits (charter N-6).
3. Entry frontmatter keys are exactly those in `references/schema.md`; the validator rejects unknown keys and no task adds a field for a consumer (charter N-7, P-2).
4. Skill text never says a tool "does not exist"; only "does not appear in the archive" (charter R-8, D-7).
5. No write is gated by prompt text alone: schema, reachability, uniqueness, permissions, and merges are decided by scripts or Actions (charter P-4).

**Tasks and waves** (10 planned + 1 end-to-end; bootstrap first so `uv run pytest -q` works in every worktree):

| Wave | Tasks | Notes |
|---|---|---|
| 1 | **1** repo bootstrap: `pyproject.toml` (pyyaml, pytest), `.gitignore`, `LICENSE`, `CLAUDE.md`, README stub, `tests/conftest.py` + smoke test | alone: owns `pyproject.toml` (shared infra) |
| 2 | **2** schema.md + `jocasta_common.py` + `validate.py` + fixtures/tests · **3** `template/` + 3 composite actions + machinery `ci.yml` · **4** `plugin.json` + `SKILL.md` + `voice.md` + init/connect reference | disjoint dirs; SKILL.md owned by task 4 only |
| 3 | **5** search + show reference · **6** register reference · **7** ownership/deprecation references + `consensus_merge.py` + tests · **8** adoption reference + validator `--actor/--changed-only` authorization rules | 5/6/7 write only their own `references/*.md`; 8 is the only wave-3 task touching `validate.py` |
| 4 | **9** `stale_sweep.py` + tests | independent, but wave 3 is at the 4-task cap |
| 5 | **10** README for both audiences, CLAUDE.md refresh, SKILL.md reconciliation, `v1` tag | touches SKILL.md, so after wave 3 |
| 6 | **11** end-to-end sandbox: push machinery to `github.com/mbarretta/jocasta` (public), create and later delete private `mbarretta/jocasta-sandbox`, run the verification script above | outward-facing: creates two GitHub repos; orchestrator asks before pushing |

CLI contracts fixed now so parallel tasks agree: `validate.py --root DIR [--offline] [--changed-only REF --actor LOGIN]`; `consensus_merge.py --repo OWNER/REPO --pr N`; `stale_sweep.py --root DIR --repo OWNER/REPO [--dry-run]`. Composite actions call these with `python scripts/<name>.py` after `pip install pyyaml`.

## Charter follow-ups (via `/charter amend`, after approval)

- **D-8** adoption recorded as one `adoption.yaml`, self-declared per login, additive self-edits are direct commits — closes T-2.
- **D-9** deterministic layer in Python + PyYAML; instances run it via pinned composite actions from the machinery repo, never vendored — refines D-1.
- **D-10** template lives in `template/` of the machinery repo; `init` copies it — refines D-1/R-9.
- **D-11** consensus = two distinct non-owner voices (proposer counts as one); owner approval alone merges; owner "request changes" blocks auto-merge — refines R-5/D-3.
- **D-12** `release` leaves an entry active and unowned; `claim` is a PR; the validator requires an owner only on new entries — refines R-4/D-5.
- Note for T-3: nothing in `template/` or `scripts/` mentions ClickHouse; the first instance is created with `init` like any other.
