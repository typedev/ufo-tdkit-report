"""Parse and diff the TDKit build-profile YAML (issue #5, phase 1).

Build-option deltas (ttfautohint added, version bumped, formats/hinting flags
changed) are invisible to a binary font diff but materially change the output, so
they belong in release notes. All option keys are diffed (known and unknown alike)
so newly introduced options or typos still surface.

Dict-valued options (e.g. ``fontinfo``, ``metatable``, ``customWeightNames``) are
flattened to dotted keys one level deep, so a nested change surfaces as a precise
``fontinfo.versionMinor 5 -> 6`` fact instead of dumping the whole dict.
"""

from __future__ import annotations

from ufo_tdkit_report.model import ChangeFact, FactType, FileKind, ProfileSnapshot, Scope


def _flatten_options(data: dict) -> tuple[tuple[str, str], ...]:
    """Normalize profile options to sorted ``(key, repr(value))`` pairs.

    A dict-valued option is expanded one level into ``key.subkey`` entries so nested
    changes diff precisely; empty dicts are kept as a single entry.
    """
    items: list[tuple[str, str]] = []
    for key, value in data.items():
        if isinstance(value, dict) and value:
            for subkey, subvalue in value.items():
                items.append((f"{key}.{subkey}", repr(subvalue)))
        else:
            items.append((str(key), repr(value)))
    return tuple(sorted(items))


def parse_profile(blob: str | None) -> ProfileSnapshot | None:
    """Parse a profile YAML string into normalized options (dict options flattened)."""
    if not blob:
        return None
    import yaml

    try:
        data = yaml.safe_load(blob)
    except Exception:
        return None
    if not isinstance(data, dict) or "path" not in data:
        # A TDKit profile always carries the required 'path' key; this guard keeps
        # unrelated YAML (CI configs, etc.) from being mistaken for a build profile.
        return None
    # Diff all options; unknown/newly introduced keys are kept too so they surface.
    return ProfileSnapshot(options=_flatten_options(data))


def diff_profile(old: ProfileSnapshot, new: ProfileSnapshot, scope: Scope) -> list[ChangeFact]:
    old_map = dict(old.options)
    new_map = dict(new.options)
    facts: list[ChangeFact] = []
    for key in sorted(set(old_map) | set(new_map)):
        o, n = old_map.get(key), new_map.get(key)
        if o == n:
            continue
        if o is None:
            facts.append(ChangeFact(FactType.PROFILE_OPTION_ADDED, FileKind.PROFILE, scope, (key, n)))
        elif n is None:
            facts.append(ChangeFact(FactType.PROFILE_OPTION_REMOVED, FileKind.PROFILE, scope, (key, o)))
        else:
            facts.append(ChangeFact(FactType.PROFILE_OPTION_CHANGED, FileKind.PROFILE, scope, (key, o, n)))
    return facts
