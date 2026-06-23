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
  tdreport v2.005..v2.006        # committed-history report for a range (cwd repo)
  tdreport --notes v2.005..HEAD  # aggregate every commit in the range into release notes
        """,
    )
    parser.add_argument("target", nargs="?", help="repo selector (name/path), a commit range, or 'add'")
    parser.add_argument("rest", nargs="*", help="'commit', or for 'add': <name> <path>")
    parser.add_argument("--repo", default=".", help="git repo for committed-history modes (default: cwd)")
    parser.add_argument("--notes", action="store_true", help="aggregate every commit in the range into notes")
    parser.add_argument("--profile", help="path to a build-profile YAML to record in the report header")
    parser.add_argument("--threshold", type=int, default=12, help="fold detail into stats above this count")
    parser.add_argument("--json", dest="json_output", action="store_true", help="emit the report as JSON")
    parser.add_argument(
        "--ai-note", action="store_true",
        help="add a grounded AI narrative (opt-in; needs ANTHROPIC_API_KEY; never publishes)",
    )
    parser.add_argument("--ai-model", default="claude-sonnet-4-6", help="model for --ai-note")
    parser.add_argument("-y", "--yes", action="store_true", help="auto-confirm the 'commit this?' prompt")
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
                print(narrate(report, model=args.ai_model, api_key=resolve_api_key(args.repo)))
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
            rc, msg = do_commit(selector, ai=args.ai_note, model=args.ai_model)
        except (NarratorError, RuntimeError) as exc:
            print(f"error: {exc}")
            return 1
        print(msg)
        return rc

    try:
        repo, text, has_changes = inspect(selector, ai=args.ai_note, model=args.ai_model)
    except (NarratorError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1
    print(text)
    if not has_changes:
        return 0
    print(f"--- drafted in {os.path.join(repo, REPORT_RELPATH)} (edit if needed) ---")
    if _confirm("Commit this?", assume_yes=args.yes):
        try:
            rc, msg = do_commit(selector, ai=args.ai_note, model=args.ai_model)
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
