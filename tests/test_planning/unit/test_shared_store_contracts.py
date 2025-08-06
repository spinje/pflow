"""Unit tests for shared store data flow contracts.

WHEN TO RUN: Always run these tests - they're fast and use mocks.
These tests verify data flow between nodes and shared store updates.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import ComponentBrowsingNode, WorkflowDiscoveryNode


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


class TestSharedStoreContracts:
    """Tests for shared store data flow and contracts."""

    def test_init_configurable_parameters_discovery(self):
        """Test discovery node initializes with configurable retry parameters."""
        # Test default parameters
        node = WorkflowDiscoveryNode(max_retries=2, wait=0)  # Speed up tests
        assert node.max_retries == 2
        assert node.wait == 0

        # Test configurable parameters
        node2 = WorkflowDiscoveryNode(max_retries=3, wait=2.5)
        assert node2.max_retries == 3
        assert node2.wait == 2.5

    def test_prep_builds_discovery_context(self):
        """Test prep phase builds discovery context correctly."""
        with patch("pflow.planning.nodes.build_discovery_context") as mock_build:
            mock_build.return_value = "test context"

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            shared = {"user_input": "create a data pipeline"}

            result = node.prep(shared)

            assert result["user_input"] == "create a data pipeline"
            assert result["discovery_context"] == "test context"
            assert result["model_name"] == "anthropic/claude-sonnet-4-0"  # Default model
            assert result["temperature"] == 0.0  # Default temperature
            mock_build.assert_called_once_with(node_ids=None, workflow_names=None, registry_metadata=None)

    def test_exec_extracts_nested_response_correctly(self, mock_llm_response_nested):
        """CRITICAL TEST: Verify nested response extraction pattern works."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(
                found=True, workflow_name="data-pipeline", confidence=0.95
            )
            mock_get_model.return_value = mock_model

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "create a data pipeline",
                "discovery_context": "test context",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            result = node.exec(prep_res)

            # Verify lazy loading of model happens in exec
            mock_get_model.assert_called_once_with("anthropic/claude-sonnet-4-0")

            # Verify nested extraction worked
            assert result["found"] is True
            assert result["workflow_name"] == "data-pipeline"
            assert result["confidence"] == 0.95
            assert result["reasoning"] == "Test reasoning for decision"

    def test_exec_handles_not_found_case(self, mock_llm_response_nested):
        """Test exec handles case when no workflow matches."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(found=False, workflow_name=None, confidence=0.2)
            mock_get_model.return_value = mock_model

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "do something unique",
                "discovery_context": "test context",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            result = node.exec(prep_res)

            assert result["found"] is False
            assert result["workflow_name"] is None
            assert result["confidence"] == 0.2

    def test_exec_sends_correct_prompt_to_llm(self, mock_llm_response_nested):
        """Test exec sends properly formatted prompt to LLM."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(found=False)
            mock_get_model.return_value = mock_model

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "analyze CSV files",
                "discovery_context": "available workflows and nodes here",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            node.exec(prep_res)

            # Verify prompt structure
            call_args = mock_model.prompt.call_args
            prompt = call_args[0][0]
            assert "analyze CSV files" in prompt
            assert "available workflows and nodes here" in prompt
            assert "COMPLETELY satisfies" in prompt
            assert "found=true ONLY if" in prompt

            # Verify schema parameter
            from pflow.planning.nodes import WorkflowDecision

            assert call_args[1]["schema"] == WorkflowDecision
            assert call_args[1]["temperature"] == 0

    def test_model_configuration_via_params(self, mock_llm_response_nested):
        """Test that model name and temperature can be configured via params."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(found=False)
            mock_get_model.return_value = mock_model

            # Configure custom model and temperature via params
            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            node.params = {"model": "gpt-4", "temperature": 0.5}

            with patch("pflow.planning.nodes.build_discovery_context") as mock_build:
                mock_build.return_value = "test context"

                shared = {"user_input": "test"}
                prep_res = node.prep(shared)

                # Verify prep phase gets config from params
                assert prep_res["model_name"] == "gpt-4"
                assert prep_res["temperature"] == 0.5

                # Execute and verify model is loaded with custom name
                node.exec(prep_res)
                mock_get_model.assert_called_once_with("gpt-4")

                # Verify temperature is passed to prompt
                call_args = mock_model.prompt.call_args
                assert call_args[1]["temperature"] == 0.5

    def test_path_b_flow_no_match_then_browse(self, mock_registry, mock_llm_response_nested):
        """Test Path B flow: discovery finds no match, browsing selects components."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # First call for discovery (no match)
            discovery_response = mock_llm_response_nested(found=False, workflow_name=None, confidence=0.3)

            # Second call for browsing (component selection)
            browsing_response = mock_llm_response_nested(
                node_ids=["read-file", "llm", "write-file"], workflow_names=["helper-workflow"]
            )

            mock_model.prompt.side_effect = [discovery_response, browsing_response]
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.Registry") as mock_reg_class:
                mock_reg_class.return_value = mock_registry

                with patch("pflow.planning.nodes.build_planning_context") as mock_build:
                    mock_build.return_value = "planning context for generation"

                    # Run discovery node (Path B decision)
                    discovery_node = WorkflowDiscoveryNode()
                    discovery_node.wait = 0  # Speed up tests
                    shared = {"user_input": "create something new"}

                    prep_res1 = discovery_node.prep(shared)
                    exec_res1 = discovery_node.exec(prep_res1)
                    action1 = discovery_node.post(shared, prep_res1, exec_res1)

                    assert action1 == "not_found"

                    # Run browsing node (Path B continues)
                    browsing_node = ComponentBrowsingNode()
                    browsing_node.wait = 0  # Speed up tests

                    prep_res2 = browsing_node.prep(shared)
                    exec_res2 = browsing_node.exec(prep_res2)
                    action2 = browsing_node.post(shared, prep_res2, exec_res2)

                    assert action2 == "generate"
                    assert shared["browsed_components"]["node_ids"] == ["read-file", "llm", "write-file"]
                    assert shared["planning_context"] == "planning context for generation"

    def test_shared_store_keys_written_correctly(self, mock_llm_response_nested):
        """Test both nodes write expected keys to shared store."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.side_effect = [
                mock_llm_response_nested(found=False),
                mock_llm_response_nested(node_ids=["n1"], workflow_names=["w1"]),
            ]
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.Registry") as mock_reg_class:
                mock_reg_class.return_value = Mock(load=Mock(return_value={}))

                with patch("pflow.planning.nodes.build_planning_context") as mock_build:
                    mock_build.return_value = "context"

                    shared = {"user_input": "test"}

                    # Discovery node adds its keys
                    discovery = WorkflowDiscoveryNode()
                    discovery.wait = 0  # Speed up tests
                    prep1 = discovery.prep(shared)
                    exec1 = discovery.exec(prep1)
                    discovery.post(shared, prep1, exec1)

                    assert "discovery_result" in shared
                    assert "discovery_context" in shared
                    assert "found_workflow" not in shared  # Not found case

                    # Browsing node adds its keys
                    browsing = ComponentBrowsingNode()
                    browsing.wait = 0  # Speed up tests
                    prep2 = browsing.prep(shared)
                    exec2 = browsing.exec(prep2)
                    browsing.post(shared, prep2, exec2)

                    assert "browsed_components" in shared
                    assert "registry_metadata" in shared
                    assert "planning_context" in shared
