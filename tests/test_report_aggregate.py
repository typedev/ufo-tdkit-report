"""Tests for the report range aggregator."""

import subprocess

import pytest

from ufo_tdkit_report import aggregate_range
from ufo_tdkit_report.aggregate import net_out
from ufo_tdkit_report.model import ChangeFact, FactType, FileKind, Scope

# --------------------------------------------------------------------------- #
# net_out (pure)
# --------------------------------------------------------------------------- #


def _fact(ft, glyph=None, detail=(), feature_tag=None):
    return ChangeFact(ft, FileKind.GLIF, Scope(glyph=glyph, feature_tag=feature_tag), detail)


def test_net_out_glyph_add_then_remove_cancels():
    facts = [
        _fact(FactType.GLYPH_ADDED, glyph="A", detail=("A",)),
        _fact(FactType.GLYPH_REMOVED, glyph="A", detail=("A",)),
    ]
    kept, removed = net_out(facts)
    assert kept == []
    assert removed == 2


def test_net_out_one_way_add_survives():
    facts = [_fact(FactType.GLYPH_ADDED, glyph="A", detail=("A",))]
    kept, removed = net_out(facts)
    assert len(kept) == 1
    assert removed == 0


def test_net_out_kern_pair_cancels():
    pair = ("A", "V")
    facts = [
        ChangeFact(FactType.KERN_PAIR_ADDED, FileKind.KERNING, Scope(), (pair, -80)),
        ChangeFact(FactType.KERN_PAIR_REMOVED, FileKind.KERNING, Scope(), (pair, -80)),
    ]
    kept, removed = net_out(facts)
    assert kept == []
    assert removed == 2


def test_net_out_fea_rule_cancels_but_other_survives():
    facts = [
        _fact(FactType.FEA_RULE_ADDED, feature_tag="ss02", detail=("sub a by a.ss02;",)),
        _fact(FactType.FEA_RULE_REMOVED, feature_tag="ss02", detail=("sub a by a.ss02;",)),
        _fact(FactType.FEA_RULE_ADDED, feature_tag="ss02", detail=("sub b by b.ss02;",)),
    ]
    kept, removed = net_out(facts)
    assert removed == 2
    assert [f.detail for f in kept] == [("sub b by b.ss02;",)]


def test_net_out_does_not_touch_non_paired_types():
    facts = [_fact(FactType.OUTLINE_REDRAWN, glyph="A", detail=(5,))]
    kept, removed = net_out(facts)
    assert len(kept) == 1
    assert removed == 0


# --------------------------------------------------------------------------- #
# aggregate_range end-to-end against a real temp repo
# --------------------------------------------------------------------------- #


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _glif(name="A", advance=500, points=((0, 0), (10, 10))):
    pts = "".join(f'<point x="{x}" y="{y}" type="line"/>' for x, y in points)
    return (
        f'<glyph name="{name}" format="2"><advance width="{advance}"/>'
        f"<outline><contour>{pts}</contour></outline></glyph>"
    )


def _make_repo(tmp_path):
    repo = tmp_path / "font"
    glyphs = repo / "MasterRegular.ufo" / "glyphs"
    glyphs.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo, glyphs


def test_aggregate_walks_commits_and_collects_subjects(tmp_path):
    repo, glyphs = _make_repo(tmp_path)
    a = glyphs / "A_.glif"
    a.write_text(_glif("A", points=((0, 0), (10, 10))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init A")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    # commit 1: redraw A
    a.write_text(_glif("A", points=((0, 0), (99, 88))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "redraw A")

    # commit 2: add glyph B
    (glyphs / "B_.glif").write_text(_glif("B"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add B")

    report = aggregate_range(str(repo), f"{base}..HEAD")
    assert report.commit_count == 2
    subjects = [s for _, s in report.commits]
    assert subjects == ["redraw A", "add B"]

    kinds = {f.fact_type for f in report.folded_facts}
    assert FactType.OUTLINE_REDRAWN in kinds
    assert FactType.GLYPH_ADDED in kinds

    text = report.render_text()
    assert "redraw A" in text and "add B" in text
    assert "outline redrawn in `A`" in text


def test_aggregate_nets_out_add_then_remove(tmp_path):
    repo, glyphs = _make_repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    # commit 1: add glyph B
    b = glyphs / "B_.glif"
    b.write_text(_glif("B"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add B")

    # commit 2: remove glyph B again (net zero across the range)
    b.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove B")

    report = aggregate_range(str(repo), f"{base}..HEAD")
    assert report.net_removed_count == 2
    assert all(f.fact_type != FactType.GLYPH_ADDED for f in report.folded_facts)
    assert all(f.fact_type != FactType.GLYPH_REMOVED for f in report.folded_facts)


def test_aggregate_folds_repeated_edits_to_one_fact(tmp_path):
    repo, glyphs = _make_repo(tmp_path)
    a = glyphs / "A_.glif"
    a.write_text(_glif("A", points=((0, 0), (10, 10))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    # Redraw A in two consecutive commits.
    a.write_text(_glif("A", points=((0, 0), (50, 50))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "redraw 1")
    a.write_text(_glif("A", points=((0, 0), (99, 88))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "redraw 2")

    report = aggregate_range(str(repo), f"{base}..HEAD")
    redraws = [f for f in report.folded_facts if f.fact_type == FactType.OUTLINE_REDRAWN]
    assert len(redraws) == 1  # both commits' redraws of A fold into one fact


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
