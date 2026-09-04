"""Tests for the report rollup/fold logic."""

import pytest

from ufo_tdkit_report.model import ChangeFact, FactType, FileKind, Scope
from ufo_tdkit_report.rollup import fold_facts


def _advance(master, glyph="A"):
    return ChangeFact(FactType.ADVANCE_CHANGED, FileKind.GLIF, Scope(master=master, glyph=glyph), (500, 520), 20)


def test_same_change_across_masters_collapses():
    facts = [_advance(f"Master{i}") for i in range(5)]
    folded = fold_facts(facts)
    assert len(folded) == 1
    assert "across 5 masters" in folded[0].summary
    assert folded[0].count == 5
    assert not folded[0].folded


def test_component_move_groups_by_base_uniform_delta():
    facts = [
        ChangeFact(FactType.COMPONENT_MOVED, FileKind.GLIF, Scope(master="M1", glyph=g), ("ring", 50.0, 700.0))
        for g in ("Aring", "aring", "Uring")
    ]
    folded = fold_facts(facts)
    assert len(folded) == 1
    assert "component `ring` repositioned in 3 glyphs" in folded[0].summary
    assert "by (+50,+700)" in folded[0].summary


def test_component_move_groups_by_base_mixed_deltas():
    facts = [
        ChangeFact(
            FactType.COMPONENT_MOVED, FileKind.GLIF, Scope(master=f"M{i}", glyph="Aring"), ("ring", float(i), 0.0)
        )
        for i in range(3)
    ]
    folded = fold_facts(facts)
    assert len(folded) == 1
    # Mixed deltas surface as a distribution, one fact (not three).
    assert "component `ring` repositioned" in folded[0].summary
    assert "Δ(" in folded[0].summary


def test_one_glyph_many_masters_not_folded():
    # Same glyph across 20 masters is a single fold group with glyph-count 1 -> not folded.
    facts = [_advance(f"M{i}", glyph="A") for i in range(20)]
    folded = fold_facts(facts, threshold=12)
    assert len(folded) == 1
    assert not folded[0].folded
    assert "across 20 masters" in folded[0].summary


def test_high_glyph_count_folds():
    # Many distinct glyphs sharing one fold key only happens for component moves.
    facts = [
        ChangeFact(FactType.COMPONENT_MOVED, FileKind.GLIF, Scope(master="M1", glyph=f"g{i}"), ("ring", 1.0, 1.0))
        for i in range(20)
    ]
    folded = fold_facts(facts, threshold=12)
    assert folded[0].folded
    assert "folded: 20 items not enumerated" in folded[0].summary


def test_anchor_moved_folds_across_masters_with_delta():
    facts = [
        ChangeFact(FactType.ANCHOR_MOVED, FileKind.GLIF, Scope(master=f"M{i}", glyph="Ring"),
                   ("top", 0.0, 50.0))
        for i in range(3)
    ]
    folded = fold_facts(facts)
    assert len(folded) == 1
    assert "anchor `top` moved by (+0,+50) on `Ring` across 3 masters" == folded[0].summary


def test_deterministic_order():
    facts = [
        ChangeFact(FactType.UNICODE_CHANGED, FileKind.GLIF, Scope(glyph="Z"), ((), (1,))),
        ChangeFact(FactType.ADVANCE_CHANGED, FileKind.GLIF, Scope(glyph="A"), (1, 2), 1),
    ]
    a = [f.summary for f in fold_facts(facts)]
    b = [f.summary for f in fold_facts(list(reversed(facts)))]
    assert a == b


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_an_outline_redraw_reports_masters_but_not_a_point_count():
    """"~22 points moved" reads as precision and carries none.

    It does not separate a nudged terminal from a redrawn bowl, it is approximate anyway,
    and a page of them is tiring to read for a number nobody acts on. How many *masters*
    a change spans does answer a real question — is this one weight or all of them — so
    that stays. `magnitude` still carries the count: it drives sort order and threshold
    folding, and dropping it from the prose must not disturb either.
    """
    facts = [
        ChangeFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, Scope(master=m, glyph="A"), magnitude=22)
        for m in ("Bold", "Regular")
    ]
    folded = fold_facts(facts)
    assert len(folded) == 1
    assert folded[0].summary == "outline redrawn in `A` across 2 masters"
    assert "point" not in folded[0].summary
    assert "22" not in folded[0].summary


def test_the_point_count_still_orders_and_folds():
    """Removing it from the text must not remove it from the machinery."""
    facts = [
        ChangeFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, Scope(master="R", glyph="small"), magnitude=1),
        ChangeFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, Scope(master="R", glyph="big"), magnitude=99),
    ]
    folded = fold_facts(facts)
    summaries = [f.summary for f in folded]
    assert summaries == sorted(summaries) or len(summaries) == 2
    # The magnitudes survive on the atoms the folded facts were built from.
    assert {f.magnitude for f in facts} == {1, 99}


def test_the_masters_roll_call_closes_a_multi_master_report():
    """Each line says how many masters; the report should also say which.

    That question is asked at the end of reading, and collecting the answer by hand off
    twenty lines is exactly the work a report should have done for you.
    """
    from ufo_tdkit_report.model import SourceReport

    facts = [
        ChangeFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, Scope(master=m, glyph=g), magnitude=3)
        for m in ("Evacode-Bold", "Evacode-Regular")
        for g in ("A", "B")
    ]
    report = SourceReport(
        commit_spec="a..b", changed_file_count=4, raw_fact_count=len(facts),
        folded_facts=fold_facts(facts),
    )
    text = report.render_text()
    assert "### Masters touched" in text
    assert "`Evacode-Bold`, `Evacode-Regular`" in text
    assert text.index("Masters touched") > text.index("outline redrawn"), "it closes the report"


def test_a_single_master_report_has_no_roll_call():
    """A section that is sometimes empty teaches the reader to skip it.

    With one master every line already says "across 1 master"; repeating its name under a
    heading of its own is noise, not a summary.
    """
    from ufo_tdkit_report.model import SourceReport

    facts = [ChangeFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, Scope(master="Only", glyph="A"), magnitude=3)]
    report = SourceReport(
        commit_spec="a..b", changed_file_count=1, raw_fact_count=1, folded_facts=fold_facts(facts),
    )
    assert "Masters touched" not in report.render_text()
