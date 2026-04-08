"""Unit tests for runtime/node_state.py failure bookkeeping helpers."""

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
    node_succeeded,
)


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


class TestClearNodeFailure:
    def test_removes_record(self):
        shared = {"__failures__": {"node": {"data": {}, "category": "exception"}}}
        clear_node_failure(shared, "node")
        assert "node" not in shared["__failures__"]

    def test_no_op_if_absent(self):
        shared = {}
        clear_node_failure(shared, "node")
        assert shared == {}
