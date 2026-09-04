"""Tests for scripts/consensus_merge.py with every ``gh`` call faked (no network).

The fake routes each ``gh`` invocation by its arguments and records it, so a
test can assert both the decision (merged, commented, waited) and that the
script never issued a call it must not (``pr close``, a merge on a multi-file
PR, a second identical comment).
"""

from __future__ import annotations

import subprocess
import urllib.parse
from pathlib import Path

import pytest

import consensus_merge as cm
import jocasta_common as jc

REPO = "example-org/registry"
PR = 7
DEFAULT_BRANCH = "main"
ENTRY_PATH = "entries/example-cli.md"

OWNED_ENTRY = """---
name: example-cli
owner: alice
source: https://github.com/example-org/example-cli
kind: cli
registered: 2026-09-01
status: active
---
Lists the files in a directory tree that changed since a given git ref.
"""

RELEASED_ENTRY = OWNED_ENTRY.replace("owner: alice", "owner: ~")


# --- fake gh -----------------------------------------------------------------


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


def _pr_json(
    *,
    author: str = "bob",
    labels: tuple[str, ...] = ("deprecation",),
    state: str = "open",
    merged: bool = False,
    head_ref: str = "jocasta/deprecate-example-cli-bob",
) -> dict:
    return {
        "number": PR,
        "state": state,
        "merged": merged,
        "user": {"login": author},
        "labels": [{"name": name} for name in labels],
        "head": {"ref": head_ref, "sha": "abc123"},
        "base": {"ref": DEFAULT_BRANCH, "repo": {"default_branch": DEFAULT_BRANCH}},
        "title": "deprecate example-cli",
        "html_url": f"https://github.com/{REPO}/pull/{PR}",
    }


def _file(filename: str = ENTRY_PATH, status: str = "modified", previous: str | None = None) -> dict:
    data = {"filename": filename, "status": status}
    if previous is not None:
        data["previous_filename"] = previous
    return data


def _review(login: str, state: str, submitted_at: str = "2026-09-04T12:00:00Z") -> dict:
    return {"user": {"login": login}, "state": state, "submitted_at": submitted_at}


class FakeGh:
    """Routes ``gh`` calls by endpoint and records every call made."""

    def __init__(
        self,
        pr: dict,
        files: list[dict],
        reviews: list[dict],
        *,
        base_entry: str | None = OWNED_ENTRY,
        comments: list[dict] | None = None,
        merge_rc: int = 0,
    ):
        self.pr = pr
        self.files = files
        self.reviews = reviews
        self.base_entry = base_entry
        self.comments = list(comments or [])
        self.merge_rc = merge_rc
        self.calls: list[list[str]] = []

    # -- helpers --------------------------------------------------------------

    @property
    def merges(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] == ["pr", "merge"]]

    @property
    def posted_comments(self) -> list[str]:
        out = []
        for call in self.calls:
            if call[0] == "api" and "POST" in call and "/comments" in " ".join(call):
                idx = call.index("-f")
                out.append(call[idx + 1].removeprefix("body="))
        return out

    def assert_never_closed(self) -> None:
        for call in self.calls:
            assert "close" not in call, f"consensus_merge must never close a PR: {call}"
            if call[0] == "api":
                joined = " ".join(call)
                assert "state=closed" not in joined, f"consensus_merge must never close a PR: {call}"

    # -- dispatch -------------------------------------------------------------

    def __call__(self, args: list[str], timeout: float) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        if args[:2] == ["pr", "merge"]:
            return _completed(self.merge_rc, stderr="" if self.merge_rc == 0 else "merge refused")
        assert args[0] == "api", args
        method, endpoint, fields = _parse_api_args(args[1:])
        path, _, query = endpoint.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        page = int(params.get("page", "1"))

        prefix = f"repos/{REPO}"
        assert path.startswith(prefix), path
        path = path[len(prefix) :]

        if path == f"/pulls/{PR}":
            return _completed(0, cm.json.dumps(self.pr))
        if path == f"/pulls/{PR}/files":
            return _completed(0, cm.json.dumps(self.files if page == 1 else []))
        if path == f"/pulls/{PR}/reviews":
            return _completed(0, cm.json.dumps(self.reviews if page == 1 else []))
        if path == f"/issues/{PR}/comments":
            if method == "POST":
                self.comments.append({"body": fields["body"]})
                return _completed(0, "{}")
            return _completed(0, cm.json.dumps(self.comments if page == 1 else []))
        if path.startswith("/contents/"):
            if self.base_entry is None:
                return _completed(1, stderr="gh: Not Found (HTTP 404)")
            return _completed(0, self.base_entry)
        raise AssertionError(f"unexpected gh api call: {args}")


def _parse_api_args(args: list[str]) -> tuple[str, str, dict[str, str]]:
    method = "GET"
    endpoint = None
    fields: dict[str, str] = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--method", "-X"):
            method = args[i + 1]
            i += 2
        elif arg in ("-H", "--header", "--jq", "-q", "--input"):
            i += 2
        elif arg in ("-f", "--raw-field", "-F", "--field"):
            key, _, value = args[i + 1].partition("=")
            fields[key] = value
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            assert endpoint is None, f"two endpoints in {args}"
            endpoint = arg
            i += 1
    assert endpoint is not None, args
    return method, endpoint, fields


@pytest.fixture
def use_gh(monkeypatch):
    def install(fake: FakeGh) -> FakeGh:
        monkeypatch.setattr(jc, "run_gh", fake)
        return fake

    return install


# --- merges ------------------------------------------------------------------


def test_owner_approval_merges_with_owner_route(use_gh, capsys):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1
    merge = gh.merges[0]
    assert merge[:3] == ["pr", "merge", str(PR)]
    assert "--squash" in merge
    assert "--repo" in merge and merge[merge.index("--repo") + 1] == REPO
    subject = merge[merge.index("--subject") + 1]
    assert "route: owner" in subject
    assert "example-cli" in subject
    assert "merged" in capsys.readouterr().out
    gh.assert_never_closed()


def test_author_plus_one_non_owner_approval_merges_by_consensus(use_gh):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("carol", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1
    subject = gh.merges[0][gh.merges[0].index("--subject") + 1]
    assert "route: consensus" in subject
    body = gh.merges[0][gh.merges[0].index("--body") + 1]
    assert "bob" in body and "carol" in body
    gh.assert_never_closed()


def test_two_non_owner_approvals_merge_even_when_author_is_the_owner(use_gh):
    # The owner opened the PR but never approved it: the author does not count,
    # so two other approvals are needed and are enough.
    gh = use_gh(
        FakeGh(
            _pr_json(author="alice"),
            [_file()],
            [_review("bob", "APPROVED"), _review("carol", "APPROVED")],
        )
    )
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1
    assert "route: consensus" in gh.merges[0][gh.merges[0].index("--subject") + 1]


def test_released_entry_has_no_owner_so_two_voices_merge_a_claim(use_gh):
    pr = _pr_json(author="bob", labels=("ownership",), head_ref="jocasta/claim-example-cli-bob")
    gh = use_gh(FakeGh(pr, [_file()], [_review("carol", "APPROVED")], base_entry=RELEASED_ENTRY))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1
    subject = gh.merges[0][gh.merges[0].index("--subject") + 1]
    assert "route: consensus" in subject
    assert subject.startswith("claim example-cli")
    gh.assert_never_closed()


def test_entry_absent_from_default_branch_is_treated_as_unowned(use_gh):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file(status="added")], [_review("carol", "APPROVED")], base_entry=None))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


def test_merge_subject_falls_back_to_update_without_a_known_label(use_gh):
    pr = _pr_json(author="bob", labels=(), head_ref="feature/anything")
    gh = use_gh(FakeGh(pr, [_file()], [_review("alice", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    subject = gh.merges[0][gh.merges[0].index("--subject") + 1]
    assert subject.startswith("update example-cli")


# --- does not merge ----------------------------------------------------------


def test_author_alone_does_not_merge(use_gh, capsys):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], []))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert gh.posted_comments == []
    out = capsys.readouterr().out
    assert "1 of 2" in out
    gh.assert_never_closed()


def test_author_approving_reviewer_who_is_the_author_counts_once(use_gh):
    # GitHub forbids self-approval, but a COMMENTED review from the author must
    # not be mistaken for a second voice either.
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("bob", "COMMENTED"), _review("bob", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []


def test_owner_changes_requested_blocks_even_with_two_non_owner_approvals(use_gh, capsys):
    gh = use_gh(
        FakeGh(
            _pr_json(author="bob"),
            [_file()],
            [_review("carol", "APPROVED"), _review("dave", "APPROVED"), _review("alice", "CHANGES_REQUESTED")],
        )
    )
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert "alice" in gh.posted_comments[0]
    assert "requested changes" in gh.posted_comments[0]
    assert "not merged" in capsys.readouterr().out
    gh.assert_never_closed()


def test_owner_latest_review_wins(use_gh):
    # Owner approved, then requested changes: the later review governs.
    gh = use_gh(
        FakeGh(
            _pr_json(author="bob"),
            [_file()],
            [
                _review("alice", "APPROVED", "2026-09-04T10:00:00Z"),
                _review("alice", "CHANGES_REQUESTED", "2026-09-04T11:00:00Z"),
            ],
        )
    )
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1


def test_dismissed_approval_is_not_a_voice(use_gh):
    gh = use_gh(
        FakeGh(
            _pr_json(author="bob"),
            [_file()],
            [
                _review("carol", "APPROVED", "2026-09-04T10:00:00Z"),
                _review("carol", "DISMISSED", "2026-09-04T11:00:00Z"),
            ],
        )
    )
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []


def test_bot_approvals_are_not_voices(use_gh):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("some-app[bot]", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []


def test_owner_changes_requested_comment_is_posted_once(use_gh):
    existing = [{"body": f"{cm.COMMENT_MARKER.format(kind='blocked')}\nalready said so"}]
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "CHANGES_REQUESTED")], comments=existing))
    assert cm.run(REPO, PR) == 0
    assert gh.posted_comments == []
    assert gh.merges == []


def test_a_new_situation_gets_its_own_comment(use_gh):
    # The PR was once refused for its file set; now it is a single entry and the
    # owner has requested changes. The earlier comment must not silence this one.
    existing = [{"body": f"{cm.COMMENT_MARKER.format(kind='files')}\nrefused back then"}]
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "CHANGES_REQUESTED")], comments=existing))
    assert cm.run(REPO, PR) == 0
    assert len(gh.posted_comments) == 1
    assert "requested changes" in gh.posted_comments[0]
    assert gh.posted_comments[0].startswith(cm.COMMENT_MARKER.format(kind="blocked"))


# --- refused PRs -------------------------------------------------------------


@pytest.mark.parametrize(
    "files, fragment",
    [
        ([_file(), _file("entries/other-tool.md")], "2 files"),
        ([_file(), _file("adoption.yaml")], "2 files"),
        ([_file("adoption.yaml")], "adoption.yaml"),
        ([_file("entries/README.md")], "README"),
        ([_file("entries/nested/deep.md")], "entries/nested/deep.md"),
        ([_file(status="removed")], "deleted"),
        ([_file(status="renamed", previous="entries/old-name.md")], "renamed"),
        ([], "0 files"),
    ],
)
def test_pr_not_touching_exactly_one_entry_is_refused_with_a_comment(use_gh, files, fragment):
    gh = use_gh(FakeGh(_pr_json(author="bob"), files, [_review("alice", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert fragment in gh.posted_comments[0]
    gh.assert_never_closed()


def test_refusal_comment_is_not_repeated(use_gh):
    files = [_file(), _file("entries/other-tool.md")]
    existing = [{"body": f"{cm.COMMENT_MARKER.format(kind='files')}\nalready refused"}]
    gh = use_gh(FakeGh(_pr_json(author="bob"), files, [], comments=existing))
    assert cm.run(REPO, PR) == 0
    assert gh.posted_comments == []


def test_unparseable_entry_on_default_branch_is_not_merged(use_gh):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("carol", "APPROVED")], base_entry="no frontmatter\n"))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert "frontmatter" in gh.posted_comments[0]


# --- idempotence -------------------------------------------------------------


def test_rerun_on_merged_pr_exits_zero_with_a_notice(use_gh, capsys):
    gh = use_gh(FakeGh(_pr_json(author="bob", state="closed", merged=True), [_file()], [_review("alice", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert gh.posted_comments == []
    assert "already merged" in capsys.readouterr().out
    # Only the PR itself was fetched; nothing else was needed.
    assert len(gh.calls) == 1


def test_closed_unmerged_pr_is_left_alone(use_gh, capsys):
    gh = use_gh(FakeGh(_pr_json(author="bob", state="closed"), [_file()], [_review("alice", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert "closed" in capsys.readouterr().out
    gh.assert_never_closed()


# --- failures ----------------------------------------------------------------


def test_gh_api_failure_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(jc, "run_gh", lambda args, timeout: _completed(1, stderr="gh: HTTP 500 boom"))
    assert cm.run(REPO, PR) == 1
    assert "boom" in capsys.readouterr().err


def test_gh_missing_exits_one(monkeypatch, capsys):
    def missing(args, timeout):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(jc, "run_gh", missing)
    assert cm.run(REPO, PR) == 1
    assert "gh not found" in capsys.readouterr().err


def test_merge_failure_exits_one(use_gh, capsys):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "APPROVED")], merge_rc=1))
    assert cm.run(REPO, PR) == 1
    assert len(gh.merges) == 1
    assert "merge refused" in capsys.readouterr().err


# --- decide() as a pure function ---------------------------------------------


def test_decide_owner_approval_beats_consensus_count():
    latest = {"alice": "APPROVED", "carol": "APPROVED"}
    decision = cm.decide(owner="alice", author="bob", latest_reviews=latest)
    assert decision.action == "merge" and decision.route == "owner"


def test_decide_reports_voice_count_when_short():
    decision = cm.decide(owner="alice", author="bob", latest_reviews={})
    assert decision.action == "wait"
    assert decision.voices == ["bob"]


def test_decide_unowned_entry_needs_two_voices():
    assert cm.decide(owner=None, author="bob", latest_reviews={}).action == "wait"
    merged = cm.decide(owner=None, author="bob", latest_reviews={"carol": "APPROVED"})
    assert merged.action == "merge" and merged.route == "consensus"
    assert merged.voices == ["bob", "carol"]


# --- CLI ---------------------------------------------------------------------


def test_main_parses_the_documented_contract(monkeypatch):
    seen = {}

    def fake_run(repo, pr):
        seen["args"] = (repo, pr)
        return 0

    monkeypatch.setattr(cm, "run", fake_run)
    assert cm.main(["--repo", REPO, "--pr", str(PR)]) == 0
    assert seen["args"] == (REPO, PR)


@pytest.mark.parametrize("argv", [[], ["--repo", REPO], ["--pr", "7"], ["--repo", "no-slash", "--pr", "7"], ["--repo", REPO, "--pr", "x"]])
def test_main_rejects_bad_usage(argv):
    with pytest.raises(SystemExit) as exc:
        cm.main(argv)
    assert exc.value.code == 2


def test_script_depends_only_on_stdlib_and_pyyaml():
    text = Path(cm.__file__).read_text(encoding="utf-8")
    imports = {
        line.split()[1].split(".")[0]
        for line in text.splitlines()
        if line.startswith(("import ", "from ")) and not line.startswith("from __future__")
    }
    allowed = {"argparse", "dataclasses", "json", "subprocess", "sys", "tempfile", "jocasta_common", "yaml", "pathlib", "re"}
    assert imports <= allowed, imports - allowed


# --- reference docs pin the protocol the script enforces --------------------

REFERENCES = Path(__file__).resolve().parent.parent / "skills" / "jocasta" / "references"


def test_write_paths_reference_names_branches_labels_and_the_retry_recipe():
    text = (REFERENCES / "write-paths.md").read_text(encoding="utf-8")
    assert "jocasta/<mode>-<name>-<login>" in text
    assert "`deprecation`" in text and "`ownership`" in text
    assert "pull --rebase" in text
    assert "adoption.yaml" in text


def test_ownership_reference_covers_every_mode_and_the_consensus_rules():
    text = (REFERENCES / "ownership.md").read_text(encoding="utf-8")
    for heading in ("deprecate", "transfer", "release", "claim"):
        assert f"## `{heading}" in text, f"missing a section for {heading}"
    assert "owner: ~" in text
    assert "unowned" in text
    assert "two" in text.lower() and "non-owner" in text.lower()
    assert "does not exist" not in text.lower()
