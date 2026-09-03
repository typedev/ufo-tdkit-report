"""Global test isolation for the tool's config directory.

Every test gets its own config dir, on every platform. This lives in ``conftest.py``
rather than in each test file on purpose: redirecting ``XDG_CONFIG_HOME`` — the previous
approach — is ignored by the macOS branch of ``config_dir()``, so on a Mac the suite ran
against the developer's REAL config and could overwrite their stored API key. An autouse
fixture makes that impossible to forget in a new test file.
"""

import pytest

from ufo_tdkit_report.config import CONFIG_DIR_VAR


@pytest.fixture(autouse=True)
def isolated_tdreport_config(tmp_path, monkeypatch):
    # Both are set, and they agree: tests that assert on a path built from
    # `tmp_path / "cfg"` keep working, and the explicit override wins everywhere.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv(CONFIG_DIR_VAR, str(tmp_path / "cfg" / "ufo-tdkit-report"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
