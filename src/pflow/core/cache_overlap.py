"""Shared overlap detection between ``prompt_cache:`` chunks and prompt-body refs.

When an LLM node declares ``prompt_cache: [X]`` and the node's prompt body
also references ``${X}`` (or any sub-path of ``X``), pflow currently sends the
value twice: once cached in the system blocks, once embedded inline in the
user message. The cache stores ``X`` at 0.1x rate; the prompt body still
sends ``X`` at 1.0x rate every call. Net cache benefit is ~zero.

This module is the single source of truth for that overlap rule. The
validator (``data_flow.py``) emits ERROR/WARNING diagnostics when overlaps
fire at validate time; the analyzer renderer (``prompt_cache_analysis``) surfaces
the same overlaps for greenfield workflows. Sharing the implementation keeps
both byte-identical so agents don't hit a UX loop where the analyzer
recommends a setup the validator then rejects.

Parser invariant: ``chunk.name == chunk.var_expr`` for every parsed chunk
(see ``markdown_parser.py:1754``). Path comparisons therefore use chunk_name
directly as the path string — no var_by_name lookup needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pflow.runtime.template_resolver import TemplateResolver

# Filter for valid pflow variable refs. Bash syntax (${var:-default},
# ${var%pattern}, ${#count}) and truncated nested templates fail this match
# and must be skipped — they cannot overlap a cache chunk by definition.
_PFLOW_VAR_RE = re.compile(rf"^{TemplateResolver._VAR_NAME_PATTERN}$")


@dataclass(frozen=True)
class Overlap:
    """One overlap finding.

    ``kind`` discriminates the three semantic cases:

    - ``"duplicate"``: cache chunk path equals body ref path (e.g. cache
      ``[concept]`` + body ``${concept}``). The most expensive form — cached
      bytes are sent inline at 1.0x every call.
    - ``"cache_contains_body"``: cache path is a strict prefix of body path
      (e.g. cache ``[concept]`` + body ``${concept.title}``). The body ref
      reads a sub-path that's already cached as part of the larger value.
    - ``"body_contains_cache"``: body path is a strict prefix of cache path
      (e.g. cache ``[concept.title]`` + body ``${concept}``). The body
      sends the larger parent that contains the cached sub-path.
    """

    chunk_name: str
    body_ref: str
    kind: Literal["duplicate", "cache_contains_body", "body_contains_cache"]


def _canonicalize_path(p: str) -> tuple[str, ...]:
    """Split a pflow variable path into a canonical tuple.

    Splits on ``.`` AND before each ``[`` so array indices become their own
    segments. Empty segments are dropped. Non-string / empty inputs return
    the empty tuple.

    Examples:
        ``"concept"``         → ``("concept",)``
        ``"concept.title"``   → ``("concept", "title")``
        ``"items[0]"``        → ``("items", "[0]")``
        ``"items[0].field"``  → ``("items", "[0]", "field")``
        ``"a.b[2].c"``        → ``("a", "b", "[2]", "c")``
    """
    if not isinstance(p, str) or not p:
        return ()
    parts: list[str] = []
    for dot_part in p.split("."):
        if not dot_part:
            continue
        # A segment may contain one or more bracketed indices. Split out
        # each ``[N]`` while keeping the brackets attached so ``items[0]``
        # canonicalizes to ``("items", "[0]")`` and ``items[0][1]`` to
        # ``("items", "[0]", "[1]")``.
        if "[" in dot_part:
            head, _, rest = dot_part.partition("[")
            if head:
                parts.append(head)
            for seg in rest.split("["):
                parts.append("[" + seg)
        else:
            parts.append(dot_part)
    return tuple(parts)


def _is_strict_prefix(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """True iff ``a`` is a non-empty proper prefix of ``b``."""
    return 0 < len(a) < len(b) and b[: len(a)] == a


def _batch_aliases(node: dict[str, Any]) -> set[str]:
    """Return the batch alias name(s) for a node.

    Mirrors the helper in ``prompt_cache_analysis.analyze``. Lifted here so the
    validator can compute the same alias set without importing the analyzer
    module (analyzer → data_flow is a one-way dependency).
    """
    batch = node.get("batch")
    if not isinstance(batch, dict):
        return set()
    return {str(batch.get("as", "item"))}


def _is_batch_scoped_ref(ref: str, aliases: set[str]) -> bool:
    """True iff ``ref`` is rooted at a batch alias (``${item.X}``, ``${item}``)."""
    return any(ref == alias or ref.startswith(f"{alias}.") or ref.startswith(f"{alias}[") for alias in aliases)


def _extract_body_refs(prompt_text: str, batch_aliases: set[str]) -> list[str]:
    """Return unique pflow variable refs found in the prompt body, in source order.

    Coalesce operands (``${a ?? b}``) are split and checked independently.
    Bash syntax (``${var:-default}``) and batch-scoped refs (``${item.X}``)
    are filtered out — they cannot overlap a stable cache chunk.
    """
    body_refs: list[str] = []
    seen_refs: set[str] = set()
    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(prompt_text):
        for operand in TemplateResolver.split_coalesce_operands(match.group(1)):
            if operand in seen_refs:
                continue
            # Literal operands (Optional A) are values, not cache-chunk refs.
            if TemplateResolver.is_literal_operand(operand):
                continue
            if not _PFLOW_VAR_RE.match(operand):
                continue
            if _is_batch_scoped_ref(operand, batch_aliases):
                continue
            seen_refs.add(operand)
            body_refs.append(operand)
    return body_refs


def _classify_pair(
    cache_path: tuple[str, ...], body_path: tuple[str, ...]
) -> Literal["duplicate", "cache_contains_body", "body_contains_cache"] | None:
    """Return the overlap kind for one ``(cache_path, body_path)`` pair, or None."""
    if cache_path == body_path:
        return "duplicate"
    if _is_strict_prefix(cache_path, body_path):
        return "cache_contains_body"
    if _is_strict_prefix(body_path, cache_path):
        return "body_contains_cache"
    return None


def compute_overlaps(
    *,
    prompt_text: str,
    prompt_cache: list[str],
    cache_item_names: set[str],
    batch_aliases: set[str],
) -> list[Overlap]:
    """Detect overlaps between cached chunks and prompt-body references.

    Returns an empty list when ``prompt_text`` is empty / non-string OR
    ``prompt_cache`` is empty. Body refs that fail ``_PFLOW_VAR_RE`` (bash
    syntax) or that are batch-scoped (``${item.X}``) are skipped — they
    cannot overlap a cache chunk by definition.

    Overlap kinds: see :class:`Overlap`.
    """
    if not isinstance(prompt_text, str) or not prompt_text or not prompt_cache:
        return []

    body_refs = _extract_body_refs(prompt_text, batch_aliases)
    if not body_refs:
        return []

    overlaps: list[Overlap] = []
    for chunk_name in prompt_cache:
        if chunk_name not in cache_item_names:
            continue
        cache_path = _canonicalize_path(chunk_name)
        if not cache_path:
            continue
        for body_ref in body_refs:
            body_path = _canonicalize_path(body_ref)
            if not body_path:
                continue
            kind = _classify_pair(cache_path, body_path)
            if kind is not None:
                overlaps.append(Overlap(chunk_name, body_ref, kind))
    return overlaps


__all__ = [
    "Overlap",
    "compute_overlaps",
]
