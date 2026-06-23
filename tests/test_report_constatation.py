"""T3: no changed tracked file is silently dropped — non-source files get a
bare constatation fact (added/removed/modified), while source files keep their
semantic facts and produce no extra note."""

import subprocess

import pytest

from ufo_tdkit_report import extract_facts, extract_working_facts
from ufo_tdkit_report.classify import file_note, status_verb
from ufo_tdkit_report.model import FactType


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
    glyphs = repo / "M.ufo" / "glyphs"
    glyphs.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (10, 10))))
    (repo / "README.md").write_text("v1\n")
    (repo / "old.txt").write_text("bye\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo, glyphs


def test_status_verb_maps_porcelain_codes():
    assert status_verb("A") == "added"
    assert status_verb("D") == "removed"
    assert status_verb(" M") == "modified"   # unstaged modify (2-char)
    assert status_verb("??") == "added"      # untracked
    assert status_verb("R100") == "renamed"
    assert status_verb(None) == "modified"


def test_file_note_shape():
    fact = file_note("build/run.sh", "A")
    assert fact.fact_type is FactType.FILE_CHANGED
    assert fact.detail == ("build/run.sh", "added")


def test_committed_other_files_surface_as_constatation(tmp_path):
    repo, glyphs = _repo(tmp_path)
    # one semantic change (.glif) + a non-source modify + a non-source delete + a new file
    (glyphs / "A_.glif").write_text(_glif("A", points=((0, 0), (99, 88))))
    (repo / "README.md").write_text("v2\n")
    (repo / "old.txt").unlink()
    (repo / "build.sh").write_text("echo hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "mixed")

    report = extract_facts(str(repo), "HEAD~1..HEAD")
    kinds = {f.fact_type for f in report.folded_facts}

    # the .glif still produces a semantic fact, NOT a constatation
    assert FactType.OUTLINE_REDRAWN in kinds
    # the other files fold into a single constatation line
    assert FactType.FILE_CHANGED in kinds
    other = next(f.summary for f in report.folded_facts if f.fact_type is FactType.FILE_CHANGED)
    assert "README.md" in other and "(modified)" in other
    assert "old.txt" in other and "(removed)" in other
    assert "build.sh" in other and "(added)" in other
    # the .glif is not double-counted as an "other file"
    assert "A_.glif" not in other


def test_working_tree_other_file_noted(tmp_path):
    repo, glyphs = _repo(tmp_path)
    (repo / "notes.txt").write_text("scratch\n")  # untracked non-source file
    report = extract_working_facts(str(repo))
    other = [f for f in report.folded_facts if f.fact_type is FactType.FILE_CHANGED]
    assert other and "notes.txt" in other[0].summary and "(added)" in other[0].summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
