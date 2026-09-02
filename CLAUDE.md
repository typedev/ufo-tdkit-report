# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`ufo-tdkit-report` (CLI: `tdreport`) is a deterministic, git-centric source-change
extractor for UFO / designspace font projects. It diffs font **sources** semantically
(formatting-agnostic) and compresses the changes into a few facts, catching outline
redraws and feature-rule changes a binary font diff misses. It shells out to `git` but
depends on no particular font compiler. Optionally it drafts a grounded commit message or
release notes through any of several AI providers — Claude, GPT, Grok, DeepSeek, Qwen,
or a local model — all opt-in.

## Commands

The project uses `uv` (there is a `uv.lock` and `.venv`).

```bash
uv run pytest -q                              # full test suite (~190 tests, ~3s)
uv run pytest tests/test_report_rollup.py     # one test file
uv run pytest -k outline_redraw               # one test by name substring
uv run ruff check .                           # lint (config in pyproject.toml)
uv run ruff check --fix .                     # autofix lint
uv run tdreport ...                           # run the CLI from source
uv run tdreport --version                     # version (also in every report footer)
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
- **`narrator.py`** is the opt-in AI layer: prompts, grounding rules, HTTP plumbing.
  See its constraints below.
- **`providers.py`** is the provider table and the two dialect adapters (`anthropic`
  Messages, OpenAI-compatible `/chat/completions`). Pure — payload/header building and
  response parsing, no I/O. Every provider but Anthropic speaks the OpenAI dialect, so a
  new one is a table row.
- **`settings.py`** owns AI **accounts** and `resolve_ai_settings` — the single
  precedence chain (see below). **`config.py`** holds the config-dir/`.env` primitives
  both `settings` and `registry` need (split out to avoid an import cycle; still
  re-exported from `narrator`).
- **`cli.py`** dispatches: a `target` containing `..` (or `--notes`) → committed-history
  modes; a command word (`settings`, `accounts`, `account`, `repo`, `bind`, `add`, `ls`,
  `rm`, `prune`, `set-*`) → that command; otherwise the working-tree commit assistant
  (`commit.py`). **`settings_ui.py`** is the `tdreport settings` screen — a front-end
  over `settings`/`registry` that holds no state of its own, and prints a listing (or
  `--json`) instead of blocking when there is no TTY. It has two scopes: account-wide
  (`run_settings_menu`) and one repository (`run_repo_menu`, `tdreport settings <repo>`).
  The repo scope exists because provider+key live on the account while model/language can
  live on the repo, and from a repo that split is invisible — so every value is rendered
  **with its source** (`repo_snapshot` computes the provenance) and the lever offered is
  the one that belongs to that level. Keep that: a repo screen that let you set a provider
  directly would silently pair it with another provider's key.
- **`registry.py`** is a `name → {path, ...overrides}` JSON map in the config dir;
  `commit.py` resolves a repo from cwd / registered name / explicit path. An unknown bare
  target is an **error**, never a silent cwd fallback. The legacy flat form
  (`name → path`) is read transparently. Entries are also looked up **by path**
  (`entry_for_path`), matching the nearest registered **ancestor** so any path inside a
  repo resolves to it — `git -C` accepts anything inside a repo, and a literal-path
  lookup let a consumer's subdirectory fall through to the default account with the wrong
  provider and key, silently.
  Addressing a repo by **path** auto-registers it under the git root's basename
  (`cli._auto_register`) — but only an explicit path argument, and never silently: it
  prints what it remembered, and a name already pointing elsewhere is reported rather
  than overwritten. A repo's own `model`/`language`/`provider`/`account` overrides are
  set with `tdreport repo <name> <field> <value>` — that is how two repos get different
  models while sharing one stored key, so reach for it before suggesting a second
  account. TDKit's own registry has the opposite wart (every path ever passed is
  registered forever, resolution never checks the path still exists) — hence `stale()`,
  `prune()` and the `MISSING` marker in `tdreport ls` here.

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
  attached verbatim in a `<details>` block for verification, and this layer never
  publishes anything. That guarantee matters more, not less, now that a small local model
  can be the narrator: grounding rules are shared by both prompts (`_GROUNDING_RULES`), so
  a change to them applies to release notes and commit messages alike. Resolution and key
  storage are pure-ish and unit-tested without network. See also the three bullets below,
  which carry the rules this one used to state alone.
- **One resolution chain, one config directory.** Every AI setting — provider, model,
  language, base URL, key — resolves in `settings.resolve_ai_settings` and nowhere else:
  `explicit argument > repo entry > account > default account > built-in default`. That
  chain must hold for *library* callers too, not just the CLI: `narrate`/`narrate_commit`
  take everything as `... | None = None` and resolve internally — never default a public
  signature to a concrete model/provider, or an embedding tool silently bypasses the
  owner's preference (this was a real bug, fixed in 0.1.2 and generalised since). The
  built-in defaults live once, in `providers.py` (`DEFAULT_PROVIDER`, `DEFAULT_MODEL`,
  `DEFAULT_LANGUAGE`) — never re-spell a model id as a literal in `cli.py`/`commit.py`
  (it was duplicated in four places once). The CLI passes flags down **unresolved**, so a
  repo's own binding still applies. Reports also carry their own `repo`, and
  `narrate(report)` falls back to it, so a consumer cannot forget which repository a
  report belongs to. That field must stay out of `to_dict()` and every renderer — it is a
  machine-local path, and byte-stable output must not depend on where the repo lives.
  When a named repo matches no registry entry, `AiSettings.repo_bound` is False and
  `warn_if_unbound` raises `UnboundRepoWarning` (only with 2+ accounts, where the binding
  could have mattered); silence there hides narrating on the wrong provider and key.
- **Secrets have exactly one home.** API keys live only in `<config>/.env`, `0600`, one
  variable per account (`TDREPORT_KEY_<ACCOUNT>`); `<config>/settings.json` and
  `<config>/repos.json` hold provider/model/language/bindings and **never** a secret.
  Writes go through `config.write_dotenv_var`, which preserves every other line — never
  rewrite that file wholesale (one account's key must not drop another's). Nothing
  tdreport-related is written **inside the font repository**: a config file there would
  be committed and shared, which is how keys leak. The key is not read from the process
  environment, a repo `.env`, or the cwd — don't reintroduce those fallbacks. Removing an
  account removes its key; anything user-facing shows a masked key, never the value.
- **Providers are a table, not integrations.** `providers.py` speaks two dialects and
  nothing else; a new vendor is a row. No vendor SDK, no third-party runtime dep — plain
  `urllib` with an injected `transport` so prompt assembly and parsing are testable
  offline. `list_models()` feeds the pickers from the provider's live `/models` and
  degrades to its hint list with no key/network, so picking a model works offline. Those
  hint lists are *hints*: the live list is authoritative and a raw id is always accepted.
  `DEFAULT_MAX_TOKENS` covers the **whole** completion, reasoning included — a reasoning
  model can spend the entire cap thinking and return no text, which off the wire is
  indistinguishable from having nothing to say. Hence 8192 rather than a prose-sized cap,
  and `_truncation_error`, which reports the token counts instead of "empty narrative".
  Don't shrink that default back.
- **Localization stops at the prose.** `--ai-lang` / `set-lang` changes only the AI
  narrative. The deterministic report, the attached facts, section headings and the
  attribution footer stay English — localizing them would make byte-stable output depend
  on a local preference. The language rule also instructs the model to keep every
  identifier verbatim; a model writing in German will otherwise "translate" a glyph name,
  which is exactly the ungrounded invention the narrator exists to prevent.

## Versioning & releases

`pyproject.toml` `version` is the **single source of truth**; `__init__.__version__` reads
it back from installed package metadata (`0.0.0+unknown` in an uninstalled source tree),
`render.py` stamps it into every report footer and commit trailer, and `tdreport --version`
prints it. SemVer, tag `v<version>`. The version is deliberately *static*, not derived from
git (setuptools-scm/hatch-vcs style): a dirty-tree or dev version string would leak into
report output and break byte-stability.

`tests/test_report_version.py` fails if `pyproject.toml` and the newest released CHANGELOG
section disagree, so the two cannot drift.

To cut a release:

```bash
# 1. move the accumulated `## [Unreleased]` entries into `## [X.Y.Z] - <today>` and
#    leave `## [Unreleased]` in place with `_Nothing yet._`; add the compare links
# 2. bump `version` in pyproject.toml
uv lock                                   # uv.lock records the project version too
uv run --extra dev pytest -q && uv run ruff check .
git commit -am "chore(release): X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main --follow-tags
```

## Testing conventions

Tests pair fast unit tests (an injected fake `runner`/`transport`, canned stdout) with
integration tests that build a real temp git repo via `subprocess` + `tmp_path`. When
touching `gitsource.py` or `narrator.py`, prefer the injection seams over real network/git
in unit tests. One test file per module (`tests/test_report_<module>.py`).

The interactive screens (`settings_ui.py`) are tested the same way: `monkeypatch` on
`builtins.input` with a fixed script that raises `EOFError` when exhausted, so a menu that
fails to terminate fails the test rather than hanging. `_read_secret` bypasses `input()`
(it uses `getpass`, or `sys.stdin.readline()` off a TTY), so a key prompt is driven by
patching `sys.stdin.readline` — see `_secret()` in `tests/test_report_settings_ui.py`.
Note that `list_models` binds its `transport` as a *default argument*, so patching
`narrator._http_get` after import has no effect; patch `narrator.list_models` instead.
