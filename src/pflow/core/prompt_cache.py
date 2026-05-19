"""Prompt cache rendering primitives for Task 159 prompt caching.

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
from pflow.core.llm_capabilities import get_breakpoint_budget


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

    Delivered through ``shared["__pflow_prompt_cache__"]`` (a
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
    serialize to a stable string ``"<pflow.core.prompt_cache._ChunkAbsentSentinel>"``
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
    """Per-provider ``cache_control`` marker dict. Placement is determined by
    ``_compute_marker_chunk_indices`` (called from ``_build_system_blocks``):
    Anthropic gets up to 4 markers per request; other providers get a terminal
    marker only.

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


# --- Multi-breakpoint marker placement (task-159 follow-up) ----------------


def _compute_marker_chunk_indices(
    n_rendered_chunks: int,
    provider_name: str | None,
    prewarm_consumes_slot: bool,
) -> tuple[int, ...]:
    """Return chunk indices (into the rendered subset) that receive cache_control markers.

    The rendered subset is the post-ABSENT-filter chunk list produced by
    ``_build_system_blocks``. Indices are 0-based into THAT list, not into the
    declared ``## Cache`` block.

    **Anthropic** (budget=4): first ``(budget - 1 - prewarm_slot)`` chunks each
    get their own marker; remaining chunks merge into the terminal marker.
    Convention: chunks declared stable-to-volatile in ``## Cache`` so dense
    early markers capture rarely-changing prefixes and the terminal marker
    catches the all-stable case.

    **All other providers** (budget=1): terminal marker only — identical to
    today's behavior.

    Below-minimum markers are stripped later by
    ``LLMNode._strip_below_min_cache_markers`` (already plural-aware). No
    token reasoning needed here.

    **Pure function**: deterministic given inputs. Called from
    ``LLMNode._build_system_blocks`` (prep side) and NOT from
    ``plan_node._render_cache_for_hash`` (hash side intentionally doesn't
    track wire-format markers — DD#19 byte-identity preserved by design).

    **Scope of "centralized" placement**: this function owns placement for
    declared ``## Cache`` chunks (the multi-block list rendered by
    ``_build_system_blocks``). The auto-batch-prefix path in
    ``_build_user_message_blocks`` emits its own single ``cache_control``
    marker on the static prefix block — it does NOT route through this
    function because there is only one prefix block by construction
    (no chunks to spread across). The 4-marker Anthropic per-request cap
    is shared across both paths: prewarm reserves one slot here via
    ``prewarm_consumes_slot=True`` so the system_blocks placement stays
    within budget when the prewarm path also emits a marker.

    **Caller contract**: ``n_rendered_chunks >= 1``. ``_build_system_blocks``
    guards via ``if not rendered: return None`` before calling this. A
    ``ValueError`` enforces the contract — a silent empty return would hide
    caller bugs (cache rendering would proceed with zero markers and no
    signal).
    """
    if n_rendered_chunks < 1:
        raise ValueError(
            "_compute_marker_chunk_indices requires n_rendered_chunks >= 1 — "
            "the caller (_build_system_blocks) must guard the empty list."
        )
    budget = get_breakpoint_budget(provider_name)
    if prewarm_consumes_slot:
        budget -= 1
    # ``budget <= 1`` covers two cases: (a) the natural budget-1 providers
    # (openai/gemini/unknown — single terminal marker only), and (b) the
    # hypothetical budget=0 case where prewarm consumed the only slot on a
    # budget-1 provider. In (b) we still emit a terminal marker because no
    # provider in pflow's current matrix shares a hard per-request cap
    # between prewarm and content markers — Anthropic's 4-cap is shared and
    # handled by the prewarm slot reservation above; the budget-1 providers
    # treat cache_control as a no-op on the prewarm channel. Revisit if a
    # future provider has a strict shared cap.
    if budget <= 1:
        return (n_rendered_chunks - 1,)
    if n_rendered_chunks <= budget:
        return tuple(range(n_rendered_chunks))
    return (*range(budget - 1), n_rendered_chunks - 1)


def _looks_like_routed_anthropic(model: str | None) -> bool:
    """Heuristic: model identifier looks like routed Anthropic but doesn't
    match pflow's native Anthropic prefix.

    Returns True when:
      - ``detect_provider(model)`` returns None (unknown to pflow), AND
      - the model string contains ``"claude"`` or ``"anthropic"`` (substring,
        case-insensitive).

    Catches the common router shapes ``openrouter/anthropic/claude-...``,
    ``bedrock/anthropic.claude-...``, ``vertex_ai/claude-...`` and any
    similar future variant — without enumerating routers. False-positive
    surface is tiny because no shipping non-Anthropic model name today
    contains those substrings.

    This helper is the detection rule behind ``cache.routed-provider-degraded``:
    users running a multi-chunk ``## Cache`` on a routed-Anthropic model are
    silently losing per-chunk caching (terminal marker still works, but
    chunks-individual reuse is lost). The diagnostic surfaces this so the
    user can either switch to the canonical ``anthropic/`` prefix or, for
    compliance-routed callers, knowingly accept the limitation.
    """
    from pflow.core.llm_providers import detect_provider

    if not model:
        return False
    if detect_provider(model) is not None:
        return False
    lowered = model.lower()
    return "claude" in lowered or "anthropic" in lowered


# --- Public block builder (extracted core of LLMNode._build_system_blocks) ---


def build_cache_system_blocks(
    *,
    user_system: str | None,
    cache_ctx: CacheRenderContext | None,
    shared: dict[str, Any],
    model: str,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Build cache system content blocks with provider-specific ``cache_control`` markers.

    Pure function: no warnings, no side effects. Extracts the core
    block-building logic from ``LLMNode._build_system_blocks`` so both the
    LLM node prep path and future synthetic cache warmup can share it.

    Returns ``(system_blocks, chunks_skipped)`` — same contract as
    ``_build_system_blocks``. ``system_blocks`` is ``None`` when no cache
    rendering applies (no ctx, empty subset, or every chunk filtered as
    ABSENT) — caller falls back to the plain-string ``system`` path so
    byte-for-byte behavior is preserved for opt-out nodes.

    When at least one chunk renders, the returned list is:

    1. The user's ``system`` param (when set) as the FIRST block, no marker.
    2. One block per declared chunk in declaration order: ``prose_before``
       concatenated with the deterministic-serialized chunk value.
    3. Per-provider ``cache_control`` markers placed by
       ``_compute_marker_chunk_indices``: Anthropic gets up to 4 markers
       (first N-1 chunks individual + terminal merge); other providers get
       a terminal marker only.

    The ABSENT filter is symmetric with
    ``runtime/engine/plan_node._render_cache_for_hash`` — both sites import
    ``_resolve_chunk_value`` from this module. If they diverge, hash and
    prep render different bytes for the same logical state.
    """
    if cache_ctx is None or not cache_ctx.subset or cache_ctx.cache_block is None:
        return None, []

    chunks_by_name = {c.name: c for c in cache_ctx.cache_block.items}
    rendered: list[tuple[str, str]] = []  # (prose_before, value_str)
    chunks_skipped: list[str] = []

    for name in cache_ctx.subset:
        chunk = chunks_by_name.get(name)
        if chunk is None:
            continue
        value = _resolve_chunk_value(chunk, shared)
        if isinstance(value, _ChunkAbsentSentinel):
            chunks_skipped.append(name)
            continue
        rendered.append((chunk.prose_before, value))

    if not rendered:
        return None, chunks_skipped

    blocks: list[dict[str, Any]] = []
    if user_system:
        blocks.append({"type": "text", "text": user_system})
    for prose, value in rendered:
        blocks.append({"type": "text", "text": prose + value})

    from pflow.core.llm_providers import detect_provider

    provider = detect_provider(model)
    provider_name = provider.name if provider else None

    chunk_block_offset = 1 if user_system else 0
    marker_indices = _compute_marker_chunk_indices(
        n_rendered_chunks=len(rendered),
        provider_name=provider_name,
        prewarm_consumes_slot=cache_ctx.prewarm,
    )
    # Shallow dict copy is sufficient TODAY because _build_cache_control_marker
    # returns flat dicts ({"type": ..., "ttl": ...}). If a future provider needs
    # a nested marker shape (e.g., {"type": ..., "config": {...}}), switch to
    # copy.deepcopy here to prevent aliasing across blocks.
    marker = _build_cache_control_marker(provider_name, cache_ctx.cache_block.ttl)
    for chunk_idx in marker_indices:
        blocks[chunk_block_offset + chunk_idx]["cache_control"] = dict(marker)

    return blocks, chunks_skipped


# --- Warmup user-message blocks (auto-batch-prefix counterpart) ---


def build_warmup_user_message_blocks(
    *,
    cache_ctx: CacheRenderContext,
    shared: dict[str, Any],
    model: str,
) -> list[dict[str, Any]] | None:
    """Build user_message_blocks for a synthetic warmup call's auto-batch-prefix.

    Mirrors what ``nodes/llm/llm.py::_build_user_message_blocks`` produces
    for a real batch item — same resolved static prefix, same ``cache_control``
    marker — but with a tiny ``"OK"`` suffix instead of a per-item value.
    This lets the warmup populate the provider's user-message prefix cache
    so subsequent batch items get reads instead of racing to write.

    Returns ``None`` when no auto-batch-prefix would be rendered:
    - No unresolved batch prompt or batch alias.
    - No per-item reference in the prompt (no ``${item.X}``).
    - Boundary at position 0 (no static prefix exists).

    TTL handling matches ``_build_user_message_blocks`` line 684: when
    ``cache_ctx.cache_block is None``, ``ttl=None`` is passed to
    ``_build_cache_control_marker`` which defaults to 5m via ``parse_cache_ttl``.
    """
    from pflow.core.llm_providers import detect_provider
    from pflow.core.prompt_refs import first_per_item_position

    if cache_ctx.unresolved_batch_prompt is None or cache_ctx.batch_alias is None:
        return None

    boundary = first_per_item_position(
        cache_ctx.unresolved_batch_prompt,
        cache_ctx.batch_alias,
        cache_ctx.node_inputs,
    )
    if boundary is None or boundary == 0:
        return None

    static_prefix = _resolve_static_prefix_for_cache(
        cache_ctx.unresolved_batch_prompt[:boundary],
        shared,
    )
    if not static_prefix:
        return None

    provider = detect_provider(model)
    provider_name = provider.name if provider else None
    ttl = cache_ctx.cache_block.ttl if cache_ctx.cache_block else None
    marker = _build_cache_control_marker(provider_name, ttl)
    return [
        {"type": "text", "text": static_prefix, "cache_control": marker},
        {"type": "text", "text": "OK"},
    ]
