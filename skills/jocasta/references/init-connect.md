# init and connect

Two modes that point a machine at a registry. `init` creates the registry first; `connect` assumes it exists. Neither deploys anything: the result is a GitHub repo whose thin workflows call this plugin's composite actions at a pinned tag, plus one local config file (charter U-4, N-1, R-9).

Both modes end with the plain-statement line required by SKILL.md's voice rule: what was created, pushed, or written, with paths, before any character text.

## Shared preconditions

1. `gh auth status` succeeds. If it does not, stop and tell the user to run `gh auth login`; do not continue with a partially authenticated session.
2. `gh api user --jq .login` returns the caller's login. Keep it; it is the commit author's identity for `init` and the value `connect` should confirm can see the repo.
3. `${CLAUDE_PLUGIN_ROOT}` resolves to a checkout of this plugin. `init` needs `${CLAUDE_PLUGIN_ROOT}/template/` to exist; if it does not, the plugin install is broken and the response says so.

## `init <org>/<name> [--public]`

Creates a new registry repo from the bundled template and connects this machine to it. Private by default; `--public` makes it public. The `<org>` may be a user login.

Before running anything, confirm two inputs with the user in one question:

- **Visibility.** Restate what was asked (private unless `--public`) so an accidental public registry does not happen.
- **Team name.** The template's `jocasta.yaml` carries `team: PLACEHOLDER_TEAM`. Propose `<name>` as the team name; accept whatever the user gives. This is a display string, not an identifier, and it does not have to match the repo.

Then, in order. Stop at the first failure and report what did and did not happen; never leave the user guessing whether a repo was created.

1. **Create the repo.**

   ```
   gh repo create <org>/<name> --private --description "Jocasta tool registry"
   ```

   With `--public`, pass `--public` instead of `--private`. If `gh` reports the repo already exists, stop: `init` never writes into an existing repo. Offer `connect <org>/<name>` if it is already a registry.

2. **Let Actions open pull requests.** The stale sweep opens its deprecation pull requests with the workflow's own token, and GitHub refuses that unless the repository's "Allow GitHub Actions to create and approve pull requests" setting is on; `gh repo create` leaves it off.

   ```
   gh api -X PUT repos/<org>/<name>/actions/permissions/workflow -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true
   ```

   `-F` rather than `-f` for the second field, so the boolean is sent as a boolean and not the string `"true"`. The call needs admin on the new repo, which its creator has unless an organization policy withholds it. If GitHub refuses the call, this is the one step that is not a stop: continue, and say so in the closing statement. The registry works without it, except that the sweep pushes its proposal branches and then fails to open their pull requests until an admin turns the setting on or the `JOCASTA_TOKEN` secret is set (see "What `init` does not do" below).

3. **Clone it to a working directory** outside the snapshot cache (a fresh temporary directory is fine):

   ```
   gh repo clone <org>/<name> <workdir>
   ```

   The clone is empty. Create the default branch explicitly so the workflows' `push` trigger has a known branch name: `git -C <workdir> checkout -b main`.

4. **Copy the template verbatim**, including dotfiles:

   ```
   cp -R "${CLAUDE_PLUGIN_ROOT}/template/." <workdir>/
   ```

   Do not edit, reorder, or "improve" anything copied. The template is owned by the plugin and pinned to the actions by `machinery_ref`; local edits are the version-skew problem D-1 warned about.

5. **Replace the one placeholder.** `jocasta.yaml` contains `team: PLACEHOLDER_TEAM`. Replace `PLACEHOLDER_TEAM` with the confirmed team name, in that file only. Then confirm nothing else carries the marker: `grep -rn PLACEHOLDER_TEAM <workdir>` must print nothing. Leave `schema_version` and `machinery_ref` as the template has them.

6. **Commit and push.**

   ```
   git -C <workdir> add -A
   git -C <workdir> commit -m "Initialize jocasta registry"
   git -C <workdir> push -u origin main
   ```

   The commit message is fixed. The push triggers the instance's `validate.yml`, which must pass on an empty `entries/` directory; if the user later reports it red, the machinery is at fault, not their registry.

7. **Write the local config.**

   ```
   mkdir -p ~/.config/jocasta
   printf 'registry: %s\n' "<org>/<name>" > ~/.config/jocasta/config.yaml
   ```

   If a config already exists pointing at a different registry, say which one it pointed at before overwriting it.

8. **Seed the snapshot** so the first `search` is instant: `gh repo clone <org>/<name> ~/.cache/jocasta/<org>/<name> -- --depth 1`. Skip silently if it already exists.

9. **Close with the plain statement**, then at most one sentence of register. For example:

   > Created `<org>/<name>` (private) and pushed the initial commit `Initialize jocasta registry` to `main`. Wrote `~/.config/jocasta/config.yaml` with `registry: <org>/<name>`.

   If you stopped partway, the statement names the last step that completed and the first that did not, with the error text.

   If step 2 was refused, the statement adds one sentence saying so and naming the two remedies: an admin turns on "Allow GitHub Actions to create and approve pull requests", or a `JOCASTA_TOKEN` secret is added.

What `init` does not do: it does not create GitHub teams, branch protection, secrets, or environments; beyond the one Actions setting in step 2, it does not enable or configure Actions past what the workflow files themselves declare; it does not add collaborators. The workflow token alone does not cover every template workflow: `validate` and `stale-sweep` run with the repository's own `GITHUB_TOKEN`, which can read only the registry itself and can open pull requests only while the step 2 setting is on. A caller who is not an admin of the new repo (step 2 refused), or whose tools' sources live in private repositories, adds a repository secret named `JOCASTA_TOKEN` holding a personal access token or GitHub App token that can read those sources and open pull requests on the registry; `validate.yml` and `stale-sweep.yml` use it in place of the workflow token whenever it is present. Anyone who can push to the repo can use the registry; that is GitHub's permission model doing the work (charter N-5).

## `connect <org>/<repo>`

Points this machine at a registry that already exists.

1. **Check the repo is a registry.**

   ```
   gh api repos/<org>/<repo>/contents/jocasta.yaml --jq .name
   ```

   Success prints `jocasta.yaml`. A 404 means either the repo is not a registry or the caller cannot see it; `gh` does not distinguish, so the response says both possibilities and stops. Do not write config to a repo that failed this check.

2. **Write the local config** exactly as in `init` step 7, with the same warning if an existing config pointed elsewhere.

3. **Seed the snapshot** as in `init` step 8.

4. **Close with the plain statement:**

   > Wrote `~/.config/jocasta/config.yaml` with `registry: <org>/<repo>`.

   If the config previously pointed at another registry, the statement names it.

`connect` never touches the registry repo itself. Its only write is the local config file.

## Switching registries

`connect` overwrites the single config file, so a person on two teams switches by running `connect` again. Per-project pinning is the first rule of config discovery in SKILL.md: a checkout of a registry repo (any directory with `jocasta.yaml`) uses that registry regardless of the config file.
