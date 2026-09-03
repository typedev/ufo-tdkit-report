"""Aggregate per-commit facts across a ``base..head`` range into release notes.

Walks every commit in the range, extracts its raw facts (live, via the ``commit_facts``
seam), nets out add-then-remove churn, then reuses the phase-1 ``fold_facts`` rollup —
which already merges the same entity across masters AND across commits. The result is a
release-notes-shaped report that combines binary-invisible source facts with the
commit-message history.

Deterministic and offline. No AI, no network.
"""

from __future__ import annotations

from ufo_tdkit_report.gitsource import GitSource
from ufo_tdkit_report.model import ChangeFact, FactType, RangeReport
from ufo_tdkit_report.rollup import DEFAULT_THRESHOLD, fold_facts
from ufo_tdkit_report.service import _resolve_profile, commit_facts

# Inverse fact-type pairs and the entity key that must match for them to cancel.
# Key derivation: (uses_glyph_scope, detail_index). detail_index None -> no detail key.
_INVERSE_PAIRS = {
    FactType.GLYPH_ADDED: FactType.GLYPH_REMOVED,
    FactType.COMPONENT_ADDED: FactType.COMPONENT_REMOVED,
    FactType.KERN_PAIR_ADDED: FactType.KERN_PAIR_REMOVED,
    FactType.FEA_RULE_ADDED: FactType.FEA_RULE_REMOVED,
    FactType.FEA_FEATURE_ADDED: FactType.FEA_FEATURE_REMOVED,
    FactType.PROFILE_OPTION_ADDED: FactType.PROFILE_OPTION_REMOVED,
    FactType.ANCHOR_ADDED: FactType.ANCHOR_REMOVED,
}
_PAIRED_TYPES = set(_INVERSE_PAIRS) | set(_INVERSE_PAIRS.values())


def _entity_key(fact: ChangeFact) -> tuple:
    """Identity that an add/remove pair must share to cancel (ignores add/remove direction)."""
    ft = fact.fact_type
    if ft in (FactType.GLYPH_ADDED, FactType.GLYPH_REMOVED):
        return ("glyph", fact.scope.glyph)
    if ft in (FactType.COMPONENT_ADDED, FactType.COMPONENT_REMOVED):
        base = fact.detail[0] if fact.detail else None
        return ("component", fact.scope.glyph, base)
    if ft in (FactType.KERN_PAIR_ADDED, FactType.KERN_PAIR_REMOVED):
        return ("kern", fact.detail[0] if fact.detail else None)
    if ft in (FactType.FEA_RULE_ADDED, FactType.FEA_RULE_REMOVED):
        return ("fea_rule", fact.scope.feature_tag, fact.detail[0] if fact.detail else None)
    if ft in (FactType.FEA_FEATURE_ADDED, FactType.FEA_FEATURE_REMOVED):
        return ("fea_feature", fact.detail[0] if fact.detail else None)
    if ft in (FactType.PROFILE_OPTION_ADDED, FactType.PROFILE_OPTION_REMOVED):
        return ("profile", fact.detail[0] if fact.detail else None)
    if ft in (FactType.ANCHOR_ADDED, FactType.ANCHOR_REMOVED):
        return ("anchor", fact.scope.glyph, fact.detail[0] if fact.detail else None)
    return ("other", id(fact))


def net_out(facts: list[ChangeFact]) -> tuple[list[ChangeFact], int]:
    """Drop add/remove pairs that cancel on the same entity within the range.

    Order-independent: an entity that was both added and removed anywhere in the range
    nets to nothing ("did the release introduce this?"). Returns ``(kept, removed_count)``.

    Limitation: a remove-then-readd with *different* content also cancels, losing the
    net edit. Accepted deliberately; non-paired fact types are never touched.
    """
    added_keys: set[tuple] = set()
    removed_keys: set[tuple] = set()
    for fact in facts:
        if fact.fact_type in _INVERSE_PAIRS:  # an "added" side
            added_keys.add(_entity_key(fact))
        elif fact.fact_type in _INVERSE_PAIRS.values():  # a "removed" side
            removed_keys.add(_entity_key(fact))
    cancelled = added_keys & removed_keys

    kept: list[ChangeFact] = []
    removed_count = 0
    for fact in facts:
        if fact.fact_type in _PAIRED_TYPES and _entity_key(fact) in cancelled:
            removed_count += 1
            continue
        kept.append(fact)
    return kept, removed_count


def aggregate_range(
    repo: str,
    spec: str,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    profile: str | None = None,
    family: str | None = None,
    schema=None,
) -> RangeReport:
    """Aggregate facts across every commit in ``spec`` (a ``base..head`` range).

    ``schema`` (optional, duck-typed ``get(key).consequence_text(off)``) is injected by
    a build tool to enrich build-profile facts with grounded consequences; None keeps
    the schema-agnostic line.
    """
    repo = str(repo)
    git = GitSource(repo)
    base, head = git.resolve_spec(spec)
    range_spec = f"{base}..{head}"

    commits = git.list_commits(base, head)

    all_facts: list[ChangeFact] = []
    for commit in commits:
        all_facts.extend(commit_facts(repo, commit.sha, family=family))

    kept, net_removed = net_out(all_facts)
    folded = fold_facts(kept, threshold=threshold, schema=schema)
    profile_name, profile_options = _resolve_profile(repo, profile)

    return RangeReport(
        range_spec=range_spec,
        commits=[(c.sha, c.subject) for c in commits],
        folded_facts=folded,
        raw_fact_count=len(all_facts),
        net_removed_count=net_removed,
        profile_name=profile_name,
        profile_options=profile_options,
        repo=str(repo),
    )
