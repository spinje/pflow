"""Comprehensive tests for ResultPreparationNode.

Tests cover all three entry scenarios:
1. Success path from ParameterPreparationNode (both Path A and Path B)
2. Missing parameters from ParameterMappingNode
3. Failed generation from ValidatorNode after 3 attempts

Tests verify:
- Success determination logic
- Error message construction
- Output format compliance with spec
- Flow termination (post() returns None)
- Both Path A (found_workflow) and Path B (generated_workflow) sources
"""

from unittest.mock import patch

import pytest

from pflow.planning.nodes import ResultPreparationNode


class TestResultPreparationNode:
    """Test ResultPreparationNode final output packaging."""

    @pytest.fixture
    def result_node(self):
        """Create ResultPreparationNode instance."""
        return ResultPreparationNode()

    @pytest.fixture
    def valid_workflow_ir(self):
        """Valid workflow IR for testing."""
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "test.txt"}},
                {"id": "n2", "type": "llm", "params": {"prompt": "Process this"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
        }

    @pytest.fixture
    def execution_params(self):
        """Valid execution parameters."""
        return {
            "input_file": "data.txt",
            "output_dir": "./output",
        }

    @pytest.fixture
    def workflow_metadata(self):
        """Sample workflow metadata."""
        return {
            "name": "test-workflow",
            "description": "A test workflow",
            "tags": ["test", "example"],
        }

    # Success Path Tests (Entry Point 1: From ParameterPreparationNode)

    def test_success_path_a_found_workflow(self, result_node, valid_workflow_ir, execution_params, workflow_metadata):
        """Test successful result from Path A (found existing workflow)."""
        shared = {
            "found_workflow": {
                "ir": valid_workflow_ir,
                "name": "existing-workflow",
            },
            "execution_params": execution_params,
            "workflow_metadata": workflow_metadata,
            "discovery_result": {
                "found": True,
                "workflow_name": "existing-workflow",
            },
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify success
        assert exec_res["success"] is True
        assert exec_res["workflow_ir"] == valid_workflow_ir
        assert exec_res["execution_params"] == execution_params
        assert exec_res["workflow_metadata"] == workflow_metadata
        assert exec_res["error"] is None
        assert exec_res["missing_params"] is None

    def test_success_path_b_generated_workflow(
        self, result_node, valid_workflow_ir, execution_params, workflow_metadata
    ):
        """Test successful result from Path B (generated new workflow)."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": execution_params,
            "workflow_metadata": workflow_metadata,
            "generation_attempts": 1,
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify success
        assert exec_res["success"] is True
        assert exec_res["workflow_ir"] == valid_workflow_ir
        assert exec_res["execution_params"] == execution_params
        assert exec_res["workflow_metadata"] == workflow_metadata
        assert exec_res["error"] is None
        assert exec_res["missing_params"] is None

    def test_path_a_takes_precedence_over_path_b(
        self, result_node, valid_workflow_ir, execution_params, workflow_metadata
    ):
        """Test that Path A (found_workflow) takes precedence when both paths have data."""
        path_a_workflow = {**valid_workflow_ir, "source": "path_a"}
        path_b_workflow = {**valid_workflow_ir, "source": "path_b"}

        shared = {
            "found_workflow": {"ir": path_a_workflow},
            "generated_workflow": path_b_workflow,  # Should be ignored
            "execution_params": execution_params,
            "workflow_metadata": workflow_metadata,
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify Path A workflow was used
        assert exec_res["success"] is True
        assert exec_res["workflow_ir"]["source"] == "path_a"

    # Missing Parameters Tests (Entry Point 2: From ParameterMappingNode)

    def test_missing_parameters_failure(self, result_node, valid_workflow_ir):
        """Test failure due to missing parameters from ParameterMappingNode."""
        missing_params = ["api_key", "output_file", "threshold"]

        shared = {
            "generated_workflow": valid_workflow_ir,
            "missing_params": missing_params,
            "execution_params": {"partial": "param"},  # Some params but not all
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify failure
        assert exec_res["success"] is False
        assert exec_res["workflow_ir"] is None
        assert exec_res["execution_params"] is None
        assert exec_res["missing_params"] == missing_params
        assert "Missing required parameters: api_key, output_file, threshold" in exec_res["error"]

    def test_missing_params_with_no_workflow(self, result_node):
        """Test missing parameters with no workflow available."""
        missing_params = ["input_file"]

        shared = {
            "missing_params": missing_params,
            # No workflow_ir available
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify failure with multiple error components
        assert exec_res["success"] is False
        assert exec_res["workflow_ir"] is None
        assert exec_res["missing_params"] == missing_params
        assert "No workflow found or generated" in exec_res["error"]
        assert "Missing required parameters: input_file" in exec_res["error"]

    # Failed Generation Tests (Entry Point 3: From ValidatorNode)

    def test_failed_generation_after_three_attempts(self, result_node):
        """Test failure from ValidatorNode after 3 generation attempts."""
        validation_errors = [
            "Invalid node type: unknown-node",
            "Missing required field: ir_version",
            "Circular dependency detected",
            "Fourth error that should be truncated",
        ]

        shared = {
            "generation_attempts": 3,
            "validation_errors": validation_errors,
            # No valid workflow_ir
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify failure
        assert exec_res["success"] is False
        assert exec_res["workflow_ir"] is None
        assert exec_res["error"] == (
            "Workflow generation failed after 3 attempts. "
            "Validation errors: Invalid node type: unknown-node; "
            "Missing required field: ir_version; Circular dependency detected"
        )
        # Note: Only first 3 errors included

    def test_validation_errors_without_max_attempts(self, result_node):
        """Test validation errors when attempts < 3."""
        validation_errors = ["Node 'n1' references unknown type"]

        shared = {
            "generation_attempts": 2,  # Less than 3
            "validation_errors": validation_errors,
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify failure
        assert exec_res["success"] is False
        assert "No workflow found or generated" in exec_res["error"]
        assert "Validation errors: Node 'n1' references unknown type" in exec_res["error"]

    # Edge Cases and Error Conditions

    def test_no_execution_params(self, result_node, valid_workflow_ir):
        """Test failure when execution_params is None."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            # execution_params is missing/None
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify failure - success requires execution_params
        assert exec_res["success"] is False
        assert exec_res["workflow_ir"] is None
        assert "Unknown error occurred" in exec_res["error"]

    def test_empty_execution_params_is_valid(self, result_node, valid_workflow_ir):
        """Test that empty dict for execution_params is considered valid."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": {},  # Empty but not None
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify success - empty params dict is valid
        assert exec_res["success"] is True
        assert exec_res["execution_params"] == {}

    def test_multiple_error_conditions(self, result_node):
        """Test error message construction with multiple failure reasons."""
        shared = {
            # No workflow
            "generation_attempts": 3,
            "missing_params": ["param1", "param2"],
            "validation_errors": ["Error 1", "Error 2"],
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify all error components are included
        assert exec_res["success"] is False
        error = exec_res["error"]
        assert "Workflow generation failed after 3 attempts" in error
        assert "Missing required parameters: param1, param2" in error
        assert "Validation errors: Error 1; Error 2" in error

    def test_unknown_error_fallback(self, result_node):
        """Test unknown error message when no specific error conditions exist."""
        shared = {
            # No workflow, no params, no specific errors
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify unknown error
        assert exec_res["success"] is False
        assert exec_res["error"] == "No workflow found or generated"

    # Post Method Tests

    def test_post_returns_none_for_flow_termination(self, result_node, valid_workflow_ir, execution_params):
        """Test that post() returns None to terminate the flow."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": execution_params,
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)
        action = result_node.post(shared, prep_res, exec_res)

        # Verify flow termination
        assert action is None

    def test_post_stores_planner_output_in_shared(self, result_node, valid_workflow_ir, execution_params):
        """Test that post() stores the planner_output in shared store."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": execution_params,
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)
        result_node.post(shared, prep_res, exec_res)

        # Verify output is stored
        assert "planner_output" in shared
        assert shared["planner_output"] == exec_res
        assert shared["planner_output"]["success"] is True

    @patch("pflow.planning.nodes.logger")
    def test_post_logs_success_for_path_a(self, mock_logger, result_node, valid_workflow_ir, execution_params):
        """Test that post() logs success message for Path A (found workflow)."""
        shared = {
            "found_workflow": {"ir": valid_workflow_ir},
            "execution_params": execution_params,
            "discovery_result": {
                "found": True,
                "workflow_name": "test-workflow",
            },
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)
        result_node.post(shared, prep_res, exec_res)

        # Verify logging
        mock_logger.info.assert_any_call("Planner completed successfully")
        mock_logger.info.assert_any_call("Reused existing workflow: test-workflow")

    @patch("pflow.planning.nodes.logger")
    def test_post_logs_success_for_path_b(self, mock_logger, result_node, valid_workflow_ir, execution_params):
        """Test that post() logs success message for Path B (generated workflow)."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": execution_params,
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)
        result_node.post(shared, prep_res, exec_res)

        # Verify logging
        mock_logger.info.assert_any_call("Planner completed successfully")
        mock_logger.info.assert_any_call("Generated new workflow")

    @patch("pflow.planning.nodes.logger")
    def test_post_logs_failure(self, mock_logger, result_node):
        """Test that post() logs failure message."""
        shared = {
            "missing_params": ["param1"],
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)
        result_node.post(shared, prep_res, exec_res)

        # Verify failure logging
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "Planner failed:" in warning_call
        assert "Missing required parameters: param1" in warning_call

    # Output Format Compliance Tests

    def test_output_format_success(self, result_node, valid_workflow_ir, execution_params, workflow_metadata):
        """Test that successful output matches the expected format."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": execution_params,
            "workflow_metadata": workflow_metadata,
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify output structure
        assert isinstance(exec_res, dict)
        assert "success" in exec_res
        assert "workflow_ir" in exec_res
        assert "execution_params" in exec_res
        assert "missing_params" in exec_res
        assert "error" in exec_res
        assert "workflow_metadata" in exec_res

        # Verify success values
        assert exec_res["success"] is True
        assert exec_res["workflow_ir"] is not None
        assert exec_res["execution_params"] is not None
        assert exec_res["missing_params"] is None
        assert exec_res["error"] is None
        assert exec_res["workflow_metadata"] is not None

    def test_output_format_failure(self, result_node):
        """Test that failure output matches the expected format."""
        shared = {
            "missing_params": ["param1"],
            "validation_errors": ["Error 1"],
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify output structure
        assert isinstance(exec_res, dict)
        assert "success" in exec_res
        assert "workflow_ir" in exec_res
        assert "execution_params" in exec_res
        assert "missing_params" in exec_res
        assert "error" in exec_res
        assert "workflow_metadata" in exec_res

        # Verify failure values
        assert exec_res["success"] is False
        assert exec_res["workflow_ir"] is None
        assert exec_res["execution_params"] is None
        assert exec_res["missing_params"] == ["param1"]
        assert exec_res["error"] is not None
        assert exec_res["workflow_metadata"] is None

    def test_empty_metadata_not_included(self, result_node, valid_workflow_ir, execution_params):
        """Test that empty workflow_metadata is set to None in output."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": execution_params,
            "workflow_metadata": {},  # Empty metadata
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify empty metadata becomes None
        assert exec_res["workflow_metadata"] is None

    def test_empty_missing_params_not_included(self, result_node, valid_workflow_ir, execution_params):
        """Test that empty missing_params list is set to None in output."""
        shared = {
            "generated_workflow": valid_workflow_ir,
            "execution_params": execution_params,
            "missing_params": [],  # Empty list
        }

        prep_res = result_node.prep(shared)
        exec_res = result_node.exec(prep_res)

        # Verify empty list becomes None
        assert exec_res["missing_params"] is None

    # Prep Method Data Gathering Tests

    def test_prep_gathers_all_data(self, result_node, valid_workflow_ir, execution_params, workflow_metadata):
        """Test that prep() gathers all relevant data from shared store."""
        shared = {
            "found_workflow": {"ir": valid_workflow_ir},
            "generated_workflow": {"different": "workflow"},  # Should be ignored
            "execution_params": execution_params,
            "missing_params": ["param1"],
            "validation_errors": ["error1"],
            "generation_attempts": 2,
            "workflow_metadata": workflow_metadata,
            "discovery_result": {"found": True},
        }

        prep_res = result_node.prep(shared)

        # Verify all data gathered
        assert prep_res["workflow_ir"] == valid_workflow_ir  # From found_workflow
        assert prep_res["execution_params"] == execution_params
        assert prep_res["missing_params"] == ["param1"]
        assert prep_res["validation_errors"] == ["error1"]
        assert prep_res["generation_attempts"] == 2
        assert prep_res["workflow_metadata"] == workflow_metadata
        assert prep_res["discovery_result"] == {"found": True}

    def test_prep_handles_missing_keys_gracefully(self, result_node):
        """Test that prep() handles missing keys with defaults."""
        shared = {}  # Empty shared store

        prep_res = result_node.prep(shared)

        # Verify defaults
        assert prep_res["workflow_ir"] is None
        assert prep_res["execution_params"] is None
        assert prep_res["missing_params"] == []
        assert prep_res["validation_errors"] == []
        assert prep_res["generation_attempts"] == 0
        assert prep_res["workflow_metadata"] == {}
        assert prep_res["discovery_result"] is None
