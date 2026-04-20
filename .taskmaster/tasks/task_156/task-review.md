# Task 156 Review: `--dry-run` flag with cache plan + cost/duration estimates

## Metadata

- **Implementation window**: 2026-04-18 → 2026-04-20
- **Branch**: `feat/add-dry-run-flag` (7 commits ahead of `main`)
- **GitHub issue**: [#310](https://github.com/spinje/pflow/issues/310)
- **Related artifacts**:
  - Spec: `.taskmaster/tasks/task_156/task-156.md`
  - Plan: `.taskmaster/tasks/task_156/implementation/implementation-plan.md` (2759 L)
  - Progress log (design journey): `.taskmaster/tasks/task_156/implementation/progress-log.md` (1965 L)
- **Follow-ups filed**: GH #318 (batch-of-sub-workflow cost aggregation)
- **PR**: not yet opened
- **Scope**: ~11.5k added, ~1.1k removed, 43 files

## Executive Summary

`pflow <workflow> --dry-run` (and MCP `plan_workflow`) produce a typed `Plan` describing what would happen at runtime — which nodes serve from cache, which would execute, historical LLM cost + duration estimates, sub-workflow recursion — without invoking any node side effects. Built around a shared `plan_node()` primitive that both the execution engine and the planner call, so the two cannot drift on cache-key computation, template resolution, or cache semantics. A drift-catcher test suite empirically enforces that promise on every build.

## What Was Built

**Core surface**:
- `pflow <workflow> --dry-run [--output-format json] [--only <node>] [--no-cache]` — CLI entry point
- `WorkflowRunner.plan(workflow, params, config) -> Plan` — programmatic entry point
- MCP `plan_workflow(workflow, parameters) -> dict[str, Any]` — agent-facing tool (returns dict, not str — only such tool in the suite, intentional)

**Data model** (`execution/result.py`):
- `Plan`, `PlanEntry`, `PlanSummary` frozen dataclasses
- `PlanEntry.status`: `Literal["cached", "execute", "sub_workflow", "opaque", "routing_error"]`
- `PlanEntry.cause`: `Literal["hash_match", "no_cache_match", "downstream", "cache_disabled", "template_error", "dynamic", "routing_error"]`
- Cost + duration fields: `last_cost_usd`, `last_duration_ms`, `last_run_age_sec`
- Summary with per-level AND `_including_nested` variants for nested aggregation

**Deviations from spec** (all intentional, user-driven during polish):
- Spec text-output required `No side effects performed.` final line → **dropped** (user: redundant given `--dry-run` flag is the contract)
- Spec text header was `Plan for <workflow>` → changed to `Dry-run for <basename>` (JSON `plan.workflow` keeps full absolute path as stable agent contract)
- Added `cost_basis: Literal["upper_bound", "exact"]` to summary (not in original spec; added during BFS review for agent cost-gating honesty)
- Added `estimated_duration_ms` and `nodes_without_duration_history` dimensions (entire duration axis added post-initial-impl; user requested "how long" alongside "how much")
- Added `execute_by_type_including_nested` (nested type rollup for multi-level plans)
- Sub-workflows reached via BFS post-first-miss now RECURSE (produce nested `sub_plan`) instead of rendering as flat leaf entries — spec was silent; this is the #1 iteration-UX scenario

**Bundled prerequisites** (discovered during planning):
- `LLMNode.post()` now calls `enrich_llm_usage_with_cost(llm_usage)` before writing to shared — pre-existing bug: engine step 15 ran AFTER step 12 (memo write), so memo entries had no `cost_usd`. Fix required for historical-cost lookups to work at all.
- `MemoizationCache` schema: new index `idx_node_id_created_at`, new methods `get_with_age` and `get_latest_for_node(node_id, *, workflow_path=None)` with SQL NULL guard.
- `_synthesize_inline_workflow_id(ir)` → `ir-hash:<md5>` in `WorkflowRunner._prepare_workflow` (inline dict/content-string/MCP-inline runs previously wrote NULL `workflow_path`, pooling cache history across unrelated workflows).

## Implementation Approach

**Option E: shared `plan_node()` primitive** — chosen after unanimous 4-agent poll over Options A (engine mode flag), A-refined (flag + static post-pass), B (separate walker), C (collector object), D (separate module). Consensus reasoning: any approach where "two code paths must stay in sync on cache-hit semantics" is the top failure pattern for this feature class; making them call the same function eliminates drift by construction. The engine's `_execute_node` has a natural seam at `node._run()` — steps 1-7 "decide what would happen," step 9 "do it." Factor steps 4-7 into `plan_node()`. Engine + planner consume the returned `NodePlan` differently.

**Three implementation iterations** (visible in commit history):
1. `fc4b530b implementation completed` — initial if-elif walker with 4 `# noqa: C901` suppressions
2. `df5f1856 refactor(plan): rewrite planner as explicit state machine` — `Transition` enum + `_classify` pure mapping + `_advance` match-dispatch. Third-pass shape.
3. Ongoing polish: duration axis, BFS sub-workflow recursion, summary type aggregation

**The state-machine shape is load-bearing**:
```python
class Transition(Enum):
    FOLLOW          # advance to successor on action
    STOP            # clean termination
    BOUNDARY        # first would-execute node → BFS downstream, then stop
    ROUTING_ERROR   # cached action has no matching successor

def _classify(entry: PlanEntry, curr) -> Decision  # pure mapping
def _advance(decision, *, state: _WalkerState) -> Any | None  # match dispatch
```

`build_plan`'s main loop does three things per iteration: plan one node, classify, dispatch. Extending the planner means: add a `PlanEntry.status` Literal → add an entry builder (`_template_error_entry` / `_cache_disabled_entry` / `_cached_memo_entry` / `_cached_in_process_entry` / `_miss_entry` pattern) → add a `_classify` case → add a `match` arm in `_advance`. **In that order.**

## Files Modified/Created

### Production (16 files, ~3k LOC added)

**New**:
- `src/pflow/runtime/engine/plan_node.py` (131 L) — `plan_node()` + `NodePlan` frozen dataclass. Owns config hashing, non-batch template resolution, memo + in-process cache lookup. Does NOT mutate shared, NOT call `enforce_loop_guard`, NOT emit progress/trace.
- `src/pflow/execution/plan.py` (1570 L) — `build_plan()` state-machine walker, sub-workflow recursion, BFS post-boundary, historical stats lookup, summary aggregation. The big file.
- `src/pflow/execution/formatters/plan_formatter.py` (331 L) — JSON-as-SSOT rendering; text derives from it; boundary divider idiom; 1s threshold for per-entry duration text; recursive "nothing cached" check.
- `src/pflow/core/duration_format.py` (53 L) — rich-format breakpoints (`450ms`, `2.3s`, `3m12s`, `1h5m`). Intentionally distinct from `output_controller.py`'s compact inline format.

**Modified (high-impact)**:
- `src/pflow/runtime/engine/instrumentation.py` (+148) — split `check_memo_cache` and `check_cache_validity` into pure-lookup (`memo_cache_lookup`, `in_process_cache_lookup`) + apply-side-effect (`apply_memo_hit`) pairs. Thin wrappers preserved for 10 pre-existing test callers. `write_memo_cache(*, duration_ms=None)` injects `__pflow_stats__` reserved key. `apply_memo_hit` STRIPS `__pflow_stats__` on restore (asymmetric by design — cached vs fresh must be observably identical).
- `src/pflow/runtime/engine/engine.py` (+88) — `_execute_node` replaces inline steps 4-7 with single `plan_node()` call + status dispatch. Explicit `invalidate_cache` on hash mismatch post-refactor (pure `in_process_cache_lookup` no longer does this side effect).
- `src/pflow/runtime/cache.py` (+99) — `idx_node_id_created_at` index, `get_with_age(cache_key)`, `get_latest_for_node(node_id, *, workflow_path=None)`. NULL guard in scoped query falls back to unscoped (SQL `WHERE x = NULL` matches zero rows — required for pre-synthesis legacy rows).
- `src/pflow/execution/runner.py` (+80) — `WorkflowRunner.plan()`, `_synthesize_inline_workflow_id(ir)`. `_prepare_workflow` injects `_pflow_workflow_file` via `setdefault` against `resolved.file_path` or synthetic hash.
- `src/pflow/execution/result.py` (+84) — three new frozen dataclasses.
- `src/pflow/cli/commands/run.py` (+100) — `--dry-run` flag, `_validate_dry_run_flag_combination` (hard-error with `--validate-only`/`--report`), `_display_plan_result` with severity-based exit code.
- `src/pflow/mcp_server/services/execution_service.py` (+79) — `plan_workflow` service method with structured exception handling (`WorkflowValidationError` → `format_validation_failure`; `CompilationError`/`MarkdownParseError` → `format_diagnostic`). Matches `save_workflow` pattern.
- `src/pflow/mcp_server/tools/execution_tools.py` (+23) — `plan_workflow` MCP tool registration.
- `src/pflow/nodes/llm/llm.py` (+5) — `enrich_llm_usage_with_cost(llm_usage)` before `shared["llm_usage"] = ...`.

**Modified (low-impact)**:
- `src/pflow/execution/formatters/node_output_formatter.py` (+6) — `_`-prefix key filter at three iteration sites (text, output-values, runtime-paths) so `__pflow_stats__` doesn't leak into `-p/--print`, `--structure`, MCP node-run text.
- `src/pflow/core/trace_report.py` (+4) — same filter at report iteration site.
- `src/pflow/runtime/engine/__init__.py` (+3) — re-export `NodePlan`, `plan_node`.

**Docs updated**: 8 CLAUDE.md files (`runtime/`, `runtime/engine/`, `execution/`, `execution/formatters/`, `cli/`, `cli/commands/`, `mcp_server/`, `mcp_server/services/`, `mcp_server/tools/`).

### Tests (13 files, ~3.2k LOC added, ~115 new tests)

**Load-bearing**:
- `tests/test_execution/test_plan_drift.py` (1873 L, **30 tests**) — every test runs a workflow end-to-end via `WorkflowEngine` AND plans it via `build_plan`, asserts predictions match execution outcomes. If this suite fails, the plan-vs-runtime contract has broken — fix the divergence, do not weaken the test. Covers: fresh/cached/config-edit/conditional-branch/sub-workflow-partial-cache/batch/cache-false/BFS-enumeration/routing-error/nested-cost-rollup/cost-basis-propagation/visit-counts-pre-bump/BFS-downstream-stats/duration-rollup/batch-LLM-cost/workflow-path-scoping/sub-workflow-output-resolution/undeclared-outputs-fallback/NULL-guard/inline-relative-refs/cached-loop-visit-two-reexecutes/cache-disabled-historical-stats/BFS-recurses-into-sub-workflow/downstream-linear-exact-basis/placeholders-satisfy-required-inputs/nested-type-aggregation/downstream-cycle-detection/cached-end-clean-termination.

**Defense-in-depth**:
- `tests/test_execution/test_plan_classify.py` (209 L, 20 tests) — unit-pins `_classify` + `_represents_work` semantics independently of the empirical drift suite. Catches regressions that happen to pass drift (e.g. scenario doesn't exercise a status).

**Other new**:
- `tests/test_runtime/test_plan_node.py` (176 L, 7 tests) — primitive contract
- `tests/test_execution/test_plan.py` (317 L, 11 tests) — `build_plan` integration
- `tests/test_execution/formatters/test_plan_formatter.py` (216 L, 8 tests) — formatter rendering decisions
- `tests/test_cli/test_dry_run.py` (275 L, 12 tests) — CLI composition + zero-side-effects + no-network
- `tests/test_cli/test_dry_run_subprocess.py` (87 L, 1 test) — real subprocess JSON stderr silence (CliRunner can't reach this)
- `tests/test_mcp_server/test_plan_workflow.py` (100 L, 4 tests) — MCP/CLI JSON parity
- `tests/test_core/test_duration_format.py` (96 L, ~26 parametrized)

**Modified**:
- `tests/test_runtime/test_cache.py` (+101, 6 new) — `get_with_age`/`get_latest_for_node` + index probe
- `tests/test_runtime/test_instrumented_wrapper.py` (+20, 1) — regression guard for LLMNode cost-in-memo
- `tests/test_execution/test_runner.py` (+82, 5 new) — `_synthesize_inline_workflow_id` determinism/distinctness/setdefault
- `tests/test_nodes/test_llm/test_llm.py` (+1) — expected-dict update for `cost_usd`

## Integration Points & Dependencies

### Incoming (consumers of the new code)

- `WorkflowEngine._execute_node` → `plan_node()` (engine step 4-7 replaced)
- `execution/plan.py::build_plan` → `plan_node()` + `apply_memo_hit` + `enforce_loop_guard` + `MemoizationCache.get_latest_for_node` + `resolve_sub_workflow` + `compile_workflow` + `resolve_output_source`
- `WorkflowRunner.plan` → `build_plan()` + `format_plan_*` (via callers)
- `cli/commands/run.py::_display_plan_result` → `WorkflowRunner.plan` + `format_plan_text/json`
- `mcp_server/services/execution_service.py::plan_workflow` → `WorkflowRunner.plan` + `format_plan_json`
- Tests consume the new primitives directly (drift-catcher, classifier, cache tests)

### Outgoing (what the new code depends on)

- `plan_node()` depends on: `compute_config_hash`, `compute_node_config` (instrumentation), `resolve_templates` (template_resolution), `memo_cache_lookup` + `in_process_cache_lookup` (instrumentation)
- `build_plan()` depends on: `plan_node`, `apply_memo_hit`, `enforce_loop_guard`, `invalidate_cache`, `MemoizationCache.{get_latest_for_node, get_with_age}`, `resolve_sub_workflow` (core/workflow/), `compile_workflow` (runtime/compilation/), `resolve_output_source` (runtime/output_resolver/), `_synthesize_inline_workflow_id` (indirectly via runner's shared)
- `format_plan_text/json` depends on: `Diagnostic.to_dict` + `format_diagnostic` (core/diagnostic_render), `format_duration` (core/duration_format), `_NODE_TYPE_TAGS` (local)

### Shared Store Keys

**NEW reserved dunder key** — engine-owned, node-authors must NOT write:
- `__pflow_stats__`: dict injected by `write_memo_cache` into the cached output blob. Currently `{"duration_ms": float}`, extendable (memory, tokens). `_make_serializable` in `cache.py` collapses dunder-keyed values to type name for deterministic cache-key hashing, so stats deltas never invalidate cache identity. Single-underscore naming (`_pflow_stats`) would feed stats INTO the hash — silent cache-breakage.
- `apply_memo_hit` STRIPS this key on restore to `shared[node_id]`. Asymmetric by design: fresh execution would never produce it, so restoring it would make cached vs fresh paths observably differ (template resolution, equality, trace output).
- Display sites MUST filter `_`-prefix keys when iterating output dicts (4 sites patched).

**NEW semantics on existing key**:
- `_pflow_workflow_file` can now be `"ir-hash:<md5hex>"` for inline runs (dict IR, content-string, MCP-inline). Previously only file paths or absent. Agents parsing this key MUST tolerate the `ir-hash:` prefix. `_synthesize_inline_workflow_id` is the sole write site for the synthetic form.

**Planner-owned scratch `shared`**:
- `build_plan` constructs its own `__execution__` sub-dict with `completed_nodes`/`node_actions`/`node_hashes`/`node_visit_counts`. The walker MUTATES these (`apply_memo_hit` on cache hit, `enforce_loop_guard` pre-bump). Required for byte-identical cache keys at downstream nodes — without it, downstream template resolution sees empty state and computes different keys than the engine would.

## Architectural Decisions & Tradeoffs

### D1. Option E (shared primitive) over A/A-refined/B/C/D
**Reasoning**: Unanimous 4-agent poll with convergent rationale — "two code paths that must stay in sync" is the #1 failure pattern for this feature class; shared function eliminates drift by construction. Mode-flag approaches (A/A-refined) grow new conditionals as edge cases accrue. Parallel-walker (B/D) must reimplement graph traversal, edge semantics, batch logic, sub-workflow handling, cycle detection — every piece is a drift surface.
**Alternative considered**: Option A (engine mode flag) looked smallest on diff but wrong on final-code simplicity.
**Cost**: Required splitting `check_memo_cache` / `check_cache_validity` into pure + apply halves (~50 LOC refactor, 10 pre-existing tests preserved via thin wrappers).

### D2. State machine over if-elif walker
**Reasoning**: Second 4-agent poll ranked state-machine (Transition enum + `_classify` + match) over fine-grained helpers over inline branches. Metric: "AI-agent cold-read comprehension" — how many jumps to understand one decision. Enum + match expose the state space in ~40 LOC of `build_plan` + `_advance`.
**Alternative considered**: Fine-grained helpers (51 top-level symbols, McCabe-optimized) — optimized for the wrong metric.
**Cost**: ~40 LOC more than inline branches, but zero `# noqa: C901` and a single place where `status → Transition` is expressed.

### D3. Parameterized sub-workflow recursion (not two functions)
**Reasoning**: `_plan_sub_workflow(..., cause="no_cache_match" | "downstream")` has one recursion point with `if downstream:` branches for the 5% that varies (skip `plan_node`, skip output population). Two separate functions re-introduce drift between pre-boundary and post-boundary paths.
**Load-bearing**: If a future reviewer "simplifies" by splitting, the drift class returns.

### D4. `_execute_entry` chokepoint for all `status="execute"` entries
**Reasoning**: First-miss (`_miss_entry`) AND BFS-downstream (`_make_downstream_entry`) both flow through `_execute_entry(config, cache, *, cause, diagnostic=None)`. Historical stats lookup happens in ONE place. Before this, the downstream path built bare `PlanEntry` without stats — agents cost-gating on downstream LLM nodes saw `$0` even when history existed.
**Load-bearing**: Any new code path producing execute entries MUST route through `_execute_entry`. Direct `PlanEntry(status="execute", ...)` construction re-introduces the bug.

### D5. `__pflow_stats__` dunder name over single-underscore
**Reasoning**: `_make_serializable` collapses dunder-keyed values to type name for deterministic cache-key hashing. Single-underscore keys feed INTO the hash — every duration delta would invalidate caching silently.
**Discovery**: Found via verification agent, not through testing. Would have been a silent correctness bug in production.

### D6. Historical cost over token-based prediction
**Reasoning**: `cost_usd` lives in `llm_usage` of every memoized LLM entry (after the LLMNode.post() fix). `get_latest_for_node(node_id)` retrieves it. No new dependencies (`tiktoken`, per-model encoders). Output tokens would still be guessed. `≈` + "historical, actual may vary" hedges fidelity appropriately for cost-gating.
**Cost**: First run of any LLM node shows `≈ $? (no history)` — accepted tradeoff for the iteration loop (second run onward has data).

### D7. Duration stored inside output blob, not as SQL column
**Reasoning**: Cost already lives inside the output blob (`llm_usage.cost_usd`). Zero schema migration. Reader + writer live in the same conceptual location. Dunder-naming hides it from cache hash.
**Alternative considered**: `duration_ms REAL` column — rejected for schema churn and because existing cache rows would have NULL (TTL eviction takes 24h to clean up mismatched rows anyway).

### D8. BFS over non-error successors post-first-miss (upper bound)
**Reasoning**: Linear default-following gives a lower-bound cost (one path). Cost-gate DANGER — underestimates. BFS enumerates all reachable branches → upper-bound cost → cost-gate SAFE (agent aborts a maybe-cheap run, never burns tokens on a maybe-expensive run). When semantics aren't definitive, prefer failure-mode = "user annoyance" over "user bill."
**Contract**: `summary.cost_basis` exposes "upper_bound" vs "exact" so agents can interpret the number.

### D9. `cost_basis` honors branching, not mode
**Reasoning**: Linear downstream graphs ARE exactly what will run — historical cost IS the exact cost (only the hedge is historical). Only branching flips to upper_bound. Hardcoding either side produces misleading output for the OTHER scenario. Parent aggregates via one-way latch: any child `upper_bound` → parent `upper_bound`.

### D10. `workflow_path` scoping with NULL guard
**Reasoning**: Two workflows with overlapping node IDs (`classify`, `summarize`, `fetch`) silently polluted each other's cost/duration history. Scope by workflow_path. But SQL `WHERE x = NULL` matches zero rows — direct-IR / content-string runs would silently break. Guard against None → fall back to unscoped.
**Test-critical**: `test_plan_direct_ir_null_workflow_path_historical_stats` pins the guard; mutation-verified.

### D11. `_synthesize_inline_workflow_id(ir)` for inline-run scoping
**Reasoning**: Inline runs (dict, content-string, MCP-inline) previously wrote NULL `workflow_path`. NULL-guard fallback to unscoped means two inline workflows sharing node IDs pooled history. Primary `--dry-run` use case is MCP agents iterating on inline markdown — exactly the pollution case.
**Implementation**: `hashlib.md5(canonical_json, usedforsecurity=False).hexdigest()` → `"ir-hash:<hex>"`. Injected via `setdefault` so pre-injecting callers (legacy) survive.
**Format contract**: `ir-hash:` prefix is stable — agents may parse.

### D12. Structured MCP exceptions (not flattened RuntimeError)
**Reasoning**: Agents reading MCP responses need structured diagnostics (titles, paths, `suggestion` fields, similar-names). Flattening to `RuntimeError(str(e))` loses the rich fields. Match `save_workflow`'s pattern: catch `WorkflowValidationError` → `format_validation_failure`; catch `CompilationError`/`MarkdownParseError` → `format_diagnostic` per diagnostic.

### D13. CLI flag composition: hard-error vs silent-accept
**Reasoning**: Different audiences + different exit contracts = hard error (`--dry-run` + `--validate-only`). Nothing to report from a non-execution = hard error (`--dry-run` + `--report`/`--report-dir`). Silent accept for no-ops that preserve script composability (`--no-trace` has nothing to skip; `-p` can't suppress a plan whose entire purpose IS the output).

### D14. Severity-based exit code
**Reasoning**: Mirror `_display_validation_result`'s convention. Any ERROR-severity diagnostic in the plan (e.g. strict-mode unresolvable template) exits 1. WARNING-only plans (routing errors, sub-workflow opaque) exit 0.

### D15. Exception-for-control-flow in `_ChildCompileFailed`
**Reasoning**: Replaces `CompiledWorkflow | PlanEntry` sum type with `isinstance` plumbing. Scoped to one module, single raise site, single catch site. Would be anti-pattern at larger scope — here it's legitimate.

## Technical Debt Incurred

### TD1. `--no-cache` also suppresses historical stats (deferred)

`--no-cache` sets `MemoizationCache(read_enabled=False)`. All reads short-circuit to None — including `get_latest_for_node` for historical stats. A user flipping `--no-cache` to force a fresh run loses cost visibility on that run. Current behavior is technically spec-compliant (spec: "skip all memo-cache lookups") but arguably wrong UX.

**Preferred fix** (documented but deferred — no user signal yet): add `stats_read_enabled: bool = True` to `MemoizationCache.__init__`. `get_latest_for_node` / `get_with_age` consult `stats_read_enabled` instead of `read_enabled`. Planner never sets `stats_read_enabled=False`. ~10 LOC.

**Re-open criteria** documented in `progress-log.md`.

### TD2. Batch-of-sub-workflow cost aggregation (GH #318)

Batch LLM node with per-item sub-workflow refs. Outer WorkflowExecutor isn't memoized (`node_type_name == "WorkflowExecutor"` skip at `instrumentation.py:196-197`). Child's individual LLM nodes ARE memoized (scoped to child's `workflow_path`) but invisible to the parent planner's `get_latest_for_node(batch_id)` lookup. Agents running batch-of-sub-workflow see cost under-report.

**Fix**: requires per-item sub-workflow recursion at plan time — a new planner capability. Two candidate approaches documented in GH #318 (~200 LOC representative-item, ~450 LOC full per-item). Implementing agent should discuss before committing.

## Testing Implementation

### Test Strategy

Three layers of coverage, each catching a different failure class:

1. **Primitive contract** (`test_plan_node.py`, `test_plan_classify.py`) — unit-pins `plan_node()` return shape and `Transition` state-machine mapping.
2. **Integration** (`test_plan.py`, `test_plan_formatter.py`) — `build_plan` + formatter on synthetic IRs.
3. **Parity** (`test_plan_drift.py`) — runs workflow through engine AND planner, asserts plan prediction matches engine outcome. This is the load-bearing invariant.
4. **End-to-end** (`test_dry_run.py`, `test_dry_run_subprocess.py`, `test_plan_workflow.py`) — CLI + MCP surface including no-network, subprocess stderr silence, JSON shape parity.

**Quality bar**: mutation-verified. For every high-value regression guard, the production code the test protects was temporarily mutated to confirm the test fails. At least 8 tests explicitly proven:
- `test_plan_bfs_downstream_attaches_historical_stats` — mutation removes `_execute_entry` dispatch for `_make_downstream_entry` → fails
- `test_plan_duration_nested_rollup` — mutation removes nested duration merge → fails
- `test_plan_walker_bumps_visit_counts_before_plan_node` — mutation removes visit-count bump → fails
- `test_plan_cost_nested_rollup` — mutation disables `_lookup_last_cost` in `_miss_entry` → fails
- `test_plan_cost_basis_propagates_upper_bound` — mutation removes upper-bound latch → fails
- `test_plan_batch_llm_cost_aggregates_across_results` — mutation disables `_extract_batch_cost_from_results` → fails
- `test_plan_workflow_path_scoped_lookup_no_pollution` — mutation removes workflow_path scoping → fails
- `test_plan_sub_workflow_downstream_templates_resolve` — mutation disables `_populate_sub_workflow_outputs` → fails
- `test_plan_sub_workflow_undeclared_outputs_fallback` — mutation removes `_mirror_child_shared` → fails
- `test_plan_direct_ir_null_workflow_path_historical_stats` — mutation removes NULL guard → fails
- `test_inline_dict_run_scopes_cache_to_ir_hash` + `test_plan_no_cross_pollution_*` — mutation disables synthesis → fails

**Manual regression**: 32-scenario adversarial CLI pass (2026-04-20) caught contracts automated tests don't reach: real exit codes, stderr silence, canary-file proof of zero side effects, cross-workflow pollution at OS level, TEST-NET-1 HTTP non-calls. Documented in progress log.

### Critical Tests (don't weaken these)

- `tests/test_execution/test_plan_drift.py` — 30 cases; if a case fails, engine and planner have diverged. Fix the divergence, don't adjust the test.
- `tests/test_execution/test_plan_classify.py` — 20 cases; pins the `Transition` + `_represents_work` mapping independently.
- `tests/test_runtime/test_instrumented_wrapper.py::test_llmnode_post_enriches_cost_before_memo_write` — regression guard for the LLMNode cost bug.
- `tests/test_execution/test_runner.py::test_inline_dict_run_scopes_cache_to_ir_hash` — protects the inline-scoping synthesis site.
- `tests/test_cli/test_dry_run_subprocess.py::test_dry_run_json_mode_emits_no_stderr` — real subprocess; CliRunner can't reach this contract.

## Unexpected Discoveries

### Integration-time discoveries that shaped the implementation

1. **LLMNode cost bug** — pre-existing: engine's step 15 `enrich_llm_cost` runs AFTER step 12 `write_memo_cache`, so memoized `llm_usage` never had `cost_usd`. Fix: call `enrich_llm_usage_with_cost` inside `LLMNode.post()` before the shared write. Idempotent (short-circuits on existing `cost_usd`).

2. **`_make_serializable` dunder collapse** — cache.py's hashing path collapses dunder-keyed values to type name. Initially we considered `_pflow_stats` (single underscore). Verification agent caught that stats would feed into cache hash → silent invalidation. Renamed to `__pflow_stats__` (dunder).

3. **SQL NULL semantics** — verification before L3 fix: `WHERE workflow_path = NULL` matches zero rows in SQL (NULL doesn't equal NULL without `IS NULL`). Scoping without a NULL guard silently breaks direct-IR / content-string runs.

4. **BFS-downstream stats gap** — found while wiring a test, not by review: `_make_downstream_entry` built bare `PlanEntry` without historical stats. Downstream LLM cost showed $0 even when history existed. Fix: chokepoint primitive `_execute_entry`.

5. **Sub-workflow BFS-leaf collapse** — parent with upstream edit → BFS reaches sub-workflow → flat leaf with no `sub_plan` → nested LLM cost hidden. Biggest agent iteration-UX bug. Fix: BFS now dispatches `WorkflowExecutor` → `_plan_sub_workflow(cause="downstream")` → nested plan with `_force_downstream=True`.

6. **NamespacedSharedStore populates shared[sub_wf_id] implicitly** — an agent's research claim contradicted this ("runtime doesn't populate this"). Empirical test via actual run proved runtime DOES populate it via `NamespacedSharedStore.__init__` + `_expose_child_outputs`. Lesson: verify empirically when agent claims conflict with observed behavior.

7. **Undeclared-output fallback** — runtime has a branch at `workflow_executor.py:472-478`: when child has no `## Outputs`, copies non-internal, non-input keys. Initial L1 fix only handled declared case. Undeclared case completes the symmetry (`_mirror_child_shared`).

8. **Placeholder inputs must be non-empty per type** — `""` fails the child's emptiness validator; `0` fails `minimum: 1`. Empirical: `compile_workflow` rejects missing required inputs. `_TYPE_PLACEHOLDERS` tuned for existing validators.

9. **Batch output blob structure** — LLM cost in batch mode lives in `results[i].llm_usage.cost_usd`, not at top level `llm_usage.cost_usd`. `_extract_batch_cost_from_results` sums across `results[]` when top level is absent. `results` is "successes only" — failures live in `errors[]`, cache write skipped on raise.

10. **Engine invalidate_cache on hash mismatch** — pre-refactor `check_cache_validity` did this side effect inline. Post-refactor pure `in_process_cache_lookup` doesn't. Engine MUST explicitly call `invalidate_cache` on hash mismatch for a previously-completed node — without it, stale entries leak on error paths.

### Edge cases the test suite encodes

- Cached node with `action="end"` → STOP regardless of successors (engine's `_handle_no_successor` clean termination)
- Cached node with only `error` successors + non-error action → STOP (all-error-successors clean termination)
- Cached node with `action="error"` + error successor → FOLLOW (on-error handler path)
- Retry loops with `on-error: self` → real cyclic successor edges → `visited_edges: set[(node_id, action)]` (NOT visited-by-node-only)
- Loop iteration 2+ of cached node → `enforce_loop_guard` invalidates completed_nodes → re-executes (matches engine, NOT "cached_in_process")
- Inline workflow with relative sub-workflow ref (`./child.pflow.md`) → `Path("ir-hash:...").parent == Path(".")` → resolves from CWD (matches runtime)

## Patterns Established

### P1. Shared Primitive Over Parallel Code

When two code paths must stay in sync on the same decision, extract the decision into a named primitive they both call. Drift is impossible by construction. Name it grep-discoverable. Document the invariant at both call sites.

Applied: `plan_node()` for cache-hit semantics. Could also apply to: validation phases (when we have several), compile-time vs runtime template resolution (already partially shared).

### P2. State Machine + Discriminated Union for Multi-Status Dispatch

Graph walkers with multi-status dispatch become unreadable as if-elif chains grow. Use `Enum + match + pure _classify` instead:

```python
class Transition(Enum):
    FOLLOW; STOP; BOUNDARY; ROUTING_ERROR

@dataclass(frozen=True)
class Decision:
    kind: Transition
    action: str = "default"

def _classify(entry, curr) -> Decision:  # pure
    ...

def _advance(decision, *, state) -> Next | None:
    match decision.kind:
        case Transition.STOP: ...
        case Transition.FOLLOW: ...
```

Adding a status = add Literal + entry builder + classify case + match arm. Compile-time exhaustiveness via mypy. Unit tests pin the mapping.

### P3. Chokepoint Primitive for Structured Outputs

When multiple code paths produce the same structured output, funnel them through a single primitive that guarantees the invariant. `_execute_entry` for `PlanEntry(status="execute")` is the canonical example — historical stats attachment was divergent across paths before the primitive.

Signal to apply: any structured output where some callers are missing a field the others populate.

### P4. Reserved Dunder Keys for Engine Metadata

Engine-injected output metadata uses double-underscore (`__pflow_stats__`). `cache.py::_make_serializable` collapses dunders for deterministic cache-key hashing. Single-underscore would feed into the hash and silently break caching.

Applied for duration today; extendable to memory/tokens without schema change. Readers must be absent-tolerant (pre-migration entries lack the key). Writers that restore to live shared MUST strip (asymmetric). Display sites MUST filter `_`-prefix keys.

### P5. Scratch-Owned Mutation is Legitimate

The contract "function does not mutate shared state" applies to caller-owned state, NOT scratch state the function constructs internally. `build_plan`'s scratch `shared` dict is planner-owned — mutating `apply_memo_hit` on cache hits is REQUIRED for byte-identical cache keys at downstream nodes.

Document the distinction in a module docstring. Future reviewers will otherwise "simplify" the mutation away and cause silent drift.

### P6. Parameterize Over Duplicate

When two code paths share ~95% of logic with one branching decision, parameterize via an enum or Literal. `_plan_sub_workflow(..., cause="no_cache_match" | "downstream")` over two separate functions. Splitting re-introduces drift.

### P7. Mutation Verification for Regression Guards

Writing a test that passes against current code is easy. Proving it would catch a regression requires mutating the production code and confirming failure. For every high-value test, do this explicitly. Document which mutation the test catches.

### P8. IR-Hash Synthesis for Inline-Run Scoping

When a system scopes data by file path but accepts inline input, NULL paths silently pool. Synthesize a stable identifier from IR content hash: `f"ir-hash:{md5(canonical_json).hexdigest()}"`. Use `hashlib.md5(..., usedforsecurity=False)` (modern idiom, not `noqa: S324`). Inject via `setdefault` for caller back-compat.

Applicable anywhere: dict IRs, content strings, MCP-inline submissions.

### Anti-patterns to avoid

- **Don't add `dry_run: bool` mode flags to hot-path engines** — the method call IS the mode (`runner.plan()` vs `runner.run()`).
- **Don't "clean up" `apply_memo_hit` in the planner** — it's load-bearing for downstream cache-key parity.
- **Don't collapse thin wrappers** (`check_memo_cache`, `check_cache_validity`) — they preserve pre-existing test callers without mechanical updates.
- **Don't widen existing fields to cover new dimensions** — `nodes_without_history` means "LLM with no cost data"; widening to "any node with no data" changes user-visible semantics. Add `nodes_without_duration_history` as parallel instead.
- **Don't remove `workflow_path is not None` guard** — SQL NULL silently breaks scoping.
- **Don't build `PlanEntry(status="execute", ...)` directly** — use `_execute_entry` chokepoint.
- **Don't call `enforce_loop_guard` inside `plan_node`** — the walker owns loop-guard invocation; `plan_node` must be side-effect-free on caller's state.

## Breaking Changes

### API

None. `WorkflowRunner.run`, `.validate`, CLI public flags unchanged. `WorkflowRunner.plan()` is new. CLI `--dry-run` is new. MCP `plan_workflow` is new.

Internal refactors (affecting test callers only):
- `check_memo_cache` signature unchanged, internals delegate to new primitives.
- `check_cache_validity` signature unchanged, internals delegate to new primitives.
- `write_memo_cache` gained optional `duration_ms=None` kwarg.
- `MemoizationCache.get_latest_for_node` now takes optional `*, workflow_path=None`.

### Behavioral

- **LLMNode.post()**: `shared["llm_usage"]` now includes `cost_usd`. Was absent before (engine enrichment ran later). One pre-existing test updated (`test_usage_data_stored_correctly`).
- **Memo cache entries**: now include `__pflow_stats__.duration_ms` in the stored output blob. Old entries without the key are tolerated (absent-tolerant readers).
- **Inline runs**: `shared["_pflow_workflow_file"]` now populated with `"ir-hash:<md5>"` (was absent → NULL in cache). Affects: `get_latest_for_node` scoping (now works correctly), sub-workflow base-path resolution (CWD-relative, unchanged behavior).
- **`apply_memo_hit`**: strips `__pflow_stats__` from restored output. Live shared state never sees the key (consistent with fresh-execution behavior).
- **Engine `_execute_node`**: steps 4-7 replaced by `plan_node()` call. Semantics byte-identical (drift-catcher enforces).
- **Display sites** (node_output_formatter, trace_report): filter `_`-prefix keys when iterating output. Previously showed all keys. No reserved keys existed before this change, so no user-visible output changed retroactively — just prevents `__pflow_stats__` leak.

## Future Considerations

### Extension Points

- **Task 133** (Unified Per-Node Storage for Trace and Cache) reuses `__pflow_stats__` convention. Extend the dict with additional engine metadata.
- **Task 125** (Human-in-the-Loop Approval Gates) can consume `Plan` output as approval primitive — agent presents plan + cost, user confirms, agent runs.
- **Task 46** (Workflow Export to Zero-Dependency Code) must preserve `plan_node()` semantics in exported form or document the gap.
- **Task 152** (MCP Server CLI Surface Parity) — `plan_workflow` MCP tool already landed as part of this task; no parity gap.

### Scalability Concerns

- **Historical cost drift**: LLM providers change pricing. Cache entries with `cost_usd` computed at write time become stale. `enrich_llm_usage_with_cost` reads `llm_pricing.py` at write time. A workflow cached under old prices shows old cost on dry-run. Acceptable for v1 — agents care about order-of-magnitude for gating.
- **`__pflow_stats__` extensibility**: adding memory/tokens to the dict is fine but changes the output-blob structure — old cache entries lack new fields. Readers must be absent-tolerant (already the pattern).
- **`get_latest_for_node` TTL**: 24h. A workflow untouched for 25h shows `≈ $? (no history)`. Fine for iteration loop, potentially surprising for long-lived infrequent workflows.
- **Dry-run JSON size**: full-precision floats, nested sub_plans, diagnostics — grows roughly linearly with node count + sub-workflow depth. No pagination today; not expected to matter until workflows grow 100x.

## AI Agent Guidance

### Quick Start for Related Tasks

**Read first (in order)**:
1. `src/pflow/execution/plan.py` — top-of-file docstring with the 4 load-bearing invariants
2. `src/pflow/execution/CLAUDE.md` — "Dry-Run Planner" section
3. `src/pflow/runtime/engine/CLAUDE.md` — "plan_node.py" + "Engine-injected output metadata `__pflow_stats__`"
4. `tests/test_execution/test_plan_drift.py` — the parity contract in action
5. This file

**For changes to cache-hit semantics**: edit `plan_node()` ONLY. Both engine and planner inherit via single call site.

**For new `PlanEntry.status`**: Literal (result.py) → entry builder (plan.py `_plan_standard_node`) → `_classify` case → `_advance` match arm → test_plan_classify.py case → possibly drift-catcher case. In that order.

**For new summary field**: `PlanSummary` field → `_summarize` + `_compute_totals` → `_summary_to_dict` → formatter text rendering → test coverage.

**For new sub-workflow behavior**: modify `_plan_sub_workflow` parameterized by `cause`, NOT by adding a second function. Respect the opaque pre-check (runs BEFORE plan_node to handle `workflow: ${var}`).

**For new historical stats**: add to the `__pflow_stats__` dict (not a new top-level key). Keep dunder naming. Make readers absent-tolerant. Strip in `apply_memo_hit`. Filter at display sites.

### Common Pitfalls

1. **Adding `if dry_run:` branches to the engine** — breaks Option E. Extract the decision into `plan_node()` or a sibling primitive instead.
2. **"Cleaning up" planner-owned shared mutation** — `apply_memo_hit` on cache hit is load-bearing. Scratch `shared` is planner-owned.
3. **Single-underscore for injected metadata** — feeds into cache hash via `_make_serializable`. Use double-underscore.
4. **Removing `workflow_path is not None` guard** — SQL NULL silently breaks scoping.
5. **Mocking `plan_node` or `build_plan` in tests** — drift-catcher needs real execution.
6. **Direct `PlanEntry(status="execute", ...)` construction** — misses historical stats. Use `_execute_entry`.
7. **Collapsing thin wrappers** (`check_memo_cache`, `check_cache_validity`) — preserves pre-existing test callers.
8. **Assuming `_pflow_workflow_file` is always a file path** — can now be `"ir-hash:<md5>"`. Agents parsing it must handle both.
9. **Testing through CliRunner for agent-UX contracts** — CliRunner masks stderr routing, `logger.*` interleaving, real exit codes. Use subprocess tests for those.
10. **Widening existing summary fields** — `nodes_without_history` = LLM cost. Don't retask for duration. Add a parallel field.

### Test-First Recommendations

When modifying:
- `plan_node()` → run full `test_plan_drift.py`; any failure means engine and planner have diverged, fix the primitive.
- `_classify` → run `test_plan_classify.py` + `test_plan_drift.py`. Drift-catcher's empirical coverage may miss a branch; classifier unit tests pin it.
- `_execute_entry` → mutation-verify via `test_plan_bfs_downstream_attaches_historical_stats`.
- `_plan_sub_workflow` → mutation-verify via `test_plan_bfs_recurses_into_sub_workflow_carrying_child_stats` + `test_plan_sub_workflow_undeclared_outputs_fallback`.
- `_synthesize_inline_workflow_id` → run `test_inline_dict_run_scopes_cache_to_ir_hash` + `test_plan_no_cross_pollution_between_distinct_inline_workflows`.
- `MemoizationCache.get_latest_for_node` NULL guard → `test_plan_direct_ir_null_workflow_path_historical_stats`.
- `apply_memo_hit` strip logic → add a test that puts `__pflow_stats__` in a cache entry, triggers a hit, asserts the key is NOT in live shared.
- Any change to display-site filtering → verify `__pflow_stats__` doesn't leak into `-p/--print`, `--structure`, `--report`, MCP node-run text.

When adding a new node-type tag: update `_NODE_TYPE_TAGS` in `plan_formatter.py`. Keep class-name as stable contract in JSON; translate only in text rendering.

---

*Generated from implementation context of Task 156.*
