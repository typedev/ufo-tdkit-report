"""Commit assistant — document uncommitted changes and commit.

`tdreport` (or `tdreport <repo>`) inspects the working tree vs HEAD, prints a drafted
commit message and writes it to an editable file in the project; `tdreport <repo> commit`
commits with that file (generating it first if absent). Deterministic by default;
`--ai-note` runs the grounded commit narrator. The repo is the cwd, a registered name,
or an explicit path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ufo_tdkit_report.render import render_commit_message
from ufo_tdkit_report.service import extract_working_facts

REPORT_RELPATH = os.path.join(".tdreport", "commit-message.md")


def _git(repo: str, *args: str, input_text: str | None = None):
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, input=input_text, check=False
    )


def resolve_repo(target: str | None = None) -> str:
    """Git root for a target: None -> cwd; a registered name -> its path; else a path.

    A bare target that is neither a registered name nor an existing path is an ERROR —
    we never silently fall back to the cwd repo (that would report on the wrong project).
    """
    if not target:
        candidate = "."
    else:
        from ufo_tdkit_report import registry

        registered = registry.resolve(target)
        if registered:
            candidate = registered
        elif os.path.exists(target):
            candidate = target
        else:
            raise RuntimeError(
                f"unknown repo '{target}': not a registered name "
                f"(register it with `tdreport add {target} <path>`) and not an existing path"
            )
    base = candidate if os.path.isdir(candidate) else os.path.dirname(os.path.abspath(candidate))
    if not base:
        base = "."
    proc = _git(base, "rev-parse", "--show-toplevel")
    root = (proc.stdout or "").strip()
    if proc.returncode != 0 or not root:
        raise RuntimeError(f"could not locate a git repository for '{target or base}'")
    return root


def report_path(repo: str) -> Path:
    return Path(repo) / REPORT_RELPATH


def _ensure_gitignored(repo: str) -> None:
    """Make sure `.tdreport/` is gitignored so the draft never gets committed as a file."""
    gitignore = Path(repo) / ".gitignore"
    entry = ".tdreport/"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
        if entry not in existing.split():
            with gitignore.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(entry + "\n")
    except OSError:
        pass


def inspect(target: str | None = None, *, ai: bool = False, model: str | None = None) -> tuple[str, str, bool]:
    """Inspect uncommitted changes; write the drafted message to the report file.

    Returns ``(repo, message_text, has_changes)``. Does not print — the CLI does.
    ``model=None`` resolves through :func:`narrator.resolve_model`; it is only consulted
    when ``ai`` is set.
    """
    repo = resolve_repo(target)
    report = extract_working_facts(repo)
    has_changes = bool(report.folded_facts)

    if ai:
        from ufo_tdkit_report.narrator import narrate_commit, resolve_model
        from ufo_tdkit_report.narrator import resolve_api_key as _resolve_key

        # model=None -> the `tdreport set-model` preference, else the built-in default.
        text = narrate_commit(report, model=resolve_model(explicit=model), api_key=_resolve_key())
    else:
        text = render_commit_message(report)

    _ensure_gitignored(repo)
    path = report_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return repo, text, has_changes


def commit(target: str | None = None, *, ai: bool = False, model: str | None = None) -> tuple[int, str]:
    """Commit the working tree using the drafted message (generating it if absent).

    Returns ``(exit_code, message)``.
    """
    repo = resolve_repo(target)

    # Nothing staged/unstaged/untracked → nothing to commit (check before touching .gitignore).
    status = _git(repo, "status", "--porcelain")
    if not (status.stdout or "").strip():
        return 0, "nothing to commit — working tree is clean"

    _ensure_gitignored(repo)
    path = report_path(repo)
    if not path.is_file():
        inspect(target, ai=ai, model=model)

    _git(repo, "add", "-A")
    commit_msg = path.read_text(encoding="utf-8")
    proc = _git(repo, "commit", "-F", str(path))
    if proc.returncode != 0:
        return 1, f"git commit failed: {(proc.stderr or '').strip()}"

    # Drop the temporary draft now that it is the commit message.
    try:
        path.unlink()
    except OSError:
        pass
    subject = commit_msg.splitlines()[0] if commit_msg.strip() else ""
    return 0, f"committed: {subject}"
