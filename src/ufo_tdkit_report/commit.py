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

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ufo_tdkit_report.config import config_dir
from ufo_tdkit_report.render import render_commit_message
from ufo_tdkit_report.service import extract_working_facts

DRAFT_NAME = "commit-message.md"
STATE_NAME = "draft.json"
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
    """A readable, collision-free, REGISTRATION-INDEPENDENT directory name for a repo.

    Basename plus a short digest of the absolute path: two repos called `Sans` in
    different places never share a draft, and — the reason for the digest rather than the
    registered name — registering a repo does not move its drafts. Keying by the
    registered name orphaned any draft written before registration, silently.
    """
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


@dataclass(frozen=True)
class DraftState:
    """What is known about an existing draft, and whether it can still be trusted.

    Two independent questions, because they have different answers and different costs:

    ``edited``  — the file differs from the text tdreport produced, so a human changed it.
                  Overwriting that silently loses their words, and for an ``--ai-note``
                  draft it also throws away a paid model call.
    ``stale``   — the working tree no longer produces the facts this draft describes.
                  Committing it would put a wrong description of the change into git
                  history, which is the one failure this whole tool exists to prevent.

    Staleness is measured against the FACTS, not the files: an editor re-serializing a
    UFO changes bytes but produces identical facts, and must not invalidate a draft.
    """

    path: Path
    exists: bool = False
    edited: bool = False
    stale: bool = False
    ai: bool = False


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def facts_digest(report) -> str:
    """A stable fingerprint of what a report says. Reuses the byte-stability guarantee."""
    return _digest(json.dumps(report.to_dict(), sort_keys=True, ensure_ascii=False))


def state_path(repo: str) -> Path:
    return report_path(repo).with_name(STATE_NAME)


def _write_state(repo: str, *, facts: str, generated: str, ai: bool) -> None:
    path = state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"facts": facts, "generated": generated, "ai": ai}, indent=2) + "\n",
        encoding="utf-8",
    )


def draft_state(repo: str, report=None) -> DraftState:
    """Inspect the stored draft for ``repo``. Reads only; never writes or prompts."""
    draft = report_path(repo)
    if not draft.is_file():
        return DraftState(path=draft)
    try:
        stored = json.loads(state_path(repo).read_text(encoding="utf-8"))
        text = draft.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        # No sidecar (or unreadable): assume a human owns the file rather than risk
        # overwriting it, and cannot tell whether it is stale.
        return DraftState(path=draft, exists=True, edited=True)
    if report is None:
        report = extract_working_facts(repo)
    return DraftState(
        path=draft,
        exists=True,
        edited=_digest(text) != stored.get("generated"),
        stale=facts_digest(report) != stored.get("facts"),
        ai=bool(stored.get("ai")),
    )


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
    regenerate: bool = False,
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

    # A draft the owner has edited is theirs, not ours to overwrite — re-running to look
    # at the report again must not cost them their words (or a paid narration).
    state = draft_state(repo, report)
    if state.edited and not regenerate:
        return repo, state.path.read_text(encoding="utf-8"), has_changes

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
    _write_state(repo, facts=facts_digest(report), generated=_digest(text), ai=ai)
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
    allow_stale: bool = False,
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
    else:
        # `git add -A` below commits the tree as it is NOW; the draft describes the tree as
        # it was THEN. Shipping the two together writes a wrong description into history.
        state = draft_state(repo)
        if state.stale and not allow_stale:
            hint = " (it was AI-written; add `--ai-note`)" if state.ai else ""
            return 1, (
                f"the working tree changed since this draft was written, so it no longer "
                f"describes what would be committed. Redraft with `tdreport "
                f"{target or '.'}`{hint}, or commit it anyway with --stale-ok.\n"
                f"draft: {path}"
            )

    _git(repo, "add", "-A")
    commit_msg = path.read_text(encoding="utf-8")
    proc = _git(repo, "commit", "-F", str(path))
    if proc.returncode != 0:
        return 1, f"git commit failed: {(proc.stderr or '').strip()}"

    # Drop the temporary draft now that it is the commit message.
    for leftover in (path, state_path(repo)):
        try:
            leftover.unlink()
        except OSError:
            pass
    subject = commit_msg.splitlines()[0] if commit_msg.strip() else ""
    return 0, f"committed: {subject}"
