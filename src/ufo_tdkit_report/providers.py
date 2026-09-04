"""The API providers the narrator can talk to, and the two dialects they speak.

There are not N integrations here, there is a **table**. Every provider worth
supporting speaks one of exactly two HTTP dialects:

- ``anthropic`` — the Messages API (``/messages``, ``x-api-key``, top-level ``system``);
- ``openai``    — the OpenAI-compatible ``/chat/completions`` that Google (through its
  ``/v1beta/openai`` compatibility layer), xAI, Mistral, Groq, DeepSeek, DashScope
  (Qwen), Moonshot, Z.ai, Ollama, LM Studio, vLLM and OpenRouter all implement.

So adding a provider is one row, and running against a local model is a row with a
``localhost`` base URL and ``requires_key=False``. Everything stays on ``urllib``:
no vendor SDK, no third-party dependency, consistent with the rest of the tool.

The model lists below are **hints** for the offline picker only. The live
``/models`` endpoint is authoritative wherever it is reachable, and any id the API
accepts can be typed by hand — nothing here locks a model out.
"""

from __future__ import annotations

from dataclasses import dataclass

ANTHROPIC_API_VERSION = "2023-06-01"

# The one built-in default, and the single source of truth for it (see CLAUDE.md).
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_LANGUAGE = "English"
# Covers the WHOLE completion, reasoning included — a reasoning model can spend the lot
# thinking and return no text, which off the wire is indistinguishable from having
# nothing to say. Hence a cap far larger than any narration needs. It is still not
# enough for every model (a DeepSeek reasoner ate all 8192 on a small report), which is
# why it is now a *setting* rather than only a flag: raise it per account or per repo.
# Don't raise it globally — `max_tokens` goes to all fourteen providers, and some models
# cap their output well below a number chosen to suit the most talkative one.
DEFAULT_MAX_TOKENS = 8192


class NarratorError(RuntimeError):
    """Raised when narration cannot be produced (no key, network, refusal, bad shape).

    Defined here rather than in ``narrator`` so the dialect adapters can raise it
    without importing the narrator (which imports this module). It is re-exported
    from ``narrator`` and the package root, where callers have always found it.
    """


@dataclass(frozen=True)
class Provider:
    """One API endpoint family: where to POST, how to authenticate, what to expect back."""

    name: str
    label: str
    dialect: str  # "anthropic" | "openai"
    base_url: str
    default_model: str  # "" -> the user must pick one (ids move too fast to guess)
    known_models: tuple[tuple[str, str], ...] = ()
    requires_key: bool = True
    # OpenAI's own newer models reject `max_tokens` and want `max_completion_tokens`;
    # every other OpenAI-compatible server still wants `max_tokens`.
    max_tokens_field: str = "max_tokens"
    # The conventional env-var name for this vendor's key. NOT read from the process
    # environment (that discipline is absolute) — shown in help text, and read from
    # <config>/.env as a legacy fallback for the pre-accounts single-key layout.
    legacy_key_var: str = ""
    notes: str = ""


_ANTHROPIC_MODELS = (
    ("claude-opus-5", "Claude Opus 5"),
    ("claude-opus-4-8", "Claude Opus 4.8"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
)

PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (
        Provider(
            name="anthropic",
            label="Anthropic (Claude)",
            dialect="anthropic",
            base_url="https://api.anthropic.com/v1",
            default_model=DEFAULT_MODEL,
            known_models=_ANTHROPIC_MODELS,
            legacy_key_var="ANTHROPIC_API_KEY",
        ),
        Provider(
            name="openai",
            label="OpenAI (GPT / Codex models)",
            dialect="openai",
            base_url="https://api.openai.com/v1",
            default_model="",
            known_models=(("gpt-5", "GPT-5"), ("gpt-5-mini", "GPT-5 mini"), ("gpt-4o", "GPT-4o")),
            max_tokens_field="max_completion_tokens",
            legacy_key_var="OPENAI_API_KEY",
            notes="`codex` is OpenAI's coding agent, not a separate API — it runs these models.",
        ),
        Provider(
            name="xai",
            label="xAI (Grok)",
            dialect="openai",
            base_url="https://api.x.ai/v1",
            default_model="",
            known_models=(("grok-4", "Grok 4"), ("grok-3", "Grok 3"), ("grok-3-mini", "Grok 3 mini")),
            legacy_key_var="XAI_API_KEY",
        ),
        Provider(
            name="gemini",
            label="Google (Gemini)",
            dialect="openai",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            default_model="",
            known_models=(
                ("gemini-3.8-flash", "Gemini 3.8 Flash"),
                ("gemini-3.7-flash", "Gemini 3.7 Flash"),
                ("gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)"),
                ("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ),
            legacy_key_var="GEMINI_API_KEY",
            notes="Google's OpenAI-compatible layer; the native generateContent API is not used.",
        ),
        Provider(
            name="mistral",
            label="Mistral AI",
            dialect="openai",
            base_url="https://api.mistral.ai/v1",
            default_model="",
            known_models=(
                ("mistral-large-latest", "Mistral Large"),
                ("mistral-medium-latest", "Mistral Medium"),
                ("mistral-small-latest", "Mistral Small"),
                ("codestral-latest", "Codestral"),
            ),
            legacy_key_var="MISTRAL_API_KEY",
        ),
        Provider(
            name="groq",
            label="Groq (fast open models)",
            dialect="openai",
            base_url="https://api.groq.com/openai/v1",
            default_model="",
            known_models=(
                ("openai/gpt-oss-120b", "GPT-OSS 120B"),
                ("openai/gpt-oss-20b", "GPT-OSS 20B"),
                ("llama-3.3-70b-versatile", "Llama 3.3 70B"),
            ),
            legacy_key_var="GROQ_API_KEY",
        ),
        Provider(
            name="deepseek",
            label="DeepSeek",
            dialect="openai",
            base_url="https://api.deepseek.com/v1",
            default_model="",
            known_models=(("deepseek-chat", "DeepSeek Chat"), ("deepseek-reasoner", "DeepSeek Reasoner")),
            legacy_key_var="DEEPSEEK_API_KEY",
        ),
        Provider(
            name="qwen",
            label="Qwen (Alibaba DashScope)",
            dialect="openai",
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            default_model="",
            known_models=(("qwen-max", "Qwen Max"), ("qwen-plus", "Qwen Plus"), ("qwen-turbo", "Qwen Turbo")),
            legacy_key_var="DASHSCOPE_API_KEY",
            notes="Mainland-China endpoint: set a base URL of https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        Provider(
            name="moonshot",
            label="Moonshot (Kimi)",
            dialect="openai",
            base_url="https://api.moonshot.ai/v1",
            default_model="",
            known_models=(
                ("kimi-k3", "Kimi K3"),
                ("kimi-k2.7-code", "Kimi K2.7 Code"),
                ("kimi-k2.6", "Kimi K2.6"),
            ),
            legacy_key_var="MOONSHOT_API_KEY",
            notes="Mainland-China endpoint: set a base URL of https://api.moonshot.cn/v1",
        ),
        Provider(
            name="zai",
            label="Z.ai (GLM)",
            dialect="openai",
            base_url="https://api.z.ai/api/paas/v4",
            default_model="",
            known_models=(("glm-5.3", "GLM-5.3"), ("glm-5.2", "GLM-5.2"), ("glm-4.7", "GLM-4.7")),
            legacy_key_var="ZAI_API_KEY",
            notes="Coding-plan endpoint: set a base URL of https://api.z.ai/api/coding/paas/v4",
        ),
        Provider(
            name="openrouter",
            label="OpenRouter (many vendors, one key)",
            dialect="openai",
            base_url="https://openrouter.ai/api/v1",
            default_model="",
            legacy_key_var="OPENROUTER_API_KEY",
        ),
        Provider(
            name="ollama",
            label="Ollama (local)",
            dialect="openai",
            base_url="http://localhost:11434/v1",
            default_model="",
            requires_key=False,
            notes="Models come from `ollama pull`; the live list is the truth.",
        ),
        Provider(
            name="lmstudio",
            label="LM Studio (local)",
            dialect="openai",
            base_url="http://localhost:1234/v1",
            default_model="",
            requires_key=False,
        ),
        Provider(
            name="custom",
            label="Custom OpenAI-compatible endpoint",
            dialect="openai",
            base_url="",
            default_model="",
            requires_key=False,
            notes="Point it at any OpenAI-compatible server (vLLM, llama.cpp, a gateway) with a base URL.",
        ),
    )
}


def get_provider(name: str | None) -> Provider:
    """Look a provider up by name. Unknown -> NarratorError naming the valid ones."""
    key = (name or DEFAULT_PROVIDER).strip().lower()
    provider = PROVIDERS.get(key)
    if provider is None:
        raise NarratorError(f"unknown AI provider '{name}' — known: {', '.join(sorted(PROVIDERS))}")
    return provider


def _base(provider: Provider, base_url: str | None = None) -> str:
    base = (base_url or provider.base_url or "").rstrip("/")
    if not base:
        raise NarratorError(
            f"provider '{provider.name}' has no base URL — set one for the account "
            f"(e.g. http://localhost:8000/v1)"
        )
    return base


def messages_url(provider: Provider, base_url: str | None = None) -> str:
    base = _base(provider, base_url)
    return f"{base}/messages" if provider.dialect == "anthropic" else f"{base}/chat/completions"


def models_url(provider: Provider, base_url: str | None = None) -> str:
    return f"{_base(provider, base_url)}/models"


def build_headers(provider: Provider, api_key: str | None) -> dict[str, str]:
    """Auth + content headers for one request. Pure."""
    headers = {"content-type": "application/json"}
    if provider.dialect == "anthropic":
        headers["x-api-key"] = api_key or ""
        headers["anthropic-version"] = ANTHROPIC_API_VERSION
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def build_payload(provider: Provider, *, model: str, system: str, user: str, max_tokens: int) -> dict:
    """The request body for one narration call. Pure.

    The two dialects differ in exactly two places: where the system prompt goes, and
    what the token cap is called.
    """
    if provider.dialect == "anthropic":
        return {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    return {
        "model": model,
        provider.max_tokens_field: max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def _error_text(data: dict) -> str | None:
    """The error message in either dialect's error payload, if this is one."""
    if data.get("type") == "error" and isinstance(data.get("error"), dict):
        err = data["error"]
        return f"{err.get('type')}: {err.get('message')}"
    err = data.get("error")
    if isinstance(err, dict):  # OpenAI-compatible: a bare top-level "error" object
        return f"{err.get('type') or err.get('code')}: {err.get('message')}"
    if isinstance(err, str) and err:  # Ollama returns a plain string
        return err
    return None


def _content_text(content) -> str:
    """Flatten a message content that may be a string or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _truncation_error(data: dict, max_tokens_field: str) -> NarratorError:
    """Explain an answer that never started because the token cap ran out.

    A reasoning model spends the SAME budget on its private reasoning and on the answer,
    so a cap sized for the answer alone can be consumed entirely before a single visible
    token is written. The response then looks identical to a model with nothing to say —
    hence the numbers, and the way out.
    """
    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens")
    spent = usage.get("completion_tokens") or usage.get("output_tokens")
    why = f"all {reasoning} of them on internal reasoning" if reasoning else "before writing anything"
    return NarratorError(
        f"the model hit its token cap ({spent} tokens, {why}) and produced no text. "
        f"Raise the cap with `--ai-max-tokens` (this is a reasoning model spending the "
        f"same budget on thinking and on the answer), or pick a non-reasoning model."
    )


def parse_message(provider: Provider, data: dict) -> str:
    """Extract narrative text from a response in this provider's dialect. Pure.

    Raises NarratorError on an API error, a refusal, a truncation, or an unexpected shape
    — an empty narrative must never be mistaken for a report with nothing to say.
    """
    detail = _error_text(data)
    if detail:
        raise NarratorError(f"API error: {detail}")

    if provider.dialect == "anthropic":
        if data.get("stop_reason") == "refusal":
            raise NarratorError("model refused to generate the narrative")
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "".join(parts).strip()
        truncated = data.get("stop_reason") == "max_tokens"
    else:
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise NarratorError("unexpected response shape: no choices")
        message = choices[0].get("message") or {}
        if message.get("refusal"):
            raise NarratorError(f"model refused to generate the narrative: {message['refusal']}")
        if choices[0].get("finish_reason") == "content_filter":
            raise NarratorError("model refused to generate the narrative (content filter)")
        text = _content_text(message.get("content")).strip()
        truncated = choices[0].get("finish_reason") == "length"

    if not text:
        if truncated:
            raise _truncation_error(data, provider.max_tokens_field)
        raise NarratorError("empty narrative from model")
    return text


def parse_models(provider: Provider, data: dict) -> list[tuple[str, str]]:
    """Extract ``[(id, label), ...]`` from a ``/models`` response. Pure.

    Returns ``[]`` on an error payload or an unexpected shape — the caller falls back
    to the provider's hint list rather than failing, since this only feeds a picker.
    Both dialects use ``{"data": [{"id": ...}]}``; only Anthropic adds a display name.
    """
    if _error_text(data):
        return []
    models: list[tuple[str, str]] = []
    for entry in data.get("data") or []:
        if not isinstance(entry, dict):
            continue
        model_id = (entry.get("id") or "").strip()
        if model_id:
            models.append((model_id, (entry.get("display_name") or model_id).strip()))
    return models
