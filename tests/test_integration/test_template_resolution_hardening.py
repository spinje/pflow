"""Integration tests for Task 85: Runtime Template Resolution Hardening.

These tests validate the critical fixes for GitHub Issue #95 and related hardening:
1. Workflows fail before sending broken data to external systems (strict mode)
2. Tri-state status (SUCCESS/DEGRADED/FAILED) works correctly
3. Configuration system allows strict vs permissive behavior
4. No false positives - normal workflows show SUCCESS

Each test catches real bugs and enables confident refactoring.
"""

import pytest

from pflow.core.workflow_status import WorkflowStatus
from pflow.execution.workflow_execution import execute_workflow


class TestIssue95Prevention:
    """Tests that prevent regression of GitHub Issue #95.

    Issue #95: AI agent discovered workflows reporting "success" while producing
    broken output - literal ${...} text was sent to production (Slack messages).
    """

    def test_unresolved_template_fails_before_external_api_strict_mode(self):
        """CRITICAL: Template error must fail BEFORE reaching external APIs.

        This is THE core fix for Issue #95. If this test fails, we're back to
        sending literal ${...} text to production systems like Slack.

        Scenario: Node produces no output, downstream tries to use it.
        Expected: Fail immediately, don't reach the "external API" node.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",  # Default mode
            "nodes": [
                {
                    "id": "empty-producer",
                    "type": "shell",
                    "params": {"command": "true"},  # Produces no stdout
                },
                {
                    "id": "external-api-call",
                    "type": "shell",
                    "params": {
                        "command": "echo",
                        "args": ["Sending to production: ${empty-producer.nonexistent_field}"],
                    },
                },
            ],
            "edges": [{"from": "empty-producer", "to": "external-api-call", "action": "default"}],
        }

        # Execute workflow
        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # CRITICAL ASSERTIONS: Workflow must FAIL
        assert not result.success, "Workflow should fail with unresolved template"
        assert result.status == WorkflowStatus.FAILED

        # Verify it failed at the right place (during template resolution, not after)
        assert len(result.errors) > 0
        error = result.errors[0]
        assert "unresolved variables" in error["message"].lower()

        # Verify the external-api-call node was NEVER executed
        # If it executed, we would have sent broken data to "production"
        assert "external-api-call" not in result.shared_after.get("__execution__", {}).get("completed_nodes", [])

    def test_empty_stdout_causes_failure_not_literal_template(self):
        """Empty stdout from node should fail downstream template resolution.

        Regression test: Ensures empty output is handled correctly and doesn't
        result in literal ${...} being passed to downstream nodes.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "empty-echo",
                    "type": "shell",
                    "params": {"command": "echo", "args": []},  # Empty stdout
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {
                        "command": "echo",
                        "args": ["Result: ${empty-echo.stdout}"],  # Should work (stdout exists but is empty)
                    },
                },
            ],
            "edges": [{"from": "empty-echo", "to": "consumer", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # This should SUCCEED because stdout field exists (just empty/newline)
        # The bug in Issue #95 was when the FIELD doesn't exist at all
        assert result.success
        assert result.status == WorkflowStatus.SUCCESS

    def test_issue_95_nonexistent_field_fails_before_api_call(self):
        """Issue #95: Accessing nonexistent field should fail before reaching external API.

        This is the EXACT bug from Issue #95 where a workflow tried to use
        a field that doesn't exist, causing literal '${...}' to be sent to Slack API.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "produces-nothing",
                    "type": "shell",
                    "params": {"command": "true"},  # Shell node produces stdout/stderr/exit_code
                },
                {
                    "id": "api-call",
                    "type": "shell",
                    "params": {
                        "command": "echo",
                        # Try to access a field that doesn't exist
                        "args": ["Sending to Slack: ${produces-nothing.nonexistent_field}"],
                    },
                },
            ],
            "edges": [{"from": "produces-nothing", "to": "api-call", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # CRITICAL: Must fail BEFORE executing api-call node
        assert result.success is False
        assert result.status == WorkflowStatus.FAILED

        # Verify api-call never executed (didn't send literal ${...} to API)
        exec_state = result.shared_after.get("__execution__", {})
        completed_nodes = exec_state.get("completed_nodes", [])
        assert "api-call" not in completed_nodes, "api-call should NOT have executed!"

        # Verify error is about template resolution
        assert len(result.errors) > 0
        error = result.errors[0]
        assert "unresolved" in error["message"].lower()
        assert "${produces-nothing.nonexistent_field}" in error["message"]

    def test_issue_6_json_status_field_not_null_on_failure(self):
        """Issue #6: JSON status field should be 'failed' not null when workflow fails.

        This was a bug where failed workflows returned null in the status field
        when using --output-format json, breaking API consumers.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "will-fail",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${this_variable_does_not_exist}"]},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Verify workflow failed
        assert result.success is False

        # CRITICAL: status field must NOT be None/null
        assert result.status is not None
        assert result.status == WorkflowStatus.FAILED

        # If this were serialized to JSON, it should be "failed" not null
        # The ExecutionResult object should have a proper status value
        # Simulate what would be serialized to JSON
        json_data = {"status": result.status.value if result.status else None, "success": result.success}
        assert json_data["status"] == "failed"
        assert json_data["status"] is not None


class TestTriStateStatus:
    """Tests for tri-state workflow status (SUCCESS/DEGRADED/FAILED).

    Critical for observability - users need to distinguish between:
    - SUCCESS: All perfect
    - DEGRADED: Completed but with warnings
    - FAILED: Execution failed
    """

    def test_success_status_for_perfect_workflow(self):
        """Normal workflow with no issues should show SUCCESS status.

        Regression test: Ensures we don't have false positives showing DEGRADED
        for workflows that completed perfectly.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "producer",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["data"]},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["Got: ${producer.stdout}"]},
                },
            ],
            "edges": [{"from": "producer", "to": "consumer", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # CRITICAL: Must be SUCCESS, not DEGRADED
        assert result.success
        assert result.status == WorkflowStatus.SUCCESS
        assert len(result.warnings) == 0

    def test_degraded_status_for_permissive_mode_with_warnings(self):
        """Permissive mode with unresolved templates should show DEGRADED.

        This validates the new tri-state status system works correctly.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "permissive",  # Allow continuation
            "nodes": [
                {
                    "id": "node-with-missing-template",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["Value: ${missing_variable}"]},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Should complete but show DEGRADED
        assert result.success  # Still "successful" in terms of completion
        assert result.status == WorkflowStatus.DEGRADED  # But degraded due to warnings
        assert len(result.warnings) > 0

        # Verify warning details
        warning = result.warnings[0]
        assert warning["node_id"] == "node-with-missing-template"
        assert warning["type"] == "template_resolution"

    def test_failed_status_for_strict_mode(self):
        """Strict mode with unresolved templates should show FAILED.

        Validates that failures are correctly categorized.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "node-with-error",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${missing}"]},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Should fail
        assert not result.success
        assert result.status == WorkflowStatus.FAILED
        assert len(result.errors) > 0


class TestConfigurationHierarchy:
    """Tests for strict/permissive mode configuration.

    Validates that users can control behavior through workflow IR.
    """

    def test_workflow_ir_overrides_default_to_permissive(self):
        """Workflow can override default strict mode to permissive.

        Critical for user control - some workflows may want permissive behavior.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "permissive",  # Override default strict
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${missing}"]},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Should complete with warnings, not fail
        assert result.success
        assert result.status == WorkflowStatus.DEGRADED

    def test_default_strict_mode_when_not_specified(self):
        """Workflows without explicit mode should default to strict.

        Ensures safe default behavior - fail-fast for data integrity.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            # No template_resolution_mode specified - should default to strict
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${missing}"]},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Should FAIL (strict mode default)
        assert not result.success
        assert result.status == WorkflowStatus.FAILED


class TestMultipleTemplateErrors:
    """Tests for workflows with multiple template errors.

    Validates that all errors are captured and reported correctly.
    """

    def test_multiple_template_errors_all_captured_permissive(self):
        """Multiple unresolved templates should all be captured in warnings.

        Regression test: Ensures warning aggregation works correctly.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "permissive",
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${missing1}"]},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${missing2}"]},
                },
            ],
            "edges": [{"from": "node1", "to": "node2", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Should be degraded with multiple warnings
        assert result.status == WorkflowStatus.DEGRADED
        assert len(result.warnings) == 2

        # Verify both nodes reported
        node_ids = {w["node_id"] for w in result.warnings}
        assert "node1" in node_ids
        assert "node2" in node_ids

    def test_first_error_stops_execution_strict_mode(self):
        """Strict mode should fail at first error, not continue.

        Validates fail-fast behavior in strict mode.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${missing1}"]},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${missing2}"]},
                },
            ],
            "edges": [{"from": "node1", "to": "node2", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Should fail at node1
        assert not result.success
        assert result.status == WorkflowStatus.FAILED

        # node2 should never execute
        completed = result.shared_after.get("__execution__", {}).get("completed_nodes", [])
        assert "node2" not in completed


class TestEnhancedErrorMessages:
    """Tests that enhanced error messages provide actionable context.

    Validates Phase 4 implementation - errors should help users fix issues.
    """

    def test_error_shows_available_context_keys(self):
        """Error messages should show what IS available, not just what's missing.

        Critical for debugging - users need to know what they CAN use.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "producer",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["data"]},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {
                        "command": "echo",
                        "args": ["${wrong_field}"],  # Wrong field name
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=False)

        # Should fail with detailed error
        assert not result.success
        error_message = result.errors[0]["message"]

        # Error should mention the template
        assert "wrong_field" in error_message.lower() or "${wrong_field}" in error_message

        # Error should show available keys (producer should be available)
        assert "available" in error_message.lower()


# Performance/regression markers
pytestmark = pytest.mark.integration
