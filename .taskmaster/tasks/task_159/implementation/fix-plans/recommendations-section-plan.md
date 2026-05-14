# Task 159 v1 — Recommendations Section: Detection Algorithms + `suggested_blocks` Populator + `cache.discrepancy --from-trace`

## Context

Task 159 shipped the structural cache feature end-to-end (parser → IR → validator → memo-hash gate → adapter rendering → prewarm split → trace 2.1.0 → analyzer scaffolding → CLI/MCP/dry-run nudge). 5920 tests pass; the DD#19 silent-stale-cache gate holds.

What's missing: the **value-prop layer** of the analyzer. The `pflow analyze-cache` command currently answers "what does this workflow cost?" but **not** "where should I add caching?" — and the spec mode-1 example (lines 332-472 of `task-159.md`) is precisely that second question.

Concretely, 6 catalog warning IDs and 1 result-shape field never get populated:

| Surface | Current state | Gap |
|---|---|---|
| `cache.batch-prewarm-recommended` | catalog row + dispatch wired, **never emitted** | no `savings_ratio` computation |
| `cache.padding-advisory` | `padding_advisor.compute_padding_advisories()` exists, **never invoked** by `analyze.py` | candidate construction missing |
| `cache.dynamic-before-static` | catalog row + dispatch wired, **never emitted** | no prompt-template walker |
| `cache.shared-context-undeclared` (in-workflow) | catalog row + dispatch wired, **never emitted** | no cross-node reference detector |
| `cache.cross-workflow-prose-mismatch` | walker scaffolded, returns `()` | walker doesn't carry IRs to the analyzer |
| `cache.discrepancy` (`--from-trace`) | infra scaffolded, eager imports of `_resolve_chunk_value` (`analyze.py:37-41`); **no emission code** | Sub-segment C — analyzer consumes planner's predicted cache_keys + observable trace fields |
| `analysis.suggested_blocks` | initialized empty, returned empty | populator missing |

This plan closes the gap with **3 PR-sized sub-segments** (A: in-workflow detections + `suggested_blocks`; B: cross-workflow walker extension; C: `cache.discrepancy --from-trace` via planner-output consumption).

The structural backbone (catalog dispatch, `make_diagnostic`, `cache_render.py` shared helpers, `token_estimation.py` 4-tier, `cost_estimation.py` aggregate math, trace 2.1.0 schema) is locked from prior segments — this plan **consumes** those primitives.

> **This plan was reviewed in two rounds (10 specialist-agent passes total).** Round 1 found 11 Criticals → revised. Round 2 found 14 NEW Criticals introduced by Round-1 fixes — concentrated entirely in sub-segment C's predicted-key plumbing where the analyzer attempted to externally re-derive the runtime's cache_key pipeline. **Round-3 deep investigation (4 parallel pflow-searcher agents + direct code reads) surfaced the architectural fix:** the dry-run planner ALREADY produces predicted cache_keys via `plan_node`. **The right shape is "analyzer consumes planner output"** — same architectural pattern as ruff/clippy consuming rustc's analysis, mypy consuming Python's AST, ts-eslint consuming tsc's checker. Sub-segment C has been entirely rewritten around this pattern; Round-2 Criticals are obsolete by design change.

## Operating principles

- **TDD where shaped for it.** All 4 detections + populator + discrepancy emission are pure functions of `(workflow_ir, per_call_rows, optional_trace, optional_plan)` → `list[Diagnostic]`. Per-id fixtures **MUST include at least one dotted-path chunk (`${node-id.field}`)** — bare-`${concept}` fixtures from Segment 4 missed CRIT-1; mandatory structural defense.
- **Mutation-test thought experiment per detection.** Comment out `make_diagnostic("cache.X", ...)`; the per-id fixture MUST fail.
- **Verify before encoding.** Re-grep cited line numbers — auto-format may drift them.
- **One commit per sub-segment.** A → B → C in order.
- **`make test` + `make check` + `test_plan_drift.py` + `test_golden_baseline_hashes_match` green before each commit.** DD#19 hash-stability gate is sacred.
- **No new catalog IDs.** All 6 are in the catalog (12 total, locked per DD#29). Surface to user if a new ID is wanted.
- **Don't re-derive runtime semantics from outside the runtime.** Load-bearing lesson from Round 2. Sub-segment C uses `compile_workflow + build_plan` directly — the dry-run planner's drift-tested primitives. Adding `cache_key: str | None = None` to `PlanEntry` is the SOLE runtime-adjacent change in this plan.

## Verified facts (cited file:line)

These claims drive the algorithm specs below. Re-verify before patching.

**Analyzer surface:**
- `analyze.py:431-478` — `_per_node_warnings(node, row)` is the per-node integration point. Currently emits `cache.below-min-predicted` + `cache.prewarm-no-prefix`. Called from `analyze.py:223`.
- `analyze.py:202` — `suggested_blocks: list[SuggestedBlock] = []` initialized empty, never appended.
- `analyze.py:516-560` — `_build_cross_workflow_findings`: `prose_mismatches=()` and `value_flow_opportunities=()` stubbed at lines 558-559.
- `analyze.py:661-695` — `_build_recommended_actions(warnings)` does NOT filter by severity, NOT dedupe, NOT cap. Sub-segment C adds aggregation + cap (CRIT-4 from Round 1).

**Parser invariants (CRIT-1):**
- `markdown_parser.py:1707` — `name = var_expr` — chunk identifier IS the full var_expr verbatim.
- `markdown_parser.py:1755-1762` — invariant `chunk.name == chunk.var_expr` raises if they diverge.
- `markdown_parser.py:1765-1767` — IR emits `{"name", "var", "prose_before", "_source_line"}`. `name` and `var` are byte-equal full paths.

**Template walker:**
- `template_resolver.py:36` — `TEMPLATE_PATTERN` regex; iterate via `TEMPLATE_PATTERN.finditer`.
- `template_resolver.py:182-213` — `extract_root_node_id` splits on `[\.\[]`; returns BARE root only. **Don't use for declared_names membership** — chunk names are full paths.
- `template_resolver.py:185-198` — `split_coalesce_operands(expr)` for `${a ?? b}`.

**Cache render helpers:**
- `cache_render.py:128` — `_resolve_chunk_value(chunk, shared)` returns `_CHUNK_ABSENT` on `NodeStatus.ABSENT` or permissive-echo.
- `cache_render.py:213` — `_resolve_static_prefix_for_cache(template_str, shared)` substitutes via `_deterministic_serialize`.

**Auto-batch-prefix runtime precedent:**
- `nodes/llm/llm.py:350-354` — boundary regex: `re.compile(r"\$\{" + re.escape(alias) + r"(\.|\[)")` + `.search()`.

**Sub-segment C primitives (planner-consumption pattern — Round 3 verified):**
- `execution/plan.py:203-227` — `build_plan(compiled, params, cache, registry, *, workflow_name, only_node, _visited_paths, _depth, _parent_workflow_file) -> Plan`.
- `execution/plan.py:464-500` — `_create_planner_shared(compiled, params, cache, parent_workflow_file)` builds shared dict including `__pflow_cache_render__`. **Currently private (leading underscore).** C.2 promotes to public.
- `execution/result.py:82-108` — `PlanEntry` dataclass: `node_id, node_type, status, cause, action, age_sec, last_cost_usd, last_duration_ms, last_run_age_sec, sub_plan, diagnostic, batch_count, batch_parallel, batch_items_cached, batch_items_total`. **`cache_key` is NOT present today** — C.2 adds it.
- `execution/result.py:Plan` — `entries: list[PlanEntry]`, `diagnostics: list[Diagnostic]`. Sub-workflow entries have `sub_plan: Plan | None`.
- `runtime/engine/plan_node.py:35` — `NodePlan(cache_key=...)` — cache_key IS computed during planning; just not propagated onto PlanEntry today.
- `tests/test_execution/test_plan_drift.py:2088` — `test_plan_matches_engine_for_workflow_with_prompt_cache` — existing parity test catching engine ↔ planner cache_key drift on cache-using workflows. **C.2 extends this** to assert `entry.cache_key == engine_cache_key`.
- `execution/plan.py:1941-1958` — `_placeholder_child_inputs(child_ir)` — synthesizes placeholders for declared inputs (sub-workflow path; reference pattern only — analyzer catches `CompilationError` per D11).
- `execution/runner.py:386-420` — `WorkflowRunner.plan()` — the existing precedent for non-engine code calling `compile_workflow + build_plan`.

**Trace 2.1.0:**
- `runtime/workflow_trace.py:283-336` — `_collect_llm_calls_from_events` is an INSTANCE METHOD, AND skips `cached` events at line 312. **Cannot be reused for discrepancy detection.** C.1 writes a NEW ~15-LOC walker including cached events.
- `workflow_trace.py:236-241` — `event["llm_call"]` IS `llm_usage` whole. Cache fields at `event["llm_call"]["cache_key"]`, `["cache_source"]`, `["cache_age_sec"]`, `["cache_chunks_skipped"]`. Verified populated for memo HITs via `apply_memo_hit:381-387`.

**Diagnostic identity:**
- `core/diagnostic.py:101-104` — `__hash__` is `(severity, source, node_id, id or message)`. CRIT-5 from Round 1 still applies: B.3 sets `node_id=parent_node_id` for cross-workflow case to dedup-distinguish from A.4's in-workflow `node_id=None`.

**Existing tests breaking in B (CRIT-8):**
- `tests/test_core/test_cache_analysis_renderers.py:97-98` — `assert cw["prose_mismatches"] == []` and `assert cw["value_flow_opportunities"] == []`.
- `tests/test_mcp_server/test_analyze_cache_tool.py:95-96` — same.

**Catalog row required-context-keys (verbatim):**
- `cache.dynamic-before-static`: `node_id, dynamic_ref, dynamic_line, cacheable_tokens, affected_calls, savings_usd, projected_ratio_pct`
- `cache.batch-prewarm-recommended`: `node_id, batch_size, prefix_tokens_estimated, savings_pct, savings_usd`
- `cache.padding-advisory`: `node_id, current_subset, suggested_subset, savings_usd`
- `cache.shared-context-undeclared`: `node_count, shared_chunks, affected_workflow, savings_usd`
- `cache.cross-workflow-prose-mismatch`: `parent_workflow, child_workflow, chunk_name, parent_prose, child_prose`
- `cache.discrepancy`: base `node_id, trace_path, predicted_pct, actual_pct, root_cause, root_cause_summary`; **nullable** `cache_age_sec, predicted_cache_key, actual_cache_key`; per-cause `affected_workflow` (ttl_expiry) / `skipped_chunk` (chunk_skipped).

---

## Sub-segment A: In-workflow detections + `suggested_blocks` populator + validator-findings surfacing

**Scope:** ~320 LOC + ~34 tests. One commit. (Up from ~310 LOC + ~30 tests after A.6 was bundled in via the prep agent's adversarial drill 2026-04-30.)

### A.1 — `cache.batch-prewarm-recommended`

New branch in `analyze.py::_per_node_warnings`. Algorithm per spec DD#33:

```
For LLM node with batch (dict) AND prewarm not declared (or False):
  alias = batch.get("as", "item")
  unresolved = node.params.prompt
  match = re.search(r"\$\{" + re.escape(alias) + r"(\.|\[)", unresolved)
  if match is None or match.start() == 0: skip   # cache.prewarm-no-prefix covers position-0
  P = estimate_tokens(model, unresolved[:match.start()], ...).0
  D = estimate_tokens(model, unresolved[match.start():], ...).0
  if P < get_min_cache_tokens(model): skip
  N = batch_size_estimated  (from PerCallRow)
  if N is None or N < 2: skip
  savings_ratio = ((N-1) * 1.15 * P) / (N * (1.25*P + D))   # constants per spec DD#33 (fixed)
  savings_pct = round(100 * savings_ratio)
  savings_usd = compute via cost_estimation; None if unpriced
  if savings_usd is not None and savings_usd < 0.005: skip
  if savings_pct < 5 and savings_usd is None: skip
  emit make_diagnostic("cache.batch-prewarm-recommended", node_id, batch_size=N,
                       prefix_tokens_estimated=P, savings_pct, savings_usd)
```

**Mutual exclusion with `cache.prewarm-no-prefix`:** existing rule fires when `prewarm: true` AND boundary at position 0; A.1 fires when `prewarm` undeclared/False AND boundary > 0. Mutually exclusive.

**Fixture:** N=8, ~2k prefix, 100 dynamic, anthropic/sonnet. Assert `context.batch_size == 8`, `context.savings_pct ≈ 89` (exact). Negative: same workflow with `prewarm: true` → no fire.

### A.2 — `cache.padding-advisory`

New top-level helper called from `analyze()` after per-call rows.

```
declared_chunks = workflow_ir["cache"]["items"]
if not declared_chunks: return []
declared_names = [c["name"] for c in declared_chunks]
candidates: list[PaddingCandidate] = []
for each LLM node with non-empty prompt_cache:
  current_subset = tuple(node["prompt_cache"])
  first_pos = declared_names.index(current_subset[0])
  if first_pos == 0: continue
  prefix_chunks = tuple(declared_names[:first_pos])
  suggested_subset = prefix_chunks + current_subset
  prefix_tokens = sum(estimate_tokens(model, "<sample>", ...)[0] for chunk in prefix_chunks)
  call_count = derived from per_call_row
  rate = input_rate(model)
  savings_usd = 0.9 * prefix_tokens * call_count * rate if rate is not None else None
  if savings_usd is None: continue           # D10: skip unpriced models in v1
  candidates.append(PaddingCandidate(node["id"], current_subset, suggested_subset, savings_usd))
return compute_padding_advisories(candidates)   # applies floors $0.005/$0.05
```

**Fixture:** workflow with declared `[concept, concept-brief.response, scorer.response]` (dotted-path coverage), node A `prompt_cache: [scorer.response]`, node B `prompt_cache: [concept-brief.response, scorer.response]`. Assert two `cache.padding-advisory` Diagnostics; verify `context.suggested_subset` is a list.

### A.3 — `cache.dynamic-before-static` (full-path classifier — CRIT-1 fix)

```
For LLM node with non-empty prompt_cache:
  declared_names = set(item["name"] for item in workflow_ir["cache"]["items"])  # FULL PATHS
  if not declared_names: skip
  prompt = node["params"]["prompt"]
  for match in TEMPLATE_PATTERN.finditer(prompt):
    var_expr = match.group(1)
    if is_coalesce_expression(var_expr):
      operands = split_coalesce_operands(var_expr)
      is_dynamic = all(op not in declared_names for op in operands)
    else:
      is_dynamic = var_expr not in declared_names   # FULL-PATH check
    if not is_dynamic: continue
    dynamic_position = match.start()
    cacheable_after = prompt[match.end():]
    cacheable_tokens = estimate_tokens(model, cacheable_after, ...).0
    if cacheable_tokens < get_min_cache_tokens(model): break  # subsequent dynamic refs have less
    affected_calls = batch_size_estimated or 1
    rate = input_rate(model)
    savings_usd = 0.9 * cacheable_tokens * affected_calls * rate if rate is not None else None
    bytes_before = prompt[:dynamic_position]
    tokens_before = estimate_tokens(model, bytes_before, ...).0
    projected_ratio_pct = round(100 * cacheable_tokens / max(1, cacheable_tokens + tokens_before))
    dynamic_line = 1 + prompt[:dynamic_position].count("\n")
    emit make_diagnostic("cache.dynamic-before-static", node_id, dynamic_ref=var_expr,
                         dynamic_line, cacheable_tokens, affected_calls, savings_usd, projected_ratio_pct)
    break   # only emit for FIRST dynamic ref
```

**Coalesce edge case:** `${declared_a ?? undeclared_b}` is STATIC (a is declared) — matches Task 128 branch-convergence semantics.

**Fixture:** workflow declaring `creative-direction.response` (dotted-path); LLM node prompt `"Score: ${user_input}\n\n## Direction\n${creative-direction.response}\n\n[~2000 tokens of static rubric]"`. Assert fires with `context.dynamic_ref == "user_input"`. Assert `${creative-direction.response}` NOT classified as dynamic (FULL-path matches; root `creative-direction` does NOT — but full path is the check).

### A.5 — `suggested_blocks` populator (RUNS BEFORE A.4 — CRIT-6 fix)

`_populate_suggested_blocks(workflow_ir, per_call_rows, memo_cache, workflow_path) -> tuple[list[SuggestedBlock], dict[str, float | None], list[str]]`. Called from `analyze()` BEFORE A.4.

```
declared_names = set(item["name"] for item in workflow_ir.get("cache", {}).get("items", []))
ref_to_nodes: dict[var_expr, list[node_id]] = {}   # FULL-PATH keying
ref_first_seen: dict[var_expr, int] = {}            # IR order for tie-break

for node_idx, node in enumerate(workflow_ir["nodes"]):
  if node.get("type") != "llm": continue
  prompt = node["params"]["prompt"]
  seen_in_this_node: set[str] = set()
  for match in TEMPLATE_PATTERN.finditer(prompt):
    var_expr = match.group(1)
    operands = split_coalesce_operands(var_expr) if is_coalesce_expression(var_expr) else [var_expr]
    for op in operands:
      if op in seen_in_this_node: continue
      seen_in_this_node.add(op)
      ref_to_nodes.setdefault(op, []).append(node["id"])
      ref_first_seen.setdefault(op, node_idx)

shared_undeclared = [(v, n) for v, n in ref_to_nodes.items() if len(n) >= 2 and v not in declared_names]
if not shared_undeclared: return ([], {}, [])

ordered_chunks = sorted(shared_undeclared, key=lambda i: (-len(i[1]), ref_first_seen[i[0]], i[0]))
# Build chunks + per-node assignments + savings; var WRAPPED as "${full.path}" for spec mode-1 JSON.
# size_tokens_est: try memo first; fall back to 0 with note.
# estimated_savings_usd: None if any chunk unpriced (tri-state); sum otherwise.

block = SuggestedBlock(target_file=workflow_path or "<root>", ttl="5m",
                       chunks=tuple(chunks_for_block),
                       per_node_assignments=per_node_assignments,
                       estimated_savings_usd=estimated_savings_usd)
return ([block], savings_by_chunk, list(unique_nodes_using_any_shared_chunk))
```

**Renderer (`render_text.py`):** spec mode-1 dictates "## Suggested ## Cache block — {target_file}" section with paste-ready block AND per-node `prompt_cache:` assignments (W-IMPACT-W2).

**v1 scope:** greenfield only. Steady-state extension deferred (D3).

**Fixture:** workflow without `## Cache`; two LLM nodes both reference `${concept-brief.response}` AND `${concept}`. Assert `analyze().suggested_blocks` length 1; chunks ordered most-shared-first with deterministic tie-break; chunk `name == "concept-brief.response"` (full path), `var == "${concept-brief.response}"` (wrapped).

### A.4 — `cache.shared-context-undeclared` (in-workflow case)

Called AFTER A.5; consumes `(suggested_blocks, savings_by_chunk, affected_nodes)`.

```
if not suggested_blocks: return []
block = suggested_blocks[0]   # v1: greenfield single-block
emit make_diagnostic("cache.shared-context-undeclared",
                     node_id=None,                          # workflow-scoped per catalog
                     node_count=len(affected_nodes),
                     shared_chunks=[c.name for c in block.chunks],
                     affected_workflow=workflow_path or "<root>",
                     savings_usd=block.estimated_savings_usd)
```

**Fixture:** synthetic workflow without `## Cache`, two LLM nodes referencing `${concept-brief.response}` (dotted-path). Assert `context.shared_chunks == ["concept-brief.response"]`, `context.node_count == 2`.

### A.6 — Surface validator findings in `analyze()`

**Scope:** ~10 LOC + 4 tests. Bundles into sub-segment A's commit (sub-segment A already opens `analyze.py`; bundling cost near-zero).

**Why:** spec § "Strict Order Validation" line 217 says: *"Error is caught by both `pflow run` validation and `pflow analyze-cache` (via the shared `data_flow.py::validate_data_flow()` call site)."* Today `analyze.py` does NOT call `validate_data_flow()` — the validator-shipped catalog IDs (`cache.order-mismatch`, `cache.unused-chunk`, `cache.invalid-on-non-llm`) silently disappear from `pflow analyze-cache` output. After A wires up the analytical detections, the asymmetry gets worse: an analyze-cache report shows "5 cache opportunities" while a hidden `cache.order-mismatch` ERROR sits unrendered, the kind of correctness bug the cache feature was designed to surface. Surfaced by the prep agent's adversarial drill (2026-04-30).

**Implementation** — call validator and extend warnings inside `analyze()` after per-call rows (around `analyze.py:~233`, after the cross_workflow walker call):

```python
from pflow.core.workflow.data_flow import validate_data_flow

# A.6: surface validator-shipped catalog findings (cache.order-mismatch,
# cache.unused-chunk, cache.invalid-on-non-llm) so analyze-cache output is
# complete. Without this, ERROR-severity cache misconfigurations silently
# hide from analyze-cache while pflow run blocks on them — agents reading
# analyze-cache would think the workflow is fine.
#
# `check_inputs=False` because analyze-cache may run with no parameters
# (DD#35); the cache-specific checks inside _validate_cache_block don't
# depend on input resolution.
validator_diagnostics = validate_data_flow(workflow_ir, check_inputs=False)
# Filter to cache-namespaced IDs only — other data-flow diagnostics (cycles,
# undefined nodes) are out of analyze-cache's scope; they fire at pflow run.
warnings.extend(d for d in validator_diagnostics if d.id and d.id.startswith("cache."))
```

**Exit-code contract — keep advisory** (per DD#36): `pflow analyze-cache` continues to exit 0 even when ERROR-severity findings appear in `warnings[]`. Rationale:
- DD#36 declares analytical findings advisory; they never gate execution.
- The `pflow run` path is the gate — it blocks on `cache.order-mismatch` already.
- Agents who want to gate on findings inspect `warnings[].severity == "error"` from JSON output themselves; that's the right separation (decision belongs to the caller, not the tool).
- Surfacing the same diagnostic at both surfaces dedups via the existing identity tuple `(severity, source, node_id, id)` — no double-render risk.

**Tests** (add to `tests/test_core/test_cache_analysis_analyze.py`):

1. `test_analyze_surfaces_cache_order_mismatch` — workflow with out-of-order `prompt_cache:`. Assert `analyze().warnings` contains a Diagnostic with `id == "cache.order-mismatch"` and `severity == ERROR`.
2. `test_analyze_surfaces_cache_unused_chunk` — workflow with declared but unreferenced chunk. Assert `cache.unused-chunk` warning appears.
3. `test_analyze_surfaces_cache_invalid_on_non_llm` — `prompt_cache:` on a `type: shell` node. Assert `cache.invalid-on-non-llm` ERROR appears.
4. **Negative control:** `test_analyze_filters_non_cache_diagnostics` — workflow with a non-cache data-flow issue (e.g., a cycle or undefined node ref); assert no non-`cache.*` diagnostic appears in `analyze().warnings` (only `cache.*` IDs are surfaced).

**Per-id coverage update:** `test_emitted_diagnostics_round_trip_for_real_producer_paths` (in `tests/test_core/test_cache_analysis_per_id_coverage.py`) currently skips `cache.order-mismatch`, `cache.unused-chunk`, `cache.invalid-on-non-llm` via the `VALIDATOR_SHIPPED` guard. After A.6 ships, the analyzer also emits them via `analyze()` — the guard can either remain (production-driven test covers them via separate emitter) or be dropped (analyzer + validator paths dedup correctly via identity tuple). Pick at implementation time; either works.

**Out of v1.x scope:** non-cache data-flow diagnostics (cycles, undefined nodes) intentionally excluded from analyze-cache output — they're orthogonal to cache analysis and fire at `pflow run`. If users want a unified workflow-health view, that's a separate task.

**Mutation-test thought experiment:** comment out the `warnings.extend(...)` line; the three new positive tests must fail, and the negative control must still pass.

---

## Sub-segment B: Cross-workflow walker extension (prose-mismatch + value-flow)

**Scope:** ~110 LOC + ~12 tests. One commit.

### B.1 — Walker extension

`src/pflow/core/cache_analysis/cross_workflow.py` — `walk_cross_workflow` ALWAYS returns `CrossWorkflowResult` now (no conditional return — mypy clean per W-IMPACT-W4):

```python
@dataclass(frozen=True)
class CrossWorkflowResult:
    edges: tuple[CrossWorkflowEdge, ...]
    cache_items_by_workflow: dict[str, tuple[dict[str, Any], ...]]
    # Keyed by SAME label `walk_cross_workflow` uses (parent_workflow / child_workflow on edges)
```

Cache items collected eagerly per `_process_one_call` BEFORE recursion.

**Existing callers update:** ~15 call sites in `tests/test_core/test_cache_analysis_cross_workflow.py` change `edges = walk_cross_workflow(...)` → `result = walk_cross_workflow(...); edges = result.edges`. Plus 1 in `analyze.py`.

### B.2 — Prose-mismatch detection

```
for edge in result.edges:
  if edge.is_rename: continue                          # rename takes precedence per DD#26
  parent_items = result.cache_items_by_workflow.get(edge.parent_workflow, ())
  child_items = result.cache_items_by_workflow.get(edge.child_workflow, ())
  parent_by_name = {it["name"]: it for it in parent_items}
  child_by_name = {it["name"]: it for it in child_items}
  for chunk_name in parent_by_name.keys() & child_by_name.keys():
    if parent_by_name[chunk_name]["prose_before"] != child_by_name[chunk_name]["prose_before"]:
      emit make_diagnostic("cache.cross-workflow-prose-mismatch", parent_workflow, child_workflow,
                           chunk_name, parent_prose, child_prose)
```

Byte-by-byte comparison; whitespace normalization deferred to v1.x.

### B.3 — Value-flow opportunities (CRIT-1 + CRIT-5 fix)

```
for edge in result.edges:
  if edge.is_rename: continue
  if edge.parent_value_expr is None: continue
  parent_declared = {it["name"] for it in result.cache_items_by_workflow.get(edge.parent_workflow, ())}
  child_declared = {it["name"] for it in result.cache_items_by_workflow.get(edge.child_workflow, ())}
  # CRIT-1: full-path comparison (parent_value_expr is the FULL path inside ${...}).
  if edge.parent_value_expr in parent_declared: continue
  if edge.child_input_name in child_declared: continue
  # CRIT-5: node_id=parent_node_id makes this dedup-distinct from A.4 (which uses node_id=None).
  emit make_diagnostic("cache.shared-context-undeclared",
                       node_id=edge.parent_node_id,         # CRIT-5 dedup boundary
                       node_count=2,
                       shared_chunks=[edge.child_input_name],
                       affected_workflow=edge.parent_workflow,
                       savings_usd=None)                    # cross-workflow estimation deferred
```

**Fixtures:**
- `test_cross_workflow_prose_mismatch_fires_when_parent_and_child_diverge_on_dotted_path` (CRIT-1)
- `test_cross_workflow_value_flow_fires_with_distinct_node_id_for_dedup` (CRIT-5)
- `test_cross_workflow_value_flow_dedup_does_not_collide_with_in_workflow_shared_context`

**CRIT-8 — Existing tests update:**
- `test_cache_analysis_renderers.py:97-98` — refactor to construct `CacheAnalysis` directly with synthetic empty fields.
- `test_analyze_cache_tool.py:95-96` — same.

---

## Sub-segment C: `cache.discrepancy --from-trace` via planner-output consumption

**Scope:** ~120 LOC across 3 surfaces (analyzer C.1+C.3, planner extension C.2) + ~15 tests. One commit.

### Architectural decision (READ THIS FIRST)

**The dry-run planner already produces predicted cache_keys via `plan_node`.** Round-2 review found that re-implementing `compute_node_config + compute_node_cache_key + compute_batch_cache_key + resolve_templates` in a new `predicted_key.py` module produced ~9 distinct shape mismatches with the runtime — every one a silent false-positive trap. **The right pattern is "analyzer is a third consumer of `plan_node`"** (alongside engine and planner) — same architectural shape as ruff/clippy consuming rustc's HIR, mypy consuming Python's AST, ts-eslint consuming tsc's checker. **No top-10% codebase re-implements compiler semantics for analysis purposes.**

**Drift defense reuses existing infrastructure.** `tests/test_execution/test_plan_drift.py` (33+ tests) already enforces engine ↔ planner cache_key parity. The analyzer becomes a third consumer of the SAME primitive; if engine and planner ever drift on cache_keys, the EXISTING test fires. **C.2 extends `test_plan_matches_engine_for_workflow_with_prompt_cache` (line 2088) by ~5 LOC** to assert `entry.cache_key == engine_cache_key` — closing the loop. NO new structural-defense test file.

**The sole runtime-adjacent change:** add `cache_key: str | None = None` to `PlanEntry` at `execution/result.py:82-108`. Propagate from `NodePlan.cache_key` at the ~7 PlanEntry construction sites in `plan.py`. Documented as: **"PlanEntry exposes the predicted cache_key the planner already computed; previously dropped in transit."** Backward-compat (default None).

This collapses C from ~600 LOC of agonizing (Round 1 + Round 2 fix attempts) to ~120 LOC of clean reuse. **The Round-2 Critical findings (split_params return-order swap, prompt_cache_content shape mismatch, semantic_config divergence, template_params={}, NodeConfig.from_ir, layer policy violation, missing-upstream over-broad iteration, etc.) are all obsolete.** They were artifacts of solving the wrong problem.

### C.1 — Trace event walker including cached events (~15 LOC)

NEW helper `_iter_llm_events` in `analyze.py`. Mirrors `_collect_llm_calls_from_events` traversal at `workflow_trace.py:293-336` but DROPS the `if event.get("cached"): continue` skip. Yields `(node_id, event)` so consumers see both `event["cached"]` AND `event["llm_call"]`.

```python
def _iter_llm_events(events: list[dict[str, Any]]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Recursive walker that includes cached events. The trace's own
    `_collect_llm_calls_from_events` skips cached events for cost aggregation;
    discrepancy detection needs them — that's the whole point of `--from-trace`.
    """
    for event in events:
        if "llm_call" in event:
            yield event.get("node_id", "unknown"), event
        for item in event.get("batch_items", []):
            if "llm_call" in item:
                yield event.get("node_id", "unknown"), item
            yield from _iter_llm_events(item.get("events", []))
        yield from _iter_llm_events(event.get("sub_workflow_events", []))
```

### C.2 — Predicted cache_keys via `build_plan` consumption (~70 LOC across 2 files + 1 test extension)

**(a) Extend `PlanEntry`** in `execution/result.py:82-108`:
```python
cache_key: str | None = None
# Predicted cache_key from planner's plan_node call. None when entry has no cache state
# (routing errors, opaque sub-workflows, batch entries that aggregate per-item keys).
```

**(b) Propagate `cache_key=plan.cache_key` at the ~7 PlanEntry construction sites in `execution/plan.py`** (per `grep "PlanEntry("` output: lines 521, 842, 883, 895, 922, 1071, 1165, 1310, 1749, 2008). At each site where the walker has `NodePlan` in scope, add `cache_key=plan.cache_key`. Sites without NodePlan (routing errors, opaque sub-workflows) pass `cache_key=None`.

**(c) Promote `_create_planner_shared` to public.** Rename to `create_planner_shared` in `execution/plan.py:464`; keep underscore alias for in-tree backward-compat (`_create_planner_shared = create_planner_shared`). The analyzer becomes a public consumer.

**(d) Extend `test_plan_matches_engine_for_workflow_with_prompt_cache` (line 2088)** to assert `plan.entries[0].cache_key == engine_cache_key`. **THE structural defense.** Without it, future refactors of `compute_node_config` could drift PlanEntry.cache_key from runtime silently.

Concrete implementation — capture engine's actual cache_key via direct SQL on the cache db (test-only, no API change to `MemoizationCache`):

```python
# After `_run(compiled, cache, params={"concept": "caching"})` populates the memo cache:
import sqlite3
conn = sqlite3.connect(tmp_path / "cache.db")
try:
    row = conn.execute(
        "SELECT cache_key FROM cache_entries "
        "WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
        ("gen",),
    ).fetchone()
    engine_cache_key = row[0] if row else None
finally:
    conn.close()

# Then after build_plan:
gen_entry = next(e for e in plan.entries if e.node_id == "gen")
assert engine_cache_key is not None, "engine did not populate cache row"
assert gen_entry.cache_key == engine_cache_key, (
    f"PlanEntry.cache_key drift: planner={gen_entry.cache_key!r} engine={engine_cache_key!r}"
)
```

Mutation: change one PlanEntry construction site in `plan.py` to drop `cache_key=plan.cache_key` → this assertion fails immediately. ~10 LOC of test addition, including the assertion + helper SQL block.

**(e) New analyzer helpers:**

```python
def _predict_cache_keys(workflow_ir, parameters, memo_cache, workflow_path):
    """Consume the planner's predicted cache_keys. The analyzer is a third
    consumer of `plan_node` (alongside engine and planner); drift caught by
    test_plan_drift.py's existing parity assertions extended in C.2(d)."""
    from pflow.core.exceptions import CompilationError
    from pflow.execution.plan import build_plan
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow

    notes: list[str] = []
    try:
        registry = Registry()
        compiled = compile_workflow(workflow_ir, registry, parameters or {})
        plan = build_plan(
            compiled, parameters or {}, memo_cache, registry,
            _parent_workflow_file=workflow_path,
        )
    except CompilationError as exc:
        # D11-A: catch + continue with observable-only attribution.
        notes.append(
            f"Discrepancy detection: predicted-key matching unavailable ({type(exc).__name__}). "
            "Provide required inputs via `pflow analyze-cache <wf> key=value` for full detection. "
            "Observable-field attributions (TTL expiry, chunk skipped) still apply."
        )
        return {}, notes

    return _flatten_plan_keys(plan), notes


def _flatten_plan_keys(plan, acc=None):
    """Walk parent + nested sub_plans; collect node_id → cache_key flat.
    Sub-workflow internal nodes are reachable via PlanEntry.sub_plan."""
    acc = {} if acc is None else acc
    for entry in plan.entries:
        if entry.cache_key is not None:
            acc[entry.node_id] = entry.cache_key
        if entry.sub_plan is not None:
            _flatten_plan_keys(entry.sub_plan, acc)
    return acc
```

**Partial-inputs handling (D11-A):** when `compile_workflow` raises (missing required inputs, type errors), catch + append notes + return `({}, notes)`. Caller then attributes via observable fields ONLY (ttl_expiry, chunk_skipped) — `key_mismatch` is suppressed. Spec-permitted: 4-of-5 root_causes detectable from observable fields per Round-3 verification.

### C.3 — `_emit_discrepancy_diagnostics` + `_attribute_root_cause` + `_aggregate_and_cap_discrepancies` (~50 LOC)

```python
def _emit_discrepancy_diagnostics(
    workflow_ir, trace_data, parameters, memo_cache, workflow_path, notes
) -> list[Diagnostic]:
    if not str(trace_data.get("format_version", "")).startswith("2.1"):
        return []  # 2.0.0 — already noted upstream

    predicted_keys, predict_notes = _predict_cache_keys(
        workflow_ir, parameters, memo_cache, workflow_path,
    )
    notes.extend(predict_notes)

    raw_diags: list[Diagnostic] = []
    for node_id, event in _iter_llm_events(trace_data.get("nodes", [])):
        llm_call = event.get("llm_call", {})
        actual_key = llm_call.get("cache_key")
        cache_age_sec = llm_call.get("cache_age_sec")
        chunks_skipped = llm_call.get("cache_chunks_skipped")    # CRIT-7: don't default to []

        cache_create = llm_call.get("cache_creation_input_tokens") or 0
        cache_read = llm_call.get("cache_read_input_tokens") or 0
        if cache_create == 0 and cache_read == 0:
            continue  # cache wasn't engaged at all (S-SILENT-S7)

        actual_pct = round(100 * cache_read / max(1, cache_read + cache_create))
        predicted_key = predicted_keys.get(node_id)

        # When predicted_key is missing (sub-workflow internal, compile failure, batch aggregation),
        # skip key_mismatch but still attribute via observable signals (D11-A path).
        predicted_pct = (
            100 if (predicted_key is not None and predicted_key == actual_key)
            else 0
        )
        if predicted_key is None:
            # Trace-observation-only: only emit if observable signals indicate genuine discrepancy.
            if not (chunks_skipped or
                    (cache_age_sec is not None and cache_age_sec > 300)):
                continue

        if abs(predicted_pct - actual_pct) < 5 and predicted_key is not None:
            continue  # in agreement

        root_cause, summary, extra = _attribute_root_cause(
            cache_age_sec=cache_age_sec, chunks_skipped=chunks_skipped,
            predicted_key=predicted_key, actual_key=actual_key,
            ttl=workflow_ir.get("cache", {}).get("ttl"),
            provider=detect_provider(llm_call.get("model")),
            node_id=node_id, workflow_path=workflow_path,
            predicted_pct=predicted_pct, actual_pct=actual_pct,
        )

        raw_diags.append(make_diagnostic(
            "cache.discrepancy", node_id=node_id,
            trace_path=trace_data.get("workflow_path") or "<unknown>",
            predicted_pct=predicted_pct, actual_pct=actual_pct,
            root_cause=root_cause, root_cause_summary=summary,
            cache_age_sec=cache_age_sec,
            predicted_cache_key=predicted_key,                # nullable per catalog
            actual_cache_key=actual_key,                       # nullable per catalog
            **extra,
        ))

    return _aggregate_and_cap_discrepancies(raw_diags, max_total=20)


def _attribute_root_cause(*, cache_age_sec, chunks_skipped, predicted_key, actual_key,
                          ttl, provider, node_id, workflow_path, predicted_pct, actual_pct):
    # CRIT-7: distinguish None (field absent on older trace) from [] (genuinely empty).
    if chunks_skipped is None:
        return ("unknown",
                f"Cache chunks-skipped field absent on this trace event "
                f"(predicted={predicted_pct}%, actual={actual_pct}%); cannot attribute for {node_id}",
                {})
    if chunks_skipped:
        return ("chunk_skipped",
                f"Cache chunk {chunks_skipped[0]!r} skipped at runtime (branch absent)",
                {"skipped_chunk": chunks_skipped[0]})

    # CRIT-11: TTL=None → provider default. Anthropic/OpenAI/Gemini all ~5m default.
    effective_ttl = ttl
    if effective_ttl is None and provider and provider.name in {"anthropic", "openai", "gemini"}:
        effective_ttl = "5m"

    if cache_age_sec is not None:
        if effective_ttl == "5m" and cache_age_sec >= 300:
            return ("ttl_expiry",
                    f"Cache entry was {cache_age_sec:.0f}s old (>= 5m TTL); upstream write expired",
                    {"affected_workflow": workflow_path or "<root>"})
        if effective_ttl == "1h" and cache_age_sec >= 3600:
            return ("ttl_expiry",
                    f"Cache entry was {cache_age_sec:.0f}s old (>= 1h TTL)",
                    {"affected_workflow": workflow_path or "<root>"})

    if predicted_key is not None and predicted_key != actual_key:
        return ("key_mismatch",
                "Upstream value changed between predicted run and actual run",
                {})

    return ("unknown",
            f"Cannot attribute discrepancy to known causes "
            f"(predicted={predicted_pct}%, actual={actual_pct}%); inspect trace events for {node_id}",
            {})


def _aggregate_and_cap_discrepancies(diags, *, max_total):
    """Group by (node_id, root_cause); one rep per group with affected_invocations=N.
    Cap total emissions to max_total, sorted by frequency descending."""
    groups: dict[tuple[str | None, str], list[Diagnostic]] = {}
    for d in diags:
        ctx = d.context or {}
        key = (d.node_id, ctx.get("root_cause", "unknown"))
        groups.setdefault(key, []).append(d)
    aggregated: list[Diagnostic] = []
    for group in groups.values():
        rep = group[0]
        merged_context = {**(rep.context or {}), "affected_invocations": len(group)}
        # Use dataclasses.replace to avoid mutating shared context dict.
        aggregated.append(dataclasses.replace(rep, context=merged_context))
    aggregated.sort(key=lambda d: -((d.context or {}).get("affected_invocations", 1)))
    return aggregated[:max_total]
```

**Note:** `Diagnostic` is non-frozen but `make_diagnostic` may share context refs across diagnostics; `dataclasses.replace` is the defensive choice.

**Fixtures (~12 tests):**
- `test_iter_llm_events_yields_cached_events` — load-bearing walker test.
- `test_discrepancy_fires_for_ttl_expiry_with_explicit_5m`
- `test_discrepancy_fires_for_ttl_expiry_with_implicit_default` (CRIT-11)
- `test_discrepancy_fires_for_chunk_skipped` (dotted-path coverage)
- `test_discrepancy_fires_for_key_mismatch_when_inputs_provided`
- `test_discrepancy_silent_when_actual_matches_prediction`
- `test_discrepancy_skips_when_cache_chunks_skipped_field_absent` (CRIT-7)
- `test_discrepancy_skips_predicted_key_match_when_compile_fails` (D11-A)
- `test_discrepancy_observable_attribution_still_fires_when_no_predicted_keys` (D11-A)
- `test_discrepancy_silent_on_2_0_0_trace`
- `test_discrepancy_skips_when_cache_disengaged` (S-SILENT-S7)
- `test_discrepancy_aggregates_per_node_root_cause_with_cap` (CRIT-4)
- `test_discrepancy_recurses_into_sub_workflow_events`

**No `test_predicted_key_runtime_parity.py`** — drift defense IS the extended `test_plan_matches_engine_for_workflow_with_prompt_cache`.

---

## Test approach

Per-id structural emission tests in NEW `tests/test_core/test_cache_analysis_per_id_emission.py`. Each detection has a synthetic minimal workflow that triggers EXACTLY that ID via the full `analyze()` call.

Mandatory per-fixture:
1. `analyze(...).warnings` contains a Diagnostic with `id == "cache.<expected>"`.
2. Diagnostic's `context` has the catalog's required-context-keys.
3. **Specific values** (`context.batch_size == 8`, `context.savings_pct ≈ 89` exact).
4. **Negative fixture per detection** — workflow where it should NOT fire.
5. **At least one fixture per detection uses a DOTTED-PATH chunk name** (CRIT-1 structural coverage).

**Catalog-emission sync:**
```python
@pytest.mark.parametrize("warning_id", sorted(CACHE_WARNING_CATALOG.keys()))
def test_every_emittable_id_has_an_emission_fixture(warning_id):
    VALIDATOR_SHIPPED = {"cache.order-mismatch", "cache.unused-chunk", "cache.invalid-on-non-llm"}
    if warning_id in VALIDATOR_SHIPPED: pytest.skip("validator-shipped, not analyzer-emitted")
    fixtures_for_id = [n for n in dir(...) if warning_id.replace("cache.", "") in n]
    assert fixtures_for_id, f"No emission fixture for {warning_id}"
```

**Production-shape testing:** all fixtures call `analyze(...)` end-to-end with real `MemoizationCache(test_db_path)`. NO shortcut helpers.

**Drift defense for sub-segment C:** existing `test_plan_drift.py::test_plan_matches_engine_for_workflow_with_prompt_cache` (line 2088) extended with `entry.cache_key` parity assertion. NO new structural-defense test file.

---

## User decisions surfaced

### D1 — `cache.dynamic-before-static` "dynamic" classifier
**(A) Recommended:** any `${var}` whose FULL PATH is not in `## Cache.items` is dynamic. Matches spec mode-1.
(B) Stricter: only `${batch_alias.X}`. False-negatives on common case.

### D2 — `cache.shared-context-undeclared` match strategy
**(A) Recommended:** reference-based (full-path grouping). Matches spec mode-1 verbatim.
(B) Longest-common-prefix byte matching. False-positive-prone.

### D3 — `suggested_blocks` populator scope
**(A) Recommended:** greenfield only in v1.
(B) Greenfield + steady-state. Defer.

### D4 — Per-id emission test approach
**(A) Recommended:** per-id structural emission tests (new file).
(B) Byte-exact golden files. Drifts on every formatting change.

### D5 — `cache.discrepancy` predicted_pct simplification
**(A) Recommended (v1):** binary — `predicted_pct = 100 if predicted_key == actual_key else 0`.
(B) Refined: `savings_ratio × 100`. Defer.

### ~~D6 — Predicted-key fidelity strategy~~ — RESOLVED by Round-3 design change
Round 2 surfaced ~9 shape mismatches when re-implementing `compute_node_cache_key` from scratch. Round 3 verified the architectural fix: **consume `build_plan`'s predicted cache_keys directly** via the new `PlanEntry.cache_key` field. Drift caught by extended `test_plan_drift.py` parity assertion. Round-2 Criticals obsolete.

### D7 — Workflow inputs in shared-context detection
**(A) Recommended:** include workflow inputs. Spec mode-1 includes `${concept}` (a workflow input).
(B) Exclude. Avoids noise on UUID-shaped inputs.

### D8 — Nested workflow recursion for A.4 / A.5
**(A) Recommended:** root workflow only; B's walker handles boundaries.
(B) Recurse A.4/A.5 into children. Cross-attribution noise risk.

### D9 — `cache.discrepancy` aggregation + cap
**(A) Recommended:** per `(node_id, root_cause)` aggregation with `affected_invocations=N`; `max_total=20` cap, sorted by frequency descending.
(B) Per-event emission, no cap. Floods Recommendations on noisy traces.

### D10 — `cache.padding-advisory` for unpriced models
**(A) Recommended (current):** skip emission when `savings_usd is None`.
(B) Add nullable `savings_usd` to catalog. DD#29 catalog tweak.

### D11 — `cache.discrepancy` when `compile_workflow` fails / inputs partial — NEW
When `pflow analyze-cache <wf> --from-trace <path>` runs WITHOUT all required inputs, `compile_workflow` may raise `CompilationError`.

**(A) Recommended:** catch `CompilationError`, append notes entry, continue with **observable-only attribution** (ttl_expiry / chunk_skipped / unknown). 4-of-5 root_causes still detect; `key_mismatch` suppressed. **No false positives.** Spec-permitted (catalog row's `predicted_cache_key` is nullable; spec line 269 explicitly accepts "omits cache-key-correlated analysis with an info message").
(B) Require full inputs (Click validation error). Stricter; blocks the "I have a workflow file and a trace, show me what's wrong" exploration path.
(C) Use placeholder inputs (`_placeholder_child_inputs` pattern). Predicted keys derived from placeholders → false `key_mismatch` on every input-referencing node. Noise.

**Importance: 3/5.** (A) is the safe default; matches spec DD#35 "inputs are optional."

---

## Sub-segment dependencies + commit order

| Order | Sub-segment | Structural depends on | Tests gate |
|---|---|---|---|
| 1 | A — In-workflow detections + `suggested_blocks` populator + summarize.py G-tweak | none | A.x emission tests + G-tweak test + golden hash baseline + `test_plan_drift.py` |
| 2 | B — Cross-workflow walker extension + prose-mismatch + value-flow | none (independent of A) | B.x emission tests + existing test updates (CRIT-8) + walker regression |
| 3 | C — `cache.discrepancy --from-trace` via planner consumption (incl. `PlanEntry.cache_key` extension) | none (independent of A and B) | C.x emission tests + extended `test_plan_drift.py` parity (cache_key assertion) + 2.0.0/2.1.0 trace fixtures |

**A, B, C are all structurally independent.** Recommended ordering is A → B → C for UX (A delivers the highest-visibility recommendations + suggested blocks first; B layers cross-workflow detections; C adds trace-mode discrepancies). If any sub-segment is blocked, the others still ship. C.3's algorithm reads trace events directly (NOT per-call rows), so it doesn't need A's data.

---

## Files to modify

**Sub-segment A (production):**
- `src/pflow/core/cache_analysis/analyze.py` — extend `_per_node_warnings`; add `_emit_padding_advisories` + `_populate_suggested_blocks` + `_emit_shared_context_warnings`; **A.6: import `validate_data_flow` and surface validator-shipped catalog findings (~10 LOC)**. ~220 LOC total.
- `src/pflow/core/cache_analysis/cost_estimation.py` — helpers for per-detection savings_usd + 1h-TTL. ~30 LOC.
- `src/pflow/core/cache_analysis/render_text.py` — Suggested ## Cache block rendering INCLUDING per-node assignments (W-IMPACT-W2). ~80 LOC.
- `src/pflow/core/cache_analysis/render_json.py` — populate `suggested_blocks`. ~10 LOC.
- `src/pflow/core/cache_analysis/summarize.py` — G-tweak per CRIT-10 (`aggregate_savings_first_run_usd` first). ~10 LOC delta.

**Sub-segment A (tests):**
- `tests/test_core/test_cache_analysis_per_id_emission.py` — NEW. ~25 tests.
- `tests/test_core/test_cache_analysis_summarize.py` — append G-tweak test. +1 test.
- `tests/test_core/test_cache_analysis_analyze.py` — append A.6 validator-surfacing tests (3 positive + 1 negative control). +4 tests.

**Sub-segment B (production):**
- `src/pflow/core/cache_analysis/cross_workflow.py` — `CrossWorkflowResult` + always-collect `cache_items_by_workflow`. ~50 LOC.
- `src/pflow/core/cache_analysis/analyze.py` — extend `_build_cross_workflow_findings` for prose-mismatch + value-flow. ~50 LOC.

**Sub-segment B (tests + existing-test updates):**
- `tests/test_core/test_cache_analysis_per_id_emission.py` — append B.x fixtures. ~7 tests.
- `tests/test_core/test_cache_analysis_cross_workflow.py` — extend + update ~15 callers (`edges = walk(...)` → `result = walk(...); edges = result.edges`). ~5 new tests.
- **`tests/test_core/test_cache_analysis_renderers.py:97-98`** — UPDATE assertions (CRIT-8).
- **`tests/test_mcp_server/test_analyze_cache_tool.py:95-96`** — UPDATE assertions (CRIT-8).

**Sub-segment C (production — 3 surfaces):**
- `src/pflow/execution/result.py:82-108` — add `cache_key: str | None = None` to `PlanEntry`. ~1 LOC.
- `src/pflow/execution/plan.py` — propagate `cache_key=plan.cache_key` at ~7 PlanEntry construction sites; rename `_create_planner_shared` → `create_planner_shared` (public; keep underscore alias). ~15 LOC delta.
- `src/pflow/core/cache_analysis/analyze.py` — add `_iter_llm_events`, `_predict_cache_keys`, `_flatten_plan_keys`, `_emit_discrepancy_diagnostics`, `_attribute_root_cause`, `_aggregate_and_cap_discrepancies`. **Integration point in `analyze()`:** call `_emit_discrepancy_diagnostics(...)` AFTER `_build_cross_workflow_findings` extends warnings (analyze.py:~234) and BEFORE `_aggregate_confidence` is called (analyze.py:~237). Append result to the same `warnings: list[Diagnostic]` accumulator. Pass the existing `notes: list[str]` so `notes` entries from `_predict_cache_keys` (e.g., the D11-A `CompilationError` path) flow into `analysis.notes`. ~100 LOC.

**Sub-segment C (tests):**
- `tests/test_core/test_cache_analysis_per_id_emission.py` — append C.x fixtures. ~12 tests.
- `tests/test_execution/test_plan_drift.py:2088` — extend `test_plan_matches_engine_for_workflow_with_prompt_cache` with `entry.cache_key == engine_cache_key` assertion (direct SQL on cache db; full code in C.2 spec above). ~10 LOC.

**Total estimate:** ~580 production LOC + ~56 tests across 3 commits. (Up from ~570 + ~52 after A.6 was bundled into sub-segment A.)

---

## Verification

### Per sub-segment

```bash
make test                                              # full suite green
make check                                             # ruff + ruff-format + mypy + deptry
uv run pytest tests/test_execution/test_plan_drift.py  # extended in C with cache_key parity
uv run pytest tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match  # DD#19
```

### End-to-end smoke (after sub-segment A)

Synthetic workflows under `scratchpads/recommendations-verification/`:

```bash
uv run pflow analyze-cache scratchpads/recommendations-verification/greenfield-dotted.pflow.md
```

Expected (per spec mode-1):
- Recommendations section with `cache.shared-context-undeclared` entries.
- `## Suggested ## Cache block` section with paste-ready block AND per-node assignments.
- **CRITICAL:** chunks include dotted-path names (CRIT-1 verification).

### End-to-end smoke (after sub-segment C)

```bash
uv run pflow analyze-cache <workflow-path> --from-trace ~/.pflow/debug/<latest>.json
uv run pflow analyze-cache <workflow-path> --from-trace ~/.pflow/debug/<latest>.json sources='[...]'  # full inputs
```

Expected (per spec mode-4):
- Discrepancies section with `cache.discrepancy` entries when predicted ≠ actual.
- Without inputs: `notes` entry "predicted-key matching unavailable" + observable-only attributions still fire (D11-A behavior).
- With full inputs: `key_mismatch` attribution fires when upstream values changed.
- Aggregated per `(node_id, root_cause)`; total ≤ 20.

### Lyrics-generator end-to-end (DEFERRED — needs explicit user permission)

Per agent-handoff: don't touch `/Users/andfal/projects/music-generation/` without asking.

---

## Out of scope (defer to v1.x)

- Real per-chunk token estimation (`_estimate_cacheable_tokens` is 75%-of-prompt heuristic).
- Steady-state `suggested_blocks` extension (greenfield only per D3).
- `parallel_write_race` discrepancy attribution (cross-event correlation).
- Refined `predicted_pct` (savings_ratio × 100 per D5).
- Byte-exact golden files (per-id structural is the v1 floor per D4).
- Anthropic 1h-TTL cost override drift detection (lockstep removal at `llm_client.py:1047` + `cost_estimation.py` once LiteLLM upstream pricing fix lands).
- Recursive A.4/A.5 into nested workflows (D8).
- Cleaner `cache.shared-context-undeclared` rendering when `savings_usd=None` (DD#29 catalog change).
- Prose normalization for `cache.cross-workflow-prose-mismatch` (whitespace tolerance).
- Sub-workflow internal LLM nodes when parent `compile_workflow` fails (D11). The `_flatten_plan_keys` recursion handles the success case via `entry.sub_plan`.

---

## Notes for the executing agent

1. **Read `task-159.md` spec mode-1 (lines 332-472) AND mode-4 (lines 485-493) end-to-end before starting.**
2. **Re-grep before patching.** Auto-format may have shifted line numbers since plan-write. Find `_per_node_warnings`, `suggested_blocks: list = []`, `_build_cross_workflow_findings`, the 7 PlanEntry constructor sites by string search.
3. **TDD per detection.** Per-id emission fixture FIRST in `test_cache_analysis_per_id_emission.py`; watch fail → implement → watch pass. Mandatory dotted-path coverage.
4. **Mutation-test thought experiment per detection.** Comment out `make_diagnostic`; fixture MUST fail.
5. **Sub-segment C order: extend `PlanEntry` first, propagate, extend the parity test, run tests, THEN write the analyzer side.** If the parity test passes after PlanEntry extension, the runtime-adjacent change is correct. THEN the analyzer becomes a simple consumer.
6. **Don't try to predict cache_keys outside the planner.** That was Round 1's wrong approach. Use `build_plan` and read `entry.cache_key`. The drift defense already exists.
7. **`make_diagnostic` validates required context keys at construction.** Use the catalog row's `required_context_keys` (cited verbatim) as authoritative.
8. **`_resolve_chunk_value` and `_resolve_static_prefix_for_cache` are load-bearing for A.3/A.4/A.5 byte-identity.** Use them — don't inline.
9. **The user's working style:** "20 turns over a wrong design." Surface algorithm decisions before encoding. D1-D11 are pre-surfaced; new ones during implementation follow the same shape (option A/B/C + recommendation + tradeoff + importance score).
10. **The user's load-bearing principle:** "prioritize simplicity of the FINAL code, not how easy it is to get there." If a design choice is locally easier but produces uglier final code (e.g., re-implementing runtime semantics outside the runtime), pick the cleaner end-state even if the path is longer. Apply the "what would top-10% codebases do?" test at every fork.
11. **After each commit, optionally run `/code-review`** (7 agents, no `review-plan`) against staged changes.
12. **One commit per sub-segment.** A → B → C. Don't bundle.

---

## Critical files (absolute paths)

**Production (modify):**
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/cross_workflow.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/render_text.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/render_json.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/cost_estimation.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/summarize.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/execution/result.py` (sub-segment C: `PlanEntry.cache_key` field)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/execution/plan.py` (sub-segment C: propagate cache_key; promote `_create_planner_shared` to public)

**Reusable primitives (consume only):**
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_render.py` — `_resolve_chunk_value`, `_resolve_static_prefix_for_cache`, `_CHUNK_ABSENT`, `deterministic_serialize`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/warning_catalog.py` — catalog rows + `make_diagnostic`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/token_estimation.py` — `estimate_tokens`, `estimate_output_tokens`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/padding_advisor.py` — `compute_padding_advisories`, `PaddingCandidate`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/runtime/template_resolver.py` — `TEMPLATE_PATTERN`, `split_coalesce_operands`, `is_coalesce_expression` (NOT `extract_root_node_id` — full-path classifier)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/runtime/engine/plan_node.py` — `plan_node` (load-bearing primitive C consumes via `build_plan`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/runtime/__init__.py` — `compile_workflow` re-export
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/registry/__init__.py` — `Registry()` constructor

**Tests (create or extend):**
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_core/test_cache_analysis_per_id_emission.py` — NEW
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_core/test_cache_analysis_cross_workflow.py` — extend
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_core/test_cache_analysis_summarize.py` — extend (G-tweak)
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_core/test_cache_analysis_renderers.py` — UPDATE (CRIT-8)
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_mcp_server/test_analyze_cache_tool.py` — UPDATE (CRIT-8)
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_execution/test_plan_drift.py:2088` — extend with `entry.cache_key` parity assertion (sub-segment C drift defense)

**Spec + plan source-of-truth:**
- `/Users/andfal/projects/pflow-feat-prompt-caching/.taskmaster/tasks/task_159/task-159.md` (mode-1: lines 332-472; mode-4: lines 485-493; warning JSON: lines 580-606)
- `/Users/andfal/projects/pflow-feat-prompt-caching/.taskmaster/tasks/task_159/implementation/implementation-plan.md` (F1 catalog rows; F2 composition)
- `/Users/andfal/projects/pflow-feat-prompt-caching/.taskmaster/tasks/task_159/implementation/implementation-progress-log.md` (Segments 1-4 + cost wiring follow-up)
