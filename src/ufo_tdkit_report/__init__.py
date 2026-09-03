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

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("ufo-tdkit-report")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"

from ufo_tdkit_report.aggregate import aggregate_range
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
from ufo_tdkit_report.service import commit_facts, extract_facts, extract_working_facts
from ufo_tdkit_report.settings import Account, AiSettings, UnboundRepoWarning

__all__ = [
    "__version__",
    "extract_facts",
    "extract_working_facts",
    "aggregate_range",
    "commit_facts",
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
    "UnboundRepoWarning",
    "SourceReport",
    "RangeReport",
    "FoldedFact",
    "ChangeFact",
    "FactType",
    "FileKind",
    "Scope",
]
