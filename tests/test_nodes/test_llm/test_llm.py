"""Tests for the LLM node covering all 22 criteria from the specification.

These tests target the new pflow-owned LiteLLM adapter at
``pflow.core.llm_client.complete``. The autouse ``mock_llm_client`` fixture
in ``tests/conftest.py`` patches that function with a ``MockLLMClient`` for
every test; tests can take ``mock_llm_client`` as a parameter to inspect
recorded calls or configure custom responses.
"""

import time
from typing import ClassVar
from unittest.mock import patch

import litellm.exceptions
import pytest

from pflow.core.llm_client import AdapterResponse
from pflow.nodes.llm import LLMNode


class TestLLMNode:
    """Test suite for LLMNode covering all specification criteria."""

    # Test Criteria 1: prompt in params → prompt extracted correctly
    def test_prompt_from_params(self, mock_llm_client):
        """Test that prompt is extracted from params."""
        mock_llm_client.set_response("*", None, "Test response")

        node = LLMNode()
        node.set_params({"prompt": "Test prompt from params"})
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Test response"
        assert mock_llm_client.call_history[-1]["prompt"] == "Test prompt from params"
        assert mock_llm_client.call_history[-1]["temperature"] == 1.0

    # Test Criteria 2: prompt with direct params assignment → prompt extracted correctly
    def test_prompt_with_direct_params_assignment(self, mock_llm_client):
        """Test that prompt works with direct params assignment."""
        mock_llm_client.set_response("*", None, "Param response")

        node = LLMNode()
        node.params = {"prompt": "Test prompt from params"}
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Param response"
        assert mock_llm_client.call_history[-1]["prompt"] == "Test prompt from params"
        assert mock_llm_client.call_history[-1]["temperature"] == 1.0

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

    # Test Criteria 4: model parameter used → adapter called with correct model
    def test_model_parameter_used(self, mock_llm_client):
        """Test that model parameter is passed through to the adapter."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "model": "gpt-4"})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["model"] == "gpt-4"

    # Test Criteria 5: temperature set to 0.0 → temperature=0.0 in kwargs
    def test_temperature_zero(self, mock_llm_client):
        """Test temperature=0.0 is passed correctly."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "temperature": 0.0})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["temperature"] == 0.0
        assert mock_llm_client.call_history[-1]["prompt"] == "Test"

    # Test Criteria 6: temperature set to 2.0 → temperature=2.0 in kwargs
    def test_temperature_two(self, mock_llm_client):
        """Test temperature=2.0 is passed correctly."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "temperature": 2.0})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["temperature"] == 2.0
        assert mock_llm_client.call_history[-1]["prompt"] == "Test"

    # Test Criteria 7: system parameter provided → system in kwargs
    def test_system_parameter_included(self, mock_llm_client):
        """Test that system parameter is included in kwargs when provided."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "system": "You are helpful"})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["system"] == "You are helpful"
        assert mock_llm_client.call_history[-1]["temperature"] == 1.0
        assert mock_llm_client.call_history[-1]["prompt"] == "Test"

    # Test Criteria 8: system parameter None → system explicitly None in adapter call
    def test_system_none_not_in_kwargs(self, mock_llm_client):
        """Test that system is None in the adapter call when not provided.

        The new adapter signature uses ``system: str | None = None``, so the
        recorded call_history captures the literal None rather than "missing".
        """
        node = LLMNode()
        node.set_params({"prompt": "Test"})  # No system parameter
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["system"] is None

    # Test Criteria 9: max_tokens provided → max_tokens in kwargs
    def test_max_tokens_included(self, mock_llm_client):
        """Test that max_tokens is included when provided."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "max_tokens": 100})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["max_tokens"] == 100
        assert mock_llm_client.call_history[-1]["prompt"] == "Test"
        assert mock_llm_client.call_history[-1]["temperature"] == 1.0

    # Test Criteria 10: max_tokens None → max_tokens None in adapter call
    def test_max_tokens_none_not_in_kwargs(self, mock_llm_client):
        """Test that max_tokens is None in the adapter call when not provided."""
        node = LLMNode()
        node.set_params({"prompt": "Test"})  # No max_tokens
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["max_tokens"] is None

    # Test Criteria 11: response.text returned → "Forced evaluation" stored in shared
    def test_response_text_called(self, mock_llm_client):
        """Test that the adapter response.text is stored in shared store."""
        mock_llm_client.set_response("*", None, "Forced evaluation")

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared = {}

        node.run(shared)

        assert shared["response"] == "Forced evaluation"

    # Test Criteria 12: response stored → shared["response"] equals response text
    def test_response_stored_in_shared(self, mock_llm_client):
        """Test that response is stored in shared store."""
        mock_llm_client.set_response("*", None, "Stored response")

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared = {}

        node.run(shared)

        assert shared["response"] == "Stored response"

    # Test Criteria 13: action returned → run() returns "default"
    def test_default_action_returned(self, mock_llm_client):
        """Test that run() always returns 'default' action."""
        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared = {}

        action = node.run(shared)

        assert action == "default"

    # Test Criteria 14: NotFoundError raised → Returns error action with helpful message
    def test_unknown_model_error_handling(self, monkeypatch):
        """Test that LiteLLM's NotFoundError is handled correctly with error action.

        The new adapter raises ``litellm.exceptions.NotFoundError`` for unknown
        models (was ``llm.UnknownModelError`` under the old library). The user-
        facing error text now references ``pflow settings llm show`` instead of
        ``llm models``.
        """

        def raise_not_found(**kwargs):
            raise litellm.exceptions.NotFoundError(
                message="Model not found", model=kwargs.get("model", "unknown"), llm_provider="anthropic"
            )

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", raise_not_found)

        node = LLMNode(wait=0)  # No wait between retries for faster tests
        node.set_params({"prompt": "Test", "model": "bad-model"})
        shared = {}

        # Node should return "error" action and set error in shared
        action = node.run(shared)

        assert action == "error"
        assert "error" in shared
        error_msg = shared["error"]
        assert "Unknown model: bad-model" in error_msg
        assert "pflow settings llm show" in error_msg
        # Verify empty response and usage as per spec
        assert shared["response"] == ""
        assert shared["llm_usage"] == {}

    # Test Criteria 15: AuthenticationError raised → Returns error action with helpful message
    def test_needs_key_exception_handling(self, monkeypatch):
        """Test that LiteLLM's AuthenticationError is handled with error action.

        The new adapter raises ``litellm.exceptions.AuthenticationError`` for
        missing/invalid API keys (was ``llm.NeedsKeyException``). The user-
        facing error text now references ``pflow settings set-env`` instead of
        ``llm keys set``.
        """

        def raise_auth(**kwargs):
            raise litellm.exceptions.AuthenticationError(
                message="API key required", model=kwargs.get("model", "unknown"), llm_provider="anthropic"
            )

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", raise_auth)

        node = LLMNode(wait=0)  # No wait between retries for faster tests
        node.set_params({"prompt": "Test"})
        shared = {}

        action = node.run(shared)

        assert action == "error"
        assert "error" in shared
        error_msg = shared["error"]
        assert "API key required" in error_msg
        assert "pflow settings set-env" in error_msg
        # Verify empty response and usage as per spec
        assert shared["response"] == ""
        assert shared["llm_usage"] == {}

    # Test Criteria 16: Generic exception → Returns error action with retry count
    def test_generic_exception_handling(self, monkeypatch):
        """Test that generic exceptions include retry count in error."""

        def raise_runtime(**kwargs):
            raise RuntimeError("Network error")

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", raise_runtime)

        node = LLMNode(max_retries=2, wait=0)  # Custom retry count, no wait
        node.set_params({"prompt": "Test"})
        shared = {}

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
    def test_temperature_below_zero_clamped(self, mock_llm_client):
        """Test that temperature below 0 is clamped to 0.0."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "temperature": -0.5})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["temperature"] == 0.0

    # Test Criteria 19: Temperature > 2.0 → clamped to 2.0
    def test_temperature_above_two_clamped(self, mock_llm_client):
        """Test that temperature above 2.0 is clamped to 2.0."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "temperature": 3.5})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["temperature"] == 2.0

    # Test Criteria 20: Empty response → empty string stored in shared["response"]
    def test_empty_response_stored(self, mock_llm_client):
        """Test that empty response is stored as empty string."""
        mock_llm_client.set_response("*", None, "")

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared = {}

        action = node.run(shared)

        assert shared["response"] == ""
        assert action == "default"  # Not an error

    # Test Criteria 21: Usage data stored with correct field names
    def test_usage_data_stored_correctly(self, monkeypatch):
        """Test that usage data is stored with correct field names.

        Hand-builds an ``AdapterResponse`` with specific token counts since the
        default mock generates token counts from the prompt length. This is the
        simplest way to assert against specific values.
        """

        def custom_complete(**kwargs):
            return AdapterResponse(
                text="Response with usage",
                usage={
                    "model": "gpt-4",
                    "input_tokens": 150,
                    "output_tokens": 75,
                    "total_tokens": 225,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 20,
                    "cost_usd": 0.00966,
                },
                model="gpt-4",
                has_schema=False,
            )

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", custom_complete)

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
            "cost_usd": 0.00966,
        }

    # Test Criteria 22: Adapter returns empty usage dict → {} stored in shared["llm_usage"]
    def test_usage_none_stores_empty_dict(self, monkeypatch):
        """Test that empty usage dict from adapter results in empty shared["llm_usage"]."""

        def custom_complete(**kwargs):
            # Adapter returning an empty usage dict (legacy behavior was usage=None
            # from the underlying llm library; the adapter normalizes to {}).
            return AdapterResponse(text="No usage data", usage={}, model="gpt-4", has_schema=False)

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", custom_complete)

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared = {}

        node.run(shared)

        assert shared["llm_usage"] == {}  # Empty dict, not None

    # Additional test: System parameter from params
    def test_system_parameter_from_params(self, mock_llm_client):
        """Test that system parameter is read from params."""
        node = LLMNode()
        node.set_params({"prompt": "Test", "system": "Param system"})
        shared = {}

        node.run(shared)

        assert mock_llm_client.call_history[-1]["system"] == "Param system"
        assert mock_llm_client.call_history[-1]["prompt"] == "Test"
        assert mock_llm_client.call_history[-1]["temperature"] == 1.0

    # Additional test: Retry behavior
    def test_retry_behavior_on_transient_failure(self, monkeypatch):
        """Test that node retries on transient failures."""

        # Track call count and fail twice, then succeed
        call_count = {"n": 0}

        def flaky_complete(**kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError(f"Transient error #{call_count['n']}")
            return AdapterResponse(text="Success after retry", usage={}, model="test", has_schema=False)

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", flaky_complete)

        node = LLMNode(max_retries=3, wait=0.01)  # Short wait for testing
        node.set_params({"prompt": "Test"})
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Success after retry"
        assert call_count["n"] == 3


class TestStripCodeBlock:
    """Tests for LLMNode._strip_code_block — code fence stripping without JSON parsing."""

    def test_strips_json_code_block(self):
        """Strips ```json ... ``` and returns inner content as string."""
        response = '```json\n{"key": "value"}\n```'
        result = LLMNode._strip_code_block(response)
        assert result == '{"key": "value"}'
        assert isinstance(result, str)

    def test_strips_plain_code_block(self):
        """Strips ``` ... ``` (no language tag) and returns inner content as string."""
        response = '```\n{"key": "value"}\n```'
        result = LLMNode._strip_code_block(response)
        assert result == '{"key": "value"}'
        assert isinstance(result, str)

    def test_strips_with_leading_trailing_whitespace(self):
        """Strips code block even with leading/trailing whitespace on outer response."""
        response = '  \n```json\n{"key": "value"}\n```\n  '
        result = LLMNode._strip_code_block(response)
        assert result == '{"key": "value"}'

    def test_does_not_strip_prose_with_embedded_code_blocks(self):
        """Prose containing code blocks is preserved as-is (the bug fix)."""
        response = 'Summary:\n```json\n{"key": "value"}\n```\nMore text'
        result = LLMNode._strip_code_block(response)
        assert result == response

    def test_does_not_strip_plain_text(self):
        """Plain text passes through unchanged."""
        response = "Hello world"
        result = LLMNode._strip_code_block(response)
        assert result == "Hello world"

    def test_does_not_strip_raw_json(self):
        """Raw JSON without code blocks passes through unchanged."""
        response = '{"key": "value"}'
        result = LLMNode._strip_code_block(response)
        assert result == '{"key": "value"}'

    def test_always_returns_str(self):
        """Return type is always str, never dict or list."""
        cases = [
            '```json\n{"key": "value"}\n```',
            "```json\n[1, 2, 3]\n```",
            "```\ntrue\n```",
            "plain text",
            '{"already": "json"}',
        ]
        for response in cases:
            result = LLMNode._strip_code_block(response)
            assert isinstance(result, str), f"Expected str for input: {response!r}"

    def test_handles_empty_string(self):
        """Empty string returns empty string."""
        assert LLMNode._strip_code_block("") == ""

    def test_handles_only_backticks(self):
        """Malformed fence (no closing) returns original."""
        response = "```json\nno closing"
        result = LLMNode._strip_code_block(response)
        assert result == response

    def test_multiline_content_in_code_block(self):
        """Multi-line content inside code block is preserved."""
        response = '```json\n{\n  "a": 1,\n  "b": 2\n}\n```'
        result = LLMNode._strip_code_block(response)
        assert result == '{\n  "a": 1,\n  "b": 2\n}'

    def test_code_block_with_trailing_text_preserved(self):
        """When response starts with code block but has trailing text, nothing is stripped.

        We never silently discard content. If the LLM adds text after the
        closing fence, the response is returned unchanged (with fences intact).
        This is more conservative — downstream dot-notation access may fail,
        but the user gets the full response and a clear error rather than
        silent data loss.
        """
        response = '```json\n{"key": "value"}\n```\nNote: uses v2 format'
        result = LLMNode._strip_code_block(response)
        assert result == response


class TestPostStoresStringResponse:
    """Tests that post() always stores a string in shared['response']."""

    def test_prose_response_is_str(self, mock_llm_client):
        """LLM returns prose → shared['response'] is str."""
        mock_llm_client.set_response("*", None, "This is a prose response about JSON.")

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared: dict = {}

        node.run(shared)

        assert isinstance(shared["response"], str)
        assert shared["response"] == "This is a prose response about JSON."

    def test_code_block_json_response_is_str(self, mock_llm_client):
        """LLM returns code-block-wrapped JSON → shared['response'] is str (clean JSON text)."""
        mock_llm_client.set_response("*", None, '```json\n{"items": [1, 2, 3]}\n```')

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared: dict = {}

        node.run(shared)

        assert isinstance(shared["response"], str)
        assert shared["response"] == '{"items": [1, 2, 3]}'

    def test_raw_json_response_stays_as_str(self, mock_llm_client):
        """LLM returns raw JSON (no code blocks) → shared['response'] is str, NOT parsed.

        This is the key behavioral change from the old parse_json_response.
        The old method would json.loads() this into a dict. The new behavior
        keeps it as a string — downstream consumers parse via template dot
        notation (${node.response.field}).
        """
        mock_llm_client.set_response("*", None, '{"items": [1, 2, 3], "count": 3}')

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared: dict = {}

        node.run(shared)

        assert isinstance(shared["response"], str)
        assert shared["response"] == '{"items": [1, 2, 3], "count": 3}'

    def test_prose_with_embedded_json_preserved(self, mock_llm_client):
        """LLM returns prose with embedded JSON → full prose preserved (bug fix)."""
        prose = 'Here is the analysis:\n```json\n{"key": "value"}\n```\nEnd of report.'
        mock_llm_client.set_response("*", None, prose)

        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared: dict = {}

        node.run(shared)

        assert isinstance(shared["response"], str)
        assert shared["response"] == prose


class TestStructuredOutput:
    """Tests for output_schema parameter — structured output via the adapter's schema= kwarg.

    When output_schema is set, the adapter's response advertises has_schema=True
    and post() parses the JSON response into a dict. Without it, behavior is
    unchanged (response is always a string).
    """

    SIMPLE_SCHEMA: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name", "age"],
    }

    def test_output_schema_passed_to_model_prompt(self, mock_llm_client):
        """output_schema in params → schema=<dict> recorded in adapter call."""
        # Mock returns valid JSON for the schema (default fallback would be
        # the {"response": "mock response"} dict, also valid JSON for storage).
        mock_llm_client.set_response("*", self.SIMPLE_SCHEMA, {"name": "Alice", "age": 30})

        node = LLMNode()
        node.set_params({"prompt": "Extract info", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        node.run(shared)

        # call_history records schema as the dict's "title" or None for dicts
        # without title; we just need to verify a schema was passed (non-None
        # marker indicates the adapter received output_schema).
        # The mock's _schema_name returns None for dicts without "title", so
        # check the parsed response which proves has_schema was True.
        assert shared["response"] == {"name": "Alice", "age": 30}

    def test_output_schema_not_in_kwargs_when_absent(self, mock_llm_client):
        """No output_schema in params → schema is None in adapter call."""
        node = LLMNode()
        node.set_params({"prompt": "Test"})
        shared: dict = {}

        node.run(shared)

        # When no schema, recorded schema is None; mock returns text response.
        assert mock_llm_client.call_history[-1]["schema"] is None

    def test_structured_response_is_dict(self, mock_llm_client):
        """output_schema set → shared['response'] is a parsed dict."""
        mock_llm_client.set_response("*", self.SIMPLE_SCHEMA, {"name": "Alice", "age": 30})

        node = LLMNode()
        node.set_params({"prompt": "Extract", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        node.run(shared)

        assert isinstance(shared["response"], dict)
        assert shared["response"] == {"name": "Alice", "age": 30}

    def test_structured_output_skips_strip_code_block(self, mock_llm_client):
        """output_schema set → _strip_code_block is NOT called."""
        mock_llm_client.set_response("*", self.SIMPLE_SCHEMA, {"name": "Bob"})

        node = LLMNode()
        node.set_params({"prompt": "Extract", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        with patch.object(LLMNode, "_strip_code_block") as mock_strip:
            node.run(shared)
            mock_strip.assert_not_called()

    def test_nested_json_response(self, mock_llm_client):
        """Deeply nested JSON is parsed correctly."""
        nested_schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "scores": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            },
        }
        mock_llm_client.set_response("*", nested_schema, {"user": {"name": "Bob", "scores": [1, 2, 3]}})

        node = LLMNode()
        node.set_params({"prompt": "Extract", "output_schema": nested_schema})
        shared: dict = {}

        node.run(shared)

        assert shared["response"]["user"]["name"] == "Bob"
        assert shared["response"]["user"]["scores"] == [1, 2, 3]

    def test_array_response(self, monkeypatch):
        """Schema with type=array → shared['response'] is a list.

        ``set_response`` only handles dict or string responses (it serializes
        dicts to JSON strings and treats strings literally). For a list response,
        we hand-build an AdapterResponse via monkeypatch so that the JSON text
        decodes to a list, not the wrapped {"response": ...} fallback.
        """
        array_schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
        }

        def custom_complete(**kwargs):
            return AdapterResponse(
                text='[{"id": 1}, {"id": 2}]',
                usage={},
                model=kwargs.get("model", "test"),
                has_schema=True,
            )

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", custom_complete)

        node = LLMNode()
        node.set_params({"prompt": "List items", "output_schema": array_schema})
        shared: dict = {}

        node.run(shared)

        assert isinstance(shared["response"], list)
        assert shared["response"] == [{"id": 1}, {"id": 2}]

    def test_usage_metrics_preserved_with_schema(self, monkeypatch):
        """output_schema does not affect llm_usage storage."""

        def custom_complete(**kwargs):
            return AdapterResponse(
                text='{"name": "Alice"}',
                usage={
                    "model": kwargs.get("model", "test"),
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cost_usd": None,
                },
                model=kwargs.get("model", "test"),
                has_schema=True,
            )

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", custom_complete)

        node = LLMNode()
        node.set_params({"prompt": "Extract", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        node.run(shared)

        assert shared["llm_usage"]["input_tokens"] == 100
        assert shared["llm_usage"]["output_tokens"] == 50
        assert shared["llm_usage"]["total_tokens"] == 150

    def test_error_path_unaffected_by_schema(self, monkeypatch):
        """Error path still stores shared['response'] = '' (string, not dict)."""

        def raise_error(**kwargs):
            raise RuntimeError("API error")

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", raise_error)

        node = LLMNode(wait=0)
        node.set_params({"prompt": "Extract", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        action = node.run(shared)

        assert action == "error"
        assert shared["response"] == ""
        assert isinstance(shared["response"], str)
        assert "error" in shared

    def test_output_schema_none_is_string_response(self, mock_llm_client):
        """Explicit output_schema=None → string behavior unchanged."""
        mock_llm_client.set_response("*", None, '{"key": "value"}')

        node = LLMNode()
        node.set_params({"prompt": "Test", "output_schema": None})
        shared: dict = {}

        node.run(shared)

        assert isinstance(shared["response"], str)
        assert shared["response"] == '{"key": "value"}'

    def test_action_returns_default_with_schema(self, mock_llm_client):
        """run() returns 'default' when output_schema is set."""
        mock_llm_client.set_response("*", self.SIMPLE_SCHEMA, {"name": "Alice"})

        node = LLMNode()
        node.set_params({"prompt": "Extract", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        action = node.run(shared)

        assert action == "default"

    def test_malformed_json_with_schema_soft_error(self, monkeypatch):
        """Malformed JSON with output_schema returns error action, preserves raw text.

        When output_schema is set and json.loads() fails, post() returns "error"
        instead of raising. The raw response text is preserved in shared["response"]
        for downstream fallback parsing.
        """

        def custom_complete(**kwargs):
            # Return text that can't be parsed as JSON, with has_schema=True
            return AdapterResponse(text="not valid json", usage={}, model=kwargs.get("model", "test"), has_schema=True)

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", custom_complete)

        node = LLMNode(wait=0)
        node.set_params({"prompt": "Extract", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        action = node.run(shared)

        assert action == "error"
        assert shared["response"] == "not valid json"
        assert "JSON parse failed" in shared["error"]

    def test_malformed_json_preserves_usage(self, monkeypatch):
        """Usage metrics are captured even when output_schema JSON parsing fails.

        Usage extraction was moved above response parsing in post(), so
        shared["llm_usage"] is populated regardless of parse success.
        """

        def custom_complete(**kwargs):
            return AdapterResponse(
                text="not valid json at all",
                usage={
                    "model": kwargs.get("model", "test"),
                    "input_tokens": 200,
                    "output_tokens": 75,
                    "total_tokens": 275,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cost_usd": None,
                },
                model=kwargs.get("model", "test"),
                has_schema=True,
            )

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", custom_complete)

        node = LLMNode(wait=0)
        node.set_params({"prompt": "Extract", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        action = node.run(shared)

        assert action == "error"
        assert shared["response"] == "not valid json at all"
        assert "error" in shared
        # Usage must be captured even on parse failure
        assert shared["llm_usage"]["input_tokens"] == 200
        assert shared["llm_usage"]["output_tokens"] == 75
        assert shared["llm_usage"]["total_tokens"] == 275

    def test_valid_json_with_schema_unchanged(self, mock_llm_client):
        """Regression: valid JSON with output_schema still parses to dict, no error."""
        mock_llm_client.set_response("*", self.SIMPLE_SCHEMA, {"score": 5})

        node = LLMNode(wait=0)
        node.set_params({"prompt": "Rate it", "output_schema": self.SIMPLE_SCHEMA})
        shared: dict = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == {"score": 5}
        assert isinstance(shared["response"], dict)
        assert "error" not in shared


class TestTimeout:
    """Tests for LLM node timeout parameter (default 120s, configurable)."""

    def test_timeout_default_is_120(self):
        """Default timeout is 120 seconds when not specified in params."""
        node = LLMNode(wait=0)
        node.set_params({"prompt": "Test prompt"})
        shared: dict = {}

        prep_res = node.prep(shared)

        assert prep_res["timeout"] == 120

    def test_timeout_custom_value(self):
        """Custom timeout value is passed through from params."""
        node = LLMNode(wait=0)
        node.set_params({"prompt": "Test prompt", "timeout": 60})
        shared: dict = {}

        prep_res = node.prep(shared)

        assert prep_res["timeout"] == 60

    def test_timeout_raises_timeout_error(self, monkeypatch):
        """LLM call exceeding timeout returns error action via exec_fallback.

        exec() wraps _call_llm in ThreadPoolExecutor with future.result(timeout=N).
        On timeout, raises TimeoutError which PocketFlow retries, then exec_fallback
        catches it and returns an error dict processed by post().
        """

        def slow_complete(**kwargs):
            time.sleep(1)
            return AdapterResponse(text="too late", usage={}, model="test", has_schema=False)

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", slow_complete)

        node = LLMNode(wait=0, max_retries=1)
        node.set_params({"prompt": "Test", "timeout": 0.05})
        shared: dict = {}

        action = node.run(shared)

        assert action == "error"
        assert "timed out" in shared["error"]

    def test_normal_execution_within_timeout(self, mock_llm_client):
        """LLM call completing within timeout succeeds normally."""
        mock_llm_client.set_response("*", None, "Fast response")

        node = LLMNode(wait=0)
        node.set_params({"prompt": "Test", "timeout": 10})
        shared: dict = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Fast response"

    def test_timeout_not_retried(self, monkeypatch):
        """Timed-out LLM call must NOT trigger PocketFlow retries.

        exec() returns an error dict on timeout instead of raising, which
        prevents PocketFlow's retry loop from re-executing. This is critical
        because the orphan thread from the timed-out call is still running
        the API call — retrying would create duplicate in-flight requests.
        """
        call_count = {"n": 0}

        def slow_complete(**kwargs):
            call_count["n"] += 1
            time.sleep(1)
            return AdapterResponse(text="too late", usage={}, model="test", has_schema=False)

        monkeypatch.setattr("pflow.nodes.llm.llm.complete", slow_complete)

        node = LLMNode(max_retries=3, wait=0)
        node.set_params({"prompt": "Test", "timeout": 0.05})
        shared: dict = {}

        action = node.run(shared)

        assert action == "error"
        assert "timed out" in shared["error"]
        # Key assertion: complete must be called exactly once.
        # If timeout were retriable, this would be 3.
        assert call_count["n"] == 1

    def test_timeout_string_coerced(self):
        """String timeout value is coerced to float."""
        node = LLMNode(wait=0)
        node.set_params({"prompt": "Test", "timeout": "60"})
        shared: dict = {}

        prep_res = node.prep(shared)

        assert prep_res["timeout"] == 60.0

    def test_timeout_zero_rejected(self):
        """Zero timeout raises ValueError during prep."""
        node = LLMNode(wait=0)
        node.set_params({"prompt": "Test", "timeout": 0})
        shared: dict = {}

        with pytest.raises(ValueError, match="positive"):
            node.prep(shared)

    def test_timeout_negative_rejected(self):
        """Negative timeout raises ValueError during prep."""
        node = LLMNode(wait=0)
        node.set_params({"prompt": "Test", "timeout": -5})
        shared: dict = {}

        with pytest.raises(ValueError, match="positive"):
            node.prep(shared)

    def test_timeout_invalid_string_rejected(self):
        """Non-numeric string timeout raises ValueError during prep."""
        node = LLMNode(wait=0)
        node.set_params({"prompt": "Test", "timeout": "abc"})
        shared: dict = {}

        with pytest.raises(ValueError, match="positive number"):
            node.prep(shared)


class TestReasoningEffortValidation:
    """LLMNode prep() rejects invalid reasoning_effort strings.

    Bad reasoning_effort is deterministic (typo or value the user invented);
    retry won't help. Validation happens in prep() so the error surfaces
    before exec() and bypasses the retry loop.
    """

    def test_invalid_effort_rejected_in_prep(self):
        node = LLMNode()
        node.set_params({"prompt": "hello", "reasoning_effort": "ultra"})
        with pytest.raises(ValueError, match="Invalid reasoning_effort: 'ultra'"):
            node.prep({})

    @pytest.mark.parametrize(
        "effort",
        ["xhigh", "high", "medium", "low", "minimal", "none", "HIGH", "None"],
    )
    def test_valid_efforts_accepted_in_prep(self, effort):
        node = LLMNode()
        node.set_params({"prompt": "hello", "reasoning_effort": effort})
        result = node.prep({})
        assert result["reasoning_effort"] == effort


class TestReasoningKwargsForwarded:
    """LLMNode forwards mapped reasoning kwargs to the adapter.

    The mapping itself is exhaustively tested in
    ``tests/test_core/test_llm_reasoning_map.py``. These two tests verify
    that LLMNode actually wires the result through to the adapter, which
    is the LLMNode-specific contract.
    """

    def test_reasoning_effort_forwarded_to_adapter(self, mock_llm_client):
        node = LLMNode()
        node.set_params({"prompt": "think", "model": "gpt-5-mini", "reasoning_effort": "high"})
        node.run({})

        # The adapter receives reasoning_kwargs from map_reasoning_options.
        # OpenAI gpt-5* gets {"reasoning_effort": "high"}.
        assert mock_llm_client.call_history[-1]["reasoning_kwargs"] == {"reasoning_effort": "high"}

    def test_no_reasoning_kwargs_when_absent(self, mock_llm_client):
        node = LLMNode()
        node.set_params({"prompt": "ordinary call", "model": "anthropic/claude-sonnet-4-5"})
        node.run({})

        # Empty dict, not None — map_reasoning_options returns {} when no
        # reasoning input was provided.
        assert mock_llm_client.call_history[-1]["reasoning_kwargs"] == {}

    def test_model_options_forwarded_to_adapter(self, mock_llm_client):
        node = LLMNode()
        node.set_params({
            "prompt": "search",
            "model": "gpt-4o",
            "model_options": {"top_p": 0.9},
        })
        node.run({})

        assert mock_llm_client.call_history[-1]["model_options"] == {"top_p": 0.9}
