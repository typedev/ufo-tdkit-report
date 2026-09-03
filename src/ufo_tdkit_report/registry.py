"""``name -> repo entry`` registry for ``tdreport <name>``, with per-repo AI settings.

Stored as JSON in the tool's own config dir. Names are pure convenience: the core
modes (cwd, explicit path) work without registering anything. Addressing a repo by
PATH registers it under the git root's basename (see ``cli._auto_register``), so the
short name works from then on; the bare cwd mode registers nothing, and an unknown
bare NAME stays an error rather than becoming a silent registration.

An entry is an object so a repository can carry overrides beside its path::

    {"acmesans": {"path": "/abs/path", "account": "acme", "language": "Spanish"}}

The overrides name an **account** (see :mod:`settings`) — never a key. Secrets live
only in ``<config>/.env``, so this file is safe to back up or keep in dotfiles, and
nothing tdreport-related is ever written inside the font repository itself.

The older flat form (``{"name": "/abs/path"}``) is read transparently and rewritten
to the object form on the next write, so no user action is needed to upgrade.
"""

from __future__ import annotations

import json
from pathlib import Path

from ufo_tdkit_report.config import config_dir

# Per-repo keys an entry may carry besides "path". Deliberately small: anything that
# would be a secret belongs in <config>/.env, keyed by account.
OVERRIDE_KEYS = ("account", "provider", "model", "language", "strict_grounding")
# Overrides whose value is a flag rather than a name.
BOOL_OVERRIDE_KEYS = ("strict_grounding",)


def _registry_path() -> Path:
    return config_dir() / "repos.json"


def _normalize(value) -> dict | None:
    """Coerce a stored value (flat string, legacy; or object) into an entry dict."""
    if isinstance(value, str):
        return {"path": value}
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        entry = {"path": value["path"]}
        for key in OVERRIDE_KEYS:
            stored = value.get(key)
            if key in BOOL_OVERRIDE_KEYS:
                if isinstance(stored, bool):
                    entry[key] = stored
            elif isinstance(stored, str) and stored.strip():
                entry[key] = stored.strip()
        return entry
    return None


def load() -> dict[str, dict]:
    """Every registered repo as ``name -> {"path": ..., ...overrides}``.

    Unreadable/corrupt files and unusable entries degrade to empty rather than raising:
    a broken registry must not take the whole tool down.
    """
    path = _registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for name, value in data.items():
        entry = _normalize(value)
        if entry:
            out[str(name)] = entry
    return out


def save(mapping: dict[str, dict]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def add(name: str, repo_path: str, **overrides) -> str:
    """Register ``name`` -> absolute repo path; returns the stored path.

    Keyword overrides (``account``, ``provider``, ``model``, ``language``) are merged
    into the entry; passing ``None`` for one clears it. Registering an existing name
    keeps the overrides it already had.
    """
    resolved = str(Path(repo_path).expanduser().resolve())
    mapping = load()
    entry = dict(mapping.get(name) or {})
    entry["path"] = resolved
    for key, value in overrides.items():
        if key not in OVERRIDE_KEYS:
            raise ValueError(f"unknown repo override '{key}' (known: {', '.join(OVERRIDE_KEYS)})")
        if value is None:
            entry.pop(key, None)
        elif key in BOOL_OVERRIDE_KEYS:
            entry[key] = bool(value)
        elif value.strip():
            entry[key] = value.strip()
    mapping[name] = entry
    save(mapping)
    return resolved


def remove(name: str) -> bool:
    mapping = load()
    resolved = _find_name(mapping, name)
    if resolved:
        del mapping[resolved]
        save(mapping)
        return True
    return False


def _find_name(mapping: dict[str, dict], name: str) -> str | None:
    """Case-insensitive name lookup: an exact match wins, then a case-folded one."""
    if name in mapping:
        return name
    folded = name.casefold()
    for candidate in mapping:
        if candidate.casefold() == folded:
            return candidate
    return None


def entry(name: str) -> dict | None:
    """The full entry for ``name`` (path + overrides), or None if unknown."""
    mapping = load()
    resolved = _find_name(mapping, name)
    return mapping[resolved] if resolved else None


def resolve(name: str) -> str | None:
    """Return the registered path for ``name``, or None if unknown."""
    found = entry(name)
    return found["path"] if found else None


def _resolved(path: str | Path) -> Path | None:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return None


def _match_path(repo_path: str | Path) -> tuple[str, dict] | None:
    """The registered entry that OWNS ``repo_path``: an exact match or the nearest ancestor.

    `git -C <anything inside the repo>` works, so a path inside a registered repo has to
    find that repo here too — otherwise a consumer handing over a subdirectory silently
    falls through to the default account and narrates with the wrong provider and key,
    with no error to notice. The deepest registered ancestor wins, so a repo nested
    inside another still resolves to itself.
    """
    target = _resolved(repo_path)
    if target is None:
        return None
    best: tuple[str, dict] | None = None
    best_depth = -1
    for name, found in load().items():
        candidate = _resolved(found["path"])
        if candidate is None:
            continue
        if candidate == target or candidate in target.parents:
            depth = len(candidate.parts)
            if depth > best_depth:
                best, best_depth = (name, found), depth
    return best


def entry_for_path(repo_path: str | Path) -> dict | None:
    """The entry registered for a repo *path*, or None.

    The default mode is ``tdreport`` with no argument in the cwd, so per-repo settings
    have to be findable by path and not only by registered name — and findable from
    anywhere inside the repo, the way git works.
    """
    found = _match_path(repo_path)
    return found[1] if found else None


def name_for_path(repo_path: str | Path) -> str | None:
    """The registered name for a repo path (or for anything inside it), or None."""
    found = _match_path(repo_path)
    return found[0] if found else None


def stale() -> list[tuple[str, str]]:
    """Registered entries whose path is gone or is no longer a git repo.

    Kept explicit so `prune` can report before it deletes: silently dropping a name a
    user typed is worse than telling them it is dead.
    """
    dead: list[tuple[str, str]] = []
    for name, found in sorted(load().items()):
        path = Path(found["path"])
        if not path.is_dir() or not (path / ".git").exists():
            dead.append((name, found["path"]))
    return dead


def prune() -> list[tuple[str, str]]:
    """Drop every stale entry; returns what was removed."""
    dead = stale()
    if dead:
        mapping = load()
        for name, _ in dead:
            mapping.pop(name, None)
        save(mapping)
    return dead
