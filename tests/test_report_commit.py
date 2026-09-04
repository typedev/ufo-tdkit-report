"""Tests for the report commit assistant — working tree vs HEAD."""

import subprocess
from pathlib import Path

import pytest

from ufo_tdkit_report import extract_working_facts
from ufo_tdkit_report.cli import _confirm, _is_range
from ufo_tdkit_report.commit import (
    commit,
    draft_state,
    inspect,
    legacy_draft_dir,
    report_path,
    resolve_repo,
    state_path,
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


def test_registering_a_repo_does_not_move_its_draft(tmp_path):
    """Keying by the registered name orphaned any draft written before registration."""
    from ufo_tdkit_report import registry

    repo, glyphs, profile = _repo(tmp_path)
    before = report_path(str(repo))
    registry.add("MyFont", str(repo))
    assert report_path(str(repo)) == before


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


def test_an_edited_draft_survives_a_second_look(tmp_path):
    """Re-running to read the report again must not cost the owner their words.

    For an --ai-note draft it would also throw away a paid model call.
    """
    repo, glyphs, profile = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    root, _, _ = inspect(profile)
    report_path(root).write_text("MY OWN SUBJECT\n\n- written by hand\n")

    _, text, _ = inspect(profile)
    assert text == "MY OWN SUBJECT\n\n- written by hand\n"
    assert draft_state(root).edited is True

    # …until it is asked for explicitly.
    _, fresh, _ = inspect(profile, regenerate=True)
    assert "outline redrawn" in fresh
    assert draft_state(root).edited is False


def test_a_draft_goes_stale_when_the_facts_change_not_the_bytes(tmp_path):
    repo, glyphs, profile = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    root, _, _ = inspect(profile)
    assert draft_state(root).stale is False

    # Rewriting identical content changes mtime, not the facts — still fresh.
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    assert draft_state(root).stale is False

    # A real change makes the description wrong.
    (glyphs / "B_.glif").write_text(_glif("B", points=((5, 5), (6, 6))))
    assert draft_state(root).stale is True


def test_committing_a_stale_draft_is_refused_unless_allowed(tmp_path):
    """A wrong description in git history cannot be fixed without rewriting it."""
    repo, glyphs, profile = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    root, _, _ = inspect(profile)
    report_path(root).write_text("MY OWN SUBJECT\n")
    (glyphs / "B_.glif").write_text(_glif("B", points=((5, 5), (6, 6))))

    rc, msg = commit(profile)
    assert rc == 1
    assert "no longer describes what would be committed" in msg
    assert "--stale-ok" in msg
    assert report_path(root).is_file()  # nothing was committed, nothing was lost

    rc, msg = commit(profile, allow_stale=True)
    assert rc == 0
    head = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"], capture_output=True, text=True
    ).stdout.strip()
    assert head == "MY OWN SUBJECT"


def test_the_state_file_records_whether_the_draft_was_ai_written(tmp_path):
    repo, glyphs, profile = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    root, _, _ = inspect(profile)
    assert draft_state(root).ai is False
    assert state_path(root).is_file()

    # A draft with no sidecar is treated as the owner's, not ours to overwrite.
    state_path(root).unlink()
    assert draft_state(root).edited is True


def test_commit_uses_message_and_cleans_up(tmp_path):
    repo, glyphs, profile = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    rc, msg = commit(profile)
    assert rc == 0
    assert "committed:" in msg
    # the draft is gone and HEAD carries the drafted subject
    assert not report_path(resolve_repo(profile)).is_file()
    assert not state_path(resolve_repo(profile)).is_file()
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


def test_an_unchanged_repo_is_not_narrated_twice(tmp_path, monkeypatch):
    """Looking at the report again must not cost another paid call.

    Only an *edited* draft used to be kept; an untouched one was thrown away and
    redrafted, so `tdreport <repo>` twice in a row on an unchanged tree paid for two
    narrations of identical facts. The sidecar already stored the facts digest that makes
    this decidable — the reuse was one condition away the whole time.
    """
    import ufo_tdkit_report.commit as commit_module
    from ufo_tdkit_report import settings
    from ufo_tdkit_report.commit import inspect as inspect_repo

    repo, glyphs, _ = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (11, 10))))
    settings.store_account_key("sk-x")

    calls = []

    def counting(report, **kwargs):
        calls.append(kwargs)
        return "feat: redraw A\n\nOne outline moved.\n"

    monkeypatch.setattr(commit_module, "narrate_commit", counting, raising=False)
    monkeypatch.setattr("ufo_tdkit_report.narrator.narrate_commit", counting)

    inspect_repo(str(repo), ai=True)
    inspect_repo(str(repo), ai=True)
    inspect_repo(str(repo), ai=True)
    assert len(calls) == 1, "an unchanged tree must not be narrated again"

    # The escape hatches still work, and each is a deliberate act.
    inspect_repo(str(repo), ai=True, regenerate=True)
    assert len(calls) == 2, "--regenerate must redraft"
    inspect_repo(str(repo), ai=True, model="some-other-model")
    assert len(calls) == 3, "asking for another model is asking for different prose"

    # A change that alters the FACTS invalidates the draft; one that does not, does not.
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (12, 10))))
    inspect_repo(str(repo), ai=True)
    assert len(calls) == 3, "same facts, same draft — staleness is measured on facts"
    (glyphs / "B_.glif").write_text(_glif("B", points=((0, 0), (5, 5))))
    inspect_repo(str(repo), ai=True)
    assert len(calls) == 4, "a new glyph changes the facts, so the draft no longer fits"


def test_switching_between_narrated_and_plain_redrafts(tmp_path, monkeypatch):
    """A deterministic draft must not be served to someone who has since asked for prose.

    The reverse matters too: `--no-ai` after a narrated run should hand back the facts,
    not the prose that happens to be on disk.
    """
    from ufo_tdkit_report import settings
    from ufo_tdkit_report.commit import inspect as inspect_repo

    repo, glyphs, _ = _repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (11, 10))))
    settings.store_account_key("sk-x")
    monkeypatch.setattr(
        "ufo_tdkit_report.narrator.narrate_commit",
        lambda report, **kw: "feat: redraw A\n\nNarrated.\n",
    )

    _, plain, _ = inspect_repo(str(repo), ai=False)
    assert "Narrated." not in plain
    _, prose, _ = inspect_repo(str(repo), ai=True)
    assert "Narrated." in prose, "a plain draft must not stand in for a requested narration"
    _, plain_again, _ = inspect_repo(str(repo), ai=False)
    assert "Narrated." not in plain_again, "--no-ai must not serve the stored prose"
