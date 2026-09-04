# Settings map

Settings live on **two levels**. Everything else follows from that, and once you know
which level owns what, there is nothing left to remember.

| | **Account** | **Repository** |
| --- | --- | --- |
| owns | provider, **API key**, default model, default language, base URL, grounding strictness, token cap | which account to use, and a model / language / grounding / token-cap override for this repo only |
| how many | one (`default`) or several — personal, corporate, local | one entry per registered repo |
| has a key | yes, exactly one | never |

The provider and the key are inseparable: a key is a key *for* a provider. That is why
they live together on the account, and why a repo can never carry one.

```
repositories                accounts
MyFont       ──────────▶    default    anthropic · key ●
AcmeSans     ──────────▶    default    (same account, its own model)
ClientFont   ──────────▶    work       openai · key ●
```

Twenty client repositories can point at one account, so its key is stored exactly once.

## What wins

Resolution order, top down — the first thing found wins. This one chain applies to
library callers too, not just the CLI.

1. **A flag on the run** — `--ai-model`, `--ai-lang`, `--ai-provider`, `--ai-account`,
   `--ai-max-tokens`, `--strict-grounding` / `--no-strict-grounding` (in the library,
   `narrate(model=…)`)

Narration itself is **on by default**; `--no-ai` turns it off for one run, `--ai` refuses
to fall back to the deterministic report when it cannot be produced.
2. **The repo's own override** — `tdreport repo <name> …`
3. **The account that repo is bound to** — `tdreport bind`
4. **The default account** — `tdreport account use <name>`
5. **The built-in default** — provider `anthropic`, model `claude-opus-5`, language English

## Task → command

### First-time setup

| Task | Command | Level |
| --- | --- | --- |
| Store the key | `tdreport set-key sk-ant-…` | account |
| Register a repo | `tdreport ~/fonts/MyFont` — remembered as `MyFont`; the short name works from then on | repo |

### Change it for every repo

| Task | Command | Level |
| --- | --- | --- |
| Provider | `tdreport set-provider` | account |
| Model | `tdreport set-model` | account |
| Prose language | `tdreport set-lang Spanish` | account |
| Endpoint (local model, custom server) | `tdreport set-url http://localhost:11434/v1` | account |
| Refuse a narration the facts do not support | `tdreport set-grounding strict` | account |
| Give a reasoning model room to think | `tdreport set-max-tokens 32000` | account |

### Change it for one repo

| Task | Command | Level |
| --- | --- | --- |
| A different model on the same key | `tdreport repo MyFont model claude-haiku-4-5` | repo |
| A different language | `tdreport repo MyFont language German` | repo |
| Hand a field back to the account | `tdreport repo MyFont clear model` (or `clear` for all) | repo |
| Strict or lenient grounding | `tdreport repo MyFont grounding strict` | repo |
| A larger completion cap | `tdreport repo MyFont max-tokens 32000` | repo |

### A different key or provider for some repos

| Task | Command | Level |
| --- | --- | --- |
| Add a second account | `tdreport accounts` → `a`, then follow the steps | account |
| Point a repo at it | `tdreport bind work ~/fonts/ClientFont` | repo |
| Make it the default | `tdreport account use work` | account |

### Once, without saving anything

```bash
tdreport MyFont --ai-model claude-haiku-4-5 --ai-lang German
```

## The accounts screen

`tdreport accounts` is a screen, not a listing. It shows what each account brings —
provider, model, whether a key is stored:

```
AI accounts — an account carries a provider AND the key for it:

   1. default          anthropic   claude-opus-5          key set (…6QAA)  [default]
   2. work             openai      gpt-5                  key set (…9999)

   a. add an account    d. change the default    r. remove one
   a number opens that account's settings;  q. back
```

`a` asks for one labelled thing at a time: the name you choose → the provider, from a
menu → the key → the model, from that provider's live list → the language. Any step can
be skipped and set later. A number opens that account's own settings; `d` changes the
default; `r` removes an account **and its stored key**.

Scriptable equivalents, for CI or a dotfiles bootstrap:

```bash
tdreport account add work openai
tdreport --ai-account work set-key            # or `set-key sk-…`, at the cost of shell history
tdreport --ai-account work set-model gpt-5
```

## The repo screen

`tdreport settings <repo>` scopes everything to one repository and, more usefully, shows
**where each value comes from**:

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
with what each one actually brings. Options 2 through 5 set overrides for this repo only;
an empty answer clears one. Option 6 jumps to the account, which affects every repo using
it.

`tdreport repo <name>` prints the same resolution without a menu, for scripts.

## Where it lives

Three files and a drafts directory in `~/.config/ufo-tdkit-report/`
(`~/Library/Application Support/…` on macOS, `%APPDATA%\…` on Windows). Only the first
holds secrets.

| File | Contents |
| --- | --- |
| `.env` | **Keys only**, one variable per account (`TDREPORT_KEY_WORK`). Mode `0600` on Linux and macOS, checked on every read — if a copy or a backup widened it you get one note naming the `chmod`; on Windows there is no such mode bit, and the user-profile ACL protects it instead |
| `settings.json` | Accounts: provider, model, language, base URL. No secrets |
| `repos.json` | Registered repos, their bindings and overrides. No secrets |
| `drafts/` | Drafted commit messages, removed once committed. Safe to delete |
| *inside the font repo* | Nothing — not a config file, not even the draft. A file there would be committed and shared |

Keys are never read from the process environment, a repo `.env`, or the cwd, so a stray
`export` cannot leak one in. `settings.json` and `repos.json` are safe to back up.

## Rule of thumb

- **Account** — provider and key. They always travel together.
- **Repo** — model, language, grounding strictness and the token cap, when this one repo
  needs its own.

A second account is needed only when you need a **different key or a different provider**.
Different models on the same key is a repo override, not a new account.

## When something looks wrong

**The key prompt seems to ignore my paste.** It does not echo — a pasted key shows
*nothing at all*, deliberately, so it never lands in the terminal scrollback. Paste and
press Enter; a `key stored: set (…9999)` line confirms it landed. If your terminal really
cannot paste into a hidden prompt, `tdreport --ai-account <name> set-key sk-…` takes it as
an argument, at the cost of putting it in your shell history.

**The model list only shows two entries.** Read the line above it. `Models available to
this key on <provider>` is the live list from the provider; `Built-in list` is the offline
fallback, shown when there is no key yet or the endpoint could not be reached. A short
fallback list does not mean the provider only has two models — it means nobody could ask.

**`the model hit its token cap … and produced no text`.** A reasoning model spends the
completion budget on its private reasoning *before* writing anything, so a cap sized for
the prose can be consumed entirely — and the whole 8192 can go on thinking, leaving
nothing for the answer. Raise it where it belongs: `tdreport set-max-tokens 32000` for the
account, `tdreport repo <name> max-tokens 32000` for one repo, `--ai-max-tokens` for one
run. Or pick a non-reasoning model. The built-in default stays conservative because
`max_tokens` goes to every provider and some models cap their output well below it.

**`grounding check failed: … tokens do not appear in the facts`.** The narration named
identifiers the facts do not contain, and this account or repo is set to `strict`. Read
the listed tokens: a near-miss like `guillemotleft` for `guillemetleft` is the model
inventing. Re-run, or relax with `tdreport set-grounding warn` (the default), which keeps
the narration and notes the tokens instead.

**`the model did not mark up any identifiers`.** The prompt asks for glyph names,
codepoints and tags in backticks, so they can be told apart from prose — `four` and `one`
are glyph names as well as words. This model ignored that, so glyph-name checking was
skipped for that narration. The other checks still ran. Common on small local models.

**I get the plain report and no prose.** That is the fallback, and it always says why on
stderr: no key for the resolved provider, no model chosen, or the call failed. Two
surprises to check first — `--json` implies no narration (a narrative is not part of the
machine-readable facts), and a repo that is *not registered* resolves to the **default**
account, so the key you set on another account was never the one looked for. `tdreport
settings <repo>` names the source of every value. Use `--ai` to make the fallback an
error instead.

**`unknown repo 'x'`.** A bare name that was never registered is an error rather than a
guess. Register it by addressing it once by path (`tdreport ~/fonts/x`), or check
`tdreport ls`.

**Which settings would this run actually use?** `tdreport settings <repo>` (interactive)
or `tdreport repo <name>` (plain output). Both name the source of every value.

---

Full reference: [README](../README.md) · `tdreport --help` lists every command.
