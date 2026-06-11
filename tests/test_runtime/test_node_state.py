"""Unit tests for runtime/node_state.py failure bookkeeping helpers."""

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.runtime.node_state import (
    FAILURE_CATEGORY_API_WARNING,
    FAILURE_CATEGORY_EXCEPTION,
    FAILURE_CATEGORY_NODE_ERROR,
    FAILURE_CATEGORY_SHELL,
    NodeStatus,
    clear_node_failure,
    get_node_failure,
    get_node_output,
    get_node_status,
    mark_node_failed,
    new_execution_state,
    node_succeeded,
)


class TestNewExecutionState:
    def test_returns_canonical_five_key_shape(self):
        state = new_execution_state()
        assert state == {
            "completed_nodes": [],
            "node_actions": {},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        }

    def test_calls_share_no_mutable_objects(self):
        first = new_execution_state()
        second = new_execution_state()
        first["completed_nodes"].append("node-a")
        first["node_actions"]["node-a"] = "default"
        assert second["completed_nodes"] == []
        assert second["node_actions"] == {}

    def test_mark_node_failed_defensive_init_has_no_cache_hits(self):
        # mark_node_failed's engine-less defensive init must seed the
        # canonical __execution__ WITHOUT the engine-owned __cache_hits__.
        shared: dict = {}
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_SHELL)
        assert set(shared["__execution__"]) == set(new_execution_state())
        assert shared["__execution__"]["failed_node"] == "node"
        assert "__cache_hits__" not in shared


class TestGetNodeStatus:
    def test_absent(self):
        assert get_node_status({}, "node") == NodeStatus.ABSENT

    def test_succeeded(self):
        shared = {"node": {"stdout": "ok"}}
        assert get_node_status(shared, "node") == NodeStatus.SUCCEEDED

    def test_failed(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "shell_failure"}}}
        assert get_node_status(shared, "node") == NodeStatus.FAILED

    def test_failed_takes_priority_over_succeeded(self):
        # Intentional transient state: a node present in BOTH shared and
        # __failures__. This can't persist in production (mark_node_failed
        # pops shared[node_id] before writing __failures__), but exercises
        # the priority rule so get_node_status is robust if it ever does.
        shared = {
            "node": {"stdout": "stale"},
            "__failures__": {"node": {"data": {}, "category": "exception"}},
        }
        assert get_node_status(shared, "node") == NodeStatus.FAILED

    def test_internal_keys_are_absent(self):
        shared = {"__execution__": {"failed_node": None}}
        assert get_node_status(shared, "__execution__") == NodeStatus.ABSENT


class TestNodeSucceeded:
    def test_yes(self):
        assert node_succeeded({"node": {}}, "node") is True

    def test_no_for_failed(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "exception"}}}
        assert node_succeeded(shared, "node") is False

    def test_no_for_absent(self):
        assert node_succeeded({}, "missing") is False


class TestGetNodeOutput:
    def test_succeeded_returns_data(self):
        shared = {"node": {"stdout": "x"}}
        assert get_node_output(shared, "node") == {"stdout": "x"}

    def test_failed_returns_data_field(self):
        shared = {"__failures__": {"node": {"data": {"stdout": "", "exit_code": 1}, "category": "shell_failure"}}}
        assert get_node_output(shared, "node") == {"stdout": "", "exit_code": 1}

    def test_absent_returns_none(self):
        assert get_node_output({}, "missing") is None


class TestGetNodeFailure:
    def test_failed_returns_record(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "shell_failure", "error": "boom"}}}
        record = get_node_failure(shared, "node")
        assert record["category"] == "shell_failure"
        assert record["error"] == "boom"

    def test_succeeded_returns_none(self):
        assert get_node_failure({"node": {}}, "node") is None

    def test_absent_returns_none(self):
        assert get_node_failure({}, "missing") is None


class TestMarkNodeFailed:
    def _initial_shared(self):
        return {
            "node": {"stdout": "", "exit_code": 1, "command": "exit 1"},
            "__execution__": {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }

    def test_moves_data(self):
        shared = self._initial_shared()
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_SHELL, error="boom")
        assert "node" not in shared
        assert shared["__failures__"]["node"]["category"] == "shell_failure"
        assert shared["__failures__"]["node"]["error"] == "boom"
        assert shared["__failures__"]["node"]["data"] == {
            "stdout": "",
            "exit_code": 1,
            "command": "exit 1",
        }

    def test_sets_failed_node(self):
        shared = self._initial_shared()
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_EXCEPTION, error="boom")
        assert shared["__execution__"]["failed_node"] == "node"

    def test_writes_warning_only_when_given(self):
        shared = self._initial_shared()
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_API_WARNING, warning="API failed")
        assert shared["__warnings__"]["node"] == "API failed"

    def test_no_warning_if_not_given(self):
        shared = self._initial_shared()
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_SHELL, error="boom")
        assert "__warnings__" not in shared

    def test_loop_case_strips_completed_bookkeeping(self):
        shared = self._initial_shared()
        shared["__execution__"]["completed_nodes"].append("node")
        shared["__execution__"]["node_actions"]["node"] = "default"
        shared["__execution__"]["node_hashes"]["node"] = "abc"
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_NODE_ERROR)
        assert "node" not in shared["__execution__"]["completed_nodes"]
        assert "node" not in shared["__execution__"]["node_actions"]
        assert "node" not in shared["__execution__"]["node_hashes"]

    def test_creates_execution_state_if_missing(self):
        shared = {"node": {}}
        mark_node_failed(shared, "node", category=FAILURE_CATEGORY_EXCEPTION)
        assert "__execution__" in shared
        assert shared["__execution__"]["failed_node"] == "node"

    def test_handles_missing_node_data(self):
        shared = {
            "__execution__": {
                "failed_node": None,
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "node_visit_counts": {},
            }
        }
        mark_node_failed(shared, "missing", category=FAILURE_CATEGORY_EXCEPTION, error="boom")
        assert shared["__failures__"]["missing"]["data"] == {}

    def test_rejects_reserved_internal_keys(self):
        """Structural integrity guard: marking ``__execution__`` "failed" would
        write ``__failures__["__execution__"]`` AND ``__execution__["failed_node"]
        = "__execution__"`` — corrupting both dicts. Previously the guard
        silently swallowed the attempt. Now it raises so the bug surfaces
        at the caller site.
        """
        shared: dict = {"__execution__": {"failed_node": None}}
        with pytest.raises(ValueError, match="reserved internal key"):
            mark_node_failed(shared, "__execution__", category=FAILURE_CATEGORY_EXCEPTION, error="boom")
        # State is unchanged by the failed call
        assert "__failures__" not in shared
        assert shared["__execution__"]["failed_node"] is None


class TestClearNodeFailure:
    def test_removes_record(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "exception"}}}
        clear_node_failure(shared, "node")
        assert "node" not in shared["__failures__"]

    def test_no_op_if_absent(self):
        shared = {}
        clear_node_failure(shared, "node")
        assert shared == {}

    def test_clears_warning_mirror(self):
        """Regression guard: a warning written by mark_node_failed(..., warning=...)
        is mirrored into __warnings__. clear_node_failure must pop BOTH dicts or
        a successful loop recovery would leave a stale warning and _determine_status
        would incorrectly report DEGRADED after a clean retry.
        """
        shared: dict = {"__execution__": {}}
        shared["flaky"] = {"error": "Rate limited", "status_code": 429}
        mark_node_failed(
            shared,
            "flaky",
            category=FAILURE_CATEGORY_API_WARNING,
            error="Rate limited",
            warning="API error (429): Rate limited",
        )
        assert "flaky" in shared["__failures__"]
        assert "flaky" in shared["__warnings__"]

        clear_node_failure(shared, "flaky")

        assert "flaky" not in shared["__failures__"]
        assert "flaky" not in shared["__warnings__"]

    def test_preserves_diagnostic_warning_only_in_warnings_channel(self):
        """Structured warnings stay structured in __warnings__ for runner consumers."""
        warning = Diagnostic(
            severity=Severity.WARNING,
            message="Node 'flaky' failed \u2014 on-error \u2192 'handler'",
            node_id="flaky",
            source="runtime",
            context={"type": "on_error_recovery", "category": FAILURE_CATEGORY_SHELL},
        )
        shared: dict = {"__execution__": {}, "flaky": {"error": "boom"}}

        mark_node_failed(
            shared,
            "flaky",
            category=FAILURE_CATEGORY_SHELL,
            error="boom",
            warning=warning,
        )

        assert shared["__warnings__"]["flaky"] is warning
        assert "warning" not in shared["__failures__"]["flaky"]
