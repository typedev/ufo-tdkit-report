"""Parse ``*.dssketch`` sources into the designspace snapshot.

A ``.dssketch`` is a designspace written compactly (DSSketch), so it parses to the same
:class:`DesignspaceSnapshot` and diffs with ``designspace.diff_designspace``: one set of
facts, one vocabulary, whichever format a family keeps.

It is diffed **as written**, never converted. ``DSSToDesignSpace`` opens the UFOs on
disk to expand ``instances auto`` and wildcard rules, so converting an old blob would
expand it against today's sources: wrong, and different on every machine. The parser
alone (DSSketch ≥ 1.2.0) is pure and imports neither defcon nor fontTools.

One value in a parsed document does not come from the file: a line like ``Light > 295``
leaves the user value to DSSketch's bundled standards table, which can change between
DSSketch releases while the file stays the same (1.2.0 moved the width values to the
OS/2 spec). Those mappings are keyed by label, with no user value, so upgrading DSSketch
cannot read as a source edit. ``user_value_explicit`` says which form a line took; an
axis extent written with labels (``Thin:Regular:Black``) has no such flag, so a bound
that equals an inferred label's value is shown as that label.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from ufo_tdkit_report.designspace import _conditions, _location, _num, label_order
from ufo_tdkit_report.model import DesignspaceSnapshot

# The name DSSketch gives an unnamed rule: its position. Inserting a rule renumbers every
# one after it, so an unnamed rule is identified by what it substitutes instead.
_POSITIONAL_RULE = re.compile(r"rule(\d+)")


def _parse(blob: str):
    from dssketch import DSSParser

    # Not strict: a revision with validation problems is still a revision to diff. What
    # still raises (no axes, no sources) falls back to the bare file line (T3).
    return DSSParser(strict_mode=False).parse(blob)


def _extent(axis) -> str:
    inferred = {m.user_value: m.label for m in axis.mappings if not m.user_value_explicit}

    def bound(value) -> str:
        return inferred.get(value) or _num(value)

    return f"{axis.tag} {bound(axis.minimum)}:{bound(axis.default)}:{bound(axis.maximum)}"


def _rules(doc) -> tuple:
    rules = []
    for index, rule in enumerate(doc.rules, start=1):
        if rule.pattern:  # a wildcard or multi-glyph rule, kept as written
            subs = ((rule.pattern, rule.to_pattern or ""),)
        else:
            subs = tuple(tuple(sub) for sub in rule.substitutions)
        name = rule.name or ""
        positional = _POSITIONAL_RULE.fullmatch(name)
        if positional and int(positional.group(1)) == index:
            name = "; ".join(f"{a} > {b}" for a, b in subs)
        conditions = [{**c, "name": c.get("axis", "?")} for c in rule.conditions]
        rules.append((name, _conditions([conditions] if conditions else []), subs))
    return tuple(sorted(rules))


def _settings(doc) -> tuple:
    settings = {"family": doc.family, "suffix": doc.suffix, "sources path": doc.path}
    settings["instances"] = "off" if doc.instances_off else "auto" if doc.instances_auto else "explicit"
    if doc.instances_skip:
        settings["instances skip"] = ", ".join(sorted(doc.instances_skip))
    for source in doc.sources:
        name = PurePosixPath(source.filename).stem if source.filename else source.name
        if source.is_base:
            settings["base master"] = name
        flags = [flag for flag, on in (
            ("sparse", source.is_sparse), ("copy info", source.copy_info), ("copy lib", source.copy_lib),
            ("copy groups", source.copy_groups), ("copy features", source.copy_features),
        ) if on]
        if flags:
            settings[f"master `{name}` options"] = ", ".join(flags)
    for var, value in doc.avar2_vars.items():
        settings[f"avar2 variable `${var}`"] = _num(value)
    for mapping in doc.avar2_mappings:
        where = ", ".join(f"{axis}={_num(v)}" for axis, v in sorted(mapping.input.items()))
        key = f"avar2 mapping `{mapping.name}`" if mapping.name else f"avar2 mapping [{where}]"
        output = ", ".join(f"{axis}={_num(v)}" for axis, v in sorted(mapping.output.items()))
        settings[key] = f"[{where}] > {output}" if mapping.name else output
    return tuple(sorted((key, value) for key, value in settings.items() if value))


def parse_dssketch(blob: str | None) -> DesignspaceSnapshot | None:
    if not blob:
        return None
    try:
        doc = _parse(blob)
    except Exception:
        return None

    axes, maps, labels = [], [], []
    for axis in doc.axes:
        axes.append((axis.name, _extent(axis)))
        points, named = [], []
        for m in axis.mappings:
            user = float(m.user_value) if m.user_value_explicit else m.label
            points.append((user, float(m.design_value)))
            if m.user_value_explicit:  # an inferred line is already its map point
                named.append((float(m.user_value), m.label, "elidable" if m.elidable else ""))
            elif m.elidable:
                named.append((None, m.label, "elidable"))
        maps.append((axis.name, tuple(sorted(points, key=lambda p: (isinstance(p[0], str), p[0])))))
        labels.append((axis.name, tuple(sorted(named, key=label_order))))
    for axis in doc.hidden_axes:
        axes.append((axis.name, f"{axis.tag} {_num(axis.minimum)}:{_num(axis.default)}:{_num(axis.maximum)} hidden"))

    sources = {}
    for src in doc.sources:
        ident = PurePosixPath(src.filename).stem if src.filename else src.name
        if src.layer:
            ident = f"{ident}/{src.layer}"
        sources[ident] = tuple(sorted(_location(src.location)))

    return DesignspaceSnapshot(
        axes=tuple(sorted(axes)),
        sources=tuple(sorted(sources)),
        instances=(),  # DSSketch writes no explicit instances; `instances` is a setting
        rules=_rules(doc),
        axis_maps=tuple(sorted(maps)),
        axis_labels=tuple(sorted(labels)),
        source_locations=tuple(sorted(sources.items())),
        settings=_settings(doc),
    )
