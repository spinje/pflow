"""Smoke tests for the complete planner flow.

These tests verify basic execution of the planner flow without full integration.
They use heavy mocking to ensure fast, deterministic tests.

The validation flow has been redesigned to extract parameters BEFORE validation,
allowing workflows with required inputs to pass validation correctly.
"""

import json
from unittest.mock import Mock, patch

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning import create_planner_flow


class TestPlannerSmoke:
    """Basic smoke tests for planner execution."""

    @pytest.fixture
    def test_workflow(self):
        """A simple test workflow."""
        return {
            "name": "test-workflow",
            "description": "Test workflow for smoke tests",
            "version": "1.0.0",
            "ir": {
                "ir_version": "0.1.0",
                "nodes": [{"id": "node1", "type": "test-node", "params": {"param": "${input}"}}],
                "edges": [],
                "start_node": "node1",
                "inputs": {"input": {"description": "Test input", "type": "string", "required": True}},
            },
        }

    @pytest.fixture
    def mock_llm_discovery_found(self):
        """Mock LLM that finds an existing workflow."""

        def mock_response(*args, **kwargs):
            response = Mock()
            response.text.return_value = json.dumps({
                "found": True,
                "workflow_name": "test-workflow",
                "confidence": 0.95,
                "reasoning": "Exact match found",
            })
            return response

        return mock_response

    @pytest.fixture
    def mock_llm_discovery_not_found(self):
        """Mock LLM that doesn't find a workflow."""

        def mock_response(*args, **kwargs):
            response = Mock()
            response.text.return_value = json.dumps({
                "found": False,
                "workflow_name": None,
                "confidence": 0.0,
                "reasoning": "No matching workflow",
            })
            return response

        return mock_response

    @pytest.fixture
    def mock_llm_param_extraction(self):
        """Mock LLM that extracts parameters - matches ParameterExtraction model."""

        def mock_response(*args, **kwargs):
            response = Mock()
            response.text.return_value = json.dumps({
                "extracted": {  # Correct field per ParameterExtraction model
                    "input": "test_value"  # Direct value, not nested object
                },
                "missing": [],  # No missing parameters
                "confidence": 0.9,
                "reasoning": "Extracted all parameters",
            })
            return response

        return mock_response

    def test_path_a_smoke(self, tmp_path, test_workflow, mock_llm_discovery_found, mock_llm_param_extraction):
        """Smoke test for Path A execution."""
        # Create test workflow manager
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))
        test_manager.save(
            name="test-workflow", workflow_ir=test_workflow["ir"], description="Test workflow for smoke tests"
        )

        # Mock LLM
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.side_effect = [
                mock_llm_discovery_found(),  # Discovery finds workflow
                mock_llm_param_extraction(),  # Parameter extraction
            ]
            mock_get_model.return_value = mock_model

            # Create and run flow
            flow = create_planner_flow(wait=0)
            shared = {"user_input": "run test workflow", "workflow_manager": test_manager}

            # Execute flow
            flow.run(shared)

            # Verify result
            assert "planner_output" in shared
            output = shared["planner_output"]
            assert output["success"] is True
            assert output["workflow_ir"] is not None
            assert output["execution_params"] is not None
            assert output["error"] is None

    def test_path_a_missing_params(self, tmp_path, test_workflow, mock_llm_discovery_found):
        """Test Path A with missing parameters."""
        # Create test workflow manager
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))
        test_manager.save(
            name="test-workflow", workflow_ir=test_workflow["ir"], description="Test workflow for smoke tests"
        )

        # Mock LLM - no parameters extracted
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.side_effect = [
                mock_llm_discovery_found(),  # Discovery finds workflow
                Mock(
                    text=lambda: json.dumps({
                        "extracted": {},
                        "missing": ["input"],
                        "confidence": 0.3,
                        "reasoning": "Missing required input parameter",
                    })
                ),  # Missing required param
            ]
            mock_get_model.return_value = mock_model

            # Create and run flow
            flow = create_planner_flow(wait=0)
            shared = {"user_input": "run test workflow", "workflow_manager": test_manager}

            # Execute flow
            flow.run(shared)

            # Verify result
            assert "planner_output" in shared
            output = shared["planner_output"]
            assert output["success"] is False
            assert output["error"] is not None
            assert "Missing required parameters" in output["error"]

    def test_flow_handles_missing_user_input(self, tmp_path):
        """Test that flow raises ValueError when required user_input is missing."""
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))

        # Create flow without user_input
        flow = create_planner_flow(wait=0)
        shared = {"workflow_manager": test_manager}

        # Execute flow - should raise ValueError for missing required input
        # This is correct behavior: missing required inputs should fail fast
        with pytest.raises(ValueError, match="Missing required 'user_input'"):
            flow.run(shared)
