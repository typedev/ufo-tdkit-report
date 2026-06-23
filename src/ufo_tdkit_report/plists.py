"""Parse and diff UFO plist sources: kerning, groups, fontinfo (issue #5, phase 1).

Uses stdlib ``plistlib`` (order-agnostic into dicts), so reformatting is invisible.
fontinfo is filtered to a curated set of high-signal release-relevant keys.
"""

from __future__ import annotations

import plistlib

from ufo_tdkit_report.model import (
    ChangeFact,
    FactType,
    FileKind,
    FontInfoSnapshot,
    GroupsSnapshot,
    KernSnapshot,
    Scope,
)

# fontinfo keys worth reporting in release notes (version, naming, vendor, key metrics).
_FONTINFO_KEYS = (
    "versionMajor",
    "versionMinor",
    "familyName",
    "styleName",
    "styleMapFamilyName",
    "styleMapStyleName",
    "openTypeNamePreferredFamilyName",
    "openTypeNamePreferredSubfamilyName",
    "openTypeNameVersion",
    "openTypeOS2VendorID",
    "openTypeOS2WeightClass",
    "openTypeOS2WidthClass",
    "unitsPerEm",
    "ascender",
    "descender",
    "capHeight",
    "xHeight",
    "italicAngle",
)


def _loads(blob: str | None):
    if not blob:
        return None
    try:
        return plistlib.loads(blob.encode("utf-8"))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# kerning
# --------------------------------------------------------------------------- #


def parse_kerning(blob: str | None) -> KernSnapshot | None:
    data = _loads(blob)
    if not isinstance(data, dict):
        return None
    pairs = []
    for left, rights in data.items():
        if isinstance(rights, dict):
            for right, value in rights.items():
                pairs.append(((str(left), str(right)), value))
    return KernSnapshot(pairs=tuple(sorted(pairs)))


def diff_kerning(old: KernSnapshot, new: KernSnapshot, scope: Scope) -> list[ChangeFact]:
    old_map = dict(old.pairs)
    new_map = dict(new.pairs)
    facts: list[ChangeFact] = []
    for pair in sorted(set(old_map) | set(new_map)):
        o, n = old_map.get(pair), new_map.get(pair)
        if o == n:
            continue
        if o is None:
            facts.append(ChangeFact(FactType.KERN_PAIR_ADDED, FileKind.KERNING, scope, (pair, n)))
        elif n is None:
            facts.append(ChangeFact(FactType.KERN_PAIR_REMOVED, FileKind.KERNING, scope, (pair, o)))
        else:
            facts.append(ChangeFact(FactType.KERN_PAIR_CHANGED, FileKind.KERNING, scope, (pair, o, n)))
    return facts


# --------------------------------------------------------------------------- #
# groups
# --------------------------------------------------------------------------- #


def parse_groups(blob: str | None) -> GroupsSnapshot | None:
    data = _loads(blob)
    if not isinstance(data, dict):
        return None
    groups = tuple(sorted((str(name), tuple(str(m) for m in members)) for name, members in data.items()))
    return GroupsSnapshot(groups=groups)


def diff_groups(old: GroupsSnapshot, new: GroupsSnapshot, scope: Scope) -> list[ChangeFact]:
    old_map = {name: set(members) for name, members in old.groups}
    new_map = {name: set(members) for name, members in new.groups}
    facts: list[ChangeFact] = []
    for name in sorted(set(old_map) | set(new_map)):
        if name not in new_map:
            facts.append(ChangeFact(FactType.GROUP_REMOVED, FileKind.GROUPS, scope, (name,)))
        elif name not in old_map:
            facts.append(ChangeFact(FactType.GROUP_ADDED, FileKind.GROUPS, scope, (name,)))
        elif old_map[name] != new_map[name]:
            added = tuple(sorted(new_map[name] - old_map[name]))
            removed = tuple(sorted(old_map[name] - new_map[name]))
            facts.append(
                ChangeFact(FactType.GROUP_MEMBERSHIP_CHANGED, FileKind.GROUPS, scope, (name, added, removed))
            )
    return facts


# --------------------------------------------------------------------------- #
# fontinfo
# --------------------------------------------------------------------------- #


def parse_fontinfo(blob: str | None) -> FontInfoSnapshot | None:
    data = _loads(blob)
    if not isinstance(data, dict):
        return None
    items = tuple(sorted((k, repr(data[k])) for k in _FONTINFO_KEYS if k in data))
    return FontInfoSnapshot(items=items)


def diff_fontinfo(old: FontInfoSnapshot, new: FontInfoSnapshot, scope: Scope) -> list[ChangeFact]:
    old_map = dict(old.items)
    new_map = dict(new.items)
    facts: list[ChangeFact] = []
    for key in sorted(set(old_map) | set(new_map)):
        o, n = old_map.get(key), new_map.get(key)
        if o != n:
            facts.append(ChangeFact(FactType.FONTINFO_CHANGED, FileKind.FONTINFO, scope, (key, o, n)))
    return facts
