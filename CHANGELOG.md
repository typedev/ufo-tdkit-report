# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version in
`pyproject.toml` is the single source of truth; each release is tagged `v<version>`.

## [Unreleased]

### Added
- **Five more AI providers: `gemini`, `mistral`, `groq`, `moonshot` (Kimi) and `zai`
  (GLM).** Google's Gemini reaches the narrator through its OpenAI-compatibility layer
  at `/v1beta/openai`, so it is a table row like the rest — no new dialect, no vendor
  SDK, still no third-party runtime dependency. Each row carries the vendor's regional
  or coding-plan endpoint as a note where one exists (Moonshot's `.cn` host, Z.ai's
  coding-plan host), reachable with `tdreport set-url`.

### Changed
- `--ai-provider --help` now spells its provider list from the table instead of a
  hand-written string, which had already gone stale once.

## [0.4.1] - 2026-09-03

### Fixed
- **Redirected output no longer dies on Windows.** Printing to a real Windows console is
  fine — Python writes it as UTF-16 through `WriteConsoleW` whatever the code page is.
  Redirect it and the stream falls back to `locale.getpreferredencoding()`, the ANSI code
  page, where the `→` in a rendered report raises `UnicodeEncodeError`. Since
  `tdreport v1..v2 > notes.md` is how release notes are captured, that is the normal
  path. The CLI now reconfigures its own streams to UTF-8, skipping streams that are
  already UTF-8 or cannot be reconfigured. (Python 3.15 makes UTF-8 mode the default and
  this becomes a no-op; the floor here is 3.10.)
- **A repo path with non-ASCII characters no longer comes back mojibake on Windows.**
  `commit.py` ran git with `text=True` and no encoding, so output was decoded with the
  locale encoding — and `rev-parse --show-toplevel` goes through it. It now decodes
  UTF-8 explicitly, as `gitsource.py` already did.

### Changed
- Documentation no longer claims `0600` unconditionally for the key file. That is true on
  Linux and macOS; Windows has no such mode bit — `chmod` there only toggles read-only —
  and the file is protected by the ACL of the user-profile directory instead. The code
  said as much already; the user-facing docs did not.
- CI runs on **Windows** as well as Linux and macOS. `config_dir()` branches per OS and
  the Windows branch had never executed anywhere — the macOS branch had the same status
  until yesterday, and it turned out to be broken.

## [0.4.0] - 2026-09-03

### Added
- **`TDREPORT_CONFIG_DIR`** relocates the whole config directory on any platform — a
  portable install, a test harness, a second profile. It chooses the *directory*; the API
  key still comes only from `.env` inside it or from an explicit argument, never from the
  environment.
- **CI** — `pytest` and `ruff` on every push and pull request, across Python 3.10 (the
  floor from `requires-python`) and 3.13, on Linux **and macOS**. macOS is not padding:
  `config_dir()` branches per platform and font work is heavily macOS, so a Linux-only
  matrix would never exercise half of that path.

### Fixed
- **The test suite could overwrite a real config on macOS.** Isolation worked by
  redirecting `XDG_CONFIG_HOME`, which `config_dir()` ignores on macOS — so on a Mac the
  suite ran against the developer's actual `~/Library/Application Support/…` and, since
  it exercises `store_api_key`, could clobber their stored API key. `config_dir()` now
  honours `TDREPORT_CONFIG_DIR` on every platform, and an autouse fixture in
  `conftest.py` points every test at its own directory, so a new test file cannot forget.
  This does not weaken the key's two sources: it chooses *which directory* `.env` lives
  in, the way `GIT_CONFIG_GLOBAL` moves git's config. **CI on macOS found this on its
  first green-on-Linux run** — a Linux-only matrix never would have.
- Test repositories now configure their own git identity. Several suites relied on the
  developer's global `user.name`/`user.email`; on a runner without one, 18 tests failed.

### Changed
- Module and test docstrings no longer carry `(issue #5, phase N)` breadcrumbs pointing
  at a tracker outside this repository, and `profile.py` describes "a build-profile YAML"
  rather than naming one build tool — the module is deliberately build-tool-agnostic, so
  naming a vendor in its own docstring contradicted the invariant it implements.

## [0.3.2] - 2026-09-03

### Fixed
- **An edited draft is no longer silently overwritten.** Re-running `tdreport <repo>` to
  read the report again used to rewrite the draft, discarding whatever the owner had
  written into it — and, for an `--ai-note` draft, throwing away a paid model call with
  it. The draft is now kept and shown, with a note; `--regenerate` replaces it on
  request.
- **A stale draft can no longer put a wrong description into git history.** `commit`
  stages the tree as it is *now* and commits it with text drafted *then*; if files
  changed in between, the message described a different change. That is the one failure
  this tool exists to prevent, and it was silent. The draft now records a fingerprint of
  the facts it describes, and committing a stale one is refused — on a TTY with a
  `[r]edraft / [c]ommit anyway / [a]bort` question, in a pipe with an error and
  `--stale-ok` named as the way out.

  Staleness is measured against the **facts**, not the files: an editor re-serializing a
  UFO changes bytes while producing identical facts, and must not invalidate a draft.
  The fingerprint is a digest of the deterministic report, reusing the byte-stability
  guarantee the project already provides.
- The draft directory is keyed by path digest rather than by the registered name, so
  **registering a repo no longer orphans a draft** written before it was registered.

### Added
- `commit.draft_state(repo)` reports whether a draft `exists`, was `edited`, has gone
  `stale`, and whether it was `ai`-written; `commit.state_path(repo)` locates its sidecar.
  `commit(..., allow_stale=True)` and `inspect(..., regenerate=True)` are the library
  equivalents of `--stale-ok` and `--regenerate`.

## [0.3.1] - 2026-09-03

### Changed
- **The drafted commit message moved out of the font repository.** It used to be written
  to `<repo>/.tdreport/commit-message.md`, which required appending a line to the
  repository's own `.gitignore` — a silent edit to a tracked file in someone else's
  project, made to hide a problem the tool itself had created. Nothing tdreport-related
  is written inside a repository any more, the same rule accounts and bindings already
  follow. `_ensure_gitignored` is gone.

  The draft now lives at `<config>/drafts/<repo>/commit-message.md`, keyed by the
  registered name (or the basename plus a digest of the path, so two repos called `Sans`
  never share one). Not a temp directory: an hour can pass between drafting and
  committing, `/tmp` is cleared on reboot, and re-generating a deterministic draft is free
  while an `--ai-note` draft cost a paid model call.

  A leftover `<repo>/.tdreport/` from an older version is **reported, not deleted** — it
  is the owner's repository, and the `.gitignore` line an older version added is theirs
  to remove.

  `commit.REPORT_RELPATH` is gone (the draft is no longer at a path relative to the
  repo); `commit.report_path(repo)` still returns the draft's location and is the
  supported way to find it. `commit.legacy_draft_dir(repo)` reports a leftover one.

## [0.3.0] - 2026-09-02

### Added
- **A deterministic grounding check.** After a narration, the tokens in the prose are
  compared against the facts the model was given — offline, no second model call. It
  reports codepoints, measurements, feature tags and alternates that the facts do not
  contain, and **near-misses** of names that they do (`guillemotleft` for
  `guillemetleft`), which is what invention actually looks like. The narrator's guarantee
  used to rest entirely on the model's obedience plus a human reading the `<details>`
  block; that was fine for a large hosted model and thin once a local 7B can narrate.
- **Identifiers are now marked up, and the markup is what gets checked.** The prompt asks
  the model to backtick every glyph name, codepoint, tag, master name and path. This is
  not cosmetic: `four`, `one`, `section`, `period` and `bullet` are standard glyph names
  *and* ordinary English words, so "in one glyph across four masters" is correct prose
  containing two of them. No length filter or neighbourhood heuristic separates those
  cases — a rule keyed on "a glyph name next to another glyph name" flags the `one` in
  that very sentence. The model declares what it means by marking it up, and the check
  verifies the declaration instead of guessing at intent.
- **A skipped check is reported, not passed over.** When the facts contain identifiers
  and the narrative marks up none, the result says glyph-name checking was skipped for
  that narration — a weak model ignoring the instruction must not look like a clean pass.
- **`strict_grounding`, resolved like every other setting.** Warning is the default; a
  strict account or repo refuses the narration instead. It is a setting rather than only
  a flag because it belongs to the *model* — a small local one earns a refusal, a large
  hosted one usually needs only the note. Set it with `tdreport set-grounding
  strict|warn`, per repo with `tdreport repo <name> grounding strict|warn`, per run with
  `--strict-grounding` / `--no-strict-grounding`; it appears in both settings screens.
- Release notes carry the findings in a caution block above the `<details>` facts. A
  **commit message never does** — `git commit -F` does not strip comments, so a note
  appended there would land in history; it is raised as a `GroundingWarning` instead,
  which the CLI shows as a `note:` line before the "Commit this?" prompt.

_What it cannot catch:_ an invented **meaning** attached to a real identifier ("uni20C5,
the Tamil currency sign"). No token comparison reaches that, and the attached facts remain
the answer. The check narrows the gap; it does not close it.

## [0.2.1] - 2026-09-02

### Fixed
- **A path *inside* a registered repo now finds it.** `entry_for_path` matched paths
  literally, so a consumer that handed over a subdirectory — which `git -C` accepts
  happily — fell through to the default account and narrated with the wrong provider and
  key, silently. It now matches the nearest registered ancestor, deepest first, so a repo
  nested inside another still resolves to itself.

### Added
- **Reports carry the repository they came from.** `extract_facts`,
  `extract_working_facts` and `aggregate_range` record it, and `narrate(report)` uses it
  when no `repo=` is passed — so an embedding tool can no longer forget to say which
  repository a report belongs to and quietly get the default account's provider and key.
  The field is deliberately absent from `to_dict()` and from every renderer: it is a
  machine-local path, and letting it reach the output would break byte-stability.
- **An unregistered repo is announced, not passed over in silence.**
  `AiSettings.repo_bound` says whether a named repo matched a registry entry, and
  `narrate`/`narrate_commit` raise `UnboundRepoWarning` when it did not — but only when
  more than one account exists, since with a single account the binding could not have
  changed anything. The CLI renders it as one readable `note:` line rather than a Python
  warning traceback.

## [0.2.0] - 2026-09-02

### Added
- **Multiple AI providers.** `--ai-note` is no longer Anthropic-only: Claude, OpenAI
  (the models behind Codex), xAI Grok, DeepSeek, Qwen (DashScope), OpenRouter, and local
  models via Ollama, LM Studio or any OpenAI-compatible server (vLLM, llama.cpp, a
  gateway). New `providers.py` holds a table of endpoints and exactly **two** dialect
  adapters — Anthropic Messages and OpenAI `/chat/completions` — because every provider
  but Anthropic speaks the latter. Adding one is a table row, not an integration. Still
  no vendor SDK and no third-party runtime dependency: a plain `urllib` POST with an
  injected transport. Pick one with `tdreport set-provider` or `--ai-provider`.
- **AI accounts.** An account bundles provider + model + language + one key under a short
  name; repositories reference it *by name* (`tdreport bind <account> [<repo>]`), so many
  corporate repos share a key that is stored exactly once. `tdreport accounts`,
  `tdreport account add|rm|use <name>`, and `--ai-account` for a single run. Removing an
  account also removes its stored key. Keys live only in `<config>/.env` (`0600`), one
  variable per account; the new `<config>/settings.json` and the registry hold no
  secrets, and nothing tdreport-related is ever written inside the font repository.
- **Narration language.** `tdreport set-lang <language>` / `--ai-lang` makes the AI write
  its prose in another language. Only the prose: the deterministic report, the attached
  facts, headings and footer stay English, so byte-stable output never depends on a local
  preference. The model is instructed to keep every identifier — glyph names, codepoints,
  feature tags, paths, option keys — verbatim rather than translating it.
- **Per-repo overrides.** A registry entry can carry `account`, `provider`, `model` and
  `language` beside its path, matched by repo *path* so the plain `tdreport` in a cwd
  picks its own settings up.
- `tdreport accounts` shows every account's provider, model, language and key status —
  keys always masked, never printed.
- **`tdreport settings`** — one interactive screen for provider, model, key, language,
  base URL, accounts and registered repos (with binding, unbinding and pruning). It is a
  front-end only: every edit goes through the same functions the `set-*` commands use, so
  the two can be mixed. Keys are shown masked, never printed. Without a TTY it prints the
  listing and exits rather than blocking on input a pipe can never supply;
  `tdreport settings --json` emits the same state as JSON.
- **`tdreport settings <repo>`** — the settings screen scoped to one repository. Two
  settings live on the account (provider and key, which belong together) and two can live
  on the repo (model, language); from a repo that split is invisible, so this screen shows
  every value **with its source** ("from this repo" / "from account 'work'" / "from
  built-in default") and offers the right lever for each: an account picker that lists
  what each account brings (provider + key status), and per-repo overrides that an empty
  answer clears. It warns when a repo has no key on its account, and when switching
  account leaves a repo-pinned model belonging to a different provider. Non-interactively
  it prints the same resolution, `--json` included; a path argument registers the repo
  like every other path target.
- **`tdreport accounts` is a screen, not a listing.** It shows what each account brings
  (provider, model, key status, which is the default) and offers `a` to add one, `d` to
  change the default, `r` to remove one, or a number to open that account's settings.
  Adding walks through the parts one labelled question at a time — name, provider, key,
  model, language — because `account add work openai` is four bare words in a row with
  nothing to say which one you invent and which one is a provider. `tdreport account add`
  on a TTY runs the same flow. Off a TTY both keep the old non-interactive behaviour, so
  scripts and CI are unaffected.
- Every model picker now says **which list it is showing**: the models the key can reach,
  or the built-in fallback with the reason (no key yet, or the endpoint was unreachable).
  A fallback list is indistinguishable from a real one, so a two-entry list read as "this
  provider only has two models" when it meant "nobody could ask".
- The API-key prompt states that **input is hidden** before you type, and confirms the
  stored key masked afterwards. A pasted key shows nothing at all, which reads as the
  terminal ignoring the paste — you press Enter, no key is stored, and the model picker
  quietly falls back to the offline list.
- **Repos are remembered when addressed by path.** `tdreport ~/fonts/AcmeSans` registers
  it under the git root's basename and says so, so `tdreport AcmeSans` works from then
  on. Never silent, never destructive: a name already pointing at a different repo is
  reported and not overwritten. The bare cwd mode registers nothing, and an unknown bare
  name is still an error rather than a silent guess.
- **`tdreport repo <name> [<field> <value>]`** — per-repo overrides without a second
  account: `model`, `language`, `provider`, `account`, and `clear` to hand a field back.
  This is what gives two repos different models while sharing one stored key. With no
  field it prints what that repo resolves to and why (overrides, account, provider,
  model, language, key status). The same is editable from the `settings` repos screen,
  and `tdreport ls` now shows each repo's overrides.
- `tdreport ls`, `tdreport rm <name>`, `tdreport prune` — list registered repos (dead
  paths marked `MISSING`), forget one, or drop every entry whose repo is gone.
- `tdreport set-url <base-url>` points an account at a custom OpenAI-compatible endpoint
  (a local server on a non-default host, vLLM, llama.cpp, a gateway, the mainland-China
  DashScope endpoint).
- `registry.stale()` / `registry.prune()` report and drop entries whose repo is gone.

### Fixed
- **Reasoning models produced an empty narrative.** The completion cap covers a model's
  private reasoning as well as its answer, and DeepSeek's reasoners spent the whole
  2048-token default on thinking — `finish_reason: length`, `reasoning_tokens: 2048`,
  no visible text — which surfaced as the unhelpful `empty narrative from model`. The
  default cap is now **8192** (a cap is not a charge: nothing is paid for tokens that are
  not generated), a truncated answer with no text is now reported with the token counts
  and the way out, and `--ai-max-tokens` overrides the cap per run.

### Changed
- **The registry format is now an object per entry** (`{"name": {"path": ...}}`) so a
  repository can carry its bindings beside its path. The old flat form
  (`{"name": "/path"}`) is read transparently and rewritten on the next write — no user
  action needed. Name lookup is now case-insensitive.
- **One resolution chain for every AI setting**, in `settings.resolve_ai_settings`:
  explicit argument > repo entry > account > default account > built-in default. It
  applies to library callers, not just the CLI — generalising the 0.1.2 fix from the
  model to the provider, language, base URL and key.
- `narrate()` / `narrate_commit()` now resolve the API key too when none is passed,
  instead of refusing; an explicitly passed key still wins. They also accept `repo=`,
  `provider=`, `language=` and `account=`.
- The attribution footer names the provider alongside the model
  (`model: deepseek/deepseek-chat`): with several providers reachable, a model id alone
  no longer identifies what produced the prose.
- `tdreport set-key` and `set-model` now write to the selected account rather than to
  global variables. A pre-accounts config (`ANTHROPIC_API_KEY` and `TDREPORT_AI_MODEL` in
  `<config>/.env`) keeps working unchanged as the `default` account.
- Local providers get a longer default timeout (300 s): a local server loads the model on
  the first request.
- Config-directory and `.env` primitives moved to a new `config.py` so `registry` and
  `settings` can share them without an import cycle. They remain importable from
  `narrator` for compatibility.

## [0.1.2] - 2026-09-01

### Fixed
- `narrate()` and `narrate_commit()` now resolve the narration model themselves when the
  caller passes none (`model=None` → `resolve_model()`), instead of freezing
  `DEFAULT_MODEL` into the signature. A library consumer that did not pass a model
  silently got the built-in default and never saw the owner's `tdreport set-model`
  preference — the resolution order `explicit > TDREPORT_AI_MODEL in <config>/.env >
  DEFAULT_MODEL` lived only in the CLI. It now holds for every caller. Backwards
  compatible: passing a model explicitly is unchanged.

## [0.1.1] - 2026-08-24

### Added
- `tdreport --version`. The version is stamped into report footers and commit trailers,
  so it needs to be queryable without reading a report.
- `tdreport set-model` picks the `--ai-note` model from a **numbered menu of available
  models**, and stores it beside the key in `<config>/.env` (`TDREPORT_AI_MODEL`). The menu
  is fetched live from the Anthropic Models API so it cannot go stale, falls back to a
  built-in list with no key or no network, and accepts a typed model id that is not listed.
  `tdreport set-model <id>` sets one directly (no TTY needed, for CI). Exposed in the
  library as `list_models()` / `store_model()` / `resolve_model()`.
- `tdreport set-key <KEY>` stores the Anthropic API key in the single supported
  on-disk home (`<config>/.env`) with owner-only permissions (`0600`); with no argument
  it prompts without echoing (or reads stdin), so the key never lands in shell history.
  Exposed in the library as `store_api_key()`.
- `extract_facts` / `extract_working_facts` / `aggregate_range` accept an optional
  `schema=` to inject build-profile consequence knowledge (the seam a build tool uses).

### Fixed
- **Reasoning models produced an empty narrative.** The completion cap covers a model's
  private reasoning as well as its answer, and DeepSeek's reasoners spent the whole
  2048-token default on thinking — `finish_reason: length`, `reasoning_tokens: 2048`,
  no visible text — which surfaced as the unhelpful `empty narrative from model`. The
  default cap is now **8192** (a cap is not a charge: nothing is paid for tokens that are
  not generated), a truncated answer with no text is now reported with the token counts
  and the way out, and `--ai-max-tokens` overrides the cap per run.

### Changed
- **Default AI model is now `claude-opus-5`** (was `claude-sonnet-4-6`), and the id is no
  longer duplicated: `narrator.DEFAULT_MODEL` is the single source of truth, where the
  literal had been copied into `cli.py` and twice into `commit.py` — so changing the
  constant left three code paths on the old model. Model selection now resolves as
  `--ai-model` > the `tdreport set-model` preference > `DEFAULT_MODEL`; as with the API
  key, the process environment is never consulted.
- `<config>/.env` is written by merge (`_write_dotenv_var`) instead of wholesale, so
  storing the model no longer clobbers the key (or vice versa) and hand-written lines in
  that file survive. It stays owner-only (0600).
- **AI API key resolution narrowed to two sources** (was six): an explicit argument and
  `<config>/.env` only. The process environment (`ANTHROPIC_API_KEY`), a repo `.env`, a
  cwd `.env`, and the plain `<config>/anthropic_key` file are no longer consulted — so the
  secret lives in exactly one owner-only file and cannot leak in from a stray export or a
  project `.env`. `resolve_api_key()` lost its `repo` parameter (now keyword-only
  `explicit=`); `tdreport set-key` is the supported way to populate the key.
- No changed tracked file is silently dropped: any non-source file (or a known
  source file that produced no semantic delta, or a whole-file add/remove) now
  surfaces as a bare constatation under an **Other files** section
  (`added`/`removed`/`modified`), folded into one line. `.gitignore` is still honoured.
- Default AI model for `--ai-note` is now `claude-sonnet-4-6` (was `claude-opus-4-8`);
  override per-run with `--ai-model`.
- The attribution credit now also appears on commit messages (`tdreport <repo>` /
  `... commit`) as a plain trailer line (`Generated by tdreport <version>`, plus the AI
  model with `--ai-note`) — not markdown, so it sits cleanly in the git commit.

### Fixed
- `resolve_repo`: a bare target that is neither a registered name nor an existing path
  now raises a clear error instead of silently falling back to the cwd repo (which made
  `tdreport <unknown-name>` report "no changes" against the wrong project).

## [0.1.0] - 2026-06-23

### Added
- Initial standalone release, extracted from TDKit's `tdkit.report`.
- Semantic source-change diff: outlines (coordinate-based), kerning/groups, fontinfo,
  OpenType features (`feaLib` rule level), designspace, and build-profile YAML.
- Working-tree commit assistant (`tdreport`, `tdreport <repo>`, `tdreport ... commit`).
- Range / release-notes aggregation (`tdreport <range>`, `tdreport --notes`).
- Repo name registry (`tdreport add <name> <path>`) — explicit registration; cwd and
  explicit paths work without it.
- Opt-in grounded AI narration (`--ai-note`, `ANTHROPIC_API_KEY`), facts attached for
  verification.
- Attribution footer on reports: `Generated by tdreport <version>` (version read from
  package metadata); with `--ai-note` it reads `... with AI narration, model: <model>`.
  Commit messages stay footer-free. `__version__` is exported from the package.

### Fixed
- **Reasoning models produced an empty narrative.** The completion cap covers a model's
  private reasoning as well as its answer, and DeepSeek's reasoners spent the whole
  2048-token default on thinking — `finish_reason: length`, `reasoning_tokens: 2048`,
  no visible text — which surfaced as the unhelpful `empty narrative from model`. The
  default cap is now **8192** (a cap is not a charge: nothing is paid for tokens that are
  not generated), a truncated answer with no text is now reported with the token counts
  and the way out, and `--ai-max-tokens` overrides the cap per run.

### Changed (vs. the in-TDKit version)
- Repo-centric instead of profile-centric: addressed by cwd / registered name / path,
  not by a build-profile name.
- Build-tool-agnostic: no dependency on a profile database or an option schema. The
  profile-option *consequence* schema is injected by the consumer (`fold_facts(schema=)`)
  rather than self-loaded.
- AI key / config resolved from this tool's own config dir (`~/.config/ufo-tdkit-report/`).

[Unreleased]: https://github.com/typedev/ufo-tdkit-report/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/typedev/ufo-tdkit-report/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/typedev/ufo-tdkit-report/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/typedev/ufo-tdkit-report/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/typedev/ufo-tdkit-report/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/typedev/ufo-tdkit-report/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/typedev/ufo-tdkit-report/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/typedev/ufo-tdkit-report/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/typedev/ufo-tdkit-report/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/typedev/ufo-tdkit-report/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/typedev/ufo-tdkit-report/releases/tag/v0.1.0
