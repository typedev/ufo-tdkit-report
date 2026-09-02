"""Optional, grounded AI narration of report facts.

Turns the deterministic facts + commit history into release-notes prose. The
narrator is STRICTLY grounded: it may only restate the facts it is given, never
invent glyph names, codepoint meanings, or option semantics. The motivating miss
was an ungrounded model parroting a doc error about a hinting flag and inventing a
name for an unassigned codepoint — so the deterministic facts are always attached
verbatim in a ``<details>`` block for verification, and this layer never publishes
anything.

Provider-agnostic: *where* the request goes and *what shape* it takes live in
:mod:`providers` (a table plus two dialects), *which* settings apply lives in
:mod:`settings` (one resolution chain). This module owns only the prompts, the
grounding rules, and the HTTP plumbing. No vendor SDK and no third-party deps — the
call is a plain ``urllib`` POST, and the transport is injected so prompt assembly and
response parsing are unit-testable without the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ufo_tdkit_report.config import (
    config_dir,
    config_env_path,
    read_dotenv_key,
)
from ufo_tdkit_report.model import RangeReport, SourceReport
from ufo_tdkit_report.providers import (
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
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
from ufo_tdkit_report.settings import (
    AiSettings,
    resolve_ai_settings,
    resolve_api_key,
    resolve_model,
    store_account_key,
    store_api_key,
    store_model,
    warn_if_unbound,
)

# Re-exported so the pre-accounts import sites keep working unchanged.
__all__ = [
    "DEFAULT_LANGUAGE",
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "KNOWN_MODELS",
    "NarratorError",
    "build_messages",
    "config_dir",
    "config_env_path",
    "list_models",
    "narrate",
    "narrate_commit",
    "parse_message_response",
    "parse_models_response",
    "read_dotenv_key",
    "resolve_ai_settings",
    "resolve_api_key",
    "resolve_model",
    "store_account_key",
    "store_api_key",
    "store_model",
]

# The cap covers the WHOLE completion, and a reasoning model spends it on its private
# reasoning first — 2048 was enough for the prose but got eaten entirely by thinking on
# DeepSeek's reasoners, yielding an empty answer. It is a cap, not a charge: nothing is
# paid for tokens that are not generated, so it costs a non-reasoning model nothing.
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TIMEOUT = 60
# Local servers load the model on the first request; a cloud-sized timeout is not enough.
LOCAL_TIMEOUT = 300

# The offline fallback for the Anthropic picker, kept at this name for compatibility.
# Every provider carries its own hint list in `providers.PROVIDERS`.
KNOWN_MODELS: tuple[tuple[str, str], ...] = PROVIDERS[DEFAULT_PROVIDER].known_models


_GROUNDING_RULES = """\
- Use ONLY the facts and commit subjects provided. Never add a glyph, codepoint,
  feature, metric, or build option that is not in the facts.
- Never invent or guess the NAME or MEANING of a codepoint, glyph, or build option.
  If a fact says `uni20C5`, write `uni20C5` — do not name it. If you do not know what
  an option does, describe only that it changed; do not explain its effect.
- Do not editorialize about quality, intent, or impact beyond what the facts state.
  Where the facts are ambiguous, hedge ("appears to", "according to the source diff").\
"""

_SYSTEM_PROMPT = f"""\
You write release notes for a font from a list of DETERMINISTIC, machine-extracted
source-change facts and commit subjects. The facts are ground truth; the commit
subjects are the human authors' own words.

Rules — follow them exactly:
{_GROUNDING_RULES}
- Group related facts into a few themed paragraphs (e.g. outline/drawing changes,
  spacing/kerning, OpenType features, metadata/build settings). Be concise.
- Output GitHub-flavored Markdown: a short title line, then themed prose. No preamble
  like "Here are the notes". Do not restate the raw fact list — it is attached
  separately for verification.\
"""


_COMMIT_SYSTEM_PROMPT = f"""\
You write a git COMMIT MESSAGE for a font from a list of DETERMINISTIC, machine-extracted
source-change facts (uncommitted working-tree changes).

Rules — follow them exactly:
{_GROUNDING_RULES}
- Output a real commit message: a single concise SUBJECT line (≤ 72 chars, imperative mood,
  no trailing period), then a blank line, then a short body of `- ` bullets grouping the
  changes. No Markdown headings, no preamble, no "verify before publishing" notes.\
"""


def language_rule(language: str | None) -> str:
    """The prose-language instruction, or ``""`` for the default English.

    Only the *prose* is translated. Identifiers must survive verbatim: a model asked to
    write in German will otherwise cheerfully "translate" a glyph name, which is exactly
    the ungrounded invention this whole layer exists to prevent. The deterministic
    report, the attached facts and the attribution footer stay English regardless — they
    are machine output, and localizing them would make the byte-stable report depend on
    a local preference.
    """
    language = (language or "").strip()
    if not language or language.casefold() == DEFAULT_LANGUAGE.casefold():
        return ""
    return (
        f"\n- Write the prose in {language}. Keep every identifier VERBATIM in its original "
        f"form — glyph names, codepoints (`uni20C5`), OpenType feature/class/table tags, "
        f"master and instance names, file paths and build-option keys are never translated, "
        f"transliterated, or re-cased."
    )


def _commit_language_rule(language: str | None) -> str:
    rule = language_rule(language)
    if not rule:
        return ""
    return rule + (
        "\n- Keep the conventional-commit type prefix (`feat:`, `fix:`, `chore:`) in English: "
        "it is syntax, not prose."
    )


def _facts_block(report: SourceReport | RangeReport) -> str:
    """The deterministic facts as the model sees them (and as we attach for verify).

    Rendered without the attribution footer — the narrated output carries its own
    single AI footer, so the embedded ``<details>`` report must not repeat it.
    """
    from ufo_tdkit_report.render import render_range_report, render_report

    if isinstance(report, RangeReport):
        return render_range_report(report, footer=False)
    return render_report(report, footer=False)


def build_messages(report: SourceReport | RangeReport, *, language: str | None = None) -> tuple[str, str]:
    """Assemble (system_prompt, user_content) for the narration call. Pure."""
    facts = _facts_block(report)
    user = (
        "Write release notes from the following deterministic font source-change "
        "report. Stay strictly within these facts.\n\n"
        f"{facts}\n"
    )
    return _SYSTEM_PROMPT + language_rule(language), user


def parse_message_response(data: dict) -> str:
    """Extract narrative text from an Anthropic Messages API response. Pure.

    Kept for compatibility; the dialect-aware entry point is
    :func:`providers.parse_message`.
    """
    return parse_message(PROVIDERS[DEFAULT_PROVIDER], data)


def parse_models_response(data: dict) -> list[tuple[str, str]]:
    """Extract ``[(id, display_name), ...]`` from an Anthropic Models response. Pure."""
    return parse_models(PROVIDERS[DEFAULT_PROVIDER], data)


def _http_post(url: str, headers: dict, body: bytes, timeout: int) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(detail)  # API errors come back as JSON with an error payload
        except json.JSONDecodeError:
            raise NarratorError(f"HTTP {exc.code}: {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise NarratorError(f"network error: {exc.reason}") from exc


def _http_get(url: str, headers: dict, timeout: int) -> dict:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(detail)
        except json.JSONDecodeError:
            raise NarratorError(f"HTTP {exc.code}: {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise NarratorError(f"network error: {exc.reason}") from exc


def list_models(
    *,
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    transport=_http_get,
    timeout: int = DEFAULT_TIMEOUT,
    limit: int = 100,
) -> list[tuple[str, str]]:
    """Models this key can use, newest first: ``[(id, label), ...]``.

    Asks the provider's ``/models`` endpoint so the picker never goes stale, and degrades
    to the provider's built-in hint list when there is no key, no network, or an unusable
    response — picking a model must work offline. ``transport`` is injected for tests.
    """
    prov = get_provider(provider)
    fallback = list(prov.known_models)
    if prov.requires_key and not api_key:
        return fallback
    try:
        url = models_url(prov, base_url)
    except NarratorError:
        return fallback
    if prov.dialect == "anthropic":
        url = f"{url}?limit={limit}"
    try:
        data = transport(url, build_headers(prov, api_key), timeout)
    except NarratorError:
        return fallback
    return parse_models(prov, data) or fallback


def _timeout_for(settings: AiSettings, timeout: int | None) -> int:
    """Explicit timeout wins; a local endpoint gets a longer one (cold model load)."""
    if timeout is not None:
        return timeout
    return LOCAL_TIMEOUT if not settings.provider.requires_key else DEFAULT_TIMEOUT


def _call(system: str, user: str, *, settings: AiSettings, transport, max_tokens: int, timeout: int) -> str:
    settings.require()
    payload = build_payload(
        settings.provider,
        model=settings.model,
        system=system,
        user=user,
        max_tokens=max_tokens,
    )
    headers = build_headers(settings.provider, settings.api_key)
    url = messages_url(settings.provider, settings.base_url)
    data = transport(url, headers, json.dumps(payload).encode("utf-8"), timeout)
    return parse_message(settings.provider, data)


def narrate_commit(
    report: SourceReport,
    *,
    model: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
    language: str | None = None,
    account: str | None = None,
    repo: str | None = None,
    transport=_http_post,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int | None = None,
) -> str:
    """Narrate the facts as a grounded git commit message (subject + body, no <details>).

    Every unset argument resolves through :func:`settings.resolve_ai_settings`, so a
    library caller that picks nothing still gets the owner's account, model, provider and
    language rather than a signature-frozen default.
    """
    # `.require()` up front: a missing key or model must fail before any work, not after
    # the prompt has been assembled (embedding callers rely on the early NarratorError).
    # The report remembers where it came from, so a caller that forgets `repo=` still
    # gets that repository's own account, model and language rather than the default
    # account's — forgetting used to fail silently, with the wrong provider and key.
    repo = repo or getattr(report, "repo", None)
    resolved = resolve_ai_settings(
        repo=repo, account=account, provider=provider, model=model, language=language, api_key=api_key
    )
    warn_if_unbound(resolved, repo)
    settings = resolved.require()
    facts = _facts_block(report)
    user = (
        "Write a git commit message from the following deterministic source-change facts. "
        "Stay strictly within these facts.\n\n"
        f"{facts}\n"
    )
    system = _COMMIT_SYSTEM_PROMPT + _commit_language_rule(settings.language)
    from ufo_tdkit_report.render import _credit

    msg = _call(
        system, user, settings=settings, transport=transport,
        max_tokens=max_tokens, timeout=_timeout_for(settings, timeout),
    ).rstrip()
    return f"{msg}\n\n{_credit(ai=True, model=settings.model, provider=settings.provider_name)}\n"


def narrate(
    report: SourceReport | RangeReport,
    *,
    model: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
    language: str | None = None,
    account: str | None = None,
    repo: str | None = None,
    transport=_http_post,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int | None = None,
) -> str:
    """Return a grounded Markdown narrative with the deterministic facts attached.

    The deterministic facts are always appended in a ``<details>`` block so the
    ground truth travels with the prose and can be verified before publishing. The
    facts, the footer and the section headings stay English whatever the prose
    language is: they are deterministic output and must not vary per user.
    """
    # The report remembers where it came from, so a caller that forgets `repo=` still
    # gets that repository's own account, model and language rather than the default
    # account's — forgetting used to fail silently, with the wrong provider and key.
    repo = repo or getattr(report, "repo", None)
    resolved = resolve_ai_settings(
        repo=repo, account=account, provider=provider, model=model, language=language, api_key=api_key
    )
    warn_if_unbound(resolved, repo)
    settings = resolved.require()
    system, user = build_messages(report, language=settings.language)
    narrative = _call(
        system, user, settings=settings, transport=transport,
        max_tokens=max_tokens, timeout=_timeout_for(settings, timeout),
    )

    from ufo_tdkit_report.render import attribution

    facts = _facts_block(report)
    return (
        f"{narrative}\n\n"
        f"> AI-drafted from deterministic facts — verify before publishing.\n\n"
        f"<details>\n<summary>Technical details (deterministic, auto-generated — verify here)</summary>\n\n"
        f"{facts}\n\n</details>\n\n"
        f"{attribution(ai=True, model=settings.model, provider=settings.provider_name)}\n"
    )
