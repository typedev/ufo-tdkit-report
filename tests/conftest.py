"""Global test isolation: the config directory, and the network.

Every test gets its own config dir, on every platform. This lives in ``conftest.py``
rather than in each test file on purpose: redirecting ``XDG_CONFIG_HOME`` — the previous
approach — is ignored by the macOS branch of ``config_dir()``, so on a Mac the suite ran
against the developer's REAL config and could overwrite their stored API key. An autouse
fixture makes that impossible to forget in a new test file.

The second fixture exists because narration is the CLI's **default** since 0.5.0. Any
test that runs `main()` against a repo while a key happens to be stored would otherwise
reach a real provider — a paid call, from the test suite, dependent on a network. The
seams are injected everywhere on purpose (see the narrator's `transport=`), so a test
that means to exercise narration passes its own; one that does not should never get
that far. Reaching the real HTTP functions therefore fails the test, loudly, instead of
quietly spending money.
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


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    """Make the suite behave as if there is no network, except on loopback.

    Two reasons. Narration is the CLI's default since 0.5.0, so a test running `main()`
    while a key happens to be stored would otherwise make a real, paid call. And several
    tests assert the *offline* behaviour — `list_models` degrading to its hint list, the
    CLI falling back to the deterministic report — which without this passed or failed
    depending on whether the machine running them had a network. Now they do not.

    Patched at `urlopen`, deliberately: the narrator binds its `transport` as a *default
    argument*, so replacing `narrator._http_post` after import changes nothing — the same
    trap CLAUDE.md's testing notes record for `list_models`. A test that injects its own
    `transport=` never reaches here.

    `URLError` rather than an assertion, because that is what genuinely having no network
    raises, and the code under test is supposed to survive it. The loopback exemption is
    for the end-to-end test that runs a real HTTP server in-process.
    """
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    real_urlopen = urllib.request.urlopen

    def _guarded(request, *args, **kwargs):
        url = getattr(request, "full_url", request)
        host = urlparse(url if isinstance(url, str) else str(url)).hostname or ""
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_urlopen(request, *args, **kwargs)
        raise urllib.error.URLError(
            f"blocked by the test suite: {host or url} is off-machine. Inject a fake "
            f"`transport=` to exercise a request, or `--no-ai` to not make one."
        )

    monkeypatch.setattr("urllib.request.urlopen", _guarded)
