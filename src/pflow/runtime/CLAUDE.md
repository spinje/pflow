# Runtime Module

Compilation and execution infrastructure. Compiles workflow IR into `CompiledWorkflow` (bare nodes + per-node configs), then executes via `WorkflowEngine`.

## File Structure

```
src/pflow/runtime/
├── __init__.py              # Exports: compile_workflow(), WorkflowEngine, CompiledWorkflow, etc.
├── compilation/             # IR→CompiledWorkflow compiler (see compilation/CLAUDE.md)
├── engine/                  # Orchestration engine (see engine/CLAUDE.md)
├── node_state.py            # Canonical node state queries + failure bookkeeping
├── cache.py                 # Persistent memoization cache (SQLite, cross-run)
├── template_resolver.py     # Template variable detection and resolution
├── template_validation/     # Template validation package (see template_validation/CLAUDE.md)
├── workflow_executor.py     # Nested workflow executor node (with compile-once cache)
├── workflow_trace.py        # Trace collection with thread-safe LLM interception
└── output_resolver.py       # Output declaration resolver
```

## Compilation Pipeline

See `compilation/CLAUDE.md` for details. Quick summary:

`compile_workflow()` → parse IR → resolve file refs → validate → instantiate bare nodes + `NodeConfig` → wire edges → `CompiledWorkflow`.

**CompilationError** (in `core/exceptions.py`): fields `phase`, `node_id`, `node_type`, `details`, `suggestion`.

## Execution Engine

See `engine/CLAUDE.md` for full architecture. Quick summary:

`WorkflowEngine(metrics, trace, only_node).run(workflow, shared)` → walks graph, handles template resolution, namespacing, batch, caching, tracing, progress per node.

### Node Execution State Invariant

```python
shared[node_id]            # node executed successfully
shared["__failures__"][id] # node executed and failed
# neither key present       # node did not execute
```

Never both. To query state, use `pflow.runtime.node_state`:

- `get_node_status(shared, node_id) -> NodeStatus` (`ABSENT`/`SUCCEEDED`/`FAILED`)
- `get_node_output(shared, node_id) -> Optional[dict]` — succeeded OR failed data
- `get_node_failure(shared, node_id) -> Optional[dict]` — failure record only
- `node_succeeded(shared, node_id) -> bool`
- `mark_node_failed(shared, node_id, *, category, error=None, warning=None)` — **single write site**
- `clear_node_failure(shared, node_id)` — wired into loop re-entry only

All 5 engine failure paths funnel through `mark_node_failed`: `cache_result` (action="error" → handled in engine.py step 17.5), `handle_api_warning`, `_handle_no_successor`, exception path, defensive paths. Direct writes to `__failures__`/`failed_node`/`__warnings__[id]` are contract violations — they drift from the canonical record shape.

`__failures__` entries persist for the workflow lifetime; cleared only on loop re-entry and memo cache hits. Long-running loops with heavy retry accumulate entries until the loop commits.

## Template System

### TemplateResolver (`template_resolver.py`)

**Regex**: `r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"`

**Path support**: `${data.user.name}`, `${items[0].title}`, `${data[5].users[2]}`

**Escape syntax**: `$${var}` prevents resolution via regex negative lookbehind. Partially implemented: prevents resolution but does NOT strip the extra `$` (output contains literal `$${var}`).

**Nested index templates**: `${results[${item.index}].response}` — inner resolved first. One level of nesting supported.

**JSON auto-parsing**: Path traversal auto-parses JSON strings. Only dict/list results used — numeric strings like Discord snowflake IDs preserved as strings.

**Type behavior**:
- Simple templates (`${var}`): preserve original type
- Complex templates (`"Hello ${name}"`): always string
- Inline objects (`{"key": "${dict_var}"}`): preserve inner types
- Unresolved: remain as-is for debugging

**Resolution context**: `dict(shared)` — shared store is the single source of runtime data. No `initial_params` override.

> For JSON auto-parsing and type coercion details, see `architecture/core-concepts/data-type-coercion.md`.

### Template Validation (`template_validation/`)

Pre-execution validation. See `template_validation/CLAUDE.md`.

## Planner (Dry-Run)

Dry-run planning is split across two files:

- `runtime/engine/plan_node.py` — shared per-node decision primitive (`plan_node(node, config, shared) -> NodePlan`)
- `execution/plan.py` — graph walker that builds typed `Plan` results via an explicit `Transition` state machine

**Load-bearing invariant**: `plan_node()` is the single authoritative source for cache-hit semantics. Both the engine and the planner call it. Changes to cache-key computation, template resolution, or cache-enable rules MUST live in `plan_node()`, not in `engine._execute_node()` or `execution/plan.py`.

**Walker shape** (`execution/plan.py`): transitions are a discriminated union — `Transition.FOLLOW` / `STOP` / `BOUNDARY` / `ROUTING_ERROR`. `_classify(entry, curr) -> Decision` is the one authoritative mapping from `PlanEntry.status` to transition; `_advance(...)` is a `match` dispatch that acts on the decision. Extending the planner with a new status means: add a `PlanEntry.status` literal, add an entry builder in `_plan_standard_node`, add a `_classify` case, add the `match` arm in `_advance`. In that order. See `execution/CLAUDE.md` → "Dry-Run Planner" for the full walker documentation.

**Sub-workflow recursion is parameterized, not duplicated**: `_plan_sub_workflow(..., cause="no_cache_match" | "downstream")` is the single recursion point. Pre-boundary walker dispatches `WorkflowExecutor` via `_plan_one_node` with default `cause`; post-boundary BFS (`_make_downstream_entry`) dispatches with `cause="downstream"`, which threads `_force_downstream=True` into `_build_plan_with_shared` so the child uses `_bfs_from_start` over its entire graph. Both produce a nested `sub_plan` so `estimated_cost_usd_including_nested` rolls up correctly regardless of which path reached the sub-workflow.

Parity is enforced by `tests/test_execution/test_plan_drift.py`. State-machine transitions are unit-tested in `tests/test_execution/test_plan_classify.py`. If either test fails, fix the divergence instead of weakening the test.

## Other Components

### WorkflowExecutor (`workflow_executor.py`)

Runtime node for nested workflow execution. Child outputs auto-expose via namespace.

- **`workflow` param**: file path or saved workflow name. The only sub-workflow reference mechanism.
- **`inputs` param**: dict of values passed to the child's declared `## Inputs`. Every key must be declared; extras rejected at parse time (Step 7 + sub-workflow validator, both directions) and at runtime (`_validate_child_params`).
- **Closed schema via `ALLOWED_PARAMS`** (`ClassVar[frozenset[str]]`): `workflow`, `inputs`, `error_action`, `storage_mode`, `max_depth`. Validator Step 7 reads this attribute to reject unknown top-level fields — forward-compatible shape for the planned schema-declaration refactor (see task list).
- **Auto-outputs**: child's `## Outputs` exposed via namespace. No declarations → all non-internal keys exposed.
- **Storage modes**: `mapped` (default, isolated) and `shared` (parent storage directly).
- **Compile-once cache**: `_compiled_workflow_cache` (dict keyed by resolved workflow path) + `_loaded_ir_cache` (dict keyed by raw workflow ref) — compiles once per unique child, reuses for sequential batch items. Heterogeneous batches (`${item.workflow}` varies per item) correctly cache each child independently.
- **Circular detection** via `_pflow_stack`, **max depth** via `_pflow_depth` (default 10).
- **Relative paths** resolve from parent workflow directory via `_pflow_workflow_file`.
- **Cross-cutting key propagation**: `_PROPAGATED_KEYS` — `__registry__`, `__progress_callback__`, `__mcp_pool__`, `__warnings__`, `_trace_collector`. Per-workflow keys (`__execution__`, `__cache_hits__`, `__template_errors__`, `__failures__`) NOT propagated — child gets its own. Adding `__failures__` here would leak child node IDs into parent state.
- **`error_action` covers BOTH prep and exec failures** (GH #284). Prep-time failures (missing required inputs, undeclared extras, non-dict `inputs:`, missing file, circular ref, max depth) are captured into a `_prep_error` marker in `prep_res` so `exec()`/`post()` dispatch them uniformly through `error_action`. The recoverable exception set is `_PREP_RECOVERABLE` — `CompilationError` is explicitly excluded (broken workflow definitions are not routable). One caveat: if the failure text matches `api_warning_detector` patterns (e.g. "not found"), the engine's API warning layer overrides the action back to `"error"` regardless of `error_action` — pre-existing engine behavior, applies to all node types. Tracked as GH #301.

### MemoizationCache (`cache.py`)

Persistent cross-run caching. SQLite at `~/.pflow/cache/cache.db`, WAL journal, zlib-compressed BLOBs.

- **Cache key**: `md5(config_hash + resolved_inputs)`. Batch nodes add semantic config + resolved items.
- **TTL**: 24h. **`read_enabled=False`**: writes still happen, reads return None (`--no-cache`).
- **Side-effecting nodes ARE cached** — intentional for iteration loop. `--no-cache` escape hatch.
- **Test isolation**: `conftest.py::isolate_pflow_config` monkey-patches to temp paths.
- **Integration**: Created by Runner, stored as `shared["__memoization_cache__"]`, consumed by `engine/instrumentation.py`.
- **Workflow scoping**: `workflow_path` column scopes `get_latest_for_node` lookups so unrelated workflows with overlapping node IDs don't pool cost/duration history. File/library runs use the resolved absolute path; inline runs (dict IR, content-string markdown, MCP-inline) use a synthetic `ir-hash:<md5>` identifier injected by `runner._prepare_workflow`. Never write NULL `workflow_path` from new code paths — `WHERE workflow_path = NULL` matches zero rows in SQL and the scoped lookup silently falls back to unscoped, pooling history across distinct submissions. `get_latest_for_node` guards against NULL input with an unscoped fallback, which is load-bearing for pre-synthesis legacy rows.

### WorkflowTraceCollector (`workflow_trace.py`)

- **Format 2.0.0**: Tree-structured events with `node_output`, `template_resolutions`, `node_params`, `batch_items`, `sub_workflow_events`
- **Thread-safe LLM interception**: Reference counting + per-thread collector lookup. Child collectors skip interception.
- **Batch item tracing**: via `_batch_trace` shared-store accumulator (GIL-safe for parallel)
- **Sub-workflow tracing**: Child collectors created by `WorkflowExecutor`, events embedded as `sub_workflow_events`
- **Per-node aggregation rule — "last event per `node_id` = final state"**: Status determination and the `failed_node_ids` list (written to the trace file by `save_to_file`) both derive from `_final_events_by_node()`. Loop recovery records two events for the same node_id; only the later one counts for workflow-level aggregation. See GH #240.
- **`nodes_executed` vs `nodes_failed` semantics**: `nodes_executed = len(self.events)` counts **per-visit** (total invocations). `nodes_failed = len(failed_node_ids)` counts **per-node** (unique failed nodes). Under loop recovery the two diverge: 2 visits, 0 failed nodes → `nodes_executed=2, nodes_failed=0`. `failed_node_ids` is sorted alphabetically for deterministic JSON output.
- **`mark_last_event_failed(node_id, *, error)`**: mutation API used by the engine's `_handle_no_successor` in the non-error-action branch. Flips the most recent event for `node_id` to `success=False` so the trace and `__failures__` agree for routing failures on custom actions. See GH #250.

### Output Resolver (`output_resolver.py`)

`populate_declared_outputs()` maps namespaced outputs to root level. Raises `OutputResolutionError` when a source can't be resolved.

**Coalesce semantics — easy to regress**: `_is_all_absent_coalesce` distinguishes legitimate branch-convergence fallthrough from real errors. A coalesce silently skips ONLY when every operand has `status == "absent"`. Any FAILED or PATH_ERROR operand forces an error — that's the "primary failed via on-error → recovery handler" case the system has to surface, not swallow.

## Reserved Shared Store Keys (Canonical Reference)

```python
# Execution tracking (managed by engine/instrumentation.py)
shared["__execution__"] = {
    "completed_nodes": [],     # Successfully executed nodes
    "node_actions": {},        # Actions returned by each node
    "node_hashes": {},         # MD5 config hashes for cache validation
    "failed_node": None,       # Node that caused workflow failure
    "node_visit_counts": {},   # Per-node visit counter (loop guard)
    "only_node": None,         # --only target node ID (set by engine)
}

# Failure archive (managed by runtime/node_state.py::mark_node_failed)
shared["__failures__"] = {
    "node_id": {
        "data": {...},        # what was at shared[node_id] before the move (may be {})
        "category": "shell_failure" | "node_action_error" | "api_warning" | "routing_error" | "exception" | "template_error",
        "error": "...",       # human-readable error (optional)
        "warning": "...",     # set for api_warning and on-error recovery (optional)
    }
}

# System keys
shared["_trace_collector"] = WorkflowTraceCollector
shared["__progress_callback__"] = func
shared["__warnings__"] = {}               # Node warnings → DEGRADED status
shared["__cache_hits__"] = []             # Nodes served from cache
shared["__template_errors__"] = {}        # Permissive mode errors
shared["__mcp_pool__"] = MCPConnectionPool
shared["__memoization_cache__"] = MemoizationCache
shared["__index__"] = int                 # 0-based batch item index

# Nested workflow keys
shared["_pflow_depth"] = int
shared["_pflow_stack"] = list[str]
shared["_pflow_workflow_file"] = str
```

## Critical Behaviors

### Cache Invalidation (Two Levels)

**In-process cache** (within a single `engine.run()`): Node in `completed_nodes` AND config hash matches → skip re-execution. Invalidated on parameter change (hash mismatch) or revisited nodes (loops).

**Memoization cache** (cross-run, SQLite-backed): `cache_key = hash(config + resolved_inputs)` → hit returns cached output without executing. Invalidated when: config changes (edited node params, different template text), resolved inputs change (upstream produced different output, CLI override changed), or TTL expires (24h default). **Skipped for revisited nodes** (`visit_count > 1`) — memoization is for cross-run caching, not loop caching. **Skipped for workflow nodes** — sub-workflow files may change between runs; inner nodes are individually cached via the propagated `__memoization_cache__`. Error results are never cached. **Cost aggregation** (`collect_llm_calls()`, `_collect_llm_summary()`) excludes cached events — only nodes that actually executed contribute to the run's reported cost.

### Error Categorization (API Warning Detection)

**Validation errors** (parameter format issues, 73 patterns checked):
- `validation_error` — bad request, invalid parameter, schema error
- `template_error` — unresolved variables (triggers ValueError)

**Resource errors** (external state, 20 patterns):
- `resource_error` — not found, forbidden
- API warnings: Slack `"ok": false`, Discord errors, GraphQL `"errors": []`
- HTTP status codes: 401, 403, 404, 429

**Ambiguity rule**: When an error matches BOTH validation and resource patterns, it's treated as **validation** (validation wins).

## Gotchas

- **Batch nodes skip top-level template resolution** — engine guards on `not config.batch_config`
- **Fresh Registry instance** — always pass a new one to `compile_workflow()` per execution
- **`__` prefixed params are reserved** — never use for user parameters
- **Don't modify `__execution__` structure** — checkpoint integrity is critical for resume
- **`_source_line` keys NOT filtered in split_params** — `python_code.py` reads them
- **Compile-once cache is keyed by resolved workflow path** (`_compiled_workflow_cache`). Heterogeneous batches with `${item.workflow}` varying per item correctly cache each child separately.
- **Two validation files** — `compilation/ir_preparation.py` (compiler-time) vs `core/workflow/validator.py` (pre-execution). Don't confuse them.
