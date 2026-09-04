# Write paths: direct commit or pull request

Every mode that changes the registry lands its change in one of two ways (charter D-3): a **direct commit** to the instance's default branch, or a **pull request** that the instance's `consensus-merge` workflow merges once it has the votes. Which one is decided here, once, by who the caller is relative to the file they are touching. The model never chooses; it looks the situation up in the table and follows the recipe. The push authorization check in the instance's `validate.yml` (`validate.py --changed-only`) enforces the same table on the server side, so a direct commit that the table does not allow is caught even if the skill gets it wrong: the workflow runs after the push lands and turns the run red with an `authorization` line. It does not undo the push; only branch protection turns a red check into a refusal (see Authorization on push, below) (charter P-4, P-5).

Throughout, `<snapshot>` is `~/.cache/jocasta/<org>/<repo>` (SKILL.md, Snapshot), `<login>` is the caller's GitHub login from `gh api user --jq .login`, and `<default>` is the instance's default branch (`gh api repos/<org>/<repo> --jq .default_branch`).

## Decision table

| The caller wants to | And the caller is | Path | Details |
|---|---|---|---|
| `register` a new entry | anyone (they become the owner) | direct commit | Commit message `register <name>`. `references/register.md`. |
| `deprecate <name>` | the entry's owner | direct commit | Sets `status: deprecated`, `route: owner`. Commit message `deprecate <name>`. |
| `deprecate <name>` | not the owner (including when the entry is unowned) | PR | Branch `jocasta/deprecate-<name>-<login>`, label `deprecation`, `route: consensus`. |
| `transfer <name> <login>` | the entry's owner | direct commit | Commit message `transfer <name> to <login>`. |
| `transfer <name> <login>` | not the owner | refused | Nothing written. Point at `claim` (for themselves) or at the owner. |
| `release <name>` | the entry's owner | direct commit | Sets `owner: ~`. Commit message `release <name>`. |
| `release <name>` | not the owner | refused | Nothing written. |
| `claim <name>` | not the owner (the usual case: the entry is unowned) | PR | Branch `jocasta/claim-<name>-<login>`, label `ownership`. |
| `claim <name>` | already the owner | nothing to do | Say so; nothing written. |
| `adopt <name>` / `unadopt <name>` | anyone, editing only their own login | direct commit | `adoption.yaml` only. Commit message `adopt <name>` / `unadopt <name>`. `references/adoption.md`. |
| edit `adoption.yaml` for another login | anyone | refused | Adoption is self-declared; the validator turns the push's `validate` run red. |
| flag a dead source | the `stale-sweep` workflow, not a person | PR | Branch `jocasta/stale-<name>`, labels `stale-source` and `deprecation`, `route: stale-source`. Opened by the machinery, merged by consensus or closed by the owner after fixing the source. |

The rule behind the table: **touching an entry you do not own is never silent** (P-5). If the caller owns the file, or is editing only their own line in `adoption.yaml`, the change is theirs and commits directly. Anything else leaves a reviewable artifact that other people decide on. No mode edits more than one file per write, and no mode ever deletes an entry file: entries are deprecated, not deleted.

The `deprecate` and `claim` protocols themselves, including what goes in the frontmatter and the closing messages, are in `references/ownership.md`. This file only says how the change reaches the repo.

Four modes are outside the table because they never write to a registry that has other people's work in it. `search` and `show` read only. `connect` writes only `~/.config/jocasta/config.yaml`. `init` commits and pushes `Initialize jocasta registry` to a repo it has just created, empty and with no other author yet, which SKILL.md's mode table calls `direct commit (to the new repo)`; the steps are in `references/init-connect.md`.

## Direct commit recipe

Used by `register`, owner `deprecate`/`transfer`/`release`, and `adopt`/`unadopt`.

1. Refresh: `git -C <snapshot> pull --ff-only`. If it fails, stop and report (SKILL.md, Snapshot).
2. Confirm the snapshot is on `<default>` with a clean tree: `git -C <snapshot> status --porcelain` prints nothing. If a previous write left a branch checked out, `git -C <snapshot> checkout <default>` first.
3. Make the edit: exactly one file, `entries/<name>.md` or `adoption.yaml`.
4. Validate (SKILL.md, Running the validator locally). Show failures verbatim, fix, re-run; never bypass.
5. Commit:

   ```
   git -C <snapshot> add <the one file>
   git -C <snapshot> commit -m "<message from the table>"
   ```

6. Push: `git -C <snapshot> push origin <default>`.
7. If the push is rejected, follow the retry recipe below.
8. Read back the commit SHA (`git -C <snapshot> rev-parse --short HEAD`) for the plain statement.

## Push rejected: the retry recipe

A push is rejected when someone else committed to `<default>` since the snapshot was refreshed. Retry exactly once:

```
git -C <snapshot> pull --rebase origin <default>
```

- **Rebase succeeds:** re-run the validator over the rebased tree (the other commit may have registered the same name or changed the same entry), then `git -C <snapshot> push origin <default>` again.
- **Rebase conflicts:** `git -C <snapshot> rebase --abort`. The snapshot now holds a local commit that has not landed; say so, name the conflicting file, and stop. Do not resolve the conflict silently and do not reset the snapshot, because the local commit is the user's work.
- **Second push also rejected:** stop and report the rejection text verbatim. The user can run the mode again after the snapshot is refreshed; the retry budget is one, not a loop.

Either way, the closing plain statement says what state the snapshot is in: pushed with the SHA, or holding an unpushed commit and why.

## Pull request recipe

Used by non-owner `deprecate` and by `claim`. The PR changes one file, carries one label, and says why in its body; that is everything the `consensus-merge` workflow needs.

1. Refresh: `git -C <snapshot> pull --ff-only`, on `<default>` with a clean tree, as above.
2. Branch: `git -C <snapshot> checkout -b jocasta/<mode>-<name>-<login>` where `<mode>` is `deprecate` or `claim`. If the branch already exists locally or on the remote, an earlier attempt is still in flight: look for its PR with `gh pr list --repo <org>/<repo> --head jocasta/<mode>-<name>-<login>`, report the URL, and stop rather than opening a second one.
3. Edit `entries/<name>.md` and nothing else. Validate as for a direct commit.
4. Commit and push the branch:

   ```
   git -C <snapshot> add entries/<name>.md
   git -C <snapshot> commit -m "<mode> <name>"
   git -C <snapshot> push -u origin jocasta/<mode>-<name>-<login>
   ```

5. Make sure the label exists (the template ships no labels; `gh pr create --label` fails on an unknown one):

   ```
   gh label create <label> --repo <org>/<repo> --description "<description>"
   ```

   with `deprecation` / "Proposes retiring an entry" or `ownership` / "Proposes a change of owner". If `gh` says the label already exists, continue.

6. Open the PR:

   ```
   gh pr create --repo <org>/<repo> --base <default> --head jocasta/<mode>-<name>-<login> \
     --title "<mode> <name>" --label <label> --body "<body>"
   ```

   The body states the reason in plain words, then how the PR is decided. Template:

   > **Why:** <the caller's reason, one or two sentences, as they gave it>
   >
   > Opened by `<login>` with the jocasta skill. The `consensus-merge` workflow merges this when the entry's owner approves it, or when two people who are not the owner have voiced support (the author counts as one). If the owner requests changes it stays open for discussion. It is never closed automatically.

7. Return the snapshot to the default branch so later reads are not made from the PR branch: `git -C <snapshot> checkout <default>`.
8. Read the PR URL from `gh pr create`'s output for the plain statement.

A pushed branch whose PR could not be opened (step 6 failed) is reported as exactly that: branch pushed, PR not opened, with the error text. The user can open it by hand or re-run the mode.

## What the consensus action does with the PR

`scripts/consensus_merge.py`, run by the instance's `consensus-merge` workflow on every open, label, push, and review event:

- refuses (comments once, does not merge) any PR whose changed-file set is not exactly one file matching `entries/<name>.md`, with a kebab-case name, directly under `entries/`: two or more files, `adoption.yaml`, `entries/README.md`, a file in a subdirectory of `entries/`, a deleted entry, and a renamed entry all fail this gate;
- reads the entry's owner from the default branch; an entry that is unowned (`owner: ~`) or new has no owner;
- merges when the owner's latest review is an approval (route `owner`), or when two distinct non-owner voices exist: the author (if not the owner) plus reviewers whose latest review is an approval (route `consensus`);
- does not merge while the owner's latest review requests changes, and says so once in a comment;
- otherwise waits, printing how many voices are still needed;
- merges with a squash commit whose subject names the route, for example `deprecate example-cli (route: consensus)`;
- never closes a PR, and does nothing on a PR that is already merged or closed.

Because the merge is a squash of a one-file branch, the resulting commit on `<default>` looks exactly like a direct commit of the same edit. The full decision rules with worked examples are in `references/ownership.md`.

One trigger caveat for the `stale-source` row. A PR that `stale_sweep.py` opens with the workflow's own `GITHUB_TOKEN` does not start the `consensus-merge` workflow's `opened` run, because GitHub does not let a workflow token trigger further workflows; the same goes for the instance's `validate` run on that PR. The script first runs on the first human event on the PR: a review, a label, or a push to its branch. A team that wants the sweep's PRs treated like a person's from the moment they open sets the `JOCASTA_TOKEN` secret to a personal access token or GitHub App token; the template's `stale-sweep.yml` passes it through when present. Nothing in this file changes for the skill: it never opens `stale-source` PRs itself.

## Authorization on push

The instance's `validate.yml` runs `validate.py --changed-only <before> --actor <pusher>` on every push to the default branch, after the push has landed. It turns the run red, with one `authorization` line, for a direct push that adds an entry the pusher does not own, edits an entry the pusher did not own before the push (transfer and release by the owner are allowed), deletes an entry, or changes any login but the pusher's own in `adoption.yaml`. It does not reject or revert the push: git has already accepted it, and the red run is the signal to a person to revert. Merges performed by the consensus workflow are exempt; the PR path already gated them.

Two limits follow, and the same repository setting backstops both. A red run only blocks the branch when branch protection on the default branch requires the `validate` status check. And the exemption is a shape test, not a provenance test: the check skips any `HEAD` with two parents (and any push by `github-actions[bot]`) because that is what a PR merge looks like, so someone with push access can wrap an edit to another person's entry in a local `git merge --no-ff` and push a merge commit the check waves through; requiring pull requests on the default branch closes that. `init` sets up neither; a repository admin does, once. This is the mechanism that makes the direct-commit column safe to offer at all (charter P-4); the rule's full reach is in `references/adoption.md` and the code in `scripts/validate.py`.
