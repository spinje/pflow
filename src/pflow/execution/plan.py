"""Execution planner for --dry-run."""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from time import time
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import CompilationError
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from pflow.execution.result import Plan, PlanEntry, PlanSummary
from pflow.registry import Registry
from pflow.runtime.cache import MemoizationCache
from pflow.runtime.engine.instrumentation import apply_memo_hit
from pflow.runtime.engine.plan_node import plan_node
from pflow.runtime.engine.types import CompiledWorkflow, NodeConfig

logger = logging.getLogger(__name__)

_LLM_NODE_CLASSES: frozenset[str] = frozenset({"LLMNode", "ClaudeCodeNode"})
_MAX_SUB_WORKFLOW_DEPTH = 10


def build_plan(  # noqa: C901
    compiled: CompiledWorkflow,
    params: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    workflow_name: str = "<unnamed>",
    only_node: str | None = None,
    _visited_paths: list[str] | None = None,
    _depth: int = 0,
    _parent_workflow_file: str | None = None,
) -> Plan:
    """Build an execution plan for a compiled workflow."""
    if only_node is not None and _depth == 0 and only_node not in compiled.node_configs:
        available = sorted(compiled.node_configs.keys())
        raise CompilationError(
            f"Node '{only_node}' not found",
            phase="only_node_resolution",
            details={"available_nodes": available},
            suggestion=f"Available nodes: {', '.join(available)}",
        )

    visited_paths = list(_visited_paths) if _visited_paths else []

    shared: dict[str, Any] = {**params}
    shared.update(compiled.resolved_defaults)
    shared["__memoization_cache__"] = cache
    shared["__execution__"] = {
        "completed_nodes": [],
        "node_actions": {},
        "node_hashes": {},
        "failed_node": None,
        "node_visit_counts": {},
    }
    shared["__cache_hits__"] = []
    if _parent_workflow_file:
        shared["_pflow_workflow_file"] = _parent_workflow_file

    entries: list[PlanEntry] = []
    diagnostics: list[Diagnostic] = []
    visited_edges: set[tuple[str, str]] = set()
    first_miss_node_id: str | None = None
    cost_basis = "exact"

    curr = compiled.start_node
    while curr is not None:
        node_id = getattr(curr, "node_id", None)
        if node_id is None or node_id not in compiled.node_configs:
            logger.debug("Skipping node with missing node_id or config in plan walk")
            break

        config = compiled.node_configs[node_id]
        visit_counts = shared["__execution__"]["node_visit_counts"]
        visit_counts[node_id] = visit_counts.get(node_id, 0) + 1

        entry = _plan_one_node(
            curr,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=_depth,
            parent_workflow_file=_parent_workflow_file,
        )

        if entry.sub_plan is not None:
            diagnostics.extend(entry.sub_plan.diagnostics)
        if entry.diagnostic is not None:
            diagnostics.append(entry.diagnostic)

        entries.append(entry)

        if entry.status == "cached":
            action = entry.action or "default"
        elif entry.status == "sub_workflow" and entry.sub_plan is not None:
            child_summary = entry.sub_plan.summary
            child_has_work = child_summary.execute_count > 0 or (child_summary.execute_including_nested or 0) > 0
            if child_has_work:
                first_miss_node_id = node_id
            action = "default"
        elif entry.status == "opaque":
            first_miss_node_id = node_id
            action = "default"
        elif entry.status == "routing_error":
            break
        else:
            first_miss_node_id = node_id
            action = "default"

        if action == "end":
            break
        if curr.successors and all(name == "error" for name in curr.successors):
            break

        if entry.status == "cached" and action != "default" and action not in curr.successors:
            routing_diag = Diagnostic(
                severity=Severity.WARNING,
                message=(
                    f"Node '{node_id}' cached action '{action}' has no matching successor. "
                    f"Available: {list(curr.successors)}. At runtime the engine would fail "
                    "with a routing error — fix the workflow edges."
                ),
                node_id=node_id,
                source="planner",
                context={"category": "routing_error"},
            )
            entries.append(
                PlanEntry(
                    node_id=node_id,
                    node_type=_node_type_name(config),
                    status="routing_error",
                    cause="routing_error",
                    diagnostic=routing_diag,
                )
            )
            diagnostics.append(routing_diag)
            break

        if only_node is not None and first_miss_node_id == only_node:
            break

        if first_miss_node_id is not None:
            bfs_entries, bfs_flipped_basis = _bfs_downstream(
                boundary_node=curr,
                compiled=compiled,
                visited_nodes={entry.node_id for entry in entries if entry.sub_plan is None},
                visited_edges=visited_edges,
                only_node=only_node,
            )
            entries.extend(bfs_entries)
            if bfs_flipped_basis:
                cost_basis = "upper_bound"
            break

        edge = (node_id, action)
        if edge in visited_edges:
            break
        visited_edges.add(edge)
        curr = curr.successors.get(action)

        if only_node is not None and node_id == only_node:
            break

    summary = _summarize(entries, diagnostics, cost_basis=cost_basis)
    return Plan(
        workflow=workflow_name,
        entries=entries,
        summary=summary,
        diagnostics=diagnostics,
    )


def _bfs_downstream(  # noqa: C901
    *,
    boundary_node: Any,
    compiled: CompiledWorkflow,
    visited_nodes: set[str],
    visited_edges: set[tuple[str, str]],
    only_node: str | None,
) -> tuple[list[PlanEntry], bool]:
    """BFS over non-error successors starting from the boundary node."""
    entries: list[PlanEntry] = []
    flipped_basis = False
    queue: deque[Any] = deque()

    boundary_non_error = [(action, succ) for action, succ in boundary_node.successors.items() if action != "error"]
    if len(boundary_non_error) > 1:
        flipped_basis = True

    boundary_id = getattr(boundary_node, "node_id", None)
    for action, succ in boundary_non_error:
        if boundary_id is not None:
            edge = (boundary_id, action)
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
        queue.append(succ)

    while queue:
        node = queue.popleft()
        node_id = getattr(node, "node_id", None)
        if node_id is None or node_id in visited_nodes:
            continue
        visited_nodes.add(node_id)

        if node_id not in compiled.node_configs:
            continue
        config = compiled.node_configs[node_id]
        entries.append(
            PlanEntry(
                node_id=node_id,
                node_type=_node_type_name(config),
                status="execute",
                cause="downstream",
            )
        )

        if only_node is not None and node_id == only_node:
            break

        non_error_successors = [(action, succ) for action, succ in node.successors.items() if action != "error"]
        if len(non_error_successors) > 1:
            flipped_basis = True

        for action, succ in non_error_successors:
            edge = (node_id, action)
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
            queue.append(succ)

    return entries, flipped_basis


def _node_type_name(config: NodeConfig) -> str:
    """Get the user-facing node type for display and aggregation."""
    return config.node_type_name


def _plan_one_node(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    visited_paths: list[str],
    depth: int,
    parent_workflow_file: str | None,
) -> PlanEntry:
    """Plan a single node."""
    if config.node_type_name == "WorkflowExecutor":
        return _plan_sub_workflow(
            curr,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=depth,
            parent_workflow_file=parent_workflow_file,
        )
    return _plan_standard_node(curr, config, shared, cache)


def _plan_standard_node(  # noqa: C901
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
) -> PlanEntry:
    """Plan a non-WorkflowExecutor node."""
    plan = plan_node(curr, config, shared)

    if plan.template_exception is not None:
        attached_diag = getattr(plan.template_exception, "_pflow_template_diagnostic", None)
        if not isinstance(attached_diag, Diagnostic):
            attached_diag = Diagnostic(
                severity=Severity.WARNING,
                message=str(plan.template_exception),
                node_id=config.node_id,
                source="planner",
                context={"category": "template_error"},
            )
        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="execute",
            cause="template_error",
            diagnostic=attached_diag,
        )

    if plan.status == "cache_disabled":
        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="execute",
            cause="cache_disabled",
        )

    if plan.status == "cached_memo":
        if plan.cached_output is not None and plan.cached_action is not None:
            apply_memo_hit(
                config.node_id,
                shared,
                plan.cached_action,
                plan.cached_output,
                plan.config_hash,
            )

        age_sec: float | None = None
        if plan.cache_key is not None:
            with_age = cache.get_with_age(plan.cache_key)
            if with_age is not None:
                age_sec = time() - with_age[2]

        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="cached",
            cause="hash_match",
            action=plan.cached_action or "default",
            age_sec=age_sec,
        )

    if plan.status == "cached_in_process":
        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="cached",
            cause="hash_match",
            action=plan.cached_action or "default",
            age_sec=None,
        )

    last_cost, last_age = _lookup_last_cost(config, cache)
    permissive_diag: Diagnostic | None = None
    if plan.template_errors:
        last_err = plan.template_errors[-1]
        attached = last_err.get("diagnostic") if isinstance(last_err, dict) else None
        if isinstance(attached, Diagnostic):
            permissive_diag = attached

    return PlanEntry(
        node_id=config.node_id,
        node_type=_node_type_name(config),
        status="execute",
        cause="template_error" if permissive_diag is not None else "no_cache_match",
        last_cost_usd=last_cost,
        last_run_age_sec=last_age,
        diagnostic=permissive_diag,
    )


def _plan_sub_workflow(  # noqa: C901
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    visited_paths: list[str],
    depth: int,
    parent_workflow_file: str | None,
) -> PlanEntry:
    """Compile and recursively plan a sub-workflow."""
    node_id = config.node_id
    node_type = _node_type_name(config)

    if depth >= _MAX_SUB_WORKFLOW_DEPTH:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity=Severity.WARNING,
                message=f"Max sub-workflow depth {_MAX_SUB_WORKFLOW_DEPTH} exceeded at '{node_id}'",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )

    workflow_ref = None
    if config.template_config:
        workflow_ref = config.template_config.template_params.get("workflow")
        if workflow_ref is None:
            workflow_ref = config.template_config.static_params.get("workflow")
    if workflow_ref is None:
        workflow_ref = curr.params.get("workflow") if hasattr(curr, "params") else None

    if isinstance(workflow_ref, str) and "${" in workflow_ref:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="opaque",
            cause="dynamic",
        )

    plan = plan_node(curr, config, shared)
    if plan.template_exception is not None:
        attached_diag = getattr(plan.template_exception, "_pflow_template_diagnostic", None)
        if not isinstance(attached_diag, Diagnostic):
            attached_diag = Diagnostic(
                severity=Severity.WARNING,
                message=str(plan.template_exception),
                node_id=node_id,
                source="planner",
                context={"category": "template_error"},
            )
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=attached_diag,
        )

    merged: dict[str, Any] = {}
    if config.template_config:
        merged.update(config.template_config.static_params or {})
    if plan.resolved_params:
        merged.update(plan.resolved_params)

    base_path = Path(parent_workflow_file).parent if parent_workflow_file else None
    try:
        resolved = resolve_sub_workflow(merged, base_path=base_path)
    except _SUB_WORKFLOW_RESOLVE_EXCEPTIONS as exc:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity=Severity.WARNING,
                message=f"Sub-workflow resolve failed: {exc}",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )

    if resolved is None:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="opaque",
            cause="dynamic",
        )

    resolved_path_str = str(resolved.path.resolve()) if resolved.path else None
    if resolved_path_str and resolved_path_str in visited_paths:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity=Severity.WARNING,
                message=f"Circular sub-workflow reference: {resolved_path_str}",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )

    raw_inputs = merged.get("inputs")
    if raw_inputs is not None and not isinstance(raw_inputs, dict):
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity=Severity.WARNING,
                message=f"Workflow node 'inputs:' resolved to {type(raw_inputs).__name__}, expected dict",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )
    child_inputs = dict(raw_inputs) if raw_inputs else {}

    child_initial_params = dict(child_inputs)
    if resolved.path:
        child_initial_params["_pflow_workflow_file"] = resolved_path_str

    try:
        from pflow.runtime.compilation.compiler import compile_workflow

        compiled_child = compile_workflow(
            resolved.ir,
            registry=registry,
            initial_params=child_initial_params,
        )
    except _CHILD_COMPILE_EXCEPTIONS as exc:
        child_diags = _safe_to_diagnostics(exc)
        primary = (
            child_diags[0]
            if child_diags
            else Diagnostic(
                severity=Severity.ERROR,
                message=f"Sub-workflow compile failed: {exc}",
                node_id=node_id,
                source="planner",
                context={"category": "compilation"},
            )
        )
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=primary,
        )

    workflow_ref_for_name = merged.get("workflow") or "<sub-workflow>"
    child_plan = build_plan(
        compiled_child,
        child_inputs,
        cache,
        registry,
        workflow_name=str(workflow_ref_for_name),
        _visited_paths=[*visited_paths, resolved_path_str] if resolved_path_str else visited_paths,
        _depth=depth + 1,
        _parent_workflow_file=resolved_path_str,
    )

    if resolved.warnings:
        child_plan = Plan(
            workflow=child_plan.workflow,
            entries=child_plan.entries,
            summary=child_plan.summary,
            diagnostics=[*child_plan.diagnostics, *resolved.warnings],
        )

    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="sub_workflow",
        cause="no_cache_match",
        sub_plan=child_plan,
    )


def _build_sub_workflow_exception_tuples() -> tuple[tuple[type[BaseException], ...], tuple[type[BaseException], ...]]:
    """Build the exception tuples used by _plan_sub_workflow."""
    from pflow.core.exceptions import (
        CompilationError as CoreCompilationError,
    )
    from pflow.core.exceptions import (
        MarkdownParseError,
        SchemaValidationError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    )

    resolve_excs = (FileNotFoundError, ValueError, MarkdownParseError, WorkflowNotFoundError)
    compile_excs = (
        CoreCompilationError,
        WorkflowValidationError,
        MarkdownParseError,
        SchemaValidationError,
    )
    return resolve_excs, compile_excs


_SUB_WORKFLOW_RESOLVE_EXCEPTIONS, _CHILD_COMPILE_EXCEPTIONS = _build_sub_workflow_exception_tuples()


def _safe_to_diagnostics(exc: BaseException) -> list[Diagnostic]:
    """Safely extract Diagnostics from an exception with to_diagnostics()."""
    if not hasattr(exc, "to_diagnostics"):
        return []
    try:
        diagnostics = exc.to_diagnostics()
    except Exception:
        return []
    return [diagnostic for diagnostic in diagnostics if isinstance(diagnostic, Diagnostic)]


def _lookup_last_cost(config: NodeConfig, cache: MemoizationCache) -> tuple[float | None, float | None]:
    """Look up the most recent historical cost for an LLM-family node."""
    if config.node_type_name not in _LLM_NODE_CLASSES:
        return None, None

    latest = cache.get_latest_for_node(config.node_id)
    if latest is None:
        return None, None

    output, created_at = latest
    llm_usage = output.get("llm_usage") if isinstance(output, dict) else None
    if not isinstance(llm_usage, dict):
        return None, None

    cost = llm_usage.get("cost_usd")
    if not isinstance(cost, (int, float)):
        return None, None

    return float(cost), time() - created_at


def _summarize(  # noqa: C901
    entries: list[PlanEntry],
    diagnostics: list[Diagnostic],
    *,
    cost_basis: str = "exact",
) -> PlanSummary:
    """Aggregate per-level counts plus nested aggregation if needed."""
    del diagnostics

    total = len(entries)
    cached_count = sum(1 for entry in entries if entry.status == "cached")

    def _is_executing(entry: PlanEntry) -> bool:
        if entry.status in ("execute", "opaque"):
            return True
        if entry.status == "sub_workflow" and entry.sub_plan is not None:
            summary = entry.sub_plan.summary
            return summary.execute_count > 0 or (summary.execute_including_nested or 0) > 0
        return False

    execute_count = sum(1 for entry in entries if _is_executing(entry))

    cache_boundary: str | None = None
    for entry in entries:
        if _is_executing(entry) and entry.cause != "downstream":
            cache_boundary = entry.node_id
            break

    execute_by_type: dict[str, int] = {}
    for entry in entries:
        if _is_executing(entry):
            execute_by_type[entry.node_type] = execute_by_type.get(entry.node_type, 0) + 1

    estimated_cost_usd = sum(entry.last_cost_usd for entry in entries if entry.last_cost_usd is not None)
    nodes_without_history = sum(
        1
        for entry in entries
        if entry.status == "execute" and entry.node_type in _LLM_NODE_CLASSES and entry.last_cost_usd is None
    )

    has_nested = any(entry.sub_plan is not None for entry in entries)
    total_nested: int | None = None
    cached_nested: int | None = None
    execute_nested: int | None = None
    cost_nested: float | None = None
    nwh_nested: int | None = None
    effective_cost_basis = cost_basis

    if has_nested:
        total_nested = total
        cached_nested = cached_count
        execute_nested = execute_count
        cost_nested = estimated_cost_usd
        nwh_nested = nodes_without_history
        for entry in entries:
            if entry.sub_plan is None:
                continue
            child = entry.sub_plan.summary
            total_nested += child.total_including_nested if child.total_including_nested is not None else child.total
            cached_nested += (
                child.cached_including_nested if child.cached_including_nested is not None else child.cached_count
            )
            execute_nested += (
                child.execute_including_nested if child.execute_including_nested is not None else child.execute_count
            )
            cost_nested += (
                child.estimated_cost_usd_including_nested
                if child.estimated_cost_usd_including_nested is not None
                else child.estimated_cost_usd
            )
            nwh_nested += (
                child.nodes_without_history_including_nested
                if child.nodes_without_history_including_nested is not None
                else child.nodes_without_history
            )
            if child.cost_basis == "upper_bound":
                effective_cost_basis = "upper_bound"

    return PlanSummary(
        total=total,
        cached_count=cached_count,
        execute_count=execute_count,
        cache_boundary=cache_boundary,
        execute_by_type=execute_by_type,
        estimated_cost_usd=estimated_cost_usd,
        nodes_without_history=nodes_without_history,
        cost_basis=effective_cost_basis,
        total_including_nested=total_nested,
        cached_including_nested=cached_nested,
        execute_including_nested=execute_nested,
        estimated_cost_usd_including_nested=cost_nested,
        nodes_without_history_including_nested=nwh_nested,
    )
