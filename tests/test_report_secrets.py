"""Tests for one property: a stored API key does not escape the file it lives in.

Property-scoped rather than module-scoped, because the ways a key escapes are not
confined to the module that stores it — a dataclass repr, a JSON dump, a stray file in
the config directory. Each test here is a *place* a key could surface, not a function.

The sweep tests are deliberately blunt: they write a key with a distinctive marker and
then grep everything the tool produced. A leak found by reading code is a leak someone
has to remember to look for; a leak found by searching the bytes is not.
"""

import json
import os
import stat
import warnings
from pathlib import Path

import pytest

from ufo_tdkit_report import registry, settings

SECRET = "sk-MARKER-do-not-leak-9f3a2b7c"
MARKER = "MARKER-do-not-leak"


def _stored(account="default", provider="anthropic"):
    if account != "default":
        settings.add_account(account, provider=provider)
    settings.store_account_key(SECRET, account=account)
    return settings.resolve_ai_settings(account=account)


def test_resolved_settings_never_render_the_key():
    """`AiSettings` carries a live key into places nobody chose to put it.

    A traceback frame, a pytest failure dump (pytest prints locals), a debugger, a
    `print()` during a bug hunt — a plain dataclass repr copies the key into a terminal
    scrollback or a CI log in every one of them. This is the test that would have caught
    that, so it checks all three renderings rather than just `repr`.
    """
    resolved = _stored()
    for rendering in (repr(resolved), str(resolved), f"{resolved}", "{}".format(resolved)):  # noqa: UP032
        assert MARKER not in rendering
        assert SECRET not in rendering
    # Still useful to a reader: presence and enough to tell two keys apart.
    assert "set (…2b7c)" in repr(resolved)
    assert resolved.api_key == SECRET  # the value itself is of course still available


def test_masked_renderings_never_contain_the_whole_key():
    resolved = _stored()
    assert MARKER not in resolved.masked_api_key
    assert MARKER not in settings.masked_key("default")
    # A short key must not be "masked" into revealing itself by being shorter than the tail.
    settings.store_account_key("abcd", account="default")
    assert settings.masked_key("default") == "set"


def test_only_the_env_file_holds_the_key(tmp_path):
    """Everything else the tool writes is safe to back up, commit or paste into an issue."""
    _stored("work", provider="openai")
    registry.add("myfont", str(tmp_path), account="work", model="gpt-5")
    settings.resolve_ai_settings(repo=str(tmp_path))

    config = Path(os.environ["TDREPORT_CONFIG_DIR"])
    leaking = [
        path.name
        for path in config.rglob("*")
        if path.is_file() and MARKER in path.read_text(errors="replace")
    ]
    assert leaking == [".env"], f"the key reached {leaking}"


@pytest.mark.skipif(os.name == "nt", reason="Windows chmod only toggles read-only; the ACL protects it")
def test_the_key_file_is_owner_only():
    _stored()
    mode = stat.S_IMODE((Path(os.environ["TDREPORT_CONFIG_DIR"]) / ".env").stat().st_mode)
    assert mode == 0o600, f"group/other can read the key file (mode {mode:04o})"


def test_the_settings_screens_serialise_a_mask_not_a_key(tmp_path):
    """`--json` is the machine-readable settings; it is also the easiest thing to paste."""
    from ufo_tdkit_report import settings_ui

    _stored("work", provider="openai")
    registry.add("myfont", str(tmp_path), account="work")
    for snapshot in (settings_ui.settings_snapshot("work"), settings_ui.repo_snapshot("myfont")):
        assert MARKER not in json.dumps(snapshot, default=str)


def test_the_suite_cannot_reach_an_off_machine_host():
    """A meta-test: the guard in conftest is protection, so it must not vanish quietly.

    Narration is the CLI default, so a test running `main()` with a key stored would
    otherwise make a real, paid call to a real provider — one did, before the guard.
    """
    import urllib.error
    import urllib.request

    with pytest.raises(urllib.error.URLError, match="blocked by the test suite"):
        urllib.request.urlopen("https://api.anthropic.com/v1/models", timeout=1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


@pytest.mark.skipif(os.name == "nt", reason="Windows chmod toggles read-only; mode bits carry no meaning")
def test_a_widened_key_file_is_reported_on_every_read_path(tmp_path):
    """0600 at write time is not 0600 forever.

    `cp -r` of a dotfiles directory, a restored backup, an unpacked archive or a
    permissive `umask` all widen the file afterwards, and nothing used to say so. The
    check therefore lives on the *read* path, where every consumer of the key passes,
    rather than beside the write that already sets the mode.
    """
    from ufo_tdkit_report.config import InsecureKeyFileWarning, read_dotenv_key

    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-loose\n")
    env.chmod(0o644)

    with pytest.warns(InsecureKeyFileWarning, match="chmod 600"):
        assert read_dotenv_key([env]) == "sk-loose"  # stated, not refused: still readable

    env.chmod(0o600)
    with warnings.catch_warnings():
        warnings.simplefilter("error", InsecureKeyFileWarning)
        assert read_dotenv_key([env]) == "sk-loose"
