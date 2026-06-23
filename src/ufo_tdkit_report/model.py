"""Data model for the report extractor (issue #5, phase 1).

Pure data vocabulary: normalized source snapshots, the deterministic change-fact
taxonomy, and the rolled-up report. This module imports nothing beyond the standard
library so it stays trivially importable and unit-testable.

Snapshots are normalized (serialization-order agnostic) so editor re-serialization
noise diffs to nothing. Facts are deterministic; ordering into output is always
total and value-based so reports are byte-stable across runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class FileKind(Enum):
    """Source file category a fact originates from."""

    GLIF = "glif"
    KERNING = "kerning"
    GROUPS = "groups"
    FONTINFO = "fontinfo"
    FEATURES = "features"
    DESIGNSPACE = "designspace"
    PROFILE = "profile"


class FactType(Enum):
    """Classified, deterministic source change."""

    # glif
    GLYPH_ADDED = "glyph-added"
    GLYPH_REMOVED = "glyph-removed"
    ADVANCE_CHANGED = "advance-changed"
    UNICODE_CHANGED = "unicode-changed"
    COMPONENT_ADDED = "component-added"
    COMPONENT_REMOVED = "component-removed"
    COMPONENT_MOVED = "component-moved"
    COMPONENT_SCALED = "component-scaled"
    OUTLINE_REDRAWN = "outline-redrawn"
    CONTOUR_COUNT_CHANGED = "contour-count-changed"
    ANCHOR_ADDED = "anchor-added"
    ANCHOR_REMOVED = "anchor-removed"
    ANCHOR_MOVED = "anchor-moved"
    GLYPH_LIB_CHANGED = "glyph-lib-changed"
    # kerning / groups
    KERN_PAIR_ADDED = "kern-pair-added"
    KERN_PAIR_REMOVED = "kern-pair-removed"
    KERN_PAIR_CHANGED = "kern-pair-changed"
    GROUP_ADDED = "group-added"
    GROUP_REMOVED = "group-removed"
    GROUP_MEMBERSHIP_CHANGED = "group-membership-changed"
    # fontinfo
    FONTINFO_CHANGED = "fontinfo-changed"
    # features
    FEA_RULE_ADDED = "fea-rule-added"
    FEA_RULE_REMOVED = "fea-rule-removed"
    FEA_CLASS_CHANGED = "fea-class-changed"
    FEA_FEATURE_ADDED = "fea-feature-added"
    FEA_FEATURE_REMOVED = "fea-feature-removed"
    # designspace
    AXIS_CHANGED = "axis-changed"
    MASTER_ADDED = "master-added"
    MASTER_REMOVED = "master-removed"
    INSTANCE_CHANGED = "instance-changed"
    DS_RULE_CHANGED = "ds-rule-changed"
    # build profile
    PROFILE_OPTION_ADDED = "profile-option-added"
    PROFILE_OPTION_REMOVED = "profile-option-removed"
    PROFILE_OPTION_CHANGED = "profile-option-changed"


# --------------------------------------------------------------------------- #
# Normalized source snapshots
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ComponentRef:
    """A normalized component reference inside a glyph outline."""

    base: str
    x_offset: float
    y_offset: float
    x_scale: float
    y_scale: float
    xy_scale: float
    yx_scale: float

    @property
    def offset(self) -> tuple[float, float]:
        return (self.x_offset, self.y_offset)

    @property
    def scale(self) -> tuple[float, float, float, float]:
        return (self.x_scale, self.xy_scale, self.yx_scale, self.y_scale)


@dataclass(frozen=True)
class ContourSig:
    """Coordinate-bearing signature of one contour.

    Carries the actual point coordinates (not just the count) so a redraw that
    preserves point count but moves coordinates is still detected.
    """

    points: tuple[tuple[float, float, str | None], ...]

    @property
    def n_points(self) -> int:
        return len(self.points)


@dataclass(frozen=True)
class AnchorSig:
    """A normalized anchor (name + position)."""

    name: str | None
    x: float
    y: float


@dataclass(frozen=True)
class GlifSnapshot:
    """Normalized, serialization-order-agnostic view of one ``.glif``."""

    name: str
    advance_width: float | None
    advance_height: float | None
    unicodes: tuple[int, ...]
    components: tuple[ComponentRef, ...]
    contours: tuple[ContourSig, ...]
    anchors: frozenset[AnchorSig]
    lib_items: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class KernSnapshot:
    """Flat kerning view: ``{(left, right): value}``."""

    pairs: tuple[tuple[tuple[str, str], float], ...]


@dataclass(frozen=True)
class GroupsSnapshot:
    """Groups view: ``{group_name: (member, ...)}`` with member order ignored."""

    groups: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class FontInfoSnapshot:
    """Selected high-signal fontinfo keys as sorted ``(key, repr(value))`` pairs."""

    items: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FeaSnapshot:
    """Normalized features view: rules collapsed per feature tag + classes."""

    rules_by_feature: tuple[tuple[str, tuple[str, ...]], ...]
    classes: tuple[tuple[str, tuple[str, ...]], ...]
    top_level: tuple[str, ...]
    parse_failed: bool = False


@dataclass(frozen=True)
class DesignspaceSnapshot:
    """Coarse designspace view: axes, sources, instances, rules."""

    axes: tuple[tuple[str, ...], ...]
    sources: tuple[str, ...]
    instances: tuple[str, ...]
    rules: tuple[str, ...]


@dataclass(frozen=True)
class ProfileSnapshot:
    """Normalized build-profile options as sorted ``(key, repr(value))`` pairs."""

    options: tuple[tuple[str, str], ...]


# --------------------------------------------------------------------------- #
# Facts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Scope:
    """Where a change happened."""

    family: str | None = None
    master: str | None = None
    glyph: str | None = None
    feature_tag: str | None = None


@dataclass(frozen=True)
class ChangeFact:
    """A single deterministic change record.

    ``detail`` is a small fact-type-specific hashable payload (e.g. ``(base, dx, dy)``
    for a component move, ``(key, old, new)`` for a profile option). ``magnitude``
    drives sort order and threshold folding (e.g. number of points moved).
    """

    fact_type: FactType
    file_kind: FileKind
    scope: Scope
    detail: tuple = ()
    magnitude: float | None = None


@dataclass
class FoldedFact:
    """A group of atoms collapsed into one user-facing line."""

    fact_type: FactType
    file_kind: FileKind
    summary: str
    affected: tuple[Scope, ...] = ()
    count: int = 0
    folded: bool = False
    representative_detail: tuple = ()

    def to_dict(self) -> dict:
        return {
            "fact_type": self.fact_type.value,
            "file_kind": self.file_kind.value,
            "summary": self.summary,
            "count": self.count,
            "folded": self.folded,
            "glyphs": sorted({s.glyph for s in self.affected if s.glyph}),
            "masters": sorted({s.master for s in self.affected if s.master}),
        }


@dataclass
class SourceReport:
    """The full deterministic report for a commit (range)."""

    commit_spec: str
    folded_facts: list[FoldedFact] = field(default_factory=list)
    raw_fact_count: int = 0
    changed_file_count: int = 0
    profile_name: str | None = None
    profile_options: dict | None = None

    def to_dict(self) -> dict:
        return {
            "commit_spec": self.commit_spec,
            "raw_fact_count": self.raw_fact_count,
            "changed_file_count": self.changed_file_count,
            "profile_name": self.profile_name,
            "profile_options": self.profile_options,
            "facts": [f.to_dict() for f in self.folded_facts],
        }

    def render_text(self) -> str:
        # Implemented in report.py to keep rendering out of the data model.
        from ufo_tdkit_report.render import render_report

        return render_report(self)


@dataclass
class RangeReport:
    """Aggregated report across all commits of a ``base..head`` range."""

    range_spec: str
    commits: list[tuple[str, str]] = field(default_factory=list)  # (sha, subject), oldest first
    folded_facts: list[FoldedFact] = field(default_factory=list)
    raw_fact_count: int = 0
    net_removed_count: int = 0
    profile_name: str | None = None
    profile_options: dict | None = None

    @property
    def commit_count(self) -> int:
        return len(self.commits)

    def to_dict(self) -> dict:
        return {
            "range_spec": self.range_spec,
            "commit_count": self.commit_count,
            "commits": [{"sha": sha, "subject": subject} for sha, subject in self.commits],
            "raw_fact_count": self.raw_fact_count,
            "net_removed_count": self.net_removed_count,
            "profile_name": self.profile_name,
            "profile_options": self.profile_options,
            "facts": [f.to_dict() for f in self.folded_facts],
        }

    def render_text(self) -> str:
        from ufo_tdkit_report.render import render_range_report

        return render_range_report(self)
