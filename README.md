# jocasta

Jocasta is the archive of a team's tools: describe what you need in your own
words and she tells you what already answers to it, who owns it, and whether it
is still alive. She is a GitHub repo and a Claude Code skill, nothing more. The
repo is the whole archive, and the skill is how people submit, search, and
retire entries without ever learning its schema. Registering a tool must stay
cheaper than mentioning it in Slack, because an archive people skip becomes an
archive that lies. And the archive is never confused with the world: if a thing
is not in the records, that is a fact about the records.

This repository is the **machinery**: the skill, the entry schema, the Python
validators, the composite GitHub Actions, and the `template/` a team copies to
create its own registry. Each team's registry (an **instance**) is a separate
repo of Markdown entries plus three thin workflows that call this repo's
actions at a pinned tag. Nothing is deployed anywhere.

## Install the plugin

The plugin needs [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
with plugin support, the [GitHub CLI](https://cli.github.com/) (`gh`) logged
in, and Python 3.11 or newer with either [`uv`](https://docs.astral.sh/uv/) or
PyYAML installed, so the skill can run the validator on your machine.

This repo is its own single-plugin marketplace (`.claude-plugin/marketplace.json`
alongside `.claude-plugin/plugin.json`). Inside Claude Code:

```
/plugin marketplace add mbarretta/jocasta
/plugin install jocasta@jocasta
```

or from a shell:

```
claude plugin marketplace add mbarretta/jocasta
claude plugin install jocasta@jocasta
```

Both forms are the ones `claude plugin marketplace --help` and
`claude plugin install --help` document (Claude Code 2.1); the manifests pass
`claude plugin validate .`. Restart Claude Code after installing, then say
`jocasta` (or just ask "is there a tool for ...") and the skill answers.

## Stand up a registry

One person on the team runs, in Claude Code:

```
jocasta init <org>/<name>
```

The skill confirms visibility (private unless you add `--public`) and a team
name, then creates the repo with `gh repo create`, copies `template/` into it
verbatim, replaces the one placeholder, pushes the commit `Initialize jocasta
registry`, and writes `~/.config/jocasta/config.yaml` pointing at the new repo.
Everyone else points their machine at it with:

```
jocasta connect <org>/<name>
```

which checks the repo carries a `jocasta.yaml` and writes the same config file.
A checkout of the registry repo itself is also a valid place to work: when the
current directory holds `jocasta.yaml`, that registry wins over the config
file.

`init` creates no branch protection, secrets, or teams. The registry's
workflows run with the repository's own token, and anyone who can push to the
repo can use it. See [staying honest](#how-the-archive-stays-honest) below for
the two settings worth turning on by hand.

## Find a tool

Ask in prose: "is there a tool for diffing two parquet files?", "what do we
have for checking which directories a branch touched?". The skill pulls a
shallow clone of the registry (`~/.cache/jocasta/<org>/<repo>`), reads every
entry's description, and ranks the candidates by fit to your need first, then
by how many colleagues have adopted each one, then by status. Deprecated
entries are still listed, clearly marked with why and when they were retired,
so a tool you already have installed can tell you what replaced it. Names are
the weakest signal: a tool called `pq-diff` may not diff parquet, and the tool
that does may be called `table-compare`; only the description decides.

When nothing fits, the answer is that what you describe does not appear in the
archive, with the nearest miss if there is one. The archive speaks only for its
records, never for the world. `jocasta show <name>` prints one entry in full
with its adopters.

## Register a tool

Say "register a tool" (or "I built a thing") and give the URL. The skill reads
the repo's README to draft a description in the words someone with the need
would use, proposes a name and a kind (command-line tool, script, or agent
skill), lifts a one-line install command if the README has one, and asks you
to confirm. You are never shown YAML or asked for a field by its schema name.

Before anything is written, the skill compares your draft against every
existing entry and reports what overlaps, with owner and adopter count, and
asks whether to continue, adopt the existing tool instead, or stop. The report
is made even when the answer is that nothing overlaps. Then it writes
`entries/<name>.md`, runs the validator (schema, reachable source, unique
name, owner present), and commits directly to the registry's default branch as
`register <name>` with you as the owner. The response opens with the file,
commit, and repo before any other text.

Only things a person can run on their own machine are admitted: an executable,
a script, or an agent skill. Hosted services and documentation pages are
declined without anything being written.

## Retire a tool

Every entry has exactly one owner, and nothing is ever deleted: a retired tool
stays in the archive as `status: deprecated` with the route that retired it,
the date, and an optional note. Three routes:

- **Owner.** The owner says "deprecate <name>"; the change is a direct commit
  to the default branch.
- **Consensus.** Anyone else who says "deprecate <name>" gets a pull request on
  branch `jocasta/deprecate-<name>-<login>`, labeled `deprecation`, with their
  reason in the body. The instance's `consensus-merge` workflow merges it when
  the owner approves, or when two people who are not the owner have voiced
  support (the author counts as one). If the owner requests changes it stays
  open; it is never closed automatically.
- **Stale source.** Once a week the instance's `stale-sweep` workflow checks
  every active entry's source, trying again after a pause when one does not
  answer, and for any that fails both attempts opens
  a pull request on `jocasta/stale-<name>`, labeled `stale-source` and
  `deprecation`, proposing the retirement. Fix the source (or update the
  entry's `source` on the default branch) and close the PR to dismiss it;
  closing without fixing only postpones it until the next sweep.

Ownership moves the same way: `transfer <name> <login>` and `release <name>`
are owner-only direct commits (a released entry stays active and shows as
unowned), and `claim <name>` opens a pull request labeled `ownership` that
merges on the same rule.

Two things about the consensus gate to know before you rely on it. First, the
merge script only ever merges a pull request whose changed-file set is exactly
one file named `entries/<name>.md` at the top of `entries/`: two files,
`adoption.yaml`, `entries/README.md`, a nested path, a deletion, or a rename is
refused with one explanatory comment and the PR stays open for you to fix.
Second, a pull request opened by `stale-sweep` with the workflow's own token
does not start the `consensus-merge` workflow's `opened` run, because GitHub
does not let a workflow token trigger further workflows; the script first runs
on the first human event on that PR (a review, a label, or a push to its
branch). Set the instance's `JOCASTA_TOKEN` secret to a personal access token
or GitHub App token if you want the sweep's pull requests treated like a
person's from the moment they open.

## Adoption

"adopt <name>" records that you use a tool; "unadopt <name>" withdraws it.
Both edit one file, `adoption.yaml` (tool name to a list of GitHub logins), as
a direct commit of your own login and nothing else. Adoption is self-declared,
per login, and readable by everyone with access to the registry; the skill
never infers it from installs or shell history and never records anyone but
the caller. Search ranks on it after fit, so a tool three colleagues have
adopted is a better first answer than one nobody has.

## How the archive stays honest

Schema, reachability, uniqueness, permissions, and merges are decided by
scripts and GitHub Actions, never by the model. The instance's three workflows
pin this repo's composite actions at a tag:

| Workflow (instance) | Action (machinery) | What it runs |
|---|---|---|
| `validate.yml`, on every push to the default branch and every pull request | `mbarretta/jocasta/.github/actions/validate@v1` | `scripts/validate.py --root $GITHUB_WORKSPACE --changed-only <before> --actor <pusher> --event <event>`: every schema rule, plus the authorization rule that a direct push may only add an entry the pusher owns, edit an entry the pusher owned before the push, or change the pusher's own line in `adoption.yaml`. Entries are deprecated, never deleted. |
| `consensus-merge.yml`, on pull request open, label, push, and review | `mbarretta/jocasta/.github/actions/consensus-merge@v1` | `scripts/consensus_merge.py --repo <repo> --pr <n>`: the one-file gate and the owner-or-two-voices rule above. |
| `stale-sweep.yml`, weekly and on demand | `mbarretta/jocasta/.github/actions/stale-sweep@v1` | `scripts/stale_sweep.py --root $GITHUB_WORKSPACE --repo <repo> [--dry-run]`: the stale-source route above. |

Instances stay in step with the machinery in two ways. The `@v1` pin means an
instance runs whatever this repo's `v1` tag points at on each workflow run,
with no vendored copy of the scripts to fall behind; which commits `v1` is
moved to is this repo's release decision, not the instance's.
`schema_version` in the instance's `jocasta.yaml` (`1` today, alongside
`machinery_ref: v1`) must equal the `SCHEMA_VERSION` constant in
`scripts/validate.py`, and a mismatch fails validation naming both numbers;
that is how a schema change becomes a loud, deliberate upgrade on the
instance rather than a silent misread. A change to the entry format therefore
ships as a new tag and a new schema version together.

What the push check does and does not do, so nobody mistakes it for more than
it is. `validate.yml` runs after a push has landed; a violation turns that run
red with one `authorization` line, it does not undo the commit. The check
skips a `pull_request` event's run (the workflow passes `github.event_name` as
`--event`; that checkout is GitHub's synthetic merge, and the pull request
path is gated by review and `consensus-merge`) and any push made by
`github-actions[bot]`. A `push` is checked even when `HEAD` is a merge commit,
so a local `git merge --no-ff` of someone else's entry, or clicking Merge on
one's own pull request, goes red for whoever pushed or merged it. Red after
the fact is all the check can do, and the pull request's own run passes by
construction, so requiring the `validate` status check alone does not stop a
self-merge from landing. The backstop is branch protection on the instance's
default branch that requires the `validate` status check, requires pull
requests, and requires at least one approving review. `init` does not set
these; a repository admin does, once.

## Layout

| Path | What it is |
|---|---|
| `skills/jocasta/` | The Claude Code skill: `SKILL.md` (modes, config, snapshot, identity, voice) and `references/*.md` (one protocol per file, plus the schema and voice guides). |
| `scripts/` | `validate.py`, `consensus_merge.py`, `stale_sweep.py`, and `jocasta_common.py`. Python 3.11+ and PyYAML, nothing else. |
| `.github/actions/` | The three composite actions instances call at `@v1`. |
| `template/` | What `init` copies to create an instance: `jocasta.yaml`, `adoption.yaml`, `entries/README.md`, a README, and the three workflows. |
| `.claude-plugin/` | `plugin.json` and the single-plugin `marketplace.json`. |
| `tests/` | pytest suite; `uv run pytest -q` runs it. |

Development notes for working on this repo are in [CLAUDE.md](CLAUDE.md). What
the project is supposed to be, with its requirements, non-goals, invariants,
and decision log, is in [CHARTER.md](CHARTER.md).
