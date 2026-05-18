# Multi-Breakpoint Prompt Caching for Anthropic — Implementation Progress Log

**Branch**: `main` (working tree)
**Date**: 2026-05-18
**Plan source**: User-supplied implementation plan (Task 159 follow-up, see DD#11 / DD#19)

## What this delivers

Workflows with multiple `## Cache` chunks that change at different
frequencies (system prompt → knowledge base → session context → per-call)
now get **automatic, per-chunk cache reuse on Anthropic** — without any
new workflow syntax and without affecting non-Anthropic providers.

Before this change, despite a workflow declaring N chunks, the runtime
emitted **one** `cache_control` breakpoint per LLM call (on the last
chunk). That was the deferred v1 single-breakpoint strategy.

After this change:
- **Anthropic** (budget=4): first `(budget - 1)` chunks each get their own
  marker; remaining chunks merge into the terminal marker.
- **All other providers** (budget=1): terminal marker only, byte-identical
  to today's behavior.

## High-level result

- **Production code change**: ~50 LOC across 3 files.
- **Test code change**: ~280 LOC across 4 test files.
- **Zero hash drift**: golden baseline tests pass unchanged.
- **Zero memo cache invalidation**: hash side intentionally untouched.
- **Final gates**:
  - `make check`: ruff/ruff-format/mypy/deptry all pass.
  - `make test`: 6998 passed, 1 skipped.
  - Targeted: 175/175 cache-render+capability+hash+rendering+strip tests pass.
  - Cache analysis regression: 377/377 pass.

## Files changed

### Production code

| File | Change |
|---|---|
| `src/pflow/core/llm_capabilities.py` | Added `ANTHROPIC_BREAKPOINT_BUDGET=4`, `CONSERVATIVE_BREAKPOINT_BUDGET=1`, `get_breakpoint_budget()`. |
| `src/pflow/core/cache_render.py` | Added top-level import of `get_breakpoint_budget`; added `compute_marker_chunk_indices()` pure function. Updated stale docstring on `_build_cache_control_marker`. |
| `src/pflow/nodes/llm/llm.py` | Imported `compute_marker_chunk_indices`. Replaced single-marker placement at `_build_system_blocks` with a loop over computed indices. Updated docstring. Extended `_strip_below_min_cache_markers` with per-channel warning suppression when any marker survives. |
| `src/pflow/core/llm_client.py` | Adapter docstring updated. |
| `src/pflow/core/cache_analysis/analyze.py` | `_GroupedConsumerProjection` docstring updated (per-call denominator stays correct under multi-marker). |
| `src/pflow/core/cache_analysis/CLAUDE.md` | Cross-boundary rec phrasing updated. |

### Agent-facing content

| File | Change |
|---|---|
| `src/pflow/guide/features/prompt-caching.md` | Two new sections: "Order chunks stable-to-volatile" and "Anthropic via proxies: per-chunk caching only fires with the `anthropic/` prefix". Rewritten twice to drop pflow-internal vocabulary. |
| `examples/core/prompt-caching-multi-chunk.pflow.md` | New fixture: 3 cache chunks declared stable-to-volatile, consumed by 2 LLM nodes. Validates clean. |

### Tests

| File | Change |
|---|---|
| `tests/test_core/test_cache_render.py` | New `TestComputeMarkerChunkIndices` class (15 tests). |
| `tests/test_core/test_llm_capabilities.py` | New `TestGetBreakpointBudget` class (5 tests). |
| `tests/test_nodes/test_llm/test_prompt_cache_rendering.py` | New `TestMultiBreakpointPlacement` class (10 tests). Rewrote existing `test_multi_chunk_declaration_order_preserved`. Updated header docstring. |
| `tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py` | New `TestStripBelowMinSuppression` class (4 tests). |
| `tests/test_core/test_trace_report.py` | New `test_cached_system_renders_all_multi_breakpoint_markers` smoke test. |
| `tests/test_core/test_cache_analysis_per_id_emission.py` | Docstring updated (test logic unchanged). |

## Critical architectural insights (verified during implementation)

### 1. Hash side is marker-agnostic by design

The single most load-bearing fact about this change:

`runtime/engine/plan_node.py::_render_cache_for_hash` (lines 152-192) produces
`[{"name", "prose", "value"}, ...]` dicts — **no marker info, no provider
detection, no TTL, no `cache_control` field**. Markers are a pure
wire-format concern that affects what gets sent to the provider but NOT
what pflow hashes for memo cache identity.

This means **`compute_marker_chunk_indices` is called from the prep side
only**, never from the hash side. As a direct consequence:

- `_render_cache_for_hash` required ZERO changes.
- `compute_node_config` signature unchanged.
- `tests/test_runtime/fixtures/golden_config_hashes.json` did not drift.
- Existing memo cache entries remain valid across the upgrade.
- DD#19 byte-identity invariant preserved automatically.

The byte-equivalence tests (`test_hash_render_and_prep_render_byte_equivalent_*`)
compare `hash["prose"] + hash["value"]` vs `prep_block["text"]` —
multi-marker adds `cache_control` keys but does not touch `text` bytes,
so these tests pass unchanged.

### 2. `cache_ctx.prewarm` is the post-pre-flight truth

`_build_system_blocks` reads `cache_ctx.prewarm` (the engine pre-strips
this to `False` when `_should_disable_below_min_prewarm` fires on a
small batch prefix). This is the right input — using `config.prewarm`
or the IR-time prewarm would leak pre-strip state and over-reserve the
budget.

There's a documented sub-optimal corner: when prewarm passes pre-flight
but bails out at runtime (e.g., images present, alignment fail —
7 gate conditions in `llm.py:504-525`), `cache_ctx.prewarm` stays `True`
and we conservatively reserve a slot we won't use. Cost: one declared
marker we could have placed but didn't — strictly less aggressive
caching, never an API error. The 4-marker cap is never exceeded.

This is captured in `test_prewarm_declared_but_bailed_out_still_reserves_slot`.

### 3. The strip walker uses cross-channel cumulative tokens

`_strip_below_min_cache_markers` accumulates tokens across both channels
in order (`system_blocks` → `user_message_blocks`). A marker in the
prewarm channel sees cumulative tokens from EVERY block before it,
including all of `system_blocks`.

Consequence for the new suppression logic: "declared survives + prewarm
stripped" is structurally rare. Once `system_blocks` accumulates past
threshold, no later `user_message_blocks` marker can ever strip. This
is why the planned test under that name was reframed to
`test_prewarm_channel_suppresses_when_any_marker_survives` covering the
same suppression rule on a different, achievable channel config.

### 4. Single-chunk behavior is byte-identical

For 1 rendered chunk on any provider, `compute_marker_chunk_indices`
returns `(0,)`, producing exactly the same `cache_control` placement
as the v1 single-marker code. So:
- 1-chunk workflows are completely unchanged.
- All existing single-chunk tests in the suite pass unchanged.
- All single-chunk assertions like `sent[-1]["cache_control"] == {...}`
  remain correct.

The only test that needed an assertion change was the one explicitly
testing 3-chunk Anthropic placement.

## Deviations from the plan

### Intentional improvements

#### `assert` → `raise ValueError`

The plan specified using `assert n_rendered_chunks >= 1` to enforce the
caller contract. Ruff's `S101` rule flagged this as a security/style
violation (asserts disappear under `-O` flag in production Python).
Switched to:

```python
if n_rendered_chunks < 1:
    raise ValueError(
        "compute_marker_chunk_indices requires n_rendered_chunks >= 1 — "
        "the caller (_build_system_blocks) must guard the empty list."
    )
```

Same contract enforcement, lint-clean. The test
`test_raises_on_empty_rendered` was updated to expect `ValueError`
(with `match="n_rendered_chunks >= 1"`) instead of `AssertionError`.

#### Dropped two redundant tests

The plan listed `test_empty_returns_empty` and `test_empty_with_prewarm`
asserting an empty-tuple return for `n_rendered_chunks=0`. These are
inconsistent with the contract enforcement the SAME plan mandates (a
defensive empty return is exactly what the contract was meant to
prevent). Replaced with one positive test confirming the raise.
Coverage is equivalent.

#### Reframed `test_prewarm_channel_independent_of_declared_channel`

The plan called for a test where "declared survives + prewarm
stripped". The strip walker's cross-channel cumulative measurement
makes this structurally unreachable. Renamed to
`test_prewarm_channel_suppresses_when_any_marker_survives` and tested
the same suppression rule on a prewarm-only multi-marker configuration
(early below threshold, terminal above). Comments in the test
document the structural-rarity reason for the renaming.

### Quality fixes after first pass

#### Agent-facing prose: rewritten to drop internal vocabulary

First-pass guide additions used phrases like "multi-breakpoint
placement", "terminal marker", and "single-terminal-marker behavior" —
these are pflow-internal jargon. A fresh CLI agent author reading them
would have no anchor.

Rewritten to address agents who use the CLI to build workflows (not
contributors reading source):

- "Multi-breakpoint placement" → "per-chunk caching" / "each chunk's
  cache covers everything declared before it".
- "Terminal marker" → "the end of the full cached prefix remains
  cacheable as a single block".
- "Single-terminal-marker behavior" → "as a single cached prefix, not
  per-chunk".
- "Set the relevant API base via your provider configuration instead"
  (vague) → "address the model directly with `model: anthropic/claude-...`
  and provide `ANTHROPIC_API_KEY`" (concrete).

The example fixture's H1 description was similarly cleaned ("Demonstrates
multi-breakpoint prompt caching" → "Declares three `## Cache` chunks
ordered stable-to-volatile").

#### Fixture cache-chunk mis-parse

Initial example workflow had `Session context for ${session_id}:` inside
the `## Cache` block prose. The parser treated `${session_id}` as its
own chunk, yielding 4 declared chunks with `session_id` unused. Fixed
by removing the inline reference; `session_id` flows only through the
shell node, not the cache.

#### Monkeypatch tests refactored

Two suppression tests originally used `pytest.MonkeyPatch()` directly
with `try/finally monkey.undo()` boilerplate because they needed
per-text-value token counts (not constants). After review, switched to
the standard `monkeypatch: pytest.MonkeyPatch` fixture parameter and
called `monkeypatch.setattr` / `_stub_token_counter` directly. Matches
the style of every other test in the file.

## Test counts at each gate

| Gate | Tests | Result |
|---|---|---|
| `TestComputeMarkerChunkIndices` | 15 | All pass |
| `TestGetBreakpointBudget` | 5 | All pass |
| `TestMultiBreakpointPlacement` | 10 | All pass |
| `TestStripBelowMinSuppression` | 4 | All pass |
| `test_cached_system_renders_all_multi_breakpoint_markers` | 1 | Pass |
| `test_prompt_cache_rendering.py` (full) | 62 | All pass |
| `test_prompt_cache_below_min_runtime.py` (full) | 16 | All pass |
| `test_prompt_cache_hash.py` (golden baseline) | 16 | All pass unchanged |
| `test_cache_analysis_renderers.py` + `test_cache_analysis_analyze.py` | 377 | All pass |
| `make check` | — | Clean |
| `make test` (full suite) | 6998 passed, 1 skipped | Clean |

## Algorithm cheat-sheet (recorded for future readers)

```
n = rendered chunk count (post-ABSENT-filter)
budget = 4 if provider == "anthropic" else 1
if prewarm_consumes_slot: budget -= 1

if budget <= 1:           return (n - 1,)                  # terminal only
if n <= budget:           return tuple(range(n))           # all individual
                          return (*range(budget - 1),      # first (budget-1)
                                  n - 1)                    # plus terminal
```

Worked examples:
- Anthropic, 3 chunks, no prewarm → `(0, 1, 2)` — every chunk.
- Anthropic, 4 chunks, no prewarm → `(0, 1, 2, 3)` — every chunk.
- Anthropic, 5 chunks, no prewarm → `(0, 1, 2, 4)` — first three + terminal (chunk 3 merged in).
- Anthropic, 7 chunks, no prewarm → `(0, 1, 2, 6)` — first three + terminal.
- Anthropic, 5 chunks, prewarm=True (budget=3) → `(0, 1, 4)`.
- Anthropic, 1 chunk, no prewarm → `(0,)`.
- OpenAI/Gemini, any N → `(N-1,)` — terminal only.
- OpenAI, 3 chunks, prewarm=True (budget collapses to 0, then `<= 1` branch) → `(2,)` — still terminal.

## Loose ends (intentionally skipped, documented for follow-up)

### Operational verification (requires live API)

These were called out in the plan as "recommended" sanity checks but
need credentials to run:

1. **Real Anthropic smoke**: `uv run pflow examples/core/prompt-caching-multi-chunk.pflow.md` against a live Anthropic API key, then `grep '"cache_control"' ~/.pflow/debug/workflow-trace-*.json | wc -l` expecting `>= 3`. The unit + integration tests cover the placement algorithm thoroughly, but no automated test exercises the full live wire format.

2. **`pflow analyze-cache` before/after diff**: compare analyzer JSON for a known baseline workflow before vs. after the change. The 377 cache_analysis regression tests provide programmatic coverage; the explicit JSON diff was not run.

### Out-of-scope items for separate GH issues (per user instruction, deferred)

The plan's "Out of Scope / Deferred to GH Issues" section listed 7
follow-up items. User explicitly said to handle GH issue creation
separately:

1. Per-marker telemetry in `pflow report` (derive per-marker
   hit/miss from `cache_read_input_tokens`).
2. Cross-node analyzer recommendations (recommend chunk reorderings
   based on shared-prefix patterns).
3. Routed-Anthropic diagnostic (`cache.routed-provider-degraded`
   when an Anthropic-looking model name routes through a proxy
   prefix). Currently covered by a guide doc note only.
4. Convention enforcement (advisory based on observed chunk-change
   frequencies from trace history).
5. Budget exhaustion advisory (`cache.too-many-chunks-for-provider`
   INFO when `n_rendered_chunks > budget`).
6. Per-chunk TTL override (mix 1h stable prefix + 5m volatile tail).
7. Per-marker analyzer threshold modeling (predict per-EARLIER-marker
   activation rates).

## Pre-implementation audit (recorded for reproducibility)

Per the plan, ran the stale-vocabulary grep BEFORE writing code:

```
$ grep -rn 'single-breakpoint\|LAST chunk only\|LAST block only\|single cache_control\|single provider cache breakpoint\|DD#11' src/ tests/ architecture/ docs/
src/pflow/core/llm_client.py:236-237        single-marker contract comment
src/pflow/core/cache_render.py:183          _build_cache_control_marker docstring
src/pflow/core/cache_analysis/CLAUDE.md:184 cross-boundary recs phrasing
src/pflow/nodes/llm/llm.py:790-791          _build_system_blocks docstring
tests/test_nodes/test_llm/test_prompt_cache_rendering.py:1   header docstring
tests/test_nodes/test_llm/test_prompt_cache_rendering.py:208 inline comment
```

Plus `cache_analysis/analyze.py:6171` and
`tests/test_core/test_cache_analysis_per_id_emission.py:2868` flagged
by the plan directly. All 8 sites updated.

Post-implementation re-grep returns zero hits for any stale phrase.

JSON fixture audit (`grep -rn '"cache_control"' tests/fixtures/ examples/`)
returned zero hits — no committed JSON files embed wire-format markers
that would drift under multi-marker placement.

## Risk register (final state)

| Risk | Status | Evidence |
|---|---|---|
| Hash drift breaking memo cache | Prevented | Hash side untouched. `test_golden_baseline_hashes_match` passes unchanged. |
| 4-marker API limit exceeded | Prevented | `compute_marker_chunk_indices` enforces budget. Prewarm conservatively reserves slot. Both tested. |
| Non-Anthropic providers break | Prevented | Algorithm collapses to single terminal marker for budget ≤ 1. Tested for openai/gemini/None/unknown. |
| Cross-workflow SUM in analyzer breaks | Prevented | Markers cover contiguous prefixes in declaration order; per-call denominator unchanged. 377/377 analyzer tests pass. |
| `_strip_below_min_cache_markers` fails | Prevented | Function was already plural-aware; suppression added without changing strip behavior. 16/16 strip tests pass. |
| Warning noise on multi-chunk workflows | Mitigated | Suppression-when-any-marker-survives. Locked by `TestStripBelowMinSuppression`. |
| OpenRouter/Bedrock/Vertex silent degradation | Documented | Guide section with concrete fix. Runtime diagnostic deferred to GH follow-up. |
| Stable-to-volatile convention not enforced | Documented | Guide explains; multi-marker is never net-negative vs single-marker. |
| Heterogeneous batch with prewarm — sub-optimal per-item placement | Documented | Conservative slot reservation never exceeds API cap. `_build_system_blocks` comment + dedicated test. |
| Stale docstrings (8 sites) | Resolved | All updated in lockstep with code change. |
| Trace fixture drift | Prevented | Audit returned zero hits. |

## Reference for future readers

- Algorithm: `src/pflow/core/cache_render.py::compute_marker_chunk_indices`
- Budget table: `src/pflow/core/llm_capabilities.py::get_breakpoint_budget`
- Placement loop: `src/pflow/nodes/llm/llm.py::_build_system_blocks` (chunk_block_offset + marker_indices loop)
- Strip suppression: `src/pflow/nodes/llm/llm.py::_strip_below_min_cache_markers` (per-channel "any surviving marker" check)
- Test matrix: `tests/test_core/test_cache_render.py::TestComputeMarkerChunkIndices`
- End-to-end placement tests: `tests/test_nodes/test_llm/test_prompt_cache_rendering.py::TestMultiBreakpointPlacement`
- Strip-suppression unit tests: `tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py::TestStripBelowMinSuppression`
- Agent-facing guide: `src/pflow/guide/features/prompt-caching.md` — sections "Order chunks stable-to-volatile" and "Anthropic via proxies"
- Example fixture: `examples/core/prompt-caching-multi-chunk.pflow.md`

## Anthropic documentation reference (verified at implementation time)

Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching

Key facts:
- Max 4 `cache_control` breakpoints per request (API returns 400 if exceeded).
- Pricing is delta-based on writes — adding more breakpoints does NOT cost more.
- Reads: longest matching prefix wins via a 20-block lookback window.
- Min tokens applies per-breakpoint cumulatively from prompt start (matches existing `_strip_below_min_cache_markers` semantics).

So multiple breakpoints are strictly an improvement: the write side is
free, and the read side gains independence (a change in chunk[N] no
longer invalidates the cached portion through chunk[N-1]).

---

# Follow-up: code review pass (3 specialist agents + 1 verifier)

After the initial commit landed, ran `/code-review` with the 3 most relevant
agents in parallel: **review-impact-completeness**, **review-silent-failures**,
**review-feature-interactions**. A targeted **pflow-codebase-searcher** agent
verified two analyzer-side claims before classification.

## Verdicts

| Class | Count | Notes |
|---|---|---|
| Critical | 0 | No correctness bugs found. |
| Confirmed (action taken) | 6 | All addressed in the follow-up commit. |
| Confirmed but deferred | 3 | GH issue work, per user instruction to handle separately. |
| Disputed | 4 | See below for evidence. |

## Disputed findings (with evidence)

**Cost projection under-estimated 4× under multi-marker** — feature-interactions
claimed Anthropic charges per-write per scope so 4 markers = 4 × cache_creation
cost. Verifier confirmed `core/cache_analysis/cost_estimation.py:281-318, 494-593`
uses `row.cache_active.tokens_estimated` (cumulative-through-terminal) once
per call with a single `write_rate × tokens` math. This matches Anthropic's
documented delta-pricing — writing markers at [0..K] and [0..N] in the same
request charges deltas, not duplicates. The reviewer mis-modeled the pricing.

**Parallel batch heterogeneous ABSENT × OpenAI sticky routing** — flagged
as a multi-marker regression. Pre-existing behavior (ABSENT-filter and
per-item rendering existed before this commit). Not introduced.

**`cache_skipped_reason` partial-survival** — reviewer noted "This is actually
correct behavior" inline; the observability gap is real but is covered by
deferred follow-up #410 (per-marker telemetry).

**Trace report `default=str` for hypothetical nested markers** — markers
today are flat. The implementation comment already documents the migration
trigger to `copy.deepcopy`. Adding a test for a hypothetical state isn't
useful; the new deepcopy-aliasing regression test (item #1 below) covers
the migration trigger.

## Follow-up commit content

Six in-commit fixes (3 tests, 3 docstring/comment touch-ups):

1. **`test_mutating_one_markers_top_level_does_not_leak_to_others`** — behavioral
   guard for the shallow-copy footgun documented at `_build_system_blocks:872-875`.
   Today markers are flat, so this tests the simpler top-level case; the
   inline comment documents the deepcopy migration trigger for nested markers.

2. **Centralization docstrings tightened across 3 sites**:
   - `_compute_marker_chunk_indices`: added "Scope of centralized placement"
     block explaining `_build_user_message_blocks` is a parallel emitter by
     construction; the 4-marker cap is shared via `prewarm_consumes_slot`.
   - `_build_user_message_blocks`: inline cross-reference at the
     `cache_control` emit site.
   - `_build_openai_cache_kwargs`: replaced "last block" framing with the
     explicit budget-1 + `_compute_marker_chunk_indices` derivation.

3. **`_strip_below_min_cache_markers` docstring**: added "Asymmetry to be
   aware of" + "`*_measured_tokens` semantics" paragraphs documenting the
   cross-channel cumulative vs per-channel suppression interaction, and the
   smallest-stripped-scope semantics of the measured tokens field.

4. **`_compute_marker_chunk_indices` body**: inline comment on the `budget <= 1`
   guard explaining the budget=0 hypothetical (when a future budget=1 provider
   also debits a prewarm slot — still emits terminal marker; revisit if a
   future provider has a strict shared cap).

5. **`test_cross_channel_cumulative_prewarm_marker_survives_via_system_accumulation`**
   — locks the cross-channel cumulative + per-channel suppression asymmetry
   newly documented in #3 above. 3 declared (cum 400/800/1200, threshold 1024,
   so 0,1 strip and 2 survives) + prewarm marker (cum 1250, survives because
   the system-channel already crossed threshold).

6. **`test_openai_prompt_cache_key_pinned_hash_for_known_content`** — pins
   the OpenAI MD5 hex (`180791359f4acd84630ff34114e4bf39`) for known cache
   content. Trips loudly if `get_breakpoint_budget("openai")`,
   `_build_cache_control_marker`, `_compute_marker_chunk_indices` for
   budget=1, or the deterministic-JSON serialization changes in a way that
   would silently invalidate sticky routing across deploys.

## Additional cleanup (after follow-up commit)

Three more touch-ups landed after the review pass:

**A. Function renamed: `compute_marker_chunk_indices` → `_compute_marker_chunk_indices`.**
Aligns with the project convention for one-call-site private helpers in
`cache_render.py` (`_resolve_chunk_value`, `_build_cache_control_marker`,
`_resolve_static_prefix_for_cache`). Signals the private-contract intent —
future callers can't sneak in without acknowledging the empty-input guard.

**B. End-to-end `WorkflowRunner` test** at
`tests/test_integration/test_prompt_cache_multi_chunk.py`. Drives the
committed `examples/core/prompt-caching-multi-chunk.pflow.md` through
`WorkflowRunner.run()` with the mock LLM and asserts that both consumer
LLM nodes (`summarize`, `translate`) reach the adapter with 3 system blocks,
each carrying a `cache_control` marker. Closes the cross-layer test gap
that unit-level placement tests don't cover.

**C. This addendum.**

## Confirmed but deferred (filed for separate GH follow-up)

1. **Routed-Anthropic silent degradation** — both reviewers flagged. Currently
   covered by the guide doc; deferred to GH #409 per the commit message.
   Real user-visible silent failure: a workflow with `model:
   openrouter/anthropic/claude-sonnet-4-5` and 4 declared chunks silently
   gets 1 marker. Fix would emit an INFO diagnostic
   `cache.routed-provider-degraded` from `_compute_marker_chunk_indices` when
   `provider_name is None AND n_rendered_chunks > 1 AND bare_model matches
   /anthropic|claude-/`. ~20 LOC + 3-4 tests + warning-catalog entry.

2. **`_attribute_root_cause` priority under multi-marker.** Verifier confirmed
   the function reads ONLY `chunks_skipped` (`analyze.py:7983-8008`); zero-cache
   telemetry and below_min are not consulted. When suppressed-below-min +
   ABSENT chunks coexist, the analyzer attributes to ABSENT branches —
   pointing the user at the wrong root cause. Pre-existing design choice;
   multi-marker just makes "suppressed below_min + ABSENT" the more common
   case. Worth filing as analyzer follow-up.

3. **Storage-mode-shared × parallel batch × `## Cache` UNSUPPORTED COMBO.**
   Pre-existing silent-but-benign behavior documented in `runtime/CLAUDE.md`.
   Multi-marker widens the corrupted-state surface (N possible marker
   topologies vs. just N positions). No current consumer reads parent's
   `__pflow_cache_render__` after a parallel batch, so the corruption is
   unobservable today. File the runtime guard before Task 160's analyzer
   refactor lands and might add such a consumer.

## Final state — verification

Both commits combined:

| Gate | Result |
|---|---|
| `make check` | clean (ruff/ruff-format/mypy/deptry) |
| Targeted tests (cache_render, capabilities, hash, rendering, below-min, batch, multi-chunk integration) | 198/198 pass |
| `make test` (full suite) | 7002 passed, 1 skipped |
| Pre-implementation grep audit (stale single-marker phrases) | zero hits |
| JSON fixture audit (`'"cache_control"'` in committed fixtures) | zero hits |
| Hash byte-identity (`test_golden_baseline_hashes_match`) | pass unchanged |

## Test counts — running total

Initial commit (76334d0): +39 new tests across 5 files.
Follow-up commit (review pass fixes): +3 tests (deepcopy-aliasing,
cross-channel cumulative, OpenAI MD5 pin).
This cleanup pass: +1 end-to-end test through `WorkflowRunner`.

Total new test coverage attributable to multi-breakpoint work: **43 tests**.

## Lessons recorded for future readers

1. **The "fully centralized" framing was technically false.** `_build_user_message_blocks`
   is a parallel `cache_control` emission site (single-marker by construction).
   Both reviewer + this addendum now document the constraint explicitly.

2. **One reviewer was confidently wrong about Anthropic's pricing semantics.**
   The cost-projection 4×-under-estimate claim was a categorical error
   contradicting both the implementation plan's pricing citation and the
   actual Anthropic docs. Verification before classification caught this —
   trusting the reviewer's verdict on the surface would have triggered a
   wrong analyzer-refactor.

3. **The deepcopy comment was paper without a test.** The reviewer was
   right: a single behavioral test (mutate one marker, assert neighbors
   unchanged) makes the migration trigger enforceable.

4. **The strip walker's cross-channel cumulative vs per-channel suppression
   asymmetry is subtle.** Documenting it explicitly in the function docstring
   prevents future contributors from "fixing" the cumulative to reset
   per-channel — which would silently break Anthropic's documented
   "cumulative through preceding content" semantics.
