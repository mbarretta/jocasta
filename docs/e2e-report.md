# End-to-end sandbox verification, v1

Dates: first round 2026-09-04, retry 2026-09-06. Machinery:
`github.com/mbarretta/jocasta`, public, tag `v1` at `ecadd4d` (main at
`48c8aa1`, same tree; unchanged between the two rounds). Instance:
`github.com/mbarretta/jocasta-sandbox`, private, created for this run.
Account: `mbarretta`, the only GitHub account available.

## Result in one paragraph

Two rounds. In the **first round** the skill's protocols and all three
scripts behaved as the design plan's "Verification" section says when driven
by hand against the real private instance (`init`, the overlap gate, every
direct-commit mode, the search wording, both non-owner PR paths,
`consensus_merge.py` refusing with one voice, `stale_sweep.py` opening and
then not opening a `route: stale-source` PR, the own-login rule on
`adoption.yaml`), but **every one of the instance's 22 GitHub Actions runs
failed before reaching a script**: the composite actions pass
`${{ github.action_ref }}` to a nested `actions/checkout@v7`, and inside a
nested action's `with:` block that expression resolves to the nested action's
ref (`v7`), not the caller's (`v1`) — discrepancy D1. The **retry** could not
fix D1 (that is a machinery change and a re-tag, outside this task), so it
put a shim in the sandbox: copies of the three `v1` actions differing in
exactly that one line, with the sandbox workflows pointed at them. Through
the shim the unmodified `v1` scripts ran under Actions and the plan's
GitHub-side outcomes were observed: `validate` green on every direct-commit
write and red for the right reason on a dead source and on a foreign login in
`adoption.yaml`; `consensus-merge` evaluating both open PRs and refusing to
merge with one non-owner voice; the sweep, from a `workflow_dispatch`,
finding the dead source and pushing its `route: stale-source` proposal
branch, and opening nothing after the fix. One expected outcome did not
happen and became a confirmed discrepancy: the sweep's `gh pr create` under
the workflow token was refused because GitHub's "Allow GitHub Actions to
create and approve pull requests" setting is off by default, so
`init-connect.md`'s "the default `GITHUB_TOKEN` is enough" is not true as
written (D3). Still not observed: the `@v1` remote action reference itself
(D1 stays open and deferred), `validate` on an empty registry from Actions,
a sweep PR opened by the workflow token, and anything needing a second
account. Three discrepancies are recorded below and deferred rather than
fixed here. The sandbox could not be deleted (token lacks `delete_repo`) and
is left in place.

## How this was run

- The e2e acts as a user of the skill: `skills/jocasta/SKILL.md` and its
  `references/*.md` were followed literally, command by command, with `gh` and
  `git`. Where a step is model judgment (drafting prose from a README, the
  overlap report, ranking a search), the judgment was made by hand and the
  resulting text is reproduced here as the skill would have shown it.
- The plugin root was the machinery worktree at `48c8aa1`; the validator was
  run as `uv run --project <plugin root> python <plugin root>/scripts/validate.py --root <snapshot>`
  (SKILL.md, "Running the validator locally"), online unless stated.
- The snapshot clone lived under a scratch directory instead of
  `~/.cache/jocasta/<org>/<repo>` (a location substitution only; every
  command was otherwise the reference's). `~/.config/jocasta/config.yaml` was
  written by `init` as specified and removed at the end because it pointed at
  a sandbox.
- Commits were signed with the account's usual gitsign setup; nothing about
  signing was changed.
- Every commit, PR, and run URL is linked. The sandbox is private, so the
  links resolve only for its owner.
- The retry (2026-09-06) used a fresh clone of the sandbox as the snapshot,
  again under the scratch directory, and the same plugin root (`48c8aa1`,
  whose tree is `v1`'s). Config discovery took SKILL.md's first branch (the
  cwd was a registry checkout whose `origin` is
  `mbarretta/jocasta-sandbox`), so no `~/.config/jocasta/config.yaml` was
  written this time. Nothing in the machinery repository was changed by
  either round; the only file this task writes is this report.

## Preconditions (ac1)

Confirmed before acting, all user-approved through the orchestrator:

| Check | Result |
|---|---|
| `gh repo view mbarretta/jocasta` | `PUBLIC`, `https://github.com/mbarretta/jocasta` |
| `git ls-remote` tag `v1` | annotated tag `b065006` → commit `ecadd4d`; `main` = `48c8aa1`; `main^{tree}` == `v1^{tree}` (`5fbb714`) |
| `gh auth status` | logged in as `mbarretta`; scopes `gist, read:org, repo, workflow` (no `delete_repo`) |
| `mbarretta/jocasta-sandbox` | did not exist before the run; permission to create and later delete it was given |

Machinery-side checks from the first Verification bullet, run in the worktree:

- `uv run pytest -q`: 263 passed.
- `uv run python scripts/validate.py --root template --offline`: `ok: 0 entries validated`, exit 0.
- Every fixture under `tests/fixtures/invalid/` fails with one plain line
  naming its rule, with two explainable exceptions: `name-duplicate` prints
  two lines (the duplicate is also a filename mismatch, so both rules fire),
  and `source-unreachable` passes under `--offline` because that flag skips
  reachability by design (the suite tests it with a faked `gh`).

## Steps, first round (2026-09-04)

Legend for "Match": **yes** = observed exactly what the plan's Verification
section expects; **script yes / action no** = the script produced the expected
result when run locally, but the instance workflow that should have run it
failed at the machinery checkout (discrepancy D1). The "action no" cells are
revisited in "Retry: the Actions side, through a sandbox shim" below, which
records which of them were later observed under Actions and which still were
not.

| # | Step | Commit / artifact | Instance run | Match |
|---|---|---|---|---|
| 1 | `init mbarretta/jocasta-sandbox` (private) | [`129d59f`](https://github.com/mbarretta/jocasta-sandbox/commit/129d59f194d691970af2e2c98db18258519c7dc6) `Initialize jocasta registry` | [validate 33928875466](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33928875466) **failure** | workflows appear: yes; `validate` green on empty registry: **no** (D1) |
| 2 | `register ripgrep` | [`0b53e61`](https://github.com/mbarretta/jocasta-sandbox/commit/0b53e612f942564ba0984119ea306b077c6f9188) | [validate 33929055079](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929055079) failure | script yes / action no |
| 3 | `register the-silver-searcher` (overlaps #2) | [`3c1ee5e`](https://github.com/mbarretta/jocasta-sandbox/commit/3c1ee5e365c045ef156d9eec994aa85614907100) | [validate 33929153848](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929153848) failure | overlap reported before any write: yes; lands as direct commit: yes; CI green: no (D1) |
| 4 | `search`, empty `search`, `show` | read-only | none | yes |
| 5 | `adopt ripgrep` | [`f96c82a`](https://github.com/mbarretta/jocasta-sandbox/commit/f96c82a49e2ef8fce97bc86208ecc1580c5ef978) | [validate 33929161569](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929161569) failure | adopter count shown by search: yes; action no |
| 6 | `deprecate the-silver-searcher` as owner | [`b94ea99`](https://github.com/mbarretta/jocasta-sandbox/commit/b94ea994881e336937228a580fb0812686194ad9) | [validate 33929191026](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929191026) failure | direct commit, still in search and marked: yes; action no |
| 7 | `release ripgrep` | [`f65ea53`](https://github.com/mbarretta/jocasta-sandbox/commit/f65ea53faf3b0de69d5392f65892e2bdd48881bb) | [validate 33929197503](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929197503) failure | entry active and unowned: yes; action no |
| 8 | `register fd` (for the sweep) | [`db471ce`](https://github.com/mbarretta/jocasta-sandbox/commit/db471ce303d18475101300fa7d9815741cd53bc1) | [validate 33929201337](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929201337) failure | script yes / action no |
| 9 | `claim ripgrep` (unowned → PR) | [PR #1](https://github.com/mbarretta/jocasta-sandbox/pull/1), branch `jocasta/claim-ripgrep-mbarretta`, label `ownership` | consensus-merge [33929268968](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929268968), [33929269001](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929269001); validate [33929269035](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929269035); all failure | PR opened as specified: yes; `consensus_merge.py` refuses with 1 voice: yes (locally); action no |
| 10 | `deprecate ripgrep` as non-owner (→ PR) | [PR #2](https://github.com/mbarretta/jocasta-sandbox/pull/2), branch `jocasta/deprecate-ripgrep-mbarretta`, label `deprecation` | consensus-merge [33929283700](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929283700), [33929284023](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929284023); validate [33929283661](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929283661); all failure | same as #9 |
| 11 | break `fd` source, push | [`740960b`](https://github.com/mbarretta/jocasta-sandbox/commit/740960b0c51292bd65ff82c99fc2d1d9ce53b6b2) | [validate 33929362504](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929362504) failure | local validator red with `source: unreachable`: yes; action no |
| 12 | `stale-sweep.yml` via `workflow_dispatch` | — | [stale-sweep 33929361965](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929361965) **failure** | **no** (D1); reproduced with `stale_sweep.py` locally → [PR #3](https://github.com/mbarretta/jocasta-sandbox/pull/3), `route: stale-source` |
| 13 | fix source, close PR #3, sweep again | [`e389c65`](https://github.com/mbarretta/jocasta-sandbox/commit/e389c65487d48bf4e219fd5e435f49dde15e82dd) | [validate 33929460394](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929460394), [stale-sweep 33929492475](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929492475); both failure | next sweep opens nothing: yes (locally); action no |
| 14 | `adoption.yaml` + foreign login, push | [`a66cdba`](https://github.com/mbarretta/jocasta-sandbox/commit/a66cdba80e4e07bf8e03a772b9738bdb83dffd21) | [validate 33929501613](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929501613) failure (at checkout, not on the rule) | own-login rule fires locally with the documented line: yes; action no |
| 15 | delete the sandbox | `gh repo delete mbarretta/jocasta-sandbox --yes` → HTTP 403, needs `delete_repo` | — | left in place (allowed by ac4) |

### 1. `init`

`references/init-connect.md`, steps 1–8, as written:

```
gh repo create mbarretta/jocasta-sandbox --private --description "Jocasta tool registry"
gh repo clone mbarretta/jocasta-sandbox <workdir>
git -C <workdir> checkout -b main
cp -R "<plugin root>/template/." <workdir>/
sed -i '' 's/PLACEHOLDER_TEAM/jocasta-sandbox/' <workdir>/jocasta.yaml
grep -rn PLACEHOLDER_TEAM <workdir>          # printed nothing
git -C <workdir> add -A && git -C <workdir> commit -m "Initialize jocasta registry" && git -C <workdir> push -u origin main
printf 'registry: %s\n' mbarretta/jocasta-sandbox > ~/.config/jocasta/config.yaml
gh repo clone mbarretta/jocasta-sandbox <snapshot> -- --depth 1
```

Observed: repo created private at 23:15:51Z; commit `129d59f` pushed;
`gh workflow list` shows `consensus-merge`, `stale-sweep`, `validate`, all
active. The `validate` run on the push started with
`base-ref: 0000000000000000000000000000000000000000` and `actor: mbarretta`
(the template's expressions are right) and then failed in the composite
action's first step: `actions/checkout@v7` with `repository: mbarretta/jocasta`,
`ref: v7`, fetching `+refs/tags/v7*:refs/tags/v7*`, three attempts, exit 1.
The validator never ran. See D1.

Also observed: step 4's literal replacement rewrote the template's own
comment, because `template/jocasta.yaml` line 1 reads "`init` replaces
PLACEHOLDER_TEAM with your team's name"; after the step the sandbox's file says
"`init` replaces jocasta-sandbox with your team's name". The step's `grep`
check passes only because the comment was rewritten too. See D2.

Plain statement the skill would have closed with:

> Created `mbarretta/jocasta-sandbox` (private) and pushed the initial commit `Initialize jocasta registry` to `main`. Wrote `~/.config/jocasta/config.yaml` with `registry: mbarretta/jocasta-sandbox`.

### 2 and 3. `register`, twice, the second overlapping the first

`references/register.md`. Source READMEs were read with
`gh api repos/{o}/{r}/readme -H "Accept: application/vnd.github.raw+json"`
and the body drafted from them (two paragraphs: what it does, when to reach
for it and what it is not). Name proposed from the repo name (`ripgrep`;
`the_silver_searcher` → `the-silver-searcher`), kind `cli` from the README,
install line lifted from it. `owner`, `registered`, `status` never asked.

Overlap gate, first registration (archive empty):

> Nothing in the archive overlaps with `ripgrep`. Continuing.

Overlap gate, second registration, reported before anything was written:

> Before I write anything: `1` existing entries overlap.
>
> - `ripgrep`, owner `mbarretta`, active, `0` adopters. Searches a directory tree for a regular expression and prints the matching lines, respecting gitignore. It overlaps because the draft describes the same need: search a codebase for a pattern from the shell, skipping ignored files.
>
> Continue registering `the-silver-searcher` as a distinct tool, `adopt ripgrep` instead, or abort?

Answer: continue. Write path for both: `git pull --ff-only`, write
`entries/<name>.md` with the schema's keys in order, validator online
(`ok: 1 entries validated`, then `ok: 2 entries validated`), `git add` that one
path, `git commit -m "register <name>"`, `git push`. Both landed first try
(`0b53e61`, `3c1ee5e`). Closing statements:

> Committed `entries/ripgrep.md` to `main` of `mbarretta/jocasta-sandbox` (`0b53e61`), owner `mbarretta`, kind `cli`.

> Committed `entries/the-silver-searcher.md` to `main` of `mbarretta/jocasta-sandbox` (`3c1ee5e`), owner `mbarretta`, kind `cli`.

Both `validate` runs failed at the machinery checkout (D1). Run locally with
the arguments the action would have passed
(`--changed-only <before> --actor mbarretta`, on a full clone at the pushed
commit), each push passes: `authorization: 1 changed registry file(s) checked
for mbarretta` then `ok`. The full per-push table is under "Authorization
checks, run locally" below.

### 4. `search`, empty `search`, `show`

`references/search.md`. Every `entries/*.md` except `README.md` and
`adoption.yaml` were read from the refreshed snapshot; fit judged on the
bodies; ranked fit, adopters, status. Evaluated against the first round's
final snapshot (`a66cdba`), so `ripgrep` shows the adopter count after step 5 and after the
hand edit in step 14.

Need: "find every place a function name is used across a large repo without
wading through vendored or generated files".

```
1. `ripgrep` — Searches a directory tree for a regular expression, line by line, and prints the matching lines with file names.
   owner: unowned
   status: active
   adopters: 2
   source: https://github.com/BurntSushi/ripgrep
   install: `brew install ripgrep`

2. `the-silver-searcher` — Searches source code for a pattern across a directory tree and prints the matching lines, in the manner of ack but much faster.
   owner: `mbarretta`
   status: deprecated — retired by its owner on 2026-09-04: Superseded by ripgrep, which is faster and actively maintained.
   adopters: 0
   source: https://github.com/ggreer/the_silver_searcher
   install: `brew install the_silver_searcher`
```

`fd` was read and discarded: its body says it finds files by name and does
not search contents, so it has no fit for this need even though it shares
"search" vocabulary. The deprecated entry stays in the list and is marked
(R-5). Before step 5, `ripgrep` showed `adopters: 0`; after `f96c82a`, `1`.

Need with nothing in the archive: "convert spreadsheets to parquet". Response,
in full:

> What you describe does not appear in the archive.
>
> If you build one, `register` it and the next person who asks will find it here.

The phrase "does not exist" was not used anywhere in this run.

`show fd` printed the frontmatter as a fenced `yaml` block byte for byte, the
body as written, and `adopters: none recorded`. `show pq-diff` (absent):

> `pq-diff` does not appear in the archive.

### 5. `adopt ripgrep`

`references/adoption.md`. `adoption.yaml` was `{}` under its three comment
lines; the login was added as `ripgrep: [mbarretta]` keeping the comments and
the flow style; validator `ok: 2 entries validated`; `git add adoption.yaml`,
`git commit -m "adopt ripgrep"`, `git push` → `f96c82a`.

> Committed `adopt ripgrep` to `main` of `mbarretta/jocasta-sandbox` (`f96c82a`): added `mbarretta` under `ripgrep` in `adoption.yaml`.

Local `--changed-only f96c82a^ --actor mbarretta`: pass. Instance run: D1.

### 6. `deprecate the-silver-searcher` as owner

`references/ownership.md`. Caller `mbarretta` equals `owner`, so the
direct-commit row. Frontmatter edited to `status: deprecated` plus
`deprecated: {route: owner, date: 2026-09-04, note: Superseded by ripgrep, which is faster and actively maintained.}`;
one sentence appended to the body, "Deprecated in favor of `ripgrep`."; commit
`deprecate the-silver-searcher` → `b94ea99`.

> Committed `entries/the-silver-searcher.md` to `main` of `mbarretta/jocasta-sandbox` (`b94ea99`): `status: deprecated`, route `owner`, date `2026-09-04`.

Search (step 4) still lists it, marked. Local authorization check: pass
(owner at `REF` was the actor). Instance run: D1.

### 7. `release ripgrep`

Owner only, direct commit: `owner: mbarretta` → `owner: ~`, nothing else;
commit `release ripgrep` → `f65ea53`. Search shows `owner: unowned`, status
still `active`.

> Committed `entries/ripgrep.md` to `main` of `mbarretta/jocasta-sandbox` (`f65ea53`): owner `mbarretta` -> `~`. The entry is active and unowned.

Local authorization check: pass (a release by the previous owner). Instance
run: D1.

Process note, stated so the record is honest: for steps 6, 7 and 8 the local
validator was invoked with a shell variable that did not word-split, so it
did not run *before* those three commits. It was run afterwards over the same
tree (`ok: 3 entries validated`, online) and the three commits are what it
would have validated; but in those three cases the reference's order
(validate, then commit) was not followed by the operator. Every other write in
this run validated before committing.

### 8. `register fd`

As steps 2–3. Overlap gate: "Nothing in the archive overlaps with `fd`.
Continuing." (its body says it finds files by name and does not search their
contents, which is a different need from the two searchers). Commit
`register fd` → `db471ce`. Local authorization check: pass.

### 9 and 10. The PR paths: `claim` and non-owner `deprecate`

With one account, the only way to reach the PR rows of
`references/write-paths.md` is an **unowned** entry, and `ripgrep` is unowned
after step 7: a caller who is not the owner (there is none) opens a PR for
both `claim` and `deprecate`. Both followed the PR recipe exactly:
`git pull --ff-only` on `main`, `git checkout -b jocasta/<mode>-ripgrep-mbarretta`,
edit `entries/ripgrep.md` only, validator online (`ok: 3 entries validated`),
`git add entries/ripgrep.md`, `git commit -m "<mode> ripgrep"`,
`git push -u origin <branch>`, `gh label create <label> --repo … --description "…"`
(the template ships no labels; both were created), `gh pr create --base main --head <branch> --title "<mode> ripgrep" --label <label> --body "<Why + how it is decided>"`,
`git checkout main`.

- [PR #1 `claim ripgrep`](https://github.com/mbarretta/jocasta-sandbox/pull/1): branch `jocasta/claim-ripgrep-mbarretta`, label `ownership`, diff `owner: ~` → `owner: mbarretta`.
- [PR #2 `deprecate ripgrep`](https://github.com/mbarretta/jocasta-sandbox/pull/2): branch `jocasta/deprecate-ripgrep-mbarretta`, label `deprecation`, diff adds `status: deprecated` and `deprecated: {route: consensus, date: 2026-09-04, note: …}`.

Closing statements:

> Opened https://github.com/mbarretta/jocasta-sandbox/pull/1 (branch `jocasta/claim-ripgrep-mbarretta`, label `ownership`) proposing owner `mbarretta`. Nothing on `main` has changed.
>
> It merges when one more person approves; you are the first of two voices.

> Opened https://github.com/mbarretta/jocasta-sandbox/pull/2 (branch `jocasta/deprecate-ripgrep-mbarretta`, label `deprecation`) proposing `status: deprecated`, route `consensus`. Nothing on `main` has changed.
>
> It merges when one more person approves; you are the first of two voices.

Each PR started the instance's `consensus-merge` workflow twice (`opened`,
`labeled`) and `validate` once (`pull_request`); all six runs failed at the
machinery checkout (D1), so the action never evaluated either PR. Run
locally with the action's arguments:

```
$ consensus_merge.py --repo mbarretta/jocasta-sandbox --pr 1
pr #1: waiting: 1 of 2 non-owner voices (mbarretta)
$ consensus_merge.py --repo mbarretta/jocasta-sandbox --pr 2
pr #2: waiting: 1 of 2 non-owner voices (mbarretta)
```

Exit 0 both times; no merge, no comment, no close; both PRs remain open. That
is the plan's "refuses to merge with one non-owner voice" outcome, reached by
the script rather than by the workflow. **Not exercised**, because there is
one account: a second account approving to reach two voices and the squash
merge with `(route: consensus)` in the subject; an owner's approval merging
with `(route: owner)`; an owner's `CHANGES_REQUESTED` blocking; `claim`
"entry shows new owner" after merge. GitHub does not let an account review
its own PR, so none of these can be reached from `mbarretta` alone. The
script-level rules for those cases are covered by
`tests/test_consensus_merge.py` with `gh` mocked.

### 11 to 13. The stale-source route

Step 11 broke `fd`'s source by hand on `main`: `source: https://github.com/sharkdp/fd`
→ `https://github.com/sharkdp/fd-e2e-source-gone-0000`. This is the one write
in the run that the skill itself would have refused (the validator, run
first, printed exactly one line:
`entries/fd.md: source: unreachable (gh api repos/sharkdp/fd-e2e-source-gone-0000 failed: gh: Not Found (HTTP 404)): https://github.com/sharkdp/fd-e2e-source-gone-0000`,
exit 1); it was pushed anyway to simulate a source that died after
registration (`740960b`). The instance's `validate` run for it failed at the
checkout (D1), so the red-with-`source`-line outcome the workflow should have
shown was not observed.

Step 12: `gh workflow run stale-sweep.yml --repo mbarretta/jocasta-sandbox -f dry-run=false`
→ [run 33929361965](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929361965),
failure at the machinery checkout (D1); the sweep never ran. Reproduced
locally from the snapshot at `740960b`, first as a dry run then live, with
`--pause 0` to skip the retry wait:

```
$ stale_sweep.py --root <snapshot> --repo mbarretta/jocasta-sandbox --dry-run --pause 0
fd: stale (unreachable twice: gh api repos/sharkdp/fd-e2e-source-gone-0000 failed: gh: Not Found (HTTP 404)); dry run, would open PR 'deprecate fd (stale source)' from branch jocasta/stale-fd
ripgrep: reachable
the-silver-searcher: skipped; already deprecated (route owner, 2026-09-04)
sweep: 2 active entries checked, 1 stale, 1 PRs would be opened, 1 skipped
$ stale_sweep.py --root <snapshot> --repo mbarretta/jocasta-sandbox --pause 0
fd: stale (…); opened https://github.com/mbarretta/jocasta-sandbox/pull/3
ripgrep: reachable
the-silver-searcher: skipped; already deprecated (route owner, 2026-09-04)
sweep: 2 active entries checked, 1 stale, 1 PRs opened, 1 skipped
```

[PR #3 `deprecate fd (stale source)`](https://github.com/mbarretta/jocasta-sandbox/pull/3):
branch `jocasta/stale-fd`, labels `stale-source` and `deprecation` (the
`stale-source` label was created by the script with the wording from
`write-paths.md`), diff changes exactly `entries/fd.md`: `status: active` →
`status: deprecated` plus `deprecated: {route: stale-source, date: 2026-09-04, note: "Source did not answer on the stale sweep of 2026-09-04 (unreachable twice: …)"}`.
Body states why, names the owner, says how it is decided and how to dismiss
it (fix the source, close the PR). The snapshot was left on `main`, clean.

Because the PR was opened with the operator's token rather than the
workflow's `GITHUB_TOKEN`, two things differ from what the instance would do:
its author is `mbarretta` (the entry's owner), so
`consensus_merge.py --pr 3` reports `waiting: 0 of 2 non-owner voices` (an
owner-author is not a voice, as `ownership.md`'s table says), whereas a
sweep PR opened by the workflow would have `github-actions[bot]` as author;
and the `pull_request` workflows **did** fire on it (three `consensus-merge`
runs for `opened` and the two labels, one `validate`, all failing at the
checkout), whereas the documented GitHub rule is that a PR opened with the
workflow token starts none of them. The "PRs opened by the sweep do not
trigger the instance's `pull_request` workflows" limit was therefore
**expected but not observable** in this run.

Step 13: source restored on `main` (`e389c65`, validator online `ok: 3
entries validated` before the commit), PR #3 closed by hand with
`gh pr close 3` per the PR body's instructions, then the sweep again:

```
fd: reachable
ripgrep: reachable
the-silver-searcher: skipped; already deprecated (route owner, 2026-09-04)
sweep: 2 active entries checked, 0 stale, 0 PRs opened, 1 skipped
```

Nothing opened, as the plan expects. A second `workflow_dispatch`
([run 33929492475](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929492475))
failed at the checkout like the first.

### 14. `adoption.yaml` with someone else's login

Hand edit `ripgrep: [mbarretta]` → `ripgrep: [mbarretta, octocat]`, commit,
push (`a66cdba`). The schema-only validator passes this file (a non-empty
login list is well formed); the rule that should catch it is the
`--changed-only` authorization check that only the workflow runs. The
instance's run failed at the checkout (D1), so the plan's "`validate.yml`
fails with the own-login rule" was not observed there. Run locally with the
action's arguments plus `--offline` (`--changed-only e389c65 --actor mbarretta`
on a clone at `a66cdba`; only the reachability check differs from the action,
and it does not bear on this rule):

```
authorization: 1 changed registry file(s) checked for mbarretta
adoption.yaml: authorization: octocat added under 'ripgrep' by mbarretta, who may only add their own login; open a PR instead
```

exit 1. The line is the one `references/adoption.md` documents. The commit is
on `main` (the check runs after the push and cannot undo it, as the docs
say); reverting it by direct push would trip the same rule from the other
side (removing `octocat`), which is the documented symmetry, so the edit was
left in place for the record. This step was done last so nothing after it
depended on a clean `adoption.yaml`.

### 15. Deleting the sandbox

```
$ gh repo delete mbarretta/jocasta-sandbox --yes
HTTP 403: Must have admin rights to Repository. (https://api.github.com/repos/mbarretta/jocasta-sandbox)
This API operation needs the "delete_repo" scope. To request it, run:  gh auth refresh -h github.com -s delete_repo
```

The token lacks the scope and refreshing auth scopes was out of bounds for
this run, so **the sandbox is left in place**, private, with its ten commits,
three PRs (two open, one closed), three `jocasta/*` branches and the
`e2e-probe` branch. To delete it:

```
gh auth refresh -h github.com -s delete_repo
gh repo delete mbarretta/jocasta-sandbox --yes
```

Local cleanup done: `~/.config/jocasta/config.yaml` (written by `init`,
pointing at the sandbox) removed; no `~/.cache/jocasta` was created because
the snapshot lived in the scratch directory.

Retry, 2026-09-06: the same command was run again at the end of the retry and
was refused with the same `HTTP 403` / `delete_repo` message. The sandbox
stays in place; the two commands above still apply.

## Retry: the Actions side, through a sandbox shim (2026-09-06)

The first round's evaluator asked for the Actions-side outcomes to be
observed rather than reproduced by hand. Fixing D1 means editing
`.github/actions/{validate,consensus-merge,stale-sweep}/action.yml` and
`tests/test_template.py` in the machinery and moving or re-cutting the `v1`
tag, none of which this task may do (its only repository write is this
report). What it may change is the sandbox, which it owns for the run. So the
retry added a **shim** to the sandbox: byte-for-byte copies of the three `v1`
composite actions under the sandbox's own `.github/actions/<name>/`, each
differing from the machinery's file in exactly one line,
`ref: ${{ github.action_ref }}` → `ref: v1` (the value the fixed expression
yields when an instance calls the action at `@v1`; the shim hard-codes it
rather than evaluating the expression for a local action), and the three template workflows pointed at those
local copies (`uses: ./.github/actions/<name>`), with the original `uses:`
line kept as a comment. Everything downstream of that line is the machinery's:
every run below checks out `mbarretta/jocasta` at `v1` (`HEAD is now at
ecadd4d` in each log), installs PyYAML, and runs the unmodified `v1` script
with the arguments the template passes. The shim was verified against the
worktree before it was pushed (three files identical apart from the one line;
all YAML parses).

Shim commits:
[`e46792b`](https://github.com/mbarretta/jocasta-sandbox/commit/e46792bbb7623b86dc404ff3708b7433c308c607)
(the copies and the three `uses:` lines) and
[`f6d4bad`](https://github.com/mbarretta/jocasta-sandbox/commit/f6d4bad5d2b9c52ca2ef64d6692f75209153a817)
(see accommodation 1 below).

**What the shim shows, and what it does not.** It shows that with the ref
line corrected the three actions reach their scripts, and that the scripts
behave as the plan says under the workflow token and the template's events,
permissions, and inputs. It does **not** exercise the
`mbarretta/jocasta/.github/actions/<name>@v1` reference itself, which still
fails exactly as in the first round; D1 is confirmed, not closed. Two
accommodations were needed for the shim alone and are not findings about the
machinery:

1. A local action has to exist in the runner's workspace, so the sandbox's
   `consensus-merge.yml` gained an `actions/checkout@v7` step
   (`persist-credentials: false`) ahead of the local action. The template
   correctly has no checkout there: the remote `@v1` action needs none, since
   `consensus_merge.py` works through the API. The first two `labeled` runs
   after `e46792b` failed on exactly this
   ([34048648571](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048648571),
   [34048650911](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048650911):
   "Can't find 'action.yml' … Did you forget to run actions/checkout").
2. `pull_request: labeled` runs use GitHub's cached test-merge commit of the
   PR, and that cache lagged the base-branch push of `f6d4bad`: re-labelling
   the two PRs twice more re-ran the pre-`f6d4bad` workflow and failed the
   same way four more times
   ([34048983990](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048983990),
   [34048986869](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048986869),
   [34049249812](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049249812),
   [34049251875](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049251875);
   `refs/pull/1/merge` still held the older file). One empty commit on each
   PR branch (`synchronize`;
   [`5d749f1`](https://github.com/mbarretta/jocasta-sandbox/commit/5d749f13803a2827a3109b7dbd832bae7bcc2bda),
   [`b949fd4`](https://github.com/mbarretta/jocasta-sandbox/commit/b949fd40c8241ed9952cda938ec56ad29c8e0a3c))
   refreshed the merge commit and the runs went green. Each PR still changes
   exactly one file. With the real remote action the workflow file never
   changes on the base branch mid-PR, so this would not arise.

Every write in the retry followed its reference's order: file written,
validator run online over the snapshot and green, the one path staged,
commit, push, then the instance's `validate` run watched. One departure from
the letter of the references, stated for the record: `git pull --ff-only`
was run once, before the first write (`register jq`); the later writes went
out from a snapshot that was the instance's tip only because this session
had just pushed it and nothing else writes to the sandbox, not because the
per-mode refresh was repeated. That also closes the first round's process note about steps
6–8: `register`, `adopt`, `deprecate` as owner, and `release` were each
exercised again with the validator before the commit, and each push's run is
linked below.

### The plan's GitHub-side expectations, observed

| Plan expectation | Sandbox write | Run | Observed | Verdict |
|---|---|---|---|---|
| `validate.yml` passes | shim push [`e46792b`](https://github.com/mbarretta/jocasta-sandbox/commit/e46792bbb7623b86dc404ff3708b7433c308c607) (no registry file changed) | [validate 34048149577](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048149577) success | `authorization: 0 changed registry file(s) checked for mbarretta` / `ok: 3 entries validated` | green on a push, **yes**; "on the empty registry", **not re-observable** (the instance is no longer empty and `init` was not re-run; first round's push `129d59f` failed at the checkout) |
| `register` lands as a direct commit; CI green | `register jq` [`31d8fee`](https://github.com/mbarretta/jocasta-sandbox/commit/31d8fee71b31f4a81346be6acb0d52c867ed3c60) | [validate 34048626104](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048626104) success | `authorization: 1 changed registry file(s) checked for mbarretta` / `ok: 4 entries validated` | **yes** |
| `adopt`; CI green; `search` shows the adopter count | `adopt jq` [`b62cd53`](https://github.com/mbarretta/jocasta-sandbox/commit/b62cd5332bf2111e9a6817b08adf459b1de8ad04) | [validate 34049327272](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049327272) success | 1 file checked; ok. `search` afterwards: `jq … adopters: 1` | **yes** |
| consensus PR path: the action runs and refuses with one non-owner voice | PR #1, PR #2 re-triggered (accommodation 2) | consensus-merge [34049447938](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049447938) (#1), [34049457370](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049457370) (#2), both success | `pr #1: waiting: 1 of 2 non-owner voices (mbarretta)`; `pr #2: waiting: 1 of 2 non-owner voices (mbarretta)`; exit 0; no merge, no comment, no close; both PRs still open | **yes** — the AC's floor |
| `validate` on a pull request | same two PRs | validate [34049447809](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049447809), [34049457340](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049457340), both success | `authorization: skipped; HEAD b416aff45aaf is a merge commit and the PR path already gated it` / `ok: 4 entries validated` (the `v1` validator's two-parent skip, as `adoption.md` documents) | yes (not a plan bullet; recorded for completeness) |
| `deprecate` as owner → direct commit; entry still in `search`, marked | `deprecate jq` [`b8bc178`](https://github.com/mbarretta/jocasta-sandbox/commit/b8bc17803b748617991a9ba03edc18a74c3317d6) (`route: owner`, `date: 2026-09-06`, note, body untouched) | [validate 34050089367](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34050089367) success | 1 file checked; ok. `search` lists `jq` as `deprecated — retired by its owner on 2026-09-06` | **yes** |
| `release` → direct commit; entry active and unowned | `release fd` [`81a58f6`](https://github.com/mbarretta/jocasta-sandbox/commit/81a58f6d2f4c3c1c9b88074e3df0bc3cd69ad2b1) | [validate 34050149068](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34050149068) success | 1 file checked; ok. `show fd`: `owner: ~`, `status: active` | **yes** (`claim` from another account: one-account limit, unchanged) |
| break a `source` URL → `validate` red | hand edit [`4d6ba51`](https://github.com/mbarretta/jocasta-sandbox/commit/4d6ba51ea42d5a51ee764f20aeef74e54bce04b1) (the local validator refused it first, as in the first round) | [validate 34049695634](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049695634) **failure** | `entries/fd.md: source: unreachable (gh api repos/sharkdp/fd-e2e-source-gone-0000 failed: gh: Not Found (HTTP 404)): …`; exit 1 | **yes** — red for the rule, not the checkout |
| `stale-sweep.yml` via dispatch → PR opened with `route: stale-source` | `gh workflow run stale-sweep.yml -f dry-run=false` | [stale-sweep 34049705584](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049705584) **failure** | `fd: stale (unreachable twice: …); could not open a proposal: gh pr create failed: pull request create failed: GraphQL: GitHub Actions is not permitted to create or approve pull requests (createPullRequest)` / `jq: reachable` / `ripgrep: reachable` / `the-silver-searcher: skipped; already deprecated (route owner, 2026-09-04)` / `sweep: 3 active entries checked, 1 stale, 0 PRs opened, 1 skipped, 1 failed`; exit 1. Before the refusal the sweep had force-pushed its branch `jocasta/stale-fd` as `github-actions[bot]`: [`cdac4e5`](https://github.com/mbarretta/jocasta-sandbox/commit/cdac4e516c890f9b736e4c29e5de12030caaae59) `deprecate fd (stale source)`, whose diff is exactly the `status: deprecated` + `deprecated: {route: stale-source, date: 2026-09-06, note: …}` change the plan expects | **partial**: sweep runs from the dispatch and produces the proposal; the PR is refused by a repository setting → **D3 confirmed** |
| (same, dry run) | `-f dry-run=true` | [stale-sweep 34049819315](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049819315) success | `fd: stale (…); dry run, would open PR 'deprecate fd (stale source)' from branch jocasta/stale-fd` / `sweep: 3 active entries checked, 1 stale, 1 PRs would be opened, 1 skipped` | yes |
| fix the source; next sweep opens nothing | [`2b9348f`](https://github.com/mbarretta/jocasta-sandbox/commit/2b9348fc994768058cabdec576eafd6e7c4d056e) (validator green before the commit) | [validate 34049933776](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049933776) success; [stale-sweep 34049957928](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049957928) success | `fd: reachable` / `jq: reachable` / `ripgrep: reachable` / `the-silver-searcher: skipped …` / `sweep: 3 active entries checked, 0 stale, 0 PRs opened, 1 skipped` | **yes** (there was no PR to close first, since none was opened; the bot's branch was left as pushed) |
| `adoption.yaml` + someone else's login → `validate.yml` fails with the own-login rule | hand edit [`1a9fb2b`](https://github.com/mbarretta/jocasta-sandbox/commit/1a9fb2bd445c36e4daec226d253144c472f6188d) (`jq: [mbarretta]` → `jq: [mbarretta, octocat]`) | [validate 34050270035](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34050270035) **failure** | `authorization: 1 changed registry file(s) checked for mbarretta` / `adoption.yaml: authorization: octocat added under 'jq' by mbarretta, who may only add their own login; open a PR instead`; exit 1 | **yes** — the exact line `adoption.md` documents |
| delete the sandbox | `gh repo delete mbarretta/jocasta-sandbox --yes` | — | `HTTP 403 … needs the "delete_repo" scope` | left in place (ac4) |

The `register jq` interview, for the record: source
`https://github.com/jqlang/jq` first (README read with `gh api
repos/jqlang/jq/readme`), name `jq` from the repo name, kind `cli` (a single
portable C binary), install `brew install jq`; `owner`, `registered`, `status`
never asked. Overlap gate, reported before the write: "Nothing in the archive
overlaps with `jq`. Continuing." (two text searchers and a file finder are a
different need from a JSON processor). Closing statement:

> Committed `entries/jq.md` to `main` of `mbarretta/jocasta-sandbox` (`31d8fee`), owner `mbarretta`, kind `cli`.

`search` against the final snapshot (`1a9fb2b`) for "pull one field out of a
command's JSON output from the shell" returns `jq` alone, marked
`status: deprecated — retired by its owner on 2026-09-06: Retired by its
owner at the end of the end-to-end run.`, `adopters: 2` (the second is the
hand-edited `octocat`); the three other entries are read and discarded as a
different need. The empty-result and `show` wording are as in step 4.

### Still not observed after the retry

- The `mbarretta/jocasta/.github/actions/<name>@v1` reference itself. D1 is
  open; the shim substitutes the fixed line, it does not test the machinery's.
- `validate` green on an **empty** registry from Actions. The first round's
  only empty-registry push (`129d59f`) failed at the checkout, and the retry
  did not re-run `init`; the local reproduction in "Authorization checks, run
  locally" is the only evidence for that bullet.
- A sweep PR opened by the workflow token, its `github-actions[bot]` author,
  the GitHub rule that such a PR starts no `pull_request` workflows, and
  closing it after a fix. All wait on the repository setting in D3. Turning
  that setting on for the sandbox
  (`gh api -X PUT repos/mbarretta/jocasta-sandbox/actions/permissions/workflow -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true`,
  or Settings → Actions → General → "Allow GitHub Actions to create and
  approve pull requests") was refused by the permission layer this run
  operated under and was not retried; with it on, the next
  `workflow_dispatch` against a dead source is expected to open the PR from
  branch `jocasta/stale-fd`.
- Everything that needs a second or third GitHub account (unchanged from the
  first round's "Known limits").

### Retry runs (24; 13 success, 9 failure, 2 skipped)

| Run | Workflow | Event | Ref | Result | Reached the script? |
|---|---|---|---|---|---|
| [34048149577](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048149577) | validate | push | main `e46792b` | success | yes |
| [34048626104](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048626104) | validate | push | main `31d8fee` | success | yes |
| [34048648571](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048648571) | consensus-merge | pull_request (labeled) | PR #1 | failure | no: shim accommodation 1 |
| [34048650911](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048650911) | consensus-merge | pull_request (labeled) | PR #2 | failure | no: shim accommodation 1 |
| [34048918196](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048918196) | validate | push | main `f6d4bad` | success | yes |
| [34048983990](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048983990) | consensus-merge | pull_request (labeled) | PR #1 | failure | no: shim accommodation 2 |
| [34048986869](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34048986869) | consensus-merge | pull_request (labeled) | PR #2 | failure | no: shim accommodation 2 |
| [34049249812](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049249812) | consensus-merge | pull_request (labeled) | PR #1 | failure | no: shim accommodation 2 |
| [34049251875](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049251875) | consensus-merge | pull_request (labeled) | PR #2 | failure | no: shim accommodation 2 |
| [34049327272](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049327272) | validate | push | main `b62cd53` | success | yes |
| [34049445909](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049445909) | validate | push | jocasta/claim-ripgrep-mbarretta | skipped | non-default branch, by design |
| [34049447809](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049447809) | validate | pull_request (synchronize) | PR #1 | success | yes |
| [34049447938](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049447938) | consensus-merge | pull_request (synchronize) | PR #1 | success | yes: `waiting: 1 of 2` |
| [34049455403](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049455403) | validate | push | jocasta/deprecate-ripgrep-mbarretta | skipped | non-default branch, by design |
| [34049457340](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049457340) | validate | pull_request (synchronize) | PR #2 | success | yes |
| [34049457370](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049457370) | consensus-merge | pull_request (synchronize) | PR #2 | success | yes: `waiting: 1 of 2` |
| [34049695634](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049695634) | validate | push | main `4d6ba51` | failure | yes: `source: unreachable` |
| [34049705584](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049705584) | stale-sweep | workflow_dispatch | main `4d6ba51` | failure | yes: PR creation refused (D3) |
| [34049819315](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049819315) | stale-sweep | workflow_dispatch (dry run) | main `4d6ba51` | success | yes |
| [34049933776](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049933776) | validate | push | main `2b9348f` | success | yes |
| [34049957928](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049957928) | stale-sweep | workflow_dispatch | main `2b9348f` | success | yes: `0 stale, 0 PRs opened` |
| [34050089367](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34050089367) | validate | push | main `b8bc178` | success | yes |
| [34050149068](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34050149068) | validate | push | main `81a58f6` | success | yes |
| [34050270035](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34050270035) | validate | push | main `1a9fb2b` | failure | yes: own-login rule |

Every run that reached a script did so through the shim's `ref: v1` checkout
(`HEAD is now at ecadd4d` in the log), that is, with the machinery exactly as
tagged.

## Authorization checks, run locally

What `validate.py --root <clone> --changed-only <before> --actor mbarretta`
prints when run on a full clone checked out at each pushed commit, with
`<before>` set as the action's `base-ref` would be (`github.event.before`;
the all-zeros SHA for the first push) and `--offline` added, so these runs
cover the schema and authorization rules but not reachability (which the
online runs before each commit covered). This is the check every `validate`
run on `main` was supposed to perform.

| Push | `<before>` → `HEAD` | Result |
|---|---|---|
| Initialize jocasta registry | `0000000` → `129d59f` | first-push marker notice; 1 file checked; `ok: 0 entries validated` |
| register ripgrep | `129d59f` → `0b53e61` | 1 file checked; ok |
| register the-silver-searcher | `0b53e61` → `3c1ee5e` | 1 file checked; ok |
| adopt ripgrep | `3c1ee5e` → `f96c82a` | 1 file checked; ok |
| deprecate the-silver-searcher | `f96c82a` → `b94ea99` | 1 file checked; ok |
| release ripgrep | `b94ea99` → `f65ea53` | 1 file checked; ok |
| register fd | `f65ea53` → `db471ce` | 1 file checked; ok |
| adoption.yaml foreign login | `e389c65` → `a66cdba` | `adoption.yaml: authorization: octocat added under 'ripgrep' by mbarretta, who may only add their own login; open a PR instead`; exit 1 |

(`740960b` and `e389c65`, the source break and fix, were run with the online
schema validator instead: red with the `source` line, then ok.)

## All Actions runs, first round (27)

The retry's 24 runs are tabulated in the retry section above; together the
sandbox has 51. First round: 27 runs. 22 failed, every one at the composite action's first step with
`ref: v7`; 4 were skipped by design (`validate` on a push to a non-default
branch); 1 succeeded (the diagnostic probe).

| Run | Workflow | Event | Ref | Result |
|---|---|---|---|---|
| [33928875466](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33928875466) | validate | push | main `129d59f` | failure |
| [33929034394](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929034394) | validate | push | e2e-probe | skipped (non-default branch) |
| [33929034506](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929034506) | e2e-probe | push | e2e-probe `0219345` | success |
| [33929055079](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929055079) | validate | push | main `0b53e61` | failure |
| [33929153848](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929153848) | validate | push | main `3c1ee5e` | failure |
| [33929161569](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929161569) | validate | push | main `f96c82a` | failure |
| [33929191026](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929191026) | validate | push | main `b94ea99` | failure |
| [33929197503](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929197503) | validate | push | main `f65ea53` | failure |
| [33929201337](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929201337) | validate | push | main `db471ce` | failure |
| [33929266255](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929266255) | validate | push | jocasta/claim-ripgrep-mbarretta | skipped |
| [33929268968](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929268968) | consensus-merge | pull_request | PR #1 | failure |
| [33929269001](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929269001) | consensus-merge | pull_request | PR #1 | failure |
| [33929269035](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929269035) | validate | pull_request | PR #1 | failure |
| [33929281155](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929281155) | validate | push | jocasta/deprecate-ripgrep-mbarretta | skipped |
| [33929283661](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929283661) | validate | pull_request | PR #2 | failure |
| [33929283700](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929283700) | consensus-merge | pull_request | PR #2 | failure |
| [33929284023](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929284023) | consensus-merge | pull_request | PR #2 | failure |
| [33929361965](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929361965) | stale-sweep | workflow_dispatch | main `740960b` | failure |
| [33929362504](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929362504) | validate | push | main `740960b` | failure |
| [33929419648](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929419648) | validate | push | jocasta/stale-fd | skipped |
| [33929422594](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929422594) | consensus-merge | pull_request | PR #3 | failure |
| [33929422620](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929422620) | validate | pull_request | PR #3 | failure |
| [33929422646](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929422646) | consensus-merge | pull_request | PR #3 | failure |
| [33929422790](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929422790) | consensus-merge | pull_request | PR #3 | failure |
| [33929460394](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929460394) | validate | push | main `e389c65` | failure |
| [33929492475](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929492475) | stale-sweep | workflow_dispatch | main `e389c65` | failure |
| [33929501613](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929501613) | validate | push | main `a66cdba` | failure |

## Discrepancies

None was fixed during this run; each is recorded here and handed off as a
deferral so it gets a decision rather than a silent edit.

### D1. Composite actions check out the wrong machinery ref (blocks every instance workflow)

**Where:** `.github/actions/validate/action.yml`, `.github/actions/consensus-merge/action.yml`,
`.github/actions/stale-sweep/action.yml`, the first step of each:

```yaml
- uses: actions/checkout@v7
  with:
    repository: mbarretta/jocasta
    ref: ${{ github.action_ref }}
```

**Observed:** in all 22 failing runs the step's resolved inputs show
`ref: v7`, and git fetched `+refs/heads/v7*:refs/remotes/origin/v7* +refs/tags/v7*:refs/tags/v7*`
from `mbarretta/jocasta`, which has no such ref, so the checkout failed and
every later step was skipped. The instance had called the action at `@v1`
and `github.action_ref` should have been `v1`.

**Cause:** inside a composite action, `github.action_ref` (like
`github.action_path` and `github.action_repository`) is re-scoped when it is
evaluated in the `with:` block of a nested `uses:` step: it names the nested
action's ref, here `actions/checkout`'s `v7`. This is long-standing GitHub
runner behaviour (the "`github.action_ref` in composite action with nested
action" issue), not a transient fault; the value is correct in a `run:`
step's `env:`.

**Confirmed workaround (sandbox probe):** a throwaway composite action on the
sandbox's `e2e-probe` branch captured the ref in a `run` step first and read
it back from `env`:

```yaml
- shell: bash
  env:
    CAPTURED_REF: ${{ github.action_ref }}
  run: echo "JOCASTA_MACHINERY_REF=${CAPTURED_REF}" >> "$GITHUB_ENV"
- uses: actions/checkout@v7
  with:
    repository: <the machinery>
    ref: ${{ env.JOCASTA_MACHINERY_REF }}
```

[Run 33929034506](https://github.com/mbarretta/jocasta-sandbox/actions/runs/33929034506)
(called as `mbarretta/jocasta-sandbox/.github/actions/probe@e2e-probe`)
logged `captured github.action_ref in run-step env = e2e-probe`, the nested
checkout's resolved input `ref: e2e-probe`, and a successful checkout at that
ref. The probe checked out the sandbox itself rather than the machinery, so
it demonstrates the mechanism, not the machinery checkout; the fix is the same
three lines in each of the three action files, plus a test in
`tests/test_template.py` (which currently pins the `ref: ${{ github.action_ref }}`
expression) and a new tag or a moved `v1`, since instances pin `@v1`.

**Consequence for the first round:** every "action no" cell in the first
round's table. Nothing GitHub-side in the plan's Verification list was
observed working then: not `validate` green on the empty registry, not CI
green on registrations, not the consensus action running, not the sweep's PR
from a dispatch, not the red run on the foreign login. The scripts were
verified by hand instead.

**Retry (2026-09-06):** the sandbox shim (copies of the three actions with
only this line changed to `ref: v1`) reached the `v1` scripts in every run
that got past the shim's own setup (16 of 16: 13 green and 3 red for a rule
the script applied), and the plan's GitHub-side
outcomes were then observed as listed in the retry section. That confirms the
fix is this one line per file and nothing else in the actions. **Status:
open, deferred.** The fix touches
`.github/actions/{validate,consensus-merge,stale-sweep}/action.yml` (capture
`github.action_ref` in a `run` step's `env` and read it back from `env` for
the nested checkout, as the probe did), `tests/test_template.py:200` (which
pins the current `ref: ${{ github.action_ref }}` expression and must pin the
corrected one), and the `v1` tag (moved, or a new tag with instances
re-pinned), and needs a push to `mbarretta/jocasta`; none of that is this
task's to do.

### D2. `template/jocasta.yaml`'s comment carries the placeholder the protocol replaces

**Where:** `template/jocasta.yaml` line 1 ("`init` replaces PLACEHOLDER_TEAM
with your team's name") versus `references/init-connect.md` step 4 ("Replace
`PLACEHOLDER_TEAM` with the confirmed team name, in that file only. Then
confirm nothing else carries the marker: `grep -rn PLACEHOLDER_TEAM <workdir>`
must print nothing").

**Observed:** following the step literally rewrites the comment to "`init`
replaces jocasta-sandbox with your team's name" in the instance
(`129d59f`, `jocasta.yaml` line 1). Following it non-literally (replace only
the `team:` value) leaves the marker in the comment and fails the step's own
grep check. Either the comment should not name the marker, or the check
should be scoped to the `team:` line. Cosmetic; the workflows and validator
do not read the comment.

### D3. `init` promises the default `GITHUB_TOKEN` suffices; the sweep cannot open its PR with it (confirmed in the retry)

**Where:** `references/init-connect.md`, "What `init` does not do": "The
default `GITHUB_TOKEN` is enough for the template workflows."

**Observed (first round):** unverified, because no workflow reached its
script (D1); the sweep's PR #3 was opened with a user token, which does not
exercise the path.

**Observed (retry):** with the shim in place, `stale-sweep.yml` via
`workflow_dispatch` on a registry with one dead source
([run 34049705584](https://github.com/mbarretta/jocasta-sandbox/actions/runs/34049705584))
ran `stale_sweep.py`, which force-pushed its proposal branch
`jocasta/stale-fd` as `github-actions[bot]`
([`cdac4e5`](https://github.com/mbarretta/jocasta-sandbox/commit/cdac4e516c890f9b736e4c29e5de12030caaae59),
the correct `route: stale-source` change) and then failed at
`gh pr create` with

```
GraphQL: GitHub Actions is not permitted to create or approve pull requests (createPullRequest)
```

reporting `1 failed` and exiting 1 (the workflow run is red, which is the
right signal). The sandbox's setting at the time, read with
`gh api repos/mbarretta/jocasta-sandbox/actions/permissions/workflow`, was
`{"default_workflow_permissions":"read","can_approve_pull_request_reviews":false}`,
GitHub's default for a repository created by `gh repo create` as `init`
does. So the sentence is not true as written: the token's *scopes*
(`contents: write`, `pull-requests: write` in the template) are enough, but
the repository must also have "Allow GitHub Actions to create and approve
pull requests" turned on, or the weekly sweep will push branches and never
open the PR they are for. Fix candidates, for the deferral: (a) change the
sentence in `init-connect.md` and add the setting to `init`'s steps (one
`gh api -X PUT repos/<org>/<repo>/actions/permissions/workflow -F can_approve_pull_request_reviews=true -f default_workflow_permissions=read`;
expected to work with the `repo` scope, but not verified in this run, where
the call was not made) or to the template README's setup notes; (b)
alternatively document a `JOCASTA_TOKEN` personal token for the sweep, which
the template's `token:` input already accepts. Which is the user's call. Side
observation, not a separate discrepancy: when PR creation fails the sweep has
already pushed the branch, so an instance in this state accumulates
`jocasta/stale-<name>` branches with no PR; the next successful sweep
force-pushes the same branch and opens the PR, so nothing is lost.

## Known limits, as instructed

- **One account.** Everything that needs a second or third GitHub account was
  not exercised: two non-owner approvals merging a `deprecation` or
  `ownership` PR by consensus, an owner's approval merging by the `owner`
  route, an owner's request-for-changes blocking, and the post-merge state of
  a claimed entry. The consensus path was taken exactly as far as one account
  allows: PRs opened by the skill's recipe, and `consensus_merge.py` evaluating
  them and waiting with `1 of 2 non-owner voices`.
- **Workflow-token PRs and `pull_request` triggers.** The rule that a PR
  opened with `GITHUB_TOKEN` starts no `pull_request` workflows was expected
  but not observable in either round: in the first the sweep never ran (D1)
  and its PR was opened with a user token; in the retry the sweep ran but
  GitHub refused to let it open a PR (D3), and changing that repository
  setting was outside what this run could do.
- **`delete_repo` scope.** The sandbox could not be deleted (both rounds) and
  is left in place; the two commands to delete it are in step 15.

## Sandbox state at the end

`mbarretta/jocasta-sandbox`, private. `main` at `1a9fb2b`, nineteen commits.
First round (ten): `129d59f` Initialize, `0b53e61` register ripgrep,
`3c1ee5e` register the-silver-searcher, `f96c82a` adopt ripgrep, `b94ea99`
deprecate the-silver-searcher, `f65ea53` release ripgrep, `db471ce` register
fd, `740960b` break fd source, `e389c65` fix fd source, `a66cdba`
foreign-login adoption edit. Retry (nine): `e46792b` shim, `31d8fee`
register jq, `f6d4bad` shim checkout, `b62cd53` adopt jq, `4d6ba51` break fd
source, `2b9348f` fix fd source, `b8bc178` deprecate jq, `81a58f6` release
fd, `1a9fb2b` foreign-login adoption edit. Entries: `fd` (active, unowned),
`jq` (deprecated, route `owner`, owner `mbarretta`), `ripgrep` (active,
unowned), `the-silver-searcher` (deprecated, route `owner`).
`adoption.yaml`: `jq: [mbarretta, octocat]`, `ripgrep: [mbarretta, octocat]`
(both deliberate violations). PRs: #1 `claim ripgrep` open (2 commits, the
second empty), #2 `deprecate ripgrep` open (same), #3 `deprecate fd (stale
source)` closed. Branches: `main`, `jocasta/claim-ripgrep-mbarretta`,
`jocasta/deprecate-ripgrep-mbarretta`, `jocasta/stale-fd` (now at the bot's
`cdac4e5`, no PR), `e2e-probe`. Labels added: `ownership`, `deprecation`,
`stale-source`. The shim is on `main`: `.github/actions/{validate,consensus-merge,stale-sweep}/action.yml`
and the three rewired workflows, so **this sandbox is not a clean `init`
product and should not be reused as one**; delete it, or re-run `init` into
a new repository, before any further verification. Actions setting
`can_approve_pull_request_reviews` is still `false`. 51 runs in all: 31
failure (22 first-round checkout failures, 6 shim-accommodation failures, 3
red for the right reason), 6 skipped, 14 success (13 retry, 1 probe).
