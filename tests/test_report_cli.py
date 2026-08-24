"""Tests for the CLI dispatch bits that carry their own logic (`tdreport set-model`).

No network and no git: `list_models` degrades to the built-in list without a key, and
the config dir is redirected to tmp_path, so the picker is exercised offline.
"""

import pytest

from ufo_tdkit_report.cli import _choose_model, main
from ufo_tdkit_report.narrator import DEFAULT_MODEL, resolve_model

MODELS = [("claude-opus-5", "Claude Opus 5"), ("claude-haiku-4-5", "Claude Haiku 4.5")]


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
