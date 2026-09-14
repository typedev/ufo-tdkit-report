"""Parse and diff ``features.fea`` at the rule level.

Binary diff only sees feature *tags* (added/removed). Real releases add substitution
rules *inside existing* tags (e.g. ss02/ss03/pnum/tnum), which a tag-level view
misses entirely. We parse the feaLib AST and set-diff the normalized rule strings
per feature tag, and per standalone ``lookup`` block — a lookup defined at top level
and referenced from several features is where shared contextual logic lives, and
diffing it as one opaque block reported a one-line edit as the whole lookup removed
and re-added.

**Class order is semantic.** In ``sub @A by @B`` members pair by position, so
reordering ``@B`` re-pairs every glyph while no rule text changes. A sorted view
diffed that to nothing — a real fix to a stylistic set went unreported. So classes keep
source order, and every single substitution records the glyph pairs it expands to:
when those pairs change under an unchanged rule, the fact says exactly which glyph now
becomes which. That is the effect a reader needs, and it is computed, not guessed.

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


def _rule_text(rule) -> str:
    try:
        return rule.asFea().strip()
    except Exception:
        return repr(rule)


def _class_members(definition) -> tuple[str, ...]:
    """A class's members as written, in source order — nested ``@CLASS`` refs unexpanded.

    Unexpanded on purpose: expanding would report one glyph added to ``@FIGURES`` again
    under every class that includes it. The *expanded* view is what substitutions use,
    and :func:`_single_pairs` computes that separately.
    """
    try:
        return tuple(definition.glyphs.asFea().strip().strip("[]").split())
    except Exception:
        return ()


def _single_pairs(rule) -> tuple[tuple[str, str], ...] | None:
    """The ``(input, output)`` glyph pairs a single substitution expands to, in order.

    None for anything that is not a one-to-one substitution or cannot be expanded.
    """
    from fontTools.feaLib import ast

    if not isinstance(rule, ast.SingleSubstStatement):
        return None
    try:
        inputs = [g for container in rule.glyphs for g in container.glyphSet()]
        outputs = [g for container in rule.replacements for g in container.glyphSet()]
    except Exception:
        return None
    if len(outputs) == 1:
        outputs = outputs * len(inputs)
    if len(inputs) != len(outputs):
        return None
    return tuple(zip(inputs, outputs))


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
    rules_by_lookup: dict[str, set[str]] = {}
    lookup_users: dict[str, set[str]] = {}
    classes: dict[str, tuple[str, ...]] = {}
    top_level: set[str] = set()
    # (feature_tag, lookup, rule_text) -> glyph pairs; a rule repeated verbatim merges.
    substitutions: dict[tuple[str, str, str], set[tuple[str, str]]] = {}

    def collect(statements, bucket: set[str], feature: str, lookup: str) -> None:
        for rule in _flatten_statements(statements):
            text = _rule_text(rule)
            bucket.add(text)
            if feature and isinstance(rule, ast.LookupReferenceStatement):
                lookup_users.setdefault(rule.lookup.name, set()).add(feature)
            pairs = _single_pairs(rule)
            if pairs:
                substitutions.setdefault((feature, lookup, text), set()).update(pairs)

    for st in doc.statements:
        if isinstance(st, ast.FeatureBlock):
            collect(st.statements, rules_by_feature.setdefault(st.name, set()), st.name, "")
        elif isinstance(st, ast.LookupBlock):
            collect(st.statements, rules_by_lookup.setdefault(st.name, set()), "", st.name)
        elif isinstance(st, ast.GlyphClassDefinition):
            classes[st.name] = _class_members(st)
        elif not _is_comment(st):
            top_level.add(_rule_text(st))

    def frozen(mapping: dict[str, set[str]]) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple(sorted((name, tuple(sorted(values))) for name, values in mapping.items()))

    return FeaSnapshot(
        rules_by_feature=frozen(rules_by_feature),
        classes=tuple(sorted(classes.items())),
        top_level=tuple(sorted(top_level)),
        rules_by_lookup=frozen(rules_by_lookup),
        lookup_users=frozen(lookup_users),
        substitutions=tuple(sorted((key, tuple(sorted(pairs))) for key, pairs in substitutions.items())),
    )


def _rule_facts(old_rules, new_rules, scope: Scope, extra: tuple = ()) -> list[ChangeFact]:
    facts = []
    for rule in sorted(set(new_rules) - set(old_rules)):
        facts.append(ChangeFact(FactType.FEA_RULE_ADDED, FileKind.FEATURES, scope, (rule, *extra)))
    for rule in sorted(set(old_rules) - set(new_rules)):
        facts.append(ChangeFact(FactType.FEA_RULE_REMOVED, FileKind.FEATURES, scope, (rule, *extra)))
    return facts


def _mapping_changes(old_pairs, new_pairs) -> tuple[tuple[str, str | None, str | None], ...]:
    """``(input, old_output, new_output)`` for every input whose output changed."""
    old_map, new_map = dict(old_pairs), dict(new_pairs)
    return tuple(
        (glyph, old_map.get(glyph), new_map.get(glyph))
        for glyph in sorted(set(old_map) | set(new_map))
        if old_map.get(glyph) != new_map.get(glyph)
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
        facts.extend(_rule_facts(old_feats[tag], new_feats[tag], feat_scope))

    old_lookups = dict(old.rules_by_lookup)
    new_lookups = dict(new.rules_by_lookup)
    users = dict(old.lookup_users) | dict(new.lookup_users)
    for name in sorted(set(old_lookups) | set(new_lookups)):
        lookup_scope = Scope(family=scope.family, master=scope.master, lookup=name)
        # Where the lookup runs is what turns a rule into an effect a reader can place.
        facts.extend(_rule_facts(
            old_lookups.get(name, ()), new_lookups.get(name, ()), lookup_scope, (users.get(name, ()),)
        ))

    old_classes = dict(old.classes)
    new_classes = dict(new.classes)
    for name in sorted(set(old_classes) | set(new_classes)):
        before, after = old_classes.get(name), new_classes.get(name)
        if before == after:
            continue
        before, after = before or (), after or ()
        added = tuple(m for m in after if m not in before)
        removed = tuple(m for m in before if m not in after)
        reordered = not added and not removed
        facts.append(ChangeFact(
            FactType.FEA_CLASS_CHANGED, FileKind.FEATURES, scope, (name, added, removed, reordered)
        ))

    # A rule whose text is unchanged but whose glyph pairs moved: a class it names was
    # edited. Rules that were added or removed are already facts of their own.
    old_subs = dict(old.substitutions)
    for key, new_pairs in new.substitutions:
        if key not in old_subs:
            continue
        changes = _mapping_changes(old_subs[key], new_pairs)
        if not changes:
            continue
        feature, lookup, rule = key
        sub_scope = Scope(
            family=scope.family, master=scope.master, feature_tag=feature or None, lookup=lookup or None
        )
        facts.append(ChangeFact(FactType.FEA_MAPPING_CHANGED, FileKind.FEATURES, sub_scope, (rule, changes)))

    # Top-level (non-feature, non-lookup) rule churn, including the parse-failure fallback.
    if old.top_level != new.top_level:
        facts.extend(_rule_facts(old.top_level, new.top_level, scope))

    return facts
