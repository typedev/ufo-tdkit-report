"""Parse and diff ``*.designspace`` sources coarsely.

We parse selected fields with ``xml.etree`` (no temp files, fully deterministic):
axes, sources (masters), instances, and ``<rules>``. Substitution-level rule
diffing is deferred to a later phase.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from ufo_tdkit_report.model import ChangeFact, DesignspaceSnapshot, FactType, FileKind, Scope


def parse_designspace(blob: str | None) -> DesignspaceSnapshot | None:
    if not blob:
        return None
    try:
        root = ET.fromstring(blob)
    except ET.ParseError:
        return None

    axes = []
    for axis in root.findall(".//axes/axis"):
        axes.append(
            (
                axis.get("tag", ""),
                axis.get("name", ""),
                axis.get("minimum", ""),
                axis.get("maximum", ""),
                axis.get("default", ""),
            )
        )

    sources = []
    for src in root.findall(".//sources/source"):
        sources.append(src.get("name") or src.get("filename") or "")

    instances = []
    for inst in root.findall(".//instances/instance"):
        instances.append(inst.get("name") or inst.get("postscriptfontname") or "")

    rules = [rule.get("name", "") for rule in root.findall(".//rules/rule")]

    return DesignspaceSnapshot(
        axes=tuple(sorted(axes)),
        sources=tuple(sorted(sources)),
        instances=tuple(sorted(instances)),
        rules=tuple(sorted(rules)),
    )


def diff_designspace(old: DesignspaceSnapshot, new: DesignspaceSnapshot, scope: Scope) -> list[ChangeFact]:
    facts: list[ChangeFact] = []

    if old.axes != new.axes:
        facts.append(ChangeFact(FactType.AXIS_CHANGED, FileKind.DESIGNSPACE, scope, (old.axes, new.axes)))

    old_sources, new_sources = set(old.sources), set(new.sources)
    for name in sorted(new_sources - old_sources):
        facts.append(ChangeFact(FactType.MASTER_ADDED, FileKind.DESIGNSPACE, scope, (name,)))
    for name in sorted(old_sources - new_sources):
        facts.append(ChangeFact(FactType.MASTER_REMOVED, FileKind.DESIGNSPACE, scope, (name,)))

    if set(old.instances) != set(new.instances):
        added = tuple(sorted(set(new.instances) - set(old.instances)))
        removed = tuple(sorted(set(old.instances) - set(new.instances)))
        facts.append(ChangeFact(FactType.INSTANCE_CHANGED, FileKind.DESIGNSPACE, scope, (added, removed)))

    if old.rules != new.rules:
        facts.append(ChangeFact(FactType.DS_RULE_CHANGED, FileKind.DESIGNSPACE, scope, (old.rules, new.rules)))

    return facts
