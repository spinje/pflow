"""Comprehensive tests for discovery system nodes.

These tests focus on real behavior validation, especially the critical
nested response extraction pattern and routing decisions.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.planning.nodes import ComponentBrowsingNode, WorkflowDiscoveryNode


@pytest.fixture
def mock_workflow_manager():
    """Mock workflow manager for testing workflow loading."""
    manager = Mock()
    manager.load.return_value = {
        "name": "test-workflow",
        "description": "A test workflow",
        "ir": {
            "ir_version": "0.1.0",
            "nodes": [{"id": "n1", "type": "test-node"}],
            "edges": [],
        },
        "created_at": "2024-01-30T10:00:00Z",
        "updated_at": "2024-01-30T10:00:00Z",
        "version": "1.0.0",
    }
    return manager


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


class TestWorkflowDiscoveryNode:
    """Tests for WorkflowDiscoveryNode - the entry point router."""

    def test_init_configurable_parameters(self):
        """Test node initializes with configurable retry parameters."""
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

    def test_post_routes_found_existing_path_a(self, mock_workflow_manager, mock_llm_response_nested):
        """Test post routes to 'found_existing' for Path A when workflow found."""
        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = mock_workflow_manager

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"discovery_context": "test context"}
            exec_res = {
                "found": True,
                "workflow_name": "test-workflow",
                "confidence": 0.95,
                "reasoning": "Perfect match",
            }

            action = node.post(shared, prep_res, exec_res)

            assert action == "found_existing"
            assert shared["discovery_result"] == exec_res
            assert shared["discovery_context"] == "test context"
            assert shared["found_workflow"]["name"] == "test-workflow"
            mock_workflow_manager.load.assert_called_once_with("test-workflow")

    def test_post_routes_not_found_path_b(self, mock_llm_response_nested):
        """Test post routes to 'not_found' for Path B when no workflow found."""
        node = WorkflowDiscoveryNode()
        node.wait = 0  # Speed up tests
        shared = {}
        prep_res = {"discovery_context": "test context"}
        exec_res = {"found": False, "workflow_name": None, "confidence": 0.2, "reasoning": "No match"}

        action = node.post(shared, prep_res, exec_res)

        assert action == "not_found"
        assert shared["discovery_result"] == exec_res
        assert shared["discovery_context"] == "test context"
        assert "found_workflow" not in shared

    def test_post_handles_workflow_not_found_error(self, mock_workflow_manager, caplog):
        """Test post handles case when workflow exists in LLM but not on disk."""
        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_workflow_manager.load.side_effect = WorkflowNotFoundError("not-on-disk")
            mock_wm_class.return_value = mock_workflow_manager

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"discovery_context": "test context"}
            exec_res = {"found": True, "workflow_name": "not-on-disk", "confidence": 0.9, "reasoning": "Found it"}

            with caplog.at_level(logging.WARNING):
                action = node.post(shared, prep_res, exec_res)

            assert action == "not_found"  # Falls back to Path B
            assert "not-on-disk" in caplog.text
            assert "not found on disk" in caplog.text
            assert "found_workflow" not in shared

    def test_exec_fallback_handles_llm_failure(self):
        """Test exec_fallback provides safe defaults on LLM failure."""
        node = WorkflowDiscoveryNode()
        node.wait = 0  # Speed up tests
        prep_res = {"user_input": "test", "discovery_context": "context"}
        exc = ValueError("LLM API failed")

        result = node.exec_fallback(prep_res, exc)

        assert result["found"] is False
        assert result["workflow_name"] is None
        assert result["confidence"] == 0.0
        assert "LLM API failed" in result["reasoning"]

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


class TestComponentBrowsingNode:
    """Tests for ComponentBrowsingNode - Path B component selector."""

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
                node_ids=None, workflow_names=None, registry_metadata=mock_registry.load()
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

    def test_post_handles_planning_context_error_dict(self, caplog):
        """Test post handles error dict from build_planning_context."""
        with patch("pflow.planning.nodes.build_planning_context") as mock_build:
            # Return error dict structure
            mock_build.return_value = {
                "error": "Some components not found",
                "missing_nodes": ["unknown-node"],
                "missing_workflows": ["missing-workflow"],
            }

            node = ComponentBrowsingNode()
            node.wait = 0  # Speed up tests
            shared = {}
            prep_res = {"registry_metadata": {}}
            exec_res = {
                "node_ids": ["unknown-node"],
                "workflow_names": ["missing-workflow"],
                "reasoning": "Bad selection",
            }

            with caplog.at_level(logging.WARNING):
                action = node.post(shared, prep_res, exec_res)

            assert action == "generate"  # Still routes to generate
            assert shared["planning_context"] == ""  # Empty on error
            assert "Planning context error" in caplog.text

            # Check structured logging extra fields
            warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
            assert len(warning_records) > 0
            assert warning_records[0].phase == "post"
            assert warning_records[0].missing_nodes == ["unknown-node"]
            assert warning_records[0].missing_workflows == ["missing-workflow"]

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
            )

    def test_exec_fallback_handles_llm_failure(self):
        """Test exec_fallback provides safe defaults on LLM failure."""
        node = ComponentBrowsingNode()
        node.wait = 0  # Speed up tests
        prep_res = {"user_input": "test", "discovery_context": "context", "registry_metadata": {}}
        exc = RuntimeError("API timeout")

        result = node.exec_fallback(prep_res, exc)

        assert result["node_ids"] == []
        assert result["workflow_names"] == []
        assert "API timeout" in result["reasoning"]

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


class TestIntegration:
    """Integration tests showing both nodes working together."""

    def test_path_a_flow_complete_match(self, mock_workflow_manager, mock_llm_response_nested):
        """Test complete Path A flow: discovery finds match, loads workflow."""
        with patch("llm.get_model") as mock_get_model:
            # Setup mock model for discovery
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(
                found=True, workflow_name="csv-processor", confidence=0.98
            )
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
                mock_wm_class.return_value = mock_workflow_manager

                # Run discovery node
                discovery_node = WorkflowDiscoveryNode()
                discovery_node.wait = 0  # Speed up tests
                shared = {"user_input": "process CSV files"}

                prep_res = discovery_node.prep(shared)
                exec_res = discovery_node.exec(prep_res)
                action = discovery_node.post(shared, prep_res, exec_res)

                # Verify Path A routing
                assert action == "found_existing"
                assert shared["found_workflow"]["name"] == "test-workflow"
                assert shared["discovery_result"]["found"] is True
                assert shared["discovery_result"]["workflow_name"] == "csv-processor"

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


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_discovery_with_empty_user_input(self):
        """Test discovery validates required user_input."""
        node = WorkflowDiscoveryNode()
        node.wait = 0  # Speed up tests

        # Test that missing user_input raises ValueError
        shared = {}  # No user_input key
        with pytest.raises(ValueError, match="Missing required 'user_input'"):
            node.prep(shared)

        # Test with empty string also raises
        shared = {"user_input": ""}
        with pytest.raises(ValueError, match="Missing required 'user_input'"):
            node.prep(shared)

        # Test fallback to params works
        node.params = {"user_input": "test input"}
        node.wait = 0  # Speed up tests
        with patch("pflow.planning.nodes.build_discovery_context") as mock_build:
            mock_build.return_value = "test context"
            prep_res = node.prep({})  # Empty shared but params has it
            assert prep_res["user_input"] == "test input"

    def test_browsing_validates_required_user_input(self):
        """Test browsing validates required user_input."""
        node = ComponentBrowsingNode()
        node.wait = 0  # Speed up tests

        # Test that missing user_input raises ValueError
        shared = {}  # No user_input key
        with (
            pytest.raises(ValueError, match="Missing required 'user_input'"),
            patch("pflow.planning.nodes.Registry") as mock_registry,
        ):
            mock_registry.return_value.load.return_value = {}
            node.prep(shared)

    def test_browsing_with_empty_selections(self, mock_llm_response_nested):
        """Test browsing handles empty component selections."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(node_ids=[], workflow_names=[])
            mock_get_model.return_value = mock_model

            with patch("pflow.planning.nodes.Registry") as mock_reg_class:
                mock_reg_class.return_value = Mock(load=Mock(return_value={}))

                with patch("pflow.planning.nodes.build_planning_context") as mock_build:
                    mock_build.return_value = "empty context"

                    node = ComponentBrowsingNode()
                    node.wait = 0  # Speed up tests
                    shared = {"user_input": "unclear request"}

                    prep_res = node.prep(shared)
                    exec_res = node.exec(prep_res)
                    action = node.post(shared, prep_res, exec_res)

                    assert action == "generate"  # Still routes to generate
                    assert shared["browsed_components"]["node_ids"] == []
                    assert shared["browsed_components"]["workflow_names"] == []

    def test_discovery_handles_malformed_llm_response(self):
        """Test discovery handles malformed LLM responses gracefully."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            response = Mock()
            # Simulate malformed response structure
            response.json.return_value = {"unexpected": "structure"}
            mock_model.prompt.return_value = response
            mock_get_model.return_value = mock_model

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            prep_res = {
                "user_input": "test",
                "discovery_context": "context",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            # Should raise ValueError for invalid structure
            with pytest.raises(ValueError, match="Invalid LLM response structure"):
                node.exec(prep_res)

    def test_browsing_handles_registry_load_failure(self, caplog):
        """Test browsing handles registry load failures gracefully."""
        with patch("llm.get_model"), patch("pflow.planning.nodes.Registry") as mock_reg_class:
            mock_registry = Mock()
            mock_registry.load.side_effect = RuntimeError("Registry corrupted")
            mock_reg_class.return_value = mock_registry

            with patch("pflow.planning.nodes.build_discovery_context") as mock_build:
                mock_build.return_value = "minimal context"

                node = ComponentBrowsingNode()
                node.wait = 0  # Speed up tests
                shared = {"user_input": "test"}

                # Should not raise - continues with empty registry
                with caplog.at_level(logging.ERROR):
                    prep_res = node.prep(shared)

                # Verify it logged the error and used empty registry
                assert "Failed to load registry" in caplog.text
                assert "Registry corrupted" in caplog.text
                assert prep_res["registry_metadata"] == {}  # Empty registry used

    def test_discovery_long_user_input_truncation(self, mock_llm_response_nested, caplog):
        """Test discovery handles very long user input with truncation in logs."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response_nested(found=False)
            mock_get_model.return_value = mock_model

            node = WorkflowDiscoveryNode()
            node.wait = 0  # Speed up tests
            long_input = "x" * 500  # Very long input
            prep_res = {
                "user_input": long_input,
                "discovery_context": "context",
                "model_name": "anthropic/claude-sonnet-4-0",
                "temperature": 0.0,
            }

            with caplog.at_level(logging.DEBUG):
                node.exec(prep_res)

            # Check that logging truncates to 100 chars
            assert "xxx..." in caplog.text  # Shows truncation
            assert len([r for r in caplog.records if len(r.message) > 150]) == 0
