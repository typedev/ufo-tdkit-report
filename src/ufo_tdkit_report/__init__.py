"""ufo-tdkit-report — deterministic, git-centric UFO/designspace source-change extractor.

Reads a commit (range) of a font source repo, diffs the sources semantically
(formatting-agnostic), and compresses the changes into a few deterministic facts —
catching outline redraws and feature-rule changes that a binary font diff misses.

    from ufo_tdkit_report import extract_facts
    report = extract_facts(repo, "HEAD")
    print(report.render_text())

Everything a consumer needs is re-exported here, and that deliberately includes the
warning categories a public call can *raise* (``GroundingWarning``, ``UnboundRepoWarning``)
— not only the functions it can call. A consumer that must reach into ``settings`` or
``narrator`` to catch what ``narrate`` or ``resolve_ai_settings`` throws is pinned to
this package's internal layout, and an ordinary refactor here would break it without
looking like an API change from the inside. The module-level names stay valid.
"""

from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import version as _pkg_version

from ufo_tdkit_report.aggregate import aggregate_range
from ufo_tdkit_report.config import InsecureKeyFileWarning
from ufo_tdkit_report.model import (
    ChangeFact,
    FactType,
    FileKind,
    FoldedFact,
    RangeReport,
    Scope,
    SourceReport,
)
from ufo_tdkit_report.narrator import (
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    KNOWN_MODELS,
    GroundingWarning,
    NarratorError,
    list_models,
    narrate,
    narrate_commit,
    resolve_ai_settings,
    resolve_api_key,
    resolve_model,
    store_account_key,
    store_api_key,
    store_model,
)
from ufo_tdkit_report.providers import PROVIDERS, Provider
from ufo_tdkit_report.service import (
    commit_facts,
    describe_changes,
    extract_facts,
    extract_working_facts,
)
from ufo_tdkit_report.settings import Account, AiSettings, UnboundRepoWarning


def _editable_source_version() -> str | None:
    """The version in the source tree an editable install points at, or None.

    An editable install freezes its metadata at install time and then runs code that
    moves on without it, so `tdreport --version` keeps reporting whatever was current
    when it was installed. That is not cosmetic here: the version is stamped into every
    report footer and every commit trailer, so a stale one writes a false claim into git
    history — an editable install at 0.4.1 was running 0.5.x code and saying 0.4.1.

    This is not a derived or dev version — no git, no dirty-tree suffix, nothing that
    would make output depend on the checkout's state (see CLAUDE.md). It reads the same
    static number from `pyproject.toml`, the single source of truth, so an editable
    install and a real one at the same commit stamp identical bytes.

    Never raises: any surprise falls back to the recorded metadata.
    """
    try:
        import json
        import re
        from pathlib import Path
        from urllib.parse import unquote, urlparse

        info = json.loads(distribution("ufo-tdkit-report").read_text("direct_url.json") or "")
        if not info.get("dir_info", {}).get("editable"):
            return None
        source = Path(unquote(urlparse(info["url"]).path)) / "pyproject.toml"
        found = re.search(r'^version = "([^"]+)"', source.read_text(encoding="utf-8"), re.M)
        return found.group(1) if found else None
    except Exception:  # noqa: BLE001 — a version lookup must never break an import
        return None


try:
    __version__ = _editable_source_version() or _pkg_version("ufo-tdkit-report")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"


__all__ = [
    "__version__",
    "extract_facts",
    "extract_working_facts",
    "aggregate_range",
    "commit_facts",
    "describe_changes",
    "narrate",
    "narrate_commit",
    "resolve_api_key",
    "store_api_key",
    "resolve_model",
    "store_model",
    "resolve_ai_settings",
    "store_account_key",
    "list_models",
    "Account",
    "AiSettings",
    "Provider",
    "PROVIDERS",
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "DEFAULT_LANGUAGE",
    "KNOWN_MODELS",
    "NarratorError",
    "GroundingWarning",
    "InsecureKeyFileWarning",
    "UnboundRepoWarning",
    "SourceReport",
    "RangeReport",
    "FoldedFact",
    "ChangeFact",
    "FactType",
    "FileKind",
    "Scope",
]
