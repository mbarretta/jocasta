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
in the machinery repo at <https://github.com/mbarretta/jocasta>. Install it
once, then connect it to this registry:

```
/plugin marketplace add mbarretta/jocasta
/plugin install jocasta@jocasta
```

then, in any project, tell the skill which registry to use with
`jocasta connect <owner>/<repo>` naming this repository. The machinery repo's
README is the authoritative install guide if these commands change.

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
  and rejects entries that do not fit the schema, point at an unreachable
  source, lack an owner, reuse a name, or touch an entry the author does not
  own.
- `consensus-merge` merges a deprecation or ownership pull request when the
  entry's owner approves it, or when two people who are not the owner agree.
- `stale-sweep` checks every active entry's source weekly and opens a pull
  request proposing deprecation when a source has gone away. Fix the source and
  close the pull request to dismiss it.

The workflows run with the repository's own token, which can read only this
repository. If your tools live in private repositories, add a repository
secret named `JOCASTA_TOKEN` holding a token that can read them, so that
`validate` and `stale-sweep` can confirm each source is still there.

Nothing in this repository is deployed. If a workflow needs to change, the
change belongs in the machinery repo; this repo only pins the version.
