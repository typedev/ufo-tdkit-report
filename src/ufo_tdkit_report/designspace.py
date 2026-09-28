"""Parse and diff ``*.designspace`` sources.

Parsed with fontTools' ``designspaceLib`` from the blob string (no temp files, fully
deterministic). A designspace is mostly *numbers that place things*: an axis map pairs
a user-facing value with a design location, an instance location says where a static
style is interpolated, a source location where a master sits. The first differ compared
only axis extents and instance *names*, so remapping a weight axis — every named style
moved to a new design location — surfaced as a bare "modified". Now each of those is a
fact that says which value moved from where to where.

Identity is chosen to survive re-serialization: masters by their UFO file stem (the
``source.N`` names a generator writes shift when a source is inserted), rules and axes by
name, instances by name or PostScript name. Everything is sorted by value.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from ufo_tdkit_report.model import ChangeFact, DesignspaceSnapshot, FactType, FileKind, Scope


def _num(value) -> str:
    if isinstance(value, (tuple, list)):  # anisotropic location
        return "(" + ", ".join(_num(v) for v in value) + ")"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _axis_extent(axis) -> str:
    values = getattr(axis, "values", None)
    if values:  # a discrete axis
        return "{" + " ".join(_num(v) for v in values) + f"}} default {_num(axis.default)}"
    return f"{_num(axis.minimum)}:{_num(axis.default)}:{_num(axis.maximum)}"


def _location(mapping, space: str = "") -> tuple[tuple[str, str], ...]:
    prefix = f"{space} " if space else ""
    return tuple((f"{prefix}{dim}", _num(value)) for dim, value in (mapping or {}).items())


def _conditions(condition_sets) -> str:
    alternatives = []
    for conditions in condition_sets or ():
        parts = []
        for cond in conditions:
            low, high, name = cond.get("minimum"), cond.get("maximum"), cond.get("name", "?")
            if low is not None and high is not None:
                parts.append(f"{_num(low)} ≤ {name} ≤ {_num(high)}")
            elif low is not None:
                parts.append(f"{name} ≥ {_num(low)}")
            elif high is not None:
                parts.append(f"{name} ≤ {_num(high)}")
        alternatives.append(" and ".join(parts))
    return " or ".join(a for a in alternatives if a) or "always"


def parse_designspace(blob: str | None) -> DesignspaceSnapshot | None:
    if not blob:
        return None
    from fontTools.designspaceLib import DesignSpaceDocument

    try:
        doc = DesignSpaceDocument.fromstring(blob)
    except Exception:
        return None

    axes, maps, labels = [], [], []
    for axis in doc.axes:
        axes.append((axis.name, f"{axis.tag} {_axis_extent(axis)}"))
        maps.append((axis.name, tuple(sorted((float(i), float(o)) for i, o in axis.map or ()))))
        labels.append((axis.name, tuple(sorted(
            (float(label.userValue), label.name, "elidable" if label.elidable else "")
            for label in getattr(axis, "axisLabels", None) or ()
        ))))

    sources = {}
    for src in doc.sources:
        ident = PurePosixPath(src.filename).stem if src.filename else (src.name or "")
        if src.layerName:
            ident = f"{ident}/{src.layerName}"
        sources[ident] = tuple(sorted(_location(getattr(src, "designLocation", None) or src.location)))

    instances = {}
    for inst in doc.instances:
        ident = inst.name or inst.postScriptFontName or " ".join(
            p for p in (inst.familyName, inst.styleName) if p
        ) or inst.filename or ""
        place = _location(getattr(inst, "designLocation", None) or inst.location)
        place += _location(getattr(inst, "userLocation", None), "user")
        if getattr(inst, "locationLabel", None):
            place += (("label", inst.locationLabel),)
        instances[ident] = tuple(sorted(place))

    rules = tuple(sorted(
        (rule.name or "", _conditions(rule.conditionSets), tuple(tuple(sub) for sub in rule.subs))
        for rule in doc.rules
    ))

    return DesignspaceSnapshot(
        axes=tuple(sorted(axes)),
        sources=tuple(sorted(sources)),
        instances=tuple(sorted(instances)),
        rules=rules,
        axis_maps=tuple(sorted(maps)),
        axis_labels=tuple(sorted(labels)),
        source_locations=tuple(sorted(sources.items())),
        instance_locations=tuple(sorted(instances.items())),
    )


def _order(key) -> tuple:
    """Total order over map keys that may mix numbers and labels (a .dssketch axis map)."""
    return (isinstance(key, str), key)


def label_order(label: tuple) -> tuple:
    """Total order over ``(user value, name, flags)`` labels whose user value may be None."""
    value, name, flags = label
    return (value is None, value or 0.0, name, flags)


def _value_changes(old_pairs, new_pairs) -> tuple:
    """``(key, old, new)`` for every key whose value differs; None where it is absent."""
    old_map, new_map = dict(old_pairs), dict(new_pairs)
    return tuple(
        (key, old_map.get(key), new_map.get(key))
        for key in sorted(set(old_map) | set(new_map), key=_order)
        if old_map.get(key) != new_map.get(key)
    )


def diff_designspace(old: DesignspaceSnapshot, new: DesignspaceSnapshot, scope: Scope) -> list[ChangeFact]:
    facts: list[ChangeFact] = []

    def fact(fact_type: FactType, detail: tuple) -> None:
        facts.append(ChangeFact(fact_type, FileKind.DESIGNSPACE, scope, detail))

    for name, before, after in _value_changes(old.axes, new.axes):
        fact(FactType.AXIS_CHANGED, (name, before, after))

    # Maps and labels only for axes on both sides: a new axis is already one fact.
    both_axes = {name for name, _ in old.axes} & {name for name, _ in new.axes}
    old_maps, new_maps = dict(old.axis_maps), dict(new.axis_maps)
    old_labels, new_labels = dict(old.axis_labels), dict(new.axis_labels)
    for name in sorted(both_axes):
        changes = _value_changes(old_maps.get(name, ()), new_maps.get(name, ()))
        if changes:
            fact(FactType.AXIS_MAP_CHANGED, (name, changes))
        before, after = set(old_labels.get(name, ())), set(new_labels.get(name, ()))
        if before != after:
            added, removed = sorted(after - before, key=label_order), sorted(before - after, key=label_order)
            fact(FactType.AXIS_LABELS_CHANGED, (name, tuple(added), tuple(removed)))

    old_sources, new_sources = set(old.sources), set(new.sources)
    for name in sorted(new_sources - old_sources):
        fact(FactType.MASTER_ADDED, (name,))
    for name in sorted(old_sources - new_sources):
        fact(FactType.MASTER_REMOVED, (name,))
    old_src_loc, new_src_loc = dict(old.source_locations), dict(new.source_locations)
    for name in sorted(old_sources & new_sources):
        changes = _value_changes(old_src_loc[name], new_src_loc[name])
        if changes:
            fact(FactType.MASTER_MOVED, (name, changes))

    if set(old.instances) != set(new.instances):
        added = tuple(sorted(set(new.instances) - set(old.instances)))
        removed = tuple(sorted(set(old.instances) - set(new.instances)))
        fact(FactType.INSTANCE_CHANGED, (added, removed))
    old_inst_loc, new_inst_loc = dict(old.instance_locations), dict(new.instance_locations)
    for name in sorted(set(old.instances) & set(new.instances)):
        changes = _value_changes(old_inst_loc[name], new_inst_loc[name])
        if changes:
            fact(FactType.INSTANCE_MOVED, (name, changes))

    old_rules = {name: (cond, subs) for name, cond, subs in old.rules}
    new_rules = {name: (cond, subs) for name, cond, subs in new.rules}
    for name, before, after in _value_changes(old_rules, new_rules):
        fact(FactType.DS_RULE_CHANGED, (name, before, after))

    for key, before, after in _value_changes(old.settings, new.settings):
        fact(FactType.DS_SETTING_CHANGED, (key, before, after))

    return facts
