# register

One guided pass that turns a source URL into a catalogued entry. The submitter gives a URL, confirms a description in their own words, and answers at most three short questions; the skill writes `entries/<name>.md` exactly as `references/schema.md` specifies, reports overlap before anything is written, runs the validator, and commits directly to the instance's default branch (charter R-2, R-3, R-6, D-3). The model drafts and judges; the validator and the instance's push check decide whether the entry lands (P-4). Registering must stay cheaper than mentioning the tool in Slack (P-2): every question below exists because `schema.md` requires the answer, and nothing is asked that the skill can find out for itself.

Preconditions are the ones SKILL.md sets for every mode: `gh auth status` succeeds, the caller's login is known (`gh api user --jq .login`), the registry is resolved, and the snapshot at `~/.cache/jocasta/<org>/<repo>` has just been refreshed with `git pull --ff-only`. If any of those fail, stop there; `register` never runs against a stale or unauthenticated snapshot.

## What the archive admits

Before drafting anything, decide whether the thing can be catalogued at all. The archive records tools a person can run on their own machine: an **executable**, a **script**, or an **agent skill**. That is the D-4 boundary, and `kind`'s three-value enum is the same boundary made mechanical (N-4). A hosted service, a SaaS product, a web app, a dashboard, a documentation page, or a link to a wiki is refused, however useful it is.

The README usually settles it. When it does not, ask one plain question: "Is this something you run on your own machine, or something you visit?" Do not register on a guess.

Refuse with nothing written, and say what the archive holds instead of pronouncing on the thing itself:

> Nothing written. The archive catalogues what a person can run on their own machine: an executable, a script, or an agent skill. `<what they offered>` is a hosted service, so there is no shelf for it here.

Vary the second sentence to name what it actually is (a web app, a documentation page, a service). Never deny that the tool is real; it plainly is, it simply is not the kind of thing this archive records. If the source repo contains both a hosted service and a CLI that talks to it, the CLI can be registered on its own; say so and continue with the CLI as the tool.

## The interview

Ask in this order. Each question is put in plain words; the submitter is never shown YAML and never asked for a field by its schema name. When the README gives enough to propose everything, put the proposals in a single message (draft prose, name, kind, install line) and ask for one confirmation; ask separately only about what the README left blank. The mapping from question to key is for your eyes, not theirs:

| Step | What the submitter is asked | What it fills |
|---|---|---|
| 1 | "Where does it live?" (a URL) | `source`, and the material for the body |
| 2 | "I'll file it as `<proposed>`; keep that name?" | `name` |
| 3 | "Is this a command-line program, a script you run, or an agent skill?" (only if the README leaves it unclear) | `kind` |
| 4 | "Is there a one-line install command?" (only if the README has none) | `install` (optional) |
| never asked | | `owner` (the caller's login), `registered` (today, `YYYY-MM-DD`), `status` (`active`) |

### 1. Source URL first

The URL is the only thing needed to begin, and it is what makes the rest of the interview short. If the caller is inside a git checkout whose `origin` is a GitHub URL and gave no URL, propose that origin and confirm it; do not assume.

Normalize the URL: `https://`, no trailing slash, no `.git` suffix. For `https://github.com/{o}/{r}` read the README to draft the prose:

```
gh api repos/{o}/{r}/readme -H "Accept: application/vnd.github.raw+json"
```

The `Accept` header returns the file's text instead of a base64 `content` field. A 404 means the repo has no README, or the caller cannot see it; `gh api repos/{o}/{r} --jq .description` gives the one-line description, and if that is empty too, ask the submitter for two or three sentences on what it does. For a source that is not on github.com, fetch the page if it is fetchable and otherwise ask the same question. Reachability itself is not your call: the validator checks `source` and the instance's CI checks it again on push.

From the README, draft the body in the words someone with the need would use: first what the tool does, then when you would reach for it and what it is not. Two short paragraphs is the norm. Show the draft to the submitter as prose ("Here is how I'd describe it") and accept edits. The body is what search reads (R-1); a draft that only restates the repo name is an entry nobody will find.

### 2. Name

Propose the name from the repo name: lower-case, `[a-z0-9]` words joined by single hyphens, nothing else (the validator's kebab-case rule). `Apk_Find` becomes `apk-find`; a scoped package like `@acme/pq-diff` becomes `pq-diff`. Then check the snapshot: if `entries/<proposed>.md` already exists, say who owns it and ask for a different name; never overwrite an entry. Uniqueness is finally decided by the validator, not by this check.

### 3. Kind

Infer `cli`, `script`, or `skill` from the README (a `SKILL.md` in the repo is a skill; an installable binary or a package with an entry point is a `cli`; a file you run with an interpreter is a `script`). Ask only if you cannot tell. Anything outside the three answers was refused in the previous section.

### 4. Install line

Optional, and only ever one line. Lift it from the README when there is an obvious one (`brew install ...`, `pip install ...`, `npm install -g ...`, `claude plugin install ...`); otherwise ask once and accept "no". Do not invent one, and do not compose a multi-step recipe; the archive describes tools, it does not build them (N-3).

### Never asked

`owner` is the caller's login from `gh api user --jq .login`; registering on someone else's behalf is not a thing this mode does (transfer exists for that). `registered` is today's date. `status` is `active`. Do not surface these to the submitter as questions.

## The overlap gate

This gate runs before any write: nothing is written until it has run and the submitter has answered. It is mandatory even when the answer is that nothing overlaps (R-3).

Compare the confirmed draft prose, the proposed name, and the source URL against **every existing entry** in the snapshot, including deprecated ones: read each `entries/*.md` body and frontmatter, and `adoption.yaml` for adopter counts. Judge fit the way search does (`references/search.md`): does an existing tool answer the same need, or a need a reader would confuse with it? Do not match on name alone, and do not skip entries because their names look unrelated. An entry whose `source` equals the new URL is the strongest possible overlap: the tool is already catalogued under another name.

Report before asking anything else. With candidates:

> Before I write anything: `<n>` existing entries overlap.
>
> - `<name>`, owner `<login>` (or unowned), `<active | deprecated (route, date)>`, `<k>` adopters. `<One sentence: what it does.>` `<One sentence: why it overlaps with the draft.>`
>
> Continue registering `<new-name>` as a distinct tool, `adopt <name>` instead, or abort?

Without candidates, the report is still made, in these words:

> Nothing in the archive overlaps with `<new-name>`. Continuing.

Then act on the answer:

- **Continue**: proceed to the write path. The submitter has seen the overlap and decided; do not relitigate it.
- **Adopt**: hand off to `adopt <existing>` in `references/adoption.md`. Nothing is written by `register`, and the closing line says so.
- **Abort**: stop. Respond with "Nothing written." and one sentence at most.

Present the three choices neutrally (see `references/voice.md`, example 3). A deprecated candidate is still reported, with its route and date; a new tool that replaces a retired one is a legitimate reason to continue, and the report is what lets the submitter say so.

## The write path

Only after the gate. Every step runs against the snapshot, never against a working tree of the user's.

1. **Refresh once more.** `git -C <snapshot> pull --ff-only`. The interview and the gate take time; this closes most of the window in which someone else's push would reject yours. If it fails, stop and report as SKILL.md's Snapshot section says.

2. **Write `entries/<name>.md`** with keys in this order and no others, omitting `install` when there is none:

   ```markdown
   ---
   name: <name>
   owner: <caller login>
   source: <normalized URL>
   kind: <cli | script | skill>
   install: <one line, omitted if none>
   registered: <YYYY-MM-DD>
   status: active
   ---
   <confirmed prose body>
   ```

   The format is `references/schema.md`'s and nothing else: no extra keys, no `deprecated` block on a new entry, no comments. A key the schema does not list fails validation with `unknown-key`, and adding one to serve some reader's convenience is exactly what N-7 forbids.

3. **Run the validator** over the snapshot, without `--offline`:

   ```
   uv run --project "${CLAUDE_PLUGIN_ROOT}" python "${CLAUDE_PLUGIN_ROOT}/scripts/validate.py" --root <snapshot>
   ```

   (or the `python3` form from SKILL.md's "Running the validator locally" section when `uv` is absent). Exit 0 continues. On exit 1, show the output verbatim, one line per failure, and fix the entry: a `name` failure goes back to the name step, a `source` failure means the URL is wrong or unreachable and the submitter must say which, a `body` failure means the draft came out empty. Re-run until it exits 0. Never bypass a failure, never add `--offline` to dodge a reachability check, and never commit a red validator; the validator is the gate (P-4, R-6), and the instance's CI would refuse the push anyway.

4. **Commit** the one file, with the fixed message:

   ```
   git -C <snapshot> add entries/<name>.md
   git -C <snapshot> commit -m "register <name>"
   ```

   Stage that path only. Nothing else in the snapshot should have changed, and if something has, that is a problem to report, not to sweep into the commit.

5. **Push.**

   ```
   git -C <snapshot> push
   ```

   If the push succeeds, record the SHA with `git -C <snapshot> rev-parse --short HEAD` and go to the closing message.

6. **On a rejected push** (non-fast-forward: someone pushed while the interview ran), rebase and retry once:

   ```
   git -C <snapshot> pull --rebase
   ```

   If the rebase stops on a conflict, run `git -C <snapshot> rebase --abort` so the snapshot is never left mid-rebase, then stop and report: the only file this commit touches is `entries/<name>.md`, so a conflict means someone registered the same name in the meantime, and the submitter needs to pick another. If the rebase completes cleanly, re-run the validator (the pull may have brought in an entry with the same name or source, and uniqueness is checked against the whole set), then `git -C <snapshot> push` one more time. If that second push is also rejected, stop and report; do not loop. The commit stays in the snapshot, which is what makes the next `pull --ff-only` fail loudly instead of losing it, and the report says exactly that: what is committed locally, what is not on the instance, and the error text.

   `references/write-paths.md` holds the same rebase-retry recipe for every direct-commit mode; this is the D-3 direct path for an entry the caller owns.

7. **Authorization on push** is the instance's `validate.yml` running `--changed-only` with the pusher as actor: a new entry must be owned by the actor. Because `owner` defaults to the caller, this passes by construction. If the user later reports that run red, the machinery is at fault or the login was wrong; the skill never edits `owner` to make it pass.

## Closing message

The first line is the plain statement, before any character text (R-8, SKILL.md voice rule 1). A reader who stops after one line knows what is in their repo. Then at most one sentence of register, in the manner of `references/voice.md` example 2.

On success:

> Committed `entries/<name>.md` to `<default branch>` of `<org>/<repo>` (`<sha>`), owner `<login>`, kind `<kind>`.
>
> The archive has it now. Anyone who asks for `<the need in a few words>` will be pointed to you.

If the push landed only after the rebase, say so in the same first line: `(<sha>, after rebasing onto newer commits)`.

On abort at the overlap gate, or on a refusal:

> Nothing written.

followed by the one sentence that names why. When the submitter chose to adopt instead, the closing message is `adopt`'s, from `references/adoption.md`: it states the adoption commit, and `register` has nothing to add.

When the push was rejected twice:

> Committed `entries/<name>.md` locally in the snapshot (`<sha>`) but the push to `<org>/<repo>` was rejected twice; nothing is on the instance. `<git's error text>`
>
> Run `register` again once the snapshot pulls cleanly; the local commit will be carried along.

Never paraphrase the path, the SHA, the repo, or the validator's lines into character. Voice goes in the framing sentence, and only there.
