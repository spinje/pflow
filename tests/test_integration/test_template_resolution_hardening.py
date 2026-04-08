"""Integration tests for Task 85: Runtime Template Resolution Hardening.

These tests validate the critical fixes for GitHub Issue #95 and related hardening:
1. Workflows fail before sending broken data to external systems
2. Tri-state status (SUCCESS/DEGRADED/FAILED) works correctly
3. Static validation catches template errors before execution begins
4. No false positives - normal workflows show SUCCESS

Each test catches real bugs and enables confident refactoring.

FIX HISTORY:
- Original: Tests assumed template errors were caught at runtime (during execution).
- Updated: execute_workflow() now runs WorkflowValidator.validate() before execution
  even when enable_repair=False. Template errors are caught at validation time,
  meaning shared_after is {} (no execution happened) and action_result is
  "validation_failed". This is STRONGER behavior - errors are caught earlier.
- Permissive mode tests: The static WorkflowValidator does not respect
  template_resolution_mode - it catches all invalid templates as errors.
  Tests that previously expected DEGRADED status with permissive mode now
  verify that the static validator catches errors (FAILED status).
- Latest: execute_workflow() no longer runs WorkflowValidator.validate() — callers
  own their preconditions. The compiler runs data flow + template validation as
  defense-in-depth. Undefined variables are caught by data flow validation
  (CompilationError, action_result="compilation_failed"). Invalid field access
  on existing nodes is caught by template validation (ValueError,
  action_result="error").
"""

import pytest

from pflow.core.diagnostic import format_diagnostic
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def execute_workflow(workflow_ir: dict, execution_params: dict, **_kwargs: object) -> object:
    """Compatibility shim: routes old execute_workflow() calls through WorkflowRunner."""
    return WorkflowRunner().run(workflow_ir, execution_params, RunnerConfig())


class TestIssue95Prevention:
    """Tests that prevent regression of GitHub Issue #95.

    Issue #95: AI agent discovered workflows reporting "success" while producing
    broken output - literal ${...} text was sent to production (Slack messages).
    """

    def test_unresolved_template_fails_before_external_api_strict_mode(self):
        """CRITICAL: Template error must fail BEFORE reaching external APIs.

        This is THE core fix for Issue #95. If this test fails, we're back to
        sending literal ${...} text to production systems like Slack.

        Scenario: Node produces no output, downstream tries to use nonexistent field.
        Expected: Fail at compilation, before any node executes.
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
                        "command": "echo 'Sending to production: ${empty-producer.nonexistent_field}'",
                    },
                },
            ],
            "edges": [{"from": "empty-producer", "to": "external-api-call", "action": "default"}],
        }

        # Execute workflow
        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # CRITICAL ASSERTIONS: Workflow must FAIL
        assert not result.success, "Workflow should fail with unresolved template"
        assert result.status == WorkflowStatus.FAILED

        # Verify it failed before any user nodes executed
        assert len(result.errors) > 0
        error = result.errors[0]
        # Validator catches that nonexistent_field is not a valid shell output
        assert "nonexistent_field" in error.message

        # No user nodes should have completed
        completed = result.shared_after.get("__execution__", {}).get("completed_nodes", [])
        assert "external-api-call" not in completed

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
                    "params": {"command": "echo"},  # Empty stdout
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {
                        "command": "echo 'Result: ${empty-echo.stdout}'",  # Should work (stdout exists but is empty)
                    },
                },
            ],
            "edges": [{"from": "empty-echo", "to": "consumer", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

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
                        "command": "echo 'Sending to Slack: ${produces-nothing.nonexistent_field}'",
                    },
                },
            ],
            "edges": [{"from": "produces-nothing", "to": "api-call", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # CRITICAL: Must fail BEFORE executing api-call node
        assert result.success is False
        assert result.status == WorkflowStatus.FAILED

        # Verify error is about the nonexistent field
        assert len(result.errors) > 0
        error = result.errors[0]
        assert "nonexistent_field" in error.message

        # No user nodes should have completed
        completed = result.shared_after.get("__execution__", {}).get("completed_nodes", [])
        assert "api-call" not in completed

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
                    "params": {"command": "echo '${this_variable_does_not_exist}'"},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

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
                    "cache": False,
                    "params": {"command": "echo data"},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {"command": "echo 'Got: ${producer.stdout}'"},
                },
            ],
            "edges": [{"from": "producer", "to": "consumer", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # CRITICAL: Must be SUCCESS, not DEGRADED
        assert result.success
        assert result.status == WorkflowStatus.SUCCESS
        assert len(result.warnings) == 0

    def test_invalid_template_caught_at_compilation_in_permissive_mode(self):
        """Compiler catches invalid templates regardless of permissive mode.

        The compiler's template validation catches undefined variables.
        Permissive mode only affects runtime resolution, but the compiler
        prevents execution from starting.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "permissive",  # Does not affect compiler validation
            "nodes": [
                {
                    "id": "node-with-missing-template",
                    "type": "shell",
                    "params": {"command": "echo 'Value: ${missing_variable}'"},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # Template validation catches the invalid template before execution
        assert not result.success
        assert result.status == WorkflowStatus.FAILED
        assert len(result.errors) > 0

        # Error should mention the missing variable
        error_message = result.errors[0].message
        assert "missing_variable" in error_message

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
                    "params": {"command": "echo '${missing}'"},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # Should fail
        assert not result.success
        assert result.status == WorkflowStatus.FAILED
        assert len(result.errors) > 0


class TestConfigurationHierarchy:
    """Tests for strict/permissive mode configuration.

    Validates that users can control behavior through workflow IR.
    """

    def test_permissive_mode_still_fails_compilation_for_unknown_templates(self):
        """Permissive mode does not bypass compiler validation.

        The compiler catches templates referencing unknown variables
        regardless of template_resolution_mode setting.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "permissive",  # Override default strict
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {"command": "echo '${missing}'"},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # Template validation catches it - fails before execution
        assert not result.success
        assert result.status == WorkflowStatus.FAILED

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
                    "params": {"command": "echo '${missing}'"},
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # Should FAIL (strict mode default)
        assert not result.success
        assert result.status == WorkflowStatus.FAILED


class TestMultipleTemplateErrors:
    """Tests for workflows with multiple template errors.

    Validates that all errors are captured and reported correctly.
    """

    def test_multiple_template_errors_all_captured_at_compilation(self):
        """Multiple unresolved templates should all be captured as compilation errors.

        Data flow validation catches both undefined variables and raises a
        single CompilationError containing all error messages.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "permissive",
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {"command": "echo '${missing1}'"},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo '${missing2}'"},
                },
            ],
            "edges": [{"from": "node1", "to": "node2", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # Template validation catches both errors before execution
        assert not result.success
        assert result.status == WorkflowStatus.FAILED

        # Both template errors should be captured in the error message
        error_messages = " ".join(error.message for error in result.errors)
        assert "missing1" in error_messages
        assert "missing2" in error_messages

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
                    "params": {"command": "echo '${missing1}'"},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "echo '${missing2}'"},
                },
            ],
            "edges": [{"from": "node1", "to": "node2", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # Should fail
        assert not result.success
        assert result.status == WorkflowStatus.FAILED

        # No execution happened - node2 was never reached
        completed = result.shared_after.get("__execution__", {}).get("completed_nodes", [])
        assert "node2" not in completed


class TestEnhancedErrorMessages:
    """Tests that enhanced error messages provide actionable context.

    Validates Phase 4 implementation - errors should help users fix issues.
    """

    def test_error_shows_available_outputs_for_invalid_field(self):
        """Error messages should show what IS available when accessing invalid field.

        Critical for debugging - users need to know what they CAN use.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "template_resolution_mode": "strict",
            "nodes": [
                {
                    "id": "producer",
                    "type": "shell",
                    "params": {"command": "echo data"},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {"command": "echo '${producer.wrong_field}'"},
                },
            ],
            "edges": [{"from": "producer", "to": "consumer", "action": "default"}],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        # Should fail with detailed error
        assert not result.success
        error = result.errors[0]
        error_message = error.message
        rendered = format_diagnostic(error)

        # Error should mention the wrong field
        assert "wrong_field" in error_message

        # Error should show available outputs from producer (stdout, stderr, etc.)
        assert "available" in rendered.lower()


# Performance/regression markers
pytestmark = pytest.mark.integration
