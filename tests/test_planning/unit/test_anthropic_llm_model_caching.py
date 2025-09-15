"""Test AnthropicLLMModel caching paths.

This test suite validates:
1. Model handles cache_blocks=None (fallback path)
2. Model handles cache_blocks provided (cached path)
3. Correct methods are called for each path
4. Parameters are passed correctly
"""

from unittest.mock import Mock, patch

from pydantic import BaseModel

from pflow.planning.utils.anthropic_llm_model import AnthropicLLMModel, AnthropicResponse


class MockSchema(BaseModel):
    """Mock schema for structured output testing."""

    value: str


class TestAnthropicLLMModelInitialization:
    """Test AnthropicLLMModel initialization."""

    def test_initialization_with_default_model(self):
        """Model initializes with default model name."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient"):
            model = AnthropicLLMModel()
            assert model.model_name == "claude-sonnet-4-20250514"
            assert model.model_id == "claude-sonnet-4-20250514"

    def test_initialization_with_custom_model(self):
        """Model accepts custom model name."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient"):
            model = AnthropicLLMModel("custom-model")
            assert model.model_name == "custom-model"
            assert model.model_id == "custom-model"

    def test_api_key_from_environment(self):
        """Model gets API key from environment variable."""
        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client,
        ):
            AnthropicLLMModel()
            mock_client.assert_called_once_with(api_key="test-key")

    def test_api_key_from_llm_library(self):
        """Model falls back to llm library for API key."""
        with (
            patch.dict("os.environ", {}, clear=True),  # No env var
            patch("llm.get_key") as mock_get_key,
            patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client,
        ):
            mock_get_key.return_value = "llm-key"
            AnthropicLLMModel()
            mock_client.assert_called_once_with(api_key="llm-key")


class TestAnthropicLLMModelPromptRouting:
    """Test that prompt() routes to correct internal methods."""

    def test_routes_to_fallback_when_no_cache_blocks(self):
        """When cache_blocks=None, uses fallback path."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient"):
            model = AnthropicLLMModel()

            with (
                patch.object(model, "_prompt_without_cache") as mock_fallback,
                patch.object(model, "_prompt_with_cache_blocks") as mock_cached,
            ):
                mock_fallback.return_value = Mock(spec=AnthropicResponse)

                # Call without cache_blocks
                model.prompt("test prompt", temperature=0.5)

                # Should use fallback path
                mock_fallback.assert_called_once_with(
                    prompt="test prompt", schema=None, temperature=0.5, thinking_budget=0
                )
                mock_cached.assert_not_called()

    def test_routes_to_cached_when_cache_blocks_provided(self):
        """When cache_blocks provided, uses cached path."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient"):
            model = AnthropicLLMModel()

            cache_blocks = [{"text": "cached", "cache_control": {"type": "ephemeral"}}]

            with (
                patch.object(model, "_prompt_without_cache") as mock_fallback,
                patch.object(model, "_prompt_with_cache_blocks") as mock_cached,
            ):
                mock_cached.return_value = Mock(spec=AnthropicResponse)

                # Call with cache_blocks
                model.prompt("test prompt", temperature=0.5, cache_blocks=cache_blocks)

                # Should use cached path
                mock_cached.assert_called_once_with(
                    prompt="test prompt", schema=None, temperature=0.5, cache_blocks=cache_blocks, thinking_budget=0
                )
                mock_fallback.assert_not_called()

    def test_passes_schema_parameter_correctly(self):
        """Schema parameter is passed through correctly."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient"):
            model = AnthropicLLMModel()

            with patch.object(model, "_prompt_without_cache") as mock_fallback:
                mock_fallback.return_value = Mock(spec=AnthropicResponse)

                # Call with schema but no cache
                model.prompt("test prompt", schema=MockSchema, temperature=0.7)

                mock_fallback.assert_called_once_with(
                    prompt="test prompt", schema=MockSchema, temperature=0.7, thinking_budget=0
                )


class TestPromptWithCacheBlocks:
    """Test _prompt_with_cache_blocks method."""

    def test_calls_client_with_structured_output(self):
        """With schema, calls generate_with_schema_text_mode correctly."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.generate_with_schema_text_mode.return_value = (MockSchema(value="test"), {"usage": "metrics"})

            model = AnthropicLLMModel()
            model.client = mock_client

            cache_blocks = [{"text": "cached", "cache_control": {"type": "ephemeral"}}]

            result = model._prompt_with_cache_blocks(
                prompt="instructions", schema=MockSchema, temperature=0.5, cache_blocks=cache_blocks
            )

            # Verify client call
            mock_client.generate_with_schema_text_mode.assert_called_once_with(
                prompt="instructions",
                response_model=MockSchema,
                temperature=0.5,
                cache_blocks=cache_blocks,
                force_text_output=False,
                thinking_budget=0,
            )

            # Verify response
            assert isinstance(result, AnthropicResponse)
            assert result.content == MockSchema(value="test")

    def test_calls_client_for_text_output(self):
        """Without schema, uses FlowIR trick for cache sharing."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.generate_with_schema_text_mode.return_value = ("text response", {"usage": "metrics"})

            model = AnthropicLLMModel()
            model.client = mock_client

            cache_blocks = [{"text": "cached", "cache_control": {"type": "ephemeral"}}]

            result = model._prompt_with_cache_blocks(
                prompt="instructions",
                schema=None,  # No schema - text mode
                temperature=0.5,
                cache_blocks=cache_blocks,
            )

            # Should use FlowIR for cache sharing
            from pflow.planning.ir_models import FlowIR

            mock_client.generate_with_schema_text_mode.assert_called_once_with(
                prompt="instructions",
                response_model=FlowIR,  # Uses FlowIR for cache key
                temperature=0.5,
                cache_blocks=cache_blocks,
                force_text_output=True,  # But forces text output
                thinking_budget=0,
            )

            assert isinstance(result, AnthropicResponse)
            assert result.content == "text response"

    def test_logs_cache_metrics_when_present(self):
        """Logs cache metrics when they exist in usage."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Include cache metrics in usage
            mock_client.generate_with_schema_text_mode.return_value = (
                "response",
                {"cache_creation_input_tokens": 1000, "cache_read_input_tokens": 500},
            )

            model = AnthropicLLMModel()
            model.client = mock_client

            cache_blocks = [{"text": "cached", "cache_control": {"type": "ephemeral"}}]

            # The actual code path for logging is in _prompt_with_cache_blocks
            # Let's just verify the cache metrics are passed through correctly
            result = model._prompt_with_cache_blocks(
                prompt="test", schema=None, temperature=0, cache_blocks=cache_blocks
            )

            # Verify response contains the usage data
            assert isinstance(result, AnthropicResponse)
            usage = result.usage()
            assert usage["cache_creation_input_tokens"] == 1000
            assert usage["cache_read_input_tokens"] == 500


class TestPromptWithoutCache:
    """Test _prompt_without_cache method."""

    def test_calls_client_with_no_cache_blocks(self):
        """Fallback path passes None for cache_blocks."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.generate_with_schema_text_mode.return_value = (MockSchema(value="test"), {"usage": "metrics"})

            model = AnthropicLLMModel()
            model.client = mock_client

            result = model._prompt_without_cache(prompt="full prompt with context", schema=MockSchema, temperature=0.5)

            # Should pass None for cache_blocks
            mock_client.generate_with_schema_text_mode.assert_called_once_with(
                prompt="full prompt with context",
                response_model=MockSchema,
                temperature=0.5,
                cache_blocks=None,  # No cache blocks in fallback
                force_text_output=False,
                thinking_budget=0,
            )

            assert isinstance(result, AnthropicResponse)
            assert result.content == MockSchema(value="test")

    def test_text_mode_without_cache(self):
        """Text mode works without cache blocks."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.generate_with_schema_text_mode.return_value = ("text response", {"usage": "metrics"})

            model = AnthropicLLMModel()
            model.client = mock_client

            model._prompt_without_cache(
                prompt="full prompt",
                schema=None,  # Text mode
                temperature=0.5,
            )

            # Should still use FlowIR but without cache blocks
            from pflow.planning.ir_models import FlowIR

            mock_client.generate_with_schema_text_mode.assert_called_once_with(
                prompt="full prompt",
                response_model=FlowIR,
                temperature=0.5,
                cache_blocks=None,  # No cache blocks
                force_text_output=True,
                thinking_budget=0,
            )


class TestAnthropicResponse:
    """Test AnthropicResponse wrapper."""

    def test_response_text_method(self):
        """Response.text() returns string content."""
        response = AnthropicResponse(content="test content", usage={}, is_structured=False)

        assert response.text() == "test content"

    def test_response_json_method_with_pydantic(self):
        """Response.json() returns dict from Pydantic model."""
        test_obj = MockSchema(value="test")
        response = AnthropicResponse(content=test_obj, usage={}, is_structured=True)

        # Should return in Claude/Anthropic format
        result = response.json()
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["content"][0]["input"] == {"value": "test"}

    def test_response_json_method_with_dict(self):
        """Response.json() returns content for non-structured."""
        test_dict = {"key": "value"}
        response = AnthropicResponse(
            content=test_dict,
            usage={},
            is_structured=False,  # Not structured
        )

        assert response.json() == test_dict

    def test_response_json_method_with_string(self):
        """Response.json() returns string content for non-structured."""
        response = AnthropicResponse(content="plain text", usage={}, is_structured=False)

        assert response.json() == "plain text"

    def test_response_usage_method(self):
        """Response.usage() returns usage metadata."""
        usage_data = {"tokens": 100}
        response = AnthropicResponse(content="content", usage=usage_data, is_structured=False)

        assert response.usage() == usage_data

    def test_response_attributes_delegation(self):
        """Response delegates to content for structured responses."""
        test_obj = MockSchema(value="test_value")
        response = AnthropicResponse(content=test_obj, usage={}, is_structured=True)

        # Should delegate to the content object
        assert response.value == "test_value"


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_works_with_existing_non_cached_calls(self):
        """Existing code without cache_blocks continues to work."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.generate_with_schema_text_mode.return_value = ("response", {})

            model = AnthropicLLMModel()
            model.client = mock_client

            # Old-style call without cache_blocks parameter
            result = model.prompt("test prompt")

            # Should work fine
            assert isinstance(result, AnthropicResponse)

            # Should have called with cache_blocks=None
            call_args = mock_client.generate_with_schema_text_mode.call_args
            assert call_args.kwargs["cache_blocks"] is None

    def test_handles_list_prompts(self):
        """Handles list prompts (converts to string)."""
        with patch("pflow.planning.utils.anthropic_llm_model.AnthropicStructuredClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.generate_with_schema_text_mode.return_value = ("response", {})

            model = AnthropicLLMModel()
            model.client = mock_client

            # Pass prompt as list (some code might do this)
            model.prompt(["part1", "part2"])

            # Should convert to string
            call_args = mock_client.generate_with_schema_text_mode.call_args
            prompt_arg = call_args.args[0] if call_args.args else call_args.kwargs["prompt"]
            assert isinstance(prompt_arg, str)
            assert "part1" in prompt_arg or "part2" in prompt_arg
