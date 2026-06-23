"""tdreport — deterministic UFO/designspace/profile source-change extractor (issue #5).

Reads a commit (range) of a font source repo, diffs the sources semantically
(formatting-agnostic), and compresses the changes into a few deterministic facts —
catching outline redraws and feature-rule changes that a binary font diff misses.

Public API (consumed by the future releaser/aggregator, issue #4):

    from ufo_tdkit_report import extract_facts
    report = extract_facts(repo, "HEAD")
    print(report.render_text())
"""

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
from ufo_tdkit_report.narrator import NarratorError, narrate, narrate_commit, resolve_api_key
from ufo_tdkit_report.service import commit_facts, extract_facts, extract_working_facts

__all__ = [
    "extract_facts",
    "extract_working_facts",
    "aggregate_range",
    "commit_facts",
    "narrate",
    "narrate_commit",
    "resolve_api_key",
    "NarratorError",
    "SourceReport",
    "RangeReport",
    "FoldedFact",
    "ChangeFact",
    "FactType",
    "FileKind",
    "Scope",
]
