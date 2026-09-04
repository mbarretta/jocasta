---
charter_version: "1.0"
project: jocasta
created: 2026-09-04
last_amended: 2026-09-04
---

# jocasta — Project Charter

## North Star

Jocasta is the archive of a team's tools: describe what you need in your own words and
she tells you what already answers to it, who owns it, and whether it is still alive.
She is a GitHub repo and an agent skill, nothing more — the repo is the whole archive,
and the skill is how people submit, search, and retire entries without ever learning its
schema. Registering a tool must stay cheaper than mentioning it in Slack, because an
archive people skip becomes an archive that lies. And the archive is never confused with
the world: if a thing is not in the records, that is a fact about the records.

## Motivation

I have built this once before and it did not stick, but the problem did not go away:
people on the team build good tools, and nobody finds them at the moment they would
help. The sharing happens in channel scrollback that is gone in a week, so a tool is
discoverable only by whoever was reading that day. Duplicated effort is the visible cost
— two people building the same thing months apart, each certain nothing existed — but
the real problem is that "is there already something for this?" has no answerable form.

## Users & Use Cases

Primary user: an engineer on a team that builds its own tools, at the moment they have a
need — not the person maintaining the registry. Any team can run an instance; the first
one will be my SA team at ClickHouse.

- **U-1** (active): Describe a need in prose and learn whether a tool already exists, before writing any code.
- **U-2** (active): Register a tool in one guided pass, without reading a schema, and hear up front if it overlaps something already registered.
- **U-3** (active): Retire a tool honestly — because its owner walked away, or because two people who do not own it say it is dead.
- **U-4** (active): Stand up a registry for a team that has none, in one command, with nothing to deploy.

## Requirements

- **R-1** (active): Search takes a prose description of a need and returns ranked candidate tools — not a keyword match over names. [serves U-1]
- **R-2** (active): Registration is a single guided pass; the submitter never sees the schema and the skill writes valid metadata. [serves U-2]
- **R-3** (active): Every submission is evaluated for overlap against existing entries, and the overlap is reported to the submitter before anything is written. [serves U-1, U-2]
- **R-4** (active): An entry has exactly one owner, who can hand ownership to someone else or release it. [serves U-3]
- **R-5** (active): Deprecation has three routes — the owner's call, two non-owners' consensus, or a stale-source flag — and deprecated entries stay searchable and clearly marked. [serves U-3]
- **R-6** (active): Submissions are mechanically validated before they land: schema, reachable source, owner present, name unused. [serves U-2]
- **R-7** (active): The registry records adoption signal, and search may rank on it rather than on description match alone. [serves U-1]
- **R-8** (active): The skill speaks as Jocasta Nu, archivist of the collection — precise, proprietary, unimpressed by disorder — and never says a tool does not exist, only that it does not appear in the archive. Clarity outranks voice. [serves U-1, U-2]
- **R-9** (active): A team creates its own registry from the public template in one command, public or private. [serves U-4]

## Non-Goals

- **N-1** (active): No server, database, or hosted service — the GitHub repo is the entire backend. If it cannot be done with git and the GitHub API, it does not happen.
- **N-2** (active): No web UI, dashboard, or generated catalog site. The interfaces are the skill and the repo itself.
- **N-3** (active): No hosting, mirroring, vendoring, building, or running of registered tools. Metadata only.
- **N-4** (active): No entries for things that are not locally runnable — no hosted services, SaaS products, or documentation links (boundary defined by D-4).
- **N-5** (active): No identity or permission system of its own. GitHub accounts are the identity; GitHub permissions are the authorization.
- **N-6** (active): No single org's assumptions in the public machinery — the reusable half never learns anything about ClickHouse.
- **N-7** (active): No consumer's schema in the archive. Entries describe the tool; anything a consumer needs that the tool itself does not have is that consumer's problem (boundary defined by D-6).

## Invariants

- **P-1** (active): A wrong registry is worse than no registry. Anything that makes entries cheaper to add than to keep honest is a mistake.
- **P-2** (active): Registering stays cheaper than mentioning the tool in Slack. A required field that is not load-bearing is a bug.
- **P-3** (active): The repo is the API — human-readable files a person can grep, hand-edit, and review as a diff. Every behavior must survive that.
- **P-4** (active): Model judgment advises; mechanism gates. Search and overlap evaluation are the model's job; validation, permissions, and merges are deterministic.
- **P-5** (active): Contested changes leave a reviewable artifact. Touching an entry you do not own is never silent.
- **P-6** (active): The registry describes tools; it never owns them. Authority over a tool stays in the tool's own repo.

## Decision Log

### D-1 — Machinery public, registry instances per-org (2026-09-04, active)
- **Decision:** The public repo ships the skill, the schema, the validators, and a repo template; each team runs an init command to create its own registry repo.
- **Rejected:** One repo holding both skill and live data (a public artifact cannot carry a private org's tool inventory, and "anyone can run one" would degrade to forking); publishing only a documented schema (all the setup friction, nothing enforcing the shape).
- **Tradeoff accepted:** Two repos to keep in step, and a schema-version skew problem the first time an instance lags the machinery.
- **Affects:** R-9, N-6, U-4.

### D-2 — The GitHub repo is the entire backend (2026-09-04, active)
- **Decision:** All state — entries, owners, deprecation votes, adoption signal — lives in human-readable files in a git repo, read and written through git and the GitHub API.
- **Rejected:** A hosted service with a database (a service nobody runs is a registry nobody trusts; the ops cost dwarfs the problem); a local filesystem registry (defeats sharing, which is the entire point).
- **Tradeoff accepted:** Search runs over a fetched snapshot instead of an index, so it costs a fetch and will not scale to thousands of entries; concurrent writes are git's problem, which means occasional conflicts.
- **Affects:** R-1, P-3, N-1.

### D-3 — Direct commit for your own entries, PR for contested ones (2026-09-04, active)
- **Decision:** Registering a tool or editing one you own commits to the default branch. Anything touching an entry you do not own — a deprecation vote, an ownership claim — opens a PR, and GitHub approvals carry the two-non-owner consensus.
- **Rejected:** A PR for everything (review friction on your own metadata breaks P-2's cost ceiling); a direct commit for everything (nothing contested is reviewable, and consensus deprecation has nowhere to live).
- **Tradeoff accepted:** Two write paths to build and explain, and a poor-but-uncontested entry can land unreviewed.
- **Affects:** R-2, R-5, R-6, P-5.

### D-4 — Locally runnable tools only (2026-09-04, active)
- **Decision:** An entry must be something a person can run on their own machine — an executable, a script, or an agent skill.
- **Rejected:** Cataloging anything useful (the registry becomes a bookmark list and "can I run this?" stops being answerable); executables only (excludes agent skills, which is where much of the team's new work is).
- **Tradeoff accepted:** Genuinely useful internal tools that happen to be web apps have no home here.
- **Affects:** N-4.

### D-5 — Exactly one owner per entry, handed off rather than shared (2026-09-04, active)
- **Decision:** One name owns an entry. On a multi-person project someone raises their hand; when they are done or they leave, they hand it to a named successor or release it.
- **Rejected:** An owner list (quorum questions everywhere — whose call deprecates a tool, how many owners must approve a transfer — for a problem "raise your hand" already solves); no ownership at all (deprecation and staleness stop being answerable, which is half the point of the archive).
- **Tradeoff accepted:** A genuinely shared tool has one accountable name that may be the wrong one, and an owner who leaves without handing off makes a live tool look abandoned.
- **Affects:** R-4, R-5.

### D-6 — Consumers adapt to the archive, not the reverse (2026-09-04, active)
- **Decision:** The entry schema is designed for the discovery question and nothing else. forge — the first consumer — adapts to what the archive records; the archive never adds a field because forge wants it.
- **Rejected:** Adopting forge's registry entry shape (the archive would then serve one consumer, and every other consumer would inherit forge's vocabulary); emitting a forge-specific view alongside the canonical entries (two schemas to keep honest, and the second one wins the moment they disagree).
- **Tradeoff accepted:** forge integration is more work on forge's side, and it is not in v1; until then a found tool must be installed by hand.
- **Affects:** N-7, R-1.

### D-7 — The Jocasta Nu voice is load-bearing, not decoration (2026-09-04, active)
- **Decision:** The skill's prompt gives it the register of the Jedi Archives librarian, including her one hard rule inverted: never "it does not exist," only "it does not appear in the archive."
- **Rejected:** A neutral tool voice (nothing to make people want to consult it, and the archive/world distinction has no natural home); the character without the correction (her canonical line is exactly the failure this project must not earn).
- **Tradeoff accepted:** A voice with attitude can add friction to the one interaction that must stay frictionless (P-2). Clarity wins every conflict — the voice is never allowed to obscure what she did to the repo.
- **Affects:** R-8, P-2.

## Open Tensions

- **T-1** (open): R-1's search quality against D-2's no-index constraint. Prose search over a fetched snapshot is fine at team scale and breaks at org scale. Revisit past roughly 200 entries, or when a search stops feeling instant.
- **T-2** (open): R-7's adoption signal is telemetry, recorded in a repo everyone can read, about an archive whose selling point is honesty. What gets recorded, by whom, and whether it is per-person or aggregate is unresolved.
- **T-3** (open): N-6 versus reality — every real requirement will arrive from the ClickHouse instance, and the pull to encode its habits in the public machinery is constant.

## Revision History

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-04 | Founded (greenfield init). |
