"""Workflow execution engine.

Replaces Flow._orch() + all 4 wrappers. One class that walks the node graph
and handles all runtime concerns (template resolution, namespacing, caching,
tracing, batch iteration, progress callbacks) directly during traversal.

Key design decisions:
- _execute_single_node returns a tuple (action, last_resolutions, template_errors)
  — NO instance state. This prevents data races in parallel batch.
- Shared store is the single source of runtime data — no initial_params override.
- Template resolution happens EARLY in _execute_node — before cache check.
  The resolved params are used for both cache key computation AND param setting.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType
from typing import Any, Literal

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import (
    CompilationError,
    GateDenied,
    GateNotInteractiveError,
    GateResolverError,
    LoopCarryError,
    LoopConditionError,
    ResumeNotResumableError,
)
from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.prompt_cache import CacheRenderContext
from pflow.core.validation_utils import VALIDATION_PLACEHOLDER
from pflow.runtime.node_state import (
    FAILURE_CATEGORY_EXCEPTION,
    FAILURE_CATEGORY_HTTP,
    FAILURE_CATEGORY_LLM,
    FAILURE_CATEGORY_MCP,
    FAILURE_CATEGORY_NODE_ERROR,
    FAILURE_CATEGORY_ROUTING,
    FAILURE_CATEGORY_SHELL,
    FAILURE_CATEGORY_TEMPLATE,
    get_node_failure,
    mark_node_failed,
)
from pflow.runtime.template_resolver import TemplateResolver

from .api_warning_detector import detect_api_warning
from .batch_executor import _collect_batch_trace, execute_batch
from .gate import detect_escalation, run_approval_gate, run_escalation_gate, scan_batch_escalations
from .instrumentation import (
    apply_memo_hit,
    cache_result,
    call_completion_callback,
    call_start_callback,
    enforce_loop_guard,
    handle_api_warning,
    handle_cached_execution,
    initialize_execution_state,
    invalidate_cache,
    record_trace,
    write_memo_cache,
)
from .loop_control import evaluate_loop_condition, is_carry_iteration, loop_runtime_scope, resolve_loop_cap
from .namespaced_store import NamespacedSharedStore
from .plan_node import NodePlan, plan_node
from .template_resolution import contains_unresolved_template, resolve_templates
from .types import CompiledWorkflow, NodeConfig

# Map node class names to failure categories for step 17.5 (error-action
# path). The node type is known at compile time — no data-shape heuristic
# needed. Unlisted types fall back to FAILURE_CATEGORY_NODE_ERROR.
_NODE_TYPE_FAILURE_CATEGORY: dict[str, str] = {
    "ShellNode": FAILURE_CATEGORY_SHELL,
    "HttpNode": FAILURE_CATEGORY_HTTP,
    "MCPNode": FAILURE_CATEGORY_MCP,
    "LLMNode": FAILURE_CATEGORY_LLM,
}

# Actions that represent a clean-success verdict — the node made no failure or
# routing decision of its own. The api_warning detector only UPGRADES these into
# failures (a node that returned "default" but whose output betrays a silent API
# error, e.g. Slack ok:false in a 200). Any other action — an "error", or a
# deliberate custom route like error_action's "continue" — is the node speaking
# for itself, and must not be second-guessed by the detector. See GH #301 / #474.
# "end" counts as clean-success: it is an intentional-termination directive, not a
# failure acknowledgement, so a silent API error in its output should still surface.
# The gate covers ANY non-clean action, not only the "error"/"continue" cases #301/#474
# named — a deliberate verdict of any kind wins. Safe today because no node returns a
# custom routing action together with detector-matchable output (HTTP/MCP/Slack/GraphQL
# payloads only ever ride "default"/"error"); revisit this gate if a future node does.
_CLEAN_SUCCESS_ACTIONS = frozenset({"", "default", "end"})

# Read-only empty mapping used to restore ``__pflow_prompt_cache__`` after a
# child engine.run completes when the parent had no value installed. Module
# level so deeply-nested sub-workflow restores don't allocate per call.
_EMPTY_PROMPT_CACHE: Mapping[str, CacheRenderContext] = MappingProxyType({})


def _diagnose_carry_ref(template: str, node_id: str, latest: Any) -> tuple[str, list[str], str] | None:
    """For a simple self-ref carry ``${node_id.a.b...}``, walk the loop node's latest
    output along the WHOLE path and, if a segment is absent, return
    ``(missing_path, available_keys_at_that_level, resolved_prefix)``; else ``None``.

    Unlike a first-segment-only check, this diagnoses NESTED refs — a ``code`` body's
    ``${tick.result.next}`` (``result`` exists but has no ``next``) is reported at the
    ``result.next`` level with ``result``'s keys as the available outputs, so the most
    common inline carry shape gets the carry-aware message instead of falling through
    to the generic ``inputs:`` template error.

    Conservative by construction — returns ``None`` (defer to the value-based permissive
    check / generic strict error) for:
    - coalesce/complex refs (their ``??`` fallback may resolve);
    - a bare ``${node_id}`` whole-output carry (never "absent");
    - any path that descends through a NON-dict value (e.g. a JSON string or list),
      which might still resolve at runtime — never claim absence we can't prove.
    """
    if not isinstance(latest, dict):
        return None
    var = TemplateResolver.extract_simple_template_var(template)
    if var is None or TemplateResolver.is_coalesce_expression(var):
        return None
    prefix = f"{node_id}."
    if not var.startswith(prefix):
        return None
    # Path after the node id; strip any [index] suffix per segment (dict-keyed walk).
    segments = [seg.split("[", 1)[0] for seg in var[len(prefix) :].split(".") if seg]
    current: Any = latest
    walked: list[str] = []
    for seg in segments:
        if not isinstance(current, dict):
            return None  # descends into a non-dict — may still resolve; defer
        if seg not in current:
            return (".".join([*walked, seg]), _loop_available_outputs(current), ".".join(walked))
        walked.append(seg)
        current = current[seg]
    return None  # fully resolved — not a carry failure


def _loop_available_outputs(latest: Any) -> list[str]:
    """The output keys an agent can carry from a given output level — minus engine-internal ones."""
    if not isinstance(latest, dict):
        return []
    return sorted(k for k in latest if not str(k).startswith("_") and k != "loop_stopped")


def _carry_unresolved_error(
    node_id: str, key: str, template: str, missing_path: str | None, available: list[str], parent_prefix: str
) -> LoopCarryError:
    avail_str = ", ".join(available) if available else "(none)"
    produced = f"output '{missing_path}'" if missing_path else "the carried output"
    if available:
        # Reconstruct the correct ref depth so the example is paste-able for nested
        # (code) bodies too: ${node.result.done}, not the wrong top-level ${node.done}.
        ref_root = f"{node_id}.{parent_prefix}." if parent_prefix else f"{node_id}."
        fix = (
            "A carried input is fed from this loop node's own output each iteration. "
            f"Reference one of its outputs ({avail_str}) — e.g. `{key}: ${{{ref_root}{available[0]}}}` — "
            "or have the loop node emit that output."
        )
    else:
        fix = (
            "A carried input is fed from this loop node's own output each iteration. "
            "Reference a declared output of the loop, or have the loop node emit the carried value."
        )
    return LoopCarryError(
        f"Loop '{node_id}': carried input '{key}' could not be resolved — loop node "
        f"'{node_id}' did not produce {produced} this iteration (carried via {template}). "
        f"Available outputs: {avail_str}.",
        node_id=node_id,
        suggestion=fix,
    )


def _assert_carried_inputs_resolved(config: NodeConfig, plan: NodePlan, shared: dict[str, Any]) -> None:
    """Make a carried output the body didn't produce this iteration fail LOUD and
    CARRY-AWARE in every template-resolution mode.

    Carry is structural plumbing, so an unresolved carried input must raise a
    ``LoopCarryError`` that names the loop node and lists its available outputs —
    never a generic ``inputs:`` template error (strict) nor a silent literal
    (permissive). Two detection paths feed one message:

    - resolved (permissive, or a clean strict miss): ``plan.resolved_params`` is
      populated; a carried key absent from, or still holding its ``${...}`` ref in,
      the resolved inputs is unresolved.
    - strict failure: ``plan_node`` raised (``plan.template_exception`` set, no
      resolved params); a carried *self-reference* whose output the body omitted is
      the failure. Coalesce/complex refs are deferred to the generic error.
    """
    carry = config.loop_config.carry if config.loop_config is not None else {}
    if not carry:
        return
    node_id = config.node_id
    latest = shared.get(node_id)
    available = _loop_available_outputs(latest)

    resolved_params = plan.resolved_params
    resolved_inputs = resolved_params.get("inputs") if isinstance(resolved_params, dict) else None
    if not isinstance(resolved_inputs, dict):
        resolved_inputs = None

    # Resolved cleanly but produced no inputs mapping — structural (shouldn't happen for
    # a validated carry loop, but keep the loud guard instead of silently skipping).
    if resolved_inputs is None and plan.template_exception is None:
        raise LoopCarryError(
            f"Loop '{node_id}' carried inputs could not be resolved because the node produced no inputs mapping.",
            node_id=node_id,
            suggestion="Seed every carried key in the node's `inputs:` mapping.",
        )

    for key, template in carry.items():
        diag = _diagnose_carry_ref(template, node_id, latest)
        if resolved_inputs is not None:
            unresolved = key not in resolved_inputs or contains_unresolved_template(resolved_inputs[key], template)
        else:
            # strict: plan_node raised before resolving — only flag a self-ref whose
            # output the body demonstrably omitted (so an unrelated template error
            # isn't masked by a misleading carry message; it falls through to raise).
            unresolved = plan.template_exception is not None and diag is not None
        if unresolved:
            if diag is not None:
                missing_path, key_available, parent_prefix = diag
            else:
                # coalesce/complex ref, or a non-dict descent we won't guess at:
                # name no specific field; list the loop node's top-level outputs.
                missing_path, key_available, parent_prefix = None, available, ""
            raise _carry_unresolved_error(node_id, key, template, missing_path, key_available, parent_prefix)


def build_prompt_cache_dict(
    workflow: CompiledWorkflow,
    shared: dict[str, Any],
) -> dict[str, CacheRenderContext]:
    """Build the per-node ``CacheRenderContext`` map for one engine.run.

    Includes only LLM nodes that have at least one cache-relevant declaration
    (``prompt_cache_items``, ``prewarm``, or a workflow-level ``## Cache``
    block). Sparse by design — non-cache workflows produce an empty dict and
    consumers (`plan_node`, `LLMNode.prep`) read via the canonical
    ``(shared.get(K) or {}).get(node_id)`` defensive pattern.
    """
    cache_block = workflow.cache_block
    out: dict[str, CacheRenderContext] = {}
    for node_id, config in workflow.node_configs.items():
        if config.node_type_name != "LLMNode":
            continue
        if not (config.prompt_cache_items or config.prewarm or cache_block):
            continue
        prewarm = config.prewarm
        if _should_disable_below_min_prewarm(node_id, config, shared):
            prewarm = False
        out[node_id] = _make_prompt_cache_context(config, cache_block, prewarm=prewarm)
    return out


def _make_prompt_cache_context(
    config: NodeConfig,
    cache_block: Any,
    *,
    prewarm: bool | None = None,
) -> CacheRenderContext:
    """Build one node's ``CacheRenderContext`` from its ``NodeConfig``.

    ``unresolved_batch_prompt`` and ``batch_alias`` are populated only for
    batch LLM nodes (D.1 auto-prefix detection reads them); non-batch nodes
    get ``None`` for both.
    """
    unresolved = None
    alias = None
    node_inputs = None
    if config.batch_config and config.template_config:
        unresolved = config.template_config.template_params.get("prompt") or config.template_config.static_params.get(
            "prompt"
        )
        alias = config.batch_config.item_alias
        raw_inputs = _node_inputs_from_config(config)
        if isinstance(raw_inputs, Mapping):
            # Snapshot + freeze for parallel-batch safety. CacheRenderContext
            # is shared by batch workers, so the immutability contract is
            # explicit even though template_params is compile-time data.
            node_inputs = MappingProxyType(dict(raw_inputs))
    return CacheRenderContext(
        cache_block=cache_block,
        subset=config.prompt_cache_items,
        prewarm=config.prewarm if prewarm is None else prewarm,
        unresolved_batch_prompt=unresolved,
        batch_alias=alias,
        node_inputs=node_inputs,
    )


def _should_disable_below_min_prewarm(
    node_id: str,
    config: NodeConfig,
    shared: dict[str, Any],
) -> bool:
    if not config.prewarm or config.batch_config is None or config.template_config is None:
        return False
    if config.prompt_cache_items:
        # Per-call _strip_below_min_cache_markers is authoritative for combined channels.
        return False

    model_raw = config.template_config.template_params.get("model") or config.template_config.static_params.get("model")
    if model_raw is None:
        return False
    model = _resolve_template_string(model_raw, shared)
    if model is None or model == VALIDATION_PLACEHOLDER:
        return False

    prompt_raw = config.template_config.template_params.get("prompt") or config.template_config.static_params.get(
        "prompt"
    )
    if not isinstance(prompt_raw, str):
        return False

    from pflow.core.prompt_cache_analysis.below_min_tokens_detector import is_below_min_cache, provider_note
    from pflow.core.prompt_cache_analysis.context import AnalysisContext
    from pflow.core.prompt_cache_analysis.token_estimation import tokenize_prompt_region_lower_bound
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic
    from pflow.core.prompt_refs import first_per_item_position

    alias = config.batch_config.item_alias
    first = first_per_item_position(prompt_raw, alias, _node_inputs_from_config(config))
    if first is None or first <= 0:
        return False

    ctx = AnalysisContext.build(
        workflow_ir={},
        parameters=shared,
        memo_cache=shared.get("__memoization_cache__"),
        workflow_path=shared.get("_pflow_workflow_file"),
    )
    prefix_tokens, unresolved_refs = tokenize_prompt_region_lower_bound(prompt_raw[:first], model=model, ctx=ctx)
    if unresolved_refs:
        return False
    if not is_below_min_cache(model, prefix_tokens):
        return False

    diagnostic = make_diagnostic(
        "cache.prewarm-disabled-below-min",
        node_id=node_id,
        affected_workflow=shared.get("_pflow_workflow_file") or "<unknown>",
        model=model,
        cacheable_tokens=prefix_tokens,
        min_tokens=get_min_cache_tokens(model),
        provider_note=provider_note(model),
        alias=alias,
    )
    shared.setdefault("__warnings__", {})[node_id] = diagnostic
    shared.setdefault("__prewarm_disabled_below_min__", {})[node_id] = "below_min"
    return True


def _node_inputs_from_config(config: NodeConfig) -> Mapping[str, Any] | None:
    template_config = config.template_config
    if template_config is None:
        return None
    raw_inputs = template_config.template_params.get("inputs") or template_config.static_params.get("inputs")
    return raw_inputs if isinstance(raw_inputs, Mapping) else None


def _resolve_template_string(raw: Any, shared: dict[str, Any]) -> str | None:
    if not isinstance(raw, str):
        return str(raw) if raw is not None else None
    try:
        resolved = TemplateResolver.resolve_template(raw, shared)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(resolved, str) or TemplateResolver.TEMPLATE_PATTERN.search(resolved):
        return None
    return resolved


def parse_only_path(only_node: str | None) -> tuple[str | None, str | None]:
    """Split a dotted ``--only`` path into (this_level, child_level).

    ``'a.b.c'`` → ``('a', 'b.c')``.  No dots → ``(value, None)``.
    ``None`` → ``(None, None)``.

    Raises ``CompilationError`` on malformed paths (empty segments from
    leading/trailing dots like ``'.b'``, ``'a.'``, or ``'a..b'``).
    """
    if only_node is None or "." not in only_node:
        return only_node, None
    if ".." in only_node:
        raise CompilationError(
            f"Invalid --only path: '{only_node}' contains an empty segment",
            phase="only_node_resolution",
            suggestion="Use 'parent-node.child-node' format, e.g. '--only my-workflow.target-step'.",
        )
    first, remaining = only_node.split(".", 1)
    if not first or not remaining:
        raise CompilationError(
            f"Invalid --only path: '{only_node}' contains an empty segment",
            phase="only_node_resolution",
            suggestion="Use 'parent-node.child-node' format, e.g. '--only my-workflow.target-step'.",
        )
    return first, remaining


def validate_only_target(workflow: CompiledWorkflow, only_node: str | None) -> tuple[str | None, str | None]:
    """Parse and validate an ``--only`` target; return ``(this_only, child_only)``.

    Shared between the runtime engine (``WorkflowEngine._run_inner``) and the
    dry-run planner (``execution/plan.py::_build_plan_with_shared``) so ``run``
    and ``plan`` reject identical ``--only`` values with identical
    ``CompilationError`` text and category.

    Ordering is load-bearing: the membership check runs FIRST so ``--only
    typo.child`` still reports "not found" with the available-nodes list,
    while ``--only realnode.child`` reports the "not supported" message.
    Targeting a node inside a sub-workflow is deferred (see issue #443 plan
    "Deferred"); under snapshot ``--only`` it's an explicit error rather than
    a silent re-walk.

    ``None`` returns ``(None, None)`` without validating. An empty string is
    a hard error ("Node '' not found") — never a silent full run; malformed
    agent input must fail loudly.

    ``child_only`` is currently ALWAYS ``None`` on successful return — dotted
    targets raise above. The tuple shape is reserved for the deferred
    nested-targeting follow-up (issue #443, "the dotted plumbing exists
    dormant").
    """
    this_only, child_only = parse_only_path(only_node)
    if this_only is None:
        return None, None
    if this_only not in workflow.node_configs:
        available = sorted(workflow.node_configs.keys())
        raise CompilationError(
            f"Node '{this_only}' not found",
            phase="only_node_resolution",
            details={"available_nodes": available},
            suggestion=f"Available nodes: {', '.join(available)}",
        )
    if child_only:
        raise CompilationError(
            f"--only '{only_node}': targeting a nested node (dotted path) is not supported under snapshot --only.",
            phase="only_node_resolution",
            suggestion=f"Run --only '{this_only}' to run that node alone, or run the full workflow.",
        )
    return this_only, child_only


def is_clean_termination(action: str | None, successors: dict[str, Any]) -> bool:
    """Whether the graph walk should clean-terminate after a node returns `action`.

    Shared predicate between the runtime engine (`_handle_no_successor` —
    called when no successor matches the action) and the dry-run planner's
    `_classify`. Centralized here so termination semantics can't drift.

    Two cases count as clean termination:
    - `action == "end"` — the intentional-termination sentinel a node can
      return to stop the walk without a routing error.
    - All successor edges are on-error handlers (`all(k == "error" ...)`)
      — no forward path exists; falling off the end is clean.

    Returns `True` for clean termination, `False` when the missing-successor
    condition should surface as a routing error.
    """
    return action == "end" or all(k == "error" for k in successors)


class RouteKind(Enum):
    """Outcome categories of ``route_action``."""

    FOLLOW = auto()
    CLEAN_STOP = auto()
    ROUTING_ERROR = auto()


@dataclass(frozen=True)
class RouteDecision:
    """Result of ``route_action``. ``next_node`` is set only for FOLLOW."""

    kind: RouteKind
    next_node: Any = None


def route_action(action: str | None, successors: dict[str, Any]) -> RouteDecision:
    """Pure routing kernel: where does the walk go after a node yields ``action``?

    Shared between the runtime engine (``WorkflowEngine._run_inner``'s
    successor step) and the dry-run planner's ``_classify``
    (``execution/plan.py``), so the precedence rule — successor match wins,
    then clean termination (via ``is_clean_termination``), else routing
    error — is expressed exactly once. Side effects stay with the callers:
    the engine maps ROUTING_ERROR to ``_handle_no_successor`` (failure
    archive, cache invalidation, trace flip); the planner overlays its
    BOUNDARY concept on top via ``_represents_work``.

    ``action`` is taken as-is by design (critical asymmetry): the engine
    feeds the live action string (possibly None — the lookup falls back to
    "default"); the planner feeds the cached action for cached entries and
    "default" for everything else. Each caller decides what action means.

    ``.get(...) is None`` is the official no-successor test: successors only
    ever hold node objects (``BaseNode.next()`` is the single write site, and
    no node class defines ``__bool__``/``__len__``), so no falsy-but-present
    successor is constructible.
    """
    nxt = successors.get(action or "default")
    if nxt is not None:
        return RouteDecision(RouteKind.FOLLOW, nxt)
    if is_clean_termination(action, successors):
        return RouteDecision(RouteKind.CLEAN_STOP)
    return RouteDecision(RouteKind.ROUTING_ERROR)


def find_node_by_id(start_node: Any, node_id: str) -> Any:
    """BFS the compiled graph from ``start_node`` for the node whose ``.node_id`` matches.

    Used by ``--only`` snapshot execution (engine + planner): the normal walk
    reaches nodes by following ``.successors``, but ``--only`` jumps straight to
    the target after seeding upstream from a snapshot, so it needs the target's
    bare node object directly. Cycle-guarded via object identity. Raises
    ``CompilationError`` when ``node_id`` is unreachable from ``start_node`` —
    fail-loud, since callers have already validated the id against
    ``node_configs``, so unreachability means a compiler/graph bug, not user
    error.
    """
    from collections import deque

    seen: set[int] = set()
    queue: deque[Any] = deque([start_node])
    while queue:
        node = queue.popleft()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        if getattr(node, "node_id", None) == node_id:
            return node
        for successor in node.successors.values():
            queue.append(successor)
    raise CompilationError(
        f"--only target '{node_id}' is not reachable from the workflow start node.",
        phase="only_node_resolution",
        suggestion="This indicates a compiler/graph bug — the node exists in node_configs "
        "but isn't wired into the graph.",
    )


def seed_walk_entry(
    shared: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    entry: str,
    start_node: Any,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """Seed upstream outputs from a prior run's events and locate the walk entry node.

    The shared "seed + locate-entry" composition (Task 164 Phase 0), used by
    BOTH the runtime engine (``_run_only_snapshot``) and the dry-run planner
    (``execution/plan.py::_resolve_walk_start``) so entry/seeding semantics
    cannot drift between the preview and the run — pinned by
    ``test_engine_and_planner_walk_entry_state_match``. Resume (engine
    re-entry + planner resume view) becomes additional callers of this exact
    composition.

    Returns ``(entry_node, seeded_final_events_by_node)``. Deliberately
    NOTHING else is shared here (scope guard: if this grows a mode flag or
    callback, back off): loading events, ``initialize_execution_state``,
    ``restored_nodes``/``only_node`` stamping, and degraded advisories all
    stay caller-side — they differ per surface by design.
    """
    from pflow.runtime.workflow_trace import seed_snapshot_into_shared

    final = seed_snapshot_into_shared(shared, events, exclude=entry)
    return find_node_by_id(start_node, entry), final


def build_snapshot_degraded_diagnostic(this_only: str, *, source: Literal["planner", "runtime"]) -> Diagnostic:
    """Build the ``only.snapshot-degraded`` WARNING ``Diagnostic``.

    Shared between the engine's ``_emit_snapshot_degraded_advisory`` (sink:
    ``__warnings__["__only_snapshot__"]`` → DEGRADED status) and the dry-run
    planner's ``_resolve_walk_start`` (``execution/plan.py``; sink: the plan's
    diagnostics list), so id / title / suggestions cannot drift between the
    preview and the run. Message tense differs by design: the planner speaks
    future-conditional ("would restore"), the engine past ("restored"). The
    planner variant carries ``context={"category": "execution_failure"}``;
    the runtime variant keeps ``context=None`` (the Diagnostic default).
    """
    verb = "would restore" if source == "planner" else "restored"
    return Diagnostic(
        severity=Severity.WARNING,
        title="Restored upstream from a degraded run",
        message=(
            f"--only '{this_only}' {verb} upstream from a DEGRADED full run; the restored "
            f"upstream data may be incomplete (e.g. a batch step that continued past failed "
            f"items dropped them from its results). Re-run the full workflow to refresh the snapshot."
        ),
        suggestions=[
            "Re-run the full workflow once to record a clean (success) snapshot, then retry --only.",
        ],
        node_id=this_only,
        source=source,
        context={"category": "execution_failure"} if source == "planner" else None,
        id="only.snapshot-degraded",
    )


class WorkflowEngine:
    """Executes a CompiledWorkflow by walking the node graph and handling all runtime concerns."""

    def __init__(
        self,
        metrics_collector: Any | None = None,
        trace_collector: Any | None = None,
        only_node: str | None = None,
        workflow_path: str | None = None,
        snapshot_events: list[dict] | None = None,
        resume_from: str | None = None,
        resume_events: list[dict] | None = None,
        resume_source_id: str | None = None,
    ):
        if resume_from is not None and only_node is not None:
            raise ValueError("resume_from and only_node are mutually exclusive")
        self.metrics = metrics_collector
        self.trace = trace_collector
        self.only_node = only_node
        # issue #443: identifier used to locate the most-recent full-run trace
        # for ``--only`` snapshot reuse (resolved file path or ``ir-hash:<md5>``
        # for inline runs — byte-identical to the trace collector's
        # ``workflow_path``). ``snapshot_events`` lets callers/tests inject the
        # upstream events directly, bypassing the on-disk lookup. Both default
        # ``None`` — many construction sites rely on the defaults.
        self.workflow_path = workflow_path
        self.snapshot_events = snapshot_events
        # Task 164: resume re-entry, mirroring the only_node/snapshot_events
        # precedent. ``resume_from`` = the failed node K to re-enter the walk at;
        # ``resume_events`` = the source trace's top-level events to seed
        # upstream from (``ResumeSource.events``); ``resume_source_id`` = the
        # source run's execution_id, stamped into ``__execution__`` for the
        # display/JSON surface. All default ``None`` (normal full run).
        self.resume_from = resume_from
        self.resume_events = resume_events
        self.resume_source_id = resume_source_id

    def _run_node_with_child_only(
        self, node: Any, config: NodeConfig, shared: dict[str, Any], child_only: str | None
    ) -> str:
        """Execute a node, injecting ``_pflow_child_only_node`` for sub-workflow targeting.

        The key is written before and cleaned up after execution (including on
        exception) so it never leaks into ``shared_after``.
        """
        if child_only:
            shared["_pflow_child_only_node"] = child_only
        try:
            return self._execute_node(node, config, shared)
        finally:
            if child_only:
                shared.pop("_pflow_child_only_node", None)

    def run(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> str:
        """Execute a compiled workflow. Returns action string.

        Installs ``self.trace`` into ``shared["__trace_collector__"]`` and a
        per-workflow ``CacheRenderContext`` map into
        ``shared["__pflow_prompt_cache__"]`` for the duration of the run.
        The save/restore pattern correctly handles nested sub-workflow runs
        (parent's values reinstated after a child engine.run completes).
        """
        # Install this engine's trace collector so LLMNode.prep() can find
        # it. Save+restore handles nested sub-workflow runs (parent's
        # collector reinstated after a child engine.run completes).
        #
        # Write-back form (not .pop()) because shared may be a
        # NamespacedSharedStore (sub-workflow path) which doesn't implement
        # pop. All consumers of __trace_collector__ use .get() (verified by
        # grep — runner.py, success_formatter.py, error_formatter.py,
        # cli/error_output.py, workflow_executor.py), so writing None back
        # when the key was originally absent is indistinguishable from
        # absence to every reader.
        # Task 159 B3.2: install per-workflow CacheRenderContext map. Always
        # install (even when the dict is empty) so child engine.run masks the
        # parent's value during sub-workflow execution. MappingProxyType
        # enforces read-only at the call sites; consumers use the
        # ``(shared.get(K) or {}).get(node_id)`` defensive pattern. On
        # restore-from-absent, write the module-level _EMPTY_PROMPT_CACHE
        # constant rather than ``None`` so a future consumer that drops the
        # ``or {}`` defense hits a Mapping, not None.get(...).
        #
        # Build BEFORE installing anything so an exception during
        # ``build_prompt_cache_dict`` leaves shared completely unchanged —
        # otherwise a build-time exception would leak the trace install
        # (saved_trace overwritten, finally never fires).
        saved_trace = shared.get("__trace_collector__")
        saved_prompt_cache = shared.get("__pflow_prompt_cache__")
        new_prompt_cache = MappingProxyType(build_prompt_cache_dict(workflow, shared))
        if self.trace is not None:
            shared["__trace_collector__"] = self.trace
            # 2.4.0: stamp the run's ``--only`` target (None for a full run) so the saved trace excludes
            # itself as a snapshot source when it's an ``--only`` run. Only the ROOT engine (depth 0)
            # stamps it — a nested sub-workflow engine REUSES the same run-scoped collector (Task 172) and
            # must not clobber the root's target to its own ``None``, or an ``--only <sub-workflow>`` trace
            # would masquerade as a full-run snapshot source (issue #443).
            if shared.get("_pflow_depth", 0) == 0:
                self.trace.only_node = self.only_node
                # Task 173 (A1): open the streamed trace eagerly so the file + meta line exist from t=0
                # — a live overlay can discover this run before its first node completes. AFTER the
                # only_node stamp so meta records the right target; idempotent + gated (no-op for
                # MCP/--no-trace and under the pytest trace_files gate).
                self.trace.start_streaming()
        shared["__pflow_prompt_cache__"] = new_prompt_cache
        try:
            return self._run_inner(workflow, shared)
        finally:
            shared["__trace_collector__"] = saved_trace
            shared["__pflow_prompt_cache__"] = (
                saved_prompt_cache if saved_prompt_cache is not None else _EMPTY_PROMPT_CACHE
            )

    def _run_inner(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> str:
        """Run body — split out so run() can wrap with save/restore cleanly."""
        # 0. --only: snapshot semantics (issue #443). Do NOT re-walk the graph —
        # that re-executes and re-fires side-effecting upstream nodes (e.g.
        # `gh pr create`) on every iteration. Instead restore upstream from the
        # most recent full run's trace and execute ONLY the target.
        # validate_only_target rejects unknown ids and dotted (nested) targets
        # first; a missing snapshot is a hard error, never a silent re-walk.
        this_only, _ = validate_only_target(workflow, self.only_node)
        if this_only is not None:
            return self._run_only_snapshot(workflow, shared, this_only)

        # 1. Reset visit counts
        if "__execution__" in shared and "node_visit_counts" in shared["__execution__"]:
            shared["__execution__"]["node_visit_counts"] = {}

        # 2. Walk graph, entering at the start node — or at the failed node K
        # when resuming (Task 164: a parameterized entry into the one loop,
        # never a second traversal).
        curr = self._walk_entry(workflow, shared)
        last_action = None
        # issue #445: per-node loop iteration counters (the loop's OWN count,
        # distinct from the hard ``node_visit_counts`` guard) and resolved caps.
        loop_counts: dict[str, int] = {}
        loop_caps: dict[str, int] = {}
        try:
            while curr is not None:
                node_id = getattr(curr, "node_id", None)
                if node_id is None or node_id not in workflow.node_configs:
                    raise CompilationError(
                        "Node in graph has no node_id or missing from node_configs",
                        phase="execution",
                        suggestion="This indicates a compiler bug",
                    )

                config = workflow.node_configs[node_id]

                # issue #445: expose 1-based ${__iteration__} for the loop body and
                # raise __loop_active__ (suppresses inner memo reads) for the duration
                # of this iteration. The scope keeps __iteration__ across re-entry
                # (cleared by the re-entry logic / outer finally below), so
                # clear_iteration_on_exit=False here.
                is_loop = config.loop_config is not None
                iteration: int | None = None
                if is_loop:
                    loop_counts[node_id] = loop_counts.get(node_id, 0) + 1
                    iteration = loop_counts[node_id]

                # The walk is full-run-only now: --only is handled by
                # _run_only_snapshot above. _run_node_with_child_only stays
                # dormant (always passed None) so the dotted-child plumbing is
                # ready for the deferred nested-targeting follow-up.
                with loop_runtime_scope(shared, is_loop, iteration=iteration, clear_iteration_on_exit=False):
                    last_action = self._run_node_with_child_only(curr, config, shared, None)

                # issue #445: loop re-entry. Re-enter only on the normal-return
                # path (never when the node errored) when the condition is truthy
                # and under the cap — ``continue`` re-enters ``while curr:`` so
                # enforce_loop_guard fires for visit N+1. Otherwise the loop is
                # done (drained, capped, OR errored): clear ${__iteration__} before
                # routing so neither a post-loop node NOR an on-error handler reads
                # a stale value, then fall through to normal successor routing.
                if config.loop_config is not None:
                    if not str(last_action or "").startswith("error") and self._loop_should_reenter(
                        config, shared, node_id, loop_counts, loop_caps
                    ):
                        continue
                    shared.pop("__iteration__", None)

                # Follow successor edge (shared routing kernel — see route_action)
                decision = route_action(last_action, curr.successors)
                if decision.kind is not RouteKind.FOLLOW:
                    if decision.kind is RouteKind.ROUTING_ERROR:
                        # Assignment is load-bearing: _handle_no_successor returns
                        # "error" so the run's action string reflects the failure
                        # (WorkflowExecutor checks it for child success).
                        last_action = self._handle_no_successor(last_action, node_id, curr, shared)
                    break
                curr = decision.next_node
        finally:
            # Defensive: an error mid-loop never leaks ${__iteration__} into the
            # surfaced shared_after. The clean-exit path already popped it above.
            shared.pop("__iteration__", None)

        # 3. Populate declared outputs
        self._populate_outputs(workflow, shared, last_action)

        return str(last_action) if last_action else "default"

    def _run_only_snapshot(self, workflow: CompiledWorkflow, shared: dict[str, Any], this_only: str) -> str:
        """Execute ONLY the target node against a frozen upstream snapshot (issue #443).

        Snapshot semantics for FLAT ``--only`` (dotted is rejected upstream by
        ``validate_only_target``). Rather than re-walking from the start node —
        which re-executes and re-fires side-effecting upstream nodes on every
        iteration — restore every upstream node's output from the most recent
        full successful run's trace, then execute only ``this_only``. Upstream is
        reused, never re-run.

        No usable snapshot → ``OnlySnapshotMissingError`` (never a silent
        re-walk). A ``loop:`` target runs a single iteration. Restored nodes are
        recorded in ``__execution__["restored_nodes"]`` so the display layer
        reports them as ``not_executed`` rather than executed, even though
        seeding ``shared[node_id]`` makes ``get_node_status`` SUCCEEDED (correct
        for data-flow: templates, coalesce, and ``## Cache`` rendering SHOULD see
        the restored values).
        """
        from pflow.runtime.workflow_trace import load_snapshot_or_raise

        events, source_status = load_snapshot_or_raise(
            self.workflow_path, this_only, snapshot_events=self.snapshot_events
        )
        target_node, final = seed_walk_entry(shared, events, entry=this_only, start_node=workflow.start_node)

        initialize_execution_state(shared)
        shared["__execution__"]["restored_nodes"] = [nid for nid in final if nid != this_only]

        if source_status == "degraded":
            self._emit_snapshot_degraded_advisory(shared, this_only)

        config = workflow.node_configs[this_only]
        is_loop = config.loop_config is not None
        with loop_runtime_scope(shared, is_loop, iteration=1 if is_loop else None, clear_iteration_on_exit=True):
            last_action = self._execute_node(target_node, config, shared)

        # __execution__["only_node"] was written by _execute_node step 2, so
        # output routing (find_only_output) stays target-scoped. Resolvable
        # declared outputs are populated; unresolvable ones are swallowed under
        # --only by _populate_outputs.
        self._populate_outputs(workflow, shared, last_action)
        return str(last_action) if last_action else "default"

    def _walk_entry(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> Any:
        """Return the walk's entry node: ``start_node``, or K when resuming (Task 164)."""
        if self.resume_from is not None:
            return self._prepare_resume(workflow, shared)
        return workflow.start_node

    def _prepare_resume(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> Any:
        """Seed upstream from the source trace and return the walk entry node K (Task 164).

        Runs inside ``_run_inner`` on the main thread, after ``start_streaming()``
        — the re-recorded restored events flush right after the meta line. The
        seed → ``initialize_execution_state`` → stamp ordering mirrors
        ``_run_only_snapshot``'s load-bearing prologue. Deliberately does NOT set
        ``__execution__["only_node"]`` (outputs route across the whole resumed
        tail) and adds no ``loop_runtime_scope`` (that's the snapshot's
        single-shot pattern; the walk wraps every node itself).
        """
        try:
            entry_node, final = seed_walk_entry(
                shared, self.resume_events or [], entry=str(self.resume_from), start_node=workflow.start_node
            )
        except CompilationError:
            # Without this wrap, a --force resume after K was renamed/removed
            # surfaces find_node_by_id's "compiler/graph bug" error — misattributed.
            raise ResumeNotResumableError(
                f"Step '{self.resume_from}' no longer exists in the workflow — it was renamed or "
                f"removed since the failed run.",
                execution_id=self.resume_source_id,
                suggestions=["Re-run the workflow from the start instead of resuming."],
            ) from None
        initialize_execution_state(shared)
        restored = [nid for nid in final if nid != self.resume_from]
        # Engine-only keys, stamped here per the node_state pattern — never added
        # to new_execution_state(). The display/JSON surface reads all three.
        shared["__execution__"]["restored_nodes"] = restored
        shared["__execution__"]["resumed_from"] = self.resume_source_id
        shared["__execution__"]["resume_entry_node"] = self.resume_from
        # Decision 6: re-record each restored node's final event into THIS attempt's
        # trace so it is self-contained — resume-of-a-resume and later --only runs
        # seed from the newest attempt alone. cached=True supplies status "cached"
        # (cost exclusion + UI rendering follow with zero further change); no
        # sub_workflow_events/batch_items (seeding never reads them; a childless
        # cached host is safe for tree()/cost).
        if self.trace is not None:
            for nid in restored:
                ev = final[nid]
                self.trace.record_node_execution(
                    node_id=nid,
                    node_type=ev.get("node_type", "unknown"),
                    duration_ms=0.0,
                    success=True,
                    node_output=ev.get("node_output"),
                    cached=True,
                    restored=True,
                )
        return entry_node

    @staticmethod
    def _emit_snapshot_degraded_advisory(shared: dict[str, Any], this_only: str) -> None:
        """Surface a loud (DEGRADED-flipping) advisory when the snapshot source degraded.

        A ``degraded`` full run can carry PARTIAL upstream data — e.g. a batch
        host with ``error_handling: continue`` records ``success=True`` with
        failed items dropped from ``results`` and degrades the trace. Restoring
        it silently would feed the target incomplete upstream, so we never seed a
        degraded snapshot silently: a WARNING ``Diagnostic`` written to
        ``__warnings__`` flips workflow status to DEGRADED and surfaces in
        CLI/JSON/report output.

        Stored under a dedicated synthetic key (not ``this_only``) so a target
        that emits its own ``__warnings__[this_only]`` entry can't overwrite it;
        the Diagnostic carries ``node_id=this_only`` so it still attributes to
        the node the user is iterating on (``_extract_runtime_warnings`` keeps
        the explicit node_id rather than substituting the dict key).
        """
        shared.setdefault("__warnings__", {})["__only_snapshot__"] = build_snapshot_degraded_diagnostic(
            this_only, source="runtime"
        )

    def _loop_should_reenter(
        self,
        config: NodeConfig,
        shared: dict[str, Any],
        node_id: str,
        loop_counts: dict[str, int],
        loop_caps: dict[str, int],
    ) -> bool:
        """Decide whether a ``loop:`` node re-enters after a clean run (issue #445).

        Order is load-bearing: a falsy condition is a CLEAN drain (``loop_stopped:
        "condition"``); a truthy condition that has reached the cap is a
        non-degrading advisory (``loop_stopped: "max_iterations"`` + INFO). The cap
        counts the loop's OWN iterations and is always ``<= MAX_NODE_VISITS``, so it
        stops before the hard visit guard would raise.

        The cap is resolved ONCE per loop and memoized in ``loop_caps`` — a
        ``max_iterations: ${template}`` that resolves to different values across
        iterations uses its first-iteration value (a loop's cap is fixed by design).
        """
        loop_config = config.loop_config
        if loop_config is None:  # caller guards; defensive for type-narrowing
            return False

        if loop_config.until_template is not None:
            should_continue = evaluate_loop_condition(loop_config.until_template, shared, node_id, until=True)
        elif loop_config.while_template is not None:
            should_continue = evaluate_loop_condition(loop_config.while_template, shared, node_id)
        else:
            raise LoopConditionError(
                f"Node '{node_id}' loop has neither `while:` nor `until:` configured.",
                node_id=node_id,
                suggestion="Declare exactly one loop condition: `while: ${node.output}` or `until: ${node.output}`.",
            )
        if not should_continue:
            self._mark_loop_stopped(shared, node_id, "condition")
            return False

        cap = loop_caps.get(node_id)
        if cap is None:
            cap = resolve_loop_cap(loop_config, shared, node_id)
            loop_caps[node_id] = cap

        if loop_counts[node_id] >= cap:
            self._mark_loop_stopped(shared, node_id, "max_iterations")
            self._emit_loop_cap_advisory(shared, node_id, cap, until=loop_config.until_template is not None)
            return False

        return True

    @staticmethod
    def _mark_loop_stopped(shared: dict[str, Any], node_id: str, reason: str) -> None:
        """Stamp ``loop_stopped`` on the loop node's output so JSON/MCP/CLI can read why it ended."""
        node_output = shared.get(node_id)
        if isinstance(node_output, dict):
            node_output["loop_stopped"] = reason

    @staticmethod
    def _emit_loop_cap_advisory(shared: dict[str, Any], node_id: str, cap: int, *, until: bool = False) -> None:
        """Emit a non-degrading INFO advisory when a loop stops because it hit its cap.

        Mirrors the empty-input batch advisory (``batch_executor._push_batch_warnings``):
        an ``INFO`` Diagnostic written to ``__warnings__`` surfaces in reports / CLI /
        JSON without flipping the workflow to DEGRADED.

        The wording is polarity-aware (``until``): a ``while:`` loop caps with its
        condition still *truthy* (it never went falsy); an ``until:`` loop caps with
        its condition still *falsy* (it never went truthy). Hard-coding the ``while``
        phrasing for an ``until`` loop would tell the agent to make the source "go
        falsy" — the exact polarity confusion ``until:`` exists to prevent.

        Overwrite precedence (deliberate): this writes ``__warnings__[node_id]``
        unconditionally. It is reached only on the non-error re-entry path, and the
        failure-path writers (``mark_node_failed``) plus batch's advisory writers
        (batch is mutually exclusive with loop) never coexist with it. The one
        non-error writer that CAN coexist is an ``llm`` loop body emitting its own
        INFO/WARNING advisory on the same capping iteration; in that case the cap
        advisory intentionally WINS (it explains *why the loop stopped* — the more
        important signal). Per-iteration ``clear_node_failure`` already pops stale
        warnings on re-entry, so only the final iteration's advisory is at stake.
        """
        keyword = "until" if until else "while"
        still_state = "falsy" if until else "truthy"
        target_state = "truthy" if until else "falsy"
        shared.setdefault("__warnings__", {})[node_id] = Diagnostic(
            severity=Severity.INFO,
            title="Loop reached max_iterations",
            message=(
                f"Loop node '{node_id}' stopped after reaching its max_iterations cap ({cap}) "
                f"with its `{keyword}:` condition still {still_state}."
            ),
            suggestions=[
                "Expected when capping a stop-on-condition loop. If the loop should have drained "
                f"naturally, raise max_iterations or check that the `{keyword}:` source eventually goes {target_state}.",
            ],
            node_id=node_id,
            source="runtime",
            id="loop.max-iterations-reached",
        )

    def _populate_outputs(self, workflow: CompiledWorkflow, shared: dict[str, Any], last_action: str | None) -> None:
        """Resolve declared workflow outputs into the shared store.

        Under ``--only``, outputs whose source templates cannot resolve (because
        the source node was skipped) are skipped without error — the resolver
        writes each successful resolution to ``shared`` during iteration before
        raising ``OutputResolutionError`` for failures, so resolvable outputs
        are still populated. Non-``--only`` runs re-raise so the user sees the
        full error.
        """
        is_error = last_action and isinstance(last_action, str) and str(last_action).startswith("error")
        if not workflow.outputs or is_error:
            return

        from pflow.core.user_errors import OutputResolutionError
        from pflow.runtime.output_resolver import populate_declared_outputs

        try:
            populate_declared_outputs(shared, {"outputs": workflow.outputs})
        except OutputResolutionError:
            if not self.only_node:
                raise

    def _handle_no_successor(
        self, last_action: str | None, node_id: str, curr: Any, shared: dict[str, Any]
    ) -> str | None:
        """Handle case where no successor matches the current action.

        Distinguishes intentional termination from routing errors:
        - "end" action or no forward (non-error) edges → clean termination
        - Unmatched action with forward edges present → routing failure

        Returns the (possibly updated) last_action.
        """
        # Defensive guard: the walk loop only reaches here on a route_action
        # ROUTING_ERROR (clean termination breaks without calling), so this
        # check is unreachable from _run_inner — kept so any future direct
        # caller still gets the clean-termination short-circuit.
        if is_clean_termination(last_action, curr.successors):
            return last_action  # Intentional termination or no forward path

        # A node that FAILED (action="error") is already archived in __failures__ with
        # its real error + remedy (engine step 17.5 / handle_api_warning). Emitting a
        # generic "add on-error" routing hint here would visually outrank that real fix
        # and train agents to route the failure instead of fixing its cause (GH #437).
        # The failure already stands on its own; just propagate "error". (This branch is
        # reachable only for action="error" — only that path archives into __failures__.)
        if get_node_failure(shared, node_id) is not None:
            return "error"

        # A custom (non-error) action with no matching successor IS a genuine routing
        # bug — surface it. Roll back the success bookkeeping cache_result added and
        # archive as a routing failure.
        warning_msg = (
            f"Node '{node_id}' returned action '{last_action}' "
            f"but no successor edge matches. Available: {list(curr.successors)}. "
            'Use next: str = "end" to terminate intentionally.'
        )
        invalidate_cache(node_id, shared)
        mark_node_failed(
            shared,
            node_id,
            category=FAILURE_CATEGORY_ROUTING,
            error=warning_msg,
            warning=warning_msg,
        )
        # The trace event was recorded at step 16 with success=True (because
        # is_error_action was False for this custom action). Flip it so trace
        # and __failures__ agree — see GH #250. Note: the mutation only sets
        # success=False + error text; the failure category (FAILURE_CATEGORY_ROUTING)
        # lives on the __failures__ record set by mark_node_failed above, not on
        # the trace event itself (events don't carry a category field).
        if self.trace is not None:
            self.trace.mark_last_event_failed(node_id, error=warning_msg)
        return "error"

    def _execute_node(self, node: Any, config: NodeConfig, shared: dict[str, Any]) -> str:  # noqa: C901
        """Execute a single node with all runtime concerns.

        The carried-loop input override (round N>1) lives in ``plan_node`` —
        resolution + config-hash + execution all observe the effective inputs.
        Here we assert that no carried input was left unresolved and raise a
        carry-aware error in EITHER mode — strict (``plan_node`` captured a
        template error) or permissive (``plan_node`` left a literal ``${...}``).
        See ``_assert_carried_inputs_resolved``.
        """
        start_time = time.perf_counter()
        shared_keys_before = set(shared.keys()) if (self.trace or self.metrics) else set()

        # (Step 1 — LLM trace registration — removed in Task 158 Phase A
        # post-cleanup. The trace collector is now installed by `run()`
        # into ``shared["__trace_collector__"]`` and resolved by
        # ``LLMNode.prep()`` directly. Lifecycle step numbers below
        # preserved for cross-reference with engine/CLAUDE.md.)

        # 2. Execution state
        initialize_execution_state(shared)
        if self.only_node:
            shared["__execution__"]["only_node"] = self.only_node

        # 3. Loop guard
        enforce_loop_guard(config.node_id, shared)

        # Steps 5-11 are inside try so template errors get recorded in trace
        last_resolutions: dict = {}
        template_errors: list = []
        resolved_params: dict | None = None
        batch_trace_items: list | None = None
        child_trace_events: list | None = None
        host_frame: Any = None  # Task 172: a sub-workflow host's reserved correlation (run-scoped)
        start_frame: Any = None  # Task 173: a leaf's node.start correlation (reserved seq, reused at completion)

        try:
            plan = plan_node(node, config, shared)

            # Task 166: carry owns its own error in BOTH resolution modes. Run this
            # BEFORE re-raising a strict template_exception so a carried output the
            # body omitted surfaces as a carry-aware LoopCarryError (naming the loop
            # node + listing available outputs), not a generic `inputs:` template
            # error. Skipped on cache hits (a carry iteration is always a re-entry
            # miss, but stay defensive). Permissive mode lands here with no exception.
            if is_carry_iteration(config, shared) and plan.status not in ("cached_memo", "cached_in_process"):
                _assert_carried_inputs_resolved(config, plan, shared)

            if plan.template_exception is not None:
                raise plan.template_exception

            if plan.status in ("cached_memo", "cached_in_process"):
                # Task 159 E.1: ``cache_source`` is keyword-driven by plan status.
                # - ``cached_memo``: ``apply_memo_hit`` already augments
                #   ``llm_usage`` with ``cache_source="memo"`` plus the matching
                #   key + age. Pass ``cache_source=None`` so
                #   ``handle_cached_execution`` does NOT overwrite that augment.
                # - ``cached_in_process``: nothing has augmented yet; pass
                #   ``"in_process"`` so the trace correctly tags the intra-run
                #   loop-revisit hit. DD#22 distinguishes the two layers.
                if plan.status == "cached_memo" and plan.cached_output is not None and plan.cached_action is not None:
                    apply_memo_hit(
                        config.node_id,
                        shared,
                        plan.cached_action,
                        plan.cached_output,
                        plan.config_hash,
                        node_type_name=config.node_type_name,
                        cache_key=plan.cache_key,
                        created_at=plan.cached_created_at,
                    )
                    cached_source: str | None = None
                else:
                    cached_source = "in_process"
                # GH #540: record the RESOLVED params + template resolutions the cache
                # key was computed from, so a cached event carries the same Input detail
                # as a fresh one (the `pflow ui` panel reads node_params; `pflow report`
                # reads template_resolutions). plan.resolved_params is None for batch /
                # no-template nodes — fall back to node.params, exactly mirroring the miss
                # path (where node.params is only reassigned to resolved_params when present).
                return str(
                    handle_cached_execution(
                        config.node_id,
                        shared,
                        plan.cached_action,
                        shared_keys_before,
                        config.node_type_name,
                        plan.resolved_params if plan.resolved_params is not None else node.params,
                        self.trace,
                        cache_source=cached_source,
                        template_resolutions=plan.last_resolutions,
                    )
                )

            last_resolutions = plan.last_resolutions
            template_errors = plan.template_errors
            resolved_params = plan.resolved_params
            cache_key = plan.cache_key
            config_hash = plan.config_hash

            if config.node_id in shared["__execution__"]["completed_nodes"]:
                cached_hash = shared["__execution__"]["node_hashes"].get(config.node_id)
                if cached_hash != plan.config_hash:
                    invalidate_cache(config.node_id, shared)

            # 7.5 Approval gate (Task 125): pause BEFORE the start callback and the
            # node.start marker, so a denied node never appears in the trace and no
            # progress partial line is open at prompt time. Cached nodes never reach
            # here (early-return above) — a cache hit performs no action, so there
            # is nothing to approve. Preview = resolved params; static params for
            # no-template nodes (plan.resolved_params is None then). Raises
            # GateDenied / GateNotInteractiveError — both exempted in the except
            # arm below (a gate verdict is not a node failure).
            if config.approval:
                run_approval_gate(
                    config,
                    resolved_params if resolved_params is not None else node.params,
                    shared,
                    self.trace,
                )

            # 8. Progress callback (node_start)
            call_start_callback(config.node_id, shared)

            # 8.5 Task 173 (node.start): flush a live in-flight marker the overlay tailer renders as
            # `running`, reserving this node's seq for its completion event to reuse. Skipped for
            # sub-workflow hosts (WorkflowExecutor reserves via descend(); host node.start is deferred
            # L2) and a no-op unless the collector is run-scoped + streaming. The returned frame MUST
            # reach every completion record below (step 16 / api-warning / except) so the seq is reused,
            # never re-taken — keeping on-disk event seqs identical to a run without node.start.
            if self.trace is not None and config.node_type_name != "WorkflowExecutor":
                start_frame = self.trace.begin_node(config.node_id, config.node_type_name)

            # 9. Execute: batch or single
            if config.batch_config:
                action = execute_batch(node, config, shared, self._execute_single_node)
                # NOTE: per-item batch trace events stay in ``shared["_batch_trace"]``
                # until the single drain right before ``record_trace`` below. Draining
                # here would lose the items if any later step (write_memo_cache,
                # detect_api_warning, metrics) raised — the except handler's drain
                # would then pop an already-empty buffer. Symmetry with the except
                # path is the whole point of Bundle 8's shared-store recovery channel.
                # Task 125: a direct batch host has no per-item gate seam — an
                # UNDECIDED escalation marker in an item's result would be silently
                # ignored. Fail loudly instead (decided markers, answered inside a
                # sequential sub-workflow item, are skipped).
                scan_batch_escalations(shared, config.node_id)
            else:
                # Set resolved params on node and execute
                if resolved_params is not None:
                    node.params = resolved_params
                    # Write permissive-mode errors to shared store (last error per node,
                    # matching old TemplateAwareNodeWrapper behavior — multiple errors
                    # per node would require changing the consumer in runner.py)
                    if template_errors:
                        shared.setdefault("__template_errors__", {})[config.node_id] = template_errors[-1]

                store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
                action = node._run(store)

                # Read child trace events + host correlation frame from WorkflowExecutor.
                # `_child_trace_events` is set only on the OLD buffer path (events to embed);
                # `_host_frame` only on the NEW run-collector path (its reserved seq/parent_id).
                if config.node_type_name == "WorkflowExecutor":
                    child_trace_events = getattr(node, "_child_trace_events", None)
                    host_frame = getattr(node, "_host_frame", None)

            # 10. API warning detection. Only run it on a clean-success verdict — see
            # _CLEAN_SUCCESS_ACTIONS. A node that returned an error action (GH #474) or a
            # deliberate custom route like error_action's "continue" (GH #301) has already
            # spoken; the detector must not override its routing or relabel its failure.
            # error-action failures fall through to step 17.5, which writes the on_error_recovery
            # diagnostic (with handler) or a plain node failure (terminal) — consistent across
            # all node types, independent of whether the error text matches a pattern.
            warning = None
            if action is None or str(action) in _CLEAN_SUCCESS_ACTIONS:
                warning = detect_api_warning(config.node_id, shared, node_type_name=config.node_type_name)
            if warning:
                # Drain the per-item buffer even though ``handle_api_warning``
                # discards batch items today (pre-existing, see W2 in PR #405
                # review). The drain prevents the accumulator from leaking into
                # shared state for the rest of the workflow run.
                if config.batch_config:
                    _collect_batch_trace(shared, config.node_id)
                return handle_api_warning(
                    config.node_id,
                    shared,
                    warning,
                    self.metrics,
                    self.trace,
                    start_time,
                    shared_keys_before,
                    config.node_type_name,
                    node.params,
                    recovered=node.successors.get("error") is not None,
                    frame=host_frame or start_frame,
                )

            # 10.5 Escalation detection (Task 125). Non-batch, clean-success only:
            # an error action's data is archived by step 17.5 (pausing after that
            # would break the shared-XOR-__failures__ invariant), and the
            # api-warning early-return above already ended warning verdicts. The
            # PAUSE happens at step 17.7 (after the node's own completion trace
            # and callback); detection must run here because an escalating result
            # is an incomplete work product and must not enter either cache below.
            escalation = None
            if not config.batch_config and (action is None or str(action) in _CLEAN_SUCCESS_ACTIONS):
                escalation = detect_escalation(shared, config.node_id)

            # 11. Cache result (in-process only — not gated by cache_enabled)
            if escalation is None:
                cache_result(config.node_id, config_hash, action, shared)

            # 12. Duration (computed here so the memo cache write can record it
            # for --dry-run historical estimates — see plan_formatter.py).
            duration_ms = (time.perf_counter() - start_time) * 1000

            # 13. Memo cache write (skip for nodes with cache: false)
            if config.cache_enabled and escalation is None:
                write_memo_cache(
                    config.node_id,
                    shared,
                    cache_key,
                    action,
                    duration_ms=duration_ms,
                    node_type_name=config.node_type_name,
                )

            # 14. Metrics
            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

            # Pre-compute trace error for action="error" happy-path failures
            # (no exception raised, but the trace event should still carry the
            # actual error text so --report and other trace consumers don't
            # fall back to "Unknown error").
            is_error_action = str(action).startswith("error")
            trace_error: str | None = None
            if is_error_action:
                node_data_snapshot = shared.get(config.node_id, {})
                if isinstance(node_data_snapshot, dict):
                    trace_error = node_data_snapshot.get("error")

            # 16. Trace — node returning "error" action is a failure even without exception.
            # Single drain site for batch trace events: collects from the shared
            # store accumulator just before record_trace consumes them. The
            # except handler below has a symmetric drain so completed-before-
            # failure events survive into the trace identically.
            if config.batch_config:
                batch_trace_items = _collect_batch_trace(shared, config.node_id)
            record_trace(
                config.node_id,
                config.node_type_name,
                shared,
                start_time,
                shared_keys_before,
                last_resolutions,
                batch_trace_items,
                child_trace_events,
                node.params,
                self.trace,
                success=not is_error_action,
                error=trace_error,
                frame=host_frame or start_frame,
            )

            # 17. Completion callback
            ignore_errors = node.params.get("ignore_errors", False) if isinstance(node.params, dict) else False
            call_completion_callback(
                config.node_id,
                shared,
                action,
                duration_ms,
                ignore_errors=ignore_errors,
            )

            # Step 17.5: archive failed node data to __failures__.
            # Runs AFTER trace, metrics, and completion callback so they
            # all see the data in shared[node_id]. After this, the node
            # is in __failures__ and consumers must use get_node_output.
            #
            # Category is resolved from the compile-time node type name
            # via _NODE_TYPE_FAILURE_CATEGORY — no data-shape heuristic.
            #
            # When an error successor exists (on-error handler), pass
            # warning= so __warnings__ is populated and _determine_status
            # returns DEGRADED instead of SUCCESS. Without this, recovered
            # workflows silently report SUCCESS (GH #246).
            if str(action).startswith("error"):
                node_data = shared.get(config.node_id, {})
                node_error = node_data.get("error") if isinstance(node_data, dict) else None
                error_handler = node.successors.get("error")
                handler_id = getattr(error_handler, "node_id", None) if error_handler else None
                category = _NODE_TYPE_FAILURE_CATEGORY.get(config.node_type_name, FAILURE_CATEGORY_NODE_ERROR)
                recovery_warning = (
                    Diagnostic(
                        severity=Severity.WARNING,
                        message=f"Node '{config.node_id}' failed — on-error → '{handler_id}'",
                        node_id=config.node_id,
                        source="runtime",
                        context={"type": "on_error_recovery", "category": category},
                    )
                    if handler_id
                    else None
                )
                mark_node_failed(
                    shared,
                    config.node_id,
                    category=category,
                    error=node_error,
                    warning=recovery_warning,
                )

            # 17.7 Escalation pause (Task 125). After the node's own completion
            # trace/callback (its success record stands untouched) and before
            # returning to the walk, whose loop-re-entry check must see the
            # human's decision in the store. Mutually exclusive with step 17.5
            # (detection is clean-success-only).
            if escalation is not None:
                run_escalation_gate(config, escalation, shared, self.trace)

            return action

        except (GateDenied, GateNotInteractiveError, GateResolverError) as gate_exc:
            # Task 125: a gate verdict is control flow, NOT a node failure — no
            # error trace event, no error callback, no mark_node_failed, no
            # _pflow_node_id. (A denied node never ran; a non-interactive
            # escalation's node already has its honest success record.) The
            # trailer channel: _determine_trace_status derives from node events
            # only, so without this flag a denied run's own trace would read
            # "success". Set here (every engine level passes through, root last)
            # so the flag lands on the run-scoped collector even when the gate
            # fired under a buffered child collector.
            if self.trace is not None:
                self.trace.gate_outcome = "denied" if isinstance(gate_exc, GateDenied) else "failed"

                # Code-review fix: a sub-workflow HOST's own completion event is
                # normally recorded at step 16 below, reusing the seq
                # WorkflowExecutor.exec() reserved via trace.descend(). Re-raising
                # here means node._run() never returns, so step 16 never runs —
                # the reserved seq gets no event. If a SIBLING step inside that
                # sub-workflow already recorded before the gate fired, its event's
                # parent_id now points at nothing: an in-memory tree() rebuild
                # (finalize(), or any caller of collect_llm_calls()) raises
                # "orphan event" — silently losing the run's own trace file (or
                # crashing a caller that hits tree() directly). Recording the
                # host's event here closes the reservation. success=True: the
                # WorkflowExecutor node itself didn't error — the run's
                # denied/failed verdict is carried independently by gate_outcome
                # above, not by this per-node flag. Fires once per nesting level
                # (each ancestor's own _execute_node catches this exception and
                # checks its own node's _host_frame as it re-raises in turn).
                # Batch hosts stay None here: batch-item children run under
                # buffered collectors (descend() is never called on that path).
                host_frame = getattr(node, "_host_frame", None)
                if host_frame is not None:
                    record_trace(
                        config.node_id,
                        config.node_type_name,
                        shared,
                        start_time,
                        shared_keys_before,
                        last_resolutions,
                        batch_trace_items,
                        child_trace_events,
                        node.params,
                        self.trace,
                        success=True,
                        frame=host_frame,
                    )
            raise

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(config.node_id, duration_ms)

            # Extract partial resolutions from template errors (attached by resolve_templates)
            error_resolutions = getattr(e, "_pflow_partial_resolutions", None) or last_resolutions

            # Drain per-item trace events on the failure path too. When
            # execute_batch raises (fail_fast all-failed), items that completed
            # before the failing item still appear in shared["_batch_trace"].
            # Without this drain, completed nested LLM work would silently vanish
            # from the trace, and analyze-cache would report `[unexecuted]` for
            # nodes that actually ran.
            batch_trace_items = _collect_batch_trace(shared, config.node_id) if config.batch_config else None

            record_trace(
                config.node_id,
                config.node_type_name,
                shared,
                start_time,
                shared_keys_before,
                error_resolutions,
                batch_trace_items,
                child_trace_events,
                node.params,
                self.trace,
                error=e,
                frame=host_frame or start_frame,
            )

            call_completion_callback(config.node_id, shared, "error", duration_ms, error=e)

            # LAST STEP: archive the failed node's data to __failures__.
            # All trace/metrics/callback have already read shared[node_id].

            # Categorize template-resolution ValueErrors specifically so the
            # formatter can render them as template errors, not generic exceptions.
            is_template_error = isinstance(e, ValueError) and getattr(e, "_pflow_partial_resolutions", None) is not None
            category = FAILURE_CATEGORY_TEMPLATE if is_template_error else FAILURE_CATEGORY_EXCEPTION

            node_data = shared.get(config.node_id, {})
            node_error = node_data.get("error") if isinstance(node_data, dict) else None
            mark_node_failed(
                shared,
                config.node_id,
                category=category,
                error=node_error or str(e),
            )

            if not hasattr(e, "_pflow_node_id"):
                e._pflow_node_id = config.node_id  # type: ignore[attr-defined]

            raise

    def _execute_single_node(self, node: Any, config: NodeConfig, shared: dict[str, Any]) -> tuple[str, dict, list]:
        """Execute a non-batch node: resolve templates, namespace, run.

        Returns (action, last_resolutions, template_errors).
        NO instance state stored — safe for parallel batch.
        """
        last_resolutions: dict = {}
        template_errors: list = []

        if config.template_config:
            merged_params, last_resolutions, template_errors = resolve_templates(
                config.template_config, shared, config.node_id
            )
            node.params = merged_params
            if template_errors:
                shared.setdefault("__template_errors__", {})[config.node_id] = template_errors[-1]

        store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
        action = node._run(store)

        return action, last_resolutions, template_errors
