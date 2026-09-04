"""Tests for the grounded AI narrator.

No network: the prompt assembly and response parsing are pure, and `narrate` takes
an injected transport so the HTTP layer is never exercised here.
"""

import json
import os
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
    language_rule,
    list_models,
    narrate,
    narrate_commit,
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


def test_narrate_wires_transport_and_attaches_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))  # no stored preference
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


def test_narrate_honors_the_stored_model_preference(tmp_path, monkeypatch):
    # A library caller that passes no model must still get the owner's `set-model`
    # preference: the default is resolved inside narrate(), not frozen in the signature.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    store_model("claude-haiku-4-5")
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["body"] = body
        return {"content": [{"type": "text", "text": "ok"}]}

    out = narrate(_report(), api_key="test-key", transport=fake_transport)
    assert b'"model": "claude-haiku-4-5"' in captured["body"]
    assert "claude-haiku-4-5" in out  # and the attribution names what actually ran

    # An explicit argument still wins over the stored preference.
    narrate(_report(), model="claude-opus-4-8", api_key="test-key", transport=fake_transport)
    assert b'"model": "claude-opus-4-8"' in captured["body"]


def test_narrate_commit_honors_the_stored_model_preference(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    store_model("claude-haiku-4-5")
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["body"] = body
        return {"content": [{"type": "text", "text": "fix: redraw Ring"}]}

    out = narrate_commit(_report(), api_key="test-key", transport=fake_transport)
    assert b'"model": "claude-haiku-4-5"' in captured["body"]
    assert "claude-haiku-4-5" in out

    narrate_commit(_report(), model="claude-opus-4-8", api_key="test-key", transport=fake_transport)
    assert b'"model": "claude-opus-4-8"' in captured["body"]


def test_narrate_missing_key_raises(tmp_path, monkeypatch):
    # With nothing configured and nothing passed, narration is an explicit error that
    # names where the key goes. (XDG is redirected so the developer's own stored key
    # cannot make this pass or fail by accident.)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    with pytest.raises(NarratorError, match="set-key"):
        narrate(_report(), api_key=None, transport=lambda *a, **k: {})


def test_narrate_resolves_the_stored_key_when_none_is_passed(tmp_path, monkeypatch):
    # Same rule as the model preference: a caller that passes nothing gets the owner's
    # configured account, rather than being refused for a key that is sitting right there.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    store_api_key("sk-ant-stored")
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["headers"] = headers
        return {"content": [{"type": "text", "text": "ok"}]}

    narrate(_report(), transport=fake_transport)
    assert captured["headers"]["x-api-key"] == "sk-ant-stored"


def _key_file(path, body):
    """A .env written the way the tool writes one: owner-only.

    Left at the default umask it is world-readable, which now (correctly) raises
    `InsecureKeyFileWarning` — the fixture has to match reality or it tests a file
    shape the tool never produces.
    """
    path.write_text(body)
    if os.name != "nt":
        path.chmod(0o600)
    return path


def test_read_dotenv_key_parses_forms(tmp_path):
    env = _key_file(tmp_path / ".env",
        "# a comment\n"
        "OTHER=ignore\n"
        'export ANTHROPIC_API_KEY="sk-ant-quoted"\n'
    )
    assert read_dotenv_key([env]) == "sk-ant-quoted"


def test_read_dotenv_key_plain_and_missing(tmp_path):
    env = _key_file(tmp_path / ".env", "ANTHROPIC_API_KEY=sk-plain\nPATH=/should/not/matter\n")
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
    _key_file(config / ".env", "ANTHROPIC_API_KEY=from-tdkit-config\n")
    assert resolve_api_key() == "from-tdkit-config"


def test_store_api_key_writes_single_file_owner_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))

    path = store_api_key("  sk-ant-stored  ")  # whitespace is trimmed
    assert path == config_env_path()
    assert path.read_text() == "ANTHROPIC_API_KEY=sk-ant-stored\n"
    # 0600: not readable/writable by group or other.
    if os.name == "posix":
        # Windows chmod cannot express 0600; the user-profile ACL protects the file
        # instead (see `config.secure`). The storage behaviour below is checked anyway.
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
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
    if os.name == "posix":
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


def test_a_report_carries_its_repo_so_a_caller_cannot_forget(tmp_path, monkeypatch):
    """`narrate(report)` finds that repository's account without being told twice.

    The consumer used to have to remember `repo=`; forgetting it failed silently, on the
    default account's provider and key. Now the report knows where it came from.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    import subprocess

    from ufo_tdkit_report import extract_working_facts, registry, settings

    repo = tmp_path / "MyFont"
    (repo / "sources").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    (repo / "a.txt").write_text("x")

    settings.add_account("work", provider="deepseek", model="deepseek-chat")
    settings.store_account_key("sk-work", account="work")
    registry.add("MyFont", str(repo), account="work")

    # Built from a SUBDIRECTORY, and narrated with no repo= at all.
    report = extract_working_facts(str(repo / "sources"))
    assert report.repo == str(repo / "sources")

    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["url"] = url
        captured["auth"] = headers.get("Authorization")
        return {"choices": [{"message": {"content": "prose"}}]}

    narrate(report, transport=fake_transport)
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-work"


def test_the_repo_never_reaches_the_output(tmp_path, monkeypatch):
    """It is a machine-local path: in the report it would break byte-stability."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    import subprocess

    from ufo_tdkit_report import extract_working_facts

    repo = tmp_path / "MyFont"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    (repo / "a.txt").write_text("x")

    report = extract_working_facts(str(repo))
    assert report.repo == str(repo)
    assert "repo" not in report.to_dict()
    assert str(repo) not in report.render_text()


# --- providers and language ---------------------------------------------------------


def test_narrate_through_an_openai_dialect_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    settings.add_account("work", provider="deepseek", model="deepseek-chat")
    settings.store_account_key("sk-work", account="work")
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(body)
        return {"choices": [{"finish_reason": "stop", "message": {"content": "Prose."}}]}

    out = narrate(_report(), account="work", transport=fake_transport)

    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-work"
    assert captured["body"]["messages"][0]["role"] == "system"  # OpenAI dialect shape
    assert captured["body"]["model"] == "deepseek-chat"
    assert "Prose." in out
    # The facts still travel with the prose, and the footer names what produced it.
    assert "<details>" in out
    assert "outline redrawn in `Ring`" in out
    assert "deepseek/deepseek-chat" in out


def test_language_rule_only_applies_to_prose_and_protects_identifiers():
    assert language_rule(None) == ""
    assert language_rule("English") == ""  # the default adds nothing to the prompt
    rule = language_rule("Spanish")
    assert "Write the prose in Spanish" in rule
    assert "VERBATIM" in rule
    assert "uni20C5" in rule  # the model is shown what must not be translated


def test_language_reaches_the_prompt_but_not_the_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["body"] = json.loads(body)
        return {"content": [{"type": "text", "text": "Notas."}]}

    out = narrate(_report(), api_key="k", language="Spanish", transport=fake_transport)
    assert "Write the prose in Spanish" in captured["body"]["system"]
    # The deterministic half stays English: headings, facts and footer are machine output.
    assert "## Source changes" in out
    assert "Generated by tdreport" in out


def test_commit_narration_keeps_the_conventional_commit_prefix_english(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    captured = {}

    def fake_transport(url, headers, body, timeout):
        captured["body"] = json.loads(body)
        return {"content": [{"type": "text", "text": "fix: redibujar Ring"}]}

    narrate_commit(_report(), api_key="k", language="Spanish", transport=fake_transport)
    system = captured["body"]["system"]
    assert "Write the prose in Spanish" in system
    assert "conventional-commit type prefix" in system


def test_list_models_for_an_openai_dialect_provider():
    captured = {}

    def fake_transport(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return {"data": [{"id": "deepseek-chat"}]}

    models = list_models(provider="deepseek", api_key="k", transport=fake_transport)
    assert models == [("deepseek-chat", "deepseek-chat")]
    assert captured["url"] == "https://api.deepseek.com/v1/models"
    assert "limit=" not in captured["url"]  # an Anthropic-only query param
    assert captured["headers"]["Authorization"] == "Bearer k"


def test_list_models_queries_a_keyless_local_provider():
    # Ollama needs no key, so an empty key must not short-circuit the live list.
    def fake_transport(url, headers, timeout):
        assert url == "http://localhost:11434/v1/models"
        return {"data": [{"id": "llama3.2"}]}

    assert list_models(provider="ollama", transport=fake_transport) == [("llama3.2", "llama3.2")]


def test_end_to_end_over_real_http_against_a_loopback_server(tmp_path, monkeypatch):
    """The real urllib path, not the injected transport: a stub OpenAI-compatible server.

    Everything else here injects `transport`, which never exercises `_http_post` itself —
    the one place a header/encoding mistake would hide. Loopback only, no network.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings

    received = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep pytest output clean
            pass

        def do_POST(self):
            received["path"] = self.path
            received["auth"] = self.headers.get("Authorization")
            received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            payload = json.dumps(
                {"choices": [{"finish_reason": "stop", "message": {"content": "Se redibujó Ring."}}]}
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        settings.add_account("local", provider="custom", model="stub-7b", language="Spanish", base_url=base)
        settings.store_account_key("sk-local", account="local")
        out = narrate(_report(), account="local", timeout=10)
    finally:
        server.shutdown()

    assert received["path"] == "/v1/chat/completions"
    assert received["auth"] == "Bearer sk-local"
    assert received["body"]["model"] == "stub-7b"
    assert "Write the prose in Spanish" in received["body"]["messages"][0]["content"]
    # Prose in Spanish; the deterministic half and the footer stay English.
    assert "Se redibujó Ring." in out
    assert "## Source changes" in out
    assert "custom/stub-7b" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_the_resolved_cap_and_strictness_reach_the_request(monkeypatch, tmp_path):
    """Both were accepted by the public signature and thrown away.

    `max_tokens` defaulted to a concrete number in the signature — the pattern CLAUDE.md
    forbids for model and provider, and for the same reason: it silently overrode what
    the owner had configured. `strict_grounding` was worse: it was never passed to the
    resolver at all, so `--strict-grounding` and `narrate(strict_grounding=True)` did
    nothing. A flag that quietly does nothing is worse than one that does not exist,
    because this one is a safety setting.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from ufo_tdkit_report import settings
    from ufo_tdkit_report.providers import DEFAULT_MAX_TOKENS

    settings.store_account_key("sk-x")
    seen = {}

    def transport(url, headers, body, timeout):
        seen.update(json.loads(body))
        return {"content": [{"type": "text", "text": "Outlines were redrawn."}], "stop_reason": "end_turn"}

    narrate(_report(), transport=transport)
    assert seen["max_tokens"] == DEFAULT_MAX_TOKENS

    settings.update_account("default", max_tokens=32000)
    narrate(_report(), transport=transport)
    assert seen["max_tokens"] == 32000, "the account's cap must win over the built-in"

    narrate(_report(), transport=transport, max_tokens=4096)
    assert seen["max_tokens"] == 4096, "an explicit argument must win over the account"

    # Strictness now actually reaches the check: an ungrounded narration is refused.
    def inventing(url, headers, body, timeout):
        return {
            "content": [{"type": "text", "text": "Redrew `guillemotleft` at U+FFFE."}],
            "stop_reason": "end_turn",
        }

    with pytest.raises(NarratorError, match="grounding"):
        narrate(_report(), transport=inventing, strict_grounding=True)
