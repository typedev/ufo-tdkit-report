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


def _is_range(arg: str | None) -> bool:
    """True if ``arg`` is a commit range (``a..b``) → committed-history modes.

    Everything else (a registry name, a path, None) is a repo selector for the
    working-tree commit assistant.
    """
    return bool(arg) and ".." in arg


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tdreport",
        description="Deterministic UFO/designspace source-change extractor & narrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tdreport                       # commit assistant: draft a message for the cwd repo's working tree
  tdreport --ai-note             # same, narrated by a grounded AI
  tdreport commit                # commit the cwd working tree with the drafted message
  tdreport myfont                # commit assistant for a registered repo (see `add`)
  tdreport myfont commit         # commit a registered repo's working tree
  tdreport ~/fonts/MyFont        # commit assistant for an explicit repo path
  tdreport add myfont ~/fonts/MyFont   # register a name -> repo path
  tdreport set-key sk-ant-...     # store the Anthropic API key (owner-only) for --ai-note
  tdreport set-model              # pick the --ai-note model from a menu of available ones
  tdreport v2.005..v2.006        # committed-history report for a range (cwd repo)
  tdreport --notes v2.005..HEAD  # aggregate every commit in the range into release notes
        """,
    )
    parser.add_argument(
        "target", nargs="?",
        help="repo selector (name/path), a commit range, 'add', 'set-key', or 'set-model'",
    )
    parser.add_argument(
        "rest", nargs="*",
        help="'commit'; for 'add': <name> <path>; for 'set-key': <api-key>; for 'set-model': <model-id>",
    )
    parser.add_argument("--repo", default=".", help="git repo for committed-history modes (default: cwd)")
    parser.add_argument("--notes", action="store_true", help="aggregate every commit in the range into notes")
    parser.add_argument("--profile", help="path to a build-profile YAML to record in the report header")
    parser.add_argument("--threshold", type=int, default=12, help="fold detail into stats above this count")
    parser.add_argument("--json", dest="json_output", action="store_true", help="emit the report as JSON")
    parser.add_argument(
        "--ai-note", action="store_true",
        help="add a grounded AI narrative (opt-in; needs a key via `tdreport set-key`; never publishes)",
    )
    from ufo_tdkit_report.narrator import DEFAULT_MODEL

    parser.add_argument(
        "--ai-model", default=None,
        help=f"model for --ai-note, overriding `tdreport set-model` (built-in default: {DEFAULT_MODEL})",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="auto-confirm the 'commit this?' prompt")

    from ufo_tdkit_report import __version__

    # The version is stamped into report footers and commit trailers; make it queryable.
    parser.add_argument("--version", action="version", version=f"tdreport {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    import json

    from ufo_tdkit_report import NarratorError

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

    # --- key storage: `tdreport set-key [<key>]` (single owner-only home for the AI key) ---
    if args.target == "set-key":
        from ufo_tdkit_report.narrator import store_api_key

        # An inline key lands in shell history; prefer prompting/stdin when omitted.
        key = args.rest[0] if args.rest else _read_secret("Anthropic API key: ")
        try:
            path = store_api_key(key)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"stored Anthropic API key in {path} (permissions 0600)")
        return 0

    # The narration model, resolved once: --ai-model > `tdreport set-model` > built-in default.
    from ufo_tdkit_report.narrator import resolve_model

    # --- model preference: `tdreport set-model [<model-id>]` (menu when omitted) ---
    if args.target == "set-model":
        from ufo_tdkit_report.narrator import list_models, resolve_api_key, store_model

        current = resolve_model()
        if args.rest:
            chosen = args.rest[0]
        elif not sys.stdin.isatty():
            print(f"current AI model: {current}")
            print("error: usage: tdreport set-model <model-id> (no TTY to show the menu)")
            return 1
        else:
            # Live list when a key is available, the built-in list otherwise.
            chosen = _choose_model(list_models(api_key=resolve_api_key()), current)
            if not chosen:
                print(f"unchanged: {current}")
                return 0
        try:
            path = store_model(chosen)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"AI model set to {chosen} (stored in {path})")
        return 0

    model = resolve_model(explicit=args.ai_model)

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

        if args.ai_note:
            from ufo_tdkit_report import narrate
            from ufo_tdkit_report.narrator import resolve_api_key

            try:
                print(narrate(report, model=model, api_key=resolve_api_key()))
            except NarratorError as exc:
                print(f"error: AI narration failed: {exc}")
                return 1
            return 0
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json_output else report.render_text())
        return 0

    # --- working-tree commit assistant (repo selector: cwd / name / path) ---
    from ufo_tdkit_report.commit import REPORT_RELPATH, inspect
    from ufo_tdkit_report.commit import commit as do_commit

    # `tdreport commit` (cwd) or `tdreport <repo> commit`
    if args.target == "commit" and not args.rest:
        selector, action = None, "commit"
    else:
        selector, action = args.target, (args.rest[0] if args.rest else None)

    if action == "commit":
        try:
            rc, msg = do_commit(selector, ai=args.ai_note, model=model)
        except (NarratorError, RuntimeError) as exc:
            print(f"error: {exc}")
            return 1
        print(msg)
        return rc

    try:
        repo, text, has_changes = inspect(selector, ai=args.ai_note, model=model)
    except (NarratorError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1
    print(text)
    if not has_changes:
        return 0
    print(f"--- drafted in {os.path.join(repo, REPORT_RELPATH)} (edit if needed) ---")
    if _confirm("Commit this?", assume_yes=args.yes):
        try:
            rc, msg = do_commit(selector, ai=args.ai_note, model=model)
        except (NarratorError, RuntimeError) as exc:
            print(f"error: {exc}")
            return 1
        print(msg)
        return rc
    hint = selector or "."
    print(f"Not committed. Run `tdreport {hint} commit` when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
