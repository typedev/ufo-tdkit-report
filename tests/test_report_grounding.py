"""Tests for the deterministic grounding check.

Precision matters more than recall here: a checker that cries wolf on correct prose gets
switched off, and then it protects nothing. So the first two tests are about NOT firing.
"""

import pytest

from ufo_tdkit_report.grounding import Finding, check, vocabulary
from ufo_tdkit_report.model import FactType, FileKind, FoldedFact, RangeReport, Scope

FACTS = """## Source changes: v1 → HEAD

### Outlines
- outline redrawn in `guillemetleft`, `guillemetright`, `question` (~24 points moved)
- component `question` shifted by (+130,+0) in 1 glyph across 1 master

### OpenType features
- feature `ss02`: rule added `sub a by a.ss02;`
- codepoint `uni20C5` assigned

### Metadata
- fontinfo `styleName`: 'Bold' -> 'Bold Italic' across 1 master
"""


def _kinds(result):
    return {(f.kind, f.token) for f in result.findings}


def test_a_faithful_narrative_produces_nothing():
    narrative = (
        "Redraw punctuation and wire an alternate\n\n"
        "- Redraw outlines in `guillemetleft`, `guillemetright` and `question` (~24 points moved)\n"
        "- Shift the `question` component by (+130,+0) in one glyph across four masters\n"
        "- Add feature `ss02`, rule `sub a by a.ss02;`\n"
        "- Assign codepoint `uni20C5`\n"
        "- Change fontinfo `styleName` from 'Bold' to 'Bold Italic'\n"
    )
    result = check(narrative, FACTS)
    assert result.findings == ()
    assert result.ok
    assert result.summary() == ""


def test_ordinary_words_that_are_also_glyph_names_are_left_alone():
    """`four`, `one`, `period`, `section` are standard glyph names AND English words.

    No length filter or neighbourhood rule separates them — a rule keyed on "a glyph name
    near another glyph name" flags the `one` in this very sentence. The markup does it.
    """
    narrative = (
        "Shift the `question` component in one glyph across four masters; "
        "the section on metadata changed by one degree of style, over a period."
    )
    assert check(narrative, FACTS).findings == ()


def test_marked_up_identifiers_are_checked_because_the_model_declared_them():
    narrative = "Redraw `guillemotleft` and `questiondown`; add `ss03`; assign `uni20C6`."
    result = check(narrative, FACTS)
    tokens = {f.token for f in result.findings}
    assert tokens == {"guillemotleft", "questiondown", "ss03", "uni20C6"}
    # `four` in backticks WOULD be a claim about the glyph — and is not in the facts.
    assert "four" in {f.token for f in check("across `four` masters", FACTS).findings}


def test_shapes_prose_never_takes_are_checked_without_markup():
    narrative = (
        "Assign codepoint uni20C6. Shift by (+150,+0). "
        "Add ss03 and a.ss03 to the set."
    )
    result = check(narrative, FACTS)
    assert ("codepoint", "uni20C6") in _kinds(result)
    assert ("measurement", "(+150,+0)") in _kinds(result)
    assert {"ss03", "a.ss03"} <= {f.token for f in result.findings}


def test_a_near_miss_of_a_known_name_is_the_signature_of_invention():
    result = check("Redraw outlines in guillemotleft and question.", FACTS)
    (finding,) = result.findings
    assert finding == Finding("near-miss", "guillemotleft", "guillemetleft")
    assert "nearest match" in finding.describe()


def test_sentence_punctuation_is_not_read_as_a_difference():
    """Glyph names carry dots, so the word pattern must allow them — and then trim them."""
    assert check("The change assigns uni20C5. It also touches question.", FACTS).findings == ()


def test_plurals_and_prose_casing_are_tolerated():
    narrative = "Across masters, the Question glyph and the guillemets were redrawn."
    assert check(narrative, FACTS).findings == ()


def test_a_narrative_without_markup_reports_the_lost_coverage():
    """Silence about a skipped check is the same failure as a skipped check."""
    result = check("Redraw outlines in guillemetleft and question.", FACTS)
    assert result.findings == ()
    assert result.markup_missing is True
    assert "did not mark up any identifiers" in result.summary()

    # Once anything is marked up, the check ran.
    assert check("Redraw `question`.", FACTS).markup_missing is False
    # And facts with no identifiers at all cannot be under-marked.
    assert check("Nothing to say.", "- no semantic source changes").markup_missing is False


def test_vocabulary_uses_the_structured_names_not_only_the_rendered_text():
    report = RangeReport(
        range_spec="v1..HEAD",
        folded_facts=[
            FoldedFact(
                FactType.OUTLINE_REDRAWN, FileKind.GLIF, "outlines redrawn in 3 glyphs",
                affected=[Scope(glyph="Adieresis", master="Bold Italic")],
            )
        ],
    )
    vocab = vocabulary("outlines redrawn in 3 glyphs", report)
    assert "Adieresis" in vocab
    assert "Bold Italic" in vocab
    # …so naming that glyph is grounded even though the summary never spells it out.
    assert check("Redraw `Adieresis`.", "outlines redrawn in 3 glyphs", report).findings == ()


def test_findings_are_deduplicated_and_ordered():
    # `a.ss03` matches both the tag shape and the near-miss rule; it is reported once.
    result = check("Add `a.ss03` to the set.", FACTS)
    assert len([f for f in result.findings if f.token == "a.ss03"]) == 1
    kinds = [f.kind for f in result.findings]
    assert kinds == sorted(kinds, key=lambda k: ["identifier", "codepoint", "near-miss"].index(k))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
