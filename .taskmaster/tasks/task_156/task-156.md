# Task 156: Add `--dry-run` flag with cache plan and cost estimates

## Description

Add `--dry-run` to `pflow run` that builds a static execution plan — which nodes would serve from cache, which would actually execute, with historical cost estimates for LLM nodes — without invoking any side effects. Factored around a new shared `plan_node()` primitive that both the execution engine and the dry-run planner call, so the two paths cannot drift on cache-key computation, template resolution, or cache semantics. Resolves GitHub issue #310.

## Status

done

## Completed

2026-04-20

## Priority

medium

## Problem

During iteration on a multi-node workflow, agents and humans need to answer "what will happen if I run this now?" before spending time, tokens, or dollars. Today the only way to find out is to actually run the workflow:

- The 30-second, $0.10-per-iteration lyrics pipeline in issue #310 is the motivating example — a full run is required just to see whether the LLM-heavy step at the end is cache-hit or cache-miss.
- Existing flags are the wrong tool: `--no-cache` forces a full run (opposite of what's wanted); `--only <node>` runs one node but still executes it; `--validate-only` says nothing about what would happen at runtime.
- Runtime progress output (`↻ cached`, `✓ executed`) is emitted *during* execution, after side effects have already fired.
- Agents iterating on workflows have no pre-flight check: they can't cost-gate before running, can't diff "what changed" between two workflow edits, and can't reason about which of their edits invalidated the cache.

`pflow` already internally computes everything needed — cache keys, template resolution, memoization lookup — but exposes none of it without triggering `node._run()`.

## Solution

Add `--dry-run` as a sibling to `--validate-only`, `--only`, `--no-cache`, `--report`. Output is a narrative plan in text mode and a structured document in JSON mode. Exits 0 on a successful plan, non-zero only on unresolvable planning-time failures (missing required input, compile error, unresolvable `${...}`).

**Implementation shape — Option E: a shared `plan_node()` primitive.** The engine's per-node sequence has a natural seam: steps 4-7 (config hash, template resolution, cache lookup) are pure; step 9 (`node._run()`) is the only side effect. Extract the pure portion into `plan_node(node, config, shared) -> NodePlan`. Execution engine: call `plan_node()`, then run the node if not cached. Dry-run planner: call `plan_node()`, record an entry, stop at first cache miss for that branch. Cache-key computation and template resolution live in **exactly one function** shared by both paths — drift is impossible by construction.

**Cost estimates**: for every would-execute LLM-family node, look up the most recent memo-cache entry for that `node_id` (ignoring current cache key) and surface its stored `cost_usd` as a historical estimate. Aggregate at the summary. Label with `≈` and "based on last runs, actual may vary". Fixes a bug as prerequisite: `LLMNode.post()` currently doesn't enrich `llm_usage` with `cost_usd` before the cache write, so today's memo entries have no cost data (`ClaudeNode` already does this correctly).

**Sub-workflow recursion**: when the planner hits a `WorkflowExecutor` node, it resolves the child, compiles it with the shared registry, and recursively calls `build_plan` with the shared `MemoizationCache`. The child's plan nests under the parent entry. Planner-owned cycle/depth tracking mirrors the runtime's protection.

**Text output** uses a boundary-divider idiom: one marker line at the first cache miss, no per-line "downstream of X" repetition. Cached nodes show age; would-execute LLM nodes show `≈ $cost`. One summary line aggregates counts and total estimated cost.

**JSON output** pre-computes agent-ready fields in `summary`: `cache_boundary` (single pointer for "what changed?"), `execute_by_type` (count of LLM vs HTTP vs code, for cost reasoning), `estimated_cost_usd`. Per-entry `cause` is a short stable enum (`no_cache_match`, `downstream`, `cache_disabled`, `template_error`).

## Design Decisions

1. **Option E (shared `plan_node` primitive) over Option A (engine mode flag), A-refined (flag + static post-pass), and D (separate planner).** Poll of 4 independent agents was unanimous on E. A: "one conditional in the hot path" grows into many as edge cases emerge — mode flags in execution code leak. D: parallel code paths that "must stay in sync" on cache-key / template / edge semantics is the #1 failure pattern for this kind of feature. E gives future agents one home for the shared logic, named and grep-discoverable, with drift eliminated structurally.

2. **Extract only the pure portion of steps 4-7, not all of 1-7.** Steps 1-3 (LLM interception, execution state init, loop guard) have side effects the planner doesn't want. The shared primitive covers config hash, template resolution, memo-cache lookup, and in-process cache lookup — the "decide what would happen to this node" computation.

3. **Split `check_memo_cache` and `check_cache_validity` into pure-lookup + side-effect-apply pairs; keep thin wrappers.** Verification found the on-hit side effects in `check_memo_cache` are a contiguous 4-line block, cleanly extractable. Thin wrappers preserve the 9 existing tests in `test_checkpoint_tracking.py` without mechanical rewrites — only 1 test needs a real update.

4. **Historical cost estimates, not tokenization.** "Last-seen cost" via `MemoizationCache.get_latest_for_node(node_id)` reuses data we already have and adds no dependencies. Tokenization-based prediction would add `tiktoken`-class libraries, per-model encoders, and still be wrong for output tokens. Historical cost with a clear `≈` hedge is the right fidelity for cost-gate decisions.

5. **Cost fix bundled into the same task.** `LLMNode.post()` not calling `enrich_llm_usage_with_cost` is a pre-existing bug that also blocks this feature. It affects every memo-cached LLM entry today (trace consumers read the live dict post-enrichment, so they see cost, but the cache doesn't). Splitting into a precursor PR has no real benefit — it's small (~5 lines), mechanically tested, and conceptually part of enabling the feature.

6. **Boundary-divider text format over per-line reasons.** Repeating "(downstream of 'X')" on 10-30 lines of a long workflow is noise. One divider line + node-type tags (`[LLM]`, `[code]`) on each node gives agents the signal without the boilerplate.

7. **`cause` enum as stable contract.** Agents will `jq .plan[].cause`. The initial enum (`no_cache_match`, `downstream`, `cache_disabled`, `template_error`) is the stable vocabulary. Future refinements (e.g. distinguishing "config changed" from "inputs changed") will extend, not rename.

8. **Graph walker uses `visited_edges: set[(node_id, action)]`, not `visited: set[node_id]`.** Verified: pflow's graph has real cyclic `successors` edges for retry loops (e.g. `flaky - "error" >> flaky`). A per-node visited set breaks legitimate loops. The per-edge set terminates after one traversal per distinct edge — correct for a plan.

9. **Post-first-miss: BFS over all non-`error` outgoing edges, label "downstream".** For would-execute nodes the action is unknown; following only `default` misses conditional branches (`success`/`failure` forks). BFS over named action edges, skipping `on-error` handlers, captures all reachable "would execute" nodes without double-counting.

10. **Sub-workflow recursion uses `resolve_sub_workflow` from `core/workflow/sub_workflow_resolver.py`, not the top-level `execution/workflow_resolver.py`.** That resolver handles file refs, saved names, and dynamic-template refs (returning `None` for `workflow: ${var}`, correctly marking them as opaque at plan time). Planner-level `visited_paths` and `depth` replace runtime's `_pflow_stack` / `_pflow_depth` — no shared-store dependency.

11. **Opaque sub-workflows when `workflow` ref is a template.** `resolve_sub_workflow` returns `None` for `workflow: ${item.child}`. Emit `▸ [sub-workflow: dynamic, cannot plan]` rather than guessing. Agents reading JSON see `status: "opaque"`.

12. **Drift-catcher test as living invariant.** A test runs a workflow via real engine and captures per-node outcomes (cached vs executed, action returned), then runs the same workflow via `--dry-run` and asserts the plan prediction matches. Prevents the Option-D-style drift failure mode from sneaking back in via future refactor.

13. **MCP server exposure bundled, not deferred.** `pflow-as-MCP-server` exposes `execute_workflow` and `validate_workflow`; adding `plan_workflow` is ~40 production lines + ~60 test lines (service method + tool registration + response shape match). Shipping a CLI-only dry-run in a codebase with strong MCP parity (Task 152 tracks parity) would be inconsistent with pflow's agent-first positioning. Deferring a tiny, naturally-composing extension is false economy — a follow-up issue would land within a week anyway.

14. **CLI flag composition rules.** `--dry-run` hard-errors with `--validate-only` (different audiences) and `--report`/`--report-dir` (nothing to report); silently accepts `--no-trace` (no trace to skip) and `-p/--print` (the plan *is* the result — suppressing it is nonsensical). Hard errors go to mistakes; silent accepts go to no-ops that preserve script composability.

## Dependencies

None. All prerequisites are internal changes bundled into this task:

- `LLMNode.post()` cost enrichment (pre-existing bug fix)
- `MemoizationCache` schema: `idx_node_id_created_at` index
- `MemoizationCache` API: `get_latest_for_node(node_id)`, extend `get()` to return `created_at` (or add parallel method)

Related but not blocking:
- Task 75 (Execution Preview in Validation) — originally scoped a narrower preview inside `--validate-only`. Issue #310 correctly argued for a distinct flag; task 75 can be deprecated or refocused on other preview dimensions (required credentials, data flow visualization).

## Requirements

### CLI surface
- `pflow run <workflow> --dry-run [params...]` MUST produce a plan without invoking any node's `_run()` method.
- `pflow run <workflow> --dry-run --output-format json` MUST emit a single JSON document to stdout, with no other stdout output.
- Text mode output MUST be readable to agents scanning stderr-like output (progress-style format).
- `--dry-run` MUST exit 0 when the plan builds successfully, regardless of cached/execute mix.
- `--dry-run` MUST exit 1 when the plan cannot be built (missing required input, compile error, unresolvable template at planner level).
- `--dry-run` MUST compose with `--only <node>`: plan up to and including `<node>`, stop.
- `--dry-run` MUST compose with `--no-cache`: cache reads disabled, every node shows as would-execute (no boundary line because nothing is cached).
- `--dry-run` MUST be mutually exclusive with `--validate-only` — passing both MUST hard-error with a clear "pick one" message (different audiences, different exit contracts).
- `--dry-run` MUST hard-error when combined with `--report` or `--report-dir` (message: "`--report` has nothing to report in `--dry-run` mode — remove one flag").
- `--dry-run` MUST silently accept `--no-trace` as a no-op (dry-run never saves traces; this keeps script composability clean).
- `--dry-run` MUST silently ignore `-p/--print` (the plan output *is* the result; `-p` suppressing it would make the command useless). Plan renders fully regardless.
- `--dry-run` MUST NOT save a trace file (no execution → no meaningful trace).
- `--dry-run` MUST NOT fire `--report` generation (no execution → no report).

### No side effects
- The planner MUST NOT invoke `node._run()` for any node.
- The planner MUST NOT spawn subprocesses (shell nodes).
- The planner MUST NOT open network connections (HTTP, LLM, MCP nodes).
- The planner MUST NOT write files (file nodes).
- The planner MUST NOT mutate the caller's shared store or other caller-owned state.

### Shared primitive — `plan_node()`
- MUST be located under `src/pflow/runtime/engine/` and be callable from both engine and planner.
- MUST return a typed `NodePlan` dataclass with an explicit status enum (not a tuple, not a string).
- MUST produce a cache key byte-identical to the one the engine produces at runtime for the same node and shared state (verified by drift-catcher test).
- MUST NOT call `check_memo_cache`'s side-effect block, `check_cache_validity`'s `invalidate_cache` call, or any progress/trace/metrics emitter.
- MUST NOT invoke `enforce_loop_guard` (has side effects on `visit_counts` and `__failures__`). When calling memo-cache helpers that accept `visit_counts`, pass `{}` or equivalent sentinel.

### Graph traversal
- MUST use `visited_edges: set[(node_id, action)]` for loop termination.
- MUST handle the `"end"` action as clean termination (matching engine semantics).
- MUST follow the cached action when a cache hit is known.
- After the first cache miss, MUST BFS over all non-`"error"` outgoing edges to enumerate reachable "would-execute" nodes.
- MUST NOT silently fall back from a missing named action to `default` (matches engine behavior — missing named action is a routing error).
- MUST surface routing errors as plan entries (not as exit-1 failures), with `cause: "routing_error"`.

### Cache semantics
- MUST respect `cache: false` per-node: such nodes always show as would-execute, `cause: "cache_disabled"`.
- MUST respect `--no-cache` at the CLI level: skip all memo-cache lookups, everything shows as would-execute.
- MUST NOT trigger in-process cache invalidation (side effect the planner must avoid).
- MUST skip memoization for `WorkflowExecutor` nodes, matching engine behavior.

### Sub-workflow recursion
- MUST recurse into `WorkflowExecutor` nodes whose `workflow` param resolves statically to a file or saved name.
- MUST mark as opaque (`status: "sub_workflow", cause: "dynamic"`) when `workflow` is a template that can't resolve at planner level.
- MUST propagate a single `MemoizationCache` instance through all recursion levels (matching runtime propagation).
- MUST propagate the same `Registry` instance through all recursion levels.
- MUST enforce a planner-level `max_depth` (default: 10, matching `WorkflowExecutor.MAX_DEPTH_DEFAULT`).
- MUST detect cycles via planner-level `visited_paths` (list of resolved child paths).
- MUST surface child `CompilationError` as a plan entry without aborting the parent plan (pass through `to_diagnostics()` structure).
- When any node inside a sub-workflow would execute, the parent `WorkflowExecutor` entry MUST be treated as a cache boundary, and nodes after it at the parent level MUST be labeled downstream.
- MUST surface parser warnings from child `resolve_sub_workflow` return in the plan's `diagnostics[]` array (matches runtime's `_propagate_child_parser_warnings` behavior).

### Cost estimates
- For every LLM-family node (class names: `LLMNode`, `ClaudeNode`) with status `execute`, the planner MUST look up `MemoizationCache.get_latest_for_node(node_id)`.
- When the latest entry has `llm_usage.cost_usd`, the planner MUST attach it to the PlanEntry as `last_cost_usd` and the age as `last_run_age_sec`.
- When no entry exists or `cost_usd` is missing, the planner MUST set `last_cost_usd: None` and render as `≈ $? (no history)`.
- Summary MUST expose `estimated_cost_usd` (sum of `last_cost_usd` over would-execute entries, None values treated as 0) and `nodes_without_history` (count of would-execute LLM nodes with no historical cost).
- Text mode MUST label cost estimates with `≈` and include "based on last runs, actual may vary" qualifier in the summary.
- Cost display precision: 2 decimal places when cost ≥ $0.01 (e.g., `$0.03`, `$15.47`); 4 decimal places when cost < $0.01 (e.g., `$0.0004`). Applies to both per-entry `last_cost_usd` rendering and summary `estimated_cost_usd`. JSON `last_cost_usd` and `estimated_cost_usd` fields are full-precision floats — formatting is text-mode only.

### Prerequisite bug fix — `LLMNode` cost
- `src/pflow/nodes/llm/llm.py::LLMNode.post()` MUST call `enrich_llm_usage_with_cost(llm_usage)` before writing `llm_usage` to the shared store, mirroring `ClaudeNode`'s existing behavior.
- After the fix, `MemoizationCache` entries for `LLMNode` executions MUST contain `cost_usd` in their stored `llm_usage`.
- Fix MUST NOT change live-run behavior for trace/metrics consumers (they already read post-enrichment).

### Cache extensions
- `MemoizationCache` MUST gain `CREATE INDEX IF NOT EXISTS idx_node_id_created_at ON cache_entries(node_id, created_at DESC)` in its schema initialization.
- `MemoizationCache` MUST gain `get_latest_for_node(node_id: str) -> Optional[tuple[dict, float]]` returning (output_dict, created_at_epoch_seconds) for the most recent entry matching node_id, or None.
- `MemoizationCache` MUST gain a parallel method `get_with_age(cache_key: str) -> Optional[tuple[str, dict, float]]` returning (action, output, created_at_epoch_seconds). `get()` signature is unchanged — existing callers are unaffected.

### Text output format
- Cached nodes render as `↻ {node_id}  ({age} ago)` where age is short-format (`10m`, `2h`, `3d`).
- Would-execute nodes render as `▸ {node_id}  [{type}]` with type drawn from `node_type_name` (`LLM`, `HTTP`, `code`, `shell`, `MCP`, etc.).
- Would-execute LLM nodes additionally render `≈ $X.XX (last run {age} ago)`.
- A single `─── cache boundary: '{node_id}' ───` divider appears at the first cache miss. No divider when everything is cached. Divider reads "nothing cached — full run" when nothing is cached.
- Sub-workflows render as `▸ {node_id}  [sub-workflow '{ref}']` with child entries indented 4 spaces; nested boundary dividers render at the appropriate indent level.
- Summary line: `Summary: N cached · M would execute (X LLM, Y code, ...)`.
- Cost line (when any cost data): `Estimated cost: ≈ $X.XX  (historical, actual may vary)`.
- Final line (always): `No side effects performed.`

### JSON output format
- Top-level shape: `{workflow, plan, summary, diagnostics}`.
- Each `plan[]` entry: `{node_id, node_type, status, cause, action?, age_sec?, last_cost_usd?, last_run_age_sec?, sub_plan?}`.
- `status` enum values: `"cached"`, `"execute"`, `"sub_workflow"`, `"opaque"`, `"routing_error"`.
- `cause` enum values: `"hash_match"`, `"no_cache_match"`, `"downstream"`, `"cache_disabled"`, `"template_error"`, `"dynamic"`, `"routing_error"`.
- `summary`: `{total, cached_count, execute_count, cache_boundary, execute_by_type, estimated_cost_usd, nodes_without_history, total_including_nested?, cached_including_nested?, execute_including_nested?}`.
- `cache_boundary` is the `node_id` of the first would-execute node (null when everything is cached).
- `execute_by_type` is `{node_type_name: count}` for would-execute entries only.
- `diagnostics[]` follows existing `Diagnostic.to_dict()` shape for any template/compile errors captured during planning.
- JSON mode MUST NOT emit any output on stderr (follow pflow's JSON silence convention).

### Drift-catcher test
- A test MUST execute a multi-node workflow end-to-end via `WorkflowEngine`, capturing per-node status (cached vs executed) and action returned.
- The same workflow (same shared store state) MUST be dry-run-planned.
- For every node the plan visited, the plan's prediction (`cached` with action X, or `execute`) MUST match what actually happened.
- The test MUST cover: fresh run (nothing cached), re-run (everything cached), partial cache after config edit, conditional branching with cached actions.

### MCP server exposure
- `pflow-as-MCP-server` MUST expose a `plan_workflow(workflow, params)` tool alongside the existing `execute_workflow` and `validate_workflow` tools.
- The MCP tool's JSON response shape MUST match the CLI's `--dry-run --output-format json` output exactly (same top-level keys, same plan entry shape, same summary fields).
- Service method MUST delegate to `WorkflowRunner.plan()` (the same entry point the CLI uses).
- Error handling MUST follow existing MCP tool conventions (wrap exceptions into structured error responses, no raw tracebacks to the agent).

### Documentation
- `src/pflow/runtime/engine/CLAUDE.md` MUST describe `plan_node()` as the shared primitive and update the step-numbered walkthrough.
- `src/pflow/runtime/CLAUDE.md` MUST reference `plan_node()` in the engine section.
- `src/pflow/execution/CLAUDE.md` MUST document `WorkflowRunner.plan()` alongside `.run()` and `.validate()`.
- `src/pflow/cli/CLAUDE.md` and `src/pflow/cli/commands/CLAUDE.md` MUST document the `--dry-run` flag in the run-command flag table.
- CLAUDE.md files MUST flag the drift-catcher test as the invariant enforcing plan/execution parity.

## Implementation Notes

Full file-level implementation details (exact signatures, line numbers, diffs, test updates) will live in `.taskmaster/tasks/task_156/implementation/implementation-plan.md` — to be drafted after this spec is approved.

Key integration points the implementation touches:

- **Split cache lookups** — `src/pflow/runtime/engine/instrumentation.py`: new pure `memo_cache_lookup()` and `in_process_cache_lookup()` functions; existing `check_memo_cache` / `check_cache_validity` become thin wrappers composing the pure lookup with the side-effect apply. This preserves 9 existing tests in `test_checkpoint_tracking.py` without mechanical updates.

- **New `plan_node()` primitive** — `src/pflow/runtime/engine/plan_node.py` (new file): calls `compute_config_hash`, `resolve_templates` (when applicable, skipping batch nodes per existing engine contract), and the pure cache lookups. Returns `NodePlan` dataclass. Handles `WorkflowExecutor` skip.

- **Engine integration** — `src/pflow/runtime/engine/engine.py::_execute_node`: replace steps 4-7 with a single call to `plan_node()`, dispatch on the returned `NodePlan.status`. Preserves all existing execution behavior.

- **Planner** — `src/pflow/execution/plan.py` (new file): `build_plan(compiled, params, cache, registry, ...) -> Plan`. Walks `compiled.start_node.successors` with `visited_edges` loop termination. Calls `plan_node()` per node. Post-first-miss: BFS over outgoing non-error edges, marking downstream. Dispatches `WorkflowExecutor` nodes to `_plan_sub_workflow()` using `resolve_sub_workflow` from `core/workflow/sub_workflow_resolver.py`. Tracks `visited_paths` + `depth` for cycle/depth protection.

- **Formatter** — `src/pflow/execution/formatters/plan_formatter.py` (new file): `format_plan_text(plan) -> str` and `format_plan_json(plan) -> dict`. Boundary-divider rendering, short age format, node-type tags, cost annotations.

- **Runner** — `src/pflow/execution/runner.py`: new `plan(workflow, params, config) -> Plan` method. Resolves, compiles, delegates to `build_plan`. Does NOT create trace/metrics collectors (no execution).

- **CLI** — `src/pflow/cli/commands/run.py`: `@click.option("--dry-run")`, mutual exclusion check against `--validate-only`, routing branch to `runner.plan()`, formatter invocation, exit-code mapping.

- **LLMNode cost fix** — `src/pflow/nodes/llm/llm.py::LLMNode.post()`: single call to `enrich_llm_usage_with_cost(llm_usage)` before the shared-store write. Consistent with `ClaudeNode`'s already-cost-aware behavior (ClaudeNode writes `cost_usd` directly from the SDK's `total_cost_usd`; `LLMNode` gets there via the pricing-table lookup).

- **Cache extensions** — `src/pflow/runtime/cache.py`: schema gains `idx_node_id_created_at` index. New methods: `get_latest_for_node(node_id) -> Optional[tuple[dict, float]]` (for cost lookup) and `get_with_age(cache_key) -> Optional[tuple[str, dict, float]]` (for cached-entry age rendering). `get()` signature unchanged.

- **MCP server exposure** — `src/pflow/mcp_server/services/execution_service.py`: new `plan_workflow(workflow, params) -> dict` method delegating to `WorkflowRunner.plan()` and returning the JSON shape. Tool registration in the MCP tool registry mirrors the `validate_workflow` and `execute_workflow` patterns.

- **Result types** — `src/pflow/execution/result.py`: new `Plan`, `PlanEntry`, `PlanSummary` dataclasses with documented field contracts. Status and cause fields typed as `Literal[...]`.

Files to modify (summary):

| File | Action |
|---|---|
| `src/pflow/runtime/engine/instrumentation.py` | Modify — split cache lookups, keep wrappers |
| `src/pflow/runtime/engine/engine.py` | Modify — call `plan_node()` from `_execute_node` |
| `src/pflow/runtime/engine/plan_node.py` | Create — shared primitive |
| `src/pflow/runtime/cache.py` | Modify — index, `get_latest_for_node`, age support |
| `src/pflow/nodes/llm/llm.py` | Modify — cost enrichment in `post()` |
| `src/pflow/execution/plan.py` | Create — planner walker |
| `src/pflow/execution/formatters/plan_formatter.py` | Create — text + JSON rendering |
| `src/pflow/execution/runner.py` | Modify — add `plan()` method |
| `src/pflow/execution/result.py` | Modify — `Plan`, `PlanEntry`, `PlanSummary` |
| `src/pflow/cli/commands/run.py` | Modify — `--dry-run` flag + routing + mutual-exclusion checks |
| `src/pflow/mcp_server/services/execution_service.py` | Modify — add `plan_workflow` service method |
| `src/pflow/mcp_server/` (tool registration site) | Modify — expose `plan_workflow` as an MCP tool |
| `src/pflow/runtime/engine/CLAUDE.md` | Update |
| `src/pflow/runtime/CLAUDE.md` | Update |
| `src/pflow/execution/CLAUDE.md` | Update |
| `src/pflow/cli/CLAUDE.md` | Update |
| `src/pflow/cli/commands/CLAUDE.md` | Update |
| `tests/test_runtime/test_plan_node.py` | Create |
| `tests/test_execution/test_plan.py` | Create |
| `tests/test_execution/test_plan_drift.py` | Create — drift-catcher |
| `tests/test_execution/formatters/test_plan_formatter.py` | Create |
| `tests/test_cli/test_dry_run.py` | Create |
| `tests/test_runtime/test_memoization_integration.py` | Update — 1 signature update |
| `tests/test_runtime/test_instrumented_wrapper.py` | Update — LLMNode cost write-site test |
| `tests/test_mcp_server/test_plan_workflow.py` | Create — MCP `plan_workflow` tool tests |

Pre-verification already completed (see conversation history for full findings):
- Template/cache helpers are safe to reuse from outside the engine with a scratch `shared` dict.
- `cost_usd` is NOT in memo cache for `LLMNode` today (write-ordering issue). Fix is to call `enrich_llm_usage_with_cost` at the node level.
- `resolve_sub_workflow` (not `resolve_workflow`) is the right resolver for planner recursion.
- Graph walker must use `visited_edges: set[(node_id, action)]`; loops are real cyclic edges.
- Cache-lookup split is clean: no mock patches, 9 tests affected, thin wrappers preserve ~all of them.
- Blast radius of the refactor is narrow: `engine.py` is the only production caller of the affected helpers.

## Verification

### Automated

- `make test` passes including new test files.
- `make check` clean (lint + type).
- **Drift-catcher test** (`tests/test_execution/test_plan_drift.py`): runs multi-node workflow twice (fresh + re-run + partial-invalidation), asserts plan prediction matches actual execution outcome for every node the plan visited.
- **Plan walker tests**: `visited_edges` loop termination, `"end"` action handling, BFS over branches post-first-miss, routing error rendering.
- **Sub-workflow recursion tests**: static ref, template ref (opaque), cycle detection, max-depth, child compile error surfaced without aborting parent plan.
- **Cost lookup tests**: LLM node with history → estimate attached, LLM node without history → `None`, non-LLM nodes → no lookup attempted, summary aggregation correct.
- **LLMNode cost bug fix test**: after a live run, `MemoizationCache` entry contains `cost_usd` in `llm_usage`.
- **CLI integration tests**: `--dry-run` exits 0 on success, 1 on missing input, composes with `--only`, `--no-cache`, `--no-trace`, `-p` (silent accept), refuses to compose with `--validate-only` and `--report`/`--report-dir` (hard error).
- **MCP tool tests**: `plan_workflow` returns a JSON response matching the CLI `--dry-run --output-format json` shape for representative workflows (linear, branching, sub-workflow, cache boundary, LLM cost estimate).
- **Output format tests**: text boundary-divider rendering, JSON schema compliance, agent-parseable `jq` queries work against sample output.

### Manual scenarios (all must be verified before merge)

1. **Happy path — all cached**: run a workflow twice (first real, second `--dry-run`). Second shows `↻ cached` on every node, no boundary, `Summary: N cached · 0 would execute`.

2. **Edit invalidates cache**: run once, edit a prompt, `--dry-run`. Shows cache hits up to the edited node, boundary at the edited node, "downstream" labels on everything after.

3. **Nothing cached**: `--dry-run --no-cache` or fresh install shows `─── nothing cached — full run ───` and all nodes as would-execute.

4. **Sub-workflow recursion**: parent with 2 nodes around a `workflow:` child with 3 nodes. Edit a prompt inside the child. `--dry-run` shows parent's pre-child as cached, child plan shows cached nodes + boundary + would-execute, parent's post-child as "downstream" of the child.

5. **Cost estimate**: LLM-heavy workflow run once (builds cache), edit upstream to invalidate, `--dry-run`. Shows `≈ $X` annotations on LLM nodes and accurate `Estimated cost` aggregate.

6. **No-history cost**: new LLM node added to workflow, `--dry-run`. Shows `≈ $? (no history)` on that node, `nodes_without_history: 1` in summary.

7. **Dynamic sub-workflow ref**: workflow with `workflow: ${item.ref}` in a batch. `--dry-run` shows that node as `[sub-workflow: dynamic, cannot plan]`.

8. **Opaque on `cache: false`**: node with `cache: false` in workflow. `--dry-run` shows it as would-execute with `cause: cache_disabled` regardless of upstream state.

9. **JSON mode**: `pflow run foo.pflow.md --dry-run --output-format json | jq .summary.cache_boundary` returns the expected node_id.

10. **Cost gate**: `pflow run foo.pflow.md --dry-run -f json | jq '.summary.estimated_cost_usd'` returns a number agents can compare against a threshold.

11. **Zero side effects**: `pflow run foo.pflow.md --dry-run` in a workflow with shell (`echo hello > /tmp/pflow_dryrun_canary`) produces no file at `/tmp/pflow_dryrun_canary`. LLM/HTTP/MCP network traffic verified absent via a pytest fixture that asserts the network mock sees zero outbound requests during `--dry-run` execution.

12. **Exit codes**: `--dry-run` with missing required input exits 1 with the same `Diagnostic` as `pflow run` would produce.

### Drift-guard greps

- `rg "check_memo_cache|check_cache_validity" src/` — only engine.py, instrumentation.py (wrapper definitions), and tests should match.
- `rg "plan_node" src/` — engine.py and plan_node.py are production callers; plan.py is the planner caller.
- `rg "node._run|_run\(" src/pflow/execution/plan.py` — zero matches (planner never invokes nodes).

## References

- **GitHub issue**: #310 — "Add --dry-run flag to pflow run that shows execution plan without invoking side effects"
- **Related superseded spec**: `.taskmaster/tasks/task_75/task-75.md` — "Execution Preview in Validation" (originally scoped a narrower preview inside `--validate-only`; deprecated by this task's narrower-surface approach).
- **Shared primitives being reused**:
  - `src/pflow/runtime/engine/template_resolution.py::resolve_templates` — pure, safe for scratch shared
  - `src/pflow/runtime/engine/instrumentation.py::compute_node_config`, `compute_config_hash` — pure
  - `src/pflow/runtime/cache.py::compute_node_cache_key`, `compute_batch_cache_key` — pure
  - `src/pflow/core/workflow/sub_workflow_resolver.py::resolve_sub_workflow` — handles file + saved + dynamic refs
  - `src/pflow/core/llm_pricing.py::enrich_llm_usage_with_cost` — used by the bug fix
  - `src/pflow/runtime/compilation/compiler.py::compile_workflow` — reused for sub-workflow compilation during planning
- **Test isolation pattern**: `tests/conftest.py::isolate_pflow_config` monkey-patches `MemoizationCache` DB path — dry-run tests must use the same fixture.
- **Design principle**: CLAUDE.md "Core Directive — Operational Precision" §5 "Integration readiness > feature completeness" — Option E was chosen because it composes cleanly with existing execution code rather than introducing a parallel system.
- **Prior tasks informing design**:
  - Task 106 (Workflow Iteration Cache) — established `MemoizationCache`, `__cache_hits__`, and the CLI flag patterns for `--only`, `--no-cache`.
  - Task 138 (Shared Execution Pipeline) — established `WorkflowRunner` as the unified entry point used here via `.plan()`.
  - Task 148 (Failed-node invariant) — informed the "don't break the `__failures__` contract" constraint; planner never writes failure records.
- **Follow-up artifact**: `.taskmaster/tasks/task_156/implementation/implementation-plan.md` — to be drafted after this spec is approved.
