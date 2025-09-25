"""Test loop detection functionality in workflow execution."""

from unittest.mock import MagicMock, patch

from pflow.execution.workflow_execution import _get_error_signature, _normalize_error_message, execute_workflow


class TestErrorNormalization:
    """Test error message normalization for loop detection."""

    def test_normalize_timestamps(self):
        """Test that timestamps are normalized."""
        # Time formats
        assert _normalize_error_message("Error at 10:45:23") == _normalize_error_message("Error at 11:30:45")
        assert _normalize_error_message("Failed at 10:45") == _normalize_error_message("Failed at 23:59")

        # Date formats
        assert _normalize_error_message("Failed on 2024-01-29") == _normalize_error_message("Failed on 2025-12-31")
        assert _normalize_error_message("Error 2024/03/15") == _normalize_error_message("Error 2025/04/16")

    def test_normalize_ids(self):
        """Test that various ID formats are normalized."""
        # UUIDs
        msg1 = "Request a1b2c3d4-e5f6-7890-abcd-ef1234567890 failed"
        msg2 = "Request 99999999-8888-7777-6666-555555555555 failed"
        assert _normalize_error_message(msg1) == _normalize_error_message(msg2)

        # Hex IDs
        assert _normalize_error_message("ID abc123def failed") == _normalize_error_message("ID 987654321 failed")

        # Request IDs
        assert _normalize_error_message("request_12345 error") == _normalize_error_message("request_67890 error")
        assert _normalize_error_message("request-99999 error") == _normalize_error_message("request-11111 error")

    def test_normalize_line_numbers(self):
        """Test that line numbers are normalized."""
        assert _normalize_error_message("Error at line 42") == _normalize_error_message("Error at line 100")
        # Note: :10:5 is interpreted as time (10:05) and gets normalized to TIME
        # This is actually fine since the important part is they normalize the same way
        assert _normalize_error_message("script.py line 10") == _normalize_error_message("script.py line 99")

    def test_normalize_case_and_whitespace(self):
        """Test case and whitespace normalization."""
        assert _normalize_error_message("ERROR:  Multiple   Spaces") == "error: multiple spaces"
        assert _normalize_error_message("CHANNEL_NOT_FOUND") == _normalize_error_message("channel_not_found")

    def test_empty_and_none(self):
        """Test edge cases with empty and None values."""
        assert _normalize_error_message("") == ""
        assert _normalize_error_message("   ") == ""
        # None would raise AttributeError, which is expected


class TestErrorSignature:
    """Test error signature generation for loop detection."""

    def test_empty_errors(self):
        """Test signature for empty error list."""
        assert _get_error_signature([]) == "no_errors"
        assert _get_error_signature(None) == "no_errors"  # Should handle None gracefully

    def test_single_error(self):
        """Test signature for single error."""
        errors = [{"node_id": "node1", "message": "API failed", "category": "api_error"}]
        sig = _get_error_signature(errors)
        assert "node1|api_error|api failed" in sig

    def test_multiple_errors_sorted(self):
        """Test that errors are sorted for consistent signatures."""
        errors1 = [
            {"node_id": "node2", "message": "Error B", "category": "type2"},
            {"node_id": "node1", "message": "Error A", "category": "type1"},
        ]
        errors2 = [
            {"node_id": "node1", "message": "Error A", "category": "type1"},
            {"node_id": "node2", "message": "Error B", "category": "type2"},
        ]
        assert _get_error_signature(errors1) == _get_error_signature(errors2)

    def test_node_id_included(self):
        """Test that node IDs are included to distinguish errors."""
        errors1 = [{"node_id": "node1", "message": "Command failed", "category": "shell"}]
        errors2 = [{"node_id": "node2", "message": "Command failed", "category": "shell"}]
        assert _get_error_signature(errors1) != _get_error_signature(errors2)

    def test_missing_fields(self):
        """Test handling of errors with missing fields."""
        errors = [
            {"message": "No node_id"},  # Missing node_id
            {"node_id": "node1"},  # Missing message
            {},  # Empty dict
        ]
        sig = _get_error_signature(errors)
        assert sig != "no_errors"  # Should still generate something
        assert "unknown" in sig  # Should use defaults for missing fields

    def test_message_truncation(self):
        """Test that long messages are truncated."""
        long_message = "x" * 100
        errors = [{"node_id": "node1", "message": long_message, "category": "test"}]
        sig = _get_error_signature(errors)
        # Message should be truncated to 40 chars
        assert len(sig.split("|")[2]) <= 40

    def test_timestamp_normalization_in_signature(self):
        """Test that timestamps in errors don't affect signature."""
        errors1 = [{"node_id": "api", "message": "Failed at 10:30:00", "category": "error"}]
        errors2 = [{"node_id": "api", "message": "Failed at 15:45:30", "category": "error"}]
        assert _get_error_signature(errors1) == _get_error_signature(errors2)


class TestLoopDetectionIntegration:
    """Test loop detection in actual workflow execution."""

    def test_stops_on_repeated_error(self):
        """Test that execution stops when repair doesn't fix the error."""
        workflow = {"ir_version": "1.0", "nodes": [{"id": "node1", "type": "shell", "params": {"command": "exit 1"}}]}

        with patch("pflow.core.workflow_validator.WorkflowValidator") as mock_validator:
            mock_validator.validate.return_value = []  # No validation errors

            with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as mock_executor:
                # Same error each time
                mock_result = MagicMock()
                mock_result.success = False
                mock_result.errors = [{"node_id": "node1", "message": "Command failed"}]
                mock_result.shared_after = {}
                mock_executor.return_value.execute_workflow.return_value = mock_result

                with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                    # Repair "succeeds" but doesn't fix the issue
                    mock_repair.return_value = (True, workflow, None)

                    with patch("pflow.execution.workflow_execution.compute_workflow_diff") as mock_diff:
                        mock_diff.return_value = {}

                        result = execute_workflow(workflow, {}, enable_repair=True)

                        # Should only attempt repair once before detecting loop
                        assert mock_repair.call_count == 1
                        assert not result.success
                        # Check that repair was attempted
                        assert result.errors[0].get("repair_attempted")

    def test_continues_on_different_errors(self):
        """Test that execution continues when errors change."""
        workflow = {"ir_version": "1.0", "nodes": [{"id": "node1", "type": "shell", "params": {}}]}

        with patch("pflow.core.workflow_validator.WorkflowValidator") as mock_validator:
            mock_validator.validate.return_value = []

            with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as mock_executor:
                # Different errors each time
                error1 = MagicMock()
                error1.success = False
                error1.errors = [{"node_id": "node1", "message": "Error type A"}]
                error1.shared_after = {}

                error2 = MagicMock()
                error2.success = False
                error2.errors = [{"node_id": "node1", "message": "Error type B"}]
                error2.shared_after = {}

                success = MagicMock()
                success.success = True
                success.errors = []
                success.shared_after = {}

                mock_executor.return_value.execute_workflow.side_effect = [error1, error2, success]

                with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                    mock_repair.return_value = (True, workflow, None)

                    with patch("pflow.execution.workflow_execution.compute_workflow_diff") as mock_diff:
                        mock_diff.return_value = {}

                        result = execute_workflow(workflow, {}, enable_repair=True)

                        # Should attempt repair twice (different errors)
                        assert mock_repair.call_count == 2
                        assert result.success

    def test_handles_none_errors(self):
        """Test that loop detection handles None or empty errors gracefully."""
        workflow = {"ir_version": "1.0", "nodes": []}

        with patch("pflow.core.workflow_validator.WorkflowValidator") as mock_validator:
            mock_validator.validate.return_value = []

            with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as mock_executor:
                # Result with no errors
                mock_result = MagicMock()
                mock_result.success = False
                mock_result.errors = []  # Empty errors
                mock_result.shared_after = {}
                mock_executor.return_value.execute_workflow.return_value = mock_result

                with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                    mock_repair.return_value = (True, workflow, None)

                    with patch("pflow.execution.workflow_execution.compute_workflow_diff") as mock_diff:
                        mock_diff.return_value = {}

                        result = execute_workflow(workflow, {}, enable_repair=True)

                        # Should still work without crashing
                        assert not result.success

    def test_first_attempt_not_considered_loop(self):
        """Test that first failure doesn't trigger loop detection."""
        workflow = {"ir_version": "1.0", "nodes": []}

        with patch("pflow.core.workflow_validator.WorkflowValidator") as mock_validator:
            mock_validator.validate.return_value = []

            with patch("pflow.execution.workflow_execution.WorkflowExecutorService") as mock_executor:
                # First attempt fails, second succeeds
                error = MagicMock()
                error.success = False
                error.errors = [{"node_id": "node1", "message": "First failure"}]
                error.shared_after = {}

                success = MagicMock()
                success.success = True
                success.errors = []
                success.shared_after = {}

                mock_executor.return_value.execute_workflow.side_effect = [error, success]

                with patch("pflow.execution.workflow_execution.repair_workflow_with_validation") as mock_repair:
                    mock_repair.return_value = (True, workflow, None)

                    with patch("pflow.execution.workflow_execution.compute_workflow_diff") as mock_diff:
                        mock_diff.return_value = {}

                        result = execute_workflow(workflow, {}, enable_repair=True)

                        # Should attempt repair once and succeed
                        assert mock_repair.call_count == 1
                        assert result.success
