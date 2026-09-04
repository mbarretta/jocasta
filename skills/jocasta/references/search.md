# search and show

The two read-only modes. Neither writes to the snapshot or the instance; there is nothing to validate, commit, or push, and no plain statement of a change to lead with, so the response opens with the result.

Both modes start the same way. Resolve the registry (SKILL.md, Config discovery), then refresh the snapshot:

```
git -C ~/.cache/jocasta/<org>/<repo> pull --ff-only
```

If the pull fails, stop and report it as SKILL.md's Snapshot section says; do not search a snapshot you could not refresh, because a stale answer about ownership or status is the one thing the archive must not give (charter P-1).

## search `<need in prose>`

Search takes a need in the words the person actually used and returns ranked candidates from the archive. It is judgment over prose, not a lookup (charter R-1, D-2). The steps, in order:

1. **Read everything.** Open every `entries/*.md` in the snapshot except `entries/README.md`, and open `adoption.yaml`. There is no index and no shortlist step; the whole archive is the input. If an entry's frontmatter does not parse, keep going with the rest and say at the end which file you could not read.

2. **Judge fit, entry by entry.** For each entry, read the prose body first and the frontmatter second, and decide how well the tool answers the stated need. Fit is a judgment about what the tool does and when someone would reach for it, drawn from the body's own description of what it is and what it is not. `kind` and `install` are supporting context; the `name` is the weakest signal of all. **Never keyword-match names alone.** A tool called `pq-diff` may not diff parquet, and the tool that does may be called `table-compare`; only the body can tell you. A need phrased in different vocabulary from the body still fits if the described behavior matches. Discard entries with no real fit; "shares a word with the question" is not fit.

3. **Rank the survivors** by, in this order:
   1. **Fit**, as judged in step 2. This dominates: a well-fitting tool nobody has adopted outranks a poorly-fitting tool everyone uses.
   2. **Adopter count**, the number of logins listed under the entry's name in `adoption.yaml` (zero when the name is absent from the file). Adoption is the archive's only usage signal (charter R-7), and it breaks ties in fit; it never overrides fit.
   3. **Status**, active above deprecated. A deprecated entry is still a candidate and still appears (charter R-5); it just sorts below an equally fitting active one, and it is marked so the reader can see why.

4. **Present the candidates** in rank order using the output template below. Show every entry with real fit, usually one to five. Do not pad the list with weak matches to look thorough, and do not truncate a genuinely close second to look decisive. When nothing survives step 2, use the empty-result wording.

What search never does: it never asserts that a tool with the needed behavior is absent from the world, only from the records; it never ranks on the caller's own adoption, on the owner's identity, or on `registered` date; and it never invents a summary a body does not support.

## Output template

One block per candidate, in rank order. Every line comes from the entry or from `adoption.yaml`; nothing is paraphrased into character.

```
1. `<name>` — <one line: what the tool does, taken from the first sentence of the body>
   owner: `<login>`                       (or: owner: unowned)
   status: active                         (or: status: deprecated — retired by its owner on <date>: <note>)
   adopters: <N>
   source: <source URL>
   install: `<install line>`              (omit this line when the entry has no install field)
```

Rules for each line:

- **name**: the frontmatter `name`, in backticks. It is also the argument to `show`, `adopt`, and every other mode, so it is quoted exactly.
- **what**: one line, drawn from the body, in the body's words trimmed to a sentence. Not the name restated, not your guess at the purpose.
- **owner**: the `owner` login. When the frontmatter has `owner: ~`, write `unowned` (never "orphaned" or "abandoned"; the entry is active and anyone may `claim` it).
- **status**: `active`, or `deprecated` followed by the route in words and the date from the `deprecated` block: `retired by its owner on <date>`, `retired by consensus on <date>`, or `retired because its source no longer answers, on <date>`. Append the `note` after a colon when there is one. A deprecated entry is never dropped from the list and never shown without this marking (charter R-5); the reader must be able to see at a glance that it is retired and why.
- **adopters**: the count of logins under the name in `adoption.yaml`; `0` when the name is not there.
- **source**: the `source` URL verbatim.
- **install**: the `install` line in backticks, only when present. In v1 the user runs it by hand; the archive never runs anything (charter N-3, D-6).

After the list, at most one sentence of register (references/voice.md). If an entry could not be read in step 1, name the file here in one plain sentence.

Worked example, against the need "which parts of the repo did this branch touch":

```
1. `example-cli` — Lists the files in a directory tree that changed since a given git ref and groups them by top-level directory.
   owner: `alice`
   status: active
   adopters: 2
   source: https://github.com/example-org/example-cli
   install: `brew install example-org/tap/example-cli`

2. `legacy-script` — Prints the top-level directories a branch touched, one per line.
   owner: `bob`
   status: deprecated — retired by its owner on 2026-08-15: Superseded by example-cli, which handles nested directories.
   adopters: 1
   source: https://github.com/example-org/legacy-script
```

Both fit. `example-cli` ranks first on fit and adopters, and `legacy-script` stays in the list, marked, because a reader who already has it installed deserves to learn from the archive that it was retired and what replaced it.

## Empty result

When no entry survives step 2, the response opens with this sentence, verbatim:

> What you describe does not appear in the archive.

Then, when there is a nearest miss worth naming, one line for it in the output-template shape with a short clause on why it fell short; then the standing invitation:

> If you build one, `register` it and the next person who asks will find it here.

The full response for a need with no near miss is therefore two lines. The full response with one near miss is the sentence, the candidate block, and the invitation. Nothing more.

The wording is deliberate. The phrase "does not exist" is forbidden in every mode (SKILL.md, Voice; charter R-8, D-7); the archive knows its records and nothing else, and an empty search means the records are silent, not that the world is. Do not soften it into "I couldn't find" (which implies the search failed) or harden it into "there is no tool for" (which claims knowledge of the world).

## `show <name>`

Prints one entry in full and who has adopted it. After the snapshot refresh:

1. Look for `entries/<name>.md`. Match the name exactly; names are kebab-case and case-sensitive.
2. If the file is present, print, in this order:
   - the frontmatter, as a fenced `yaml` block, byte for byte as written in the file (including `owner: ~` for a released entry and the whole `deprecated` block when there is one);
   - the body, as written;
   - the adopters: the list of logins under `<name>` in `adoption.yaml`, one per line, or the line `adopters: none recorded` when the name is absent from the file.

   Then at most one sentence of register. The frontmatter is shown raw on purpose: `show` is the one mode where a reader wants the record itself rather than a rendering of it.
3. If the file is absent, the response opens with:

   > `<name>` does not appear in the archive.

   Then, when the archive holds a name that differs only by case, hyphenation, or an obvious typo, offer it: "Did you mean `<other-name>`?" Otherwise suggest `search` with the need in prose; the person may know the tool by a name the archive does not.

`show` does not validate, does not summarize, and does not rank. It reads two files and prints them.

## Scale: a fetch, not an index (charter D-2, T-1)

Search is a fetch, not an index. Every search reads every entry in a shallow clone that was just pulled; there is no search index, no embedding store, and no service to keep warm, because the repo is the entire backend (charter D-2). The accepted cost is that the model reads the whole archive on every question, which is instant at team scale and stops being instant somewhere around a few hundred entries. The charter records this as open tension T-1 and puts the threshold at roughly 200 entries.

So, on every search, count the files you read in step 1. When the count exceeds roughly 200, warn the user in one plain sentence after the results, once per session:

> This archive has <N> entries; search reads all of them on every question, and past roughly 200 that stops being instant. The charter (T-1) says to revisit the design at this point.

The warning is information, not a refusal: still answer the question. Do not build a local index, cache summaries between sessions, or skip entries to compensate; those are the design change T-1 exists to decide deliberately, not something the skill improvises.
