# Plan: Fix L-1 (cost+rows) + L-2 + L-12 + L-3 — Trace-Mode Per-Call Model & Cost Projection

## Status (post-review, post-L-10/L-11)

The L-10/L-11 agent landed `requires_complete_trace` catalog flag + `final_status` discriminator + `truncated` vocab (commit on 2026-05-09). Their fix closed: L-10, L-11, A-3, B-18, and the HEADER aspect of L-1 (the scale line now shows "using gemini/..." instead of "no model resolved" when `trace_coverage="complete"` lets observed_models flow into `models_in_use` via the union at analyze.py:3926).

**Still open (this plan addresses)**:
- **L-1 cost projection** — `_partition_priced_rows` (cost_estimation.py:421) still excludes rows when `not row.model`. With clean env, rows have `model=""` from IR, get tagged `unresolved_model`, projections fall to `None`, `actual_vs_no_cache_delta` renders unavailable.
- **L-1 per-call rendering** — `_format_per_call_row` (render_text.py:1089) still uses `row.model` directly. Clean-env rows render `model=` + 35 spaces.
- **L-2** — Per-call rows show IR-declared model when settings.default_model differs from trace's observed model. Cost off by ~10× when IR=haiku and trace=gemini.
- **L-12** — Same root as L-2: `event.llm_call.model` known to analyzer but not used for per-call rendering.
- **L-3** — `Actual trace delta:` line falls through to "unavailable" because L-1's cost projection is broken; needs to populate AND be the primary line in trace mode.

## Context

Task 159 (prompt caching) baseline audit found that the analyzer ignores trace-observed model evidence in cost projection and per-call rendering, even when the L-10/L-11 fix lets observed flow into the workflow-header summary. The fix is to substitute observed model into `row.model` at row construction time when trace evidence is consistent — every downstream consumer (cost projection, threshold checks, tokenization, rendering) reads `row.model` and gets correct behavior automatically. A workflow-level header disclosure surfaces IR-vs-observed divergence (no per-row repetition). The existing `Actual trace delta:` line — which already computes `no_cache - actually_paid` — populates correctly once cost projections fire AND is moved to the primary position with relabel `Actual savings (this run):`.

## Preconditions

L-10/L-11 must have landed. Verify before starting:

```bash
grep "requires_complete_trace" src/pflow/core/cache_analysis/warning_catalog.py  # must match
grep "_filter_trace_dependent_warnings" src/pflow/core/cache_analysis/analyze.py  # must match
grep "trace_coverage_truncated" src/pflow/core/cache_analysis/analyze.py  # must match (renamed from "trace_coverage_partial")
```

If any miss, stop — rebase first.

After verifying, get fresh line numbers since L-10/L-11 may have shifted ranges:

```bash
grep -n "^def _build_per_call_row\|^def _build_summary\|^def _render_header\|^def _format_per_call_row\|^def _render_summary_deltas\|^def _partition_priced_rows" src/pflow/core/cache_analysis/*.py
```

Use the line numbers returned — the line numbers in this plan are pre-L-10/L-11 references.

## User decisions (locked)

1. **No `model_is_heterogeneous` promotion for multi-observed**. Keep that flag semantically pure (IR-declared `${...}` only). For trace-only multi-observed (IR was single-model but trace shows ≥2 distinct models on one node): set `row.model = ""` so cost projection excludes the row, AND render `<varies>` via a derived check (`len(observed_models) > 1`) at the per-call display site. This avoids misleading "model varies per batch item" prose at `_format_scale_line` (which fires for IR-heterogeneous nodes only). **Reviewer-driven correction from initial plan.**
2. **Divergence UX**: ONE workflow-level disclosure in the header when IR-declared model is not in observed. **No per-row annotation.**
3. **Fix scope**: L-1 (cost+rows) + L-2 + L-12 + L-3 as one coordinated batch.
4. **L-3 treatment**: reorder existing `Actual trace delta:` line to FIRST in delta block in trace mode + relabel to `Actual savings (this run):`. Both occurrences (priced site + unavailable-fallback site) get the relabel.
5. **Truncated-trace label**: stays unqualified — `Actual savings (this run):` (NOT `(executed)` qualified). Rationale: cost is paid regardless of whether the workflow finished; the qualifier would mislead.

---

## Task list (atomic, in order)

### Task 1: Effective-model substitution at row construction

**File**: `src/pflow/core/cache_analysis/analyze.py`
**Function**: `_build_per_call_row`
**Pre-L-10/L-11 line range**: 1380-1520 (verify post-rebase)

**Current code shape** (lines 1394-1401 + ~1489):

```python
explicit = node.get("params", {}).get("model") or node.get("model")
model_is_heterogeneous = isinstance(explicit, str) and "${" in explicit
if model_is_heterogeneous:
    model = ""
elif explicit:
    model = str(explicit)
else:
    model = get_default_workflow_model() or ""

# ... ~90 lines later ...

observed_models = tuple(sorted({
    str(call.get("model")) for call in trace_llm_calls if call.get("model")
}))
```

**Replace with**:

```python
explicit = node.get("params", {}).get("model") or node.get("model")
model_is_heterogeneous = isinstance(explicit, str) and "${" in explicit

# Compute observed_models early so it can drive effective-model resolution.
# trace_llm_calls is in scope (function parameter — no signature change).
observed_models = tuple(sorted({
    str(call.get("model")) for call in trace_llm_calls if call.get("model")
}))

# Effective-model resolution: trace truth wins when present and unambiguous.
# - Heterogeneous IR (`${...}` template) stays heterogeneous.
# - Multi-observed (trace shows ≥2 distinct models on one node): set model=""
#   so cost projection excludes as `unresolved_model`. Per-call rendering
#   shows `<varies>` via a derived check (Task 4). NOT promoted to
#   `model_is_heterogeneous=True` — that flag stays bound to IR-declared
#   `${...}` so `_format_scale_line`'s "model varies per batch item" prose
#   only fires when the IR actually declared variance.
# - Single observed model: that IS what ran. Use for pricing, thresholds,
#   rendering. IR-vs-observed divergence surfaced once at the header (Task 4).
if model_is_heterogeneous:
    model = ""
elif len(observed_models) > 1:
    model = ""
elif len(observed_models) == 1:
    model = observed_models[0]
elif explicit:
    model = str(explicit)
else:
    model = get_default_workflow_model() or ""
```

**Then DELETE** the duplicate `observed_models = ...` computation at the original line ~1489. Keep adjacent variables (`trace_cache_creation`, `trace_cache_read`, `observed_call_count = len(trace_llm_calls)`) intact. The constructor call at PerCallRow(..., observed_models=observed_models, ...) reads the new earlier-computed local.

**Manual verification of the deletion** (no test catches a silent dead-code reassignment — `make check`'s ruff config doesn't flag duplicate variable assignment):
```bash
grep -n 'observed_models = tuple(sorted' src/pflow/core/cache_analysis/analyze.py
```
Must return EXACTLY ONE match (the new earlier-computed line). If two matches, the duplicate at line ~1489 wasn't deleted — the second assignment overwrites the first with the same value (functionally OK, structurally wrong; tech debt).

**Mutation contracts** (Task 8 tests verify):
- Removing `len(observed_models) == 1` branch → L-1 single-observed test fails (row.model stays "" or IR).
- Removing `len(observed_models) > 1` branch → multi-observed test fails (row.model gets a wrong single value).
- Reordering branches (e.g., putting `elif explicit:` before `elif len(observed_models) == 1`) → L-2 test fails (IR wins instead of observed).

### Task 2: Add `ir_default_model` field to `AnalysisSummary`

**File**: `src/pflow/core/cache_analysis/analyze.py`
**Class**: `AnalysisSummary`
**Pre-L-10/L-11 line range**: 355-440

**Add field** after `observed_models_in_trace` (currently line 413):

```python
# IR-resolved default model captured at analysis time (settings.default_model
# OR auto-detected, whichever `get_default_workflow_model()` returns). Used by
# the header to disclose when IR's declared default differs from
# observed_models_in_trace (L-2 scenario: settings=haiku but trace=gemini).
# None when no settings.default_model and no auto-detected key.
ir_default_model: str | None = None
```

**JSON shape**: emitted unconditionally (default `None`). Every JSON baseline drifts — see Task 9 for scope.

### Task 3: Compute `ir_default_model` once per analyze() invocation

**File**: `src/pflow/core/cache_analysis/analyze.py`
**Function**: `analyze()` (the top-level entry point)

**Capture once at analyze() entry, pass to `_build_summary` as kwarg.** Avoids the implicit "called once" assumption and prevents settings-file re-reads. The value is invariant within an analysis run.

```python
# At top of analyze():
ir_default_model = get_default_workflow_model()
```

**Pass through to `_build_summary`** (extend signature with `ir_default_model: str | None`). At the AnalysisSummary constructor inside `_build_summary`, add the kwarg:

```python
return AnalysisSummary(
    ...,
    observed_models_in_trace=observed_models,
    ir_default_model=ir_default_model,  # NEW
    ...
)
```

**Verify import** at top of `analyze.py` line 56: `from pflow.core.llm_config import get_default_workflow_model` — already exists.

### Task 4: Per-call render: `<varies>` for multi-observed + header divergence disclosure

**File**: `src/pflow/core/cache_analysis/render_text.py`

**(a) Per-call model column** — current code (line 1089):

```python
model_display = "<varies>" if row.model_is_heterogeneous else row.model
```

**Replace with**:

```python
# Multi-observed (trace shows ≥2 models on one node) renders <varies> too.
# IR-declared `${...}` already sets model_is_heterogeneous; trace-only multi
# is detected via observed_models length — keeping the flag semantically pure
# (Task 1 rationale).
if row.model_is_heterogeneous or len(row.observed_models) > 1:
    model_display = "<varies>"
else:
    model_display = row.model
```

The existing `observed_models=...` annotation at line 1091 already gates on `model_is_heterogeneous OR len(observed_models) > 1` — works without change for both cases.

**(b) Header disclosure** — `_render_header` at the existing `Observed models:` line (currently line 144-145):

```python
if s.observed_models_in_trace:
    lines.append(f"  Observed models: {', '.join(s.observed_models_in_trace)}")
```

**Append after** with the disclosure (only when divergent):

```python
# IR-vs-observed divergence disclosure (L-2). Renders ONLY when:
# - Trace evidence exists (non-empty observed_models_in_trace)
# - AND IR-resolved default model is non-empty
# - AND the IR-resolved model is NOT among observed
# Common case (IR matches observed, or no IR resolution): no line.
if (
    s.observed_models_in_trace
    and s.ir_default_model
    and s.ir_default_model not in s.observed_models_in_trace
):
    lines.append(
        f"  IR/settings declares: {s.ir_default_model} "
        f"(overridden by trace evidence)"
    )
```

### Task 5: Reorder + relabel TWO `Actual trace delta:` sites (L-3)

**File**: `src/pflow/core/cache_analysis/render_text.py`
**Function**: `_render_summary_deltas`
**Pre-L-10/L-11 line range**: 458-498

**Current code at line 478**:

```python
lines.append(f"  Actual trace delta:         {actual}")
```

**Current code at line 487 (unavailable fallback)**:

```python
lines.append(f"  Actual trace delta:         unavailable (projection excludes {paths})")
```

**Both lines have hardcoded 9-space padding (28 chars total)** — already misaligned with first/rerun lines using `:29s` (29 chars). Plan claim of "29-char-padded" was wrong; this fixes the latent misalignment AND applies the relabel uniformly.

**Replace both** with consistent `:29s` formatting:

```python
# Line 478 priced site:
actual_label = "Actual savings (this run):"
lines.append(f"  {actual_label:29s} {actual}")

# Line 487 unavailable-fallback site:
lines.append(f"  {actual_label:29s} unavailable (projection excludes {paths})")
```

**Reorder for trace mode**: in `_render_summary_deltas`, the assembled `lines` should put `Actual savings (this run):` BEFORE `First-run delta:` and `Rerun delta:` when in trace mode. Identify trace mode via:

```python
in_trace_mode = s.evidence_scope in {"complete_trace", "truncated_trace_executed_subset"}
```

Implementation: compute the actual-savings line first, then prepend to `lines` if rendered AND `in_trace_mode`. In static mode (`evidence_scope == "static_analysis"`), keep existing positional order (actual line typically suppressed anyway).

**Mutation contracts**:
- Reverting reorder → Test 8 line-index assertion fails.
- Missing the line-487 relabel → Test 9 fails (unavailable case still shows "Actual trace delta:").

### Task 6: Add `ir_default_model` to JSON output

**File**: `src/pflow/core/cache_analysis/render_json.py`
**Function**: summary builder (search: `grep -n "observed_models_in_trace" render_json.py` — emitted at line ~97)

**Add new key** adjacent to `observed_models_in_trace`:

```python
"ir_default_model": summary.ir_default_model,  # may be null
"observed_models_in_trace": list(summary.observed_models_in_trace),
```

**JSON_FORMAT_VERSION**: stays at `"4.1"`. Additive within minor.

**Update the version-history docstring** in `cache_analysis/__init__.py` (file HAS one — append a one-liner at the existing 4.1 history):

```
"4.1: Added summary.ir_default_model (additive) — workflow-level disclosure of IR-resolved default when divergent from observed_models_in_trace."
```

### Task 6.5: Update MCP tool docstring

**File**: `src/pflow/mcp_server/tools/execution_tools.py`
**Lines**: 371-377 (the JSON shape documentation)

**Verify**: `grep -n "observed_models_in_trace\|format_version\|summary fields" src/pflow/mcp_server/tools/execution_tools.py`

The docstring at line 371-377 documents `format_version` policy + top-level keys. **Add `ir_default_model`** to whatever summary-field enumeration appears (search for `observed_models_in_trace` if listed). Mirror the version-history note from Task 6.

### Task 7: Verify all `row.model` consumers transitively correct

**Architectural payoff of substitute-at-construction**: every consumer reading `row.model` gets correct effective-model behavior automatically. Below are ALL `row.model` consumer sites (~19 total per impact-completeness review). **Do NOT edit these — verify only.**

| File:line | Function | Behavior after Task 1 |
|---|---|---|
| `cost_estimation.py:421-435` | `_partition_priced_rows` | Pricing decisions use effective model. L-1 + L-2 fix center. ✓ |
| `cost_estimation.py:478` | `_aggregate_with_cache_projection` cohort key | Effective-model cohorts split correctly when trace observed mismatch. ✓ |
| `cost_estimation.py:513` | `_aggregate_first_run_savings` cohort key | Symmetric to 478. ✓ |
| `analyze.py:1730, 1806-1864` | Token estimation calls | Tokenizer family uses effective. **Numerical drift expected on rows where IR≠observed** — see Task 9 audit note. ✓ |
| `analyze.py:2095` | `_build_suggested_chunks_and_assignments` | First-row model for greenfield discovery. ✓ |
| `analyze.py:2200-2225` | `_threshold_entry_for_node` | Threshold via `get_min_cache_tokens(effective)`. **Writes `entry["model"]` consumed by `render_text.py:778` (suggested-block) AND `render_json.py:206` (per_node_thresholds JSON)** — JSON field changes from IR-declared to effective; baselines drift. ✓ |
| `analyze.py:2307` | `_consolidate_to_root_advisories` representative model | `next((row.model for row in rows if row.model), "")` picks effective. ✓ |
| `analyze.py:2546` | `_detect_model_cache_fragmentation` cohort key | Fragmentation grouping by effective model — better behavior than IR. ✓ |
| `analyze.py:2617` | `_homogeneous_model_for_system_group` | Effective. ✓ |
| `analyze.py:2658` | `_group_prompt_cache_rows_by_model` | Write-penalty grouping by effective. ✓ |
| `analyze.py:2778-2786` | `_single_call_write_penalty` | Pricing + thresholds at effective rates. ✓ |
| `analyze.py:2864-2867` | `_emit_padding_advisories` | Padding savings at effective rates. ✓ |
| `analyze.py:3010` | `_savings_for_shared_ref` | Token savings at effective rates. ✓ |
| `analyze.py:3920-3933` | `static_models` aggregation | `static_models` set now contains effective. Union with `observed_models` is idempotent (effective IS observed in trace mode). ✓ |
| `analyze.py:4154-4157` | `_unavailable_models_by_workflow` | Reports observed unpriced models in trace mode (correct improvement). ✓ |
| `analyze.py:917-935` | `_collect_ir_static_llm_models` | UNTOUCHED — IR walker, doesn't read `row.model`. Drift gate (`_trace_aligns_with_ir`) preserved. ✓ |
| `analyze.py:3551` | `_emit_discrepancy_diagnostics` | Bypasses `row.model`; uses `llm_call.get("model")` from trace event. Unaffected. ✓ |
| `render_text.py:1089` | `_format_per_call_row` | Updated by Task 4(a). ✓ |
| `render_json.py:214` | per-call `model` JSON field | Emits effective directly. ✓ |

### Task 8: Add regression tests (production-shape — Pitfall #19 defense)

**File**: `tests/test_core/test_cache_analysis_analyze.py`

**Patch idiom** — both `sys.modules[...]` and `importlib.import_module(...)` are used in this file (12 vs 6 occurrences). Use `sys.modules[...]` for new tests to match the dominant pattern:

```python
import sys
analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
```

**ALL tests must drive `analyze(...)` end-to-end** with real workflow IR and real trace fixtures (Pitfall #19 defense). Reference gold standard: `test_dynamic_batch_trace_preserves_observed_model_truth` at line 1010-1083.

**Test 1**: `test_observed_model_replaces_ir_when_trace_consistent`
- Setup: clean env (`get_default_workflow_model → None`), workflow IR with NO `model:` key on the LLM node, trace with single observed `gemini/gemini-2.5-flash`.
- Assert at top of test: `assert ir["nodes"][0]["params"].get("model") is None` (defensive — confirms scenario hits the no-explicit + observed-fallback path).
- Drive: `analyze(...)` end-to-end with real trace fixture written to `tmp_path`.
- Assert: `row.model == "gemini/gemini-2.5-flash"`, `row.observed_models == ("gemini/gemini-2.5-flash",)`.
- Mutation contract: reverting Task 1's `len(observed_models) == 1` branch → `row.model == ""`.

**Test 2**: `test_observed_model_overrides_ir_when_mismatched`
- Setup: `get_default_workflow_model → "anthropic/claude-haiku-4-5"`, trace shows single observed `gemini/gemini-2.5-flash`.
- Drive: `analyze(...)` end-to-end.
- Assert: `row.model == "gemini/gemini-2.5-flash"` (NOT haiku).
- Assert: `analysis.summary.ir_default_model == "anthropic/claude-haiku-4-5"`.
- Mutation contract: reverting Task 1 → `row.model == "anthropic/claude-haiku-4-5"`.

**Test 3**: `test_multi_observed_sets_model_empty_without_promoting_heterogeneous`
- Setup: IR has `params.model: anthropic/claude-haiku-4-5`, trace shows two distinct observed models on one node (`gemini/a`, `gemini/b`).
- Drive: `analyze(...)` end-to-end with synthetic trace fixture.
- Assert: `row.model == ""` (excluded from pricing).
- Assert: `row.model_is_heterogeneous is False` (IR wasn't `${...}` — flag stays pure).
- Assert: `row.observed_models == ("gemini/a", "gemini/b")`.
- Assert: `"model varies per batch item"` does NOT appear in rendered text (the misleading prose only fires for IR-heterogeneous nodes via `heterogeneous_model_node_paths`, which this row is NOT in).
- Mutation contract: reverting Task 1's multi-observed branch (treat as single-observed-fallback) → `row.model == "anthropic/claude-haiku-4-5"`. Adding the misguided promotion → `row.model_is_heterogeneous is True` AND scale line gains "model varies per batch item" prose.

**Test 4**: `test_greenfield_unchanged`
- Setup: `get_default_workflow_model → "anthropic/claude-haiku-4-5"`, NO trace.
- Drive: `analyze(...)` static.
- Assert: `row.model == "anthropic/claude-haiku-4-5"`, `row.observed_models == ()`.
- Assert: `analysis.summary.ir_default_model == "anthropic/claude-haiku-4-5"`.
- Assert: row IS priceable (no `unresolved_model` exclusion in `analysis.summary.projection_exclusions`).
- Regression-gate that greenfield path still works after Task 1's reordering of branches.

**File**: `tests/test_core/test_cache_analysis_renderers.py`

**Tests 5, 6, 7 must drive `analyze(...)` end-to-end, NOT hand-construct CacheAnalysis** (Pitfall #19 defense — review-test-fidelity flagged the original plan synthetic-fixture risk).

**Test 5**: `test_header_discloses_ir_default_when_overridden_by_trace`
- Setup: `get_default_workflow_model → "anthropic/claude-haiku-4-5"`, real trace fixture observing `gemini/gemini-2.5-flash` only.
- Drive: `analyze(...)` end-to-end → `render_text(analysis)`.
- Assert: rendered text contains `"IR/settings declares: anthropic/claude-haiku-4-5 (overridden by trace evidence)"`.
- Mutation contract: reverting Task 3 → `summary.ir_default_model is None` → renderer skips disclosure → test fails.

**Test 6**: `test_header_does_not_disclose_when_ir_matches_observed`
- Setup: `get_default_workflow_model → "anthropic/claude-haiku-4-5"`, trace observes `anthropic/claude-haiku-4-5`.
- Drive: `analyze(...)` → `render_text`.
- Assert: rendered text does NOT contain `"IR/settings declares:"`.
- Mutation contract: dropping the `not in` check in Task 4(b) → test fails.

**Test 7**: `test_header_does_not_disclose_when_no_observed`
- Setup: `get_default_workflow_model → "anthropic/claude-haiku-4-5"`, NO trace (greenfield).
- Drive: `analyze(...)` → `render_text`.
- Assert: rendered text does NOT contain `"IR/settings declares:"`.
- Mutation contract: dropping the `s.observed_models_in_trace and` guard → test fails on greenfield workflows.

**Test 8**: `test_actual_savings_delta_first_in_trace_mode`
- Setup: `get_default_workflow_model → "anthropic/claude-sonnet-4-5"` (real litellm pricing), real trace fixture with one priceable LLM node, trace `final_status: "success"`, `output_tokens` populated, single observed model that has pricing → ensures `evidence_scope == "complete_trace"`, no projection_exclusions, both `actually_paid_usd` and `no_cache_hypothetical_usd` non-None.
- Drive: `analyze(...)` → `render_text(analysis)`.
- **Step 1 — guard against silent-pass**: `assert "Actual savings (this run):" in text`
- **Step 2 — assert ordering**: split text by lines; find indices of each delta label; assert `actual_idx < first_run_idx < rerun_idx` (raises if any label missing).
- Mutation contract: reverting Task 5 reorder → ordering assertion fails.

**Test 9**: `test_actual_savings_label_replaces_actual_trace_delta_both_sites`
- Setup A (priced): same as Test 8.
- Setup B (unavailable fallback): drive `analyze(...)` with a workflow whose projections fail (e.g., heterogeneous-only batch with no priceable rows; or use the lyrics-generator-style fixture with `projection_exclusions`).
- Drive both: `render_text(analysis)`.
- Assert for both: `"Actual trace delta:" not in text` AND `"Actual savings (this run):" in text`.
- Mutation contract: missing the line-487 (unavailable fallback) relabel → fixture B test fails.

**Test 10**: `test_l1_cost_projection_works_with_observed_only`
- Setup: clean env (no `default_model`), trace with consistent observed model that has pricing in litellm.
- Drive: `analyze(...)` end-to-end.
- Assert: `analysis.summary.no_cache_hypothetical_usd is not None`.
- Assert: `analysis.summary.actual_vs_no_cache_delta.kind != "unavailable"` (loosened from `== "savings"` per review-test-fidelity W-1 — match L-1 contract: cost projection works, doesn't matter whether savings/break_even).
- Assert: `row.cost_usd is not None` for the trace-sourced row.
- Mutation contract: reverting Task 1 → cost projection back to `unavailable` → kind assertion fails.

**Test 10.5**: `test_actual_savings_label_unqualified_in_truncated_trace_mode`
- Setup: trace fixture with `final_status: "failed"` AND ≥1 row with `did_not_execute_in_trace=True` → `evidence_scope == "truncated_trace_executed_subset"`. Other rows priceable so `actually_paid_usd` and `no_cache_hypothetical_usd` are non-None.
- Drive: `analyze(...)` → `render_text(analysis)`.
- Assert: rendered text contains `"Actual savings (this run):"` (NOT `"Actual savings (this run, executed):"` or any `(executed)` qualifier — locks user decision 5).
- Assert: text contains `"First-run delta (executed):"` and `"Rerun delta (executed):"` (existing behavior — those DO get qualified for truncated traces).
- Mutation contract: changing the new label to qualify with `(executed)` → assertion fails. Reverting Task 5 → `Actual trace delta:` appears instead.

**Test 11**: `test_mixed_per_node_explicit_default_and_heterogeneous_integration`
- Workflow with 3 LLM nodes:
  - Node A: `params.model: anthropic/claude-haiku-4-5` (explicit)
  - Node B: no `model:` key (defaults to `get_default_workflow_model()`)
  - Node C: `params.model: ${item.model}` (heterogeneous template)
- Setup: `get_default_workflow_model → "gemini/gemini-2.5-flash"`. Trace observes:
  - Node A → `anthropic/claude-haiku-4-5` (matches IR explicit)
  - Node B → `openai/gpt-4o-mini` (DIVERGES from default-fallback)
  - Node C → multiple per-item models (heterogeneous, expected)
- Drive: `analyze(...)` end-to-end.
- Assert: `rows["A"].model == "anthropic/claude-haiku-4-5"` (single-observed matches IR).
- Assert: `rows["B"].model == "openai/gpt-4o-mini"` (single-observed wins over IR's default).
- Assert: `rows["C"].model == ""`, `rows["C"].model_is_heterogeneous is True` (IR `${...}` preserved).
- Assert: header text contains `"IR/settings declares: gemini/gemini-2.5-flash (overridden by trace evidence)"` (default-fallback isn't in observed).
- Mutation contract: this is the L-1+L-2+heterogeneous integration scenario; any single-row regression hides here.

**Test 12 (renderers)**: `test_json_summary_includes_ir_default_model_when_set`
- Drive: `analyze(...)` with `get_default_workflow_model → "anthropic/claude-haiku-4-5"` → `render_json`.
- Assert: `payload["summary"]["ir_default_model"] == "anthropic/claude-haiku-4-5"`.

**Test 13 (renderers)**: `test_json_summary_ir_default_model_null_when_unset`
- Drive: `analyze(...)` with `get_default_workflow_model → None` → `render_json`.
- Assert: `payload["summary"]["ir_default_model"] is None`.

**Test 14 (renderers, fragmentation interaction)**: `test_fragmentation_grouping_uses_effective_model_in_trace_mode`
- Workflow with 2 LLM nodes, IR uniform (e.g., both `model: anthropic/claude-haiku-4-5`), trace observes node 1 → `gemini/a`, node 2 → `gemini/b` (different observed models).
- Drive: `analyze(...)` end-to-end.
- Assert: `cache.heterogeneous-models-fragment-cache` warning fires (rows now group by effective model = different cohorts; pre-fix grouping by IR would have shown uniform haiku → no fragmentation).
- Mutation contract: reverting Task 1 → fragmentation by IR-uniform → warning doesn't fire → test fails.

### Task 9: Re-capture affected baselines

**Two distinct drift sources**:

**(a) Per-call `model=` column drift** (text baselines): rows previously rendering empty 35-space pad or IR-declared model now render observed-when-trace-consistent. ~11 directories per searcher report:

```bash
cd .taskmaster/tasks/task_159/baseline
./regenerate.sh 01-parser-errors/03-two-vars-in-chunk
./regenerate.sh 01-parser-errors/09-prompt-body-shadows-cache
./regenerate.sh 02-validator-errors/06-cache-content-below-min-predicted
./regenerate.sh 02-validator-errors/07-unused-chunk
./regenerate.sh 02-validator-errors/08-analyze-cache-surfaces-undeclared-name
./regenerate.sh 03-analyze-cache-modes/03-steady-state-text
./regenerate.sh 03-analyze-cache-modes/06-no-trace-autoload
./regenerate.sh 03-analyze-cache-modes/08-all-rows-flag
./regenerate.sh 10-live-recordings/05-gemini-lyrics-generator
./regenerate.sh 12-real-world-lyrics-generator/01-analyze-cache-text
./regenerate.sh 12-real-world-lyrics-generator/03-analyze-cache-song-creator-text
```

**(b) JSON `summary.ir_default_model` field added unconditionally** — affects ~34+ baselines (verified: 34 baselines reference `observed_models_in_trace`, 39 reference `format_version`). Use grep-based discovery rather than hand-listing:

```bash
cd .taskmaster/tasks/task_159/baseline
for f in $(grep -rl '"observed_models_in_trace"\|"format_version"' . --include='expected-stdout.txt'); do
  case_dir=$(dirname "$f" | sed "s|^./||")
  ./regenerate.sh "$case_dir"
done
./verify.sh  # must report 65/65 passed
```

**Strict-improvement audit** before committing — check every diff line:

| Diff pattern | Action |
|---|---|
| `model=` column populated where previously empty 35-space pad | ✓ Improvement |
| `model=` column shows observed where previously showed IR-declared | ✓ Improvement (L-2) |
| `Cost without caching:` shows real number where previously `unavailable` | ✓ Improvement (L-1 cost) |
| `Actual savings (this run):` line appears as first delta in trace mode | ✓ Improvement (L-3) |
| `Actual trace delta:` → `Actual savings (this run):` (relabel) | ✓ Improvement |
| New JSON `"ir_default_model"` key | ✓ Additive |
| New header line `IR/settings declares: ... (overridden by trace evidence)` | ✓ Improvement (L-2 disclosure) |
| `tokens=`, `cacheable=`, `ratio=` values shifted on rows where IR≠observed | **EXPECTED** — tokenizer family changed (haiku→gemini etc.). Verify direction is plausible (Gemini token counts differ from Anthropic for same text). NOT a regression. |
| `per_node_thresholds[].model` JSON field changes from IR to effective | ✓ Expected per Task 7 |
| Anything DEGRADING (info disappearing, numbers getting worse without explanation) | **STOP** — investigate |

### Task 10: Update `BASELINE-AUDIT.md` Section F

**File**: `.taskmaster/tasks/task_159/baseline/BASELINE-AUDIT.md`
**Section F**: Move L-1, L-2, L-12, L-3 from MERGE-BLOCK to RESOLVED with commit hash reference. Keep source-line citations as a contract record.

### Task 11: Update `CLAUDE.md` for cache_analysis module

**File**: `src/pflow/core/cache_analysis/CLAUDE.md`

Add under "Key Components — Non-Obvious Details" → "analyze.py":

> **Effective-model semantics**: `PerCallRow.model` is the *effective* model for analysis — observed-from-trace when consistent (single observed), IR-declared otherwise. The substitution happens once at row construction (`_build_per_call_row`); all 19 downstream consumers (cost projection, threshold checks, tokenization, rendering, fragmentation grouping) read `row.model` and get correct behavior transparently. IR-vs-observed divergence is disclosed at workflow level via `AnalysisSummary.ir_default_model` rendered in the header (`IR/settings declares: X (overridden by trace evidence)`) — no per-row annotation. Multi-observed rows (trace shows multiple distinct models on one node) are NOT promoted to `model_is_heterogeneous=True` — that flag stays bound to IR-declared `${...}` so `_format_scale_line`'s "model varies per batch item" prose only fires when IR actually declared variance. Multi-observed gets `model=""` (excluded from pricing) + `<varies>` rendering via a derived `len(observed_models) > 1` check at the per-call display site.

---

## Critical files (full list)

**Modified**:
- `src/pflow/core/cache_analysis/analyze.py` — Tasks 1, 2, 3
- `src/pflow/core/cache_analysis/render_text.py` — Tasks 4, 5
- `src/pflow/core/cache_analysis/render_json.py` — Task 6
- `src/pflow/core/cache_analysis/__init__.py` — Task 6 (version-history docstring)
- `src/pflow/core/cache_analysis/CLAUDE.md` — Task 11
- `src/pflow/mcp_server/tools/execution_tools.py` — Task 6.5
- `tests/test_core/test_cache_analysis_analyze.py` — Tests 1-4, 10, 11 (Task 8)
- `tests/test_core/test_cache_analysis_renderers.py` — Tests 5-9, 12-14 (Task 8)
- `.taskmaster/tasks/task_159/baseline/BASELINE-AUDIT.md` — Task 10
- ~34+ baseline `expected-stdout.txt` files — Task 9 (regenerated)

**Read-only verification**:
- `src/pflow/core/cache_analysis/cost_estimation.py` — verify don't edit (Task 7)
- `src/pflow/core/llm_config.py` — verify `get_default_workflow_model` semantics
- `src/pflow/core/cache_analysis/warning_catalog.py` — verify `requires_complete_trace` flag exists (precondition)

---

## Verification

### Unit tests
```bash
make test  # full suite (-m "not e2e")
```

Required passes:
- All 15 new tests from Task 8 (Tests 1–14 + 10.5).
- Existing `test_dynamic_batch_trace_preserves_observed_model_truth` (line 1010-1083) — IR `${item.model}` heterogeneity preserved.
- Existing `test_complete_trace_with_heterogeneous_projection_exclusion_suppresses_actual_delta` (line 1086-1170).
- `test_golden_baseline_hashes_match` (DD#19) — should NOT drift; this fix doesn't touch hash inputs.
- `test_plan_drift.py` 34/34.
- **`test_cache_analysis_summarize.py` full suite** — `summarize.py` reads `summary.first_run_delta.kind`, `summary.rerun_delta.kind`, `summary.actionable_opportunities` for the dry-run nudge. Task 1 doesn't change those fields directly, but Task 1 changes the cost-projection paths that COMPUTE delta kinds. Tests that assert on `kind == "unavailable"` for scenarios where projections previously fell through (e.g., L-1 clean env) will FAIL after the fix because Task 1 makes those projections succeed. Audit each summarize test: if it asserts unavailability for a scenario where trace evidence exists with priceable observed models, that assertion encoded the now-fixed bug — update the test.

### Baseline harness
```bash
cd .taskmaster/tasks/task_159/baseline
./verify.sh  # 65 passed, 0 drifted, 0 harness errors
```

### make check
```bash
make check  # ruff + ruff-format + mypy + deptry — all clean
```

### Manual smoke (L-1 clean env)

```bash
mv ~/.pflow/settings.json ~/.pflow/settings.json.bak 2>/dev/null
uv run pflow analyze-cache \
  .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md \
  --from-trace .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json \
  sources='["..."]'
mv ~/.pflow/settings.json.bak ~/.pflow/settings.json 2>/dev/null
```

Expected:
- Header: `Workflow: 25 LLM nodes using 3 models: gemini/...` (L-10/L-11 already gives this)
- Per-call rows show `model=gemini/gemini-2.5-flash` (NOT empty 35-space pads) — **L-2/L-12 fix evidence**
- Summary: `Actual savings (this run): saves ~$X.XX/run actual vs no-cache, ~50% of baseline` as FIRST delta line — **L-3 fix evidence**
- `Cost without caching:` shows real dollar value (NOT `unavailable`) — **L-1 cost fix evidence**

### Manual smoke (L-2 mismatch)

```bash
echo '{"version": "1.0.0", "llm": {"default_model": "anthropic/claude-haiku-4-5"}}' > ~/.pflow/settings.json
uv run pflow analyze-cache \
  .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md \
  --from-trace .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json \
  sources='["..."]'
```

Expected:
- Header includes new line: `IR/settings declares: anthropic/claude-haiku-4-5 (overridden by trace evidence)` — **L-2 disclosure evidence**
- Per-call rows show `model=gemini/gemini-2.5-flash` (NOT haiku)
- Cost numbers priced at gemini rates (apples-to-apples)
- `Actual savings (this run):` is the meaningful primary number

### Fragmentation interaction smoke

Run baseline `04-warning-catalog/15-cache.heterogeneous-models-fragment-cache`. After regen, the warning should still fire for IR-declared multi-model setups (existing behavior). Test 14 covers the new trace-only-multi-model fragmentation case.

---

## Rollback strategy

Each task is independently revertable:
- Tasks 1, 2, 3 are coupled (effective-model substitution + `ir_default_model` capture). Revert together.
- Task 4(a) (per-call `<varies>` for multi-observed) — independent.
- Task 4(b) (header disclosure) — independent.
- Task 5 (L-3 reorder + relabel both sites) — independent.
- Task 6 + 6.5 (JSON + MCP docstring) — additive; reverting deletes one key + doc lines.

Mutation contracts in Tests 1-14 provide structural protection against silent reverts.

---

## Out of scope

- L-10, L-11, A-3, B-18 — closed by parallel agent; do NOT touch their work.
- L-1 HEADER ASPECT — closed by L-10/L-11; this plan addresses cost projection + per-call rendering only.
- L-4, L-5, L-6, L-7, L-8 — deferred to v1.x per Section F triage.
- Per-row IR-divergence annotation — rejected in favor of header-level disclosure (user decision).
- Auto-load drift gate (`_trace_aligns_with_ir`) — confirmed correct; my fix is downstream.
- `model_is_heterogeneous` semantic broadening — explicitly NOT done; flag stays IR-declared-only.
