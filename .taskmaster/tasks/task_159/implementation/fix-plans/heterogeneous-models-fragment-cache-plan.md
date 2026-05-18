# Plan: `cache.heterogeneous-models-fragment-cache` + `cache.first-call-write-penalty`

## Context

Stage 2 verification of Task 159 (prompt caching) surfaced **Finding #11**: when a workflow's nodes use different exact-model strings on different LLM nodes that share cached chunks via `prompt_cache:`, **each model writes its own cache namespace**. Bytes are never shared across model boundaries — the workflow author thinks they're amortizing one cache write across N calls, but they're actually paying N writes (one per exact model). The analyzer never warns about this.

**Finding #12** (sibling): a model whose only call in the workflow declares `prompt_cache:` pays a cache_creation cost (1.25× rate for Anthropic 5m, 2× for 1h) with zero subsequent reads to amortize → declaring cache for that lone call costs MORE than not declaring it.

The two findings share a single detection primitive — *group rows by canonical exact model* — and naturally fall out of one walk. The closest precedent (`_consolidate_to_root_advisories`) explicitly defers per-model checks at `analyze.py:1834-1836`: *"Heterogeneous-model workflows would warrant per-model checks; defer to v1.x if real usage hits the pattern."* This plan fills that documented gap.

**Cache scope correction**: the original spec at `reports/cache-heterogeneous-models-fragment.md` framed cache fragmentation across multiple dimensions (model + workflow). Empirical verification of cross-workflow trace files showed **provider-side cache is workflow-blind**: identical content + identical model shares cache across workflow boundaries. The only fragmentation dimension worth detecting for $$$ savings is **canonical exact model**. Workflow scoping affects only pflow's local memo cache (Finding #2 territory, separate concern).

## Design

**One detector. Two catalog entries. Both diagnostics fall out of the same group walk.**

```
_detect_model_cache_fragmentation(*, workflow_ir, rows_by_node, declared_chunks, ctx) -> list[Diagnostic]:
  1. Filter rows: skip model_is_heterogeneous, did_not_execute_in_trace, empty model, empty declared_prompt_cache.
  2. Group surviving rows by normalize_model_name(row.model)  →  dict[canonical_model, list[PerCallRow]]
  3. Compute per-group cache_creation cost using row.cacheable_tokens_estimated × _write_rate_for_ttl(...).
     Honest-unmeasurable: if ANY group's cost is None, skip emit (mirror _check_root_for_consolidation).
  4. If len(groups) >= 2 AND chunks intersect across >=2 groups:
       Emit ONE cache.heterogeneous-models-fragment-cache (WARNING, priority 10), workflow-scoped.
  5. For each group of size 1 whose row declares prompt_cache:
       Emit cache.first-call-write-penalty (INFO, priority 30), node-scoped.
       Suppress if row.prewarm == True (prewarm amortizes the write).
       Suppress if normalize_model_name(model) starts with "gemini/" (free implicit cache, no real penalty).
```

**Root-only by design** — matches existing convention at `analyze.py:473-476`. Sub-workflow fragmentation surfaces when the agent runs `analyze-cache` on that sub-workflow file (recursion at the CLI invocation level, not the detector level). One mental model, applied per-workflow.

**No new abstractions**. Reuses:
- `normalize_model_name` (`core/llm_providers.py:82`) — canonical grouping key. No `canonical_model_for_cache` primitive needed; if two rows write `gemini-2.5-flash` and `gemini/gemini-2.5-flash`, they group correctly.
- `_write_rate_for_ttl(pricing, ttl, model)` (`cost_estimation.py:236`) — TTL-aware (handles Anthropic 5m vs 1h with the recent LiteLLM `cache_creation_input_token_cost_above_1hr` fix).
- `_input_rate(model)` (`analyze.py:2127`) — for the no-cache hypothetical in #12.
- `_extract_cache_ttl(workflow_ir.get("cache"))` (`analyze.py:706`) — TTL access.
- `make_diagnostic(...)` from `warning_catalog.py` — catalog-as-SSoT.
- The `overlap_lines` idiom from `cache.prompt-body-duplicates-cache` — producer pre-formats the bulleted list as a string; renderer slots it into `message_template`.

## Cost projection math

### `cache.heterogeneous-models-fragment-cache` (#11)

Pick the **largest group** (most rows) as the survivor — most defensible single-model-consolidation target. Sum the OTHER groups' cache_creation cost as redundant:

```
sorted_groups = sorted(groups, key=lambda g: -len(g.rows))
survivor = sorted_groups[0]
redundant_groups = sorted_groups[1:]
savings_usd = sum(group.cache_creation_cost for group in redundant_groups)
```

Where each `group.cache_creation_cost = group.shared_tokens × _write_rate_for_ttl(pricing, ttl, group.model)`.

`shared_tokens` per group = sum of `_estimate_chunk_tokens` for the chunks the group's rows actually share with at least one OTHER group's rows. (Use `_estimate_chunk_tokens` only as a structural helper — but the spec'd version is wrong for content tokens. Better: derive from `min(row.cacheable_tokens_estimated for row in group.rows)` — cap at smallest row's cacheable count to avoid double-counting.) **Decision: use the smallest row's `cacheable_tokens_estimated` per group** — represents the bytes ALL rows in the group provably write.

If any group has `_input_rate(group.model) is None` OR `cacheable_tokens_estimated is None`: skip the warning (honest-unmeasurable).

### `cache.first-call-write-penalty` (#12)

```
write_cost = row.cacheable_tokens_estimated × _write_rate_for_ttl(pricing, ttl, row.model)
hypothetical_no_cache_cost = row.cacheable_tokens_estimated × _input_rate(row.model)
savings_usd = write_cost - hypothetical_no_cache_cost
# 5m Anthropic: 0.25 × input_rate × tokens (you'd save 25% by removing the declaration)
# 1h Anthropic: 1.00 × input_rate × tokens (write rate is 2× input)
# Gemini: suppress entirely
```

If `_input_rate` returns None: emit with `savings_usd=None` (catalog allows via `nullable_cost_keys`).

## Catalog entries

### `cache.heterogeneous-models-fragment-cache`

```python
"cache.heterogeneous-models-fragment-cache": CacheWarningSpec(
    severity=Severity.WARNING,
    source="cache_analyzer",
    category=CACHE_WARNING_CATEGORY,
    message_template=(
        "Workflow declares cached chunks shared across {model_group_count} exact models "
        "({models_csv}). Each model has a separate cache namespace — bytes are written "
        "{model_group_count}× instead of 1×.{savings_clause}\n"
        "{model_groups_lines}"
    ),
    required_context_keys=(
        ("model_group_count", int),
        ("models_csv", str),
        ("model_groups", list),
        ("model_groups_lines", str),
        ("shared_chunks", list),
        ("affected_workflow", str),
        ("savings_usd", float),
    ),
    suggestions_template=(
        "Consolidate to one exact model so all calls share one cache namespace, OR",
        "Ensure each model has enough calls in the workflow to amortize its own cache write.",
    ),
    path_template="workflows[path={affected_workflow}]",
    nullable_cost_keys=frozenset({"savings_usd"}),
    headline_template=(
        "Cache fragmented across {model_group_count} exact models — "
        "declared chunks written {model_group_count}×, never shared"
    ),
),
```

`model_groups_lines` is producer-formatted, e.g.:
```
  • anthropic/claude-haiku-4-5 (3 nodes): creative-direction, song-architecture, easter-eggs
  • gemini/gemini-2.5-flash-lite (1 node): generate-chorus-options
```

`model_groups: list[dict]` (typed JSON payload):
```json
[
  {"model": "anthropic/claude-haiku-4-5", "node_paths": ["creative-direction", "song-architecture", "easter-eggs"], "node_count": 3, "cache_creation_cost_usd": 0.0081},
  {"model": "gemini/gemini-2.5-flash-lite", "node_paths": ["generate-chorus-options"], "node_count": 1, "cache_creation_cost_usd": 0.0024}
]
```

### `cache.first-call-write-penalty`

```python
"cache.first-call-write-penalty": CacheWarningSpec(
    severity=Severity.INFO,
    source="cache_analyzer",
    category=CACHE_ADVISORY_CATEGORY,
    message_template=(
        "{node_id}: only call to {model} in this workflow with `prompt_cache:` declared. "
        "Cache write costs ~{write_cost_str} with no subsequent reads to amortize — "
        "removing the declaration would save {penalty_str}.{savings_clause}"
    ),
    required_context_keys=(
        ("node_id", str),
        ("model", str),
        ("write_cost_str", str),
        ("penalty_str", str),
        ("affected_workflow", str),
        ("savings_usd", float),
    ),
    suggestions_template=(
        "Remove `prompt_cache:` from {node_id} (single-call write penalty), OR",
        "Add more calls to {model} elsewhere in the workflow so the cache_creation cost amortizes.",
    ),
    path_template="nodes[id={node_id}].prompt_cache",
    nullable_cost_keys=frozenset({"savings_usd"}),
    headline_template="Single-call cache write penalty on {node_id} ({model})",
),
```

### Priority entries (`warning_catalog.py:670-697`)

```python
"cache.heterogeneous-models-fragment-cache": 10,  # Tier-1 actionable opportunity
"cache.first-call-write-penalty": 30,              # Tier-5 informational
```

### `see_also`

Both default to `("caching",)` — existing topic, no new guide section needed in v1.

## Files to modify

### Production (4 files)

1. **`src/pflow/core/cache_analysis/warning_catalog.py`**
   - Add 2 catalog entries (lines ~640+, with the `llm.thinking-temperature-mismatch` precedent for namespace mixing)
   - Add 2 priority entries to `RECOMMENDED_ACTION_PRIORITY` (lines 670-697)
   - Update module docstring count narrative (lines 8-9) — informational only, not enforced
   - **No** new helper functions in this file (avoid `_compute_distribution_clause` reuse — keys don't match)

2. **`src/pflow/core/cache_analysis/analyze.py`**
   - Add `_detect_model_cache_fragmentation` next to `_consolidate_to_root_advisories` (line ~1800)
   - Add helper `_format_model_groups_lines(groups: list[dict]) -> str` for the bulleted block (private to analyze.py; mirror `data_flow.py:983-995` overlap_lines pattern)
   - Add helper `_compute_model_group_costs(groups, ttl, ctx) -> dict | None` (returns None when honest-unmeasurable)
   - Wire detector at line 500-507 alongside existing root-only emitters:
     ```python
     warnings.extend(
         _detect_model_cache_fragmentation(
             workflow_ir=workflow_ir,
             rows_by_node=rows_by_node,
             declared_chunks=declared_chunks,
             ctx=ctx,
         )
     )
     ```

3. **`src/pflow/core/cache_analysis/CLAUDE.md`**
   - Bump catalog count narrative at line ~245 (loose, not enforced)

4. **`src/pflow/mcp_server/tools/execution_tools.py`**
   - Add 2 lines to docstring catalog list at line 425 area
   - Update count phrase at line 408: `(17 entries in v1 — 16 cache.* plus 1 llm.*)` → `(19 entries in v1 — 18 cache.* plus 1 llm.*)`
   - Enforced by `tests/test_mcp_server/test_analyze_cache_tool.py::test_docstring_lists_every_catalog_id`

### Tests (5 files)

5. **`tests/test_core/test_cache_analysis_warnings.py`**
   - Bump `test_catalog_has_seventeen_entries_v1` → `test_catalog_has_nineteen_entries_v1` at line 46-63 (or rename with new count); update its docstring summary
   - Add 2 entries to `_minimal_context_kwargs` at line 448-567

6. **`tests/test_core/test_cache_analysis_per_id_coverage.py`**
   - Add 2 entries to `_kwargs_for` at line 43-189
   - Add 2 producer-driven blocks to `test_emitted_diagnostics_round_trip_for_real_producer_paths` at line 307-815 (drives `analyze()` end-to-end with inline IRs that trigger each ID)

7. **`tests/test_core/test_cache_analysis_per_id_emission.py`** (the primary test home)
   - New section dividers for both new IDs
   - Per ID: 1 firing test + 2-3 suppression tests, each with `Mutation test:` docstring annotation naming the production guard it pins. Mirror the `cache.consolidate-to-root-recommended` block at lines 2423-2594.
   - Tests for `cache.heterogeneous-models-fragment-cache`:
     - `test_fragmentation_fires_for_two_exact_models_sharing_chunks`
     - `test_fragmentation_silent_when_single_model`
     - `test_fragmentation_silent_when_no_chunk_overlap`
     - `test_fragmentation_skips_heterogeneous_batch_rows`
     - `test_fragmentation_skips_when_any_group_cost_is_none` (honest-unmeasurable)
   - Tests for `cache.first-call-write-penalty`:
     - `test_write_penalty_fires_for_single_call_with_declared_cache`
     - `test_write_penalty_silent_when_group_size_gt_one`
     - `test_write_penalty_silent_when_prewarm_true`
     - `test_write_penalty_silent_for_gemini_implicit_cache`
   - Co-emission test:
     - `test_fragmentation_and_write_penalty_coemit_when_one_group_has_size_one`

8. **`tests/test_cli/test_analyze_cache.py`**
   - Add 1 `CliRunner.invoke(...)` JSON test per new ID asserting the catalog ID appears in `payload["warnings"]`. Mirror line 122-142 (existing `cache.below-min-predicted` precedent).

## Edge cases (covered by tests)

| Case | Behavior |
|---|---|
| Single-model workflow | No fragmentation; #12 fires only if a single LLM node declares cache and has size 1 |
| Two models, no shared chunks | No #11 (no fragmentation to report); per-group #12 may still fire |
| All groups size > 1 | Only #11 fires |
| One group size = 1, declares cache | #12 fires for that node + possibly #11 if other groups exist |
| `model_is_heterogeneous = True` row | Excluded entirely (within-batch heterogeneity deferred to v1.x) |
| `did_not_execute_in_trace = True` row | Excluded |
| `prewarm: true` on size-1 group | Suppress #12 (write is amortized via prewarm) |
| Gemini-only group of size 1 | Suppress #12 (free implicit cache, no real penalty) |
| `_input_rate` returns None for any group | Skip emit entirely (honest-unmeasurable) |
| Brownfield (with trace) | Identical math; `cacheable_tokens_estimated` already pulls from trace tier (`cache_creation + cache_read`) — no special-case code |
| Greenfield (no trace) | `cacheable_tokens_estimated` from estimator/heuristic tier; warning fires if data is sufficient |

## Verification

### Unit + integration

```bash
make test                    # all tests; expect +12 to +15 new tests passing
make check                   # ruff, ruff-format, mypy, deptry green
```

Per-test expectation: `test_emitted_diagnostics_round_trip_for_real_producer_paths` grows by 2 producer blocks; `test_catalog_has_nineteen_entries_v1` passes; `test_docstring_lists_every_catalog_id` passes after MCP docstring update.

### End-to-end against real fixture

```bash
# Greenfield mixed-model fixture (already exists from Stage 2 verification):
uv run pflow analyze-cache \
  scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md \
  --format=json | jq '.warnings[].id'
# Expect: cache.heterogeneous-models-fragment-cache present (depends on whether mixed-model declares ## Cache; verify the fixture)
```

```bash
# Brownfield against song-creator's recorded run:
uv run pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator.pflow.md \
  --from-trace scratchpads/stage2-verification/song-creator/RUN-HAIKU-FINAL-trace.json \
  --format=text
# Expect: if song-creator has mixed exact-models with shared cached chunks, warning fires.
# Today (post-Stage-2 fixes) it's all Haiku — warning correctly silent.
```

### Mutation contracts

Each of the 5 firing tests should fail with a clear assertion when the corresponding production guard is reverted. Test reviewer checks: docstring `Mutation test:` line names a real guard in `analyze.py`; reverting that guard makes the named test fail; restoring passes.

### MCP parity

```bash
uv run pflow mcp-server  # in another terminal, then:
# Use MCP client to call analyze_cache tool against the mixed-model fixture
# Expect: warnings[i].id includes the new IDs; warnings[i].context carries model_groups list
```

## Out of scope (file as follow-ups)

1. **Within-batch heterogeneity (`model: ${item.model}`)** — single batch node running N items across M exact models. `TraceExecutionIndex.llm_calls_by_key` uses `setdefault` and keeps only the FIRST batch item's call data; per-resolved-model breakdown is destroyed. Detection requires walking `tree.iter_llm_leaves` directly — fundamentally brownfield-only (greenfield can't predict per-item models). **GH issue to file after this PR lands**: extend the detector to fold trace-leaf groups into the same `model_groups` dict; clearly label as brownfield-only emission.

2. **Cross-workflow cache fragmentation (Finding #21)** — empirically verified to be a non-issue at the provider level (provider IS workflow-blind when content + model match). Memo cache scoping is workflow-bound but that's Finding #2's territory. No catalog entry needed.

3. **`canonical_model_for_cache()` primitive** — `normalize_model_name` is sufficient for v1. If real workflows hit `models/<vertex-name>` aliasing in production, the fix belongs in `normalize_model_name` itself with awareness of all callers (runtime, pricing, our detector).

4. **Provider-aware text on `cache.below-min-predicted`** (Finding #10) — separate refactor.

5. **`rerun_within_ttl_hypothetical_usd` modeling memo cache** (Finding #2) — separate refactor.
