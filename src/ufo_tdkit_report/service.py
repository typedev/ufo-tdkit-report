"""Orchestrate the report extractor: git -> classify -> rollup -> report.

This is the seam the future releaser/aggregator (issue #4) consumes: it returns a
structured ``SourceReport`` and never prints.
"""

from __future__ import annotations

from pathlib import Path

from ufo_tdkit_report.classify import ChangedFile, classify_change, file_note
from ufo_tdkit_report.gitsource import GitSource
from ufo_tdkit_report.model import SourceReport
from ufo_tdkit_report.paths import classify_path
from ufo_tdkit_report.rollup import DEFAULT_THRESHOLD, fold_facts


def _decode(blob: bytes | None) -> str | None:
    if blob is None:
        return None
    return blob.decode("utf-8", "replace")


def _resolve_profile(repo: str, profile: str | None):
    """Return ``(profile_name, profile_options_dict)`` for the report header, or (None, None).

    ``profile`` is an optional path to a build-profile YAML to record in the header
    (relative paths resolve against the repo). ufo-tdkit-report is build-tool-agnostic:
    it does not resolve stored profile names — a consumer that has a profile database
    passes the YAML path (or its options) directly.
    """
    if not profile:
        return (None, None)

    import yaml

    path = Path(profile)
    if not path.is_absolute():
        path = Path(repo) / profile
    if path.exists() and path.suffix in (".yaml", ".yml"):
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return (profile, loaded)
        except Exception:
            pass
    return (profile, None)


def extract_facts(
    repo: str | Path,
    commit_spec: str | None = None,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    profile: str | None = None,
    family: str | None = None,
    schema=None,
) -> SourceReport:
    """Extract deterministic source-change facts for a commit (range).

    ``schema`` (optional, duck-typed) is injected by a build tool to enrich
    build-profile facts with grounded consequences; None keeps the bare line.
    """
    repo = str(repo)
    git = GitSource(repo)
    base, head = git.resolve_spec(commit_spec)
    spec = commit_spec or f"{base}..{head}"

    facts, changed_file_count = _extract_raw(git, base, head, family=family)

    folded = fold_facts(facts, threshold=threshold, schema=schema)
    profile_name, profile_options = _resolve_profile(repo, profile)

    return SourceReport(
        commit_spec=spec,
        folded_facts=folded,
        raw_fact_count=len(facts),
        changed_file_count=changed_file_count,
        profile_name=profile_name,
        profile_options=profile_options,
    )


def _extract_raw(git: GitSource, base: str, head: str, *, family: str | None = None):
    """Return ``(raw_facts, changed_file_count)`` for a ``base..head`` diff.

    Shared by ``extract_facts`` (single diff) and the aggregator (per commit).
    """
    changed = git.list_changed(base, head)
    relevant = [cf for cf in changed if classify_path(cf.path) is not None]

    specs: list[str] = []
    for cf in relevant:
        if cf.old_spec:
            specs.append(cf.old_spec)
        if cf.new_spec:
            specs.append(cf.new_spec)
    blobs = git.read_blobs(specs)

    facts = []
    classified: set[str] = set()
    for cf in relevant:
        old_blob = _decode(blobs.get(cf.old_spec)) if cf.old_spec else None
        new_blob = _decode(blobs.get(cf.new_spec)) if cf.new_spec else None
        produced = classify_change(ChangedFile(cf.path, cf.status, old_blob, new_blob), family=family)
        facts.extend(produced)
        if produced:
            classified.add(cf.path)
    # T3: every changed file that produced no semantic fact (unknown type, whole-file
    # add/remove, or no semantic delta) still surfaces as a bare constatation.
    for cf in changed:
        if cf.path not in classified:
            facts.append(file_note(cf.path, cf.status))
    return facts, len(changed)


def extract_working_facts(
    repo: str | Path,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    family: str | None = None,
    schema=None,
) -> SourceReport:
    """Extract facts for the **uncommitted** working tree (HEAD ↔ disk).

    ``schema`` (optional, duck-typed) enriches build-profile facts when injected.
    """
    repo = str(repo)
    git = GitSource(repo)
    changes = git.list_working_changes()  # [(path, status_code), ...]
    relevant = [(p, st) for (p, st) in changes if classify_path(p) is not None]

    old_specs = [f"HEAD:{p}" for (p, _) in relevant]
    blobs = git.read_blobs(old_specs)

    facts = []
    classified: set[str] = set()
    for path, status in relevant:
        old_blob = _decode(blobs.get(f"HEAD:{path}"))  # None when the file is new vs HEAD
        disk = Path(repo) / path
        new_blob = disk.read_text(encoding="utf-8", errors="replace") if disk.is_file() else None
        produced = classify_change(ChangedFile(path, status, old_blob, new_blob), family=family)
        facts.extend(produced)
        if produced:
            classified.add(path)
    # T3: surface every other changed tracked file as a bare constatation.
    for path, status in changes:
        if path not in classified:
            facts.append(file_note(path, status))

    folded = fold_facts(facts, threshold=threshold, schema=schema)
    return SourceReport(
        commit_spec="working tree",
        folded_facts=folded,
        raw_fact_count=len(facts),
        changed_file_count=len(changes),
    )


def commit_facts(repo: str, sha: str, *, family: str | None = None):
    """Raw facts introduced by a single commit (``sha~1..sha``).

    The storage seam for the aggregator: this currently re-extracts live, but a future
    ``git notes`` / trailer cache can be slotted in here without touching callers.
    """
    git = GitSource(str(repo))
    facts, _ = _extract_raw(git, f"{sha}~1", sha, family=family)
    return facts
