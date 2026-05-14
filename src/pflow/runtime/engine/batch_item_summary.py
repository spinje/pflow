"""Display-safe summaries for failed batch input items."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

MAX_SUMMARY_CHARS = 240
MAX_SHORT_STRING_CHARS = 80
MAX_LABEL_CHARS = 80
MAX_DICT_FIELDS = 4
HASH_HEX_CHARS = 12
LABEL_KEYS = ("label", "name", "id", "title", "path", "file", "filename", "workflow")
SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
)

_HEX_RE = re.compile(r"^[0-9a-f]{12}$")


def summarize_batch_item(item: Any) -> dict[str, Any]:
    """Return a bounded, JSON-serializable identity summary for a batch item.

    The original failed item remains the runtime source of truth. This helper
    only produces a safe companion shape for terminal, MCP, report, and JSON
    renderers that must not dump arbitrarily large values.
    """
    try:
        serialized = _serialize_for_hash(item)
        digest = _hash_text(serialized)
        summary, truncated = _summarize_value(item, digest)
        summary, shortened = _shorten_summary(summary)
        result: dict[str, Any] = {
            "summary_version": 1,
            "type": _type_name(item),
            "size_chars": len(serialized),
            "sha256": digest,
            "summary": summary,
            "truncated": bool(truncated or shortened),
        }
        if isinstance(item, Mapping):
            label = _extract_label(item)
            if label is not None:
                result["label"] = label
        return result
    except Exception:
        return {
            "summary_version": 1,
            "type": "unrepresentable",
            "size_chars": 0,
            "sha256": _hash_text("<unrepresentable>"),
            "summary": "<unrepresentable>",
            "truncated": True,
        }


def _serialize_for_hash(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=_safe_str, ensure_ascii=False)
    except Exception:
        return _safe_repr(value)


def _safe_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return _safe_repr(value)


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {_type_name(value)}>"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:HASH_HEX_CHARS]


def _hash_value(value: Any) -> str:
    return _hash_text(_serialize_for_hash(value))


def _type_name(value: Any) -> str:
    try:
        return type(value).__name__
    except Exception:
        return "unknown"


def _summarize_value(value: Any, digest: str) -> tuple[str, bool]:
    if isinstance(value, str):
        return _summarize_string(value, digest)
    if isinstance(value, Mapping):
        return _summarize_mapping(value)
    if isinstance(value, tuple):
        return f"<tuple len={len(value)} sha256={digest}>", True
    if _is_non_string_sequence(value):
        return f"<list len={len(value)} sha256={digest}>", True
    if _is_scalar(value):
        return _bounded_repr(value)
    return f"<{_type_name(value)} sha256={digest}>", True


def _summarize_mapping(value: Mapping[Any, Any]) -> tuple[str, bool]:
    fragments: list[str] = []
    truncated = False
    ordered_keys = _ordered_mapping_keys(value)

    for key in ordered_keys[:MAX_DICT_FIELDS]:
        try:
            field_value = value[key]
        except Exception:
            field_value = "<unavailable>"
            truncated = True
        fragment, field_truncated = _summarize_field(key, field_value)
        fragments.append(fragment)
        truncated = truncated or field_truncated

    omitted = max(0, len(ordered_keys) - MAX_DICT_FIELDS)
    if omitted:
        fragments.append(f"... +{omitted} fields")
        truncated = True

    summary = _join_fragments(fragments, fallback=f"<dict {len(ordered_keys)} fields sha256={_hash_value(value)}>")
    return summary, truncated


def _ordered_mapping_keys(value: Mapping[Any, Any]) -> list[Any]:
    keys = list(value.keys())
    ordered: list[Any] = []
    for label_key in LABEL_KEYS:
        for key in keys:
            if key not in ordered and isinstance(key, str) and key == label_key:
                ordered.append(key)
                break
    ordered.extend(key for key in keys if key not in ordered)
    return ordered


def _extract_label(value: Mapping[Any, Any]) -> str | None:
    for key in LABEL_KEYS:
        raw = value.get(key)
        if _is_scalar(raw):
            text = _safe_str(raw).strip()
            if text:
                return _bound_text(text, MAX_LABEL_CHARS)
    return None


def _summarize_field(key: Any, value: Any) -> tuple[str, bool]:
    key_text = _bound_key(key)
    if _is_sensitive_key(key_text):
        return f"{key_text}=<redacted sha256={_hash_value(value)}>", True

    if isinstance(value, str):
        rendered, truncated = _summarize_string(value, _hash_value(value))
        return f"{key_text}={rendered}", truncated
    if isinstance(value, Mapping):
        return f"{key_text}=<dict {len(value)} fields sha256={_hash_value(value)}>", True
    if isinstance(value, tuple):
        return f"{key_text}=<tuple len={len(value)} sha256={_hash_value(value)}>", True
    if _is_non_string_sequence(value):
        return f"{key_text}=<list len={len(value)} sha256={_hash_value(value)}>", True
    if _is_scalar(value):
        rendered, truncated = _bounded_repr(value)
        return f"{key_text}={rendered}", truncated
    return f"{key_text}=<{_type_name(value)} sha256={_hash_value(value)}>", True


def _summarize_string(value: str, digest: str) -> tuple[str, bool]:
    if len(value) <= MAX_SHORT_STRING_CHARS:
        return repr(value), False
    return f"<str {len(value)} chars sha256={digest}>", True


def _bounded_repr(value: Any) -> tuple[str, bool]:
    text = _safe_repr(value)
    bounded = _bound_text(text, MAX_SHORT_STRING_CHARS)
    return bounded, bounded != text


def _bound_key(key: Any) -> str:
    text = _safe_str(key)
    if not text:
        return "<empty>"
    return _bound_text(text, 48)


def _bound_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_non_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _join_fragments(fragments: list[str], *, fallback: str) -> str:
    kept: list[str] = []
    length = 0
    for fragment in fragments:
        extra = len(fragment) + (2 if kept else 0)
        if kept and length + extra > MAX_SUMMARY_CHARS:
            break
        if not kept and len(fragment) > MAX_SUMMARY_CHARS:
            break
        kept.append(fragment)
        length += extra

    if not kept:
        return fallback if len(fallback) <= MAX_SUMMARY_CHARS else fallback[:MAX_SUMMARY_CHARS]
    return "; ".join(kept)


def _shorten_summary(summary: str) -> tuple[str, bool]:
    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary, False
    parts = summary.split("; ")
    while len(parts) > 1 and len("; ".join(parts)) > MAX_SUMMARY_CHARS:
        parts.pop()
    shortened = "; ".join(parts)
    if len(shortened) <= MAX_SUMMARY_CHARS:
        return shortened, True

    # Last resort for hostile single-field summaries. Avoid splitting a hash
    # placeholder when possible by dropping the whole field.
    if "sha256=" in shortened:
        match = re.search(r"sha256=([0-9a-f]{0,12})", shortened)
        if match and not _HEX_RE.match(match.group(1)):
            return "<summary shortened>", True
    return shortened[: MAX_SUMMARY_CHARS - 3] + "...", True
