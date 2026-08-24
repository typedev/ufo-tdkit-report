"""ufo-tdkit-report — deterministic, git-centric UFO/designspace source-change extractor.

Reads a commit (range) of a font source repo, diffs the sources semantically
(formatting-agnostic), and compresses the changes into a few deterministic facts —
catching outline redraws and feature-rule changes that a binary font diff misses.

    from ufo_tdkit_report import extract_facts
    report = extract_facts(repo, "HEAD")
    print(report.render_text())
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
    DEFAULT_MODEL,
    KNOWN_MODELS,
    NarratorError,
    list_models,
    narrate,
    narrate_commit,
    resolve_api_key,
    resolve_model,
    store_api_key,
    store_model,
)
from ufo_tdkit_report.service import commit_facts, extract_facts, extract_working_facts

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
    "list_models",
    "DEFAULT_MODEL",
    "KNOWN_MODELS",
    "NarratorError",
    "SourceReport",
    "RangeReport",
    "FoldedFact",
    "ChangeFact",
    "FactType",
    "FileKind",
    "Scope",
]
