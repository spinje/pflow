"""High-value tests for API warning detection system."""

import json
from unittest.mock import Mock

from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper


class TestCriticalAPIWarningScenarios:
    """Test the most important real-world scenarios."""

    def test_slack_mcp_channel_not_found(self):
        """Test the exact Slack MCP scenario that prompted this feature."""
        mock_node = Mock()
        mock_node._run = Mock(return_value="default")
        mock_node.node_id = "send_response"

        wrapper = InstrumentedNodeWrapper(mock_node, "send_response")

        # Exact structure from user's trace file
        mcp_response = {"successful": True, "error": None, "data": {"ok": False, "error": "channel_not_found"}}

        shared = {
            "__execution__": {"completed_nodes": [], "node_actions": {}, "node_hashes": {}},
            "send_response": {
                "result": json.dumps(mcp_response)  # MCP stores as JSON string
            },
        }

        # Execute the node
        result = wrapper._run(shared)

        # Verify it prevents repair
        assert result == "error", "Should stop workflow"
        assert shared.get("__non_repairable_error__") is True, "Should prevent repair attempts"
        assert shared["__warnings__"]["send_response"] == "API error: channel_not_found"

    def test_graphql_http_200_with_errors(self):
        """Test GraphQL returning HTTP 200 with errors (common GitHub API case)."""
        wrapper = InstrumentedNodeWrapper(Mock(), "github-graphql")

        shared = {
            "github-graphql": {
                "response": {"errors": [{"message": "Repository not found"}], "data": None},
                "status_code": 200,  # GraphQL always returns 200
            }
        }

        warning = wrapper._detect_api_warning(shared)
        assert warning == "API error: Repository not found"

    def test_http_4xx_not_checked(self):
        """Test that HTTP 4xx/5xx are NOT checked (node already returns error)."""
        wrapper = InstrumentedNodeWrapper(Mock(), "api-call")

        # HTTP node with 404 - should not trigger warning
        # because the node itself returns "error" action
        shared = {"api-call": {"response": {"message": "Not found"}, "status_code": 404}}

        warning = wrapper._detect_api_warning(shared)
        assert warning is None, "Should not check 4xx responses (node handles it)"

    def test_handle_non_repairable_error_adds_warnings_to_errors(self):
        """Test that _handle_non_repairable_error converts warnings to errors.

        The non-repairable error flow:
        1. Node detects API error (tested in test_slack_mcp_channel_not_found)
        2. InstrumentedNodeWrapper sets __non_repairable_error__ flag
        3. execute_workflow checks flag and calls _handle_non_repairable_error
        4. _handle_non_repairable_error adds warnings to errors list

        This test verifies step 4 - the conversion of warnings to errors.
        """
        from pflow.execution import ExecutionResult
        from pflow.execution.workflow_execution import _handle_non_repairable_error

        # Create a result with non-repairable error flag and warnings
        result = ExecutionResult(
            success=False,
            shared_after={
                "__non_repairable_error__": True,
                "__warnings__": {
                    "send_response": "API error: channel_not_found",
                    "another_node": "API error: rate_limited",
                },
            },
            errors=[],
            action_result="error",
            node_count=2,
            duration=1.0,
            output_data=None,
            metrics_summary=None,
        )

        # Call the handler
        handled_result = _handle_non_repairable_error(result)

        # Verify warnings were converted to non_repairable errors
        assert len(handled_result.errors) == 2

        error_messages = [e["message"] for e in handled_result.errors]
        assert "channel_not_found" in error_messages[0] or "channel_not_found" in error_messages[1]
        assert "rate_limited" in error_messages[0] or "rate_limited" in error_messages[1]

        # Verify all errors are marked non_repairable
        for error in handled_result.errors:
            assert error["category"] == "non_repairable"
            assert error["fixable"] is False
            assert error["source"] == "api"

    def test_no_false_positive_on_null_error(self):
        """Test that successful responses with error:null don't trigger warnings.

        This was a real bug - MCP responses include 'error': null for successful
        calls, which triggered our pattern #8 incorrectly.
        """
        wrapper = InstrumentedNodeWrapper(Mock(), "mcp-node")

        # Exact structure from real MCP success response
        mcp_success = {
            "successful": True,
            "error": None,  # This was causing false positive!
            "data": {"ok": True, "messages": [{"text": "Hello"}]},
        }

        shared = {"mcp-node": {"result": json.dumps(mcp_success)}}

        warning = wrapper._detect_api_warning(shared)
        assert warning is None, f"Should not detect warning for successful response with error:null, got: {warning}"

        # Also test direct dict with null error
        shared = {"api": {"success": True, "error": None, "data": {"result": "success"}}}
        wrapper2 = InstrumentedNodeWrapper(Mock(), "api")
        warning = wrapper2._detect_api_warning(shared)
        assert warning is None, "Should not trigger on null error field"

    def test_common_api_patterns(self):
        """Test the most common real-world API error patterns."""
        wrapper = InstrumentedNodeWrapper(Mock(), "api")

        # The new implementation is more conservative - it only blocks repair for clear resource errors
        # Validation errors are allowed through for repair attempts
        critical_patterns = [
            # Slack/Discord - channel_not_found is a resource error
            ({"ok": False, "error": "channel_not_found"}, True),
            # GraphQL - Unauthorized is a resource/permission error
            ({"errors": [{"message": "Unauthorized"}]}, True),
            # REST APIs - Rate limit is a resource error
            ({"status": "error", "message": "Rate limit exceeded"}, True),
            # Authentication errors with standard error format
            ({"success": False, "error_code": "UNAUTHORIZED", "error": "Invalid token"}, True),
            # Not found errors
            ({"ok": False, "error": "user_not_found"}, True),
            # Validation errors - these are now allowed for repair
            ({"ok": False, "error": "invalid_parameter"}, False),
            ({"status": "error", "message": "Invalid input format"}, False),
            # Success cases that should NOT trigger
            ({"ok": True, "data": {"messages": []}}, False),
            ({"status": "success", "result": {"id": 123}}, False),
        ]

        for data, should_warn in critical_patterns:
            shared = {"api": data}
            warning = wrapper._detect_api_warning(shared)

            if should_warn:
                assert warning is not None, f"Should detect error in: {data}"
                assert "API error" in warning
            else:
                assert warning is None, f"Should NOT detect error in: {data}"


class TestIntegrationWithExistingSystems:
    """Test that API warnings integrate properly with existing features."""

    def test_checkpoint_compatibility(self):
        """Test that API warnings are detected and would affect checkpointing."""
        wrapper = InstrumentedNodeWrapper(Mock(), "api-call")

        # Test that permission denied is detected as a resource error
        shared = {
            "api-call": {"ok": False, "error": "permission denied"},
        }

        warning = wrapper._detect_api_warning(shared)

        # Should detect the warning
        assert warning is not None, "Should detect permission denied as API error"
        assert "permission denied" in warning

        # The actual checkpoint behavior is tested in test_slack_mcp_channel_not_found
        # This test just verifies the detection logic for checkpoint-related errors

    def test_loop_detection_fallback(self):
        """Test that loop detection still works if we miss an API error."""
        # This test verifies our safety net is still in place
        # Even if API warning detection misses something,
        # loop detection will catch it after 1-2 attempts

        from pflow.execution.workflow_execution import _get_error_signature

        # Same error before and after repair
        errors1 = [{"message": "Unknown API error pattern", "node_id": "api"}]
        errors2 = [{"message": "Unknown API error pattern", "node_id": "api"}]

        sig1 = _get_error_signature(errors1)
        sig2 = _get_error_signature(errors2)

        assert sig1 == sig2, "Loop detection should identify repeated errors"
