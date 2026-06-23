"""Parse and diff ``.glif`` sources semantically (issue #5, phase 1).

A glif blob is parsed via ``readGlyphFromString`` into a defcon ``Glyph`` so the
view is normalized: ``<advance>``/``<unicode>`` ordering and whitespace are ignored,
which filters editor re-serialization noise. Outlines are compared by point
*coordinates*, not point count, so a redraw that preserves the count is detected.
"""

from __future__ import annotations

from ufo_tdkit_report.model import (
    AnchorSig,
    ChangeFact,
    ComponentRef,
    ContourSig,
    FactType,
    FileKind,
    GlifSnapshot,
    Scope,
)

# Coordinate rounding: integer/float serialization differences must not look like
# changes, but real sub-unit edits should still register.
_COORD_PRECISION = 3


def _round(value: float) -> float:
    return round(float(value), _COORD_PRECISION)


def parse_glif(glif_xml: str) -> GlifSnapshot | None:
    """Parse a glif XML string into a normalized snapshot, or None on failure."""
    import defcon
    from fontTools.ufoLib.glifLib import readGlyphFromString

    glyph = defcon.Glyph()
    try:
        readGlyphFromString(glif_xml, glyphObject=glyph, pointPen=glyph.getPointPen())
    except Exception:
        return None

    components = tuple(
        ComponentRef(
            base=c.baseGlyph,
            x_scale=_round(c.transformation[0]),
            xy_scale=_round(c.transformation[1]),
            yx_scale=_round(c.transformation[2]),
            y_scale=_round(c.transformation[3]),
            x_offset=_round(c.transformation[4]),
            y_offset=_round(c.transformation[5]),
        )
        for c in glyph.components
    )
    contours = tuple(
        ContourSig(points=tuple((_round(p.x), _round(p.y), p.segmentType) for p in contour))
        for contour in glyph
    )
    anchors = frozenset(
        AnchorSig(name=a.name, x=_round(a.x), y=_round(a.y)) for a in glyph.anchors
    )
    lib_items = tuple(sorted((str(k), repr(v)) for k, v in dict(glyph.lib).items()))

    return GlifSnapshot(
        name=glyph.name,
        advance_width=_round(glyph.width) if glyph.width is not None else None,
        advance_height=_round(glyph.height) if glyph.height is not None else None,
        unicodes=tuple(sorted(set(glyph.unicodes))),
        components=components,
        contours=contours,
        anchors=anchors,
        lib_items=lib_items,
    )


def _diff_components(old: GlifSnapshot, new: GlifSnapshot, scope: Scope) -> list[ChangeFact]:
    """Match components by base name (tolerant of reorder) and classify changes."""
    facts: list[ChangeFact] = []

    def by_base(comps: tuple[ComponentRef, ...]) -> dict[str, list[ComponentRef]]:
        out: dict[str, list[ComponentRef]] = {}
        for c in comps:
            out.setdefault(c.base, []).append(c)
        return out

    old_by_base = by_base(old.components)
    new_by_base = by_base(new.components)

    for base in sorted(set(old_by_base) | set(new_by_base)):
        olds = old_by_base.get(base, [])
        news = new_by_base.get(base, [])
        # Pair as many as exist on both sides (stable order); leftovers = add/remove.
        paired = min(len(olds), len(news))
        for o, n in zip(olds[:paired], news[:paired]):
            if o == n:
                continue
            dx, dy = _round(n.x_offset - o.x_offset), _round(n.y_offset - o.y_offset)
            if (dx, dy) != (0, 0):
                facts.append(ChangeFact(FactType.COMPONENT_MOVED, FileKind.GLIF, scope, (base, dx, dy)))
            if o.scale != n.scale:
                facts.append(ChangeFact(FactType.COMPONENT_SCALED, FileKind.GLIF, scope, (base,)))
        for _ in news[paired:]:
            facts.append(ChangeFact(FactType.COMPONENT_ADDED, FileKind.GLIF, scope, (base,)))
        for _ in olds[paired:]:
            facts.append(ChangeFact(FactType.COMPONENT_REMOVED, FileKind.GLIF, scope, (base,)))
    return facts


def _diff_anchors(old: GlifSnapshot, new: GlifSnapshot, scope: Scope) -> list[ChangeFact]:
    """Match anchors by name (tolerant of reorder) and classify add/remove/move."""
    facts: list[ChangeFact] = []

    def by_name(anchors) -> dict[str, list]:
        out: dict[str, list] = {}
        for a in anchors:
            out.setdefault(a.name or "", []).append(a)
        return out

    old_by_name = by_name(old.anchors)
    new_by_name = by_name(new.anchors)

    for name in sorted(set(old_by_name) | set(new_by_name)):
        olds = old_by_name.get(name, [])
        news = new_by_name.get(name, [])
        paired = min(len(olds), len(news))
        for o, n in zip(olds[:paired], news[:paired]):
            dx, dy = _round(n.x - o.x), _round(n.y - o.y)
            if (dx, dy) != (0, 0):
                facts.append(ChangeFact(FactType.ANCHOR_MOVED, FileKind.GLIF, scope, (name, dx, dy)))
        for _ in news[paired:]:
            facts.append(ChangeFact(FactType.ANCHOR_ADDED, FileKind.GLIF, scope, (name,)))
        for _ in olds[paired:]:
            facts.append(ChangeFact(FactType.ANCHOR_REMOVED, FileKind.GLIF, scope, (name,)))
    return facts


def _diff_outline(old: GlifSnapshot, new: GlifSnapshot, scope: Scope) -> list[ChangeFact]:
    facts: list[ChangeFact] = []
    old_counts = tuple(c.n_points for c in old.contours)
    new_counts = tuple(c.n_points for c in new.contours)
    if (len(old.contours), old_counts) != (len(new.contours), new_counts):
        facts.append(
            ChangeFact(
                FactType.CONTOUR_COUNT_CHANGED,
                FileKind.GLIF,
                scope,
                (len(old.contours), len(new.contours)),
            )
        )
        return facts

    # Same structure (contour count + per-contour point counts): look for moved coords.
    moved = 0
    for o, n in zip(old.contours, new.contours):
        if o.points != n.points:
            moved += sum(1 for a, b in zip(o.points, n.points) if a != b)
    if moved:
        facts.append(ChangeFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, scope, (moved,), magnitude=moved))
    return facts


def diff_glif(old: GlifSnapshot, new: GlifSnapshot, scope: Scope) -> list[ChangeFact]:
    """Classified change records between two glyph snapshots (same glyph)."""
    facts: list[ChangeFact] = []

    if (old.advance_width, old.advance_height) != (new.advance_width, new.advance_height):
        magnitude = None
        if old.advance_width is not None and new.advance_width is not None:
            magnitude = abs(new.advance_width - old.advance_width)
        facts.append(
            ChangeFact(
                FactType.ADVANCE_CHANGED,
                FileKind.GLIF,
                scope,
                (old.advance_width, new.advance_width),
                magnitude=magnitude,
            )
        )

    if old.unicodes != new.unicodes:
        facts.append(ChangeFact(FactType.UNICODE_CHANGED, FileKind.GLIF, scope, (old.unicodes, new.unicodes)))

    facts.extend(_diff_components(old, new, scope))
    facts.extend(_diff_outline(old, new, scope))

    if old.anchors != new.anchors:
        facts.extend(_diff_anchors(old, new, scope))

    if old.lib_items != new.lib_items:
        facts.append(ChangeFact(FactType.GLYPH_LIB_CHANGED, FileKind.GLIF, scope))

    return facts
