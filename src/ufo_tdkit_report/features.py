"""Parse and diff ``features.fea`` at the rule level (issue #5, phase 1).

Binary diff only sees feature *tags* (added/removed). Real releases add substitution
rules *inside existing* tags (e.g. ss02/ss03/pnum/tnum), which a tag-level view
misses entirely. We parse the feaLib AST and set-diff the normalized rule strings
per feature tag.

``followIncludes=False`` is mandatory: we parse blob strings out of git with no
working tree, so ``include()`` targets are not on disk and the default would raise.
Any feaLib failure falls back to a line-normalized textual diff so one unparseable
file never aborts the run.
"""

from __future__ import annotations

from ufo_tdkit_report.model import ChangeFact, FactType, FeaSnapshot, FileKind, Scope


def _is_comment(statement) -> bool:
    """True for feaLib comment nodes / comment-only lines (not real rules)."""
    from fontTools.feaLib import ast

    if isinstance(statement, ast.Comment):
        return True
    try:
        return statement.asFea().strip().startswith("#")
    except Exception:
        return False


def _flatten_statements(statements):
    """Yield leaf rule statements, descending into nested blocks and skipping comments."""
    for st in statements:
        inner = getattr(st, "statements", None)
        if inner is not None:
            yield from _flatten_statements(inner)
        elif not _is_comment(st):
            yield st


def _line_normalized_fallback(text: str) -> FeaSnapshot:
    """When feaLib cannot parse: treat each non-empty stripped line as a top-level rule."""
    lines = tuple(sorted({ln.strip() for ln in text.splitlines() if ln.strip()}))
    return FeaSnapshot(rules_by_feature=(), classes=(), top_level=lines, parse_failed=True)


def parse_fea(text: str | None) -> FeaSnapshot | None:
    if text is None:
        return None
    import io

    from fontTools.feaLib import ast
    from fontTools.feaLib.parser import Parser

    try:
        doc = Parser(io.StringIO(text), glyphNames=set(), followIncludes=False).parse()
    except Exception:
        return _line_normalized_fallback(text)

    rules_by_feature: dict[str, set[str]] = {}
    classes: dict[str, tuple[str, ...]] = {}
    top_level: set[str] = set()

    for st in doc.statements:
        if isinstance(st, ast.FeatureBlock):
            bucket = rules_by_feature.setdefault(st.name, set())
            for rule in _flatten_statements(st.statements):
                try:
                    bucket.add(rule.asFea().strip())
                except Exception:
                    bucket.add(repr(rule))
        elif isinstance(st, ast.GlyphClassDefinition):
            try:
                members = tuple(sorted(st.glyphs.glyphSet()))
            except Exception:
                members = ()
            classes[st.name] = members
        else:
            try:
                top_level.add(st.asFea().strip())
            except Exception:
                top_level.add(repr(st))

    return FeaSnapshot(
        rules_by_feature=tuple(sorted((tag, tuple(sorted(rules))) for tag, rules in rules_by_feature.items())),
        classes=tuple(sorted(classes.items())),
        top_level=tuple(sorted(top_level)),
    )


def diff_fea(old: FeaSnapshot, new: FeaSnapshot, scope: Scope) -> list[ChangeFact]:
    facts: list[ChangeFact] = []

    old_feats = dict(old.rules_by_feature)
    new_feats = dict(new.rules_by_feature)
    for tag in sorted(set(old_feats) | set(new_feats)):
        feat_scope = Scope(family=scope.family, master=scope.master, feature_tag=tag)
        if tag not in new_feats:
            facts.append(ChangeFact(FactType.FEA_FEATURE_REMOVED, FileKind.FEATURES, feat_scope, (tag,)))
            continue
        if tag not in old_feats:
            facts.append(ChangeFact(FactType.FEA_FEATURE_ADDED, FileKind.FEATURES, feat_scope, (tag,)))
            continue
        old_rules, new_rules = set(old_feats[tag]), set(new_feats[tag])
        for rule in sorted(new_rules - old_rules):
            facts.append(ChangeFact(FactType.FEA_RULE_ADDED, FileKind.FEATURES, feat_scope, (rule,)))
        for rule in sorted(old_rules - new_rules):
            facts.append(ChangeFact(FactType.FEA_RULE_REMOVED, FileKind.FEATURES, feat_scope, (rule,)))

    old_classes = dict(old.classes)
    new_classes = dict(new.classes)
    for name in sorted(set(old_classes) | set(new_classes)):
        if old_classes.get(name) != new_classes.get(name):
            facts.append(ChangeFact(FactType.FEA_CLASS_CHANGED, FileKind.FEATURES, scope, (name,)))

    # Top-level (non-feature) rule churn, including the parse-failure fallback path.
    if old.top_level != new.top_level:
        old_top, new_top = set(old.top_level), set(new.top_level)
        for rule in sorted(new_top - old_top):
            facts.append(ChangeFact(FactType.FEA_RULE_ADDED, FileKind.FEATURES, scope, (rule,)))
        for rule in sorted(old_top - new_top):
            facts.append(ChangeFact(FactType.FEA_RULE_REMOVED, FileKind.FEATURES, scope, (rule,)))

    return facts
