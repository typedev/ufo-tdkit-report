# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`ufo-tdkit-report` (CLI: `tdreport`) is a deterministic, git-centric source-change
extractor for UFO / designspace font projects. It diffs font **sources** semantically
(formatting-agnostic) and compresses the changes into a few facts, catching outline
redraws and feature-rule changes a binary font diff misses. It shells out to `git` but
depends on no particular font compiler. Optionally it drafts a grounded commit message or
release notes via the Anthropic API (opt-in).

## Commands

The project uses `uv` (there is a `uv.lock` and `.venv`).

```bash
uv run pytest -q                              # full test suite (~80 tests, <1s)
uv run pytest tests/test_report_rollup.py     # one test file
uv run pytest -k outline_redraw               # one test by name substring
uv run ruff check .                           # lint (config in pyproject.toml)
uv run ruff check --fix .                     # autofix lint
uv run tdreport ...                           # run the CLI from source
```

There is no separate build/typecheck step. `ruff` enforces `E,W,F,I,N` at line-length 120,
target py310.

## Architecture

A strict one-way pipeline; each stage is a separate module and the data vocabulary
(`model.py`) imports nothing beyond the stdlib so it stays trivially unit-testable.

```
git plumbing  →  path classify  →  parse + diff  →  fold/rollup  →  render / narrate
gitsource.py     paths.py          classify.py       rollup.py       render.py
                                    + per-kind        aggregate.py    narrator.py
                                    parsers
```

- **`service.py`** is the orchestration seam. `extract_facts` (committed range),
  `extract_working_facts` (uncommitted tree), and `commit_facts` (one commit) are the
  public API re-exported from `__init__.py`. Nothing below `service` prints; rendering is
  separate.
- **`gitsource.py`** is the *only* module that shells out. `git -C <repo>` everywhere (no
  reliance on process cwd). `runner` is injectable (`subprocess.run` by default) so the
  layer is unit-tested with canned stdout; blobs are batch-fetched via `git cat-file
  --batch`. Working-tree changes come from `git status --porcelain=v1 -z`.
- **`paths.py`** maps a repo-relative path to a `FileKind` (or `None` to ignore). The
  authoritative glyph *name* comes from the parsed `.glif` body, never the filename (UFO
  mangles filenames).
- **`classify.py`** routes a `ChangedFile` (blobs already resolved) to the right
  parser+differ pair and returns raw `ChangeFact`s. `file_note()` emits a bare
  constatation for any changed tracked file that produced no semantic fact (see T3 below).
- **Per-kind parse/diff modules**: `glif.py` (coordinate-level outline/component/anchor
  diff), `plists.py` (kerning/groups/fontinfo), `features.py` (OpenType `.fea` via
  `feaLib`, rule level), `designspace.py` (axes/masters/instances), `profile.py`
  (build-profile YAML, option level). Each parses to a **normalized, serialization-order-
  agnostic snapshot** (`model.py`) so editor re-serialization noise diffs to nothing.
- **`rollup.py`** (`fold_facts`) is the compression core: it groups identical atoms across
  masters into one folded fact, groups component shifts by `(base, delta)` to surface
  batch ops, and above `--threshold` distinct glyphs emits statistics instead of
  enumerating. All ordering is total and value-based so output is **byte-stable** across
  runs.
- **`aggregate.py`** (`aggregate_range`) walks every commit in a range, nets out
  add-then-remove churn (`net_out`), then reuses `fold_facts` — producing release notes.
- **`render.py`** turns reports into text/markdown and owns the attribution footer.
  `SourceReport.render_text()` / `RangeReport.render_text()` delegate here.
- **`narrator.py`** is the opt-in AI layer. See its constraints below.
- **`cli.py`** dispatches: a `target` containing `..` (or `--notes`) → committed-history
  modes; `add` → registry; otherwise the working-tree commit assistant (`commit.py`).
- **`registry.py`** is a `name → path` JSON map in the config dir; `commit.py` resolves a
  repo from cwd / registered name / explicit path. An unknown bare target is an **error**,
  never a silent cwd fallback.

## Invariants to preserve

- **Determinism & byte-stability.** No `Date.now()`/random in output paths; every sort key
  is total and value-based. Snapshots are normalized so reordered serialization diffs to
  nothing. Changing fold/sort logic will churn every downstream report — keep ordering
  total.
- **No silent omissions (referred to as "T3").** Every changed tracked file surfaces as a
  fact: semantic when available, else a bare `added/removed/modified` constatation under an
  "Other files" section (`FactType.FILE_CHANGED` / `FileKind.OTHER`). `.gitignore` is
  honoured. Don't add a code path that drops a changed file.
- **Build-tool-agnostic.** The tool has no built-in knowledge of any build tool's profile
  options. Build-profile *consequence* semantics are injected by a consumer via
  `fold_facts(..., schema=...)` / the `schema=` param on the public extract/aggregate API
  (duck-typed `schema.get(key).consequence_text(off)`). Without a schema, profile changes
  render as a bare option diff. Do not hardcode option meanings.
- **Grounded, non-publishing AI.** `narrator.py` may only restate the facts it is given —
  never invent a glyph/codepoint/option name or meaning. The deterministic facts are always
  attached verbatim in a `<details>` block for verification. The Anthropic call is a plain
  `urllib` POST (no `anthropic` SDK, no third-party deps) with an injectable `transport` so
  prompt assembly and parsing are testable offline. Default model is `claude-sonnet-4-6`
  (override with `--ai-model`). The API key is resolved from this tool's own config dir
  (`~/.config/ufo-tdkit-report/`), never written to the process environment.

## Testing conventions

Tests pair fast unit tests (an injected fake `runner`/`transport`, canned stdout) with
integration tests that build a real temp git repo via `subprocess` + `tmp_path`. When
touching `gitsource.py` or `narrator.py`, prefer the injection seams over real network/git
in unit tests. One test file per module (`tests/test_report_<module>.py`).
