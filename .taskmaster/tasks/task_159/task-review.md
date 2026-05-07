# Task 159 Review: Prompt Caching via Declarative `## Cache` Block

## Metadata

- **Branch**: `feat/prompt-caching` (90 commits ahead of `main`)
- **Implementation Date**: 2026-04-29 → 2026-05-07
- **Code change scale**: 366 files, +126,479 / −1,095 lines
- **Test count**: ~6,248 passing on default suite (`make test` / `-m "not e2e"`)
- **Trace format**: bumped 2.0.0 → 2.1.0 → 2.2.0 (additive)
- **JSON output format**: 1.0 → 1.1 → 2.0 → 2.1 → 4.0 (atomic cost primitives)
- **Catalog size**: closed list of **19 `cache.*` warning IDs** (started at 10 in spec)
- **Spec**: `.taskmaster/tasks/task_159/task-159.md` (~617 lines, 37 design decisions)
- **Implementation log**: `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md` (8,338 lines — read it; do not skim)

## Executive Summary

Task 159 ships provider-level prompt caching as a declarative workflow surface (`## Cache` block + per-node `prompt_cache:` opt-in), auto batch-prefix caching gated on `prewarm: true`, a new `pflow analyze-cache` command with text/JSON/MCP parity, and trace-format extensions to record cache fidelity. The cache rendering layer was end-to-end verified on real Anthropic + Gemini calls (−25% first-run, −73% rerun-within-TTL). Most volume is in the **analyzer** (`src/pflow/core/cache_analysis/`, ~9,500 LOC across 11 modules), not the rendering hot path — because diagnosing "where should I cache?" is the harder problem than "how do I emit a marker?"

## Implementation Overview

### What Was Built

**Surface** (workflow-author facing):
- New top-level `## Cache` markdown section parsed into `ir["cache"] = {ttl, items: [{name, var, prose_before, _source_line}, ...]}`.
- New per-LLM-node fields: `prompt_cache: [name1, name2, ...]` (subset of `## Cache.items`, declaration-order strict) and `prewarm: bool` (gates auto batch-prefix).
- Existing `cache: bool` (memo opt-out) remains untouched and orthogonal — see DD#5.

**Rendering** (LLM call hot path):
- Cache rendering happens in `src/pflow/core/llm_client.py` (the LiteLLM adapter seam from Task 158). `complete()` widened: `system: str | list[ContentBlock] | None`; new `user_message_blocks: list[dict] | None` for batch-prefix paths.
- Per-provider TTL translation in `src/pflow/core/cache_render.py::_build_cache_control_marker(provider_name, ttl)` (Anthropic native, Gemini → `cachedContents`, OpenAI → `prompt_cache_retention`).
- Memo-cache-hash correctness (DD#19): `compute_node_config(prompt_cache_content=)` keyword-only kwarg, conditional inclusion, mirrors `batch_config` precedent.

**Static analysis** (`pflow analyze-cache`):
- 4-mode output (greenfield / steady-state / already-optimal / `--from-trace`) at parity between text + JSON + MCP.
- 4-tier token estimation (trace → memo → estimator → heuristic) for `input_tokens_estimated`, `output_tokens_estimated`, `cacheable_tokens_estimated` — each independently sourced.
- 4-state cost (`trace` / `trace_partial` / `recomputed` / `unavailable`).
- Cross-workflow walker (Tier 2) detects rename-across-boundary, prose mismatches, value-flow opportunities.
- Discrepancy attribution (`--from-trace`): TTL expiry / chunks_skipped / key_mismatch / unknown.
- 19 stable catalog IDs at `src/pflow/core/cache_analysis/warning_catalog.py::CACHE_WARNING_CATALOG`.

**Trace format**:
- 2.1.0: `trace["workflow_path"]`, per-event `cache_key` / `cache_source` / `cache_age_sec`.
- 2.2.0: per-event cache rendering snapshot + sub-workflow cost rollup metadata.
- Filename schema: `workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json` (8-hex-char md5 of `workflow_path`) — enables O(matches) glob lookup vs. O(N) scan.

### Implementation Approach

The plan ran in **4 segments → Stage 1 verification → Stage 1.5 → Stage A/0/B/C data-model redesign → Stage 2 paid verification → 21 Stage 2 follow-up findings + 10 fix-briefs**. Each "stage" was a pause-and-review handoff because the user's directive was "no commits until end of segment, full code review at each firebreak" (4-agent code review at every boundary).

The arc that mattered:
1. **Segments 1–4**: ship the literal feature (parser, validator, hash gate, rendering, prewarm, trace, analyzer, docs).
2. **Stage 1 verification on lyrics-generator**: surfaced the architectural smell that the analyzer wasn't actually file-resolving prompts — `tokens=7` on a 3,752-token prompt (was tokenizing the literal `"./prompt.md"` filename string). Path 1 fix made `resolve_workflow` and `resolve_sub_workflow` both file-resolve at the boundary.
3. **Stage A/0/B/C data-model redesign**: collapsed pre-computed views (`recommended_actions`, `cross_workflow.*`) into derived projections from `analysis.warnings` (single source of truth). JSON 1.1 → 2.0 bump.
4. **Stage 2**: real-money verification (~$0.03 across Anthropic + Gemini smoke runs) confirmed cache rendering layer works AND surfaced 21 analyzer findings: `cacheable_tokens` 100× off, partial-trace evidence scope, paid-vs-source cost semantics for memo hits, dynamic batch cost cohorts, etc.

## Files Modified/Created

> Below: only the load-bearing modules. Comprehensive diff via `git diff main..HEAD --stat`.

### Core Changes — New modules

| File | LOC | Purpose |
|---|---|---|
| `src/pflow/core/cache_render.py` | 245 | `CacheChunkIR` / `CacheBlockIR` / `CacheRenderContext` frozen dataclasses, `_resolve_chunk_value`, `_resolve_static_prefix_for_cache`, `_ChunkAbsentSentinel`, `_build_cache_control_marker`, `deterministic_serialize`. **Lives in `core/` not `runtime/` so `nodes/llm/llm.py` can import without layer violation.** |
| `src/pflow/core/cache_overlap.py` | 193 | Detects when prompt body duplicates `## Cache` content (`cache.prompt-body-duplicates-cache` / `cache.prompt-body-shadows-cache`). |
| `src/pflow/core/llm_capabilities.py` | 130 | Per-model `get_min_cache_tokens(model)` lookup. Anthropic version-specific minimums (Sonnet 4.5: 1024; Sonnet 4.6/Haiku 3.5: 2048; Opus 4.5+/Haiku 4.5: 4096) per DD#32. Conservative-floor 4096 for unknown. |
| `src/pflow/core/llm_usage.py` | 66 | LLM usage normalization helpers consumed by analyzer + runtime. |
| `src/pflow/core/markdown_parser.py` | 292 | Extracted parser; `_SectionType.CACHE` + `_parse_cache_code_block` (chunk = `[prose-before-${var}][${var}]` pair). |
| `src/pflow/core/trace_tree.py` | 560 | Atomic cost primitives — `iter_actual_cost_events()`, `cost_for_event/node/batch_item`, `total_cost`. Single source of truth for current-run cost contract (cached LLM events count as paid-cost boundaries with observed zero). |
| `src/pflow/core/workflow_id.py` | 46 | `synthesize_inline_workflow_id(ir)` — pure utility, no internal pflow imports. Used by trace writer + analyzer autoload + memo cache scoping. |
| `src/pflow/core/cache_analysis/__init__.py` | 25 | Package surface — re-exports `analyze`, `summarize`, `render_text`, `render_json`, `JSON_FORMAT_VERSION`. |
| `src/pflow/core/cache_analysis/analyze.py` | 3,872 | Analyzer entry point. `analyze(workflow_ir, *, parameters, workflow_path, base_path, trace_path, auto_load_trace, memo_cache) -> CacheAnalysis`. |
| `src/pflow/core/cache_analysis/warning_catalog.py` | 1,241 | 19-ID closed catalog. `CacheWarningSpec` frozen dataclass. `RECOMMENDED_ACTION_PRIORITY` dict. `make_diagnostic` (catalog dispatch). `resolve_headline_for(diag)` SSoT helper. |
| `src/pflow/core/cache_analysis/render_text.py` | 1,166 | Text renderer. Section ordering. `_row_has_real_data` Option C filter. Headline-led recommendations. Multi-line cross-workflow boundary findings. |
| `src/pflow/core/cache_analysis/cost_estimation.py` | 604 | 4-state `CostDelta`. `compute_aggregate_costs`. Per-cohort projection (`current` and `optimized` always over the same row cohort to avoid >100% savings rendering). Anthropic 1h-TTL multiplier (2.0× per Spike 3 / DD#37). |
| `src/pflow/core/cache_analysis/token_estimation.py` | 419 | `estimate_tokens(model, text, *, trace, memo_cache, node_id, workflow_path) -> (int, str)`. `estimate_cacheable_tokens` 4-tier with asymmetric fall-through (declared+partial-memo → estimator; candidate-only+partial-memo → unavailable). `_estimate_ref_tokens` MOVED here (was in analyze.py); `analyze.py` re-imports for backward-compat with monkeypatch sites. |
| `src/pflow/core/cache_analysis/cross_workflow.py` | 416 | Tier 2 walker (`walk_cross_workflow → CrossWorkflowResult`). Mirrors mermaid renderer traversal. |
| `src/pflow/core/cache_analysis/padding_advisor.py` | 64 | Sensitivity floors ($0.005/advisory, $0.05 cumulative). |
| `src/pflow/core/cache_analysis/render_json.py` | 274 | JSON shape per spec; `JSON_FORMAT_VERSION = "4.0"`. |
| `src/pflow/core/cache_analysis/context.py` | 245 | `AnalysisContext` frozen dataclass — bundles `(workflow_ir, parameters, memo_cache, trace_data, workflow_path, base_path)`; methods `trace_event_for`, `cost_usd_for_node`, `resolve_ref_value`. |
| `src/pflow/core/cache_analysis/below_min_tokens_detector.py` | 92 | Unified analyzer-tier + runtime-tier (`LLMNode.post()` post-call) emission. |
| `src/pflow/core/cache_analysis/view_helpers.py` | 159 | `build_recommended_actions(warnings)` — derived view from `analysis.warnings`. `_CROSS_WORKFLOW_ALIGNMENT_IDS` filter (rename + prose-mismatch render only in Sub-workflow boundaries section). |
| `src/pflow/core/cache_analysis/summarize.py` | 121 | `--dry-run` nudge. `format_dry_run_nudge(savings_usd, savings_pct, opportunity_count)` accepts `Optional[float]/Optional[int]` — drops dollar figure entirely on None or sub-cent (tri-state contract). |
| `src/pflow/cli/commands/analyze_cache.py` | 157 | CLI command with `--format`, `--from-trace`, `--no-trace-autoload` (NOT `--no-trace` — collides with `pflow run --no-trace`), `--all-rows`. 9-condition exit-code contract. |

### Core Changes — Modified

| File | Purpose of change |
|---|---|
| `src/pflow/core/llm_client.py` | `complete()` system widened to list-of-blocks + new `user_message_blocks` kwarg. `_maybe_normalize_anthropic_1h_cost` override at `_to_adapter_response`. |
| `src/pflow/core/diagnostic.py` | Added `Diagnostic.id: str | None` (top-level stable ID per DD#27). Identity tuple updated to `(severity, source, node_id, id or message)`. New cache category constants. |
| `src/pflow/core/diagnostic_render.py` | `_format_cache_warning_or_advisory` dispatcher; closed-list `_CACHE_INLINE_CONTEXT_KEYS`. ERROR-severity `[id]` prefix shown next to title; non-error IDs unbracketed (per Stage 1 final UX). |
| `src/pflow/core/ir_schema.py` | Top-level `cache` field schema; per-node `prompt_cache: list[str]`, `prewarm: bool`, `_source_line: int`. |
| `src/pflow/core/workflow/data_flow.py` | `_validate_cache_block` + 5 helpers. STEP 1 non-LLM rejection MUST run before STEP 2 shape skip; STEP 3b (top-level checks) MUST run after STEP 2 (so `referenced_chunks` is populated for unused-chunk computation). `# noqa: C901` on this single function — clearly numbered linear contract is part of the spec. |
| `src/pflow/runtime/engine/namespaced_store.py` | **Now inherits `collections.abc.MutableMapping[str, Any]`.** Shrank from 218 → 154 lines (ABC mixin handles keys/items/values/get/setdefault/update). Bug #2 fix from Segment 3 verification (cache rendering silently dropped every dotted-path chunk because TemplateResolver did `isinstance(value, dict)` and the proxy wasn't a dict). |
| `src/pflow/runtime/template_resolver.py` | `_get_dict_value` checks `isinstance(value, Mapping)`, not `dict`. |
| `src/pflow/runtime/engine/plan_node.py` | Reordered: resolve templates BEFORE config hash. `_render_cache_for_hash` filters `_CHUNK_ABSENT` symmetrically with prep side. |
| `src/pflow/runtime/engine/instrumentation.py` | `apply_memo_hit` / `write_memo_cache` / `handle_cached_execution` widened with keyword-only `node_type_name` / `cache_key` / `created_at` / `cache_source`. `_should_write_cache_metadata(node_type_name)` allowlist gate (LLMNode only — ClaudeCodeNode INTENTIONALLY excluded). |
| `src/pflow/runtime/engine/types.py` | `NodeConfig.prompt_cache_items: tuple[str, ...]`, `prewarm: bool`. `CompiledWorkflow.cache_block: CacheBlockIR | None`. |
| `src/pflow/runtime/cache.py` | `_METADATA_KEY_SUFFIXES = ("_source_line", "_source_lines", "_source_files")` filter at `compute_node_cache_key` (closes GH #357: `pflow save` rewrites frontmatter, shifting line numbers, invalidating cache_key on every run). `_make_serializable` raises `TypeError` on `_ChunkAbsentSentinel` (defense — fires if symmetric filter ever leaks). |
| `src/pflow/runtime/workflow_trace.py` | `format_trace_filename(workflow_path, workflow_name, timestamp)` — hash-keyed schema. |
| `src/pflow/runtime/compilation/compiler.py` | `_extract_prompt_cache_items` (rejects `tuple("string")` silent-splat via explicit `isinstance(raw, list)` precondition). `_build_cache_block` produces frozen `CacheBlockIR`. |
| `src/pflow/runtime/engine/engine.py` | `_build_cache_render_dict` (sparse — LLM nodes with cache state only). Save/restore `__pflow_cache_render__` mirroring `__trace_collector__` pattern. |
| `src/pflow/runtime/workflow_executor.py` | Inline comment block above `_PROPAGATED_KEYS` documenting that `__pflow_cache_render__` is INTENTIONALLY excluded (sub-workflow isolation). |
| `src/pflow/nodes/llm/llm.py` | Imports `_resolve_chunk_value`, `_ChunkAbsentSentinel`, `_build_cache_control_marker`, `CacheRenderContext` from `core.cache_render` as **local module bindings** (divergence-injection meta-test depends on this — verified at the test-injection seam). New helpers: `_assemble_cache_prep`, `_build_user_message_blocks`, `_build_system_blocks`, `_emit_observed_below_min_cache_warning` (runtime-tier `cache.below-min-tokens` emission). |
| `src/pflow/execution/runner.py` | Removed `_resolve_file_references` method (Path 1 — boundary contract). `_build_cache_nudge` for `--dry-run` integration. |
| `src/pflow/execution/workflow_resolver.py` | `_resolve_file_refs_at_boundary` helper. Module docstring documents the boundary contract. **`ResolvedWorkflow.ir` is now fully file-resolved by contract.** |
| `src/pflow/execution/plan.py` | `_create_planner_shared` → public `create_planner_shared` (alias kept for backward-compat). `PlanEntry.cache_key` propagated. |
| `src/pflow/cli/commands/run.py` | `--cache/--no-cache` help text updated for two-cache-layer model (memo opt-out only; does NOT disable provider prompt cache). |
| `src/pflow/mcp_server/services/execution_service.py` + `tools/execution_tools.py` | MCP `analyze_cache(workflow, parameters)` parity. Locked docstring lists every catalog ID + format-version policy + tri-state cost contract. |
| `src/pflow/guide/features/caching.md` | NEW `pflow guide caching` topic (~235 lines). |

### Test Files

**Critical regression gates** (do not delete or weaken):

| Test | What it locks | Mutation contract |
|---|---|---|
| `tests/test_runtime/fixtures/golden_config_hashes.json` + `test_prompt_cache_hash.py::test_golden_baseline_hashes_match` | DD#19 byte-identity of `compute_node_config` across 30 nodes / 9 workflows. | Drifts on any change to hash inputs; regen via `scripts/generate_config_hash_baseline.py`. |
| `test_plan_drift.py::test_plan_matches_engine_for_workflow_with_prompt_cache` | Planner ↔ engine parity for cache-using workflows. | Without `_build_cache_render_dict` install in `_create_planner_shared`, planner and engine config_hash diverge silently. |
| `test_prompt_cache_rendering.py::test_resolve_chunk_value_is_imported_locally_at_both_sites` | Hash-side and prep-side import the SAME helper as local module bindings. | Catches structural divergence (one site re-imports from elsewhere); pair with `test_resolve_chunk_value_bindings_are_independent`. |
| `test_prompt_cache_rendering.py::test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store` | DD#19 production-shape (NamespacedSharedStore wrap + dotted path). REPLACED a synthetic-dict tautology that hid Bug #2. | Without `NamespacedSharedStore` ↔ `Mapping` ↔ TemplateResolver fix, dotted-path chunks silently filter as `_CHUNK_ABSENT`. |
| `test_workflow_resolver_contract.py::test_resolve_workflow_returns_fully_file_resolved_ir` | Path 1 boundary contract — every `FILE_RESOLVABLE_PARAMS` field returns resolved content. | Walks IR; failure message points future contributors at the contract docstring. |
| `test_sub_workflow_resolver.py::test_resolve_sub_workflow_cross_workflow_walker_sees_resolved_prompts` | Same boundary contract for child IRs (Stage C verification fix). | Without resolution at `resolve_sub_workflow`, `_count_llm_nodes_referencing_path` operates on filename strings → false `child_count == 0` → all cross-boundary findings suppressed. |
| `test_trace_format_2_1.py::test_handle_cached_execution_does_not_overwrite_memo_cache_source` | Bug #1 regression: `apply_memo_hit` augments `cache_source="memo"`; `handle_cached_execution` must NOT overwrite to `"in_process"`. | Sensitivity-verified: changing `cached_source = None` to `"in_process"` at engine.py:440 causes test failure. |
| `test_cache_analysis_per_id_coverage.py` (28 tests) | Every catalog ID round-trips through `Diagnostic.to_dict() → json.dumps/loads → equal dict` and carries `id` at top level. | Catches per-ID JSON serialization regressions. |
| `test_cache_analysis_per_id_emission.py` (~50+ production-shape tests) | Pitfall #19 defense — every emission test drives `analyze(...)` end-to-end with REAL `MemoizationCache.put` calls or trace fixtures. | If any emitter loses an emission path, the catalog round-trip test passes (catalog dispatch unchanged) but emission test fails (production code path broken). |

## Integration Points & Dependencies

### Incoming (consumers of this task's surface)

| Component | Interface |
|---|---|
| `pflow run` (validation pre-execution) | `validate_data_flow()` returns cache diagnostics. Structural cache errors (`cache.order-mismatch`, `cache.invalid-on-non-llm`) block run; analytical findings (`cache.below-min-tokens`, etc.) never block per DD#36. |
| `pflow save` | Round-trips `## Cache` block byte-for-byte (parser is deterministic). |
| `pflow run --dry-run` | `Runner._build_cache_nudge` calls `cache_analysis.analyze(...) → summarize_from_analysis(...)` and appends `Diagnostic(id="cache.opportunities-available")` to plan. Silent on already-optimal. |
| `pflow analyze-cache` | CLI calls `cache_analysis.analyze()` + `render_text()` / `render_json()`. |
| MCP `analyze_cache` tool | Same `analyze()` + `render_json()`. CLI/MCP parity per Task 152. |
| `pflow report` | Trace 2.1.0+ fields (`cache_source`, `cache_age_sec`, `cache_chunks_skipped`) surface in per-node report pages via `core/trace_report.py`. |
| `pflow visualize` | Cache section is invisible to mermaid (correct — graph topology unchanged). |
| `LLMNode.post()` | Emits runtime-tier `cache.below-min-tokens` via `_emit_observed_below_min_cache_warning` when provider telemetry shows 0 cache_creation/read despite declared `prompt_cache:`. |

### Outgoing (what this task depends on)

| This Task → | Via |
|---|---|
| Task 158 (LiteLLM migration) | `core/llm_client.py` adapter seam. `complete()` accepts `cache_control` content blocks. Typed `LLMCallError` exceptions. Diagnostic pipeline. |
| `core/workflow/sub_workflow_resolver.py` | Cross-workflow walker uses `resolve_sub_workflow` to traverse children. Now file-resolves at boundary (Stage C verification fix). |
| `runtime/cache.py::MemoizationCache` | Memo tier of token estimation reads `get_latest_for_node()`. `compute_node_cache_key` filters parser metadata keys (GH #357 fix). |
| `core/file_resolver.py` (Task 129) | Path 1 boundary contract — file resolution centralized at `resolve_workflow` + `resolve_sub_workflow`. |
| `core/diagnostic.py` | `Diagnostic.id` field used as identity-tuple dedup key when present. |

### Shared Store Keys

| Key | Purpose | Lifecycle |
|---|---|---|
| `__pflow_cache_render__` | `MappingProxyType` outer wrap; sparse dict `{node_id: CacheRenderContext}`. Read-only per node. | Save/restore in `WorkflowEngine.run` mirroring `__trace_collector__`. **Intentionally NOT in `_PROPAGATED_KEYS`** — sub-workflows get their own render context from their own compiled workflow. |
| `__cache_chunks_skipped__` (in prep_res) | List of chunk names that resolved to `_CHUNK_ABSENT`. | Threaded from `LLMNode.prep` → `post` (success path) and through 4 error wrap sites (`_call_llm` LLMCallError, `exec` FuturesTimeoutError, `exec_fallback`, `post` JSON-parse). `_propagate_error_to_shared` preserves it when zeroing `llm_usage`. |
| `__warnings__[node_id]` | Runtime-emitted warnings (e.g., prewarm-disabled-no-images, observed below-min-tokens). | GH #374 filed for cross-cutting modernization (workflow scoping, list-shaped values, live emission). |
| `_pflow_workflow_file` | Used by trace writer to derive `workflow_path` field on save. | For inline runs: `synthesize_inline_workflow_id(ir) → "ir-hash:<md5>"`. |

## Architectural Decisions & Tradeoffs

### Patterns established (load-bearing)

**1. Resolve at boundary, not at every consumer.** Path 1 architectural fix made `resolve_workflow` (`execution/workflow_resolver.py`) and `resolve_sub_workflow` (`core/workflow/sub_workflow_resolver.py`) both file-resolve before returning. Every downstream consumer (analyzer, validator, compiler, runner) gets resolved IR for free. The contract test (`test_resolve_workflow_returns_fully_file_resolved_ir`) catches the regression class structurally — walks every `FILE_RESOLVABLE_PARAMS` field and asserts no `is_file_reference(value)` matches.

> **For agents extending this**: do NOT add `resolve_file_references()` calls at consumer sites. Extend the boundary in `resolve_workflow()` / `resolve_sub_workflow()` and the contract test catches your work. See `architecture/architecture.md` and module docstrings for the contract.

**2. Catalog as SSoT (`warning_catalog.py`).** `CacheWarningSpec` carries `severity`, `category`, `message_template`, `headline_template`, `suggestions_templates`, `required_context_keys`, `priority`. `make_diagnostic(warning_id, **context)` is THE constructor. Adding a new ID requires:
- New row in `CACHE_WARNING_CATALOG` (DD#29 design review)
- Priority entry in `RECOMMENDED_ACTION_PRIORITY` (else falls to default 100, lowest)
- Per-id-coverage test entry (`_kwargs_for` in `test_cache_analysis_per_id_coverage.py`)
- Production emission test (Pitfall #19 — drives `analyze(...)` end-to-end)

**3. Hash-vs-prep render byte-identity (DD#19).** `plan_node._render_cache_for_hash` (Segment 2) and `LLMNode._build_system_blocks` (Segment 3) MUST resolve cache content via the SAME helper (`_resolve_chunk_value` from `core.cache_render`) and filter the SAME sentinel (`_ChunkAbsentSentinel`). Both sites import as **local module bindings** (`from pflow.core.cache_render import _resolve_chunk_value, _CHUNK_ABSENT, _ChunkAbsentSentinel`). The divergence-injection meta-test enforces this at the test-injection seam.

> **For agents touching cache rendering**: do NOT inline resolution at one site. The third line of defense — `_make_serializable` raising `TypeError` on `_ChunkAbsentSentinel` — fires if the symmetric filter ever leaks. The first two lines (symmetric helpers + symmetric filters) are what keep silent stale-cache from happening.

**4. Tri-state contracts are honest.** Three independent conventions:
- **Cost**: `priced` / `partial` / `unavailable` (NEVER `$0.00` for unavailable).
- **Token source**: `trace` / `memo` / `estimator` / `heuristic` (per-metric — `data_source`, `output_data_source`, `cacheable_data_source` may legitimately diverge).
- **Cache source**: `memo` (cross-process via SQLite) / `in_process` (same-run reuse) / fresh.

`format_dry_run_nudge(savings_usd=None)` drops the dollar figure entirely vs. emitting `-$0.00/run`. Same threshold (sub-cent < $0.005) treated as None. Top-10% codebases (mypy, ruff, rustc) consistently distinguish unavailable from zero.

**5. Honest unmeasurable convention.** When data is absent, return `None` and label it `"unavailable"`. Never fabricate from defaults. Sites: `_estimate_ref_tokens`, `_compute_model_group_costs`, `_savings_for_shared_ref`, `_emit_observed_below_min_cache_warning`. `_normalize_empty(value)` in `AnalysisContext` collapses empty `""` / `{}` / `[]` to None to push the caller to Tier 4 (otherwise `cacheable=0` looks like "we measured 0" when actually we have no data).

**6. Evidence-basis principle.** Predictive warnings about state comparisons fire only when the state to compare against exists. `cache.cross-workflow-rename-detected` requires at least one side to declare `## Cache` (the rename's premise — diverging prose labels would break byte-level cache match — is hypothetical without `## Cache` blocks). `child_count == 0` filter on cross-workflow value-flow findings (suppress when child has no LLM consumers of the value).

**7. Producer-side actionability gate.** A `cache.shared-context-undeclared` is emitted ONLY when a paste-ready `SuggestedBlock` can accompany it (clears below-min-tokens, ≥2 reusable LLM nodes, known model+tokens). Speculative or not-yet-actionable shared refs go in `Notes`, not `Recommended actions`. Single producer-side gate; no renderer-side suppression.

**8. Two-pass analyzer.** `analyze()` runs cheap detector first (`_detect_candidate_subsets` walks IR for shared template references — no tokenization), then heavy row build (`_build_per_call_rows_and_warnings` reads memo + tokenizes prompts). Order matters: Tier 2 of `estimate_cacheable_tokens` needs the candidate list to project from on greenfield workflows.

**9. Three-tier validation/analysis (DD#36).** **Analytical findings never block `pflow run`.**
- `pflow run` validation (always, fast, deterministic) — structural cache checks only; no tokenizer, no historical state.
- `pflow run --dry-run` (opt-in, slow OK) — full analytical pass.
- `pflow analyze-cache` (dedicated, slow OK) — full sectioned output + `--from-trace`.

**10. Shim pattern for relocations.** When relocating a public-internal function (e.g., `_estimate_ref_tokens` moved from `analyze.py` → `token_estimation.py`), leave a 5-line delegating shim at the old import path. Existing tests don't churn; new code uses the canonical path. Saves ~70 test-import-line edits across the recommendations refactor + Stage 0 data-model redesign.

### Tradeoffs accepted

- **Cross-workflow auto-fix suggestions deferred** (DD#26 criterion B — picking which prose canonicalizes has no obvious right answer). v1 ships warnings; agents make the call.
- **Per-item TTL not supported** (DD#7) — block-level `5m` / `1h` covers realistic cases.
- **`pflow cache apply` deferred** (DD#28) — `FixAction` typed substructure not added; `suggestions: list[str]` + `context: dict` covers v1.
- **ClaudeCodeNode out of scope** (DD#21) — uses `claude_agent_sdk` directly; SDK handles cache transparently.
- **Multi-breakpoint per-call placement deferred** (DD#11) — v1 places one `cache_control` marker per distinct subset end (1 declared + up to 1 batch auto-prefix = 2 max per call, well within Anthropic 4-marker limit).
- **`storage_mode: shared` × `## Cache`** documented as v1-unsupported in `runtime/CLAUDE.md`. No consumer reads parent cache_render after parallel batch completes; defer enforcement to v1.x if real usage hits it.

### Technical debt deliberately incurred

| Item | Rationale |
|---|---|
| **`_estimate_cacheable_tokens` 75%-of-prompt heuristic** (Tier 3 of cacheable estimation) | Conservative; clamped to `min(cacheable_tokens, input_tokens)` to prevent ratio>100%. Real per-chunk estimation is GH-deferred. |
| **BFS-downstream cache_key prediction gap** | Plan-time prediction requires knowing post-edit upstream output, which no source has. Silent-skip note tells agents "I can't predict for these N events." Documented in tacit-knowledge entry "BFS-downstream cache_key gap" of progress log. |
| **Trace 2.1.0 lacks input fingerprint** | Decision 1 detects `params={} + declared inputs` and suppresses predicted-key matching with honest note. Trace 2.2.0 recording input fingerprint is the principled long-term fix. |
| **JSON 4.0 atomic cost primitives** | Restructured cost output to expose `current_cost`, `cost_without_caching`, `cost_on_rerun`, `actually_paid` as independent atoms with their own `tier` labels. JSON 2.0 → 4.0 (skipping 3.0 for stage numbering parity). |

## Testing Implementation

### Test Strategy Applied

- **Pitfall #19 defense** drove fixture design: every emission test must drive `analyze(...)` (or `WorkflowRunner.run()`) end-to-end with REAL state (memo cache, trace JSON, NamespacedSharedStore wrap). Synthetic-dict fixtures hid 8+ bugs in this branch — search `Pitfall #19` in the progress log for the catalog of instances.
- **Mutation testing as litmus for negative fixtures**: every Tier 1 / Stage A-C fix has a docstring describing what mutating the production fix would break. Verified by `git stash` → assert test fails with locked diagnostic; `git stash pop` → passes.
- **Test isolation**: extended `tests/conftest.py::isolate_pflow_config` to patch BOTH `Path.home()` AND `os.environ["HOME"]` (production code uses both idioms; pre-existing fixture closed only some sites). Closed 2 unrelated isolation gaps as a bonus.
- **Test suite split**: `make test` (-m "not e2e") — default, fast. `make test-e2e` — real subprocess / shell-pipe boundary. `make test-all-local` — both. Trace file writes disabled by default in tests via `@pytest.mark.trace_files` opt-in.

### Critical Test Cases (top of test pyramid)

See **Test Files** table above. The 6 most load-bearing regression gates are the `golden_config_hashes`, `test_plan_drift_*_with_prompt_cache`, `_byte_equivalent_through_namespaced_store`, `_imported_locally_at_both_sites`, `_returns_fully_file_resolved_ir`, and `_does_not_overwrite_memo_cache_source`. If any of these go red on a future change, **stop and read the linked module docstring before fixing**. They're not test-coverage tests; they're contract gates.

## Unexpected Discoveries

### Gotchas Encountered

1. **`NamespacedSharedStore` was duck-typed but not type-tagged.** It implemented dict-like methods but didn't inherit `dict` or any ABC. `TemplateResolver._get_dict_value` did `isinstance(value, dict)` → False → silent template echo → `_resolve_chunk_value`'s permissive-echo branch fired → `_CHUNK_ABSENT` → cache rendering silently dropped every dotted-path chunk in production. Pure-greenfield smoke tests didn't catch it because synthetic fixtures used raw dicts. Fix: inherit `MutableMapping` (and check `Mapping` not `dict` in resolver). Module shrank 218 → 154 LOC because ABC mixin handles the helper methods.

2. **`pflow save` rewrites frontmatter on every invocation.** Adds `execution_count`, `last_execution_*`, etc. Shifts every body section's `_source_line`. `compute_node_cache_key` was consuming `resolved_inputs` verbatim, including the `_*_source_line` keys → fresh cache_key on every save → memo miss forever. Pre-existing pflow bug; fixed inline as GH #357 because shipping Task 159 without it would surprise the first user who saves a `## Cache` workflow. The compute_node_config path already filtered these for the same reason.

3. **`_scan_trace_dir` was O(N).** Reading and JSON-parsing every file in `~/.pflow/debug/` to filter by `workflow_path`. On a machine with 67k traces: 14s per `analyze-cache` invocation; 11 analyze-cache tests × 14s = ~155s cumulative (~40s wall on 4 workers). Fix: identity-encoded filenames (`workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json`) + glob lookup. Hash collision (32 bits) defended by inner `data["workflow_path"] == workflow_path` re-check.

4. **Trace JSON top-level events list is keyed `"nodes"`, not `"events"`.** Pre-fix the analyzer's token_estimation tier-1 walker read `trace.get("events")` → silent fall-through to estimator/heuristic. Synthetic test fixtures matched the buggy reader → all tests passed. One-character typo. (Pitfall #19 instance #3.)

5. **`MockLLMClient` always populates cache token fields.** Default 0 cache_creation/read. Once Stage 2 added runtime-tier `cache.below-min-tokens` emission via `LLMNode.post()`, the mock default became "cache definitively did not fire" instead of "we don't know." `test_prompt_cache_fires_under_no_cache_flag` had to be updated to stage nonzero mock telemetry. GH #375 filed for `usage_present` toggle.

6. **`SchemaValidationError` and `WorkflowValidationError` are SIBLING subclasses of `PflowError`, not related to each other.** Decision 1's `params={}` early-return covered the common case but didn't catch other `compile_workflow` failure modes (wrong input type, empty required-non-empty value, etc.). Bug A from the post-recommendations adversarial drill.

7. **The user's pushback "schema bumps are cheap" reframed cost.** Initial framing of "Fix B is 250 LOC" turned out to be 140 after honest decomposition. But asking "what does Fix B actually buy?" showed it doesn't solve the upstream-cascade scenario (post-edit upstream output unavailable from any source). The cost question masked a more important question: **does the fix solve the actual problem?** Three "fixes" turned out to all hit the same wall once data flow was traced.

### Edge Cases Found

- N=1 batches skip auto-batch-prefix (no fan-out, no savings).
- Heterogeneous batch sub-workflows: per-item cache_keys diverge for the same node_id. `_flatten_plan_keys` detects collision and drops colliding nodes (observable-only fallback) rather than picking an arbitrary winner. Top-10% pattern: refuse to attribute rather than misattribute.
- Cached LLM events are paid-cost boundaries (yield observed zero-cost evidence in `iter_actual_cost_events()`). Cached non-LLM events without LLM descendants do NOT contribute LLM cost evidence (would fabricate a zero where the workflow had no LLM cost at all).
- `cache_chunks_skipped` flows through 5 paths in `LLMNode`, not 4: success path + 4 error-wrap sites. `_propagate_error_to_shared(preserve_usage=False)` zeroes `shared["llm_usage"] = {}` so the field has to be threaded through the zeroing.

## Patterns Established

### Reusable Patterns (highest leverage)

**1. `# noqa: C901` is forbidden per user directive.** When a function nudges past complexity 10, **decompose into helpers**. The `_OPTIONAL_SCALAR_FIELDS` constants-driven loop in `_entry_to_dict` is the canonical "force-decompose" pattern. Pre-existing `# noqa: C901` (`engine.py:382`, `markdown_parser.py:264`) are NOT touched (out-of-scope grandfather rule for this task).

**2. Frozen dataclasses for shared types live in `core/`.** Layer policy: `nodes/` can import from `core/`, NOT `runtime/`. `CacheChunkIR`, `CacheBlockIR`, `CacheRenderContext` live in `core/cache_render.py`. `runtime/engine/types.py` imports `CacheBlockIR` directly (runtime → core is allowed) for `CompiledWorkflow.cache_block`.

**3. Keyword-only parameter defense.** When widening a function with new fields, use `*,` separator. Without it, `apply_memo_hit("X", {}, "default", {}, "hash", "LLMNode", "key", 1234.5)` looks plausible and would silently misroute. Cheap byte-cost; prevents future positional-arg-drift bugs.

**4. Sparse data structures with defensive consumer reads.** `_build_cache_render_dict` includes a node only if at least one of `(prompt_cache_items, prewarm, workflow.cache_block)` is set. Consumers do `(shared.get(K) or {}).get(node_id)` defensive read. Save/restore writes `_EMPTY_CACHE_RENDER` (not `None`) on restore-from-absent — defense-in-depth for consumers that drop the `or {}`.

**5. Production-shape testing as Pitfall #19 defense.** Every emission test drives `analyze(...)` (or `WorkflowRunner.run()`) end-to-end with real state (memo cache, NamespacedSharedStore wrap, real trace files). Synthetic-dict fixtures with single-root chunks are sentinels for hidden bugs.

### Anti-Patterns to Avoid

- **Lazy `__getattr__` re-export.** Tried and rejected at `cache_analysis/__init__.py`. Fights Python's module attribute caching — once a submodule is imported elsewhere, Python sets it as an attribute and `__getattr__` is bypassed. Use plain top-level imports.
- **Pre-computed views as data-model citizens.** Stage A → Stage 0 collapsed `recommended_actions`, `cross_workflow.{rename,prose,value_flow}` from `CacheAnalysis` fields → derived projections from `analysis.warnings` (single source of truth). External JSON shape preserved via on-demand filtering. Pre-computed views invite duplication and drift.
- **Filter at consumer if signal correctness depends on data.** Stage B's `child_count == 0` filter operated on broken IRs (Path 1 missed `resolve_sub_workflow`). Path 2 architectural fix: extend the boundary contract; consumer-side filters become defensible against a clean signal.
- **Synthetic test fixtures matching buggy code shapes.** Pitfall #19 has bitten this branch ≥8 times. Defense: every regression gate test must drive a real production code path.

## Breaking Changes

### API/Interface Changes

- `Diagnostic` identity tuple changed from `(severity, source, node_id, message)` to `(severity, source, node_id, id or message)`. When `id` is set, it's the dedup key. Backward-compat preserved for diagnostics not yet migrated.
- `complete()` adapter: `system: str | None` → `system: str | list[ContentBlock] | None`. Added `user_message_blocks: list[dict] | None = None`.
- `compute_node_config` keyword-only `prompt_cache_content: list[dict] | None = None`. Conditional inclusion mirrors `batch_config` precedent.
- `apply_memo_hit` / `write_memo_cache` / `handle_cached_execution` widened with keyword-only `node_type_name`, `cache_key`, `created_at`, `cache_source`. Production callers all updated; future direct callers MUST pass these.
- `WorkflowTraceCollector(*, workflow_path=None)` keyword-only kwarg.
- `NamespacedSharedStore` inherits `MutableMapping`. `__contains__(key: object)` not `key: str` (ABC requires `object`).

### Behavioral Changes

- **Trace format 2.1.0+** writes `workflow_path` field. 2.0.0 readers ignore it (forward-compatible per existing `format_version.startswith("2.")` consumer gate). Auto-load skips 2.0.0 traces (no `workflow_path`); explicit `--from-trace <path>` still works on both.
- **`pflow save` round-trips `## Cache`** byte-for-byte. Existing memo cache entries written under the old (line-shift-corrupted) cache_key become unreachable; expire naturally via 24h TTL.
- **`--no-cache` flag scope clarified**: disables pflow's local memo only. Does NOT disable LLM provider prompt caching. Documented in CLI help text + `pflow guide caching`.
- **Trace filename schema bumped**: `workflow-trace-{wf_hash}-{safe_name}-{timestamp}.json`. Existing pre-fix traces silently bypassed by autoload (no hash prefix). Acceptable per DD#34 ("auto-load is convenience; explicit loading is the contract").
- **Path 1 boundary contract**: `ResolvedWorkflow.ir` is now fully file-resolved. Two other IR-load boundaries (`runtime/compilation/compiler.py:570-581`, `core/workflow/validator.py:784-789`) keep their resolution calls — different code paths (sub-workflow children loaded by executor, child IR validation recursion).

## Future Considerations

### Extension Points

- **Adding a new catalog warning ID**: row in `CACHE_WARNING_CATALOG` + priority entry + per-id-coverage test + production emission test. Requires user/spec design review (DD#29).
- **Adding a new analyzer detection**: helper at `analyze.py`, register catalog ID, write production-shape emission test driving `analyze(...)` end-to-end with real fixtures. Use `AnalysisContext.cost_usd_for_node` / `resolve_ref_value` rather than re-marshaling inputs.
- **Trace format 2.3.0**: bump `TRACE_FORMAT_VERSION` in `runtime/workflow_trace.py`. Forward-compat gate (`format_version.startswith("2.") and not startswith("2.0")`) keeps 2.0/2.1/2.2 readers compatible. Document semantic shift in `runtime/CLAUDE.md` "Reserved Shared Store Keys" subsection.
- **JSON output bump**: additive shape changes don't bump version (consumers gate on `format_version.startswith(MAJOR)`); semantic shifts in field meaning bump minor; field removal bumps major. Document in `render_json.py` version-history block.
- **Adding a new file-resolvable param type**: extend `FILE_RESOLVABLE_PARAMS` in `core/file_resolver.py` AND the contract test catches the regression class for free.

### Scalability Concerns

- `_scan_trace_dir` was the O(N) bug; current schema is O(matches) via hash-keyed glob. Future trace-volume growth should not regress this.
- `MemoizationCache.get_latest_for_node` is queried per-LLM-node by the analyzer's memo tier; large workflows (100+ LLM nodes) make many queries. Currently fine; if it becomes hot, batch-query API would be the right shape.
- Cross-workflow walker uses `WorkflowValidator._enumerate_child_calls` for batch sub-workflow enumeration. Heterogeneous batches yield N edges; very large dynamic batches (1000+ items) could explode the walker. Filed as part of GH #360.

## AI Agent Guidance

### Quick Start for Related Tasks

**Read first** (in this order):
1. `task-159.md` (spec) — Problem framing, 37 design decisions, requirements.
2. `src/pflow/core/cache_analysis/CLAUDE.md` — current-state tacit knowledge (added during cleanup pass).
3. `src/pflow/core/cache_analysis/warning_catalog.py` — catalog SSoT structure.
4. `src/pflow/core/cache_render.py` — rendering primitives (frozen dataclasses + helpers).
5. `src/pflow/runtime/CLAUDE.md` — Reserved Shared Store Keys section (`__pflow_cache_render__`).
6. The progress log's "Tacit knowledge for the next agent" subsections at each segment boundary — these distill load-bearing knowledge.

**Patterns to follow**:
- Catalog-first thinking: every cache-related warning has a catalog row before it has a detector.
- Production-shape tests: drive `analyze(...)` or `WorkflowRunner.run()` end-to-end. Avoid synthetic-dict fixtures.
- Honest unmeasurable: return `None` when data absent, label it `"unavailable"`.
- Tri-state cost: never emit `$0.00` for unavailable. `format_dry_run_nudge` is the reference impl.
- Use `AnalysisContext` for analyzer helpers needing `(workflow_ir, parameters, memo_cache, trace_data)`. Don't add new positional kwargs to `analyze()` helpers.
- Layer policy: shared types in `core/`; consumers in `nodes/` import from `core/`, NOT `runtime/`.

### Common Pitfalls

1. **Pitfall #19 (synthetic fixtures hide production bugs).** Has bitten this branch 8+ times. Every regression gate test should drive real production code paths. Search `Pitfall #19` in the progress log for the full catalog.
2. **Hash-vs-prep render symmetry breakage.** If you touch cache rendering, both `plan_node._render_cache_for_hash` AND `LLMNode._build_system_blocks` must use the SAME helper from `core.cache_render` as local module bindings.
3. **Catalog drift between validator and analyzer.** Three IDs (`cache.order-mismatch`, `cache.unused-chunk`, `cache.invalid-on-non-llm`) have producers in BOTH `data_flow.py` AND `warning_catalog.py`. Templates were carefully matched; if you change one side, both must change in lockstep.
4. **`# noqa: C901` is forbidden.** Decompose into helpers. The constants-driven-loop pattern at `_entry_to_dict._OPTIONAL_SCALAR_FIELDS` is the canonical decomposition shape.
5. **`MockLLMClient` cache token defaults are no longer neutral.** With runtime-tier `cache.below-min-tokens` emission, default 0 cache_creation/read means "cache did not fire." Tests that exercise cache-declaring LLM calls must explicitly stage telemetry.
6. **Don't add `resolve_file_references()` calls at consumer sites.** Path 1 boundary contract: extend `resolve_workflow` / `resolve_sub_workflow`. Contract test catches regressions.
7. **`see_also=["caching"]` literal**: the repo-wide `test_all_see_also_literals_resolve_to_real_guide_topics` test enforces that the topic exists. The `caching` topic is now registered; future see_also additions must register their topics first.

### Test-First Recommendations

When modifying cache rendering:
1. Run `test_golden_baseline_hashes_match` first. If it goes red, the change touched `compute_node_config` semantics — review DD#19.
2. Run `test_resolve_chunk_value_is_imported_locally_at_both_sites` + `test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store`. These are the structural defenses.
3. Run `test_plan_drift.py` (33-34 tests). Planner ↔ engine parity.

When modifying the analyzer:
1. Run `test_cache_analysis_per_id_coverage.py` (catalog round-trip).
2. Run `test_cache_analysis_per_id_emission.py` (production-shape emission).
3. Run `test_workflow_resolver_contract.py` (Path 1 boundary).

When adding a catalog ID:
1. Add row + priority + per-id-coverage `_kwargs_for` + production emission test.
2. Update `mcp_server/tools/execution_tools.py` docstring catalog count.
3. Update `pflow guide caching` catalog table.
4. Update task-159.md spec catalog (DD#29 closed-list discipline).

---

*Generated from implementation context of Task 159. Implementation log: `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md` (8,338 lines, the load-bearing tacit-knowledge artifact). Spec: `.taskmaster/tasks/task_159/task-159.md` (~617 lines). Branch `feat/prompt-caching` — 90 commits, 366 files changed.*
