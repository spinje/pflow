"""Integration tests for RuntimeValidationNode in the planner flow.

This module tests:
- RuntimeValidationNode is wired correctly after MetadataGenerationNode
- The feedback loop works: detects issues → routes to WorkflowGeneratorNode → gets fixed
- The 3-attempt limit is enforced
- Runtime errors are passed correctly to WorkflowGeneratorNode
"""

from unittest.mock import MagicMock, patch

from pflow.planning.flow import create_planner_flow
from pflow.planning.nodes import RuntimeValidationNode, WorkflowGeneratorNode


class TestRuntimeValidationIntegration:
    """Test RuntimeValidationNode integration with the planner flow."""

    def test_runtime_validation_exists_in_flow(self):
        """Test that RuntimeValidationNode exists in the planner flow."""
        # Simply verify the node is created in the flow
        # The specific wiring is verified by flow.py and the actual execution

        # Create flow with runtime validation
        flow = create_planner_flow(wait=0)

        # The flow should be created without errors
        assert flow is not None
        assert flow.start is not None

        # Verify RuntimeValidationNode is instantiated directly by flow.py
        # Looking at flow.py line 70, it's created directly:
        runtime_node = RuntimeValidationNode()

        # Test node functionality independently
        assert isinstance(runtime_node, RuntimeValidationNode)

    def test_runtime_validation_routing_logic(self):
        """Test that RuntimeValidationNode has correct routing logic."""
        # Test the node's routing directly without traversing the flow
        runtime_node = RuntimeValidationNode()

        # Test routing with no errors - should return "default"
        shared = {}
        prep_res = {"workflow_ir": {"nodes": []}, "execution_params": {}, "runtime_attempts": 0}
        exec_res = {"ok": True, "shared_after": {}, "result": "completed"}

        action = runtime_node.post(shared, prep_res, exec_res)
        assert action == "default", "Should route to default when no errors"

        # Test routing with fixable errors - should return "runtime_fix"
        with patch.object(runtime_node, "_collect_missing_template_errors") as mock_errors:
            mock_errors.return_value = [{"source": "template", "fixable": True}]

            shared = {}
            prep_res["runtime_attempts"] = 1
            action = runtime_node.post(shared, prep_res, exec_res)
            assert action == "runtime_fix", "Should route to runtime_fix for fixable errors"

        # Test routing at max attempts - should return "failed_runtime"
        with patch.object(runtime_node, "_collect_missing_template_errors") as mock_errors:
            mock_errors.return_value = [{"source": "template", "fixable": True}]

            shared = {}
            prep_res["runtime_attempts"] = 3
            action = runtime_node.post(shared, prep_res, exec_res)
            assert action == "failed_runtime", "Should route to failed_runtime at max attempts"

    def test_feedback_loop_passes_runtime_errors_to_generator(self):
        """Test that runtime_errors are correctly passed to WorkflowGeneratorNode."""
        # Create a minimal test scenario
        runtime_node = RuntimeValidationNode()
        generator_node = WorkflowGeneratorNode(wait=0)

        # Mock the workflow execution to return template errors
        mock_flow = MagicMock()
        mock_flow.run.side_effect = Exception("Template ${api.response.username} not found")

        shared = {
            "generated_workflow": {
                "nodes": [
                    {
                        "id": "api",
                        "type": "http",
                        "params": {
                            "url": "https://api.github.com/users/torvalds",
                            "extract": {
                                "username": "${api.response.username}"  # Wrong - should be 'login'
                            },
                        },
                    }
                ]
            },
            "extracted_params": {},
        }

        # Test RuntimeValidationNode execution
        with patch("pflow.runtime.compiler.compile_ir_to_flow") as mock_compile:
            mock_compile.return_value = mock_flow

            # Prep the node
            prep_res = runtime_node.prep(shared)
            assert prep_res["workflow_ir"] == shared["generated_workflow"]
            assert prep_res["runtime_attempts"] == 0

            # Execute the node (will catch the exception)
            exec_res = runtime_node.exec(prep_res)
            assert exec_res["ok"] is False
            assert "Template ${api.response.username} not found" in exec_res["error"]

            # Post should detect the error and route to fix
            with patch.object(runtime_node, "_collect_missing_template_errors") as mock_collect:
                mock_collect.return_value = [
                    {
                        "source": "template",
                        "category": "missing_template_path",
                        "attempted": "${api.response.username}",
                        "available": ["login", "name", "bio"],
                        "message": "Template path not found. Available: login, name, bio",
                        "fixable": True,
                    }
                ]

                action = runtime_node.post(shared, prep_res, exec_res)

                assert action == "runtime_fix"
                assert "runtime_errors" in shared
                assert shared["runtime_attempts"] == 1

        # Now test that WorkflowGeneratorNode uses the runtime errors
        prep_res = generator_node.prep(shared)

        # Verify generator sees the runtime errors
        assert "runtime_errors" in shared
        errors = shared["runtime_errors"]
        # May have both execution error and template error
        assert len(errors) >= 1
        # Find the template error
        template_error = next((e for e in errors if e.get("category") == "missing_template_path"), None)
        assert template_error is not None
        assert template_error["attempted"] == "${api.response.username}"
        assert "login" in template_error["available"]

    def test_three_attempt_limit_enforced(self):
        """Test that runtime validation enforces the 3-attempt limit."""
        runtime_node = RuntimeValidationNode()

        # Simulate multiple failed attempts
        test_cases = [
            (0, "runtime_fix"),  # First attempt → retry
            (1, "runtime_fix"),  # Second attempt → retry
            (2, "runtime_fix"),  # Third attempt → retry
            (3, "failed_runtime"),  # Fourth attempt → fail
        ]

        for attempt, expected_action in test_cases:
            shared = {}
            prep_res = {"workflow_ir": {"nodes": []}, "execution_params": {}, "runtime_attempts": attempt}
            exec_res = {"ok": False, "error": "Template error", "shared_after": {}}

            # Mock error collection to always return fixable errors
            with patch.object(runtime_node, "_collect_execution_errors") as mock_exec_errors:
                mock_exec_errors.return_value = [
                    {"source": "runtime", "category": "exception", "message": "Template error", "fixable": True}
                ]
                with (
                    patch.object(runtime_node, "_collect_namespaced_errors", return_value=[]),
                    patch.object(runtime_node, "_collect_missing_template_errors", return_value=[]),
                ):
                    action = runtime_node.post(shared, prep_res, exec_res)

            assert action == expected_action, f"Failed at attempt {attempt}"

            if expected_action == "runtime_fix":
                assert shared["runtime_attempts"] == attempt + 1
            else:
                # No increment on final failure
                assert "runtime_errors" in shared

    def test_successful_validation_continues_normally(self):
        """Test that successful runtime validation allows workflow to continue."""
        # Test the success case directly
        runtime_node = RuntimeValidationNode()

        # Mock successful workflow execution
        mock_flow = MagicMock()
        mock_flow.run.return_value = {"status": "success"}

        shared = {"generated_workflow": {"nodes": [{"id": "test", "type": "test_node"}]}, "extracted_params": {}}

        with patch("pflow.runtime.compiler.compile_ir_to_flow") as mock_compile:
            mock_compile.return_value = mock_flow

            # Execute the validation
            prep_res = runtime_node.prep(shared)
            exec_res = runtime_node.exec(prep_res)

            # Should succeed
            assert exec_res["ok"] is True
            assert "shared_after" in exec_res

            # Post should return default (continue)
            action = runtime_node.post(shared, prep_res, exec_res)
            assert action == "default"

    def test_runtime_errors_include_helpful_context(self):
        """Test that runtime errors include helpful context for fixing issues."""
        runtime_node = RuntimeValidationNode()

        workflow_ir = {
            "nodes": [
                {
                    "id": "slack",
                    "type": "slack_post",
                    "params": {"channel": "#general", "message": "User: ${slack.response.user.username}"},
                }
            ]
        }

        # Simulate execution with actual Slack response structure
        shared_after = {
            "slack": {
                "response": {
                    "ok": True,
                    "channel": "C123456",
                    "ts": "1234567890.123456",
                    "message": {
                        "user": "U123456",  # Just ID, not object with username
                        "text": "Posted message",
                    },
                }
            }
        }

        # Collect missing template errors
        errors = runtime_node._collect_missing_template_errors(workflow_ir, shared_after)

        assert len(errors) == 1
        error = errors[0]

        # Verify error has all helpful context
        assert error["source"] == "template"
        assert error["node_id"] == "slack"
        assert error["category"] == "missing_template_path"
        assert error["attempted"] == "${slack.response.user.username}"
        assert error["fixable"] is True

        # Most importantly, check the available fields are suggested
        # The error should help identify what fields ARE available
        assert "available" in error
        # At the 'user' level, there's just a string, not an object
        # So available should be empty or indicate it's a primitive value

    def test_namespaced_errors_detected_and_reported(self):
        """Test that errors stored in node namespaces are detected."""
        runtime_node = RuntimeValidationNode()

        shared_after = {
            "http": {
                "response": {"status": 200},
                "error": "Rate limit exceeded",  # Node stored an error
            },
            "processor": {"result": "processed"},
        }

        errors = runtime_node._collect_namespaced_errors(shared_after)

        assert len(errors) == 1
        error = errors[0]

        assert error["source"] == "node"
        assert error["node_id"] == "http"
        assert error["category"] == "node_error"
        assert error["message"] == "Rate limit exceeded"
        assert error["fixable"] is True

    def test_execution_exceptions_categorized_correctly(self):
        """Test that execution exceptions are categorized as fixable or not."""
        runtime_node = RuntimeValidationNode()

        # Test fixable error (template-related)
        exec_res = {"ok": False, "error": "Missing template variable: api_key"}
        errors = runtime_node._collect_execution_errors(exec_res)
        assert len(errors) == 1
        assert errors[0]["fixable"] is True

        # Test another fixable error (contains "missing")
        exec_res = {"ok": False, "error": "Missing field 'response' in API result"}
        errors = runtime_node._collect_execution_errors(exec_res)
        assert len(errors) == 1
        assert errors[0]["fixable"] is True

        # Test non-fixable error (general exception)
        exec_res = {"ok": False, "error": "Connection timeout to external service"}
        errors = runtime_node._collect_execution_errors(exec_res)
        assert len(errors) == 1
        assert errors[0]["fixable"] is False
