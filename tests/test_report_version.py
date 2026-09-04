"""The release metadata must not drift apart.

`pyproject.toml` is the single source of truth for the version; the newest released
CHANGELOG section has to name that same version, and the git tag is `v<version>`. These
are file-level checks on purpose — comparing against ``importlib.metadata`` instead would
fail on a stale virtualenv rather than on a real mistake.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+")


def _pyproject_version() -> str:
    # Regex rather than tomllib: tomllib is 3.11+, and this package supports 3.10.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match, "no version in pyproject.toml"
    return match.group(1)


def _changelog_releases() -> list[tuple[str, str]]:
    """Released ``(version, date)`` headings, newest first. `[Unreleased]` is skipped."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$", text, re.MULTILINE)


def test_version_is_semver():
    assert SEMVER.match(_pyproject_version())


def test_changelog_documents_the_current_version():
    releases = _changelog_releases()
    assert releases, "CHANGELOG has no released sections"
    newest, _date = releases[0]
    assert newest == _pyproject_version(), (
        f"pyproject version {_pyproject_version()} is not the newest CHANGELOG "
        f"section ({newest}) — bump both, or cut the release section"
    )


def test_changelog_has_an_unreleased_section():
    # Where the next change goes; forgetting it is how entries land in a shipped section.
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text


def test_changelog_releases_are_ordered_newest_first():
    releases = _changelog_releases()
    versions = [tuple(int(p) for p in v.split(".")) for v, _ in releases]
    assert versions == sorted(versions, reverse=True)
    dates = [d for _, d in releases]
    assert dates == sorted(dates, reverse=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_an_editable_install_reports_the_source_version_not_the_installed_one():
    """An editable install's metadata is frozen; the code it runs is not.

    That gap is what made a `tdreport` installed at 0.4.1 stamp "0.4.1" into reports it
    generated with 0.5.x code — a false claim in every report footer and every commit
    trailer, in the one field CLAUDE.md calls a guarantee. The project's own dev
    environment is an editable install, so this test exercises the real path rather than
    a mock: `__version__` must agree with `pyproject.toml`, whatever the metadata says.
    """
    import re
    from pathlib import Path

    import ufo_tdkit_report

    # Regex, not `tomllib` — that is 3.11+ stdlib and this project's floor is 3.10. The
    # test above this one says so in a comment; `_editable_source_version` parses it the
    # same way for the same reason. I imported tomllib here anyway and CI's three 3.10
    # jobs caught it, which is what a version matrix is for.
    root = Path(__file__).resolve().parent.parent
    found = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert found, "pyproject.toml has no version line"
    assert ufo_tdkit_report.__version__ == found.group(1)


def test_the_version_lookup_never_raises(monkeypatch):
    """It runs at import time, so a surprise here would take the whole package down."""
    import ufo_tdkit_report

    def explode(*_args, **_kwargs):
        raise RuntimeError("no metadata here")

    monkeypatch.setattr("ufo_tdkit_report.distribution", explode)
    assert ufo_tdkit_report._editable_source_version() is None
