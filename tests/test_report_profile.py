"""Tests for the report build-profile YAML differ (issue #5)."""

import pytest

from ufo_tdkit_report.model import FactType, Scope
from ufo_tdkit_report.profile import diff_profile, parse_profile
from ufo_tdkit_report.rollup import fold_facts

SCOPE = Scope()


class _FakeSpec:
    """Minimal stand-in for an injected schema's per-option spec."""

    def __init__(self, text: str):
        self._text = text

    def consequence_text(self, off):  # noqa: ARG002 — fake ignores direction
        return self._text


class _FakeSchema:
    """Duck-typed schema: ``get(key) -> spec with consequence_text(off)`` or None.

    The real option schema lives in the build tool (e.g. tdbuilder) and is injected;
    this package only relies on the seam, so the test injects a tiny fake.
    """

    def __init__(self, mapping: dict):
        self._m = {k: _FakeSpec(v) for k, v in mapping.items()}

    def get(self, key):
        return self._m.get(key)


def _summary(old_yaml: str, new_yaml: str, *, schema=None) -> str:
    facts = diff_profile(parse_profile(old_yaml), parse_profile(new_yaml), SCOPE)
    folded = fold_facts(facts, schema=schema)
    assert len(folded) == 1
    return folded[0].summary


def test_option_added_and_changed():
    old = parse_profile("path: src/Dummy.designspace\nversionMinor: 5\n")
    new = parse_profile("path: src/Dummy.designspace\nversionMinor: 6\nttfautohint: true\n")
    facts = diff_profile(old, new, SCOPE)
    kinds = {f.fact_type for f in facts}
    assert FactType.PROFILE_OPTION_ADDED in kinds     # ttfautohint
    assert FactType.PROFILE_OPTION_CHANGED in kinds   # versionMinor


def test_consequence_appended_for_known_option():
    """An injected schema's consequence is appended to the build-profile fact."""
    schema = _FakeSchema({"ttfautohint": "no TT hinting is applied"})
    s = _summary(
        "path: x.designspace\nttfautohint: true\n",
        "path: x.designspace\nttfautohint: false\n",
        schema=schema,
    )
    assert "changed True -> False" in s
    assert "no TT hinting is applied" in s  # the injected consequence text


def test_no_schema_is_byte_identical_bare_line():
    """schema=None reproduces the original schema-agnostic summary (no suffix)."""
    s = _summary(
        "path: x.designspace\nttfautohint: true\n",
        "path: x.designspace\nttfautohint: false\n",
    )
    assert s == "build profile: option `ttfautohint` changed True -> False"


def test_unknown_option_falls_back_unchanged():
    """A key absent from the injected schema -> bare line, no crash, no suffix."""
    schema = _FakeSchema({})
    s = _summary(
        "path: x.designspace\nzzz_custom: 1\n",
        "path: x.designspace\nzzz_custom: 2\n",
        schema=schema,
    )
    assert s == "build profile: option `zzz_custom` changed 1 -> 2"


def test_nested_dict_option_diffs_by_dotted_key():
    old = parse_profile("path: x.designspace\nfontinfo:\n  versionMinor: 5\n  familyName: Dummy\n")
    new = parse_profile("path: x.designspace\nfontinfo:\n  versionMinor: 6\n  familyName: Dummy\n")
    facts = diff_profile(old, new, SCOPE)
    # Only the nested key that changed surfaces — not the whole fontinfo dict.
    assert len(facts) == 1
    assert facts[0].fact_type == FactType.PROFILE_OPTION_CHANGED
    assert facts[0].detail == ("fontinfo.versionMinor", "5", "6")


def test_nested_dict_key_added():
    old = parse_profile("path: x.designspace\nfontinfo:\n  versionMinor: 5\n")
    new = parse_profile("path: x.designspace\nfontinfo:\n  versionMinor: 5\n  designer: Someone\n")
    facts = diff_profile(old, new, SCOPE)
    assert len(facts) == 1
    assert facts[0].fact_type == FactType.PROFILE_OPTION_ADDED
    assert facts[0].detail[0] == "fontinfo.designer"


def test_option_removed():
    old = parse_profile("path: x.designspace\nttfautohint: true\n")
    new = parse_profile("path: x.designspace\n")
    facts = diff_profile(old, new, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.PROFILE_OPTION_REMOVED]


def test_reordered_keys_is_noise():
    old = parse_profile("path: x.designspace\nvariable: true\nstatic: false\n")
    new = parse_profile("static: false\nvariable: true\npath: x.designspace\n")
    assert old == new
    assert diff_profile(old, new, SCOPE) == []


def test_non_profile_yaml_rejected():
    # No 'path' key -> not a TDKit profile (e.g. a CI config).
    assert parse_profile("name: CI\non: push\njobs: {}\n") is None


def test_invalid_yaml_returns_none():
    assert parse_profile("path: [unbalanced\n") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
