# adopt and unadopt

Two modes that record whether the caller uses a tool. Adoption is the signal search ranks on after fit (charter R-7): an entry three colleagues have adopted is a better first answer than one nobody has. Both modes edit one file, `adoption.yaml`, commit directly to the default branch, and never touch an entry.

## What is recorded, and by whom

Adoption is self-declared, per login, and public to the team: `adoption.yaml` maps each tool name to the list of GitHub logins who have said they use it, nothing more. A person adds only their own login and removes only their own login; the skill never records anyone else's, never infers adoption from installs, shell history, or commits, and never aggregates or anonymizes the list, because the file is the whole record and anyone with read access to the registry can open it. What a reader learns is exactly what each named person chose to say about themselves, and each of them can withdraw it with `unadopt`. The validator enforces the same boundary on push: a direct commit to `adoption.yaml` may add or remove the actor's own login and no one else's (charter T-2 is answered here; N-5 supplies the identity).

## Shared preconditions

1. `gh auth status` succeeds and `gh api user --jq .login` returns the caller's login. That login is the only one either mode writes. Never ask the user for it and never read it from git config.
2. The registry is resolved and the snapshot is current: `git -C ~/.cache/jocasta/<org>/<repo> pull --ff-only` (SKILL.md, Snapshot). If the pull fails, report it and stop.
3. `entries/<name>.md` exists in the snapshot. If it does not, nothing is written; the response is that `<name>` does not appear in the archive, followed by the two or three nearest entry names if any are close. Deprecated entries are still in the archive and may be adopted; say that the entry is retired in the closing line.

## `adopt <name>`

1. Read `adoption.yaml`. An absent file, an empty file, and `{}` all mean nobody has recorded adoption yet.
2. If the caller's login is already listed under `<name>`, nothing is written. Say so and stop.
3. Add the login: append it to the list under `<name>`, creating the key if it is missing, and write the mapping back with its keys sorted. Do not reorder, rename, or edit any other login or key; the diff must show one added login and nothing else. Keep the file's leading comment lines, if any, and the one-line flow style shown in `references/schema.md`:

   ```yaml
   example-cli: [alice, bob]
   legacy-script: [carol]
   ```

4. Run the validator over the snapshot (SKILL.md, Running the validator locally). If it fails, show its output verbatim, fix, and re-run; never bypass it.
5. Commit and push:

   ```
   git -C <snapshot> add adoption.yaml
   git -C <snapshot> commit -m "adopt <name>"
   git -C <snapshot> push
   ```

   If the push is rejected, the default branch moved: run `git -C <snapshot> pull --rebase` and push once more. If it is rejected again, stop and report the state of the snapshot rather than retrying; the full recipe is in `references/write-paths.md`.

6. Close with the plain statement, then at most one sentence of register:

   > Committed `adopt <name>` to `main` of `<org>/<repo>` (`<sha>`): added `<login>` under `<name>` in `adoption.yaml`.

## `unadopt <name>`

The mirror image. Same preconditions, same file, same push recipe.

1. If the caller's login is not listed under `<name>`, nothing is written. Say so and stop.
2. Remove the login from the list under `<name>`. If the list is then empty, remove the key. Change nothing else; the diff must show one removed login (and possibly its now-empty key) and nothing else.
3. Validate, then commit with the message `unadopt <name>` and push with the same rebase-and-retry rule.
4. Close with the plain statement:

   > Committed `unadopt <name>` to `main` of `<org>/<repo>` (`<sha>`): removed `<login>` from `<name>` in `adoption.yaml`.

## What the push check enforces

The instance's `validate` workflow runs `validate.py --changed-only <ref> --actor <login>` on every push to the default branch, with `<ref>` the commit the branch was at before the push (`github.event.before`) and `<login>` the GitHub account that pushed. Besides the schema, it applies the `authorization` rule from `references/schema.md`: between the two commits, under every key of `adoption.yaml`, the only login that may appear or disappear is the actor's own, and any `entries/*.md` the push added must name the actor as owner while any it modified must have been the actor's at `<ref>`. A violation is one line, `adoption.yaml: authorization: <detail>; open a PR instead`, and the workflow goes red. If the skill followed the steps above, that line is not reachable: it exists for a hand edit that touched someone else's login.

Where the rule's reach ends, so nobody mistakes it for more than it is:

- **Pull requests are not authorized by this rule.** On `pull_request` events the workflow checks out GitHub's synthetic merge commit, and the check skips merge commits with a notice; the PR path is gated by review and the consensus action instead (charter D-3, P-5). The same skip applies to pushes made by `github-actions[bot]`, which is how a consensus merge lands. A consequence: on a `synchronize` event GitHub sets `before` to the previous head of the PR branch, so a diff against it would see only the newly pushed commits; that does not matter here because the PR path is skipped by construction.
- **It reads what git shows it.** A first push, or a `before` that is not in the checkout, treats every file as added, so every entry must be the pusher's and every adopter listed must be the pusher. A rewritten history it cannot diff is treated the same way. Blocking force pushes on the default branch is branch protection's job, and a team that wants it turns it on in the repository settings; the validator does not reach there (charter N-5).
- **Only `entries/*.md` and `adoption.yaml` are checked.** `jocasta.yaml`, the workflows, and the READMEs are governed by who can push to the repository at all.
- **It runs after the push, not before it.** A red `validate` run means the commit is already on the default branch; the workflow cannot undo it, it names the problem so a person can revert. To make a red check block the branch, enable branch protection on the default branch requiring the `validate` status check. The template does not set this up; `init` creates no branch protection.
- **The merge-commit skip is a shape test, not a provenance test.** The check skips any `HEAD` with two parents because that is what a PR merge looks like; it does not confirm the merge came from a pull request. Someone with push access can wrap an edit to another person's entry, or to another login in `adoption.yaml`, in a local `git merge --no-ff` and push a merge commit the check waves through. The backstop is the same branch protection: require pull requests on the default branch, and direct pushes, merge-shaped or not, cannot land.
