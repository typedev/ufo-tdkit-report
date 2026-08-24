"""Tests for the grounded AI narrator (issue #5, phase 5).

No network: the prompt assembly and response parsing are pure, and `narrate` takes
an injected transport so the HTTP layer is never exercised here.
"""

import stat

import pytest

from ufo_tdkit_report.model import FactType, FileKind, FoldedFact, RangeReport
from ufo_tdkit_report.narrator import (
    DEFAULT_MODEL,
    KNOWN_MODELS,
    NarratorError,
    build_messages,
    config_dir,
    config_env_path,
    list_models,
    narrate,
    parse_message_response,
    parse_models_response,
    read_dotenv_key,
    resolve_api_key,
    resolve_model,
    store_api_key,
    store_model,
)


def _report():
    facts = [
        FoldedFact(FactType.OUTLINE_REDRAWN, FileKind.GLIF, "outline redrawn in `Ring` (~24 points moved)"),
        FoldedFact(FactType.FEA_RULE_ADDED, FileKind.FEATURES, "feature ss02: rule added `sub a by a.ss02;`"),
    ]
    return RangeReport(
        range_spec="v1..HEAD",
        commits=[("abc1234def", "features: wire ss02 alternates")],
        folded_facts=facts,
        raw_fact_count=2,
    )


def test_build_messages_includes_facts_and_grounding():
    system, user = build_messages(_report())
    assert "ONLY the facts" in system
    assert "never" in system.lower()
    # The actual facts must be in the user content (the model's ground truth).
    assert "outline redrawn in `Ring`" in user
    assert "features: wire ss02 alternates" in user


def test_parse_message_response_extracts_text():
    data = {
        "type": "message",
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "## Notes\n\nOutlines were redrawn."},
        ],
    }
    assert parse_message_response(data) == "## Notes\n\nOutlines were redrawn."


def test_parse_message_response_refusal_raises():
    with pytest.raises(NarratorError, match="refused"):
        parse_message_response({"stop_reason": "refusal", "content": []})


def test_parse_message_response_api_error_raises():
    data = {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}
    with pytest.raises(NarratorError, match="authentication_error"):
        parse_message_response(data)


def test_parse_message_response_empty_raises():
    with pytest.raises(NarratorError, match="empty"):
        parse_message_response({"stop_reason": "end_turn", "content": []})


def test_narrate_wires_transport_and_attaches_facts():
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return {
            "type": "message",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "## Release\n\nRing was redrawn."}],
        }

    out = narrate(_report(), api_key="test-key", transport=fake_transport)

    # Narrative prose present.
    assert "Ring was redrawn." in out
    # Deterministic facts attached verbatim for verification.
    assert "<details>" in out
    assert "outline redrawn in `Ring`" in out
    assert "verify before publishing" in out
    # Request shape: correct endpoint, headers, model.
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert DEFAULT_MODEL.encode() in captured["body"]  # default model, via the one constant


def test_narrate_missing_key_raises():
    # No env fallback any more: a missing api_key is an explicit error.
    with pytest.raises(NarratorError, match="set-key"):
        narrate(_report(), api_key=None, transport=lambda *a, **k: {})


def test_read_dotenv_key_parses_forms(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "OTHER=ignore\n"
        'export ANTHROPIC_API_KEY="sk-ant-quoted"\n'
    )
    assert read_dotenv_key([env]) == "sk-ant-quoted"


def test_read_dotenv_key_plain_and_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-plain\nPATH=/should/not/matter\n")
    assert read_dotenv_key([env]) == "sk-plain"
    assert read_dotenv_key([tmp_path / "nope.env"]) is None


def test_resolve_api_key_explicit_wins(tmp_path, monkeypatch):
    # The explicit argument short-circuits before any disk access.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert resolve_api_key(explicit="explicit") == "explicit"


def test_resolve_api_key_ignores_env_and_local_dotenv(tmp_path, monkeypatch):
    # The two sources are explicit + <config>/.env ONLY: not the process env,
    # not a repo/cwd .env. A stray export or local .env must not leak in.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("ANTHROPIC_API_KEY=from-local-dotenv\n")
    monkeypatch.chdir(repo)
    assert resolve_api_key() is None  # env + local .env are both ignored


def test_resolve_api_key_from_config_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    config = tmp_path / "cfg" / "ufo-tdkit-report"
    config.mkdir(parents=True)
    assert config_dir() == config  # honors XDG_CONFIG_HOME
    (config / ".env").write_text("ANTHROPIC_API_KEY=from-tdkit-config\n")
    assert resolve_api_key() == "from-tdkit-config"


def test_store_api_key_writes_single_file_owner_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    path = store_api_key("  sk-ant-stored  ")  # whitespace is trimmed
    assert path == config_env_path()
    assert path.read_text() == "ANTHROPIC_API_KEY=sk-ant-stored\n"
    # 0600: not readable/writable by group or other.
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # Round-trips through the resolver.
    assert resolve_api_key() == "sk-ant-stored"


def test_store_api_key_rejects_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    with pytest.raises(ValueError, match="empty"):
        store_api_key("   ")


def test_resolve_model_precedence(tmp_path, monkeypatch):
    # explicit argument > stored preference > built-in default.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert resolve_model() == DEFAULT_MODEL
    store_model("claude-haiku-4-5")
    assert resolve_model() == "claude-haiku-4-5"
    assert resolve_model(explicit="claude-opus-4-8") == "claude-opus-4-8"


def test_resolve_model_ignores_process_env(tmp_path, monkeypatch):
    # Same discipline as the API key: the process environment is never consulted.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("TDREPORT_AI_MODEL", "from-env")
    assert resolve_model() == DEFAULT_MODEL


def test_store_model_preserves_the_api_key(tmp_path, monkeypatch):
    # Both live in <config>/.env: storing one must not clobber the other, in either order.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    store_api_key("sk-ant-stored")
    path = store_model("claude-sonnet-5")
    assert path == config_env_path()
    assert resolve_api_key() == "sk-ant-stored"
    assert resolve_model() == "claude-sonnet-5"

    store_api_key("sk-ant-rotated")  # rotating the key keeps the model preference
    assert resolve_model() == "claude-sonnet-5"
    assert resolve_api_key() == "sk-ant-rotated"

    # Still owner-only, and re-setting a var rewrites in place rather than appending.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    store_model("claude-opus-5")
    assert path.read_text().count("TDREPORT_AI_MODEL=") == 1


def test_store_model_rejects_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    with pytest.raises(ValueError, match="empty"):
        store_model("  ")


def test_write_dotenv_var_keeps_unrelated_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    path = config_env_path()
    path.parent.mkdir(parents=True)
    path.write_text("# hand-written\nOTHER=keep-me\nexport ANTHROPIC_API_KEY=sk-hand\n")

    store_model("claude-sonnet-5")
    text = path.read_text()
    assert "# hand-written" in text
    assert "OTHER=keep-me" in text
    assert resolve_api_key() == "sk-hand"  # the `export ` form survives untouched
    assert resolve_model() == "claude-sonnet-5"


def test_parse_models_response():
    data = {
        "data": [
            {"type": "model", "id": "claude-opus-5", "display_name": "Claude Opus 5"},
            {"type": "model", "id": "claude-haiku-4-5"},  # no display_name -> falls back to the id
            {"type": "model", "id": ""},  # unusable, dropped
        ]
    }
    assert parse_models_response(data) == [
        ("claude-opus-5", "Claude Opus 5"),
        ("claude-haiku-4-5", "claude-haiku-4-5"),
    ]
    assert parse_models_response({"type": "error", "error": {"message": "nope"}}) == []
    assert parse_models_response({}) == []


def test_list_models_uses_transport():
    captured = {}

    def fake_transport(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return {"data": [{"id": "claude-opus-5", "display_name": "Claude Opus 5"}]}

    models = list_models(api_key="test-key", transport=fake_transport)
    assert models == [("claude-opus-5", "Claude Opus 5")]
    assert captured["url"].startswith("https://api.anthropic.com/v1/models")
    assert captured["headers"]["x-api-key"] == "test-key"


def test_list_models_falls_back_offline():
    # Picking a model must work with no key, no network, and on an unusable response.
    def boom(url, headers, timeout):
        raise NarratorError("network error: unreachable")

    assert list_models(api_key=None) == list(KNOWN_MODELS)
    assert list_models(api_key="k", transport=boom) == list(KNOWN_MODELS)
    assert list_models(api_key="k", transport=lambda *a: {"data": []}) == list(KNOWN_MODELS)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
