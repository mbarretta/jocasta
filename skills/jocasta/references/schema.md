# Registry schema

This file is the schema. `scripts/validate.py` enforces exactly what is written
here and nothing else: a frontmatter key that does not appear below is an
error, and no field is ever added to serve a downstream consumer (charter N-7,
D-6). Every required field carries a one-line reason it is load-bearing,
because a required field that is not load-bearing is a bug (charter P-2).

A registry instance is a git repository with three kinds of file:

```
jocasta.yaml          registry-level config: schema version, team, machinery ref
adoption.yaml         who uses what: tool name -> list of GitHub logins
entries/<name>.md     one file per tool: YAML frontmatter plus a prose body
entries/README.md     reserved; not an entry, ignored by the validator
```

## Entry files: `entries/<name>.md`

One Markdown file per tool. The frontmatter is the mechanical part the
validator checks; the body is prose the skill reads when it searches.

```markdown
---
name: example-cli
owner: alice
source: https://github.com/example-org/example-cli
kind: cli
install: brew install example-org/tap/example-cli
registered: 2026-09-01
status: active
---
Lists the files in a directory tree that changed since a given git ref and
groups them by the top-level directory they live in.

Reach for it when you want to know which parts of a large repo a branch
touched without reading the whole diff. It is not a diff viewer.
```

### Frontmatter fields

| Key | Required | Type | Rule | Why it is load-bearing |
|---|---|---|---|---|
| `name` | yes | string | Equals the filename stem; kebab-case (`[a-z0-9]` words joined by single hyphens); unique across `entries/`. | It is the identity every other file refers to: `adoption.yaml` keys, PR titles, the `show <name>` mode, and the filename itself. Uniqueness is what makes "name unused" checkable (R-6). |
| `owner` | yes | GitHub login, or `~` | A single login (GitHub's rules: alphanumerics and single hyphens, no leading or trailing hyphen, at most 39 characters). `~` (YAML null) means the entry has been released. | One accountable name is what makes deprecation, transfer, and staleness answerable (R-4, D-5), and it is what the direct-commit authorization check compares against. |
| `source` | yes | http(s) URL | Must be reachable: github.com URLs are checked with `gh api repos/{owner}/{repo}` (so private repos the caller can see count); other URLs get an HTTP HEAD, falling back to GET. Skipped under `--offline`. | The archive describes tools it never owns (P-6); the source is the only pointer to the real thing, and a dead source is exactly what the stale-source route exists to catch (R-5, R-6). |
| `kind` | yes | enum: `cli`, `script`, `skill` | One of the three values. | This is the D-4 boundary made mechanical: an entry must be something a person can run locally, and the enum refuses anything else (N-4). |
| `install` | no | string | When present, a non-empty one-line command. | Optional on purpose: a found tool is installed by hand in v1 (D-6), so this is a convenience for the reader, not a contract. |
| `registered` | yes | ISO date `YYYY-MM-DD` | A calendar date, not a timestamp. | Lets a reader tell a recent entry from an old one at a glance and gives the stale sweep and any later report a fixed anchor without reading git history. |
| `status` | yes | enum: `active`, `deprecated` | One of the two values. | Deprecated entries stay in the archive and stay searchable (R-5); this flag is how they are clearly marked instead of deleted. |
| `deprecated` | iff `status: deprecated` | mapping | Present when and only when `status` is `deprecated`. Keys: `route` (required, enum: `owner`, `consensus`, `stale-source`), `date` (required, ISO date), `note` (optional, non-empty string). | Records which of the three routes retired the tool and when (R-5), so the archive can say why something is deprecated rather than only that it is. |

Anything else in the frontmatter fails validation with `unknown-key`.

### Body

The body is everything after the closing `---`. At least one non-empty
paragraph is required. Write it in the words someone with the need would use:
first what the tool does, then when you would reach for it and what it is not.
Search reads the body, not just the name (R-1), so an empty body is an entry
nobody will find.

### Ownership states

- A new entry must name an owner. The skill defaults it to the caller's GitHub
  login.
- `owner: ~` is legal only on an existing entry after its owner has released
  it. The schema check accepts `~` wherever it appears; the rule that a release
  must be performed by the previous owner is enforced by the push authorization
  check (`--changed-only`, below), not by the schema.
- A released entry stays `status: active` and search shows it as unowned.
  Anyone may claim it.

## `jocasta.yaml`

```yaml
schema_version: 1
team: example-team
machinery_ref: v1
```

| Key | Rule | Why |
|---|---|---|
| `schema_version` | Must equal the `SCHEMA_VERSION` constant in `scripts/validate.py` (currently `1`). A mismatch is an error naming both versions. | This is how D-1's version-skew tradeoff is made loud instead of silent: an instance that lags the machinery is refused, not misread. |
| `team` | Free text; a name for the registry. | Informational only: it tells a reader whose registry this is. The validator does not check it. |
| `machinery_ref` | The tag of this machinery repo the instance workflows pin (`@v1`). | Lets a reader see at a glance which machinery version the instance is on. |

A missing or unreadable `jocasta.yaml` fails with `config`; an `adoption.yaml` that is not a mapping fails with `adoption`.

## `adoption.yaml`

```yaml
example-cli: [alice, bob]
legacy-script: [carol]
```

A mapping from tool name to a list of GitHub logins who use the tool. An empty
file or `{}` means nobody has recorded adoption yet.

| Rule | Why |
|---|---|
| Every key names an existing entry in `entries/`. | Adoption of a tool that does not appear in the archive is noise search would rank on (R-7). |
| Every value is a list of non-empty strings, each login listed once (compared case-insensitively). | Search counts adopters; a scalar, an empty login, or a repeated one would make the count wrong. |

Push authorization (`--changed-only`, below) restricts a direct commit to
adding or removing the actor's own login.

## Validator output

`scripts/validate.py --root DIR [--offline] [--changed-only REF --actor LOGIN]`
exits 0 when the registry is clean and 1 when any rule fails, printing one
plain line per failure:

```
entries/<file>.md: <rule>: <detail>
adoption.yaml: adoption: <detail>
jocasta.yaml: <config|schema-version>: <detail>
```

Rule names: `frontmatter`, `unknown-key`, `name`, `owner`, `source`, `kind`,
`install`, `registered`, `status`, `deprecated`, `body`, `adoption`, `config`,
`schema-version`, and `authorization` (below). The skill shows these lines to
the submitter verbatim when a write fails; it never bypasses them (P-4).

## Push authorization: `--changed-only REF --actor LOGIN`

The schema rules say whether the registry is well formed. The `authorization`
rule, run by the instance's `validate` workflow on every push to the default
branch, says whether that push was the actor's to make directly (charter D-3,
P-4). It diffs `REF...HEAD` inside `--root` and reads both sides from git.
Logins are compared case-insensitively, as GitHub treats them.

| Change | Allowed when |
|---|---|
| `entries/<name>.md` added | Its `owner` is the actor. |
| `entries/<name>.md` modified | Its `owner` at `REF` was the actor. This is what makes transfer and release the previous owner's call, and what keeps a claim of an unowned (`~`) entry on the PR path. |
| `entries/<name>.md` deleted | Never. Entries are deprecated, not deleted. |
| `adoption.yaml` | Under every tool key, the only login that appears or disappears between `REF` and `HEAD` is the actor's own. Adding a key that holds only the actor's login is fine; so is removing one. |
| anything else | Not the validator's concern; repository permissions govern those files. |

A violation prints `<file>: authorization: <detail>; open a PR instead`. When
`REF` is the all-zeros SHA of a first push or is not a commit in the checkout,
every registry file is treated as added and the same rules apply. The check is
skipped, with a printed notice, when the actor is `github-actions[bot]` or
`HEAD` is a merge commit: both are the shape a pull request merge takes, which
review and the consensus action already gated. The skip tests shape, not
provenance, and the workflow runs after the push has landed; `references/adoption.md`
describes what the workflow passes as `REF`, where the rule's reach ends, and
the branch protection that backstops it.
