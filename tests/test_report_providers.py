"""Tests for the provider table and the two API dialects.

Pure functions only — no network, no transport. What matters here is that the two
dialects differ in exactly the places they are supposed to and nowhere else.
"""

import pytest

from ufo_tdkit_report.providers import (
    PROVIDERS,
    NarratorError,
    build_headers,
    build_payload,
    get_provider,
    messages_url,
    models_url,
    parse_message,
    parse_models,
)

ANTHROPIC = PROVIDERS["anthropic"]
OPENAI = PROVIDERS["openai"]
DEEPSEEK = PROVIDERS["deepseek"]
GEMINI = PROVIDERS["gemini"]
OLLAMA = PROVIDERS["ollama"]


def test_every_provider_row_is_usable():
    for name, provider in PROVIDERS.items():
        assert provider.name == name
        assert provider.dialect in ("anthropic", "openai")
        assert provider.label
        # A keyless provider is a local one; it must point somewhere local or be custom.
        if not provider.requires_key and provider.base_url:
            assert "localhost" in provider.base_url


def test_every_keyed_provider_has_a_reachable_https_base_url():
    """A row whose base URL is wrong is indistinguishable from a dead key at runtime.

    Nothing here calls the network; this only asserts the shape a row must have to be
    usable at all, so a typo in a new row fails at import time rather than on someone's
    first paid call.
    """
    for provider in PROVIDERS.values():
        if provider.name == "custom":  # the one row that is deliberately blank
            continue
        assert provider.base_url.startswith(("https://", "http://localhost"))
        assert not provider.base_url.endswith("/")  # `_base` rstrips, so keep it canonical
        if provider.requires_key:
            assert provider.legacy_key_var


def test_gemini_rides_the_openai_dialect_on_a_nested_base_path():
    """Google's compatibility layer lives under /v1beta/openai, not at the host root.

    It is the only row whose base URL has a path segment beyond the version, so the
    URL join is worth pinning: a lost `/openai` is a 404 that reads like a bad key.
    """
    assert GEMINI.dialect == "openai"
    assert messages_url(GEMINI) == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert models_url(GEMINI) == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    assert build_headers(GEMINI, "k")["Authorization"] == "Bearer k"
    # Gemini is not OpenAI: it takes the ordinary `max_tokens`, not the newer field.
    assert build_payload(GEMINI, model="m", system="s", user="u", max_tokens=7)["max_tokens"] == 7


def test_get_provider_unknown_names_the_valid_ones():
    with pytest.raises(NarratorError, match="deepseek"):
        get_provider("gpt")


def test_urls_per_dialect_and_base_override():
    assert messages_url(ANTHROPIC) == "https://api.anthropic.com/v1/messages"
    assert messages_url(DEEPSEEK) == "https://api.deepseek.com/v1/chat/completions"
    assert models_url(DEEPSEEK) == "https://api.deepseek.com/v1/models"
    # A per-account base URL wins, and a trailing slash does not double up.
    assert messages_url(OLLAMA, "http://box:8000/v1/") == "http://box:8000/v1/chat/completions"


def test_custom_provider_without_a_base_url_is_an_explicit_error():
    with pytest.raises(NarratorError, match="base URL"):
        messages_url(PROVIDERS["custom"])


def test_headers_carry_the_right_auth_scheme():
    assert build_headers(ANTHROPIC, "k")["x-api-key"] == "k"
    assert build_headers(ANTHROPIC, "k")["anthropic-version"] == "2023-06-01"
    assert build_headers(DEEPSEEK, "k")["Authorization"] == "Bearer k"
    # A keyless local server gets no Authorization header at all.
    assert "Authorization" not in build_headers(OLLAMA, None)


def test_payload_shapes_differ_only_where_the_apis_do():
    anthropic = build_payload(ANTHROPIC, model="m", system="SYS", user="USR", max_tokens=7)
    assert anthropic == {
        "model": "m",
        "max_tokens": 7,
        "system": "SYS",
        "messages": [{"role": "user", "content": "USR"}],
    }
    openai_like = build_payload(DEEPSEEK, model="m", system="SYS", user="USR", max_tokens=7)
    assert openai_like["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USR"},
    ]
    assert openai_like["max_tokens"] == 7
    assert "system" not in openai_like
    # OpenAI's own newer models reject `max_tokens`.
    assert build_payload(OPENAI, model="m", system="s", user="u", max_tokens=7)["max_completion_tokens"] == 7
    assert "max_tokens" not in build_payload(OPENAI, model="m", system="s", user="u", max_tokens=7)


def test_parse_message_openai_dialect():
    data = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Prose."}}]}
    assert parse_message(DEEPSEEK, data) == "Prose."
    # Some servers return content as a list of parts.
    parts = {"choices": [{"message": {"content": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}}]}
    assert parse_message(DEEPSEEK, parts) == "AB"


def test_parse_message_openai_refusals_and_errors():
    with pytest.raises(NarratorError, match="refused"):
        parse_message(DEEPSEEK, {"choices": [{"message": {"refusal": "no"}}]})
    with pytest.raises(NarratorError, match="content filter"):
        parse_message(DEEPSEEK, {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]})
    with pytest.raises(NarratorError, match="invalid_api_key"):
        parse_message(DEEPSEEK, {"error": {"type": "invalid_api_key", "message": "bad"}})
    with pytest.raises(NarratorError, match="model not found"):
        parse_message(OLLAMA, {"error": "model not found"})  # Ollama returns a bare string
    with pytest.raises(NarratorError, match="no choices"):
        parse_message(DEEPSEEK, {"choices": []})
    with pytest.raises(NarratorError, match="empty"):
        parse_message(DEEPSEEK, {"choices": [{"message": {"content": "   "}}]})


def test_truncation_before_any_text_is_named_not_called_empty():
    """A reasoning model can spend the whole cap thinking, and answer nothing.

    Off the wire that is indistinguishable from a model with nothing to say, so the
    error has to carry the numbers and the way out. Shape below is DeepSeek's, verbatim.
    """
    data = {
        "choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "…"}}],
        "usage": {
            "completion_tokens": 2048,
            "completion_tokens_details": {"reasoning_tokens": 2048},
        },
    }
    with pytest.raises(NarratorError) as exc:
        parse_message(DEEPSEEK, data)
    message = str(exc.value)
    assert "token cap" in message
    assert "2048" in message
    assert "internal reasoning" in message
    assert "--ai-max-tokens" in message

    # Anthropic signals the same thing with stop_reason.
    with pytest.raises(NarratorError, match="token cap"):
        parse_message(ANTHROPIC, {"stop_reason": "max_tokens", "content": [], "usage": {"output_tokens": 900}})

    # A genuinely empty answer that was NOT truncated keeps the plain message.
    with pytest.raises(NarratorError, match="empty narrative"):
        parse_message(DEEPSEEK, {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]})


def test_a_reasoning_model_that_did_answer_is_returned_normally():
    # `reasoning_content` sits beside the answer and is not part of the narrative.
    data = {"choices": [{"finish_reason": "stop", "message": {
        "content": "Outlines were redrawn.", "reasoning_content": "thinking out loud"}}]}
    assert parse_message(DEEPSEEK, data) == "Outlines were redrawn."


def test_parse_message_anthropic_dialect_is_unchanged():
    data = {"type": "message", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Prose."}]}
    assert parse_message(ANTHROPIC, data) == "Prose."
    with pytest.raises(NarratorError, match="refused"):
        parse_message(ANTHROPIC, {"stop_reason": "refusal", "content": []})


def test_parse_models_both_dialects():
    # OpenAI-compatible lists carry no display name: the id is the label.
    assert parse_models(DEEPSEEK, {"data": [{"id": "deepseek-chat", "object": "model"}]}) == [
        ("deepseek-chat", "deepseek-chat")
    ]
    assert parse_models(ANTHROPIC, {"data": [{"id": "x", "display_name": "X"}]}) == [("x", "X")]
    assert parse_models(DEEPSEEK, {"error": {"message": "nope"}}) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
