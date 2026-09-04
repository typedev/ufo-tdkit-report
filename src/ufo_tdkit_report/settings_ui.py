"""The interactive ``tdreport settings`` screen, and its non-interactive listing.

A *front-end only*: every change goes through :mod:`settings` and :mod:`registry`, so
this module holds no state and is never a second source of truth. Nothing here prints a
secret — keys are shown through :func:`settings.masked_key`.

Two modes, deliberately:

- a TTY gets the menu loop (``run_settings_menu``);
- anything else — a pipe, CI, a hook — gets :func:`render_settings`, a plain listing (or
  JSON), and exits. A settings screen that blocks waiting for input it can never receive
  is worse than no settings screen.
"""

from __future__ import annotations

import json

from ufo_tdkit_report import registry, settings
from ufo_tdkit_report.providers import NarratorError


def _prompt(question: str, default: str = "") -> str | None:
    """One line of input. None means the user aborted (Ctrl-C / EOF)."""
    try:
        return input(question).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def settings_snapshot(account: str | None = None) -> dict:
    """Everything the screen shows, as data. No secrets — the key is a masked marker."""
    name = account or settings.default_account_name()
    resolved = settings.resolve_ai_settings(account=name)
    repos = registry.load()
    return {
        "account": name,
        "default_account": settings.default_account_name(),
        "provider": resolved.provider_name,
        "model": resolved.model,
        "language": resolved.language,
        "base_url": resolved.base_url,
        "grounding": "strict" if resolved.strict_grounding else "warn",
        "max_tokens": resolved.max_tokens,
        "key": settings.masked_key(name),
        "accounts": sorted(settings.accounts()),
        "repos": {
            repo_name: {k: v for k, v in entry.items()}
            for repo_name, entry in sorted(repos.items())
        },
        "config_dir": str(settings.settings_path().parent),
    }


def render_settings(account: str | None = None, *, as_json: bool = False) -> str:
    """The non-interactive view: what is configured, without changing anything."""
    snap = settings_snapshot(account)
    if as_json:
        return json.dumps(snap, indent=2, sort_keys=True, ensure_ascii=False)

    lines = [f"Settings — account '{snap['account']}'", ""]
    for label, value in (
        ("AI provider", snap["provider"]),
        ("Model", snap["model"] or "(not set)"),
        ("API key", snap["key"]),
        ("Language", snap["language"]),
        ("Base URL", snap["base_url"] or "(provider default)"),
        ("Grounding", snap["grounding"]),
    ):
        lines.append(f"  {label:<12} {value}")
    accounts_line = ", ".join(snap["accounts"])
    if len(snap["accounts"]) > 1:
        accounts_line += f" (default: {snap['default_account']})"
    lines.append(f"  {'Accounts':<12} {accounts_line}")
    bound = {n: e["account"] for n, e in snap["repos"].items() if e.get("account")}
    lines.append(f"  {'Repos':<12} {len(snap['repos'])} registered, {len(bound)} bound")
    for repo_name, entry in snap["repos"].items():
        suffix = f"  -> account '{entry['account']}'" if entry.get("account") else ""
        lines.append(f"      {repo_name}: {entry['path']}{suffix}")
    lines.append("")
    lines.append(f"  config: {snap['config_dir']}")
    return "\n".join(lines)


# --- the repo-scoped screen ---------------------------------------------------------
#
# Two settings live on the ACCOUNT (provider and key, because they belong together — a
# key is a key *for* a provider) and two can live on the REPO (model, language). Looking
# at a repo, that split is invisible and the whole thing reads as "why can I not just
# pick a provider here?". So this screen shows every value **with its source**, and
# offers the right lever for each: an account for provider+key, an override for the rest.


def repo_snapshot(name: str) -> dict:
    """What one repo resolves to, and where each value comes from."""
    from ufo_tdkit_report.config import LEGACY_MODEL_VAR, config_env_path, read_dotenv_key

    entry = registry.entry(name)
    if entry is None:
        raise NarratorError(f"no registered repo '{name}' — see `tdreport ls`")
    resolved = settings.resolve_ai_settings(repo=entry["path"])
    account = settings.get_account(entry.get("account") or settings.default_account_name())

    def source(field: str, account_value: str) -> str:
        if entry.get(field):
            return "this repo"
        if account_value:
            return f"account '{account.name}'"
        if field == "model" and read_dotenv_key([config_env_path()], LEGACY_MODEL_VAR):
            return "stored preference"
        return "built-in default"

    return {
        "name": name,
        "path": entry["path"],
        "overrides": {k: v for k, v in entry.items() if k != "path"},
        "account": account.name,
        "account_is_explicit": bool(entry.get("account")),
        "provider": resolved.provider_name,
        "provider_source": "this repo" if entry.get("provider") else f"account '{account.name}'",
        "model": resolved.model,
        "model_source": source("model", account.model),
        "language": resolved.language,
        "language_source": source("language", account.language),
        "grounding": "strict" if resolved.strict_grounding else "warn",
        "grounding_source": (
            "this repo" if "strict_grounding" in entry else f"account '{account.name}'"
        ),
        "max_tokens": resolved.max_tokens,
        "max_tokens_source": (
            "this repo" if entry.get("max_tokens")
            else (f"account '{account.name}'" if account.max_tokens else "built-in default")
        ),
        "key": settings.masked_key(account.name),
        "needs_key": resolved.provider.requires_key,
    }


def render_repo_settings(name: str, *, as_json: bool = False) -> str:
    snap = repo_snapshot(name)
    if as_json:
        return json.dumps(snap, indent=2, sort_keys=True, ensure_ascii=False)
    lines = [f"Settings — repo '{snap['name']}'", f"  {snap['path']}", ""]
    for label, value, origin in (
        ("Account", snap["account"], "this repo" if snap["account_is_explicit"] else "default account"),
        ("Provider", snap["provider"], snap["provider_source"]),
        ("API key", snap["key"], f"account '{snap['account']}'"),
        ("Model", snap["model"] or "(not set)", snap["model_source"]),
        ("Language", snap["language"], snap["language_source"]),
        ("Grounding", snap["grounding"], snap["grounding_source"]),
        ("Max tokens", str(snap["max_tokens"]), snap["max_tokens_source"]),
    ):
        lines.append(f"  {label:<10} {value:<28} from {origin}")
    return "\n".join(lines)


def _choose_account(current: str) -> str | None:
    """Numbered menu of accounts, each shown with what it actually brings: provider + key."""
    names = sorted(settings.accounts())
    print("\nAccounts — an account carries the provider AND the key for it:\n")
    for number, name in enumerate(names, 1):
        resolved = settings.resolve_ai_settings(account=name)
        marker = "  <- current" if name == current else ""
        print(f"  {number:>2}. {name:<16} {resolved.provider_name:<12} key {settings.masked_key(name)}{marker}")
    print()
    answer = _prompt(f"Number, or an account name [{current}]: ")
    if answer is None:
        return None
    if not answer:
        return current
    if answer.isdigit():
        index = int(answer)
        if not 1 <= index <= len(names):
            print(f"no option {index} (pick 1-{len(names)})")
            return None
        return names[index - 1]
    return answer


def _edit_repo_override(name: str, field: str) -> None:
    entry = registry.entry(name)
    if not entry:
        return
    snap = repo_snapshot(name)
    inherited = snap[field]
    if field == "model":
        from ufo_tdkit_report.cli import _choose_model

        resolved = settings.resolve_ai_settings(repo=entry["path"])
        print(f"\nA model for '{name}' only; the account keeps its own. Enter keeps the current one.")
        models, _live = models_for(resolved)
        value = _choose_model(models, inherited) if models else _prompt(f"Model id [{inherited}]: ")
        if value is None or value == inherited:
            return
    else:
        print(f"\nEmpty clears the override, back to '{inherited}' from account '{snap['account']}'.")
        value = _prompt(f"{field.capitalize()} for '{name}' [{entry.get(field, '')}]: ")
        if value is None:
            return
    registry.add(name, entry["path"], **{field: value or None})
    print(f"'{name}' {field}: {value or '(inherited)'}")


def _edit_repo_grounding(name: str) -> None:
    """Strict or warn for this repository only; empty hands it back to the account."""
    entry = registry.entry(name)
    if not entry:
        return
    snap = repo_snapshot(name)
    print("\n  strict — refuse a narration whose tokens the facts do not support")
    print("  warn   — keep it and note them")
    print(f"  empty  — inherit from account '{snap['account']}'")
    answer = _prompt(f"  Grounding for '{name}' [{snap['grounding']}]: ")
    if answer is None:
        return
    if not answer:
        registry.add(name, entry["path"], strict_grounding=None)
        print(f"  '{name}' grounding: inherited")
        return
    from ufo_tdkit_report.cli import _parse_strictness

    strict = _parse_strictness(answer)
    if strict is None:
        print(f"  expected 'strict' or 'warn', got '{answer}'")
        return
    registry.add(name, entry["path"], strict_grounding=strict)
    print(f"  '{name}' grounding: {'strict' if strict else 'warn'}")


def run_repo_menu(name: str) -> int:
    """The interactive screen for one repository."""
    while True:
        try:
            snap = repo_snapshot(name)
        except NarratorError as exc:
            print(f"error: {exc}")
            return 1
        print(f"\nSettings — repo '{snap['name']}'")
        print(f"  {snap['path']}\n")
        origin = "this repo" if snap["account_is_explicit"] else "default account"
        print(f"   1. Account    {snap['account']:<22} from {origin}")
        print(f"      provider   {snap['provider']:<22} from {snap['provider_source']}")
        print(f"      API key    {snap['key']:<22} from account '{snap['account']}'")
        print(f"   2. Model      {(snap['model'] or '(not set)'):<22} from {snap['model_source']}")
        print(f"   3. Language   {snap['language']:<22} from {snap['language_source']}")
        print(f"   4. Grounding  {snap['grounding']:<22} from {snap['grounding_source']}")
        print(f"   5. Max tokens {str(snap['max_tokens']):<22} from {snap['max_tokens_source']}")
        print("   6. Edit the account itself (affects every repo using it)")
        print("   q. Quit")
        if snap["needs_key"] and snap["key"] == "not set":
            # The key belongs to the account, so it is set through option 5 (the account
            # screen) — option 1 only picks a *different* account, which may already have
            # one. This line named option 4 until the Grounding row pushed everything down.
            print(f"\n   ! account '{snap['account']}' has no key — option 6 to set one, "
                  f"or option 1 to use an account that has one")
        if snap["overrides"].get("provider"):
            print("\n   ! this repo overrides the provider but uses the account's key —")
            print("     that only works if the key is valid for both")

        answer = _prompt("\nNumber to change [q]: ")
        if answer is None or answer in ("", "q", "quit"):
            return 0
        try:
            if answer == "1":
                chosen = _choose_account(snap["account"])
                if chosen and chosen != snap["account"]:
                    settings.get_account(chosen)  # reject a typo before writing
                    registry.add(name, snap["path"], account=chosen)
                    print(f"'{name}' now uses account '{chosen}'")
                    # A model id belongs to a provider, and switching account can change
                    # the provider under a repo-level override. We cannot tell which ids
                    # are valid where (no vendor knowledge lives in this tool), so say so
                    # at the moment the mismatch is created rather than guessing.
                    override = snap["overrides"].get("model")
                    if override:
                        new_provider = settings.resolve_ai_settings(repo=snap["path"]).provider_name
                        print(
                            f"  note: this repo pins the model '{override}' — check it exists for "
                            f"provider {new_provider} (option 2), or clear it with an empty answer"
                        )
            elif answer == "2":
                _edit_repo_override(name, "model")
            elif answer == "3":
                _edit_repo_override(name, "language")
            elif answer == "4":
                _edit_repo_grounding(name)
            elif answer == "5":
                _edit_repo_max_tokens(name)
            elif answer == "6":
                run_settings_menu(snap["account"])
            else:
                print(f"no option '{answer}'")
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")


# --- the interactive screen ---------------------------------------------------------


def _edit_provider(account: str) -> None:
    from ufo_tdkit_report.cli import _choose_provider

    current = settings.resolve_ai_settings(account=account).provider_name
    chosen = _choose_provider(current)
    if not chosen or chosen == current:
        return
    settings.update_account(account, provider=chosen)
    resolved = settings.resolve_ai_settings(account=account)
    print(f"provider: {chosen}")
    # Switching provider deliberately leaves no model behind; say what is still needed.
    if not resolved.model:
        print("  (no model for this provider yet — pick one from this menu)")
    if resolved.provider.requires_key and not resolved.api_key:
        print("  (no key for this provider yet — set one from this menu)")


def _edit_model(account: str) -> None:
    from ufo_tdkit_report.cli import _choose_model

    resolved = settings.resolve_ai_settings(account=account)
    models, _live = models_for(resolved)
    if not models:
        print(f"No model list available for {resolved.provider_name} — type an id.")
    chosen = _choose_model(models, resolved.model)
    if not chosen:
        return
    settings.update_account(account, model=chosen)
    print(f"model: {chosen}")


def _edit_key(account: str) -> None:
    if prompt_key(account):
        print(f"  stored owner-only in {settings.config_env_path()}")


def _edit_language(account: str) -> None:
    current = settings.resolve_ai_settings(account=account).language
    answer = _prompt(f"Language for AI prose [{current}]: ")
    if answer is None:
        return
    settings.update_account(account, language=answer or current)
    print(f"language: {answer or current}  (facts, headings and footer stay English)")


def _edit_base_url(account: str) -> None:
    current = settings.resolve_ai_settings(account=account).base_url
    print("Empty clears it, falling back to the provider's own endpoint.")
    answer = _prompt(f"Base URL [{current}]: ")
    if answer is None:
        return
    settings.update_account(account, base_url=answer)
    print(f"base URL: {answer or '(provider default)'}")


def prompt_key(account: str) -> str | None:
    """Ask for an API key. Returns the stored key, or None if nothing was entered.

    The prompt says the input is hidden. It is not obvious: a pasted key shows nothing at
    all, which reads as "the terminal is ignoring me" — you press Enter, no key is stored,
    and the next screen quietly falls back to the offline model list. So: say it up front,
    and confirm (masked) that it landed.
    """
    from ufo_tdkit_report.cli import _read_secret

    resolved = settings.resolve_ai_settings(account=account)
    print(f"\n  API key for {resolved.provider_name}. Input is HIDDEN — paste it and press Enter.")
    print("  Nothing will appear as you type; that is expected. Enter alone skips for now.")
    key = _read_secret(f"  Key for '{account}': ")
    if not key:
        print(f"  no key stored for '{account}' yet "
              f"(later: `tdreport --ai-account {account} set-key sk-...`)")
        return None
    settings.store_account_key(key, account=account)
    print(f"  key stored: {settings.masked_key(account)}")
    return key


def models_for(resolved) -> tuple[list[tuple[str, str]], bool]:
    """``(models, live)`` for a resolved account, saying WHICH list this is.

    A fallback list looks exactly like a real one, so a short list reads as "this provider
    only has two models" when it really means "no key, so nobody could ask". The caller
    prints which it got.
    """
    from ufo_tdkit_report.narrator import list_models

    provider = resolved.provider
    can_ask = bool(resolved.api_key) or not provider.requires_key
    models = list_models(
        provider=provider.name, api_key=resolved.api_key, base_url=resolved.base_url
    )
    live = can_ask and models != list(provider.known_models)
    if live:
        print(f"\n  Models available to this key on {provider.name}:")
    elif can_ask:
        print(f"\n  Built-in list for {provider.name} — the live list could not be fetched "
              f"(network, or the endpoint rejected the key).")
    else:
        print(f"\n  Built-in list for {provider.name} — no key yet, so the live list was not "
              f"requested. Any id can be typed; `set-model` shows the real list once a key is set.")
    return models, live


def add_account_flow(name: str | None = None, provider: str | None = None) -> settings.Account | None:
    """Create an account step by step. Returns the new Account, or None if cancelled.

    Four bare words in a row (`account add work openai`) are unreadable — nothing in them
    says which one you invent and which one is a provider. So the parts are asked for one
    at a time, each labelled, and anything you skip can be set later.
    """
    from ufo_tdkit_report.cli import _choose_model, _choose_provider

    print("\nNew account — a name you choose, plus the provider whose key it will hold.")
    if not name:
        name = _prompt("\n  Name (e.g. work, client-acme): ")
        if not name:
            print("cancelled")
            return None
    try:
        settings.validate_account_name(name)
    except ValueError as exc:
        print(f"error: {exc}")
        return None

    if not provider:
        provider = _choose_provider("anthropic")
        if not provider:
            print("cancelled")
            return None
    try:
        account = settings.add_account(name, provider=provider)
    except (NarratorError, ValueError) as exc:
        print(f"error: {exc}")
        return None

    resolved = settings.resolve_ai_settings(account=name)
    if resolved.provider.requires_key:
        prompt_key(name)
    if not resolved.base_url:
        url = _prompt(f"\n  Base URL for {provider} (required, e.g. http://localhost:8000/v1): ")
        if url:
            settings.update_account(name, base_url=url)

    resolved = settings.resolve_ai_settings(account=name)
    models, live = models_for(resolved)
    print()
    model = _choose_model(models, resolved.model) if models else _prompt("  Model id (empty for later): ")
    if model:
        settings.update_account(name, model=model)

    language = _prompt(f"\n  Language for AI prose [{resolved.language}]: ")
    if language:
        settings.update_account(name, language=language)

    final = settings.resolve_ai_settings(account=name)
    print(f"\nCreated account '{name}'")
    print(f"  provider  {final.provider_name}")
    print(f"  model     {final.model or '(not set — `tdreport --ai-account %s set-model`)' % name}")
    print(f"  key       {settings.masked_key(name)}")
    print(f"  language  {final.language}")
    if final.provider.requires_key and not final.api_key:
        print(f"\n  next: store the key — `tdreport --ai-account {name} set-key`")
        print(f"        then pick from the live model list — `tdreport --ai-account {name} set-model`")
    else:
        print(f"\n  next: point a repo at it — `tdreport bind {name} <path>`")
    return account


def run_accounts_menu(highlight: str | None = None) -> int:
    """The accounts screen: what exists, what each brings, and how to add one."""
    while True:
        current_default = settings.default_account_name()
        names = sorted(settings.accounts())
        print("\nAI accounts — an account carries a provider AND the key for it:\n")
        for number, name in enumerate(names, 1):
            resolved = settings.resolve_ai_settings(account=name)
            marks = []
            if name == current_default:
                marks.append("default")
            if name == highlight:
                marks.append("this repo")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            print(
                f"  {number:>2}. {name:<16} {resolved.provider_name:<11} "
                f"{(resolved.model or '(no model)'):<22} key {settings.masked_key(name)}{suffix}"
            )
        print("\n   a. add an account    d. change the default    r. remove one")
        print("   a number opens that account's settings;  q. back")
        answer = _prompt("\n> ")
        if answer is None or answer in ("", "b", "q", "quit"):
            return 0
        try:
            if answer == "a":
                add_account_flow()
            elif answer == "d":
                chosen = _choose_account(current_default)
                if chosen and chosen != current_default:
                    print(f"default account: {settings.set_default_account(chosen)}")
            elif answer == "r":
                name = _prompt("Remove which account (its key goes with it)? ")
                if not name:
                    continue
                if settings.remove_account(name):
                    print(f"removed '{name}' and its stored key")
                else:
                    print(f"no such account '{name}'")
            elif answer.isdigit() and 1 <= int(answer) <= len(names):
                run_settings_menu(names[int(answer) - 1])
            else:
                print(f"no option '{answer}'")
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")


def _edit_repo_max_tokens(name: str) -> None:
    """This repo's own completion cap. Empty keeps it; 0 hands it back to the account."""
    from ufo_tdkit_report.cli import _parse_token_cap

    entry = registry.entry(name) or {}
    current = settings.resolve_ai_settings(repo=entry.get("path")).max_tokens
    answer = _prompt(f"\n  Max tokens for '{name}', 0 to use the account's [{current}]: ")
    if answer is None or not answer.strip():
        print(f"unchanged: {current}")
        return
    chosen = _parse_token_cap(answer)
    if chosen is None:
        return
    registry.add(name, entry["path"], max_tokens=chosen)
    resolved = settings.resolve_ai_settings(repo=entry["path"]).max_tokens
    print(f"max tokens: {resolved}" + ("" if chosen else " (from the account)"))


def _edit_max_tokens(account: str) -> None:
    """The completion cap for this account. Empty keeps it; 0 hands it back to the default."""
    from ufo_tdkit_report.cli import _parse_token_cap
    from ufo_tdkit_report.narrator import DEFAULT_MAX_TOKENS

    current = settings.resolve_ai_settings(account=account).max_tokens
    print(f"\n  Completion cap for account '{account}'. This covers the WHOLE completion —")
    print("  a reasoning model spends the same budget on thinking and on the answer, and")
    print("  can consume all of it before writing a word.")
    answer = _prompt(f"\n  Tokens, or 0 for the built-in {DEFAULT_MAX_TOKENS} [{current}]: ")
    if answer is None or not answer.strip():
        print(f"unchanged: {current}")
        return
    chosen = _parse_token_cap(answer)
    if chosen is None:
        return
    settings.update_account(account, max_tokens=chosen)
    print(f"max tokens: {settings.resolve_ai_settings(account=account).max_tokens}")


def _edit_grounding(account: str) -> None:
    """Strict or warn, for this account.

    It belongs to the model rather than to the run: a small local model earns a refusal,
    a large hosted one usually only needs the note.
    """
    current = "strict" if settings.resolve_ai_settings(account=account).strict_grounding else "warn"
    print("\n  warn   — note the tokens the facts do not support, keep the narration")
    print("  strict — refuse it instead")
    answer = _prompt(f"  Grounding for '{account}' [{current}]: ")
    if answer is None:
        return
    from ufo_tdkit_report.cli import _parse_strictness

    strict = _parse_strictness(answer or current)
    if strict is None:
        print(f"  expected 'strict' or 'warn', got '{answer}'")
        return
    settings.update_account(account, strict_grounding=strict)
    print(f"  grounding: {'strict' if strict else 'warn'}")


def _repos_screen() -> None:
    while True:
        entries = sorted(registry.load().items())
        print("\nRegistered repos:\n")
        if not entries:
            print("  (none yet — `tdreport <path>` remembers a repo the first time)")
        for number, (name, entry) in enumerate(entries, 1):
            extras = [f"{k}={v}" for k, v in sorted(entry.items()) if k != "path"]
            suffix = f"  [{', '.join(extras)}]" if extras else ""
            print(f"  {number:>2}. {name:<16} {entry['path']}{suffix}")
        dead = registry.stale()
        if dead:
            print(f"\n  {len(dead)} stale (path gone): {', '.join(n for n, _ in dead)}")
        print("\n  b. bind to an account    m. model for one repo    l. language for one repo")
        print("  u. unbind (clears every override)    r. remove    p. prune stale    q. back")
        answer = _prompt("\n> ")
        if answer is None or answer in ("", "q", "back"):
            return
        if answer == "p":
            pruned = registry.prune()
            print(f"pruned {len(pruned)} stale entr{'y' if len(pruned) == 1 else 'ies'}")
        elif answer == "r":
            name = _prompt("Remove which repo? ")
            if name:
                print("removed" if registry.remove(name) else f"no such repo '{name}'")
        elif answer == "u":
            name = _prompt("Unbind which repo? ")
            entry = registry.entry(name) if name else None
            if entry:
                registry.add(name, entry["path"], account=None)
                print(f"'{name}' now uses the default account")
            elif name:
                print(f"no such repo '{name}'")
        elif answer in ("m", "l"):
            field = "model" if answer == "m" else "language"
            name = _prompt(f"Set {field} for which repo? ")
            entry = registry.entry(name) if name else None
            if not entry:
                if name:
                    print(f"no such repo '{name}'")
                continue
            resolved = settings.resolve_ai_settings(repo=entry["path"])
            inherited = resolved.model if field == "model" else resolved.language
            print(f"Empty clears the override (back to '{inherited}' from the account).")
            value = _prompt(f"{field.capitalize()} for '{name}' [{entry.get(field, '')}]: ")
            if value is None:
                continue
            registry.add(name, entry["path"], **{field: value or None})
            print(f"'{name}' {field}: {value or '(inherited)'}")
        elif answer == "b":
            name = _prompt("Bind which repo? ")
            entry = registry.entry(name) if name else None
            if not entry:
                if name:
                    print(f"no such repo '{name}'")
                continue
            account = _prompt(f"To which account ({', '.join(sorted(settings.accounts()))})? ")
            if not account:
                continue
            try:
                settings.get_account(account)
            except NarratorError as exc:
                print(f"error: {exc}")
                continue
            registry.add(name, entry["path"], account=account)
            print(f"'{name}' now uses account '{account}'")
        else:
            return


def run_settings_menu(account: str | None = None) -> int:
    """The interactive screen. Returns a process exit code."""
    account = account or settings.default_account_name()
    while True:
        try:
            snap = settings_snapshot(account)
        except NarratorError as exc:  # the edited account was removed underneath us
            print(f"error: {exc}")
            account = settings.default_account_name()
            continue
        print(f"\nSettings — account '{account}'\n")
        print(f"   1. AI provider   {snap['provider']}")
        print(f"   2. Model         {snap['model'] or '(not set)'}")
        print(f"   3. API key       {snap['key']}")
        print(f"   4. Language      {snap['language']}")
        print(f"   5. Base URL      {snap['base_url'] or '(provider default)'}")
        print(f"   6. Grounding     {snap['grounding']}"
              f"{'  (refuse a narration the facts do not support)' if snap['grounding'] == 'strict' else ''}")
        print(f"   7. Max tokens    {snap['max_tokens']}")
        print(f"   8. Accounts      {', '.join(snap['accounts'])}")
        bound = sum(1 for e in snap["repos"].values() if e.get("account"))
        print(f"   9. Repos         {len(snap['repos'])} registered, {bound} bound")
        print("   q. Quit")
        answer = _prompt("\nNumber to change [q]: ")
        if answer is None or answer in ("", "q", "quit"):
            return 0
        actions = {
            "1": _edit_provider,
            "2": _edit_model,
            "3": _edit_key,
            "4": _edit_language,
            "5": _edit_base_url,
            "6": _edit_grounding,
            "7": _edit_max_tokens,
        }
        try:
            if answer in actions:
                actions[answer](account)
            elif answer == "8":
                run_accounts_menu(account)
            elif answer == "9":
                _repos_screen()
            else:
                print(f"no option '{answer}'")
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
