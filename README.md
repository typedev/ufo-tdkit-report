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
  prose, attaching the facts verbatim for verification. Needs an Anthropic API key
  (see [AI narration](#ai-narration-opt-in)).

## Install

This is a command-line tool, so install it as a **global CLI** with
[`uv`](https://docs.astral.sh/uv): that puts the `tdreport` command on your `PATH`
(no `sudo`, no virtualenv to activate) while keeping its dependencies isolated in their
own environment. It is not on PyPI yet, so install straight from the source — a git URL
or a local checkout:

```bash
uv tool install git+https://github.com/typedev/ufo-tdkit-report.git
# or, from a local checkout of this repo:
uv tool install .
```

Then `tdreport` works from any directory. Update or remove it later with:

```bash
uv tool upgrade ufo-tdkit-report     # reinstall from the same source
uv tool uninstall ufo-tdkit-report
```

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

## AI narration (opt-in)

AI narration is **off** unless you pass `--ai-note`. When you do, the tool needs an
Anthropic API key, which it reads from a **single place**: its own config file,

| OS      | path                                                     |
| ------- | -------------------------------------------------------- |
| Linux   | `~/.config/ufo-tdkit-report/.env` (or `$XDG_CONFIG_HOME/ufo-tdkit-report/.env`) |
| macOS   | `~/Library/Application Support/ufo-tdkit-report/.env`    |
| Windows | `%APPDATA%\ufo-tdkit-report\.env`                        |

Set it once with `set-key` — the file is created with owner-only permissions (`0600`):

```bash
tdreport set-key sk-ant-...     # store the key (also accepts it on stdin: `… | tdreport set-key`)
```

Running `tdreport set-key` with no argument prompts for the key without echoing it
(so it never lands in your shell history). The key lives in that one file and nowhere
else: the tool deliberately does **not** read `ANTHROPIC_API_KEY` from the environment,
nor a `.env` in the repo or cwd — so a stray export or a project `.env` can't leak in.

Then narrate:

```bash
tdreport --ai-note                          # commit message, AI-drafted
tdreport --notes v2.005..HEAD --ai-note     # release notes, AI-drafted
tdreport --ai-note --ai-model claude-opus-4-8   # pick the model (default: claude-sonnet-4-6)
```

The narrator is strictly grounded — it may only restate the deterministic facts, which
are always attached verbatim in a `<details>` block — and it never publishes anything.

In code, pass the key explicitly (the only other accepted source) or store it once:

```python
from ufo_tdkit_report import extract_facts, narrate, resolve_api_key, store_api_key

store_api_key("sk-ant-...")                 # write it to <config>/.env, 0600 (one-time)
report = extract_facts(".", "HEAD~1..HEAD")
print(narrate(report, model="claude-opus-4-8", api_key=resolve_api_key()))
print(narrate(report, api_key="sk-ant-..."))   # …or supply it explicitly per call
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
