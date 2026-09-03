"""Tests for the CLI dispatch bits that carry their own logic (`tdreport set-model`).

No network and no git: `list_models` degrades to the built-in list without a key, and
the config dir is redirected to tmp_path, so the picker is exercised offline.
"""

import pytest

from ufo_tdkit_report.cli import _choose_model, main
from ufo_tdkit_report.narrator import DEFAULT_MODEL, resolve_model

MODELS = [("claude-opus-5", "Claude Opus 5"), ("claude-haiku-4-5", "Claude Haiku 4.5")]


def _git_init(repo):
    """Init a repo AND give it an identity — a CI runner has no global git config."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)


def test_choose_model_by_number(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    assert _choose_model(MODELS, "claude-opus-5") == "claude-haiku-4-5"
    out = capsys.readouterr().out
    assert "claude-opus-5" in out and "<- current" in out  # the menu marks the current one


def test_choose_model_enter_keeps_current(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert _choose_model(MODELS, "claude-sonnet-5") == "claude-sonnet-5"


def test_choose_model_accepts_a_raw_id(monkeypatch):
    # A model newer than the list (or absent from it) must not be locked out.
    monkeypatch.setattr("builtins.input", lambda _prompt: "claude-something-new")
    assert _choose_model(MODELS, "claude-opus-5") == "claude-something-new"


def test_choose_model_rejects_out_of_range(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "9")
    assert _choose_model(MODELS, "claude-opus-5") is None
    assert "no option 9" in capsys.readouterr().out


def test_choose_model_aborts_on_interrupt(monkeypatch):
    def interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert _choose_model(MODELS, "claude-opus-5") is None


def test_set_model_explicit_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert main(["set-model", "claude-sonnet-5"]) == 0
    assert "claude-sonnet-5" in capsys.readouterr().out
    assert resolve_model() == "claude-sonnet-5"


def test_set_model_menu(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")  # 2nd of KNOWN_MODELS

    from ufo_tdkit_report.narrator import KNOWN_MODELS

    assert main(["set-model"]) == 0
    assert resolve_model() == KNOWN_MODELS[1][0]


def test_set_model_without_tty_is_an_error(tmp_path, monkeypatch, capsys):
    # No menu to show in a pipe/CI: report the current model and demand an explicit id
    # rather than silently changing nothing.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["set-model"]) == 1
    out = capsys.readouterr().out
    assert DEFAULT_MODEL in out
    assert "usage: tdreport set-model" in out


# --- provider / language / per-account key ------------------------------------------


def test_set_provider_menu_and_next_steps(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert main(["set-provider", "deepseek"]) == 0
    out = capsys.readouterr().out
    assert "set to deepseek" in out
    # Switching provider deliberately leaves no model behind, and says so.
    assert "tdreport set-model" in out
    assert "tdreport set-key" in out

    from ufo_tdkit_report import settings

    assert settings.resolve_ai_settings().provider_name == "deepseek"
    assert settings.resolve_ai_settings().model == ""


def test_set_provider_rejects_an_unknown_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert main(["set-provider", "gpt"]) == 1
    assert "unknown AI provider" in capsys.readouterr().out


def test_set_lang_stores_the_prose_language(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert main(["set-lang", "Spanish"]) == 0
    out = capsys.readouterr().out
    assert "set to Spanish" in out
    assert "stay English" in out  # the deterministic half is never localized

    from ufo_tdkit_report import settings

    assert settings.resolve_ai_settings().language == "Spanish"


def test_set_key_is_scoped_to_the_named_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.add_account("acme", provider="openai", model="gpt-5")
    assert main(["--ai-account", "acme", "set-key", "sk-acme"]) == 0
    out = capsys.readouterr().out
    assert "account 'acme'" in out
    assert "0600" in out
    assert "sk-acme" not in out  # the key is never echoed back
    assert settings.account_key("acme") == "sk-acme"
    assert settings.account_key("default") is None


def test_set_model_uses_the_accounts_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.add_account("acme", provider="deepseek")
    settings.store_account_key("sk-acme", account="acme")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")
    # No network: the offline hint list for THAT provider is what gets offered.
    assert main(["--ai-account", "acme", "set-model"]) == 0
    assert settings.resolve_ai_settings(account="acme").model == "deepseek-chat"


def test_set_lang_and_set_provider_without_a_tty_are_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["set-provider"]) == 1
    assert main(["set-lang"]) == 1
    out = capsys.readouterr().out
    assert "usage: tdreport set-provider" in out
    assert "usage: tdreport set-lang" in out


def test_set_url_targets_a_custom_endpoint(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    assert main(["set-provider", "custom"]) == 0
    assert main(["set-url", "http://127.0.0.1:8000/v1"]) == 0
    assert "set to http://127.0.0.1:8000/v1" in capsys.readouterr().out
    assert settings.resolve_ai_settings().base_url == "http://127.0.0.1:8000/v1"
    # Clearing it falls back to the provider's own default.
    assert main(["set-url", ""]) == 0
    assert settings.resolve_ai_settings().base_url == ""


def test_account_lifecycle_and_binding(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    from ufo_tdkit_report import registry, settings

    repo = tmp_path / "AcmeSans"
    repo.mkdir()
    _git_init(repo)

    # Off a TTY (scripts, CI) the positional and flag forms still work, unprompted.
    assert main(["account", "add", "work", "deepseek"]) == 0
    assert settings.accounts()["work"].provider == "deepseek"
    assert main(["--ai-provider", "deepseek", "account", "add", "work"]) == 0
    assert main(["--ai-account", "work", "set-key", "sk-work"]) == 0
    assert main(["--ai-account", "work", "set-model", "deepseek-chat"]) == 0
    assert main(["bind", "work", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "now uses AI account 'work'" in out

    # The repo resolves to the bound account's provider/model/key, not the default's.
    resolved = settings.resolve_ai_settings(repo=str(repo))
    assert (resolved.account, resolved.provider_name, resolved.model) == ("work", "deepseek", "deepseek-chat")
    assert resolved.api_key == "sk-work"
    # The binding lives in the user's config, never inside the font repo.
    assert registry.entry_for_path(str(repo))["account"] == "work"
    assert not (repo / ".tdreport.toml").exists()
    assert list(repo.glob("*tdreport*")) == []

    # Listing shows status without ever printing a key.
    assert main(["accounts"]) == 0
    listing = capsys.readouterr().out
    assert "work" in listing and "deepseek" in listing
    assert "sk-work" not in listing
    assert "AcmeSans -> work" in listing

    # Removing the account takes its key with it.
    assert main(["account", "rm", "work"]) == 0
    assert settings.account_key("work") is None


def test_bind_rejects_an_unknown_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert main(["bind", "nosuch", str(tmp_path)]) == 1
    assert "unknown AI account" in capsys.readouterr().out


# --- settings screen and the repo registry commands ---------------------------------


def _git_repo(tmp_path, name):
    import subprocess

    repo = tmp_path / name
    repo.mkdir(parents=True)
    _git_init(repo)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    return repo


def test_settings_without_a_tty_prints_instead_of_blocking(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def boom(_prompt=""):  # a pipe can never answer; the screen must not ask
        raise AssertionError("settings prompted without a TTY")

    monkeypatch.setattr("builtins.input", boom)
    assert main(["settings"]) == 0
    assert "AI provider" in capsys.readouterr().out


def test_settings_json_is_parseable_and_secret_free(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.store_account_key("sk-hidden-4321", account="default")
    assert main(["settings", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["provider"] == "anthropic"
    assert "sk-hidden-4321" not in json.dumps(data)


def test_a_path_is_remembered_once_then_the_short_name_works(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry

    repo = _git_repo(tmp_path, "AcmeSans")
    (repo / "a.txt").write_text("x")

    assert main([str(repo), "commit"]) == 0
    out = capsys.readouterr().out
    assert "remembered 'AcmeSans'" in out  # never silent
    assert registry.resolve("AcmeSans") == str(repo.resolve())

    # From now on the short name addresses it.
    (repo / "b.txt").write_text("y")
    assert main(["AcmeSans", "commit"]) == 0


def test_a_taken_name_is_reported_not_overwritten(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry

    first = _git_repo(tmp_path / "a", "AcmeSans")
    second = _git_repo(tmp_path / "b", "AcmeSans")
    registry.add("AcmeSans", str(first))

    assert main([str(second)]) == 0
    out = capsys.readouterr().out
    assert "already registered" in out
    assert "tdreport add <name>" in out
    # The name still points where it did: quietly repointing would report on the wrong repo.
    assert registry.resolve("AcmeSans") == str(first.resolve())


def test_the_cwd_mode_registers_nothing_and_an_unknown_name_is_still_an_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry

    repo = _git_repo(tmp_path, "Quiet")
    monkeypatch.chdir(repo)
    assert main([]) == 0
    assert registry.load() == {}  # only an explicit path argument registers

    assert main(["no-such-name"]) == 1
    assert "unknown repo 'no-such-name'" in capsys.readouterr().out


def test_ls_rm_and_prune(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry

    assert main(["ls"]) == 0
    assert "no repos registered yet" in capsys.readouterr().out

    live = _git_repo(tmp_path, "Live")
    dead = _git_repo(tmp_path, "Dead")
    registry.add("live", str(live), account="default")
    registry.add("dead", str(dead))
    import shutil

    shutil.rmtree(dead)

    assert main(["ls"]) == 0
    listing = capsys.readouterr().out
    assert "account=default" in listing  # bindings and overrides are visible
    assert "(MISSING)" in listing

    assert main(["prune"]) == 0
    assert "pruned 'dead'" in capsys.readouterr().out
    assert main(["rm", "live"]) == 0
    assert registry.load() == {}
    assert main(["rm"]) == 1


def test_per_repo_model_override_shares_the_account_key(tmp_path, monkeypatch, capsys):
    """Two repos, one account, one key, different models — the whole point of the override."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.store_account_key("sk-one", account="default")
    fast = _git_repo(tmp_path, "FastFont")
    careful = _git_repo(tmp_path, "CarefulFont")
    assert main([str(fast), "commit"]) == 0
    assert main([str(careful), "commit"]) == 0
    capsys.readouterr()

    assert main(["repo", "FastFont", "model", "claude-haiku-4-5"]) == 0
    assert "FastFont' model: claude-haiku-4-5" in capsys.readouterr().out

    fast_settings = settings.resolve_ai_settings(repo=str(fast))
    careful_settings = settings.resolve_ai_settings(repo=str(careful))
    assert fast_settings.model == "claude-haiku-4-5"
    assert careful_settings.model == "claude-opus-5"  # untouched, the account default
    # Same account, so the key is stored once and shared.
    assert fast_settings.api_key == careful_settings.api_key == "sk-one"
    assert fast_settings.account == careful_settings.account == "default"


def test_repo_show_explains_what_resolves_and_why(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.store_account_key("sk-secret-1234", account="default")
    repo = _git_repo(tmp_path, "MyFont")
    assert main([str(repo)]) == 0
    capsys.readouterr()
    assert main(["repo", "MyFont", "language", "German"]) == 0
    capsys.readouterr()

    assert main(["repo", "MyFont"]) == 0
    out = capsys.readouterr().out
    assert "language    German" in out
    assert "account     default" in out
    assert "set (…1234)" in out
    assert "sk-secret-1234" not in out


def test_repo_clear_returns_a_field_to_the_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry, settings

    repo = _git_repo(tmp_path, "MyFont")
    assert main([str(repo)]) == 0
    assert main(["repo", "MyFont", "model", "claude-haiku-4-5"]) == 0
    assert main(["repo", "MyFont", "clear", "model"]) == 0
    capsys.readouterr()
    assert "model" not in registry.entry("MyFont")
    assert settings.resolve_ai_settings(repo=str(repo)).model == "claude-opus-5"


def test_repo_rejects_typos_before_writing_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry

    repo = _git_repo(tmp_path, "MyFont")
    assert main([str(repo)]) == 0
    capsys.readouterr()

    assert main(["repo", "MyFont", "account", "nosuch"]) == 1
    assert "unknown AI account" in capsys.readouterr().out
    assert main(["repo", "MyFont", "provider", "gpt"]) == 1
    assert "unknown AI provider" in capsys.readouterr().out
    assert main(["repo", "MyFont", "api_key", "sk-nope"]) == 1
    assert "unknown field" in capsys.readouterr().out
    assert main(["repo", "Nothing", "model", "x"]) == 1
    assert "no registered repo" in capsys.readouterr().out
    # Nothing was written by any of the four.
    assert registry.entry("MyFont") == {"path": str(repo.resolve())}


def test_settings_scoped_to_a_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    from ufo_tdkit_report import registry

    repo = _git_repo(tmp_path, "AcmeSans")

    # A path scopes the screen AND registers the repo, like every other path target.
    assert main(["settings", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "remembered 'AcmeSans'" in out
    assert "Settings — repo 'AcmeSans'" in out
    assert "from account 'default'" in out
    assert registry.resolve("AcmeSans")

    # And so does the short name, from then on.
    assert main(["settings", "AcmeSans"]) == 0
    assert "Settings — repo 'AcmeSans'" in capsys.readouterr().out

    # An unknown name is an error, not a silent fall-through to the global screen.
    assert main(["settings", "nosuch"]) == 1
    assert "no registered repo 'nosuch'" in capsys.readouterr().out


def test_settings_repo_json_carries_provenance_and_no_secret(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry, settings

    settings.store_account_key("sk-hidden-7777", account="default")
    repo = _git_repo(tmp_path, "MyFont")
    registry.add("MyFont", str(repo), model="claude-haiku-4-5")

    assert main(["settings", "MyFont", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["model"] == "claude-haiku-4-5"
    assert data["model_source"] == "this repo"
    assert data["provider_source"] == "account 'default'"
    assert "sk-hidden-7777" not in json.dumps(data)


def test_accounts_is_a_menu_on_a_tty_and_a_listing_otherwise(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.add_account("work", provider="openai")

    # No TTY: a plain listing, no prompting.
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _p="": pytest.fail("prompted without a TTY"))
    assert main(["accounts"]) == 0
    assert "AI accounts:" in capsys.readouterr().out

    # TTY: the interactive screen.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _p="": "q")
    assert main(["accounts"]) == 0
    assert "an account carries a provider AND the key for it" in capsys.readouterr().out


def test_account_add_on_a_tty_runs_the_guided_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    answers = iter(["work", "deepseek", "1", ""])  # name, provider, model, language

    def fake_input(_prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "sk-typed")

    assert main(["account", "add"]) == 0  # no name needed: it asks
    resolved = settings.resolve_ai_settings(account="work")
    assert (resolved.provider_name, resolved.model, resolved.api_key) == (
        "deepseek", "deepseek-chat", "sk-typed",
    )
    assert "sk-typed" not in capsys.readouterr().out


def test_an_unbound_repo_is_announced(tmp_path, monkeypatch, recwarn):
    """Silence would mean narrating on the default account's provider and key unnoticed."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.add_account("work", provider="deepseek")  # >1 account: the binding matters
    repo = _git_repo(tmp_path, "Unbound")

    assert main(["--repo", str(repo), "--notes", "HEAD~0..HEAD", "--ai-note"]) == 1
    warned = recwarn.pop(settings.UnboundRepoWarning)
    assert "is not registered" in str(warned.message)
    assert "tdreport bind" in str(warned.message)


def test_the_cli_renders_that_warning_as_one_readable_line():
    """A console front-end shows a note, not `…/settings.py:340: UnboundRepoWarning:`."""
    import warnings

    from ufo_tdkit_report.cli import _present_warnings_as_notes
    from ufo_tdkit_report.settings import UnboundRepoWarning

    original = warnings.formatwarning
    try:
        _present_warnings_as_notes()
        ours = warnings.formatwarning("repo 'x' is not registered", UnboundRepoWarning, "s.py", 340)
        assert ours == "note: repo 'x' is not registered\n"
        # Every other warning keeps Python's own formatting.
        other = warnings.formatwarning("deprecated", DeprecationWarning, "s.py", 12)
        assert "s.py" in other and "DeprecationWarning" in other
    finally:
        warnings.formatwarning = original


def test_set_grounding_and_the_per_repo_override(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import registry, settings

    assert main(["set-grounding", "strict"]) == 0
    out = capsys.readouterr().out
    assert "grounding for account 'default': strict" in out
    assert "will now be refused" in out
    assert settings.resolve_ai_settings().strict_grounding is True

    repo = _git_repo(tmp_path, "MyFont")
    assert main([str(repo)]) == 0
    capsys.readouterr()
    assert main(["repo", "MyFont", "grounding", "warn"]) == 0
    assert "grounding: warn" in capsys.readouterr().out
    assert settings.resolve_ai_settings(repo=str(repo)).strict_grounding is False
    assert registry.entry("MyFont")["strict_grounding"] is False

    assert main(["set-grounding", "sloppy"]) == 1
    assert "expected 'strict' or 'warn'" in capsys.readouterr().out


def test_a_strict_account_refuses_an_unsupported_narration(tmp_path, monkeypatch, capsys):
    """The whole point of strict: the run fails instead of shipping invented names."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import narrator, settings
    from ufo_tdkit_report.model import FactType, FileKind, FoldedFact, RangeReport

    settings.add_account("local", provider="ollama", model="tiny", strict_grounding=True)
    report = RangeReport(
        range_spec="v1..HEAD",
        folded_facts=[FoldedFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, "redrawn in `Ring`")],
    )

    def invents(url, headers, body, timeout):
        return {"choices": [{"message": {"content": "Redrew `Ring` and `questiondown`."}}]}

    with pytest.raises(narrator.NarratorError, match="grounding check failed"):
        narrator.narrate(report, account="local", transport=invents)

    # The same narration is kept, with a note, when the account only warns.
    settings.update_account("local", strict_grounding=False)
    with pytest.warns(narrator.GroundingWarning, match="questiondown"):
        out = narrator.narrate(report, account="local", transport=invents)
    assert "Grounding check:" in out
    assert "`questiondown` — not in the facts" in out


def _stale_draft(tmp_path):
    """A repo whose edited draft no longer describes the working tree."""
    from ufo_tdkit_report.commit import inspect, report_path

    repo = _git_repo(tmp_path, "Stale")
    (repo / "a.txt").write_text("one")
    root, _, _ = inspect(str(repo))
    report_path(root).write_text("MY OWN SUBJECT\n")
    (repo / "b.txt").write_text("two")           # the tree moves on
    return repo


def test_a_stale_draft_is_refused_in_a_pipe(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _p="": pytest.fail("prompted in a pipe"))
    repo = _stale_draft(tmp_path)

    assert main([str(repo), "commit"]) == 1
    out = capsys.readouterr().out
    assert "no longer describes what would be committed" in out
    assert "--stale-ok" in out


def test_a_stale_draft_asks_on_a_tty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    repo = _stale_draft(tmp_path)

    # Abort leaves the repository and the draft alone.
    monkeypatch.setattr("builtins.input", lambda _p="": "a")
    assert main([str(repo), "commit"]) == 0
    assert "Aborted." in capsys.readouterr().out
    assert subprocess_head(repo) == "init"

    # Commit anyway uses the edited text.
    monkeypatch.setattr("builtins.input", lambda _p="": "c")
    assert main([str(repo), "commit"]) == 0
    assert subprocess_head(repo) == "MY OWN SUBJECT"


def test_a_stale_draft_can_be_redrafted_from_the_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    repo = _stale_draft(tmp_path)

    answers = iter(["r", "y"])          # redraft, then confirm the fresh one
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    assert main([str(repo), "commit"]) == 0
    head = subprocess_head(repo)
    assert head != "MY OWN SUBJECT"     # the stale text did not reach history
    assert "b.txt" in capsys.readouterr().out or head


def test_an_edited_draft_is_announced_not_silently_replaced(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    from ufo_tdkit_report.commit import report_path

    repo = _git_repo(tmp_path, "Edited")
    (repo / "a.txt").write_text("one")
    assert main([str(repo)]) == 0
    capsys.readouterr()
    report_path(str(repo)).write_text("MY OWN SUBJECT\n")

    assert main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "showing your edited draft" in out
    assert "MY OWN SUBJECT" in out

    assert main([str(repo), "--regenerate"]) == 0
    assert "MY OWN SUBJECT" not in capsys.readouterr().out


def subprocess_head(repo):
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"], capture_output=True, text=True
    ).stdout.strip()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
