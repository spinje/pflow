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
from collections import defaultdict, deque
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
from pflow.runtime.engine.batch_executor import resolve_batch_items
from pflow.runtime.engine.engine import is_clean_termination
from pflow.runtime.engine.instrumentation import apply_memo_hit, enforce_loop_guard
from pflow.runtime.engine.plan_node import NodePlan, plan_node
from pflow.runtime.engine.template_resolution import resolve_templates
from pflow.runtime.engine.types import BatchConfig, CompiledWorkflow, NodeConfig
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.workflow_executor import WorkflowExecutor

logger = logging.getLogger(__name__)

_LLM_NODE_CLASSES: frozenset[str] = frozenset({"LLMNode", "ClaudeCodeNode"})

_CostBasis = Literal["upper_bound", "exact"]


@dataclass
class _WalkerState:
    """Mutable state threaded through the walker's per-iteration dispatch.

    Pass-by-reference replaces the 10-arg `_advance` signature. Every
    field is planner-owned; mutating them is the walker's job.

    `shared`, `registry`, `visited_paths`, `depth` are the four pieces
    needed by sub-workflow recursion — they flow through `_apply_boundary`
    and `_bfs_downstream` so BFS can dispatch `WorkflowExecutor` nodes to
    `_plan_sub_workflow(cause="downstream")` and produce nested sub_plans
    for cost/duration rollup, instead of flat leaf entries that lose the
    nested signal.
    """

    entries: list[PlanEntry]
    diagnostics: list[Diagnostic]
    visited_edges: set[tuple[str, str]]
    only_node: str | None
    shared: dict[str, Any]
    registry: Registry
    visited_paths: list[str]
    depth: int
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


@dataclass(frozen=True)
class _PreparedSubWorkflow:
    """Resolved sub-workflow target ready for recursive planning."""

    merged: dict[str, Any]
    child_inputs: dict[str, Any]
    resolved: Any
    resolved_path_str: str | None
    compiled_child: CompiledWorkflow


@dataclass(frozen=True)
class _PreparedBatchSubWorkflowParams:
    """Item[0]-resolved params needed to plan a batch sub-workflow."""

    merged: dict[str, Any]
    child_inputs: dict[str, Any]
    raw_inputs_template: Any


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

    # No matching successor. Shared with engine's `_handle_no_successor` via
    # `is_clean_termination` — "end" sentinel and all-error-successors clean-
    # terminate in both paths by construction.
    if is_clean_termination(action, curr.successors):
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
    _force_downstream: bool = False,
) -> tuple[Plan, dict[str, Any]]:
    """Internal variant of `build_plan` that also exposes the scratch shared.

    `_plan_sub_workflow` calls this to access the child's post-walk shared
    state, which has cached outputs populated via `apply_memo_hit`. Those
    values drive exact resolution of the child's declared `## Outputs`
    templates — matching what runtime does when a sub-workflow completes.

    `_force_downstream=True` is used when planning a sub-workflow reached
    post-first-miss in a parent: the entire child graph is downstream by
    construction (parent's upstream has changed, so we can't reason about
    individual child cache-state). Skips the state machine and BFSes from
    the start node, marking every entry `cause="downstream"` with
    historical cost/duration estimates scoped to the child's workflow_path.
    Cost basis is always `upper_bound` — conservative for cost-gating.
    """
    _validate_only_target(compiled, only_node, _depth)

    shared = _create_planner_shared(compiled, params, cache, _parent_workflow_file)
    visited_paths = list(_visited_paths) if _visited_paths else []
    workflow_path = shared.get("_pflow_workflow_file")

    if _force_downstream:
        entries, branched = _bfs_from_start(
            start_node=compiled.start_node,
            compiled=compiled,
            cache=cache,
            registry=registry,
            shared=shared,
            visited_paths=visited_paths,
            depth=_depth,
            workflow_path=workflow_path,
            only_node=only_node,
        )
        diagnostics: list[Diagnostic] = []
        for entry in entries:
            if entry.sub_plan is not None:
                diagnostics.extend(entry.sub_plan.diagnostics)
            if entry.diagnostic is not None:
                diagnostics.append(entry.diagnostic)
        # Only flip to upper_bound if BFS actually encountered branching.
        # Linear downstream graphs have an exact topology — every node WILL
        # run at runtime. The historical-cost hedge is separate, carried by
        # the formatter's default "historical, actual may vary" suffix.
        plan = Plan(
            workflow=workflow_name,
            entries=entries,
            summary=_summarize(entries, cost_basis="upper_bound" if branched else "exact"),
            diagnostics=diagnostics,
        )
        return plan, shared

    state = _WalkerState(
        entries=[],
        diagnostics=[],
        visited_edges=set(),
        only_node=only_node,
        workflow_path=workflow_path,
        shared=shared,
        registry=registry,
        visited_paths=visited_paths,
        depth=_depth,
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
        shared=state.shared,
        registry=state.registry,
        visited_paths=state.visited_paths,
        depth=state.depth,
    )
    state.entries.extend(bfs_entries)
    for entry in bfs_entries:
        if entry.sub_plan is not None:
            state.diagnostics.extend(entry.sub_plan.diagnostics)
        if entry.diagnostic is not None:
            state.diagnostics.append(entry.diagnostic)
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
    shared: dict[str, Any],
    registry: Registry,
    visited_paths: list[str],
    depth: int,
) -> tuple[list[PlanEntry], bool]:
    """Enumerate reachable would-execute nodes after the first cache miss.

    Walks non-"error" outgoing edges breadth-first from `boundary_node`'s
    successors (the boundary node itself is already an entry). Returns the
    discovered entries plus a `branched` flag — true when any traversed node
    had more than one non-error successor, which flips the plan's cost_basis
    to upper_bound (conservative for cost gating).

    `WorkflowExecutor` nodes dispatch to `_plan_sub_workflow(cause="downstream")`
    so nested cost/duration rolls up through the standard sub_plan path.
    """
    queue: deque[Any] = deque()
    branched_seed = _seed_bfs(boundary_node, queue, visited_edges)
    entries, branched_walk = _bfs_walk(
        queue=queue,
        compiled=compiled,
        cache=cache,
        visited_nodes=visited_nodes,
        visited_edges=visited_edges,
        only_node=only_node,
        workflow_path=workflow_path,
        shared=shared,
        registry=registry,
        visited_paths=visited_paths,
        depth=depth,
    )
    return entries, branched_seed or branched_walk


def _bfs_from_start(
    *,
    start_node: Any,
    compiled: CompiledWorkflow,
    cache: MemoizationCache,
    registry: Registry,
    shared: dict[str, Any],
    visited_paths: list[str],
    depth: int,
    workflow_path: str | None,
    only_node: str | None,
) -> tuple[list[PlanEntry], bool]:
    """BFS over the entire graph from the start node, every entry downstream.

    Used by `_build_plan_with_shared(force_downstream=True)` when a sub-workflow
    is reached post-first-miss in a parent — the whole child graph inherits
    downstream status regardless of individual cache state. Unlike
    `_bfs_downstream`, the start node is INCLUDED in the output because it
    isn't an entry yet.
    """
    queue: deque[Any] = deque([start_node])
    return _bfs_walk(
        queue=queue,
        compiled=compiled,
        cache=cache,
        visited_nodes=set(),
        visited_edges=set(),
        only_node=only_node,
        workflow_path=workflow_path,
        shared=shared,
        registry=registry,
        visited_paths=visited_paths,
        depth=depth,
    )


def _bfs_walk(
    *,
    queue: deque[Any],
    compiled: CompiledWorkflow,
    cache: MemoizationCache,
    visited_nodes: set[str],
    visited_edges: set[tuple[str, str]],
    only_node: str | None,
    workflow_path: str | None,
    shared: dict[str, Any],
    registry: Registry,
    visited_paths: list[str],
    depth: int,
) -> tuple[list[PlanEntry], bool]:
    """Shared BFS loop used by both downstream-after-boundary and force-downstream.

    Callers seed the queue differently (successors vs start node) but the
    loop body — dequeue, build entry, enqueue successors — is identical.

    `enforce_loop_guard()` is intentionally NOT called here — BFS is per-visit
    enumeration for cost/duration estimation, not re-execution. The boundary
    node (or start node in force-downstream) was the last place the guard ran
    in the main walker; downstream entries never re-enter the engine's repeat-
    visit invalidation path, so there's nothing for the guard to protect
    against. Calling it inside BFS would double-bump visit counts and wrongly
    invalidate in-process cache state the walker still depends on.
    """
    entries: list[PlanEntry] = []
    branched = False

    while queue:
        node = queue.popleft()
        entry = _make_downstream_entry(
            node,
            compiled,
            cache,
            visited_nodes,
            workflow_path=workflow_path,
            shared=shared,
            registry=registry,
            visited_paths=visited_paths,
            depth=depth,
        )
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
    shared: dict[str, Any],
    registry: Registry,
    visited_paths: list[str],
    depth: int,
) -> PlanEntry | None:
    """Build a downstream PlanEntry for a BFS-discovered node, or None to skip it.

    Downstream entries go through `_execute_entry` so historical stats (cost
    + duration) are attached by construction. Skipping the stats lookup here
    was a real bug — agents cost-gating on an LLM node that happened to sit
    downstream of a non-LLM miss saw `$0` even when history existed.

    `WorkflowExecutor` nodes dispatch to `_plan_sub_workflow(cause="downstream")`
    so nested child plans are produced and nested cost/duration rolls up via
    the existing `estimated_cost_usd_including_nested` machinery. Without
    this, sub-workflows reached via BFS became opaque leaves hiding every
    internal LLM cost — the #1 cost-gating blind spot for iteration edits.
    """
    node_id = getattr(node, "node_id", None)
    if not isinstance(node_id, str) or node_id in visited_nodes:
        return None
    if node_id not in compiled.node_configs:
        return None
    visited_nodes.add(node_id)
    config = compiled.node_configs[node_id]

    if config.node_type_name == "WorkflowExecutor":
        return _plan_sub_workflow(
            node,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=depth,
            cause="downstream",
        )

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
    cause: Literal["no_cache_match", "downstream"] = "no_cache_match",
) -> PlanEntry:
    """Compile and recursively plan a nested workflow.

    Flat early-return ladder — each check either short-circuits with a
    descriptive PlanEntry or passes its value through to the next stage.

    `cause="downstream"` — used when this sub-workflow is reached via BFS
    post-first-miss in the parent. In that mode we skip template-driven
    param resolution (parent's upstream state is dirty, inputs can't
    resolve reliably) and recurse with `_force_downstream=True` so the
    child's entire graph inherits downstream status with historical
    stats scoped to the child's workflow_path.
    """
    node_id = config.node_id
    node_type = config.node_type_name
    downstream = cause == "downstream"

    if config.batch_config and not downstream:
        return _plan_batch_sub_workflow(
            curr,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=depth,
        )

    guard_entry = _precheck_sub_workflow(curr, config, depth=depth)
    if guard_entry is not None:
        return guard_entry

    params_or_entry = _resolve_sub_workflow_params(curr, config, shared, downstream=downstream)
    if isinstance(params_or_entry, PlanEntry):
        return params_or_entry
    merged, child_inputs = params_or_entry
    target_or_entry = _prepare_sub_workflow(
        merged=merged,
        child_inputs=child_inputs,
        shared=shared,
        registry=registry,
        visited_paths=visited_paths,
        node_id=node_id,
        node_type=node_type,
        downstream=downstream,
    )
    if isinstance(target_or_entry, PlanEntry):
        return target_or_entry
    prepared = target_or_entry

    child_plan, child_shared = _build_plan_with_shared(
        prepared.compiled_child,
        prepared.child_inputs,
        cache,
        registry,
        workflow_name=str(prepared.merged.get("workflow") or "<sub-workflow>"),
        _visited_paths=[*visited_paths, prepared.resolved_path_str] if prepared.resolved_path_str else visited_paths,
        _depth=depth + 1,
        _parent_workflow_file=prepared.resolved_path_str,
        _force_downstream=downstream,
    )
    child_plan = _attach_sub_workflow_warnings(child_plan, prepared.resolved.warnings)

    # Populate parent's shared[node_id] with the child's outputs so downstream
    # nodes that template against ${<node_id>.<key>} can resolve at plan time.
    # Mirrors the runtime path: engine wraps the WorkflowExecutor node with a
    # NamespacedSharedStore → child outputs land at shared[node_id][key].
    # Skipped in downstream mode: the child wasn't walked through the state
    # machine, so its scratch shared has no apply_memo_hit-populated outputs
    # to resolve from. Parent's downstream successors won't template against
    # this sub_plan anyway (they're all downstream too).
    if not downstream:
        _populate_sub_workflow_outputs(
            shared,
            node_id,
            prepared.compiled_child,
            child_shared,
            prepared.child_inputs,
        )

    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="sub_workflow",
        cause=cause,
        sub_plan=child_plan,
    )


def _plan_batch_sub_workflow(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    visited_paths: list[str],
    depth: int,
) -> PlanEntry:
    """Plan a batch WorkflowExecutor by recursively planning one child per item."""
    node_id = config.node_id
    node_type = config.node_type_name
    batch_config = config.batch_config
    if batch_config is None:
        return _sub_workflow_error_entry(node_id, node_type, "Batch sub-workflow planning requires batch config")

    guard_entry = _precheck_sub_workflow(curr, config, depth=depth)
    if guard_entry is not None:
        return guard_entry

    items_or_entry = _resolve_batch_sub_workflow_items(config, shared, batch_config)
    if isinstance(items_or_entry, PlanEntry):
        return items_or_entry
    items = items_or_entry

    if not items:
        return _empty_batch_sub_workflow_entry(curr, config, shared, batch_config)

    params_or_entry = _prepare_batch_sub_workflow_params(curr, config, shared, items, batch_config)
    if isinstance(params_or_entry, PlanEntry):
        return params_or_entry
    batch_params = params_or_entry
    target_or_entry = _prepare_sub_workflow(
        merged=batch_params.merged,
        child_inputs=batch_params.child_inputs,
        shared=shared,
        registry=registry,
        visited_paths=visited_paths,
        node_id=node_id,
        node_type=node_type,
    )
    if isinstance(target_or_entry, PlanEntry):
        return target_or_entry
    prepared = target_or_entry
    child_plans, item_outputs, per_item_diagnostics = _plan_batch_sub_workflow_items(
        items=items,
        shared=shared,
        cache=cache,
        registry=registry,
        batch_config=batch_config,
        raw_inputs_template=batch_params.raw_inputs_template,
        prepared=prepared,
        depth=depth,
        visited_paths=visited_paths,
        node_id=node_id,
    )

    aggregated_plan = _aggregate_batch_child_plans(
        child_plans,
        batch_parallel=batch_config.parallel,
        batch_count=len(items),
        extra_diagnostics=per_item_diagnostics,
    )
    shared[node_id] = _build_batch_output_shape(item_outputs, items, batch_config)

    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="sub_workflow",
        cause="no_cache_match",
        sub_plan=aggregated_plan,
        batch_count=len(items),
        batch_parallel=batch_config.parallel,
    )


def _precheck_sub_workflow(curr: Any, config: NodeConfig, *, depth: int) -> PlanEntry | None:
    """Return an early guard entry for depth / dynamic-ref failures."""
    node_id = config.node_id
    node_type = config.node_type_name
    if depth >= WorkflowExecutor.MAX_DEPTH_DEFAULT:
        return _sub_workflow_error_entry(
            node_id,
            node_type,
            f"Max sub-workflow depth {WorkflowExecutor.MAX_DEPTH_DEFAULT} exceeded at '{node_id}'",
        )

    workflow_ref = _raw_workflow_ref(curr, config)
    if isinstance(workflow_ref, str) and "${" in workflow_ref:
        return _opaque_sub_workflow_entry(node_id, node_type)
    return None


def _resolve_sub_workflow_base_path(shared: dict[str, Any]) -> Path:
    """Resolve child workflow refs against the same base runtime uses."""
    parent_file = shared.get("_pflow_workflow_file")
    return Path(parent_file).parent if parent_file else Path.cwd()


def _prepare_sub_workflow(
    *,
    merged: dict[str, Any],
    child_inputs: dict[str, Any],
    shared: dict[str, Any],
    registry: Registry,
    visited_paths: list[str],
    node_id: str,
    node_type: str,
    downstream: bool = False,
) -> _PreparedSubWorkflow | PlanEntry:
    """Resolve, cycle-check, and compile a child workflow target."""
    try:
        resolved = resolve_sub_workflow(merged, base_path=_resolve_sub_workflow_base_path(shared))
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

    effective_inputs = _effective_child_inputs(resolved.ir, child_inputs, downstream=downstream)
    try:
        compiled_child = _compile_child(resolved.ir, resolved_path_str, effective_inputs, registry, node_id, node_type)
    except _ChildCompileFailed as failure:
        return failure.entry

    return _PreparedSubWorkflow(
        merged=merged,
        child_inputs=effective_inputs,
        resolved=resolved,
        resolved_path_str=resolved_path_str,
        compiled_child=compiled_child,
    )


def _attach_sub_workflow_warnings(plan: Plan, warnings: list[Diagnostic] | tuple[Diagnostic, ...]) -> Plan:
    """Append resolver warnings to a child plan when present."""
    if not warnings:
        return plan
    return Plan(
        workflow=plan.workflow,
        entries=plan.entries,
        summary=plan.summary,
        diagnostics=[*plan.diagnostics, *warnings],
    )


def _resolve_batch_sub_workflow_items(
    config: NodeConfig,
    shared: dict[str, Any],
    batch_config: BatchConfig,
) -> list[Any] | PlanEntry:
    """Resolve batch items for a WorkflowExecutor or surface an honest entry."""
    items = resolve_batch_items(batch_config.items_template, shared)
    if items is None:
        return _opaque_sub_workflow_entry(config.node_id, config.node_type_name)
    if not isinstance(items, list):
        return _sub_workflow_error_entry(
            config.node_id,
            config.node_type_name,
            f"Workflow batch items resolved to {type(items).__name__}, expected list",
        )
    return items


def _empty_plan(workflow: str) -> Plan:
    """Create an empty nested plan with fully-populated zero summary fields."""
    return Plan(
        workflow=workflow,
        entries=[],
        summary=PlanSummary(
            total=0,
            cached_count=0,
            execute_count=0,
            cache_boundary=None,
            execute_by_type={},
            estimated_cost_usd=0.0,
            nodes_without_history=0,
            estimated_duration_ms=0.0,
            nodes_without_duration_history=0,
            opaque_count=0,
            cost_basis="exact",
            total_including_nested=0,
            cached_including_nested=0,
            execute_including_nested=0,
            execute_by_type_including_nested={},
            estimated_cost_usd_including_nested=0.0,
            nodes_without_history_including_nested=0,
            estimated_duration_ms_including_nested=0.0,
            nodes_without_duration_history_including_nested=0,
            opaque_count_including_nested=0,
        ),
    )


def _empty_batch_sub_workflow_entry(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    batch_config: BatchConfig,
) -> PlanEntry:
    """Return the empty-batch plan entry and runtime-shaped shared output."""
    workflow_ref = _raw_workflow_ref(curr, config)
    shared[config.node_id] = _build_batch_output_shape([], [], batch_config)
    return PlanEntry(
        node_id=config.node_id,
        node_type=config.node_type_name,
        status="sub_workflow",
        cause="no_cache_match",
        sub_plan=_empty_plan(str(workflow_ref or "<sub-workflow>")),
        batch_count=0,
        batch_parallel=batch_config.parallel,
    )


def _prepare_batch_sub_workflow_params(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    items: list[Any],
    batch_config: BatchConfig,
) -> _PreparedBatchSubWorkflowParams | PlanEntry:
    """Resolve item[0]-scoped params for a batch sub-workflow."""
    try:
        shared[batch_config.item_alias] = items[0]
        shared["__index__"] = 0
        if config.template_config:
            resolved_params, _, _ = resolve_templates(config.template_config, shared, config.node_id)
            merged = dict(getattr(curr, "params", {}) or {})
            if config.template_config:
                merged.update(config.template_config.static_params or {})
            merged.update(resolved_params)
        else:
            merged = dict(getattr(curr, "params", {}) or {})
    except Exception as exc:
        if isinstance(exc, ValueError):
            return _template_error_entry(config, exc)
        logger.warning("Batch sub-workflow template resolution failed: %s", exc)
        return _sub_workflow_error_entry(config.node_id, config.node_type_name, f"Template resolution failed: {exc}")
    finally:
        shared.pop(batch_config.item_alias, None)
        shared.pop("__index__", None)

    raw_inputs = merged.get("inputs")
    if raw_inputs is not None and not isinstance(raw_inputs, dict):
        return _sub_workflow_error_entry(
            config.node_id,
            config.node_type_name,
            f"Workflow node 'inputs:' resolved to {type(raw_inputs).__name__}, expected dict",
        )

    raw_inputs_template = None
    if config.template_config:
        raw_inputs_template = config.template_config.template_params.get("inputs")

    return _PreparedBatchSubWorkflowParams(
        merged=merged,
        child_inputs=dict(raw_inputs) if raw_inputs else {},
        raw_inputs_template=raw_inputs_template,
    )


def _resolve_per_item_sub_workflow_inputs(
    *,
    shared: dict[str, Any],
    batch_config: BatchConfig,
    item: Any,
    idx: int,
    raw_inputs_template: Any,
    default_inputs: dict[str, Any],
    node_id: str,
) -> tuple[dict[str, Any], Diagnostic | None]:
    """Resolve child inputs for one batch item, falling back to item[0] shape.

    Returns (inputs, diagnostic). Diagnostic is non-None when resolution
    produced a non-dict — runtime would raise ValueError in that case, so
    we surface a WARNING to make the plan honest about a likely runtime failure.
    """
    if raw_inputs_template is None:
        return default_inputs, None
    per_item_context = {**shared, batch_config.item_alias: item, "__index__": idx}
    resolved_inputs = TemplateResolver.resolve_nested(raw_inputs_template, per_item_context)
    if isinstance(resolved_inputs, dict):
        return resolved_inputs, None
    diag = Diagnostic(
        severity=Severity.WARNING,
        source="planner",
        node_id=node_id,
        message=(
            f"Batch item {idx}: 'inputs:' resolved to {type(resolved_inputs).__name__}, "
            f"expected dict. Runtime will reject this item."
        ),
        context={"category": "validation", "batch_item_index": idx},
    )
    return default_inputs, diag


def _extract_child_outputs(
    compiled_child: CompiledWorkflow,
    child_shared: dict[str, Any],
    child_inputs: dict[str, Any],
) -> dict[str, Any]:
    """Mirror runtime child-output exposure for one per-item child plan."""
    declared = getattr(compiled_child, "outputs", None)
    if isinstance(declared, dict) and declared:
        return _resolve_declared_outputs(declared, child_shared)
    return _mirror_child_shared(child_shared, child_inputs)


def _plan_batch_sub_workflow_items(
    *,
    items: list[Any],
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    batch_config: BatchConfig,
    raw_inputs_template: Any,
    prepared: _PreparedSubWorkflow,
    depth: int,
    visited_paths: list[str],
    node_id: str,
) -> tuple[list[Plan], list[dict[str, Any]], list[Diagnostic]]:
    """Plan each batch item's child workflow and collect exposed outputs."""
    child_plans: list[Plan] = []
    item_outputs: list[dict[str, Any]] = []
    child_workflow_name = str(prepared.merged.get("workflow") or "<sub-workflow>")
    child_visited_paths = [*visited_paths, prepared.resolved_path_str] if prepared.resolved_path_str else visited_paths

    per_item_diagnostics: list[Diagnostic] = []

    for idx, item in enumerate(items):
        per_item_inputs, input_diag = _resolve_per_item_sub_workflow_inputs(
            shared=shared,
            batch_config=batch_config,
            item=item,
            idx=idx,
            raw_inputs_template=raw_inputs_template,
            default_inputs=prepared.child_inputs,
            node_id=node_id,
        )
        if input_diag is not None:
            per_item_diagnostics.append(input_diag)
        child_plan, child_shared = _build_plan_with_shared(
            prepared.compiled_child,
            per_item_inputs,
            cache,
            registry,
            workflow_name=child_workflow_name,
            _visited_paths=child_visited_paths,
            _depth=depth + 1,
            _parent_workflow_file=prepared.resolved_path_str,
        )
        child_plans.append(child_plan)
        item_outputs.append(_extract_child_outputs(prepared.compiled_child, child_shared, per_item_inputs))

    if prepared.resolved.warnings:
        child_plans[0] = _attach_sub_workflow_warnings(child_plans[0], prepared.resolved.warnings)

    return child_plans, item_outputs, per_item_diagnostics


def _nested_or_level(summary: PlanSummary, *, nested: str, level: str) -> Any:
    """Read the *_including_nested variant of a summary field, falling back to per-level."""
    value = getattr(summary, nested)
    return value if value is not None else getattr(summary, level)


def _aggregate_batch_summary(child_plans: list[Plan], *, batch_parallel: bool) -> PlanSummary:
    """Build a single PlanSummary aggregating N per-item child plan summaries."""
    per_item_totals = [_nested_or_level(p.summary, nested="total_including_nested", level="total") for p in child_plans]
    per_item_cached = [
        _nested_or_level(p.summary, nested="cached_including_nested", level="cached_count") for p in child_plans
    ]
    per_item_execute = [
        _nested_or_level(p.summary, nested="execute_including_nested", level="execute_count") for p in child_plans
    ]
    per_item_cost = [
        _nested_or_level(p.summary, nested="estimated_cost_usd_including_nested", level="estimated_cost_usd")
        for p in child_plans
    ]
    per_item_duration = [
        _nested_or_level(p.summary, nested="estimated_duration_ms_including_nested", level="estimated_duration_ms")
        for p in child_plans
    ]
    per_item_no_history = [
        _nested_or_level(p.summary, nested="nodes_without_history_including_nested", level="nodes_without_history")
        for p in child_plans
    ]
    per_item_no_duration = [
        _nested_or_level(
            p.summary, nested="nodes_without_duration_history_including_nested", level="nodes_without_duration_history"
        )
        for p in child_plans
    ]
    per_item_opaque = [
        _nested_or_level(p.summary, nested="opaque_count_including_nested", level="opaque_count") for p in child_plans
    ]

    execute_by_type: dict[str, int] = {}
    for p in child_plans:
        child_types = (
            p.summary.execute_by_type_including_nested
            if p.summary.execute_by_type_including_nested is not None
            else p.summary.execute_by_type
        )
        for node_type, count in child_types.items():
            execute_by_type[node_type] = execute_by_type.get(node_type, 0) + count

    cost_basis: _CostBasis = "exact"
    if any(p.summary.cost_basis == "upper_bound" for p in child_plans):
        cost_basis = "upper_bound"

    total_duration = max(per_item_duration) if batch_parallel else sum(per_item_duration)
    agg_total = sum(per_item_totals)
    agg_cached = sum(per_item_cached)
    agg_execute = sum(per_item_execute)
    agg_cost = sum(cost for cost in per_item_cost if cost is not None)
    agg_no_history = sum(per_item_no_history)
    agg_no_duration = sum(per_item_no_duration)
    agg_opaque = sum(per_item_opaque)

    return PlanSummary(
        total=agg_total,
        cached_count=agg_cached,
        execute_count=agg_execute,
        cache_boundary=None,
        execute_by_type=execute_by_type,
        estimated_cost_usd=agg_cost,
        nodes_without_history=agg_no_history,
        estimated_duration_ms=total_duration,
        nodes_without_duration_history=agg_no_duration,
        opaque_count=agg_opaque,
        cost_basis=cost_basis,
        total_including_nested=agg_total,
        cached_including_nested=agg_cached,
        execute_including_nested=agg_execute,
        execute_by_type_including_nested=execute_by_type,
        estimated_cost_usd_including_nested=agg_cost,
        nodes_without_history_including_nested=agg_no_history,
        estimated_duration_ms_including_nested=total_duration,
        nodes_without_duration_history_including_nested=agg_no_duration,
        opaque_count_including_nested=agg_opaque,
    )


def _aggregate_batch_child_plans(
    child_plans: list[Plan],
    *,
    batch_parallel: bool,
    batch_count: int,
    extra_diagnostics: list[Diagnostic] | None = None,
) -> Plan:
    """Collapse N per-item child plans into one display/rollup plan."""
    if not child_plans:
        return Plan(
            workflow="<sub-workflow>",
            entries=[],
            summary=PlanSummary(
                total=0,
                cached_count=0,
                execute_count=0,
                cache_boundary=None,
                execute_by_type={},
                estimated_cost_usd=0.0,
                nodes_without_history=0,
                estimated_duration_ms=0.0,
                nodes_without_duration_history=0,
                opaque_count=0,
                cost_basis="exact",
                total_including_nested=0,
                cached_including_nested=0,
                execute_including_nested=0,
                execute_by_type_including_nested={},
                estimated_cost_usd_including_nested=0.0,
                nodes_without_history_including_nested=0,
                estimated_duration_ms_including_nested=0.0,
                nodes_without_duration_history_including_nested=0,
                opaque_count_including_nested=0,
            ),
        )

    entries_by_node: dict[str, list[PlanEntry]] = defaultdict(list)
    seen_node_ids: list[str] = []
    seen_lookup: set[str] = set()
    for plan in child_plans:
        for entry in plan.entries:
            entries_by_node[entry.node_id].append(entry)
            if entry.node_id not in seen_lookup:
                seen_lookup.add(entry.node_id)
                seen_node_ids.append(entry.node_id)

    synthetic_entries: list[PlanEntry] = []
    for node_id in seen_node_ids:
        entries_for_node = entries_by_node.get(node_id, [])
        if not entries_for_node:
            continue

        items_traversed = len(entries_for_node)
        cached_count = sum(
            1
            for entry in entries_for_node
            if entry.status == "cached" or (entry.status == "sub_workflow" and not _represents_work(entry))
        )
        cost_values = [entry.last_cost_usd for entry in entries_for_node if entry.last_cost_usd is not None]
        duration_values = [entry.last_duration_ms for entry in entries_for_node if entry.last_duration_ms is not None]
        age_values = [entry.age_sec for entry in entries_for_node if entry.age_sec is not None]
        template_entry = entries_for_node[0]

        synthetic_entries.append(
            PlanEntry(
                node_id=node_id,
                node_type=template_entry.node_type,
                status="cached" if cached_count == items_traversed else "execute",
                cause="hash_match" if cached_count == items_traversed else "no_cache_match",
                last_cost_usd=sum(cost_values) / len(cost_values) if cost_values else None,
                last_duration_ms=sum(duration_values) / len(duration_values) if duration_values else None,
                age_sec=max(age_values) if age_values else None,
                batch_items_cached=cached_count,
                batch_items_total=items_traversed,
                sub_plan=template_entry.sub_plan,
            )
        )

    summary = _aggregate_batch_summary(child_plans, batch_parallel=batch_parallel)
    all_diagnostics = [diagnostic for child_plan in child_plans for diagnostic in child_plan.diagnostics]
    if extra_diagnostics:
        all_diagnostics.extend(extra_diagnostics)
    return Plan(
        workflow=child_plans[0].workflow,
        entries=synthetic_entries,
        summary=summary,
        diagnostics=all_diagnostics,
    )


def _build_batch_output_shape(
    item_outputs: list[dict[str, Any]],
    items: list[Any],
    batch_config: BatchConfig,
) -> dict[str, Any]:
    """Mirror the runtime batch result shape for downstream template resolution."""
    results: list[dict[str, Any]] = []
    for idx, (item, output) in enumerate(zip(items, item_outputs, strict=True)):
        result = dict(output) if output else {}
        result["item"] = item
        result["original_index"] = idx
        results.append(result)
    return {
        "results": results,
        "count": len(items),
        "success_count": len(item_outputs),
        "error_count": 0,
        "errors": None,
        "batch_metadata": {
            "parallel": batch_config.parallel,
            "max_concurrent": batch_config.max_concurrent if batch_config.parallel else None,
            "max_retries": batch_config.max_retries,
            "retry_wait": batch_config.retry_wait if batch_config.retry_wait > 0 else None,
            "execution_mode": "parallel" if batch_config.parallel else "sequential",
            "timing": None,
        },
    }


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
    """Copy non-internal, non-input child_shared keys — runtime fallback parity.

    Filter rule lives on `WorkflowExecutor.is_exposable_child_key` (shared
    with runtime's `_expose_child_outputs`) so prefix changes can't drift.
    """
    input_keys = set(child_inputs.keys())
    return {
        key: value for key, value in child_shared.items() if WorkflowExecutor.is_exposable_child_key(key, input_keys)
    }


def _resolve_sub_workflow_params(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    *,
    downstream: bool,
) -> tuple[dict[str, Any], dict[str, Any]] | PlanEntry:
    """Return `(merged_params, child_inputs)` or a PlanEntry on failure.

    Splits the two behaviors of `_plan_sub_workflow` that vary by `cause`:
    - `downstream=True`: parent is in BFS mode, so parent's upstream state
      is dirty. `plan_node` would hit template_exception on any
      `inputs: ${upstream.x}`. Bypass template resolution entirely — use
      the raw workflow ref and empty inputs. The child's BFS-from-start
      walk doesn't consume inputs.
    - `downstream=False`: normal state-machine mode. Run `plan_node` for
      template resolution, surface template errors, validate inputs shape.
    """
    if downstream:
        return {"workflow": _raw_workflow_ref(curr, config)}, {}

    planned = plan_node(curr, config, shared)
    if planned.template_exception is not None:
        return _template_error_entry(config, planned.template_exception)
    merged = _merged_sub_workflow_params(curr, config, planned)
    raw_inputs = merged.get("inputs")
    if raw_inputs is not None and not isinstance(raw_inputs, dict):
        return _sub_workflow_error_entry(
            config.node_id,
            config.node_type_name,
            f"Workflow node 'inputs:' resolved to {type(raw_inputs).__name__}, expected dict",
        )
    child_inputs: dict[str, Any] = dict(raw_inputs) if raw_inputs else {}
    return merged, child_inputs


_PLACEHOLDER_STRING = "<dry-run-downstream-placeholder>"

_TYPE_PLACEHOLDERS: dict[str, Any] = {
    "array": [None],
    "list": [None],
    "object": {"_placeholder": True},
    "dict": {"_placeholder": True},
    "string": _PLACEHOLDER_STRING,
    "str": _PLACEHOLDER_STRING,
    "integer": 1,
    "int": 1,
    "number": 1,
    "float": 1.0,
    "boolean": False,
    "bool": False,
}


def _placeholder_child_inputs(child_ir: dict[str, Any]) -> dict[str, Any]:
    """Synthesize placeholder values for every declared child input.

    Used only in downstream mode: the parent is in BFS-post-miss, so the
    real upstream-resolved inputs aren't available. The child's BFS walk
    never reads inputs (no template resolution, no node execution — just
    topology + historical-stats lookup), so the placeholder values are
    never observed. We just need compile_workflow's required-input check
    to pass.
    """
    declared = child_ir.get("inputs") or {}
    if not isinstance(declared, dict):
        return {}
    placeholders: dict[str, Any] = {}
    for name, spec in declared.items():
        type_name = spec.get("type") if isinstance(spec, dict) else None
        placeholders[name] = _TYPE_PLACEHOLDERS.get(str(type_name))
    return placeholders


def _effective_child_inputs(
    child_ir: dict[str, Any],
    child_inputs: dict[str, Any],
    *,
    downstream: bool,
) -> dict[str, Any]:
    """Return the inputs dict to pass to the child compiler.

    In downstream mode, substitute placeholder values so compile-time
    required-input checks pass (parent's upstream is dirty, real values
    aren't available, BFS-from-start never reads them). In normal mode,
    pass the caller-provided inputs through untouched — missing required
    inputs SHOULD fail loudly there.
    """
    if downstream:
        return _placeholder_child_inputs(child_ir)
    return child_inputs


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
    """Entry for a sub-workflow that failed at resolve / validate / cycle check.

    Severity is ERROR: each of the four call sites (max-depth exceeded,
    resolve exception, circular reference, bad `inputs:` shape) represents
    a workflow the engine would fail at runtime. `_display_plan_result`
    uses diagnostic severity to decide the CLI exit code — ERROR here
    ensures `--dry-run` exits 1 for these cases, matching the spec's
    "MUST exit 1 when the plan cannot be built" contract and the
    convention shared with `_template_error_entry` and
    `_compile_error_entry` (both also ERROR). Agents cost-gating via
    `exit != 0` need this signal to abort on broken workflow topology.
    """
    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="execute",
        cause="template_error",
        diagnostic=Diagnostic(
            severity=Severity.ERROR,
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
    opaque_count: int


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
            opaque_count=totals.opaque_count,
            cost_basis=cost_basis,
        )

    nested_total = totals.total
    nested_cached = totals.cached_count
    nested_execute = totals.execute_count
    nested_by_type: dict[str, int] = dict(totals.execute_by_type)
    nested_cost = totals.estimated_cost_usd
    nested_nwh = totals.nodes_without_history
    nested_duration = totals.estimated_duration_ms
    nested_nwdh = totals.nodes_without_duration_history
    nested_opaque = totals.opaque_count
    effective_basis = cost_basis

    for entry in entries:
        if entry.sub_plan is None:
            continue
        child = entry.sub_plan.summary
        nested_total += child.total_including_nested or child.total
        nested_cached += child.cached_including_nested or child.cached_count
        nested_execute += child.execute_including_nested or child.execute_count
        child_types = child.execute_by_type_including_nested or child.execute_by_type
        for node_type, count in child_types.items():
            nested_by_type[node_type] = nested_by_type.get(node_type, 0) + count
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
        nested_opaque += (
            child.opaque_count_including_nested
            if child.opaque_count_including_nested is not None
            else child.opaque_count
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
        opaque_count=totals.opaque_count,
        cost_basis=effective_basis,
        total_including_nested=nested_total,
        cached_including_nested=nested_cached,
        execute_including_nested=nested_execute,
        execute_by_type_including_nested=nested_by_type,
        estimated_cost_usd_including_nested=nested_cost,
        nodes_without_history_including_nested=nested_nwh,
        estimated_duration_ms_including_nested=nested_duration,
        nodes_without_duration_history_including_nested=nested_nwdh,
        opaque_count_including_nested=nested_opaque,
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
    opaque_count = 0

    for entry in entries:
        if entry.status == "cached":
            cached_count += 1

        if entry.status == "opaque":
            opaque_count += 1

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
        opaque_count=opaque_count,
    )
