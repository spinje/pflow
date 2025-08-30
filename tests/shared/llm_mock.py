"""LLM-level mock for testing without API calls.

This module provides a clean mock at the LLM API level, replacing the
problematic planning module mock that manipulates sys.modules.
"""

import json
from typing import Any, Optional
from unittest.mock import Mock


class MockLLMModel:
    """Mock LLM model that simulates the llm library's Model interface."""

    def __init__(self, model_name: str, mock_get_model: "MockGetModel"):
        self.model_name = model_name
        self._mock_get_model = mock_get_model
        self._default_response = {
            "found": False,
            "workflow_name": None,
            "confidence": 0.5,
            "reasoning": "Mock response",
        }

    def prompt(self, prompt: str, schema: Optional[type] = None, temperature: float = 0.0, **kwargs) -> Mock:
        """Simulate LLM prompt method."""
        # Record the call
        call_record = {
            "model": self.model_name,
            "prompt": prompt[:500] if len(prompt) > 500 else prompt,  # Truncate long prompts
            "schema": schema.__name__ if schema else None,
            "temperature": temperature,
            "kwargs": kwargs,
        }
        self._mock_get_model.call_history.append(call_record)

        # Get configured response or use default
        response_data = self._mock_get_model.get_response(self.model_name, schema)

        # Create mock response object
        response = Mock()

        # Handle Anthropic's nested response format
        if schema:
            # Structured response with nested format
            nested_response = {"content": [{"input": response_data}]}
            response.json.return_value = nested_response
        else:
            # Text response - text() is a method that returns the text (llm library behavior)
            response_text = json.dumps(response_data) if isinstance(response_data, dict) else str(response_data)
            # Make text a callable that returns the text
            response.text = Mock(return_value=response_text)

        # Add usage tracking as a method (matching llm library)
        usage_data = Mock()
        # LLMNode expects .input and .output properties
        usage_data.input = len(prompt.split())
        usage_data.output = 50  # Arbitrary for mock
        usage_data.details = {}  # Empty details dict
        response.usage = Mock(return_value=usage_data)

        return response


class MockGetModel:
    """Mock for llm.get_model function."""

    def __init__(self):
        self.call_history = []
        self._responses = {}
        self._default_responses = {
            "WorkflowDecision": {
                "found": False,
                "workflow_name": None,
                "confidence": 0.3,
                "reasoning": "No exact match found",
            },
            "ComponentSelection": {
                "node_ids": ["read-file", "write-file"],
                "workflow_names": [],
                "reasoning": "Selected basic file nodes",
            },
            "ParameterDiscovery": {"parameters": {}, "stdin_type": None, "reasoning": "No parameters found"},
            "ParameterExtraction": {
                "extracted": {},
                "missing": [],
                "confidence": 0.8,
                "reasoning": "Parameters extracted",
            },
            "FlowIR": {
                "ir_version": "0.1.0",
                "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "{{input_file}}"}}],
                "edges": [],
                "start_node": "read",
                "inputs": {"input_file": {"type": "string", "description": "Input file path"}},
                "outputs": {},
            },
            "WorkflowMetadata": {
                "suggested_name": "test-workflow",
                "description": "A test workflow",
                "search_keywords": ["test"],
                "capabilities": ["testing"],
                "typical_use_cases": ["unit tests"],
            },
        }

    def __call__(self, model_name: str) -> MockLLMModel:
        """Return a mock model when get_model is called."""
        return MockLLMModel(model_name, self)

    def set_response(self, model: str, schema: Optional[Any], response: dict):
        """Configure response for specific model and schema combination."""
        key = f"{model}:{schema.__name__ if schema else 'text'}"
        self._responses[key] = response

    def get_response(self, model: str, schema: Optional[type]) -> dict:
        """Get configured response or default."""
        key = f"{model}:{schema.__name__ if schema else 'text'}"

        # Check for specific configuration
        if key in self._responses:
            return self._responses[key]

        # Use schema-based default if available
        if schema and schema.__name__ in self._default_responses:
            return self._default_responses[schema.__name__]

        # Final fallback
        return {"response": "mock response"}

    def reset(self):
        """Reset mock state for test isolation."""
        self.call_history.clear()
        self._responses.clear()


def create_mock_get_model() -> MockGetModel:
    """Factory function to create a mock get_model."""
    return MockGetModel()
