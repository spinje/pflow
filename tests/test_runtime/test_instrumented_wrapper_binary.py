"""Test InstrumentedWrapper with non-dict outputs (binary data case)."""

from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper


class MockNode:
    """Mock node that doesn't cause infinite loops in wrapper traversal."""

    def __init__(self, node_id="test_node"):
        self.node_id = node_id
        # No inner_node, _inner_node, or _wrapped attributes

    def _run(self, shared):
        return "default"


class TestInstrumentedWrapperBinarySupport:
    """Test that InstrumentedWrapper handles non-dict outputs without crashing."""

    def test_string_output_no_crash(self):
        """Test that string output from node doesn't crash wrapper."""
        # Create a proper mock node
        mock_node = MockNode("test_node")

        # Create wrapper
        wrapper = InstrumentedNodeWrapper(mock_node, "test_node")

        # Create shared store with string output (simulating base64 binary data)
        shared = {
            "test_node": "iVBORw0KGgoAAAANSUhEUgAAAAUA"  # Simulated base64 string
        }

        # Execute - should not crash when checking for API warnings
        result = wrapper._run(shared)

        assert result == "default"
        assert shared["__execution__"]["completed_nodes"] == ["test_node"]

    def test_bytes_output_no_crash(self):
        """Test that bytes output from node doesn't crash wrapper."""
        # Create a proper mock node
        mock_node = MockNode("binary_node")

        # Create wrapper
        wrapper = InstrumentedNodeWrapper(mock_node, "binary_node")

        # Create shared store with bytes output (actual binary data)
        shared = {
            "binary_node": b"\x89PNG\r\n\x1a\n"  # PNG header bytes
        }

        # Execute - should not crash when checking for API warnings
        result = wrapper._run(shared)

        assert result == "default"
        assert shared["__execution__"]["completed_nodes"] == ["binary_node"]

    def test_list_output_no_crash(self):
        """Test that list output from node doesn't crash wrapper."""
        # Create a proper mock node
        mock_node = MockNode("list_node")

        # Create wrapper
        wrapper = InstrumentedNodeWrapper(mock_node, "list_node")

        # Create shared store with list output (e.g., JSON array response)
        shared = {"list_node": ["item1", "item2", "item3"]}

        # Execute - should not crash
        result = wrapper._run(shared)

        assert result == "default"
        assert shared["__execution__"]["completed_nodes"] == ["list_node"]

    def test_int_output_no_crash(self):
        """Test that integer output from node doesn't crash wrapper."""
        # Create a proper mock node
        mock_node = MockNode("count_node")

        # Create wrapper
        wrapper = InstrumentedNodeWrapper(mock_node, "count_node")

        # Create shared store with integer output
        shared = {"count_node": 42}

        # Execute - should not crash
        result = wrapper._run(shared)

        assert result == "default"
        assert shared["__execution__"]["completed_nodes"] == ["count_node"]

    def test_none_output_no_crash(self):
        """Test that None output from node doesn't crash wrapper."""
        # Create a proper mock node
        mock_node = MockNode("none_node")

        # Create wrapper
        wrapper = InstrumentedNodeWrapper(mock_node, "none_node")

        # Create shared store with None output
        shared = {"none_node": None}

        # Execute - should not crash
        result = wrapper._run(shared)

        assert result == "default"
        assert shared["__execution__"]["completed_nodes"] == ["none_node"]

    def test_dict_output_still_checks_warnings(self):
        """Test that dict outputs still get API warning checks."""
        # Create a proper mock node
        mock_node = MockNode("api_node")

        # Create wrapper
        wrapper = InstrumentedNodeWrapper(mock_node, "api_node")

        # Create shared store with dict containing API error
        shared = {"api_node": {"success": False, "error": "Resource not found"}}

        # Execute - should detect API warning
        wrapper._run(shared)

        # Check that warning was detected
        assert shared.get("__warnings__", {}).get("api_node") is not None
        warning = shared["__warnings__"]["api_node"]
        assert "Resource not found" in warning or "API request failed" in warning

    def test_unwrap_mcp_response_with_non_dict(self):
        """Test _unwrap_mcp_response handles non-dict correctly."""
        mock_node = MockNode()
        wrapper = InstrumentedNodeWrapper(mock_node, "test")

        # Test with various non-dict types
        assert wrapper._unwrap_mcp_response("string") is None
        assert wrapper._unwrap_mcp_response(123) is None
        assert wrapper._unwrap_mcp_response([1, 2, 3]) is None
        assert wrapper._unwrap_mcp_response(None) is None
        assert wrapper._unwrap_mcp_response(b"bytes") is None

    def test_extract_error_code_with_non_dict(self):
        """Test _extract_error_code handles non-dict safely."""
        mock_node = MockNode()
        wrapper = InstrumentedNodeWrapper(mock_node, "test")

        # Should return None for non-dict inputs
        assert wrapper._extract_error_code("string") is None
        assert wrapper._extract_error_code(123) is None
        assert wrapper._extract_error_code(None) is None
        assert wrapper._extract_error_code([]) is None

    def test_extract_error_message_with_non_dict(self):
        """Test _extract_error_message handles non-dict safely."""
        mock_node = MockNode()
        wrapper = InstrumentedNodeWrapper(mock_node, "test")

        # Should return None for non-dict inputs
        assert wrapper._extract_error_message("string") is None
        assert wrapper._extract_error_message(123) is None
        assert wrapper._extract_error_message(None) is None
        assert wrapper._extract_error_message([]) is None

    def test_http_binary_response_scenario(self):
        """Test realistic scenario: HTTP node returning binary response as string."""
        # This simulates what happens when HTTP node downloads an image
        mock_http_node = MockNode("download_image")

        wrapper = InstrumentedNodeWrapper(mock_http_node, "download_image")

        # Simulate HTTP node storing base64-encoded image
        shared = {
            "download_image": {
                "response": "iVBORw0KGgoAAAANSUhEUgAAAAUA...",  # base64 string
                "response_is_binary": True,
                "status_code": 200,
                "response_headers": {"content-type": "image/png"},
            }
        }

        # Should work fine - wrapper sees dict with response field
        result = wrapper._run(shared)
        assert result == "default"

        # Now test the case where response is returned directly (issue from bug)
        shared = {
            "download_image": "iVBORw0KGgoAAAANSUhEUgAAAAUA..."  # Direct string
        }

        # Should not crash even with direct string
        result = wrapper._run(shared)
        assert result == "default"
