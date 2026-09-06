# Tool registry

This repository is the archive of this team's tools. Every file under
`entries/` describes one thing a person can run on their own machine: a
command-line tool, a script, or an agent skill. Each entry names the tool, who
owns it, where its source lives, and whether it is still active, followed by a
prose description written so that someone with a need, not a name, can find
it. `adoption.yaml` records who uses what. There is nothing else: no server,
no site, no database. The repo is the registry, and it is read and written
through the jocasta skill and ordinary git.

## Search before you build

Before writing a new tool, ask the archive whether one already answers to your
need. Describe the need in your own words; the skill ranks what is registered
by fit, adoption, and status, and tells you plainly when nothing appears in the
archive. A tool that exists but is not registered is invisible here, which is
why registering must stay cheap and why you should register what you build.

## Install the skill

The registry is used through the `jocasta` plugin for Claude Code, which lives
in the machinery repo at <https://github.com/mbarretta/jocasta>. That repo is
its own plugin marketplace, so install it once, inside Claude Code:

```
/plugin marketplace add mbarretta/jocasta
/plugin install jocasta@jocasta
```

(or `claude plugin marketplace add mbarretta/jocasta` and
`claude plugin install jocasta@jocasta` from a shell). Then point the skill at
this registry with `jocasta connect <owner>/<repo>`, naming this repository.
The machinery repo's README is the authoritative install guide if these
commands change.

From there, speak to the skill in prose:

- "is there a tool for ..." searches the archive.
- "register a tool" walks you through adding one; you are never shown the
  schema, and you hear about overlapping entries before anything is written.
- "deprecate ...", "transfer ...", "release ..." and "claim ..." manage
  ownership and retirement.
- "adopt ..." records that you use a tool, which helps search rank it.

## How the archive stays honest

Three thin workflows under `.github/workflows/` call the machinery's actions at
a pinned release (`machinery_ref` in `jocasta.yaml`):

- `validate` runs on every push to the default branch and every pull request
  and turns the run red for any entry that does not fit the schema, points at
  an unreachable source, lacks an owner, or reuses a name, and for any direct
  push that touches an entry the pusher does not own or another person's line
  in `adoption.yaml`. It runs after the push has landed, so a red run is a
  signal to revert, not a wall; see the note on branch protection below.
- `consensus-merge` merges a deprecation or ownership pull request when the
  entry's owner approves it, or when two people who are not the owner agree.
  It only ever merges a pull request that changes exactly one
  `entries/<name>.md`; anything else gets one explanatory comment and stays
  open.
- `stale-sweep` checks every active entry's source weekly and opens a pull
  request proposing deprecation when a source has gone away. Fix the source and
  close the pull request to dismiss it.

The workflows run with the repository's own token, which can read only this
repository and cannot trigger other workflows. Two consequences, both fixed by
one secret: if your tools live in private repositories, `validate` and
`stale-sweep` cannot confirm their sources are still there; and a pull request
opened by `stale-sweep` does not start `consensus-merge` until a person reviews
it, labels it, or pushes to its branch. Add a repository secret named
`JOCASTA_TOKEN` holding a personal access token or GitHub App token that can
read those repositories, and both workflows use it instead.

One more thing the sweep needs: the repository setting "Allow GitHub Actions to
create and approve pull requests" (Settings, Actions, General). Without it,
`stale-sweep` pushes its proposal branch and then cannot open the pull request
for it. `init` turns the setting on when it creates the registry; if that was
refused, an admin can turn it on by hand, or the same `JOCASTA_TOKEN` secret
covers it.

Branch protection is not set up for you. `validate` cannot undo a push it
flags, and a pull request's own run is skipped (the pull request path is gated
by review and `consensus-merge` instead), so someone with push access could
open a pull request that edits another person's entry and merge it themselves;
the merge turns the next `validate` run red, after it has landed. To make a red
check block the default branch, enable branch protection requiring the
`validate` status check; to close the self-merge path, it must also require
pull requests and at least one approving review.

Nothing in this repository is deployed. If a workflow needs to change, the
change belongs in the machinery repo; this repo only pins the version.
