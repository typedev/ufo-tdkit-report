"""Global test isolation for the tool's config directory.

Every test gets its own config dir, on every platform. This lives in ``conftest.py``
rather than in each test file on purpose: redirecting ``XDG_CONFIG_HOME`` — the previous
approach — is ignored by the macOS branch of ``config_dir()``, so on a Mac the suite ran
against the developer's REAL config and could overwrite their stored API key. An autouse
fixture makes that impossible to forget in a new test file.
"""

import os
import shutil
import stat
import sys

import pytest

from ufo_tdkit_report.config import CONFIG_DIR_VAR


def rmtree(path) -> None:
    """`shutil.rmtree` that also works on a git repo under Windows.

    Git marks objects in `.git/objects` read-only, and Windows refuses to delete a
    read-only file — the plain call raises `PermissionError [WinError 5]`.
    """

    def _drop_readonly(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_drop_readonly)
    else:
        shutil.rmtree(path, onerror=_drop_readonly)


@pytest.fixture(autouse=True)
def isolated_tdreport_config(tmp_path, monkeypatch):
    # Both are set, and they agree: tests that assert on a path built from
    # `tmp_path / "cfg"` keep working, and the explicit override wins everywhere.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv(CONFIG_DIR_VAR, str(tmp_path / "cfg" / "ufo-tdkit-report"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
