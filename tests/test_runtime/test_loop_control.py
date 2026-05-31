"""Unit coverage for the loop condition/cap runtime belt (issue #445).

These are the belt-and-suspenders guards that prevent an infinite loop when a
workflow slips past validation (programmatic IR, or a dynamic output that turns
out to be a string at runtime). A regression here silently re-opens the
foot-gun, so they get direct unit coverage rather than only integration tests.
"""

import pytest

from pflow.core.exceptions import LoopConditionError
from pflow.runtime.engine import instrumentation
from pflow.runtime.engine.loop_control import (
    _coerce_runtime_cap,
    evaluate_loop_condition,
    loop_runtime_scope,
    resolve_loop_cap,
)
from pflow.runtime.engine.types import LoopConfig

# --- evaluate_loop_condition ------------------------------------------------


def test_absent_reference_is_falsy_stop() -> None:
    assert evaluate_loop_condition("${n.x}", {}, "n") is False


def test_empty_list_is_falsy() -> None:
    assert evaluate_loop_condition("${n.x}", {"n": {"x": []}}, "n") is False


def test_nonempty_list_is_truthy() -> None:
    assert evaluate_loop_condition("${n.x}", {"n": {"x": [1]}}, "n") is True


def test_zero_is_falsy_positive_is_truthy() -> None:
    assert evaluate_loop_condition("${n.x}", {"n": {"x": 0}}, "n") is False
    assert evaluate_loop_condition("${n.x}", {"n": {"x": 3}}, "n") is True


def test_false_bool_is_falsy() -> None:
    assert evaluate_loop_condition("${n.x}", {"n": {"x": False}}, "n") is False


def test_string_value_raises_not_loops() -> None:
    # Belt half 2: a string that slipped past validation must RAISE, never bool().
    with pytest.raises(LoopConditionError, match="string"):
        evaluate_loop_condition("${n.x}", {"n": {"x": "0\n"}}, "n")


def test_malformed_template_stops_safely() -> None:
    # Not a single ${...} reference → stop (fail-safe), never loop on garbage.
    assert evaluate_loop_condition("not a template", {}, "n") is False


def test_coalesce_falls_through_to_stop_when_unresolved() -> None:
    assert evaluate_loop_condition("${a.x ?? b.y}", {}, "n") is False


def test_coalesce_resolves_typed_value() -> None:
    assert evaluate_loop_condition("${a.x ?? b.y}", {"b": {"y": 1}}, "n") is True


# --- resolve_loop_cap / _coerce_runtime_cap ---------------------------------


def test_literal_cap_passthrough() -> None:
    assert resolve_loop_cap(LoopConfig("${n.x}", max_iterations=5), {}, "n") == 5


def test_default_cap_is_max_node_visits() -> None:
    assert resolve_loop_cap(LoopConfig("${n.x}"), {}, "n") == instrumentation.MAX_NODE_VISITS


def test_template_cap_resolves() -> None:
    assert resolve_loop_cap(LoopConfig("${n.x}", max_iterations_template="${cap}"), {"cap": 4}, "n") == 4


def test_template_cap_numeric_string_resolves() -> None:
    assert resolve_loop_cap(LoopConfig("${n.x}", max_iterations_template="${cap}"), {"cap": "7"}, "n") == 7


def test_template_cap_non_int_raises() -> None:
    with pytest.raises(LoopConditionError, match="not a positive integer"):
        resolve_loop_cap(LoopConfig("${n.x}", max_iterations_template="${cap}"), {"cap": "abc"}, "n")


def test_template_cap_unresolved_raises() -> None:
    # Absent ${cap} → resolve_template returns the literal "${cap}" → int() fails.
    with pytest.raises(LoopConditionError):
        resolve_loop_cap(LoopConfig("${n.x}", max_iterations_template="${cap}"), {}, "n")


def test_runtime_cap_zero_raises() -> None:
    with pytest.raises(LoopConditionError, match=">= 1"):
        _coerce_runtime_cap(0, "n", "${cap}")


def test_runtime_cap_negative_raises() -> None:
    with pytest.raises(LoopConditionError, match=">= 1"):
        _coerce_runtime_cap(-2, "n", "${cap}")


def test_runtime_cap_over_max_raises() -> None:
    with pytest.raises(LoopConditionError, match="exceeding the hard visit"):
        _coerce_runtime_cap(instrumentation.MAX_NODE_VISITS + 1, "n", "${cap}")


def test_runtime_cap_non_numeric_type_raises() -> None:
    with pytest.raises(LoopConditionError, match="not a positive integer"):
        _coerce_runtime_cap([1, 2], "n", "${cap}")


def test_runtime_cap_float_truncates() -> None:
    assert _coerce_runtime_cap(3.9, "n", "${cap}") == 3


def test_runtime_cap_respects_lowered_env(monkeypatch) -> None:
    monkeypatch.setattr(instrumentation, "MAX_NODE_VISITS", 3)
    assert _coerce_runtime_cap(3, "n", "${cap}") == 3
    with pytest.raises(LoopConditionError, match="exceeding the hard visit"):
        _coerce_runtime_cap(4, "n", "${cap}")


# --- loop_runtime_scope: the clear_iteration_on_exit asymmetry ---------------
# Load-bearing and shared by two callers (engine passes False, planner True), so
# it gets direct coverage rather than only the indirect integration path.


def test_scope_keeps_iteration_when_not_clearing() -> None:
    """Engine path: ${__iteration__} survives the scope so it persists across re-entry."""
    shared: dict = {}
    with loop_runtime_scope(shared, True, iteration=2, clear_iteration_on_exit=False):
        assert shared["__iteration__"] == 2
        assert shared["__loop_active__"] == 1
    assert shared["__iteration__"] == 2  # kept
    assert "__loop_active__" not in shared  # depth back to 0 → popped


def test_scope_clears_iteration_when_requested() -> None:
    """Planner path: ${__iteration__} must not leak to later nodes after one pass."""
    shared: dict = {}
    with loop_runtime_scope(shared, True, iteration=2, clear_iteration_on_exit=True):
        assert shared["__iteration__"] == 2
    assert "__iteration__" not in shared  # cleared
    assert "__loop_active__" not in shared


def test_scope_loop_active_is_a_depth_counter() -> None:
    """Nested loops: __loop_active__ counts depth, only popped at depth 0."""
    shared: dict = {}
    with loop_runtime_scope(shared, True, iteration=1, clear_iteration_on_exit=False):
        with loop_runtime_scope(shared, True, iteration=1, clear_iteration_on_exit=False):
            assert shared["__loop_active__"] == 2
        assert shared["__loop_active__"] == 1  # inner exit decrements, doesn't pop
    assert "__loop_active__" not in shared


def test_scope_is_noop_when_inactive() -> None:
    shared: dict = {}
    with loop_runtime_scope(shared, False, iteration=5, clear_iteration_on_exit=False):
        assert "__iteration__" not in shared
        assert "__loop_active__" not in shared
    assert shared == {}
