"""Deterministic post-check: does the narrative stay inside the facts it was given?

The narrator may only restate the facts. That guarantee used to rest entirely on the
model's obedience plus a human reading the ``<details>`` block — fine for a large hosted
model, thin once a local 7B can be the narrator. This module checks what a machine can
check, offline and deterministically, and says plainly what it cannot.

**Why shape, not absence.** The first design flagged every narrative token missing from
the facts. On a real narration that flagged forty-eight words — ``Redraw``,
``punctuation``, ``across``, ``four`` — and nothing useful. Prose is *supposed* to contain
words that are not in the facts. So every rule here keys on a form that prose does not
take, or on the model's own markup.

**Why markup.** ``four``, ``one``, ``section``, ``period`` and ``bullet`` are all standard
glyph names AND ordinary English words; ``in one glyph across four masters`` is correct
prose containing two of them. No length filter or neighbourhood heuristic resolves that —
a rule keyed on "a glyph name near another glyph name" flags the ``one`` in that very
sentence. So the prompt asks the model to backtick every identifier, and this module
verifies the model's own declaration instead of guessing at intent. When the model
ignores that instruction the coverage is lost, and :attr:`GroundingReport.markup_missing`
says so rather than letting it pass as a clean result.

**What it cannot catch:** an invented *meaning* attached to a real identifier ("uni20C5,
the Tamil currency sign"). No token comparison reaches that. The attached facts remain
the answer there — this check narrows the gap, it does not close it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Forms prose does not take, so they can be checked without markup.
_CODEPOINT = re.compile(r"\b(?:uni[0-9A-Fa-f]{4,6}|u[0-9A-Fa-f]{4,6}|U\+[0-9A-Fa-f]{4,6})\b")
_DELTA = re.compile(r"\(\s*[+-]\d+\s*,\s*[+-]?\d+\s*\)")
_APPROX = re.compile(r"~\s*\d+")
_TAG = re.compile(r"\b(?:ss|cv)\d{2}\b|\b[A-Za-z][A-Za-z0-9]*\.[A-Za-z0-9._]+\b")
_TICKED = re.compile(r"`([^`\n]+)`")
# Words long enough for a one-edit difference to mean something rather than be a coincidence.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_.]{4,}")

_KIND_ORDER = ("identifier", "codepoint", "near-miss", "tag", "measurement")


@dataclass(frozen=True)
class Finding:
    """One token in the narrative that the facts do not support."""

    kind: str  # identifier | codepoint | near-miss | tag | measurement
    token: str
    near: str | None = None

    def describe(self) -> str:
        if self.near:
            return f"`{self.token}` — not in the facts (nearest match: `{self.near}`)"
        return f"`{self.token}` — not in the facts"


@dataclass(frozen=True)
class GroundingReport:
    """The verdict for one narration."""

    findings: tuple[Finding, ...] = ()
    markup_missing: bool = False
    checked: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.findings

    def summary(self) -> str:
        """One human line, or ``""`` when there is nothing to say."""
        if self.findings:
            listed = ", ".join(f"`{f.token}`" for f in self.findings)
            return (
                f"{len(self.findings)} token(s) in the narrative do not appear in the "
                f"facts: {listed}"
            )
        if self.markup_missing:
            return (
                "the model did not mark up any identifiers, so glyph-name checking was "
                "skipped for this narration"
            )
        return ""


def _one_edit_apart(a: str, b: str) -> bool:
    """True if ``a`` and ``b`` differ by a single insert, delete or substitution."""
    if abs(len(a) - len(b)) > 1 or a == b:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = seen = 0
    while i < len(short) and j < len(long):
        if short[i] != long[j]:
            seen += 1
            if seen > 1:
                return False
            j += 1
        else:
            i += 1
            j += 1
    return True


def identifiers(facts: str, report=None) -> set[str]:
    """Only the things the facts present AS identifiers, not their English prose.

    The near-miss rule compares against this and not against every word in the facts.
    Comparing against all of them made ``changed`` a one-edit "near miss" of ``changes``
    in the report's own heading — two ordinary words, a pure false positive. Identifiers
    are what the facts backtick, plus the structured glyph and master names behind the
    text, which are authoritative where the rendering is merely formatting.
    """
    found = set(_TICKED.findall(facts)) | set(_CODEPOINT.findall(facts)) | set(_TAG.findall(facts))
    for fact in getattr(report, "folded_facts", ()) or ():
        for scope in getattr(fact, "affected", ()) or ():
            for value in (getattr(scope, "glyph", None), getattr(scope, "master", None)):
                if value:
                    found.add(value)
    return found


def vocabulary(facts: str, report=None) -> set[str]:
    """Everything the model was shown: the identifiers plus the surrounding wording.

    Used to decide whether a token *appeared*; :func:`identifiers` is used to decide what
    a token could plausibly be a corruption OF.
    """
    return identifiers(facts, report) | set(_WORD.findall(facts))


def _grounded(token: str, facts: str, vocab: set[str]) -> bool:
    """A token is grounded if it was shown verbatim, or as a plain plural/case variant."""
    if token in vocab or token in facts:
        return True
    lowered = {v.lower() for v in vocab}
    return token.lower() in lowered or token.rstrip("s").lower() in lowered


def check(narrative: str, facts: str, report=None) -> GroundingReport:
    """Compare a narrative against the facts it was generated from. Pure, offline."""
    vocab = vocabulary(facts, report)
    found: dict[str, Finding] = {}
    checks: list[str] = []

    def record(kind: str, token: str, near: str | None = None) -> None:
        existing = found.get(token)
        if existing and _KIND_ORDER.index(existing.kind) <= _KIND_ORDER.index(kind):
            return
        found[token] = Finding(kind, token, near)

    # 1. The model's own markup: it declared these to be identifiers.
    ticked = _TICKED.findall(narrative)
    if ticked:
        checks.append("marked-up identifiers")
        for token in ticked:
            token = token.strip().rstrip(",.;:")
            if token and not _grounded(token, facts, vocab):
                record("identifier", token)

    # 2-4. Forms prose does not take, checked with or without markup.
    for pattern, kind, label in (
        (_CODEPOINT, "codepoint", "codepoints"),
        (_DELTA, "measurement", "measurements"),
        (_APPROX, "measurement", "measurements"),
        (_TAG, "tag", "feature tags and alternates"),
    ):
        hits = pattern.findall(narrative)
        if hits and label not in checks:
            checks.append(label)
        for token in hits:
            normalized = re.sub(r"\s+", "", token)
            if normalized not in re.sub(r"\s+", "", facts) and not _grounded(token, facts, vocab):
                record(kind, token)

    # 5. A near-miss of something the model WAS shown: what invention actually looks like.
    checks.append("near-misses of known names")
    candidates = [v for v in identifiers(facts, report) if len(v) >= 6]
    for raw in _WORD.findall(narrative):
        # Glyph names carry dots (`a.ss02`), so the word pattern has to allow them — which
        # means sentence punctuation sticks to the token and would read as a one-edit
        # difference from the real name. Trim it before judging.
        token = raw.rstrip(".,;:")
        if not token or _grounded(token, facts, vocab):
            continue
        near = next((v for v in candidates if _one_edit_apart(token, v)), None)
        if near:
            record("near-miss", token, near)

    ordered = sorted(found.values(), key=lambda f: (_KIND_ORDER.index(f.kind), f.token))
    return GroundingReport(
        findings=tuple(ordered),
        markup_missing=bool("`" in facts and not ticked),
        checked=tuple(checks),
    )
