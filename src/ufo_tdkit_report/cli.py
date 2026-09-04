"""Command-line entry point for ``tdreport``.

Repo-centric: operate on the current repo (cwd), a registered name, or an explicit
path. Default mode is the working-tree commit assistant; a commit range (contains
``..``) or ``--notes`` switches to committed-history reporting.
"""

from __future__ import annotations

import argparse
import os
import sys


def _confirm(question: str, *, assume_yes: bool = False) -> bool:
    """Interactive y/N prompt. Auto-yes with --yes; silent no when not a TTY (pipes/CI)."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def _read_secret(prompt: str) -> str:
    """Read a secret without echoing it (interactive TTY), or from a pipe (CI)."""
    if sys.stdin.isatty():
        import getpass

        try:
            return getpass.getpass(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
    return sys.stdin.readline().strip()


def _choose_provider(current: str) -> str | None:
    """Numbered menu of the known providers. Returns the chosen name, or None to abort."""
    from ufo_tdkit_report.providers import PROVIDERS

    entries = sorted(PROVIDERS.values(), key=lambda p: (p.requires_key is False, p.name))
    print("Available providers:\n")
    for number, provider in enumerate(entries, 1):
        marker = "  <- current" if provider.name == current else ""
        print(f"  {number:>2}. {provider.label:<38} {provider.name}{marker}")
        if provider.notes:
            print(f"      {provider.notes}")
    print()
    try:
        answer = input(f"Number, or a provider name [{current}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not answer:
        return current
    if answer.isdigit():
        index = int(answer)
        if not 1 <= index <= len(entries):
            print(f"error: no option {index} (pick 1-{len(entries)})")
            return None
        return entries[index - 1].name
    return answer


def _choose_model(models: list[tuple[str, str]], current: str) -> str | None:
    """Numbered menu of available models. Returns the chosen id, or None to abort.

    Enter keeps the current model; a raw id can also be typed, so a model missing from
    the list (or newer than it) is never locked out.
    """
    print("Available models:\n")
    for number, (model_id, label) in enumerate(models, 1):
        marker = "  <- current" if model_id == current else ""
        print(f"  {number:>2}. {label:<20} {model_id}{marker}")
    print()
    try:
        answer = input(f"Number, or a model id [{current}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not answer:
        return current
    if answer.isdigit():
        index = int(answer)
        if not 1 <= index <= len(models):
            print(f"error: no option {index} (pick 1-{len(models)})")
            return None
        return models[index - 1][0]
    return answer


def _auto_register(selector: str) -> str:
    """Remember a repo the first time it is addressed by PATH; returns its git root.

    ``tdreport ~/fonts/MyFont`` should be needed once — afterwards ``tdreport MyFont``
    works. Only an explicit path argument triggers this: the bare ``tdreport`` in a cwd
    registers nothing, and an unknown bare NAME stays an error rather than becoming a
    silent registration.

    Deliberately never silent and never destructive: it prints what it remembered, and a
    name already pointing somewhere else is reported, not overwritten — quietly
    repointing a name is how you end up reporting on the wrong project.
    """
    from ufo_tdkit_report import registry
    from ufo_tdkit_report.commit import resolve_repo

    repo = resolve_repo(selector)
    existing = _registry_name_for(repo)
    if existing:
        return repo  # already known under some name
    name = os.path.basename(repo)
    taken = registry.resolve(name)
    if taken:
        print(f"note: the name '{name}' is already registered to {taken}; not remembering this one.")
        print(f"      give it another name with `tdreport add <name> {repo}`")
        return repo
    registry.add(name, repo)
    print(f"remembered '{name}' -> {repo}  (next time: `tdreport {name}`)")
    return repo


def _registry_name_for(repo: str) -> str | None:
    from ufo_tdkit_report import registry

    return registry.name_for_path(repo)


def _repo_path(selector):
    """The repository a selector points at, or None when it cannot be resolved.

    Only used to give the settings resolver a repo whose binding to honour. An
    unresolvable selector is not reported here — `inspect` raises for it a moment later
    with a better message, and this must not pre-empt that with a worse one.
    """
    from ufo_tdkit_report.commit import resolve_repo

    try:
        return resolve_repo(selector)
    except RuntimeError:
        return None


def _no_narration(args, why: str, fix: str = "") -> bool:
    """Report why there is no narrative, and whether that is fatal.

    The deterministic facts are the ground truth and they cost nothing to produce, so a
    provider that is unconfigured, unreachable or unhappy costs you the prose, not the
    report. `--ai` is for the caller who would rather fail than receive the quieter
    output — CI that publishes the prose has no use for a report it did not ask for.
    The note goes to stderr, so stdout stays exactly the byte-stable report.
    """
    if args.require_ai:
        from ufo_tdkit_report import NarratorError

        raise NarratorError(f"--ai was requested but the narrative cannot be produced: {why}")
    print(f"note: {why}, so this is the deterministic report only."
          f"{' ' + fix + '.' if fix else ''}", file=sys.stderr)
    return False


def _narration_wanted(args, ai_opts, repo=None) -> bool:
    """Whether this run narrates. AI is the default; three things turn it off.

    `--no-ai` and `--json` are the caller saying so — the first outright, the second
    because JSON is the machine-readable *facts* and a narrative is not part of them.
    The third is having nothing to narrate with, and that one is **announced**: falling
    back silently would make the same command on the same repository print different
    things depending on whether a key happens to be configured, which is exactly the
    kind of invisible difference this tool exists to remove. The note goes to stderr so
    the report on stdout stays byte-stable and pipeable.
    """
    if args.no_ai:
        return False
    if args.json_output:
        return False
    from ufo_tdkit_report import NarratorError, resolve_ai_settings
    from ufo_tdkit_report.settings import warn_if_unbound

    try:
        resolved = resolve_ai_settings(
            repo=repo, account=ai_opts.get("account"), provider=ai_opts.get("provider"),
            model=ai_opts.get("model"), language=ai_opts.get("language"),
        )
    except NarratorError as exc:  # an unknown provider or account named on the command line
        return _no_narration(args, str(exc))
    # Say this even when we are about to fall back — an unregistered repo resolving to the
    # default account is the likeliest reason a key the owner *has* was not the one looked
    # for, so it explains the fallback rather than merely accompanying it.
    if repo:
        warn_if_unbound(resolved, repo)
    if resolved.provider.requires_key and not resolved.api_key:
        return _no_narration(
            args, f"no API key for provider '{resolved.provider_name}'",
            fix="`tdreport set-key` enables the narrative; `--no-ai` silences this note",
        )
    if not resolved.model:
        return _no_narration(
            args, f"no model chosen for provider '{resolved.provider_name}'",
            fix="`tdreport set-model` enables the narrative",
        )
    return True


def _do_commit(selector, args, ai_opts, do_commit) -> int:
    """Commit, resolving a stale draft first: ask on a TTY, refuse in a pipe.

    A draft that no longer describes the working tree would put a wrong description into
    git history — unfixable afterwards without rewriting it. So the default is to refuse,
    and the way out is explicit.
    """
    from ufo_tdkit_report import NarratorError
    from ufo_tdkit_report.commit import draft_state, inspect, resolve_repo

    stale_ok = args.stale_ok
    try:
        repo_path = resolve_repo(selector)
        state = draft_state(repo_path)
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    try:
        use_ai = _narration_wanted(args, ai_opts, repo=repo_path)
    except NarratorError as exc:
        print(f"error: {exc}")
        return 1

    if state.exists and state.stale and not stale_ok:
        if not sys.stdin.isatty():
            print("error: the working tree changed since this draft was written, so it no "
                  "longer describes what would be committed.")
            print(f"       redraft it, or pass --stale-ok to commit it anyway. draft: {state.path}")
            return 1
        print("The working tree changed since this draft was written, so it no longer")
        print("describes what would be committed.")
        if state.ai:
            print("(this draft was written by AI — redrafting without `--no-ai` keeps it prose)")
        answer = (_prompt_line("  [r]edraft, [c]ommit anyway, [a]bort? ") or "a").lower()
        if answer.startswith("r"):
            try:
                _, text, _ = inspect(selector, ai=use_ai, regenerate=True, **ai_opts)
            except (NarratorError, RuntimeError) as exc:
                print(f"error: {exc}")
                return 1
            print(text)
            if not _confirm("Commit this?", assume_yes=args.yes):
                print("Not committed.")
                return 0
        elif answer.startswith("c"):
            stale_ok = True
        else:
            print("Aborted.")
            return 0

    try:
        rc, msg = do_commit(selector, ai=use_ai, allow_stale=stale_ok, **ai_opts)
    except (NarratorError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1
    print(msg)
    return rc


def _parse_token_cap(answer: str) -> int | None:
    """A token cap from user input: a positive int, or 0 to clear. None means rejected.

    Rejected loudly here, unlike the tolerant coercion in `settings`/`registry`: a stored
    file may have been hand-edited by someone who is not present, but a value typed at
    the CLI has an author standing right there to be told.
    """
    text = (answer or "").strip()
    if text in ("", "clear", "default", "0"):
        return 0
    try:
        cap = int(text)
    except ValueError:
        print(f"error: expected a number of tokens, got '{answer}'")
        return None
    if cap < 1:
        print(f"error: a token cap must be positive, got {cap}")
        return None
    return cap


def _parse_strictness(answer: str) -> bool | None:
    """`strict`/`warn` (and the obvious synonyms) -> a flag, or None if unrecognised."""
    value = (answer or "").strip().lower()
    if value in ("strict", "on", "yes", "true", "1", "refuse"):
        return True
    if value in ("warn", "off", "no", "false", "0", "warning"):
        return False
    return None


def _prompt_line(question: str) -> str | None:
    """One line of input; None when the user aborts."""
    try:
        return input(question).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _is_range(arg: str | None) -> bool:
    """True if ``arg`` is a commit range (``a..b``) → committed-history modes.

    Everything else (a registry name, a path, None) is a repo selector for the
    working-tree commit assistant.
    """
    return bool(arg) and ".." in arg


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tdreport",
        description="AI-narrated source-change reports for UFO/designspace fonts, grounded in a deterministic diff",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tdreport                       # commit assistant: draft a message for the cwd repo's working tree
  tdreport --no-ai               # same, deterministic facts only (no model call)
  tdreport commit                # commit the cwd working tree with the drafted message
  tdreport myfont                # commit assistant for a registered repo (see `add`)
  tdreport myfont commit         # commit a registered repo's working tree
  tdreport ~/fonts/MyFont        # commit assistant for an explicit repo path
  tdreport add myfont ~/fonts/MyFont   # register a name -> repo path
  tdreport set-provider           # pick the AI provider (Claude, GPT, Gemini, Grok, local...)
  tdreport set-key sk-...         # store that provider's API key, owner-only
  tdreport set-model              # pick the narration model from a menu of available ones
  tdreport set-lang Spanish       # AI prose language (the deterministic facts stay English)
  tdreport set-grounding strict   # refuse a narration the facts do not support (default: warn)
  tdreport set-max-tokens 32000   # completion cap; raise it for a reasoning model
  tdreport set-url http://localhost:8000/v1   # a custom OpenAI-compatible endpoint
  tdreport --ai-max-tokens 16000  # room for a reasoning model to think before it writes
  tdreport settings               # interactive screen for all of the above
  tdreport settings MyFont        # …scoped to one repo: what applies to it, and from where
  tdreport ls / rm <name> / prune # registered repos: list, forget, drop dead entries
  tdreport accounts               # menu of AI accounts: what each has, and add/remove
  tdreport account add                 # a second account: asks for a name, then shows a menu
  tdreport account add work --ai-provider openai   # …or say both outright
  tdreport bind work ~/fonts/AcmeSans  # that repo uses that account (and so its key)
  tdreport repo MyFont model claude-haiku-4-5   # this repo only, same account and key
  tdreport repo MyFont                 # what this repo resolves to, and why
  tdreport v2.005..v2.006        # committed-history report for a range (cwd repo)
  tdreport --notes v2.005..HEAD  # aggregate every commit in the range into release notes
        """,
    )
    parser.add_argument(
        "target", nargs="?",
        help="repo selector (name/path), a commit range, or a command: 'settings', "
             "'accounts', 'account', 'repo', 'bind', 'add', 'ls', 'rm', 'prune', "
             "'set-key', 'set-model', 'set-provider', 'set-lang', 'set-url', 'set-grounding',\n"
             "'set-max-tokens'",
    )
    parser.add_argument(
        "rest", nargs="*",
        help="'commit'; for 'add': <name> <path>; for the 'set-*' commands: the value to store",
    )
    parser.add_argument("--repo", default=".", help="git repo for committed-history modes (default: cwd)")
    parser.add_argument("--notes", action="store_true", help="aggregate every commit in the range into notes")
    parser.add_argument("--profile", help="path to a build-profile YAML to record in the report header")
    parser.add_argument("--threshold", type=int, default=12, help="fold detail into stats above this count")
    parser.add_argument("--json", dest="json_output", action="store_true", help="emit the report as JSON")
    ai_group = parser.add_mutually_exclusive_group()
    ai_group.add_argument(
        "--no-ai", action="store_true",
        help="deterministic facts only, no AI narrative (also implied by --json, and by "
             "having no AI account configured)",
    )
    ai_group.add_argument(
        "--ai", dest="require_ai", action="store_true",
        help="require the narrative: fail instead of falling back to the deterministic "
             "report when it cannot be produced (for CI that needs the prose)",
    )
    # The pre-0.5 spelling of what is now the default. Accepted and ignored so existing
    # scripts, hooks and docs keep working; hidden so --help teaches the current shape.
    parser.add_argument("--ai-note", action="store_true", help=argparse.SUPPRESS)
    from ufo_tdkit_report.narrator import DEFAULT_MODEL

    parser.add_argument(
        "--ai-model", default=None,
        help=f"narration model, overriding `tdreport set-model` (built-in default: {DEFAULT_MODEL})",
    )
    from ufo_tdkit_report.providers import PROVIDERS

    parser.add_argument(
        "--ai-provider", default=None,
        # Spelled from the table, not by hand: a hardcoded list here goes stale the next
        # time a row is added, and this help text is where people look for the names.
        help=f"narration provider, overriding the account's ({', '.join(PROVIDERS)})",
    )
    parser.add_argument(
        "--ai-lang", default=None,
        help="language for the AI prose, e.g. Spanish (the deterministic facts stay English)",
    )
    parser.add_argument(
        "--ai-account", default=None,
        help="AI account to use for this run, overriding the repo's binding and the default",
    )
    from ufo_tdkit_report.narrator import DEFAULT_MAX_TOKENS

    parser.add_argument(
        "--strict-grounding", dest="strict_grounding", action="store_true", default=None,
        help="refuse a narration whose tokens the facts do not support (default: warn). "
             "Also settable per account/repo — see `tdreport set-grounding`",
    )
    parser.add_argument(
        "--no-strict-grounding", dest="strict_grounding", action="store_false",
        help="warn instead of refusing, overriding a strict account or repo",
    )
    parser.add_argument(
        "--ai-max-tokens", type=int, default=None,
        help=f"completion cap for this run, overriding `tdreport set-max-tokens` "
             f"(built-in default: {DEFAULT_MAX_TOKENS}); a reasoning model "
             f"spends this budget on thinking before it writes anything",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="auto-confirm the 'commit this?' prompt")
    parser.add_argument(
        "-r", "--regenerate", action="store_true",
        help="redraft the commit message from the current changes, discarding your edits",
    )
    parser.add_argument(
        "--stale-ok", dest="stale_ok", action="store_true",
        help="commit an edited draft even though the working tree moved since it was written",
    )

    from ufo_tdkit_report import __version__

    # The version is stamped into report footers and commit trailers; make it queryable.
    parser.add_argument("--version", action="version", version=f"tdreport {__version__}")
    return parser


def _force_utf8_streams() -> None:
    """Make stdout/stderr UTF-8 so redirected output survives on Windows.

    Printing to a real Windows console is fine — Python writes it as UTF-16 through
    WriteConsoleW whatever the code page is. Redirect it, though, and the stream falls
    back to `locale.getpreferredencoding()`, which on Windows is the ANSI code page: the
    `→` in a rendered report then raises UnicodeEncodeError. `tdreport v1..v2 > notes.md`
    is exactly how release notes get captured, so that is not an edge case.

    Python 3.15 makes UTF-8 mode the default (PEP 686) and this becomes a no-op, but the
    floor here is 3.10. Skipped when a stream is already UTF-8 or cannot be reconfigured
    (a captured stream under pytest, a redirect installed by an embedding tool).
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", "") or ""
        if encoding.lower().replace("-", "") == "utf8":
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _present_warnings_as_notes() -> None:
    """Render this tool's own warnings as plain CLI notes, not Python tracebacks.

    An unbound repo has to be *said* — silence there means the narration ran on the
    default account's provider and key while the user believed otherwise. The library
    raises it as a warning so any consumer sees it; a console front-end should show it
    as one readable line on stderr, not as `…/settings.py:340: UnboundRepoWarning:`.
    """
    import warnings

    from ufo_tdkit_report.config import InsecureKeyFileWarning
    from ufo_tdkit_report.narrator import GroundingWarning
    from ufo_tdkit_report.settings import UnboundRepoWarning

    ours = (UnboundRepoWarning, GroundingWarning, InsecureKeyFileWarning)
    original = warnings.formatwarning

    def _format(message, category, filename, lineno, line=None):
        if isinstance(category, type) and issubclass(category, ours):
            return f"note: {message}\n"
        return original(message, category, filename, lineno, line)

    warnings.formatwarning = _format
    for category in ours:
        warnings.simplefilter("always", category)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.require_ai and args.json_output:
        # Not a fallback decision — the two flags ask for different artefacts, and
        # picking one silently would be answering a question nobody asked.
        parser.error("--ai and --json ask for different things: --json emits the "
                     "deterministic facts, and a narrative is not part of them")
    import json

    from ufo_tdkit_report import NarratorError

    _force_utf8_streams()
    _present_warnings_as_notes()

    # --- registry: `tdreport add <name> <path>` ---
    if args.target == "add":
        from ufo_tdkit_report import registry

        if len(args.rest) != 2:
            print("error: usage: tdreport add <name> <path>")
            return 1
        name, path = args.rest
        stored = registry.add(name, path)
        print(f"registered '{name}' -> {stored}")
        return 0

    from ufo_tdkit_report import registry as _registry
    from ufo_tdkit_report import settings as _settings

    # Which account these `set-*` commands act on: --ai-account, else the default one.
    account_name = args.ai_account or _settings.default_account_name()

    # --- key storage: `tdreport set-key [<key>]` (owner-only, scoped to one account) ---
    if args.target == "set-key":
        try:
            provider_name = _settings.resolve_ai_settings(account=account_name).provider_name
        except NarratorError as exc:
            print(f"error: {exc}")
            return 1
        # An inline key lands in shell history; prefer prompting/stdin when omitted.
        key = args.rest[0] if args.rest else _read_secret(f"API key for {provider_name}: ")
        try:
            path = _settings.store_account_key(key, account=account_name)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"stored the {provider_name} API key for account '{account_name}' in {path} (permissions 0600)")
        return 0

    # --- the settings screen: `tdreport settings [<repo>]` ---
    if args.target == "settings":
        from ufo_tdkit_report import settings_ui

        # `tdreport settings <repo>` scopes the screen to one repository: the same values,
        # each shown with WHERE it comes from, and the right lever offered for each.
        repo_name = None
        if args.rest:
            selector = args.rest[0]
            repo_name = _registry.entry(selector) and selector
            if not repo_name:
                if not os.path.exists(selector):
                    print(f"error: no registered repo '{selector}' — see `tdreport ls`")
                    return 1
                try:
                    repo_path = _auto_register(selector)
                except RuntimeError as exc:
                    print(f"error: {exc}")
                    return 1
                repo_name = _registry.name_for_path(repo_path)
                if not repo_name:
                    print(f"error: could not register {repo_path}; use `tdreport add <name> {repo_path}`")
                    return 1

        # Never block on input that a pipe or CI can never supply: show and exit.
        try:
            if args.json_output or not sys.stdin.isatty():
                if repo_name:
                    print(settings_ui.render_repo_settings(repo_name, as_json=args.json_output))
                else:
                    print(settings_ui.render_settings(args.ai_account, as_json=args.json_output))
                return 0
        except NarratorError as exc:
            print(f"error: {exc}")
            return 1
        return settings_ui.run_repo_menu(repo_name) if repo_name else settings_ui.run_settings_menu(args.ai_account)

    # --- registry listing / removal / pruning ---
    if args.target in ("ls", "rm", "prune"):
        entries = sorted(_registry.load().items())
        if args.target == "ls":
            if not entries:
                print("no repos registered yet — `tdreport <path>` remembers one the first time")
                return 0
            for name, entry in entries:
                extras = [f"{k}={v}" for k, v in sorted(entry.items()) if k != "path"]
                overrides = f"  [{', '.join(extras)}]" if extras else ""
                gone = "" if os.path.isdir(entry["path"]) else "  (MISSING)"
                print(f"{name:<20} {entry['path']}{overrides}{gone}")
            return 0
        if args.target == "rm":
            if not args.rest:
                print("error: usage: tdreport rm <name>")
                return 1
            for name in args.rest:
                print(f"removed '{name}'" if _registry.remove(name) else f"no such repo '{name}'")
            return 0
        pruned = _registry.prune()
        if not pruned:
            print("nothing to prune — every registered repo is still there")
            return 0
        for name, path in pruned:
            print(f"pruned '{name}' ({path} is gone)")
        return 0

    # --- accounts: `tdreport accounts` / `tdreport account add|rm|use <name>` ---
    if args.target == "accounts":
        from ufo_tdkit_report import settings_ui

        if sys.stdin.isatty() and not args.json_output:
            return settings_ui.run_accounts_menu()
        current = _settings.default_account_name()
        print("AI accounts:\n")
        for name, acct in sorted(_settings.accounts().items()):
            resolved = _settings.resolve_ai_settings(account=name)
            marker = "  <- default" if name == current else ""
            print(f"  {name}{marker}")
            print(f"      provider {acct.provider}")
            print(f"      model    {resolved.model or '(not set)'}")
            print(f"      language {resolved.language}")
            print(f"      key      {_settings.masked_key(name)}")
        bound = {
            repo_name: entry["account"]
            for repo_name, entry in sorted(_registry.load().items())
            if entry.get("account")
        }
        if bound:
            print("\nBound repos:")
            for repo_name, acct_name in bound.items():
                print(f"  {repo_name} -> {acct_name}")
        return 0

    if args.target == "account":
        action = args.rest[0] if args.rest else ""
        name = args.rest[1] if len(args.rest) > 1 else ""
        # `account add work openai` works, but four bare words in a row are unreadable —
        # nothing says which one you invent and which one is a provider. So on a TTY the
        # missing parts are asked for, with the provider offered as the same menu the
        # settings screen uses. Positional/flag forms stay for scripts and CI.
        provider = (args.rest[2] if len(args.rest) > 2 else None) or args.ai_provider
        interactive = sys.stdin.isatty()

        # On a TTY, creating an account is a guided flow (name, provider, key, model,
        # language) rather than a row of unlabelled positional words.
        if action == "add" and interactive:
            from ufo_tdkit_report import settings_ui

            return 0 if settings_ui.add_account_flow(name or None, provider) else 1

        if action not in ("add", "rm", "use") or not name:
            print("error: usage: tdreport account add [<name>] [<provider>] | account rm|use <name>")
            return 1
        try:
            if action == "add":
                acct = _settings.add_account(name, provider=provider or "anthropic")
                print(f"created account '{acct.name}' (provider {acct.provider})")
                print(f"next: `tdreport --ai-account {acct.name} set-key` and `set-model`")
            elif action == "rm":
                if _settings.remove_account(name):
                    print(f"removed account '{name}' and its stored key")
                else:
                    print(f"no such account '{name}'")
                    return 1
            else:
                print(f"default AI account is now '{_settings.set_default_account(name)}'")
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        return 0

    # --- per-repo settings: `tdreport repo <name> [<field> <value>]` ---
    if args.target == "repo":
        from ufo_tdkit_report import settings_ui

        if not args.rest:
            print(settings_ui.render_settings(args.ai_account))
            return 0
        name = args.rest[0]
        entry = _registry.entry(name)
        if not entry:
            print(f"error: no registered repo '{name}' — see `tdreport ls`")
            return 1
        field = args.rest[1] if len(args.rest) > 1 else ""
        value = " ".join(args.rest[2:]) if len(args.rest) > 2 else ""

        if not field:  # show what this repo resolves to, and why
            resolved = _settings.resolve_ai_settings(repo=entry["path"])
            print(f"{name}: {entry['path']}\n")
            overrides = {k: v for k, v in entry.items() if k != "path"}
            print(f"  overrides   {overrides or '(none)'}")
            print(f"  account     {resolved.account}")
            print(f"  provider    {resolved.provider_name}")
            print(f"  model       {resolved.model or '(not set)'}")
            print(f"  language    {resolved.language}")
            print(f"  max tokens  {resolved.max_tokens}")
            print(f"  key         {_settings.masked_key(resolved.account)}")
            return 0

        if field == "clear":
            fields = [value] if value else list(_registry.OVERRIDE_KEYS)
            _registry.add(name, entry["path"], **{f: None for f in fields})
            print(f"'{name}' now inherits {', '.join(fields)} from its account")
            return 0
        if field in ("max-tokens", "max_tokens"):
            cap = _parse_token_cap(value)
            if cap is None:
                return 1
            _registry.add(name, entry["path"], max_tokens=cap)
            if cap:
                print(f"'{name}' max tokens: {cap}")
            else:
                print(f"'{name}' now inherits max tokens from its account")
            return 0
        if field in ("grounding", "strict_grounding"):
            strict = _parse_strictness(value)
            if strict is None:
                print(f"error: expected 'strict' or 'warn', got '{value}'")
                return 1
            _registry.add(name, entry["path"], strict_grounding=strict)
            print(f"'{name}' grounding: {'strict' if strict else 'warn'}")
            return 0
        if field not in _registry.OVERRIDE_KEYS:
            print(f"error: unknown field '{field}' (known: {', '.join(_registry.OVERRIDE_KEYS)}, clear)")
            return 1
        if not value:
            print(f"error: usage: tdreport repo {name} {field} <value>")
            return 1
        try:
            # Validate before writing: an unknown account or provider is a typo, not a setting.
            if field == "account":
                _settings.get_account(value)
            elif field == "provider":
                from ufo_tdkit_report.providers import get_provider

                get_provider(value)
            _registry.add(name, entry["path"], **{field: value})
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        print(f"'{name}' {field}: {value}")
        return 0

    # --- binding: `tdreport bind <account> [<repo>]` ---
    if args.target == "bind":
        from ufo_tdkit_report.commit import resolve_repo

        if not args.rest:
            print("error: usage: tdreport bind <account> [<repo>]")
            return 1
        account, selector = args.rest[0], (args.rest[1] if len(args.rest) > 1 else None)
        try:
            _settings.get_account(account)  # fail before touching the registry
            repo = resolve_repo(selector)
        except (NarratorError, RuntimeError) as exc:
            print(f"error: {exc}")
            return 1
        name = _registry.name_for_path(repo) or os.path.basename(repo)
        _registry.add(name, repo, account=account)
        print(f"'{name}' ({repo}) now uses AI account '{account}'")
        return 0

    # --- provider: `tdreport set-provider [<name>]` (menu when omitted) ---
    if args.target == "set-provider":
        try:
            current = _settings.resolve_ai_settings(account=account_name).provider_name
        except NarratorError as exc:
            print(f"error: {exc}")
            return 1
        if args.rest:
            chosen = args.rest[0]
        elif not sys.stdin.isatty():
            print(f"current AI provider: {current}")
            print("error: usage: tdreport set-provider <name> (no TTY to show the menu)")
            return 1
        else:
            chosen = _choose_provider(current)
            if not chosen:
                print(f"unchanged: {current}")
                return 0
        try:
            _settings.update_account(account_name, provider=chosen)
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        resolved = _settings.resolve_ai_settings(account=account_name)
        print(f"AI provider for account '{account_name}' set to {chosen}")
        if not resolved.model:
            print("next: pick a model with `tdreport set-model`")
        if resolved.provider.requires_key and not resolved.api_key:
            print("next: store a key with `tdreport set-key`")
        return 0

    # --- endpoint: `tdreport set-url <base-url>` (custom / non-default local hosts) ---
    if args.target == "set-url":
        resolved = _settings.resolve_ai_settings(account=account_name)
        if args.rest:
            chosen = args.rest[0]
        elif not sys.stdin.isatty():
            print(f"current base URL: {resolved.base_url or '(provider default)'}")
            print("error: usage: tdreport set-url <base-url> (no TTY to prompt)")
            return 1
        else:
            try:
                chosen = input(f"Base URL [{resolved.base_url}]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
        try:
            _settings.update_account(account_name, base_url=chosen)
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        shown = chosen or "(provider default)"
        print(f"base URL for account '{account_name}' set to {shown}")
        return 0

    # --- completion cap: `tdreport set-max-tokens [<n>]` ---
    if args.target == "set-max-tokens":
        from ufo_tdkit_report.narrator import DEFAULT_MAX_TOKENS

        current = _settings.resolve_ai_settings(account=account_name).max_tokens
        if args.rest:
            chosen = _parse_token_cap(args.rest[0])
            if chosen is None:
                return 1
        elif not sys.stdin.isatty():
            print(f"current max tokens: {current}")
            print("error: usage: tdreport set-max-tokens <n> (no TTY to prompt)")
            return 1
        else:
            answer = _prompt_line(
                f"Completion cap in tokens, 0 for the built-in {DEFAULT_MAX_TOKENS} [{current}]: "
            )
            if answer is None:
                print(f"unchanged: {current}")
                return 0
            chosen = _parse_token_cap(answer) if answer.strip() else current
            if chosen is None:
                return 1
        try:
            _settings.update_account(account_name, max_tokens=chosen)
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        resolved = _settings.resolve_ai_settings(account=account_name).max_tokens
        print(f"max tokens for account '{account_name}' set to {resolved}"
              f"{' (the built-in default)' if not chosen else ''}")
        print("(this covers the WHOLE completion — a reasoning model spends the same "
              "budget on thinking and on the answer)")
        return 0

    # --- prose language: `tdreport set-lang [<language>]` ---
    if args.target == "set-lang":
        current = _settings.resolve_ai_settings(account=account_name).language
        if args.rest:
            chosen = " ".join(args.rest)
        elif not sys.stdin.isatty():
            print(f"current AI language: {current}")
            print("error: usage: tdreport set-lang <language> (no TTY to prompt)")
            return 1
        else:
            try:
                chosen = input(f"Language for AI prose [{current}]: ").strip() or current
            except (EOFError, KeyboardInterrupt):
                print()
                print(f"unchanged: {current}")
                return 0
        try:
            _settings.update_account(account_name, language=chosen)
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        print(f"AI prose language for account '{account_name}' set to {chosen}")
        print("(the deterministic facts, headings and footer stay English by design)")
        return 0

    # --- grounding strictness: `tdreport set-grounding strict|warn` ---
    if args.target == "set-grounding":
        current = "strict" if _settings.resolve_ai_settings(account=account_name).strict_grounding else "warn"
        answer = args.rest[0] if args.rest else None
        if answer is None:
            if not sys.stdin.isatty():
                print(f"current grounding: {current}")
                print("error: usage: tdreport set-grounding strict|warn (no TTY to prompt)")
                return 1
            answer = _prompt_line(f"Grounding for account '{account_name}' — strict or warn [{current}]: ")
            if answer is None:
                return 0
            answer = answer or current
        strict = _parse_strictness(answer)
        if strict is None:
            print(f"error: expected 'strict' or 'warn', got '{answer}'")
            return 1
        _settings.update_account(account_name, strict_grounding=strict)
        print(f"grounding for account '{account_name}': {'strict' if strict else 'warn'}")
        if strict:
            print("  a narration whose tokens the facts do not support will now be refused")
        return 0

    # --- model preference: `tdreport set-model [<model-id>]` (menu when omitted) ---
    if args.target == "set-model":
        try:
            resolved = _settings.resolve_ai_settings(account=account_name)
        except NarratorError as exc:
            print(f"error: {exc}")
            return 1
        current = resolved.model
        if args.rest:
            chosen = args.rest[0]
        elif not sys.stdin.isatty():
            print(f"current AI model: {current}")
            print("error: usage: tdreport set-model <model-id> (no TTY to show the menu)")
            return 1
        else:
            # Live list from the account's provider when reachable, its hint list otherwise —
            # and say which one this is, so a short list is not read as "that is all there is".
            from ufo_tdkit_report import settings_ui

            models, _live = settings_ui.models_for(resolved)
            if not models:
                print(f"No model list available for {resolved.provider_name} — type an id.")
            chosen = _choose_model(models, current)
            if not chosen:
                print(f"unchanged: {current}")
                return 0
        try:
            _settings.update_account(account_name, model=chosen)
        except (NarratorError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        print(f"AI model for account '{account_name}' set to {chosen} (stored in {_settings.settings_path()})")
        return 0

    # Per-run AI overrides are passed down UNRESOLVED: resolution happens once, inside the
    # narrator, where the target repo's own account/model/language binding is also known.
    ai_opts = dict(
        model=args.ai_model, provider=args.ai_provider, language=args.ai_lang,
        account=args.ai_account, strict_grounding=args.strict_grounding,
    )
    if args.ai_max_tokens:
        ai_opts["max_tokens"] = args.ai_max_tokens

    # --- committed-history modes: a range or --notes (repo = --repo / cwd) ---
    if args.notes or _is_range(args.target):
        if args.notes:
            from ufo_tdkit_report import aggregate_range
            from ufo_tdkit_report.gitsource import GitSource

            spec = args.target
            if not spec:
                tag = GitSource(args.repo).latest_tag()
                if not tag:
                    print("error: --notes needs a range or a tagged repo (no tags found)")
                    return 1
                spec = f"{tag}..HEAD"
            elif ".." not in spec:
                spec = f"{spec}..HEAD"
            report = aggregate_range(args.repo, spec, threshold=args.threshold, profile=args.profile)
        else:
            from ufo_tdkit_report import extract_facts

            report = extract_facts(args.repo, args.target, threshold=args.threshold, profile=args.profile)

        try:
            narrating = _narration_wanted(args, ai_opts, repo=args.repo)
        except NarratorError as exc:
            print(f"error: {exc}")
            return 1
        if narrating:
            from ufo_tdkit_report import narrate

            try:
                print(narrate(report, repo=args.repo, **ai_opts))
                return 0
            except NarratorError as exc:
                # The call was attempted and failed — a bad key, an outage, a refusal. The
                # facts are already extracted and cost nothing, so print the report rather
                # than nothing at all; `--ai` is how a caller says it wants the failure.
                if args.require_ai:
                    print(f"error: AI narration failed: {exc}")
                    return 1
                print(f"note: AI narration failed ({exc}); deterministic report follows.",
                      file=sys.stderr)
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json_output else report.render_text())
        return 0

    # --- working-tree commit assistant (repo selector: cwd / name / path) ---
    from ufo_tdkit_report.commit import commit as do_commit
    from ufo_tdkit_report.commit import (
        draft_state,
        inspect,
        legacy_draft_dir,
        report_path,
        reusable,
    )

    # `tdreport commit` (cwd) or `tdreport <repo> commit`
    if args.target == "commit" and not args.rest:
        selector, action = None, "commit"
    else:
        selector, action = args.target, (args.rest[0] if args.rest else None)

    # Addressed by path? Remember it, so the short name works from now on.
    if selector and os.path.exists(selector):
        try:
            selector = _auto_register(selector)
        except RuntimeError as exc:
            print(f"error: {exc}")
            return 1

    if action == "commit":
        return _do_commit(selector, args, ai_opts, do_commit)

    try:
        wants_ai = _narration_wanted(args, ai_opts, repo=_repo_path(selector))
        # Read the draft's state BEFORE inspect writes over it, so the note below can say
        # which of the two reasons kept it. Reusing silently would be the same invisible
        # difference the deterministic report exists to remove.
        before = draft_state(_repo_path(selector)) if _repo_path(selector) else None
        try:
            repo, text, has_changes = inspect(
                selector, ai=wants_ai, regenerate=args.regenerate, **ai_opts,
            )
        except NarratorError as exc:
            if args.require_ai or not wants_ai:
                raise
            # Same bargain as the range path: the draft is worth having without the prose.
            # Re-running costs another extraction, never another model call.
            print(f"note: AI narration failed ({exc}); drafting without it.", file=sys.stderr)
            repo, text, has_changes = inspect(
                selector, ai=False, regenerate=args.regenerate, **ai_opts,
            )
    except (NarratorError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1
    state = draft_state(repo)
    if state.edited and not args.regenerate:
        print("note: showing your edited draft, not a fresh one "
              "(`--regenerate` to redraft from the current changes)")
    elif before is not None and reusable(
        before, ai=wants_ai, regenerate=args.regenerate,
        overridden=any(v is not None for v in ai_opts.values()),
    ):
        print("note: reusing the existing draft — nothing it describes has changed "
              "(`--regenerate` to redraft anyway)")
    print(text)
    if not has_changes:
        return 0
    print(f"--- drafted in {report_path(repo)} (edit if needed) ---")
    stale_dir = legacy_draft_dir(repo)
    if stale_dir:
        # An older version kept the draft here and added a line to this repo's .gitignore
        # to hide it. Neither is used any more, and neither is ours to delete.
        print(f"note: {stale_dir} is left over from an older tdreport and can be removed,")
        print("      along with the `.tdreport/` line it added to this repo's .gitignore")
    if _confirm("Commit this?", assume_yes=args.yes):
        return _do_commit(selector, args, ai_opts, do_commit)
    hint = selector or "."
    print(f"Not committed. Run `tdreport {hint} commit` when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
