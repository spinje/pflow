"""Tests for the provider/model → reasoning kwargs map.

Replaces the live `model.Options.model_fields` introspection that previously
lived in `nodes/llm/llm.py::_map_reasoning_options` (and was tested in
`tests/test_nodes/test_llm/test_llm_reasoning.py`). The mapping logic is
identical; only the source of capabilities changed (model-name string
sniffing instead of Pydantic introspection).
"""

from __future__ import annotations

import pytest

from pflow.core.llm_reasoning_map import (
    EFFORT_BUDGET_BASE,
    EFFORT_RATIOS,
    SAFETY_FRACTION,
    _detect_capabilities,
    map_reasoning_options,
)

# --------------------------------------------------------------------------
# _detect_capabilities — the new model-name sniffing layer
# --------------------------------------------------------------------------


class TestDetectCapabilitiesAnthropic:
    """Opus 4.5 collapses into the generic Anthropic budget caps (no special
    thinking_effort relay — see #446); Opus 4.7 stays adaptive."""

    def test_opus_45_uses_budget_caps(self):
        # Opus 4.5 no longer carries a `thinking_effort` capability. It uses
        # the same thinking + thinking_budget path as every other Anthropic
        # budget-style model; the budget is derived in llm_reasoning_map.
        caps = _detect_capabilities("anthropic/claude-opus-4-5")
        assert caps == {"thinking", "thinking_budget"}

    def test_opus_45_dotted_alias(self):
        assert _detect_capabilities("anthropic/claude-opus-4.5") == {"thinking", "thinking_budget"}

    def test_opus_45_dated_variant(self):
        # Real Anthropic model ids include a date suffix (e.g. -20251101)
        caps = _detect_capabilities("anthropic/claude-opus-4-5-20251101")
        assert caps == {"thinking", "thinking_budget"}

    def test_opus_47_uses_adaptive_reasoning_effort(self):
        # Opus 4.7 must NOT get the legacy thinking/thinking_budget caps — that
        # path emits thinking.type.enabled, which Opus 4.7 rejects (GH #368).
        # It must route to the adaptive path that delegates to LiteLLM's
        # standardized reasoning_effort.
        caps = _detect_capabilities("anthropic/claude-opus-4-7")
        assert caps == {"reasoning_effort_adaptive"}
        assert "thinking_budget" not in caps

    def test_opus_47_dotted_alias(self):
        assert _detect_capabilities("anthropic/claude-opus-4.7") == {"reasoning_effort_adaptive"}

    def test_opus_47_dated_variant(self):
        caps = _detect_capabilities("anthropic/claude-opus-4-7-20260115")
        assert caps == {"reasoning_effort_adaptive"}

    def test_opus_47_unprefixed_claude_name(self):
        # Bare claude- name (no provider prefix) still routes to adaptive,
        # mirroring test_unprefixed_claude_name for Sonnet.
        assert _detect_capabilities("claude-opus-4-7") == {"reasoning_effort_adaptive"}

    def test_sonnet_4_5_no_thinking_effort(self):
        # Sonnet has thinking/thinking_budget but NOT thinking_effort
        caps = _detect_capabilities("anthropic/claude-sonnet-4-5")
        assert "thinking_effort" not in caps
        assert caps == {"thinking", "thinking_budget"}

    def test_opus_4_1_no_thinking_effort(self):
        caps = _detect_capabilities("anthropic/claude-opus-4-1-20250805")
        assert "thinking_effort" not in caps
        assert caps == {"thinking", "thinking_budget"}

    def test_unprefixed_claude_name(self):
        # Bare claude- name still detected
        caps = _detect_capabilities("claude-sonnet-4-0")
        assert caps == {"thinking", "thinking_budget"}


class TestDetectCapabilitiesGemini:
    """Gemini 3 uses thinking_level; Gemini 2.5 (non-lite) uses thinking_budget."""

    def test_gemini_3_flash(self):
        caps = _detect_capabilities("gemini-3-flash-preview")
        assert caps == {"thinking_level"}

    def test_gemini_2_5_pro(self):
        caps = _detect_capabilities("gemini-2.5-pro")
        assert caps == {"thinking_budget"}

    def test_gemini_2_5_flash(self):
        caps = _detect_capabilities("gemini-2.5-flash")
        assert caps == {"thinking_budget"}

    def test_gemini_2_5_flash_lite_no_reasoning(self):
        # Lite variant has no thinking — explicit empty set
        caps = _detect_capabilities("gemini-2.5-flash-lite")
        assert caps == set()

    def test_older_gemini_no_reasoning(self):
        caps = _detect_capabilities("gemini-1.5-pro")
        assert caps == set()


class TestDetectCapabilitiesOpenAI:
    """gpt-5* and o1/o3/o4 reasoning models; gpt-4* and below get nothing."""

    def test_gpt_5_mini(self):
        caps = _detect_capabilities("gpt-5-mini")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_gpt_5_2(self):
        caps = _detect_capabilities("gpt-5.2")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_gpt_5_2_pro(self):
        caps = _detect_capabilities("gpt-5.2-pro")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_o1_bare(self):
        caps = _detect_capabilities("o1")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_o3_bare(self):
        caps = _detect_capabilities("o3")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_o4_bare(self):
        caps = _detect_capabilities("o4-mini")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_openai_o1_prefixed(self):
        caps = _detect_capabilities("openai/o1")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_openai_o4_prefixed(self):
        caps = _detect_capabilities("openai/o4-mini")
        assert caps == {"reasoning_effort", "reasoning_max_tokens"}

    def test_gpt_4o_no_reasoning(self):
        caps = _detect_capabilities("gpt-4o")
        assert caps == set()

    def test_gpt_4o_mini_no_reasoning(self):
        caps = _detect_capabilities("gpt-4o-mini")
        assert caps == set()

    def test_gpt_4_no_reasoning(self):
        caps = _detect_capabilities("gpt-4")
        assert caps == set()


class TestDetectCapabilitiesUnknown:
    """Unknown providers return an empty set (graceful no-op)."""

    def test_completely_unknown(self):
        assert _detect_capabilities("some-future-model-xyz") == set()

    def test_ollama(self):
        # Ollama-prefixed local models have no reasoning kwargs in this map
        assert _detect_capabilities("ollama/llama3.1") == set()

    def test_openrouter_anthropic_path_is_not_anthropic(self):
        assert _detect_capabilities("openrouter/anthropic/claude-sonnet-4-5") == set()


# --------------------------------------------------------------------------
# map_reasoning_options — public API
# Mirrors the original test_llm_reasoning.py coverage but with real
# model-name strings instead of mock Options.
# --------------------------------------------------------------------------


class TestMapReasoningOptionsNoOp:
    """When no reasoning params are provided, returns empty dict."""

    def test_both_none(self):
        assert map_reasoning_options("anthropic/claude-sonnet-4-5", None, None, None) == {}

    def test_empty_string_effort(self):
        assert map_reasoning_options("anthropic/claude-sonnet-4-5", "", None, None) == {}

    def test_unsupported_model_returns_empty_even_with_effort(self):
        # gpt-4 has no reasoning fields → {}
        assert map_reasoning_options("gpt-4", "high", None, None) == {}


class TestMapReasoningMaxTokens:
    """Direct token budget via reasoning_max_tokens."""

    def test_anthropic_thinking_budget(self):
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", None, 8000, None)
        assert result == {"thinking": True, "thinking_budget": 8000}

    def test_anthropic_opus_45_thinking_budget(self):
        # Opus 4.5 uses thinking_budget for direct budget too (the
        # _map_direct_budget helper checks thinking_budget before
        # thinking_effort — by design)
        result = map_reasoning_options("anthropic/claude-opus-4-5", None, 8000, None)
        assert result == {"thinking": True, "thinking_budget": 8000}

    def test_gemini_thinking_budget_no_thinking_flag(self):
        # Gemini 2.5 has no `thinking` field, so no `thinking: True`
        result = map_reasoning_options("gemini-2.5-pro", None, 4000, None)
        assert result == {"thinking_budget": 4000}

    def test_openai_reasoning_max_tokens(self):
        result = map_reasoning_options("gpt-5-mini", None, 5000, None)
        assert result == {"reasoning_max_tokens": 5000}

    def test_max_tokens_takes_precedence_over_effort(self):
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "high", 8000, None)
        assert result == {"thinking": True, "thinking_budget": 8000}

    def test_opus_45_max_tokens_takes_precedence_over_effort(self):
        # Opus 4.5 is the only model with BOTH thinking_effort capability
        # (used when only effort is provided) AND thinking_budget capability
        # (used for direct budget). When both inputs are given, max_tokens
        # wins per map_reasoning_options' contract — the thinking_budget
        # shape is returned, NOT the thinking_effort shape. Easy to break
        # by reordering the precedence dispatch in map_reasoning_options.
        result = map_reasoning_options("anthropic/claude-opus-4-5", "high", 8000, None)
        assert result == {"thinking": True, "thinking_budget": 8000}
        assert "thinking_effort" not in result


class TestMapReasoningEffortNone:
    """effort='none' disables reasoning."""

    def test_disable_anthropic(self):
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "none", None, None)
        assert result == {"thinking": False}

    def test_disable_gemini_25(self):
        result = map_reasoning_options("gemini-2.5-pro", "none", None, None)
        assert result == {"thinking_budget": 0}

    def test_disable_gemini_3(self):
        # Gemini 3 has no off-switch — capability is `thinking_level` (categorical).
        # 'none' maps to the lowest level so callers expressing "minimum reasoning
        # cost" get the cheapest setting Gemini 3 supports.
        result = map_reasoning_options("gemini-3-flash-preview", "none", None, None)
        assert result == {"thinking_level": "minimal"}

    def test_disable_openai_returns_empty(self):
        # OpenAI has no `thinking`/`thinking_budget`/`thinking_level` field in
        # the capability set, so 'none' falls through to {}
        result = map_reasoning_options("gpt-5-mini", "none", None, None)
        assert result == {}


class TestOpus45Effort:
    """Opus 4.5 derives a thinking budget through the shared path (#446).

    It used to emit a categorical ``thinking_effort`` that never reached the
    API. It now produces the SAME budget as every other Anthropic
    budget-style model (see ``TestEffortOpusSonnetParity``). xhigh and
    minimal are no longer collapsed to high/low — they get their own ratios.
    """

    MODEL = "anthropic/claude-opus-4-5"

    def test_high(self):
        result = map_reasoning_options(self.MODEL, "high", None, None)
        assert result == {"thinking": True, "thinking_budget": 12800}  # 0.80 * 16000
        assert "thinking_effort" not in result

    def test_xhigh(self):
        result = map_reasoning_options(self.MODEL, "xhigh", None, None)
        assert result == {"thinking": True, "thinking_budget": 15200}  # 0.95 * 16000

    def test_minimal(self):
        result = map_reasoning_options(self.MODEL, "minimal", None, None)
        assert result == {"thinking": True, "thinking_budget": 1600}  # 0.10 * 16000

    def test_low(self):
        result = map_reasoning_options(self.MODEL, "low", None, None)
        assert result == {"thinking": True, "thinking_budget": 3200}  # 0.20 * 16000

    def test_medium(self):
        result = map_reasoning_options(self.MODEL, "medium", None, None)
        assert result == {"thinking": True, "thinking_budget": 8000}  # 0.50 * 16000


class TestEffortOpusSonnetParity:
    """#446 root fix: Opus 4.5 and Sonnet 4.5 now derive IDENTICAL budgets for
    the same (effort, max_tokens). The old Sonnet-vs-Opus-4.5 split is gone."""

    @pytest.mark.parametrize("effort", list(EFFORT_RATIOS))
    @pytest.mark.parametrize("max_tokens", [None, 4000, 16000, 64000])
    def test_opus_45_matches_sonnet(self, effort: str, max_tokens: int | None):
        opus = map_reasoning_options("anthropic/claude-opus-4-5", effort, None, max_tokens)
        sonnet = map_reasoning_options("anthropic/claude-sonnet-4-5", effort, None, max_tokens)
        assert opus == sonnet


class TestOpus47AdaptiveReasoning:
    """Opus 4.7 emits LiteLLM's standardized reasoning_effort (GH #368).

    Unlike every other Anthropic model it must NOT produce the
    thinking/thinking_budget shape — Opus 4.7 rejects thinking.type.enabled and
    requires the adaptive dialect, which LiteLLM builds from reasoning_effort.
    """

    MODEL = "anthropic/claude-opus-4-7"

    def test_low(self):
        assert map_reasoning_options(self.MODEL, "low", None, None) == {"reasoning_effort": "low"}

    def test_medium(self):
        assert map_reasoning_options(self.MODEL, "medium", None, None) == {"reasoning_effort": "medium"}

    def test_high(self):
        result = map_reasoning_options(self.MODEL, "high", None, None)
        assert result == {"reasoning_effort": "high"}
        # Guard against the rejected legacy shape leaking back in.
        assert "thinking_budget" not in result
        assert "thinking" not in result

    def test_xhigh_collapses_to_high(self):
        # Anthropic's effort vocabulary is low/medium/high.
        assert map_reasoning_options(self.MODEL, "xhigh", None, None) == {"reasoning_effort": "high"}

    def test_minimal_collapses_to_low(self):
        assert map_reasoning_options(self.MODEL, "minimal", None, None) == {"reasoning_effort": "low"}

    def test_none_omits_param(self):
        # reasoning_effort: none -> no param (Opus 4.7 thinks adaptively by
        # default; omitting is the control case GH #368 confirmed is accepted).
        assert map_reasoning_options(self.MODEL, "none", None, None) == {}

    def test_reasoning_max_tokens_is_ignored(self):
        # The 3rd positional arg is reasoning_max_tokens. Adaptive thinking has
        # no explicit token budget, so rather than emit the rejected budget
        # shape we drop it and let Opus 4.7 use its default adaptive thinking
        # (documented in the module docstring).
        assert map_reasoning_options(self.MODEL, None, 8000) == {}


class TestEffortOpenAI:
    """OpenAI gpt-5/o1/o3 — passes effort string through unchanged."""

    def test_high(self):
        result = map_reasoning_options("gpt-5-mini", "high", None, None)
        assert result == {"reasoning_effort": "high"}

    def test_minimal(self):
        result = map_reasoning_options("gpt-5-mini", "minimal", None, None)
        assert result == {"reasoning_effort": "minimal"}

    def test_o1(self):
        result = map_reasoning_options("o1", "medium", None, None)
        assert result == {"reasoning_effort": "medium"}


class TestEffortGemini3:
    """Gemini 3 — thinking_level, with xhigh→high mapping."""

    def test_high(self):
        result = map_reasoning_options("gemini-3-flash-preview", "high", None, None)
        assert result == {"thinking_level": "high"}

    def test_xhigh_maps_to_high(self):
        result = map_reasoning_options("gemini-3-flash-preview", "xhigh", None, None)
        assert result == {"thinking_level": "high"}

    def test_minimal_unchanged(self):
        # thinking_level accepts 'minimal' so it passes through (unlike Opus
        # 4.5's thinking_effort which maps minimal→low)
        result = map_reasoning_options("gemini-3-flash-preview", "minimal", None, None)
        assert result == {"thinking_level": "minimal"}


def _expected_budget(effort: str, max_tokens: int | None) -> int:
    """Mirror of llm_reasoning_map._fit_budget for the effort path (#446)."""
    desired = int(EFFORT_BUDGET_BASE * EFFORT_RATIOS[effort])
    if max_tokens is not None:
        desired = min(desired, int(max_tokens * SAFETY_FRACTION))
    return max(min(desired, 128000), 1024)


class TestEffortTokenBudgetCalculation:
    """Anthropic / Gemini 2.5 — clamp semantics (#446): effort drives depth
    against a fixed base; max_tokens only constrains."""

    def test_anthropic_high_with_max_tokens_equal_to_base(self):
        # max_tokens == base, so cap (0.8*16000) == desired (0.8*16000) == 12800.
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "high", None, 16000)
        assert result == {"thinking": True, "thinking_budget": 12800}

    def test_anthropic_high_uses_fixed_base_when_max_tokens_none(self):
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "high", None, None)
        expected_budget = int(EFFORT_BUDGET_BASE * 0.80)  # 12800
        assert result == {"thinking": True, "thinking_budget": expected_budget}

    def test_large_max_tokens_does_not_inflate_budget(self):
        # The headline #446 fix: raising max_tokens for a longer answer must
        # NOT inflate reasoning spend. high effort caps at the fixed base
        # (12800), NOT max_tokens * ratio (which would be 51200).
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "high", None, 64000)
        assert result["thinking_budget"] == 12800

    def test_small_max_tokens_clamps_below_ceiling(self):
        # high effort wants 12800, but max_tokens=4000 caps it to 4000*0.8=3200.
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "high", None, 4000)
        assert result["thinking_budget"] == 3200
        assert result["thinking_budget"] < 4000  # invariant: budget < max_tokens

    def test_budget_floored_to_minimum(self):
        # minimal effort with a tiny max_tokens floors to 1024.
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "minimal", None, 1100)
        assert result["thinking_budget"] == 1024

    def test_huge_max_tokens_caps_at_fixed_base_not_128k(self):
        # Under clamp the effort budget tops out at the fixed base (xhigh →
        # 15200), so the 128k ceiling no longer binds via the effort path.
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "xhigh", None, 200000)
        assert result["thinking_budget"] == 15200

    def test_gemini_25_has_no_thinking_flag(self):
        # Gemini lacks the `thinking` capability — only thinking_budget
        result = map_reasoning_options("gemini-2.5-pro", "medium", None, 16000)
        assert result == {"thinking_budget": 8000}  # 0.50 * 16000

    @pytest.mark.parametrize("effort", list(EFFORT_RATIOS))
    @pytest.mark.parametrize("max_tokens", [None, 2000, 4000, 16000, 64000, 200000])
    def test_budget_always_under_ceiling(self, effort: str, max_tokens: int | None):
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", effort, None, max_tokens)
        assert result["thinking_budget"] == _expected_budget(effort, max_tokens)
        assert result["thinking"] is True
        if max_tokens is not None:
            # The invariant the whole issue is about.
            assert result["thinking_budget"] < max_tokens


class TestUnsupportedModel:
    """Models with no reasoning support."""

    def test_gpt_4_returns_empty(self):
        result = map_reasoning_options("gpt-4", "high", None, None)
        assert result == {}

    def test_gemini_lite_returns_empty(self):
        result = map_reasoning_options("gemini-2.5-flash-lite", "high", None, None)
        assert result == {}

    def test_unknown_returns_empty(self):
        result = map_reasoning_options("future-model-2030", "high", None, None)
        assert result == {}


class TestCaseInsensitive:
    """Effort values are case-insensitive."""

    def test_uppercase(self):
        result = map_reasoning_options("gpt-5-mini", "HIGH", None, None)
        assert result == {"reasoning_effort": "high"}

    def test_mixed_case(self):
        result = map_reasoning_options("gpt-5-mini", "Medium", None, None)
        assert result == {"reasoning_effort": "medium"}

    def test_none_uppercase(self):
        result = map_reasoning_options("anthropic/claude-sonnet-4-5", "NONE", None, None)
        assert result == {"thinking": False}
