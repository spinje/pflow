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
