# Task 159 F-04 Fix — Delete Tier 3 Heuristic in `estimate_cacheable_tokens`

## Context

**Problem**: `pflow analyze-cache` produces false-positive `cache.below-min-tokens` warnings on greenfield workflows. When a `## Cache` chunk references a value not yet computable (a node-output reference like `${produce.response}` with no memo data, OR a workflow-input reference like `${article}` with no `--inputs` provided), the analyzer falls back to a Tier 3 heuristic at `src/pflow/core/cache_analysis/token_estimation.py:174-176` that fabricates a token count from `len(prompt) * 75 // 400`.

This heuristic is **conceptually wrong for declared `prompt_cache:` chunks**. pflow renders cache chunks as **prepended content blocks**, not as substrings of the prompt body. A 75%-of-prompt-body estimate has no relationship to the actual cache content size when the prompt body is small (e.g., `Summarize.`) and the cache is the bulk content.

**Concrete reproduction** (`baseline/14-pitfall-19-defenses/01-dotted-path-chunk/`):
- Workflow: `consume-1` declares `prompt_cache: [produce.response]`, prompt body is `Summarize.`
- Greenfield analyze-cache reports: `cacheable_tokens_estimated: 1, cacheable_data_source: "estimator"`
- Warning fires: `consume-1: declared cache content is ~1 tokens, below ... minimum of 1024`
- Reality: `produce.response` will be hundreds-to-thousands of tokens once `produce` runs.

**Agent UX impact**: Agents read the warning, consolidate chunks unnecessarily, then discover after the first run that their changes were undone. pflow's own canonical example (`examples/core/prompt-caching.pflow.md`) ships a preamble apologizing for the bug.

**Decision**: Delete the Tier 3 heuristic. Honest unmeasurable propagates through existing primitives — the `?` rendering already exists, `_row_has_real_data` already keeps rows visible when `declared_prompt_cache` is non-empty, and the runtime-tier observed warning at `LLMNode.post()` catches real failures after first run **when the provider exposes cache telemetry** (the runtime path gates on `llm_usage["has_cache_telemetry"]`; providers that omit cache fields entirely fall outside both layers — see Risks).

**Top-10% pattern**: Don't fabricate values to keep warnings firing. rustc/mypy/clippy report what they know and stay silent when they don't have data. Documentation (`pflow guide caching`, the per-call `?` affordance) explains the data model — analyze-cache output should not.

**Out of scope** (deliberately deferred — see end of plan):
- Per-cause Notes lines explaining WHY a chunk is unmeasurable (theorized, not observed)
- Fixing `_tokenize_declared_cache_chunks`'s parallel silent 0-skip in `input_tokens` (related but separate; smaller magnitude)

---

## Production Code Changes

### Change 1 — Delete the Tier 3 heuristic

**File**: `src/pflow/core/cache_analysis/token_estimation.py`

**Delete lines 174-176** (the entire Tier 3 block):

```python
# Tier 3: estimator (declared subset only — heuristic; preserves below-min-tokens).
if declared_subset:
    return (max(0, len(prompt) * 75 // 400), "estimator")
```

After deletion, the function flows directly from Tier 2 to Tier 4 (renamed to Tier 3 in docstring).

### Change 2 — Update `estimate_cacheable_tokens` docstring

**File**: `src/pflow/core/cache_analysis/token_estimation.py:120-148`

**Replace the existing docstring** (lines 130-148) with:

```python
    """Return ``(cacheable_tokens, source)`` using highest-fidelity available data.

    Sources: ``"trace"``, ``"memo"``, ``"parameters"``, ``"unavailable"``.

    Tier order:

    - Tier 1 (``"trace"``): declared subset + trace event with
      ``cache_creation+cache_read > 0``. Returns the sum.
    - Tier 2 (``"memo"`` / ``"parameters"``): all chunks resolve to real
      values via memo or workflow parameters. Returns the sum.
    - Tier 3 (``"unavailable"``): nothing else is honestly measurable.
      Returns ``(None, "unavailable")``.

    Tier 1 fall-through: when declared subset has trace_event with
    ``cache_creation+cache_read == 0`` (cache declared but didn't fire —
    sub-threshold etc.), fall through to Tier 2 to compute "what was
    attempted." If Tier 2 also fails, returns unavailable.

    Honest unmeasurable contract: the function never fabricates token
    counts when chunks can't be resolved. Downstream
    ``cache.below-min-tokens`` warnings naturally suppress (the detector
    requires ``estimated_tokens > 0``). The runtime-tier observed
    warning in ``LLMNode.post()`` catches the real failure case after
    first run **when the provider exposes cache telemetry** (the runtime
    path gates on ``llm_usage["has_cache_telemetry"]``; providers that
    omit cache fields entirely — custom proxies, brand-new releases — do
    not trigger the observed-tier warning either).
    """
```

### Change 3 — Update inline fall-through comment

**File**: `src/pflow/core/cache_analysis/token_estimation.py:171-172`

**Replace these lines**:
```python
        # Fall through to Tier 3 for declared (preserves below-min-tokens fidelity).
        # For candidate-only, fall through to Tier 4 (Option C — honest unmeasurable).
```

**With**:
```python
        # Fall through to Tier 3 (unavailable) — Option C honest unmeasurable.
        # Both declared and candidate subsets share this fall-through.
```

### Change 4 — Update module-level docstring

**File**: `src/pflow/core/cache_analysis/token_estimation.py:21-32`

**Replace the `estimate_cacheable_tokens:` block of the module docstring** (lines 21-32):

```python
``estimate_cacheable_tokens``:

1. ``trace``      — from a 2.1.0 trace event's
                    ``cache_creation_input_tokens + cache_read_input_tokens``.
                    Falls through when both fields are 0 (cache declared but
                    didn't fire — sub-threshold etc.).
2. ``memo``       — sum of memo-resolved chunk token counts (declared OR
                    candidate subsets). Partial memo data: declared subsets
                    fall through to Tier 3; candidate-only returns Tier 4.
3. ``estimator``  — heuristic on raw prompt template (declared subset only —
                    preserves ``cache.below-min-tokens`` warning fidelity).
4. ``unavailable`` — None propagation (Option C — honest unmeasurable).
```

**With**:

```python
``estimate_cacheable_tokens``:

1. ``trace``       — from a 2.1.0 trace event's
                     ``cache_creation_input_tokens + cache_read_input_tokens``.
                     Falls through when both fields are 0 (cache declared but
                     didn't fire — sub-threshold etc.).
2. ``memo`` /
   ``parameters``  — sum of resolved chunk token counts (declared OR
                     candidate subsets). All chunks must resolve; partial
                     resolution falls through to Tier 3.
3. ``unavailable`` — None propagation (Option C — honest unmeasurable).
                     Downstream ``cache.below-min-tokens`` naturally
                     suppresses; runtime-tier observed warning still fires
                     after first run.
```

---

## Test Updates

> **Before editing tests**, run `make test` to capture the current pass count baseline. After updates, run again and verify only the documented tests changed behavior.

### File: `tests/test_core/test_cache_analysis_token_estimation.py`

**Test 1 — `test_cacheable_tier_1_falls_through_when_zero` (lines 359-378)**

Update assertions to reflect new behavior. Replace lines 360-378:

```python
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
```

**Test 2 — `test_cacheable_tier_2_for_declared_partial_memo_falls_through_to_estimator` (lines 409-436)**

Rename function to `test_cacheable_tier_2_for_declared_partial_memo_falls_through_to_unavailable`. Replace lines 409-436:

```python
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
```

**Test 3 — `test_cacheable_tier_3_estimator_for_declared_no_history` (lines 439-456)**

DELETE this entire test (the heuristic it tests no longer exists).

REPLACE with a new test asserting the new contract:

```python
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
```

**Test 4 — `test_cacheable_tier_3_skips_for_candidate_only` (lines 459-475)**

Rename to `test_cacheable_unavailable_for_candidate_only_no_data`. Update docstring (lines 460-463) to remove the "Tier 3 heuristic" reference:

```python
def test_cacheable_unavailable_for_candidate_only_no_data() -> None:
    """Candidate (no declared) + no memo → Tier 3 unavailable.

    Defends: candidate-only path must not fabricate a number.
    """
```

Body and assertions unchanged.

**Test 5 — `test_cacheable_tier_2_short_circuits_when_model_empty` (lines 493-516)**

Update docstring and assertion. Replace lines 493-516:

```python
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
```

**Test 6 — `test_sum_resolved_chunk_tokens_returns_none_on_unmeasurable_chunk` (lines 541-569)**

Rename function to `test_cacheable_tier_2_partial_memo_position_independent_falls_through_to_unavailable` (the old name referred to the internal helper `_sum_resolved_chunk_tokens`, but the test calls the public `estimate_cacheable_tokens`; the new name reflects the actual tested contract). Replace lines 541-569:

```python
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
```

### File: `tests/test_core/test_cache_analysis_analyze.py`

**Test 7 — `test_heterogeneous_batch_with_declared_cache_uses_estimator_tier` (lines 2749-2789)**

Rename to `test_heterogeneous_batch_with_declared_cache_falls_through_to_unavailable`. Replace lines 2749-2789:

```python
def test_heterogeneous_batch_with_declared_cache_falls_through_to_unavailable(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heterogeneous batch (``model: ${item.model}``) + declared
    ``prompt_cache`` → Tier 2 short-circuits on empty model; falls
    through to honest unavailable.

    Closes Case 8a end-to-end: unit test #5 covers the gate; this
    verifies the full path through ``analyze()``. Post-F-04 fix: no
    fabricated estimator number, no false-positive below-min warning.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {"items": {"type": "array"}},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "batch": {"items": "${items}", "as": "item"},
                "params": {
                    "model": "${item.model}",
                    "prompt": "${context}\n\nScore the thing." + ("x" * 1000),
                },
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path="/abs/het.pflow.md", auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.model_is_heterogeneous is True
    assert row.cacheable_tokens_estimated is None
    assert row.cacheable_data_source == "unavailable"
    # No false-positive below-min-tokens warning.
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert not below_min, f"unexpected warnings: {[w.id for w in analysis.warnings]}"
```

**Test 8 — `test_below_min_tokens_still_fires_when_estimator_says_below_min` (lines 2925-2965)**

Rename to `test_below_min_tokens_fires_when_memo_data_shows_below_min`. The test must now drive the warning via real memo data instead of the deleted Tier 3 heuristic. The fixture pattern matches the existing brownfield test at `test_cache_analysis_analyze.py:2553-2588` (verified against production code).

Replace the entire test body (read lines 2925-2965 to find the full block):

```python
def test_below_min_tokens_fires_when_memo_data_shows_below_min(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When source is ``"memo"`` (not ``"trace"``) and tokens are below
    threshold, the warning still fires. Locks the inverse contract:
    suppression is keyed on ``"trace"`` specifically, not on cacheable
    > 0 alone.

    Defends: the suppression gate must be keyed on ``"trace"``; any
    other tier name (``"memo"``, ``"parameters"``) would suppress the
    warning for those sources too. Pitfall #19: drives via real
    ``MemoizationCache.put`` not synthetic fixture.
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Lock token counter to a deterministic small value below 1024 (sonnet
    # min). Defends against tokenizer drift.
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 100)

    workflow_path = "/abs/below_min_via_memo.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    # Note required positional: action="default" — MemoizationCache.put has
    # no default for `action`. Mirror the existing brownfield test pattern
    # at test_cache_analysis_analyze.py:2576-2582.
    cache.put(
        cache_key="seeded-context",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "tiny content"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context.response", "prose_before": "Context:\n"}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "${context.response}\n\nDo work.",
                },
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        auto_load_trace=False,
    )
    row = analysis.per_call[0]
    # Tighten: parameters tier is unreachable in this fixture (inputs={}),
    # so the only legitimate value is "memo".
    assert row.cacheable_data_source == "memo"
    assert row.cacheable_tokens_estimated is not None
    assert row.cacheable_tokens_estimated < 1024
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert len(below_min) == 1, (
        f"cache.below-min-tokens should fire when memo says below threshold; "
        f"got: {[w.id for w in analysis.warnings]}"
    )
```

> **Verified**: this fixture matches the existing brownfield test at `test_cache_analysis_analyze.py:2553-2588`. Memo cache is auto-discovered by `analyze()` via the standard `MemoizationCache()` lookup at `~/.pflow/cache/cache.db` (which `monkeypatch` redirects to `tmp_path`). The `db_path=cache_db_path` explicit path is the established pattern in this file. `MemoizationCache.put` requires `action`, `cache_key`, `node_id`, `workflow_path`, `output` — no defaults.

**Test 9 — `test_declared_partial_memo_falls_through_to_estimator_end_to_end` (lines 3078-3131)**

Rename to `test_declared_partial_memo_falls_through_to_unavailable_end_to_end`. Read lines 3078-3131 first; update assertions:
- Find any line asserting `row.cacheable_data_source == "estimator"` → replace with `row.cacheable_data_source == "unavailable"`
- Find any line asserting `row.cacheable_tokens_estimated > 0` or `is not None` → replace with `row.cacheable_tokens_estimated is None`
- Update docstring to say "falls through to Tier 3 unavailable" instead of "Tier 3 estimator"

**Test 10 — `test_child_workflow_unresolved_input_remains_unavailable` (lines 1039-1082)**

Read lines 1039-1082. The test name says "remains_unavailable" already — likely just needs assertion update. Find and replace ONLY:
- `row.cacheable_data_source == "estimator"` → `row.cacheable_data_source == "unavailable"`

> **CRITICAL — do NOT touch `data_source == "estimator-partial"`** if present nearby in the same test. That field is `data_source` (input tokens), not `cacheable_data_source` (cacheable tokens). Per the "Critical scoping note" at the top of this plan, `data_source == "estimator-partial"` remains valid post-fix; only `cacheable_data_source == "estimator"` is being removed.

If the test was originally written to test that unresolved input refs land at `estimator` (despite the name), update to assert `unavailable` consistently. Test name now matches behavior post-fix.

### File: `tests/test_core/test_cache_analysis_analyze.py` (additional drive-by + 2 new tests)

**Drive-by — Mutation contract docstring update (line 2563-2565)**

The existing test `test_brownfield_memo_populates_cacheable_via_memo_tier` has a docstring that describes a mutation against the deleted Tier 3 heuristic. After the fix, the mutation contract no longer matches reality.

Read lines 2563-2566. The current docstring reads:

```
Defends: reverting to a static heuristic drops cacheable to ~187
(heuristic value) and the source label to ``"estimator"`` instead
of ``"memo"``.
```

Replace with:

```
Defends: blocking the memo tier (e.g., short-circuiting Tier 2 with
an empty-model check or removing the chunks-resolve loop) drops
cacheable to ``None`` and the source label to ``"unavailable"`` —
no longer to a fabricated heuristic value, since Tier 3 is deleted.
```

This is a docstring-only change; the test's behavior assertions are unaffected (it asserts the brownfield-memo path produces real numbers).

**New Test 12 — Explicit F-04 regression test**

Add a new test in `tests/test_core/test_cache_analysis_analyze.py` (placement: near the other `test_below_min_tokens_*` tests, around line 2965):

```python
def test_f04_greenfield_node_output_chunk_does_not_emit_false_below_min_warning(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-04 regression — the bug this PR fixes.

    Pre-fix: a workflow where ``prompt_cache:`` references an upstream
    node output (``${produce.response}``) AND no memo data exists would
    fall through Tier 1 (no trace) → Tier 2 (no memo) → Tier 3 heuristic
    → fabricated ~``len(prompt) * 75 // 400`` token count → false-positive
    ``cache.below-min-tokens`` warning ("declared cache content is ~1
    tokens, below ... minimum of 1024").

    Post-fix: Tier 3 is deleted; the path lands at Tier 4 unavailable.
    No warning fires; cacheable is ``None``; agent gets honest
    unmeasurable signal.

    Defends: re-introducing any heuristic on prompt body for declared
    subsets would re-emit this false-positive.

    This is a unit-level mirror of the ``baseline/14-pitfall-19-defenses
    /01-dotted-path-chunk/`` reproduction case.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {"article": {"type": "string", "required": True}},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "produce.response", "var": "produce.response", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "produce",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Echo the article: ${article}",
                },
            },
            {
                "id": "consume",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Summarize.",
                },
                "prompt_cache": ["produce.response"],
            },
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path="/abs/f04.pflow.md", auto_load_trace=False)

    consume_row = next(r for r in analysis.per_call if r.node_path == "consume")
    assert consume_row.cacheable_tokens_estimated is None
    assert consume_row.cacheable_data_source == "unavailable"
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert not below_min, (
        f"F-04 regression: cache.below-min-tokens fired on greenfield "
        f"node-output chunk. Warnings: {[w.id for w in analysis.warnings]}"
    )
```

**New Test 13 — Partial inputs boundary**

Add a new test (near Test 12) covering the mixed-resolution case (some chunks resolve via parameters, others reference unresolved node outputs):

```python
def test_partial_input_resolution_with_node_output_chunk_returns_unavailable(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed ## Cache: input-ref chunk + node-output-ref chunk. Only
    the input-ref resolves (via parameters). Per the symmetric Tier 2
    contract (any unresolvable chunk → unavailable), the cacheable
    estimate must be ``None`` rather than a partial sum or fabricated
    heuristic.

    Defends: any future "partial-lower-bound" implementation that emits
    a non-None cacheable for partial-resolution would silently change
    the warning behavior. This locks the symmetric all-or-nothing
    contract documented in ``estimate_cacheable_tokens``'s docstring
    post-fix.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {"concept": {"type": "string", "required": True}},
        "cache": {
            "ttl": "5m",
            "items": [
                {"name": "concept", "var": "concept", "prose_before": "Concept: "},
                {"name": "upstream.response", "var": "upstream.response", "prose_before": "\nAnalysis: "},
            ],
        },
        "nodes": [
            {
                "id": "upstream",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Analyze ${concept}"},
            },
            {
                "id": "downstream",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "Summarize."},
                "prompt_cache": ["concept", "upstream.response"],
            },
        ],
        "edges": [],
    }

    analysis = analyze(
        workflow_ir,
        workflow_path="/abs/partial.pflow.md",
        parameters={"concept": "demo"},
        auto_load_trace=False,
    )
    downstream_row = next(r for r in analysis.per_call if r.node_path == "downstream")
    assert downstream_row.cacheable_data_source == "unavailable"
    assert downstream_row.cacheable_tokens_estimated is None
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert not below_min
```

> **Verify before writing**: confirm `analyze()`'s signature accepts `parameters=` (verified — used by `test_cache_analysis_analyze.py:1138-1173 test_cacheable_tokens_includes_cache_content_when_chunks_only_in_cache_block` which passes `parameters=`).

### File: `tests/test_cli/test_analyze_cache.py`

**Test 11 — `test_analyze_cache_with_workflow_having_warnings_still_exits_zero` (lines 355-375)**

Read lines 355-375. The test uses `_LLM_WORKFLOW` with no parameters; the chunk `${topic}` is a workflow input. With Tier 3 deleted, this would no longer fire any warning, breaking the test's premise.

**Update the test** to provide a positional `key=value` parameter so the warning fires from Tier 2 (parameters):

```python
def test_analyze_cache_with_workflow_having_warnings_still_exits_zero(
    tmp_path: Path,
) -> None:
    """Warnings (non-blocking) should not affect exit code.

    Post-F-04 fix: provides ``topic=hi`` as a positional param so the
    warning fires from Tier 2 (parameters), not the deleted Tier 3
    heuristic. ``"hi"`` tokenizes well below 1024 (sonnet min).
    """
    workflow_path = _write_workflow(tmp_path, _LLM_WORKFLOW)
    runner = CliRunner()
    # CRITICAL: analyze-cache uses positional `key=value` params via
    # @click.argument("params", nargs=-1) — there is no --inputs flag.
    # Verified at src/pflow/cli/commands/analyze_cache.py:42-43.
    # Match the file's existing convention: invoke via `cli`, prefix args
    # with the subcommand name "analyze-cache".
    result = runner.invoke(
        cli,
        ["analyze-cache", str(workflow_path), "topic=hi", "--no-trace-autoload"],
    )
    assert result.exit_code == 0
    assert "cache.below-min-tokens" in result.output
```

> **Verified**: `cli` is imported at the top of `tests/test_cli/test_analyze_cache.py:17` (`from pflow.cli.main import cli`). The `_write_workflow` helper exists at line 20-23. Both follow the existing convention in this file.

---

## Documentation Updates

### Doc 1 — Drop "estimator" from `cacheable_data_source` enumerations + fix pre-existing "parameters" omission

There is pre-existing doc drift: 2 sites omit `"parameters"` from the enumeration even though the field already emits 5 values. While we're touching these sites, fix the drift.

**File**: `src/pflow/core/cache_analysis/render_json.py:219-223`

Find the inline comment that says (approximate text — verify exact wording):
> "Independent tier label for the cacheable metric. Sources: 'trace', 'memo', 'estimator', 'unavailable'."

Replace `'trace', 'memo', 'estimator', 'unavailable'` with `'trace', 'memo', 'parameters', 'unavailable'`.

**File**: `src/pflow/core/cache_analysis/analyze.py:132-134`

Find the comment block above the `cacheable_data_source` field on the `PerCallRow` dataclass that says (approximate):
> "Sources: 'trace', 'memo', 'parameters', 'estimator', 'unavailable'. 'parameters' is added by Track B (Phase B)..."

Replace `'trace', 'memo', 'parameters', 'estimator', 'unavailable'` with `'trace', 'memo', 'parameters', 'unavailable'`. Drop the Track B mention if it specifically references "estimator" (re-read the surrounding paragraph for context).

### Doc 2 — MCP tool docstring

**File**: `src/pflow/mcp_server/tools/execution_tools.py:457-461`

Find the docstring text:
> "**per_call[].cacheable_data_source** is INDEPENDENT from `data_source` and tracks the cacheable-tokens metric specifically. Values: `trace` / `memo` / `parameters` / `estimator` / `unavailable`."

Replace `trace` / `memo` / `parameters` / `estimator` / `unavailable` with `trace` / `memo` / `parameters` / `unavailable`.

### Doc 3 — Cache analysis CLAUDE.md

**File**: `src/pflow/core/cache_analysis/CLAUDE.md`

Find the section "### token_estimation.py" and the "Asymmetric fall-through for cacheable-token estimation" subsection. Currently includes:
> "For DECLARED subsets: partial memo data → falls through to Tier 3 (heuristic) to preserve `cache.below-min-tokens` warning fidelity."
> "For CANDIDATE-only (greenfield projection): partial memo data → returns `(None, "unavailable")` (Option C — honest unmeasurable)."

**Replace** the asymmetric fall-through paragraph with:
> "Symmetric fall-through: when chunks can't be fully resolved (any chunk returns None from `_estimate_ref_tokens`), both DECLARED and CANDIDATE subsets return `(None, "unavailable")`. Honest unmeasurable. The previous declared-subset Tier 3 heuristic was deleted (F-04 fix) — it fabricated `len(prompt) * 75 // 400` token counts that didn't reflect actual cache content size and produced false-positive `cache.below-min-tokens` warnings."

Also find any reference to "Tier 1 fall-through" that mentions Tier 3 and update to reflect the new tier set (trace → memo/parameters → unavailable).

### Doc 4 — Example preamble

**File**: `examples/core/prompt-caching.pflow.md`

**Delete lines 12-15** (the entire blockquote that documents the bug):

```markdown
> Greenfield `analyze-cache` will warn that the cached chunk is below the
> provider's minimum token threshold — it can only estimate from the literal
> `${extract.response}` reference until you run once. Run the workflow with
> a real article, then re-run `analyze-cache` to see actual cache projections.
```

**Replace with** a corrected hint about the data flow:

```markdown
> Greenfield `analyze-cache` reports cacheable tokens as unavailable for
> chunks referencing upstream node outputs (here, `${extract.response}`).
> Run the workflow once to populate the memo cache, then re-run
> `analyze-cache` to see real cache projections.
```

> **CRITICAL — do NOT mention `--inputs` here.** `analyze-cache` uses
> positional `key=value` params, not a `--inputs` flag (verified at
> `src/pflow/cli/commands/analyze_cache.py:42-43` — `@click.argument("params", nargs=-1)`).
> The example workflow has only one input (`article`) referenced via
> `${article}` in `extract`'s prompt body, NOT as a `## Cache` chunk —
> so passing `article=...` to `analyze-cache` would not affect cacheable
> token measurement here. The simplest accurate guidance is "run once,
> populate memo cache."

This file is consumed by `tests/test_docs/test_example_validation.py` (auto-discovered via `rglob`). The change is markdown-comment-only and doesn't affect IR validation. No test changes needed in `test_docs/`.

### Doc 5 — pflow guide caching

**File**: `src/pflow/guide/features/caching.md`

No changes required. The `cache.below-min-tokens` row in the catalog table (line 222) reads "declared cache content below provider minimum" — this description remains accurate post-fix (warning still fires when we have real data showing below threshold). The guide doesn't reference the "estimator" tier or Tier 3 heuristic.

### Doc 6.5 — Cache analysis package version history

**File**: `src/pflow/core/cache_analysis/__init__.py:12-35`

The version history block enumerates `cacheable_data_source` enum changes inline. The current "2.1" entry mentions: *"`cacheable_data_source` gains `'parameters'` value."* — that's still accurate.

The Tier 3 deletion narrows the enum from 5 → 4 values (drops `"estimator"`). Per the consumer rule documented at line 33 (*"semantic shifts in field meaning bump minor"*), this is a semantic shift on the field's value space.

**Add a new `"4.1"` entry** to the version history block (insert after the `"4.0"` entry):

```python
- ``"4.1"`` — F-04 fix: ``per_call[].cacheable_data_source`` enum narrowed
  from 5 values to 4 — ``"estimator"`` is no longer emitted. Pre-fix, the
  declared-subset Tier 3 heuristic at ``token_estimation.py:174-176`` would
  fabricate a ``len(prompt) * 75 // 400`` token count when memo/parameters
  couldn't resolve chunks; the value carried the ``"estimator"`` source
  label. Post-fix, that path returns ``(None, "unavailable")`` per the
  honest-unmeasurable contract. Field shape unchanged; only the value
  enum narrows. No production code branched on ``"estimator"`` for this
  field.
```

**Then bump the constant** at line 47:

```python
JSON_FORMAT_VERSION: Final[str] = "4.1"
```

This is a minor bump (additive value-set narrowing), not major. Consumers gating on `format_version.startswith("4.")` are unaffected.

**Update Doc 1's render_json scope**: when emitting `format_version` at the top of the JSON output (`render_json.py`), the version string changes from `"4.0"` to `"4.1"`. Verify against `render_json.py` to ensure the constant is read from `__init__.py:JSON_FORMAT_VERSION` and not hard-coded.

### Doc 6 — Task spec

**File**: `.taskmaster/tasks/task_159/task-159.md`

**No changes required.** The spec discusses `"estimator"` exclusively as a tier label of `data_source` (the input-tokens metric, produced by `estimate_tokens(model, text)` via `litellm.token_counter`). This tier is **NOT** being deleted — `data_source == "estimator"` remains a valid runtime value.

This fix only touches `cacheable_data_source` (the cacheable-tokens metric, produced by `estimate_cacheable_tokens`), which is a separate field on `PerCallRow`.

### Critical scoping note: `data_source` vs `cacheable_data_source`

These are **two independent fields** on `PerCallRow`:

| Field | Function that produces it | "estimator" tier? |
|---|---|---|
| `data_source` (input tokens) | `estimate_tokens(model, text)` — `litellm.token_counter` | **KEPT** — still emits `"estimator"` |
| `cacheable_data_source` (cacheable tokens) | `estimate_cacheable_tokens(...)` — currently has Tier 3 heuristic | **REMOVED** — Tier 3 deleted; `"estimator"` no longer emitted for this field |

When updating docs (Docs 1-3), only update enumerations that explicitly describe `cacheable_data_source` values. Do NOT alter enumerations describing `data_source` (input tokens) — `"estimator"` is still valid there.

---

## Baseline Fixture Regeneration

Seven baseline expected-stdout files lock current Tier 3 outputs. After production code + tests are updated, regenerate via the harness.

### Step 1 — Regenerate

Run from repo root:

```bash
./.taskmaster/tasks/task_159/baseline/regenerate.sh
```

This re-runs every case under `.taskmaster/tasks/task_159/baseline/` and writes new `expected-stdout.txt` / `expected-stderr.txt` / `expected-exit-code.txt`.

### Step 2 — Verify each case manually

The 7 cases below will have meaningful diffs. Inspect each before committing.

| Case path | Expected diff |
|---|---|
| `04-warning-catalog/09-cache.below-min-tokens/expected-stdout.txt` | **Behavior change**: workflow fires warning today via Tier 3. After fix, the warning will not fire unless `--inputs` is provided (this case's workflow already declares an input that needs values for Tier 2). **Action**: update `command.sh` to pass `--inputs` for the relevant declared input so the warning fires legitimately. Update `README.md` mutation contract: "warning fires when memo/parameters data shows below threshold" (was: "fires from heuristic"). |
| `04-warning-catalog/01-cache.order-mismatch/expected-stdout.txt` | Cacheable changes from `1` to `null`; warning is `cache.order-mismatch` (validator), unaffected. |
| `04-warning-catalog/02-cache.unused-chunk/expected-stdout.txt` | Cacheable changes from `4` to `null`; primary warning is `cache.unused-chunk`, unaffected. |
| `04-warning-catalog/18-cache.prompt-body-duplicates-cache/expected-stdout.txt` | Cacheable changes from `6` to `null`; primary warning is `cache.prompt-body-duplicates-cache`, unaffected. |
| `14-pitfall-19-defenses/01-dotted-path-chunk/expected-stdout.txt` | **Cleanest reproduction of F-04 fix**: cacheable changes from `1` to `null`, two false-positive `cache.below-min-tokens` warnings disappear. Update README: clarify the case still tests Bug #2 (NamespacedSharedStore dotted-path resolution); the previous "cacheable=1" was incidental, not the test's load-bearing assertion. |
| `03-analyze-cache-modes/04-steady-state-json/expected-stdout.txt` | Cacheable values for declared subsets become `null` for greenfield rows; warning counts may decrease. |
| `12-real-world-lyrics-generator/02-analyze-cache-json/expected-stdout.txt` | **Largest diff**: 7 entries with cacheable values 799-2763 become `null`. Manually verify each entry's row corresponds to a declared chunk that references either a node output (no memo) or unresolved input. Don't blanket-accept — review each. |

### Step 3 — Verify the broader baseline still passes

```bash
./.taskmaster/tasks/task_159/baseline/verify.sh
```

Expected: 63/63 cases pass. Any unexpected diff means a fixture not in the table above changed; investigate before committing.

---

## Verification

### Pre-implementation belt-and-braces audit

Before editing any code, run a final grep sweep to catch test sites the search agents may have missed. The expected match set is documented above (11 tests across 3 files); any extra match needs a manual update plan before proceeding.

```bash
# Find all test assertions on cacheable_data_source = "estimator"
grep -rn 'cacheable_data_source.*"estimator"' tests/ \
  | grep -v "^Binary file"

# Find all test assertions on cacheable_data_source = "estimator" in fixtures
grep -rn '"cacheable_data_source": "estimator"' .taskmaster/tasks/task_159/baseline/

# Find any production code that branches on the deleted value
grep -rn 'cacheable_data_source.*"estimator"' src/
```

Expected matches:
- 6 tests in `tests/test_core/test_cache_analysis_token_estimation.py` (lines 359, 409, 439, 459, 493, 541 — wait, `_skips_for_candidate_only` doesn't match this exact pattern; verify)
- 4 tests in `tests/test_core/test_cache_analysis_analyze.py` (lines 1081, 2787, 2925-region, 3078-region)
- 1 test in `tests/test_cli/test_analyze_cache.py` (line 355-region)
- 7 baseline expected-stdout files (listed in the Baseline Fixture Regeneration section)
- **Zero production matches in `src/`** — confirms no code branches on the deleted tier value.

If the grep returns matches outside this set, STOP and add the new sites to the implementation order before proceeding.

### Pre-implementation reproduction (current bug)

Confirm the bug currently exists:

```bash
uv run pflow analyze-cache .taskmaster/tasks/task_159/baseline/14-pitfall-19-defenses/01-dotted-path-chunk/workflow.pflow.md --no-trace-autoload --format=json | python -c "import json, sys; d = json.load(sys.stdin); print('warnings:', [w['id'] for w in d['warnings']]); print('cacheable values:', [r['cacheable_tokens_estimated'] for r in d['per_call']])"
```

Expected pre-fix: `warnings: ['cache.below-min-tokens', 'cache.below-min-tokens']`, `cacheable values: [None, 1, 1]`.

### Post-implementation verification

#### Step 1 — Targeted unit tests pass

```bash
uv run pytest tests/test_core/test_cache_analysis_token_estimation.py -v
uv run pytest tests/test_core/test_cache_analysis_analyze.py -v -k "below_min or partial_memo or heterogeneous_batch or unresolved_input"
uv run pytest tests/test_cli/test_analyze_cache.py -v
```

Expected: all pass with the updated assertions.

#### Step 2 — Defense in depth still works (runtime-tier observed warning)

```bash
uv run pytest tests/test_execution/test_runner.py -v -k "below_min or cache_telemetry or zero_provider_tokens"
```

Expected: pass unchanged. Independent code path, not affected by deletion.

#### Step 3 — Per-id emission tests still pass

```bash
uv run pytest tests/test_core/test_cache_analysis_per_id_emission.py -v
```

Expected: pass. Tests use real memo/parameter data per Pitfall #19 doctrine, so they don't depend on Tier 3.

#### Step 4 — Full default suite

```bash
make test
```

Expected: 6,342 passing (the current baseline) — no decrease. May see test count decrease by 1 if Test 3 deletion is not paired with the new test (it is).

#### Step 5 — Quality checks

```bash
make check
```

Expected: clean (ruff, ruff-format, mypy, deptry).

#### Step 6 — Manual smoke

**A. The reproduction case now produces honest output**:

```bash
uv run pflow analyze-cache .taskmaster/tasks/task_159/baseline/14-pitfall-19-defenses/01-dotted-path-chunk/workflow.pflow.md --no-trace-autoload --format=json | python -c "import json, sys; d = json.load(sys.stdin); print('warnings:', [w['id'] for w in d['warnings']]); print('cacheable values:', [r['cacheable_tokens_estimated'] for r in d['per_call']])"
```

Expected post-fix: `warnings: []`, `cacheable values: [None, None, None]`.

**B. With a positional `key=value` param, the warning still fires legitimately**:

Create a test workflow `/tmp/test-fires.pflow.md`:

```markdown
# Test
## Inputs
### topic
- type: string
- required: true
## Cache
```cache
Topic: ${topic}
```
## Steps
### summarize
- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [topic]
```prompt
Summarize.
```
```

Run (note: `analyze-cache` takes positional `key=value` params, NOT a `--inputs` flag — verified at `analyze_cache.py:42-43`):

```bash
uv run pflow analyze-cache /tmp/test-fires.pflow.md topic=hi --no-trace-autoload --format=json | python -c "import json, sys; d = json.load(sys.stdin); print('warnings:', [w['id'] for w in d['warnings']]); print('cacheable_data_source:', [r['cacheable_data_source'] for r in d['per_call']])"
```

Expected: `warnings: ['cache.below-min-tokens']`, `cacheable_data_source: ['parameters']`.

**C. The canonical example no longer apologizes**:

```bash
uv run pflow analyze-cache examples/core/prompt-caching.pflow.md --no-trace-autoload --format=json | python -c "import json, sys; d = json.load(sys.stdin); print('warnings:', [w['id'] for w in d['warnings']])"
```

Expected: no `cache.below-min-tokens` (greenfield, node-output ref unmeasurable). Other warnings (e.g., shared-context recommendations) may still fire.

#### Step 7 — Mutation checks (two layers)

**Layer 1 — Production deletion**: Confirm the fix is real, not coincidental. Revert the production deletion and re-run the targeted tests; a specific count must fail.

```bash
git stash push src/pflow/core/cache_analysis/token_estimation.py
uv run pytest tests/test_core/test_cache_analysis_token_estimation.py tests/test_core/test_cache_analysis_analyze.py tests/test_cli/test_analyze_cache.py -v 2>&1 | grep -E "PASS|FAIL"
git stash pop
```

Expected during stash: **AT MINIMUM 9 tests fail** — the floor is precise, not "at least 4":
- `test_cacheable_tier_1_falls_through_when_zero` (Test 1)
- `test_cacheable_tier_2_for_declared_partial_memo_falls_through_to_unavailable` (Test 2)
- `test_cacheable_tier_3_unavailable_for_declared_no_history` (Test 3)
- `test_cacheable_tier_2_short_circuits_when_model_empty` (Test 5)
- `test_cacheable_tier_2_partial_memo_position_independent_falls_through_to_unavailable` (Test 6)
- `test_heterogeneous_batch_with_declared_cache_falls_through_to_unavailable` (Test 7)
- `test_below_min_tokens_fires_when_memo_data_shows_below_min` (Test 8 — fails differently: warning now fires from BOTH memo AND the restored heuristic, may double-count or change the warning context)
- `test_declared_partial_memo_falls_through_to_unavailable_end_to_end` (Test 9)
- `test_f04_greenfield_node_output_chunk_does_not_emit_false_below_min_warning` (Test 12)
- `test_partial_input_resolution_with_node_output_chunk_returns_unavailable` (Test 13)

If **fewer than 9 tests fail**, the mutation contract is weaker than expected; investigate which assertion is too loose and tighten it.

**Layer 2 — Detector primitive**: Confirm the load-bearing None-handling at `below_min_tokens_detector.py:65` is what suppresses the warning, not just an incidental gate. Mutate the detector to remove the None guard:

```bash
# Edit src/pflow/core/cache_analysis/below_min_tokens_detector.py:65
# Change: if evidence.estimated_tokens is None or evidence.estimated_tokens <= 0:
# To:     if evidence.estimated_tokens is None:  # remove the <= 0 check
# (Or comment out the entire line for a stronger mutation)

git stash push src/pflow/core/cache_analysis/below_min_tokens_detector.py
# ... apply mutation manually ...
uv run pytest tests/test_core/test_below_min_tokens_detector.py -v
git stash pop  # or git checkout to restore
```

This proves: `None`-propagation through the detector is what gates suppression. If the detector's None-handling regresses (e.g., a future contributor changes line 65), the existing detector tests catch it independently of our F-04 fix.

---

## Out of Scope (deliberately deferred)

### Notes lines explaining WHY a chunk is unmeasurable

**Status**: NOT in this fix. Theorized solution to a non-observed problem (CLAUDE.md: "Solve observed problems, not theorized ones"). The existing `?` rendering + agent context (workflow file, declared `prompt_cache:`, model) + `pflow guide caching` topic + MCP tool docstring is sufficient for agents to figure out remediation. If real-world usage shows agents getting confused, file as a follow-up; don't pre-invent.

### `_tokenize_declared_cache_chunks` silent 0-skip in `input_tokens`

**Status**: NOT in this fix. Located at `src/pflow/core/cache_analysis/analyze.py:1554-1599`. Same conceptual pattern (silently degrades unresolvable chunks) but for `input_tokens` not `cacheable_tokens`. Lower magnitude of misinformation (under-counts vs fabricates). Different fix surface (would need cascading changes to `data_source` enum and renderer). Different test surface. Keep PR scope tight; file as a separate finding if desired.

### CLI flag name collision (`--no-trace` vs `--no-trace-autoload`)

**Status**: NOT in this fix. Documented as UX 2 in `scratchpads/task159-baseline-findings-report.md`. Independent issue, separate fix.

### Other findings from the baseline triage

UX 1 (undocumented suppression gates), UX 4 (inconsistent catalog-ID surfacing), F-03 (`pflow guide` auto-detect missing caching topic), Bug 1 (`thinking_effort` silent drop), Bug 3 (trace auto-load silent miss): all separate fixes, NOT in this PR. This PR is focused on F-04 only.

---

## Risks

1. **`cacheable_data_source` value enum shrinks from 5 to 4 — `data_source` enum is unchanged.** Be precise about which field is being narrowed. `cacheable_data_source` (cacheable-tokens metric): drops `"estimator"`, leaves `{trace, memo, parameters, unavailable}`. `data_source` (input-tokens metric): UNCHANGED — `"estimator"` and `"heuristic"` still valid. No production code branches on the deleted value (Agent 4 verified). Per CLAUDE.md ("NO USERS yet"), the enum narrowing is contractually safe.

2. **`12-real-world-lyrics-generator/02-analyze-cache-json` baseline diff is large** — 7 entries change. Manually inspect each transformation rather than blanket-accepting the regenerated output.

3. **`04-warning-catalog/09-cache.below-min-tokens` case requires `command.sh` update** — it's the only case whose primary purpose was testing the deleted code path. After fix, it tests the same warning via Tier 2 (memo or parameters). Update the case's `command.sh` to pass `--inputs` and update `README.md` mutation contract accordingly.

4. **`memo_cache` parameter to `analyze()`** — Test 8 assumes `analyze()` accepts a `memo_cache` keyword argument. Verify against `src/pflow/core/cache_analysis/analyze.py` before writing. If the production signature differs, adapt the test's seeding mechanism (write a real trace file and use `trace_path=`, mirroring the pattern in Test 7's neighboring tests at `test_cache_analysis_analyze.py:2867+`).

5. **CLI uses positional `key=value` params, NOT a `--inputs` flag** — verified at `src/pflow/cli/commands/analyze_cache.py:42-43` (`@click.argument("params", nargs=-1)`). The plan's Test 11, manual smoke commands, and example preamble all use this corrected syntax. Be careful when reading older docs or scratchpads that may reference a non-existent `--inputs` flag.

6. **Defense-in-depth has a provider-telemetry gate**: `LLMNode._emit_observed_below_min_cache_warning` at `nodes/llm/llm.py:191` checks `llm_usage.get("has_cache_telemetry", False)`. Providers that omit cache fields entirely (custom proxies, OpenAI-compatible endpoints lacking cache reporting, brand-new releases) won't trigger the runtime-tier warning. After this fix, those workflows are silent in BOTH the predicted AND observed tiers — agents would only learn cache failed via cost analysis or trace inspection. This pre-existing gap is documented but worth knowing; no fix in this PR.

7. **JSON_FORMAT_VERSION bumps from `"4.0"` to `"4.1"`** — Doc 6.5 specifies this. Consumers gating on `format_version.startswith("4.")` are unaffected. New consumers gating on the exact value would need to update.

---

## Critical Files (modified)

- `src/pflow/core/cache_analysis/token_estimation.py` (production deletion + docstrings)
- `src/pflow/core/cache_analysis/render_json.py` (1 doc comment)
- `src/pflow/core/cache_analysis/analyze.py` (1 doc comment on PerCallRow field)
- `src/pflow/core/cache_analysis/CLAUDE.md` (asymmetric fall-through paragraph)
- `src/pflow/core/cache_analysis/__init__.py` (version history block + `JSON_FORMAT_VERSION` bump 4.0 → 4.1)
- `src/pflow/mcp_server/tools/execution_tools.py` (1 docstring)
- `examples/core/prompt-caching.pflow.md` (preamble blockquote)
- `tests/test_core/test_cache_analysis_token_estimation.py` (6 tests updated/replaced/renamed)
- `tests/test_core/test_cache_analysis_analyze.py` (4 tests updated/renamed + 2 NEW tests + 1 docstring drive-by)
- `tests/test_cli/test_analyze_cache.py` (1 test updated — positional params, not `--inputs` flag)
- `.taskmaster/tasks/task_159/baseline/04-warning-catalog/09-cache.below-min-tokens/command.sh` (add positional `key=value` param)
- `.taskmaster/tasks/task_159/baseline/04-warning-catalog/09-cache.below-min-tokens/README.md` (mutation contract update)
- `.taskmaster/tasks/task_159/baseline/14-pitfall-19-defenses/01-dotted-path-chunk/README.md` (mutation contract clarification)
- 7 `expected-stdout.txt` files (regenerated via `regenerate.sh`)

## Critical Files (read-only context — do not modify)

- `src/pflow/core/cache_analysis/below_min_tokens_detector.py` — confirm warning suppression logic (the detector at lines 65-66 already returns None for `estimated_tokens is None or <= 0`; no change needed)
- `src/pflow/nodes/llm/llm.py` — runtime-tier observed warning at `_emit_observed_below_min_cache_warning` (lines 168-218); confirms defense in depth
- `src/pflow/core/cache_analysis/render_text.py:1105-1127` (`_row_has_real_data`) — confirms rows with declared `prompt_cache:` stay visible after fix; `cacheable=?` rendering preserves visibility
- `tests/CLAUDE.md` — Pitfall #19 doctrine (production-shape fixtures over synthetic dicts)

---

## Implementation Order (suggested)

1. Run the pre-implementation belt-and-braces grep audit (Verification Step 0). Stop and investigate if extra matches surface.
2. Production code deletion (Change 1) + docstring updates (Changes 2-4)
3. Update `__init__.py` (Doc 6.5) — bump `JSON_FORMAT_VERSION` to `"4.1"` and add the version history entry
4. Run `make test` — observe failures (this confirms Tier 3 is exercised by exactly the documented sites; the failures will guide test updates)
5. Update existing tests 1-11 (in order)
6. Add new Tests 12 + 13 (F-04 regression + partial-inputs boundary) and the drive-by docstring update on `test_brownfield_memo_populates_cacheable_via_memo_tier`
7. Run targeted test files to confirm green
8. Update docs (Doc 1, 2, 3, 4) — drop `"estimator"` from `cacheable_data_source` enums, fix pre-existing `"parameters"` omission
9. Update baseline fixture `command.sh` + `README.md` files (cases 09 and dotted-path-chunk)
10. Run `./.taskmaster/tasks/task_159/baseline/regenerate.sh`
11. Manually review each of the 7 expected diffs (especially the lyrics-generator JSON; don't blanket-accept)
12. Run full verification (Verification section Steps 1-7, including the two-layer mutation check)
13. Run `make check` (ruff, ruff-format, mypy, deptry)
14. Verify final state: 6,342+ tests passing on default suite (baseline + 2 new tests = 6,344)
