# Plan: Fix 5 verification-found bugs from commit `1fabde31` (Task 159 prompt caching)

## Context

End-to-end verification of commit `1fabde31` (TraceTree consolidation + sub-workflow rollup + JSON 4.0 atomic primitives) found 5 bugs the test suite missed. The architectural foundation is solid (recursive correctness, 3-deep nesting, sub-workflow rollup, phantom-row suppression all verified). What slipped through is concentrated in two correctness areas (Bug 4, Bug 5) and three small UX/contract surfaces (Bugs 1, 2, 3).

Two bugs need real architectural decisions; the rest are mechanical. Each phase below is one atomic commit ("ships green tests + check + plan_drift + golden baseline").

---

## Phase A — Bug 4: `cacheable_tokens` clamped wrongly (HIGH correctness)

### Problem

`analyze.py:1070` clamps `cacheable_with_clamp = min(cacheable_tokens, input_tokens)`. The clamp's invariant ("cache cannot exceed total") was correct for the original heuristic-vs-tokenizer mismatch (Bug C). After the 2026-05-01 cost-projection fix moved cacheable to real per-chunk tokenization, the clamp's premise broke: `input_tokens_estimated` on the greenfield path is the **resolved prompt body only** — cache content is not added. When `## Cache` declares chunks referenced by name in `prompt_cache:` but NOT inlined in the prompt body, the clamp truncates correct ~2391-token cacheable values down to ~4 (the prompt body size). Agents are advised to remove `prompt_cache:` declarations that are actually correct.

### Root cause

`PerCallRow.input_tokens_estimated` semantically should equal "tokens billed by the LLM" (prompt body + cache content). On greenfield it computes only `tokenize(resolved_prompt)`. The two fields the clamp reconciles measure different things.

### Fix (top-10%: make the invariant structurally true)

Make `input_tokens_estimated` actually equal the total billed tokens. The clamp then becomes a no-op (kept as defense-in-depth). `cache_ratio_pct` (cacheable/input) becomes meaningful.

**Greenfield path** (`_estimate_row_tokens` in `analyze.py:1116-1149`): when the node has `prompt_cache: [...]` declared, also tokenize each declared chunk's resolved value and add to `input_tokens`. Reuses the existing `_estimate_ref_tokens` helper from `token_estimation.py` — no new tokenization primitive.

**Trace path:** Anthropic-style traces split cache from non-cache (`input_tokens` excludes cache; `cache_creation` + `cache_read` are the cache portion). Sum them. Gemini/OpenAI fold cache into `input_tokens` already (and report `cache_creation == 0`); detect via `cache_creation > 0` and only sum when Anthropic-style. **In-scope for this phase.** Long-term: normalize `billed_input_tokens` at the trace recording layer (`llm_client._normalize`) — out of scope, file as v1.x follow-up.

### Files

- `src/pflow/core/cache_analysis/analyze.py:1116-1149` — `_estimate_row_tokens`: add cache content tokens for declared subsets on greenfield + Anthropic-style trace paths
- Optional: extract `_total_input_tokens(node, trace_event, ctx)` helper if `_estimate_row_tokens` gets unwieldy
- Existing helper to reuse: `_estimate_ref_tokens` in `src/pflow/core/cache_analysis/token_estimation.py:351-378`

### Tests

- **Update** `tests/test_core/test_cache_analysis_analyze.py:453-486` (`test_per_call_cache_ratio_never_exceeds_100_pct`): rewrite docstring to clarify the invariant is now structural (cache is part of input by construction). Drop the "Mutation test" comment that pinned the clamp as the spec. Test passes unchanged because invariant still holds.
- **Add** `test_cacheable_tokens_includes_cache_content_when_chunks_only_in_cache_block`: Bug 4 reproducer. Workflow with `## Cache` declaring `${context}`, `prompt_cache: [context]`, prompt body = `"Draft a summary."`. Pass `parameters={"context": "X" * 19117}`. Assert `cacheable_tokens_estimated > 1024` (above provider minimum) AND no `cache.below-min-tokens` warning fires.
- **Add** `test_total_input_tokens_anthropic_trace_sums_cache_portions`: trace tier with Anthropic shape (`input_tokens=500`, `cache_creation=1500`, `cache_read=0`), assert `input_tokens_estimated == 2000`.
- **Add** `test_total_input_tokens_gemini_trace_does_not_double_count`: trace tier with Gemini shape (`input_tokens=2000`, `cache_creation=0`, `cache_read=1500`), assert `input_tokens_estimated == 2000` (not 3500).

### Verification

```bash
# Manual Bug 4 reproducer (greenfield):
CONTEXT=$(yes "filler" | head -200 | tr -d '\n')
uv run pflow analyze-cache /tmp/with-cache.pflow.md context="$CONTEXT" --format=json | \
  jq '.per_call[] | {node: .node_path, input: .input_tokens_estimated, cacheable: .cacheable_tokens_estimated}'
# Expect: cacheable > 2000, no cache.below-min-tokens warning

uv run pytest tests/test_core/test_cache_analysis_analyze.py -k "ratio or cacheable_tokens or total_input"
make check
```

---

## Phase B — Bug 5: cross-workflow discrepancy detection skips sub-workflow nodes (MEDIUM-HIGH correctness)

### Problem

`cache.discrepancy` silently skips LLM nodes inside sub-workflows. Investigation traced the gap to `execution/plan.py`'s `_force_downstream=True` mode: BFS-downstream-built child entries have `cache_key=None` because `_make_downstream_entry` calls `_execute_entry` directly without invoking `plan_node`. `_flatten_plan_keys` correctly skips entries with `cache_key=None`, so sub-workflow predictions never enter the predicted_keys dict.

### Root cause

The cache analyzer's prediction layer is **coupled to the execution planner**. `_predict_cache_keys` calls `compile_workflow + build_plan` and harvests cache_keys from PlanEntry. The planner's BFS-downstream mode legitimately can't compute cache_keys (parent's upstream state is dirty, child inputs are placeholders) — but the analyzer inherits that limitation even when it has all the data it needs (per-workflow resolved parameters via `parameters_for_workflow`).

### Fix (top-10%: decouple analyzer predictions from execution planner)

`cache_render.py` already declares analyze.py as the third intended consumer of cache-rendering helpers (module docstring lines 1-11). The architectural direction is documented; the implementation didn't follow through. Replace `_predict_cache_keys`'s planner call with direct computation using `cache_render` helpers + `runtime.cache.compute_node_cache_key`.

**New design:**

```
_predict_cache_keys(cw_result, ctx) -> (predicted_keys, notes):
  for workflow_path, ir in cw_result.irs_by_workflow.items():
      params = ctx.parameters_for_workflow(workflow_path)
      for node in ir["nodes"]:
          if not _is_llm_with_prompt_cache(node):
              continue
          key, why_skipped = _predict_node_cache_key(node, params, ctx.memo_cache, workflow_path)
          if key is not None:
              predicted_keys[(workflow_path, node["id"])] = key
          else:
              notes.append(why_skipped)  # per-node reason — not a generic catch-all
```

Where `_predict_node_cache_key` reuses `cache_render._resolve_chunk_value` + `cache_render._resolve_static_prefix_for_cache` + `runtime.cache.compute_node_cache_key` to compute the byte-identical key the runtime would use. Returns `None` only for genuinely-unresolvable refs (truly dirty upstream node outputs that aren't in memo).

**Side benefits:**
- Drops the `compile_workflow + build_plan` call from the analyzer hot path (~big speedup on multi-workflow analyses)
- Removes the entire class of "cache_key absent because BFS-downstream" silent skips
- `parameters_for_workflow` infrastructure (Phase 2a from the original plan) gets a second consumer, justifying its existence
- Per-node skip notes replace the generic "skipped attribution for N events" noise — agents see exactly which node's prediction failed and why

**What stays the same:**
- The existing two-pass infrastructure (`_predict_cache_keys` returns dict + notes; `_emit_discrepancy_diagnostics` consumes dict) — unchanged contract
- Memo cache integration — `_resolve_chunk_value` reads memo via the same path runtime uses
- Byte-identity contract — same helpers, same answers

### Files

- `src/pflow/core/cache_analysis/analyze.py:2327-2397` — replace `_predict_cache_keys` body. Drop the `compile_workflow + build_plan` call. Walk `cw_result.irs_by_workflow`. Add `_predict_node_cache_key(node, params, memo_cache, workflow_path) -> tuple[str | None, str | None]` helper.
- `src/pflow/core/cache_analysis/analyze.py:418` (the existing `walk_cross_workflow` call site) — pass `cw_result` into `_predict_cache_keys` (currently passes `workflow_ir`, `parameters`, `memo_cache`, `workflow_path`)
- Existing helpers to reuse:
  - `src/pflow/core/cache_render.py:128 _resolve_chunk_value`
  - `src/pflow/core/cache_render.py:213 _resolve_static_prefix_for_cache`
  - `src/pflow/core/cache_render.py:99 deterministic_serialize`
  - `src/pflow/runtime/cache.py:91 compute_node_cache_key`
  - `src/pflow/core/cache_analysis/context.py::AnalysisContext.parameters_for_workflow`
- **Out of scope:** `execution/plan.py`'s BFS-downstream mode stays as-is. The planner's `cache_key=None` on BFS-downstream entries is correct for ITS purposes (cost projection) — the planner shouldn't try to compute cache_keys it can't trust. Decoupling means the analyzer no longer cares.

### Tests

- **Add** `test_predict_cache_keys_includes_sub_workflow_nodes`: parent + child workflow, both have LLM nodes with `prompt_cache:`. Pass parameters resolving both. Assert returned dict has entries for `(parent_path, parent_node_id)` AND `(child_path, child_node_id)`.
- **Add** CliRunner test `test_analyze_cache_emits_discrepancy_for_sub_workflow_node_via_subprocess`: synthesized trace with parent.draft + child.review, both with wrong `cache_key`. Pass `--inputs topic=foo`. Assert TWO `cache.discrepancy` entries fire, each with correct `affected_workflow`.
- **Add** `test_predict_node_cache_key_returns_none_for_unresolvable_node_output_ref`: chunk references `${some_node.response}` where `some_node` isn't in memo or parameters. Assert returns `(None, "...")` with a structured per-node skip reason (NOT the generic catch-all).
- **Add** `test_predict_cache_keys_byte_identical_to_runtime`: drive a small workflow through `WorkflowRunner` once, capture the runtime cache_key from the memo entry, then call `_predict_cache_keys` and assert byte-equality. Defends the byte-identity contract that makes discrepancy detection work.

### Verification

```bash
# Manual Bug 5 reproducer:
mkdir -p /tmp/discrep && # write parent.pflow.md, child.pflow.md, trace.json from verification report
uv run pflow analyze-cache /tmp/discrep/parent.pflow.md --from-trace /tmp/discrep/trace.json topic=foo --format=json | \
  jq '.warnings[] | select(.id == "cache.discrepancy") | {node: .node_id, scope: .context.workflow_path_short}'
# Expect: TWO entries (parent.draft, child.review), correctly scoped

uv run pytest tests/test_core/test_cache_analysis_per_id_emission.py -k discrepancy
uv run pytest tests/test_cli/test_analyze_cache.py
make check
```

---

## Phase C — Bug 1: `recommended_actions` doesn't disambiguate same-node-id (HIGH UX)

### Problem

`view_helpers.py:118-122` only sets `scope_workflow` when `d.node_id is None` (workflow-level findings). Per-node findings carry `affected_workflow` in their context but the projection drops it. Agents reading multi-workflow recommended actions see `draft / draft / review` with no way to tell which workflow each `draft` is in. The plan's Phase 2c renderer-overhaul list spec'd workflow scope on per-call grouping, drill-in section, unavailable-models attribution, and discrepancy messages — but NOT recommended_actions. Plan-level miss with same UX impact.

### Fix (top-10%: rustc/clippy convention — `<symbol> in <location>`)

Drop the `if d.node_id is None:` guard in `view_helpers.py:119`. Always populate `scope_workflow` from `affected_workflow` when present and non-empty. Renderer (`render_text.py:491-498`) inlines scope on the same line as node_id when both are set: `<node_id> in <basename>`. JSON consumers see both fields populated; existing dispatch on `(node_id, scope_workflow)` still works.

**Single-workflow output unchanged**: when there are no sub-workflows, `affected_workflow` equals the analyzed workflow's own path. Renderer suppresses the `in <basename>` suffix when scope matches the analyzed workflow (same condition the per-call table already uses for "no subheaders for single-workflow analysis"). Agents analyzing a single file see no behavioral change.

### Files

- `src/pflow/core/cache_analysis/view_helpers.py:118-122` — drop `if d.node_id is None:` guard. Always populate `scope_workflow` when context's `affected_workflow` is a non-empty string. Update the dataclass docstring at `analyze.py:158-181` ("at most one is set" claim is wrong now — both can be set; `node_id` carries the symbol, `scope_workflow` carries its location).
- `src/pflow/core/cache_analysis/render_text.py:491-498` — emit `<node_id> in <basename>` when both set; suppress ` in <basename>` when scope_workflow equals analyzed workflow.
- Existing helper to reuse: `_short_workflow_label` (already exists in render_text.py)

### Tests

- **Update** `tests/test_core/test_cache_analysis_renderers.py:531 test_text_recommended_actions_render_workflow_scope_for_workflow_level_findings` — assertions stay valid (basename still appears) but should also verify that workflow-level findings keep their existing single-line scope shape.
- **Add** `test_text_recommended_actions_per_node_finding_includes_workflow_scope_in_multi_workflow_analysis`: parent + child both have `draft` with `cache.below-min-tokens`. Assert text output contains literal `draft in parent.pflow.md` AND `draft in child.pflow.md`.
- **Add** `test_text_recommended_actions_single_workflow_omits_scope_suffix`: single-workflow analysis with `cache.below-min-tokens`. Assert the action item does NOT contain ` in `.
- **Add** `test_json_recommended_actions_per_node_finding_carries_scope_workflow`: same multi-workflow fixture. Assert `recommended_actions[0].scope_workflow` AND `node_id` both populated.

### Verification

```bash
uv run pflow analyze-cache tests/fixtures/cache_analysis/parent.pflow.md
# Expect Recommended actions section shows:
#   1. ... draft in parent.pflow.md
#   2. ... draft in child.pflow.md
#   3. ... review in child.pflow.md

uv run pytest tests/test_core/test_cache_analysis_renderers.py -k recommended_actions
make check
```

---

## Phase D — Bugs 2 + 3: contract hardening + doc drift (LOW, one commit)

### Bug 2 — `_ensure_workflow_scope` accepts `affected_workflow=None`

**Problem:** `warning_catalog.py:953` checks key presence (`"affected_workflow" in context_kwargs`), not value validity. `affected_workflow=None` slips through the contract. No production caller currently triggers this (synthesizer at `analyze.py:144` produces `ir-hash:` ID), but the contract is the load-bearing guard the Phase 1 commit message brags about.

**Fix:** mirror the existing consumer pattern at `view_helpers.py:121` (`if isinstance(affected, str) and affected:`). One-line change to the guard:

```python
# Before:
if node_id is None or "affected_workflow" in context_kwargs:
    return

# After:
if node_id is None:
    return
affected = context_kwargs.get("affected_workflow")
if isinstance(affected, str) and affected:
    return
raise KeyError(...)
```

**File:** `src/pflow/core/cache_analysis/warning_catalog.py:943-958`

**Test:** **Add** `test_make_diagnostic_node_id_with_affected_workflow_none_raises`: `make_diagnostic('cache.below-min-tokens', node_id='x', affected_workflow=None, ...)` raises `KeyError`. (Currently does NOT raise — value-validity hole.)

### Bug 3 — Stale `current_cost` in user-facing note text

**Problem:** `cross_workflow.py:260` says `"current_cost is trace-driven"`. JSON 4.0 renamed the field to `actually_paid_usd`. Agents reading the note can't find `current_cost` anywhere.

**Fix:** rename the inline string to `actually_paid_usd is trace-driven`.

**File:** `src/pflow/core/cache_analysis/cross_workflow.py:258-261`

**Tests:** the searcher confirmed zero tests assert on this literal substring. No test updates needed.

**Verification (combined):**

```bash
uv run pytest tests/test_core/test_cache_analysis_warnings.py -k affected_workflow_none
uv run pflow analyze-cache /tmp/het-batch-parent.pflow.md  # heterogeneous batch reproducer
# Expect note includes "actually_paid_usd is trace-driven" (not "current_cost")
make check
```

---

## Architectural decisions documented inline

1. **Bug 4 chose to fix `input_tokens` semantics, not remove the clamp.** Removing the clamp re-opens the original Bug C symptom (cacheable > input from tokenizer-vs-heuristic mismatch). Fixing the semantic premise eliminates Bug 4 and makes Bug C structurally impossible.

2. **Bug 4 trace-tier provider detection is in-scope-pragmatic.** Anthropic vs Gemini cache-token reporting differs; full normalization belongs at `llm_client._normalize` (records a clean `billed_input_tokens` field). That refactor is out of scope; the analyzer's per-provider sum is a contained workaround. **File as v1.x:** "Normalize billed_input_tokens at trace-recording layer."

3. **Bug 5 chose decouple over surgical-planner-fix.** Surgical fix (make BFS-downstream call `plan_node` when inputs resolve) would patch the symptom but leave the analyzer-planner coupling. Decoupling matches `cache_render.py`'s documented intent ("third site" comment), drops a heavy `compile_workflow + build_plan` call from the analyzer hot path, and produces correct predictions regardless of whether the parent path is state-machine or BFS-downstream.

4. **Bug 1 chose inline `<symbol> in <location>` over per-finding scope sub-line.** Matches rustc/clippy/mypy convention. Keeps action items single-line for narrow terminals. JSON shape unchanged (both fields can co-exist).

5. **Phase ordering: A → B → C → D.** A and B are correctness fixes that need verification on real workflows; C is UX requiring renderer test updates; D is two one-liners. Each phase is independently revertible; no cross-phase dependencies.

---

## Verification (full suite, after all 4 phases)

```bash
make test                                                       # 6,103+ tests including new
make check                                                      # ruff + ruff-format + mypy + deptry
uv run pytest tests/test_execution/test_plan_drift.py           # 33/33 sacred parity
uv run pytest tests/test_runtime/test_prompt_cache_hash.py      # 15/15 golden baseline (DD#19)
uv run pflow analyze-cache tests/fixtures/cache_analysis/parent.pflow.md --format=json | \
  jq '.format_version, .summary.actually_paid_tier, .recommended_actions[] | .scope_workflow'
# Expect: "4.0", "unavailable" (greenfield), all three actions show scope_workflow set
```

End-to-end manual verification per phase: see each phase's "Verification" block above.

## Out of scope / filed as v1.x

- **Trace-recording-layer normalization of `billed_input_tokens`**: would let the analyzer drop its provider-aware sum. (Phase A workaround documented.)
- **Sub-workflow consolidation advisories** (`_consolidate_to_root_advisories` walks parent IR only): drill-in section is the documented mitigation today.
- **Dynamic-batch / template-items child workflow attribution** (#360 / #366): trace 2.2 schema with per-event `workflow_path` is the long-term fix.
- **`mutation-audit` ad-hoc**: not a per-PR gate; run before release.
