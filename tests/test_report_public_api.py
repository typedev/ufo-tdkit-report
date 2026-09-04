"""Tests for the package's public surface — what `from ufo_tdkit_report import ...` gives.

The point of these is not to inventory names for their own sake. A consumer that can only
reach something by importing `ufo_tdkit_report.settings` or `ufo_tdkit_report.narrator` is
pinned to this package's internal layout, and moving that name later looks like an
ordinary refactor from in here while breaking them out there. So the rule this file
enforces is: everything a documented public call can raise is reachable from the root.
"""

import warnings

import pytest

import ufo_tdkit_report as pkg
from ufo_tdkit_report.narrator import GroundingWarning as narrator_GroundingWarning
from ufo_tdkit_report.settings import UnboundRepoWarning as settings_UnboundRepoWarning


def test_everything_in_all_actually_resolves():
    missing = [name for name in pkg.__all__ if not hasattr(pkg, name)]
    assert missing == []


@pytest.mark.parametrize("name", ["NarratorError", "GroundingWarning", "UnboundRepoWarning"])
def test_every_raisable_category_is_exported_from_the_root(name):
    """`narrate` and `resolve_ai_settings` are public; so must be what they throw.

    Exporting the call but not its exception is half a contract — the caller still has to
    import from an internal module to write the `except`/`catch_warnings` around it.
    """
    assert name in pkg.__all__
    assert issubclass(getattr(pkg, name), (Exception, Warning))


def test_module_level_names_stay_the_same_objects():
    """The root is a re-export, not a second definition.

    `except ufo_tdkit_report.UnboundRepoWarning` must catch what `settings` raises, and
    the older import sites must keep working — two classes with one name would be a
    silent, extremely confusing break.
    """
    assert pkg.UnboundRepoWarning is settings_UnboundRepoWarning
    assert pkg.GroundingWarning is narrator_GroundingWarning


def test_the_root_categories_catch_what_the_library_actually_raises():
    """Filtering on the re-exported category is the usage this export exists for."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pkg.UnboundRepoWarning)
        warnings.warn("unbound", settings_UnboundRepoWarning, stacklevel=1)
    assert len(caught) == 1
    assert issubclass(caught[0].category, pkg.UnboundRepoWarning)

    with pytest.warns(pkg.GroundingWarning):
        warnings.warn("ungrounded", narrator_GroundingWarning, stacklevel=1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_extraction_never_narrates_however_the_cli_default_changes(tmp_path):
    """The composition is opt-in; the extractors stay pure.

    Not "the only public call that touches the network" — `narrate` and `list_models`
    reach a provider by their nature, and claiming otherwise was wrong in the docs for a
    while. The boundary worth pinning is narrower and real: turning a repository into
    facts must never involve a model.

    `extract_facts` and friends are embedded in build pipelines, where a paid model call
    is not a reasonable thing for a fact extractor to make on its own initiative. Making
    narration the CLI default must not quietly change that, so this pins the boundary:
    the new convenience is the one that narrates, and the old ones still cannot.
    """
    import inspect as _inspect

    assert "describe_changes" in pkg.__all__
    for name in ("extract_facts", "extract_working_facts", "aggregate_range", "commit_facts"):
        source = _inspect.getsource(getattr(pkg, name))
        assert "narrate" not in source, f"{name} must not narrate"

    signature = _inspect.signature(pkg.describe_changes)
    assert signature.parameters["ai"].default is True
    # The resolution chain owns every AI setting: a concrete default here would silently
    # bypass the owner's account and model (CLAUDE.md's one-resolution-chain invariant).
    for name in ("model", "provider", "language", "account", "strict_grounding"):
        assert signature.parameters[name].default is None
