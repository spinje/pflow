"""High-value tests for API warning detection and error formatting system."""

import json
from unittest.mock import Mock

from pflow.execution.executor_service import WorkflowExecutorService
from pflow.runtime.wrappers.api_warning_detector import detect_api_warning
from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper


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

        # Verify it stops workflow execution and records a warning
        assert result == "error", "Should stop workflow"
        assert shared["__warnings__"]["send_response"] == "API error: channel_not_found"

    def test_graphql_http_200_with_errors(self):
        """Test GraphQL returning HTTP 200 with errors (common GitHub API case)."""
        shared = {
            "github-graphql": {
                "response": {"errors": [{"message": "Repository not found"}], "data": None},
                "status_code": 200,  # GraphQL always returns 200
            }
        }

        warning = detect_api_warning("github-graphql", shared)
        assert warning == "API error: Repository not found"

    def test_http_4xx_not_checked(self):
        """Test that HTTP 4xx/5xx are NOT checked (node already returns error)."""
        # HTTP node with 404 - should not trigger warning
        # because the node itself returns "error" action
        shared = {"api-call": {"response": {"message": "Not found"}, "status_code": 404}}

        warning = detect_api_warning("api-call", shared)
        assert warning is None, "Should not check 4xx responses (node handles it)"

    def test_no_false_positive_on_null_error(self):
        """Test that successful responses with error:null don't trigger warnings.

        This was a real bug - MCP responses include 'error': null for successful
        calls, which triggered our pattern #8 incorrectly.
        """
        # Exact structure from real MCP success response
        mcp_success = {
            "successful": True,
            "error": None,  # This was causing false positive!
            "data": {"ok": True, "messages": [{"text": "Hello"}]},
        }

        shared = {"mcp-node": {"result": json.dumps(mcp_success)}}

        warning = detect_api_warning("mcp-node", shared)
        assert warning is None, f"Should not detect warning for successful response with error:null, got: {warning}"

        # Also test direct dict with null error
        shared = {"api": {"success": True, "error": None, "data": {"result": "success"}}}
        warning = detect_api_warning("api", shared)
        assert warning is None, "Should not trigger on null error field"

    def test_common_api_patterns(self):
        """Test the most common real-world API error patterns."""
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
            warning = detect_api_warning("api", shared)

            if should_warn:
                assert warning is not None, f"Should detect error in: {data}"
                assert "API error" in warning
            else:
                assert warning is None, f"Should NOT detect error in: {data}"


class TestIntegrationWithExistingSystems:
    """Test that API warnings integrate properly with existing features."""

    def test_checkpoint_compatibility(self):
        """Test that API warnings are detected and would affect checkpointing."""
        # Test that permission denied is detected as a resource error
        shared = {
            "api-call": {"ok": False, "error": "permission denied"},
        }

        warning = detect_api_warning("api-call", shared)

        # Should detect the warning
        assert warning is not None, "Should detect permission denied as API error"
        assert "permission denied" in warning

        # The actual checkpoint behavior is tested in test_slack_mcp_channel_not_found
        # This test just verifies the detection logic for checkpoint-related errors

    def test_api_warning_detection_reports_resource_errors(self):
        """Test that API warning detection reports resource errors.

        When an API error is detected (e.g., channel_not_found), the
        warning should surface clearly in execution state.
        """
        shared = {
            "api": {"ok": False, "error": "channel_not_found"},
        }

        warning = detect_api_warning("api", shared)
        assert warning is not None, "Should detect channel_not_found as API error"


class TestErrorFormattingSurfacesWarnings:
    """Tests that API warnings survive through the error formatting path.

    These protect against regressions where detection works but the actionable
    message is lost during error list construction. All three bugs were found
    by code reviewers — the detection tests above passed while production
    showed generic "Workflow failed with action: error" messages.
    """

    def test_api_warning_message_reaches_error_list(self):
        """API warning in __warnings__ must appear in _build_error_list output.

        Bug: _extract_error_info never checked __warnings__, so GraphQL 200-with-errors
        produced "Workflow failed with action: error" instead of "API error: Repository not found".
        """
        svc = WorkflowExecutorService()

        shared = {
            "__execution__": {
                "completed_nodes": ["github-graphql"],
                "node_actions": {"github-graphql": "error"},
                "node_hashes": {},
                "failed_node": "github-graphql",
            },
            "__warnings__": {"github-graphql": "API error: Repository not found"},
            "github-graphql": {
                "response": {"errors": [{"message": "Repository not found"}], "data": None},
                "status_code": 200,
            },
        }

        errors = svc._build_error_list(False, "error", shared)
        assert len(errors) >= 1
        assert "Repository not found" in errors[0]["message"]

    def test_mcp_null_error_with_nested_data_error(self):
        """MCP response {"error": null, "data": {"error": "X"}} must surface "X".

        Bug: "error" key present but null → str(None) → user saw "None" as error message.
        After fix for null, nested data.error was still not unwrapped → generic fallback.
        """
        svc = WorkflowExecutorService()

        mcp_response = json.dumps({
            "successful": True,
            "error": None,
            "data": {"ok": False, "error": "channel_not_found"},
        })

        shared = {
            "__execution__": {
                "completed_nodes": ["send"],
                "node_actions": {"send": "error"},
                "node_hashes": {},
                "failed_node": "send",
            },
            "send": {"result": mcp_response},
        }

        errors = svc._build_error_list(False, "error", shared)
        assert len(errors) >= 1
        assert "channel_not_found" in errors[0]["message"]
        assert "None" not in errors[0]["message"]

    def test_api_warning_takes_priority_over_node_error(self):
        """When both __warnings__ and node-level error exist, warning wins.

        The warning message from InstrumentedNodeWrapper is the most actionable
        (e.g., "API error: Repository not found"). The node-level error may be
        a less useful raw message. Priority ordering in _extract_error_info matters.
        """
        svc = WorkflowExecutorService()

        shared = {
            "__execution__": {
                "completed_nodes": ["api-call"],
                "node_actions": {"api-call": "error"},
                "node_hashes": {},
                "failed_node": "api-call",
            },
            "__warnings__": {"api-call": "API error: Rate limit exceeded"},
            "api-call": {"error": "HTTP request failed"},  # Less actionable
        }

        errors = svc._build_error_list(False, "error", shared)
        assert len(errors) >= 1
        assert "Rate limit exceeded" in errors[0]["message"]
        assert "HTTP request failed" not in errors[0]["message"]
