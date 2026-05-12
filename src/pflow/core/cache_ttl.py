"""Prompt-cache TTL parsing and provider capability helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from pflow.core.diagnostic import CACHE_FAILURE_CATEGORY, Diagnostic, Severity

DEFAULT_CACHE_TTL_SECONDS: Final[int] = 300
MAX_CACHE_TTL_SECONDS: Final[int] = 3600
CACHE_TTL_PATTERN: Final = r"^(([1-9]|[1-5][0-9]|60)m|1h)$"
_TTL_RE: Final = re.compile(CACHE_TTL_PATTERN)
_DISCRETE_PROVIDER_SECONDS: Final = {DEFAULT_CACHE_TTL_SECONDS, MAX_CACHE_TTL_SECONDS}


@dataclass(frozen=True)
class CacheTTL:
    """Parsed pflow prompt-cache TTL."""

    original: str | None
    label: str
    seconds: int


def parse_cache_ttl(value: str | None) -> CacheTTL:
    """Parse pflow's human TTL syntax.

    Accepted values are omitted/``None`` (the pflow default ``5m``),
    ``1m`` through ``60m``, and ``1h`` as an alias for 60 minutes.
    Provider wire formats such as ``300s`` are intentionally rejected.
    """
    if value is None:
        return CacheTTL(original=None, label="5m", seconds=DEFAULT_CACHE_TTL_SECONDS)
    if not isinstance(value, str) or not _TTL_RE.match(value):
        raise ValueError(_ttl_error_message(value))
    if value == "1h":
        return CacheTTL(original=value, label=value, seconds=MAX_CACHE_TTL_SECONDS)
    minutes = int(value.removesuffix("m"))
    return CacheTTL(original=value, label=value, seconds=minutes * 60)


def is_valid_cache_ttl(value: str | None) -> bool:
    """Return whether ``value`` is valid pflow TTL syntax."""
    try:
        parse_cache_ttl(value)
    except ValueError:
        return False
    return True


def cache_ttl_syntax_hint() -> str:
    """Human-facing syntax hint shared by parser/docs-adjacent errors."""
    return "Use '- ttl: 5m' or any value from '1m' through '60m'; '1h' is also accepted."


def is_cache_ttl_supported_by_provider(provider_name: str | None, ttl: str | None) -> bool:
    """Return whether pflow can honestly honor ``ttl`` for ``provider_name``."""
    parsed = parse_cache_ttl(ttl)
    if provider_name == "gemini":
        return True
    if provider_name in {"anthropic", "openai"}:
        return parsed.seconds in _DISCRETE_PROVIDER_SECONDS
    # Unknown providers keep the historical bare-marker defensive behavior for
    # default/1h TTLs, but pflow cannot promise minute-precise dynamic TTLs.
    return parsed.seconds in _DISCRETE_PROVIDER_SECONDS


def unsupported_cache_ttl_message(
    *,
    node_id: str,
    provider_name: str | None,
    ttl: str | None,
) -> str:
    """Build the stable user-facing unsupported-provider TTL message."""
    provider_label = provider_name or "unknown provider"
    parsed = parse_cache_ttl(ttl)
    return (
        f"Node '{node_id}' uses {provider_label} but ## Cache ttl is '{parsed.label}'. "
        f"{provider_label} prompt caching through pflow does not support minute-level TTLs. "
        "Use '- ttl: 5m' or '- ttl: 1h', or switch cached LLM nodes to Gemini."
    )


def build_unsupported_cache_ttl_diagnostic(
    *,
    node_id: str,
    provider_name: str | None,
    ttl: str | None,
    model: str | None = None,
) -> Diagnostic:
    """Build the canonical unsupported-provider TTL diagnostic."""
    parsed = parse_cache_ttl(ttl)
    provider_label = provider_name or "unknown provider"
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Cache Failure",
        node_id=node_id,
        id="cache.unsupported-provider-ttl",
        message=unsupported_cache_ttl_message(node_id=node_id, provider_name=provider_name, ttl=ttl),
        suggestions=[
            "Use '- ttl: 5m' or '- ttl: 1h' on the workflow ## Cache block.",
            "Use a Gemini model for cached LLM nodes that need minute-level TTLs.",
        ],
        context={
            "category": CACHE_FAILURE_CATEGORY,
            "path": f"nodes[id={node_id}].params.model",
            "provider": provider_label,
            "model": model,
            "ttl": parsed.label,
            "ttl_seconds": parsed.seconds,
        },
        see_also=["prompt-caching"],
    )


def _ttl_error_message(value: object) -> str:
    return (
        f"Invalid cache TTL {value!r}. Accepted values are '1m' through '60m', '1h', or omitted for the default '5m'."
    )
