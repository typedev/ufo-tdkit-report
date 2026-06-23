# ufo-tdkit-report

Deterministic, git-centric source-change extractor and narrator for UFO / designspace
font projects. It diffs the **sources** semantically (formatting-agnostic) and compresses
the changes into a few facts — catching outline redraws and feature-rule changes that a
binary font diff misses. Optionally drafts a grounded commit message or release notes.

Standalone and build-tool-agnostic: it needs **git**, not any particular font compiler.

## Features

- **Semantic source diff** — outlines (coordinate-based, not text), kerning/groups,
  fontinfo, OpenType features (`feaLib` rule level), designspace (axes/masters/instances),
  and build-profile YAML (option level).
- **No silent omissions** — every changed tracked file surfaces as a fact (semantic when
  available, else a bare added/removed/modified note). `.gitignore` is honoured.
- **Commit assistant** — draft a commit message from the working tree.
- **Range / release notes** — aggregate a tag/commit range into notes.
- **Grounded AI narration** (opt-in) — `--ai-note` turns the deterministic facts into
  prose, attaching the facts verbatim for verification. Needs `ANTHROPIC_API_KEY`.

## Install

```bash
pip install ufo-tdkit-report
```

## Usage

```bash
# Working-tree commit assistant
tdreport                       # draft a message for the current repo
tdreport --ai-note             # narrated by a grounded AI
tdreport commit                # commit the working tree with the drafted message

# Named repos (explicit registration — nothing is auto-registered)
tdreport add myfont ~/fonts/MyFont
tdreport myfont                # commit assistant for a registered repo
tdreport ~/fonts/MyFont        # or an explicit path

# Committed history
tdreport v2.005..v2.006        # endpoint diff of a range (cwd repo)
tdreport --notes v2.005..HEAD  # aggregate every commit in the range into release notes
```

## Library

```python
from ufo_tdkit_report import extract_facts, aggregate_range
report = extract_facts(".", "HEAD~1..HEAD")
print(report.render_text())
```

Build-profile *consequence* semantics (e.g. "ttfautohint off → no TT hinting") are
build-tool-specific: a consumer that owns an option schema injects it via
`fold_facts(..., schema=...)`. Without one, profile changes render as a bare option diff.

## License

Apache-2.0
