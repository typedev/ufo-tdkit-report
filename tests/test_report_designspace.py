"""Tests for the report designspace differ."""

import pytest

from ufo_tdkit_report.designspace import diff_designspace, parse_designspace
from ufo_tdkit_report.model import FactType, Scope

SCOPE = Scope()


def _ds(axis_max=900, masters=("Regular", "Bold"), instances=("Regular",)):
    sources = "".join(
        f'<source filename="{m}.ufo" name="{m}"/>' for m in masters
    )
    insts = "".join(f'<instance name="{i}"/>' for i in instances)
    return (
        '<designspace format="4.0">'
        f'<axes><axis tag="wght" name="Weight" minimum="100" maximum="{axis_max}" default="400"/></axes>'
        f"<sources>{sources}</sources>"
        f"<instances>{insts}</instances>"
        "</designspace>"
    )


def test_axis_change():
    old = parse_designspace(_ds(axis_max=900))
    new = parse_designspace(_ds(axis_max=1000))
    assert [f.fact_type for f in diff_designspace(old, new, SCOPE)] == [FactType.AXIS_CHANGED]


def test_master_added():
    old = parse_designspace(_ds(masters=("Regular",)))
    new = parse_designspace(_ds(masters=("Regular", "Bold")))
    facts = diff_designspace(old, new, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.MASTER_ADDED]
    assert facts[0].detail == ("Bold",)


def test_reordered_sources_is_noise():
    old = parse_designspace(_ds(masters=("Regular", "Bold")))
    new = parse_designspace(_ds(masters=("Bold", "Regular")))
    assert old == new
    assert diff_designspace(old, new, SCOPE) == []


def test_malformed_designspace_returns_none():
    assert parse_designspace("<designspace not closed") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
