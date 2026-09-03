"""Tests for the report commit assistant — working tree vs HEAD (issue #5)."""

import subprocess
from pathlib import Path

import pytest

from ufo_tdkit_report import extract_working_facts
from ufo_tdkit_report.cli import _confirm, _is_range
from ufo_tdkit_report.commit import (
    commit,
    inspect,
    legacy_draft_dir,
    report_path,
    resolve_repo,
)
from ufo_tdkit_report.model import FactType, FileKind, FoldedFact, SourceReport
from ufo_tdkit_report.render import render_commit_message


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Drafts live in the config dir now, so every test needs its own."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _glif(name="A", advance=500, points=((0, 0), (10, 10))):
    pts = "".join(f'<point x="{x}" y="{y}" type="line"/>' for x, y in points)
    return (
        f'<glyph name="{name}" format="2"><advance width="{advance}"/>'
        f"<outline><contour>{pts}</contour></outline></glyph>"
    )


def _repo(tmp_path):
    repo = tmp_path / "font"
    glyphs = repo / "MasterRegular.ufo" / "glyphs"
    glyphs.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (10, 10))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    profile = repo / "prof.yaml"
    profile.write_text("path: MasterRegular.ufo\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "profile")
    return repo, glyphs, str(profile)


def test_extract_working_facts_uncommitted(tmp_path):
    repo, glyphs, _ = _repo(tmp_path)
    # uncommitted: redraw A + new untracked glyph B
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    (glyphs / "B_.glif").write_text(_glif("B"))
    report = extract_working_facts(str(repo))
    kinds = {f.fact_type for f in report.folded_facts}
    assert FactType.OUTLINE_REDRAWN in kinds
    assert FactType.GLYPH_ADDED in kinds
    assert report.commit_spec == "working tree"


def test_render_commit_message_subject_and_body():
    facts = [
        FoldedFact(FactType.GLYPH_ADDED, FileKind.GLIF, "glyph `B` added"),
        FoldedFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, "outline redrawn in `A`"),
    ]
    report = SourceReport(commit_spec="working tree", folded_facts=facts)
    msg = render_commit_message(report)
    subject = msg.splitlines()[0]
    assert "glyph `B` added" in subject
    assert "Outlines & glyphs:" in msg
    assert "- outline redrawn in `A`" in msg


def test_render_commit_message_empty():
    report = SourceReport(commit_spec="working tree", folded_facts=[])
    assert render_commit_message(report).strip() == "No source changes"


def test_inspect_writes_the_draft_outside_the_repository(tmp_path):
    """Nothing tdreport-related is written inside the font repo — not even a draft.

    It used to land in `<repo>/.tdreport/`, which meant appending a line to the
    repository's own `.gitignore`: a silent edit to a tracked file, to hide a problem the
    tool had just created.
    """
    repo, glyphs, profile = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    gitignore = tmp_path / "font" / ".gitignore"
    before = gitignore.read_text() if gitignore.is_file() else None

    root, text, changed = inspect(profile)

    assert changed is True
    assert "outline redrawn" in text
    draft = report_path(root)
    assert draft.is_file()
    assert "outline redrawn" in draft.read_text()
    # In the config dir, keyed by this repo…
    assert str(tmp_path / "cfg" / "ufo-tdkit-report" / "drafts") in str(draft)
    # …and the repository is exactly as it was.
    assert not (Path(root) / ".tdreport").exists()
    assert (gitignore.read_text() if gitignore.is_file() else None) == before


def test_two_repos_with_the_same_name_get_separate_drafts(tmp_path):
    first, _, profile_a = _repo(tmp_path / "a")
    second, _, profile_b = _repo(tmp_path / "b")
    assert report_path(str(first)) != report_path(str(second))


def test_a_leftover_in_repo_draft_dir_is_reported_not_deleted(tmp_path):
    """It is the owner's repository; saying so is ours, removing it is theirs."""
    repo, _, profile = _repo(tmp_path)
    stale = Path(repo) / ".tdreport"
    stale.mkdir()
    (stale / "commit-message.md").write_text("old draft")

    assert legacy_draft_dir(str(repo)) == stale
    inspect(profile)
    assert stale.is_dir()  # untouched
    assert legacy_draft_dir(str(tmp_path)) is None


def test_inspect_clean_tree_reports_no_changes(tmp_path):
    repo, glyphs, profile = _repo(tmp_path)
    _, text, changed = inspect(profile)
    assert changed is False
    assert text.strip() == "No source changes"


def test_commit_uses_message_and_cleans_up(tmp_path):
    repo, glyphs, profile = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    rc, msg = commit(profile)
    assert rc == 0
    assert "committed:" in msg
    # the draft is gone and HEAD carries the drafted subject
    assert not report_path(resolve_repo(profile)).is_file()
    head = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"], capture_output=True, text=True
    ).stdout.strip()
    assert "outline redrawn in `A`" in head
    # tree is clean afterwards; a second commit is a no-op
    rc2, msg2 = commit(profile)
    assert rc2 == 0
    assert "nothing to commit" in msg2


def test_commit_clean_tree_is_noop(tmp_path):
    repo, glyphs, profile = _repo(tmp_path)
    rc, msg = commit(profile)
    assert rc == 0
    assert "nothing to commit" in msg


def test_confirm(monkeypatch):
    import sys

    # auto-yes short-circuits everything
    assert _confirm("ok?", assume_yes=True) is True
    # non-interactive (no TTY) → silent no (never blocks pipes/CI)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert _confirm("ok?") is False
    # interactive: answer drives the result
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    assert _confirm("ok?") is True
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert _confirm("ok?") is False


def test_is_range_dispatch():
    # A range (contains '..') routes to committed-history; everything else is a
    # repo selector for the working-tree commit assistant.
    assert _is_range("v2.005..HEAD") is True
    assert _is_range("HEAD~1..HEAD") is True
    assert _is_range("myfont") is False  # a registry name / repo selector
    assert _is_range("HEAD") is False    # a bare commit-ish is not a range
    assert _is_range(None) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
