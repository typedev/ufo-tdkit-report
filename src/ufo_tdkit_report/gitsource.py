"""Git plumbing for the report extractor (issue #5, phase 1).

The only module that shells out. ``runner`` is injectable so the layer can be
unit-tested with canned stdout, while integration tests use a real temp repo.
All commands use ``git -C <repo>`` (no reliance on the process cwd).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class GitChangedFile:
    """A file changed between two revisions, with blob *specs* (not yet read)."""

    path: str
    status: str  # "A" | "M" | "D" | "R..."
    old_spec: str | None  # "<base>:<path>" or None for additions
    new_spec: str | None  # "<head>:<path>" or None for deletions


@dataclass(frozen=True)
class CommitInfo:
    """A commit in a range: full sha + subject line."""

    sha: str
    subject: str

    @property
    def short(self) -> str:
        return self.sha[:7]


class GitSource:
    """Resolve a commit spec and fetch changed files + blobs from a git repo."""

    def __init__(self, repo: str, runner=subprocess.run):
        self.repo = str(repo)
        self._runner = runner

    def _run(self, *args: str) -> bytes:
        result = self._runner(
            ["git", "-C", self.repo, *args],
            capture_output=True,
            check=False,
        )
        return result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode()

    def resolve_spec(self, spec: str | None) -> tuple[str, str]:
        """Normalize a commit spec to ``(base, head)``.

        None -> ``HEAD~1..HEAD``; ``"abc"`` -> ``abc~1..abc``; ``"A..B"`` -> ``A, B``.
        """
        if not spec:
            return ("HEAD~1", "HEAD")
        if ".." in spec:
            base, head = spec.split("..", 1)
            return (base or "HEAD~1", head or "HEAD")
        return (f"{spec}~1", spec)

    def list_commits(self, base: str, head: str) -> list[CommitInfo]:
        """Commits in ``base..head`` (oldest first) as ``CommitInfo`` (sha + subject)."""
        out = self._run("log", "--reverse", "--format=%H%x00%s", f"{base}..{head}")
        text = out.decode("utf-8", "replace")
        commits: list[CommitInfo] = []
        for line in text.splitlines():
            if not line:
                continue
            sha, _, subject = line.partition("\0")
            commits.append(CommitInfo(sha=sha, subject=subject))
        return commits

    def latest_tag(self) -> str | None:
        """Most recent tag reachable from HEAD, or None if the repo has no tags."""
        proc = self._runner(
            ["git", "-C", self.repo, "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            check=False,
        )
        if getattr(proc, "returncode", 1) != 0:
            return None
        out = proc.stdout if isinstance(proc.stdout, bytes) else proc.stdout.encode()
        tag = out.decode("utf-8", "replace").strip()
        return tag or None

    def list_changed(self, base: str, head: str) -> list[GitChangedFile]:
        """Return changed files between ``base`` and ``head`` (NUL-delimited parse)."""
        out = self._run("diff", "--name-status", "-z", base, head).decode("utf-8", "replace")
        fields = out.split("\0")
        changed: list[GitChangedFile] = []
        i = 0
        while i < len(fields):
            status = fields[i]
            if not status:
                i += 1
                continue
            code = status[0]
            if code == "R":
                # Rename: status, old path, new path.
                old_path, new_path = fields[i + 1], fields[i + 2]
                changed.append(
                    GitChangedFile(new_path, status, f"{base}:{old_path}", f"{head}:{new_path}")
                )
                i += 3
                continue
            path = fields[i + 1]
            old_spec = None if code == "A" else f"{base}:{path}"
            new_spec = None if code == "D" else f"{head}:{path}"
            changed.append(GitChangedFile(path, status, old_spec, new_spec))
            i += 2
        return changed

    def list_working_changes(self) -> list[str]:
        """Repo-relative paths changed in the working tree vs HEAD (staged + unstaged + untracked).

        Parses ``git status --porcelain=v1 -z --untracked-files=all``. Rename/copy entries
        contribute both the new and the original path (the caller diffs each against HEAD).
        """
        out = self._run("status", "--porcelain=v1", "-z", "--untracked-files=all").decode(
            "utf-8", "replace"
        )
        tokens = out.split("\0")
        paths: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if not tok or len(tok) < 4:
                i += 1
                continue
            code = tok[0:2]
            path = tok[3:]
            if code and code[0] in ("R", "C"):
                # -z rename/copy: this token holds the new path, the next holds the original.
                orig = tokens[i + 1] if i + 1 < len(tokens) else ""
                if orig:
                    paths.append(orig)
                paths.append(path)
                i += 2
                continue
            paths.append(path)
            i += 1
        return paths

    def read_blobs(self, specs: list[str]) -> dict[str, bytes]:
        """Fetch many blobs in one ``git cat-file --batch`` call. Missing -> absent."""
        specs = [s for s in specs if s]
        if not specs:
            return {}
        data = ("\n".join(specs) + "\n").encode()
        proc = self._runner(
            ["git", "-C", self.repo, "cat-file", "--batch"],
            input=data,
            capture_output=True,
            check=False,
        )
        out = proc.stdout if isinstance(proc.stdout, bytes) else proc.stdout.encode()
        result: dict[str, bytes] = {}
        i = 0
        for spec in specs:
            nl = out.find(b"\n", i)
            if nl == -1:
                break
            header = out[i:nl].decode("utf-8", "replace")
            if header.endswith("missing"):
                i = nl + 1
                continue
            try:
                size = int(header.split()[2])
            except (IndexError, ValueError):
                break
            body = out[nl + 1 : nl + 1 + size]
            result[spec] = body
            i = nl + 1 + size + 1  # skip trailing newline
        return result

    def blob_exists(self, spec: str) -> bool:
        """True if ``<rev>:<path>`` resolves to a blob (used for profile-in-repo check)."""
        proc = self._runner(
            ["git", "-C", self.repo, "cat-file", "-e", spec],
            capture_output=True,
            check=False,
        )
        return getattr(proc, "returncode", 1) == 0
