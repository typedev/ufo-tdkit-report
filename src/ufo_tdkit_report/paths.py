"""Map a repo-relative source path to its file kind and master/family (issue #5).

Pure string logic. The authoritative glyph *name* comes from the glif body (parsed
elsewhere), not the filename, because UFO filenames use name-mangling.
"""

from __future__ import annotations

import re

from ufo_tdkit_report.model import FileKind

_UFO_RE = re.compile(r"(?P<master>[^/]+)\.ufo/")


def master_of(path: str) -> str | None:
    """Return the ``<Master>`` from ``.../<Master>.ufo/...`` or None."""
    m = _UFO_RE.search(path)
    return m.group("master") if m else None


def classify_path(path: str) -> FileKind | None:
    """Classify a changed file into a report FileKind, or None if irrelevant."""
    lower = path.lower()
    if lower.endswith(".glif"):
        return FileKind.GLIF
    if lower.endswith("kerning.plist"):
        return FileKind.KERNING
    if lower.endswith("groups.plist"):
        return FileKind.GROUPS
    if lower.endswith("fontinfo.plist"):
        return FileKind.FONTINFO
    if lower.endswith(".fea"):
        return FileKind.FEATURES
    if lower.endswith(".designspace"):
        return FileKind.DESIGNSPACE
    if lower.endswith((".yaml", ".yml")):
        return FileKind.PROFILE
    return None
