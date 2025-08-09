"""Unit tests for component browsing and selection logic.

WHEN TO RUN: Always run these tests - they're fast and use mocks.
These tests verify component selection, over-inclusive strategies, and browsing behavior.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import ComponentBrowsingNode


@pytest.fixture
def mock_registry():
    """Mock registry with test data."""
    registry = Mock()
    registry.load.return_value = {
        "read-file": {
            "module": "pflow.nodes.file.read_file",
            "class_name": "ReadFileNode",
            "interface": {
                "description": "Read content from a file",
                "inputs": [{"key": "file_path", "type": "str"}],
                "outputs": [{"key": "content", "type": "str"}],
            },
        },
        "llm": {
            "module": "pflow.nodes.llm.llm_node",
            "class_name": "LLMNode",
            "interface": {
                "description": "Process text with LLM",
                "inputs": [{"key": "prompt", "type": "str"}],
                "outputs": [{"key": "response", "type": "str"}],
            },
        },
    }
    return registry


@pytest.fixture
def mock_llm_response_nested():
    """Mock LLM response with CRITICAL nested structure for Anthropic."""

    def create_response(found=False, workflow_name=None, confidence=0.8, node_ids=None, workflow_names=None):
        """Create mock response with correct nested structure."""
        response = Mock()

        if node_ids is not None or workflow_names is not None:
            # ComponentSelection response
            response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "node_ids": node_ids or [],
                            "workflow_names": workflow_names or [],
                            "reasoning": "Test reasoning for component selection",
                        }
                    }
                ]
            }
        else:
            # WorkflowDecision response
            response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "found": found,
                            "workflow_name": workflow_name,
                            "confidence": confidence,
                            "reasoning": "Test reasoning for decision",
                        }
                    }
                ]
            }
        return response

    return create_response


class TestComponentBrowsingSelection:
    """Tests for ComponentBrowsingNode selection logic."""

    def test_init_configurable_parameters(self):
        """Test node initializes with configurable retry parameters."""
        # Test default parameters
        node = ComponentBrowsingNode(max_retries=2, wait=0)  # Speed up tests
        assert node.max_retries == 2
        assert node.wait == 0

        # Test configurable parameters
        node2 = ComponentBrowsingNode(max_retries=3, wait=2.5)
        assert node2.max_retries == 3
        assert node2.wait == 2.5

    def test_prep_loads_registry_and_context(self, mock_registry):
        """Test prep phase loads registry metadata and builds context."""
        with (
            patch("pflow.planning.nodes.Registry") as mock_reg_class,
            patch("pflow.planning.nodes.build_discovery_context") as mock_build,
        ):
            mock_reg_class.return_value = mock_registry
            mock_build.return_value = "discovery context"

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {"user_input": "process files"}

            result = node.prep(shared)

            assert result["user_input"] == "process files"
            assert result["discovery_context"] == "discovery context"
            assert result["registry_metadata"] == mock_registry.load()
            assert result["model_name"] == "anthropic/claude-sonnet-4-0"  # Default model
            assert result["temperature"] == 0.0  # Default temperature

            mock_build.assert_called_once_with(
                node_ids=None, workflow_names=None, registry_metadata=mock_registry.load(), workflow_manager=None
            )

    def test_exec_extracts_nested_response_correctly(self, mock_llm_response_nested):
        """CRITICAL TEST: Verify nested response extraction for component selection."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(
                node_ids=["read-file", "llm", "write-file"], workflow_names=["data-pipeline", "text-processor"]
            )
            mock_get_model.return_value = mock_model

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "process CSV and generate report",
                "discovery_context": "test context",
                "registry_metadata": {},
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            result = node.exec(prep_res)

            # Verify lazy loading of model happens in exec
            mock_get_model.assert_called_once_with("anthropic/claude-sonnet-4-0")

            # Verify nested extraction worked
            assert result["node_ids"] == ["read-file", "llm", "write-file"]
            assert result["workflow_names"] == ["data-pipeline", "text-processor"]
            assert result["reasoning"] == "Test reasoning for component selection"

    def test_exec_uses_over_inclusive_prompt(self, mock_llm_response_nested):
        """Test exec uses over-inclusive selection strategy in prompt."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(node_ids=[], workflow_names=[])
            mock_get_model.return_value = mock_model

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "test request",
                "discovery_context": "components",
                "registry_metadata": {},
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            node.exec(prep_res)

            # Verify prompt encourages over-inclusion
            call_args = mock_model.prompt.call_args
            prompt = call_args[0][0]
            assert "BE OVER-INCLUSIVE" in prompt
            assert "even 20% relevance" in prompt
            assert "Include supporting nodes" in prompt
            assert "Better to include too many" in prompt

    def test_post_always_routes_to_generate(self):
        """Test post always routes to 'generate' for Path B continuation."""
        with patch("pflow.planning.nodes.build_planning_context") as mock_build:
            mock_build.return_value = "detailed planning context"

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"registry_metadata": {"test": "metadata"}}
            exec_res = {
                "node_ids": ["read-file", "llm"],
                "workflow_names": ["pipeline"],
                "reasoning": "Selected components",
            }

            action = node.post(shared, prep_res, exec_res)

            assert action == "generate"  # Always routes to generate
            assert shared["browsed_components"] == exec_res
            assert shared["registry_metadata"] == {"test": "metadata"}
            assert shared["planning_context"] == "detailed planning context"

    def test_post_builds_planning_context_with_selections(self):
        """Test post correctly calls build_planning_context with selections."""
        with patch("pflow.planning.nodes.build_planning_context") as mock_build:
            mock_build.return_value = "context"

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"registry_metadata": {"meta": "data"}}
            exec_res = {"node_ids": ["n1", "n2"], "workflow_names": ["w1"], "reasoning": "reason"}

            node.post(shared, prep_res, exec_res)

            mock_build.assert_called_once_with(
                selected_node_ids=["n1", "n2"],
                selected_workflow_names=["w1"],
                registry_metadata={"meta": "data"},
                saved_workflows=None,
                workflow_manager=None,
            )

    def test_model_configuration_via_params(self, mock_llm_response_nested, mock_registry):
        """Test that model name and temperature can be configured via params."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(node_ids=["n1"], workflow_names=["w1"])
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.Registry") as mock_reg_class:
                mock_reg_class.return_value = mock_registry

                with patch("pflow.planning.nodes.build_discovery_context") as mock_build:
                    mock_build.return_value = "test context"

                    # Configure custom model and temperature via params
                    node = ComponentBrowsingNode()
                    node.wait = 0  # Speed up tests
                    node.params = {"model": "gpt-4-turbo", "temperature": 0.7}

                    shared = {"user_input": "test"}
                    prep_res = node.prep(shared)

                    # Verify prep phase gets config from params
                    assert prep_res["model_name"] == "gpt-4-turbo"
                    assert prep_res["temperature"] == 0.7

                    # Execute and verify model is loaded with custom name
                    node.exec(prep_res)
                    mock_get_model.assert_called_once_with("gpt-4-turbo")

                    # Verify temperature is passed to prompt
                    call_args = mock_model.prompt.call_args
                    assert call_args[1]["temperature"] == 0.7
