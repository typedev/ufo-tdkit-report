"""Tests for AI accounts and the single settings-resolution chain.

Every test redirects XDG_CONFIG_HOME at a tmp dir: the config is the unit under test,
so it must never be the developer's real one. No network anywhere.
"""

import stat

import pytest

from ufo_tdkit_report import registry, settings
from ufo_tdkit_report.config import config_env_path
from ufo_tdkit_report.providers import DEFAULT_MODEL, NarratorError


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def _repo(tmp_path, name):
    """A directory that looks enough like a git repo for the registry."""
    path = tmp_path / name
    (path / ".git").mkdir(parents=True)
    return path


def test_a_fresh_config_still_has_a_default_account():
    assert "default" in settings.accounts()
    assert settings.default_account_name() == "default"
    resolved = settings.resolve_ai_settings()
    assert resolved.provider_name == "anthropic"
    assert resolved.model == DEFAULT_MODEL
    assert resolved.language == "English"


def test_accounts_hold_no_secret_and_keys_are_scoped():
    settings.add_account("acme", provider="openai", model="gpt-5", language="German")
    settings.store_account_key("sk-acme", account="acme")
    settings.store_account_key("sk-personal", account="default")

    # The non-secret file must never contain a key.
    assert "sk-" not in settings.settings_path().read_text()
    # Each account reads its own secret; neither inherits the other's.
    assert settings.account_key("acme") == "sk-acme"
    assert settings.account_key("default") == "sk-personal"
    # Both live in the one owner-only .env, side by side.
    env = config_env_path()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "TDREPORT_KEY_ACME=sk-acme" in env.read_text()
    assert "TDREPORT_KEY_DEFAULT=sk-personal" in env.read_text()


def test_masked_key_never_shows_the_secret():
    settings.store_account_key("sk-ant-abcdef1234", account="default")
    shown = settings.masked_key("default")
    assert shown == "set (…1234)"
    assert "abcdef" not in shown
    assert settings.masked_key("nosuch") == "not set"


def test_removing_an_account_takes_its_key_with_it():
    settings.add_account("acme", provider="openai")
    settings.store_account_key("sk-acme", account="acme")
    assert settings.remove_account("acme") is True
    assert "sk-acme" not in config_env_path().read_text()
    assert "acme" not in settings.accounts()
    with pytest.raises(ValueError, match="cannot be removed"):
        settings.remove_account("default")


def test_account_names_that_would_share_a_secret_are_rejected():
    settings.add_account("acme-eu", provider="openai")
    # 'acme.eu' would normalize to the same TDREPORT_KEY_ACME_EU variable.
    with pytest.raises(ValueError, match="collides"):
        settings.add_account("acme.eu", provider="openai")
    with pytest.raises(ValueError, match="invalid account name"):
        settings.add_account("-nope")


def test_unknown_provider_and_account_are_explicit_errors():
    with pytest.raises(NarratorError, match="unknown AI provider"):
        settings.add_account("x", provider="gpt")
    with pytest.raises(NarratorError, match="unknown AI account"):
        settings.resolve_ai_settings(account="nosuch")


def test_resolution_precedence(tmp_path):
    settings.add_account("acme", provider="deepseek", model="deepseek-chat", language="Spanish")
    repo = _repo(tmp_path, "AcmeSans")
    registry.add("acmesans", str(repo), account="acme")

    # Repo binding picks the account up, by PATH (the plain `tdreport` in a cwd).
    bound = settings.resolve_ai_settings(repo=str(repo))
    assert (bound.account, bound.provider_name, bound.model, bound.language) == (
        "acme", "deepseek", "deepseek-chat", "Spanish",
    )
    # A per-repo override beats the account it points at.
    registry.add("acmesans", str(repo), account="acme", language="Portuguese")
    assert settings.resolve_ai_settings(repo=str(repo)).language == "Portuguese"
    # An explicit argument beats everything.
    assert settings.resolve_ai_settings(repo=str(repo), language="Italian").language == "Italian"
    assert settings.resolve_ai_settings(repo=str(repo), model="m2").model == "m2"
    # An unbound repo falls back to the default account.
    other = _repo(tmp_path, "Other")
    assert settings.resolve_ai_settings(repo=str(other)).provider_name == "anthropic"


def test_the_bound_account_supplies_the_key_not_the_default_one(tmp_path):
    settings.add_account("acme", provider="deepseek", model="deepseek-chat")
    settings.store_account_key("sk-acme", account="acme")
    settings.store_account_key("sk-personal", account="default")
    repo = _repo(tmp_path, "AcmeSans")
    registry.add("acmesans", str(repo), account="acme")
    assert settings.resolve_ai_settings(repo=str(repo)).api_key == "sk-acme"


def test_a_pre_accounts_config_keeps_working():
    # The old layout: one Anthropic key and one model preference in .env, no settings.json.
    settings.store_api_key("sk-ant-legacy")
    settings.store_model("claude-haiku-4-5")
    assert not settings.settings_path().exists()
    resolved = settings.resolve_ai_settings()
    assert resolved.api_key == "sk-ant-legacy"
    assert resolved.model == "claude-haiku-4-5"
    # A named account never inherits that legacy key.
    settings.add_account("acme", provider="anthropic")
    assert settings.account_key("acme") is None


def test_require_explains_what_is_missing():
    settings.add_account("acme", provider="deepseek")  # no model, no key
    resolved = settings.resolve_ai_settings(account="acme")
    with pytest.raises(NarratorError, match="no model set"):
        resolved.require()
    settings.update_account("acme", model="deepseek-chat")
    with pytest.raises(NarratorError, match="no API key"):
        settings.resolve_ai_settings(account="acme").require()
    # A local provider needs no key at all.
    settings.add_account("local", provider="ollama", model="llama3")
    settings.resolve_ai_settings(account="local").require()


def test_switching_provider_does_not_carry_a_stale_model_over():
    # The reason the model is stored per account rather than globally.
    settings.update_account("default", model="claude-opus-5")
    settings.add_account("work", provider="deepseek")
    assert settings.resolve_ai_settings(account="work").model == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
