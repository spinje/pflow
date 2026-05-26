"""Tests for the pflow LiteLLM adapter (`pflow.core.llm_client`).

All tests mock ``litellm.completion`` — no network calls. The adapter's
contract is:

1. Build the right ``messages`` and kwargs for LiteLLM
2. Translate Anthropic reasoning kwargs to LiteLLM-native shape
3. Translate every LiteLLM exception (the catch is structural over
   ``openai.OpenAIError``, the actual base of LiteLLM's exception
   hierarchy) into a typed ``LLMCallError`` subclass —
   ``UnknownModelError`` / ``MissingApiKeyError`` /
   ``LLMResponseParseError`` / ``LLMTransientError`` / ``InvalidRequestError``
4. Normalize the response into a stable shape across providers
5. Invoke ``trace_hook`` before and after the call

Per Phase 0 spike: providers populate cache tokens differently — Anthropic
uses ``cache_creation_input_tokens`` / ``cache_read_input_tokens`` directly,
Gemini and OpenAI use ``prompt_tokens_details.cached_tokens``. The adapter
normalizes both into the stable ``usage`` dict shape.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import litellm.exceptions
import pytest

from pflow.core.exceptions import (
    InvalidRequestError,
    LLMCallError,
    LLMResponseParseError,
    LLMTransientError,
    MissingApiKeyError,
    MissingSdkError,
    UnknownModelError,
)
from pflow.core.llm_client import (
    AdapterResponse,
    Attachment,
    _build_messages,
    _normalize_model_name,
    _translate_reasoning_for_litellm,
    complete,
)

# --------------------------------------------------------------------------
# Helpers — build a fake LiteLLM ModelResponse via SimpleNamespace
# --------------------------------------------------------------------------


def make_litellm_response(
    *,
    text: str | None = "OK",
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cache_creation: int | None = None,
    cache_read: int | None = None,
    cached_tokens_details: int | None = None,
    reasoning_tokens: int | None = None,
    response_cost: float | None = 0.001,
    finish_reason: str | None = "stop",
) -> SimpleNamespace:
    """Mimic ``litellm.ModelResponse``'s attribute shape minimally.

    Real LiteLLM ``ModelResponse`` is a Pydantic model; we only need the
    attribute access pattern the adapter reads. Using SimpleNamespace
    avoids pulling Pydantic internals into the test.

    Pass ``text=None`` to mimic the reasoning-model empty-output case
    (provider returns ``message.content=None``); the adapter normalizes
    this to ``text=""``. Pass ``reasoning_tokens=N`` to populate
    ``usage.completion_tokens_details.reasoning_tokens`` (the LiteLLM-
    standardized field for thinking-token counts across providers).
    """
    message = SimpleNamespace(content=text, reasoning_content=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
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
    if reasoning_tokens is not None:
        usage_kwargs["completion_tokens_details"] = SimpleNamespace(reasoning_tokens=reasoning_tokens)
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
# _normalize_model_name
# --------------------------------------------------------------------------


class TestNormalizeModelName:
    """Auto-prefix bare model names with the correct provider slug."""

    @pytest.mark.parametrize(
        ("bare", "expected"),
        [
            ("gpt-4o-mini", "openai/gpt-4o-mini"),
            ("gpt-5.2", "openai/gpt-5.2"),
            ("o1-preview", "openai/o1-preview"),
            ("o3-mini", "openai/o3-mini"),
            ("o4-mini", "openai/o4-mini"),
            ("claude-sonnet-4-5", "anthropic/claude-sonnet-4-5"),
            ("claude-opus-4-5", "anthropic/claude-opus-4-5"),
            ("gemini-2.5-flash", "gemini/gemini-2.5-flash"),
            ("gemini-3-flash-preview", "gemini/gemini-3-flash-preview"),
        ],
    )
    def test_known_bare_names_get_prefixed(self, bare: str, expected: str) -> None:
        assert _normalize_model_name(bare) == expected

    @pytest.mark.parametrize(
        "already_prefixed",
        [
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4-5",
            "gemini/gemini-2.5-flash",
            "ollama/llama3",
            "together_ai/some-model",
        ],
    )
    def test_already_prefixed_names_pass_through(self, already_prefixed: str) -> None:
        assert _normalize_model_name(already_prefixed) == already_prefixed

    @pytest.mark.parametrize(
        "unknown",
        [
            "llama3",
            "mistral-large",
            "qwen-72b",
        ],
    )
    def test_unknown_bare_names_pass_through(self, unknown: str) -> None:
        assert _normalize_model_name(unknown) == unknown


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

    def test_thinking_true_without_budget_raises(self):
        with pytest.raises(InvalidRequestError) as exc_info:
            _translate_reasoning_for_litellm("anthropic/claude-sonnet-4-5", {"thinking": True})
        assert "thinking=True requires thinking_budget or thinking_effort" in str(exc_info.value)

    def test_opus_47_reasoning_effort_passes_through(self):
        # Opus 4.7 uses adaptive thinking: llm_reasoning_map emits LiteLLM's
        # standardized reasoning_effort, and the Anthropic translator must pass
        # it through UNCHANGED (NOT convert it to the thinking.type.enabled
        # budget shape, which Opus 4.7 rejects — GH #368). LiteLLM >=1.83 then
        # builds the native thinking.type.adaptive + output_config.effort shape.
        result = _translate_reasoning_for_litellm(
            "anthropic/claude-opus-4-7",
            {"reasoning_effort": "low"},
        )
        assert result == {"reasoning_effort": "low"}
        assert "thinking" not in result


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
    @patch("litellm.completion")
    def test_text_only_call(self, mock_completion):
        mock_completion.return_value = make_litellm_response(text="hello world")

        response = complete(model="gpt-4o-mini", prompt="Say hello.")

        # Verify call kwargs — model is normalized (bare "gpt-*" → "openai/gpt-*")
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-4o-mini"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Say hello."}]
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["stream"] is False

        # Verify response shape
        assert isinstance(response, AdapterResponse)
        assert response.text == "hello world"
        assert response.model == "openai/gpt-4o-mini"
        assert response.has_schema is False
        # `.text` is an attribute, not callable (different from llm library)
        assert not callable(response.text)

    @patch("litellm.completion")
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

    @patch("litellm.completion")
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

    @patch("litellm.completion")
    def test_with_attachment_url(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(
            model="gpt-4o",
            prompt="describe",
            attachments=[Attachment(kind="image_url", value="https://example.com/cat.jpg")],
        )
        messages = mock_completion.call_args.kwargs["messages"]
        assert isinstance(messages[-1]["content"], list)

    @patch("litellm.completion")
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

    @patch("litellm.completion")
    def test_with_reasoning_kwargs_gemini_passthrough(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(
            model="gemini-2.5-pro",
            prompt="hi",
            reasoning_kwargs={"thinking_budget": 4000},
        )
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["thinking_budget"] == 4000

    @patch("litellm.completion")
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

    @patch("litellm.completion")
    def test_model_options_reject_reasoning_keys(self, mock_completion):
        with pytest.raises(InvalidRequestError) as exc_info:
            complete(
                model="anthropic/claude-sonnet-4-5",
                prompt="hi",
                model_options={"thinking": True},
            )
        assert "reasoning option keys" in str(exc_info.value)
        mock_completion.assert_not_called()

    @patch("litellm.completion")
    def test_timeout_passed_through(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        complete(model="gpt-4o-mini", prompt="hi", timeout=30.0)
        assert mock_completion.call_args.kwargs["timeout"] == 30.0


class TestCompleteUsageNormalization:
    @patch("litellm.completion")
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
        assert response.usage["uncached_input_tokens"] == 55
        assert response.usage["cache_creation_input_tokens"] == 0
        assert response.usage["cache_read_input_tokens"] == 1345
        # ``has_cache_telemetry`` is True because cache_read=1345 was reported
        # by the provider — distinguishes "reported zero" from "didn't report."
        assert response.usage["has_cache_telemetry"] is True
        assert response.usage["input_token_accounting"] == "total" + "_includes_cache"
        assert response.usage["cost_usd"] == 0.003

    @patch("litellm.completion")
    def test_total_style_cache_usage_keeps_prompt_tokens_as_input_total(self, mock_completion):
        mock_completion.return_value = make_litellm_response(
            prompt_tokens=4974,
            completion_tokens=51,
            cache_creation=0,
            cache_read=4938,
        )
        response = complete(model="anthropic/claude-haiku-4-5", prompt="hi")

        assert response.usage["input_tokens"] == 4974
        assert response.usage["uncached_input_tokens"] == 36
        assert response.usage["cache_read_input_tokens"] == 4938
        assert response.usage["input_token_accounting"] == "total" + "_includes_cache"

    @patch("litellm.completion")
    def test_split_style_cache_usage_adds_cache_fields_to_input_total(self, mock_completion):
        mock_completion.return_value = make_litellm_response(
            prompt_tokens=36,
            completion_tokens=51,
            cache_creation=0,
            cache_read=4938,
        )
        response = complete(model="anthropic/claude-haiku-4-5", prompt="hi")

        assert response.usage["input_tokens"] == 4974
        assert response.usage["uncached_input_tokens"] == 36
        assert response.usage["cache_read_input_tokens"] == 4938
        assert response.usage["input_token_accounting"] == "split" + "_cache_fields"

    @patch("litellm.completion")
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
        assert response.usage["input_tokens"] == 1226
        assert response.usage["uncached_input_tokens"] == 0
        assert response.usage["cache_creation_input_tokens"] == 0
        assert response.usage["cache_read_input_tokens"] == 1226

    @patch("litellm.completion")
    def test_no_cache_tokens_zeroed(self, mock_completion):
        # Cold OpenAI call — no cache fields populate
        mock_completion.return_value = make_litellm_response(prompt_tokens=100, completion_tokens=20)
        response = complete(model="gpt-4o-mini", prompt="hi")
        assert response.usage["cache_creation_input_tokens"] == 0
        assert response.usage["cache_read_input_tokens"] == 0
        # Provider returned no cache telemetry — ``has_cache_telemetry`` MUST
        # be False so the runtime ``cache.below-min-predicted`` guard skips
        # rather than treat ``0+0`` as evidence of below-threshold cache.
        # Reviewer Finding 2 regression: pre-fix, the adapter normalized
        # absent telemetry to 0 with no presence flag, causing observed-tier
        # detection to false-positive on every cold OpenAI call.
        assert response.usage["has_cache_telemetry"] is False

    @patch("litellm.completion")
    def test_cost_none_when_response_cost_missing(self, mock_completion):
        # _hidden_params has no response_cost (e.g. unknown model)
        mock_completion.return_value = make_litellm_response(response_cost=None)
        response = complete(model="some/exotic-model", prompt="hi")
        assert response.usage["cost_usd"] is None

    @patch("litellm.completion")
    def test_cost_coerced_to_float(self, mock_completion):
        mock_completion.return_value = make_litellm_response(response_cost=0.0123456789)
        response = complete(model="gpt-4o-mini", prompt="hi")
        assert isinstance(response.usage["cost_usd"], float)

    @patch("litellm.completion")
    def test_cost_populated_via_upstream_merge_on_missing_model(
        self, mock_completion, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Call-site ordering in ``complete()``: merge happens before completion.

        Verifies two things — both observable from this test:
        1. ``ensure_model_priced`` runs from within ``complete()`` when the
           model is missing from ``litellm.model_cost`` (proven by
           ``register_calls`` being populated).
        2. The merge runs BEFORE ``litellm.completion`` (proven by
           ``complete()`` returning success — if merge ran after, the call
           order assertion below would fail in CI under code drift).

        Does NOT verify LiteLLM's internal cost calculator behavior:
        ``litellm.completion`` is mocked, so the ``cost_usd`` assertion
        below just exercises the mocked literal flowing through pflow's
        response normalization. The real cost-calculator integration is
        covered by manual e2e probes against ``gemini/gemini-3.5-flash``
        documented in PR #424.
        """
        import httpx
        import litellm

        from pflow.core import litellm_runtime

        # Reset the latch so the helper actually attempts the fetch.
        monkeypatch.setattr(litellm_runtime, "_upstream_attempted", False)
        # Force the model to appear missing from the bundled map.
        monkeypatch.setattr(litellm, "model_cost", {}, raising=False)

        fake_upstream_map = {
            "some/brand-new-model": {
                "input_cost_per_token": 1.5e-6,
                "output_cost_per_token": 9e-6,
                "litellm_provider": "gemini",
                "mode": "chat",
            },
        }

        # Stub httpx.get so we don't fire real HTTP to GitHub.
        def fake_httpx_get(url, *args, **kwargs):
            return MagicMock(
                raise_for_status=lambda: None,
                json=lambda: fake_upstream_map,
            )

        monkeypatch.setattr(httpx, "get", fake_httpx_get)

        register_calls: list[dict] = []

        def fake_register(upstream_map: dict) -> None:
            register_calls.append(upstream_map)
            # Simulate LiteLLM's real behavior: register_model merges the
            # upstream entries into litellm.model_cost.
            litellm.model_cost.update(upstream_map)

        monkeypatch.setattr(litellm, "register_model", fake_register)

        mock_completion.return_value = make_litellm_response(
            prompt_tokens=5,
            completion_tokens=58,
            response_cost=0.0005295,  # what LiteLLM would compute post-merge
        )

        response = complete(model="some/brand-new-model", prompt="hi")

        # 1. ensure_model_priced ran from within complete() and called
        #    register_model exactly once with the dict-form upstream map.
        assert len(register_calls) == 1
        assert register_calls[0] == fake_upstream_map
        # 2. The mocked response_cost flowed through pflow's response
        #    normalization (does NOT exercise LiteLLM's cost calculator).
        assert response.usage["cost_usd"] == 0.0005295

    @patch("litellm.completion")
    def test_thinking_tokens_zero_when_no_reasoning(self, mock_completion):
        # Non-reasoning model — no completion_tokens_details on usage.
        mock_completion.return_value = make_litellm_response(prompt_tokens=10, completion_tokens=5)
        response = complete(model="gpt-4o-mini", prompt="hi")
        assert response.usage["thinking_tokens"] == 0
        assert response.usage["thinking_budget"] == 0

    @patch("litellm.completion")
    def test_thinking_tokens_extracted_from_completion_details(self, mock_completion):
        # LiteLLM standardizes the per-call reasoning-token count to
        # usage.completion_tokens_details.reasoning_tokens regardless of
        # provider (Anthropic extended thinking, OpenAI o1/o3, Gemini 2.5/3).
        mock_completion.return_value = make_litellm_response(
            prompt_tokens=23,
            completion_tokens=157,
            reasoning_tokens=144,
        )
        response = complete(model="gemini/gemini-3-flash-preview", prompt="hi")
        assert response.usage["thinking_tokens"] == 144

    @patch("litellm.completion")
    def test_thinking_budget_mirrored_from_anthropic_request_kwargs(self, mock_completion):
        # Anthropic uses kwargs["thinking"]={"type":"enabled","budget_tokens":N}.
        # Adapter mirrors the budget into the response usage dict so the
        # metrics layer can compute thinking-utilization without needing
        # LLMNode to thread request kwargs into outputs.
        mock_completion.return_value = make_litellm_response(reasoning_tokens=512)
        response = complete(
            model="anthropic/claude-opus-4-5",
            prompt="hi",
            reasoning_kwargs={"thinking_effort": "medium"},
        )
        # 'medium' resolves to 0.5 * 16000 = 8000 budget per the EFFORT_RATIOS map
        assert response.usage["thinking_budget"] == 8000
        assert response.usage["thinking_tokens"] == 512

    @patch("litellm.completion")
    def test_thinking_budget_mirrored_from_gemini_top_level(self, mock_completion):
        # Gemini 2.5 uses top-level kwargs["thinking_budget"] instead of the
        # nested Anthropic shape. Adapter handles both paths.
        mock_completion.return_value = make_litellm_response(reasoning_tokens=200)
        response = complete(
            model="gemini-2.5-flash",
            prompt="hi",
            reasoning_kwargs={"thinking_budget": 1024},
        )
        assert response.usage["thinking_budget"] == 1024
        assert response.usage["thinking_tokens"] == 200


class TestCompleteErrorPaths:
    """The adapter translates every deterministic LiteLLM exception into a
    typed pflow subclass; non-deterministic ones propagate raw so the
    caller's retry loop can decide. Each subclass IS-A ``LLMCallError``,
    so consumers that catch the base class continue to work.
    """

    @patch("litellm.completion")
    def test_bad_request_raises_invalid_request_error(self, mock_completion):
        # Generic BadRequestError (anything that isn't an unknown-model case)
        # → InvalidRequestError. Catches via the LLMCallError base too.
        mock_completion.side_effect = litellm.exceptions.BadRequestError(
            message="temperature may only be set to 1 when thinking is enabled",
            model="anthropic/claude-opus-4-5",
            llm_provider="anthropic",
        )
        with pytest.raises(InvalidRequestError) as exc_info:
            complete(model="anthropic/claude-opus-4-5", prompt="hi")
        assert "Invalid request" in str(exc_info.value)
        assert "anthropic/claude-opus-4-5" in str(exc_info.value)
        # IS-A LLMCallError — the base catch still works.
        assert isinstance(exc_info.value, LLMCallError)
        # Underlying exception preserved as cause for traceback context.
        assert isinstance(exc_info.value.__cause__, litellm.exceptions.BadRequestError)

    @patch("litellm.completion")
    def test_not_found_raises_unknown_model_error(self, mock_completion):
        mock_completion.side_effect = litellm.exceptions.NotFoundError(
            message="Model not found",
            model="anthropic/claude-foo-99",
            llm_provider="anthropic",
        )
        with pytest.raises(UnknownModelError) as exc_info:
            complete(model="anthropic/claude-foo-99", prompt="hi")
        assert "anthropic/claude-foo-99" in str(exc_info.value)
        # Structured discriminator pins which sub-case fired.
        assert exc_info.value.reason == "unknown_name"
        assert isinstance(exc_info.value, LLMCallError)

    @patch("litellm.completion")
    def test_no_provider_prefix_raises_unknown_model_error(self, mock_completion):
        # Regression: bare model name (no provider prefix) used to surface as
        # a raw JSON envelope wrapped in LLMCallError. The substring detector
        # now translates it to UnknownModelError(reason="missing_prefix") so
        # consumers can build a precise "missing prefix" message without
        # re-parsing the message text.
        mock_completion.side_effect = litellm.exceptions.BadRequestError(
            message="LLM Provider NOT provided. Pass in the LLM provider...",
            model="gibberish",
            llm_provider="",
        )
        with pytest.raises(UnknownModelError) as exc_info:
            complete(model="gibberish", prompt="hi")
        assert "no provider prefix" in str(exc_info.value)
        # Structured discriminator distinguishes this from an unknown-name case.
        assert exc_info.value.reason == "missing_prefix"

    @patch("litellm.completion")
    def test_authentication_error_raises_missing_api_key_error(self, mock_completion):
        mock_completion.side_effect = litellm.exceptions.AuthenticationError(
            message="invalid key",
            model="gpt-4o-mini",
            llm_provider="openai",
        )
        with pytest.raises(MissingApiKeyError) as exc_info:
            complete(model="gpt-4o-mini", prompt="hi")
        assert "gpt-4o-mini" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, litellm.exceptions.AuthenticationError)

    @patch("litellm.completion")
    def test_permission_denied_raises_missing_api_key_error(self, mock_completion):
        # PermissionDeniedError requires an httpx.Response — provide a minimal
        # one so the constructor accepts it.
        resp = httpx.Response(403, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
        mock_completion.side_effect = litellm.exceptions.PermissionDeniedError(
            message="key lacks permission",
            model="gpt-4o-mini",
            llm_provider="openai",
            response=resp,
        )
        with pytest.raises(MissingApiKeyError) as exc_info:
            complete(model="gpt-4o-mini", prompt="hi")
        assert "gpt-4o-mini" in str(exc_info.value)

    @patch("litellm.completion")
    def test_timeout_raises_llm_transient_error(self, mock_completion):
        # Transient errors (Timeout, RateLimitError, InternalServerError)
        # are wrapped in LLMTransientError so the architectural seal stays
        # intact: consumers (LLMNode retry loop, smart_filter) catch the
        # LLMCallError umbrella without ever importing litellm.exceptions.
        # LLMNode's _call_llm re-raises this rather than catching it like
        # the deterministic subclasses, so the Node retry loop fires.
        mock_completion.side_effect = litellm.exceptions.Timeout(
            message="timed out",
            model="gpt-4o-mini",
            llm_provider="openai",
        )
        with pytest.raises(LLMTransientError) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        assert exc_info.value.model == "openai/gpt-4o-mini"
        assert exc_info.value.kind == "timeout"
        # IS-A LLMCallError — base catch still works for graceful degradation.
        assert isinstance(exc_info.value, LLMCallError)
        # Underlying exception preserved for traceback.
        assert isinstance(exc_info.value.__cause__, litellm.exceptions.Timeout)

    @patch("litellm.completion")
    def test_rate_limit_raises_llm_transient_error(self, mock_completion):
        mock_completion.side_effect = litellm.exceptions.RateLimitError(
            message="rate limit exceeded",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )
        with pytest.raises(LLMTransientError) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        assert isinstance(exc_info.value, LLMCallError)
        assert exc_info.value.kind == "rate_limit"

    @patch("litellm.completion")
    def test_internal_server_error_raises_llm_transient_error(self, mock_completion):
        mock_completion.side_effect = litellm.exceptions.InternalServerError(
            message="upstream 500",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )
        with pytest.raises(LLMTransientError) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        assert isinstance(exc_info.value, LLMCallError)
        assert exc_info.value.kind == "server_error"

    @patch("litellm.completion")
    def test_api_connection_error_raises_llm_transient_with_connection_kind(self, mock_completion):
        # Pin the fourth LLMTransientKind value end-to-end at the seam.
        # The other three (timeout, rate_limit, server_error) are pinned
        # above; without this case a regression in the "connection"
        # classifier branch would slip through.
        mock_completion.side_effect = litellm.exceptions.APIConnectionError(
            message="network down",
            model="gemini/gemini-2.5-flash",
            llm_provider="gemini",
        )
        with pytest.raises(LLMTransientError) as exc_info:
            complete(model="gemini/gemini-2.5-flash", prompt="hi")
        assert isinstance(exc_info.value, LLMCallError)
        assert exc_info.value.kind == "connection"


# --------------------------------------------------------------------------
# Architectural seal contract — every classified LiteLLM exception must
# wrap to LLMCallError. Parametrized so adding a new LiteLLM exception
# class without updating _classify_litellm_error fails this test loudly.
# --------------------------------------------------------------------------


def _make_bad_request(msg="bad", model="m", provider="openai"):
    return litellm.exceptions.BadRequestError(message=msg, model=model, llm_provider=provider)


def _make_auth(msg="invalid key", model="gpt-4o-mini", provider="openai"):
    return litellm.exceptions.AuthenticationError(message=msg, model=model, llm_provider=provider)


def _make_not_found(model="anthropic/claude-foo-99", provider="anthropic"):
    return litellm.exceptions.NotFoundError(message="model not found", model=model, llm_provider=provider)


def _make_permission_denied(model="gpt-4o-mini", provider="openai"):
    resp = httpx.Response(403, request=httpx.Request("POST", "https://x"))
    return litellm.exceptions.PermissionDeniedError(
        message="lacks permission", model=model, llm_provider=provider, response=resp
    )


def _make_no_provider_prefix(model="gibberish"):
    return litellm.exceptions.BadRequestError(
        message="LLM Provider NOT provided. Pass in the LLM provider...",
        model=model,
        llm_provider="",
    )


def _make_timeout(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.Timeout(message="timed out", model=model, llm_provider=provider)


def _make_rate_limit(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.RateLimitError(message="429", model=model, llm_provider=provider)


def _make_internal_server(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.InternalServerError(message="upstream 500", model=model, llm_provider=provider)


def _make_api_connection(model="gemini/gemini-3-flash-preview", provider="gemini"):
    # The Phase A review's central finding: this class previously leaked raw
    # past the seam because the old enumerative catch tuple didn't include it.
    return litellm.exceptions.APIConnectionError(message="network down", model=model, llm_provider=provider)


def _make_api_connection_missing_sdk(model="vertex_ai/gemini-2.0-flash", provider="vertex_ai"):
    # Missing SDK install — permanent failure, not transient. LiteLLM uses
    # implicit chaining (raise X inside except Y), so ImportError lands on
    # __context__, not __cause__. The detector walks both chains.
    outer = litellm.exceptions.APIConnectionError(
        message="Google Cloud SDK not found. Install it with: pip install 'litellm[google]'",
        model=model,
        llm_provider=provider,
    )
    outer.__context__ = ImportError("No module named 'google'")
    return outer


def _make_service_unavailable(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.ServiceUnavailableError(message="503 unavailable", model=model, llm_provider=provider)


def _make_bad_gateway(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.BadGatewayError(message="502 bad gateway", model=model, llm_provider=provider)


def _make_api_response_validation(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.APIResponseValidationError(
        message="invalid response shape", model=model, llm_provider=provider
    )


def _make_context_window(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.ContextWindowExceededError(message="too many tokens", model=model, llm_provider=provider)


def _make_content_policy(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.ContentPolicyViolationError(
        message="policy violation", model=model, llm_provider=provider
    )


def _make_unsupported_params(model="openai/gpt-4o-mini", provider="openai"):
    return litellm.exceptions.UnsupportedParamsError(message="unsupported param", model=model, llm_provider=provider)


# Every entry asserts the structural contract: the LiteLLM exception class
# is wrapped in the named pflow subclass (which IS-A LLMCallError, so the
# umbrella catches it for graceful degradation). Adding a new branch to
# _classify_litellm_error means adding a row here. Adding a new LiteLLM
# subclass that maps to the default fallback is also expected to be
# represented (treated as InvalidRequestError).
_SEAL_CONTRACT_CASES = [
    pytest.param(_make_bad_request, InvalidRequestError, id="bad_request_to_invalid_request"),
    pytest.param(_make_auth, MissingApiKeyError, id="auth_to_missing_api_key"),
    pytest.param(_make_not_found, UnknownModelError, id="not_found_to_unknown_model"),
    pytest.param(_make_permission_denied, MissingApiKeyError, id="permission_denied_to_missing_api_key"),
    pytest.param(_make_no_provider_prefix, UnknownModelError, id="no_provider_prefix_to_unknown_model"),
    pytest.param(_make_timeout, LLMTransientError, id="timeout_to_transient"),
    pytest.param(_make_rate_limit, LLMTransientError, id="rate_limit_to_transient"),
    pytest.param(_make_internal_server, LLMTransientError, id="internal_server_to_transient"),
    pytest.param(_make_api_connection, LLMTransientError, id="api_connection_to_transient"),
    pytest.param(_make_api_connection_missing_sdk, MissingSdkError, id="api_connection_missing_sdk_to_missing_sdk"),
    pytest.param(_make_service_unavailable, LLMTransientError, id="service_unavailable_to_transient"),
    pytest.param(_make_bad_gateway, LLMTransientError, id="bad_gateway_to_transient"),
    pytest.param(_make_api_response_validation, LLMResponseParseError, id="api_response_validation_to_parse_error"),
    pytest.param(_make_context_window, InvalidRequestError, id="context_window_to_invalid_request"),
    pytest.param(_make_content_policy, InvalidRequestError, id="content_policy_to_invalid_request"),
    pytest.param(_make_unsupported_params, InvalidRequestError, id="unsupported_params_to_invalid_request"),
]


class TestAdapterSealContract:
    """The adapter is the single seam where LiteLLM exceptions cross into pflow.

    Every LiteLLM exception we know about MUST be caught and wrapped as
    ``LLMCallError`` (or a subclass). If a new LiteLLM class appears that
    we forgot to classify, the structural ``openai.OpenAIError`` catch in
    ``complete()`` still wraps it via the default branch (treats as
    ``InvalidRequestError`` — fail-fast). This parametrized contract is
    the regression guard for both halves: every named case wraps to the
    specific subclass we expect, and the umbrella ``LLMCallError`` catches
    all of them so consumers like ``smart_filter`` can degrade gracefully.
    """

    @pytest.mark.parametrize(("factory", "expected_pflow_exc"), _SEAL_CONTRACT_CASES)
    @patch("litellm.completion")
    def test_litellm_exception_wraps_to_typed_pflow_exception(self, mock_completion, factory, expected_pflow_exc):
        mock_completion.side_effect = factory()
        with pytest.raises(expected_pflow_exc) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        # IS-A LLMCallError: the umbrella catch in smart_filter / discovery
        # MUST cover every classified exception.
        assert isinstance(exc_info.value, LLMCallError)
        # Underlying LiteLLM exception is preserved as __cause__ for tracebacks.
        assert exc_info.value.__cause__ is not None

    @patch("litellm.completion")
    def test_unknown_openai_error_subclass_wraps_to_invalid_request(self, mock_completion):
        # Synthesize an unknown ``openai.OpenAIError`` subclass — represents a
        # future LiteLLM exception class we haven't taught the classifier
        # about. The default branch must wrap it so it never leaks raw.
        import openai

        class _SyntheticUnknownError(openai.OpenAIError):
            pass

        upstream = _SyntheticUnknownError("uncharted territory")
        mock_completion.side_effect = upstream
        with pytest.raises(InvalidRequestError) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        assert isinstance(exc_info.value, LLMCallError)
        assert "_SyntheticUnknownError" in str(exc_info.value)
        # provider_message is preserved on the default branch too — even for
        # exception classes we haven't classified. Future-tolerant: a new
        # LiteLLM class arriving without an explicit branch still carries
        # its raw text into the diagnostic context.
        assert exc_info.value.provider_message == str(upstream)

    @pytest.mark.parametrize(("factory", "expected_pflow_exc"), _SEAL_CONTRACT_CASES)
    @patch("litellm.completion")
    def test_seam_threads_provider_message_to_every_classification(self, mock_completion, factory, expected_pflow_exc):
        # Every classified exception MUST carry the raw upstream text as
        # ``provider_message`` so agents can discriminate sub-cases beyond
        # the typed kind/reason. The wrapped pflow ``str(self)`` is for the
        # WHAT (Diagnostic.message); ``provider_message`` is for the WHY.
        # A regression that drops provider_message= on any classification
        # branch would silently revert structured discrimination — this
        # parametrized check fails loudly instead.
        upstream = factory()
        mock_completion.side_effect = upstream
        with pytest.raises(expected_pflow_exc) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        assert exc_info.value.provider_message == str(upstream)
        # And the diagnostic context surfaces it so JSON consumers see it.
        diagnostic = exc_info.value.to_diagnostics()[0]
        assert diagnostic.context["provider_message"] == str(upstream)


class TestLLMDiagnostics:
    def test_o4_missing_key_uses_openai_env_var(self):
        exc = MissingApiKeyError("API key required", model="o4-mini", kind="missing_key")
        diagnostic = exc.to_diagnostics()[0]
        # Canonical env var is surfaced in ctx as a list (canonical first).
        assert diagnostic.context["env_vars"] == ["OPENAI_API_KEY"]
        assert "OPENAI_API_KEY" in diagnostic.suggestions[0]

    def test_gemini_missing_key_lists_both_aliases(self):
        """LiteLLM's Gemini path accepts both GEMINI_API_KEY and GOOGLE_API_KEY.
        The diagnostic must surface both so a user with only GOOGLE_API_KEY
        set sees the alias rather than a misleading "set GEMINI_API_KEY"
        suggestion. Canonical is GEMINI_API_KEY (first); GOOGLE_API_KEY is
        listed as an accepted alternate.
        """
        exc = MissingApiKeyError(
            "API key required",
            model="gemini/gemini-2.5-flash",
            kind="missing_key",
        )
        diagnostic = exc.to_diagnostics()[0]
        assert diagnostic.context["env_vars"] == ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
        # Primary suggestion uses canonical.
        assert "GEMINI_API_KEY" in diagnostic.suggestions[0]
        # The alias is surfaced in a follow-up suggestion so users with
        # GOOGLE_API_KEY set know it's accepted.
        joined = " ".join(diagnostic.suggestions)
        assert "GOOGLE_API_KEY" in joined

    def test_unknown_provider_with_prefix_surfaces_likely_env_var(self):
        """Provider isn't in the registry but the model has a parseable prefix.

        The fix (was: hardcoded ANTHROPIC_API_KEY fallback): defer to the
        provider_message and surface a heuristic likely candidate, framed
        as "likely" rather than authoritative. Agents reading the JSON get
        the structured ``likely_env_var`` field; humans see the heuristic
        in the suggestions plus the raw provider error rendered above.
        """
        exc = MissingApiKeyError(
            "API key required for model 'together_ai/llama-3-70b'",
            model="together_ai/llama-3-70b",
            kind="missing_key",
            provider_message="TogetherAIException: 'TOGETHER_API_KEY' is not set",
        )
        diagnostic = exc.to_diagnostics()[0]
        # No registry entry → empty env_vars list.
        assert diagnostic.context["env_vars"] == []
        # Heuristic surfaces as a structured field for agents to read.
        assert diagnostic.context["likely_env_var"] == "TOGETHER_AI_API_KEY"
        # Primary suggestion does NOT fabricate a wrong-but-confident env var
        # (the old bug suggested ANTHROPIC_API_KEY here).
        joined = " ".join(diagnostic.suggestions).upper()
        assert "ANTHROPIC_API_KEY" not in joined
        # Suggestions defer to the provider_message as authoritative source.
        assert "above" in diagnostic.suggestions[0].lower()
        # Heuristic appears as a "likely" candidate, not authoritative.
        assert any("likely" in s.lower() and "TOGETHER_AI_API_KEY" in s for s in diagnostic.suggestions)
        # provider_message survives so the agent can read it directly.
        assert "TOGETHER_API_KEY" in diagnostic.context["provider_message"]

    def test_unknown_provider_disclaims_multi_key_cloud_providers(self):
        """The heuristic underspecifies Bedrock/Vertex/Azure; the suggestion
        text must explicitly disclaim that to prevent a wrong-but-confident
        fix path."""
        exc = MissingApiKeyError(
            "API key required for model 'bedrock/anthropic.claude-3-sonnet'",
            model="bedrock/anthropic.claude-3-sonnet",
            kind="missing_key",
            provider_message="Bedrock authentication failed",
        )
        diagnostic = exc.to_diagnostics()[0]
        assert diagnostic.context["likely_env_var"] == "BEDROCK_API_KEY"
        # Even though the heuristic produces "BEDROCK_API_KEY", the suggestion
        # mentions multi-key cloud providers explicitly so the user doesn't
        # spend time on a single env var when AWS creds are needed.
        joined = " ".join(diagnostic.suggestions)
        assert "Bedrock" in joined
        assert "additional credentials" in joined or "multi-key" in joined.lower()

    def test_unknown_provider_no_prefix_falls_back_to_docs(self):
        """No parseable prefix and no registry entry: pure docs link.

        No more ANTHROPIC_API_KEY fabrication when we have nothing to go on.
        """
        exc = MissingApiKeyError(
            "API key required for model 'something-weird'",
            model="something-weird",
            kind="missing_key",
            provider_message=None,
        )
        diagnostic = exc.to_diagnostics()[0]
        assert diagnostic.context["env_vars"] == []
        # No likely_env_var when there's no prefix to base it on; the field
        # is omitted from ctx (None values are filtered by diagnostic_context).
        assert "likely_env_var" not in diagnostic.context
        # Suggestions don't fabricate a wrong-but-specific env var.
        joined = " ".join(diagnostic.suggestions).upper()
        assert "ANTHROPIC_API_KEY" not in joined
        assert "OPENAI_API_KEY" not in joined
        # Docs link is always present as the floor.
        assert any("docs.litellm.ai" in s for s in diagnostic.suggestions)

    def test_missing_sdk_diagnostic_preserves_provider_message(self):
        raw = "Google Cloud SDK not found. Install it with: pip install 'litellm[google]'"
        exc = MissingSdkError(
            raw,
            model="vertex_ai/gemini-2.0-flash",
            package="litellm[google]",
            provider_message=raw,
        )
        diagnostic = exc.to_diagnostics()[0]
        assert diagnostic.context["provider_message"] == raw
        assert "Google Cloud SDK not found" in diagnostic.context["provider_message"]

    def test_transient_error_diagnostic_includes_kind_and_suggestions(self):
        exc = LLMTransientError("rate limit exceeded", model="openai/gpt-4o-mini", kind="rate_limit")
        diagnostic = exc.to_diagnostics()[0]
        assert diagnostic.title == "Transient LLM Failure"
        assert diagnostic.context["kind"] == "rate_limit"
        assert any("rate limit" in suggestion.lower() for suggestion in diagnostic.suggestions)

    def test_provider_message_carries_raw_text_when_set(self):
        """provider_message is the raw upstream text, distinct from Diagnostic.message.

        For UnknownModelError and MissingApiKeyError, the constructor message
        is pflow-wrapped framing ("Unknown model: X", "API key required for X").
        The raw provider text ("Quota exceeded", "Region not allowed") only
        survives when threaded explicitly via provider_message=. The seam
        (_classify_litellm_error) does this for every classification.
        """
        raw = "Quota exceeded for free tier"
        exc = MissingApiKeyError(
            "API key required for model 'openai/gpt-4o-mini'",
            model="openai/gpt-4o-mini",
            kind="missing_key",
            provider_message=raw,
        )
        diagnostic = exc.to_diagnostics()[0]
        # Diagnostic.message is the pflow-wrapped framing (the WHAT).
        assert diagnostic.message == "API key required for model 'openai/gpt-4o-mini'"
        # provider_message is the raw upstream text (the WHY).
        assert diagnostic.context["provider_message"] == raw

    def test_provider_message_is_none_when_not_set(self):
        """Direct construction without provider_message yields None — honest signal."""
        exc = UnknownModelError("Unknown model", model="openai/nope")
        diagnostic = exc.to_diagnostics()[0]
        assert diagnostic.context["provider_message"] is None


class TestCompleteTraceHook:
    @patch("litellm.completion")
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
        assert events[0]["model"] == "openai/gpt-4o-mini"  # normalized from bare "gpt-4o-mini"
        assert events[0]["prompt"] == "rendered prompt text"
        assert events[1]["event"] == "after_call"
        assert events[1]["response"].text == "OK"

    @patch("litellm.completion")
    def test_invoked_after_on_bad_request(self, mock_completion):
        # The trace_hook MUST fire after_call before the LLMCallError raises
        # so the trace captures the failure. Otherwise an error path silently
        # produces no after_call event and trace consumers can't tell what
        # happened.
        mock_completion.side_effect = litellm.exceptions.BadRequestError(
            message="bad",
            model="m",
            llm_provider="openai",
        )
        events: list[dict] = []
        with pytest.raises(LLMCallError):
            complete(model="m", prompt="hi", trace_hook=events.append)
        assert len(events) == 2
        assert events[0]["event"] == "before_call"
        assert events[1]["event"] == "after_call"
        assert events[1]["error"] is not None
        assert "m" in events[1]["error"]

    @patch("litellm.completion")
    def test_hook_exception_does_not_break_call(self, mock_completion, caplog):
        mock_completion.return_value = make_litellm_response(text="OK")

        def boom(_event):
            raise RuntimeError("trace bug")

        # Should still return a successful response despite the hook blowing up
        caplog.set_level("WARNING", logger="pflow.core.llm_client")
        response = complete(model="gpt-4o-mini", prompt="hi", trace_hook=boom)
        assert response.text == "OK"
        assert "trace_hook raised RuntimeError: trace bug" in caplog.text

    @patch("litellm.completion")
    def test_hook_none_is_no_op(self, mock_completion):
        mock_completion.return_value = make_litellm_response()
        # Should not raise
        complete(model="gpt-4o-mini", prompt="hi", trace_hook=None)


# --------------------------------------------------------------------------
# Malformed response shape — preserves the typed-exception seal AND the
# trace contract. The openai.OpenAIError catch in complete() covers
# litellm.completion failures, but does NOT cover failures that occur
# during the success-path normalization. Without an envelope, an empty
# choices list or missing usage attribute would escape as raw IndexError /
# AttributeError and the after_call trace event would never fire.
# --------------------------------------------------------------------------


class TestNormalizeMalformedResponse:
    @patch("litellm.completion")
    def test_empty_choices_raises_response_parse_error(self, mock_completion):
        # Provider returned a successful HTTP response but an empty choices
        # list. _normalize hits raw.choices[0] → IndexError. The adapter
        # must translate this to LLMResponseParseError so the typed-exception
        # seal stays intact.
        mock_completion.return_value = SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
            _hidden_params={},
        )
        with pytest.raises(LLMResponseParseError) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        # IS-A LLMCallError — umbrella catches still work.
        assert isinstance(exc_info.value, LLMCallError)
        assert exc_info.value.model == "openai/gpt-4o-mini"
        # provider_message captures the underlying IndexError text so agents
        # see the WHY, not just the wrapped framing.
        assert exc_info.value.provider_message is not None

    @patch("litellm.completion")
    def test_missing_usage_attribute_raises_response_parse_error(self, mock_completion):
        # Provider returned content but no usage object. _normalize hits
        # raw.usage → AttributeError. Same envelope contract.
        message = SimpleNamespace(content="ok", reasoning_content=None)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        mock_completion.return_value = SimpleNamespace(
            choices=[choice],
            # No `usage` attribute.
            _hidden_params={},
        )
        with pytest.raises(LLMResponseParseError) as exc_info:
            complete(model="openai/gpt-4o-mini", prompt="hi")
        assert isinstance(exc_info.value, LLMCallError)

    @patch("litellm.completion")
    def test_malformed_response_fires_after_call_with_error(self, mock_completion):
        # Trace contract: every before_call has a matching after_call,
        # success or failure. If _normalize raises and the envelope is
        # missing, after_call would silently not fire — breaking trace
        # consumers that count begin/end pairs.
        mock_completion.return_value = SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
            _hidden_params={},
        )
        events: list[dict] = []
        with pytest.raises(LLMResponseParseError):
            complete(
                model="openai/gpt-4o-mini",
                prompt="hi",
                trace_hook=events.append,
            )
        assert len(events) == 2
        assert events[0]["event"] == "before_call"
        assert events[1]["event"] == "after_call"
        assert events[1]["error"] is not None


# --------------------------------------------------------------------------
# Empty-response warning detection
# --------------------------------------------------------------------------


class TestNormalizeEmptyResponseWarning:
    """Detect empty-content cases the agent needs to know about.

    The adapter populates ``AdapterResponse.warnings`` with structured
    entries (``kind``, ``text``, ``context``) so consumers can lift them
    into ``shared["__warnings__"]`` for surfacing in JSON output and the
    DEGRADED workflow status. Each ``kind`` discriminates a sub-case:

    * ``llm_empty_response_reasoning`` — reasoning model spent budget on
      internal thinking, emitted no visible text
    * ``llm_empty_response_max_tokens`` — non-reasoning model hit token cap
    * ``llm_empty_response_content_filter`` — provider blocked output
    * ``llm_empty_response_stop`` — model chose to stop without content
    * ``llm_empty_response_unknown`` — provider didn't report finish_reason
    * ``llm_empty_response_unrecognized_finish_reason`` — future provider
      finish_reason with no content

    ``finish_reason="tool_calls"`` is intentionally silent (expected shape
    when the model wanted tools instead of text).
    """

    @patch("litellm.completion")
    def test_reasoning_model_emits_dual_remediation(self, mock_completion):
        # Reasoning model: thinking_tokens > 0 AND text empty AND finish_reason=length
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=13,
            finish_reason="length",
            reasoning_tokens=13,  # entire output budget went to thinking
        )
        response = complete(model="gemini/gemini-3-flash-preview", prompt="hi", max_tokens=16)
        assert response.warnings, "expected at least one structured warning"
        warning = response.warnings[0]
        assert warning["kind"] == "llm_empty_response_reasoning"
        # Dual remediation: increase max_tokens OR lower reasoning_effort
        assert "max_tokens" in warning["text"]
        assert "reasoning_effort" in warning["text"]
        # Structured context for agent consumers
        assert warning["context"]["finish_reason"] == "length"
        assert warning["context"]["thinking_tokens"] == 13

    @patch("litellm.completion")
    def test_non_reasoning_model_emits_max_tokens_remediation(self, mock_completion):
        # Non-reasoning model: thinking_tokens == 0 AND thinking_budget == 0.
        # Just an output-budget exhaustion; no reasoning_effort to lower.
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=50,
            finish_reason="max_tokens",
            reasoning_tokens=0,
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        warning = response.warnings[0]
        assert warning["kind"] == "llm_empty_response_max_tokens"
        assert "max_tokens" in warning["text"]
        # No reasoning_effort hint — would mislead for a non-reasoning model
        assert "reasoning_effort" not in warning["text"]

    @patch("litellm.completion")
    def test_content_filter_finish_reason(self, mock_completion):
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=5,
            finish_reason="content_filter",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        warning = response.warnings[0]
        assert warning["kind"] == "llm_empty_response_content_filter"
        assert "blocked" in warning["text"].lower()

    @patch("litellm.completion")
    def test_stop_with_empty_content(self, mock_completion):
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=5,
            finish_reason="stop",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        warning = response.warnings[0]
        assert warning["kind"] == "llm_empty_response_stop"

    @patch("litellm.completion")
    def test_none_finish_reason(self, mock_completion):
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=5,
            finish_reason=None,
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        warning = response.warnings[0]
        assert warning["kind"] == "llm_empty_response_unknown"

    @patch("litellm.completion")
    def test_unrecognized_finish_reason_warns(self, mock_completion):
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=5,
            finish_reason="future_reason",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        warning = response.warnings[0]
        assert warning["kind"] == "llm_empty_response_unrecognized_finish_reason"
        assert warning["context"]["finish_reason"] == "future_reason"

    @patch("litellm.completion")
    def test_tool_calls_finish_reason_is_silent(self, mock_completion):
        # tool_calls: model wanted tools, no content. Expected shape, not a warning.
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=5,
            finish_reason="tool_calls",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings == []

    @patch("litellm.completion")
    def test_no_warning_when_text_present(self, mock_completion):
        # Successful call — never warn even if finish_reason is unusual
        mock_completion.return_value = make_litellm_response(
            text="hello",
            completion_tokens=10,
            finish_reason="length",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings == []

    # --- Zero-output-tokens cases ---
    # Pre-Phase-A-review-fix the gate was ``if text or output_tokens <= 0:
    # return []`` — every zero-token case fell silently, including the ones
    # below where the empty response IS the signal worth surfacing.

    @patch("litellm.completion")
    def test_content_filter_with_zero_tokens_warns(self, mock_completion):
        # Provider blocked output before any tokens were emitted.
        # Pre-fix this returned warnings == [] because of the
        # ``output_tokens <= 0`` short-circuit; agents lost the signal that
        # the provider explicitly refused the request.
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=0,
            finish_reason="content_filter",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        warning = response.warnings[0]
        assert warning["kind"] == "llm_empty_response_content_filter"
        assert "blocked" in warning["text"].lower()

    @patch("litellm.completion")
    def test_stop_with_zero_tokens_warns(self, mock_completion):
        # Model chose to stop with zero output. Anomalous; surface it.
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=0,
            finish_reason="stop",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        assert response.warnings[0]["kind"] == "llm_empty_response_stop"

    @patch("litellm.completion")
    def test_none_finish_reason_with_zero_tokens_warns(self, mock_completion):
        # Provider returned nothing AND didn't say why — investigate.
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=0,
            finish_reason=None,
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        assert response.warnings[0]["kind"] == "llm_empty_response_unknown"

    @patch("litellm.completion")
    def test_length_with_zero_tokens_warns(self, mock_completion):
        # Anomalous (a real provider should not return finish_reason=length
        # with zero completion tokens), but still worth surfacing — the
        # message says "0 tokens consumed" so the user can see the oddity.
        mock_completion.return_value = make_litellm_response(
            text=None,
            completion_tokens=0,
            finish_reason="length",
        )
        response = complete(model="openai/gpt-4o-mini", prompt="hi")
        assert response.warnings
        assert response.warnings[0]["kind"] == "llm_empty_response_max_tokens"
        assert "0 tokens consumed" in response.warnings[0]["text"]
