"""Tests for the `tdreport settings` screen.

The screen is a front-end: what these assert is that it *stores through* the settings
and registry layers, terminates, and never prints a secret. Input is monkeypatched the
way the other menu tests in this suite do it; a exhausted script raises EOF, which the
menu must treat as "quit" rather than crashing.
"""

import json

import pytest

from ufo_tdkit_report import registry, settings, settings_ui
from ufo_tdkit_report.providers import NarratorError


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _answers(monkeypatch, *script):
    """Feed the menu a fixed script; anything past it is EOF (i.e. quit)."""
    it = iter(script)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)


def _repo(tmp_path, name):
    path = tmp_path / name
    (path / ".git").mkdir(parents=True)
    return path


def test_render_settings_shows_status_without_the_key(tmp_path):
    settings.store_account_key("sk-ant-abcd1234", account="default")
    out = settings_ui.render_settings()
    assert "AI provider  anthropic" in out
    assert "set (…1234)" in out
    assert "sk-ant-abcd1234" not in out
    assert "abcd" not in out.replace("…1234", "")


def test_render_settings_as_json_is_machine_readable(tmp_path):
    settings.store_account_key("sk-secret-value", account="default")
    repo = _repo(tmp_path, "MyFont")
    registry.add("myfont", str(repo), account="default")
    data = json.loads(settings_ui.render_settings(as_json=True))
    assert data["provider"] == "anthropic"
    assert data["repos"]["myfont"]["account"] == "default"
    assert "sk-secret-value" not in json.dumps(data)


def test_menu_quits_immediately_and_on_eof(monkeypatch, capsys):
    _answers(monkeypatch, "q")
    assert settings_ui.run_settings_menu() == 0
    _answers(monkeypatch)  # empty script -> EOF on the first prompt
    assert settings_ui.run_settings_menu() == 0
    assert "Settings" in capsys.readouterr().out


def test_menu_changes_provider_model_and_language(monkeypatch):
    # 1 -> provider menu -> "deepseek"; 2 -> model menu -> first entry; 4 -> language.
    _answers(monkeypatch, "1", "deepseek", "2", "1", "4", "German", "q")
    assert settings_ui.run_settings_menu() == 0
    resolved = settings.resolve_ai_settings()
    assert (resolved.provider_name, resolved.model, resolved.language) == (
        "deepseek", "deepseek-chat", "German",
    )


def test_menu_stores_a_key_without_echoing_it(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)  # _read_secret reads a line
    monkeypatch.setattr("sys.stdin.readline", lambda: "sk-typed-9876\n")
    _answers(monkeypatch, "3", "q")
    assert settings_ui.run_settings_menu() == 0
    assert settings.account_key("default") == "sk-typed-9876"
    assert "sk-typed-9876" not in capsys.readouterr().out


def test_menu_unknown_option_does_not_crash(monkeypatch, capsys):
    _answers(monkeypatch, "42", "q")
    assert settings_ui.run_settings_menu() == 0
    assert "no option '42'" in capsys.readouterr().out


def _secret(monkeypatch, value):
    """`_read_secret` bypasses input(): off a TTY it reads a line from stdin."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdin.readline", lambda: value + "\n")


def test_models_for_says_which_list_it_is(monkeypatch, capsys):
    """A fallback list looks exactly like a real one — the difference has to be said."""
    from ufo_tdkit_report import narrator

    settings.add_account("dsp", provider="deepseek")
    resolved = settings.resolve_ai_settings(account="dsp")

    # No key: the live list is not even requested.
    models, live = settings_ui.models_for(resolved)
    assert live is False
    assert models == list(resolved.provider.known_models)
    out = capsys.readouterr().out
    assert "no key yet, so the live list was not requested" in out

    # With a key and a reachable endpoint: the real list, named as such. (`list_models`
    # binds its transport as a default argument, so the seam here is the function.)
    settings.store_account_key("sk-dsp", account="dsp")
    resolved = settings.resolve_ai_settings(account="dsp")
    monkeypatch.setattr(
        narrator, "list_models",
        lambda **kw: [("deepseek-chat", "deepseek-chat"), ("deepseek-v9", "deepseek-v9")],
    )
    models, live = settings_ui.models_for(resolved)
    assert live is True
    assert ("deepseek-v9", "deepseek-v9") in models
    assert "Models available to this key on deepseek" in capsys.readouterr().out

    # With a key but an unusable endpoint, list_models degrades to the hint list — which
    # must be reported as a fallback, not passed off as what the key can reach.
    monkeypatch.setattr(narrator, "list_models", lambda **kw: list(resolved.provider.known_models))
    models, live = settings_ui.models_for(resolved)
    assert live is False
    assert "the live list could not be fetched" in capsys.readouterr().out


def test_prompt_key_names_the_hidden_input_and_confirms(monkeypatch, capsys):
    settings.add_account("dsp", provider="deepseek")
    _secret(monkeypatch, "sk-pasted-5555")
    assert settings_ui.prompt_key("dsp") == "sk-pasted-5555"
    out = capsys.readouterr().out
    # The reason a paste "does nothing": it is hidden. Say so before, confirm after.
    assert "Input is HIDDEN" in out
    assert "key stored: set (…5555)" in out
    assert "sk-pasted-5555" not in out

    # An empty answer is not a silent no-op either.
    _secret(monkeypatch, "")
    assert settings_ui.prompt_key("dsp") is None
    assert "no key stored for 'dsp' yet" in capsys.readouterr().out


def test_add_account_flow_asks_for_each_part(monkeypatch, capsys):
    _secret(monkeypatch, "sk-work-9876")
    # name -> provider -> (key via stdin) -> model menu (1st of deepseek's hints) -> language
    _answers(monkeypatch, "work", "deepseek", "1", "German")
    account = settings_ui.add_account_flow()
    assert account is not None

    resolved = settings.resolve_ai_settings(account="work")
    assert resolved.provider_name == "deepseek"
    assert resolved.model == "deepseek-chat"
    assert resolved.language == "German"
    assert resolved.api_key == "sk-work-9876"

    out = capsys.readouterr().out
    assert "a name you choose, plus the provider whose key it will hold" in out
    assert "Created account 'work'" in out
    assert "tdreport bind work" in out          # says what to do next
    assert "sk-work-9876" not in out            # and never echoes the key


def test_add_account_flow_lets_every_step_be_skipped(monkeypatch):
    _secret(monkeypatch, "")                     # no key yet
    _answers(monkeypatch, "later", "anthropic", "", "")   # model: Enter keeps current; language: Enter
    assert settings_ui.add_account_flow() is not None
    resolved = settings.resolve_ai_settings(account="later")
    assert resolved.provider_name == "anthropic"
    assert resolved.api_key is None
    assert resolved.language == "English"


def test_add_account_flow_cancels_and_validates(monkeypatch, capsys):
    _answers(monkeypatch, "")                    # empty name aborts
    assert settings_ui.add_account_flow() is None
    assert "cancelled" in capsys.readouterr().out

    _answers(monkeypatch, "-bad")
    assert settings_ui.add_account_flow() is None
    assert "invalid account name" in capsys.readouterr().out
    assert "-bad" not in settings.accounts()


def test_accounts_menu_lists_adds_and_removes(monkeypatch, capsys):
    settings.add_account("work", provider="openai", model="gpt-5")
    settings.store_account_key("sk-work", account="work")

    # d -> default picker -> "work"; r -> remove it; q
    _answers(monkeypatch, "d", "work", "r", "work", "q")
    assert settings_ui.run_accounts_menu() == 0
    out = capsys.readouterr().out
    assert "an account carries a provider AND the key for it" in out
    assert "openai" in out and "gpt-5" in out
    assert "sk-work" not in out
    assert "work" not in settings.accounts()
    assert settings.account_key("work") is None
    assert settings.default_account_name() == "default"   # fell back after removal


def test_accounts_menu_opens_one_account(monkeypatch, capsys):
    settings.add_account("work", provider="deepseek")
    # 2 -> 'work' (sorted: default, work) -> quit its screen -> quit
    _answers(monkeypatch, "2", "q", "q")
    assert settings_ui.run_accounts_menu() == 0
    assert "Settings — account 'work'" in capsys.readouterr().out


def test_repos_screen_binds_unbinds_and_prunes(monkeypatch, tmp_path):
    settings.add_account("work", provider="deepseek")
    live = _repo(tmp_path, "Live")
    dead = _repo(tmp_path, "Dead")
    registry.add("live", str(live))
    registry.add("dead", str(dead))
    from conftest import rmtree

    rmtree(dead)

    # 8 -> repos; b -> bind "live" to "work"; p -> prune; q -> back; q -> quit
    _answers(monkeypatch, "8", "b", "live", "work", "p", "q", "q")
    assert settings_ui.run_settings_menu() == 0
    assert registry.entry("live")["account"] == "work"
    assert registry.entry("dead") is None

    _answers(monkeypatch, "8", "u", "live", "q", "q")
    assert settings_ui.run_settings_menu() == 0
    assert "account" not in registry.entry("live")


def test_repos_screen_sets_and_clears_a_per_repo_model(monkeypatch, tmp_path):
    repo = _repo(tmp_path, "MyFont")
    registry.add("myfont", str(repo))

    # 8 -> repos; m -> model for "myfont" -> a haiku id; q -> back; q -> quit
    _answers(monkeypatch, "8", "m", "myfont", "claude-haiku-4-5", "q", "q")
    assert settings_ui.run_settings_menu() == 0
    assert settings.resolve_ai_settings(repo=str(repo)).model == "claude-haiku-4-5"

    # An empty answer clears the override, back to the account's model.
    _answers(monkeypatch, "8", "m", "myfont", "", "q", "q")
    assert settings_ui.run_settings_menu() == 0
    assert "model" not in registry.entry("myfont")
    assert settings.resolve_ai_settings(repo=str(repo)).model == "claude-opus-5"


def test_repos_screen_refuses_an_unknown_account(monkeypatch, tmp_path, capsys):
    live = _repo(tmp_path, "Live")
    registry.add("live", str(live))
    _answers(monkeypatch, "8", "b", "live", "nosuch", "q", "q")
    assert settings_ui.run_settings_menu() == 0
    assert "unknown AI account" in capsys.readouterr().out
    assert "account" not in registry.entry("live")


# --- the repo-scoped screen ---------------------------------------------------------


def test_repo_settings_show_where_each_value_comes_from(tmp_path):
    settings.add_account("work", provider="openai", model="gpt-5", language="German")
    settings.store_account_key("sk-work-4321", account="work")
    repo = _repo(tmp_path, "AcmeSans")
    registry.add("acmesans", str(repo), account="work", model="gpt-5-mini")

    out = settings_ui.render_repo_settings("acmesans")
    # Every value carries its provenance — the split between account and repo is the
    # thing that is confusing without it.
    assert "Account    work" in out and "from this repo" in out
    assert "Provider   openai" in out
    assert "from account 'work'" in out
    assert "Model      gpt-5-mini" in out
    assert "Language   German" in out
    assert "set (…4321)" in out
    assert "sk-work-4321" not in out


def test_repo_settings_provenance_for_an_unbound_repo(tmp_path):
    repo = _repo(tmp_path, "Plain")
    registry.add("plain", str(repo))
    snap = settings_ui.repo_snapshot("plain")
    assert snap["account"] == "default"
    assert snap["account_is_explicit"] is False
    assert snap["model_source"] == "built-in default"
    assert snap["language_source"] == "built-in default"

    settings.update_account("default", model="claude-sonnet-5")
    assert settings_ui.repo_snapshot("plain")["model_source"] == "account 'default'"
    registry.add("plain", str(repo), model="claude-haiku-4-5")
    assert settings_ui.repo_snapshot("plain")["model_source"] == "this repo"


def test_repo_settings_as_json_and_unknown_repo(tmp_path):
    repo = _repo(tmp_path, "MyFont")
    registry.add("myfont", str(repo))
    data = json.loads(settings_ui.render_repo_settings("myfont", as_json=True))
    assert data["name"] == "myfont"
    assert data["provider"] == "anthropic"
    with pytest.raises(NarratorError, match="no registered repo"):
        settings_ui.repo_snapshot("nope")


def test_repo_menu_switches_account_and_warns_about_a_pinned_model(monkeypatch, tmp_path, capsys):
    settings.add_account("work", provider="openai")
    repo = _repo(tmp_path, "MyFont")
    registry.add("myfont", str(repo), model="claude-sonnet-5")

    # 1 -> account menu -> "work"; q -> quit
    _answers(monkeypatch, "1", "work", "q")
    assert settings_ui.run_repo_menu("myfont") == 0
    assert registry.entry("myfont")["account"] == "work"
    out = capsys.readouterr().out
    # The account menu names what an account actually brings.
    assert "an account carries the provider AND the key" in out
    # Switching provider under a pinned model is flagged where it is created.
    assert "pins the model 'claude-sonnet-5'" in out
    assert "provider openai" in out


def test_repo_menu_sets_and_clears_a_model_override(monkeypatch, tmp_path):
    repo = _repo(tmp_path, "MyFont")
    registry.add("myfont", str(repo))

    # 2 -> model menu -> 5th of the anthropic hint list (haiku); q
    _answers(monkeypatch, "2", "claude-haiku-4-5", "q")
    assert settings_ui.run_repo_menu("myfont") == 0
    assert registry.entry("myfont")["model"] == "claude-haiku-4-5"
    assert settings.resolve_ai_settings(repo=str(repo)).model == "claude-haiku-4-5"

    # 3 -> language, empty clears; q
    _answers(monkeypatch, "3", "German", "q")
    assert settings_ui.run_repo_menu("myfont") == 0
    assert registry.entry("myfont")["language"] == "German"
    _answers(monkeypatch, "3", "", "q")
    assert settings_ui.run_repo_menu("myfont") == 0
    assert "language" not in registry.entry("myfont")


def test_repo_menu_flags_a_missing_key_and_reaches_the_account_screen(monkeypatch, tmp_path, capsys):
    settings.add_account("work", provider="deepseek")  # no key
    repo = _repo(tmp_path, "MyFont")
    registry.add("myfont", str(repo), account="work")

    # 5 -> the account screen for 'work' -> quit it -> quit the repo screen
    _answers(monkeypatch, "5", "q", "q")
    assert settings_ui.run_repo_menu("myfont") == 0
    out = capsys.readouterr().out
    assert "has no key" in out
    assert "Settings — account 'work'" in out
    # The hint must name the option that actually sets a key. It said "4" until the
    # Grounding row was inserted above it, sending anyone who followed it to the wrong
    # setting — so pin the number against the menu it describes, not just its wording.
    assert "option 5 to set one" in out
    assert "   5. Edit the account itself" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
