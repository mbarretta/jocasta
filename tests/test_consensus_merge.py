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

# The PR-head text of a well-formed deprecation: only ``status`` and the new
# ``deprecated`` block differ from OWNED_ENTRY. FakeGh serves it by default so
# every vote-counting test carries an in-scope change.
DEPRECATED_ENTRY = OWNED_ENTRY.replace(
    "status: active",
    "status: deprecated\ndeprecated:\n  route: consensus\n  date: 2026-09-04\n  note: Superseded by newer-cli.",
)
HEAD_SHA = "abc123"


def _claimed(entry: str, login: str) -> str:
    """``entry`` with its owner line replaced by ``login``: the shape of a claim PR."""
    before = "owner: ~" if "owner: ~" in entry else "owner: alice"
    return entry.replace(before, f"owner: {login}")


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
    author_association: str = "MEMBER",
) -> dict:
    return {
        "number": PR,
        "state": state,
        "merged": merged,
        "user": {"login": author},
        "author_association": author_association,
        "labels": [{"name": name} for name in labels],
        "head": {"ref": head_ref, "sha": HEAD_SHA},
        "base": {"ref": DEFAULT_BRANCH, "repo": {"default_branch": DEFAULT_BRANCH}},
        "title": "deprecate example-cli",
        "html_url": f"https://github.com/{REPO}/pull/{PR}",
    }


def _file(filename: str = ENTRY_PATH, status: str = "modified", previous: str | None = None) -> dict:
    data = {"filename": filename, "status": status}
    if previous is not None:
        data["previous_filename"] = previous
    return data


def _review(login: str, state: str, submitted_at: str = "2026-09-04T12:00:00Z", association: str = "COLLABORATOR") -> dict:
    return {"user": {"login": login}, "state": state, "submitted_at": submitted_at, "author_association": association}


class FakeGh:
    """Routes ``gh`` calls by endpoint and records every call made."""

    def __init__(
        self,
        pr: dict,
        files: list[dict],
        reviews: list[dict],
        *,
        base_entry: str | None = OWNED_ENTRY,
        head_entry: str | None = DEPRECATED_ENTRY,
        comments: list[dict] | None = None,
        merge_rc: int = 0,
    ):
        self.pr = pr
        self.files = files
        self.reviews = reviews
        self.base_entry = base_entry
        self.head_entry = head_entry
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
            assert path == f"/contents/{ENTRY_PATH}", path
            ref = params.get("ref")
            assert ref in (DEFAULT_BRANCH, HEAD_SHA), f"contents fetched at an unexpected ref: {ref!r}"
            text = self.base_entry if ref == DEFAULT_BRANCH else self.head_entry
            if text is None:
                return _completed(1, stderr="gh: Not Found (HTTP 404)")
            return _completed(0, text)
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
    gh = use_gh(FakeGh(pr, [_file()], [_review("carol", "APPROVED")], base_entry=RELEASED_ENTRY, head_entry=_claimed(RELEASED_ENTRY, "bob")))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1
    subject = gh.merges[0][gh.merges[0].index("--subject") + 1]
    assert "route: consensus" in subject
    assert subject.startswith("claim example-cli")
    gh.assert_never_closed()


def test_entry_absent_from_default_branch_is_refused_as_a_new_entry(use_gh):
    # A new entry is registered by its owner with a direct commit; two votes
    # must not be able to add one naming an arbitrary owner (sec2).
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file(status="added")], [_review("carol", "APPROVED")], base_entry=None, head_entry=OWNED_ENTRY))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert gh.posted_comments[0].startswith(cm.COMMENT_MARKER.format(kind="scope"))
    assert "new entry" in gh.posted_comments[0]
    gh.assert_never_closed()


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


# --- content scope (sec2) ----------------------------------------------------


def test_deprecation_with_appended_body_sentence_merges(use_gh):
    head = DEPRECATED_ENTRY.rstrip("\n") + "\n\nDeprecated in favor of `newer-cli`.\n"
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("carol", "APPROVED")], head_entry=head))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


def test_deprecation_with_owner_route_and_no_note_merges(use_gh):
    head = OWNED_ENTRY.replace("status: active", "status: deprecated\ndeprecated:\n  route: owner\n  date: 2026-09-04")
    gh = use_gh(FakeGh(_pr_json(author="alice"), [_file()], [_review("bob", "APPROVED"), _review("carol", "APPROVED")], head_entry=head))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


def test_claim_of_owned_entry_by_the_author_merges(use_gh):
    pr = _pr_json(author="bob", labels=("ownership",), head_ref="jocasta/claim-example-cli-bob")
    gh = use_gh(FakeGh(pr, [_file()], [_review("carol", "APPROVED")], head_entry=_claimed(OWNED_ENTRY, "bob")))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1
    assert gh.merges[0][gh.merges[0].index("--subject") + 1].startswith("claim example-cli")


def test_claim_may_spell_the_author_login_in_another_case(use_gh):
    pr = _pr_json(author="bob", labels=("ownership",))
    gh = use_gh(FakeGh(pr, [_file()], [_review("carol", "APPROVED")], head_entry=_claimed(OWNED_ENTRY, "Bob")))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


@pytest.mark.parametrize(
    "head, fragment",
    [
        (DEPRECATED_ENTRY.replace("kind: cli", "kind: cli\ninstall: curl -fsSL https://example.com/x.sh | sh"), "`install`"),
        (OWNED_ENTRY.replace("kind: cli", "kind: cli\ninstall: curl -fsSL https://example.com/x.sh | sh"), "`install`"),
        (DEPRECATED_ENTRY.replace("example-org/example-cli", "someone-else/example-cli"), "`source`"),
        (OWNED_ENTRY.replace("kind: cli", "kind: skill"), "`kind`"),
        (OWNED_ENTRY.replace("name: example-cli", "name: other-cli"), "`name`"),
        (OWNED_ENTRY.replace("Lists the files", "Runs arbitrary code and lists the files"), "the body"),
        (DEPRECATED_ENTRY.replace("Lists the files in a directory tree that changed since a given git ref.", "Something else entirely."), "the body"),
        (DEPRECATED_ENTRY.replace("route: consensus", "route: stale-source"), "`deprecated`"),
        (OWNED_ENTRY.replace("status: active", "status: deprecated"), "`status`"),
        (_claimed(OWNED_ENTRY, "carol"), "`owner`"),
        (_claimed(DEPRECATED_ENTRY, "bob"), "`owner`"),
        (OWNED_ENTRY, "nothing"),
        ("no frontmatter\n", "frontmatter"),
    ],
    ids=["install-added-with-deprecation", "install-added", "source", "kind", "name", "body-rewritten", "body-rewritten-with-deprecation", "stale-source-route", "status-without-block", "claim-for-someone-else", "claim-plus-deprecation", "no-change", "unreadable-head"],
)
def test_out_of_scope_change_is_refused_even_with_the_owner_approval(use_gh, head, fragment):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "APPROVED"), _review("carol", "APPROVED")], head_entry=head))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert gh.posted_comments[0].startswith(cm.COMMENT_MARKER.format(kind="scope"))
    assert fragment in gh.posted_comments[0]
    gh.assert_never_closed()


def test_entry_missing_at_the_pr_head_is_refused(use_gh):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "APPROVED")], head_entry=None))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert gh.posted_comments[0].startswith(cm.COMMENT_MARKER.format(kind="scope"))


def test_scope_refusal_comment_is_not_repeated(use_gh):
    existing = [{"body": f"{cm.COMMENT_MARKER.format(kind='scope')}\nalready refused"}]
    head = OWNED_ENTRY.replace("kind: cli", "kind: cli\ninstall: pip install example-cli")
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "APPROVED")], head_entry=head, comments=existing))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert gh.posted_comments == []


def test_scope_is_checked_before_votes_are_counted(use_gh, capsys):
    # An out-of-scope PR with no votes yet hears about the scope problem now,
    # not after two people have approved it.
    head = OWNED_ENTRY.replace("kind: cli", "kind: cli\ninstall: pip install example-cli")
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [], head_entry=head))
    assert cm.run(REPO, PR) == 0
    assert len(gh.posted_comments) == 1
    assert "waiting" not in capsys.readouterr().out


# --- login case and review states (sec3) -------------------------------------


def test_owner_veto_matches_the_login_case_insensitively(use_gh):
    base = OWNED_ENTRY.replace("owner: alice", "owner: Alice")
    gh = use_gh(
        FakeGh(
            _pr_json(author="bob"),
            [_file()],
            [_review("carol", "APPROVED"), _review("dave", "APPROVED"), _review("alice", "CHANGES_REQUESTED")],
            base_entry=base,
            head_entry=DEPRECATED_ENTRY.replace("owner: alice", "owner: Alice"),
        )
    )
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert "requested changes" in gh.posted_comments[0]


def test_owner_approval_matches_the_login_case_insensitively(use_gh):
    base = OWNED_ENTRY.replace("owner: alice", "owner: Alice")
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("alice", "APPROVED")], base_entry=base, head_entry=DEPRECATED_ENTRY.replace("owner: alice", "owner: Alice")))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1
    assert "route: owner" in gh.merges[0][gh.merges[0].index("--subject") + 1]


def test_owner_author_in_another_case_is_not_a_voice(use_gh, capsys):
    base = OWNED_ENTRY.replace("owner: alice", "owner: Alice")
    gh = use_gh(FakeGh(_pr_json(author="alice"), [_file()], [_review("bob", "APPROVED")], base_entry=base, head_entry=DEPRECATED_ENTRY.replace("owner: alice", "owner: Alice")))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert "1 of 2" in capsys.readouterr().out


def test_owner_comment_after_changes_requested_keeps_the_block(use_gh):
    gh = use_gh(
        FakeGh(
            _pr_json(author="bob"),
            [_file()],
            [
                _review("carol", "APPROVED"),
                _review("alice", "CHANGES_REQUESTED", "2026-09-04T10:00:00Z"),
                _review("alice", "COMMENTED", "2026-09-04T11:00:00Z"),
            ],
        )
    )
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert len(gh.posted_comments) == 1
    assert "requested changes" in gh.posted_comments[0]


def test_reviewer_comment_after_approval_keeps_the_approval(use_gh):
    gh = use_gh(
        FakeGh(
            _pr_json(author="bob"),
            [_file()],
            [_review("carol", "APPROVED", "2026-09-04T10:00:00Z"), _review("carol", "COMMENTED", "2026-09-04T11:00:00Z")],
        )
    )
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


# --- who may be a voice (sec4) ------------------------------------------------


def test_approval_from_an_outside_account_is_not_a_voice(use_gh, capsys):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("stranger", "APPROVED", association="NONE")]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert "1 of 2" in capsys.readouterr().out


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIMER", "FIRST_TIME_CONTRIBUTOR", "MANNEQUIN"])
def test_only_owner_member_and_collaborator_reviews_count(use_gh, association):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("carol", "APPROVED", association=association)]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_repository_insiders_are_voices(use_gh, association):
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("carol", "APPROVED", association=association)]))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


def test_outside_author_is_not_a_voice(use_gh, capsys):
    gh = use_gh(FakeGh(_pr_json(author="bob", author_association="NONE"), [_file()], [_review("carol", "APPROVED")]))
    assert cm.run(REPO, PR) == 0
    assert gh.merges == []
    assert "1 of 2" in capsys.readouterr().out


def test_outside_author_claim_merges_on_two_insider_approvals(use_gh):
    pr = _pr_json(author="bob", labels=("ownership",), author_association="NONE")
    gh = use_gh(FakeGh(pr, [_file()], [_review("carol", "APPROVED"), _review("dave", "APPROVED")], head_entry=_claimed(OWNED_ENTRY, "bob")))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


def test_outside_owner_veto_is_ignored(use_gh):
    # The owner's review is subject to the same association filter as everyone else's.
    gh = use_gh(FakeGh(_pr_json(author="bob"), [_file()], [_review("carol", "APPROVED"), _review("alice", "CHANGES_REQUESTED", association="NONE")]))
    assert cm.run(REPO, PR) == 0
    assert len(gh.merges) == 1


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


def _decide(**kwargs) -> cm.Decision:
    kwargs.setdefault("author_association", "MEMBER")
    return cm.decide(**kwargs)


def test_decide_owner_approval_beats_consensus_count():
    latest = {"alice": "APPROVED", "carol": "APPROVED"}
    decision = _decide(owner="alice", author="bob", latest_reviews=latest)
    assert decision.action == "merge" and decision.route == "owner"


def test_decide_reports_voice_count_when_short():
    decision = _decide(owner="alice", author="bob", latest_reviews={})
    assert decision.action == "wait"
    assert decision.voices == ["bob"]


def test_decide_unowned_entry_needs_two_voices():
    assert _decide(owner=None, author="bob", latest_reviews={}).action == "wait"
    merged = _decide(owner=None, author="bob", latest_reviews={"carol": "APPROVED"})
    assert merged.action == "merge" and merged.route == "consensus"
    assert merged.voices == ["bob", "carol"]


def test_decide_compares_logins_case_insensitively():
    blocked = _decide(owner="Alice", author="bob", latest_reviews={"alice": "CHANGES_REQUESTED", "carol": "APPROVED"})
    assert blocked.action == "blocked"
    owner_route = _decide(owner="Alice", author="bob", latest_reviews={"alice": "APPROVED"})
    assert owner_route.action == "merge" and owner_route.route == "owner"
    # An owner-author spelled differently is still the owner, and an approval
    # from the author under another spelling is still the author's.
    waiting = _decide(owner="Alice", author="alice", latest_reviews={"Bob": "APPROVED"})
    assert waiting.action == "wait" and waiting.voices == ["Bob"]
    waiting = _decide(owner=None, author="Bob", latest_reviews={"bob": "APPROVED"})
    assert waiting.action == "wait" and waiting.voices == ["Bob"]


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", None, ""])
def test_decide_outside_author_is_not_a_voice(association):
    decision = cm.decide(owner="alice", author="bob", author_association=association, latest_reviews={"carol": "APPROVED"})
    assert decision.action == "wait"
    assert decision.voices == ["carol"]


def test_latest_review_states_keeps_only_counted_states_from_insiders():
    reviews = [
        _review("carol", "APPROVED", "2026-09-04T10:00:00Z"),
        _review("carol", "COMMENTED", "2026-09-04T11:00:00Z"),
        _review("alice", "CHANGES_REQUESTED", "2026-09-04T10:00:00Z"),
        _review("alice", "PENDING", "2026-09-04T11:00:00Z"),
        _review("dave", "APPROVED", "2026-09-04T10:00:00Z"),
        _review("dave", "DISMISSED", "2026-09-04T11:00:00Z"),
        _review("erin", "APPROVED", association="NONE"),
        _review("some-app[bot]", "APPROVED"),
        {"user": None, "state": "APPROVED", "submitted_at": "2026-09-04T12:00:00Z"},
        {"user": {"login": "frank"}, "state": "APPROVED", "submitted_at": "2026-09-04T12:00:00Z"},
    ]
    assert cm.latest_review_states(reviews) == {"carol": "APPROVED", "alice": "CHANGES_REQUESTED", "dave": "DISMISSED"}


def test_latest_review_states_merges_spellings_of_one_login():
    reviews = [_review("Carol", "APPROVED", "2026-09-04T10:00:00Z"), _review("carol", "DISMISSED", "2026-09-04T11:00:00Z")]
    assert cm.latest_review_states(reviews) == {"carol": "DISMISSED"}


# --- change_in_scope() as a pure function --------------------------------------


def test_change_in_scope_accepts_the_two_shapes():
    assert cm.change_in_scope(base_text=OWNED_ENTRY, head_text=DEPRECATED_ENTRY, author="bob") == ("deprecation", "")
    assert cm.change_in_scope(base_text=OWNED_ENTRY, head_text=_claimed(OWNED_ENTRY, "bob"), author="bob") == ("claim", "")
    assert cm.change_in_scope(base_text=RELEASED_ENTRY, head_text=_claimed(RELEASED_ENTRY, "bob"), author="bob") == ("claim", "")


def test_change_in_scope_ignores_yaml_and_whitespace_formatting():
    head = DEPRECATED_ENTRY.replace("owner: alice", "owner: 'alice'").replace("kind: cli", "kind:   cli") + "\n\n"
    assert cm.change_in_scope(base_text=OWNED_ENTRY, head_text=head, author="bob") == ("deprecation", "")


def test_change_in_scope_names_every_changed_field():
    head = _claimed(DEPRECATED_ENTRY, "bob").replace("kind: cli", "kind: skill\ninstall: pip install x")
    shape, why = cm.change_in_scope(base_text=OWNED_ENTRY, head_text=head, author="bob")
    assert shape is None
    assert "`deprecated`" in why and "`install`" in why and "`kind`" in why and "`owner`" in why and "`status`" in why


def test_change_in_scope_requires_the_base_to_be_active_for_a_deprecation():
    base = DEPRECATED_ENTRY.replace("route: consensus", "route: owner")
    shape, why = cm.change_in_scope(base_text=base, head_text=DEPRECATED_ENTRY, author="bob")
    assert shape is None and "`deprecated`" in why


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


def test_write_paths_reference_states_insider_voices_and_content_scope():
    """The consensus summary in write-paths.md must not lag the rules the script enforces."""
    text = (REFERENCES / "write-paths.md").read_text(encoding="utf-8")
    section = text.split("## What the consensus action does with the PR", 1)[1].split("\n## ", 1)[0]
    assert "`author_association`" in section
    for association in cm.VOICE_ASSOCIATIONS:
        assert f"`{association}`" in section, f"{association} is not named as a voice"
    assert "deprecation" in section and "claim" in section
    assert "`active`" in section and "`deprecated`" in section
    assert "nothing else" in section


def test_ownership_reference_covers_every_mode_and_the_consensus_rules():
    text = (REFERENCES / "ownership.md").read_text(encoding="utf-8")
    for heading in ("deprecate", "transfer", "release", "claim"):
        assert f"## `{heading}" in text, f"missing a section for {heading}"
    assert "owner: ~" in text
    assert "unowned" in text
    assert "two" in text.lower() and "non-owner" in text.lower()
    assert "does not exist" not in text.lower()
