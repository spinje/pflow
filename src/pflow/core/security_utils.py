"""Security utilities for sensitive data handling.

This module provides shared constants and functions for identifying and masking
sensitive parameters across CLI and MCP server contexts.
"""

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

# Sensitive parameter names to mask/redact
# This set is used to identify parameters that may contain credentials, tokens,
# or other sensitive information that shouldn't be logged or displayed
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "api_token",
    "access_token",
    "auth_token",
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "client_secret",
    "private_key",
    "ssh_key",
    "secret_key",
    "credential",
    "credentials",
    "authorization",
    "auth",
    "cookie",
    "cookies",
}


# Split a parameter name into words on snake_case / kebab-case / dotted / camelCase boundaries.
_WORD_BOUNDARY = re.compile(r"[_\-.\s]+|(?<=[a-z0-9])(?=[A-Z])")


def _word_signature(key: str) -> str:
    """Normalize a parameter name to a sentinel-bounded ``_word_word_`` form (lowercased words), so a plain
    substring test matches WHOLE words only: ``api_key`` / ``X-API-Key`` / ``apiKey`` all become
    ``_api_key_``, while ``author`` becomes ``_author_`` and so never matches the sensitive word ``auth``."""
    return "_" + "_".join(word.lower() for word in _WORD_BOUNDARY.split(key) if word) + "_"


_SENSITIVE_SIGNATURES = tuple(_word_signature(name) for name in SENSITIVE_KEYS)


def is_sensitive_parameter(key: str) -> bool:
    """Check whether a parameter NAME denotes sensitive data (credentials, tokens, ...).

    Word-aware and case-insensitive: a sensitive name must appear as WHOLE words in ``key`` (across
    snake_case / kebab-case / dotted / camelCase), so ``api_key`` / ``X-API-Key`` / ``apiKey`` match while
    ``author`` / ``secretary`` / ``tokens`` do NOT — the earlier raw-substring check redacted those by
    mistake. A name with no word delimiter (e.g. ``myapikey``) is one word and won't match an embedded
    ``apikey``; that trade buys the false-positive fix and is the accepted boundary (real secret params are
    delimited). The single source of truth every name-based redaction site defers to.

    Examples:
        >>> is_sensitive_parameter("api_key")
        True
        >>> is_sensitive_parameter("API_KEY")
        True
        >>> is_sensitive_parameter("author")
        False
        >>> is_sensitive_parameter("username")
        False
    """
    signature = _word_signature(key)
    return any(sig in signature for sig in _SENSITIVE_SIGNATURES)


def redact_sensitive(obj: Any) -> Any:
    """Return a copy of ``obj`` with the value of every sensitive-NAMED key replaced by ``<REDACTED>``.

    The display-side redaction for trace content, which is stored RAW so resume can restore it: every
    reader that SHOWS trace values (``pflow report``, the web UI run-node panel) applies this, while resume
    and ``--only`` loading read the trace directly. Descends every nested dict and list, so a nested
    ``headers.Authorization`` or a list-of-dicts secret is caught. Unlike ``sanitize_parameters`` it neither
    truncates long strings nor drops ``__`` keys — a debugging view shows the full realized value.
    A secret inside a free-text string (a command, an error message) has no key to match — the
    value scrub (``scrub_secret_values``) covers it.
    """
    if isinstance(obj, dict):
        return {
            key: "<REDACTED>" if isinstance(key, str) and is_sensitive_parameter(key) else redact_sensitive(value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact_sensitive(item) for item in obj]
    return obj


# A secret value shorter than this is never scrubbed: short values under sensitive names are common
# (`auth_type: basic`, `TOKEN_LIMIT: "5"`) and replacing them inside free text corrupts unrelated data.
# The same floor `llm_client._mask_key_material` uses.
MIN_SECRET_LENGTH = 8
_AUTH_SCHEME = re.compile(r"(?i)^(?:bearer|basic|token)\s+(\S+)$")


def secret_values(inputs: Mapping[str, Any]) -> frozenset[str]:
    """The values no printed surface of a run may show, given the run's declared ``inputs``.

    Every value stored in pflow settings (``pflow settings set-env`` — read from the settings file, never
    from ``os.environ``), plus every string the name rule hides in ``inputs`` (the value under a
    sensitive-named input or nested key, at any depth). A ``Bearer``/``Basic``/``Token`` value adds its
    bare credential too, since that is what a server echoes. Strings only; values shorter than
    ``MIN_SECRET_LENGTH`` or holding an unresolved ``${`` template are skipped. A secret a step
    produces mid-run is not in the set — nothing marks it secret at run start.
    """
    from pflow.core.settings import SettingsManager

    values = [*SettingsManager().list_env(mask_values=False).values(), *_sensitive_strings(inputs)]
    credentials = [match.group(1) for value in values if (match := _AUTH_SCHEME.match(value))]
    return frozenset(
        value for value in [*values, *credentials] if len(value) >= MIN_SECRET_LENGTH and "${" not in value
    )


def _sensitive_strings(obj: Any, hidden: bool = False) -> Iterable[str]:
    """Every string in ``obj`` that sits under a sensitive-named key (``hidden`` once one is passed)."""
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            yield from _sensitive_strings(value, hidden or (isinstance(key, str) and is_sensitive_parameter(key)))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _sensitive_strings(item, hidden)
    elif hidden and isinstance(obj, str):
        yield obj


def scrub_secret_values(obj: Any, secrets: frozenset[str]) -> Any:
    """Return a copy of ``obj`` with every occurrence of each value in ``secrets`` replaced by ``<REDACTED>``.

    The value-based counterpart of ``redact_sensitive``: it reaches a secret wherever it travelled — an
    error message, shell stderr, a command echo, a workflow result. Applied to data BEFORE it is
    rendered, so truncation or JSON escaping never leaves part of a secret behind. Descends dicts,
    lists, tuples and sets; dict keys and non-string leaves are kept as they are.
    """
    if not secrets:
        return obj
    ordered = sorted(secrets, key=len, reverse=True)  # a secret containing another is replaced whole

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for secret in ordered:
                if secret in value:
                    value = value.replace(secret, "<REDACTED>")
            return value
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, (tuple, set, frozenset)):
            return type(value)(scrub(item) for item in value)
        return value

    return scrub(obj)


def redact_for_display(names: Iterable[str], value: Any) -> Any:
    """``value`` as a message may show it: ``<REDACTED>`` when any name on its path (``names`` —
    the input, then each field down to the value) is sensitive; otherwise ``redact_sensitive``,
    applied inside JSON object/array TEXT too (a value quoted in a message is often an object's
    text). Text with nothing to redact keeps its bytes."""
    if any(is_sensitive_parameter(name) for name in names):
        return "<REDACTED>"
    if not isinstance(value, str):
        return redact_sensitive(value)
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    if not isinstance(parsed, (dict, list)) or (redacted := redact_sensitive(parsed)) == parsed:
        return value
    return json.dumps(redacted, ensure_ascii=False)


def mask_sensitive_value(key: str, value: str, mask_text: str = "<REDACTED>") -> str:
    """Mask a value if the parameter name is sensitive.

    Args:
        key: Parameter name
        value: Parameter value
        mask_text: Text to use for masking (default: "<REDACTED>")

    Returns:
        Original value if not sensitive, mask_text if sensitive

    Examples:
        >>> mask_sensitive_value("password", "secret123")
        '<REDACTED>'
        >>> mask_sensitive_value("username", "john")
        'john'
    """
    if is_sensitive_parameter(key):
        return mask_text
    return value


def sanitize_parameters(params: dict[str, Any], always_redact_keys: set[str] | None = None) -> dict[str, Any]:
    """Sanitize parameters to redact sensitive values.

    Recursively sanitizes dictionaries to remove:
    - Parameters specified in always_redact_keys (e.g., from settings.env)
    - Sensitive values (API keys, tokens, passwords)
    - Very long strings (potential keys/tokens)

    Args:
        params: Parameters dictionary to sanitize
        always_redact_keys: Set of param names to always redact (regardless of name pattern)

    Returns:
        Sanitized parameters with sensitive values redacted

    Example:
        >>> params = {"api_key": "sk-1234", "name": "test"}
        >>> sanitize_parameters(params)
        {'api_key': '<REDACTED>', 'name': 'test'}

        >>> params = {"safe_name": "secret", "channel": "C09"}
        >>> sanitize_parameters(params, always_redact_keys={"safe_name"})
        {'safe_name': '<REDACTED>', 'channel': 'C09'}
    """
    always_redact_keys = always_redact_keys or set()
    sanitized: dict[str, Any] = {}

    for key, value in params.items():
        # Skip internal params (start with __)
        if key.startswith("__"):
            continue

        # Redact env-derived keys (always_redact_keys) and sensitive-NAMED keys (the shared word-aware rule)
        if key in always_redact_keys or is_sensitive_parameter(key):
            sanitized[key] = "<REDACTED>"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_parameters(value, always_redact_keys=None)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_parameters(item, always_redact_keys=None) if isinstance(item, dict) else item for item in value
            ]
        elif isinstance(value, str) and len(value) > 100:
            sanitized[key] = value[:20] + "...<truncated>"
        else:
            sanitized[key] = value

    return sanitized
