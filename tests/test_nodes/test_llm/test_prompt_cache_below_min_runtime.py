"""Runtime pre-dispatch strip — when rendered cache content for a marker
is below the provider's minimum, strip the ``cache_control`` marker before
sending so the call goes out uncached instead of hard-failing on Gemini.

Tests use ``mock_llm_client.call_history_full[-1]`` to inspect the actual
blocks sent to the adapter. Token counts are stubbed via monkeypatching
``_count_text_tokens`` so the threshold-vs-measured math is deterministic
across providers and tokenizer versions.

This is the runtime ``cache.below-min-rendered`` path, distinct from
``cache.below-min-predicted`` (analyzer-time) and
``cache.below-min-observed`` (post-call telemetry).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from pflow.core.cache_render import CacheBlockIR, CacheChunkIR, CacheRenderContext
from pflow.nodes.llm import LLMNode
from pflow.nodes.llm import llm as llm_module

ANTHROPIC_1024 = "anthropic/claude-sonnet-4-5"  # min_cache_tokens = 1024
ANTHROPIC_2048 = "anthropic/claude-sonnet-4-6"  # min_cache_tokens = 2048
GEMINI = "gemini/gemini-2.5-pro"  # min_cache_tokens = 4096
UNKNOWN = "totally-fictional-model"  # falls back to CONSERVATIVE_FLOOR = 4096


# --- Helpers (mirroring tests/test_nodes/test_llm/test_prompt_cache_rendering.py) -


def _ctx(
    *,
    chunks: list[tuple[str, str]],
    subset: tuple[str, ...],
    ttl: str | None = None,
    prewarm: bool = False,
) -> CacheRenderContext:
    items = tuple(CacheChunkIR(name=n, var_expr=n, prose_before=p, source_line=0) for n, p in chunks)
    block = CacheBlockIR(ttl=ttl, items=items, source_line=0)
    return CacheRenderContext(
        cache_block=block,
        subset=subset,
        prewarm=prewarm,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )


def _install_cache_render(shared: dict[str, Any], node_id: str, ctx: CacheRenderContext) -> None:
    shared["__pflow_cache_render__"] = MappingProxyType({node_id: ctx})


def _make_node(node_id: str, *, model: str = ANTHROPIC_1024, system: str | None = None) -> LLMNode:
    node = LLMNode()
    node.node_id = node_id  # type: ignore[attr-defined]
    params: dict[str, Any] = {"prompt": "What is the answer?", "model": model}
    if system is not None:
        params["system"] = system
    node.set_params(params)
    return node


def _stub_token_counter(monkeypatch: pytest.MonkeyPatch, tokens: int) -> None:
    """Force ``_count_text_tokens`` to return ``tokens`` for every call.

    Cleaner than wrestling with provider-specific tokenizer behavior — the
    runtime strip is being tested, not the tokenizer.
    """
    monkeypatch.setattr(llm_module, "_count_text_tokens", lambda text, model: tokens)


# --- (a) Below-min content: marker stripped, warning emitted -----------------


def test_below_min_strips_cache_control_and_emits_warning(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=500)  # below Anthropic 1024

    node = _make_node("write-lyrics", model=ANTHROPIC_1024)
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",), ttl=None),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list), "expected structured blocks"
    assert all("cache_control" not in block for block in sent), f"cache_control should be stripped; got blocks: {sent}"

    warning = shared.get("__warnings__", {}).get("write-lyrics")
    assert warning is not None, "expected a rendered below-min warning to be emitted"
    assert warning.id == "cache.below-min-rendered"
    assert warning.context["cacheable_tokens"] == 500
    assert warning.context["min_tokens"] == 1024
    assert shared["llm_usage"]["cache_skipped_reason"] == "below_min"


# --- (b) Above-min content: marker preserved, no warning ---------------------


def test_above_min_keeps_cache_control_no_rendered_warning(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    # Stage realistic cache telemetry: provider reported a successful cache
    # hit, so neither rendered nor observed-tier warnings fire.
    mock_llm_client.set_response("*", None, "ok", cache_creation_input_tokens=1500, cache_read_input_tokens=0)
    _stub_token_counter(monkeypatch, tokens=1500)  # above Anthropic 1024

    node = _make_node("write-lyrics", model=ANTHROPIC_1024)
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",), ttl=None),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    assert sent[-1].get("cache_control") == {"type": "ephemeral"}, (
        f"marker should be preserved when above threshold; got: {sent[-1]}"
    )
    warning = shared.get("__warnings__", {}).get("write-lyrics")
    assert warning is None, f"no warning expected when cache fires above min; got: {warning}"
    assert shared["llm_usage"]["cache_skipped_reason"] is None


def test_prewarm_disabled_reason_flows_to_llm_usage(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")

    node = _make_node("write-lyrics", model=ANTHROPIC_1024)
    shared = {"__prewarm_disabled_below_min__": {"write-lyrics": "below_min"}}

    node.run(shared)

    assert shared["llm_usage"]["prewarm_disabled_reason"] == "below_min"


# --- (c) Boundary tests -------------------------------------------------------


def test_at_threshold_minus_one_strips(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """One token below threshold — strict ``<`` comparison."""
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=1023)  # 1024 - 1

    node = _make_node("n", model=ANTHROPIC_1024)
    shared = {"concept": "x"}
    _install_cache_render(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert all("cache_control" not in b for b in sent)


def test_at_exact_threshold_keeps(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly at threshold — provider would accept; marker preserved."""
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=1024)

    node = _make_node("n", model=ANTHROPIC_1024)
    shared = {"concept": "x"}
    _install_cache_render(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1].get("cache_control") == {"type": "ephemeral"}


# --- (d) Gemini 4096 threshold -----------------------------------------------


def test_gemini_below_4096_strips(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """The originally-reported failure mode: Gemini hard-rejects below 2048+.
    With strip, content rendering at 1135 tokens (the original repro value)
    is recognized and the marker is stripped before send."""
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=1135)  # the original repro value

    node = _make_node("score-choruses", model=GEMINI)
    shared = {"concept": "x"}
    _install_cache_render(shared, "score-choruses", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert all("cache_control" not in b for b in sent)

    warning = shared["__warnings__"]["score-choruses"]
    assert warning.context["min_tokens"] == 4096
    assert warning.context["cacheable_tokens"] == 1135
    assert "Gemini" in warning.context["provider_note"]


# --- (e) Unknown model uses CONSERVATIVE_FLOOR (4096) ------------------------


def test_unknown_model_uses_conservative_floor(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=2000)  # above 1024, below 4096 floor

    node = _make_node("n", model=UNKNOWN)
    shared = {"concept": "x"}
    _install_cache_render(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert all("cache_control" not in b for b in sent), (
        "unknown model should use CONSERVATIVE_FLOOR=4096; 2000 tokens should strip"
    )
    warning = shared["__warnings__"]["n"]
    assert warning.context["min_tokens"] == 4096


# --- (i) Observed-tier emission does not fire after pre-dispatch strip -------


def test_observed_tier_suppressed_after_rendered_strip(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """After strip, the provider sees no cache_control markers and returns no
    cache telemetry. The observed-tier emission gates on
    ``has_cache_telemetry`` (False when provider didn't report any cache
    field), so no double-emit. The rendered warning is the only one."""
    mock_llm_client.set_response(
        "*",
        None,
        "ok",
        cache_creation_input_tokens=None,  # simulate no telemetry returned
        cache_read_input_tokens=None,
    )
    _stub_token_counter(monkeypatch, tokens=500)

    node = _make_node("write-lyrics", model=ANTHROPIC_1024)
    shared = {"concept": "x"}
    _install_cache_render(shared, "write-lyrics", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    warning = shared["__warnings__"]["write-lyrics"]
    assert warning.id == "cache.below-min-rendered"


# --- Heuristic fallback when token_counter raises ----------------------------


def test_token_counter_exception_falls_back_to_chars_over_four(
    mock_llm_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``litellm.token_counter`` raises, the helper falls back to
    ``len(text) // 4``. This isolates the heuristic path."""
    import pflow.core.litellm_runtime as litellm_runtime

    class _BoomLitellm:
        def token_counter(self, **kwargs: Any) -> int:
            raise RuntimeError("simulated litellm failure")

    monkeypatch.setattr(litellm_runtime, "import_litellm", lambda: _BoomLitellm())

    # 4000 chars / 4 = 1000 estimated tokens, below 1024 → should strip.
    big_concept = "x" * 4000
    mock_llm_client.set_response("*", None, "ok")

    node = _make_node("n", model=ANTHROPIC_1024)
    shared = {"concept": big_concept}
    _install_cache_render(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert all("cache_control" not in b for b in sent)
    warning = shared["__warnings__"]["n"]
    assert warning.context["cacheable_tokens"] == 1000  # 4000 // 4
