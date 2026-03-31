"""Test API warning detection with non-dict outputs (binary data case).

Tests for detect_api_warning and its helper functions from the engine's
api_warning_detector module. Also tests that the engine handles non-dict
node outputs (strings, bytes, lists, etc.) without crashing during API
warning checks.

Migrated from wrapper-based tests to standalone function tests and
compile_ir_to_flow shim tests after the wrappers were replaced by the
engine (Task 135/138).
"""

from typing import Any

from pflow.pocketflow import Node
from pflow.runtime.engine.api_warning_detector import (
    detect_api_warning,
    extract_error_code,
    extract_error_message,
    unwrap_mcp_response,
)
from pflow.runtime.engine.instrumentation import (
    cache_result,
    initialize_execution_state,
)


class MockNode(Node):
    """Minimal test node that writes pre-set output to shared store."""

    def __init__(self, node_id: str = "test_node", output: Any = None):
        super().__init__()
        self._node_id = node_id
        self._output = output

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        return "ok"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        if self._output is not None:
            shared[self._node_id] = self._output
        return "default"


def _run_node_with_output(node_id: str, output: Any) -> dict[str, Any]:
    """Execute a node that writes the given output, then run API warning check.

    Uses standalone instrumentation functions to simulate what the engine does.
    Returns the shared store after execution.
    """
    shared: dict[str, Any] = {node_id: output}
    initialize_execution_state(shared)

    # Run API warning detection (same as engine step 10)
    warning = detect_api_warning(node_id, shared)
    if warning:
        if "__warnings__" not in shared:
            shared["__warnings__"] = {}
        shared["__warnings__"][node_id] = warning
    else:
        # Mark as completed (same as engine step 11)
        cache_result(node_id, "hash123", "default", shared)

    return shared


class TestApiWarningDetectorBinarySupport:
    """Test that detect_api_warning handles non-dict outputs without crashing."""

    def test_string_output_no_crash(self):
        """Test that string output from node doesn't crash API warning check."""
        shared = _run_node_with_output("test_node", "iVBORw0KGgoAAAANSUhEUgAAAAUA")
        assert shared["__execution__"]["completed_nodes"] == ["test_node"]

    def test_bytes_output_no_crash(self):
        """Test that bytes output from node doesn't crash API warning check."""
        shared = _run_node_with_output("binary_node", b"\x89PNG\r\n\x1a\n")
        assert shared["__execution__"]["completed_nodes"] == ["binary_node"]

    def test_list_output_no_crash(self):
        """Test that list output from node doesn't crash API warning check."""
        shared = _run_node_with_output("list_node", ["item1", "item2", "item3"])
        assert shared["__execution__"]["completed_nodes"] == ["list_node"]

    def test_int_output_no_crash(self):
        """Test that integer output from node doesn't crash API warning check."""
        shared = _run_node_with_output("count_node", 42)
        assert shared["__execution__"]["completed_nodes"] == ["count_node"]

    def test_none_output_no_crash(self):
        """Test that None output from node doesn't crash API warning check."""
        shared = _run_node_with_output("none_node", None)
        assert shared["__execution__"]["completed_nodes"] == ["none_node"]

    def test_dict_output_still_checks_warnings(self):
        """Test that dict outputs still get API warning checks."""
        shared = _run_node_with_output("api_node", {"success": False, "error": "Resource not found"})

        # Check that warning was detected
        assert shared.get("__warnings__", {}).get("api_node") is not None
        warning = shared["__warnings__"]["api_node"]
        assert "Resource not found" in warning or "API request failed" in warning

    def test_unwrap_mcp_response_with_non_dict(self):
        """Test unwrap_mcp_response handles non-dict correctly."""
        assert unwrap_mcp_response("string") is None
        assert unwrap_mcp_response(123) is None
        assert unwrap_mcp_response([1, 2, 3]) is None
        assert unwrap_mcp_response(None) is None
        assert unwrap_mcp_response(b"bytes") is None

    def test_extract_error_code_with_non_dict(self):
        """Test extract_error_code handles non-dict safely."""
        assert extract_error_code("string") is None
        assert extract_error_code(123) is None
        assert extract_error_code(None) is None
        assert extract_error_code([]) is None

    def test_extract_error_message_with_non_dict(self):
        """Test extract_error_message handles non-dict safely."""
        assert extract_error_message("string") is None
        assert extract_error_message(123) is None
        assert extract_error_message(None) is None
        assert extract_error_message([]) is None

    def test_http_binary_response_scenario(self):
        """Test realistic scenario: HTTP node returning binary response as string."""
        # Dict with response field (HTTP node format)
        shared_dict = _run_node_with_output(
            "download_image",
            {
                "response": "iVBORw0KGgoAAAANSUhEUgAAAAUA...",
                "response_is_binary": True,
                "status_code": 200,
                "response_headers": {"content-type": "image/png"},
            },
        )
        assert "download_image" in shared_dict["__execution__"]["completed_nodes"]

        # Direct string (edge case from a bug)
        shared_str = _run_node_with_output("download_image", "iVBORw0KGgoAAAANSUhEUgAAAAUA...")
        assert "download_image" in shared_str["__execution__"]["completed_nodes"]
