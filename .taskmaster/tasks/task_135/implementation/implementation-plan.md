# Task 135: Execution Core Redesign — Implementation Plan

## Context

pflow's execution core conflates compiled structure with runtime state via a 4-layer wrapper chain (3,920 lines wrapping 205 lines of PocketFlow). This causes: sub-workflows recompiling per batch item (O(N) at 20-50ms each), `initial_params` dual-data-path hacks, cross-wrapper coupling, 80% code duplication in batch paths. Task 138 created a single compilation callsite (`WorkflowRunner`) making this redesign safe.

**Goal**: Replace the wrapper chain with an orchestration engine. Shared store becomes the single source of runtime data. Compile-once falls out naturally. Subsumes Task 140.

## Architecture

```
BEFORE: compile_ir_to_flow() → Flow(start=InstrumentedWrapper(BatchNode(NamespaceWrapper(TemplateWrapper(Node)))))
         flow.run(shared) → wrapper chain handles all concerns via nested _run() delegation

AFTER:  compile_workflow() → CompiledWorkflow(start_node=BareNode, node_configs={...}, outputs={...})
         engine.run(workflow, shared) → engine handles all concerns sequentially per node
```

### Key Design Decisions from Code Review

1. **`_execute_single_node` returns a tuple** `(action, last_resolutions, template_errors)` — NO instance state on the engine. This prevents a data race in parallel batch (5/8 review agents flagged `self._last_resolutions` as a race condition).

2. **No `structural_only` compilation mode needed.** Since `initial_params` no longer gets baked into compiled nodes, compiling sub-workflows with first-item params is safe — the compiled graph IS structural by design. `prepare_inputs()` runs once, captures `resolved_defaults`, and subsequent items reuse the cached `CompiledWorkflow`. This eliminates what was Phase 5 in the original plan.

3. **Backward-compat alias returns a shim with `.run()`**, not raw `CompiledWorkflow`. 28+ tests call `flow.run(shared)` on the result — returning `CompiledWorkflow` would break them all with `AttributeError`.

4. **Template resolution happens early in `_execute_node`** — before the memo cache check. The resolved params are used for both cache key computation AND param setting. One resolution, two uses. On cache hit the sub-millisecond resolution work is "wasted" — acceptable.

5. **`compile_workflow()` includes `resolve_file_references()`** — same as current `compile_ir_to_flow()`. Without this, sub-workflow `code: @./code.py` references silently break.

6. **`CompiledWorkflow` is reusable for sequential batch items** within one execution. NOT safe for concurrent `engine.run()` calls on the same instance (because `node.params` is mutated during execution).

7. **Batch output shape is IDENTICAL to current `PflowBatchNode.post()`** — keys `results`, `count`, `success_count`, `error_count`, `errors`, `batch_metadata`. The `BATCH_OUTPUTS` contract in `template_validation/validator.py` needs no change.

---

## Phase 1: New Types + Extracted Functions (additive only — no existing code changes)

### 1A. Create `src/pflow/runtime/engine/types.py`

```python
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class TemplateConfig:
    """Per-node template configuration, built at compile time."""
    template_params: dict[str, Any]      # Params containing ${...} (raw template strings)
    static_params: dict[str, Any]        # Params without templates (already type-coerced)
    expected_types: dict[str, str]       # param_key -> declared type (from registry interface)
    resolution_mode: str                 # "strict" or "permissive"
    optional_input_keys: set[str] = field(default_factory=set)  # For branch convergence

@dataclass
class BatchConfig:
    """Per-node batch configuration, built at compile time."""
    items_template: Any                  # Template string "${node.list}" or inline list
    item_alias: str = "item"             # Variable name for current item
    error_handling: str = "fail_fast"    # "fail_fast" or "continue"
    parallel: bool = False
    max_concurrent: int = 10
    max_retries: int = 1
    retry_wait: float = 0.0

@dataclass
class NodeConfig:
    """Per-node metadata extracted at compile time. Immutable after compilation."""
    node_id: str
    node_type_name: str                          # Actual node class name (e.g., "ShellNode")
    template_config: Optional[TemplateConfig]    # None if no templates in params
    batch_config: Optional[BatchConfig]          # None if not a batch node
    namespaced: bool                             # Whether node outputs are namespaced
    interface_metadata: Optional[dict[str, Any]] # Registry interface for type validation

@dataclass
class CompiledWorkflow:
    """Structural compilation result. Reusable across sequential batch items within one execution.
    NOT safe for concurrent engine.run() calls (node.params is mutated during execution)."""
    start_node: Any                              # First bare node (BaseNode/Node instance)
    node_configs: dict[str, NodeConfig]          # node_id -> config
    outputs: dict[str, Any] = field(default_factory=dict)  # IR outputs section
    resolved_defaults: dict[str, Any] = field(default_factory=dict)  # From prepare_inputs
    env_param_names: set[str] = field(default_factory=set)
    template_resolution_mode: str = "strict"
```

### 1B. Create `src/pflow/runtime/engine/template_resolution.py`

Extract template resolution logic from `template_wrapper.py` into standalone functions:

```python
def build_type_cache(interface_metadata: Optional[dict[str, Any]]) -> dict[str, str]:
    """Extract param_key -> expected_type from registry interface metadata."""
    # Logic from TemplateAwareNodeWrapper._build_type_cache (lines 118-158)

def split_params(params: dict[str, Any], expected_types: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate params into template_params and static_params.
    Static params get type coercion via coerce_to_declared_type.
    Filter _source_line keys from BOTH buckets (they're metadata, not real params).
    Returns (template_params, static_params)."""
    # Logic from TemplateAwareNodeWrapper.set_params (lines 79-116)
    # WITHOUT the inner_node.set_params() call — just returns the split

def resolve_templates(
    template_config: TemplateConfig,
    shared: dict[str, Any],
    node_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Resolve all template params against shared store.

    Returns (merged_params, last_resolutions, template_errors).
    - merged_params: static + resolved template params (ready to set on node)
    - last_resolutions: {key: {template, resolved}} for trace capture
    - template_errors: list of error dicts for permissive mode (empty in strict — raises instead)

    Raises ValueError in strict mode on unresolved templates or type mismatches.

    ORDERING CONTRACT: The 'inputs' key is ALWAYS processed first. Resolved input values
    are merged into the resolution context before other template params are resolved.
    This enables patterns like ${text} in prompt after inputs.text is resolved.

    CONTEXT BUILDING: context = dict(shared) — NO initial_params override. The shared
    store is the single source of runtime data.

    PERMISSIVE MODE: The __PERMISSIVE_TYPE_ERROR__ prefix protocol from the old
    TemplateAwareNodeWrapper is eliminated. validate_resolved_type() returns Optional[str]
    (error message or None). resolve_templates() collects these into template_errors list.
    Strict mode raises ValueError directly. No string-prefix signaling.

    ON ERROR IN STRICT MODE: last_resolutions contains all params resolved so far
    (partial resolutions). The ValueError is raised AFTER storing partial resolutions
    so callers can use them for trace recording on the error path.
    """
    # Logic from TemplateAwareNodeWrapper.resolve_templates (lines 495-679)
```

**Also extract these helper functions** (used by `resolve_templates`):

```python
def resolve_template_parameter(key, template, context) -> tuple[Any, bool]
    # From _resolve_template_parameter (line 466)

def contains_unresolved_template(resolved_value, original_template, _depth=0) -> bool
    # From _contains_unresolved_template (line 394) + _check_string/list/dict_unresolved

def validate_resolved_type(param_key, resolved_value, template_str, expected_types, resolution_mode) -> Optional[str]
    # From _validate_resolved_type (line 160) — returns error message instead of raising
    # The __PERMISSIVE_TYPE_ERROR__ prefix protocol is eliminated

def inject_none_for_optional_inputs(key, resolved_value, template, context, optional_input_keys) -> Any
    # From _inject_none_for_optional_inputs (line 347) — already nearly standalone

def all_variables_from_absent_nodes(template_str, context) -> bool
    # From _all_variables_from_absent_nodes (line 332) — already a static method
```

**Dependencies to import**: `TemplateResolver` from `runtime/template_resolver.py`, `try_parse_json` from `core/json_utils`, `coerce_to_declared_type` from `core/param_coercion`, `build_enhanced_template_error`/`build_type_error_message`/`build_json_parse_error_message` from relocated `template_errors.py`, `get_upstream_stderr` from relocated `error_context.py`.

### 1C. Create `src/pflow/runtime/engine/batch_executor.py`

Extract batch execution logic from `batch_node.py`:

```python
def resolve_batch_items(items_template: Any, shared: dict[str, Any]) -> Any:
    """Resolve batch items template. Returns list on success, None if unresolved."""
    # Exact copy of resolve_batch_items from batch_node.py lines 91-119

def execute_batch(
    node: Any,                    # Bare node instance
    config: NodeConfig,           # Includes batch_config and template_config
    shared: dict[str, Any],       # Parent shared store
    execute_single_fn: Callable,  # Callback: (node, config, item_shared) -> (action, last_resolutions, template_errors)
) -> tuple[str, list[dict], Optional[list]]:
    """Execute a batch node: resolve items, iterate, aggregate results.

    Handles: sequential/parallel dispatch, per-item isolation, retry,
    error handling (fail_fast/continue), progress callbacks, trace capture,
    all-fail abort, empty batch warning.

    MUST initialize shared["_batch_trace"][node_id] = [] before item execution.

    Returns (action, batch_trace_items, last_resolutions_unused).
    - action: "default" on success
    - batch_trace_items: per-item trace events for record_trace()
    - last_resolutions_unused: always {} (batch items handle their own resolutions)

    Output shape written to shared[node_id] is IDENTICAL to PflowBatchNode.post():
    {results, count, success_count, error_count, errors, batch_metadata}
    """
    # Logic from PflowBatchNode.prep + _exec + post (unified)
```

**Internal helpers** (private to this module):

```python
def _execute_batch_item(
    idx: int, item: Any, node: Any, config: NodeConfig,
    parent_shared: dict[str, Any], execute_single_fn: Callable,
    batch_config: BatchConfig,
) -> tuple[dict | None, dict | None, float, dict, list]:
    """Execute single batch item with retry. UNIFIED path for both seq and parallel.
    Returns (result, error_info, duration_ms, last_resolutions, template_errors)."""
    # Merges _exec_single + _exec_single_with_node into ONE function
    # For parallel: receives deep-copied node
    # CompilationError always fatal — never swallowed, never retried

def _execute_sequential(items, node, config, parent_shared, execute_single_fn, batch_config) -> list
def _execute_parallel(items, node, config, parent_shared, execute_single_fn, batch_config) -> list
    # Parallel: deep-copies bare node per thread (cheap — trivial __init__)
    # Uses bare ThreadPoolExecutor (NOT context manager) + shutdown(wait=False, cancel_futures=True)
    # Metrics/trace collectors are NOT copied — shared across threads
def _collect_parallel_results(future_to_idx, items, results, timings, pending_errors, should_stop, batch_config, shared) -> bool
def _aggregate_batch_results(exec_res, errors, item_timings, batch_config, node_id, shared) -> str
    # From PflowBatchNode.post — writes shared[node_id] = {results, count, ...}
    # Output keys MUST match: results, count, success_count, error_count, errors, batch_metadata
def _capture_item_trace(item_shared, idx, item, duration_ms, error, node, node_id, parent_shared) -> None
    # Appends to parent_shared["_batch_trace"][node_id] — GIL-protected for parallel (CPython)
def _detect_empty_output_items(exec_res, errors) -> list[int]
    # Already standalone in batch_node.py
def _push_batch_warnings(shared, exec_res, errors, node_id, batch_config) -> None
    # From PflowBatchNode._push_warnings
```

### 1D. Create `src/pflow/runtime/engine/instrumentation.py`

Extract instrumentation concerns from `instrumented_wrapper.py` into standalone functions:

```python
# --- Execution State ---
def initialize_execution_state(shared: dict) -> None:
    """Ensure __execution__ and __cache_hits__ exist. From _initialize_execution_state."""

def enforce_loop_guard(node_id: str, shared: dict) -> dict:
    """Increment visit count, raise MaxNodeVisitsError if exceeded.
    Invalidates in-process cache for revisited nodes. Returns visit_counts dict.
    From _enforce_loop_guard."""

# --- In-Process Cache (Checkpoint/Resume) ---
def check_cache_validity(node_id: str, node_type_name: str, config_hash: str, shared: dict) -> tuple[bool, Any]:
    """Check if node is in completed list with matching hash. Returns (valid, cached_action).
    From _check_cache_validity."""

def cache_result(node_id: str, config_hash: str, action: str, shared: dict) -> None:
    """Record node as completed. From _cache_result_if_successful."""

def invalidate_cache(node_id: str, shared: dict) -> None:
    """Remove node from all cache structures. From _invalidate_cache."""

# --- Memoization Cache (Cross-Run SQLite) ---
def compute_node_config(node_type_name: str, static_params: dict, template_params: dict, batch_config: Optional[BatchConfig]) -> dict:
    """Build config dict for cache key. From _compute_node_config.
    Reads directly from config, no chain traversal.
    MUST include template_params (raw template strings) in the hash —
    changing ${old_var} to ${new_var} must invalidate the cache.
    MUST exclude _source_line keys from static_params."""

def compute_config_hash(config: dict) -> str:
    """MD5 of deterministic JSON. From _compute_config_hash."""

def check_memo_cache(
    node_id: str, node_type_name: str, config_hash: str,
    batch_config: Optional[BatchConfig],
    shared: dict, visit_counts: dict,
    resolved_params: Optional[dict] = None,  # For non-batch cache key
) -> tuple[bool, Any, Optional[str]]:
    """Check SQLite memo cache. Returns (hit, result, cache_key).
    From _check_memo_cache. Skips for revisited nodes and WorkflowExecutor.
    For non-batch: cache key = hash(config + resolved_params).
    For batch: cache key from resolve_batch_items() + semantic batch config."""

def write_memo_cache(node_id: str, shared: dict, cache_key: Optional[str]) -> None:
    """Write to SQLite cache after successful execution. From _write_memo_cache."""

# --- Metrics & Tracing ---
def record_trace(
    node_id: str, node_type_name: str, shared: dict,
    start_time: float, shared_keys_before: set,
    last_resolutions: dict, batch_trace_items: Optional[list],
    child_trace_events: Optional[list], node_params: dict,
    trace_collector: Any, cached: bool = False, error: Optional[Exception] = None,
) -> None:
    """Record trace event. From _record_trace.
    Key change: receives data directly, no chain traversal."""

def enrich_llm_cost(node_id: str, shared: dict) -> None:
    """Add cost data to llm_usage. From _enrich_llm_cost."""

def setup_llm_interception(node_id: str, node_type_name: str, node_params: dict, trace_collector: Any) -> None:
    """Set up LLM prompt/response capture. From _setup_llm_interception."""

# --- Progress Callbacks ---
def call_start_callback(node_id: str, shared: dict) -> None:
    """Call progress callback with node_start. Extracted from _run lines 763-773."""

def call_completion_callback(
    node_id: str, shared: dict, action: str, duration_ms: float,
    error: Optional[Exception] = None, ignore_errors: bool = False,
) -> None:
    """Call progress callback with node_complete. From _call_completion_callback."""

# --- API Warning ---
def handle_api_warning(node_id: str, shared: dict, warning: str, metrics: Any, trace_collector: Any, start_time: float, shared_keys_before: set) -> str:
    """Handle API warning: record failure, return 'error'. From _handle_api_warning."""
```

### 1E. Create `src/pflow/runtime/engine/__init__.py`

```python
from .types import BatchConfig, CompiledWorkflow, NodeConfig, TemplateConfig
```

### 1F. Move standalone utilities from `wrappers/` to `runtime/engine/`

| From | To | Notes |
|------|----|-------|
| `wrappers/namespaced_store.py` | `runtime/engine/namespaced_store.py` | Used by engine for per-node store proxy |
| `wrappers/api_warning_detector.py` | `runtime/engine/api_warning_detector.py` | Already standalone |
| `wrappers/template_errors.py` | `runtime/engine/template_errors.py` | Already standalone |
| `wrappers/error_context.py` | `runtime/engine/error_context.py` | Already standalone |

Update internal imports (change `from ..template_resolver` to `from pflow.runtime.template_resolver`).

**Phase 1 Verification**: `make test` — all existing tests pass (new files are additive, nothing changed).

---

## Phase 2: The Execution Engine

### 2A. Create `src/pflow/runtime/engine/engine.py`

The engine replaces `Flow._orch()` + all 4 wrappers. One class, ~400-500 lines (vs 3,920 lines of wrappers).

```python
import time
import warnings
from typing import Any, Optional

class WorkflowEngine:
    """Executes a CompiledWorkflow by walking the node graph and handling all runtime concerns."""

    def __init__(
        self,
        metrics_collector: Optional[Any] = None,
        trace_collector: Optional[Any] = None,
        only_node: Optional[str] = None,
    ):
        self.metrics = metrics_collector
        self.trace = trace_collector
        self.only_node = only_node

    def run(self, workflow: CompiledWorkflow, shared: dict[str, Any]) -> str:
        """Execute a compiled workflow. Returns action string."""
        # 1. Reset visit counts (replaces _apply_run_hooks reset)
        if "__execution__" in shared and "node_visit_counts" in shared["__execution__"]:
            shared["__execution__"]["node_visit_counts"] = {}

        # 2. Walk graph
        curr = workflow.start_node
        last_action = None
        while curr:
            # Guard: node must have node_id (set by compiler)
            node_id = getattr(curr, "node_id", None)
            if node_id is None or node_id not in workflow.node_configs:
                from pflow.runtime.compilation.compiler import CompilationError
                raise CompilationError(
                    f"Node in graph has no node_id or missing from node_configs",
                    phase="execution", suggestion="This indicates a compiler bug"
                )

            config = workflow.node_configs[node_id]
            last_action = self._execute_node(curr, config, shared)

            # --only: stop after target node
            if self.only_node and node_id == self.only_node:
                if "__execution__" in shared:
                    shared["__execution__"]["only_node"] = self.only_node
                break

            # Follow successor edge
            nxt = curr.successors.get(last_action or "default")
            if not nxt and curr.successors:
                # Write to __warnings__ for agent visibility (not warnings.warn which is invisible in JSON)
                shared.setdefault("__warnings__", {})[node_id] = (
                    f"Node '{node_id}' returned action '{last_action}' "
                    f"but no successor edge matches. Available: {list(curr.successors)}. "
                    f"Execution stopped after this node."
                )
            curr = nxt

        # 3. Populate declared outputs (replaces _apply_run_hooks output resolution)
        is_error = last_action and isinstance(last_action, str) and str(last_action).startswith("error")
        if workflow.outputs and not is_error and not self.only_node:
            from pflow.runtime.output_resolver import populate_declared_outputs
            populate_declared_outputs(shared, {"outputs": workflow.outputs})

        return str(last_action) if last_action else "default"
```

#### `_execute_node` — the core orchestration method

```python
    def _execute_node(self, node, config: NodeConfig, shared: dict) -> str:
        """Execute a single node with all runtime concerns."""
        start_time = time.perf_counter()
        shared_keys_before = set(shared.keys())

        # 1. LLM interception
        setup_llm_interception(config.node_id, config.node_type_name, node.params, self.trace)

        # 2. Execution state
        initialize_execution_state(shared)

        # 3. Loop guard
        visit_counts = enforce_loop_guard(config.node_id, shared)

        # 4. Resolve templates EARLY — needed for both cache key and execution
        last_resolutions = {}
        template_errors = []
        resolved_params = None
        if config.template_config:
            resolved_params, last_resolutions, template_errors = resolve_templates(
                config.template_config, shared, config.node_id
            )

        # 5. Memoization cache check (uses resolved_params for key)
        config_hash = compute_config_hash(compute_node_config(
            config.node_type_name,
            config.template_config.static_params if config.template_config else node.params,
            config.template_config.template_params if config.template_config else {},
            config.batch_config,
        ))
        hit, result, cache_key = check_memo_cache(
            config.node_id, config.node_type_name, config_hash,
            config.batch_config, shared, visit_counts,
            resolved_params=resolved_params,
        )
        if hit:
            return result

        # 6. In-process cache check
        cached, cached_action = check_cache_validity(config.node_id, config.node_type_name, config_hash, shared)
        if cached:
            return self._handle_cached_execution(config, shared, cached_action, last_resolutions)

        # 7. Progress callback (node_start)
        call_start_callback(config.node_id, shared)

        try:
            # 8. Execute: batch or single
            if config.batch_config:
                action, batch_trace_items = execute_batch(
                    node, config, shared, self._execute_single_node
                )
                child_trace_events = None
            else:
                # Set resolved params on node and execute
                if resolved_params is not None:
                    node.params = resolved_params
                    # Write permissive-mode errors to shared store
                    for err in template_errors:
                        shared.setdefault("__template_errors__", {})[config.node_id] = err

                store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
                action = node._run(store)
                batch_trace_items = None

                # Read child trace events from WorkflowExecutor
                child_trace_events = None
                if config.node_type_name == "WorkflowExecutor":
                    child_trace_events = getattr(node, '_child_trace_events', None)

            # 9. API warning detection
            warning = detect_api_warning(config.node_id, shared)
            if warning:
                return handle_api_warning(
                    config.node_id, shared, warning, self.metrics, self.trace,
                    start_time, shared_keys_before
                )

            # 10-15. Post-execution: cache, memo, metrics, cost, trace, callback
            cache_result(config.node_id, config_hash, action, shared)
            write_memo_cache(config.node_id, shared, cache_key)
            # metrics recording
            enrich_llm_cost(config.node_id, shared)
            record_trace(
                config.node_id, config.node_type_name, shared,
                start_time, shared_keys_before, last_resolutions,
                batch_trace_items, child_trace_events, node.params,
                self.trace,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            call_completion_callback(config.node_id, shared, action, duration_ms)

            return action

        except Exception as e:
            # Error path: still record metrics, trace, mark failure
            duration_ms = (time.perf_counter() - start_time) * 1000
            enrich_llm_cost(config.node_id, shared)
            record_trace(
                config.node_id, config.node_type_name, shared,
                start_time, shared_keys_before, last_resolutions,
                batch_trace_items, child_trace_events, node.params,
                self.trace, error=e,
            )
            if "__execution__" in shared:
                shared["__execution__"]["failed_node"] = config.node_id
            raise
```

#### `_execute_single_node` — returns tuple, NO instance state

```python
    def _execute_single_node(
        self, node, config: NodeConfig, shared: dict
    ) -> tuple[str, dict, list]:
        """Execute a non-batch node: resolve templates, namespace, run.
        Returns (action, last_resolutions, template_errors).
        NO instance state stored — safe for parallel batch."""
        last_resolutions = {}
        template_errors = []

        if config.template_config:
            merged_params, last_resolutions, template_errors = resolve_templates(
                config.template_config, shared, config.node_id
            )
            node.params = merged_params
            for err in template_errors:
                shared.setdefault("__template_errors__", {})[config.node_id] = err

        store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
        action = node._run(store)

        return action, last_resolutions, template_errors
```

### 2B. Update `src/pflow/runtime/engine/__init__.py`

```python
from .types import BatchConfig, CompiledWorkflow, NodeConfig, TemplateConfig
from .engine import WorkflowEngine
```

**Phase 2 Verification**: Unit tests for the engine (new test file). Existing tests still pass.

---

## Phase 3: Compiler Changes

### 3A. Modify `src/pflow/runtime/compilation/compiler.py`

**New `compile_workflow` function**:

```python
def compile_workflow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
) -> CompiledWorkflow:
    """Compile IR to CompiledWorkflow. No runtime state baked in."""
```

Key differences from current `compile_ir_to_flow`:
- Returns `CompiledWorkflow` instead of `Flow`
- No `metrics_collector` or `trace_collector` params (runtime concerns, set on engine)
- No `only_node` param (engine parameter)
- `_prepare_compilation()` still runs (structural validation + input resolution)
- **Includes `resolve_file_references()` step** (same as current, needed for sub-workflows)
- `_instantiate_nodes()` creates BARE nodes + NodeConfigs (no wrapper chain)
- `_wire_nodes()` unchanged (wires bare nodes)
- No `_apply_run_hooks` or `_apply_only_node_stop` (engine handles these)

**Modify `_prepare_compilation` return** to surface `resolved_defaults` and `env_param_names`:

```python
def _prepare_compilation(
    ir_dict: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    """Returns (mutated initial_params, resolved_defaults, env_param_names)."""
    # ... existing validation steps ...
    errors, defaults, env_param_names = prepare_inputs(ir_dict, initial_params, settings_env=settings_env)
    # ... existing error handling ...
    initial_params.update(defaults)
    return initial_params, defaults, env_param_names  # NEW: surface defaults + env names
```

**Replace `_create_single_node` with `_create_node_and_config`**:

```python
def _create_node_and_config(
    node_data: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
    template_resolution_mode: str,
) -> tuple[Any, NodeConfig]:
    """Create a bare node instance and its NodeConfig."""
```

This function:
1. Extracts `node_id`, `node_type`, `params` from `node_data`
2. Threads source-line metadata into params
3. Injects default LLM model if needed
4. Imports and instantiates bare node: `node_class()` (NO wrappers applied)
5. Sets `node.node_id = node_id` (engine needs this for config lookup)
6. Extracts `interface_metadata` from registry
7. Extracts `optional_input_keys` for code nodes
8. Injects special parameters (workflow `__registry__`, MCP `__mcp_server__`/`__mcp_tool__`)
9. Calls `split_params(params, expected_types)` to separate template/static (filters `_source_line` keys)
10. Sets `node.set_params(static_params)` — node gets ONLY static params at compile time
11. Builds `NodeConfig` with all per-node metadata
12. Returns `(node, config)`

**Replace `_instantiate_nodes`**:

```python
def _instantiate_nodes(
    ir_dict: dict[str, Any],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    template_resolution_mode: str = "strict",
) -> tuple[dict[str, Any], dict[str, NodeConfig]]:
    """Returns (nodes_dict, configs_dict)."""
```

**Build CompiledWorkflow at the end**:

```python
start_node = _get_start_node(nodes, ir_dict)
return CompiledWorkflow(
    start_node=start_node,
    node_configs=configs,
    outputs=ir_dict.get("outputs", {}),
    resolved_defaults=resolved_defaults,
    env_param_names=env_param_names,
    template_resolution_mode=template_resolution_mode,
)
```

### 3B. Backward-compat alias with shim

```python
class _CompiledWorkflowShim:
    """Temporary shim so compile_ir_to_flow callers can still call .run(shared)."""
    def __init__(self, workflow: CompiledWorkflow,
                 metrics_collector=None, trace_collector=None, only_node=None):
        self._workflow = workflow
        self._metrics = metrics_collector
        self._trace = trace_collector
        self._only = only_node

    def run(self, shared: dict[str, Any]) -> str:
        from pflow.runtime.engine import WorkflowEngine
        # Seed resolved defaults (the old flow.run didn't need this because
        # initial_params override handled it — the shim must compensate)
        shared.update(self._workflow.resolved_defaults)
        engine = WorkflowEngine(
            metrics_collector=self._metrics,
            trace_collector=self._trace,
            only_node=self._only,
        )
        return engine.run(self._workflow, shared)

def compile_ir_to_flow(ir_json, registry, initial_params=None, metrics_collector=None,
                       trace_collector=None, only_node=None):
    """Deprecated. Use compile_workflow() + WorkflowEngine."""
    workflow = compile_workflow(ir_json, registry, initial_params)
    return _CompiledWorkflowShim(workflow, metrics_collector, trace_collector, only_node)
```

### 3C. Update `src/pflow/runtime/__init__.py` and `compilation/__init__.py`

`runtime/__init__.py`:
```python
from .compilation import CompilationError, compile_ir_to_flow, compile_workflow, import_node_class
from .engine import CompiledWorkflow, WorkflowEngine
```

`runtime/compilation/__init__.py`:
```python
from .compiler import CompilationError, compile_ir_to_flow, compile_workflow, inject_special_parameters
```

**Phase 3 Verification**: `make test` — all tests pass via the shim alias. New compilation produces correct `CompiledWorkflow`.

---

## Phase 4: Runner + WorkflowExecutor Updates

### 4A. Modify `src/pflow/execution/runner.py`

In `_compile_and_execute`:

```python
# BEFORE:
flow = compile_ir_to_flow(resolved.ir, registry=registry, initial_params=params,
                          metrics_collector=metrics_collector, trace_collector=trace_collector,
                          only_node=config.only_node)
action_result = flow.run(shared_store)

# AFTER:
from pflow.runtime import compile_workflow, WorkflowEngine

workflow = compile_workflow(resolved.ir, registry=registry, initial_params=params)

# Seed shared store with resolved defaults (from prepare_inputs)
# User-provided params are already in shared_store via _initialize_shared_store.
# resolved_defaults contains ONLY defaults for inputs not provided by the user,
# so this doesn't overwrite user values.
shared_store.update(workflow.resolved_defaults)
if workflow.env_param_names:
    params["__env_param_names__"] = list(workflow.env_param_names)

engine = WorkflowEngine(
    metrics_collector=metrics_collector,
    trace_collector=trace_collector,
    only_node=config.only_node,
)
action_result = engine.run(workflow, shared_store)
```

### 4B. Modify `src/pflow/runtime/workflow_executor.py` — Compile-Once

```python
class WorkflowExecutor(BaseNode):
    def __init__(self):
        super().__init__()
        # Compile-once cache — instance attributes, NOT class-level
        self._cached_workflow: Optional[CompiledWorkflow] = None
        self._cached_workflow_ir_id: Optional[int] = None

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        workflow_ir = prep_res["workflow_ir"]
        child_params = prep_res["child_params"]
        parent_shared = prep_res.get("parent_shared", {})

        # Compile-once: cache compiled workflow, reuse for subsequent batch items.
        # Compiling with first-item child_params is safe — initial_params no longer
        # gets baked into compiled nodes. prepare_inputs() runs once, captures
        # resolved_defaults. The compiled graph is structural and reusable.
        # For parallel batch: each thread's deep-copied WorkflowExecutor has its own
        # _cached_workflow (starts as None, compiles independently) — O(N) compiles.
        # Sequential batch gets the full O(1) compile-once benefit.
        ir_id = id(workflow_ir)
        if self._cached_workflow is None or self._cached_workflow_ir_id != ir_id:
            self._cached_workflow = self._compile_sub_workflow(workflow_ir, prep_res, child_params)
            self._cached_workflow_ir_id = ir_id

        # Create per-item child storage
        child_storage = self._create_child_storage(parent_shared, prep_res["storage_mode"], prep_res)

        # Seed: defaults first (from compile-time), then per-item values (override defaults)
        child_storage.update(self._cached_workflow.resolved_defaults)
        child_storage.update(child_params)

        # Create per-execution trace collector
        child_trace = self._create_child_trace(parent_shared, prep_res)

        # Execute with engine
        from pflow.runtime.engine import WorkflowEngine
        engine = WorkflowEngine(trace_collector=child_trace)

        self._child_trace_events = None  # Reset per execution
        try:
            result = engine.run(self._cached_workflow, child_storage)
            if child_trace and child_trace.events:
                self._child_trace_events = child_trace.events
            # ... handle success/error as current code does ...
        except Exception as e:
            if child_trace and child_trace.events:
                self._child_trace_events = child_trace.events
            # ... current error handling ...

    def _compile_sub_workflow(self, workflow_ir, prep_res, child_params):
        """Compile sub-workflow with first-item params (captures defaults)."""
        from pflow.runtime import compile_workflow
        registry = self.params.get("__registry__")
        if registry is not None and not isinstance(registry, Registry):
            registry = None

        # Ensure file references are resolved before compilation
        # (compile_workflow includes resolve_file_references)
        try:
            return compile_workflow(
                workflow_ir,
                registry=registry or Registry(),
                initial_params=dict(child_params),  # Copy — don't mutate caller's dict
            )
        except CompilationError as e:
            if not e.details:
                e.details = {}
            e.details["sub_workflow_path"] = str(prep_res.get("workflow_path", "<unknown>"))
            raise
        except Exception as e:
            raise CompilationError(
                f"Failed to compile sub-workflow: {e!s}",
                phase="sub_workflow_compilation",
                details={"sub_workflow_path": str(prep_res.get("workflow_path", "<unknown>"))},
            ) from e

    def _create_child_trace(self, parent_shared, prep_res):
        """Create child trace collector if parent has tracing."""
        parent_trace = parent_shared.get("_trace_collector")
        if not parent_trace:
            return None
        from pflow.runtime.workflow_trace import WorkflowTraceCollector
        child_trace = WorkflowTraceCollector(
            workflow_name=str(prep_res.get("workflow_path") or "sub-workflow")
        )
        child_trace.enable_llm_interception = False
        return child_trace
```

**Phase 4 Verification**: `make test` passes. Add a compile-once regression test: counter/mock on `compile_workflow` verifying it's called exactly once when `execute_batch` processes N items sequentially.

---

## Phase 5: PocketFlow Slim + Wrapper Removal

### 5A. Rewrite `src/pflow/pocketflow/__init__.py` (~35 lines)

```python
import warnings

class BaseNode:
    def __init__(self):
        self.params, self.successors = {}, {}

    def set_params(self, params):
        self.params = params

    def next(self, node, action="default"):
        if action in self.successors:
            warnings.warn(f"Overwriting successor for action '{action}'")
        self.successors[action] = node
        return node

    def prep(self, shared): pass
    def exec(self, prep_res): pass
    def post(self, shared, prep_res, exec_res): pass

    def _exec(self, prep_res):
        return self.exec(prep_res)

    def _run(self, shared):
        p = self.prep(shared)
        e = self._exec(p)
        return self.post(shared, p, e)

    def run(self, shared):
        if self.successors:
            warnings.warn("Node won't run successors. Use WorkflowEngine.")
        return self._run(shared)

    def __rshift__(self, other):
        return self.next(other)

    def __sub__(self, action):
        if isinstance(action, str):
            return _ConditionalTransition(self, action)
        raise TypeError("Action must be a string")

class _ConditionalTransition:
    def __init__(self, src, action):
        self.src, self.action = src, action
    def __rshift__(self, tgt):
        return self.src.next(tgt, self.action)

class Node(BaseNode):
    """BaseNode with retry. self.cur_retry is instance state and NOT thread-safe.
    Safe only because: (1) sequential batch does not parallelize,
    (2) parallel batch deep-copies the node per thread."""
    def __init__(self, max_retries=1, wait=0):
        super().__init__()
        self.max_retries, self.wait = max_retries, wait

    def exec_fallback(self, prep_res, exc):
        raise exc

    def _exec(self, prep_res):
        import time
        for self.cur_retry in range(self.max_retries):
            try:
                return self.exec(prep_res)
            except Exception as e:
                if self.cur_retry == self.max_retries - 1:
                    return self.exec_fallback(prep_res, e)
                if self.wait > 0:
                    time.sleep(self.wait)
```

**Removed**: `Flow`, `BatchFlow`, `BatchNode`, all async variants, `_orch()`, `copy.copy()`.

### 5B. Delete wrapper files

- `src/pflow/runtime/wrappers/instrumented_wrapper.py` (810 lines)
- `src/pflow/runtime/wrappers/template_wrapper.py` (710 lines)
- `src/pflow/runtime/wrappers/batch_node.py` (1,034 lines)
- `src/pflow/runtime/wrappers/namespaced_wrapper.py` (94 lines)
- `src/pflow/runtime/wrappers/__init__.py`
- `src/pflow/runtime/wrappers/CLAUDE.md`

Files already moved to `engine/` in Phase 1F: `namespaced_store.py`, `api_warning_detector.py`, `template_errors.py`, `error_context.py`.

### 5C. Remove wrapper imports from `compiler.py`

Delete 4 imports (the only production-code imports):
- `from ..wrappers.namespaced_wrapper import NamespacedNodeWrapper`
- `from ..wrappers.template_wrapper import TemplateAwareNodeWrapper`
- `from pflow.runtime.wrappers.batch_node import PflowBatchNode` (lazy)
- `from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper` (lazy)

### 5D. Delete `tests/test_pocketflow/` suite

9 files (~54 tests) testing `Flow`, `BatchFlow`, `BatchNode`, async variants — all removed classes. Delete the entire directory.

### 5E. Update `PFLOW_MODIFICATIONS.md`

Replace contents: the `_orch()` hack is gone because `Flow` is gone. PocketFlow is now BaseNode + Node only.

**Phase 5 Verification**: `make check` passes (lint, types). `make test` — see Phase 6.

---

## Phase 6: Test Updates

### Tests that MUST be rewritten (~283 tests)

These directly instantiate wrapper classes:

| File | Tests | New target |
|------|-------|------------|
| `test_runtime/test_batch_node.py` | 150 | Test `execute_batch()` in `engine/batch_executor.py`. NOTE: `test_special_keys_shared_across_items` tests LOAD-BEARING shallow-copy semantics — preserve this |
| `test_runtime/test_node_wrapper.py` | 21 | Test `resolve_templates()`. NOTE: `test_priority_initial_over_shared` tests REMOVED behavior — replace with test showing defaults flow via shared store |
| `test_runtime/test_node_wrapper_json_parsing.py` | 33 | Test `resolve_templates()` JSON auto-parse |
| `test_runtime/test_node_wrapper_json_errors.py` | 12 | Test `resolve_templates()` JSON errors |
| `test_runtime/test_node_wrapper_nested_resolution.py` | 8 | Test `resolve_templates()` nested resolution |
| `test_runtime/test_node_wrapper_stderr_context.py` | 2 | Test `resolve_templates()` stderr context |
| `test_runtime/test_node_wrapper_template_validation.py` | 45 | Test `resolve_templates()` strict/permissive. NOTE: `test_simple_template_initial_params_priority` tests REMOVED behavior |
| `test_runtime/test_node_wrapper_type_validation.py` | 18 | Test `validate_resolved_type()` |
| `test_runtime/test_template_wrapper_resolve.py` | 17 | Test `resolve_templates()` |
| `test_runtime/test_instrumented_wrapper.py` | 33 | Test engine `_execute_node()`. Copy tests → delete, not rewrite |
| `test_runtime/test_instrumented_wrapper_binary.py` | 10 | Test `detect_api_warning()` (already standalone, just update import) |
| `test_runtime/test_instrumented_wrapper_config.py` | 11 | Test `compute_node_config()` / `compute_config_hash()` |
| `test_runtime/test_trace_integration.py` | 8 | Test through REAL engine execution (not synthetic `record_trace` calls). These test handoff SEAMS — preserve as integration tests |
| `test_runtime/test_memoization_integration.py` | 10 | Test through engine execution, not internal methods |

### Tests that need UPDATING

| File | Tests | Change needed |
|------|-------|--------------|
| `test_runtime/test_compiler_template_wrapping.py` | 12 | Test `split_params()` instead of `_apply_template_wrapping()` |
| `test_runtime/test_compiler_batch.py` | 19 | Remove isinstance chain checks, test NodeConfig.batch_config |
| `test_runtime/test_checkpoint_tracking.py` | 7 | Test via engine execution. Don't hardcode config hashes |
| `test_runtime/test_cache_integration.py` | 13 | Use `compile_workflow` + engine (NOT manual wrapper chain construction) |
| `test_runtime/test_flow_construction.py` | 19 | Remove isinstance checks, test node_configs. `_wire_nodes` tests stay |
| `test_runtime/test_compiler_integration.py` | 26 | Remove 3 isinstance checks, rest should pass via shim |
| `test_runtime/test_compiler_basic.py` | varies | Remove `isinstance(x, Flow)` checks, update to `CompiledWorkflow` |
| `test_runtime/test_compiler_output_wrapping.py` | 5 | Remove `flow.run.__name__ == "run_with_hooks"` checks, test engine output resolution |
| `test_runtime/test_null_defaults.py` | 2 | 2 tests import TemplateAwareNodeWrapper → use `resolve_templates()` |
| `test_runtime/test_template_resolver_nested.py` | 1 | 1 test imports TemplateAwareNodeWrapper → use `resolve_templates()` |
| `test_runtime/test_namespacing.py` | 7 | Update import path: `pflow.runtime.engine.namespaced_store.NamespacedSharedStore` |
| `test_execution/test_api_warning_system.py` | 10 | Update import: `detect_api_warning` from `engine/` |
| `test_nodes/test_shell/test_shell_stdin.py` | 4 | Use `resolve_templates()` + `node.set_params()` |
| `test_nodes/test_shell/test_shell_sigpipe.py` | 1 | Same |
| `test_nodes/test_shell/test_stdin_type_adaptation.py` | 4 | Same |
| `test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` | 2 | Remove PflowBatchNode/NamespacedNodeWrapper imports |
| `test_runtime/test_batch_node_stderr_context.py` | 13 | Test extracted error_context functions + batch_executor |
| `test_runtime/test_batch_param_override.py` | 7 | Use `compile_workflow` + engine |

### Stale patch strings (silently test nothing if not fixed)

These mock `compile_ir_to_flow` in modules that switch to `compile_workflow`:

| File | Patches | Fix |
|------|---------|-----|
| `test_runtime/test_workflow_executor/test_workflow_executor.py` | 4 | `patch("pflow.runtime.workflow_executor.compile_workflow")` |
| `test_runtime/test_workflow_executor/test_workflow_name.py` | 2 | Same |
| `test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` | 8 | Same |
| `test_execution/test_runner.py` | 1 | `patch("pflow.runtime.compile_workflow")` |
| `test_execution/test_workflow_execution.py` | 1 | Same + mock `WorkflowEngine.run` instead of `flow.run` |
| `test_mcp/test_connection_pool.py` | 1 | Same |

### New tests to ADD

| Test | What it verifies |
|------|-----------------|
| Compile-once regression | Mock/counter on `compile_workflow`, verify called exactly once for N sequential batch items |
| `initial_params` removal | Verify defaults flow through `shared_store.update(resolved_defaults)`, NOT through `initial_params` override |
| Parallel batch trace correctness | Run parallel batch, verify each item's trace has CORRECT (not cross-contaminated) `last_resolutions` |

### Tests that should PASS as-is via the shim alias

All ~126 integration tests in `tests/test_integration/` and most `test_runtime/` tests that use `compile_ir_to_flow` + `flow.run(shared)`. The `_CompiledWorkflowShim` provides `.run()`.

**Phase 6 Verification**: `make test && make check` — everything passes.

---

## Phase 7: Documentation Updates

- `src/pflow/pocketflow/CLAUDE.md` — update: BaseNode + Node only, no Flow
- `src/pflow/runtime/CLAUDE.md` — update: engine replaces wrappers, new compilation pipeline
- `src/pflow/runtime/compilation/CLAUDE.md` — update: compiler produces `CompiledWorkflow`
- `src/pflow/execution/CLAUDE.md` — update: Runner uses `compile_workflow` + `WorkflowEngine`
- `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md` — document redesign rationale
- Root `CLAUDE.md` — update project structure, remove wrapper references
- Create `src/pflow/runtime/engine/CLAUDE.md` — document engine architecture
- `architecture/architecture.md` — update: "IR → CompiledWorkflow" not "IR → Flow"
- `architecture/pflow-pocketflow-integration-guide.md` — update: engine is the executor, not PocketFlow

---

## Implementation Order

1. **Phase 1**: New types + extracted functions (additive)
2. **Phase 2**: Engine (additive)
3. **Phase 3**: Compiler changes (produces CompiledWorkflow, shim alias)
4. **Phase 4**: Runner + WorkflowExecutor (uses engine, compile-once)
5. **Phase 5**: PocketFlow slim + wrapper deletion + test_pocketflow deletion
6. **Phase 6**: Test updates
7. **Phase 7**: Documentation

**Checkpoint after Phase 3**: `make test` — all tests pass via shim alias.

**Checkpoint after Phase 4**: `make test` — Runner and WorkflowExecutor use engine directly. `/code-review` recommended here (highest-risk phases complete).

**Checkpoint after Phase 6**: `make test && make check` — everything passes.

---

## Verification Checklist

- [ ] `make test` passes
- [ ] `make check` passes (lint, type checking)
- [ ] Compile-once: counter-based test verifies `compile_workflow` called once for N sequential batch items
- [ ] Sequential batch: zero deep copies
- [ ] Parallel batch: deep copy bare nodes only
- [ ] Shared store keys match contract (same keys, same values, same timing)
- [ ] Batch error handling: CompilationError propagation, all-fail abort, empty batch warning
- [ ] `--only` flag works (engine stops after target node, stores metadata)
- [ ] Output resolution works (declared outputs populated)
- [ ] Template strict/permissive modes work
- [ ] Memoization cache works (cross-run caching, WorkflowExecutor skipped)
- [ ] Trace capture works (node events, batch items with correct per-item resolutions, sub-workflow events)
- [ ] Progress callbacks work (node_start, node_complete, batch_progress)
- [ ] No wrapper files remain in `src/pflow/runtime/wrappers/`
- [ ] PocketFlow is ~35 lines (BaseNode + _ConditionalTransition + Node)
- [ ] `initial_params` is NOT used as runtime data override anywhere
- [ ] Parallel batch trace resolutions are NOT cross-contaminated

---

## Risk Mitigation

1. **Shim alias** (Phase 3B) returns `.run()`-compatible object — integration tests pass unchanged
2. **Extracted functions** (Phase 1) are testable independently before the engine uses them
3. **Single compilation callsite** (Task 138) means compiler changes have controlled blast radius
4. **Shared store contract preserved** means formatters/display code is unaffected
5. **Nodes unchanged** means all 28 production node implementations work as-is
6. **First-item compilation** for sub-workflows means `prepare_inputs()` runs normally — no structural_only split needed, defaults are correctly captured
