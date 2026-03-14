"""Tests for reasoning/thinking parameter mapping in the LLM node."""

from typing import Any
from unittest.mock import Mock, patch

import pytest

from pflow.nodes.llm.llm import (
    DEFAULT_MAX_TOKENS_BASE,
    EFFORT_RATIOS,
    _map_reasoning_options,
)

# --- Fake Options classes to simulate provider plugins ---


def _make_model(fields: list[str]) -> Mock:
    """Create a mock llm.Model with an Options class containing given fields."""
    model = Mock()
    model.Options = type(
        "Options",
        (),
        {"model_fields": dict.fromkeys(fields)},
    )
    return model


# --- _map_reasoning_options tests ---


class TestMapReasoningOptionsNoOp:
    """When no reasoning params are provided, returns empty dict."""

    def test_both_none(self):
        model = _make_model(["thinking", "thinking_budget"])
        assert _map_reasoning_options(model, None, None, None) == {}

    def test_empty_string_effort(self):
        model = _make_model(["thinking", "thinking_budget"])
        assert _map_reasoning_options(model, "", None, None) == {}


class TestMapReasoningMaxTokens:
    """Direct token budget via reasoning_max_tokens."""

    def test_anthropic_thinking_budget(self):
        model = _make_model(["thinking", "thinking_budget"])
        result = _map_reasoning_options(model, None, 8000, None)
        assert result == {"thinking": True, "thinking_budget": 8000}

    def test_gemini_thinking_budget_no_thinking_flag(self):
        model = _make_model(["thinking_budget"])
        result = _map_reasoning_options(model, None, 4000, None)
        assert result == {"thinking_budget": 4000}

    def test_openrouter_reasoning_max_tokens(self):
        model = _make_model(["reasoning_effort", "reasoning_max_tokens"])
        result = _map_reasoning_options(model, None, 5000, None)
        assert result == {"reasoning_max_tokens": 5000}

    def test_max_tokens_takes_precedence_over_effort(self):
        model = _make_model(["thinking", "thinking_budget"])
        result = _map_reasoning_options(model, "high", 8000, None)
        assert result == {"thinking": True, "thinking_budget": 8000}


class TestMapReasoningEffortNone:
    """effort='none' disables reasoning."""

    def test_disable_anthropic(self):
        model = _make_model(["thinking", "thinking_budget"])
        result = _map_reasoning_options(model, "none", None, None)
        assert result == {"thinking": False}

    def test_disable_gemini_budget_only(self):
        model = _make_model(["thinking_budget"])
        result = _map_reasoning_options(model, "none", None, None)
        assert result == {"thinking_budget": 0}


class TestMapReasoningEffortAnthropicThinkingEffort:
    """Anthropic Opus 4.5 — has thinking_effort field."""

    def test_high(self):
        model = _make_model(["thinking", "thinking_budget", "thinking_effort"])
        result = _map_reasoning_options(model, "high", None, None)
        assert result == {"thinking_effort": "high"}

    def test_xhigh_maps_to_high(self):
        model = _make_model(["thinking", "thinking_budget", "thinking_effort"])
        result = _map_reasoning_options(model, "xhigh", None, None)
        assert result == {"thinking_effort": "high"}

    def test_minimal_maps_to_low(self):
        model = _make_model(["thinking", "thinking_budget", "thinking_effort"])
        result = _map_reasoning_options(model, "minimal", None, None)
        assert result == {"thinking_effort": "low"}


class TestMapReasoningEffortOpenAI:
    """OpenAI — has reasoning_effort field."""

    def test_high(self):
        model = _make_model(["reasoning_effort"])
        result = _map_reasoning_options(model, "high", None, None)
        assert result == {"reasoning_effort": "high"}

    def test_minimal(self):
        model = _make_model(["reasoning_effort"])
        result = _map_reasoning_options(model, "minimal", None, None)
        assert result == {"reasoning_effort": "minimal"}


class TestMapReasoningEffortGemini3:
    """Gemini 3 — has thinking_level field."""

    def test_high(self):
        model = _make_model(["thinking_level"])
        result = _map_reasoning_options(model, "high", None, None)
        assert result == {"thinking_level": "high"}

    def test_xhigh_maps_to_high(self):
        model = _make_model(["thinking_level"])
        result = _map_reasoning_options(model, "xhigh", None, None)
        assert result == {"thinking_level": "high"}

    def test_minimal(self):
        model = _make_model(["thinking_level"])
        result = _map_reasoning_options(model, "minimal", None, None)
        assert result == {"thinking_level": "minimal"}


class TestMapReasoningEffortTokenBudget:
    """Anthropic older / Gemini 2.5 — needs token budget calculation."""

    def test_high_with_max_tokens(self):
        model = _make_model(["thinking", "thinking_budget"])
        result = _map_reasoning_options(model, "high", None, 16000)
        expected_budget = int(16000 * 0.80)
        assert result == {"thinking": True, "thinking_budget": expected_budget}

    def test_high_without_max_tokens_uses_default(self):
        model = _make_model(["thinking", "thinking_budget"])
        result = _map_reasoning_options(model, "high", None, None)
        expected_budget = int(DEFAULT_MAX_TOKENS_BASE * 0.80)
        assert result == {"thinking": True, "thinking_budget": expected_budget}

    def test_budget_clamped_minimum(self):
        model = _make_model(["thinking", "thinking_budget"])
        # low effort with small max_tokens → should clamp to 1024
        result = _map_reasoning_options(model, "minimal", None, 2000)
        # 2000 * 0.10 = 200, clamped to 1024
        assert result["thinking_budget"] == 1024

    def test_budget_clamped_maximum(self):
        model = _make_model(["thinking", "thinking_budget"])
        # xhigh with huge max_tokens → should clamp to 128000
        result = _map_reasoning_options(model, "xhigh", None, 200000)
        # 200000 * 0.95 = 190000, clamped to 128000
        assert result["thinking_budget"] == 128000

    def test_gemini_budget_no_thinking_flag(self):
        model = _make_model(["thinking_budget"])
        result = _map_reasoning_options(model, "medium", None, 16000)
        expected_budget = int(16000 * 0.50)
        assert result == {"thinking_budget": expected_budget}

    @pytest.mark.parametrize("effort,ratio", EFFORT_RATIOS.items())
    def test_all_effort_levels(self, effort: str, ratio: float):
        model = _make_model(["thinking", "thinking_budget"])
        result = _map_reasoning_options(model, effort, None, 16000)
        expected = max(min(int(16000 * ratio), 128000), 1024)
        assert result["thinking_budget"] == expected


class TestMapReasoningEffortThinkingOnly:
    """Model supports thinking but no budget or effort control."""

    def test_enables_thinking(self):
        model = _make_model(["thinking"])
        result = _map_reasoning_options(model, "high", None, None)
        assert result == {"thinking": True}


class TestMapReasoningEffortUnsupportedModel:
    """Model with no reasoning-related options."""

    def test_returns_empty(self):
        model = _make_model(["temperature", "max_tokens"])
        result = _map_reasoning_options(model, "high", None, None)
        assert result == {}


class TestMapReasoningCaseInsensitive:
    """Effort values are case-insensitive."""

    def test_uppercase(self):
        model = _make_model(["reasoning_effort"])
        result = _map_reasoning_options(model, "HIGH", None, None)
        assert result == {"reasoning_effort": "high"}

    def test_mixed_case(self):
        model = _make_model(["reasoning_effort"])
        result = _map_reasoning_options(model, "Medium", None, None)
        assert result == {"reasoning_effort": "medium"}


# --- Validation: bad params fail fast without retries ---


class TestReasoningValidation:
    """Bad reasoning params should fail immediately, not retry."""

    def test_invalid_effort_rejected_in_prep(self):
        """Invalid reasoning_effort raises ValueError in prep (no retries)."""
        from pflow.nodes.llm import LLMNode

        node = LLMNode()
        node.set_params({"prompt": "hello", "reasoning_effort": "ultra"})
        with pytest.raises(ValueError, match="Invalid reasoning_effort: 'ultra'"):
            node.prep({})

    def test_valid_efforts_accepted_in_prep(self):
        """All valid effort values pass prep validation."""
        from pflow.nodes.llm import LLMNode

        for effort in ["xhigh", "high", "medium", "low", "minimal", "none", "HIGH", "None"]:
            node = LLMNode()
            node.set_params({"prompt": "hello", "reasoning_effort": effort})
            result = node.prep({})
            assert result["reasoning_effort"] == effort

    @patch("pflow.nodes.llm.llm.llm.get_model")
    def test_bad_model_options_no_retry(self, mock_get_model: Mock):
        """ValidationError from model_options returns error dict (no retry loop)."""
        from pydantic import ValidationError

        mock_model = Mock()
        mock_model.prompt.side_effect = ValidationError.from_exception_data(
            title="Options",
            line_errors=[
                {
                    "type": "extra_forbidden",
                    "loc": ("fake_option",),
                    "msg": "Extra inputs are not permitted",
                    "input": True,
                    "ctx": {},
                }
            ],
        )
        mock_model.Options = type("Options", (), {"model_fields": {"temperature": None}})
        mock_get_model.return_value = mock_model

        from pflow.nodes.llm import LLMNode

        node = LLMNode()
        node.set_params({"prompt": "hello", "model_options": {"fake_option": True}})
        shared: dict[str, Any] = {}
        node.run(shared)

        # Should fail with error, and model.prompt called only ONCE (no retries)
        assert shared.get("error")
        assert "Invalid model options" in shared["error"]
        assert mock_model.prompt.call_count == 1


# --- Integration: reasoning params flow through LLMNode.exec() ---


class TestLLMNodeReasoningIntegration:
    """Test that reasoning params are forwarded to model.prompt()."""

    @patch("pflow.nodes.llm.llm.llm.get_model")
    def test_reasoning_effort_forwarded(self, mock_get_model: Mock):
        mock_response = Mock()
        mock_response.text.return_value = "response"
        mock_response.usage.return_value = None

        mock_model = Mock()
        mock_model.prompt.return_value = mock_response
        # Simulate OpenAI model with reasoning_effort option
        mock_model.Options = type("Options", (), {"model_fields": {"reasoning_effort": None, "temperature": None}})
        mock_get_model.return_value = mock_model

        from pflow.nodes.llm import LLMNode

        node = LLMNode()
        node.set_params({"prompt": "think hard", "reasoning_effort": "high"})
        shared: dict[str, Any] = {}
        node.run(shared)

        call_kwargs = mock_model.prompt.call_args
        assert call_kwargs.kwargs["reasoning_effort"] == "high"

    @patch("pflow.nodes.llm.llm.llm.get_model")
    def test_model_options_forwarded(self, mock_get_model: Mock):
        mock_response = Mock()
        mock_response.text.return_value = "response"
        mock_response.usage.return_value = None

        mock_model = Mock()
        mock_model.prompt.return_value = mock_response
        mock_model.Options = type("Options", (), {"model_fields": {"temperature": None, "web_search": None}})
        mock_get_model.return_value = mock_model

        from pflow.nodes.llm import LLMNode

        node = LLMNode()
        node.set_params({"prompt": "search", "model_options": {"web_search": True}})
        shared: dict[str, Any] = {}
        node.run(shared)

        call_kwargs = mock_model.prompt.call_args
        assert call_kwargs.kwargs["web_search"] is True

    @patch("pflow.nodes.llm.llm.llm.get_model")
    def test_no_reasoning_params_no_extra_kwargs(self, mock_get_model: Mock):
        mock_response = Mock()
        mock_response.text.return_value = "response"
        mock_response.usage.return_value = None

        mock_model = Mock()
        mock_model.prompt.return_value = mock_response
        mock_model.Options = type("Options", (), {"model_fields": {"thinking": None, "thinking_budget": None}})
        mock_get_model.return_value = mock_model

        from pflow.nodes.llm import LLMNode

        node = LLMNode()
        node.set_params({"prompt": "no thinking"})
        shared: dict[str, Any] = {}
        node.run(shared)

        call_kwargs = mock_model.prompt.call_args
        assert "thinking" not in call_kwargs.kwargs
        assert "thinking_budget" not in call_kwargs.kwargs


# --- Contract tests: verify installed plugin Options classes match our assumptions ---


class TestPluginFieldContracts:
    """Verify that installed llm plugin Options classes have the fields
    our mapping logic relies on. If a plugin update renames a field,
    these tests fail instead of reasoning silently breaking."""

    def test_anthropic_thinking_model_fields(self):
        """Claude thinking models (3.7, Opus 4, Sonnet 4, etc.) must have
        thinking + thinking_budget fields."""
        from llm_anthropic import ClaudeOptionsWithThinking

        fields = set(ClaudeOptionsWithThinking.model_fields.keys())
        assert "thinking" in fields
        assert "thinking_budget" in fields

    def test_anthropic_thinking_effort_model_fields(self):
        """Claude Opus 4.5 must have thinking_effort field
        (in addition to thinking + thinking_budget from parent)."""
        from llm_anthropic import ClaudeOptionsWithThinkingEffort

        fields = set(ClaudeOptionsWithThinkingEffort.model_fields.keys())
        assert "thinking_effort" in fields
        assert "thinking" in fields
        assert "thinking_budget" in fields

    def test_openai_reasoning_model_fields(self):
        """OpenAI reasoning models (o1, o3, etc.) must have reasoning_effort."""
        from llm.default_plugins.openai_models import OptionsForReasoning

        fields = set(OptionsForReasoning.model_fields.keys())
        assert "reasoning_effort" in fields

    def test_gemini_dynamic_options_thinking_budget(self):
        """Gemini 2.5 models get thinking_budget added dynamically.
        Verify by instantiating a model and checking its Options."""
        from llm_gemini import GeminiPro

        model = GeminiPro("gemini-2.5-flash", can_thinking_budget=True)
        fields = set(model.Options.model_fields.keys())
        assert "thinking_budget" in fields

    def test_gemini_dynamic_options_thinking_level(self):
        """Gemini 3 models get thinking_level added dynamically."""
        from llm_gemini import GeminiPro

        model = GeminiPro(
            "gemini-3-flash-preview",
            thinking_levels=["minimal", "low", "medium", "high"],
        )
        fields = set(model.Options.model_fields.keys())
        assert "thinking_level" in fields

    def test_anthropic_model_gets_thinking_options(self):
        """A real Claude thinking model instance has the right Options class."""
        from llm_anthropic import ClaudeMessages

        model = ClaudeMessages("claude-haiku-4-5-20251001", supports_thinking=True)
        fields = set(model.Options.model_fields.keys())
        assert "thinking" in fields
        assert "thinking_budget" in fields

    def test_mapping_against_real_anthropic_options(self):
        """End-to-end: _map_reasoning_options produces valid kwargs
        for a real Claude model's Options class."""
        from llm_anthropic import ClaudeMessages

        model = ClaudeMessages("claude-haiku-4-5-20251001", supports_thinking=True)

        result = _map_reasoning_options(model, "high", None, 16000)
        # Should produce thinking + thinking_budget (not thinking_effort,
        # since Haiku 4.5 doesn't have that)
        assert "thinking" in result
        assert "thinking_budget" in result
        # Verify the kwargs are accepted by the real Options class
        model.Options(**result)  # Raises ValidationError if invalid

    def test_mapping_against_real_gemini_options(self):
        """End-to-end: _map_reasoning_options produces valid kwargs
        for a real Gemini 3 model's Options class."""
        from llm_gemini import GeminiPro

        model = GeminiPro(
            "gemini-3-flash-preview",
            thinking_levels=["minimal", "low", "medium", "high"],
        )

        result = _map_reasoning_options(model, "high", None, None)
        assert "thinking_level" in result
        # Verify the kwargs are accepted by the real Options class
        model.Options(**result)  # Raises ValidationError if invalid
