# Ownership and deprecation: deprecate, transfer, release, claim

An entry has exactly one owner, named in its `owner` field (charter R-4, D-5). The owner can hand the entry to a named successor (`transfer`), give it up (`release`), or retire it (`deprecate`). Anyone else who wants to retire an entry or take it over goes through a pull request that the instance's `consensus-merge` workflow merges when it has the votes (charter R-5, D-3, P-5). How each change reaches the repo (direct commit or PR, branch names, labels, the retry recipe) is in `references/write-paths.md`; this file is the protocol for the four modes and the rules the merge script applies.

Deprecation has three routes, recorded in the entry's `deprecated.route` field: `owner` (the owner's call), `consensus` (two non-owners agreed), and `stale-source` (the weekly sweep found the source unreachable; opened by the machinery, decided by people). A deprecated entry stays in the archive, stays searchable, and is clearly marked; nothing here ever deletes a file.

## Before any of the four modes

1. Refresh the snapshot and resolve the caller's `<login>` (SKILL.md: Snapshot, Identity).
2. Read `entries/<name>.md` from the snapshot. If there is no such file, stop with the archive wording: "`<name>` does not appear in the archive." Offer `search` if the user may have the name wrong.
3. Note the entry's `owner`. `owner: ~` means the entry is **unowned** (released); say "unowned", never "orphaned" or "abandoned".
4. Decide whether the caller is the owner: `owner == <login>`, exact match. This one comparison chooses the row in the write-paths table. The comparison is the skill's convenience; the push authorization check and the consensus script make the same comparison server-side, so a mistake here is refused, not landed.

Every closing message opens with the plain statement of what was committed (path, commit SHA, repo) or which PR was opened (URL), before any character text (charter R-8). Templates are at the end of this file.

## `deprecate <name>`

Marks a tool retired. The entry keeps its name, owner, source, body, and adopters; only `status` and the `deprecated` block change.

1. If the entry is already `status: deprecated`, nothing is written. Report its route and date: "`<name>` was retired on `<date>` (route: `<route>`)." Stop.
2. Ask for the reason in one question, and accept "none": "Why is `<name>` being retired? One line, or say none." If the answer names a replacement tool, check the replacement appears in the archive and mention it in the note by its entry name.
3. Edit the frontmatter:

   ```yaml
   status: deprecated
   deprecated:
     route: owner          # or consensus, below
     date: 2026-09-04      # today, YYYY-MM-DD
     note: Superseded by example-cli, which handles nested directories.
   ```

   Omit `note` entirely when the user gave none; an empty note fails validation. Do not rewrite the body. If the reason names a replacement, append one sentence to the body naming it (for example "Deprecated in favor of `example-cli`."), so search can route people to it.

4. **Caller is the owner:** `route: owner`. Direct commit with message `deprecate <name>`, following the direct-commit recipe in `write-paths.md`.

5. **Caller is not the owner** (including when the entry is unowned): `route: consensus`, `date` is today, the day the retirement is proposed. Follow the PR recipe in `write-paths.md`: branch `jocasta/deprecate-<name>-<login>`, label `deprecation`, body "Why:" from step 2. Then tell the user, in plain words, how the PR is decided: it merges when `<owner>` approves it, or when one more person who is not `<owner>` approves it (the author is the first of the two voices). For an unowned entry only the second path applies, and you say so.

Adopters are not touched. People who recorded that they use the tool still do; the archive now shows them a retired tool, which is the point.

## `transfer <name> <login>`

Hands the entry to a named successor. Owner only, direct commit.

1. **Caller is not the owner:** nothing is written. Say who owns it and name the two commands that would get the caller what they want (`claim <name>` for themselves; asking `<owner>` to run `transfer`). `references/voice.md`, example 4, is the shape.
2. **Entry is unowned:** nothing is written; `transfer` moves ownership from someone, and there is no one to move it from. Point at `claim <name>`.
3. **`<login>` is the current owner:** nothing to do; say so.
4. Confirm the successor is a real GitHub account: `gh api users/<login> --jq .login`. A 404 stops the mode: "`<login>` is not a GitHub login I can find." Do not guess a correction.
5. Edit `owner: <login>`. Nothing else changes, including `status` (a deprecated entry can be handed on; someone still answers for the record).
6. Direct commit with message `transfer <name> to <login>`.

The successor is not asked. Ownership in the archive is one accountable name, and the outgoing owner is the one accountable for choosing it. If the successor does not want it, `release <name>` is one command away.

## `release <name>`

Gives up ownership without retiring the tool. Owner only, direct commit.

1. **Caller is not the owner:** nothing is written; say who owns it.
2. **Entry is already unowned:** nothing is written; say it is unowned and that `claim <name>` takes it.
3. Edit `owner: ~`. `status` stays exactly as it was; a released entry is still active if it was active, and search shows it as unowned (charter R-4; the "Ownership states" section of `references/schema.md`).
4. Direct commit with message `release <name>`.

Tell the user what the archive now says: the tool is listed, unowned, and anyone may claim it; if nobody does and its source goes dark, the stale sweep will propose retiring it. A release is not a deprecation, and the response must not imply the tool is gone.

## `claim <name>`

Asks to become the owner. Always a PR labeled `ownership`, because the caller is by definition not the owner.

1. **Caller is already the owner:** nothing to do; say so.
2. **Entry is unowned** (the usual case): proceed. **Entry has an owner:** proceed, but say plainly that `<owner>` currently owns it and that the PR will merge on `<owner>`'s approval or on one more non-owner's approval; a contested claim is allowed and is exactly what the PR is for.
3. Ask the reason in one question: "Why should the archive list you as `<name>`'s owner? One line." Something like "I maintain it now" is enough; the body needs a sentence, not a case.
4. Edit `owner: <login>`. Nothing else changes.
5. Follow the PR recipe in `write-paths.md`: branch `jocasta/claim-<name>-<login>`, label `ownership`, body "Why:" from step 3, title `claim <name>`.

When the PR merges, the caller is the owner and every owner-only mode is theirs.

## How the consensus action decides

`scripts/consensus_merge.py` runs on every PR event in the instance. It is the only thing that merges a `deprecation` or `ownership` PR; the skill never merges, never approves, and never closes one. The rules, in order:

1. **Already merged or closed:** nothing happens. The script never closes, reopens, or comments on a closed PR.
2. **Exactly one `entries/<name>.md`:** a PR that changes any other set of files (two files, `adoption.yaml`, `entries/README.md`, a deleted or renamed entry) gets one comment explaining why and is not merged. Fix it by splitting the change; the PR stays open.
3. **Owner from the default branch:** the script reads the entry as it is on the default branch, not as the PR would make it (otherwise a claim could approve itself). `owner: ~` or a file not yet on the default branch means **no owner**.
4. **Latest review per person:** each reviewer's most recent review is the one that counts. An approval that was later dismissed or followed by "request changes" is gone. Reviews from `[bot]` accounts are ignored.
5. **Owner approved:** merge, route `owner`.
6. **Owner requested changes:** not merged, one comment. Two non-owner approvals do not override the owner; the PR stays open for discussion until the owner approves or someone closes it by hand.
7. **Two non-owner voices:** the PR author (when they are not the owner) is one voice; every other reviewer who is neither the owner nor the author and whose latest review is an approval is another. Two or more: merge, route `consensus`. An unowned entry can only merge this way.
8. **Otherwise:** wait. The workflow log says how many voices are still needed; the next review re-runs the script.

Merges are squash commits with the subject `<verb> <name> (route: <route>)`, where `<verb>` is `deprecate` for a `deprecation` label and `claim` for `ownership`. Re-running the script on the same PR is always safe; it comments at most once per situation (wrong file set, unreadable owner, owner requested changes), so a PR that is fixed and then blocked for a new reason still hears why.

Worked outcomes, for an entry owned by `alice`:

| PR author | Approvals (latest state) | Result |
|---|---|---|
| `bob` | none | waits: 1 of 2 non-owner voices |
| `bob` | `carol` | merged, route `consensus` (`bob` + `carol`) |
| `bob` | `alice` | merged, route `owner` |
| `alice` | `bob` | waits: the owner-author is not a voice; 1 of 2 |
| `alice` | `bob`, `carol` | merged, route `consensus` |
| `bob` | `carol`, `dave`; `alice` requested changes | not merged; one comment |
| `bob` | `carol` approved, then dismissed | waits: 1 of 2 |

For an unowned entry (`owner: ~`) the first two rows are the whole table: there is no owner to approve or to block, so two voices are needed and enough (charter R-5 "two non-owners' consensus").

## Closing messages

Plain statement first, exactly what happened to the repo, then at most one sentence of register. Fill in real values; never paraphrase a path, SHA, or URL.

**Owner deprecated (direct commit):**

> Committed `entries/<name>.md` to `<default>` of `<org>/<repo>` (`<sha>`): `status: deprecated`, route `owner`, date `<date>`.
>
> Retired by its owner. It stays in the archive, marked, so nobody rebuilds it by accident.

**Non-owner deprecation (PR):**

> Opened `<pr-url>` (branch `jocasta/deprecate-<name>-<login>`, label `deprecation`) proposing `status: deprecated`, route `consensus`. Nothing on `<default>` has changed.
>
> It merges when `<owner>` approves, or when one more person who is not `<owner>` approves; you are the first voice.

For an unowned entry, the second paragraph is: "It merges when one more person approves; you are the first of two voices."

**Transfer (direct commit):**

> Committed `entries/<name>.md` to `<default>` of `<org>/<repo>` (`<sha>`): owner `<old-login>` -> `<new-login>`.
>
> The archive now lists `<new-login>` against it.

**Release (direct commit):**

> Committed `entries/<name>.md` to `<default>` of `<org>/<repo>` (`<sha>`): owner `<login>` -> `~`. The entry is active and unowned.
>
> Anyone may `claim <name>`; until someone does, search shows it as unowned.

**Claim (PR):**

> Opened `<pr-url>` (branch `jocasta/claim-<name>-<login>`, label `ownership`) proposing owner `<login>`. Nothing on `<default>` has changed.
>
> It merges when `<owner>` approves, or when one more person approves. (For an unowned entry: "It merges when one more person approves; you are the first of two voices.")

**Refusal (owner-only mode, caller is not the owner):**

> Nothing written. `<name>` is owned by `<owner>`; only the owner can `<mode>` it.
>
> `claim <name>` opens a PR asking for ownership; `deprecate <name>` opens a PR to retire it. Either is decided by `<owner>` or by two people who are not `<owner>`.

**Nothing to do (already deprecated, already unowned, already the owner):**

> Nothing written. `<name>` <is already retired (route `<route>`, `<date>`) | is already unowned | is already yours>.

**Unknown name:**

> Nothing written. `<name>` does not appear in the archive.
>
> `search <what it does>` finds entries by what they do, not by name.
