"""Test fixtures for planning module."""

import os
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def mock_llm_model():
    """Mock LLM model for unit tests."""
    mock_model = Mock()
    # Default response for structured output
    mock_response = Mock()
    mock_response.json.return_value = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "test-node", "params": {}}],
        "edges": [],
    }
    mock_response.text.return_value = '{"test": "response"}'
    mock_model.prompt.return_value = mock_response
    return mock_model


@pytest.fixture
def mock_llm(mock_llm_model):
    """Mock the llm.get_model function."""
    with patch("llm.get_model") as mock_get_model:
        mock_get_model.return_value = mock_llm_model
        yield mock_get_model


@pytest.fixture
def mock_llm_with_schema(mock_llm_model):
    """Mock LLM that handles schema parameter."""

    def prompt_with_schema(prompt, schema=None, **kwargs):
        """Mock prompt that returns valid data for schema."""
        if schema:
            # Return mock that produces valid schema instance
            mock_response = Mock()
            # Basic workflow IR for FlowIR schema
            mock_response.json.return_value = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test-node", "params": {}}],
                "edges": [],
            }
            mock_response.text.return_value = '{"test": "response"}'
            return mock_response
        return mock_llm_model.prompt(prompt, **kwargs)

    mock_llm_model.prompt.side_effect = prompt_with_schema
    with patch("llm.get_model") as mock_get_model:
        mock_get_model.return_value = mock_llm_model
        yield mock_get_model


@pytest.fixture
def test_workflow():
    """Sample workflow for testing."""
    return {
        "name": "test-workflow",
        "description": "Test workflow for unit tests",
        "ir": {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "n1", "type": "read-file", "params": {"file_path": "$input_file"}},
                {"id": "n2", "type": "llm", "params": {"prompt": "Process: $content"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
        },
        "created_at": "2024-01-30T10:00:00Z",
        "updated_at": "2024-01-30T10:00:00Z",
        "version": "1.0.0",
    }


@pytest.fixture
def test_registry_data():
    """Sample registry data for testing."""
    return {
        "read-file": {
            "module": "pflow.nodes.file.read_file",
            "class_name": "ReadFileNode",
            "interface": {
                "inputs": [{"key": "file_path", "type": "str", "description": "Path to file"}],
                "outputs": [{"key": "content", "type": "str", "description": "File contents"}],
                "params": [],
            },
        },
        "llm": {
            "module": "pflow.nodes.llm.llm_node",
            "class_name": "LLMNode",
            "interface": {
                "inputs": [{"key": "prompt", "type": "str", "description": "LLM prompt"}],
                "outputs": [{"key": "response", "type": "str", "description": "LLM response"}],
                "params": [{"key": "model", "type": "str", "description": "Model to use"}],
            },
        },
    }


@pytest.fixture
def enable_real_llm():
    """Check if real LLM tests should run."""
    return os.getenv("RUN_LLM_TESTS", "").lower() in ("1", "true", "yes")


@pytest.fixture
def shared_store():
    """Basic shared store for planner tests."""
    return {
        "user_input": "test user input",
        "stdin_data": None,
        "current_date": "2024-01-30T10:00:00Z",
    }
