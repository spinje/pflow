# Cache Analysis Module

Static + trace-based analysis of a workflow's prompt-cache plan. Surfaces `pflow analyze-cache`, the `--dry-run` cache nudge, and the MCP `analyze_cache` tool. Reads workflow IR + optional execution trace; emits `CacheAnalysis` (data) and `Diagnostic` lists (findings).

> **Refactor planned (task 160).** This module is structured around a large `analyze.py` that absorbed multiple concerns. A pure-structural cleanup is specified in `.taskmaster/tasks/task_160/`. This document describes the **current** state — what's actually here, not what's planned.

## Disambiguation: pflow has TWO independent "cache" concepts

This is the most common source of agent confusion. Read this before anything else.

| Concept | Per-node field | Substrate | Owner |
|---|---|---|---|
| **Memoization** (pflow's local cache layer) | `cache: bool` (default `true`; `false` opts out) | `runtime/cache.py` `MemoizationCache` (SQLite at `~/.pflow/cache/cache.db`) | Memo hits skip re-execution entirely |
| **LLM provider prompt cache** (Anthropic / OpenAI / Gemini) | `prompt_cache: [name1, name2, ...]` (subset of `## Cache` block) | `prompt_cache.py` (renders content blocks with `cache_control` markers); LiteLLM adapter at `llm_client.py` emits to provider | Provider serves cached prefix; pflow still calls the LLM |

**This package (`cache_analysis/`) is exclusively about the second.** The CLI flag `--no-cache` controls *memoization* — orthogonal to this package's analysis.

The two layers interact at one point: declared `prompt_cache` content is conditionally included in the memoization config-hash so that workflows upgraded to declare prompt caching produce a fresh memo cache_key (not a stale hit on a cached output computed without the prompt prefix).

## Three different "cache key" namespaces (also confusing)

| Name | What it is | Where it lives |
|---|---|---|
| **Memo config-hash** | MD5 of the per-node config dict (resolved templates, model, params, conditional `prompt_cache` content). Determines memoization hits. | `runtime/engine/instrumentation.py::compute_node_config` |
| **LLM provider prompt cache key** | `prompt_cache_key` MD5 of the rendered cache-block content. Sent to OpenAI for sticky-routing requests sharing the prefix to the same backend (read-rate hits). | `nodes/llm/llm.py::_build_openai_cache_kwargs` |
| **Provider-side cacheable token counts** | `cache_creation_input_tokens` / `cache_read_input_tokens` reported by the provider in trace events. `input_tokens` means total prompt/input tokens after `core.llm_usage` normalization; `uncached_input_tokens` is the non-cache subset when available. | Runtime `llm_client.py`; analyzer trace reads normalize legacy traces with the same helper |

The discrepancy stage in `analyze.py` predicts **memo config-hashes** (not provider prompt cache keys) and compares them to trace events to detect when the analyzer's prediction diverged from what the engine actually computed.

## Module Structure

```
src/pflow/core/cache_analysis/
├── __init__.py                  # public API re-exports
├── analyze.py                   # orchestrator + 13 frozen dataclasses + algorithm clusters (largest module — task 160 will split)
├── context.py                   # AnalysisContext (immutable input bundle)
├── cross_workflow.py            # sub-workflow walker (DATA primitive, NOT a stage)
├── cost_estimation.py           # row-level cost projections + actually-paid math
├── token_estimation.py          # 4-tier token estimation hierarchy
├── padding_advisor.py           # sensitivity-floored padding advisories
├── below_min_tokens_detector.py # shared predicted/observed below-threshold detector
├── render_json.py               # JSON projection of CacheAnalysis
├── render_text.py               # text projection (orchestrator + section renderers)
├── render_traces_list.py        # text/json projection for trace-listing endpoints
├── summarize.py                 # one-line dry-run nudge Diagnostic
├── view_helpers.py              # recommended-actions ranking + cross-workflow filter
└── warning_catalog.py           # Frozen catalog + factory + dispatch
```

Refactor planned to split `analyze.py` into a thin orchestrator plus `stages/` and `rendering/` subdirectories — see task 160.

## Key Components — Non-Obvious Details

### analyze.py

**It is one orchestrator with internal clusters, not a flat pile of helpers.** `analyze()` builds an `AnalysisContext` and chains named stages by calling private helpers in sequence. Cluster topology (in source order):

- **13 frozen public dataclasses** at the top of the file: `PerCallRow`, `ProjectionExclusion`, `RecommendedAction`, `SuggestedBlockChunk`, `SuggestedBlock`, `CrossWorkflowFindings`, `SubWorkflowRollupEntry`, `SubWorkflowRollup`, `TraceExecutionIndex`, `CostDelta`, `TraceUnexecutedLLMRow`, `AnalysisSummary`, `CacheAnalysis` (plus the `PerNodeThresholdEntry` TypedDict). These are the package's public language but live inside the orchestrator file — this forces a documented circular-import workaround in `view_helpers.py`.
- **The orchestrator** (`analyze()` itself).
- **Trace + memo I/O loaders**: autoload from `~/.pflow/debug/`, MemoizationCache default-construction (`_default_memo_cache`, `_load_trace_explicit`, `_autoload_trace`, `_trace_aligns_with_ir`).
- **Per-call row assembly**: walks LLM nodes, builds `PerCallRow`s (`_build_per_call_rows_and_warnings`, `_build_per_call_row`, `_estimate_row_tokens`).
- **Per-node warning visitors**: **four separate functions** — `_per_node_warnings`, `_batch_prewarm_recommendations`, `_dynamic_before_static_warnings`, `_opaque_prompt_warnings`. Looks like one concern, split four ways.
- **Suggested blocks + chunk-level pricing helpers**: greenfield discovery (`_populate_suggested_blocks`, `_build_suggested_chunks_and_assignments`, `_estimate_chunk_tokens`, `_savings_for_shared_ref`).
- **Cross-workflow analytical logic**: rename / prose-mismatch / value-flow detection (`_build_cross_workflow_findings` and helpers). **The walker is in `cross_workflow.py`; the analytical logic is here.**
- **Discrepancy detection** (`_emit_discrepancy_diagnostics`, `_predict_cache_keys`): compile workflow + simulate planner + compare to trace.
- **Summary builders**: aggregation glue scattered between the orchestrator and the per-call cluster.

**Prompt ref classification**: `pflow.core.prompt_refs.classify_prompt_refs` is the canonical helper for "what does this `${X}` point to?" Every cache-analysis detector that walks `${...}` refs in an LLM prompt body should consume it. As of v0.13, production consumers cover prefix detection, prewarm detection, dynamic-before-static, batch static tail, cross-workflow LLM-consumer detection, greenfield shared-context discovery, prompt-cache-incomplete partial-declaration detection, and the runtime auto-batch-prefix path in `nodes/llm/llm.py`.

LLM `- inputs:` mappings are first-class for prompt-cache analysis. A prompt ref `${X}` mapped through `node["params"]["inputs"]` to `${item.Y}` is per-item; mapped to `${some_node.Z}` it is static. The classifier dealiases one level to match the runtime inputs-first resolution contract in `runtime/engine/template_resolution.py`; dict-valued `inputs:` entries are not recursively dealiased and pass through unchanged. Historical references to `_first_batch_scoped_template_ref` or `_is_batch_scoped_operand` should be replaced with `classify_prompt_refs` or `first_per_item_position`.

**`_run_full_validation` is the analyzer's validation seam.** It calls the same `WorkflowValidator.validate()` pipeline as run, validate-only, and save, then enriches root diagnostics with `context["affected_workflow"]` for cross-workflow scoping. Domain focus is preserved after validation: ERRORs surface universally, while advisory actions and headline counts filter to provider prompt-cache findings.

### context.py

`AnalysisContext` is the immutable input bundle threaded through all stages. The single canonical construction path is `AnalysisContext.build()` — it materializes the `TraceTree` from raw trace dict once. Direct constructor calls would skip this and produce an incoherent state.

**`resolve_ref_value(ref)` has asymmetric tier order**:

- For refs whose root is a `## Inputs` declaration: **parameters WIN over memo**. The agent's `--inputs` represents their current question; memo from a prior run with different inputs MUST NOT override.
- For refs whose root is a node id: **memo only**. Parameters never reach here because node outputs aren't passable as `--inputs`.

Empty-value normalization: returns `None` for empty string / dict / list. This is distinct from "we have a real value" and propagates as Tier-4 unavailable rather than producing false ~0-token projections.

### cross_workflow.py

**This is a WALKER, not an analytical stage.** It produces typed `CrossWorkflowEdge` and `CrossWorkflowResult` data. The cross-workflow analytical logic (rename detection, prose-mismatch, value-flow grouping) lives in `analyze.py:2134-2500` — not here.

The walker has **four downstream consumers** in `analyze.py`:
1. `_edge_child_paths(cw_result)` — extracts edge child paths for trace correlation
2. `_build_trace_execution_index(...)` — uses edge child paths
3. `_build_parameters_by_workflow(cw_result, ...)` — cross-workflow parameter resolution
4. `_build_cross_workflow_findings(cw_result=...)` — the analytical stage

Cycle handling: the root workflow path is seeded into `seen` from the outset so cycles back to the root (A → B → A) are detected at the cycle-check rather than producing a back-edge. Without this seed, downstream `_build_parameters_by_workflow` would mutate the root parameter dict.

**`is_rename` and `is_batch_alias_root` are SYNTACTIC predicates.** They answer "are the names different?" / "is the root segment the batch alias?" without judgment about whether the difference matters for caching. The decision to emit a `cache.cross-workflow-rename-detected` warning is made downstream in `analyze.py`. Post-investigation 2026-05-10: rename diagnostics are emitted for JSON/raw consumers only and are NOT rendered in CLI text. Technical reason: variable names are stripped before the provider wire format; cache fidelity is governed by prose mismatches plus undeclared sub-workflow cache inputs. Empirical reason: lyrics-generator produced 23 rename false positives for agent-facing text.

### cost_estimation.py

**Operates at row-level (post-aggregation projections), NOT chunk-level.** Two public functions:
- `compute_projections(rows, ...)` — pure tokens × rate math; never reads `row.cost_usd`. Returns `ProjectionBreakdown`.
- `compute_actually_paid(rows, *, trace=...)` — trace-driven recorded cost. Returns `ActuallyPaidCost`.

Chunk-level pricing helpers (the "if this ref were cached, how much would N callsites save?" math used by greenfield suggested-block discovery) live in `analyze.py` — `_input_rate`, `_estimate_token_savings_usd`, `_savings_for_shared_ref`, `_estimate_chunk_tokens`. These are different abstraction levels; not duplication.

**Tri-state contract (load-bearing)**: `priced` / `partial` / `unavailable`. Mirrors the LiteLLM adapter's runtime tri-state. Absolute cost atoms stay `None` on full unavailability.

**Cost deltas are summary-level domain objects.** `cost_estimation.py` still exposes low-level `ProjectionBreakdown.savings_*` values for raw arithmetic tests, but user-facing summary/JSON uses `CostDelta`: `amount_usd` is a non-negative magnitude and `kind` carries direction (`savings`, `cost_increase`, `break_even`, `unavailable`). Renderers must branch on `kind`, never infer "savings" from a signed number.

**Effective-model semantics**: `PerCallRow.model` is the effective model for analysis — observed-from-trace when consistent (single observed), IR-declared otherwise. The substitution happens once at row construction (`_build_per_call_row`); downstream consumers (cost projection, threshold checks, tokenization, rendering, fragmentation grouping) read `row.model` and get consistent behavior. IR-vs-observed divergence is disclosed at workflow level via `AnalysisSummary.ir_default_model` in the header (`IR/settings declares: X (overridden by trace evidence)`) — no per-row annotation. Multi-observed rows (trace shows multiple distinct models on one node) are NOT promoted to `model_is_heterogeneous=True`; that flag stays bound to IR-declared `${...}` so `_format_scale_line`'s "model varies per batch item" prose only fires when IR actually declared variance. Multi-observed gets `model=""` (excluded from pricing) plus `<varies>` rendering via `len(observed_models) > 1`.

**Trace coverage is not projection coverage.** `AnalysisSummary.trace_coverage` says whether static LLM rows executed. `ProjectionBreakdown.absolute_exclusions` says which executed/static rows were left out of absolute hypothetical projections (`heterogeneous_model`, `unresolved_model`, `unpriced_model`, or `missing_output_tokens`). Actual-vs-projection deltas require trace evidence and no projection exclusions; truncated traces compute the delta over the executed subset when pricing is otherwise available. With no trace, or with projection exclusions, `CostDelta.kind` stays `unavailable` with `unavailable_reason`.

**Output tokens dominate absolute costs.** Anthropic Sonnet output rate is 5× input rate; on output-heavy workflows, output cost is 60-85% of total. Cost deltas compare complete cost atoms (`no_cache_hypothetical_usd` vs `first_run_with_cache_hypothetical_usd`, etc.) so percentages are only computed over comparable baselines.

**1h-TTL Anthropic multiplier**: LiteLLM's `cache_creation_input_token_cost` is the 5-min rate (1.25× base); 1h-TTL writes cost 2× base. `_write_rate_for_ttl` applies the multiplier. Mirrors the runtime override at `llm_client.py::_maybe_normalize_anthropic_1h_cost` — keep in lockstep so predicted and actual costs price the same byte at the same rate.

### Per-call Unit Contract

`PerCallRow` token fields are per-call by contract. This includes `input_tokens_estimated`, `output_tokens_estimated`, projection `tokens_estimated` values, `chunk_tokens_estimated`, `body_tokens_estimated`, `cache_creation_input_tokens`, and `cache_read_input_tokens`. Trace rows are normalized once at the producer boundary in `_aggregate_trace_llm_calls`; downstream code must not divide again.

Workflow-level consumers multiply token fields with `invocation_count_for(row)`. That helper lives beside `PerCallRow` in `analyze.py` because it is part of the row contract: static batches use `batch_size_estimated` when known, dynamic batches use observed call count, and non-batch rows repeated through a parent batch use `observed_call_count`.

`row.cost_usd` is the deliberate exception. It is cohort actually-paid trace cost sourced through `AnalysisContext.cost_usd_for_node()` / `TraceTree.total_cost`, not through `_aggregate_trace_llm_calls`. Cost projection helpers ignore `row.cost_usd`; actual-paid aggregation sums it only on the no-trace fallback path.

Projection invariants are row-local: `cached_now_tokens_estimated`, `cache_configured.tokens_estimated`, `cache_active.tokens_estimated`, `cache_ready.tokens_estimated`, and `cache_opportunity.tokens_estimated` must not exceed `input_tokens_estimated` when known. `cache_active` is the only projection that feeds headline cost math.

### Projection model

Rows expose four projection objects:

- `cache_configured`: tokens the current workflow asks runtime to cache before provider minimum/image stripping.
- `cache_active`: configured tokens the analyzer believes remain provider-effective after known runtime gates. Only this projection may affect cost projections.
- `cache_ready`: tokens already active, configured, or unlockable with a direct cache edit in the current prompt shape.
- `cache_opportunity`: maximum provable unrealized per-call cache upside after the required edit.

`cached_now_tokens_estimated` is separate trace telemetry (`cache_creation_input_tokens + cache_read_input_tokens` when provider cache fields exist). Do not decompose provider telemetry across projection components; providers return one aggregate cache-read/write count per call.

### Staleness signals

Four independent staleness signals, four locations, no overloading:

1. **Trace staleness**: `summary.trace_workflow_relationship: null | "same_fresh" | "same_drifted" | "parent_redirect" | "different_workflow"` plus `summary.trace_model_drift_count`. Derived from `_resolve_trace_scope` + `_detect_per_node_model_drift` count. Text renders it as an indented continuation under `Trace:` so long filenames do not wrap into the signal. Narrative model-drift and redirect notes remain in `notes[]`.
2. **Memo staleness (detected)**: `summary.stale_memo_skipped_count`. Memo token/value tiers skip a memo row when its stored `cache_key` differs from `AnalysisContext.predicted_cache_keys[(workflow_path, node_id)]`; skipped rows fall through to estimator/unavailable. The accumulator is keyed by `(workflow_path, node_id)` to avoid parent/child node-id collisions.
3. **Memo staleness (uncheckable)**: `summary.stale_memo_uncheckable_count`. `_PREDICTION_SKIPPED` means prediction was attempted but intentionally skipped for that node (for example missing sub-workflow params or placeholder-tainted inputs). The memo is consumed, but the count increments so `skipped=0` does not falsely mean every consumed memo was verified fresh.
4. **Trace discovery**: `pflow analyze-cache <workflow> --list-traces` lists matching `~/.pflow/debug/workflow-trace-<hash>-*.json` files, marks the would-be autoloaded trace, includes the same disclosure note used by autoload, and annotates per-trace model drift. Drift comparison is skipped for workflows with IR-declared heterogeneous model nodes (`model=""` sentinel); unresolvable models (`None`) are silently excluded from the comparison. Empty listings exit 0 because "no traces yet" is a valid discovery result.

### token_estimation.py

**4-tier hierarchy with documented fall-through rules**: `trace → memo → estimator → heuristic`. The `estimator-partial` source is emitted when the prompt was partially-resolvable (some `${...}` refs missed); confidence aggregation treats it as estimator-tier (not heuristic) so a partially-resolved row doesn't classify the workflow as `low_no_data`.

**Symmetric fall-through for cacheable-token estimation**: when chunks can't be fully resolved (any chunk returns `None` from `_estimate_ref_tokens`), both DECLARED and CANDIDATE subsets return `(None, "unavailable")`. Honest unmeasurable. The previous declared-subset Tier 3 heuristic was deleted (F-04 fix) — it fabricated `len(prompt) * 75 // 400` token counts that didn't reflect actual cache content size and produced false-positive `cache.below-min-predicted` warnings.

**Tier 1 fall-through for declared cache that didn't fire**: when `cache_creation + cache_read == 0` in the trace event (cache declared but didn't fire — sub-threshold etc.), fall through to Tier 2 (memo/parameters) and then to unavailable if chunks still can't resolve. Downstream `cache.below-min-predicted` is emitted through `below_min_tokens_detector.py` only when there is real positive configured-token evidence, and is suppressed for observed trace-active components so it doesn't contradict trace evidence when cache demonstrably worked.

**Projection tokenization**: `tokenize_prompt_region_for_projection` can resolve parameters, memo, and trace `node_output` values through `AnalysisContext.resolve_ref_value_for_projection`. This is intentionally narrower than changing `resolve_ref_value()` globally; existing warnings keep their old resolution contract while row opportunity can use trace-backed code-node outputs.

**LiteLLM is lazy-imported** (mirrors the `llm_client.py` lazy-import pattern) to keep the analyzer package import-cheap.

### warning_catalog.py

**Frozen catalog of warning IDs.** Count is auto-derived as `EXPECTED_CATALOG_COUNT = len(CACHE_WARNING_CATALOG)` (`warning_catalog.py`) — trust the code as source of truth (currently 31). Per DD#27/29 (task-159.md), warning IDs are stable forever — adding one requires design review. This is the agent-facing API contract. Mostly ``cache.*``; one ``llm.*`` entry (``llm.thinking-temperature-mismatch``) was added when validate-time checks for non-cache provider rules became necessary.

**`Diagnostic.id` is a top-level field, not nested in `context["warning_id"]`.** Mirrors mypy / rustc / ruff / eslint / clippy convention. Identity tuple updated from `(severity, source, node_id, message)` to `(severity, source, node_id, id or message)` — when `id` is set it's the dedup key, falling back to message-keyed dedup when absent (preserves legacy sub-workflow warning dedup byte-for-byte).

**Catalog-as-SSoT for headlines**: `resolve_headline_for(diag)` looks up `headline_template` from the catalog by `diag.id` and formats against `diag.context`. **Works whether the diagnostic came from `make_diagnostic(...)` OR was built directly via `Diagnostic(id="cache.X", ...)`** — the validator emitters in `data_flow.py` use direct construction; the analyzer-side emitters use `make_diagnostic`. Both produce equivalent renderable diagnostics.

**Below-min warnings use distinct catalog IDs.** `cache.below-min-predicted` is analyzer static evidence, `cache.below-min-observed` is post-call provider telemetry, `cache.below-min-rendered` is runtime per-call marker stripping on the DECLARED channel, and `cache.prewarm-disabled-below-min` covers the prewarm cache marker failing to reach the provider — emitted by engine pre-flight (`_should_disable_below_min_prewarm`) when the static batch prefix is provably below the provider minimum at workflow entry, AND by the LLM-node dispatch strip (`_assemble_cache_prep`) when a templated model or unresolved-prefix-refs let the per-call rendering fall below the minimum. There is no evidence-kind dispatch table in the catalog; agents branch on `Diagnostic.id`.

**Prewarm-disabled is runtime-owned but catalog-backed.** Two producers, one catalog ID. (1) `build_prompt_cache_dict(workflow, shared)` can disable `CacheRenderContext.prewarm` before batch execution when the static prefix is provably below the provider minimum. It writes `cache.prewarm-disabled-below-min` to `__warnings__` and `__prewarm_disabled_below_min__[node_id] = "below_min"`. (2) `_assemble_cache_prep` in `nodes/llm/llm.py` strips a pure prewarm-channel marker at dispatch when per-call rendering falls below the minimum (templated model / unresolved refs that the pre-flight static check couldn't prove). The same catalog ID and the same `prewarm_disabled_reason` field are written in either case; LLM events carry `prewarm_disabled_reason` in trace 2.3.0 from BOTH producers.

**Routed-Anthropic advisory is runtime-emitted, INFO severity.** `cache.routed-provider-degraded` fires from `_build_system_blocks` when the model identifier looks like Anthropic routed through a proxy (substring `claude` or `anthropic` AND `detect_provider` returns None) AND multiple chunks would have benefited from per-chunk caching. INFO severity per `_determine_status`: the diagnostic surfaces in reports but does not flip workflow status to DEGRADED, so compliance-routed callers (Bedrock/Vertex) don't get a permanent regression they can't escape. Detection helper: `_looks_like_routed_anthropic(model)` in `core/prompt_cache.py`. Emitter: `_emit_routed_provider_degraded_advisory` in `nodes/llm/llm.py`. `setdefault` semantics so authoritative warnings (`cache.below-min-rendered`, `cache.prewarm-disabled-below-min`) on the same node take precedence.

**About 75% of the file is data**: catalog dict + message templates + headline templates. The remaining 25% is constructors and dispatch logic.

### render_text.py and render_json.py

Both are projections of `CacheAnalysis` — read-only, no mutation. `render_text` is one orchestrator (`render_text(analysis, all_rows=False)`) calling section renderers (header / cost block / summary / blocking errors / recommended actions / suggested blocks / cross-workflow / per-call rows / sub-workflow drill-in / notes). Each section reads only the fields it needs.

**Section visibility is deterministic from `CacheAnalysis`.** When per-call rows have no real data (greenfield, no execution), the renderer hides them and emits a Notes entry explaining the absence is intentional. The analyzer mirrors this predicate at analyze-time so the absence note appears in JSON too. Suggested-block output carries `per_node_thresholds` so greenfield recommendations show whether each node's assigned subset clears that node's model threshold.

**Trace coverage is first-class.** `AnalysisSummary.trace_coverage` is `none`, `complete`, or `truncated`. The classifier reads `trace["final_status"]` — `"truncated"` requires `final_status=="failed"` AND some static rows unexecuted (workflow died mid-run). A successful run that didn't fire conditional branches (one-of-N classify routing) classifies as `"complete"` regardless of unexecuted rows; those rows surface in `trace_unexecuted_llm_rows` for header annotation but don't trigger suppression. When a trace exists and a static LLM row is absent from `executed_keys`, the row still gets `did_not_execute_in_trace=True`, is excluded from projections, and analytical per-row warnings are suppressed for that row. **Cost-projection findings** (catalog ID with `requires_complete_trace=True` — currently only `cache.first-call-write-penalty`) are filtered when `trace_coverage=="truncated"`. **IR-derived findings** (the default — cross-workflow renames, shared-context-undeclared, etc.) flow regardless of trace coverage because they describe workflow structure, not execution evidence.

**Suggested blocks are only rendered when actionable.** If shared refs are found but assigned nodes are definitively below the provider threshold, the analyzer emits no paste-ready `## Cache` block and no `cache.shared-context-undeclared` action. It emits `cache.shared-context-undeclared-conditional` instead, naming the structural opportunity and the runtime-value precondition. Unknown threshold status still stays out of recommended actions and gets a plain note because the analyzer cannot tell whether a cache edit would fire.

**Cross-boundary recommendations (`cache.sub-workflow-cache-undeclared`) group by child workflow.** The analyzer emits one diagnostic per receiving workflow, with `context.inputs[]` listing every undeclared parent value that flows into that child. Threshold math is per consumer node and cumulative across all declared inputs, matching the per-call prefix tokens denominator (terminal marker's cumulative scope). Multi-breakpoint placement does not change this denominator. Heterogeneous consumer models use the strictest cache threshold, matching row-level cross-workflow projection and `_consolidate_to_root_advisories`. The diagnostic case is one of `actionable`, `model_switch`, `refactor`, or `unmeasurable`; text output renders the case as plain edit guidance rather than requiring agents to understand analyzer internals.

### view_helpers.py

Renderer-side projections. Five exports: `build_blocking_errors(warnings) → list[RecommendedAction]` (cache-domain ERRORs only), `build_other_blocking_errors(warnings) → list[RecommendedAction]` (non-cache ERRORs — workflow-blocking issues tangential to caching), `build_recommended_actions(warnings) → list[RecommendedAction]`, `count_rendered_findings(warnings) → tuple[int, int]`, and `is_cross_workflow_alignment(diag) → bool`.

**Lazy import inside the helper** is a documented circular-import workaround: `RecommendedAction` is defined in `analyze.py` but built here from a list of `Diagnostic`s. Top-level import would cycle.

**`_CROSS_WORKFLOW_ALIGNMENT_IDS` is a frozenset of warning IDs** (`cache.cross-workflow-rename-detected`, `cache.cross-workflow-prose-mismatch`) filtered OUT of recommended actions. `cache.cross-workflow-prose-mismatch` renders in "Sub-workflow boundaries"; `cache.cross-workflow-rename-detected` remains JSON/raw-only after the 2026-05-10 investigation because variable names do not appear on the provider wire and rendered as noise on lyrics-generator. Keep rename in the frozenset so it does not reappear in Recommended actions. **Adding a new cross-workflow alignment ID requires extending this constant in lockstep and deciding whether it renders in text or remains machine-only.**

**Action-view ranking key** (lexicographic, all ascending after negation/inversion): detection-class priority (from `RECOMMENDED_ACTION_PRIORITY` in `warning_catalog`) → savings (descending within priority tier) → severity (ERROR only for blocking errors; WARNING > INFO as a same-priority/same-savings tie-break for recommended actions) → stable alphabetical on `id`. The detection-class priority resolves the common "all INFO, no savings" case where alphabetical tiebreak used to bury actionable findings; savings before severity keeps the `ordered by impact` header honest when an INFO finding has larger projected savings than a WARNING.

### padding_advisor.py

**Sensitivity floors are load-bearing** (per spec § "Prefix-Padding Advisory"):
- Skip any individual advisory worth less than $0.005.
- Skip the entire batch when cumulative savings across surviving candidates is less than $0.05.

Without these floors, the report floods with non-actionable micro-savings advisories on workflows where padding only saves cents.

By the time a `PaddingCandidate` reaches `compute_padding_advisories`, `savings_usd` is the pre-computed dollar saving — net-positive math (extending the subset to include earlier items costs read-rate but might unlock prefix hits) is the analyzer's job upstream.

### summarize.py

**`summarize()` runs the full `analyze()` pipeline.** It is NOT a cheap shortcut — per DD#36 (task-159.md), `--dry-run` runs the full analytical pass because agents opted in. The cheaper variant `summarize_from_analysis(analysis)` exists for callers that already ran `analyze()`.

The dry-run nudge stays **silent when no actionable opportunities exist** (returns `None`). It reads `AnalysisSummary.first_run_delta` / `rerun_delta` and renders by `CostDelta.kind`: first-run savings, rerun savings, first-run added cost, or only the opportunity count when no savings is displayable. Negative-signed savings text is not allowed.

The nudge's compatibility context still exposes `estimated_savings_usd` / `estimated_savings_pct` for callers that need one headline number, but it also carries `first_run_delta_kind` and `rerun_delta_kind`. Prefer the kind fields when deciding how to phrase cost impact.

## Runtime → analyzer trace contract

The discrepancy stage and the actually-paid cost path read trace 2.1.0 fields the engine writes:

| Field | Source in runtime | Read by |
|---|---|---|
| `event["cache_source"]` (`"memo"` \| `"in_process"`) | `runtime/engine/instrumentation.py::apply_memo_hit`, `write_memo_cache`, etc. | discrepancy diagnose; trace cost summation |
| `event["cache_key"]` | same — the memo config-hash MD5 | discrepancy diagnose (compares predicted vs actual) |
| `event["cache_age_sec"]` (cache-hit events only) | `apply_memo_hit` | consumed by `trace_report.py` for "Result age" display (memo replay age only — NOT a provider-TTL signal) |
| `trace["workflow_path"]` | `runtime/workflow_trace.py::WorkflowTraceCollector` (constructor accepts it; saved to JSON unconditionally) | autoload matching by `cache_analysis.analyze:_autoload_trace`; cross-trace correlation |

Auto-load silently skips when the trace's root-level LLM `(node_id, model)` context drifts from the current IR. This mirrors the existing silent format-version / workflow-path miss behavior: `analyze-cache <workflow.pflow.md>` falls back to greenfield analysis, while explicit `--from-trace <path>` bypasses the drift gate. Sub-workflow drift is root-scoped out here; run `analyze-cache <child.pflow.md>` directly to catch child workflow changes.

**2.0.0 traces lack these fields and are skipped by autoload.** Agents pass `--from-trace <path>` to use a 2.0.0 trace explicitly. `format_version.startswith("2.")` keeps 2.0.0 readers compatible (they ignore the new fields).

**There is no Python type for this contract.** The fields are agreed-upon JSON keys. Producer and consumer must be kept in sync manually. A `TypedDict` is a candidate future addition.

## Discrepancy stage — shared predictor with --dry-run

**Both `pflow run --dry-run` and the analyzer's discrepancy stage call the same primitives:**
- `runtime/engine/plan_node.py::plan_node()` — the engine's cache-key authority
- `execution/plan.py::create_planner_shared()` — sets up the shared store

There is no duplicate predictor. `create_planner_shared` was originally `_create_planner_shared` (private) and was renamed to public in the task 159 PR specifically so the analyzer could share it. A backwards-compat alias `_create_planner_shared = create_planner_shared` is kept in `execution/plan.py`.

**Lazy imports in the discrepancy cluster are intentional.** `_build_predict_scaffold` lazy-imports `compile_workflow`, `Registry`, `create_planner_shared`, `plan_node`. These are lazy because:

- `cache_analysis.__init__` re-exports `summarize`, called on every `pflow run --dry-run`.
- LiteLLM (transitively imported by the runtime modules) costs ~700ms to load.
- Eager runtime imports would slow every dry-run by ~700ms.

**`__pflow_prompt_cache__` is installed by `create_planner_shared`** so the planner's `plan_node` produces a `config_hash` matching the engine's hash for cache-using workflows. Without this install, the analyzer's predictions would diverge silently for workflows declaring `## Cache`.

**Partial walker params get dummy-padded before compile.** When the cross-workflow walker resolves only some of a sub-workflow's declared inputs (e.g. an input that flows from an upstream sub-workflow output it can't statically reach), `_predict_one_workflow` pads the missing slots with `"__validation_placeholder__"` via `_pad_inputs_for_prediction` (same idiom as `WorkflowValidator._validate_one_child_call`). `_build_predict_scaffold` also injects `_pflow_workflow_file` so relative `@./file.ext` refs resolve against the workflow's directory. Per-node, prediction is silently skipped if the node's `prompt_cache:` references a chunk whose `var` traces to a dummied key (`_dummied_cache_chunks`) OR any `${var}` ref in the node's IR has a root in the dummied set (`_node_templates_touch`) — those predictions would carry placeholder bytes and never match the trace. Observable-field attribution (chunk-skipped) covers real skipped-chunk misses on skipped nodes; TTL expiry attribution was removed because pflow has no provider-cache age signal in traces yet. Compile failures here are debug-logged, not user-facing — the unified validator strictly precedes the prediction stage and surfaces real structural errors via `blocking_errors[]` / `other_blocking_errors[]`, so a misleading "workflow failed to compile" Note from the discrepancy stage is worse than no Note at all.

## Validator delegation

`pflow analyze-cache` runs the same `WorkflowValidator.validate()` 11-step pipeline as `pflow run`, `--validate-only`, and `pflow save`. There is no separate cache-only validation subset.

Domain focus is preserved at the renderer/aggregator boundary, not at the pipeline boundary:

- ERRORs broaden universally at the pipeline boundary: typos and broken structure block execution, so every CLI surface must show them. Domain focus is preserved at the renderer/aggregator boundary by splitting blocking errors into cache-domain (`blocking_errors[]`, rendered under `## Cache blocking errors`) and other (`other_blocking_errors[]`, rendered under `## Other blocking errors (surfaced for awareness)`). Cache-domain matches the `_is_cache_focused_for_advisory` predicate (id startswith `cache.`, `llm.thinking-temperature-mismatch`, or context.path under `cache.`/`prompt_cache`).
- WARNINGs stay cache-scoped in action UX: `build_recommended_actions` filters warning/info findings to cache-related diagnostics only. Memoization-cache lint warnings and other non-cache advisory findings remain in raw `analysis.warnings` but not in "Recommended actions".
- Derived counts stay cache-focused: `summary.actionable_opportunities`, `summary.blocking_errors`, `summary.warnings_count`, and `summary.info_count` are computed over the cache-focused subset because they drive provider prompt-cache nudges. `len(blocking_errors[])` matches `summary.blocking_errors` after the B-9 split.

`_run_full_validation` in `analyze.py` calls the unified validator with dummy-padded `extracted_params` (matching `runner.validate()` and `save_service`) and stamps `context["affected_workflow"]` on root-level diagnostics.

Per-child scoping is handled by validator step 9 itself: `_stamp_affected_workflow` in `validator.py` enriches child diagnostics with `affected_workflow=child_path` at the `_validate_one_child_call` boundary, covering load errors, file ref errors, required-input errors, parser warnings, and recursive child diagnostics.

Producer-bug exception contract: `_run_full_validation` wraps `WorkflowValidator.validate()` in `try/except Exception`. On exception, it logs at WARNING severity and surfaces a structured diagnostic so users see when validation crashed.

Per DD#20 (task-159.md), all cache structural validation lives in `core/workflow/data_flow.py::_validate_cache_block`. The analyzer never re-implements:

| Warning ID | Defined in | Severity |
|---|---|---|
| `cache.invalid-on-non-llm` | `data_flow.py::_validate_cache_block` (non-LLM rejection step) | ERROR |
| `cache.order-mismatch` | `data_flow.py::_validate_cache_block` (per-node ordering step) | ERROR |
| `cache.unused-chunk` | `data_flow.py::_validate_cache_block` (top-level unused-chunk check) | WARNING |
| `cache.prompt-body-duplicates-cache` | `data_flow.py::_validate_cache_block` (overlap check) | ERROR |
| `cache.prompt-body-shadows-cache` | `data_flow.py::_validate_cache_block` (overlap check) | WARNING |
| `llm.thinking-temperature-mismatch` | `data_flow.py::_validate_thinking_temperature_compatibility` | ERROR |

Plus four un-IDed validation diagnostics (`_make_duplicate_chunk_diagnostic`, `_make_undeclared_chunk_diagnostic`, `_make_chunk_resolution_diagnostic`, `_make_batch_scoped_rejection_diagnostic`) that surface as ERROR severity with `context.path` under `cache.` or `.prompt_cache`. The `_is_cache_focused` predicates in `analyze.py` and `view_helpers.py` treat those as cache-domain findings for aggregation and advisory filtering.

## External integration

### Production consumers (do not break these)

| Consumer | Imports | Notes |
|---|---|---|
| `cli/commands/analyze_cache.py` | `analyze, render_json, render_text` | package-level |
| `execution/runner.py` | `analyze, summarize_from_analysis` | package-level (the `--dry-run` path) |
| `mcp_server/services/execution_service.py` | `analyze, render_json` | package-level |
| `core/workflow/data_flow.py` | `warning_catalog.make_diagnostic` | direct sub-module import |

### Imports OUT of this package

| Imported | From | Why |
|---|---|---|
| `pflow.core.trace_tree.TraceTree` | `core/trace_tree.py` | shared trace-walking primitive (5 consumers across 4 packages) |
| `pflow.core.prompt_cache.deterministic_serialize` | `core/prompt_cache.py` | canonical JSON for chunk values (token estimation) |
| `pflow.runtime.template_resolver.TemplateResolver` | `runtime/template_resolver.py` | template ref resolution (lazy-imported in context.py) |
| `pflow.execution.plan.create_planner_shared` | `execution/plan.py` | discrepancy stage (lazy-imported) |
| `pflow.runtime.engine.plan_node.plan_node` | `runtime/engine/plan_node.py` | discrepancy stage (lazy-imported) |
| `pflow.runtime.compile_workflow` | `runtime/__init__.py` | discrepancy stage (lazy-imported) |
| `pflow.core.workflow.data_flow.validate_data_flow` | `core/workflow/data_flow.py` | validator delegation |
| `pflow.core.llm_providers.detect_provider` | `core/llm_providers.py` | TTL multiplier dispatch (Anthropic-only) |

## Subtle quirks worth knowing

- **`_workflow_short_name` is duplicated** in `analyze.py` and `render_text.py`. Both implement the same basename-strip-`.pflow.md` logic. The duplication is a known follow-up (task 160).
- **`__init__.py` re-exports**: `JSON_FORMAT_VERSION`, `CacheAnalysis`, `TraceListEntry`, `analyze`, `list_traces_for_workflow`, `render_json`, `render_text`, `summarize`, `summarize_from_analysis`. Public dataclasses other than `CacheAnalysis` are reachable transitively as fields of the result; importing them directly requires reaching into `analyze.py`.
- **Stable warning ID catalog**: count is auto-derived as `EXPECTED_CATALOG_COUNT = len(CACHE_WARNING_CATALOG)` (`warning_catalog.py`) — trust the code as source of truth (currently 31). Per DD#29 (task-159.md), adding new IDs requires design review. The current set spans cache-* IDs plus one `llm.*` entry (`llm.thinking-temperature-mismatch`). To enumerate exhaustively, read `CACHE_WARNING_CATALOG` keys directly rather than maintaining a list here — the code drifts faster than the doc.

## Where to add a new feature

| Want to... | Edit |
|---|---|
| Add a new cache-related warning | Catalog entry in `warning_catalog.py::CACHE_WARNING_CATALOG`, emit site in the appropriate cluster of `analyze.py` (or `data_flow.py` for structural-validation tier), test in `tests/test_core/test_cache_analysis_per_id_emission.py` |
| Change how cost projections aggregate | `cost_estimation.py::compute_projections` or `compute_actually_paid` |
| Add a new token-estimation tier | `token_estimation.py::estimate_tokens` (input) or `estimate_cacheable_tokens` |
| Change rendered text output | `render_text.py` (find the section renderer for the affected output region) |
| Change rendered JSON shape | `render_json.py` (the relevant `_X_to_dict` projection) |
| Add a new dry-run nudge condition | `summarize.py::summarize_from_analysis` (locked text format) |
| Change cross-workflow walk semantics | `cross_workflow.py` (walker only); analytical logic is in `analyze.py:_build_cross_workflow_findings` |
| Change discrepancy detection | `analyze.py` discrepancy cluster — predict + diagnose halves, glued at `_emit_discrepancy_diagnostics → _predict_cache_keys` |

## See also

- `.taskmaster/tasks/task_159/task-159.md` — the feature spec; design decisions DD#5, DD#19, DD#20, DD#26, DD#27, DD#29, DD#36, DD#37 are most relevant for this package.
- `.taskmaster/tasks/task_160/` — planned structural refactor (orchestrator split, types module, stages/ + rendering/ subdirs).
- `src/pflow/runtime/CLAUDE.md` — the runtime side of the cache-key prediction substrate (`plan_node`, `create_planner_shared`).
- `src/pflow/core/workflow/CLAUDE.md` — `data_flow.py` cache validation (the canonical home of structural cache rules).
