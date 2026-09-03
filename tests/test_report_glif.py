"""Tests for the report glif parser/differ."""

import pytest

from ufo_tdkit_report.glif import diff_glif, parse_glif
from ufo_tdkit_report.model import FactType, Scope


def _glyph(name="A", advance=500, unicode_hex="0041", points=((0, 0), (10, 10)),
           components=(), anchors=(), advance_first=True):
    adv = f'<advance width="{advance}"/>'
    uni = f'<unicode hex="{unicode_hex}"/>' if unicode_hex else ""
    head = (adv + uni) if advance_first else (uni + adv)
    pts = "".join(f'<point x="{x}" y="{y}" type="line"/>' for x, y in points)
    contour = f"<contour>{pts}</contour>" if points else ""
    comps = "".join(
        f'<component base="{b}" xOffset="{dx}" yOffset="{dy}"/>' for b, dx, dy in components
    )
    anchs = "".join(f'<anchor name="{n}" x="{x}" y="{y}"/>' for n, x, y in anchors)
    return (
        f'<glyph name="{name}" format="2">{head}'
        f"<outline>{comps}{contour}</outline>{anchs}</glyph>"
    )


SCOPE = Scope(glyph="A")


def test_reordered_advance_unicode_is_noise():
    a = parse_glif(_glyph(advance_first=True))
    b = parse_glif(_glyph(advance_first=False))
    assert a == b
    assert diff_glif(a, b, SCOPE) == []


def test_redraw_same_count_moved_coords():
    a = parse_glif(_glyph(points=((0, 0), (10, 10))))
    b = parse_glif(_glyph(points=((0, 0), (99, 88))))
    kinds = [f.fact_type for f in diff_glif(a, b, SCOPE)]
    assert kinds == [FactType.OUTLINE_REDRAWN]


def test_contour_count_change():
    a = parse_glif(_glyph(points=((0, 0), (10, 10))))
    b = parse_glif(_glyph(points=((0, 0), (10, 10), (20, 20))))
    kinds = [f.fact_type for f in diff_glif(a, b, SCOPE)]
    assert kinds == [FactType.CONTOUR_COUNT_CHANGED]


def test_advance_change():
    a = parse_glif(_glyph(advance=500))
    b = parse_glif(_glyph(advance=540))
    facts = diff_glif(a, b, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.ADVANCE_CHANGED]
    assert facts[0].magnitude == 40


def test_unicode_change():
    a = parse_glif(_glyph(unicode_hex="0041"))
    b = parse_glif(_glyph(unicode_hex="0042"))
    assert [f.fact_type for f in diff_glif(a, b, SCOPE)] == [FactType.UNICODE_CHANGED]


def test_component_reorder_is_noise():
    a = parse_glif(_glyph(points=(), components=(("B", 0, 0), ("C", 5, 5))))
    b = parse_glif(_glyph(points=(), components=(("C", 5, 5), ("B", 0, 0))))
    assert diff_glif(a, b, SCOPE) == []


def test_component_move():
    a = parse_glif(_glyph(points=(), components=(("ring", 0, 0),)))
    b = parse_glif(_glyph(points=(), components=(("ring", 50, 700),)))
    facts = diff_glif(a, b, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.COMPONENT_MOVED]
    assert facts[0].detail == ("ring", 50.0, 700.0)


def test_component_added_removed():
    a = parse_glif(_glyph(points=(), components=(("B", 0, 0),)))
    b = parse_glif(_glyph(points=(), components=(("B", 0, 0), ("acute", 0, 0))))
    added = diff_glif(a, b, SCOPE)
    assert [f.fact_type for f in added] == [FactType.COMPONENT_ADDED]
    removed = diff_glif(b, a, SCOPE)
    assert [f.fact_type for f in removed] == [FactType.COMPONENT_REMOVED]


def test_anchor_reorder_is_noise():
    a = parse_glif(_glyph(anchors=(("top", 250, 700), ("bottom", 250, 0))))
    b = parse_glif(_glyph(anchors=(("bottom", 250, 0), ("top", 250, 700))))
    assert a == b
    assert diff_glif(a, b, SCOPE) == []


def test_anchor_moved():
    a = parse_glif(_glyph(anchors=(("top", 250, 700),)))
    b = parse_glif(_glyph(anchors=(("top", 250, 750),)))
    facts = diff_glif(a, b, SCOPE)
    assert [f.fact_type for f in facts] == [FactType.ANCHOR_MOVED]
    assert facts[0].detail == ("top", 0.0, 50.0)


def test_anchor_added_and_removed():
    a = parse_glif(_glyph(anchors=(("top", 250, 700),)))
    b = parse_glif(_glyph(anchors=(("top", 250, 700), ("bottom", 250, 0))))
    added = diff_glif(a, b, SCOPE)
    assert [f.fact_type for f in added] == [FactType.ANCHOR_ADDED]
    assert added[0].detail == ("bottom",)
    removed = diff_glif(b, a, SCOPE)
    assert [f.fact_type for f in removed] == [FactType.ANCHOR_REMOVED]
    assert removed[0].detail == ("bottom",)


def test_malformed_glif_returns_none():
    assert parse_glif("<glyph not closed") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
