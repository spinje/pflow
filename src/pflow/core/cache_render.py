"""Cache rendering primitives for Task 159 prompt caching.

Frozen IR types and shared rendering helpers used at three sites:
- ``runtime/engine/plan_node.py`` — hash-time chunk rendering.
- ``nodes/llm/llm.py`` — message-time chunk rendering (C1.2).
- ``core/cache_analysis/analyze.py`` — predicted cache_key rendering (F2).

This module sits in ``core/`` because it is reachable from all three layers
without violating ``nodes/`` -> ``runtime/`` import policy. Helpers
lazy-import runtime symbols inside function bodies.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Union

from pflow.core.cache_ttl import parse_cache_ttl


@dataclass(frozen=True)
class CacheChunkIR:
    """One ``[prose-before-${var}][${var}]`` chunk in the workflow ## Cache block."""

    name: str
    var_expr: str
    prose_before: str
    source_line: int


@dataclass(frozen=True)
class CacheBlockIR:
    """Workflow-level ## Cache block IR. Frozen + tuple items so the compile-cache
    can share one instance across parallel sub-workflow invocations safely."""

    ttl: str | None
    items: tuple[CacheChunkIR, ...]
    source_line: int


@dataclass(frozen=True)
class CacheRenderContext:
    """Per-node cache rendering context, built once at engine.run() entry.

    Delivered through ``shared["__pflow_cache_render__"]`` (a
    ``MappingProxyType`` keyed by ``node_id``). Every consumer (plan_node hash
    rendering, LLMNode prep message rendering, batch_executor static-prefix
    detection) reads the same context.

    **Parallel-batch safety is by frozen-attribute construction, NOT by the
    outer MappingProxyType wrap.** ``MappingProxyType`` only blocks mutation
    of the outer ``dict[node_id, CacheRenderContext]`` keys; it does NOT
    deep-freeze field values. Today every field is immutable by construction
    (``node_inputs`` is wrapped in ``MappingProxyType`` by the producer):
    ``cache_block: CacheBlockIR`` (frozen, tuple items), ``subset: tuple``,
    ``prewarm: bool``, ``unresolved_batch_prompt: str``, ``batch_alias: str``.
    A future contributor adding a non-immutable field (e.g., a memo dict for
    resolved-chunk reuse) would silently introduce a parallel-batch race.
    Add only immutable fields here, or wrap mutable fields in their own
    immutable container. Producers MUST wrap ``node_inputs`` in
    ``MappingProxyType``; raw dicts type-check but violate this freeze
    invariant.
    """

    cache_block: CacheBlockIR | None
    subset: tuple[str, ...]
    prewarm: bool
    unresolved_batch_prompt: str | None
    batch_alias: str | None
    node_inputs: Mapping[str, Any] | None = None


# --- Sentinel for branch-absent chunks -------------------------------------


class _ChunkAbsentSentinel:
    """Marker class for "the upstream node didn't run; skip this chunk."

    Distinct type so neither ``isinstance`` checks at the filter sites nor
    the ``runtime/cache.py`` defense can ever confuse it with a real value.
    A leaked sentinel reaching ``_make_serializable`` would otherwise
    serialize to a stable string ``"<pflow.core.cache_render._ChunkAbsentSentinel>"``
    and fold into the cache hash byte-identically across runs — the silent
    stale-cache regression class B3.3 closes via the explicit guard at
    ``runtime/cache.py:_make_serializable``.
    """

    __slots__ = ()


_CHUNK_ABSENT: Final = _ChunkAbsentSentinel()


# Type alias for a chunk-render result: either the deterministic string
# representation OR the absent sentinel. Filter sites pattern-match on
# ``isinstance(result, _ChunkAbsentSentinel)`` to drop absent chunks before
# they reach the cache hash or the rendered system blocks.
ChunkRenderResult = Union[str, _ChunkAbsentSentinel]


# --- Deterministic serialization (single source of truth) ------------------


def deterministic_serialize(value: Any) -> str:
    """Serialize a resolved chunk value to canonical bytes.

    Strings pass through verbatim. Everything else is encoded as compact JSON
    with sorted keys and ``default=str`` so non-JSON-native values
    (datetimes, etc.) get a stable repr. ``json.dumps`` with these options is
    deterministic across Python implementations and dict-insertion-order
    histories — the load-bearing invariant for byte-identity at hash AND prep
    sites (B3.3 hash-vs-prep render byte-equivalence).

    Public per Task 159 G.1 — every consumer that needs canonical byte
    serialization (chunk hash, chunk message, static-prefix auto-batch,
    analyzer prediction) imports this single helper. Forking it would
    silently break the cache-key byte-identity invariant.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


# Backward-compatible private alias — kept for in-tree consumers that
# imported the underscored name during Phase B3 / C1.2. New code uses
# ``deterministic_serialize``.
_deterministic_serialize = deterministic_serialize


# --- Chunk-level resolution (single ${var} per chunk) ----------------------


def _resolve_chunk_value(chunk: CacheChunkIR, shared: dict[str, Any]) -> ChunkRenderResult:
    """Resolve one cache chunk's ``${var}`` against ``shared``.

    Returns ``_CHUNK_ABSENT`` when the chunk is structurally unresolvable
    against ``shared`` — the canonical signal for the symmetric filter both
    plan_node hash rendering and LLMNode.prep message rendering apply.
    Two distinct unresolvable cases collapse to the same sentinel:

    1. **Branch absent**: the upstream node has ``NodeStatus.ABSENT`` (e.g.
       conditional branch not taken). Detected before calling resolve.
    2. **Permissive-mode echo**: ``TemplateResolver.resolve_template`` does
       NOT raise on a missing var — it returns the literal ``"${var_expr}"``
       string verbatim (this is the resolver's permissive default, distinct
       from ``resolve_templates`` plural which raises in strict mode). If
       the resolver echoes the input, the var didn't resolve; treat that as
       absent so the filter contract holds. Without this guard the literal
       would get folded into the deterministic serialization and silently
       produce a stable hash with the placeholder string in it — and the
       prep-side render would do the same — creating false byte-equivalence
       across structurally different runs.

    Returns the deterministic string representation otherwise. Cache
    chunks are validated to reference declared inputs/step outputs (B2.3),
    so for valid workflows the absent branches are: explicit ``NodeStatus.ABSENT``
    upstream OR a transient state where the value isn't yet seeded (the
    permissive echo case).
    """
    from pflow.runtime.node_state import NodeStatus, get_node_status
    from pflow.runtime.template_resolver import TemplateResolver

    upstream_node = TemplateResolver.extract_root_node_id(chunk.var_expr)
    if get_node_status(shared, upstream_node) == NodeStatus.ABSENT:
        return _CHUNK_ABSENT
    template = "${" + chunk.var_expr + "}"
    resolved = TemplateResolver.resolve_template(template, shared)
    # Permissive-mode echo: resolver returned the unchanged template string
    # because the var didn't resolve. Collapse to the absent sentinel so the
    # filter symmetry between hash and prep sites holds.
    if isinstance(resolved, str) and resolved == template:
        return _CHUNK_ABSENT
    return _deterministic_serialize(resolved)


# --- Per-provider cache_control marker translation -------------------------


def _build_cache_control_marker(provider_name: str | None, ttl: str | None) -> dict[str, Any]:
    """Per-provider ``cache_control`` marker for the LAST chunk of a cached
    system prefix (v1 single-breakpoint strategy, task-159 DD#11).

    TTL wire-format translation (task-159 spec "TTL wire-format translation"):

    - **Anthropic**: ``{"type": "ephemeral"}`` for omitted/``5m`` (5-min IS
      the provider default; Anthropic's API does NOT accept an explicit
      ``ttl: "5m"`` — only ``"1h"`` is documented). ``"1h"`` →
      ``{"type": "ephemeral", "ttl": "1h"}``.
    - **Gemini**: always sends an explicit seconds-suffix TTL, including
      omitted pflow TTL as ``"300s"``. This keeps the default path and
      dynamic-TTL path on one wire shape; LiteLLM's Vertex translation uses
      seconds notation with an ``s`` suffix for explicit TTLs.
    - **OpenAI / unknown / out-of-vocab**: ``{"type": "ephemeral"}``
      unconditionally. ``cache_control`` markers are no-ops on OpenAI
      (auto-cache only); the bare marker is emitted for shape consistency
      (the LiteLLM call body matches across providers). The dedicated
      OpenAI knobs (``prompt_cache_key``, ``prompt_cache_retention``) flow
      through ``model_options`` from the LLMNode prep path (C3).

    Invalid TTLs intentionally fail here instead of degrading to a bare
    marker: schema/validator paths should catch malformed values before
    rendering, and silently dropping explicit TTL intent would hide bad IR.

    Returns a fresh dict on every call so callers can safely mutate / store.
    """
    parsed_ttl = parse_cache_ttl(ttl)
    if provider_name == "anthropic":
        if parsed_ttl.seconds == 3600:
            return {"type": "ephemeral", "ttl": "1h"}
        return {"type": "ephemeral"}
    if provider_name == "gemini":
        return {"type": "ephemeral", "ttl": f"{parsed_ttl.seconds}s"}
    return {"type": "ephemeral"}


# --- Static-prefix resolution (D.1 auto-batch-prefix detection) ------------


def _resolve_static_prefix_for_cache(template_str: str, shared: dict[str, Any]) -> str:
    """Resolve every ``${var}`` in ``template_str`` deterministically.

    Differs from ``TemplateResolver.resolve_template(template_str, shared)``
    in one critical place: that function uses ``str(value)`` for embedded
    refs in complex templates (per ``runtime/CLAUDE.md`` "complex templates
    always string"). For dict/list values, ``str(value)`` produces Python
    repr (``{'key': 'value'}``), NOT canonical JSON. A chunk's value at
    ``_resolve_chunk_value`` and the same value embedded in a static prefix
    would then produce different bytes — a silent cross-mode cache miss.

    Substitutes per-ref via ``_deterministic_serialize`` so the bytes match
    ``_resolve_chunk_value`` byte-for-byte for the same logical value.
    Unresolvable refs (ABSENT upstream, missing key) are left in place; the
    auto-batch cache prefix becomes non-deterministic in that case and the
    analyzer tier surfaces it via ``cache.dynamic-before-static`` /
    ``cache.discrepancy``.
    """
    import re

    from pflow.runtime.template_resolver import TemplateResolver

    def _replace_one(match: re.Match[str]) -> str:
        full_match = match.group(0)  # e.g. "${concept}" or "${a ?? b}"
        resolved = TemplateResolver.resolve_template(full_match, shared)
        if resolved == full_match:
            # Unresolved — leave the literal ${var} so downstream renderers
            # can see what didn't resolve. Mirrors permissive mode.
            return full_match
        return _deterministic_serialize(resolved)

    result: str = TemplateResolver.TEMPLATE_PATTERN.sub(_replace_one, template_str)
    return result
