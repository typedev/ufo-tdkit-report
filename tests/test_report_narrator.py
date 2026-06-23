"""Tests for the grounded AI narrator (issue #5, phase 5).

No network: the prompt assembly and response parsing are pure, and `narrate` takes
an injected transport so the HTTP layer is never exercised here.
"""

import pytest

from ufo_tdkit_report.model import FactType, FileKind, FoldedFact, RangeReport
from ufo_tdkit_report.narrator import (
    NarratorError,
    build_messages,
    config_dir,
    narrate,
    parse_message_response,
    read_dotenv_key,
    resolve_api_key,
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
    assert b"claude-sonnet-4-6" in captured["body"]  # default model


def test_narrate_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(NarratorError, match="ANTHROPIC_API_KEY"):
        narrate(_report(), transport=lambda *a, **k: {})


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


def test_resolve_api_key_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-dotenv\n")

    # explicit wins over everything
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert resolve_api_key(tmp_path, explicit="explicit") == "explicit"
    # env wins over .env
    assert resolve_api_key(tmp_path) == "from-env"
    # falls back to .env when env is unset
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert resolve_api_key(tmp_path) == "from-dotenv"


def test_resolve_api_key_from_tool_config(tmp_path, monkeypatch):
    # Key in the tool's config dir is read from any repo (no system-wide export).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    repo = tmp_path / "some-font-repo"
    repo.mkdir()
    monkeypatch.chdir(repo)  # isolate cwd so a real ./.env isn't read
    config = tmp_path / "cfg" / "ufo-tdkit-report"
    config.mkdir(parents=True)
    assert config_dir() == config  # honors XDG_CONFIG_HOME
    # no .env in repo or cwd → falls through to config/.env
    (config / ".env").write_text("ANTHROPIC_API_KEY=from-tdkit-config\n")
    assert resolve_api_key(repo) == "from-tdkit-config"
    # plain key file also works
    (config / ".env").unlink()
    (config / "anthropic_key").write_text("sk-ant-plainfile\n")
    assert resolve_api_key(repo) == "sk-ant-plainfile"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
