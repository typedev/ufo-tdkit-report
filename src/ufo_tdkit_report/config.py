"""Config-directory and ``.env`` primitives.

Split out of ``narrator`` so the modules that need them can share them without a
cycle: ``registry`` and ``settings`` both read the config dir, and ``settings``
reads the registry. This module therefore imports nothing from the package.

The discipline these functions exist to enforce: the tool has exactly ONE config
directory and ONE ``.env`` inside it, the process environment is never consulted
for a key or a preference, and a write never clobbers the entries it is not
touching (the file holds several accounts' secrets side by side).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LEGACY_KEY_VAR = "ANTHROPIC_API_KEY"
LEGACY_MODEL_VAR = "TDREPORT_AI_MODEL"

CONFIG_DIR_NAME = "ufo-tdkit-report"


def config_dir() -> Path:
    """This tool's own OS-specific config directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / CONFIG_DIR_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / CONFIG_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / CONFIG_DIR_NAME


def config_env_path() -> Path:
    """The single file API keys live in: ``<config>/.env``."""
    return config_dir() / ".env"


def secure(path: Path) -> None:
    """Best-effort: lock ``path`` to owner-only (0600) and its parent dir to 0700.

    A no-op on platforms without POSIX permission bits (e.g. Windows), where the
    user-profile directory ACL already governs access. Errors are swallowed so a
    read/store never fails just because the perms could not be tightened.
    """
    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except (OSError, NotImplementedError):
        pass


def read_dotenv_key(paths: list[Path], var: str = LEGACY_KEY_VAR) -> str | None:
    """Read a single env var from the first existing ``.env`` file in ``paths``.

    Targeted on purpose: parses only ``var`` and never touches the process environment
    or other keys (so it can't clobber PATH). Accepts ``KEY=value``, ``export
    KEY=value``, and quoted values; ignores comments/blanks.
    """
    for path in paths:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            key, _, value = line.partition("=")
            if key.strip() != var:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                return value
    return None


def write_dotenv_var(path: Path, var: str, value: str) -> Path:
    """Set ``var`` in a ``.env`` file, preserving every other line. Owner-only.

    The config file holds several accounts' secrets side by side, so a write must never
    drop the entries it is not touching (storing one account's key must not lose
    another's). Rewrites an existing definition in place, appends otherwise, and
    collapses duplicate definitions of the same var.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    out: list[str] = []
    replaced = False
    for raw in lines:
        stripped = raw.strip()
        candidate = stripped[len("export ") :].lstrip() if stripped.startswith("export ") else stripped
        if candidate.partition("=")[0].strip() == var:
            if replaced:
                continue  # a duplicate definition of the same var: drop it
            out.append(f"{var}={value}")
            replaced = True
        else:
            out.append(raw)
    if not replaced:
        out.append(f"{var}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    secure(path)
    return path


def delete_dotenv_var(path: Path, var: str) -> bool:
    """Drop every definition of ``var`` from a ``.env`` file. True if anything went.

    Used when an account is removed: its secret must not linger in the file.
    """
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    out = []
    removed = False
    for raw in lines:
        stripped = raw.strip()
        candidate = stripped[len("export ") :].lstrip() if stripped.startswith("export ") else stripped
        if candidate.partition("=")[0].strip() == var:
            removed = True
            continue
        out.append(raw)
    if removed:
        path.write_text(("\n".join(out) + "\n") if out else "", encoding="utf-8")
        secure(path)
    return removed
