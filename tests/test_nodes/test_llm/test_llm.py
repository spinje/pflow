"""Tests for the LLM node covering all 22 criteria from the specification."""

from unittest.mock import Mock, patch

import pytest

from pflow.nodes.llm import LLMNode


class TestLLMNode:
    """Test suite for LLMNode covering all specification criteria."""

    # Test Criteria 1: prompt in params → prompt extracted correctly
    def test_prompt_from_params(self):
        """Test that prompt is extracted from params."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Test response"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test prompt from params"})
            shared = {}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == "Test response"
            mock_model.prompt.assert_called_with("Test prompt from params", stream=False, temperature=1.0)

    # Test Criteria 2: prompt with direct params assignment → prompt extracted correctly
    def test_prompt_with_direct_params_assignment(self):
        """Test that prompt works with direct params assignment."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Param response"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.params = {"prompt": "Test prompt from params"}
            shared = {}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == "Param response"
            mock_model.prompt.assert_called_with("Test prompt from params", stream=False, temperature=1.0)

    # Test Criteria 3: prompt missing entirely → ValueError raised
    def test_missing_prompt_raises_error(self):
        """Test that missing prompt raises ValueError with helpful message."""
        node = LLMNode()
        node.set_params({})  # No prompt in params
        shared = {}

        with pytest.raises(ValueError) as exc_info:
            node.run(shared)

        assert "LLM node requires 'prompt'" in str(exc_info.value)
        assert "parameter" in str(exc_info.value)

    # Test Criteria 4: model parameter used → llm.get_model called with correct model
    def test_model_parameter_used(self):
        """Test that model parameter is passed to llm.get_model."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "GPT response"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "model": "gpt-4"})
            shared = {}

            node.run(shared)

            mock_get_model.assert_called_with("gpt-4")

    # Test Criteria 5: temperature set to 0.0 → temperature=0.0 in kwargs
    def test_temperature_zero(self):
        """Test temperature=0.0 is passed correctly."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Zero temp"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "temperature": 0.0})
            shared = {}

            node.run(shared)

            mock_model.prompt.assert_called_with("Test", stream=False, temperature=0.0)

    # Test Criteria 6: temperature set to 2.0 → temperature=2.0 in kwargs
    def test_temperature_two(self):
        """Test temperature=2.0 is passed correctly."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Max temp"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "temperature": 2.0})
            shared = {}

            node.run(shared)

            mock_model.prompt.assert_called_with("Test", stream=False, temperature=2.0)

    # Test Criteria 7: system parameter provided → system in kwargs
    def test_system_parameter_included(self):
        """Test that system parameter is included in kwargs when provided."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "System response"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "system": "You are helpful"})
            shared = {}

            node.run(shared)

            mock_model.prompt.assert_called_with("Test", stream=False, temperature=1.0, system="You are helpful")

    # Test Criteria 8: system parameter None → system not in kwargs
    def test_system_none_not_in_kwargs(self):
        """Test that system is not in kwargs when None."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "No system"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test"})  # No system parameter
            shared = {}

            node.run(shared)

            # Check that system was NOT passed
            call_args = mock_model.prompt.call_args
            assert "system" not in call_args[1]  # kwargs

    # Test Criteria 9: max_tokens provided → max_tokens in kwargs
    def test_max_tokens_included(self):
        """Test that max_tokens is included when provided."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Limited"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "max_tokens": 100})
            shared = {}

            node.run(shared)

            mock_model.prompt.assert_called_with("Test", stream=False, temperature=1.0, max_tokens=100)

    # Test Criteria 10: max_tokens None → max_tokens not in kwargs
    def test_max_tokens_none_not_in_kwargs(self):
        """Test that max_tokens is not in kwargs when None."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Unlimited"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test"})  # No max_tokens
            shared = {}

            node.run(shared)

            call_args = mock_model.prompt.call_args
            assert "max_tokens" not in call_args[1]  # kwargs

    # Test Criteria 11: model.prompt() called → response.text() returns "Test response"
    def test_response_text_called(self):
        """Test that response.text() is called to force evaluation."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Forced evaluation"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test"})
            shared = {}

            node.run(shared)

            mock_response.text.assert_called_once()
            assert shared["response"] == "Forced evaluation"

    # Test Criteria 12: response stored → shared["response"] equals response text
    def test_response_stored_in_shared(self):
        """Test that response is stored in shared store."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Stored response"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test"})
            shared = {}

            node.run(shared)

            assert shared["response"] == "Stored response"

    # Test Criteria 13: action returned → run() returns "default"
    def test_default_action_returned(self):
        """Test that run() always returns 'default' action."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Any response"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test"})
            shared = {}

            action = node.run(shared)

            assert action == "default"

    # Test Criteria 14: UnknownModelError raised → Returns error action with helpful message
    def test_unknown_model_error_handling(self):
        """Test that UnknownModelError is handled correctly with error action."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_get_model.side_effect = Exception("UnknownModelError: bad-model not found")

            node = LLMNode(wait=0)  # No wait between retries for faster tests
            node.set_params({"prompt": "Test", "model": "bad-model"})
            shared = {}

            # Node should return "error" action and set error in shared
            action = node.run(shared)

            assert action == "error"
            assert "error" in shared
            error_msg = shared["error"]
            assert "Unknown model: bad-model" in error_msg
            assert "llm models" in error_msg
            # Verify empty response and usage as per spec
            assert shared["response"] == ""
            assert shared["llm_usage"] == {}

    # Test Criteria 15: NeedsKeyException raised → Returns error action with helpful message
    def test_needs_key_exception_handling(self):
        """Test that NeedsKeyException is handled correctly with error action."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.side_effect = Exception("NeedsKeyException: API key required")
            mock_get_model.return_value = mock_model

            node = LLMNode(wait=0)  # No wait between retries for faster tests
            node.set_params({"prompt": "Test"})
            shared = {}

            # Node should return "error" action and set error in shared
            action = node.run(shared)

            assert action == "error"
            assert "error" in shared
            error_msg = shared["error"]
            assert "API key required" in error_msg
            assert "llm keys set" in error_msg
            # Verify empty response and usage as per spec
            assert shared["response"] == ""
            assert shared["llm_usage"] == {}

    # Test Criteria 16: Generic exception → Returns error action with retry count
    def test_generic_exception_handling(self):
        """Test that generic exceptions include retry count in error."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.side_effect = RuntimeError("Network error")
            mock_get_model.return_value = mock_model

            node = LLMNode(max_retries=2, wait=0)  # Custom retry count, no wait
            node.set_params({"prompt": "Test"})
            shared = {}

            # Node should return "error" action and set error in shared
            action = node.run(shared)

            assert action == "error"
            assert "error" in shared
            error_msg = shared["error"]
            assert "failed after 2 attempts" in error_msg
            # Verify empty response and usage as per spec
            assert shared["response"] == ""
            assert shared["llm_usage"] == {}

    # Test Criteria 17: Empty prompt → ValueError raised
    def test_empty_prompt_raises_error(self):
        """Test that empty prompt string raises ValueError."""
        node = LLMNode()
        node.set_params({"prompt": ""})  # Empty string
        shared = {}

        with pytest.raises(ValueError) as exc_info:
            node.run(shared)

        assert "LLM node requires 'prompt'" in str(exc_info.value)

    # Test Criteria 18: Temperature < 0.0 → clamped to 0.0
    def test_temperature_below_zero_clamped(self):
        """Test that temperature below 0 is clamped to 0.0."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Clamped"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "temperature": -0.5})
            shared = {}

            node.run(shared)

            mock_model.prompt.assert_called_with("Test", stream=False, temperature=0.0)

    # Test Criteria 19: Temperature > 2.0 → clamped to 2.0
    def test_temperature_above_two_clamped(self):
        """Test that temperature above 2.0 is clamped to 2.0."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Clamped"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "temperature": 3.5})
            shared = {}

            node.run(shared)

            mock_model.prompt.assert_called_with("Test", stream=False, temperature=2.0)

    # Test Criteria 20: Empty response → empty string stored in shared["response"]
    def test_empty_response_stored(self):
        """Test that empty response is stored as empty string."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = ""  # Empty response
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test"})
            shared = {}

            action = node.run(shared)

            assert shared["response"] == ""
            assert action == "default"  # Not an error

    # Test Criteria 21: response.usage() returns data → stored in shared["llm_usage"] with correct fields
    def test_usage_data_stored_correctly(self):
        """Test that usage data is stored with correct field names."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Response with usage"

            # Mock usage object
            mock_usage = Mock()
            mock_usage.input = 150
            mock_usage.output = 75
            mock_usage.details = {"cache_creation_input_tokens": 10, "cache_read_input_tokens": 20}
            mock_response.usage.return_value = mock_usage

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "model": "gpt-4"})
            shared = {}

            node.run(shared)

            assert shared["llm_usage"] == {
                "model": "gpt-4",
                "input_tokens": 150,
                "output_tokens": 75,
                "total_tokens": 225,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 20,
            }

    # Test Criteria 22: response.usage() returns None → empty dict {} stored in shared["llm_usage"]
    def test_usage_none_stores_empty_dict(self):
        """Test that None usage results in empty dict."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "No usage data"
            mock_response.usage.return_value = None  # No usage data

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test"})
            shared = {}

            node.run(shared)

            assert shared["llm_usage"] == {}  # Empty dict, not None

    # Additional test: System parameter from params
    def test_system_parameter_from_params(self):
        """Test that system parameter is read from params."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "System response"
            mock_response.usage.return_value = None

            mock_model = Mock()
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            node = LLMNode()
            node.set_params({"prompt": "Test", "system": "Param system"})
            shared = {}

            node.run(shared)

            mock_model.prompt.assert_called_with("Test", stream=False, temperature=1.0, system="Param system")

    # Additional test: Retry behavior
    def test_retry_behavior_on_transient_failure(self):
        """Test that node retries on transient failures."""
        with patch("pflow.nodes.llm.llm.llm.get_model") as mock_get_model:
            mock_response = Mock()
            mock_response.text.return_value = "Success after retry"
            mock_response.usage.return_value = None

            mock_model = Mock()
            # Fail twice, then succeed
            mock_model.prompt.side_effect = [
                RuntimeError("Transient error"),
                RuntimeError("Another transient error"),
                mock_response,
            ]
            mock_get_model.return_value = mock_model

            node = LLMNode(max_retries=3, wait=0.01)  # Short wait for testing
            node.set_params({"prompt": "Test"})
            shared = {}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == "Success after retry"
            assert mock_model.prompt.call_count == 3
