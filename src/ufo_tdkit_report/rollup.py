"""Collapse raw atomic facts into a few user-facing folded facts (issue #5, phase 1).

The compression that turns "293 changed files" into "~6 facts": group identical
atoms across masters, group component shifts by ``(base, delta)``, and above a
detail threshold emit statistics instead of enumerating every glyph.

All ordering is total and value-based so output is byte-stable.
"""

from __future__ import annotations

from collections import defaultdict

from ufo_tdkit_report.model import ChangeFact, FactType, FoldedFact

DEFAULT_THRESHOLD = 12

# Fact types whose facts are grouped by base component + delta (cross-glyph batch ops).
_COMPONENT_TYPES = {
    FactType.COMPONENT_MOVED,
    FactType.COMPONENT_SCALED,
    FactType.COMPONENT_ADDED,
    FactType.COMPONENT_REMOVED,
}


# Glyph-scoped value facts whose per-master detail (delta, point count) is aggregated
# in the summary rather than splitting the group. Identity is just the glyph.
_GLYPH_VALUE_TYPES = {
    FactType.ADVANCE_CHANGED,
    FactType.UNICODE_CHANGED,
    FactType.GLYPH_LIB_CHANGED,
    FactType.OUTLINE_REDRAWN,
    FactType.CONTOUR_COUNT_CHANGED,
    FactType.GLYPH_ADDED,
    FactType.GLYPH_REMOVED,
}

# Anchor facts fold by (glyph, anchor name); the move delta is aggregated in the summary
# (a distribution across masters), mirroring component moves.
_ANCHOR_TYPES = {FactType.ANCHOR_ADDED, FactType.ANCHOR_REMOVED, FactType.ANCHOR_MOVED}


def _key_detail(fact: ChangeFact) -> tuple:
    """The stable identity carried in the fold key (per-master variation excluded)."""
    if fact.fact_type is FactType.FILE_CHANGED:
        return ()  # all "other file" constatations fold into one group (T3)
    if fact.fact_type in _GLYPH_VALUE_TYPES:
        return ()  # identity is the glyph alone; deltas aggregate in the summary
    if fact.fact_type in _COMPONENT_TYPES:
        return (fact.detail[0],) if fact.detail else ()  # base name only
    # kern pair, group name, fontinfo key, fea rule/class/feature, profile option key
    return (fact.detail[0],) if fact.detail else ()


def _fold_key(fact: ChangeFact) -> tuple:
    """A value tuple identifying the fold group a fact belongs to.

    Master is deliberately excluded so the same edit across N masters collapses into
    one group. Component facts fold by base (across glyphs) to surface batch ops; the
    delta distribution is shown in the summary.
    """
    if fact.fact_type in _COMPONENT_TYPES:
        return (fact.fact_type, fact.file_kind, _key_detail(fact))
    return (fact.fact_type, fact.file_kind, fact.scope.glyph, fact.scope.feature_tag, _key_detail(fact))


def _glyphs(group: list[ChangeFact]) -> list[str]:
    return sorted({f.scope.glyph for f in group if f.scope.glyph})


def _masters(group: list[ChangeFact]) -> list[str]:
    return sorted({f.scope.master for f in group if f.scope.master})


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# repr() strings (profile facts carry repr'd values) that read as "off"/default.
_OFF_REPRS = {"False", "None", "''", '""', "0", "[]", "{}"}


def _repr_is_off(value_repr: str) -> bool:
    return value_repr in _OFF_REPRS


def default_profile_schema():
    """Profile-option schema for consequence enrichment — None unless injected.

    ufo-tdkit-report is standalone and git-centric: it has no built-in knowledge of
    any build tool's profile options. A consumer that owns a schema (e.g. tdbuilder)
    passes it via ``fold_facts(..., schema=...)``; without one, build-profile facts
    render as the bare, schema-agnostic line.
    """
    return None


def _summarize(key: tuple, group: list[ChangeFact], schema=None) -> str:
    fact_type: FactType = key[0]
    sample = group[0]
    masters = _masters(group)
    glyphs = _glyphs(group)
    master_suffix = f" across {_plural(len(masters), 'master')}" if masters else ""

    if fact_type in _COMPONENT_TYPES:
        base = sample.detail[0] if sample.detail else "?"
        if fact_type is FactType.COMPONENT_MOVED:
            deltas: dict[tuple, int] = defaultdict(int)
            for f in group:
                deltas[(f.detail[1], f.detail[2])] += 1
            ordered = sorted(deltas.items(), key=lambda kv: (-kv[1], kv[0]))
            if len(ordered) == 1:
                (dx, dy), _ = ordered[0]
                delta_str = f" by ({dx:+g},{dy:+g})"
            else:
                shown = "; ".join(f"Δ({dx:+g},{dy:+g})×{n}" for (dx, dy), n in ordered[:4])
                more = f" +{len(ordered) - 4} more" if len(ordered) > 4 else ""
                delta_str = f" ({shown}{more})"
            return (
                f"component `{base}` repositioned in {_plural(len(glyphs), 'glyph')}"
                f"{master_suffix}{delta_str}"
            )
        verb = {
            FactType.COMPONENT_SCALED: "rescaled",
            FactType.COMPONENT_ADDED: "added",
            FactType.COMPONENT_REMOVED: "removed",
        }[fact_type]
        return f"component `{base}` {verb} in {_plural(len(glyphs), 'glyph')}{master_suffix}"

    if fact_type in (FactType.GLYPH_ADDED, FactType.GLYPH_REMOVED):
        verb = "added" if fact_type is FactType.GLYPH_ADDED else "removed"
        return f"glyph `{sample.scope.glyph}` {verb}{master_suffix}"

    if fact_type is FactType.OUTLINE_REDRAWN:
        moved = int(max((f.magnitude or 0) for f in group))
        return f"outline redrawn in `{sample.scope.glyph}` (~{_plural(moved, 'point')} moved){master_suffix}"

    if fact_type is FactType.ADVANCE_CHANGED:
        deltas = [
            f.detail[1] - f.detail[0]
            for f in group
            if len(f.detail) == 2 and isinstance(f.detail[0], (int, float)) and isinstance(f.detail[1], (int, float))
        ]
        if deltas:
            lo, hi = min(deltas), max(deltas)
            rng = f"{lo:+g}" if lo == hi else f"{lo:+g}..{hi:+g}"
            return f"advance width changed on `{sample.scope.glyph}` ({rng}){master_suffix}"
        return f"advance width changed on `{sample.scope.glyph}`{master_suffix}"

    if fact_type is FactType.UNICODE_CHANGED:
        return f"unicode mapping changed on `{sample.scope.glyph}`{master_suffix}"

    if fact_type in _ANCHOR_TYPES:
        name = sample.detail[0] if sample.detail else "?"
        label = name or "<unnamed>"
        if fact_type is FactType.ANCHOR_MOVED:
            deltas: dict[tuple, int] = defaultdict(int)
            for f in group:
                deltas[(f.detail[1], f.detail[2])] += 1
            ordered = sorted(deltas.items(), key=lambda kv: (-kv[1], kv[0]))
            if len(ordered) == 1:
                (dx, dy), _ = ordered[0]
                delta_str = f" by ({dx:+g},{dy:+g})"
            else:
                shown = "; ".join(f"Δ({dx:+g},{dy:+g})×{n}" for (dx, dy), n in ordered[:4])
                more = f" +{len(ordered) - 4} more" if len(ordered) > 4 else ""
                delta_str = f" ({shown}{more})"
            return f"anchor `{label}` moved{delta_str} on `{sample.scope.glyph}`{master_suffix}"
        verb = "added" if fact_type is FactType.ANCHOR_ADDED else "removed"
        return f"anchor `{label}` {verb} on `{sample.scope.glyph}`{master_suffix}"

    if fact_type is FactType.GLYPH_LIB_CHANGED:
        return f"glyph lib changed on `{sample.scope.glyph}`{master_suffix}"

    if fact_type in (FactType.KERN_PAIR_ADDED, FactType.KERN_PAIR_REMOVED, FactType.KERN_PAIR_CHANGED):
        pair = sample.detail[0]
        verb = {
            FactType.KERN_PAIR_ADDED: "added",
            FactType.KERN_PAIR_REMOVED: "removed",
            FactType.KERN_PAIR_CHANGED: "changed",
        }[fact_type]
        return f"kerning pair {pair[0]}/{pair[1]} {verb}{master_suffix}"

    if fact_type in (FactType.GROUP_ADDED, FactType.GROUP_REMOVED, FactType.GROUP_MEMBERSHIP_CHANGED):
        name = sample.detail[0]
        verb = {
            FactType.GROUP_ADDED: "added",
            FactType.GROUP_REMOVED: "removed",
            FactType.GROUP_MEMBERSHIP_CHANGED: "membership changed",
        }[fact_type]
        return f"group `{name}` {verb}{master_suffix}"

    if fact_type is FactType.FONTINFO_CHANGED:
        key_name, old, new = sample.detail
        return f"fontinfo `{key_name}` changed {old} -> {new}{master_suffix}"

    if fact_type in (FactType.FEA_RULE_ADDED, FactType.FEA_RULE_REMOVED):
        tag = sample.scope.feature_tag or "?"
        verb = "added" if fact_type is FactType.FEA_RULE_ADDED else "removed"
        rule = sample.detail[0] if sample.detail else ""
        return f"feature {tag}: rule {verb} `{rule}`{master_suffix}"

    if fact_type is FactType.FEA_CLASS_CHANGED:
        return f"feature class `{sample.detail[0]}` changed{master_suffix}"

    if fact_type in (FactType.FEA_FEATURE_ADDED, FactType.FEA_FEATURE_REMOVED):
        verb = "added" if fact_type is FactType.FEA_FEATURE_ADDED else "removed"
        return f"feature {sample.detail[0]} {verb}{master_suffix}"

    if fact_type in (FactType.PROFILE_OPTION_ADDED, FactType.PROFILE_OPTION_REMOVED, FactType.PROFILE_OPTION_CHANGED):
        detail = sample.detail
        key_name = detail[0]
        if fact_type is FactType.PROFILE_OPTION_ADDED:
            line = f"build profile: option `{key_name}` added ({detail[1]})"
            new_repr = detail[1]
        elif fact_type is FactType.PROFILE_OPTION_REMOVED:
            line = f"build profile: option `{key_name}` removed (was {detail[1]})"
            new_repr = None  # reverts to default; direction is ambiguous
        else:
            line = f"build profile: option `{key_name}` changed {detail[1]} -> {detail[2]}"
            new_repr = detail[2]
        # Enrich with the schema's grounded consequence when known; unknown/custom
        # keys (or no schema) fall back to the bare line above.
        if schema is not None:
            spec = schema.get(key_name)
            if spec is not None:
                off = _repr_is_off(new_repr) if new_repr is not None else None
                text = spec.consequence_text(off)
                if text:
                    line += f" — {text}"
        return line

    if fact_type is FactType.FILE_CHANGED:
        # detail = (path, verb); list distinct files (capped). The "Other files"
        # section heading gives context, so the line itself just enumerates them.
        pairs = sorted({(f.detail[0], f.detail[1]) for f in group if f.detail})
        cap = 8
        shown = ", ".join(f"`{path}` ({verb})" for path, verb in pairs[:cap])
        more = f" +{len(pairs) - cap} more" if len(pairs) > cap else ""
        return f"{shown}{more}"

    if fact_type is FactType.AXIS_CHANGED:
        return "designspace axes changed"
    if fact_type in (FactType.MASTER_ADDED, FactType.MASTER_REMOVED):
        verb = "added" if fact_type is FactType.MASTER_ADDED else "removed"
        return f"designspace master `{sample.detail[0]}` {verb}"
    if fact_type is FactType.INSTANCE_CHANGED:
        return "designspace instances changed"
    if fact_type is FactType.DS_RULE_CHANGED:
        return "designspace rules changed"

    return f"{fact_type.value} on `{sample.scope.glyph}`{master_suffix}"


def _sort_key(folded: FoldedFact) -> tuple:
    return (folded.file_kind.value, folded.fact_type.value, -folded.count, folded.summary)


def fold_facts(
    facts: list[ChangeFact], *, threshold: int = DEFAULT_THRESHOLD, schema=None
) -> list[FoldedFact]:
    """Group raw facts into folded facts, applying the detail threshold.

    ``schema`` (a ProfileSchema or None) enriches build-profile facts with the
    option's grounded consequence; None keeps the schema-agnostic summary.
    """
    groups: dict[tuple, list[ChangeFact]] = defaultdict(list)
    for fact in facts:
        groups[_fold_key(fact)].append(fact)

    folded_list: list[FoldedFact] = []
    for key, group in groups.items():
        affected = tuple(f.scope for f in group)
        glyphs = _glyphs(group)
        # Threshold is on the number of distinct glyphs for glyph-scoped facts,
        # else on the atom count.
        magnitude = len(glyphs) if glyphs else len(group)
        folded = magnitude > threshold
        summary = _summarize(key, group, schema)
        if folded:
            summary += f" (folded: {magnitude} items not enumerated)"
        folded_list.append(
            FoldedFact(
                fact_type=key[0],
                file_kind=group[0].file_kind,
                summary=summary,
                affected=affected,
                count=len(group),
                folded=folded,
                representative_detail=group[0].detail,
            )
        )

    folded_list.sort(key=_sort_key)
    return folded_list
