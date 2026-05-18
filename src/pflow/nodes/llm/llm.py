"""General-purpose LLM node for text processing."""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.core.cache_analysis.below_min_tokens_detector import (
    BelowMinTokensEvidence,
    provider_note,
)
from pflow.core.cache_analysis.below_min_tokens_detector import (
    detect as detect_below_min_tokens,
)
from pflow.core.cache_analysis.warning_catalog import make_diagnostic
from pflow.core.cache_render import (
    CacheRenderContext,
    _build_cache_control_marker,
    _ChunkAbsentSentinel,
    _resolve_chunk_value,
    _resolve_static_prefix_for_cache,
    compute_marker_chunk_indices,
)
from pflow.core.cache_ttl import is_cache_ttl_supported_by_provider, parse_cache_ttl
from pflow.core.exceptions import LLMCallError, LLMTransientError, UnsupportedCacheTTLError
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_client import Attachment, TraceHook, complete
from pflow.core.llm_providers import detect_provider
from pflow.core.llm_reasoning_map import (
    DEFAULT_MAX_TOKENS_BASE,
    EFFORT_RATIOS,
    map_reasoning_options,
)
from pflow.core.node import Node
from pflow.core.prompt_refs import first_per_item_position

logger = logging.getLogger(__name__)

# Re-exported for backward compatibility with code that imported these names
# from pflow.nodes.llm.llm. The canonical home is pflow.core.llm_reasoning_map.
__all__ = [
    "DEFAULT_MAX_TOKENS_BASE",
    "EFFORT_RATIOS",
    "LLMNode",
]


def _error_dict_from_exception(exc: LLMCallError) -> dict[str, Any]:
    """Build the standard error-dict shape from a typed LLMCallError.

    Reads the rich diagnostic produced by ``exc.to_diagnostics()`` — which
    is the single source of truth for the user-facing message and the
    structured context (``error_class``, ``model``, ``reason``/``kind``).
    The ``_diagnostic_context`` field is lifted by
    ``executor_service._enrich_error_from_node_output`` so the runtime
    Diagnostic that reaches JSON output carries the same structured fields
    the override produced — no duplication, no drift.

    Suggestions from the override are joined into the ``error`` prose so
    text-mode consumers (CLI summaries, log-style readers) get the
    actionable remediation in the same string they'd see today.
    """
    diagnostic = exc.to_diagnostics()[0]
    message = diagnostic.message
    if diagnostic.suggestions:
        message = message + "\n\n" + "\n".join(diagnostic.suggestions)
    return {
        "response": "",
        "error": message,
        "error_class": type(exc).__name__,
        "model": exc.model or "unknown",
        "usage": {},
        "status": "error",
        "_diagnostic_context": dict(diagnostic.context or {}),
    }


def _error_dict_for_timeout(model: str, message: str) -> dict[str, Any]:
    """Build the error-dict for the in-thread FuturesTimeoutError path.

    Distinct from LiteLLM's ``Timeout`` (which is now ``LLMTransientError``).
    This path fires only for the inner ``ThreadPoolExecutor`` per-call
    timeout — when the LiteLLM call itself hung beyond ``timeout`` seconds.
    The orphan worker thread is still holding the connection open, so we
    do NOT retry (would create duplicate in-flight requests).
    """
    from pflow.core.diagnostic import LLM_FAILURE_CATEGORY

    return {
        "response": "",
        "error": message,
        "error_class": "TimeoutError",
        "model": model,
        "usage": {},
        "status": "error",
        "_diagnostic_context": {
            "category": LLM_FAILURE_CATEGORY,
            "error_class": "TimeoutError",
            "model": model,
            "kind": "pool_timeout",
        },
    }


def _error_dict_for_generic_failure(model: str, exc: Exception, attempts: int) -> dict[str, Any]:
    """Build the error-dict for ``exec_fallback`` after retry exhaustion.

    Catches non-deterministic failures that escaped ``_call_llm`` AND any
    ``LLMTransientError`` whose retry budget was exhausted.
    """
    from pflow.core.diagnostic import LLM_FAILURE_CATEGORY

    if isinstance(exc, LLMTransientError):
        diagnostic = exc.to_diagnostics()[0]
        message = f"LLM call failed after {attempts} attempts. Model: {model}. Error: {exc}"
        context = dict(diagnostic.context or {})
        context["kind"] = "retry_exhausted"
        context["transient_kind"] = exc.kind
        return {
            "response": "",
            "error": message,
            "error_class": type(exc).__name__,
            "model": model,
            "usage": {},
            "status": "error",
            "_diagnostic_context": context,
        }

    if "timed out" in str(exc).lower():
        message = (
            f"LLM call timed out after {attempts} attempts. Model: {model}. Increase timeout or check API connectivity."
        )
        error_class = "TimeoutError"
        kind = "retry_exhausted_timeout"
    else:
        message = f"LLM call failed after {attempts} attempts. Model: {model}. Error: {exc}"
        error_class = type(exc).__name__
        kind = "retry_exhausted"
    return {
        "response": "",
        "error": message,
        "error_class": error_class,
        "model": model,
        "usage": {},
        "status": "error",
        "_diagnostic_context": {
            "category": LLM_FAILURE_CATEGORY,
            "error_class": error_class,
            "model": model,
            "kind": kind,
        },
    }


def _read_cache_render_context(shared: dict[str, Any], node_id: str | None) -> CacheRenderContext | None:
    """Canonical defensive read of ``shared['__pflow_cache_render__'][node_id]``.

    Mirrors ``runtime/engine/plan_node._read_cache_context`` byte-for-byte —
    the same defensive read ensures hash-side and prep-side see the same
    context (or both miss). The ``or {}`` guard handles legacy/test paths
    where ``__pflow_cache_render__`` may be absent or set to ``None``.
    """
    if node_id is None:
        return None
    return (shared.get("__pflow_cache_render__") or {}).get(node_id)


def _emit_observed_below_min_cache_warning(
    *,
    shared: dict[str, Any],
    node_id: str | None,
    model: str,
    llm_usage: dict[str, Any],
) -> None:
    """Emit observed-tier cache.below-min-observed for LLMNode cache misses."""
    cache_ctx = _read_cache_render_context(shared, node_id)
    declared_prompt_cache = list(cache_ctx.subset) if cache_ctx and cache_ctx.subset else []
    if node_id is None or not declared_prompt_cache:
        return

    # When the provider didn't expose cache telemetry, we cannot honestly
    # observe whether the cache fired. Skip rather than emit a false-positive
    # observed-tier finding. ``has_cache_telemetry`` is the load-bearing
    # signal: it's True iff the source provider returned at least one cache
    # field. The previous ``not in llm_usage`` check was structurally
    # ineffective because ``LLMNode.post()`` always synthesizes the cache
    # keys (defaulting to 0); the presence flag carries the absence semantic
    # cleanly through the runtime → trace boundary. Mirrors the analyzer's
    # honest-unmeasurable convention used by ``_estimate_ref_tokens`` and
    # ``_compute_fragmentation_costs``.
    if not llm_usage.get("has_cache_telemetry", False):
        return

    finding = detect_below_min_tokens(
        BelowMinTokensEvidence(
            node_id=node_id,
            model=model,
            declared_prompt_cache=declared_prompt_cache,
            has_observed=True,
            observed_creation_tokens=int(llm_usage.get("cache_creation_input_tokens") or 0),
            observed_read_tokens=int(llm_usage.get("cache_read_input_tokens") or 0),
        )
    )
    if finding is None:
        return

    workflow_path = shared.get("_pflow_workflow_file") or "<unknown>"
    diagnostic = make_diagnostic(
        "cache.below-min-observed",
        node_id=finding.node_id,
        affected_workflow=workflow_path,
        model=finding.model,
        min_tokens=finding.min_tokens,
        cacheable_tokens=finding.cacheable_tokens,
        provider_note=finding.provider_note,
    )
    shared.setdefault("__warnings__", {}).setdefault(node_id, diagnostic)


def _count_text_tokens(text: str, model: str) -> int:
    """Best-effort token count for ``text`` under ``model``.

    Primary: ``litellm.token_counter`` (the same primitive
    ``cache_analysis.token_estimation`` uses). Fallback on any failure: a
    ``len(text) // 4`` heuristic — the worst-case bias is toward
    underestimating tokens for normal English, which biases the threshold
    check toward false-strip (lost savings, no error) over false-keep
    (Gemini hard-rejection). Acceptable for a binary above/below check.
    """
    try:
        from pflow.core.litellm_runtime import import_litellm

        return int(import_litellm().token_counter(model=model, text=text))
    except Exception:
        return len(text) // 4


@dataclass(frozen=True)
class CacheStripResult:
    """Records which cache markers were stripped at dispatch.

    Channels:
      - ``declared``: system_blocks markers (rendered ``prompt_cache:`` chunks).
      - ``prewarm``: user_message_blocks markers (auto-batch-prefix when
        ``prewarm: true`` fires).

    Per-channel ``*_measured_tokens`` is set only when that channel's
    marker was stripped — its value is the cumulative token count through
    the stripped block (the same number the existing warning template
    interpolates as ``cacheable_tokens``).

    Cumulative-token monotonicity guarantees ``prewarm`` strip without
    ``declared`` strip can only happen on pure-prewarm nodes (no
    ``system_blocks`` marker). Combined nodes either strip nothing,
    strip declared only, or strip both.
    """

    threshold: int
    declared_measured_tokens: int | None = None
    prewarm_measured_tokens: int | None = None


def _strip_below_min_cache_markers(
    *,
    system_blocks: list[dict[str, Any]] | None,
    user_message_blocks: list[dict[str, Any]] | None,
    model: str,
) -> CacheStripResult | None:
    """Strip ``cache_control`` markers whose cumulative cache scope is below
    the provider minimum.

    Each ``cache_control`` marker creates an independent provider cache
    scope spanning all preceding text content (including earlier blocks in
    the same message AND prior message sections — v1 order:
    ``system_blocks`` → ``user_message_blocks``). For each marker, we
    measure cumulative tokens through its block and strip the marker when
    below ``get_min_cache_tokens(model)``.

    Returns a ``CacheStripResult`` carrying per-channel ``measured_tokens``
    (smallest stripped scope in each channel), or ``None`` when no markers
    were stripped. Mutates the block dicts in place via
    ``del block["cache_control"]`` — block text content is unchanged so the
    call still goes out, it just no longer claims a cache.

    **Multi-marker semantics**: under multi-breakpoint placement (Anthropic),
    early markers' cumulative scopes are often below the provider minimum
    even when caching IS working (terminal marker survives, full prefix
    cached). We suppress the per-channel warning when AT LEAST ONE marker
    survives in that channel — the warning should signal "caching failed",
    not "some sub-markers couldn't activate."
    """
    threshold = get_min_cache_tokens(model)
    cumulative = 0
    declared_min: int | None = None
    prewarm_min: int | None = None
    # channel_label argument keeps the walker linear; per-channel
    # captures replace the previous flat ``stripped_scopes`` list.
    for channel_label, blocks in (("declared", system_blocks), ("prewarm", user_message_blocks)):
        if not blocks:
            continue
        for block in blocks:
            cumulative += _count_text_tokens(str(block.get("text", "")), model)
            if "cache_control" in block and cumulative < threshold:
                del block["cache_control"]
                if channel_label == "declared":
                    declared_min = cumulative if declared_min is None else min(declared_min, cumulative)
                else:
                    prewarm_min = cumulative if prewarm_min is None else min(prewarm_min, cumulative)

    # Suppress warnings on channels where at least one marker survived.
    # True caching failure = ALL markers in a channel stripped.
    if declared_min is not None and system_blocks and any("cache_control" in b for b in system_blocks):
        declared_min = None
    if prewarm_min is not None and user_message_blocks and any("cache_control" in b for b in user_message_blocks):
        prewarm_min = None

    if declared_min is None and prewarm_min is None:
        return None
    return CacheStripResult(
        threshold=threshold,
        declared_measured_tokens=declared_min,
        prewarm_measured_tokens=prewarm_min,
    )


def _emit_declared_rendered_below_min_warning(
    *,
    shared: dict[str, Any],
    node_id: str | None,
    model: str,
    measured_tokens: int,
    min_tokens: int,
) -> None:
    """Emit ``cache.below-min-rendered`` for a stripped DECLARED-channel marker.

    Authoritative for this run (``=`` assignment per ``nodes/CLAUDE.md``);
    the observed-tier emitter naturally suppresses itself afterward because
    the stripped marker means the provider returns no cache telemetry.
    """
    if node_id is None:
        return
    workflow_path = shared.get("_pflow_workflow_file") or "<unknown>"
    diagnostic = make_diagnostic(
        "cache.below-min-rendered",
        node_id=node_id,
        affected_workflow=workflow_path,
        model=model,
        min_tokens=min_tokens,
        cacheable_tokens=measured_tokens,
        provider_note=provider_note(model),
    )
    shared.setdefault("__warnings__", {})[node_id] = diagnostic


def _emit_prewarm_dispatch_stripped_warning(
    *,
    shared: dict[str, Any],
    node_id: str | None,
    model: str,
    measured_tokens: int,
    min_tokens: int,
    alias: str,
) -> None:
    """Emit ``cache.prewarm-disabled-below-min`` for a stripped PREWARM-channel marker.

    Same catalog ID the engine pre-flight emits; the catalog template was
    loosened so the wording is truthful for both producers (pre-flight
    disable + dispatch strip).
    """
    if node_id is None:
        return
    workflow_path = shared.get("_pflow_workflow_file") or "<unknown>"
    diagnostic = make_diagnostic(
        "cache.prewarm-disabled-below-min",
        node_id=node_id,
        affected_workflow=workflow_path,
        model=model,
        min_tokens=min_tokens,
        cacheable_tokens=measured_tokens,
        provider_note=provider_note(model),
        alias=alias,
    )
    shared.setdefault("__warnings__", {})[node_id] = diagnostic


def _build_openai_cache_kwargs(
    *,
    system_blocks: list[dict[str, Any]] | None,
    cache_ttl: str | None,
) -> dict[str, Any]:
    """OpenAI-specific cache routing kwargs (Task 159 C3).

    OpenAI caches automatically; ``cache_control`` markers are no-ops there.
    But two pflow-relevant knobs ride alongside: ``prompt_cache_key`` (sticky
    routing for parallel batches; soft-capped at ~15 RPM per backend) and
    ``prompt_cache_retention`` (DD#37 — pflow ``- ttl: 1h`` maps to ``"24h"``
    so the user's explicit opt-in isn't silently truncated by OpenAI's
    default ``in_memory`` 5-10-min idle expiry).

    Returns an empty dict when no cache rendering happened (``system_blocks``
    is ``None`` or empty) — caller merges into existing ``model_options``.

    The ``prompt_cache_key`` is MD5(deterministic-JSON(system_blocks)). On
    OpenAI the last block's marker is fixed at ``{"type": "ephemeral"}``
    (per ``_build_cache_control_marker``), so identical cache content across
    calls produces byte-identical ``system_blocks`` and thus an identical
    cache key — sticky routing fires.
    """
    if not system_blocks:
        return {}

    import hashlib

    from pflow.runtime.cache import _deterministic_json

    cache_kwargs: dict[str, Any] = {
        # MD5 is the project convention for content-identity hashing
        # (runtime/cache.py:108, instrumentation.py:191).
        "prompt_cache_key": hashlib.md5(
            _deterministic_json(system_blocks).encode(),
            usedforsecurity=False,
        ).hexdigest(),
    }
    # DD#37: workflow ttl=1h → OpenAI prompt_cache_retention="24h" (closest
    # discrete bucket above 1h; default ``in_memory`` is 5-10 min idle).
    if cache_ttl is not None and parse_cache_ttl(cache_ttl).seconds == 3600:
        cache_kwargs["prompt_cache_retention"] = "24h"
    return cache_kwargs


def _ensure_provider_supports_cache_ttl(
    *,
    provider_name: str | None,
    ttl: str | None,
    node_id: str | None,
    model: str,
) -> None:
    if is_cache_ttl_supported_by_provider(provider_name, ttl):
        return
    raise UnsupportedCacheTTLError(
        node_id=node_id or "<unknown>",
        provider_name=provider_name,
        ttl=ttl,
        model=model,
    )


def _emit_prewarm_disabled_warning(
    *,
    shared: dict[str, Any],
    node_id: str | None,
    kind: str,
    text: str,
    context: dict[str, Any],
) -> None:
    """Emit a structured ``__warnings__`` entry + a logger.warning when
    auto-batch-prefix caching gracefully degrades. Centralized so D.1's
    multiple bail-out paths share one observability surface."""
    if node_id is not None:
        shared.setdefault("__warnings__", {})[node_id] = {
            "kind": kind,
            "text": text,
            "context": context,
        }
    logger.warning("%s", text)


def _resolve_dynamic_suffix(
    *,
    unresolved: str,
    cut: int,
    static_prefix: str,
    resolved_prompt: str,
    shared: dict[str, Any],
) -> str | None:
    """Find the dynamic suffix in the resolved prompt.

    The cache path's ``static_prefix`` may differ byte-for-byte from the
    same portion in ``resolved_prompt`` (canonical JSON vs standard
    resolver's JSON-with-spaces / Python repr for embedded dict/list refs).
    Strategy:

    1. ``resolved_prompt.startswith(static_prefix)`` → fast path; trim by
       length.
    2. Fall back to the standard resolver's substitution for the same
       unresolved range; if that prefix matches, trim by its length.
    3. If neither matches, return ``None`` — caller emits the
       ``prewarm_disabled_static_prefix_unaligned`` warning and degrades
       to the plain-prompt path.
    """
    if resolved_prompt.startswith(static_prefix):
        return resolved_prompt[len(static_prefix) :]
    from pflow.runtime.template_resolver import TemplateResolver

    standard_static = TemplateResolver.resolve_template(unresolved[:cut], shared)
    if isinstance(standard_static, str) and resolved_prompt.startswith(standard_static):
        return resolved_prompt[len(standard_static) :]
    return None


def _build_user_message_blocks(
    *,
    cache_ctx: CacheRenderContext | None,
    resolved_prompt: str,
    shared: dict[str, Any],
    model: str,
    attachments: list[Attachment] | None = None,
    node_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """Auto-batch-prefix detection (Task 159 D.1).

    Returns ``None`` when the gate doesn't fire — caller falls back to the
    plain-string ``prompt`` path. Gate conditions (all required):

    1. ``cache_ctx`` exists.
    2. ``cache_ctx.prewarm`` is ``True`` (per spec DD#9 — auto-batch-prefix
       is opt-in via prewarm).
    3. ``cache_ctx.unresolved_batch_prompt`` is set (this is a batch LLM
       node; the engine populates the field for batch nodes only).
    4. ``cache_ctx.batch_alias`` is set (the per-item alias name).
    5. ``attachments`` is empty / None (Task 159 v1 limitation — see
       GH #358). pflow's ``## Cache`` rendering produces text-only content
       blocks; native image-cache support is a v1.x follow-up. When
       ``images: [...]`` AND ``prewarm: true`` both fire on the same node,
       gracefully disable prewarm for this run, emit a ``__warnings__``
       entry, and let the standard attachment path carry the images. The
       user sees the explicit signal "prewarm disabled because images."
    6. The unresolved template contains a ``${batch_alias.X}`` or
       ``${batch_alias[X]}`` reference (the boundary).
    7. The boundary's match start is > 0 (a non-trivial static prefix
       exists). When ``${item.X}`` is at position 0, F2 emits
       ``cache.prewarm-no-prefix`` in the analytical tier; runtime emits
       nothing per DD#36.

    When the gate fires, return ``[{"type": "text", "text": <static>,
    "cache_control": <marker>}, {"type": "text", "text": <suffix>}]``:

    - ``<static>``: deterministic resolution of the prefix portion via
      ``_resolve_static_prefix_for_cache`` (canonical JSON for embedded
      dict/list refs — load-bearing for hash-vs-prep byte-identity).
    - ``<marker>``: per-provider ``cache_control`` per the workflow ttl.
    - ``<suffix>``: dynamic portion of the resolved prompt (taken from
      ``resolved_prompt`` since the standard resolver already substituted
      the per-item ``${item.X}`` ref). The suffix is the resolved prompt
      minus the unresolved-static-prefix's resolved length.

    Note: the static portion's bytes here MAY differ from the same portion
    in ``resolved_prompt`` (which used the standard resolver — Python repr
    for embedded dict/list refs in complex templates). That's the
    deliberate trade-off: cache prefix bytes match the chunk-hash bytes for
    the same logical value, so cache hits fire reliably across calls. See
    ``_resolve_static_prefix_for_cache`` docstring + B3.3 plan section.
    """
    if cache_ctx is None:
        return None
    if not cache_ctx.prewarm:
        return None
    unresolved = cache_ctx.unresolved_batch_prompt
    alias = cache_ctx.batch_alias
    if unresolved is None or alias is None:
        return None

    # Task 159 v1 limitation — see GH #358. Auto batch-prefix caching cannot
    # mix with image attachments yet because ``## Cache`` chunks render as
    # text-only content blocks. When images: [...] AND prewarm: true both
    # fire, gracefully disable prewarm for this run (full fan-out, images
    # ride the standard attachment path) and emit a __warnings__ entry so
    # the user sees the degradation explicitly. Native image-cache support
    # in ``## Cache`` is the v1.x follow-up.
    if attachments:
        _emit_prewarm_disabled_warning(
            shared=shared,
            node_id=node_id,
            kind="prewarm_disabled_with_images",
            text=(
                f"Auto batch-prefix caching disabled for node "
                f"{node_id or '<unknown>'!r}: images: [...] are present and "
                "pflow v1 does not support images in the cached prefix. "
                "Either remove images:, remove prewarm:, or wait for native "
                "image-cache support (GH #358)."
            ),
            context={
                "node_id": node_id or "<unknown>",
                "image_count": len(attachments),
                "issue": "https://github.com/spinje/pflow/issues/358",
            },
        )
        return None

    boundary = first_per_item_position(unresolved, alias, cache_ctx.node_inputs)
    if boundary is None:
        return None
    cut = boundary
    if cut == 0:
        # No static portion — boundary at position 0.
        return None

    static_prefix = _resolve_static_prefix_for_cache(unresolved[:cut], shared)
    suffix = _resolve_dynamic_suffix(
        unresolved=unresolved,
        cut=cut,
        static_prefix=static_prefix,
        resolved_prompt=resolved_prompt,
        shared=shared,
    )
    if suffix is None:
        # Boundary detection couldn't align canonical-bytes or
        # standard-resolver-bytes with the resolved prompt. Should not
        # fire in practice; surface as an explicit prewarm-disabled
        # signal so observability isn't silent.
        _emit_prewarm_disabled_warning(
            shared=shared,
            node_id=node_id,
            kind="prewarm_disabled_static_prefix_unaligned",
            text=(
                f"Auto batch-prefix caching disabled for node "
                f"{node_id or '<unknown>'!r}: static-prefix bytes could not "
                "be aligned with the resolved prompt (cache-canonical and "
                "standard-resolver paths both diverged). prewarm degraded "
                "for this run; items[1:] each pay full cache-write cost."
            ),
            context={
                "node_id": node_id or "<unknown>",
                "unresolved_len": len(unresolved),
                "cut": cut,
            },
        )
        return None

    provider = detect_provider(model)
    provider_name = provider.name if provider else None
    ttl = cache_ctx.cache_block.ttl if cache_ctx.cache_block else None
    # System-block rendering validates the same provider/TTL pair when
    # prompt_cache is non-empty. Keep this check here for prewarm-only batch
    # nodes, where the cache marker is rendered in the user-message split.
    _ensure_provider_supports_cache_ttl(provider_name=provider_name, ttl=ttl, node_id=node_id, model=model)
    return [
        {
            "type": "text",
            "text": static_prefix,
            "cache_control": _build_cache_control_marker(provider_name, ttl),
        },
        {"type": "text", "text": suffix},
    ]


def _build_attachments_from_images(images: Any) -> list[Attachment]:
    """Convert the user's ``images`` param into typed ``Attachment`` blocks.

    Single-value inputs are wrapped in a list. URLs are stored verbatim;
    local paths are validated for existence and stored as image_path
    attachments (the adapter encodes them at the API boundary).
    """
    if not isinstance(images, list):
        images = [images]
    attachments: list[Attachment] = []
    for img in images:
        if not isinstance(img, str):
            raise TypeError(f"Image must be a string (URL or path), got: {type(img).__name__}")
        if img.startswith(("http://", "https://")):
            attachments.append(Attachment(kind="image_url", value=img))
            continue
        path = Path(img)
        if not path.exists():
            raise ValueError(f"Image file not found: {img}\nPlease ensure the file exists at the specified path.")
        attachments.append(Attachment(kind="image_path", value=str(path)))
    return attachments


def _assemble_cache_prep(
    *,
    user_system: str | None,
    cache_ctx: CacheRenderContext | None,
    shared: dict[str, Any],
    model: str,
    resolved_prompt: str,
    user_model_options: dict[str, Any],
    attachments: list[Attachment] | None = None,
    node_id: str | None = None,
) -> tuple[
    list[dict[str, Any]] | None,
    list[dict[str, Any]] | None,
    list[str],
    dict[str, Any],
    str | None,
    str | None,
]:
    """Build the cache-rendering quad for ``prep_res``.

    Returns ``(system_blocks, user_message_blocks, chunks_skipped,
    model_options, cache_skipped_reason, prewarm_disabled_reason)``:

    - ``system_blocks`` — declared cache rendered as content blocks (C1.2),
      or ``None`` when no cache opt-in applies.
    - ``user_message_blocks`` — auto-batch-prefix split for prewarm batches
      (D.1), or ``None`` when the gate doesn't fire.
    - ``chunks_skipped`` — names of chunks filtered as ABSENT (trace 2.1.0
      channel via ``cache_chunks_skipped`` on ``llm_usage``).
    - ``model_options`` — user options with OpenAI cache kwargs merged in
      (only on OpenAI; other providers pass through unchanged).
    - ``cache_skipped_reason`` — ``"below_min"`` when runtime strips a
      declared-channel cache marker before dispatch, else ``None``.
    - ``prewarm_disabled_reason`` — ``"below_min"`` when runtime strips a
      pure prewarm-channel cache marker before dispatch, else ``None``.

    Extracted from ``LLMNode.prep`` to keep cyclomatic complexity below the
    project's C901 threshold.
    """
    cache_skipped_reason: str | None = None
    prewarm_disabled_reason: str | None = None
    system_blocks, chunks_skipped = _build_system_blocks(
        user_system=user_system,
        cache_ctx=cache_ctx,
        shared=shared,
        model=model,
        node_id=node_id,
    )
    user_message_blocks = _build_user_message_blocks(
        cache_ctx=cache_ctx,
        resolved_prompt=resolved_prompt,
        shared=shared,
        model=model,
        attachments=attachments,
        node_id=node_id,
    )
    # Pre-dispatch strip: when the rendered cache content for any marker
    # is below the provider's minimum-cacheable-tokens, strip the marker
    # before sending. Otherwise Gemini hard-rejects the call ("Cached
    # content is too small") and Anthropic silently no-ops the marker
    # without surfacing a warning until post-call telemetry.
    result = _strip_below_min_cache_markers(
        system_blocks=system_blocks,
        user_message_blocks=user_message_blocks,
        model=model,
    )
    if result is not None:
        if result.declared_measured_tokens is not None:
            # Declared-channel strip: primary cause when both channels strip
            # (cumulative monotonicity — fix declared first; prewarm strip
            # is downstream consequence). Emit declared warning only.
            cache_skipped_reason = "below_min"
            _emit_declared_rendered_below_min_warning(
                shared=shared,
                node_id=node_id,
                model=model,
                measured_tokens=result.declared_measured_tokens,
                min_tokens=result.threshold,
            )
        elif result.prewarm_measured_tokens is not None:
            # Pure prewarm-only strip (impossible on combined nodes per
            # monotonicity). cache_ctx.batch_alias is guaranteed non-None
            # because _build_user_message_blocks returns None when alias
            # is missing, so the strip above could only have happened with
            # a valid alias in scope.
            prewarm_disabled_reason = "below_min"
            alias = cache_ctx.batch_alias if cache_ctx else None
            if alias is not None:
                _emit_prewarm_dispatch_stripped_warning(
                    shared=shared,
                    node_id=node_id,
                    model=model,
                    measured_tokens=result.prewarm_measured_tokens,
                    min_tokens=result.threshold,
                    alias=alias,
                )

    options = dict(user_model_options)
    provider = detect_provider(model)
    if provider is not None and provider.name == "openai":
        cache_ttl = cache_ctx.cache_block.ttl if cache_ctx and cache_ctx.cache_block else None
        for key, value in _build_openai_cache_kwargs(system_blocks=system_blocks, cache_ttl=cache_ttl).items():
            # ``setdefault`` so a user-provided override wins (e.g., a test
            # pinning a specific prompt_cache_key for fixture stability).
            options.setdefault(key, value)
    return system_blocks, user_message_blocks, chunks_skipped, options, cache_skipped_reason, prewarm_disabled_reason


def _build_system_blocks(
    *,
    user_system: str | None,
    cache_ctx: CacheRenderContext | None,
    shared: dict[str, Any],
    model: str,
    node_id: str | None = None,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Render the cached system prefix as structured content blocks.

    Returns ``(system_blocks, chunks_skipped)``. ``system_blocks`` is
    ``None`` when no cache rendering applies (no ctx, empty subset, or every
    chunk filtered as ABSENT) — caller falls back to today's plain-string
    ``system`` path so byte-for-byte behavior is preserved for opt-out
    nodes.

    When at least one chunk renders, the returned list is:

    1. The user's ``system`` param (when set) as the FIRST block, no marker.
    2. One block per declared chunk in declaration order: ``prose_before``
       concatenated with the deterministic-serialized chunk value.
    3. Per-provider ``cache_control`` markers placed by
       ``compute_marker_chunk_indices``: Anthropic gets up to 4 markers (first
       N-1 chunks individual + terminal merge); other providers get a terminal
       marker only. Below-min markers are stripped at request time by
       ``_strip_below_min_cache_markers``.

    The ABSENT filter MUST stay symmetric with
    ``runtime/engine/plan_node._render_cache_for_hash`` — both sites import
    ``_resolve_chunk_value`` and ``_ChunkAbsentSentinel`` from
    ``pflow.core.cache_render``. If they diverge, hash and prep render
    different bytes for the same logical state — the silent stale-cache
    regression class B3.3/C1.2 close together.
    """
    if cache_ctx is None or not cache_ctx.subset or cache_ctx.cache_block is None:
        return None, []

    chunks_by_name = {c.name: c for c in cache_ctx.cache_block.items}
    rendered: list[tuple[str, str]] = []  # (prose_before, value_str)
    chunks_skipped: list[str] = []

    for name in cache_ctx.subset:
        chunk = chunks_by_name.get(name)
        if chunk is None:
            # Validator rejects undeclared subset entries (B2.3). Defensive
            # skip here for direct-compile bypass paths (logged at the hash
            # site; we silently match the hash-side filter so bytes stay
            # symmetric).
            continue
        value = _resolve_chunk_value(chunk, shared)
        if isinstance(value, _ChunkAbsentSentinel):
            chunks_skipped.append(name)
            continue
        rendered.append((chunk.prose_before, value))

    if not rendered:
        # Every chunk was filtered. Fall back to the plain-string system
        # path (return None) but still record the skip list so the trace
        # channel can attribute discrepancies to runtime branch skips.
        return None, chunks_skipped

    blocks: list[dict[str, Any]] = []
    if user_system:
        blocks.append({"type": "text", "text": user_system})
    for prose, value in rendered:
        blocks.append({"type": "text", "text": prose + value})

    provider = detect_provider(model)
    provider_name = provider.name if provider else None
    _ensure_provider_supports_cache_ttl(
        provider_name=provider_name,
        ttl=cache_ctx.cache_block.ttl,
        node_id=node_id,
        model=model,
    )

    # Multi-breakpoint placement (Anthropic only — others get terminal marker).
    # Indices are into the RENDERED chunks (post-ABSENT-filter), so we offset
    # by the optional leading user_system block. Use cache_ctx.prewarm (NOT
    # config.prewarm or any other source) — the engine pre-strips this to
    # False when _should_disable_below_min_prewarm fires, so the post-pre-flight
    # state is the budget-truth.
    chunk_block_offset = 1 if user_system else 0
    marker_indices = compute_marker_chunk_indices(
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


class LLMNode(Node):
    """
    General-purpose LLM node for text processing and AI reasoning or data transformation.
    When using this node, you should always only have it do ONE task. If you need to do multiple AI tasks, you should use multiple LLM nodes.
    For example, if you need to create both unstructured and structured data, you should use two different LLM nodes not one node that does both.

    Interface:
    - Params: prompt: str  # Text prompt to send to model
    - Params: system: str  # System prompt (optional)
    - Params: images: list[str]  # Image URLs or file paths (optional)
    - Params: output_schema: dict  # JSON Schema for structured output (optional)
    - Params: reasoning_effort: str  # Reasoning depth: xhigh/high/medium/low/minimal/none (optional, mapped to provider-specific params)
    - Params: reasoning_max_tokens: int  # Direct reasoning token budget, mutually exclusive with reasoning_effort (optional)
    - Params: model_options: dict  # Additional provider-specific model options passed as kwargs (optional; reasoning keys must use reasoning_effort/reasoning_max_tokens)
    - Writes: shared["response"]: str|dict  # Text (str), parsed JSON (dict) when output_schema is set, or raw text on parse failure
    - Writes: shared["error"]: str  # Error message if LLM call or JSON parsing failed
    - Writes: shared["prompt"]: str  # Rendered prompt actually sent to the model (populated for tracing/audit, including per-item batch traces)
    - Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
        - model: str  # Model identifier used
        - input_tokens: int  # Number of input tokens consumed
        - output_tokens: int  # Number of output tokens generated
        - total_tokens: int  # Total tokens (input + output)
        - cache_creation_input_tokens: int  # Tokens used for cache creation
        - cache_read_input_tokens: int  # Tokens read from cache
        - thinking_tokens: int  # Reasoning/thinking tokens consumed (0 for non-reasoning models)
        - thinking_budget: int  # Reasoning token budget set on the request (0 when not configured or provider uses categorical levels)
        - cost_usd: float  # Estimated cost in USD (None when LiteLLM has no pricing data — e.g. Ollama, custom endpoints, brand-new models)
        - cache_key: str  # Trace 2.1.0 — memo cache key (write events: key the entry was created with; hit events: matching key). Absent for fresh executions without a memo write.
        - cache_source: str  # Trace 2.1.0 — "memo" | "in_process" — which pflow cache layer served this call. Absent for fresh executions.
        - cache_age_sec: float  # Trace 2.1.0 — age of the cached entry in seconds. Absent for fresh executions or in-process hits.
        - cache_chunks_skipped: list  # Trace 2.1.0 — chunk names skipped during cache rendering due to ABSENT upstream branches (default empty list).
        - cache_skipped_reason: str|None  # Trace 2.3.0 — "below_min" when runtime stripped cache markers before dispatch.
        - prewarm_disabled_reason: str|None  # Trace 2.3.0 — "below_min" when pre-flight disabled batch prewarm for this node.
    - Params: model: str  # Model to use (optional - always use smart default unless user requests specific model)
    - Params: temperature: float  # Sampling temperature (default: 1.0)
    - Params: max_tokens: int  # Max response tokens (optional)
    - Params: timeout: int  # Execution timeout in seconds for LLM API call (default: 120)
    - Actions: default (success), error (failure)
    """

    name = "llm"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize the LLM node with retry support."""
        super().__init__(max_retries=max_retries, wait=wait)

    def _validate_timeout(self) -> float:
        """Extract and validate the timeout parameter."""
        timeout = self.params.get("timeout", 120)
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            raise ValueError(f"Timeout must be a positive number, got {timeout!r}") from None
        if timeout <= 0:
            raise ValueError(f"Timeout must be a positive number, got {timeout}")
        return timeout

    @staticmethod
    def _strip_code_block(response: str) -> str:
        """Strip markdown code block fences from LLM responses.

        LLMs commonly wrap their output in code fences (```json ... ```) as a
        transport artifact. This method strips those fences when the entire
        response is a single code block, returning the inner content as a string.

        Only strips when the response both starts AND ends with code fences
        (after whitespace). Responses with trailing text after the closing
        fence are returned unchanged — we never silently discard content.

        No JSON parsing is performed — the return value is always a string.
        Downstream consumers use the template system (dot notation, type
        coercion) to parse JSON on demand.

        Args:
            response: The raw LLM response string

        Returns:
            The response with outer code block fences stripped, still as a string
        """
        trimmed = response.strip()

        if not trimmed.startswith("```") or not trimmed.endswith("```"):
            return response

        # Find the end of the opening fence line
        first_newline = trimmed.find("\n")
        if first_newline == -1:
            return response

        # Find the closing fence (last occurrence)
        closing = trimmed.rfind("```")
        if closing <= first_newline:
            return response

        # Extract content between fences
        return trimmed[first_newline + 1 : closing].strip()

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract and prepare inputs from parameters."""
        # Extract from params (template resolution handles shared store wiring)
        prompt = self.params.get("prompt")

        if not prompt:
            raise ValueError(
                "LLM node requires 'prompt' parameter. "
                "Use template syntax like '- prompt: ${previous_node.output}' "
                "to wire data from other nodes."
            )

        # System prompt from params
        system = self.params.get("system")

        # Temperature with clamping
        temperature = self.params.get("temperature", 1.0)
        temperature = max(0.0, min(2.0, temperature))

        # Build attachments from the user's images param. URLs pass through;
        # local paths are validated and stored as image_path entries (the
        # adapter encodes them at the API boundary). Image paths are inputs
        # (not workflow assets) — relative paths resolve against CWD at
        # file-open time by the adapter (Python's open() semantics). Distinct
        # from code-block file refs (``code: @./helper.py``) which resolve
        # relative to the workflow file.
        attachments = _build_attachments_from_images(self.params.get("images", []))

        # Validate reasoning_effort early (deterministic error, not worth retrying)
        reasoning_effort = self.params.get("reasoning_effort")
        valid_efforts = {*EFFORT_RATIOS.keys(), "none"}
        if reasoning_effort and reasoning_effort.lower() not in valid_efforts:
            valid_list = ", ".join(sorted(valid_efforts))
            raise ValueError(f"Invalid reasoning_effort: '{reasoning_effort}'. Must be one of: {valid_list}")

        # Model is required. The compiler injects ``model`` for every LLM
        # node (compilation/compiler.py: it either reads the user's value,
        # falls back to settings/auto-detect via ``get_default_workflow_model``,
        # or raises ``CompilationError`` when no source is available). Any
        # path that reaches here without a model has bypassed compilation
        # — typically a unit test that constructs ``LLMNode()`` directly
        # and forgot to set ``model`` in its params. Fail loudly instead
        # of silently substituting a hardcoded default.
        model = self.params.get("model")
        if not model:
            raise ValueError(
                "LLM node requires a 'model' parameter. The compiler injects this from "
                "the workflow YAML, settings.default_model, or auto-detected provider keys; "
                "if you are calling LLMNode directly (e.g. in a unit test), set "
                "'model' explicitly via node.set_params({'model': '<provider>/<model>'})."
            )

        # Cache rendering (Task 159 C1.2 + C3) — build structured
        # ``system_blocks`` with per-provider ``cache_control`` markers, plus
        # OpenAI-specific ``prompt_cache_key`` / ``prompt_cache_retention``
        # kwargs when applicable. The system_blocks filter is symmetric with
        # the hash-side at ``runtime/engine/plan_node._render_cache_for_hash``
        # — same shared helper, same ABSENT sentinel — so hash and prep
        # render byte-identical bytes for the same logical state (DD#19
        # silent-stale-cache gate).
        node_id = getattr(self, "node_id", None)
        cache_ctx = _read_cache_render_context(shared, node_id)
        (
            system_blocks,
            user_message_blocks,
            chunks_skipped,
            merged_model_options,
            cache_skipped_reason,
            prewarm_disabled_reason_dispatch,
        ) = _assemble_cache_prep(
            user_system=system,
            cache_ctx=cache_ctx,
            shared=shared,
            model=model,
            resolved_prompt=prompt,
            user_model_options=self.params.get("model_options") or {},
            attachments=attachments,
            node_id=node_id,
        )

        # Pre-flight wrote __prewarm_disabled_below_min__[node_id] BEFORE batch
        # dispatch (engine.py:_should_disable_below_min_prewarm); dispatch strip
        # writes prewarm_disabled_reason_dispatch per-call. Pre-flight wins when
        # both fire — it disabled prewarm sequencing for the whole batch, so the
        # per-call dispatch strip is downstream of that decision.
        prewarm_disabled_reason = (shared.get("__prewarm_disabled_below_min__") or {}).get(
            node_id
        ) or prewarm_disabled_reason_dispatch

        prep_res = {
            "prompt": prompt,
            "model": model,
            "temperature": temperature,
            "system": system,
            "system_blocks": system_blocks,
            "user_message_blocks": user_message_blocks,
            "__cache_chunks_skipped__": chunks_skipped,
            "__cache_skipped_reason__": cache_skipped_reason,
            "__prewarm_disabled_reason__": prewarm_disabled_reason,
            "max_tokens": self.params.get("max_tokens"),
            "attachments": attachments,
            "output_schema": self.params.get("output_schema"),
            "reasoning_effort": reasoning_effort,
            "reasoning_max_tokens": self.params.get("reasoning_max_tokens"),
            "model_options": merged_model_options,
            "timeout": self._validate_timeout(),
        }

        # Resolve the per-call trace hook on the engine thread BEFORE
        # exec() submits to the inner ThreadPoolExecutor. The hook is then
        # passed explicitly through the pool boundary as a function arg —
        # unlike the previous monkey-patched lookup which read thread-local
        # state from the worker thread (where it was never registered).
        # See plan: /Users/andfal/.claude/plans/magical-swinging-taco.md
        collector = shared.get("__trace_collector__")
        if collector is not None and node_id is not None:
            prep_res["_trace_hook"] = collector.get_trace_hook(node_id)

        return prep_res

    def _call_llm(self, prep_res: dict[str, Any], trace_hook: TraceHook | None = None) -> dict[str, Any]:
        """Execute the actual LLM API call. Extracted for timeout wrapping.

        The ``trace_hook`` is captured by ``exec()`` from ``prep_res`` BEFORE
        the inner pool.submit, then passed through the pool boundary as an
        explicit arg. Default ``None`` keeps the function callable directly
        in tests that don't care about tracing.
        """
        reasoning_kwargs = map_reasoning_options(
            prep_res["model"],
            prep_res.get("reasoning_effort"),
            prep_res.get("reasoning_max_tokens"),
            prep_res.get("max_tokens"),
        )

        # The adapter raises typed LLMCallError subclasses for deterministic
        # provider failures and LLMTransientError for transient ones. We
        # catch the deterministic ones at this single boundary (preventing
        # the Node retry loop from burning three attempts on a permanent
        # failure) and re-raise transient ones so the retry loop fires.
        # The exception's own to_diagnostics() override produces the rich
        # user-facing message + structured context — the LLMNode just
        # consumes it. See pflow.core.llm_client.complete docstring and
        # pflow.core.exceptions for the typed hierarchy.
        model = prep_res["model"]
        # Cache rendering (Task 159 C1.2): pass structured ``system_blocks``
        # to the adapter when prep built them; fall back to the plain-string
        # ``system`` path otherwise. ``complete()``'s ``system`` parameter
        # accepts both shapes (C1.1 widening).
        system_blocks = prep_res.get("system_blocks")
        system_arg: str | list[dict[str, Any]] | None = system_blocks if system_blocks else prep_res["system"]
        try:
            adapter_response = complete(
                model=model,
                prompt=prep_res["prompt"],
                system=system_arg,
                temperature=prep_res["temperature"],
                max_tokens=prep_res["max_tokens"],
                attachments=prep_res["attachments"] or None,
                schema=prep_res["output_schema"],
                reasoning_kwargs=reasoning_kwargs,
                model_options=prep_res.get("model_options") or None,
                timeout=prep_res.get("timeout"),
                trace_hook=trace_hook,
                user_message_blocks=prep_res.get("user_message_blocks"),
            )
        except LLMTransientError:
            # Transient: re-raise so the Node retry loop catches it and
            # retries. exec_fallback will fire if all retries are exhausted.
            raise
        except LLMCallError as e:
            # Deterministic: catch at single boundary, build error dict from
            # the exception's own to_diagnostics() override. Covers
            # UnknownModelError, MissingApiKeyError, InvalidRequestError, and
            # any future deterministic subclass automatically.
            #
            # Task 159 C1.2 cross-layer co-edit: the error-dict's ``usage``
            # keyset must carry ``cache_chunks_skipped`` so the trace event
            # for the failure still records runtime branch skips. We wrap at
            # the call site (here) — NOT in the builder signature — to keep
            # error-dict builders cross-cutting-stable. ``prep_res`` is the
            # method's input arg; directly available.
            err_dict = _error_dict_from_exception(e)
            err_dict["usage"]["cache_chunks_skipped"] = list(prep_res.get("__cache_chunks_skipped__", []))
            err_dict["usage"]["cache_skipped_reason"] = prep_res.get("__cache_skipped_reason__")
            err_dict["usage"]["prewarm_disabled_reason"] = prep_res.get("__prewarm_disabled_reason__")
            return err_dict

        return {
            "response": adapter_response.text,
            "usage": adapter_response.usage,
            "model": adapter_response.model,
            "has_schema": adapter_response.has_schema,
            # Pass adapter warnings through to post() so they can be lifted
            # into shared["__warnings__"] for JSON-output visibility.
            "warnings": adapter_response.warnings,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute LLM call with timeout protection."""
        timeout = prep_res.get("timeout", 120)
        # Capture the trace hook on the engine thread (resolved by prep)
        # BEFORE handing off to the pool. The hook is a closure over the
        # collector + node_id — passing it as an explicit arg makes it
        # survive the thread boundary regardless of which worker runs the
        # call. (The previous design tried to look up the active collector
        # via thread-local state on the worker thread, which always failed
        # because the worker wasn't the registered thread.)
        trace_hook = prep_res.get("_trace_hook")

        # IMPORTANT: Do NOT use `with ThreadPoolExecutor` — its __exit__ calls
        # shutdown(wait=True) which blocks until the thread finishes, defeating
        # the timeout for stuck API calls (same pattern as python_code.py).
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._call_llm, prep_res, trace_hook)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            logger.warning(
                f"LLM call timed out after {timeout}s, orphan thread may continue running",
                extra={"model": prep_res["model"], "timeout": timeout},
            )
            # Return error dict instead of raising — prevents PocketFlow retry.
            # Retrying timeouts is harmful: the orphan thread from this attempt
            # is still running the API call, so retry would create duplicate
            # in-flight requests (wasting money and adding rate-limit pressure).
            # Distinct from LiteLLM's Timeout (now LLMTransientError) — that
            # path does retry; this one explicitly does not.
            err_dict = _error_dict_for_timeout(
                prep_res["model"],
                f"LLM call timed out after {timeout}s. "
                f"Model: {prep_res['model']}. "
                f"Increase timeout or check API connectivity.",
            )
            # Task 159 C1.2 cross-layer co-edit (cache_chunks_skipped) — wrap
            # at the caller, not the builder.
            err_dict["usage"]["cache_chunks_skipped"] = list(prep_res.get("__cache_chunks_skipped__", []))
            err_dict["usage"]["cache_skipped_reason"] = prep_res.get("__cache_skipped_reason__")
            err_dict["usage"]["prewarm_disabled_reason"] = prep_res.get("__prewarm_disabled_reason__")
            return err_dict
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store."""
        # Surface the rendered prompt for tracing/audit. Critical for per-item
        # batch traces: WorkflowTraceCollector keys llm_prompts by node_id only,
        # so parallel batch workers all overwrite the same slot. The batch
        # executor's _capture_item_trace falls back to node_output["prompt"]
        # for per-item visibility — populating it here is the seam.
        rendered_prompt = prep_res.get("prompt")
        if isinstance(rendered_prompt, str):
            shared["prompt"] = rendered_prompt
        # 2.2.0: same seam for the effective system content (cache-rendered
        # list[dict] when present, else plain string). Parallel batch workers
        # overwrite the collector's llm_systems slot; the per-item trace
        # falls back to node_output["system"] for per-item visibility.
        rendered_system = prep_res.get("system_blocks") or prep_res.get("system")
        if isinstance(rendered_system, (str, list)):
            shared["system"] = rendered_system

        # Check for error first
        if isinstance(exec_res, dict) and exec_res.get("status") == "error":
            self._propagate_error_to_shared(shared, exec_res)
            return "error"  # Return error action so workflow error handling can respond

        raw_response = exec_res["response"]

        # Store usage metrics BEFORE response parsing — ensures usage is
        # captured even if output_schema JSON parsing fails below.
        # The adapter normalizes usage into a stable dict shape (matching keys
        # below), so post() reads them directly with no object-path fallback.
        usage_dict = exec_res.get("usage")
        if usage_dict:
            llm_usage = {
                "model": usage_dict.get("model", exec_res.get("model", "unknown")),
                "input_tokens": usage_dict.get("input_tokens", 0) or 0,
                "uncached_input_tokens": usage_dict.get("uncached_input_tokens", 0) or 0,
                "output_tokens": usage_dict.get("output_tokens", 0) or 0,
                "total_tokens": usage_dict.get("total_tokens", 0) or 0,
                "cache_creation_input_tokens": usage_dict.get("cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": usage_dict.get("cache_read_input_tokens", 0) or 0,
                # ``has_cache_telemetry`` distinguishes "provider reported zero
                # cache tokens" from "provider didn't expose cache telemetry."
                # Load-bearing for ``_emit_observed_below_min_cache_warning``:
                # zero counts are only evidence the cache failed to fire when
                # telemetry is actually present (otherwise we can't observe it).
                "has_cache_telemetry": bool(usage_dict.get("has_cache_telemetry", False)),
                "input_token_accounting": usage_dict.get("input_token_accounting", "total_includes_cache"),
                "thinking_tokens": usage_dict.get("thinking_tokens", 0) or 0,
                "thinking_budget": usage_dict.get("thinking_budget", 0) or 0,
                # Task 159 C1.2: per-call list of cache chunks skipped due to
                # ABSENT upstream branches (default empty). Trace 2.1.0 (E.1)
                # surfaces this so analyze-cache --from-trace can attribute
                # cache discrepancies to runtime branch skips.
                "cache_chunks_skipped": list(prep_res.get("__cache_chunks_skipped__", [])),
                "cache_skipped_reason": prep_res.get("__cache_skipped_reason__"),
                "prewarm_disabled_reason": prep_res.get("__prewarm_disabled_reason__"),
            }
            # Adapter populates cost_usd from LiteLLM's response_cost (None
            # when LiteLLM has no pricing data for the model).
            if "cost_usd" in usage_dict:
                llm_usage["cost_usd"] = usage_dict["cost_usd"]
            shared["llm_usage"] = llm_usage
        else:
            # Empty dict per spec when usage unavailable
            shared["llm_usage"] = {}

        # LLMNode-specific prompt-cache miss observation. This uses provider
        # telemetry after the call, not tokenizer work in the hot path. It
        # preserves earlier warnings via setdefault; the empty-response warning
        # below intentionally overwrites this observational warning when both
        # fire because empty response is the critical failure signal.
        # node_id is a compiler-set dynamic attribute (compilation/compiler.py:299).
        node_id = getattr(self, "node_id", None)
        observed_usage = shared.get("llm_usage")
        if isinstance(observed_usage, dict):
            _emit_observed_below_min_cache_warning(
                shared=shared,
                node_id=node_id,
                model=prep_res.get("model") or self.params.get("model") or "",
                llm_usage=observed_usage,
            )

        # Surface adapter warnings (e.g. empty-response trap on reasoning
        # models) into __warnings__ so JSON consumers see them and the
        # workflow status shifts to DEGRADED. setdefault routes __*__ keys
        # to root via the NamespacedSharedStore proxy contract; subscript
        # write hits the returned root dict. (See namespaced_store.py
        # __setitem__ rules — direct write precedent at batch_executor.py
        # ~812-814.) Each warning is a dict with `kind`/`text`/`context`.
        # Consumers normalize it with core.diagnostic.normalize_runtime_warning
        # so legacy string warnings and structured LLM warnings can coexist.
        warnings_list = exec_res.get("warnings") or []
        if warnings_list and node_id is not None:
            # In v1 the adapter emits at most one warning per call. If a
            # future case needs multiple, change the contract to a list value.
            shared.setdefault("__warnings__", {})[node_id] = warnings_list[0]

        # Parse response — schema mode or plain text. Schema mode goes
        # through json.loads first (today's contract); LLMResponseParseError
        # would also be raisable here in a future version that uses
        # parse_structured_response, but right now LLMNode's schema path is
        # the inline json.loads. We catch the typed exception to surface
        # error_class consistently with the _call_llm path.
        if exec_res["has_schema"]:
            try:
                shared["response"] = json.loads(raw_response)
            except json.JSONDecodeError as e:
                # Build the same error dict shape as _call_llm so the runtime
                # path produces the same structured Diagnostic. Use
                # LLMResponseParseError so the override produces the right
                # remediation suggestions.
                from pflow.core.exceptions import LLMResponseParseError

                err = LLMResponseParseError(
                    f"Structured output JSON parse failed: {e}",
                    model=exec_res.get("model"),
                )
                error_dict = _error_dict_from_exception(err)
                # Task 159 C1.2 cross-layer co-edit (cache_chunks_skipped) —
                # wrap at the caller. ``prep_res`` is this method's arg.
                error_dict["usage"]["cache_chunks_skipped"] = list(prep_res.get("__cache_chunks_skipped__", []))
                error_dict["usage"]["cache_skipped_reason"] = prep_res.get("__cache_skipped_reason__")
                error_dict["usage"]["prewarm_disabled_reason"] = prep_res.get("__prewarm_disabled_reason__")
                # Preserve raw response for downstream fallback parsing —
                # contract preserved from the previous behavior. Usage was
                # captured above (the call succeeded; only parsing failed),
                # so preserve_usage=True keeps shared["llm_usage"] intact.
                shared["response"] = raw_response
                self._propagate_error_to_shared(shared, error_dict, response_already_set=True, preserve_usage=True)
                return "error"
        else:
            # Unstructured output: strip code block fences (LLM transport artifact), keep as string
            shared["response"] = self._strip_code_block(raw_response)

        return "default"

    def _propagate_error_to_shared(
        self,
        shared: dict[str, Any],
        exec_res: dict[str, Any],
        *,
        response_already_set: bool = False,
        preserve_usage: bool = False,
    ) -> None:
        """Write the error-dict fields to shared store.

        Single seam for every error path's shared-store mutation:
        ``_call_llm`` typed-exception catches, the FuturesTimeoutError path
        in ``exec``, ``exec_fallback`` after retry exhaustion, and the
        JSON-parse failure path in ``post``. Surfaces the structured fields
        an agent needs to discriminate failure modes:

        - ``shared["error"]`` — the user-facing prose
        - ``shared["error_class"]`` — type(exc).__name__ for programmatic branching
        - ``shared["_diagnostic_context"]`` — full structured context dict
          lifted by ``executor_service._enrich_error_from_node_output`` into
          the runtime Diagnostic that reaches JSON output

        ``preserve_usage=True`` keeps ``shared["llm_usage"]`` intact for
        the JSON-parse path (the call itself succeeded; usage was captured
        before parsing). All other error paths zero it out — EXCEPT for
        Task 159's ``cache_chunks_skipped`` channel, which is preserved
        from ``exec_res["usage"]`` so the trace event for the failure
        still records runtime branch-skips (cross-layer co-edit; the
        wrap at the four error sites in ``_call_llm`` / ``exec`` /
        ``exec_fallback`` / ``post()`` populates this field on the
        err_dict, and this seam is what threads it into shared).
        """
        shared["error"] = exec_res.get("error", "Unknown error")
        error_class = exec_res.get("error_class")
        if error_class is not None:
            shared["error_class"] = error_class
        diagnostic_context = exec_res.get("_diagnostic_context")
        if diagnostic_context:
            shared["_diagnostic_context"] = diagnostic_context
        if not response_already_set:
            shared["response"] = ""
        if not preserve_usage:
            # Task 159 C1.2 — preserve cache_chunks_skipped from the err_dict
            # when zeroing the rest of llm_usage. The four error sites wrap
            # the err_dict's ``usage`` keyset with this field; this seam
            # threads it into shared so trace 2.1.0 records runtime branch
            # skips even on failure paths. Without this preservation, the
            # wraps at the four call sites are dead code.
            usage_in = exec_res.get("usage", {})
            cache_chunks_skipped = usage_in.get("cache_chunks_skipped", [])
            cache_skipped_reason = usage_in.get("cache_skipped_reason")
            prewarm_disabled_reason = usage_in.get("prewarm_disabled_reason")
            salvage: dict[str, Any] = {}
            if cache_chunks_skipped:
                salvage["cache_chunks_skipped"] = list(cache_chunks_skipped)
            if cache_skipped_reason:
                salvage["cache_skipped_reason"] = cache_skipped_reason
            if prewarm_disabled_reason:
                salvage["prewarm_disabled_reason"] = prewarm_disabled_reason
            shared["llm_usage"] = salvage

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle errors after all retries exhausted.

        Fires for ``LLMTransientError`` whose retry budget was exhausted
        AND any non-deterministic failure that escaped ``_call_llm``.
        Deterministic provider errors (``UnknownModelError``,
        ``MissingApiKeyError``, ``InvalidRequestError``) are caught and
        converted to error dicts at the ``_call_llm`` boundary, so they
        never reach this path.

        The timeout case keeps its specific "Increase timeout or check API
        connectivity" hint because that's the actionable remediation —
        without it, an agent retrying the workflow would just hit the same
        wall. Substring detection avoids re-importing ``litellm.exceptions``
        for what's already a string-typed concept across providers.
        """
        model = prep_res.get("model", "unknown")
        err_dict = _error_dict_for_generic_failure(model, exc, self.max_retries)
        # Task 159 C1.2 cross-layer co-edit (cache_chunks_skipped) — wrap at
        # the caller, not the builder. ``prep_res`` is this method's arg.
        err_dict["usage"]["cache_chunks_skipped"] = list(prep_res.get("__cache_chunks_skipped__", []))
        err_dict["usage"]["cache_skipped_reason"] = prep_res.get("__cache_skipped_reason__")
        err_dict["usage"]["prewarm_disabled_reason"] = prep_res.get("__prewarm_disabled_reason__")
        return err_dict
