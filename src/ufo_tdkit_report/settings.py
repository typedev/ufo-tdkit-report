"""AI **accounts** and the single resolution chain for narration settings.

An account bundles what it takes to make a call — provider, model, language, base URL —
under a short name, and owns exactly one secret. Repositories reference an account *by
name* (see :mod:`registry`), so twenty corporate repos share one key stored once:

    <config>/.env          secrets only, 0600   TDREPORT_KEY_ACME=sk-...
    <config>/settings.json accounts, no secrets {"acme": {"provider": "openai", ...}}
    <config>/repos.json    bindings, no secrets {"acmesans": {"path": ..., "account": "acme"}}

Nothing tdreport-related is written inside the font repository: a config file there
would be committed and shared, which is exactly how keys leak. The process environment
is never consulted, for a key or for a preference.

Everything funnels through :func:`resolve_ai_settings`, which is the *only* place the
precedence order lives::

    explicit argument > repo entry > account > default account > built-in default

That single seam is why a library caller gets the owner's preferences too, not just the
CLI (the bug fixed in 0.1.2, generalised).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from ufo_tdkit_report.config import (
    LEGACY_KEY_VAR,
    LEGACY_MODEL_VAR,
    config_dir,
    config_env_path,
    delete_dotenv_var,
    read_dotenv_key,
    write_dotenv_var,
)
from ufo_tdkit_report.providers import (
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    NarratorError,
    Provider,
    get_provider,
)
from ufo_tdkit_report.registry import entry_for_path as _repo_entry_for_path

DEFAULT_ACCOUNT = "default"
_KEY_VAR_PREFIX = "TDREPORT_KEY_"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class Account:
    """One named set of AI settings. Holds no secret — the key is looked up by name."""

    name: str
    provider: str = DEFAULT_PROVIDER
    model: str = ""
    language: str = ""
    base_url: str = ""
    # Refuse a narration whose tokens the facts do not support, rather than warning.
    # A per-account setting because it belongs to the MODEL: a small local one earns
    # strictness, a large hosted one usually does not.
    strict_grounding: bool = False

    def to_dict(self) -> dict:
        out = {"provider": self.provider}
        for key in ("model", "language", "base_url"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if self.strict_grounding:
            out["strict_grounding"] = True
        return out


class UnboundRepoWarning(UserWarning):
    """A repository was named but is not registered, so its own settings did not apply.

    Its own category so a console front-end can silence it and print something friendlier,
    while a library consumer still sees it on stderr without opting in.
    """


@dataclass(frozen=True)
class AiSettings:
    """Everything one narration call needs, fully resolved. No further lookups."""

    account: str
    provider: Provider
    model: str
    language: str
    base_url: str
    api_key: str | None
    strict_grounding: bool = False
    # True/False when a repo was named (did it match a registry entry?), None when none
    # was. False is the dangerous case: settings silently came from the default account.
    repo_bound: bool | None = None

    def __repr__(self) -> str:
        """Never the key itself — a dataclass repr would print it verbatim.

        This object holds a live API key and ends up in places nobody chose to put it:
        a traceback frame, a pytest failure dump (which prints locals), a debugger, a
        `print()` during a bug hunt. Any one of those copies the key into a terminal
        scrollback or a CI log. The masked tail is still enough to tell two keys apart,
        which is the only thing a reader legitimately needs here. The provider is
        rendered by name for the same reason the mask exists: a full `Provider` dump
        buries the fields that matter in a model list.
        """
        return (
            f"AiSettings(account={self.account!r}, provider={self.provider.name!r}, "
            f"model={self.model!r}, language={self.language!r}, base_url={self.base_url!r}, "
            f"api_key={self.masked_api_key!r}, strict_grounding={self.strict_grounding!r}, "
            f"repo_bound={self.repo_bound!r})"
        )

    @property
    def masked_api_key(self) -> str:
        """Safe to print: presence and the last four characters, never the value."""
        if not self.api_key:
            return "not set"
        return f"set (…{self.api_key[-4:]})" if len(self.api_key) > 4 else "set"

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def require(self) -> AiSettings:
        """Raise unless this is actually callable (model chosen, key present if needed).

        Kept out of :func:`resolve_ai_settings` so a settings display can render a
        half-configured account instead of exploding.
        """
        if not self.model:
            raise NarratorError(
                f"no model set for account '{self.account}' (provider {self.provider.name}) — "
                f"run `tdreport set-model` to pick one"
            )
        if self.provider.requires_key and not self.api_key:
            raise NarratorError(
                f"no API key for account '{self.account}' (provider {self.provider.name}) — "
                f"store one with `tdreport set-key` (saved owner-only to {config_env_path()}), "
                f"or pass it explicitly"
            )
        return self


# --- the accounts file -------------------------------------------------------------


def settings_path() -> Path:
    """The non-secret settings file: ``<config>/settings.json``."""
    return config_dir() / "settings.json"


def load_settings() -> dict:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data: dict) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _legacy_default_account() -> Account:
    """The implicit ``default`` account for a config predating accounts.

    Before accounts there was one Anthropic key and one model preference in ``.env``.
    Those keep working untouched: they simply *are* the default account.
    """
    return Account(name=DEFAULT_ACCOUNT, provider=DEFAULT_PROVIDER)


def accounts() -> dict[str, Account]:
    """Every configured account. Always contains ``default``."""
    stored = load_settings().get("accounts")
    out: dict[str, Account] = {}
    if isinstance(stored, dict):
        for name, value in stored.items():
            if not isinstance(value, dict):
                continue
            out[str(name)] = Account(
                name=str(name),
                provider=str(value.get("provider") or DEFAULT_PROVIDER),
                model=str(value.get("model") or ""),
                language=str(value.get("language") or ""),
                base_url=str(value.get("base_url") or ""),
                strict_grounding=bool(value.get("strict_grounding")),
            )
    out.setdefault(DEFAULT_ACCOUNT, _legacy_default_account())
    return out


def default_account_name() -> str:
    """The account used when a repo names none."""
    name = load_settings().get("default")
    if isinstance(name, str) and name.strip() in accounts():
        return name.strip()
    return DEFAULT_ACCOUNT


def get_account(name: str | None = None) -> Account:
    """One account by name (the default when omitted). Unknown name -> NarratorError."""
    known = accounts()
    wanted = (name or default_account_name()).strip()
    if wanted in known:
        return known[wanted]
    raise NarratorError(f"unknown AI account '{wanted}' — known: {', '.join(sorted(known))}")


def validate_account_name(name: str) -> str:
    """Accept a usable account name or explain why not.

    Names become part of an env-var name, so two that differ only in punctuation would
    collide on the same secret — rejected up front rather than silently sharing a key.
    """
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid account name '{name}' — use letters, digits, dot, dash or underscore, "
            f"starting with a letter or digit"
        )
    var = key_var(name)
    for other in accounts():
        if other != name and key_var(other) == var:
            raise ValueError(f"account name '{name}' collides with '{other}' (both map to {var})")
    return name


def add_account(
    name: str,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str = "",
    language: str = "",
    base_url: str = "",
    strict_grounding: bool = False,
    make_default: bool = False,
) -> Account:
    """Create or replace an account. Stores no secret — use :func:`store_account_key`."""
    name = validate_account_name(name)
    get_provider(provider)  # reject an unknown provider before writing anything
    account = Account(
        name=name, provider=provider, model=model, language=language,
        base_url=base_url, strict_grounding=strict_grounding,
    )
    data = load_settings()
    stored = data.get("accounts")
    data["accounts"] = dict(stored) if isinstance(stored, dict) else {}
    data["accounts"][name] = account.to_dict()
    if make_default:
        # Only ever on request: creating a second account must not silently repoint
        # every unbound repository at it.
        data["default"] = name
    save_settings(data)
    return account


def update_account(name: str | None = None, **fields) -> Account:
    """Change fields of one account (the default when omitted); returns the new state."""
    account = get_account(name)
    unknown = set(fields) - {"provider", "model", "language", "base_url", "strict_grounding"}
    if unknown:
        raise ValueError(f"unknown account field(s): {', '.join(sorted(unknown))}")
    if "provider" in fields:
        get_provider(fields["provider"])
    coerced = {
        k: bool(v) if k == "strict_grounding" else (v or "")
        for k, v in fields.items()
    }
    updated = replace(account, **coerced)
    data = load_settings()
    stored = data.get("accounts")
    data["accounts"] = dict(stored) if isinstance(stored, dict) else {}
    data["accounts"][updated.name] = updated.to_dict()
    save_settings(data)
    return updated


def set_default_account(name: str) -> str:
    """Point new/unbound repos at ``name``. Unknown name -> NarratorError."""
    account = get_account(name)
    data = load_settings()
    data["default"] = account.name
    save_settings(data)
    return account.name


def remove_account(name: str, *, drop_key: bool = True) -> bool:
    """Delete an account and (by default) its stored secret.

    The secret goes with it: leaving an orphaned key in ``.env`` is exactly the kind of
    lingering credential this layout exists to avoid.
    """
    if name == DEFAULT_ACCOUNT:
        raise ValueError("the 'default' account cannot be removed")
    data = load_settings()
    stored = data.get("accounts")
    if not isinstance(stored, dict) or name not in stored:
        return False
    accounts_left = {k: v for k, v in stored.items() if k != name}
    data["accounts"] = accounts_left
    if data.get("default") == name:
        data["default"] = DEFAULT_ACCOUNT
    save_settings(data)
    if drop_key:
        delete_dotenv_var(config_env_path(), key_var(name))
    return True


# --- secrets -----------------------------------------------------------------------


def key_var(account: str) -> str:
    """The ``.env`` variable holding this account's secret."""
    return _KEY_VAR_PREFIX + re.sub(r"[^A-Za-z0-9]", "_", account).upper()


def store_account_key(key: str, *, account: str | None = None) -> Path:
    """Write one account's API key to ``<config>/.env``, owner-only. Returns the path."""
    name = (account or default_account_name()).strip()
    key = key.strip()
    if not key:
        raise ValueError("refusing to store an empty API key")
    return write_dotenv_var(config_env_path(), key_var(name), key)


def account_key(account: str | None = None) -> str | None:
    """This account's API key, or None.

    Falls back to the pre-accounts variable (``ANTHROPIC_API_KEY``) for the *default*
    account only, so an existing config keeps working; a named account never inherits
    another one's secret by accident.
    """
    name = (account or default_account_name()).strip()
    path = config_env_path()
    found = read_dotenv_key([path], key_var(name))
    if not found and name == DEFAULT_ACCOUNT:
        found = read_dotenv_key([path], LEGACY_KEY_VAR)
    if found:
        from ufo_tdkit_report.config import secure

        secure(path)  # tighten perms on read too, in case the file was hand-created
    return found


def has_key(account: str | None = None) -> bool:
    return bool(account_key(account))


def masked_key(account: str | None = None) -> str:
    """A safe-to-print rendering of a stored key: never the key itself."""
    key = account_key(account)
    if not key:
        return "not set"
    return f"set (…{key[-4:]})" if len(key) > 4 else "set"


# --- the one resolution chain ------------------------------------------------------


def _first_not_none(*values) -> bool:
    """The first value that was actually set, along the usual chain. Defaults to False."""
    for value in values:
        if value is not None:
            return bool(value)
    return False


def resolve_ai_settings(
    *,
    repo: str | Path | None = None,
    account: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    language: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    strict_grounding: bool | None = None,
) -> AiSettings:
    """Resolve narration settings once: explicit > repo > account > default > built-in.

    ``repo`` is a repository path; its registry entry (matched by path, so the plain
    ``tdreport`` in a cwd finds it too) supplies the account binding and any per-repo
    model/language override. Nothing here reads the process environment, and no secret
    is ever taken from anywhere but ``<config>/.env`` or the explicit argument.
    """
    found = _repo_entry_for_path(repo) if repo else None
    repo_bound = None if repo is None else found is not None
    entry = found or {}

    account_name = (account or entry.get("account") or default_account_name()).strip()
    acct = get_account(account_name)

    provider_obj = get_provider(provider or entry.get("provider") or acct.provider)

    resolved_model = model or entry.get("model") or acct.model
    if not resolved_model and acct.name == DEFAULT_ACCOUNT and provider_obj.name == DEFAULT_PROVIDER:
        # Pre-accounts configs kept the model preference in .env; honour it.
        resolved_model = read_dotenv_key([config_env_path()], LEGACY_MODEL_VAR) or ""
    resolved_model = resolved_model or provider_obj.default_model

    return AiSettings(
        account=acct.name,
        provider=provider_obj,
        model=resolved_model,
        language=(language or entry.get("language") or acct.language or DEFAULT_LANGUAGE).strip(),
        base_url=(base_url or acct.base_url or provider_obj.base_url),
        api_key=api_key or account_key(acct.name),
        repo_bound=repo_bound,
        strict_grounding=_first_not_none(
            strict_grounding, entry.get("strict_grounding"), acct.strict_grounding
        ),
    )


def warn_if_unbound(resolved: AiSettings, repo) -> bool:
    """Warn when a named repo is unregistered *and* the choice could have mattered.

    Silence here is the bad failure: a consumer hands over a path, no entry matches, and
    the narration quietly runs on the default account's provider and key. Only worth
    saying when more than one account exists — with a single account there is nothing the
    binding could have changed. Returns True if a warning was issued.
    """
    if resolved.repo_bound is not False or len(accounts()) < 2:
        return False
    import warnings

    warnings.warn(
        f"repo '{repo}' is not registered, so AI settings came from account "
        f"'{resolved.account}' ({resolved.provider.name}). Register it — `tdreport {repo}` — "
        f"or bind it with `tdreport bind <account> {repo}` if it should use another one.",
        UnboundRepoWarning,
        stacklevel=3,
    )
    return True


# --- pre-accounts API, kept working -------------------------------------------------


def store_api_key(key: str, *, var: str = LEGACY_KEY_VAR) -> Path:
    """Write the API key to ``<config>/.env`` under the pre-accounts variable name.

    Retained for library callers from before accounts existed. New code (and the CLI)
    uses :func:`store_account_key`, which scopes the secret to one account.
    """
    key = key.strip()
    if not key:
        raise ValueError("refusing to store an empty API key")
    return write_dotenv_var(config_env_path(), var, key)


def resolve_api_key(*, explicit: str | None = None) -> str | None:
    """The default account's API key. Explicit argument wins; the environment is ignored."""
    return explicit or account_key()


def store_model(model: str, *, var: str = LEGACY_MODEL_VAR) -> Path:
    """Persist the default account's model in ``<config>/.env`` (pre-accounts form)."""
    model = model.strip()
    if not model:
        raise ValueError("refusing to store an empty model id")
    return write_dotenv_var(config_env_path(), var, model)


def resolve_model(*, explicit: str | None = None) -> str:
    """The model that would actually be used, through the full chain."""
    return resolve_ai_settings(model=explicit).model or DEFAULT_MODEL
