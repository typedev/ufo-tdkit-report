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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
