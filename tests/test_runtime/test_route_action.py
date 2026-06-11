"""Unit tests for the shared routing kernel ``route_action``.

The kernel expresses the walk's precedence rule — successor match wins, then
clean termination, else routing error — exactly once, for BOTH the engine's
``_run_inner`` successor step and the planner's ``_classify``. These tests
pin the kernel directly; caller-side behavior is pinned by
tests/test_runtime/test_engine_behavior.py (engine) and
tests/test_execution/test_plan_classify.py (planner).
"""

from pflow.core.node import BaseNode
from pflow.runtime.engine.engine import RouteDecision, RouteKind, route_action


def _node(node_id: str) -> BaseNode:
    node = BaseNode()
    node.node_id = node_id
    return node


class TestRouteAction:
    def test_follow_returns_successor_identity(self):
        target = _node("next-step")
        decision = route_action("default", {"default": target})
        assert decision == RouteDecision(RouteKind.FOLLOW, target)
        assert decision.next_node is target

    def test_none_action_falls_back_to_default_lookup(self):
        target = _node("next-step")
        decision = route_action(None, {"default": target})
        assert decision.kind is RouteKind.FOLLOW
        assert decision.next_node is target

    def test_custom_action_follows_matching_edge(self):
        retry_target = _node("retry-step")
        decision = route_action("retry", {"default": _node("other"), "retry": retry_target})
        assert decision.kind is RouteKind.FOLLOW
        assert decision.next_node is retry_target

    def test_end_action_is_clean_stop(self):
        decision = route_action("end", {"default": _node("unreached")})
        assert decision == RouteDecision(RouteKind.CLEAN_STOP)
        assert decision.next_node is None

    def test_all_error_successors_is_clean_stop(self):
        decision = route_action("default", {"error": _node("handler")})
        assert decision.kind is RouteKind.CLEAN_STOP

    def test_no_successors_is_clean_stop(self):
        """Empty successors: ``all()`` over nothing → no forward path → clean."""
        decision = route_action("default", {})
        assert decision.kind is RouteKind.CLEAN_STOP

    def test_unmatched_action_with_forward_edges_is_routing_error(self):
        decision = route_action("nonexistent", {"default": _node("a"), "retry": _node("b")})
        assert decision == RouteDecision(RouteKind.ROUTING_ERROR)

    def test_error_action_with_only_default_edge_is_routing_error(self):
        """An error action with a forward (non-error) edge and no handler is a
        routing failure — the engine archives it, the planner surfaces it."""
        decision = route_action("error", {"default": _node("a")})
        assert decision.kind is RouteKind.ROUTING_ERROR
