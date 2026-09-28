"""Tests for .dssketch sources: parsed as written, diffed as a designspace."""

import subprocess
import sys

import pytest

from ufo_tdkit_report import extract_facts
from ufo_tdkit_report.classify import ChangedFile, classify_change
from ufo_tdkit_report.designspace import diff_designspace
from ufo_tdkit_report.dssketch import parse_dssketch
from ufo_tdkit_report.model import FactType, FileKind, Scope
from ufo_tdkit_report.paths import classify_path
from ufo_tdkit_report.rollup import fold_facts

PATH = "sources/Sans.dssketch"

DOC = """family Sans
path masters

axes
    weight Thin:Regular:Black
        Thin > 0
        Light > 211
        Regular > 356 @elidable
        Bold > 789
        Black > 1000
    italic discrete
        Upright @elidable
        Italic

sources [wght, ital]
    Sans_Thin [Thin, Upright]
    Sans_Regular [Regular, Upright] @base
    Sans_Black [Black, Upright]
    Sans_Italic [Regular, Italic]

rules
    dollar* cent* > .rvrn (weight >= Bold) "heavy alternates"
    A > A.alt (Regular <= weight <= Bold)

instances auto
"""


def _lines(old, new):
    facts = diff_designspace(parse_dssketch(old), parse_dssketch(new), Scope(path=PATH))
    return [f.summary for f in fold_facts(facts)]


def test_dssketch_is_a_designspace():
    assert classify_path(PATH) is FileKind.DESIGNSPACE


def test_unchanged_document_diffs_to_nothing():
    reindented = "\n".join(line.replace("    ", "  ") for line in DOC.splitlines())
    assert _lines(DOC, reindented) == []


def test_unparseable_document_returns_none():
    assert parse_dssketch("") is None
    assert parse_dssketch("this is not a dssketch") is None


def test_inferred_user_values_stay_out_of_the_facts():
    snap = parse_dssketch(DOC)
    weight = dict(snap.axis_maps)["weight"]
    # `Light > 211` leaves the user value to DSSketch's standards table: keyed by label.
    assert ("Light", 211.0) in weight
    assert not any(isinstance(user, float) for user, _ in weight)
    # The extent written with labels stays labels, not the table's numbers.
    assert dict(snap.axes)["weight"] == "wght Thin:Regular:Black"


def test_a_standards_table_change_is_not_a_source_change(monkeypatch):
    import ufo_tdkit_report.dssketch as mod

    real = mod._parse

    def drifted(blob):  # what a DSSketch release with another table would infer
        doc = real(blob)
        for axis in doc.axes:
            inferred = {m.user_value for m in axis.mappings if not m.user_value_explicit}
            for bound in ("minimum", "default", "maximum"):  # an extent written with labels
                if getattr(axis, bound) in inferred:
                    setattr(axis, bound, getattr(axis, bound) + 5)
            for m in axis.mappings:
                if not m.user_value_explicit:
                    m.user_value += 5
        return doc

    before = parse_dssketch(DOC)
    monkeypatch.setattr(mod, "_parse", drifted)
    after = parse_dssketch(DOC)
    assert diff_designspace(before, after, Scope(path=PATH)) == []


def test_mapping_edits_name_the_label_or_the_written_user_value():
    new = DOC.replace("Light > 211", "Light > 220").replace("Bold > 789", "700 Bold > 789")
    assert _lines(DOC, new) == [
        "`sources/Sans.dssketch`: axis `weight` labels: added `Bold` (700)",
        "`sources/Sans.dssketch`: axis `weight` map: user 700 → design 789 (new); "
        "`Bold` no longer mapped (was 789); `Light` → design 220 (was 211)",
    ]


def test_elidable_flag_on_an_inferred_label():
    new = DOC.replace("Regular > 356 @elidable", "Regular > 356")
    assert _lines(DOC, new) == ["`sources/Sans.dssketch`: axis `weight` labels: removed `Regular` (elidable)"]


def test_master_moved_and_added():
    moved = "Sans_Italic [Bold, Italic]\n    Sans_Black_Italic [Black, Italic]"
    new = DOC.replace("Sans_Italic [Regular, Italic]", moved)
    assert _lines(DOC, new) == [
        "`sources/Sans.dssketch`: master `Sans_Black_Italic` added",
        "`sources/Sans.dssketch`: masters moved: `Sans_Italic` weight 356 → 789",
    ]


def test_names_with_spaces_are_kept_whole():
    # Before DSSketch 1.2.1 an unquoted name kept its first word: every `My Font …` master
    # became `My`, merging them into one, and a family rename read as no change.
    doc = DOC.replace("Sans_Thin [", "My Font Thin [").replace("Sans_Black [", "My Font Black [")
    assert {"My Font Thin", "My Font Black"} <= set(parse_dssketch(doc).sources)
    assert _lines(DOC, DOC.replace("family Sans", "family Sans Pro")) == [
        "`sources/Sans.dssketch`: family `Sans Pro` (was `Sans`)"
    ]


def test_rules_compare_as_written_with_open_bounds():
    new = DOC.replace("(weight >= Bold)", "(weight >= Regular)")
    assert _lines(DOC, new) == [
        "`sources/Sans.dssketch`: rule `heavy alternates`: `dollar* cent*` → `.rvrn` when weight ≥ 356 "
        "(was `dollar* cent*` → `.rvrn` when weight ≥ 789)"
    ]


def test_an_unnamed_rule_is_not_renamed_by_inserting_one_before_it():
    new = DOC.replace("rules\n", "rules\n    B > B.alt (weight >= Black)\n")
    assert _lines(DOC, new) == [
        "`sources/Sans.dssketch`: rule `B > B.alt` added: `B` → `B.alt` when weight ≥ 1000"
    ]


def test_document_settings():
    new = DOC.replace("instances auto", "instances off").replace("family Sans", "family Serif")
    assert _lines(DOC, new) == [
        "`sources/Sans.dssketch`: family `Serif` (was `Sans`)",
        "`sources/Sans.dssketch`: instances `off` (was `auto`)",
    ]


def test_classify_routes_dssketch_and_scopes_facts_to_the_file():
    new = DOC.replace("Light > 211", "Light > 220")
    facts = classify_change(ChangedFile(PATH, "M", DOC, new))
    assert [f.fact_type for f in facts] == [FactType.AXIS_MAP_CHANGED]
    assert {f.scope.path for f in facts} == {PATH}


def test_parsing_does_not_load_defcon():
    code = (
        "import sys; from ufo_tdkit_report.dssketch import parse_dssketch; "
        f"assert parse_dssketch({DOC!r}) is not None; "
        "assert 'defcon' not in sys.modules and 'fontTools' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_committed_range_reports_dssketch_facts_and_falls_back_when_unparseable(tmp_path):
    repo = tmp_path / "font"
    (repo / "sources").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / PATH).write_text(DOC)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    (repo / PATH).write_text(DOC.replace("instances auto", "instances off"))
    _git(repo, "commit", "-qam", "two")
    (repo / PATH).write_text("broken\n")
    _git(repo, "commit", "-qam", "three")

    summaries = [f.summary for f in extract_facts(str(repo), "HEAD~2..HEAD~1").folded_facts]
    assert summaries == ["`sources/Sans.dssketch`: instances `off` (was `auto`)"]
    broken = extract_facts(str(repo), "HEAD~1..HEAD").folded_facts
    assert [f.fact_type for f in broken] == [FactType.FILE_CHANGED]  # T3: named, not dropped


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
