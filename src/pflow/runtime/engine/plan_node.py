"""Shared primitive for deciding what would happen to a node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .instrumentation import (
    compute_config_hash,
    compute_node_config,
    in_process_cache_lookup,
    memo_cache_lookup,
)
from .template_resolution import resolve_templates
from .types import NodeConfig

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
    """Decide whether a node would hit cache or execute."""
    config_hash = compute_config_hash(
        compute_node_config(
            config.node_type_name,
            config.template_config.static_params if config.template_config else node.params,
            config.template_config.template_params if config.template_config else {},
            config.batch_config,
        )
    )

    resolved_params: dict[str, Any] | None = None
    last_resolutions: dict[str, Any] = {}
    template_errors: list[Any] = []

    if config.template_config and not config.batch_config:
        try:
            resolved_params, last_resolutions, template_errors = resolve_templates(
                config.template_config,
                shared,
                config.node_id,
            )
        except ValueError as exc:
            return NodePlan(
                status="miss",
                config_hash=config_hash,
                cache_key=None,
                resolved_params=None,
                cached_action=None,
                cached_output=None,
                last_resolutions=getattr(exc, "_pflow_partial_resolutions", None) or {},
                template_errors=[],
                template_exception=exc,
            )

    if not config.cache_enabled:
        return NodePlan(
            status="cache_disabled",
            config_hash=config_hash,
            cache_key=None,
            resolved_params=resolved_params,
            cached_action=None,
            cached_output=None,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
            template_exception=None,
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
        return NodePlan(
            status="cached_memo",
            config_hash=config_hash,
            cache_key=cache_key,
            resolved_params=resolved_params,
            cached_action=cached_action,
            cached_output=cached_output,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
            template_exception=None,
        )

    valid, cached_action = in_process_cache_lookup(config.node_id, config_hash, shared)
    if valid:
        return NodePlan(
            status="cached_in_process",
            config_hash=config_hash,
            cache_key=None,
            resolved_params=resolved_params,
            cached_action=cached_action,
            cached_output=None,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
            template_exception=None,
        )

    return NodePlan(
        status="miss",
        config_hash=config_hash,
        cache_key=cache_key,
        resolved_params=resolved_params,
        cached_action=None,
        cached_output=None,
        last_resolutions=last_resolutions,
        template_errors=template_errors,
        template_exception=None,
    )
