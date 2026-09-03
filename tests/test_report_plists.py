"""Tests for the report plist differs: kerning, groups, fontinfo."""

import plistlib

import pytest

from ufo_tdkit_report.model import FactType, Scope
from ufo_tdkit_report.plists import (
    diff_fontinfo,
    diff_groups,
    diff_kerning,
    parse_fontinfo,
    parse_groups,
    parse_kerning,
)

SCOPE = Scope()


def _plist(data):
    return plistlib.dumps(data).decode("utf-8")


def test_kerning_add_remove_change():
    old = parse_kerning(_plist({"A": {"V": -80, "W": -40}}))
    new = parse_kerning(_plist({"A": {"V": -100, "T": -30}}))
    facts = {f.fact_type for f in diff_kerning(old, new, SCOPE)}
    assert FactType.KERN_PAIR_CHANGED in facts  # V -80 -> -100
    assert FactType.KERN_PAIR_ADDED in facts    # T
    assert FactType.KERN_PAIR_REMOVED in facts  # W


def test_kerning_reorder_is_noise():
    old = parse_kerning(_plist({"A": {"V": -80}, "B": {"O": 10}}))
    new = parse_kerning(_plist({"B": {"O": 10}, "A": {"V": -80}}))
    assert old == new
    assert diff_kerning(old, new, SCOPE) == []


def test_groups_membership_change():
    old = parse_groups(_plist({"public.kern1.A": ["A", "Aacute"]}))
    new = parse_groups(_plist({"public.kern1.A": ["A", "Aacute", "Agrave"]}))
    facts = diff_groups(old, new, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.GROUP_MEMBERSHIP_CHANGED]
    name, added, removed = facts[0].detail
    assert added == ("Agrave",)
    assert removed == ()


def test_groups_added_removed():
    old = parse_groups(_plist({"g1": ["A"]}))
    new = parse_groups(_plist({"g2": ["B"]}))
    facts = {f.fact_type for f in diff_groups(old, new, SCOPE)}
    assert facts == {FactType.GROUP_ADDED, FactType.GROUP_REMOVED}


def test_fontinfo_version_change():
    old = parse_fontinfo(_plist({"versionMajor": 2, "versionMinor": 5, "familyName": "Dummy"}))
    new = parse_fontinfo(_plist({"versionMajor": 2, "versionMinor": 6, "familyName": "Dummy"}))
    facts = diff_fontinfo(old, new, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.FONTINFO_CHANGED]
    assert facts[0].detail[0] == "versionMinor"


def test_fontinfo_ignores_unlisted_keys():
    old = parse_fontinfo(_plist({"familyName": "Dummy", "note": "internal a"}))
    new = parse_fontinfo(_plist({"familyName": "Dummy", "note": "internal b"}))
    assert diff_fontinfo(old, new, SCOPE) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
