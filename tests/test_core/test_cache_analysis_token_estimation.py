"""F1.2 — token-estimation tier order (trace → memo → estimator → heuristic)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from pflow.core.cache_analysis.context import AnalysisContext
from pflow.core.cache_analysis.token_estimation import (
    _find_llm_event,
    estimate_cacheable_tokens,
    estimate_tokens,
    tokenize_prompt_region,
    tokenize_prompt_region_lower_bound,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeMemoCache:
    """Minimal stand-in for MemoizationCache.get_latest_for_node."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._payload = payload

    def get_latest_for_node(
        self, node_id: str, *, workflow_path: str | None = None
    ) -> tuple[dict[str, Any], float] | None:
        if self._payload is None:
            return None
        import time

        return (self._payload, time.time())


def _trace_with_node(node_id: str, input_tokens: int) -> dict[str, Any]:
    """Build a synthetic trace dict shaped like what
    ``runtime/workflow_trace.WorkflowTraceCollector.save_to_file`` writes.

    The top-level events key is ``"nodes"`` — NOT ``"events"``. Earlier
    versions of this helper used ``"events"``, which made ALL `estimate_tokens`
    tests pass while production tier-1 trace lookups silently failed (the
    Pitfall #19 anti-pattern from ``tests/CLAUDE.md``: synthetic fixtures
    matching a buggy reader rather than production shape).
    """
    return {
        "format_version": "2.1.0",
        "nodes": [
            {
                "node_id": node_id,
                "llm_call": {"input_tokens": input_tokens},
            }
        ],
    }


def _analysis_ctx(parameters: dict[str, Any]) -> AnalysisContext:
    return AnalysisContext.build(
        workflow_ir={
            "inputs": {name: {"type": "string"} for name in parameters},
            "nodes": [],
            "edges": [],
        },
        parameters=parameters,
        workflow_path="/abs/token-test.pflow.md",
    )


# ---------------------------------------------------------------------------
# Tier ordering — DD#34 / DD#31
# ---------------------------------------------------------------------------


def test_trace_wins_when_both_trace_and_memo_present() -> None:
    """Catches tier-inversion bugs: trace must win when both sources exist."""
    trace = _trace_with_node("X", input_tokens=4000)
    memo = _FakeMemoCache({"llm_usage": {"input_tokens": 999}})
    count, source = estimate_tokens("claude-sonnet-4-5", "irrelevant", trace=trace, memo_cache=memo, node_id="X")
    assert source == "trace"
    assert count == 4000


def test_memo_wins_when_no_trace_match() -> None:
    """When trace ABSENT, memo present → source = memo."""
    memo = _FakeMemoCache({"llm_usage": {"input_tokens": 2500}})
    count, source = estimate_tokens("claude-sonnet-4-5", "hello world", memo_cache=memo, node_id="X")
    assert source == "memo"
    assert count == 2500


def test_estimator_wins_when_no_trace_no_memo() -> None:
    """token_counter is the next tier."""
    count, source = estimate_tokens("claude-sonnet-4-5", "hello world test")
    assert source == "estimator"
    assert count > 0


def test_heuristic_when_text_is_none_and_warning_emitted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """text=None must NOT crash — falls through to heuristic with logger.warning
    (review-silent-failures W2: a model-name typo deserves visibility)."""
    caplog.set_level(logging.WARNING, logger="pflow.core.cache_analysis.token_estimation")
    count, source = estimate_tokens("claude-sonnet-4-5", None)  # type: ignore[arg-type]
    assert source == "heuristic"
    assert count == 0  # heuristic on None falls back to len("") // 4
    assert any(rec.levelname == "WARNING" for rec in caplog.records)


def test_heuristic_for_empty_string() -> None:
    count, source = estimate_tokens("claude-sonnet-4-5", "")
    # Empty string passes through token_counter cleanly → 0, source = estimator.
    assert count == 0
    assert source in {"estimator", "heuristic"}


def test_unknown_model_falls_back_to_estimator_with_default_tokenizer() -> None:
    """LiteLLM's token_counter does NOT raise on unknown models — falls back to
    a default tokenizer. Verified empirically (progress-log §35).
    Source label is `estimator` (slightly inaccurate), not `heuristic`."""
    count, source = estimate_tokens("brand-new-future-model-2099", "hello world test")
    assert count > 0
    assert source == "estimator"


def test_heuristic_returns_chars_div_4_when_estimator_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If token_counter raises (future regression), fall through to heuristic."""

    def _boom(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("synthetic estimator failure")

    monkeypatch.setattr("litellm.token_counter", _boom)
    text = "x" * 100
    count, source = estimate_tokens("claude-sonnet-4-5", text)
    assert source == "heuristic"
    assert count == 25  # len(text) // 4


def test_trace_with_no_matching_event_falls_back_to_memo() -> None:
    """A trace that exists but doesn't carry a per-event entry for this node_id
    must NOT misroute as `trace` source."""
    trace = _trace_with_node("OTHER", input_tokens=4000)
    memo = _FakeMemoCache({"llm_usage": {"input_tokens": 2500}})
    count, source = estimate_tokens("claude-sonnet-4-5", "hello", trace=trace, memo_cache=memo, node_id="X")
    assert source == "memo"
    assert count == 2500


def test_memo_without_input_tokens_falls_through_to_estimator() -> None:
    """A memo entry that lacks llm_usage.input_tokens (e.g., a non-LLM node's
    output) must NOT be claimed as `memo` source."""
    memo = _FakeMemoCache({"some_other_field": "value"})  # no llm_usage
    count, source = estimate_tokens("claude-sonnet-4-5", "hello world", memo_cache=memo, node_id="X")
    assert source == "estimator"
    assert count > 0


# ---------------------------------------------------------------------------
# Production-shape regression — defends against Pitfall #19 reoccurring
# ---------------------------------------------------------------------------


@pytest.mark.trace_files
def test_tier_1_trace_works_with_real_collector_round_trip(tmp_path: Any, monkeypatch: Any) -> None:
    """Production-shape contract: a trace produced by ``WorkflowTraceCollector``
    and saved via ``save_to_file`` must be readable by ``estimate_tokens`` for
    tier-1 ``trace`` source.

    Earlier versions of ``_llm_call_field_from_trace`` read
    ``trace.get("events")`` while the collector writes the top-level events
    list under the key ``"nodes"``. ALL synthetic-fixture tests passed because
    they matched the buggy reader; production users got estimator/heuristic
    instead of trace tier silently. This is the Pitfall #19 anti-pattern from
    ``tests/CLAUDE.md``: every consumer that walks production data structures
    needs at least one test that drives a real producer end-to-end.
    """
    import json

    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    collector = WorkflowTraceCollector(
        workflow_name="test-roundtrip",
        workflow_path="/some/path/test.pflow.md",
    )
    collector.record_node_execution(
        node_id="emit",
        node_type="LLMNode",
        duration_ms=1.0,
        success=True,
        node_output={
            "response": "ok",
            "llm_usage": {
                "input_tokens": 1234,
                "output_tokens": 7,
                "model": "claude-haiku-4-5",
            },
        },
    )

    saved_path = collector.save_to_file()
    trace_data = json.loads(saved_path.read_text())

    # Sanity: the collector wrote the events under the canonical "nodes" key.
    assert "nodes" in trace_data, "Producer contract drifted — events key changed"
    assert len(trace_data["nodes"]) == 1
    assert trace_data["nodes"][0]["node_id"] == "emit"

    # Tier-1 reader finds the input_tokens via the production-shaped trace.
    count, source = estimate_tokens(
        "claude-haiku-4-5",
        "irrelevant-prompt",
        trace=trace_data,
        node_id="emit",
    )
    assert source == "trace", f"Tier-1 unreachable in production shape: source={source!r}"
    assert count == 1234


def test_memo_tier_reachable_via_default_construct_in_analyze(tmp_path: Any, monkeypatch: Any) -> None:
    """CR-1305 W3 regression: ``analyze()`` default-constructs ``memo_cache``
    from disk when the caller didn't supply one. Without this, ``data_source:
    "memo"`` was unreachable from CLI/MCP/dry-run entry points (none pass a
    ``MemoizationCache`` explicitly).

    Production-shape: seeds ``~/.pflow/cache/cache.db`` (under patched
    ``Path.home()``) with a real ``MemoizationCache.put`` call carrying
    ``llm_usage.input_tokens``. Calls ``analyze()`` WITHOUT a ``memo_cache``
    kwarg. The default-construct branch fires, finds the seeded entry, and
    the per-call row's ``data_source`` is ``"memo"``.

    Mutation-test thought: removing the ``if memo_cache is None: memo_cache =
    _default_memo_cache()`` assignment in ``analyze()`` causes ``data_source``
    to fall back to ``"estimator"`` (or ``"heuristic"`` for the unknown-model
    case) — this assertion catches it.
    """
    from pflow.core.cache_analysis.analyze import analyze
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/path/sample.pflow.md"
    node_id = "summarize"

    # Seed the cache at the same default location ``_default_memo_cache`` reads.
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    cache.put(
        cache_key="seeded-key-abc",
        node_id=node_id,
        workflow_path=workflow_path,
        action="default",
        output={
            "response": "previous response",
            "llm_usage": {"input_tokens": 8888, "output_tokens": 42, "model": "claude-haiku-4-5"},
        },
    )

    workflow_ir = {
        "nodes": [
            {
                "id": node_id,
                "type": "llm",
                "params": {"model": "claude-haiku-4-5", "prompt": "Summarize ${topic}"},
            }
        ],
        "edges": [],
    }

    # No memo_cache kwarg — default-construct path fires.
    analysis = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.data_source == "memo", (
        f"data_source must be 'memo' when default-construct found the seeded entry; "
        f"got {row.data_source!r}. Default-construct branch in analyze() may not be firing."
    )
    assert row.input_tokens_estimated == 8888


def test_memo_tier_falls_back_gracefully_when_cache_db_absent(tmp_path: Any, monkeypatch: Any) -> None:
    """Default-construct must NOT create ``cache.db`` as a side effect of an
    analyze invocation. Greenfield workflow + analyze → no memo tier (returns
    None), no SQLite file written.

    Locks the load-bearing read-only invariant: analyze is a pure function of
    the workflow + optional state; it never mutates disk.
    """
    from pflow.core.cache_analysis.analyze import analyze

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "nodes": [
            {
                "id": "x",
                "type": "llm",
                "params": {"model": "claude-haiku-4-5", "prompt": "hello"},
            }
        ],
        "edges": [],
    }

    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    assert not cache_db_path.exists(), "Pre-condition: cache.db must be absent"

    analysis = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert len(analysis.per_call) == 1
    # Falls back to estimator/heuristic — neither memo nor trace data available.
    assert analysis.per_call[0].data_source in {"estimator", "heuristic"}

    # Read-only invariant: analyze did NOT create cache.db.
    assert not cache_db_path.exists(), (
        "analyze() created cache.db as a side effect — read-only contract violated. "
        "_default_memo_cache must check existence BEFORE constructing MemoizationCache."
    )


# ---------------------------------------------------------------------------
# tokenize_prompt_region — honest unmeasurable prompt-slice tokenization
# ---------------------------------------------------------------------------


def test_tokenize_prompt_region_returns_zero_for_empty_region() -> None:
    """Behavior: empty prompt regions are measurable as zero tokens.

    History: batch-prefix scans can produce empty slices at template boundaries.
    Mutation contract: remove the early empty-region return; this test fails
    if an empty slice ever becomes unavailable or raises during resolution.
    """
    assert tokenize_prompt_region("", model="", ctx=_analysis_ctx({})) == 0


def test_tokenize_prompt_region_returns_int_when_no_refs() -> None:
    """Behavior: literal-only regions tokenize directly.

    History: literal-only catalog fixtures must remain byte-identical after the
    unresolved-ref fix. Mutation contract: force all regions through template
    resolution; this test fails if literal text loses its deterministic count.
    """
    assert tokenize_prompt_region("abcd efgh", model="", ctx=_analysis_ctx({})) == 2


def test_tokenize_prompt_region_returns_int_when_all_refs_resolve() -> None:
    """Behavior: resolved refs count the substituted bytes, not template bytes.

    History: this is the safe case that should keep producing numbers.
    Mutation contract: return None whenever a region contains ``${``; this test
    fails because fully resolvable input refs must remain measurable.
    """
    ctx = _analysis_ctx({"topic": "abcd efgh"})
    assert tokenize_prompt_region("Use ${topic}", model="", ctx=ctx) == 3


def test_tokenize_prompt_region_returns_none_when_any_ref_unresolved() -> None:
    """Behavior: any unresolved ref makes the whole region unmeasurable.

    History: counting literal ``${missing.ref}`` bytes fabricated tiny
    cacheable-token counts for large upstream values. Mutation contract: remove
    the post-resolution ``TEMPLATE_PATTERN.search`` guard; this test fails
    because the unresolved template literal tokenizes as a small int.
    """
    ctx = _analysis_ctx({"topic": "resolved"})
    assert tokenize_prompt_region("Use ${topic} and ${missing.ref}", model="", ctx=ctx) is None


def test_tokenize_prompt_region_handles_dict_valued_single_ref() -> None:
    """Behavior: non-string simple-template values serialize deterministically.

    History: cache chunks and prompt slices can resolve to structured values.
    Mutation contract: remove deterministic serialization for non-strings; this
    test fails because ``estimate_tokens`` cannot count a dict directly.
    """
    ctx = _analysis_ctx({"payload": {"b": 2, "a": 1}})
    assert tokenize_prompt_region("${payload}", model="", ctx=ctx) == 3


def test_tokenize_prompt_region_handles_coalesce_with_fallback() -> None:
    """Behavior: coalesce resolves to the present fallback operand.

    History: TemplateResolver's ``??`` semantics treat absent roots as skipped,
    which is measurable when a later operand exists. Mutation contract: treat
    every multi-operand template as unresolved; this test fails because
    ``${missing ?? fallback}`` should tokenize the fallback bytes.
    """
    ctx = _analysis_ctx({"fallback": "abcd efgh"})
    assert tokenize_prompt_region("${missing ?? fallback}", model="", ctx=ctx) == 2


def test_tokenize_prompt_region_handles_empty_model_string() -> None:
    """Behavior: heterogeneous-model rows with ``model == ""`` use heuristic counts.

    History: ``estimate_tokens("", text)`` returns ``(len(text)//4,
    "heuristic")``. Mutation contract: require a truthy model before counting;
    this test fails because empty-model rows still need deterministic integers
    when the region is otherwise measurable.
    """
    ctx = _analysis_ctx({"text": "abcdefgh"})
    assert tokenize_prompt_region("${text}", model="", ctx=ctx) == 2


def test_tokenize_prompt_region_returns_none_for_indirected_per_item_ref() -> None:
    """Behavior: node-local ``params.inputs`` aliases are not resolved here.

    History: PR #390 dealiasing belongs to prompt-ref classification, not this
    generic tokenizer helper. Mutation contract: fabricate a value for alias
    ``X`` from unrelated batch context; this test fails because the helper must
    stay conservative without node-local inputs.
    """
    ctx = _analysis_ctx({"item": {"field": "abcd efgh"}})
    assert tokenize_prompt_region("${X}", model="", ctx=ctx) is None


def test_tokenize_prompt_region_returns_none_when_resolved_value_contains_literal_template_bytes() -> None:
    """Behavior: resolved values that still look like templates are unmeasurable.

    History: code-node outputs can legitimately contain ``${...}`` text; the
    conservative analyzer must not mistake that for fully resolved prompt
    bytes. Mutation contract: remove the second template-pattern scan; this
    test fails because the literal-looking output would be counted as text.
    """
    ctx = _analysis_ctx({"text": "literal ${still.template}"})
    assert tokenize_prompt_region("${text}", model="", ctx=ctx) is None


# ---------------------------------------------------------------------------
# tokenize_prompt_region_lower_bound — advisory prompt-slice tokenization
# ---------------------------------------------------------------------------


def test_lower_bound_returns_zero_for_empty_region() -> None:
    """Behavior: empty cacheable regions have no measurable bytes.

    History: lower-bound advisories distinguish zero stable bytes from unknown
    stable bytes so prewarm-no-prefix and below-min diagnostics remain
    mutually exclusive. Mutation contract: route empty input through template
    resolution; this test fails if empty regions stop returning ``(0, ())``.
    """
    assert tokenize_prompt_region_lower_bound("", model="", ctx=_analysis_ctx({})) == (0, ())


def test_lower_bound_returns_int_when_no_refs() -> None:
    """Behavior: literal regions use the same tokenizer as the exact helper.

    History: literal-only batch prefixes should stay on the confident path.
    Mutation contract: synthesize unresolved metadata for literal text; this
    test fails because no refs exist to verify.
    """
    text = "abcd efgh"
    assert tokenize_prompt_region_lower_bound(text, model="", ctx=_analysis_ctx({})) == (
        estimate_tokens("", text)[0],
        (),
    )


def test_lower_bound_returns_int_and_empty_tuple_when_all_refs_resolve() -> None:
    """Behavior: fully resolved regions are measured exactly.

    History: the advisory must not compete with confident recommendations when
    the exact path can prove the prefix size. Mutation contract: collect refs
    before resolution as unresolved; this test fails because ``${topic}``
    remains in the unresolved tuple.
    """
    ctx = _analysis_ctx({"topic": "abcd efgh"})
    assert tokenize_prompt_region_lower_bound("Use ${topic}", model="", ctx=ctx) == (3, ())


def test_lower_bound_strips_unresolved_refs_and_returns_them() -> None:
    """Behavior: unresolved placeholders count as zero bytes.

    History: score-choruses has stable prompt spans plus upstream refs the
    greenfield analyzer cannot see. Mutation contract: count literal
    ``${missing.ref}`` bytes; this test fails because the measurable count
    exceeds the stripped-text count.
    """
    ctx = _analysis_ctx({"known": "KKKK"})
    measured, unresolved = tokenize_prompt_region_lower_bound(
        "AAAA ${known} BBBB ${missing.ref} CCCC",
        model="",
        ctx=ctx,
    )
    assert measured == estimate_tokens("", "AAAA KKKK BBBB  CCCC")[0]
    assert unresolved == ("missing.ref",)


def test_lower_bound_returns_zero_when_resolution_has_user_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavior: expected resolver data errors produce a conservative zero.

    History: lower-bound numbers must never be inflated by partial work after a
    template resolver data failure. Mutation contract: fall back to tokenizing
    the raw region on ValueError; this test fails because measurable tokens
    become positive instead of zero.
    """
    from pflow.runtime.template_resolver import TemplateResolver

    def _boom(*_args: Any, **_kwargs: Any) -> str:
        raise ValueError("synthetic resolver data failure")

    monkeypatch.setattr(TemplateResolver, "resolve_template", staticmethod(_boom))
    assert tokenize_prompt_region_lower_bound("Use ${known} and ${missing}", model="", ctx=_analysis_ctx({})) == (
        0,
        ("known", "missing"),
    )


def test_prompt_region_tokenizers_do_not_swallow_programming_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unexpected resolver failures should stay visible to developers.

    The analyzer degrades on normal resolution/data errors, but broad
    ``except Exception`` hid programming bugs as "unmeasurable" cache regions.
    Mutation contract: restore a bare Exception catch in either helper; this
    test fails because RuntimeError no longer propagates.
    """
    from pflow.runtime.template_resolver import TemplateResolver

    def _boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("synthetic programming failure")

    monkeypatch.setattr(TemplateResolver, "resolve_template", staticmethod(_boom))
    ctx = _analysis_ctx({})

    with pytest.raises(RuntimeError, match="synthetic programming failure"):
        tokenize_prompt_region("Use ${known}", model="", ctx=ctx)
    with pytest.raises(RuntimeError, match="synthetic programming failure"):
        tokenize_prompt_region_lower_bound("Use ${known}", model="", ctx=ctx)


def test_lower_bound_handles_dict_valued_single_ref() -> None:
    """Behavior: non-string resolved values serialize before counting.

    History: exact tokenization already serializes dict-valued simple refs; the
    lower-bound sibling must preserve that contract. Mutation contract: require
    resolved values to be strings; this test fails because dict refs become
    unresolved instead of measurable.
    """
    ctx = _analysis_ctx({"payload": {"b": 2, "a": 1}})
    assert tokenize_prompt_region_lower_bound("${payload}", model="", ctx=ctx) == (3, ())


def test_lower_bound_handles_coalesce_with_fallback() -> None:
    """Behavior: coalesce fallbacks resolve through the shared-store builder.

    History: fallback refs are real prompt bytes when available. Mutation
    contract: build the synthetic store from only the first coalesce operand;
    this test fails because ``${missing ?? fallback}`` remains unresolved.
    """
    ctx = _analysis_ctx({"fallback": "abcd efgh"})
    assert tokenize_prompt_region_lower_bound("${missing ?? fallback}", model="", ctx=ctx) == (2, ())


def test_lower_bound_handles_indirected_per_item_ref() -> None:
    """Behavior: unresolved indirect aliases are listed, not guessed.

    History: this helper intentionally does not mirror batch-alias dealiasing;
    it only reports what the analysis context can resolve. Mutation contract:
    silently drop unresolved refs; this test fails because the verification
    target disappears.
    """
    measured, unresolved = tokenize_prompt_region_lower_bound("Intro ${X}", model="", ctx=_analysis_ctx({}))
    assert measured == estimate_tokens("", "Intro ")[0]
    assert unresolved == ("X",)


def test_lower_bound_counts_literal_spans_between_unresolved_refs() -> None:
    """Behavior: all measurable literal spans survive stripping.

    History: lower-bound prewarm advice should not collapse to zero merely
    because more than one upstream ref is unavailable. Mutation contract:
    return zero whenever any unresolved ref remains; this test fails because
    literal A/B/C spans are measurable and should count.
    """
    region = "literal A ${miss1} literal B ${miss2} literal C"
    measured, unresolved = tokenize_prompt_region_lower_bound(region, model="", ctx=_analysis_ctx({}))
    assert measured == estimate_tokens("", "literal A  literal B  literal C")[0]
    assert unresolved == ("miss1", "miss2")


# ---------------------------------------------------------------------------
# estimate_cacheable_tokens — 4-tier hierarchy (Task 159 unified function)
# ---------------------------------------------------------------------------


def _cache_trace_event(creation: int, read: int) -> dict[str, Any]:
    """Build a trace event payload with cache_creation + cache_read fields."""
    return {
        "input_tokens": creation + read,
        "cache_creation_input_tokens": creation,
        "cache_read_input_tokens": read,
    }


def test_cacheable_tier_1_trace_returns_creation_plus_read_with_asymmetric_values() -> None:
    """Tier 1: declared subset + trace event with asymmetric creation/read.

    Asymmetric values defend against ``creation + read`` → ``creation`` alone
    mutation. Reversed asymmetry (creation=599, read=1000) also returns the
    sum — defends against returning either field alone.
    """
    event = _cache_trace_event(creation=1000, read=599)
    tokens, source = estimate_cacheable_tokens(
        declared_subset=["a"],
        candidate_subset=None,
        trace_event=event,
        memo_cache=None,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="",
    )
    assert source == "trace"
    assert tokens == 1599

    reversed_event = _cache_trace_event(creation=599, read=1000)
    tokens2, source2 = estimate_cacheable_tokens(
        declared_subset=["a"],
        candidate_subset=None,
        trace_event=reversed_event,
        memo_cache=None,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="",
    )
    assert source2 == "trace"
    assert tokens2 == 1599


def test_cacheable_tier_1_falls_through_when_zero() -> None:
    """Declared + trace event with creation=0, read=0 (cache declared but
    didn't fire — sub-threshold etc.) falls through. With no memo data,
    Tier 2 fails too → returns ``(None, "unavailable")``.

    Defends: the gate must require ``> 0``, not ``>= 0``; ``>= 0`` would
    return ``(0, "trace")`` and contradict trace evidence.
    Also defends: no fabricated heuristic when memo also absent —
    honest unmeasurable propagates.
    """
    event = _cache_trace_event(creation=0, read=0)
    tokens, source = estimate_cacheable_tokens(
        declared_subset=["a"],
        candidate_subset=None,
        trace_event=event,
        memo_cache=None,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="x" * 1000,
    )
    assert source == "unavailable"
    assert tokens is None


def test_cacheable_tier_2_memo_sums_resolved_chunk_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier 2: declared subset + memo data → sum of per-chunk tokens.

    Defends: per-chunk tokens must SUM, not first-only; first-only
    returns 100 and fails.
    """

    def _fake_estimate(ref: str, **_kw: Any) -> int | None:
        return {"a": 100, "b": 200}.get(ref)

    monkeypatch.setattr(
        "pflow.core.cache_analysis.token_estimation._estimate_ref_tokens",
        _fake_estimate,
    )
    memo = _FakeMemoCache({"some": "data"})
    tokens, source = estimate_cacheable_tokens(
        declared_subset=["a", "b"],
        candidate_subset=None,
        trace_event=None,
        memo_cache=memo,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="",
    )
    assert source == "memo"
    assert tokens == 300


def test_cacheable_tier_2_for_declared_partial_memo_falls_through_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared subset + partial memo (one chunk has no data) → falls
    through to Tier 3 (unavailable). Honest unmeasurable: we can't
    sum partial chunks without misrepresenting total cache content.
    """

    def _fake_estimate(ref: str, **_kw: Any) -> int | None:
        return 100 if ref == "a" else None  # b has no data

    monkeypatch.setattr(
        "pflow.core.cache_analysis.token_estimation._estimate_ref_tokens",
        _fake_estimate,
    )
    memo = _FakeMemoCache({"some": "data"})
    tokens, source = estimate_cacheable_tokens(
        declared_subset=["a", "b"],
        candidate_subset=None,
        trace_event=None,
        memo_cache=memo,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="x" * 1000,
    )
    assert source == "unavailable"
    assert tokens is None


def test_cacheable_tier_3_unavailable_for_declared_no_history() -> None:
    """Tier 3: declared subset + no trace + no memo + no parameters →
    ``(None, "unavailable")``. Honest unmeasurable — no fabricated
    heuristic on prompt body (cache content is prepended, not a
    subset of prompt body).
    """
    tokens, source = estimate_cacheable_tokens(
        declared_subset=["a"],
        candidate_subset=None,
        trace_event=None,
        memo_cache=None,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="X" * 1000,
    )
    assert source == "unavailable"
    assert tokens is None


def test_cacheable_unavailable_for_candidate_only_no_data() -> None:
    """Candidate (no declared) + no memo → Tier 3 unavailable.

    Defends: candidate-only path must not fabricate a number.
    """
    tokens, source = estimate_cacheable_tokens(
        declared_subset=None,
        candidate_subset=["a"],
        trace_event=None,
        memo_cache=None,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="X" * 1000,
    )
    assert source == "unavailable"
    assert tokens is None


def test_cacheable_tier_4_returns_none_for_pure_greenfield() -> None:
    """Nothing declared, nothing candidate → (None, "unavailable")."""
    tokens, source = estimate_cacheable_tokens(
        declared_subset=None,
        candidate_subset=None,
        trace_event=None,
        memo_cache=None,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="X" * 1000,
    )
    assert source == "unavailable"
    assert tokens is None


def test_cacheable_tier_2_short_circuits_when_model_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heterogeneous batch (``model=""``) + declared + memo populated →
    Tier 2 short-circuits on empty model gate, falls through to Tier 3
    (unavailable). Verifies the gate ``if chunks and ... and model:``.
    """

    def _fake_estimate(ref: str, **_kw: Any) -> int | None:
        return 100  # would return data if called — but Tier 2 short-circuits

    monkeypatch.setattr(
        "pflow.core.cache_analysis.token_estimation._estimate_ref_tokens",
        _fake_estimate,
    )
    memo = _FakeMemoCache({"some": "data"})
    tokens, source = estimate_cacheable_tokens(
        declared_subset=["a"],
        candidate_subset=None,
        trace_event=None,
        memo_cache=memo,
        model="",
        workflow_path=None,
        prompt="X" * 1000,
    )
    assert source == "unavailable"  # Tier 3 fires (was: estimator)
    assert tokens is None


def test_cacheable_tier_1_does_not_fire_without_declared() -> None:
    """Candidate set + trace populated → Tier 1 N/A (only fires for declared).

    Defends: the ``declared_subset and`` precondition must hold; dropping
    it lets Tier 1 fire for candidate-only and breaks this assertion.
    """
    event = _cache_trace_event(creation=1000, read=599)
    tokens, source = estimate_cacheable_tokens(
        declared_subset=None,
        candidate_subset=["a"],
        trace_event=event,
        memo_cache=None,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="",
    )
    assert source != "trace"  # Tier 1 doesn't fire
    # Falls to Tier 2 (no memo) → Tier 4 unavailable.
    assert source == "unavailable"
    assert tokens is None


def test_cacheable_tier_2_partial_memo_position_independent_falls_through_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 chunks, mid-list chunk (position 2) is None. Returns ``(None,
    "unavailable")`` even though chunks 1 and 3 have data. Verifies the
    early-exit isn't dependent on chunk position, and that partial
    resolution becomes honest unmeasurable rather than a fabricated sum.
    """

    def _fake_estimate(ref: str, **_kw: Any) -> int | None:
        return {"a": 100, "b": None, "c": 200}.get(ref)

    monkeypatch.setattr(
        "pflow.core.cache_analysis.token_estimation._estimate_ref_tokens",
        _fake_estimate,
    )
    memo = _FakeMemoCache({"some": "data"})
    tokens, source = estimate_cacheable_tokens(
        declared_subset=["a", "b", "c"],
        candidate_subset=None,
        trace_event=None,
        memo_cache=memo,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="X" * 1000,
    )
    assert source == "unavailable"
    assert tokens is None


def test_cacheable_tier_2_for_candidate_with_full_memo_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    """Candidate + full memo (no declared) → Tier 2 memo fires.

    Closes the unit-test gap: existing tests cover declared+memo and
    candidate+no-memo but not candidate+memo. Mutation: break the
    ``declared_subset or candidate_subset`` precedence → candidate path
    returns None.
    """

    def _fake_estimate(ref: str, **_kw: Any) -> int | None:
        return {"a": 50, "b": 75}.get(ref)

    monkeypatch.setattr(
        "pflow.core.cache_analysis.token_estimation._estimate_ref_tokens",
        _fake_estimate,
    )
    memo = _FakeMemoCache({"some": "data"})
    tokens, source = estimate_cacheable_tokens(
        declared_subset=None,
        candidate_subset=["a", "b"],
        trace_event=None,
        memo_cache=memo,
        model="claude-sonnet-4-5",
        workflow_path=None,
        prompt="",
    )
    assert source == "memo"
    assert tokens == 125


def test_find_llm_event_returns_first_matching_event() -> None:
    """Trace with two ``llm_call`` events for same node_id → returns first.
    Locks deterministic event selection (cf. needs-decision item B about
    batch averaging).
    """
    trace: dict[str, Any] = {
        "nodes": [
            {"node_id": "X", "llm_call": {"input_tokens": 100, "marker": "first"}},
            {"node_id": "X", "llm_call": {"input_tokens": 200, "marker": "second"}},
            {"node_id": "Y", "llm_call": {"input_tokens": 999}},
        ],
    }
    event = _find_llm_event(trace, "X")
    assert event is not None
    assert event.get("marker") == "first"
    assert event.get("input_tokens") == 100


# ---------------------------------------------------------------------------
# Track B — Tier-2 parameters fallback for workflow-input refs.
#
# Before the fix, workflow inputs referenced in cache chunks (``${context}``)
# could only be projected from memo data — but no node has the ID
# ``context`` so memo lookup always returned None and projections fell to
# Tier 4 unavailable. With the AnalysisContext threading parameters,
# greenfield projections light up when the agent passes ``--inputs``.
# ---------------------------------------------------------------------------


def test_estimate_cacheable_tokens_uses_parameters_for_workflow_input_ref() -> None:
    """Test 2 — Greenfield Tier-2 parameters fallback.

    Defends: the ``ctx is not None`` clause in ``estimate_cacheable_tokens``
    Tier 2 dispatch must light up the parameters-tier projection;
    otherwise cacheable falls through to Tier 3 / 4 unavailable.
    """
    from pflow.core.cache_analysis.context import AnalysisContext
    from pflow.core.cache_analysis.token_estimation import estimate_cacheable_tokens

    workflow_ir = {"inputs": {"context": {"type": "string"}}}
    ctx = AnalysisContext.build(
        workflow_ir=workflow_ir,
        parameters={"context": "X" * 5000},
    )
    tokens, source = estimate_cacheable_tokens(
        declared_subset=None,
        candidate_subset=["context"],
        trace_event=None,
        memo_cache=None,
        model="anthropic/claude-sonnet-4-5",
        workflow_path=None,
        prompt="some prompt",
        ctx=ctx,
    )
    assert tokens is not None
    assert tokens > 100  # Real tokenization of 5000-char string.
    assert source == "parameters"


def test_resolve_ref_value_workflow_input_wins_over_memo() -> None:
    """Test 12 — Workflow-input parameters wins over memo (Track B asymmetry).

    The agent's ``--inputs`` represent their CURRENT question; memo from a
    prior run with different inputs MUST NOT override.
    """
    from pflow.core.cache_analysis.context import AnalysisContext

    class FakeMemo:
        def get_latest_for_node(self, node_id, *, workflow_path=None):  # type: ignore[no-untyped-def]
            if node_id == "context":
                return ({"context": "OLD memo value"}, 0.0)
            return None

    workflow_ir = {"inputs": {"context": {"type": "string"}}}
    ctx = AnalysisContext.build(
        workflow_ir=workflow_ir,
        parameters={"context": "NEW question from agent"},
        memo_cache=FakeMemo(),
    )
    value = ctx.resolve_ref_value("context")
    assert value == "NEW question from agent"


def test_resolve_ref_value_returns_none_for_empty_string() -> None:
    """Test 9 — Empty-string parameter (silent-failures defense).

    Empty values would collapse to ~0 tokens through tokenization, falsely
    signaling "we have a real value." Returning None pushes the caller to
    Tier-4 unavailable.
    """
    from pflow.core.cache_analysis.context import AnalysisContext

    workflow_ir = {"inputs": {"context": {"type": "string"}}}
    ctx = AnalysisContext.build(
        workflow_ir=workflow_ir,
        parameters={"context": ""},
    )
    assert ctx.resolve_ref_value("context") is None


# ---------------------------------------------------------------------------
# Track C — Resolve prompt template before tokenization.
#
# Greenfield ``estimate_tokens`` previously tokenized the literal template
# (``${context}`` → ~5 chars). Track C resolves against parameters/memo
# before tokenization so the count reflects the real prompt size.
# ---------------------------------------------------------------------------


def test_estimate_tokens_marks_partial_when_unresolved_refs_present() -> None:
    """Test 10 — Partial-resolution detection (silent-failures defense).

    When the caller passes ``has_unresolved_refs=True`` (some ``${...}``
    couldn't be substituted), the source label shifts to
    ``"estimator-partial"`` so agents see the lower confidence.
    """
    from pflow.core.cache_analysis.token_estimation import estimate_tokens

    tokens, source = estimate_tokens(
        "anthropic/claude-sonnet-4-5",
        "Some text with ${unresolved} ref left in it.",
        has_unresolved_refs=True,
    )
    assert tokens > 0
    assert source == "estimator-partial"

    _tokens2, source2 = estimate_tokens(
        "anthropic/claude-sonnet-4-5",
        "Same text but fully resolved.",
        has_unresolved_refs=False,
    )
    assert source2 == "estimator"
