"""Lightweight ``name -> repo path`` registry for ``tdreport <name>``.

Stored as JSON in the tool's own config dir. Names are pure convenience: the core
modes (cwd, explicit path) work without registering anything. Registration is always
explicit (``tdreport add <name> <path>``) — nothing is auto-registered.
"""

from __future__ import annotations

import json
from pathlib import Path

from ufo_tdkit_report.narrator import config_dir


def _registry_path() -> Path:
    return config_dir() / "repos.json"


def load() -> dict[str, str]:
    path = _registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save(mapping: dict[str, str]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def add(name: str, repo_path: str) -> str:
    """Register ``name`` -> absolute repo path; returns the stored path."""
    resolved = str(Path(repo_path).expanduser().resolve())
    mapping = load()
    mapping[name] = resolved
    save(mapping)
    return resolved


def remove(name: str) -> bool:
    mapping = load()
    if name in mapping:
        del mapping[name]
        save(mapping)
        return True
    return False


def resolve(name: str) -> str | None:
    """Return the registered path for ``name``, or None if unknown."""
    return load().get(name)
