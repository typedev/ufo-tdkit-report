# ufo-tdkit-report

[![CI](https://github.com/typedev/ufo-tdkit-report/actions/workflows/ci.yml/badge.svg)](https://github.com/typedev/ufo-tdkit-report/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ufo-tdkit-report)](https://pypi.org/project/ufo-tdkit-report/)
[![Python](https://img.shields.io/pypi/pyversions/ufo-tdkit-report)](https://pypi.org/project/ufo-tdkit-report/)

**Writes the commit message and the release notes for your font project** — through
Claude, GPT, Gemini, Grok, Mistral, Groq, DeepSeek, Qwen, Kimi, GLM, or a local model.

What makes that trustworthy is what sits underneath. The prose is not written from a
`git diff`; it is written from a **semantic diff of the sources** — outlines compared
coordinate by coordinate, OpenType features at the rule level, kerning and fontinfo
normalized so an editor's re-serialization diffs to nothing. The model may only restate
those facts, a deterministic check afterwards says so if it strayed, and the facts
themselves are attached verbatim to every narration so you can verify it in seconds.

```bash
tdreport                        # a drafted commit message for the working tree
tdreport --notes v2.005..HEAD   # release notes for a range
tdreport --no-ai                # …or just the facts, no model call
```

AI narration is the **default**, and it degrades rather than fails: with no provider
configured — or one that is unreachable — you get the deterministic report and a note on
stderr saying why. Standalone and build-tool-agnostic: it needs **git**, not any
particular font compiler.

## Features

- **Grounded AI narration**, on by default — the deterministic facts become prose, with
  the facts attached verbatim for verification. The model may only restate them; a
  deterministic post-check flags invention, and nothing is ever published. See
  [AI narration](#ai-narration).
- **Commit assistant** — draft a commit message from the working tree, edit it, commit it.
- **Range / release notes** — aggregate a tag/commit range into notes.
- **Semantic source diff** — the ground truth under the prose: outlines (coordinate-based,
  not text), kerning/groups, fontinfo, OpenType features (`feaLib` rule level), designspace
  (axes/masters/instances), and build-profile YAML (option level). `--no-ai` gives you
  exactly this and nothing else.
- **No silent omissions** — every changed tracked file surfaces as a fact (semantic when
  available, else a bare added/removed/modified note). `.gitignore` is honoured.
- **Your choice of AI provider** — Claude, GPT, Gemini, Grok, Mistral, Groq, DeepSeek,
  Qwen, Kimi, GLM, OpenRouter, or a local model (Ollama, LM Studio, vLLM, llama.cpp) via
  any OpenAI-compatible endpoint. See the [table](#providers) for the full list.
- **Per-repo AI accounts** — a corporate repo can use a different provider and key from
  your personal ones, with the key stored once and shared by name, never per repo.
- **Prose in your language** — `tdreport set-lang Spanish` narrates in Spanish while the
  deterministic facts stay English and byte-stable.
- **One settings screen** — `tdreport settings` for all of it; addressing a repo by path
  once is enough, the short name works afterwards. See the
  [settings map](docs/settings.md) for the whole model on one page.

## Install

This is a command-line tool, so install it as a **global CLI**: that puts the `tdreport`
command on your `PATH` (no `sudo`, no virtualenv to activate) while keeping its
dependencies isolated in their own environment.

```bash
uv tool install ufo-tdkit-report        # or: pipx install ufo-tdkit-report
```

Either works; [`uv`](https://docs.astral.sh/uv) is what this project uses for everything
else. `pip install ufo-tdkit-report` also works but puts the dependencies wherever `pip`
is pointing, which for a CLI is rarely what you want.

Then `tdreport` works from any directory:

```bash
uv tool upgrade ufo-tdkit-report     # take the newest release
uv tool uninstall ufo-tdkit-report
```

**From source instead**, to run an unreleased `main` or your own edits:

```bash
uv tool install git+https://github.com/typedev/ufo-tdkit-report.git   # from the git URL
# …or, inside a clone, `uv tool install .` (add --force to replace an existing install)
```

**As a library**, add it the way you add any dependency — a compatible-release bound is
the sensible pin, since the deterministic report is byte-stable within a minor version:

```toml
dependencies = ["ufo-tdkit-report>=0.5,<0.6"]
```

**PyPI history starts at 0.5.2.** Earlier versions exist as git tags and GitHub Releases
but were never uploaded, so an exact pin below that (`==0.5.1`) resolves to nothing from
the index — use the git URL for those, or a range, which lands on a published version
either way.

For hacking on the tool itself, work inside a synced project env instead and run via
`uv run` (no global install needed):

```bash
git clone https://github.com/typedev/ufo-tdkit-report.git
cd ufo-tdkit-report
uv sync --extra dev
uv run tdreport --help
```

Verify a global install landed on your `PATH`:

```bash
tdreport --help
```

## Usage

```bash
# Working-tree commit assistant
tdreport                       # draft a message for the current repo, narrated
tdreport --no-ai               # …the deterministic facts only, no model call
tdreport --ai                  # …require the narrative: fail rather than fall back
tdreport commit                # commit the working tree with the drafted message

# One-time setup for the narration
tdreport set-provider          # pick the provider (Claude, GPT, Gemini, Grok, local…)
tdreport set-key sk-...        # store that provider's API key, owner-only
tdreport set-model             # pick the narration model from a menu
tdreport set-lang Spanish      # optional: narrate in another language
tdreport set-url http://localhost:11434/v1   # only for `custom` or a non-default local host

# Several providers side by side (e.g. a corporate one)
tdreport accounts                    # menu: what exists, and "a" to add one
tdreport bind work ~/fonts/AcmeSans  # that repo uses that account (and its key)

# Named repos — addressing one by path remembers it
tdreport ~/fonts/MyFont        # works, and remembers it as "MyFont"
tdreport MyFont                # …so from now on the short name is enough
tdreport add myfont ~/fonts/X  # or register a name of your choosing
tdreport ls / rm <name> / prune   # list, forget, drop entries whose repo is gone

# Everything in one screen
tdreport settings              # interactive: provider, model, key, language, accounts, repos

# Committed history
tdreport v2.005..v2.006        # endpoint diff of a range (cwd repo)
tdreport --notes v2.005..HEAD  # aggregate every commit in the range into release notes
```

## Editing the drafted commit message

`tdreport <repo>` prints the draft and where it lives; answer `n` at the prompt, edit
that file, then `tdreport <repo> commit` — the edited text is used as-is, and you do not
need to repeat anything.

Two things are guarded:

- Re-running `tdreport <repo>` to look at the report again **keeps your edits** rather
  than overwriting them. Use `--regenerate` when you do want a fresh draft.
- If the working tree changes after you drafted, the message no longer describes what
  would be committed. Committing it is **refused** — on a terminal it asks whether to
  redraft, commit anyway, or abort; in a pipe it errors and names `--stale-ok`. A wrong
  description in git history cannot be fixed without rewriting it.

Staleness is judged on the *facts*, not the bytes: an editor re-serializing a UFO does
not invalidate a draft, because the extracted facts are unchanged.

## Recipes

> A one-page reference for all of the below — the two levels, what wins, and what to do
> when something looks wrong — is in **[docs/settings.md](docs/settings.md)**.

**One repo, the default model.** Address it by path once; it is remembered.

```bash
tdreport set-key sk-ant-...           # once, for everything
tdreport ~/fonts/MyFont               # remembered 'MyFont' -> …
tdreport MyFont                       # from now on, narrated
```

**A second repo on a different model, same key.** Override the model on that repo only —
no second account, so the key is still stored exactly once.

```bash
tdreport ~/fonts/AcmeSans                          # remembered 'AcmeSans'
tdreport repo AcmeSans model claude-haiku-4-5      # this repo only
tdreport repo AcmeSans                             # check what it resolves to
```

**Switch the model of one repo**, or hand it back to the account's model:

```bash
tdreport repo MyFont model claude-sonnet-5
tdreport repo MyFont clear model      # back to whatever the account uses
```

**Change the model everywhere** (the account's model, i.e. every repo without an
override):

```bash
tdreport set-model                    # menu of the provider's models
```

**A repo on a different provider with its own key** — that is what accounts are for:

```bash
tdreport accounts                     # "a" walks through name, provider, key, model
tdreport bind work ~/fonts/ClientFont # and any other repo of that client
```

**One-off, changing nothing:**

```bash
tdreport MyFont --ai-model claude-haiku-4-5 --ai-lang German
```

**Where does this repo's setting come from?** `tdreport settings <repo>` shows every
value with its source and lets you change it at the right level; `tdreport repo <name>`
prints the same resolution non-interactively; `tdreport ls` lists every repo with
its overrides; `tdreport settings` shows and edits all of it.

## AI narration

Narration is **on by default**, and needs an API key ([where it lives](#where-the-key-lives)).

Three things turn it off, and they are not the same thing:

| | what it means | note on stderr |
| --- | --- | --- |
| `--no-ai` | you asked for the facts only | no — nothing to explain |
| `--json` | machine-readable facts; a narrative is not part of `to_dict()` | no |
| nothing configured, or the provider failed | the prose could not be produced | **yes**, saying which |

The fallback is deliberate and it is deliberately loud. A tool whose output silently
depends on whether a key happens to be lying around is exactly the sort of thing this one
exists to eliminate — so the report on **stdout** stays the byte-stable artefact a pipe or
a redirect expects, and the explanation goes to **stderr**. When you would rather fail
than receive the quieter output — CI that publishes the prose, say — `--ai` says so:

```bash
tdreport --notes v2.005..HEAD --ai > notes.md   # non-zero exit; notes.md left empty
                                                # rather than holding a report you did not ask for
```

`--ai-note`, the pre-0.5 way of asking for narration, is still accepted and does nothing,
so existing scripts and hooks keep working. Asking for both at once (`--ai --json`, or
`--ai --no-ai`) is an argument error rather than a silent choice between them.

### Where the key lives

The key comes from one place, the tool's own config directory:

| OS      | path                                                     |
| ------- | -------------------------------------------------------- |
| Linux   | `~/.config/ufo-tdkit-report/` (or `$XDG_CONFIG_HOME/ufo-tdkit-report/`) |
| macOS   | `~/Library/Application Support/ufo-tdkit-report/`         |
| Windows | `%APPDATA%\ufo-tdkit-report\`                             |

Set `TDREPORT_CONFIG_DIR` to put all of it somewhere else (a portable install, a test
harness). That chooses the directory only — the API key still comes from `.env` inside
it, or from an explicit argument, and never from the environment.

Three files and a drafts directory live there, and only the first holds secrets:

| file            | contents                            | permissions |
| --------------- | ----------------------------------- | ----------- |
| `.env`          | API keys, one per account           | `0600` *    |
| `settings.json` | accounts: provider, model, language | —           |
| `repos.json`    | registered repos and their bindings | —           |
| `drafts/`       | commit-message drafts and their fingerprints, deleted once committed | — |

\* `0600` on Linux and macOS, and **checked every time the file is read**, not only set
when it is written: a `cp -r` of your dotfiles, a restored backup or a permissive `umask`
widens it silently, so a readable key file gets one note naming the mode and the `chmod`
that fixes it. Windows has no such mode bit — `chmod` there can only toggle read-only —
so the file is protected by the ACL of the user-profile directory it sits in, which is
already user-only.

Keys never appear in `settings.json` or `repos.json`, and **nothing tdreport-related is
ever written inside your font repository** — not a config file, which would be committed
and shared, and not the drafted commit message either. An earlier version kept that draft
in `<repo>/.tdreport/` and appended a line to your `.gitignore` to hide it; if you still
have that directory, tdreport says so and you can delete both. `settings.json` and
`repos.json` are safe to back up or keep in dotfiles.

The key lives in that one file and nowhere else: the tool deliberately does **not** read
`ANTHROPIC_API_KEY`/`OPENAI_API_KEY` from the environment, nor a `.env` in the repo or
cwd — so a stray export or a project `.env` can't leak in.

```bash
tdreport set-provider           # menu of providers
tdreport set-key sk-...         # that provider's key (also accepts stdin: `… | tdreport set-key`)
tdreport set-model              # menu of that provider's models
tdreport                                    # commit message, AI-drafted
tdreport --notes v2.005..HEAD               # release notes, AI-drafted
```

Running `tdreport set-key` with no argument prompts for the key without echoing it
(so it never lands in your shell history).

### Providers

| provider     | endpoint                                              | key needed |
| ------------ | ----------------------------------------------------- | ---------- |
| `anthropic`  | Claude — the default                                  | yes        |
| `openai`     | GPT (the models behind Codex)                         | yes        |
| `gemini`     | Google Gemini                                         | yes        |
| `xai`        | Grok                                                  | yes        |
| `mistral`    | Mistral AI (incl. Codestral)                          | yes        |
| `groq`       | Groq — open models, fast inference                    | yes        |
| `deepseek`   | DeepSeek                                              | yes        |
| `qwen`       | Qwen via Alibaba DashScope                            | yes        |
| `moonshot`   | Moonshot — Kimi                                       | yes        |
| `zai`        | Z.ai — GLM                                            | yes        |
| `openrouter` | many vendors behind one key                           | yes        |
| `ollama`     | local, `http://localhost:11434/v1`                    | no         |
| `lmstudio`   | local, `http://localhost:1234/v1`                     | no         |
| `custom`     | any OpenAI-compatible server (vLLM, llama.cpp, gateway) | optional |

Use `tdreport set-url <base-url>` for the `custom` provider, a local server on a
non-default host or port, or a vendor's regional endpoint — mainland-China DashScope
and Moonshot, or Z.ai's coding-plan host. `tdreport settings` prints the alternative
alongside the provider that has one.

Everything except Anthropic speaks the OpenAI-compatible `/chat/completions` API — Google
included, through its `/v1beta/openai` compatibility layer — so a provider is a table row,
not an integration, and a local model is just a base URL. No
vendor SDK is used; the call is a plain `urllib` POST, and the tool has no third-party
runtime dependency for this.

**Reasoning models** (DeepSeek's reasoners, and the reasoning modes of others) spend the
completion budget on their private reasoning *before* writing anything, so they need a
much larger cap than the prose alone would suggest — the default is 8192 and
the default is 8192 and it covers the **whole** completion. If one still stops before
answering, the note names the token counts rather than reporting an empty narrative —
and, like any narration failure, you get the deterministic report rather than nothing.
Use `--ai` to make it an error instead.

Raise the cap where it belongs rather than typing a flag every run:

```bash
tdreport set-max-tokens 32000              # this account
tdreport repo Evacode max-tokens 32000     # …or just this repo
tdreport --ai-max-tokens 32000             # …or just this run
```

The built-in default stays conservative on purpose: `max_tokens` goes to every provider,
and some models cap their output well below a number chosen to suit a talkative one.

Local models are worth a caveat: the narrator's grounding depends on the model following
instructions, and a small local model invents more than a large hosted one. The
deterministic facts are attached verbatim to every narration precisely so you can check.

### The settings screen

`tdreport settings <repo>` scopes the screen to one repository. Two settings live on the
**account** (the provider and its key — a key is a key *for* a provider) and four can
live on the **repo** (model, language, grounding strictness, token cap); looking at a repo that split
is invisible, so this screen shows every value **with where it comes from**:

```
Settings — repo 'AcmeSans'
  ~/fonts/AcmeSans

   1. Account    work                   from this repo
      provider   openai                 from account 'work'
      API key    set (…9999)            from account 'work'
   2. Model      gpt-5-mini             from this repo
   3. Language   German                 from account 'work'
   4. Grounding  strict                 from account 'work'
   5. Max tokens 32000                  from this repo
   6. Edit the account itself (affects every repo using it)
   q. Quit
```

For a repo you do not pick a provider — you pick an **account**, and option 1 lists them
with what each one actually brings:

```
Accounts — an account carries the provider AND the key for it:

   1. default          anthropic    key set (…6QAA)
   2. work             openai       key set (…9999)  <- current
```

Options 2 through 5 set overrides for this repo only (an empty answer clears one, handing
the field back to the account). Option 6 jumps into the account's own screen, which
affects every repo using it.

`tdreport settings` with no repo puts all of it on one screen — provider, model, key,
language, base URL, grounding strictness, the token cap, accounts, and the registered
repos with their bindings:

```
Settings — account 'default'

   1. AI provider   deepseek
   2. Model         deepseek-chat
   3. API key       set (…4f2a)
   4. Language      German
   5. Base URL      https://api.deepseek.com/v1
   6. Grounding     warn
   7. Max tokens    32000
   8. Accounts      default, work
   9. Repos         3 registered, 2 bound
   q. Quit
```

It changes nothing on its own: every edit goes through the same functions the `set-*`
commands use, so the two can be mixed freely. Keys are shown masked and never printed.
Without a TTY (a pipe, CI, a hook) it prints the listing and exits instead of blocking —
`tdreport settings --json` gives the same thing as machine-readable JSON.

### Registered repos

Addressing a repo **by path** remembers it under the git root's basename, so this is a
one-time cost:

```bash
tdreport ~/fonts/AcmeSans      # remembered 'AcmeSans' -> …  (next time: `tdreport AcmeSans`)
tdreport AcmeSans              # from now on
tdreport ls                    # what is registered, with bindings; MISSING marks dead paths
tdreport rm AcmeSans           # forget one
tdreport prune                 # drop every entry whose repo is gone
```

It is never silent (it says what it remembered) and never destructive: if the name
already points at a *different* repo, that is reported and nothing is overwritten — use
`tdreport add <other-name> <path>`. The bare `tdreport` in a cwd registers nothing, and
an unknown bare name is still an error rather than a silent guess.

### Accounts

An **account** bundles a provider, model, language and one key under a short name.
Repositories reference an account *by name*, so twenty corporate repos share one key that
is stored exactly once:

`tdreport accounts` is the screen for them — it lists what each account brings (provider,
model, key status) and `a` walks you through adding one, asking for the name, the
provider, the key and the model in turn:

```
AI accounts — an account carries a provider AND the key for it:

   1. default          anthropic   claude-opus-5          key set (…6QAA)  [default]
   2. work             openai      gpt-5                  key set (…9999)

   a. add an account    d. change the default    r. remove one
   a number opens that account's settings;  q. back
```

Then point repos at it:

```bash
tdreport bind work ~/fonts/AcmeSans          # this repo now uses that account
tdreport bind work ~/fonts/AcmeSerif         # …and so does this one, same key
```

Scriptable equivalents, for CI or a dotfiles bootstrap:

```bash
tdreport account add work openai             # name, then provider
tdreport --ai-account work set-key           # stored as TDREPORT_KEY_WORK
tdreport --ai-account work set-model gpt-5
tdreport account use work                    # make it the default for unbound repos
tdreport account rm work                     # removes the account AND its stored key
```

### Choosing the model

`tdreport set-model` sets the model for the **account** — that is, for every repo that
has no override of its own. It shows a numbered menu of the models available to that
account's provider:

```bash
tdreport set-model                  # menu; Enter keeps the current model
tdreport set-model deepseek-chat    # or set one directly (no menu, works in CI)
```

The menu is fetched live from the provider's `/models` endpoint, so it never goes stale;
with no key or no network it falls back to a built-in hint list, and you can always type
a model id that is not listed. The picker says which of the two you are looking at — a
short fallback list otherwise reads as "this provider only has two models" when it really
means nobody could ask yet.

The key prompt does not echo. That is deliberate (a pasted key must not land in a scroll
buffer), but it means a paste shows *nothing at all* — the prompt says so, and confirms
the stored key masked once it lands.

To give **one repo** a different model without a second account (and without storing the
key twice), override it on that repo:

```bash
tdreport repo AcmeSans model claude-haiku-4-5   # this repo only
tdreport repo AcmeSans language German          # same idea for the prose language
tdreport repo AcmeSans clear model              # back to the account's model
tdreport repo AcmeSans                          # what it resolves to, and why
```

### Language

`tdreport set-lang Spanish` (or `--ai-lang Spanish` for one run) makes the AI write its
prose in that language. Only the prose: the deterministic report, the attached facts, the
section headings and the attribution footer stay English, because they are machine output
and localizing them would make the byte-stable report depend on a local preference. The
model is also instructed to keep every identifier verbatim — glyph names, codepoints,
feature tags, paths and option keys are never translated or transliterated.

### How settings are resolved

Every setting resolves in the same order, and this order applies to library callers too,
not just the CLI:

1. an explicit argument — `--ai-model` / `--ai-provider` / `--ai-lang` / `--ai-account`
   (in the library, `narrate(model=..., provider=...)`)
2. the repository's own entry (`tdreport bind`, or a per-repo
   `model`/`language`/`grounding`/`max-tokens`)
3. the account that entry names
4. the default account (`tdreport account use`)
5. the built-in default — provider `anthropic`, model **`claude-opus-5`**, language English

The provider and model that actually ran are named in the attribution line of every
AI-drafted report and commit message, so it is always visible after the fact.

### Grounding check

The narrator may only restate the facts. That used to rest entirely on the model's
obedience plus a human reading the attached `<details>` — fine for a large hosted model,
thin once a local 7B can narrate. So after every narration the prose is compared against
the facts, deterministically and offline:

- codepoints, coordinate deltas and feature tags/alternates the facts do not contain;
- **near-misses** of names they do contain (`guillemotleft` for `guillemetleft`) — what
  invention actually looks like;
- anything the model marked up as an identifier that is not in the facts.

That last one is why the prompt asks the model to backtick every glyph name, codepoint and
tag. `four`, `one`, `section`, `period` and `bullet` are standard glyph names *and*
ordinary English words, so "in one glyph across four masters" is correct prose containing
two of them; no length filter or neighbourhood rule separates that from a glyph claim. The
model declares what it means by marking it up, and the check verifies the declaration
rather than guessing. If a model ignores that instruction, the result says glyph-name
checking was skipped — a skipped check must not look like a clean pass.

By default a finding is a note; a strict account or repo refuses the narration instead —
you get the deterministic report and a note saying the narration was refused, or a
non-zero exit if you also passed `--ai`:

```bash
tdreport set-grounding strict                  # this account
tdreport repo AcmeSans grounding warn          # …but not this repo
tdreport --strict-grounding                    # just this run
```

Strictness is a setting rather than only a flag because it belongs to the *model*: a small
local one earns a refusal, a large hosted one usually needs only the note.

**What it cannot catch:** an invented *meaning* attached to a real identifier ("`uni20C5`,
the Tamil currency sign"). No token comparison reaches that. The facts travel with every
narration precisely so that a human can.

The narrator is strictly grounded — it may only restate the deterministic facts, which
are always attached verbatim in a `<details>` block — and it never publishes anything.

In code, everything unset resolves the same way:

```python
from ufo_tdkit_report import extract_facts, narrate, resolve_ai_settings

report = extract_facts(".", "HEAD~1..HEAD")
print(narrate(report, repo="."))                  # this repo's account, model, language
print(narrate(report, provider="ollama",          # …or pin any of it per call
              model="llama3.2", language="German"))
print(resolve_ai_settings(repo=".").model)        # what a run here would use
```

## Library

The CLI's default — narrate, fall back to the facts — is one call:

```python
from ufo_tdkit_report import describe_changes

print(describe_changes(".", "HEAD~1..HEAD"))              # narrated, or the facts
print(describe_changes(".", "v1..v2", notes=True))        # release notes
print(describe_changes(".", "HEAD~1..HEAD", ai=False))    # never calls out
```

`describe_changes` is the only call here that turns a repository into a report by way of
a model; the extractors stay pure and offline, on purpose: they get embedded in build pipelines, and a fact
extractor spending money on its own initiative is not a reasonable default at that layer.
Compose them deliberately when you want the failure rather than the fallback:

```python
from ufo_tdkit_report import extract_facts, aggregate_range, narrate, resolve_ai_settings

report = extract_facts(".", "HEAD~1..HEAD")
print(report.render_text())                      # deterministic, no network

print(narrate(report))                           # raises NarratorError instead of falling back
print(resolve_ai_settings(repo=".").model)       # what a run here would use
```

Two other public calls reach a provider by their nature and are not part of extraction:
`narrate` / `narrate_commit`, and `list_models`, which queries `/models` to fill a picker
and degrades to a built-in hint list with no key or no network.

Everything unset resolves through the same chain the CLI uses, so an embedding tool
honours the owner's accounts and per-repo bindings without re-implementing the lookup.
A report remembers the repository it came from, and any path *inside* a registered repo
resolves to it, so `narrate(report)` reaches the right provider and key without the
caller restating them. When a repository is named but not registered — meaning its
settings came from the default account — a `UnboundRepoWarning` says so rather than
letting it pass unnoticed.

Three warning categories a public call can raise are exported from the package root
alongside the calls themselves, so production code never has to name an internal module
to catch one: `UnboundRepoWarning` (an unregistered repo fell back to the default account),
`GroundingWarning` (the narration used identifiers the facts do not support) and
`InsecureKeyFileWarning` (the key file is readable by others). They are *defined* in
`settings`, `narrator` and `config` respectively — beside the checks that raise them —
so the root is the address to import from in **production** code.

A *test* reaching past the root is a different thing, and a good one: raising a warning
through its defining module while your production code catches the root-imported name is
how the re-export gets verified from the outside — if one ever became a distinct subclass
rather than the same object, that test fails. `tests/test_report_public_api.py` does
exactly this here, and TDKit's suite does it from the consumer side.

```python
import warnings
from ufo_tdkit_report import GroundingWarning, InsecureKeyFileWarning, UnboundRepoWarning, narrate

with warnings.catch_warnings(record=True) as notes:
    warnings.simplefilter("always", (UnboundRepoWarning, GroundingWarning, InsecureKeyFileWarning))
    prose = narrate(report)                      # route them into your own report…
```

If your code must tolerate an *older* install than it asks for — a stale `uv tool`
install, say, which `uv sync` does not update — read them off the module by name instead.
One combined `from … import A, B, C` fails entirely when one name is missing, and the one
you would silently lose is `GroundingWarning`: the only automatic signal that a narration
invented something.

```python
import ufo_tdkit_report as report_pkg

categories = tuple(
    c for c in (getattr(report_pkg, n, None) for n in
                ("UnboundRepoWarning", "GroundingWarning", "InsecureKeyFileWarning"))
    if c is not None
)
```

`ufo_tdkit_report.settings.UnboundRepoWarning`, `ufo_tdkit_report.narrator.GroundingWarning`
and `ufo_tdkit_report.config.InsecureKeyFileWarning` remain valid names for the same
classes — the root export is an alias, never a second definition.

Build-profile *consequence* semantics (e.g. "ttfautohint off → no TT hinting") are
build-tool-specific: a consumer that owns an option schema injects it via
`fold_facts(..., schema=...)`. Without one, profile changes render as a bare option diff.

## License

Apache-2.0
