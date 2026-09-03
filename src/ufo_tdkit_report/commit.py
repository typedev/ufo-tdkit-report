"""Commit assistant — document uncommitted changes and commit.

`tdreport` (or `tdreport <repo>`) inspects the working tree vs HEAD, prints a drafted
commit message and writes it to an editable file; `tdreport <repo> commit` commits with
that file (generating it first if absent). Deterministic by default; `--ai-note` runs the
grounded commit narrator. The repo is the cwd, a registered name, or an explicit path.

The draft lives in the tool's own config directory, NOT inside the font repository. It
used to sit in `<repo>/.tdreport/`, which meant appending a line to the repository's
`.gitignore` — a silent edit to a tracked file in someone else's project, to protect
against a problem the tool itself had created. Nothing tdreport-related is written inside
a repository now; the same rule the accounts and bindings already follow.

Not a temp directory either: between drafting and committing an hour can pass, and
`/tmp` is cleared on reboot. Re-generating a deterministic draft is free, but an
`--ai-note` draft cost a paid model call.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from ufo_tdkit_report.config import config_dir
from ufo_tdkit_report.render import render_commit_message
from ufo_tdkit_report.service import extract_working_facts

DRAFT_NAME = "commit-message.md"
# Where the draft used to live, inside the repository. Only looked for now, to tell the
# owner it can go.
LEGACY_RELDIR = ".tdreport"


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


def _draft_key(repo: str) -> str:
    """A readable, collision-free directory name for one repository.

    The registered name when there is one; otherwise the basename plus a short digest of
    the absolute path, so two repos called `Sans` in different places never share a draft.
    """
    from ufo_tdkit_report import registry

    name = registry.name_for_path(repo)
    if name:
        return re.sub(r"[^A-Za-z0-9._-]", "_", name)
    import hashlib

    resolved = str(Path(repo).expanduser().resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(resolved)) or "repo"
    return f"{base}-{digest}"


def report_path(repo: str) -> Path:
    """Where this repository's draft commit message lives — in the config dir, not the repo."""
    return config_dir() / "drafts" / _draft_key(repo) / DRAFT_NAME


def legacy_draft_dir(repo: str) -> Path | None:
    """The old in-repo `.tdreport/` if this repository still has one, else None.

    Returned rather than deleted: it is the owner's repository, and their `.gitignore`
    still carries the line an older version added. The CLI says so; removing it is theirs.
    """
    path = Path(repo) / LEGACY_RELDIR
    return path if path.is_dir() else None


def inspect(
    target: str | None = None,
    *,
    ai: bool = False,
    model: str | None = None,
    provider: str | None = None,
    language: str | None = None,
    account: str | None = None,
    strict_grounding: bool | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str, bool]:
    """Inspect uncommitted changes; write the drafted message to the report file.

    Returns ``(repo, message_text, has_changes)``. Does not print — the CLI does.
    Unset AI arguments resolve through :func:`settings.resolve_ai_settings`, and the
    repo path is handed down so this repository's own account/model/language binding
    applies; they are only consulted when ``ai`` is set.
    """
    repo = resolve_repo(target)
    report = extract_working_facts(repo)
    has_changes = bool(report.folded_facts)

    if ai:
        from ufo_tdkit_report.narrator import narrate_commit

        # Everything unset resolves inside narrate_commit, against THIS repo's binding.
        extra = {"max_tokens": max_tokens} if max_tokens else {}
        text = narrate_commit(
            report, repo=repo, model=model, provider=provider, language=language,
            account=account, strict_grounding=strict_grounding, **extra
        )
    else:
        text = render_commit_message(report)

    path = report_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return repo, text, has_changes


def commit(
    target: str | None = None,
    *,
    ai: bool = False,
    model: str | None = None,
    provider: str | None = None,
    language: str | None = None,
    account: str | None = None,
    strict_grounding: bool | None = None,
    max_tokens: int | None = None,
) -> tuple[int, str]:
    """Commit the working tree using the drafted message (generating it if absent).

    Returns ``(exit_code, message)``.
    """
    repo = resolve_repo(target)

    # Nothing staged/unstaged/untracked → nothing to commit (check before touching .gitignore).
    status = _git(repo, "status", "--porcelain")
    if not (status.stdout or "").strip():
        return 0, "nothing to commit — working tree is clean"

    path = report_path(repo)
    if not path.is_file():
        inspect(target, ai=ai, model=model, provider=provider, language=language,
                account=account, strict_grounding=strict_grounding, max_tokens=max_tokens)

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
