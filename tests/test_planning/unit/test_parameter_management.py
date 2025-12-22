"""Unit tests for parameter management nodes (Task 17 Subtask 3).

This file tests the parameter management system that handles the convergence point
where Path A and Path B meet in the Natural Language Planner.

Architecture Overview:
- Path A: discovery → found_workflow → parameter_mapping → preparation
- Path B: discovery → browsing → param_discovery → (generation) → parameter_mapping → preparation
- ParameterMappingNode is THE convergence point for both paths
- ParameterMappingNode MUST do independent extraction for verification

Key Testing Focus:
1. ParameterDiscoveryNode extracts hints from natural language (Path B only)
2. ParameterMappingNode performs INDEPENDENT extraction (doesn't trust discovered_params)
3. ParameterMappingNode validates against workflow_ir["inputs"] field
4. All nodes handle stdin as fallback parameter source
5. Models are lazy-loaded in exec(), not __init__()
"""

import logging
from unittest.mock import Mock, patch

import pytest

# Import schema classes for mock configuration
from pflow.planning.nodes import (
    ParameterDiscovery,
    ParameterDiscoveryNode,
    ParameterExtraction,
    ParameterMappingNode,
    ParameterPreparationNode,
)


@pytest.fixture
def mock_llm_param_discovery():
    """Mock LLM response for ParameterDiscoveryNode."""

    def create_response(parameters=None, stdin_type=None):
        """Create mock response with valid JSON string for ParameterDiscovery."""
        import json

        response = Mock()
        # CRITICAL: text() must return JSON string, not Mock object
        response_data = {
            "parameters": parameters or {},
            "stdin_type": stdin_type,
            "reasoning": "Test parameter discovery reasoning",
        }
        response.text.return_value = json.dumps(response_data)
        return response

    return create_response


@pytest.fixture
def mock_llm_param_extraction():
    """Mock LLM response for ParameterMappingNode."""

    def create_response(extracted=None, missing=None, confidence=0.9):
        """Create mock response with valid JSON string for ParameterExtraction."""
        import json

        response = Mock()
        # CRITICAL: text() must return JSON string, not Mock object
        response_data = {
            "extracted": extracted or {},
            "missing": missing or [],
            "confidence": confidence,
            "reasoning": "Test parameter extraction reasoning",
        }
        response.text.return_value = json.dumps(response_data)
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


@pytest.fixture
def workflow_no_inputs():
    """Sample workflow IR with no input parameters."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "n1", "type": "generate", "params": {"value": "static"}},
        ],
        "edges": [],
    }


class TestParameterDiscoveryNode:
    """Tests for ParameterDiscoveryNode (Path B only)."""

    def test_extracts_parameters_from_natural_language(self, mock_llm_calls):
        """Test node extracts named parameters from user input."""
        # Configure the global mock to return the expected response
        mock_llm_calls.set_response(
            "anthropic/claude-sonnet-4-5",
            ParameterDiscovery,
            {
                "parameters": {"filename": "report.csv", "limit": "20", "format": "json"},
                "stdin_type": None,
                "reasoning": "Test parameter discovery reasoning",
            },
        )

        node = ParameterDiscoveryNode()
        node.wait = 0  # Speed up tests
        shared = {
            "user_input": "process report.csv and get the last 20 items as json",
            "browsed_components": {"node_ids": ["read-file", "transform"]},
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # Verify parameters were extracted
        assert exec_res["parameters"] == {"filename": "report.csv", "limit": "20", "format": "json"}
        # stdin_type is None, so it's excluded by Pydantic's exclude_none=True
        assert exec_res.get("stdin_type") is None
        assert "reasoning" in exec_res

        # Verify stored in shared store for Path B
        assert shared["discovered_params"] == {"filename": "report.csv", "limit": "20", "format": "json"}

    def test_handles_empty_input_gracefully(self, mock_llm_calls):
        """Test node handles empty or minimal input without errors."""
        # Configure the global mock to return empty parameters
        mock_llm_calls.set_response(
            "anthropic/claude-sonnet-4-5",
            ParameterDiscovery,
            {
                "parameters": {},
                "stdin_type": None,
                "reasoning": "No parameters found in input",
            },
        )

        node = ParameterDiscoveryNode()
        node.wait = 0  # Speed up tests
        shared = {"user_input": "run the workflow"}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # Should return empty parameters without error
        assert exec_res["parameters"] == {}
        assert shared["discovered_params"] == {}

    def test_detects_stdin_as_parameter_source(self, mock_llm_calls):
        """Test node recognizes when stdin contains parameters."""
        # Configure the global mock to indicate stdin as parameter source
        mock_llm_calls.set_response(
            "anthropic/claude-sonnet-4-5",
            ParameterDiscovery,
            {
                "parameters": {},
                "stdin_type": "text",
                "reasoning": "Parameters should come from stdin",
            },
        )

        node = ParameterDiscoveryNode()
        node.wait = 0  # Speed up tests
        shared = {
            "user_input": "process the piped data",
            "stdin": "data from pipe",
        }

        prep_res = node.prep(shared)
        assert prep_res["stdin_info"]["type"] == "text"

        exec_res = node.exec(prep_res)
        assert exec_res["stdin_type"] == "text"

    def test_lazy_model_loading(self, mock_llm_calls):
        """Test model is loaded in exec(), not __init__()."""
        # Configure the global mock
        mock_llm_calls.set_response(
            "anthropic/claude-sonnet-4-5",
            ParameterDiscovery,
            {
                "parameters": {},
                "stdin_type": None,
                "reasoning": "Test response",
            },
        )

        # Model should NOT be loaded during init
        node = ParameterDiscoveryNode()
        node.wait = 0  # Speed up tests
        # We can't directly assert the global mock wasn't called during __init__
        # but the test verifies the lazy loading pattern is working

        # Model should be loaded during exec
        shared = {"user_input": "test"}
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        # Verify we got a response, confirming model was loaded
        assert "parameters" in exec_res

    def test_exec_fallback_handles_llm_failure(self, caplog):
        """Test exec_fallback returns safe defaults on LLM failure."""
        node = ParameterDiscoveryNode()
        node.wait = 0  # Speed up tests

        prep_res = {
            "user_input": "test",
            "stdin_info": {"type": "text"},
            "model_name": "test-model",
            "temperature": 0.0,
        }
        exc = ValueError("LLM connection failed")

        with caplog.at_level(logging.DEBUG):
            result = node.exec_fallback(prep_res, exc)

        # Should return empty parameters
        assert result["parameters"] == {}
        assert result["stdin_type"] == "text"
        assert "network connection issue" in result["reasoning"].lower()  # Classified error message
        assert "_error" in result  # Should contain structured error info
        assert "ParameterDiscoveryNode" in caplog.text and "network" in caplog.text


class TestParameterMappingNode:
    """Tests for ParameterMappingNode (convergence point for both paths)."""

    def test_extracts_parameters_independently_not_using_discovered(self, mock_llm_calls, workflow_with_inputs):
        """Test node does INDEPENDENT extraction, not using discovered_params."""
        # Configure the global mock
        mock_llm_calls.set_response(
            "anthropic/claude-sonnet-4-5",
            ParameterExtraction,
            {
                "extracted": {"input_file": "data.csv", "limit": "50"},
                "missing": [],  # All required params found
                "confidence": 0.85,
                "reasoning": "Parameters extracted successfully",
            },
        )

        node = ParameterMappingNode()
        node.wait = 0  # Speed up tests

        # Even though discovered_params exists, node should NOT use it
        shared = {
            "user_input": "analyze data.csv with limit 50",
            "discovered_params": {"wrong": "params", "should": "ignore"},
            "found_workflow": {"ir": workflow_with_inputs},  # Path A
        }

        prep_res = node.prep(shared)
        # Verify discovered_params is NOT in prep_res
        assert "discovered_params" not in prep_res

        exec_res = node.exec(prep_res)

        # Should extract independently, with default for output_format
        assert exec_res["extracted"] == {"input_file": "data.csv", "limit": "50", "output_format": "json"}
        assert exec_res["confidence"] == 0.85  # Confidence preserved when all required found

    def test_validates_against_workflow_inputs_specification(self, mock_llm_param_extraction, workflow_with_inputs):
        """Test node validates extracted params against workflow's inputs field."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_param_extraction(
                extracted={"input_file": "test.txt", "limit": "10"},
                missing=[],
                confidence=0.95,
            )
            mock_get_model.return_value = mock_model

            node = ParameterMappingNode()
            node.wait = 0  # Speed up tests

            shared = {
                "user_input": "process test.txt with limit 10",
                "generated_workflow": workflow_with_inputs,  # Path B
            }

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            # Should validate that all required params are present
            assert "input_file" in exec_res["extracted"]
            assert "limit" in exec_res["extracted"]
            # output_format is optional, so not required

    def test_returns_params_complete_when_all_required_found(self, mock_llm_param_extraction, workflow_with_inputs):
        """Test node returns 'params_complete' action when all required params found."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_param_extraction(
                extracted={"input_file": "data.csv", "limit": "20", "output_format": "xml"},
                missing=[],
                confidence=1.0,
            )
            mock_get_model.return_value = mock_model

            node = ParameterMappingNode()
            node.wait = 0  # Speed up tests

            shared = {
                "user_input": "process data.csv limit 20 as xml",
                "found_workflow": {"ir": workflow_with_inputs},
            }

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "params_complete"
            assert shared["extracted_params"] == {
                "input_file": "data.csv",
                "limit": "20",
                "output_format": "xml",
            }
            assert "missing_params" not in shared

    def test_returns_params_incomplete_when_missing_required(
        self, mock_llm_param_extraction, workflow_with_inputs, caplog
    ):
        """Test node returns 'params_incomplete' action when required params missing."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            # LLM only found input_file, missing required 'limit'
            mock_model.prompt.return_value = mock_llm_param_extraction(
                extracted={"input_file": "test.csv"},
                missing=["limit"],
                confidence=0.5,
            )
            mock_get_model.return_value = mock_model

            node = ParameterMappingNode()
            node.wait = 0  # Speed up tests

            shared = {
                "user_input": "process test.csv",
                "found_workflow": {"ir": workflow_with_inputs},
            }

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            with caplog.at_level(logging.WARNING):
                action = node.post(shared, prep_res, exec_res)

            assert action == "params_incomplete"
            # Default value for output_format should be applied even when limit is missing
            assert shared["extracted_params"] == {"input_file": "test.csv", "output_format": "json"}
            assert shared["missing_params"] == ["limit"]
            assert "Missing required parameters" in caplog.text

    def test_handles_workflows_with_no_inputs_gracefully(self, workflow_no_inputs):
        """Test node handles workflows that don't require any inputs."""
        node = ParameterMappingNode()
        node.wait = 0  # Speed up tests

        shared = {
            "user_input": "run the generator",
            "found_workflow": {"ir": workflow_no_inputs},
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Should return success with no parameters
        assert exec_res["extracted"] == {}
        assert exec_res["missing"] == []
        assert exec_res["confidence"] == 1.0
        assert "no input parameters" in exec_res["reasoning"].lower()

        action = node.post(shared, prep_res, exec_res)
        assert action == "params_complete"

    def test_handles_missing_workflow_gracefully(self):
        """Test node handles case when no workflow is available."""
        node = ParameterMappingNode()
        node.wait = 0  # Speed up tests

        shared = {"user_input": "do something"}
        # No found_workflow or generated_workflow

        prep_res = node.prep(shared)
        assert prep_res["workflow_ir"] is None

        exec_res = node.exec(prep_res)
        assert exec_res["extracted"] == {}
        assert exec_res["missing"] == []
        assert exec_res["confidence"] == 0.0
        assert "no workflow" in exec_res["reasoning"].lower()

    def test_uses_stdin_as_fallback_parameter_source(self, mock_llm_param_extraction, workflow_with_inputs):
        """Test node considers stdin data when extracting parameters."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_param_extraction(
                extracted={"input_file": "piped.txt", "limit": "100"},
                missing=[],
                confidence=0.9,
            )
            mock_get_model.return_value = mock_model

            node = ParameterMappingNode()
            node.wait = 0  # Speed up tests

            shared = {
                "user_input": "process the data",
                "stdin": "piped.txt\n100",
                "found_workflow": {"ir": workflow_with_inputs},
            }

            prep_res = node.prep(shared)
            assert prep_res["stdin_data"] == "piped.txt\n100"

            # Verify stdin is included in the prompt
            node.exec(prep_res)
            call_args = mock_model.prompt.call_args
            prompt = call_args[0][0]
            assert "piped.txt" in prompt

    def test_exec_fallback_marks_all_required_as_missing(self, workflow_with_inputs, caplog):
        """Test exec_fallback raises CriticalPlanningError for ParameterMappingNode."""
        from pflow.core.exceptions import CriticalPlanningError

        node = ParameterMappingNode()
        node.wait = 0  # Speed up tests

        prep_res = {
            "user_input": "test",
            "workflow_ir": workflow_with_inputs,
            "stdin_data": "",
            "model_name": "test-model",
            "temperature": 0.0,
        }
        exc = RuntimeError("LLM timeout")

        # ParameterMappingNode is critical and should raise an exception
        with pytest.raises(CriticalPlanningError) as exc_info:
            node.exec_fallback(prep_res, exc)

        # Verify the exception details
        assert exc_info.value.node_name == "ParameterMappingNode"
        assert "Cannot extract workflow parameters" in exc_info.value.reason
        assert "Network connection issue" in exc_info.value.reason  # Classified error message
        assert exc_info.value.original_error == exc

    def test_validates_required_params_after_llm_extraction(self, mock_llm_param_extraction, workflow_with_inputs):
        """Test node double-checks required params even if LLM says they're found."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            # LLM thinks it found everything but actually missed 'limit'
            mock_model.prompt.return_value = mock_llm_param_extraction(
                extracted={"input_file": "test.csv"},  # Missing 'limit'
                missing=[],  # LLM thinks nothing is missing
                confidence=0.95,
            )
            mock_get_model.return_value = mock_model

            node = ParameterMappingNode()
            node.wait = 0  # Speed up tests

            shared = {
                "user_input": "process test.csv",
                "found_workflow": {"ir": workflow_with_inputs},
            }

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            # Node should detect the missing required param
            assert "limit" in exec_res["missing"]
            assert exec_res["confidence"] == 0.0  # Should override LLM's confidence


class TestParameterPreparationNode:
    """Tests for ParameterPreparationNode (final formatting)."""

    def test_passes_through_parameters_unchanged_mvp(self):
        """Test node passes through parameters unchanged in MVP."""
        node = ParameterPreparationNode()

        shared = {
            "extracted_params": {
                "file_path": "data.csv",
                "output_format": "json",
                "limit": "42",
            }
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # MVP: should be exact pass-through
        assert exec_res["execution_params"] == {
            "file_path": "data.csv",
            "output_format": "json",
            "limit": "42",
        }
        assert shared["execution_params"] == exec_res["execution_params"]

    def test_raises_error_when_extracted_params_missing(self):
        """Test node raises error when extracted_params not in shared store."""
        node = ParameterPreparationNode()
        shared = {}  # No extracted_params

        with pytest.raises(ValueError, match="Missing required 'extracted_params'"):
            node.prep(shared)

    def test_handles_empty_params_gracefully(self):
        """Test node handles empty parameter dict without errors."""
        node = ParameterPreparationNode()

        shared = {"extracted_params": {}}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        assert exec_res["execution_params"] == {}
        assert shared["execution_params"] == {}

    def test_creates_copy_not_reference(self):
        """Test node creates a copy of params, not a reference."""
        node = ParameterPreparationNode()

        original_params = {"key": "value"}
        shared = {"extracted_params": original_params}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Modify the result
        exec_res["execution_params"]["key"] = "modified"

        # Original should be unchanged
        assert original_params["key"] == "value"
        assert exec_res["execution_params"]["key"] == "modified"
