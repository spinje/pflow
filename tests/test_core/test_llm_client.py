"""Tests for the pflow LiteLLM adapter (`pflow.core.llm_client`).

All tests mock ``litellm.completion`` — no network calls. The adapter's
contract is:

1. Build the right ``messages`` and kwargs for LiteLLM
2. Translate Anthropic reasoning kwargs to LiteLLM-native shape
3. Catch ``BadRequestError`` and return an error-marked ``AdapterResponse``
4. Normalize the response into a stable shape across providers
5. Invoke ``trace_hook`` before and after the call

Per Phase 0 spike: providers populate cache tokens differently — Anthropic
uses ``cache_creation_input_tokens`` / ``cache_read_input_tokens`` directly,
Gemini and OpenAI use ``prompt_tokens_details.cached_tokens``. The adapter
normalizes both into the stable ``usage`` dict shape.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import litellm.exceptions
import pytest

from pflow.core.llm_client import (
    AdapterResponse,
    Attachment,
    _build_messages,
    _translate_reasoning_for_litellm,
    complete,
)

# --------------------------------------------------------------------------
# Helpers — build a fake LiteLLM ModelResponse via SimpleNamespace
# --------------------------------------------------------------------------


def make_litellm_response(
    *,
    text: str = "OK",
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cache_creation: int | None = None,
    cache_read: int | None = None,
    cached_tokens_details: int | None = None,
    response_cost: float | None = 0.001,
) -> SimpleNamespace:
    """Mimic ``litellm.ModelResponse``'s attribute shape minimally.

    Real LiteLLM ``ModelResponse`` is a Pydantic model; we only need the
    attribute access pattern the adapter reads. Using SimpleNamespace
    avoids pulling Pydantic internals into the test.
    """
    message = SimpleNamespace(content=text, reasoning_content=None)
    choice = SimpleNamespace(message=message)
    usage_kwargs: dict = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if cache_creation is not None:
        usage_kwargs["cache_creation_input_tokens"] = cache_creation
    if cache_read is not None:
        usage_kwargs["cache_read_input_tokens"] = cache_read
    if cached_tokens_details is not None:
        usage_kwargs["prompt_tokens_details"] = SimpleNamespace(cached_tokens=cached_tokens_details)
    usage = SimpleNamespace(**usage_kwargs)
    hidden = {"response_cost": response_cost} if response_cost is not None else {}
    return SimpleNamespace(choices=[choice], usage=usage, _hidden_params=hidden)


# --------------------------------------------------------------------------
# _build_messages
# --------------------------------------------------------------------------


class TestBuildMessages:
    def test_text_only(self):
        messages = _build_messages(system=None, prompt="Hello", attachments=None)
        assert messages == [{"role": "user", "content": "Hello"}]

    def test_with_system(self):
        messages = _build_messages(system="You are helpful.", prompt="Hi", attachments=None)
        assert messages == [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]

    def test_with_url_image(self):
        messages = _build_messages(
            system=None,
            prompt="What is this?",
            attachments=[Attachment(kind="image_url", value="https://example.com/cat.jpg")],
        )
        assert messages[-1]["role"] == "user"
        content = messages[-1]["content"]
        assert isinstance(content, list)
        # Image first, then text
        assert content[0] == {
            "type": "image_url",
            "image_url": {"url": "https://example.com/cat.jpg"},
        }
        assert content[1] == {"type": "text", "text": "What is this?"}

    def test_with_path_image(self, tmp_path):
        # 1x1 PNG
        png = tmp_path / "pixel.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        messages = _build_messages(
            system=None,
            prompt="describe",
            attachments=[Attachment(kind="image_path", value=str(png))],
        )
        block = messages[-1]["content"][0]
        assert block["type"] == "image_url"
        url = block["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    def test_multiple_attachments_preserve_order(self):
        messages = _build_messages(
            system=None,
            prompt="compare",
            attachments=[
                Attachment(kind="image_url", value="https://example.com/a.jpg"),
                Attachment(kind="image_url", value="https://example.com/b.jpg"),
            ],
        )
        content = messages[-1]["content"]
        assert content[0]["image_url"]["url"] == "https://example.com/a.jpg"
        assert content[1]["image_url"]["url"] == "https://example.com/b.jpg"
        assert content[2]["text"] == "compare"


# --------------------------------------------------------------------------
# _translate_reasoning_for_litellm
# --------------------------------------------------------------------------


class TestTranslateReasoningForAnthropic:
    """Anthropic shape: collapse to {thinking: {type, budget_tokens}}."""

    def test_thinking_plus_budget(self):
        result = _translate_reasoning_for_litellm(
            "anthropic/claude-sonnet-4-5",
            {"thinking": True, "thinking_budget": 8000},
        )
        assert result == {"thinking": {"type": "enabled", "budget_tokens": 8000}}

    def test_opus_45_thinking_effort_high(self):
        # thinking_effort gets translated to budget_tokens via EFFORT_RATIOS.
        # high (0.80) * DEFAULT_MAX_TOKENS_BASE (16000) = 12800
        result = _translate_reasoning_for_litellm(
            "anthropic/claude-opus-4-5",
            {"thinking_effort": "high"},
        )
        assert result == {"thinking": {"type": "enabled", "budget_tokens": 12800}}

    def test_opus_45_thinking_effort_low(self):
        # low (0.20) * 16000 = 3200
        result = _translate_reasoning_for_litellm(
            "anthropic/claude-opus-4-5",
            {"thinking_effort": "low"},
        )
        assert result == {"thinking": {"type": "enabled", "budget_tokens": 3200}}

    def test_thinking_false_disables(self):
        result = _translate_reasoning_for_litellm(
            "anthropic/claude-sonnet-4-5",
            {"thinking": False},
        )
        # Anthropic default is no thinking; we omit the thinking kwarg
        assert result == {}

    def test_empty_passthrough(self):
        assert _translate_reasoning_for_litellm("anthropic/claude-sonnet-4-5", {}) == {}


class TestTranslateReasoningForGemini:
    """Gemini reasoning kwargs pass through unchanged."""

    def test_thinking_budget_passthrough(self):
        result = _translate_reasoning_for_litellm("gemini-2.5-pro", {"thinking_budget": 4000})
        assert result == {"thinking_budget": 4000}

    def test_thinking_level_passthrough(self):
        result = _translate_reasoning_for_litellm("gemini-3-flash-preview", {"thinking_level": "high"})
        assert result == {"thinking_level": "high"}

    def test_thinking_budget_zero_passthrough(self):
        # The "none" case from the map produces {"thinking_budget": 0}
        result = _translate_reasoning_for_litellm("gemini-2.5-pro", {"thinking_budget": 0})
        assert result == {"thinking_budget": 0}


class TestTranslateReasoningForOpenAI:
    """OpenAI reasoning kwargs pass through unchanged."""

    def test_reasoning_effort_passthrough(self):
        result = _translate_reasoning_for_litellm("gpt-5-mini", {"reasoning_effort": "high"})
        assert result == {"reasoning_effort": "high"}

    def test_reasoning_max_tokens_passthrough(self):
        result = _translate_reasoning_for_litellm("gpt-5-mini", {"reasoning_max_tokens": 5000})
        assert result == {"reasoning_max_tokens": 5000}


# --------------------------------------------------------------------------
# complete() — integration with mocked litellm.completion
# --------------------------------------------------------------------------


class TestCompleteHappyPath:
    @patch("pflow.core.llm_client.litellm.completion")
    def test_text_only_call(self, mock_completion):
        mock_completion.return_value = make_litellm_response(text="hello world")

        response = complete(model="gpt-4o-mini", prompt="Say hello.")

        # Verify call kwargs
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Say hello."}]
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["stream"] is False

        # Verify response shape
        assert isinstance(response, AdapterResponse)
        assert response.text == "hello world"
        assert response.status == "ok"
        assert response.error is None
        assert response.model == "gpt-4o-mini"
        assert response.has_schema is False
        # `.text` is an attribute, not callable (different from llm library)
        assert not callable(response.text)

    @patch("pflow.core.llm_client.litellm.completion")
    def test_with_system_and_max_tokens(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(
            model="gpt-4o-mini",
            prompt="Hi",
            system="You are a friendly bot.",
            max_tokens=512,
        )
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["messages"] == [
            {"role": "system", "content": "You are a friendly bot."},
            {"role": "user", "content": "Hi"},
        ]
        assert call_kwargs["max_tokens"] == 512

    @patch("pflow.core.llm_client.litellm.completion")
    def test_with_schema(self, mock_completion):
        mock_completion.return_value = make_litellm_response(text='{"status":"OK"}')
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        }
        response = complete(model="gpt-4o-mini", prompt="status?", schema=schema)

        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema, "strict": True},
        }
        assert response.has_schema is True

    @patch("pflow.core.llm_client.litellm.completion")
    def test_with_attachment_url(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(
            model="gpt-4o",
            prompt="describe",
            attachments=[Attachment(kind="image_url", value="https://example.com/cat.jpg")],
        )
        messages = mock_completion.call_args.kwargs["messages"]
        assert isinstance(messages[-1]["content"], list)

    @patch("pflow.core.llm_client.litellm.completion")
    def test_with_reasoning_kwargs_anthropic_translation(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(
            model="anthropic/claude-sonnet-4-5",
            prompt="hi",
            reasoning_kwargs={"thinking": True, "thinking_budget": 4096},
        )
        call_kwargs = mock_completion.call_args.kwargs
        # Anthropic shape — translated to nested
        assert call_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 4096}
        # Map-shape keys must NOT leak through
        assert "thinking_budget" not in call_kwargs

    @patch("pflow.core.llm_client.litellm.completion")
    def test_with_reasoning_kwargs_gemini_passthrough(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(
            model="gemini-2.5-pro",
            prompt="hi",
            reasoning_kwargs={"thinking_budget": 4000},
        )
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["thinking_budget"] == 4000

    @patch("pflow.core.llm_client.litellm.completion")
    def test_with_model_options_overrides(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        # User-set top_p; adapter shouldn't strip it
        complete(
            model="gpt-4o-mini",
            prompt="hi",
            model_options={"top_p": 0.9, "temperature": 0.7},  # overrides default 0.0
        )
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["top_p"] == 0.9
        assert call_kwargs["temperature"] == 0.7

    @patch("pflow.core.llm_client.litellm.completion")
    def test_timeout_passed_through(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(model="gpt-4o-mini", prompt="hi", timeout=30.0)
        assert mock_completion.call_args.kwargs["timeout"] == 30.0


class TestCompleteUsageNormalization:
    @patch("pflow.core.llm_client.litellm.completion")
    def test_anthropic_cache_fields(self, mock_completion):
        # Anthropic populates cache_creation_input_tokens and cache_read_input_tokens
        mock_completion.return_value = make_litellm_response(
            prompt_tokens=1400,
            completion_tokens=164,
            cache_creation=0,
            cache_read=1345,
            response_cost=0.003,
        )
        response = complete(model="anthropic/claude-sonnet-4-5", prompt="hi")

        assert response.usage["model"] == "anthropic/claude-sonnet-4-5"
        assert response.usage["input_tokens"] == 1400
        assert response.usage["output_tokens"] == 164
        assert response.usage["total_tokens"] == 1564
        assert response.usage["cache_creation_input_tokens"] == 0
        assert response.usage["cache_read_input_tokens"] == 1345
        assert response.usage["cost_usd"] == 0.003

    @patch("pflow.core.llm_client.litellm.completion")
    def test_gemini_cache_fallback_to_prompt_tokens_details(self, mock_completion):
        # Gemini does NOT set cache_creation_input_tokens/cache_read_input_tokens.
        # It populates prompt_tokens_details.cached_tokens, which the adapter
        # should map to cache_read_input_tokens.
        mock_completion.return_value = make_litellm_response(
            prompt_tokens=1226,
            completion_tokens=10,
            cached_tokens_details=1226,
            response_cost=0.00005,
        )
        response = complete(model="gemini-2.5-flash", prompt="hi")
        assert response.usage["cache_creation_input_tokens"] == 0
        assert response.usage["cache_read_input_tokens"] == 1226

    @patch("pflow.core.llm_client.litellm.completion")
    def test_no_cache_tokens_zeroed(self, mock_completion):
        # Cold OpenAI call — no cache fields populate
        mock_completion.return_value = make_litellm_response(prompt_tokens=100, completion_tokens=20)
        response = complete(model="gpt-4o-mini", prompt="hi")
        assert response.usage["cache_creation_input_tokens"] == 0
        assert response.usage["cache_read_input_tokens"] == 0

    @patch("pflow.core.llm_client.litellm.completion")
    def test_cost_none_when_response_cost_missing(self, mock_completion):
        # _hidden_params has no response_cost (e.g. unknown model)
        mock_completion.return_value = make_litellm_response(response_cost=None)
        response = complete(model="some/exotic-model", prompt="hi")
        assert response.usage["cost_usd"] is None

    @patch("pflow.core.llm_client.litellm.completion")
    def test_cost_coerced_to_float(self, mock_completion):
        mock_completion.return_value = make_litellm_response(response_cost=0.0123456789)
        response = complete(model="gpt-4o-mini", prompt="hi")
        assert isinstance(response.usage["cost_usd"], float)


class TestCompleteErrorPaths:
    @patch("pflow.core.llm_client.litellm.completion")
    def test_bad_request_returns_error_marked_response(self, mock_completion):
        # PATTERN EXCEPTION: deterministic error → error-marked response,
        # not raised. Caller should not retry.
        mock_completion.side_effect = litellm.exceptions.BadRequestError(
            message="Invalid model: 'gpt-fake'",
            model="gpt-fake",
            llm_provider="openai",
        )
        response = complete(model="gpt-fake", prompt="hi")
        assert response.status == "error"
        assert response.error is not None
        assert "gpt-fake" in response.error
        assert response.text == ""
        assert response.model == "gpt-fake"

    @patch("pflow.core.llm_client.litellm.completion")
    def test_timeout_propagates(self, mock_completion):
        # Non-deterministic errors propagate so the caller can decide on retry
        mock_completion.side_effect = litellm.exceptions.Timeout(
            message="timed out",
            model="gpt-4o-mini",
            llm_provider="openai",
        )
        with pytest.raises(litellm.exceptions.Timeout):
            complete(model="gpt-4o-mini", prompt="hi")

    @patch("pflow.core.llm_client.litellm.completion")
    def test_authentication_error_propagates(self, mock_completion):
        mock_completion.side_effect = litellm.exceptions.AuthenticationError(
            message="invalid key",
            model="gpt-4o-mini",
            llm_provider="openai",
        )
        with pytest.raises(litellm.exceptions.AuthenticationError):
            complete(model="gpt-4o-mini", prompt="hi")


class TestCompleteTraceHook:
    @patch("pflow.core.llm_client.litellm.completion")
    def test_invoked_before_and_after_on_success(self, mock_completion):
        mock_completion.return_value = make_litellm_response(text="OK")
        events: list[dict] = []
        complete(
            model="gpt-4o-mini",
            prompt="rendered prompt text",
            trace_hook=events.append,
        )
        assert len(events) == 2
        assert events[0]["event"] == "before_call"
        assert events[0]["model"] == "gpt-4o-mini"
        assert events[0]["prompt"] == "rendered prompt text"
        assert events[1]["event"] == "after_call"
        assert events[1]["response"].text == "OK"

    @patch("pflow.core.llm_client.litellm.completion")
    def test_invoked_after_on_bad_request(self, mock_completion):
        mock_completion.side_effect = litellm.exceptions.BadRequestError(
            message="bad",
            model="m",
            llm_provider="openai",
        )
        events: list[dict] = []
        complete(model="m", prompt="hi", trace_hook=events.append)
        assert len(events) == 2
        assert events[0]["event"] == "before_call"
        assert events[1]["event"] == "after_call"
        assert events[1]["error"] is not None
        assert events[1]["response"].status == "error"

    @patch("pflow.core.llm_client.litellm.completion")
    def test_hook_exception_does_not_break_call(self, mock_completion):
        mock_completion.return_value = make_litellm_response(text="OK")

        def boom(_event):
            raise RuntimeError("trace bug")

        # Should still return a successful response despite the hook blowing up
        response = complete(model="gpt-4o-mini", prompt="hi", trace_hook=boom)
        assert response.status == "ok"
        assert response.text == "OK"

    @patch("pflow.core.llm_client.litellm.completion")
    def test_hook_none_is_no_op(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        # Should not raise
        complete(model="gpt-4o-mini", prompt="hi", trace_hook=None)
