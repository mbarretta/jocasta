"""Structural checks on references/search.md, the search and show protocols.

These pin the contract the skill relies on: the ranking order (fit, adopters,
status), the per-candidate output fields, the verbatim empty-result wording,
the `show <name>` mode, and the D-2 / T-1 scale warning. They are deliberately
literal: the reference is prose the model follows, so the words are the API.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_MD = REPO_ROOT / "skills" / "jocasta" / "references" / "search.md"
ARCHIVE_WORDING = "does not appear in the archive"


def _text() -> str:
    return SEARCH_MD.read_text()


def _section(text: str, heading_pattern: str) -> str:
    """Return the body of the first `##` section whose heading matches the pattern."""
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        if re.search(heading_pattern, heading, re.IGNORECASE):
            return body
    raise AssertionError(f"search.md has no '## ' heading matching {heading_pattern!r}")


def test_search_reference_exists_and_covers_both_modes():
    text = _text()
    assert re.search(r"^## .*\bsearch\b", text, re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^## .*`show <name>`", text, re.MULTILINE)


def test_protocol_refreshes_snapshot_then_reads_every_entry_and_adoption():
    text = _text()
    assert "pull --ff-only" in text
    assert "entries/*.md" in text
    assert "adoption.yaml" in text


def test_ranking_order_is_fit_then_adopters_then_status():
    """The ranking keys are a bolded, numbered list; pin the list itself, not stray words elsewhere."""
    keys = re.findall(r"^ {2,}\d\. \*\*([A-Za-z ]+)\*\*", _text(), re.MULTILINE)
    assert keys == ["Fit", "Adopter count", "Status"], keys
    assert "active above deprecated" in _text().lower()


def test_keyword_matching_on_names_alone_is_ruled_out():
    text = _text().lower()
    assert re.search(r"never[^.\n]*keyword", text), "the reference must say never to keyword-match names alone"
    assert "body" in text and "frontmatter" in text


def test_output_template_shows_every_required_field_per_candidate():
    template = _section(_text(), r"output")
    for field in ("name", "owner", "unowned", "status", "route", "date", "adopter", "source", "install"):
        assert field in template.lower(), f"output template does not show {field}"
    assert "deprecated" in template.lower()


def test_empty_result_wording_is_verbatim_and_uses_archive_phrase():
    section = _section(_text(), r"empty|nothing")
    quoted = re.findall(r"^> (.+)$", section, re.MULTILINE)
    assert quoted, "the empty-result wording must be given as a verbatim quoted block"
    assert any(ARCHIVE_WORDING in line for line in quoted)


def test_does_not_exist_appears_only_where_marked_forbidden():
    for n, line in enumerate(_text().splitlines(), 1):
        if "does not exist" in line.lower():
            assert re.search(r"forbid|never|banned|not allowed", line, re.IGNORECASE), (
                f"search.md:{n} uses the forbidden phrase without marking it forbidden"
            )


def test_show_prints_frontmatter_body_and_adopters_and_uses_archive_wording_for_unknown():
    section = _section(_text(), r"`show <name>`")
    lowered = section.lower()
    assert "frontmatter" in lowered and "body" in lowered and "adopter" in lowered
    assert ARCHIVE_WORDING in section


def test_scale_tradeoff_and_two_hundred_entry_warning_are_stated():
    text = _text()
    assert "D-2" in text and "T-1" in text
    assert re.search(r"fetch, not an index", text, re.IGNORECASE)
    assert "200" in text and re.search(r"\bwarn", text, re.IGNORECASE)
