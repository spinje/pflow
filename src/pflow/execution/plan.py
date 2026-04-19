"""Execution planner for --dry-run.

Walks a compiled workflow graph and produces a typed `Plan` describing what
would happen at runtime — which nodes serve from cache, which would execute,
historical cost for LLM nodes, sub-workflow recursion — without invoking any
node side effects.

Paired with `runtime/engine/plan_node.py`: the engine and the planner both
call `plan_node()` so cache-key / template-resolution semantics cannot drift.
Parity is pinned by `tests/test_execution/test_plan_drift.py`.

INVARIANTS (non-obvious — read before modifying):
- The scratch `shared` dict the planner constructs is planner-owned.
  `apply_memo_hit` must mutate it on memo hits so downstream template
  resolution matches the engine's cache-key computation. Skipping the
  mutation looks "purer" but causes silent drift.
- `enforce_loop_guard()` must run BEFORE each `plan_node()` call — same
  primitive the engine uses. It bumps visit_counts AND invalidates
  `completed_nodes`/`node_actions`/`node_hashes` for a revisited node.
  Without the invalidation, visit 2 of a successfully-cached node in a
  loop is reported as `cached_in_process` when the engine would re-execute.
- Post-first-miss: BFS over ALL non-"error" successors. Following only
  `default` underestimates cost for conditional workflows, which is the
  wrong failure mode for a cost gate.
- A cached entry whose action has no matching successor = runtime routing
  error. Surface as a plan entry and stop — the engine would fail here too.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from time import time
from typing import Any, Literal

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import CompilationError
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from pflow.execution.result import Plan, PlanEntry, PlanSummary
from pflow.registry import Registry
from pflow.runtime.cache import MemoizationCache
from pflow.runtime.engine.instrumentation import apply_memo_hit, enforce_loop_guard
from pflow.runtime.engine.plan_node import NodePlan, plan_node
from pflow.runtime.engine.types import CompiledWorkflow, NodeConfig

logger = logging.getLogger(__name__)

_LLM_NODE_CLASSES: frozenset[str] = frozenset({"LLMNode", "ClaudeCodeNode"})
_MAX_SUB_WORKFLOW_DEPTH = 10

_CostBasis = Literal["upper_bound", "exact"]


@dataclass
class _WalkerState:
    """Mutable state threaded through the walker's per-iteration dispatch.

    Pass-by-reference replaces the 10-arg `_advance` signature. Every
    field is planner-owned; mutating them is the walker's job.
    """

    entries: list[PlanEntry]
    diagnostics: list[Diagnostic]
    visited_edges: set[tuple[str, str]]
    only_node: str | None
    workflow_path: str | None = None
    cost_basis: _CostBasis = "exact"


class _ChildCompileFailed(Exception):
    """Internal signal: child workflow failed to compile at plan time.

    Carries the pre-built PlanEntry the caller should return. Used instead
    of a `CompiledWorkflow | PlanEntry` sum type so callers don't need
    `isinstance` checks. Never raised across the public boundary.
    """

    def __init__(self, entry: PlanEntry) -> None:
        super().__init__()
        self.entry = entry


# ──────────────────────────────────────────────────────────────────────────────
# Walker state machine
# ──────────────────────────────────────────────────────────────────────────────


class Transition(Enum):
    """Walker's next move after planning a single node."""

    FOLLOW = auto()  # advance to the successor on `action`
    STOP = auto()  # clean termination (end / all-error / revisited edge)
    BOUNDARY = auto()  # first would-execute node; BFS downstream then stop
    ROUTING_ERROR = auto()  # cached action has no matching successor; emit + stop


@dataclass(frozen=True)
class Decision:
    """Walker's decision for one planned entry."""

    kind: Transition
    action: str = "default"


def _classify(entry: PlanEntry, curr: Any) -> Decision:
    """Map a planned entry + current graph node to a walker transition.

    Mirrors engine semantics from `engine.run()` / `_handle_no_successor`:
    the engine does `successors.get(action)` without fallback, then treats
    `"end"` and all-error-successors as clean termination and any other
    no-match as a routing failure. This function is the one place where
    status → transition is expressed.
    """
    if entry.status == "routing_error":
        return Decision(Transition.STOP)

    action = entry.action if entry.status == "cached" and entry.action else "default"

    # Action matches a successor → walker advances through that edge.
    if action in curr.successors:
        if _represents_work(entry):
            return Decision(Transition.BOUNDARY, action)
        return Decision(Transition.FOLLOW, action)

    # No matching successor. Mirror engine's `_handle_no_successor`:
    # "end" sentinel and all-error-successors are clean termination.
    if action == "end" or all(name == "error" for name in curr.successors):
        return Decision(Transition.STOP, action)

    # Cached node routed an action that doesn't name any successor →
    # engine would mark_node_failed(FAILURE_CATEGORY_ROUTING) at runtime.
    if entry.status == "cached":
        return Decision(Transition.ROUTING_ERROR, action)

    # Execute with no matching successor — still a boundary so BFS
    # enumerates the reachable non-error successors (if any).
    if _represents_work(entry):
        return Decision(Transition.BOUNDARY, action)

    return Decision(Transition.STOP, action)


def _represents_work(entry: PlanEntry) -> bool:
    """Whether an entry means the engine would actually execute something.

    Shared by `_classify` (for boundary detection) and `_summarize`
    (for execute_count / cache_boundary). Single source of truth.
    """
    if entry.status in ("execute", "opaque"):
        return True
    if entry.status == "sub_workflow" and entry.sub_plan is not None:
        child = entry.sub_plan.summary
        return child.execute_count > 0 or (child.execute_including_nested or 0) > 0
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Main walker
# ──────────────────────────────────────────────────────────────────────────────


def build_plan(
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
    plan, _shared = _build_plan_with_shared(
        compiled,
        params,
        cache,
        registry,
        workflow_name=workflow_name,
        only_node=only_node,
        _visited_paths=_visited_paths,
        _depth=_depth,
        _parent_workflow_file=_parent_workflow_file,
    )
    return plan


def _build_plan_with_shared(
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
) -> tuple[Plan, dict[str, Any]]:
    """Internal variant of `build_plan` that also exposes the scratch shared.

    `_plan_sub_workflow` calls this to access the child's post-walk shared
    state, which has cached outputs populated via `apply_memo_hit`. Those
    values drive exact resolution of the child's declared `## Outputs`
    templates — matching what runtime does when a sub-workflow completes.
    """
    _validate_only_target(compiled, only_node, _depth)

    shared = _create_planner_shared(compiled, params, cache, _parent_workflow_file)
    visited_paths = list(_visited_paths) if _visited_paths else []
    state = _WalkerState(
        entries=[],
        diagnostics=[],
        visited_edges=set(),
        only_node=only_node,
        workflow_path=shared.get("_pflow_workflow_file"),
    )

    curr = compiled.start_node
    while curr is not None:
        node_id = getattr(curr, "node_id", None)
        if not isinstance(node_id, str) or node_id not in compiled.node_configs:
            logger.debug("Skipping node with missing node_id or config in plan walk")
            break
        config = compiled.node_configs[node_id]

        enforce_loop_guard(node_id, shared)

        entry = _plan_one_node(
            curr,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=_depth,
        )
        state.entries.append(entry)
        if entry.sub_plan is not None:
            state.diagnostics.extend(entry.sub_plan.diagnostics)
        if entry.diagnostic is not None:
            state.diagnostics.append(entry.diagnostic)

        curr = _advance(
            decision=_classify(entry, curr),
            curr=curr,
            node_id=node_id,
            config=config,
            compiled=compiled,
            cache=cache,
            state=state,
        )

    plan = Plan(
        workflow=workflow_name,
        entries=state.entries,
        summary=_summarize(state.entries, cost_basis=state.cost_basis),
        diagnostics=state.diagnostics,
    )
    return plan, shared


def _advance(
    *,
    decision: Decision,
    curr: Any,
    node_id: str,
    config: NodeConfig,
    compiled: CompiledWorkflow,
    cache: MemoizationCache,
    state: _WalkerState,
) -> Any | None:
    """Apply the walker decision by mutating `state`; return the next node or None.

    `None` means the walker should stop. This is the ONLY place where walker
    transitions are acted on — the main loop in `build_plan` never branches
    on `Transition` itself.
    """
    match decision.kind:
        case Transition.STOP:
            return None
        case Transition.ROUTING_ERROR:
            routing_entry, routing_diag = _routing_error_entry(node_id, config, decision.action, curr.successors)
            state.entries.append(routing_entry)
            state.diagnostics.append(routing_diag)
            return None
        case Transition.BOUNDARY:
            _apply_boundary(curr, compiled, cache, node_id, state)
            return None
        case Transition.FOLLOW:
            return _apply_follow(curr, node_id, decision.action, state)
        case _:
            raise AssertionError(f"unhandled walker transition: {decision.kind!r}")


def _apply_boundary(
    curr: Any,
    compiled: CompiledWorkflow,
    cache: MemoizationCache,
    node_id: str,
    state: _WalkerState,
) -> None:
    """Run BFS downstream from the boundary node; update `state` in place."""
    if state.only_node is not None and node_id == state.only_node:
        return
    bfs_entries, branched = _bfs_downstream(
        boundary_node=curr,
        compiled=compiled,
        cache=cache,
        visited_nodes={e.node_id for e in state.entries if e.sub_plan is None},
        visited_edges=state.visited_edges,
        only_node=state.only_node,
        workflow_path=state.workflow_path,
    )
    state.entries.extend(bfs_entries)
    if branched:
        state.cost_basis = "upper_bound"


def _apply_follow(
    curr: Any,
    node_id: str,
    action: str,
    state: _WalkerState,
) -> Any | None:
    """Return the next node to walk, or None to stop (only-target / revisit)."""
    if state.only_node is not None and node_id == state.only_node:
        return None
    edge = (node_id, action)
    if edge in state.visited_edges:
        return None
    state.visited_edges.add(edge)
    return curr.successors.get(action)


def _validate_only_target(compiled: CompiledWorkflow, only_node: str | None, depth: int) -> None:
    """Hard-error when --only names a node that doesn't exist (top level only)."""
    if only_node is None or depth != 0 or only_node in compiled.node_configs:
        return
    available = sorted(compiled.node_configs.keys())
    raise CompilationError(
        f"Node '{only_node}' not found",
        phase="only_node_resolution",
        details={"available_nodes": available},
        suggestion=f"Available nodes: {', '.join(available)}",
    )


def _create_planner_shared(
    compiled: CompiledWorkflow,
    params: dict[str, Any],
    cache: MemoizationCache,
    parent_workflow_file: str | None,
) -> dict[str, Any]:
    """Build the planner-owned scratch shared store.

    Matches the shape the engine expects under `__execution__`, so
    `plan_node()` and `apply_memo_hit()` can operate on it without
    special-casing.
    """
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
    if parent_workflow_file:
        shared["_pflow_workflow_file"] = parent_workflow_file
    return shared


def _routing_error_entry(
    node_id: str,
    config: NodeConfig,
    action: str,
    successors: dict[str, Any],
) -> tuple[PlanEntry, Diagnostic]:
    """Build the entry + diagnostic pair for a cached-action/no-successor mismatch."""
    diag = Diagnostic(
        severity=Severity.WARNING,
        message=(
            f"Node '{node_id}' cached action '{action}' has no matching successor. "
            f"Available: {list(successors)}. At runtime the engine would fail "
            "with a routing error — fix the workflow edges."
        ),
        node_id=node_id,
        source="planner",
        context={"category": "routing_error"},
    )
    entry = PlanEntry(
        node_id=node_id,
        node_type=config.node_type_name,
        status="routing_error",
        cause="routing_error",
        diagnostic=diag,
    )
    return entry, diag


# ──────────────────────────────────────────────────────────────────────────────
# Post-boundary BFS
# ──────────────────────────────────────────────────────────────────────────────


def _bfs_downstream(
    *,
    boundary_node: Any,
    compiled: CompiledWorkflow,
    cache: MemoizationCache,
    visited_nodes: set[str],
    visited_edges: set[tuple[str, str]],
    only_node: str | None,
    workflow_path: str | None = None,
) -> tuple[list[PlanEntry], bool]:
    """Enumerate reachable would-execute nodes after the first cache miss.

    Walks non-"error" outgoing edges breadth-first. Returns the discovered
    entries plus a `branched` flag — true when any traversed node had more
    than one non-error successor, which flips the plan's cost_basis to
    upper_bound (conservative for cost gating).
    """
    entries: list[PlanEntry] = []
    queue: deque[Any] = deque()
    branched = _seed_bfs(boundary_node, queue, visited_edges)

    while queue:
        node = queue.popleft()
        entry = _make_downstream_entry(node, compiled, cache, visited_nodes, workflow_path=workflow_path)
        if entry is None:
            continue
        entries.append(entry)
        if only_node is not None and entry.node_id == only_node:
            break
        if _enqueue_non_error_successors(node, queue, visited_edges):
            branched = True

    return entries, branched


def _seed_bfs(
    boundary_node: Any,
    queue: deque[Any],
    visited_edges: set[tuple[str, str]],
) -> bool:
    """Push boundary's non-error successors onto the BFS queue; return branched flag."""
    successors = _non_error_successors(boundary_node)
    boundary_id = getattr(boundary_node, "node_id", None)
    for action, successor in successors:
        if isinstance(boundary_id, str):
            edge = (boundary_id, action)
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
        queue.append(successor)
    return len(successors) > 1


def _make_downstream_entry(
    node: Any,
    compiled: CompiledWorkflow,
    cache: MemoizationCache,
    visited_nodes: set[str],
    *,
    workflow_path: str | None = None,
) -> PlanEntry | None:
    """Build a downstream PlanEntry for a BFS-discovered node, or None to skip it.

    Downstream entries go through `_execute_entry` so historical stats (cost
    + duration) are attached by construction. Skipping the stats lookup here
    was a real bug — agents cost-gating on an LLM node that happened to sit
    downstream of a non-LLM miss saw `$0` even when history existed.
    """
    node_id = getattr(node, "node_id", None)
    if not isinstance(node_id, str) or node_id in visited_nodes:
        return None
    if node_id not in compiled.node_configs:
        return None
    visited_nodes.add(node_id)
    config = compiled.node_configs[node_id]
    return _execute_entry(config, cache, cause="downstream", workflow_path=workflow_path)


def _enqueue_non_error_successors(
    node: Any,
    queue: deque[Any],
    visited_edges: set[tuple[str, str]],
) -> bool:
    """Enqueue a node's non-error successors; return True when it branched (>1)."""
    successors = _non_error_successors(node)
    node_id = getattr(node, "node_id", None)
    if not isinstance(node_id, str):
        return len(successors) > 1
    for action, successor in successors:
        edge = (node_id, action)
        if edge in visited_edges:
            continue
        visited_edges.add(edge)
        queue.append(successor)
    return len(successors) > 1


def _non_error_successors(node: Any) -> list[tuple[str, Any]]:
    """Return a node's successors excluding on-error handlers."""
    return [(action, successor) for action, successor in node.successors.items() if action != "error"]


# ──────────────────────────────────────────────────────────────────────────────
# Per-node planning dispatch
# ──────────────────────────────────────────────────────────────────────────────


def _plan_one_node(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    visited_paths: list[str],
    depth: int,
) -> PlanEntry:
    """Plan a single node, dispatching on WorkflowExecutor vs standard."""
    if config.node_type_name == "WorkflowExecutor":
        return _plan_sub_workflow(
            curr,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=depth,
        )
    return _plan_standard_node(curr, config, shared, cache)


def _plan_standard_node(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
) -> PlanEntry:
    """Plan a non-sub-workflow node via the shared `plan_node` primitive."""
    planned = plan_node(curr, config, shared)

    workflow_path = shared.get("_pflow_workflow_file")
    if planned.template_exception is not None:
        return _template_error_entry(config, planned.template_exception)
    if planned.status == "cache_disabled":
        return _cache_disabled_entry(config, cache, workflow_path)
    if planned.status == "cached_memo":
        return _cached_memo_entry(config, planned, shared, cache)
    if planned.status == "cached_in_process":
        return _cached_in_process_entry(config, planned)
    return _miss_entry(config, planned, cache, workflow_path=workflow_path)


# ──────────────────────────────────────────────────────────────────────────────
# PlanEntry builders (one per status)
# ──────────────────────────────────────────────────────────────────────────────


def _template_error_entry(config: NodeConfig, exc: BaseException) -> PlanEntry:
    """Entry for a strict-mode template resolution failure at planning time.

    Severity is ERROR: the runtime would raise here. `_display_plan_result`
    uses diagnostic severity to decide the CLI exit code — matching
    `validate()`'s `len(errors) == 0` convention.
    """
    attached = getattr(exc, "_pflow_template_diagnostic", None)
    if not isinstance(attached, Diagnostic):
        attached = Diagnostic(
            severity=Severity.ERROR,
            message=str(exc),
            node_id=config.node_id,
            source="planner",
            context={"category": "template_error"},
        )
    return PlanEntry(
        node_id=config.node_id,
        node_type=config.node_type_name,
        status="execute",
        cause="template_error",
        diagnostic=attached,
    )


def _cache_disabled_entry(
    config: NodeConfig,
    cache: MemoizationCache,
    workflow_path: str | None,
) -> PlanEntry:
    """Entry for a node with `cache: false` — always runs.

    Routes through `_execute_entry` so historical cost/duration estimates
    from prior runs are attached. `cache: false` means "don't use the cache
    for hit decisions"; it does NOT mean "hide history from the agent".
    """
    return _execute_entry(config, cache, cause="cache_disabled", workflow_path=workflow_path)


def _cached_memo_entry(
    config: NodeConfig,
    planned: NodePlan,
    shared: dict[str, Any],
    cache: MemoizationCache,
) -> PlanEntry:
    """Entry for a memo-cache hit; applies the engine's on-hit shared mutations."""
    if planned.cached_output is not None and planned.cached_action is not None:
        apply_memo_hit(
            config.node_id,
            shared,
            planned.cached_action,
            planned.cached_output,
            planned.config_hash,
        )
    return PlanEntry(
        node_id=config.node_id,
        node_type=config.node_type_name,
        status="cached",
        cause="hash_match",
        action=planned.cached_action or "default",
        age_sec=_cache_age(planned.cache_key, cache),
    )


def _cached_in_process_entry(config: NodeConfig, planned: NodePlan) -> PlanEntry:
    """Entry for an in-process cache hit (node already succeeded this run)."""
    return PlanEntry(
        node_id=config.node_id,
        node_type=config.node_type_name,
        status="cached",
        cause="hash_match",
        action=planned.cached_action or "default",
        age_sec=None,
    )


def _execute_entry(
    config: NodeConfig,
    cache: MemoizationCache,
    *,
    cause: Literal["no_cache_match", "downstream", "template_error", "cache_disabled"],
    diagnostic: Diagnostic | None = None,
    workflow_path: str | None = None,
) -> PlanEntry:
    """Single source of truth for `status="execute"` PlanEntry construction.

    Every would-execute entry — first-miss OR BFS-downstream — flows through
    here, so historical stats lookup is guaranteed by construction. Callers
    used to diverge (only `_miss_entry` attached cost; `_make_downstream_entry`
    did not), causing agents cost-gating on downstream LLM nodes to see `$0`.
    This primitive eliminates the drift surface.
    """
    last_cost, last_duration, last_age = _lookup_last_run_stats(config, cache, workflow_path=workflow_path)
    return PlanEntry(
        node_id=config.node_id,
        node_type=config.node_type_name,
        status="execute",
        cause=cause,
        last_cost_usd=last_cost,
        last_duration_ms=last_duration,
        last_run_age_sec=last_age,
        diagnostic=diagnostic,
    )


def _miss_entry(
    config: NodeConfig,
    planned: NodePlan,
    cache: MemoizationCache,
    *,
    workflow_path: str | None = None,
) -> PlanEntry:
    """Entry for a cache miss — the node would execute."""
    permissive_diag = _permissive_template_diagnostic(planned)
    cause: Literal["no_cache_match", "template_error"] = (
        "template_error" if permissive_diag is not None else "no_cache_match"
    )
    return _execute_entry(config, cache, cause=cause, diagnostic=permissive_diag, workflow_path=workflow_path)


def _cache_age(cache_key: str | None, cache: MemoizationCache) -> float | None:
    """Look up the age of a cached memo entry, if still present.

    Clamps to zero — a negative age (clock moved backward between cache
    write and read, e.g. NTP adjustment) should never surface as "-1s ago"
    in the plan output.
    """
    if cache_key is None:
        return None
    with_age = cache.get_with_age(cache_key)
    if with_age is None:
        return None
    return max(0.0, time() - with_age[2])


def _permissive_template_diagnostic(planned: NodePlan) -> Diagnostic | None:
    """Last structured permissive-mode template error, if any."""
    if not planned.template_errors:
        return None
    last = planned.template_errors[-1]
    attached = last.get("diagnostic") if isinstance(last, dict) else None
    return attached if isinstance(attached, Diagnostic) else None


# ──────────────────────────────────────────────────────────────────────────────
# Sub-workflow planning
# ──────────────────────────────────────────────────────────────────────────────


def _plan_sub_workflow(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    visited_paths: list[str],
    depth: int,
) -> PlanEntry:
    """Compile and recursively plan a nested workflow.

    Flat early-return ladder — each check either short-circuits with a
    descriptive PlanEntry or passes its value through to the next stage.
    """
    node_id = config.node_id
    node_type = config.node_type_name

    if depth >= _MAX_SUB_WORKFLOW_DEPTH:
        return _sub_workflow_error_entry(
            node_id,
            node_type,
            f"Max sub-workflow depth {_MAX_SUB_WORKFLOW_DEPTH} exceeded at '{node_id}'",
        )

    # Opaque pre-check: `workflow: ${...}` can't be planned; don't run plan_node.
    workflow_ref = _raw_workflow_ref(curr, config)
    if isinstance(workflow_ref, str) and "${" in workflow_ref:
        return _opaque_sub_workflow_entry(node_id, node_type)

    planned = plan_node(curr, config, shared)
    if planned.template_exception is not None:
        return _template_error_entry(config, planned.template_exception)

    merged = _merged_sub_workflow_params(curr, config, planned)

    # Resolve relative child refs against the parent's dir, or CWD for inline
    # (non-file) workflows. Mirrors `WorkflowExecutor._load_workflow` exactly:
    # `shared["_pflow_workflow_file"]` is the parent's absolute path for file
    # runs, the synthetic `"ir-hash:..."` identifier for inline runs (whose
    # `Path(...).parent` is `Path(".")` → CWD-relative), or absent.
    parent_file = shared.get("_pflow_workflow_file")
    base_path = Path(parent_file).parent if parent_file else Path.cwd()
    try:
        resolved = resolve_sub_workflow(merged, base_path=base_path)
    except _SUB_WORKFLOW_RESOLVE_EXCEPTIONS as exc:
        return _sub_workflow_error_entry(node_id, node_type, f"Sub-workflow resolve failed: {exc}")
    if resolved is None:
        return _opaque_sub_workflow_entry(node_id, node_type)

    resolved_path_str = str(resolved.path.resolve()) if resolved.path else None

    if resolved_path_str is not None and resolved_path_str in visited_paths:
        return _sub_workflow_error_entry(
            node_id,
            node_type,
            f"Circular sub-workflow reference: {resolved_path_str}",
        )

    raw_inputs = merged.get("inputs")
    if raw_inputs is not None and not isinstance(raw_inputs, dict):
        return _sub_workflow_error_entry(
            node_id,
            node_type,
            f"Workflow node 'inputs:' resolved to {type(raw_inputs).__name__}, expected dict",
        )
    child_inputs: dict[str, Any] = dict(raw_inputs) if raw_inputs else {}

    try:
        compiled_child = _compile_child(resolved.ir, resolved_path_str, child_inputs, registry, node_id, node_type)
    except _ChildCompileFailed as failure:
        return failure.entry

    child_plan, child_shared = _build_plan_with_shared(
        compiled_child,
        child_inputs,
        cache,
        registry,
        workflow_name=str(merged.get("workflow") or "<sub-workflow>"),
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

    # Populate parent's shared[node_id] with the child's outputs so downstream
    # nodes that template against ${<node_id>.<key>} can resolve at plan time.
    # Mirrors the runtime path: engine wraps the WorkflowExecutor node with a
    # NamespacedSharedStore → child outputs land at shared[node_id][key].
    # Partial failure (a declared source references an execute-marked child
    # node) silently skips that key — honest: the downstream templating it
    # will fail at plan time too, matching what would happen at runtime.
    _populate_sub_workflow_outputs(shared, node_id, compiled_child, child_shared, child_inputs)

    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="sub_workflow",
        cause="no_cache_match",
        sub_plan=child_plan,
    )


def _populate_sub_workflow_outputs(
    parent_shared: dict[str, Any],
    node_id: str,
    compiled_child: CompiledWorkflow,
    child_shared: dict[str, Any],
    child_inputs: dict[str, Any],
) -> None:
    """Expose the child sub-workflow's outputs into parent's `shared[node_id]`.

    Mirrors the runtime path in `WorkflowExecutor._expose_child_outputs`:

    - **Declared path**: when the child has `## Outputs`, resolve each
      declaration's `source:` template against the child's scratch shared
      (populated by `apply_memo_hit` for cached children). Unresolvable
      sources — declared keys whose `source:` references an execute-marked
      child node — are silently skipped; downstream parent nodes templating
      the missing key will surface a `template_error` plan entry, which is
      honest (runtime would fail the same way at plan time).

    - **Undeclared fallback**: when the child has NO declared outputs, copy
      every non-internal, non-input key from child_shared to parent's
      namespace. Matches runtime's fallback at `workflow_executor.py:472-478`.
      Agents referencing `${<node_id>.<child_node_id>.<field>}` can resolve
      the same way at plan time as at runtime.

    Writes `parent_shared[node_id]` to the resulting dict in either path.
    """
    declared = getattr(compiled_child, "outputs", None)

    if isinstance(declared, dict) and declared:
        parent_shared[node_id] = _resolve_declared_outputs(declared, child_shared)
        return

    parent_shared[node_id] = _mirror_child_shared(child_shared, child_inputs)


def _resolve_declared_outputs(
    declared: dict[str, Any],
    child_shared: dict[str, Any],
) -> dict[str, Any]:
    """Resolve each `## Outputs` declaration against the child's scratch shared.

    Delegates to runtime's `resolve_output_source`, which handles:
    - Source normalization (`node.key` / `$node.key` / `${node.key}` forms
      all accepted — matches the three formats pflow's output syntax allows).
    - Unresolved-detection (returns None when the template can't resolve).

    Unresolved sources (and sources that resolve to None) are silently
    dropped from the resulting dict. Downstream parent nodes that template
    against a missing key surface a `template_error` plan entry — honest
    about the fact that the runtime would also fail here via
    `populate_declared_outputs`.
    """
    from pflow.runtime.output_resolver import resolve_output_source

    resolved: dict[str, Any] = {}
    for output_name, decl in declared.items():
        if not isinstance(decl, dict):
            continue
        source = decl.get("source")
        if not isinstance(source, str):
            continue
        value = resolve_output_source(source, child_shared)
        if value is not None:
            resolved[output_name] = value
    return resolved


def _mirror_child_shared(
    child_shared: dict[str, Any],
    child_inputs: dict[str, Any],
) -> dict[str, Any]:
    """Copy non-internal, non-input child_shared keys — runtime fallback parity."""
    input_keys = set(child_inputs.keys())
    mirrored: dict[str, Any] = {}
    for key, value in child_shared.items():
        if not isinstance(key, str):
            continue
        if key.startswith(("_pflow_", "__")):
            continue
        if key in input_keys:
            continue
        mirrored[key] = value
    return mirrored


def _raw_workflow_ref(curr: Any, config: NodeConfig) -> Any:
    """Extract the raw `workflow:` param pre-resolution (may still be a template)."""
    if config.template_config:
        ref = config.template_config.template_params.get("workflow")
        if ref is not None:
            return ref
        return config.template_config.static_params.get("workflow")
    if hasattr(curr, "params"):
        return curr.params.get("workflow")
    return None


def _merged_sub_workflow_params(curr: Any, config: NodeConfig, planned: NodePlan) -> dict[str, Any]:
    """Merge raw node params + static template params + resolved template params.

    Seeding from `curr.params` first catches param keys that aren't tracked
    in `template_config.static_params` (some sub-workflow refs fall here).
    """
    merged: dict[str, Any] = dict(getattr(curr, "params", {}) or {})
    if config.template_config:
        merged.update(config.template_config.static_params or {})
    if planned.resolved_params:
        merged.update(planned.resolved_params)
    return merged


def _opaque_sub_workflow_entry(node_id: str, node_type: str) -> PlanEntry:
    """Entry for a sub-workflow we can't resolve at plan time."""
    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="opaque",
        cause="dynamic",
    )


def _sub_workflow_error_entry(node_id: str, node_type: str, message: str) -> PlanEntry:
    """Entry for a sub-workflow that failed at resolve / validate / cycle check."""
    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="execute",
        cause="template_error",
        diagnostic=Diagnostic(
            severity=Severity.WARNING,
            message=message,
            node_id=node_id,
            source="planner",
            context={"category": "sub_workflow"},
        ),
    )


def _compile_child(
    child_ir: dict[str, Any],
    resolved_path_str: str | None,
    child_inputs: dict[str, Any],
    registry: Registry,
    node_id: str,
    node_type: str,
) -> CompiledWorkflow:
    """Compile a resolved child workflow.

    Raises `_ChildCompileFailed` (carrying a ready-to-return PlanEntry) when
    the child fails any recoverable compile-time check. Any other exception
    propagates — only `_CHILD_COMPILE_EXCEPTIONS` is swallowed here.
    """
    from pflow.runtime.compilation.compiler import compile_workflow

    child_initial_params = dict(child_inputs)
    if resolved_path_str is not None:
        child_initial_params["_pflow_workflow_file"] = resolved_path_str
    try:
        return compile_workflow(child_ir, registry=registry, initial_params=child_initial_params)
    except _CHILD_COMPILE_EXCEPTIONS as exc:
        raise _ChildCompileFailed(_compile_error_entry(exc, node_id, node_type)) from exc


def _compile_error_entry(exc: BaseException, node_id: str, node_type: str) -> PlanEntry:
    """Build the plan entry for a sub-workflow compile failure."""
    child_diags = _safe_to_diagnostics(exc)
    diag = (
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
        diagnostic=diag,
    )


def _build_sub_workflow_exception_tuples() -> tuple[tuple[type[BaseException], ...], tuple[type[BaseException], ...]]:
    """Exceptions treated as recoverable at the planner's sub-workflow boundary."""
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
    """Best-effort extraction of Diagnostics from an exception object."""
    if not hasattr(exc, "to_diagnostics"):
        return []
    try:
        diagnostics = exc.to_diagnostics()
    except Exception:
        return []
    return [d for d in diagnostics if isinstance(d, Diagnostic)]


# ──────────────────────────────────────────────────────────────────────────────
# Historical cost lookup for LLM-family nodes
# ──────────────────────────────────────────────────────────────────────────────


def _read_stats_from_output(output: Any) -> tuple[float | None, float | None]:
    """Extract `(cost_usd, duration_ms)` from a cached output dict.

    Symmetric with `instrumentation.py::write_memo_cache`, which injects
    `__pflow_stats__` into the output blob at write time. Cost lives
    inside `llm_usage` (node-owned, LLM-only). Duration lives inside
    `__pflow_stats__` (engine-injected, all-node). Returns `(None, None)`
    for keys absent or malformed — tolerant of pre-migration cache
    entries that predate duration recording.
    """
    if not isinstance(output, dict):
        return None, None

    cost = _extract_cost_from_llm_usage(output.get("llm_usage"))
    if cost is None:
        cost = _extract_batch_cost_from_results(output.get("results"))

    duration: float | None = None
    stats = output.get("__pflow_stats__")
    if isinstance(stats, dict):
        raw_duration = stats.get("duration_ms")
        if isinstance(raw_duration, (int, float)) and math.isfinite(raw_duration):
            duration = float(raw_duration)

    return cost, duration


def _extract_cost_from_llm_usage(llm_usage: Any) -> float | None:
    """Read `cost_usd` out of an `llm_usage` dict (if that's its shape).

    Filters out `NaN`/`Inf` — those emit non-standard JSON (`NaN`,
    `Infinity`) that strict parsers like `jq` reject, silently breaking
    agent cost-gating scripts.
    """
    if not isinstance(llm_usage, dict):
        return None
    raw = llm_usage.get("cost_usd")
    if isinstance(raw, (int, float)) and math.isfinite(raw):
        return float(raw)
    return None


def _extract_batch_cost_from_results(results: Any) -> float | None:
    """Sum `cost_usd` across batch `results[i].llm_usage` entries.

    Returns None when `results` isn't a list (non-batch output) or when no
    item had a usable cost field (non-LLM batch, or LLM items that skipped
    pricing). Missing items are silently skipped — matches `results` being
    a "successes-only" list (failures live in `errors[]`, not in cache).
    """
    if not isinstance(results, list):
        return None
    total = 0.0
    found_any = False
    for item in results:
        item_cost = _extract_cost_from_llm_usage(item.get("llm_usage") if isinstance(item, dict) else None)
        if item_cost is not None:
            total += item_cost
            found_any = True
    return total if found_any else None


def _lookup_last_run_stats(
    config: NodeConfig, cache: MemoizationCache, *, workflow_path: str | None = None
) -> tuple[float | None, float | None, float | None]:
    """Historical `(cost_usd, duration_ms, age_sec)` for this node, if any.

    Cost is populated only for LLM-family nodes (matches the `_execute_entry`
    contract — non-LLM nodes have no cost dimension). Duration is populated
    for any node with a prior cache entry that recorded `duration_ms`. Age
    is the seconds since the most recent cache entry for `config.node_id`.
    Returns `(None, None, None)` when no prior entry exists.

    When `workflow_path` is provided, lookup is scoped to entries written by
    the same workflow — prevents cross-workflow pollution for common node
    names like "classify" or "fetch". Passing None falls back to unscoped
    lookup (necessary for direct-IR / content-string runs with NULL paths).
    """
    latest = cache.get_latest_for_node(config.node_id, workflow_path=workflow_path)
    if latest is None:
        return None, None, None
    output, created_at = latest
    cost, duration = _read_stats_from_output(output)
    if config.node_type_name not in _LLM_NODE_CLASSES:
        cost = None
    age = time() - created_at
    return cost, duration, age


# ──────────────────────────────────────────────────────────────────────────────
# Summary aggregation
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Totals:
    """Typed intermediate totals for summary aggregation."""

    total: int
    cached_count: int
    execute_count: int
    cache_boundary: str | None
    execute_by_type: dict[str, int]
    estimated_cost_usd: float
    nodes_without_history: int
    estimated_duration_ms: float
    nodes_without_duration_history: int


def _summarize(entries: list[PlanEntry], *, cost_basis: _CostBasis = "exact") -> PlanSummary:
    """Aggregate per-level counts plus nested rollup when sub-plans exist."""
    totals = _compute_totals(entries)
    has_nested = any(entry.sub_plan is not None for entry in entries)

    if not has_nested:
        return PlanSummary(
            total=totals.total,
            cached_count=totals.cached_count,
            execute_count=totals.execute_count,
            cache_boundary=totals.cache_boundary,
            execute_by_type=totals.execute_by_type,
            estimated_cost_usd=totals.estimated_cost_usd,
            nodes_without_history=totals.nodes_without_history,
            estimated_duration_ms=totals.estimated_duration_ms,
            nodes_without_duration_history=totals.nodes_without_duration_history,
            cost_basis=cost_basis,
        )

    nested_total = totals.total
    nested_cached = totals.cached_count
    nested_execute = totals.execute_count
    nested_cost = totals.estimated_cost_usd
    nested_nwh = totals.nodes_without_history
    nested_duration = totals.estimated_duration_ms
    nested_nwdh = totals.nodes_without_duration_history
    effective_basis = cost_basis

    for entry in entries:
        if entry.sub_plan is None:
            continue
        child = entry.sub_plan.summary
        nested_total += child.total_including_nested or child.total
        nested_cached += child.cached_including_nested or child.cached_count
        nested_execute += child.execute_including_nested or child.execute_count
        nested_cost += (
            child.estimated_cost_usd_including_nested
            if child.estimated_cost_usd_including_nested is not None
            else child.estimated_cost_usd
        )
        nested_nwh += (
            child.nodes_without_history_including_nested
            if child.nodes_without_history_including_nested is not None
            else child.nodes_without_history
        )
        nested_duration += (
            child.estimated_duration_ms_including_nested
            if child.estimated_duration_ms_including_nested is not None
            else child.estimated_duration_ms
        )
        nested_nwdh += (
            child.nodes_without_duration_history_including_nested
            if child.nodes_without_duration_history_including_nested is not None
            else child.nodes_without_duration_history
        )
        if child.cost_basis == "upper_bound":
            effective_basis = "upper_bound"

    return PlanSummary(
        total=totals.total,
        cached_count=totals.cached_count,
        execute_count=totals.execute_count,
        cache_boundary=totals.cache_boundary,
        execute_by_type=totals.execute_by_type,
        estimated_cost_usd=totals.estimated_cost_usd,
        nodes_without_history=totals.nodes_without_history,
        estimated_duration_ms=totals.estimated_duration_ms,
        nodes_without_duration_history=totals.nodes_without_duration_history,
        cost_basis=effective_basis,
        total_including_nested=nested_total,
        cached_including_nested=nested_cached,
        execute_including_nested=nested_execute,
        estimated_cost_usd_including_nested=nested_cost,
        nodes_without_history_including_nested=nested_nwh,
        estimated_duration_ms_including_nested=nested_duration,
        nodes_without_duration_history_including_nested=nested_nwdh,
    )


def _compute_totals(entries: list[PlanEntry]) -> _Totals:
    """One pass over entries computing all per-level aggregates."""
    total = len(entries)
    cached_count = 0
    execute_count = 0
    cache_boundary: str | None = None
    execute_by_type: dict[str, int] = {}
    estimated_cost_usd = 0.0
    nodes_without_history = 0
    estimated_duration_ms = 0.0
    nodes_without_duration_history = 0

    for entry in entries:
        if entry.status == "cached":
            cached_count += 1

        if _represents_work(entry):
            execute_count += 1
            execute_by_type[entry.node_type] = execute_by_type.get(entry.node_type, 0) + 1
            if cache_boundary is None and entry.cause != "downstream":
                cache_boundary = entry.node_id

        if entry.last_cost_usd is not None:
            estimated_cost_usd += entry.last_cost_usd

        if entry.status == "execute" and entry.node_type in _LLM_NODE_CLASSES and entry.last_cost_usd is None:
            nodes_without_history += 1

        if entry.last_duration_ms is not None:
            estimated_duration_ms += entry.last_duration_ms

        if entry.status == "execute" and entry.last_duration_ms is None:
            nodes_without_duration_history += 1

    return _Totals(
        total=total,
        cached_count=cached_count,
        execute_count=execute_count,
        cache_boundary=cache_boundary,
        execute_by_type=execute_by_type,
        estimated_cost_usd=estimated_cost_usd,
        nodes_without_history=nodes_without_history,
        estimated_duration_ms=estimated_duration_ms,
        nodes_without_duration_history=nodes_without_duration_history,
    )
