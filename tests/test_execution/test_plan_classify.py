"""Unit tests for the planner's state machine (`_classify`, `_represents_work`).

These tests pin the `Transition` semantics directly, complementing the
end-to-end parity guarantee in `test_plan_drift.py`. If `_classify` ever
grows a new case (e.g. a new `PlanEntry.status` value), a test here should
fail — catching the extension at the unit layer instead of waiting for an
empirical drift.
"""

from __future__ import annotations

from typing import Any

from pflow.execution.plan import Transition, _classify, _represents_work
from pflow.execution.result import Plan, PlanEntry, PlanSummary


class _StubNode:
    """Minimal successor-bearing stand-in for a compiled node."""

    def __init__(self, successors: dict[str, Any]) -> None:
        self.successors = successors


def _entry(
    status: str, *, cause: str = "no_cache_match", action: str | None = None, sub_plan: Plan | None = None
) -> PlanEntry:
    return PlanEntry(
        node_id="n",
        node_type="ShellNode",
        status=status,  # type: ignore[arg-type]
        cause=cause,  # type: ignore[arg-type]
        action=action,
        sub_plan=sub_plan,
    )


def _child_plan(*, execute_count: int = 0, execute_nested: int | None = None) -> Plan:
    summary = PlanSummary(
        total=execute_count,
        cached_count=0 if execute_count else 1,
        execute_count=execute_count,
        cache_boundary="n" if execute_count else None,
        execute_by_type={"ShellNode": execute_count} if execute_count else {},
        estimated_cost_usd=0.0,
        nodes_without_history=0,
        cost_basis="exact",
        execute_including_nested=execute_nested,
    )
    return Plan(workflow="child", entries=[], summary=summary)


# ──────────────────────────────────────────────────────────────────────────────
# _classify: status → Transition mapping
# ──────────────────────────────────────────────────────────────────────────────


def test_classify_routing_error_status_stops() -> None:
    decision = _classify(_entry("routing_error", cause="routing_error"), _StubNode({}))
    assert decision.kind is Transition.STOP


def test_classify_cached_default_action_follows() -> None:
    successor = object()
    decision = _classify(
        _entry("cached", cause="hash_match", action="default"),
        _StubNode({"default": successor}),
    )
    assert decision.kind is Transition.FOLLOW
    assert decision.action == "default"


def test_classify_cached_named_action_with_successor_follows() -> None:
    decision = _classify(
        _entry("cached", cause="hash_match", action="success"),
        _StubNode({"success": object(), "default": object()}),
    )
    assert decision.kind is Transition.FOLLOW
    assert decision.action == "success"


def test_classify_cached_named_action_without_successor_is_routing_error() -> None:
    decision = _classify(
        _entry("cached", cause="hash_match", action="success"),
        _StubNode({"default": object()}),
    )
    assert decision.kind is Transition.ROUTING_ERROR
    assert decision.action == "success"


def test_classify_end_action_stops() -> None:
    # Real pflow graphs never have "end" as a successor key — it's a runtime
    # termination sentinel. A cached node returning action="end" must STOP
    # regardless of what successors exist (mirrors engine `_handle_no_successor`).
    decision = _classify(
        _entry("cached", cause="hash_match", action="end"),
        _StubNode({"default": object()}),
    )
    assert decision.kind is Transition.STOP


def test_classify_cached_error_action_follows_error_successor() -> None:
    # Cached action="error" with a matching "error" successor must FOLLOW
    # the on-error handler, not STOP. Engine does `successors.get("error")`
    # and walks into the handler.
    handler = object()
    decision = _classify(
        _entry("cached", cause="hash_match", action="error"),
        _StubNode({"error": handler}),
    )
    assert decision.kind is Transition.FOLLOW
    assert decision.action == "error"


def test_classify_cached_named_action_with_only_error_successors_stops() -> None:
    # Cached action="success" with only an error handler: engine's
    # `all(k == "error" for k in successors)` check clean-terminates.
    # Not a routing error — planner must match.
    decision = _classify(
        _entry("cached", cause="hash_match", action="success"),
        _StubNode({"error": object()}),
    )
    assert decision.kind is Transition.STOP


def test_classify_no_successors_stops() -> None:
    decision = _classify(_entry("execute"), _StubNode({}))
    assert decision.kind is Transition.STOP


def test_classify_only_error_successors_stops() -> None:
    decision = _classify(_entry("execute"), _StubNode({"error": object()}))
    assert decision.kind is Transition.STOP


def test_classify_execute_is_boundary() -> None:
    decision = _classify(_entry("execute"), _StubNode({"default": object()}))
    assert decision.kind is Transition.BOUNDARY


def test_classify_opaque_is_boundary() -> None:
    decision = _classify(_entry("opaque", cause="dynamic"), _StubNode({"default": object()}))
    assert decision.kind is Transition.BOUNDARY


def test_classify_sub_workflow_with_child_work_is_boundary() -> None:
    decision = _classify(
        _entry("sub_workflow", sub_plan=_child_plan(execute_count=1)),
        _StubNode({"default": object()}),
    )
    assert decision.kind is Transition.BOUNDARY


def test_classify_sub_workflow_with_nested_work_is_boundary() -> None:
    # Child has 0 direct execute nodes, but a grandchild would execute.
    decision = _classify(
        _entry("sub_workflow", sub_plan=_child_plan(execute_count=0, execute_nested=1)),
        _StubNode({"default": object()}),
    )
    assert decision.kind is Transition.BOUNDARY


def test_classify_sub_workflow_fully_cached_follows() -> None:
    decision = _classify(
        _entry("sub_workflow", sub_plan=_child_plan(execute_count=0)),
        _StubNode({"default": object()}),
    )
    assert decision.kind is Transition.FOLLOW
    assert decision.action == "default"


# ──────────────────────────────────────────────────────────────────────────────
# _represents_work: the "would the engine execute something?" predicate
# ──────────────────────────────────────────────────────────────────────────────


def test_represents_work_execute_is_work() -> None:
    assert _represents_work(_entry("execute"))


def test_represents_work_opaque_is_work() -> None:
    assert _represents_work(_entry("opaque", cause="dynamic"))


def test_represents_work_cached_is_not_work() -> None:
    assert not _represents_work(_entry("cached", cause="hash_match", action="default"))


def test_represents_work_routing_error_is_not_work() -> None:
    # Routing error is a plan-time diagnostic, not runtime execution.
    assert not _represents_work(_entry("routing_error", cause="routing_error"))


def test_represents_work_sub_workflow_with_execute_count() -> None:
    assert _represents_work(_entry("sub_workflow", sub_plan=_child_plan(execute_count=1)))


def test_represents_work_sub_workflow_with_nested_execute() -> None:
    assert _represents_work(_entry("sub_workflow", sub_plan=_child_plan(execute_count=0, execute_nested=2)))


def test_represents_work_sub_workflow_all_cached_is_not_work() -> None:
    assert not _represents_work(_entry("sub_workflow", sub_plan=_child_plan(execute_count=0)))


def test_represents_work_sub_workflow_without_child_plan_is_not_work() -> None:
    # Defensive: sub_workflow with no resolved child (shouldn't happen in practice,
    # but the predicate must not crash).
    assert not _represents_work(_entry("sub_workflow"))
