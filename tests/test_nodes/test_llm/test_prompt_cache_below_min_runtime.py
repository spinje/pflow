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

from pflow.core.prompt_cache import CacheBlockIR, CacheChunkIR, CacheRenderContext
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


def _install_prompt_cache(shared: dict[str, Any], node_id: str, ctx: CacheRenderContext) -> None:
    shared["__pflow_prompt_cache__"] = MappingProxyType({node_id: ctx})


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
    _install_prompt_cache(
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
    _install_prompt_cache(
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
    _install_prompt_cache(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert all("cache_control" not in b for b in sent)


def test_at_exact_threshold_keeps(mock_llm_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly at threshold — provider would accept; marker preserved."""
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=1024)

    node = _make_node("n", model=ANTHROPIC_1024)
    shared = {"concept": "x"}
    _install_prompt_cache(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
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
    _install_prompt_cache(shared, "score-choruses", _ctx(chunks=[("concept", "")], subset=("concept",)))
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
    _install_prompt_cache(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
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
    _install_prompt_cache(shared, "write-lyrics", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    warning = shared["__warnings__"]["write-lyrics"]
    assert warning.id == "cache.below-min-rendered"


# --- Heuristic fallback when token_counter raises ----------------------------


# --- Channel-aware strip — declared vs prewarm vs combined -------------------


def _ctx_prewarm_batch(
    *,
    chunks: list[tuple[str, str]] | None = None,
    subset: tuple[str, ...] = (),
    unresolved_batch_prompt: str,
    batch_alias: str = "item",
    ttl: str | None = None,
) -> CacheRenderContext:
    items = tuple(CacheChunkIR(name=n, var_expr=n, prose_before=p, source_line=0) for n, p in (chunks or []))
    block = CacheBlockIR(ttl=ttl, items=items, source_line=0) if (items or ttl is not None) else None
    return CacheRenderContext(
        cache_block=block,
        subset=subset,
        prewarm=True,
        unresolved_batch_prompt=unresolved_batch_prompt,
        batch_alias=batch_alias,
    )


def test_prewarm_only_strip_records_prewarm_disabled_reason_and_emits_prewarm_id(
    mock_llm_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pure prewarm-channel strip — no declared cache, only auto-batch-prefix.

    Mutation contract: reverting ``_strip_below_min_cache_markers`` to drop
    per-channel tracking causes ``prewarm_disabled_reason`` to be None and
    ``cache_skipped_reason`` to be ``'below_min'``, failing assertions 1+2.
    """
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=500)  # below Anthropic 1024

    node = LLMNode()
    node.node_id = "score"  # type: ignore[attr-defined]
    node.set_params({
        "prompt": "Score this:\n\nhello world",
        "model": ANTHROPIC_1024,
    })
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score",
        _ctx_prewarm_batch(
            unresolved_batch_prompt="Score this:\n\n${item.text}",
            batch_alias="item",
        ),
    )

    node.run(shared)

    assert shared["llm_usage"]["prewarm_disabled_reason"] == "below_min"
    assert shared["llm_usage"]["cache_skipped_reason"] is None

    warning = shared["__warnings__"]["score"]
    assert warning.id == "cache.prewarm-disabled-below-min"
    assert warning.context["alias"] == "item"
    assert warning.context["cacheable_tokens"] == 500
    assert warning.context["min_tokens"] == 1024

    sent_user_blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert sent_user_blocks is not None
    assert all("cache_control" not in block for block in sent_user_blocks), (
        f"expected prewarm marker stripped; got: {sent_user_blocks}"
    )


def test_combined_declared_and_prewarm_strip_records_declared_reason_only(
    mock_llm_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Combined strip — declared chunk + prewarm batch, both stripped.

    Mutation contract: introducing an OR branch that also sets
    ``prewarm_disabled_reason`` in the combined case overwrites the declared
    warning in ``__warnings__[node_id]``, failing assertion 3.
    """
    mock_llm_client.set_response("*", None, "ok")
    _stub_token_counter(monkeypatch, tokens=300)  # well below Anthropic 1024

    node = LLMNode()
    node.node_id = "score"  # type: ignore[attr-defined]
    node.set_params({
        "prompt": "Score this:\n\nhello world",
        "model": ANTHROPIC_1024,
    })
    shared: dict[str, Any] = {"rubric": "be brief"}
    _install_prompt_cache(
        shared,
        "score",
        _ctx_prewarm_batch(
            chunks=[("rubric", "Rubric:\n")],
            subset=("rubric",),
            unresolved_batch_prompt="Score this:\n\n${item.text}",
            batch_alias="item",
        ),
    )

    node.run(shared)

    assert shared["llm_usage"]["cache_skipped_reason"] == "below_min"
    assert shared["llm_usage"]["prewarm_disabled_reason"] is None

    warning = shared["__warnings__"]["score"]
    assert warning.id == "cache.below-min-rendered"


def test_strip_result_dataclass_carries_per_channel_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct unit test on ``_strip_below_min_cache_markers``.

    Asserts the per-channel ``CacheStripResult`` shape:
      - declared-only strip → declared set, prewarm None
      - prewarm-only strip → declared None, prewarm set
      - combined → both set, declared <= prewarm (cumulative monotonicity)
      - no strip → None return
    """
    _stub_token_counter(monkeypatch, tokens=100)  # under Anthropic 1024

    # Declared-only
    system_blocks: list[dict[str, Any]] = [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]
    result = llm_module._strip_below_min_cache_markers(
        system_blocks=system_blocks,
        user_message_blocks=None,
        model=ANTHROPIC_1024,
    )
    assert result is not None
    assert result.declared_measured_tokens == 100
    assert result.prewarm_measured_tokens is None

    # Prewarm-only
    user_blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "y"},
    ]
    result = llm_module._strip_below_min_cache_markers(
        system_blocks=None,
        user_message_blocks=user_blocks,
        model=ANTHROPIC_1024,
    )
    assert result is not None
    assert result.declared_measured_tokens is None
    assert result.prewarm_measured_tokens == 100

    # Combined
    system_blocks = [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]
    user_blocks = [
        {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "y"},
    ]
    result = llm_module._strip_below_min_cache_markers(
        system_blocks=system_blocks,
        user_message_blocks=user_blocks,
        model=ANTHROPIC_1024,
    )
    assert result is not None
    assert result.declared_measured_tokens == 100
    assert result.prewarm_measured_tokens == 200
    assert result.declared_measured_tokens <= result.prewarm_measured_tokens

    # No strip (above threshold)
    _stub_token_counter(monkeypatch, tokens=5000)
    system_blocks = [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]
    result = llm_module._strip_below_min_cache_markers(
        system_blocks=system_blocks,
        user_message_blocks=None,
        model=ANTHROPIC_1024,
    )
    assert result is None


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
    _install_prompt_cache(shared, "n", _ctx(chunks=[("concept", "")], subset=("concept",)))
    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert all("cache_control" not in b for b in sent)
    warning = shared["__warnings__"]["n"]
    assert warning.context["cacheable_tokens"] == 1000  # 4000 // 4


# --- Multi-marker warning-suppression (Anthropic) --------------------------


class TestStripBelowMinSuppression:
    """Verify ``cache.below-min-rendered`` only fires when ALL markers in a
    channel were stripped (true caching failure), not when some sub-markers
    couldn't activate but caching is working via the terminal marker.

    Locks the multi-marker UX hygiene contract: today's single-marker
    rarely tripped this warning; multi-marker placement makes it common
    that EARLY markers are below threshold while the terminal marker
    survives — that's working caching, not failed caching.
    """

    def test_warning_when_all_markers_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Single terminal marker below threshold → all-stripped → warning."""
        _stub_token_counter(monkeypatch, tokens=100)  # under Anthropic 1024
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]
        result = llm_module._strip_below_min_cache_markers(
            system_blocks=system_blocks,
            user_message_blocks=None,
            model=ANTHROPIC_1024,
        )
        assert result is not None
        assert result.declared_measured_tokens == 100
        assert system_blocks[0].get("cache_control") is None

    def test_no_warning_when_terminal_survives_but_early_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """4 markers, early below threshold, terminal above → strip early,
        suppress warning (caching IS working via the terminal marker).

        Per-block tokens 500 each (cumulative 500/1000/1500/2000). Threshold
        1024. Block 0 (cum=500) and block 1 (cum=1000) get stripped. Block 2
        (cum=1500) and block 3 (cum=2000) survive. Declared channel still has
        surviving markers → no warning.
        """
        _stub_token_counter(monkeypatch, tokens=500)
        system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "y", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "z", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "w", "cache_control": {"type": "ephemeral"}},
        ]
        result = llm_module._strip_below_min_cache_markers(
            system_blocks=system_blocks,
            user_message_blocks=None,
            model=ANTHROPIC_1024,
        )
        # Early markers stripped, terminal survives.
        assert "cache_control" not in system_blocks[0]
        assert "cache_control" not in system_blocks[1]
        assert "cache_control" in system_blocks[2]
        assert "cache_control" in system_blocks[3]
        # Warning suppressed for declared channel.
        assert result is None

    def test_no_warning_when_no_markers_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All markers above threshold → nothing stripped → no warning."""
        _stub_token_counter(monkeypatch, tokens=5000)
        system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "y", "cache_control": {"type": "ephemeral"}},
        ]
        result = llm_module._strip_below_min_cache_markers(
            system_blocks=system_blocks,
            user_message_blocks=None,
            model=ANTHROPIC_1024,
        )
        assert result is None
        assert "cache_control" in system_blocks[0]
        assert "cache_control" in system_blocks[1]

    def test_prewarm_channel_suppresses_when_any_marker_survives(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multi-marker prewarm channel: early below threshold, terminal above.
        Strip the early marker, but suppress the warning because a marker
        survives in the channel.

        Cross-channel cumulative measurement makes "declared survives +
        prewarm stripped" structurally rare (once declared pushes past
        threshold, no later prewarm marker strips). This test covers the
        same suppression rule on prewarm-only configurations.
        """

        def _by_text(text: str, _model: str) -> int:
            return 5000 if text == "BIG" else 100

        monkeypatch.setattr(llm_module, "_count_text_tokens", _by_text)
        user_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": "tiny", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "BIG", "cache_control": {"type": "ephemeral"}},
        ]
        result = llm_module._strip_below_min_cache_markers(
            system_blocks=None,
            user_message_blocks=user_blocks,
            model=ANTHROPIC_1024,
        )
        assert "cache_control" not in user_blocks[0]
        assert "cache_control" in user_blocks[1]
        assert result is None

    def test_cross_channel_cumulative_prewarm_marker_survives_via_system_accumulation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Token accounting is cross-channel cumulative — a prewarm marker
        can survive purely because of the system_blocks accumulation that
        preceded it.

        Setup: 3 declared markers at 400 tokens each (cumulative 400/800/1200,
        threshold 1024 → declared 0 stripped, declared 1 stripped, declared 2
        survives) followed by a prewarm marker on a 50-token block
        (cumulative-through-prewarm = 1250, survives because the prewarm
        block extends the already-above-threshold accumulation).

        Expected: declared channel has 1 survivor (terminal) → declared
        warning suppressed. Prewarm channel has 1 survivor → prewarm warning
        suppressed. Final ``result`` is None. Locks the cross-channel
        cumulative + per-channel suppression asymmetry called out in
        ``_strip_below_min_cache_markers`` docstring.
        """

        def _by_text(_text: str, _model: str) -> int:
            return 50 if _text == "tiny-prewarm" else 400

        monkeypatch.setattr(llm_module, "_count_text_tokens", _by_text)
        system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": "decl-0", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "decl-1", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "decl-2", "cache_control": {"type": "ephemeral"}},
        ]
        user_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": "tiny-prewarm", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "suffix"},
        ]
        result = llm_module._strip_below_min_cache_markers(
            system_blocks=system_blocks,
            user_message_blocks=user_blocks,
            model=ANTHROPIC_1024,
        )
        # Declared: 0,1 stripped (cum 400, 800 < 1024); 2 survives (cum 1200).
        assert "cache_control" not in system_blocks[0]
        assert "cache_control" not in system_blocks[1]
        assert "cache_control" in system_blocks[2]
        # Prewarm marker survives — cumulative is 1250 by the time it's
        # checked, only because system_blocks already brought us past 1024.
        assert "cache_control" in user_blocks[0]
        # Both channels have surviving markers → no warning.
        assert result is None
