"""Tests for the report designspace differ."""

import pytest

from ufo_tdkit_report.classify import ChangedFile, classify_change
from ufo_tdkit_report.designspace import diff_designspace, parse_designspace
from ufo_tdkit_report.model import FactType, Scope
from ufo_tdkit_report.rollup import fold_facts

SCOPE = Scope()
PATH = "fonts/Sans.designspace"


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


def _doc(
    maps=((100, 100), (200, 160), (900, 970)),
    labels=(("Thin", 200),),
    masters=(("Thin", 100), ("Black", 900)),
    instances=(("Thin", 160), ("Black", 970)),
    rules="",
):
    """A format-5 designspace with an axis map, labels, located masters and instances."""
    axis_maps = "".join(f'<map input="{i}" output="{o}"/>' for i, o in maps)
    axis_labels = "".join(f'<label uservalue="{v}" name="{n}"/>' for n, v in labels)
    sources = "".join(
        f'<source filename="masters/Sans-{n}.ufo" name="source.{k}">'
        f'<location><dimension name="weight" xvalue="{v}"/></location></source>'
        for k, (n, v) in enumerate(masters)
    )
    insts = "".join(
        f'<instance familyname="Sans" stylename="{n}" postscriptfontname="Sans-{n}">'
        f'<location><dimension name="weight" xvalue="{v}"/></location></instance>'
        for n, v in instances
    )
    return (
        '<?xml version="1.0"?><designspace format="5.0"><axes>'
        f'<axis tag="wght" name="weight" minimum="100" maximum="900" default="400">'
        f"{axis_maps}<labels>{axis_labels}</labels></axis></axes>"
        f"<rules>{rules}</rules><sources>{sources}</sources><instances>{insts}</instances>"
        "</designspace>"
    )


def _lines(old, new):
    facts = diff_designspace(parse_designspace(old), parse_designspace(new), Scope(path=PATH))
    return [f.summary for f in fold_facts(facts)]


def test_axis_change():
    old = parse_designspace(_ds(axis_max=900))
    new = parse_designspace(_ds(axis_max=1000))
    assert [f.fact_type for f in diff_designspace(old, new, SCOPE)] == [FactType.AXIS_CHANGED]
    assert _lines(_ds(axis_max=900), _ds(axis_max=1000)) == [
        "`fonts/Sans.designspace`: axis `Weight` changed wght 100:400:900 → wght 100:400:1000"
    ]


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


def test_remapping_an_axis_names_the_values_and_the_instances_that_followed():
    """The motivating miss: an axis remap moved every named style and read as 'modified'."""
    new = _doc(maps=((100, 100), (200, 175), (900, 983)), instances=(("Thin", 175), ("Black", 983)))
    assert _lines(_doc(), new) == [
        "`fonts/Sans.designspace`: axis `weight` map: user 200 → design 175 (was 160); "
        "user 900 → design 983 (was 970)",
        "`fonts/Sans.designspace`: instances moved: `Sans-Black` weight 970 → 983; "
        "`Sans-Thin` weight 160 → 175",
    ]


def test_axis_map_points_added_and_dropped():
    new = _doc(maps=((100, 100), (300, 250), (900, 970)))
    assert _lines(_doc(), new) == [
        "`fonts/Sans.designspace`: axis `weight` map: user 200 no longer mapped (was 160); "
        "user 300 → design 250 (new)"
    ]


def test_axis_labels_added_and_removed():
    old = _doc(labels=(("Thin", 200), ("ExBold", 800)))
    new = _doc(labels=(("Hair", 100), ("Thin", 200)))
    assert _lines(old, new) == [
        "`fonts/Sans.designspace`: axis `weight` labels: added `Hair` (100); removed `ExBold` (800)"
    ]


def test_master_identity_is_the_ufo_not_the_generated_source_name():
    """Inserting a source shifts every `source.N` name; that must not read as all-new masters."""
    new = _doc(masters=(("Bold", 700), ("Thin", 100), ("Black", 900)))
    facts = diff_designspace(parse_designspace(_doc()), parse_designspace(new), SCOPE)
    assert [(f.fact_type, f.detail) for f in facts] == [(FactType.MASTER_ADDED, ("Sans-Bold",))]


def test_master_moved():
    new = _doc(masters=(("Thin", 100), ("Black", 880)))
    assert _lines(_doc(), new) == ["`fonts/Sans.designspace`: masters moved: `Sans-Black` weight 900 → 880"]


RULE = (
    '<rule name="bars"><conditionset><condition name="weight" minimum="100" maximum="{hi}"/>'
    '</conditionset><sub name="dollar" with="dollar.alt"/></rule>'
)


def test_rule_added():
    assert _lines(_doc(), _doc(rules=RULE.format(hi=600))) == [
        "`fonts/Sans.designspace`: rule `bars` added: `dollar` → `dollar.alt` when 100 ≤ weight ≤ 600"
    ]


def test_rule_condition_change_shows_both_sides():
    assert _lines(_doc(rules=RULE.format(hi=600)), _doc(rules=RULE.format(hi=500))) == [
        "`fonts/Sans.designspace`: rule `bars`: `dollar` → `dollar.alt` when 100 ≤ weight ≤ 500 "
        "(was `dollar` → `dollar.alt` when 100 ≤ weight ≤ 600)"
    ]


def test_classify_scopes_designspace_facts_to_their_file():
    new = _doc(masters=(("Thin", 100), ("Black", 880)))
    facts = classify_change(ChangedFile(PATH, "M", _doc(), new))
    assert {f.scope.path for f in facts} == {PATH}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
