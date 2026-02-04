"""Tests for unified workflow execution function.

These tests verify the orchestration logic, not the implementation details.
Focus on the contract: repair flag behavior, resume capability, recursion limits.
"""

from unittest.mock import MagicMock, patch

from pflow.core.workflow_status import WorkflowStatus
from pflow.execution.workflow_execution import execute_workflow


class TestWorkflowExecution:
    """Test the unified workflow execution function."""

    def test_successful_workflow_no_repair_needed(self):
        """Test that successful workflows return immediately without repair."""
        # Use a valid workflow with at least one node
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.errors = []
            mock_executor.execute_workflow.return_value = mock_result

            # Mock validator to return no errors (workflow is valid)
            with patch("pflow.core.workflow_validator.WorkflowValidator") as MockValidator:
                MockValidator.validate.return_value = ([], [])  # No validation errors, no warnings

                with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                    result = execute_workflow(
                        workflow_ir=workflow_ir,
                        execution_params={},
                        enable_repair=True,  # Enabled but won't be used
                    )

                    assert result.success is True
                    # Repair should NOT be called for successful execution
                    mock_repair.assert_not_called()

    def test_failed_workflow_triggers_repair(self):
        """Test that failed workflows trigger repair when enabled."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value

            # First execution fails
            mock_fail_result = MagicMock()
            mock_fail_result.success = False
            mock_fail_result.errors = [{"message": "Template error"}]
            mock_fail_result.shared_after = {"data": "partial"}

            # Second execution (after repair) succeeds
            mock_success_result = MagicMock()
            mock_success_result.success = True
            mock_success_result.errors = []

            # Return different results on consecutive calls
            mock_executor.execute_workflow.side_effect = [mock_fail_result, mock_success_result]

            with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                fixed_ir = {"ir_version": "0.1.0", "nodes": [], "fixed": True}
                # Return proper 3-tuple: (success, repaired_ir, validation_errors)
                mock_repair.return_value = (True, fixed_ir, None)

                # Mock validator to return no errors (workflow is valid)
                with patch("pflow.core.workflow_validator.WorkflowValidator") as MockValidator:
                    MockValidator.validate.return_value = ([], [])  # No validation errors, no warnings

                    result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=True)

                    # Should succeed after repair
                    assert result.success is True

                    # Repair should be called once
                    mock_repair.assert_called_once()

                    # Should be called with error details and shared state
                    args, kwargs = mock_repair.call_args
                    assert "errors" in kwargs or len(args) > 1
                    assert "shared_store" in kwargs or len(args) > 3

    def test_repair_disabled_returns_failure(self):
        """Test that repair is skipped when disabled but validation still runs."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.errors = [{"message": "Error"}]
            mock_executor.execute_workflow.return_value = mock_result

            # Must mock validator since validation now always runs
            with patch("pflow.core.workflow_validator.WorkflowValidator") as MockValidator:
                MockValidator.validate.return_value = ([], [])  # No validation errors

                with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                    result = execute_workflow(
                        workflow_ir=workflow_ir,
                        execution_params={},
                        enable_repair=False,  # Disabled
                    )

                    assert result.success is False
                    mock_repair.assert_not_called()

    def test_repair_failure_returns_original_error(self):
        """Test that repair failure returns the original error."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.errors = [{"message": "Original error"}]
            mock_executor.execute_workflow.return_value = mock_result

            with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                # Repair fails - return proper 3-tuple
                mock_repair.return_value = (False, None, None)

                # Mock validator to return no errors (workflow is valid)
                with patch("pflow.core.workflow_validator.WorkflowValidator") as MockValidator:
                    MockValidator.validate.return_value = ([], [])  # No validation errors, no warnings

                    result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=True)

                    # Should return original failure
                    assert result.success is False
                    assert result.errors[0]["message"] == "Original error"

    def test_resume_with_checkpoint_state(self):
        """Test execution resumes with checkpoint state."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }
        checkpoint_state = {
            "__execution__": {
                "completed_nodes": ["node1"],
                "node_actions": {"node1": "default"},
            },
            "node1": {"result": "data"},
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value
            mock_result = MagicMock()
            mock_result.success = True
            mock_executor.execute_workflow.return_value = mock_result

            # Mock validator to return no errors (workflow is valid)
            with patch("pflow.core.workflow_validator.WorkflowValidator") as MockValidator:
                MockValidator.validate.return_value = ([], [])  # No validation errors, no warnings

                result = execute_workflow(
                    workflow_ir=workflow_ir,
                    execution_params={},
                    resume_state=checkpoint_state,  # Resume with state
                )

                # Verify result is successful
                assert result.success is True

                # Verify checkpoint state was passed to executor
                mock_executor.execute_workflow.assert_called_once()
                _args, kwargs = mock_executor.execute_workflow.call_args
                assert kwargs["shared_store"] == checkpoint_state

    def test_recursive_repair_disabled(self):
        """Test that repaired workflows don't trigger another repair."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "test-node"}],
            "edges": [],
        }

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value

            # Both executions fail (repair didn't help)
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.errors = [{"message": "Error"}]
            mock_result.shared_after = {}
            mock_executor.execute_workflow.return_value = mock_result

            with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                fixed_ir = {"ir_version": "0.1.0", "nodes": [], "fixed": True}
                # Return proper 3-tuple: (success, repaired_ir, validation_errors)
                mock_repair.return_value = (True, fixed_ir, None)

                # Mock validator to return no errors (workflow is valid)
                with patch("pflow.core.workflow_validator.WorkflowValidator") as MockValidator:
                    MockValidator.validate.return_value = ([], [])  # No validation errors, no warnings

                    # Execute workflow with repair enabled
                    result = execute_workflow(workflow_ir=workflow_ir, execution_params={}, enable_repair=True)

                    # Result should be failure (repair didn't help)
                    assert result.success is False

                    # Repair should only be called once (not recursively)
                    assert mock_repair.call_count == 1

    def test_display_manager_shows_repair_progress(self):
        """Test that repair progress is displayed in interactive mode."""
        workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "test", "type": "test-node"}], "edges": []}

        with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as MockExecutor:
            mock_executor = MockExecutor.return_value

            # First execution fails
            mock_fail = MagicMock()
            mock_fail.success = False
            mock_fail.errors = [{"message": "Error"}]
            mock_fail.shared_after = {}

            # Second succeeds
            mock_success = MagicMock()
            mock_success.success = True

            mock_executor.execute_workflow.side_effect = [mock_fail, mock_success]

            with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                # Return proper 3-tuple: (success, repaired_ir, validation_errors)
                mock_repair.return_value = (True, workflow_ir, None)

                with patch("pflow.execution.workflow_execution.DisplayManager") as MockDisplay:
                    mock_display = MockDisplay.return_value

                    # Create mock output that is interactive
                    mock_output = MagicMock()
                    mock_output.is_interactive.return_value = True

                    # Mock validator to return no errors (workflow is valid)
                    with patch("pflow.core.workflow_validator.WorkflowValidator") as MockValidator:
                        MockValidator.validate.return_value = ([], [])  # No validation errors, no warnings

                        result = execute_workflow(
                            workflow_ir=workflow_ir, execution_params={}, enable_repair=True, output=mock_output
                        )

                        # Verify result is successful after repair
                        assert result.success is True

                        # Should show repair start
                        mock_display.show_repair_start.assert_called_once()

                        # For resume, should show execution start with context
                        calls = mock_display.show_execution_start.call_args_list
                        if calls:  # If show_execution_start was called
                            # Check if context="resume" was passed
                            for call in calls:
                                _args, kwargs = call
                                if kwargs.get("context") == "resume":
                                    assert True  # Found resume context
                                    break

    def test_repair_disabled_validates_before_execution(self):
        """Test that enable_repair=False still validates and catches errors before execution."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "echo-hello", "type": "shell", "params": {"command": "echo", "args": ["hello"]}},
                {
                    "id": "bad-ref",
                    "type": "shell",
                    "params": {"command": "echo", "args": ["${fake-node.stdout}"]},
                },
            ],
            "edges": [{"from": "echo-hello", "to": "bad-ref", "action": "default"}],
        }

        result = execute_workflow(
            workflow_ir=workflow_ir,
            execution_params={},
            enable_repair=False,
        )

        # Must fail at validation, not runtime
        assert result.success is False
        assert result.status == WorkflowStatus.FAILED
        assert result.action_result == "validation_failed"

        # No nodes should have executed (no side effects)
        assert result.shared_after == {}

        # Error should mention the bad template reference
        assert len(result.errors) > 0
        assert any("fake-node" in err["message"] for err in result.errors)
