# Execution Module

Unified execution system. Both CLI and MCP call `WorkflowRunner().run()` which owns the full execution pipeline: resolution → validation → compilation → execution → resource lifecycle → error boundary.

## File Structure

```
src/pflow/execution/
├── __init__.py              # Exports: WorkflowRunner, ExecutionResult, RunnerConfig, etc.
├── runner.py                # THE shared execution pipeline (resolve→validate→compile→execute→return)
├── result.py                # Result types: ExecutionResult, ValidationResult, RunnerConfig, ResolvedWorkflow
├── workflow_resolver.py     # Unified workflow resolution (file, library, markdown, dict → ResolvedWorkflow)
├── executor_service.py      # Internal utility: error extraction helpers (_build_error_list, etc.)
├── execution_state.py       # Per-node execution state building (shared CLI/MCP)
├── plan.py                  # Dry-run planner — graph walker with explicit `Transition` state machine
└── formatters/              # Shared output formatters (return strings/dicts, NEVER print)
    ├── error_formatter.py
    ├── success_formatter.py
    ├── node_output_formatter.py
    ├── validation_formatter.py
    ├── plan_formatter.py
    └── ... (14 formatters total, see formatters/CLAUDE.md)
```

## Dry-Run Planner (`plan.py`)

`build_plan(compiled, params, cache, registry, ...) -> Plan` walks a compiled workflow and produces a typed `Plan` describing what would happen at runtime — cached vs would-execute per node, historical cost for LLM nodes, sub-workflow recursion — without invoking any node side effects. Called by `WorkflowRunner.plan()` and the MCP `plan_workflow` tool.

### State machine (the walker's shape)

The walker is an explicit discriminated-union state machine, not a set of ad-hoc branches:

```python
class Transition(Enum):
    FOLLOW         # advance to successor on `action`
    STOP           # clean termination (end / all-error successors / revisit)
    BOUNDARY       # first would-execute node → BFS downstream, then stop
    ROUTING_ERROR  # cached action has no matching successor → emit + stop

def _classify(entry: PlanEntry, curr) -> Decision  # pure mapping
def _advance(decision, ..., state: _WalkerState) -> Any | None  # dispatches via match
```

`build_plan`'s main loop does exactly three things per iteration: plan one node, classify its transition, apply the decision. `_classify` is the one authoritative mapping from `PlanEntry.status` to `Transition` — extending the planner means adding an enum variant plus a `match` arm plus a `_classify` case, in that order. Unit tests pin the mapping at `tests/test_execution/test_plan_classify.py`.

### Load-bearing invariants (documented at top of `plan.py`)

- The scratch `shared` the planner constructs is planner-owned; `apply_memo_hit` mutates it on memo hits so downstream template resolution matches the engine's cache-key computation. Skipping the mutation looks purer but causes silent drift.
- `node_visit_counts` bumps BEFORE each `plan_node()` call, mirroring the engine's `enforce_loop_guard`. Without it, loop iteration 2+ hits memo cache differently between engine and planner.
- Post-first-miss: BFS over ALL non-"error" successors. Following only `default` underestimates cost for conditional workflows, the wrong failure mode for a cost gate.
- A cached entry whose action has no matching successor = runtime routing error. Surface as a plan entry and stop.

Parity with runtime is pinned by `tests/test_execution/test_plan_drift.py`.

### Entry-builder taxonomy

`_plan_standard_node` dispatches on `NodePlan.status` to one of five named builders: `_template_error_entry` / `_cache_disabled_entry` / `_cached_memo_entry` / `_cached_in_process_entry` / `_miss_entry`. Adding a new status means adding a builder plus one dispatch branch — no scattered edits. `_sub_workflow_error_entry` is shared by every sub-workflow failure path (depth exceeded, resolve failure, cycle, bad inputs).

### `_execute_entry` — single source of truth for `status="execute"` entries

Every would-execute entry — first-miss (`_miss_entry`) AND BFS-downstream (`_make_downstream_entry`) — flows through `_execute_entry(config, cache, *, cause, diagnostic=None)`. It calls `_lookup_last_run_stats` and attaches `last_cost_usd` + `last_duration_ms` + `last_run_age_sec` by construction. Previously the downstream path built a bare `PlanEntry` without stats, so agents cost-gating on an LLM downstream of a non-LLM miss saw `$0` even when history existed. Funneling both paths through the same primitive eliminates the drift surface. Mutation-tested: `tests/test_execution/test_plan_drift.py::test_plan_bfs_downstream_attaches_historical_stats`.

### Historical stats (`_read_stats_from_output`, `_lookup_last_run_stats`)

Cost (`llm_usage.cost_usd`, LLM-only) and duration (`__pflow_stats__.duration_ms`, all-node) both ride inside the cached output blob — no schema change to `cache_entries`. `_read_stats_from_output` is the symmetric reader for the key `instrumentation.py::write_memo_cache` injects. See `runtime/engine/CLAUDE.md` → "Engine-injected output metadata" for the convention and its load-bearing dunder-naming rationale.

`PlanSummary` carries parallel aggregates: `estimated_cost_usd` + `nodes_without_history` (LLM cost domain), `estimated_duration_ms` + `nodes_without_duration_history` (all-node duration domain), each with an `_including_nested` variant that rolls sub-workflow totals up to the parent level. Agents cost- or time-gating should read the `_including_nested` value when present; formatters do the same.

### Text vs JSON per-entry rendering

Per-entry `last_duration_ms` is only rendered in text when ≥ 1s (`_TEXT_DURATION_THRESHOLD_MS`) — see `plan_formatter.py::_format_stats_annotation`. Sub-second durations still contribute to the summary aggregate and always appear in JSON at full precision. Rationale: twenty 50ms code nodes in a row pads text output without signal; the summary's total still reflects them; agents parse JSON for exact numbers.

### Sub-workflow compile failures

`_compile_child` raises `_ChildCompileFailed(entry=...)` when the child fails a recoverable compile check. The caller unwraps it in one line (`except _ChildCompileFailed as failure: return failure.entry`), avoiding a `CompiledWorkflow | PlanEntry` sum type and the isinstance plumbing that would come with it.

## WorkflowRunner — Primary Entry Point

```python
class WorkflowRunner:
    def run(workflow, params, config, *, progress_callback=None, workflow_manager=None, workflow_name=None) -> ExecutionResult
    def validate(workflow, params, *, source_file_path=None) -> ValidationResult
    def plan(workflow, params, config) -> Plan
```

**Stateless**: fresh instance per call. No mutable state on instance.

**Pipeline** (inside `run()`):
1. `_resolve()` — unified resolver (file, library, markdown, dict → `ResolvedWorkflow`)
2. `_resolve_file_references()` — external file refs in IR
3. `_fill_declared_defaults()` — fills declared inputs with defaults or placeholders so validation doesn't flag them as missing. Stripped before compilation.
4. `_validate()` — `WorkflowValidator.validate()`, once per execution
5. Create per-execution resources (MetricsCollector, TraceCollector, MCPConnectionPool, MemoizationCache)
6. `_compile_and_execute()` — `compile_workflow()` + `WorkflowEngine.run()`. On exception: annotates `e._pflow_node_id` (skipped for `OutputResolutionError`) and `e._pflow_shared_store` so `_exception_to_result` can populate `ExecutionResult.shared_after` with the full failure state.
7. `_build_errors()` + `_extract_runtime_warnings()` — converts shared store + action result into `Diagnostic` list. Permissive-mode template warnings pass through the structured `Diagnostic` already built by `runtime/engine/template_errors.py` (preserves `unresolved_references`); api warnings still build a basic Diagnostic from `__warnings__[id]`.
8. `_cleanup()` — MCP pool shutdown, LLM interception cleanup, metrics end (in `finally`)

`plan()` reuses the same resolve → file-ref → validation → compile pipeline, then delegates to `execution/plan.py::build_plan()` instead of running the engine. No trace collector, metrics collector, MCP pool, or progress callback is created on the plan path.

**Exception boundary**: `run()` catches ALL exceptions, wraps into `ExecutionResult`. Only `KeyboardInterrupt`/`SystemExit` propagate.

**Exception-path observability** (load-bearing): `_compile_and_execute` attaches `e._pflow_shared_store = shared_store` before re-raising. `_exception_to_result` reads it via `getattr(e, "_pflow_shared_store", None)` to populate `ExecutionResult.shared_after`. Without this, exception-path crashes (shell timeout, batch all-failed raise, code node exception) lose ALL per-node detail in the CLI/MCP summary — `__failures__` is invisible to formatters even though step 17.5 archived it correctly.

**`OutputResolutionError` is excluded** from `_pflow_node_id` annotation: it's raised from `populate_declared_outputs` AFTER node execution, so the stale `__execution__["failed_node"]` (from a previously-recovered failure) would lie about the error location.

**Resource lifecycle**: Resources created in `run()` scope (not inside helpers) so `finally` always has them for cleanup. This prevents MCP server subprocess leaks.

**On-error recovery status** (GH #246 fix): When a node fails and has an `on-error` handler, engine step 17.5 passes `warning=` to `mark_node_failed`, which populates `__warnings__`. This naturally triggers DEGRADED status via the existing `_determine_status` check on `__warnings__`. The `_extract_runtime_warnings` method distinguishes recovery warnings from api_warnings by checking the `__failures__` record's `warning` field and `category`.

## Result Types (result.py)

```python
@dataclass(frozen=True)
class RunnerConfig:
    trace_enabled: bool = True
    cache_enabled: bool = True
    verbose: bool = False
    only_node: Optional[str] = None

@dataclass(frozen=True)
class ResolvedWorkflow:
    ir: dict[str, Any]
    source: str  # "file", "library", "content", "direct"
    file_path: Optional[str] = None
    diagnostics: tuple[Diagnostic, ...] = ()

@dataclass
class ValidationResult:
    valid: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]: ...

    @property
    def warnings(self) -> list[Diagnostic]: ...

@dataclass
class ExecutionResult:
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    trace: Optional[Any] = None
    metrics: Optional[Any] = None

    @property
    def errors(self) -> list[Diagnostic]: ...

    @property
    def warnings(self) -> list[Diagnostic]: ...

@dataclass(frozen=True)
class PlanEntry: ...

@dataclass(frozen=True)
class PlanSummary: ...

@dataclass(frozen=True)
class Plan:
    workflow: str
    entries: list[PlanEntry]
    summary: PlanSummary
    diagnostics: list[Diagnostic] = field(default_factory=list)
```

## Unified Resolver (workflow_resolver.py)

`resolve_workflow(identifier: str | dict, wm=None) -> ResolvedWorkflow`

Merges CLI and MCP resolvers. Input types:
- `dict` → passthrough as `source="direct"`
- String with `\n` → parse as markdown, `source="content"`
- File path → load + parse, `source="file"`, `file_path=absolute_path`
- Saved name → load from library, `source="library"`, `file_path=absolute_path`

Raises `WorkflowNotFoundError` (with `similar_names` for suggestions) on not-found.

## Error Structure (Canonical Reference)

```python
Diagnostic(
    severity=Severity.ERROR,
    source="runtime",               # Where error originated
    message="Field 'title' required",
    node_id="create-issue",         # Which node failed
    context={
        "category": "api_validation",
        # Rich context from shared_store[node_id] — see executor_service.build_error_list()
    },
)
```

`executor_service.build_error_list()` reads the failed node from `__execution__["failed_node"]`, then prefers `__failures__[id].category` (set authoritatively by `mark_node_failed`) over the legacy regex-on-message detection. The category is mapped through `_FAILURE_CATEGORY_MAP` to a Diagnostic category. Rich error context (shell command/exit_code/stderr, HTTP status_code/url/response, MCP error_details) comes from `get_node_output(shared_store, failed_node)` which reads either `shared[id]` (succeeded — unlikely on the failure path but defensive) or `__failures__[id].data`.

## execution_state.py

`build_execution_steps(workflow_ir, shared_storage, metrics_summary)` produces the per-node row list consumed by `success_formatter` and `error_formatter` for CLI/MCP execution summaries. **Status comes from `node_state.get_node_status`** (mapped through `_STATUS_MAP` to `completed`/`failed`/`not_executed`) — NOT from the singular `__execution__["failed_node"]` pointer, which loses earlier failures in multi-failure workflows. Batch metadata is read via `get_node_output` so failed batch nodes still surface `batch_metadata` / `batch_error_details` in the summary.


## Integration

**CLI**: `cli/main.py:execute_json_workflow()` calls `WorkflowRunner().run()`, passing `progress_callback=output_controller.create_progress_callback()` when progress is enabled. Handles: stdin routing, trace saving, display.

**MCP Server**: `mcp_server/services/execution_service.py` calls `WorkflowRunner().run()` without a progress callback (defaults to `None`). Three methods: `execute_workflow()`, `validate_workflow()`, `run_registry_node()`.

**Registry run**: `run_registry_node()` builds synthetic single-node IR, resolves `${ENV_VAR}` from env/settings, and routes through `WorkflowRunner().run()` with `RunnerConfig(cache_enabled=False)`.

## Testing

**Mock points**: `WorkflowRunner.run` (CLI/MCP tests), `WorkflowRunner._compile_and_execute` (bypass resolution/validation), `compile_workflow()` (compilation tests), `WorkflowValidator.validate` (warning plumbing).

**Key test files**:
- `tests/test_execution/test_runner.py` — Runner pipeline behavior
- `tests/test_integration/test_cli_mcp_parity.py` — CLI/MCP equivalence
- `tests/test_mcp_server/test_mcp_warnings.py` — validation warnings propagation

## Gotchas

- **Display-agnostic**: Never import Click or add CLI concerns here. Progress events flow through the optional `progress_callback` stored under `shared_store["__progress_callback__"]`.
- **Don't cache errors**: Never cache nodes that return "error" action.
- **`ExecutionResult.shared_after` is populated on exception paths** via the `_pflow_shared_store` annotation. Consumers can inspect `result.shared_after["__failures__"]` for failure detail even when the engine raised. Without the annotation chain, this would be empty.
- **`OutputResolutionError` carries `node_id=None`** in its Diagnostic — it's about an output declaration, not a node. Don't add per-node display logic that assumes every error has a node_id.
- **`_extract_runtime_warnings` template_error path passes through structured Diagnostic** — do NOT replace it with canned suggestion strings. The structured `unresolved_references` carry per-ref classification that the renderer consumes. Canned suggestions would silently lose all per-ref data.
- **Dict passthrough skips file ref guard**: When Runner receives dict input, `_check_inline_file_references()` is bypassed. CLI/MCP callers who pre-resolve to dict must handle this.
- **MCPNode error detection**: `MCPNode.post()` returns "default" action even on errors (workaround for missing error edges). Formatters also check for `"error"` key in outputs/shared_store.
- **`executor_service.py` is an internal utility**: Contains standalone error extraction functions (`build_error_list`, `determine_error_category`, etc.). The Runner delegates to these via `_build_errors()`. Not part of public API. Reads category from `__failures__` first; legacy regex is fallback only.
