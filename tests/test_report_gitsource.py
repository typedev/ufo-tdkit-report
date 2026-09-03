"""Tests for the report git layer + end-to-end service."""

import subprocess

import pytest

from ufo_tdkit_report import extract_facts
from ufo_tdkit_report.gitsource import GitSource
from ufo_tdkit_report.model import FactType


class _FakeProc:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_resolve_spec_variants():
    gs = GitSource("/x", runner=lambda *a, **k: _FakeProc())
    assert gs.resolve_spec(None) == ("HEAD~1", "HEAD")
    assert gs.resolve_spec("abc") == ("abc~1", "abc")
    assert gs.resolve_spec("A..B") == ("A", "B")


def test_list_changed_mocked_runner():
    # NUL-delimited `diff --name-status -z` output: M, then path.
    payload = b"M\x00MasterRegular.ufo/glyphs/A_.glif\x00A\x00MasterRegular.ufo/glyphs/B_.glif\x00"
    gs = GitSource("/x", runner=lambda *a, **k: _FakeProc(payload))
    changed = gs.list_changed("base", "head")
    assert len(changed) == 2
    assert changed[0].status == "M"
    assert changed[0].old_spec == "base:MasterRegular.ufo/glyphs/A_.glif"
    assert changed[1].status == "A"
    assert changed[1].old_spec is None  # addition


def test_read_blobs_mocked_batch():
    # cat-file --batch: "<sha> blob <size>\n<payload>\n"
    body = b"hello"
    header = f"deadbeef blob {len(body)}\n".encode()
    payload = header + body + b"\n"
    gs = GitSource("/x", runner=lambda *a, **k: _FakeProc(payload))
    out = gs.read_blobs(["HEAD:file.txt"])
    assert out == {"HEAD:file.txt": b"hello"}


# --------------------------------------------------------------------------- #
# End-to-end against a real tiny temp repo
# --------------------------------------------------------------------------- #


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(tmp_path):
    repo = tmp_path / "font"
    glyphs = repo / "MasterRegular.ufo" / "glyphs"
    glyphs.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo, glyphs


def _glif(advance=500, points=((0, 0), (10, 10))):
    pts = "".join(f'<point x="{x}" y="{y}" type="line"/>' for x, y in points)
    return (
        f'<glyph name="A" format="2"><advance width="{advance}"/>'
        f"<outline><contour>{pts}</contour></outline></glyph>"
    )


def test_end_to_end_outline_redraw(tmp_path):
    repo, glyphs = _make_repo(tmp_path)
    glif = glyphs / "A_.glif"
    glif.write_text(_glif(points=((0, 0), (10, 10))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    glif.write_text(_glif(points=((0, 0), (99, 88))))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "redraw")

    report = extract_facts(str(repo), "HEAD")
    assert report.raw_fact_count == 1
    assert report.folded_facts[0].fact_type == FactType.OUTLINE_REDRAWN
    assert "outline redrawn in `A`" in report.render_text()


def test_end_to_end_records_profile(tmp_path):
    repo, glyphs = _make_repo(tmp_path)
    (glyphs / "A_.glif").write_text(_glif())
    profile = repo / "profile.yaml"
    profile.write_text("path: MasterRegular.ufo\nttfautohint: true\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    # Change the profile in a follow-up commit.
    profile.write_text("path: MasterRegular.ufo\nttfautohint: false\nvariable: true\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "profile change")

    report = extract_facts(str(repo), "HEAD", profile="profile.yaml")
    assert report.profile_name == "profile.yaml"
    assert report.profile_options["variable"] is True
    kinds = {f.fact_type for f in report.folded_facts}
    assert FactType.PROFILE_OPTION_CHANGED in kinds  # ttfautohint true -> false
    assert FactType.PROFILE_OPTION_ADDED in kinds     # variable


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
