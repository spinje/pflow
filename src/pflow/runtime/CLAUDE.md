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

**Regex**: `TEMPLATE_PATTERN = re.compile(rf"(?<!\$)\$\{{({_COALESCE_EXPR_PATTERN})\}}")` — the capture group is the composed coalesce sub-grammar (literal-or-var-path operands separated by `??`), not a bare variable path. Negative lookbehind `(?<!\$)` guards `$${var}` escapes.

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
- **Closed schema via `ALLOWED_PARAMS`** (`ClassVar[frozenset[str]]`): `workflow`, `inputs`, `error_action`, `max_depth`. Validator Step 8 reads this attribute to reject unknown top-level fields — forward-compatible shape for the planned schema-declaration refactor (see task list).
- **Auto-outputs**: child's `## Outputs` exposed via namespace. No declarations → all non-internal keys exposed.
- **Child storage is always isolated**: the child gets a fresh store and exposes its `## Outputs` back to the parent. There is no `storage_mode` param — a former `storage_mode: shared` aliased the child store to the parent and leaked child failures/depth into it (issues #254/#231), so the param was removed entirely. Any `storage_mode:` line is now an unknown param rejected by the validator's unknown-param step.
- **Compile-once cache**: `_compiled_workflow_cache` (dict keyed by resolved workflow path) + `_loaded_ir_cache` (dict keyed by raw workflow ref) — compiles once per unique child, reuses for sequential batch items. Heterogeneous batches (`${item.workflow}` varies per item) correctly cache each child independently.
- **Circular detection** via `_pflow_stack`, **max depth** via `_pflow_depth` (default 10).
- **Relative paths** resolve from parent workflow directory via `_pflow_workflow_file`.
- **Cross-cutting key propagation**: `_PROPAGATED_KEYS` — `__registry__`, `__progress_callback__`, `__mcp_pool__`, `__warnings__`, `__parser_diagnostics__`, `__memoization_cache__`, `__trace_collector__`, `__loop_active__` (issue #445: a looped sub-workflow body inherits the active loop depth so its inner nodes also suppress memo reads for the iteration; the planner mirrors this in `execution/plan.py::create_planner_shared`). Per-workflow keys (`__execution__`, `__cache_hits__`, `__template_errors__`, `__failures__`, `__pflow_prompt_cache__`) NOT propagated — child gets its own. Adding `__failures__` here would leak child node IDs into parent state.
- **`error_action` covers BOTH prep and exec failures** (GH #284). Prep-time failures (missing required inputs, undeclared extras, non-dict `inputs:`, missing file, circular ref, max depth) are captured into a `_prep_error` marker in `prep_res` so `exec()`/`post()` dispatch them uniformly through `error_action`. The recoverable exception set is `_PREP_RECOVERABLE` — `CompilationError` is explicitly excluded (broken workflow definitions are not routable). The api_warning detector now DEFERS to a node's deliberate verdict: it only runs on a clean-success action (`_CLEAN_SUCCESS_ACTIONS`), so an `error_action` route like `continue` is no longer overridden back to `"error"` even when the failure text matches a detector pattern (e.g. "not found"). GH #301 closed.

### MemoizationCache (`cache.py`)

Persistent cross-run caching. SQLite at `~/.pflow/cache/cache.db`, WAL journal, zlib-compressed BLOBs.

- **Cache key**: `md5(config_hash + resolved_inputs)`. Batch nodes add semantic config + resolved items.
- **TTL**: 24h. **`read_enabled=False`**: writes still happen, reads return None (`--no-cache`).
- **Per-node cache default is type-based** (`compiler._default_cache_for_node_type`): only `llm` nodes default to `cache_enabled=True`; every other node type (shell, code, http, file ops, mcp, claude-code) defaults to `cache_enabled=False` because they side-effect or read external state. Per-node `cache: true` opts a node back in. `--no-cache` (`read_enabled=False`) is the run-wide escape hatch.
- **Test isolation**: `conftest.py::isolate_pflow_config` monkey-patches to temp paths.
- **Integration**: Created by Runner, stored as `shared["__memoization_cache__"]`, consumed by `engine/instrumentation.py`.
- **Workflow scoping**: `workflow_path` column scopes `get_latest_for_node` lookups so unrelated workflows with overlapping node IDs don't pool cost/duration history. File/library runs use the resolved absolute path; inline runs (dict IR, content-string markdown, MCP-inline) use a synthetic `ir-hash:<md5>` identifier injected by `runner._prepare_workflow`. Never write NULL `workflow_path` from new code paths — `WHERE workflow_path = NULL` matches zero rows in SQL and the scoped lookup silently falls back to unscoped, pooling history across distinct submissions. `get_latest_for_node` guards against NULL input with an unscoped fallback, which is load-bearing for pre-synthesis legacy rows.

### WorkflowTraceCollector (`workflow_trace.py`)

- **Format 2.x shape**: Tree-structured events with `node_output`, `template_resolutions`, `node_params`, `batch_items`, `sub_workflow_events`. Top-level `workflow_path` (resolved file path or `ir-hash:<md5>` for inline runs — symmetric with `MemoizationCache.workflow_path` scoping). Per-event cache-correlation fields on LLM events: `cache_key` / `cache_source` (`"memo" | "in_process"`) / `cache_age_sec` / `cache_chunks_skipped` flowing through `event["llm_call"]` via the existing `llm_usage` channel. Per-event `llm_system` carrying the effective system content the LLM saw — `str` for plain system params, `list[dict]` for cache-rendered prefixes (with provider-specific `cache_control` markers). Sourced from `prep_res["system_blocks"]` when prep built one, else `prep_res["system"]`; captured via the adapter's `trace_hook` `before_call` event. Surfaced in `--report` per-node markdown as `## Cached System` (before `## Prompt` to match API call order; list shape emits a fenced JSON block so `cache_control` markers stay visible). Cache-metadata fields are gated by `_should_write_cache_metadata(node_type_name)` — currently allowlisted to `LLMNode` only; ClaudeCodeNode is INTENTIONALLY excluded (its cache tokens come from the SDK, a different cache layer). Consumer rule: gate on `format_version.startswith("2.")` — additive minor bumps are forward-compat. Batch parity: `LLMNode.post()` mirrors prompt + effective system into `shared["prompt"]` / `shared["system"]` so per-item batch traces capture them; `batch_executor._capture_item_trace` pair-copies `system → llm_system` (accepts `(str, list)`).
- Per-event `event["node_id"]` and `event["llm_call"]["model"]` are consumed by `prompt_cache_analysis.trace_loading` for trace autoload/listing and model-drift notes. The existing trace shape is sufficient; no producer-side fingerprint or format bump is required for those consumers.
- **2.4.0 `only_node` (issue #443)**: a top-level field — `None` for a full run, the `--only` target name for an `--only` run. The engine stamps it at `run()` start (only the ROOT collector's value is saved). It's the snapshot-source filter: `_iter_workflow_traces` (the shared candidate iterator used by BOTH the `--only` snapshot loader AND `analyze-cache` autoload via `_collect_candidate_traces`) excludes any trace where `only_node is not None`, because an `--only` run records only its target and isn't a coherent full-run snapshot. **Invariant**: `_iter_workflow_traces` MUST NOT filter `final_status` — each consumer owns its status policy.
- **2.5.0 — interning + canonical LLM prompt/system (issue #382)**. Two shape changes, both reading-transparent on older 2.x traces:
  - **blob interning (disk-only)** — *(2.5.0-era shape; the on-disk encoding is now inline-first-occurrence `blob` lines per Task 172 — see that bullet below; this describes the original 2.5.0 form.)* every large string leaf (≥ `INTERN_MIN_BYTES`, ~1 KB) is replaced by `{"$pflow_blob": "<md5>"}` and the unique content is stored once (2.5.0: a top-level **`blobs` trailer**, last key; Task 172: an inline `blob` line). **In-memory is always plain content; blobs exist only on disk.** All trace-content reads go through the single seam `pflow.core.trace_io.load_trace_file` (the 3 readers: `_iter_workflow_traces`, `prompt_cache_analysis.trace_loading._load_trace_explicit`, `trace_report.generate_report`), which calls `resolve_blobs`. `resolve_blobs` **no-ops** when there's no `blobs` map → older un-interned traces pass through verbatim (backward-compatible). `intern_blobs` is **pure** (rebuilds every container; never mutates `self.events`, which `trace_data["nodes"]` aliases). **Top-level `blobs` is reserved**; intern is `str`-leaf-only (so `resolve` can share one immutable object across N refs). The walk is shape-agnostic (survives the deferred tree→jsonl change, Task 133).
  - **Canonical LLM prompt/system**: an LLM event surfaces the rendered prompt in **one** field, `llm_prompt` (`str | list[dict]`), and the effective system in `llm_system`. The redundant copies are stripped — `prompt`/`system` from `node_output` + `template_resolutions`, and the dead `node_params.prompt` — at the node-aware recording layer (`record_node_execution` for parent events, `_capture_item_trace` for batch items), gated on `is_llm_node_type` (`instrumentation.py`), **after** `llm_prompt`/`llm_system` promotion. `node_params.system` is **kept** (the `## System` config line, distinct from the effective `llm_system`). Batch `_capture_item_trace` **copies** `template_resolutions` before stripping (it's a caller-owned reference). Readers are union-tolerant: `## Prompt` prefers `template_resolutions.prompt.resolved` (present on old traces) and falls back to `llm_prompt` (new traces) — so old traces render identically.
  - **(C) cache-block prompt capture**: for a prewarm batch, `LLMNode.post` mirrors `prep_res["user_message_blocks"]` into `shared["user_message_blocks"]`; `_capture_item_trace` is the single blocks-or-flat writer of `llm_prompt` (the `("prompt","llm_prompt")` entry was removed from the generic promotion loop). Each item's `llm_prompt` becomes the cache-rendered blocks, so the byte-identical shared static-prefix block dedupes to **one blob** under interning. Batch-only; the non-batch trace_hook path and `llm_client.py` are untouched.
  - **`--only` caveat**: because `node_output.prompt`/`system` are no longer persisted, an `--only` snapshot can't re-seed `${node.prompt}`/`${node.system}` (canonical in `llm_prompt`/`llm_system`). Live runs are unaffected — `post` still writes `shared["prompt"]` at runtime; only re-seeding from a trace is affected. No workflow references `${node.prompt}` downstream.
  - **Forward-compat**: 2.5.0 is NOT purely additive (it removes the redundant LLM copies), but every consumer gates on `format_version.startswith("2.")`, all in-repo readers ship together, and old traces still render — so the bump is safe. (Old code reading a *new* trace would see raw `$pflow_blob` refs, but there are no external/persisted old readers.)
- **Task 133 — JSONL transport (on-disk encoding; `format_version` stays `2.x`)**: `save_to_file` now writes the trace as **JSONL** — a `meta` line (carrying a `pflow_trace` marker), one line per flattened event (`id`/`parent_id`/`seq`/`run_id` derived from the nested tree at save time, single-threaded), then `run.complete` and `blobs` **trailer lines**. The "blobs trailer (last key)" described above is now a `blobs` *line*, not a dict key. `load_trace_file` detects the marker and **reconstructs the exact nested dict** every reader expects (strips the correlation keys; a cleanly-parsed but `run.complete`-less line set → `final_status="incomplete"`, never silent success; corrupt → `JSONDecodeError` so the 3 readers degrade). In-memory shape and all readers are unchanged. Flatten/reconstruct live in `core/trace_io.py`; the save→load round-trip is the test oracle (`tests/test_core/test_trace_io.py`). Old single-object traces still load (dual-read). **Superseded by Task 172 (next bullet)** — incremental streaming, inline blobs (the `blobs` trailer line is replaced by inline `blob` lines), and robust crash-tail tolerance are now shipped, so the "deferred Phase D" / "A–C crash-tail skips the whole trace" framing above is historical.
- **Task 172 — emit-time streaming (on-disk encoding evolves; `format_version` stays `2.x`)**: the run-scoped collector now **streams** one JSONL line per node AS the run executes (so a live overlay can tail it; ADR-0008), gated by `RunnerConfig.trace_enabled` (CLI streams + `finalize()`s; MCP and `--no-trace` pass `stream_to_disk=False` → no file). Correlation (`id`/`seq`/`parent_id`/`run_id`) is assigned at **emit** time (reserve-at-descent) rather than derived at save; `ancestor_path`/`port` are emit-stamped and stripped on read. Blobs are **inline-first-occurrence `blob` lines** (`{kind, md5, value}`, written before the first event that references them — backward-only, so a crash-truncated tail stays self-consistent), replacing the `blobs` trailer: ONE representation across the streaming writer (`WorkflowTraceCollector._flush_event`, via `intern_event_leaves`) and the buffer/test whole-file writer (`flatten_trace_to_lines`, via `_inline_blobs`). `finalize()` writes the `run.complete` trailer + closes (CLI-only; idempotent). The reader's `_rebuild_event_tree` is **two-pass** — dedup-by-`id` last-wins (so a routing-dead-end re-flush of a corrected line wins) + lenient **transitive** orphan-drop when there's no `run.complete` (crash mid-sub-workflow recovers everything well-formed). `load_trace_file` **tolerates a single truncated final line** → `final_status="incomplete"`; a malformed *earlier* line still raises. Producer surface: `_open_stream`/`_flush_event`/`_flush_line`/`finalize`/`mark_last_event_failed` (re-flush) in `runtime/workflow_trace.py`.
- **`--only` snapshot helpers** (`load_snapshot_or_raise` / `load_full_run_events` / `seed_snapshot_into_shared`): `--only` runs the target against a frozen snapshot of the most recent full successful run instead of re-walking (which would re-fire side-effecting upstream). `load_full_run_events` returns the newest reusable run's `(nodes, status)` (accepts `success`/`degraded`, rejects `failed`, treats empty `nodes` as no-match); its `"degraded"` status fires only on a genuinely degrading WARNING/ERROR warning (an INFO-only advisory like an empty batch is reported `success`). `load_snapshot_or_raise` is the single home for the "no usable snapshot → `OnlySnapshotMissingError`" decision (falsy check — an EMPTY list raises). `seed_snapshot_into_shared` writes each UPSTREAM node's terminal `node_output` to `shared[node_id]` — scope is nodes that ran BEFORE the target in execution order (templates only reach earlier steps, so this covers everything the target can read; downstream nodes are excluded so their stale output isn't addressable) — filtering the EXACT `apply_memo_hit` reserved set (`__pflow_stats__`/`__pflow_warnings__`, keeping `__metrics__`) and NEVER seeding the target. Engine import of `runtime.workflow_trace` is a light edge (no LiteLLM).
- **LLM prompt + system capture**: Engine.run installs `self.trace` into `shared["__trace_collector__"]`; LLMNode.prep resolves a per-node `trace_hook` via `collector.get_trace_hook(node_id)` and threads it explicitly through the inner ThreadPoolExecutor. The hook writes to `self.llm_prompts[node_id]` AND `self.llm_systems[node_id]`; `_add_llm_data` reads from both. Save+restore around `engine.run` swaps in child collectors for sub-workflows so child LLM calls land in the child's dicts.
- **Batch item tracing**: via `_batch_trace` shared-store accumulator (GIL-safe for parallel)
- **Sub-workflow tracing**: Child collectors created by `WorkflowExecutor`, events embedded as `sub_workflow_events`
- **Per-node aggregation rule — "last event per `node_id` = final state"**: Status determination and the `failed_node_ids` list (written to the trace file by `save_to_file`) both derive from `final_events_by_node(events)` (module-level helper, also imported by `core/trace_report.py::_collect_errors`). Loop recovery records two events for the same node_id; only the later one counts for workflow-level aggregation. Single source of truth — if the rule changes, it changes in one place. See GH #240.
- **`nodes_executed` vs `nodes_failed` semantics**: `nodes_executed = len(self.events)` counts **per-visit** (total invocations). `nodes_failed = len(failed_node_ids)` counts **per-node** (unique failed nodes). Under loop recovery the two diverge: 2 visits, 0 failed nodes → `nodes_executed=2, nodes_failed=0`. `failed_node_ids` is sorted alphabetically for deterministic JSON output.
- **`mark_last_event_failed(node_id, *, error)`**: mutation API used by the engine's `_handle_no_successor` in the non-error-action branch. Flips the most recent event for `node_id` to `success=False` so the trace and `__failures__` agree for routing failures on custom actions. See GH #250.
- **Synthetic cache warmup item (`is_warmup: True`)**: When a parallel batch LLM node prewarms the provider cache, the warmup's `complete()` usage is captured as a synthetic `batch_items[]` entry with `llm_call.is_warmup = True`. Cost-summing consumers include this entry (warmup cost is real); call-counting consumers (`total_calls`, `unavailable_models`, analyzer per-node counts) MUST filter `is_warmup` to avoid inflating user-facing counts. See `engine/CLAUDE.md` → "Synthetic Cache Warmup Item" for the full filtering convention and the 8 sites that apply it.

### Output Resolver (`output_resolver.py`)

`populate_declared_outputs()` maps namespaced outputs to root level. Raises `OutputResolutionError` when a source can't be resolved.

**Coalesce semantics — easy to regress**: `_is_all_absent_coalesce` distinguishes legitimate branch-convergence fallthrough from real errors. A coalesce silently skips ONLY when every operand has `status == "absent"`. Any FAILED or PATH_ERROR operand forces an error — that's the "primary failed via on-error → recovery handler" case the system has to surface, not swallow.

## Reserved Shared Store Keys (Canonical Reference)

```python
# Execution tracking (managed by engine/instrumentation.py).
# The 5-key core shape below is constructed ONLY via
# node_state.new_execution_state() — never re-inline this literal.
shared["__execution__"] = {
    "completed_nodes": [],     # Successfully executed nodes
    "node_actions": {},        # Actions returned by each node
    "node_hashes": {},         # MD5 config hashes for cache validation
    "failed_node": None,       # Node that caused workflow failure
    "node_visit_counts": {},   # Per-node visit counter (loop guard)
    "only_node": None,         # --only target (set by engine; flat only — dotted rejected, issue #443)
    "restored_nodes": [],      # issue #443: nodes seeded from the --only snapshot (NOT executed this
                               # run). get_node_status reports them SUCCEEDED (data-flow-correct), but
                               # build_execution_steps relabels them not_executed so the summary +
                               # --report agree that only the target ran. Set only on --only runs.
}

# Failure archive (managed by runtime/node_state.py::mark_node_failed)
shared["__failures__"] = {
    "node_id": {
        "data": {...},        # what was at shared[node_id] before the move (may be {})
        "category": "shell_failure" | "http_failure" | "mcp_failure" | "llm_failure" | "node_action_error" | "api_warning" | "routing_error" | "exception" | "template_error",
        "error": "...",       # human-readable error (optional)
        # NOTE: warning text is NOT stored here — structured warnings (api_warning
        # + on-error recovery) live only in shared["__warnings__"][node_id].
    }
}

# System keys
shared["__trace_collector__"] = WorkflowTraceCollector
shared["__progress_callback__"] = func
shared["__warnings__"] = {}               # Node warnings → DEGRADED status.
                                          # Values may be legacy strings,
                                          # structured warning dicts, or
                                          # Diagnostic instances. Consumers use
                                          # normalize_runtime_warning(), except
                                          # runner._extract_runtime_warnings
                                          # preserves Diagnostic values as-is.
shared["__cache_hits__"] = []             # Nodes served from cache
shared["__template_errors__"] = {}        # Permissive mode errors
shared["__mcp_pool__"] = MCPConnectionPool
shared["__memoization_cache__"] = MemoizationCache
shared["__index__"] = int                 # 0-based batch item index
shared["__pflow_prompt_cache__"] = MappingProxyType[node_id, CacheRenderContext]
                                          # Task 159 B3.2: per-workflow prompt cache rendering map.
                                          # Read-only proxy over a dict keyed by node_id.
                                          # Engine-installed at WorkflowEngine.run() entry,
                                          # save+restore mirrors __trace_collector__. Restore
                                          # from absent writes _EMPTY_PROMPT_CACHE (a frozen
                                          # empty proxy), NEVER None. Consumers use the
                                          # canonical (shared.get(K) or {}).get(node_id)
                                          # defensive pattern. NOT in _PROPAGATED_KEYS — each
                                          # .pflow.md scopes its own ## Cache (DD#12); leaking
                                          # parent → child would break cache scoping AND the
                                          # CacheBlockIR freeze guarantee.

# Nested workflow keys
shared["_pflow_depth"] = int
shared["_pflow_stack"] = list[str]
shared["_pflow_workflow_file"] = str
shared["_pflow_child_only_node"] = str   # DORMANT plumbing for dotted --only sub-workflow targeting.
                                         # _run_node_with_child_only() can write it (engine.py) and
                                         # WorkflowExecutor.exec() reads it, but the walk currently
                                         # passes child_only=None, so it is never actually written.
                                         # Kept for the deferred nested-targeting follow-up.
```

## Critical Behaviors

### Cache Invalidation (Two Levels)

**In-process cache** (within a single `engine.run()`): Node in `completed_nodes` AND config hash matches → skip re-execution. Invalidated on parameter change (hash mismatch) or revisited nodes (loops).

**Memoization cache** (cross-run, SQLite-backed): `cache_key = hash(config + resolved_inputs)` → hit returns cached output without executing. Invalidated when: config changes (edited node params, different template text), resolved inputs change (upstream produced different output, CLI override changed), or TTL expires (24h default). **Skipped for revisited nodes** (`visit_count > 1`) — memoization is for cross-run caching, not loop caching. **Skipped for workflow nodes** — sub-workflow files may change between runs; inner nodes are individually cached via the propagated `__memoization_cache__`. Error results are never cached. **Cost aggregation** (`collect_llm_calls()`, `_collect_llm_summary()`) excludes cached events — only nodes that actually executed contribute to the run's reported cost.

### Error Categorization (API Warning Detection)

**Validation errors** (parameter format issues, ~40 patterns checked):
- `validation_error` — bad request, invalid parameter, schema error
- `template_error` — unresolved variables (triggers ValueError)

**Resource errors** (external state, ~30 patterns):
- `resource_error` — not found, forbidden
- API warnings: Slack `"ok": false`, Discord errors, GraphQL `"errors": []`
- HTTP status codes: 401, 403, 404, 429
- MCP canonical payloads: explicit failure flags under `${node.result}` (`status: "error"`, `ok: false`,
  `success: false`, etc.) are trusted even when the message text does not match known resource phrases.
  Bare `error` keys without a failure flag still use the conservative phrase checks.

**Ambiguity rule**: When an error matches BOTH validation and resource patterns, it's treated as **validation** (validation wins).

## Gotchas

- **Batch nodes skip top-level template resolution** — engine guards on `not config.batch_config`
- **Fresh Registry instance** — always pass a new one to `compile_workflow()` per execution
- **`__` prefixed params are reserved** — never use for user parameters
- **Don't modify `__execution__` structure** — checkpoint integrity is critical for resume
- **`_source_line` keys NOT filtered in split_params** — `python_code.py` reads them
- **Compile-once cache is keyed by resolved workflow path** (`_compiled_workflow_cache`). Heterogeneous batches with `${item.workflow}` varying per item correctly cache each child separately.
- **Two validation files** — `compilation/ir_preparation.py` (compiler-time) vs `core/workflow/validator.py` (pre-execution). Don't confuse them.
