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
