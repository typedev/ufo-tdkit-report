"""Optional, grounded AI narration of report facts (issue #5, phase 5).

Turns the deterministic facts + commit history into release-notes prose. The
narrator is STRICTLY grounded: it may only restate the facts it is given, never
invent glyph names, codepoint meanings, or option semantics. The motivating miss
was an ungrounded model parroting a doc error about a hinting flag and inventing a
name for an unassigned codepoint — so the deterministic facts are always attached
verbatim in a ``<details>`` block for verification, and this layer never publishes
anything.

No ``anthropic`` SDK and no third-party deps — the Anthropic call is a plain
``urllib`` POST so the feature stays opt-in and out of the core dependency set.
The HTTP transport is injected so the prompt assembly and response parsing are
unit-testable without the network.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from ufo_tdkit_report.model import RangeReport, SourceReport

_API_KEY_VAR = "ANTHROPIC_API_KEY"
_MODEL_VAR = "TDREPORT_AI_MODEL"


def read_dotenv_key(paths: list[Path], var: str = _API_KEY_VAR) -> str | None:
    """Read a single env var from the first existing ``.env`` file in ``paths``.

    Targeted on purpose: parses only ``var`` (default ANTHROPIC_API_KEY) and never
    touches the process environment or other keys (so it can't clobber PATH). Accepts
    ``KEY=value``, ``export KEY=value``, and quoted values; ignores comments/blanks.
    """
    for path in paths:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            key, _, value = line.partition("=")
            if key.strip() != var:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                return value
    return None


CONFIG_DIR_NAME = "ufo-tdkit-report"


def config_dir() -> Path:
    """This tool's own OS-specific config directory."""
    import sys

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / CONFIG_DIR_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / CONFIG_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / CONFIG_DIR_NAME


def config_env_path() -> Path:
    """The single file the Anthropic API key lives in: ``<config>/.env``."""
    return config_dir() / ".env"


def _secure(path: Path) -> None:
    """Best-effort: lock ``path`` to owner-only (0600) and its parent dir to 0700.

    A no-op on platforms without POSIX permission bits (e.g. Windows), where the
    user-profile directory ACL already governs access. Errors are swallowed so a
    read/store never fails just because the perms could not be tightened.
    """
    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except (OSError, NotImplementedError):
        pass


def _write_dotenv_var(path: Path, var: str, value: str) -> Path:
    """Set ``var`` in a ``.env`` file, preserving every other line. Owner-only.

    The config file holds both the secret key and the non-secret model preference, so a
    write must never clobber the entries it is not touching (storing a model must not
    drop the API key). Rewrites an existing definition in place, appends otherwise, and
    collapses duplicate definitions of the same var.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    out: list[str] = []
    replaced = False
    for raw in lines:
        stripped = raw.strip()
        candidate = stripped[len("export ") :].lstrip() if stripped.startswith("export ") else stripped
        if candidate.partition("=")[0].strip() == var:
            if replaced:
                continue  # a duplicate definition of the same var: drop it
            out.append(f"{var}={value}")
            replaced = True
        else:
            out.append(raw)
    if not replaced:
        out.append(f"{var}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    _secure(path)
    return path


def store_api_key(key: str, *, var: str = _API_KEY_VAR) -> Path:
    """Write the API key to its single home (``<config>/.env``), owner-only.

    Creates the config dir if needed and locks the file down to 0600 so the secret is
    not group/world-readable. Returns the path written. Raises ``ValueError`` on an
    empty key.
    """
    key = key.strip()
    if not key:
        raise ValueError("refusing to store an empty API key")
    return _write_dotenv_var(config_env_path(), var, key)


def resolve_api_key(*, explicit: str | None = None) -> str | None:
    """Resolve the Anthropic API key from the two — and only two — supported sources.

    Order: an explicit argument (a library caller passing its own key) → ``<config>/.env``
    (the single on-disk home, written by ``tdreport set-key``). Nothing else is consulted:
    not the process environment, not the repo, not the cwd. The key therefore lives in
    exactly one place, owner-only, and cannot leak in from a stray ``.env`` or a shell
    ``export`` that happens to be set.
    """
    if explicit:
        return explicit
    path = config_env_path()
    key = read_dotenv_key([path])
    if key:
        _secure(path)  # tighten perms on read too, in case the file was hand-created
    return key


def store_model(model: str, *, var: str = _MODEL_VAR) -> Path:
    """Persist the preferred narration model in ``<config>/.env``. Returns the path.

    Sits beside the API key in the one config file (the key's other entries are
    preserved). Raises ``ValueError`` on an empty id. Written by ``tdreport set-model``.
    """
    model = model.strip()
    if not model:
        raise ValueError("refusing to store an empty model id")
    return _write_dotenv_var(config_env_path(), var, model)


def resolve_model(*, explicit: str | None = None) -> str:
    """Resolve the narration model: explicit argument -> ``<config>/.env`` -> ``DEFAULT_MODEL``.

    The same two-source discipline as :func:`resolve_api_key`, plus a built-in default:
    a per-run ``--ai-model`` wins, then the preference stored by ``tdreport set-model``,
    then :data:`DEFAULT_MODEL`. The process environment is never consulted.
    """
    if explicit:
        return explicit
    return read_dotenv_key([config_env_path()], _MODEL_VAR) or DEFAULT_MODEL


API_URL = "https://api.anthropic.com/v1/messages"
MODELS_URL = "https://api.anthropic.com/v1/models"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TIMEOUT = 60

# The menu `tdreport set-model` falls back to when the live list cannot be fetched (no
# key, no network). A convenience only: any id the API accepts can still be set by hand,
# and the live list is authoritative when it is reachable.
KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ("claude-opus-5", "Claude Opus 5"),
    ("claude-opus-4-8", "Claude Opus 4.8"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
)

_SYSTEM_PROMPT = """\
You write release notes for a font from a list of DETERMINISTIC, machine-extracted
source-change facts and commit subjects. The facts are ground truth; the commit
subjects are the human authors' own words.

Rules — follow them exactly:
- Use ONLY the facts and commit subjects provided. Never add a glyph, codepoint,
  feature, metric, or build option that is not in the facts.
- Never invent or guess the NAME or MEANING of a codepoint, glyph, or build option.
  If a fact says `uni20C5`, write `uni20C5` — do not name it. If you do not know what
  an option does, describe only that it changed; do not explain its effect.
- Do not editorialize about quality, intent, or impact beyond what the facts state.
  Where the facts are ambiguous, hedge ("appears to", "according to the source diff").
- Group related facts into a few themed paragraphs (e.g. outline/drawing changes,
  spacing/kerning, OpenType features, metadata/build settings). Be concise.
- Output GitHub-flavored Markdown: a short title line, then themed prose. No preamble
  like "Here are the notes". Do not restate the raw fact list — it is attached
  separately for verification.
"""


_COMMIT_SYSTEM_PROMPT = """\
You write a git COMMIT MESSAGE for a font from a list of DETERMINISTIC, machine-extracted
source-change facts (uncommitted working-tree changes).

Rules — follow them exactly:
- Use ONLY the facts provided. Never add a glyph, codepoint, feature, metric, or option that
  is not in the facts. Never invent or guess the name/meaning of a codepoint or glyph.
- Output a real commit message: a single concise SUBJECT line (≤ 72 chars, imperative mood,
  no trailing period), then a blank line, then a short body of `- ` bullets grouping the
  changes. No Markdown headings, no preamble, no "verify before publishing" notes.
- Be terse and factual; where the facts are ambiguous, hedge ("appears to").
"""


def _facts_block(report: SourceReport | RangeReport) -> str:
    """The deterministic facts as the model sees them (and as we attach for verify).

    Rendered without the attribution footer — the narrated output carries its own
    single AI footer, so the embedded ``<details>`` report must not repeat it.
    """
    from ufo_tdkit_report.render import render_range_report, render_report

    if isinstance(report, RangeReport):
        return render_range_report(report, footer=False)
    return render_report(report, footer=False)


def build_messages(report: SourceReport | RangeReport) -> tuple[str, str]:
    """Assemble (system_prompt, user_content) for the Anthropic call. Pure."""
    facts = _facts_block(report)
    user = (
        "Write release notes from the following deterministic font source-change "
        "report. Stay strictly within these facts.\n\n"
        f"{facts}\n"
    )
    return _SYSTEM_PROMPT, user


def parse_message_response(data: dict) -> str:
    """Extract narrative text from an Anthropic Messages API response. Pure.

    Raises NarratorError on a refusal or an unexpected shape.
    """
    if data.get("type") == "error":
        err = data.get("error", {})
        raise NarratorError(f"API error: {err.get('type')}: {err.get('message')}")
    if data.get("stop_reason") == "refusal":
        raise NarratorError("model refused to generate the narrative")
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise NarratorError("empty narrative from model")
    return text


class NarratorError(RuntimeError):
    """Raised when narration cannot be produced (no key, network, refusal, bad shape)."""


def _missing_key_error() -> NarratorError:
    """A NarratorError that names the single place to put the key."""
    return NarratorError(
        f"no Anthropic API key — store one with `tdreport set-key <KEY>` "
        f"(saved owner-only to {config_env_path()}), or pass it explicitly"
    )


def _http_post(url: str, headers: dict, body: bytes, timeout: int) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(detail)  # API errors come back as JSON with type=error
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
            return json.loads(detail)  # API errors come back as JSON with type=error
        except json.JSONDecodeError:
            raise NarratorError(f"HTTP {exc.code}: {detail[:200]}") from exc
    except urllib.error.URLError as exc:
        raise NarratorError(f"network error: {exc.reason}") from exc


def parse_models_response(data: dict) -> list[tuple[str, str]]:
    """Extract ``[(id, display_name), ...]`` from a Models API response. Pure.

    Returns ``[]`` on an error payload or an unexpected shape — the caller falls back to
    :data:`KNOWN_MODELS` rather than failing, since this only feeds a picker.
    """
    if data.get("type") == "error":
        return []
    models: list[tuple[str, str]] = []
    for entry in data.get("data") or []:
        if not isinstance(entry, dict):
            continue
        model_id = (entry.get("id") or "").strip()
        if model_id:
            models.append((model_id, (entry.get("display_name") or model_id).strip()))
    return models


def list_models(
    *,
    api_key: str | None = None,
    transport=_http_get,
    timeout: int = DEFAULT_TIMEOUT,
    limit: int = 100,
) -> list[tuple[str, str]]:
    """Models this key can use, newest first: ``[(id, display_name), ...]``.

    Asks the Anthropic Models API so the picker never goes stale, and degrades to
    :data:`KNOWN_MODELS` when there is no key, no network, or an unusable response —
    picking a model must work offline. ``transport`` is injected for offline tests.
    """
    if not api_key:
        return list(KNOWN_MODELS)
    headers = {"x-api-key": api_key, "anthropic-version": API_VERSION}
    try:
        data = transport(f"{MODELS_URL}?limit={limit}", headers, timeout)
    except NarratorError:
        return list(KNOWN_MODELS)
    return parse_models_response(data) or list(KNOWN_MODELS)


def _call(system: str, user: str, *, model, api_key, transport, max_tokens, timeout) -> str:
    if not api_key:
        raise _missing_key_error()
    key = api_key
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    data = transport(API_URL, headers, json.dumps(payload).encode("utf-8"), timeout)
    return parse_message_response(data)


def narrate_commit(
    report: SourceReport,
    *,
    model: str | None = None,
    api_key: str | None = None,
    transport=_http_post,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Narrate the facts as a grounded git commit message (subject + body, no <details>).

    ``model=None`` resolves through :func:`resolve_model`, so a library caller that does
    not pick a model still gets the owner's ``tdreport set-model`` preference rather than
    the built-in default.
    """
    model = resolve_model(explicit=model)
    facts = _facts_block(report)
    user = (
        "Write a git commit message from the following deterministic source-change facts. "
        "Stay strictly within these facts.\n\n"
        f"{facts}\n"
    )
    from ufo_tdkit_report.render import _credit

    msg = _call(_COMMIT_SYSTEM_PROMPT, user, model=model, api_key=api_key,
                transport=transport, max_tokens=max_tokens, timeout=timeout).rstrip()
    return f"{msg}\n\n{_credit(ai=True, model=model)}\n"


def narrate(
    report: SourceReport | RangeReport,
    *,
    model: str | None = None,
    api_key: str | None = None,
    transport=_http_post,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Return a grounded Markdown narrative with the deterministic facts attached.

    The deterministic facts are always appended in a ``<details>`` block so the
    ground truth travels with the prose and can be verified before publishing.

    ``model=None`` resolves through :func:`resolve_model`, so a library caller that does
    not pick a model still gets the owner's ``tdreport set-model`` preference rather than
    the built-in default.
    """
    if not api_key:
        raise _missing_key_error()
    key = api_key
    model = resolve_model(explicit=model)

    system, user = build_messages(report)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    data = transport(API_URL, headers, json.dumps(payload).encode("utf-8"), timeout)
    narrative = parse_message_response(data)

    from ufo_tdkit_report.render import attribution

    facts = _facts_block(report)
    return (
        f"{narrative}\n\n"
        f"> AI-drafted from deterministic facts — verify before publishing.\n\n"
        f"<details>\n<summary>Technical details (deterministic, auto-generated — verify here)</summary>\n\n"
        f"{facts}\n\n</details>\n\n"
        f"{attribution(ai=True, model=model)}\n"
    )
