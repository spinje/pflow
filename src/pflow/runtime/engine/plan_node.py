"""Shared primitive for deciding what would happen to a node."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from pflow.core.cache_render import (
    CacheRenderContext,
    _ChunkAbsentSentinel,
    _resolve_chunk_value,
)

from .instrumentation import (
    compute_config_hash,
    compute_node_config,
    in_process_cache_lookup,
    memo_cache_lookup,
)
from .template_resolution import resolve_templates
from .types import NodeConfig

logger = logging.getLogger(__name__)

NodePlanStatus = Literal["cached_memo", "cached_in_process", "miss", "cache_disabled"]


@dataclass(frozen=True)
class NodePlan:
    """Result of evaluating a node without executing it."""

    status: NodePlanStatus
    config_hash: str
    cache_key: str | None
    resolved_params: dict[str, Any] | None
    cached_action: str | None
    cached_output: dict[str, Any] | None
    last_resolutions: dict[str, Any]
    template_errors: list[Any]
    template_exception: BaseException | None


def plan_node(node: Any, config: NodeConfig, shared: dict[str, Any]) -> NodePlan:
    """Decide whether a node would hit cache or execute.

    Task 159 B3.3: template resolution runs BEFORE config hash so the cache
    rendering helper can resolve ``${var}`` references in cache chunks
    against ``shared``. The hash includes the rendered ``prompt_cache``
    content (conditionally — opt-out nodes hash byte-identically to pre-task
    behavior; DD#19). On a strict-mode template-resolution failure, the
    config hash is still computed (without cache content) for trace fidelity,
    matching pre-task behavior.
    """
    resolved_params, last_resolutions, template_errors, template_exc = _resolve_for_plan(node, config, shared)
    prompt_cache_content = None if template_exc is not None else _render_cache_for_hash(config, shared)
    config_hash = compute_config_hash(
        compute_node_config(
            config.node_type_name,
            config.template_config.static_params if config.template_config else node.params,
            config.template_config.template_params if config.template_config else {},
            config.batch_config,
            prompt_cache_content=prompt_cache_content,
        )
    )
    if template_exc is not None:
        return _miss_with_template_error(config_hash, template_exc, last_resolutions)

    if not config.cache_enabled:
        return _make_plan(
            "cache_disabled",
            config_hash=config_hash,
            resolved_params=resolved_params,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
        )

    visit_counts = shared.get("__execution__", {}).get("node_visit_counts", {})
    hit, cache_key, cached_data = memo_cache_lookup(
        config.node_id,
        config.node_type_name,
        config_hash,
        config.batch_config,
        shared,
        visit_counts,
        resolved_params=resolved_params,
    )
    if hit and cached_data is not None:
        cached_action, cached_output = cached_data
        return _make_plan(
            "cached_memo",
            config_hash=config_hash,
            cache_key=cache_key,
            resolved_params=resolved_params,
            cached_action=cached_action,
            cached_output=cached_output,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
        )

    valid, cached_action = in_process_cache_lookup(config.node_id, config_hash, shared)
    if valid:
        return _make_plan(
            "cached_in_process",
            config_hash=config_hash,
            resolved_params=resolved_params,
            cached_action=cached_action,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
        )

    return _make_plan(
        "miss",
        config_hash=config_hash,
        cache_key=cache_key,
        resolved_params=resolved_params,
        last_resolutions=last_resolutions,
        template_errors=template_errors,
    )


def _resolve_for_plan(
    node: Any,
    config: NodeConfig,
    shared: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[Any], BaseException | None]:
    """Resolve templates for non-batch nodes; capture strict-mode failures.

    Batch nodes return ``(None, {}, [], None)`` because per-item resolution
    happens later in the batch executor. Strict-mode ``ValueError`` is caught
    so the caller can return a ``miss`` plan that surfaces the error path.
    """
    if not (config.template_config and not config.batch_config):
        return None, {}, [], None
    try:
        resolved_params, last_resolutions, template_errors = resolve_templates(
            config.template_config,
            shared,
            config.node_id,
        )
        return resolved_params, last_resolutions, template_errors, None
    except ValueError as exc:
        return None, getattr(exc, "_pflow_partial_resolutions", None) or {}, [], exc


def _render_cache_for_hash(config: NodeConfig, shared: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Render the prompt-cache subset for this node, if any.

    Returns ``None`` (so ``compute_node_config`` skips the conditional
    inclusion and produces a byte-identical hash to pre-task behavior) when
    the node has no cache opt-in. Returns a list of
    ``{"name", "prose", "value"}`` dicts in declaration order, with ABSENT
    chunks filtered (per the ``_CHUNK_ABSENT`` sentinel contract).

    Resolves chunk values against ``shared`` directly — cache chunks are
    validated as non-batch references at parse time (B2.3), so they can
    resolve from upstream node outputs even on the batch-node hash path
    (where ``resolved_params`` is ``None``).
    """
    cache_ctx = _read_cache_context(shared, config.node_id)
    if cache_ctx is None or not cache_ctx.subset or cache_ctx.cache_block is None:
        return None
    chunks_by_name = {c.name: c for c in cache_ctx.cache_block.items}
    rendered: list[dict[str, Any]] = []
    for name in cache_ctx.subset:
        chunk = chunks_by_name.get(name)
        if chunk is None:
            # Validator catches undeclared subset entries (Segment 1 B2.3).
            # Log when defense fires so bypass scenarios (direct
            # compile_workflow without WorkflowValidator) are observable
            # rather than silently producing a no-opt-in hash for a node
            # that declared a subset.
            logger.warning(
                "cache rendering skipped undeclared chunk '%s' for node '%s' — "
                "subset entry has no matching item in the workflow's ## Cache block; "
                "validator should have rejected this (B2.3). The skip prevents a crash "
                "but the resulting hash will exclude the chunk's content.",
                name,
                config.node_id,
            )
            continue
        value = _resolve_chunk_value(chunk, shared)
        if isinstance(value, _ChunkAbsentSentinel):
            continue
        rendered.append({"name": name, "prose": chunk.prose_before, "value": value})
    return rendered or None


def _read_cache_context(shared: dict[str, Any], node_id: str) -> CacheRenderContext | None:
    """Canonical defensive read of ``shared["__pflow_cache_render__"]``."""
    return (shared.get("__pflow_cache_render__") or {}).get(node_id)


def _make_plan(
    status: NodePlanStatus,
    *,
    config_hash: str,
    cache_key: str | None = None,
    resolved_params: dict[str, Any] | None = None,
    cached_action: str | None = None,
    cached_output: dict[str, Any] | None = None,
    last_resolutions: dict[str, Any] | None = None,
    template_errors: list[Any] | None = None,
) -> NodePlan:
    """Build a NodePlan with sensible defaults for the absent fields."""
    return NodePlan(
        status=status,
        config_hash=config_hash,
        cache_key=cache_key,
        resolved_params=resolved_params,
        cached_action=cached_action,
        cached_output=cached_output,
        last_resolutions=last_resolutions or {},
        template_errors=template_errors or [],
        template_exception=None,
    )


def _miss_with_template_error(
    config_hash: str,
    exc: BaseException,
    last_resolutions: dict[str, Any],
) -> NodePlan:
    """Plan returned when strict-mode template resolution failed.

    Hash is still computed (over raw template strings) so trace records
    carry useful identity info on the failure path. Cache content is NOT
    included in the hash on this path — workflows that fail at resolution
    don't materialize cache content, so including it would inflate the hash
    space unnecessarily.
    """
    return NodePlan(
        status="miss",
        config_hash=config_hash,
        cache_key=None,
        resolved_params=None,
        cached_action=None,
        cached_output=None,
        last_resolutions=last_resolutions,
        template_errors=[],
        template_exception=exc,
    )
