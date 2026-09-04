"""Structural checks on the register protocol reference.

``skills/jocasta/references/register.md`` is the contract the skill follows
when someone registers a tool. These tests pin the parts the charter makes
load-bearing: the interview order and README-assisted draft (R-2), the
mandatory overlap report before any write (R-3), the validate-then-commit
write path with the rebase retry (D-3, P-4), the plain-statement closing
line (R-8), and the locally-runnable boundary (D-4, N-4).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTER_MD = REPO_ROOT / "skills" / "jocasta" / "references" / "register.md"


def _text() -> str:
    assert REGISTER_MD.is_file(), "references/register.md is missing"
    return REGISTER_MD.read_text(encoding="utf-8")


def _section(text: str, heading_pattern: str) -> str:
    """Return the body of the first ``##`` section whose heading matches the pattern."""
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        if re.search(heading_pattern, heading, re.IGNORECASE):
            return body
    raise AssertionError(f"no '## ' heading matching {heading_pattern!r}")


def test_interview_asks_source_first_then_name_kind_install():
    interview = _section(_text(), r"interview")
    steps = re.findall(r"^### \d+\. (.+)$", interview, flags=re.MULTILINE)
    assert [s.split()[0].lower() for s in steps] == ["source", "name", "kind", "install"]
    assert "gh api repos/{o}/{r}/readme" in interview
    assert "kebab-case" in interview
    assert "gh api user --jq .login" in _text()


def test_interview_never_shows_the_submitter_yaml_or_field_names():
    text = _text()
    assert re.search(r"never (?:shown|sees?|see) (?:the )?yaml", text, re.IGNORECASE)
    # The reference must tell the model which plain question fills which key.
    for key in ("name", "owner", "source", "kind", "install", "registered", "status"):
        assert f"`{key}`" in text, f"field {key!r} is not mapped to an interview step"


def test_overlap_report_is_mandatory_before_any_write():
    text = _text()
    overlap = _section(text, r"overlap")
    assert "nothing in the archive overlaps" in overlap.lower()
    assert re.search(r"before (?:any(?:thing is)? writ|writing)", overlap, re.IGNORECASE)
    for choice in ("continue", "adopt", "abort"):
        assert choice in overlap.lower(), f"overlap gate lacks the {choice!r} choice"
    assert re.search(r"every (?:existing )?entr", overlap, re.IGNORECASE)


def test_write_path_validates_then_commits_then_pushes_with_one_rebase_retry():
    write = _section(_text(), r"write")
    positions = [
        write.index("entries/<name>.md"),
        write.index("validate.py"),
        write.index("register <name>"),
        write.index("git -C <snapshot> push"),
        write.index("git -C <snapshot> pull --rebase"),
    ]
    assert positions == sorted(positions), "write path steps are out of order"
    assert "verbatim" in write.lower()
    assert re.search(r"never bypass", write, re.IGNORECASE)
    assert re.search(r"(?:retry|try|push) (?:once|one more time|a second time)", write, re.IGNORECASE)
    assert re.search(r"stop and report", write, re.IGNORECASE)


def test_closing_message_opens_with_the_plain_statement():
    closing = _section(_text(), r"clos")
    first_quote = next(line for line in closing.splitlines() if line.startswith(">"))
    assert first_quote.startswith("> Committed `entries/<name>.md`")
    for token in ("<sha>", "<org>/<repo>"):
        assert token in first_quote


def test_refuses_anything_not_locally_runnable_with_archive_wording():
    boundary = _section(_text(), r"runnable|boundary|admit")
    for phrase in ("executable", "script", "agent skill", "hosted service"):
        assert phrase in boundary.lower()
    assert "D-4" in boundary
    assert "nothing written" in boundary.lower()
    assert "does not exist" not in boundary.lower()
