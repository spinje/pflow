"""Integration tests for parameter management nodes (Task 17 Subtask 3).

These tests verify the complete parameter management flow across multiple nodes,
including both Path A and Path B convergence scenarios.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import (
    ParameterDiscoveryNode,
    ParameterMappingNode,
    ParameterPreparationNode,
)


@pytest.fixture
def mock_llm_param_discovery():
    """Mock LLM response for ParameterDiscoveryNode with Anthropic's nested structure."""

    def create_response(parameters=None, stdin_type=None):
        """Create mock response with correct nested structure for ParameterDiscovery."""
        response = Mock()
        response.json.return_value = {
            "content": [
                {
                    "input": {
                        "parameters": parameters or {},
                        "stdin_type": stdin_type,
                        "reasoning": "Test parameter discovery reasoning",
                    }
                }
            ]
        }
        return response

    return create_response


@pytest.fixture
def mock_llm_param_extraction():
    """Mock LLM response for ParameterMappingNode with Anthropic's nested structure."""

    def create_response(extracted=None, missing=None, confidence=0.9):
        """Create mock response with correct nested structure for ParameterExtraction."""
        response = Mock()
        response.json.return_value = {
            "content": [
                {
                    "input": {
                        "extracted": extracted or {},
                        "missing": missing or [],
                        "confidence": confidence,
                        "reasoning": "Test parameter extraction reasoning",
                    }
                }
            ]
        }
        return response

    return create_response


@pytest.fixture
def workflow_with_inputs():
    """Sample workflow IR with input parameters defined."""
    return {
        "ir_version": "0.1.0",
        "inputs": {
            "input_file": {
                "type": "string",
                "required": True,
                "description": "Path to input file",
            },
            "output_format": {
                "type": "string",
                "required": False,
                "default": "json",
                "description": "Output format",
            },
            "limit": {
                "type": "integer",
                "required": True,
                "description": "Maximum number of items",
            },
        },
        "nodes": [
            {"id": "n1", "type": "read-file", "params": {"file_path": "{{input_file}}"}},
            {"id": "n2", "type": "transform", "params": {"format": "{{output_format}}"}},
        ],
        "edges": [{"from": "n1", "to": "n2"}],
    }


class TestParameterManagementIntegration:
    """Integration tests for the complete parameter management flow."""

    def test_path_a_convergence_flow(self, mock_llm_param_extraction, workflow_with_inputs):
        """Test Path A convergence: found_workflow → parameter_mapping → preparation."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_param_extraction(
                extracted={"input_file": "test.csv", "limit": "30", "output_format": "json"},
                missing=[],
                confidence=1.0,
            )
            mock_get_model.return_value = mock_model

            # Simulate Path A arriving at parameter mapping
            shared = {
                "user_input": "process test.csv with limit 30",
                "found_workflow": {"ir": workflow_with_inputs},
            }

            # Run parameter mapping (convergence point)
            mapping_node = ParameterMappingNode()
            mapping_node.wait = 0  # Speed up tests
            prep1 = mapping_node.prep(shared)
            exec1 = mapping_node.exec(prep1)
            action1 = mapping_node.post(shared, prep1, exec1)

            assert action1 == "params_complete"
            assert shared["extracted_params"]["input_file"] == "test.csv"

            # Run parameter preparation
            prep_node = ParameterPreparationNode()
            prep2 = prep_node.prep(shared)
            exec2 = prep_node.exec(prep2)
            prep_node.post(shared, prep2, exec2)

            assert shared["execution_params"]["input_file"] == "test.csv"
            assert shared["execution_params"]["limit"] == "30"

    def test_path_b_convergence_flow(self, mock_llm_param_discovery, mock_llm_param_extraction, workflow_with_inputs):
        """Test Path B convergence: param_discovery → (generation) → parameter_mapping → preparation."""
        with patch("llm.get_model") as mock_get_model:
            # Setup for discovery
            mock_model_discovery = Mock()
            mock_model_discovery.prompt.return_value = mock_llm_param_discovery(
                parameters={"file": "input.txt", "max_items": "25"}
            )

            # Setup for mapping
            mock_model_mapping = Mock()
            mock_model_mapping.prompt.return_value = mock_llm_param_extraction(
                extracted={"input_file": "input.txt", "limit": "25"},
                missing=[],
                confidence=0.85,
            )

            # Return different models based on call count
            mock_get_model.side_effect = [mock_model_discovery, mock_model_mapping]

            shared = {
                "user_input": "analyze input.txt with max 25 items",
                "browsed_components": {"node_ids": ["read-file"]},
            }

            # Run parameter discovery (Path B specific)
            discovery_node = ParameterDiscoveryNode()
            discovery_node.wait = 0  # Speed up tests
            prep1 = discovery_node.prep(shared)
            exec1 = discovery_node.exec(prep1)
            discovery_node.post(shared, prep1, exec1)

            assert shared["discovered_params"]["file"] == "input.txt"

            # Simulate generation creating a workflow
            shared["generated_workflow"] = workflow_with_inputs

            # Run parameter mapping (convergence point)
            mapping_node = ParameterMappingNode()
            mapping_node.wait = 0  # Speed up tests
            prep2 = mapping_node.prep(shared)
            exec2 = mapping_node.exec(prep2)
            action2 = mapping_node.post(shared, prep2, exec2)

            # Verify mapping did NOT use discovered_params
            assert "discovered_params" not in prep2
            assert action2 == "params_complete_validate"  # Path B goes to validation

            # Run parameter preparation
            prep_node = ParameterPreparationNode()
            prep3 = prep_node.prep(shared)
            exec3 = prep_node.exec(prep3)
            prep_node.post(shared, prep3, exec3)

            assert shared["execution_params"]["input_file"] == "input.txt"
            assert shared["execution_params"]["limit"] == "25"

    def test_convergence_with_missing_params_triggers_incomplete_path(
        self, mock_llm_param_extraction, workflow_with_inputs, caplog
    ):
        """Test both paths handle missing parameters correctly at convergence."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_param_extraction(
                extracted={"output_format": "xml"},  # Missing required params
                missing=["input_file", "limit"],
                confidence=0.2,
            )
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "convert to xml",
                "found_workflow": {"ir": workflow_with_inputs},
            }

            mapping_node = ParameterMappingNode()
            mapping_node.wait = 0  # Speed up tests
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)

            with caplog.at_level(logging.WARNING):
                action = mapping_node.post(shared, prep_res, exec_res)

            assert action == "params_incomplete"
            assert set(shared["missing_params"]) == {"input_file", "limit"}
            assert "Missing required parameters" in caplog.text

    def test_stdin_fallback_across_all_nodes(self, mock_llm_param_discovery, mock_llm_param_extraction):
        """Test all nodes properly handle stdin as parameter source."""
        with patch("llm.get_model") as mock_get_model:
            # Discovery recognizes stdin
            mock_model_discovery = Mock()
            mock_model_discovery.prompt.return_value = mock_llm_param_discovery(parameters={}, stdin_type="text")

            # Mapping extracts from stdin
            mock_model_mapping = Mock()
            mock_model_mapping.prompt.return_value = mock_llm_param_extraction(
                extracted={"data": "from_stdin"}, missing=[], confidence=0.8
            )

            mock_get_model.side_effect = [mock_model_discovery, mock_model_mapping]

            shared = {
                "user_input": "process the piped input",
                "stdin": "data_from_pipe",
            }

            # Discovery detects stdin
            discovery_node = ParameterDiscoveryNode()
            discovery_node.wait = 0  # Speed up tests
            prep1 = discovery_node.prep(shared)
            assert prep1["stdin_info"]["type"] == "text"
            exec1 = discovery_node.exec(prep1)
            assert exec1["stdin_type"] == "text"

            # Mapping uses stdin
            shared["found_workflow"] = {"ir": {"inputs": {}}}
            mapping_node = ParameterMappingNode()
            mapping_node.wait = 0  # Speed up tests
            prep2 = mapping_node.prep(shared)
            assert prep2["stdin_data"] == "data_from_pipe"
