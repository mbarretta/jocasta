"""Structural checks on the init/connect protocol reference.

``skills/jocasta/references/init-connect.md`` is what the skill follows to
create a registry. These pin the parts the end-to-end run (docs/e2e-report.md,
D3) showed are load-bearing: a repository made by ``gh repo create`` does not
let Actions open pull requests, so ``init`` must turn that setting on right
after creating the repo or the weekly stale sweep pushes branches it can never
open pull requests for; the closing paragraph must not promise that the
workflow token alone is enough, and must describe the short-lived-token route
(charter D-10: the OctoSTS App, never a stored personal access token) for a
caller who cannot change the setting; ``init`` must substitute and grep-check
the trust policy's repo placeholder alongside the team one; and ``connect``
must keep pointing at the right ``init`` steps by number once a step is
inserted.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_CONNECT_MD = REPO_ROOT / "skills" / "jocasta" / "references" / "init-connect.md"

# The one repository setting init changes. `-F` (not `-f`) so the boolean is
# sent as a boolean; the field names are GitHub's, read back from a sandbox
# with `gh api repos/<o>/<r>/actions/permissions/workflow`.
PERMISSIONS_CALL = (
    "gh api -X PUT repos/<org>/<name>/actions/permissions/workflow"
    " -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true"
)

# Charter D-10: the App a team installs once to mint minutes-lived tokens.
OCTO_STS_APP = "https://github.com/apps/octo-sts"
STS_POLICY = ".github/chainguard/jocasta.sts.yaml"
# The standing credential D-10 rejects; assembled so this file is not a hit.
RETIRED_SECRET = "JOCASTA_" + "TOKEN"


def _text() -> str:
    assert INIT_CONNECT_MD.is_file(), "references/init-connect.md is missing"
    return INIT_CONNECT_MD.read_text(encoding="utf-8")


def _section(text: str, heading_pattern: str) -> str:
    """Return the body of the first ``##`` section whose heading matches the pattern."""
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        if re.search(heading_pattern, heading, re.IGNORECASE):
            return body
    raise AssertionError(f"no '## ' heading matching {heading_pattern!r}")


def _numbered_steps(section: str) -> list[tuple[int, str, str]]:
    """``(number, bold title, body)`` for each ``N. **Title.** ...`` step, in order."""
    pieces = re.split(r"^(\d+)\. \*\*(.+?)\*\*", section, flags=re.MULTILINE)
    return [
        (int(pieces[i]), pieces[i + 1], pieces[i + 2])
        for i in range(1, len(pieces), 3)
    ]


def test_init_lets_actions_open_pull_requests_right_after_creating_the_repo():
    steps = _numbered_steps(_section(_text(), r"`init "))
    assert steps[0][1].lower().startswith("create the repo")
    _, _, body = steps[1]
    assert PERMISSIONS_CALL in body, body
    # One sentence of why: the sweep opens pull requests with the workflow token.
    assert re.search(r"sweep.*pull requests?.*workflow", body, flags=re.IGNORECASE | re.DOTALL), body
    # A refusal (no admin on the new repo) is not a stop; the fallback is the
    # short-lived App token, never a stored secret.
    assert "admin" in body and "OctoSTS" in body, body


def test_init_steps_are_consecutive_and_connect_cites_them_by_the_right_number():
    text = _text()
    steps = _numbered_steps(_section(text, r"`init "))
    assert [n for n, _, _ in steps] == list(range(1, len(steps) + 1))
    by_title = {title: n for n, title, _ in steps}
    config = next(n for title, n in by_title.items() if title.startswith("Write the local config"))
    snapshot = next(n for title, n in by_title.items() if title.startswith("Seed the snapshot"))

    connect = _section(text, r"`connect ")
    assert f"as in `init` step {config}" in connect, connect
    assert f"as in `init` step {snapshot}" in connect, connect
    assert not re.findall(rf"`init` step (?!{config}\b|{snapshot}\b)\d+", connect), connect


def test_init_substitutes_and_grep_checks_both_placeholders():
    steps = _numbered_steps(_section(_text(), r"`init "))
    (body,) = [b for _, title, b in steps if title.lower().startswith("replace the placeholders")]
    assert "PLACEHOLDER_TEAM" in body and "`jocasta.yaml`" in body, body
    assert "PLACEHOLDER_REPO" in body and f"`{STS_POLICY}`" in body, body
    assert "<org>/<name>" in body, body
    # One grep covers both markers, so neither can leak into the initial commit.
    assert re.search(r"grep -rn PLACEHOLDER_ <workdir>", body), body


def test_init_offers_the_octo_sts_app_as_an_optional_step_and_says_what_it_buys():
    steps = _numbered_steps(_section(_text(), r"`init "))
    (body,) = [b for _, title, b in steps if "octosts" in title.lower().replace("-", "")]
    assert "optional" in body.lower(), body
    assert OCTO_STS_APP in body, body
    # What it buys: sweep PRs that trigger pull_request workflows; private sources.
    assert re.search(r"`pull_request`", body) and "private" in body, body


def test_what_init_does_not_do_describes_the_short_lived_token_model():
    init = _section(_text(), r"`init ")
    (paragraph,) = [p for p in init.split("\n\n") if p.startswith("What `init` does not do")]
    assert "`GITHUB_TOKEN` is enough" not in paragraph, paragraph
    assert "OctoSTS" in paragraph and "admin" in paragraph, paragraph
    assert "short-lived" in paragraph or "minutes" in paragraph, paragraph
    # A PAT is discouraged, not documented as a route.
    assert re.search(r"personal access token", paragraph), paragraph
    assert RETIRED_SECRET not in paragraph
    # The charter N-5 sentence that closes the paragraph stays.
    assert "charter N-5" in paragraph


def test_the_retired_secret_is_named_nowhere_in_the_reference():
    assert RETIRED_SECRET not in _text()
