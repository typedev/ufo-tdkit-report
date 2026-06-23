"""Route a changed source file to the correct parser + differ (issue #5, phase 1).

Receives already-fetched blob strings (no git here) and returns raw ChangeFacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from ufo_tdkit_report import designspace, features, glif, plists, profile
from ufo_tdkit_report.model import ChangeFact, FactType, FileKind, Scope
from ufo_tdkit_report.paths import classify_path, master_of

# git status code -> human verb for constatation facts (T3).
_STATUS_VERB = {
    "A": "added", "M": "modified", "D": "removed",
    "R": "renamed", "C": "copied", "T": "modified", "?": "added",
}


def status_verb(status: str | None) -> str:
    """Map a git status code to a human verb (handles 2-char porcelain like `` M``, ``??``)."""
    code = (status or "").strip() or "M"
    return _STATUS_VERB.get(code[:1], "changed")


def file_note(path: str, status: str | None) -> ChangeFact:
    """A bare constatation fact: this tracked file changed (T3 — no silent drops)."""
    return ChangeFact(FactType.FILE_CHANGED, FileKind.OTHER, Scope(), (path, status_verb(status)))


@dataclass(frozen=True)
class ChangedFile:
    """One file changed between two revisions, with its blob contents resolved."""

    path: str
    status: str  # "A" | "M" | "D" | "R..."
    old_blob: str | None
    new_blob: str | None


def _glyph_facts(cf: ChangedFile, scope: Scope) -> list[ChangeFact]:
    old = glif.parse_glif(cf.old_blob) if cf.old_blob else None
    new = glif.parse_glif(cf.new_blob) if cf.new_blob else None
    if old is None and new is not None:
        glyph_scope = Scope(master=scope.master, glyph=new.name)
        return [ChangeFact(FactType.GLYPH_ADDED, FileKind.GLIF, glyph_scope, (new.name,))]
    if new is None and old is not None:
        glyph_scope = Scope(master=scope.master, glyph=old.name)
        return [ChangeFact(FactType.GLYPH_REMOVED, FileKind.GLIF, glyph_scope, (old.name,))]
    if old is None or new is None:
        return []
    glyph_scope = Scope(master=scope.master, glyph=new.name)
    return glif.diff_glif(old, new, glyph_scope)


def classify_change(cf: ChangedFile, family: str | None = None) -> list[ChangeFact]:
    """Parse and diff one changed file, returning its raw deterministic facts."""
    kind = classify_path(cf.path)
    if kind is None:
        return []
    scope = Scope(family=family, master=master_of(cf.path))

    if kind is FileKind.GLIF:
        return _glyph_facts(cf, scope)

    parse_diff = {
        FileKind.KERNING: (plists.parse_kerning, plists.diff_kerning),
        FileKind.GROUPS: (plists.parse_groups, plists.diff_groups),
        FileKind.FONTINFO: (plists.parse_fontinfo, plists.diff_fontinfo),
        FileKind.FEATURES: (features.parse_fea, features.diff_fea),
        FileKind.DESIGNSPACE: (designspace.parse_designspace, designspace.diff_designspace),
        FileKind.PROFILE: (profile.parse_profile, profile.diff_profile),
    }[kind]
    parse_fn, diff_fn = parse_diff

    old = parse_fn(cf.old_blob)
    new = parse_fn(cf.new_blob)
    if old is None or new is None:
        # Added or removed whole file (or unparseable). Phase 1 reports these via the
        # individual differs only when both sides parse; a bare add/remove of these
        # files is low-signal and folded by the caller's changed-file count.
        return []
    return diff_fn(old, new, scope)
