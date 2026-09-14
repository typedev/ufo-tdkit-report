"""Tests for the report features.fea rule-level differ."""

import pytest

from ufo_tdkit_report.features import diff_fea, parse_fea
from ufo_tdkit_report.model import FactType, Scope

SCOPE = Scope()


def test_rule_added_inside_existing_tag():
    """The v2.006 case: a sub added inside an existing tag, not a new tag."""
    old = parse_fea("feature ss02 { sub one by one.ss02; } ss02;")
    new = parse_fea("feature ss02 { sub one by one.ss02; sub two by two.ss02; } ss02;")
    facts = diff_fea(old, new, SCOPE)
    assert len(facts) == 1
    assert facts[0].fact_type == FactType.FEA_RULE_ADDED
    assert facts[0].scope.feature_tag == "ss02"
    assert "two" in facts[0].detail[0]


def test_rule_removed():
    old = parse_fea("feature ss02 { sub one by one.ss02; sub two by two.ss02; } ss02;")
    new = parse_fea("feature ss02 { sub one by one.ss02; } ss02;")
    facts = diff_fea(old, new, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.FEA_RULE_REMOVED]


def test_feature_added_and_removed():
    old = parse_fea("feature ss01 { sub a by a.ss01; } ss01;")
    new = parse_fea("feature ss02 { sub b by b.ss02; } ss02;")
    facts = diff_fea(old, new, SCOPE)
    kinds = {f.fact_type for f in facts}
    assert FactType.FEA_FEATURE_ADDED in kinds
    assert FactType.FEA_FEATURE_REMOVED in kinds


def test_class_change():
    old = parse_fea("@pnum_l = [zero one]; feature pnum { sub zero by zero.tf; } pnum;")
    new = parse_fea("@pnum_l = [zero one two]; feature pnum { sub zero by zero.tf; } pnum;")
    facts = diff_fea(old, new, SCOPE)
    assert any(f.fact_type == FactType.FEA_CLASS_CHANGED for f in facts)


def test_include_does_not_crash():
    """include() targets are not on disk when parsing git blobs -> must not raise."""
    snap = parse_fea("include(missing.fea);\nfeature ss01 { sub a by a.ss01; } ss01;")
    assert snap is not None
    # No exception; ss01 is captured.
    assert any(tag == "ss01" for tag, _ in snap.rules_by_feature)


def test_unparseable_falls_back_not_raises():
    old = parse_fea("this is not ::: valid fea @@@")
    new = parse_fea("this is not ::: valid fea @@@ extra line;")
    assert old.parse_failed and new.parse_failed
    facts = diff_fea(old, new, SCOPE)
    # Fallback yields a fact, not an exception.
    assert any(f.fact_type == FactType.FEA_RULE_ADDED for f in facts)


def _lines(old_text, new_text):
    from ufo_tdkit_report.rollup import fold_facts

    return [f.summary for f in fold_facts(diff_fea(parse_fea(old_text), parse_fea(new_text), SCOPE))]


LOOKUP = """
@DIGITS = [one two];
@PUNC = [comma];
@PUNC_ALT = [comma.alt];
lookup DIGIT_PUNCT {
    sub @DIGITS @PUNC' @DIGITS by @PUNC_ALT;
} DIGIT_PUNCT;
feature calt { lookup DIGIT_PUNCT; } calt;
feature tnum { lookup DIGIT_PUNCT; } tnum;
"""


def test_standalone_lookup_diffs_by_rule_and_names_its_features():
    """A one-line edit inside a top-level lookup is one fact — not the whole block
    removed and re-added under `feature ?`, commented-out lines included."""
    new = LOOKUP.replace(
        "    sub @DIGITS",
        "    # sub @DIGITS @PUNC' by @PUNC;\n    ignore sub @DIGITS @PUNC' space;\n    sub @DIGITS",
    )
    facts = diff_fea(parse_fea(LOOKUP), parse_fea(new), SCOPE)
    assert [f.fact_type for f in facts] == [FactType.FEA_RULE_ADDED]
    assert facts[0].scope.lookup == "DIGIT_PUNCT"
    assert _lines(LOOKUP, new) == [
        "lookup `DIGIT_PUNCT` (used in `calt`, `tnum`): rule added `ignore sub @DIGITS @PUNC' space;`"
    ]


def test_reordering_a_class_reports_the_glyph_pairs_it_swapped():
    """In `sub @A by @B` members pair by position: a reorder is a real change with no rule
    text changing. Sorting class members made it diff to nothing."""
    old = "@OFF = [g g.sc];\n@ON = [g.alt1 g.alt2];\nfeature ss02 { sub @OFF by @ON; } ss02;"
    new = old.replace("[g.alt1 g.alt2]", "[g.alt2 g.alt1]")
    assert _lines(old, new) == [
        "feature class `@ON`: members reordered",
        "feature ss02: `sub @OFF by @ON;` now maps `g` → `g.alt2` (was `g.alt1`); "
        "`g.sc` → `g.alt1` (was `g.alt2`)",
    ]


def test_class_change_names_members_as_written_not_their_expansion():
    """One glyph added to a nested class is reported once, not again under every class using it."""
    old = "@FIG = [zero one];\n@UC = [@FIG A B];"
    new = "@FIG = [zero one two];\n@UC = [@FIG A C];"
    assert _lines(old, new) == [
        "feature class `@FIG`: added `two`",
        "feature class `@UC`: added `C`; removed `B`",
    ]


def test_growing_a_class_shows_as_new_and_dropped_pairs():
    old = "@A = [one two];\n@B = [one.alt two.alt];\nfeature ss01 { sub @A by @B; } ss01;"
    new = "@A = [one three];\n@B = [one.alt three.alt];\nfeature ss01 { sub @A by @B; } ss01;"
    mapping = [line for line in _lines(old, new) if "now maps" in line]
    assert mapping == [
        "feature ss01: `sub @A by @B;` now maps `three` → `three.alt` (new); "
        "`two` no longer substituted (was `two.alt`)"
    ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
