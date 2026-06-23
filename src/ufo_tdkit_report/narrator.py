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


def resolve_api_key(repo: str | Path = ".", *, explicit: str | None = None) -> str | None:
    """Resolve the API key without leaking it system-wide.

    Order: explicit arg → ``ANTHROPIC_API_KEY`` env → ``.env`` in the repo/cwd →
    this tool's own config (``<config>/.env`` or a plain ``<config>/anthropic_key`` file) —
    so the key can live once in ``~/.config/ufo-tdkit-report/`` and be read from any repo.
    """
    if explicit:
        return explicit
    from_env = os.environ.get(_API_KEY_VAR)
    if from_env:
        return from_env
    config = config_dir()
    key = read_dotenv_key([Path(repo) / ".env", Path.cwd() / ".env", config / ".env"])
    if key:
        return key
    # Plain key file: the whole file is just the key.
    key_file = config / "anthropic_key"
    if key_file.is_file():
        try:
            text = key_file.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        if text:
            return text.splitlines()[0].strip()
    return None

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TIMEOUT = 60

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


def _call(system: str, user: str, *, model, api_key, transport, max_tokens, timeout) -> str:
    key = api_key or os.environ.get(_API_KEY_VAR)
    if not key:
        raise NarratorError(f"{_API_KEY_VAR} is not set (AI narration is opt-in)")
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
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    transport=_http_post,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Narrate the facts as a grounded git commit message (subject + body, no <details>)."""
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
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    transport=_http_post,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Return a grounded Markdown narrative with the deterministic facts attached.

    The deterministic facts are always appended in a ``<details>`` block so the
    ground truth travels with the prose and can be verified before publishing.
    """
    key = api_key or os.environ.get(_API_KEY_VAR)
    if not key:
        raise NarratorError(f"{_API_KEY_VAR} is not set (AI narration is opt-in)")

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
