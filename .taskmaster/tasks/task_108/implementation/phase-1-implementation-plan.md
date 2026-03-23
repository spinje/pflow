# Phase 1: Trace Enrichment + Report Generator

## Context

**Problem**: When AI agents iterate on pflow workflows, they can't see what happened inside each node. The trace JSON exists but is too dense (500KB+), truncated, and agents never open it. The core need: see the rendered prompt an LLM received alongside its response, understand batch item results, and navigate complex nested workflows — without writing custom output code.

**Solution**: Enrich the trace format to capture per-node inputs/outputs in a tree structure (matching execution hierarchy), then build a report generator that converts traces into a navigable directory of markdown files — one file per node.

**Key design decisions from discussion**:
- Replace `shared_before`/`shared_after` (O(n²) full-store snapshots) with focused `node_output` + `template_resolutions` + `mutations`
- Tree-structured trace: batch items and sub-workflow nodes are nested, not flat
- Remove all value truncation (keep only internal key filtering and binary replacement)
- LLM interception stays for top-level; child collectors skip it (prompts captured via template_resolutions instead)
- Move trace save to `finally` block (survives Ctrl+C)
- `--report` flag generates markdown directory from trace

**Trace format**: 1.2.0 → 2.0.0 (breaking, but no external consumers — only ~17 tests + 2 deprecated scripts)

---

## Architecture Overview

### New Trace Event Structure

```json
{
  "node_id": "write-lyrics",
  "node_type": "LLMNode",
  "duration_ms": 5200,
  "success": true,
  "timestamp": "...",

  "node_params": {"prompt": "Write lyrics about ${concept.title}...", "model": "gemini-3-flash"},
  "template_resolutions": {
    "prompt": {
      "template": "Write lyrics about ${concept.title}...",
      "resolved": "Write lyrics about The Canopy Umbrella..."
    }
  },
  "node_output": {"response": "Verse 1: ...", "llm_usage": {...}},
  "mutations": {"added": ["write-lyrics"], "removed": [], "modified": []},

  "llm_call": {"model": "gemini-3-flash", "total_tokens": 3200, "cost_usd": 0.01},
  "llm_prompt": "Write lyrics about The Canopy Umbrella...",
  "llm_response": "Verse 1: ...",

  "error": null,

  "batch_items": [...],
  "sub_workflow_events": [...]
}
```

**Removed**: `shared_before`, `shared_after` (full store snapshots)
**Added**: `node_params`, `template_resolutions`, `node_output`, `batch_items`, `sub_workflow_events`
**Kept**: `mutations` (computed same way internally, just not stored from full snapshots), `llm_call`, `llm_prompt`, `llm_response`

### Data Flow

```
Execution
  → TemplateAwareNodeWrapper captures last_resolutions
  → InstrumentedNodeWrapper reads last_resolutions, captures node_output
  → WorkflowTraceCollector stores event (no full-store snapshot)
  → PflowBatchNode accumulates per-item events via shared list
  → WorkflowExecutor creates child collector, embeds child events
  → save_to_file() writes tree-structured JSON
  → Report generator reads JSON, writes .md directory
```

---

## File-by-File Changes

### 1. `src/pflow/runtime/wrappers/template_wrapper.py`

**Goal**: Store the template resolution mapping so InstrumentedNodeWrapper can read it.

**Add `last_resolutions` attribute**:

In `_run()` at line 520, after `resolved_params = {}` is initialized and the for-loop resolves each param (ending at line 581 `resolved_params[key] = resolved_value`):

After line 581 (after the for loop completes, before line 642 `original_params = ...`), add:
```python
# Store resolutions for trace capture (read by InstrumentedNodeWrapper)
self.last_resolutions = {
    key: {"template": self.template_params[key], "resolved": resolved_params[key]}
    for key in resolved_params
}
```

**IMPORTANT `__setattr__` gotcha**: The wrapper's `__setattr__` (line 676) routes attributes not in `wrapper_attrs` (line 687) to `self.inner_node`. The `wrapper_attrs` set only contains: `{"inner_node", "node_id", "initial_params", "template_params", "static_params"}`. You MUST add `"last_resolutions"` to this set at line 687, otherwise setting `self.last_resolutions` will set it on the inner node instead.

Also add initialization in `__init__` (after line 73): `self.last_resolutions = {}` — but this must be set BEFORE `self.inner_node` is assigned at line 66, OR use `object.__setattr__(self, "last_resolutions", {})`. The safest approach: add `"last_resolutions"` to `wrapper_attrs` at line 687.

For the early-return path (line 508-509 when no template_params): `last_resolutions` stays as `{}` from init — correct behavior.

### 2. `src/pflow/runtime/wrappers/instrumented_wrapper.py`

**Goal**: Replace `shared_before`/`shared_after` with focused fields. Read template_resolutions from wrapper chain. Capture node_output. Support tree structure.

#### 2a. New method: `_find_template_wrapper()`

Add after `_get_actual_node_class()` (after line 748):
```python
def _find_template_wrapper(self) -> Any:
    """Traverse wrapper chain to find TemplateAwareNodeWrapper."""
    current = self.inner_node
    while current:
        # Check by attribute presence (avoids import)
        if hasattr(current, "last_resolutions"):
            return current
        if hasattr(current, "inner_node"):
            current = current.inner_node
        elif hasattr(current, "_inner_node"):
            current = current._inner_node
        else:
            break
    return None
```

#### 2b. New method: `_find_batch_or_workflow_node()`

Add after `_find_template_wrapper()`:
```python
def _find_batch_or_workflow_node(self) -> tuple[str | None, Any]:
    """Traverse wrapper chain to find PflowBatchNode or WorkflowExecutor.
    Returns (type_name, node) or (None, None)."""
    current = self.inner_node
    while current:
        cls_name = type(current).__name__
        if cls_name == "PflowBatchNode":
            return ("batch", current)
        if cls_name == "WorkflowExecutor":
            return ("workflow", current)
        if hasattr(current, "inner_node"):
            current = current.inner_node
        elif hasattr(current, "_inner_node"):
            current = current._inner_node
        else:
            break
    return (None, None)
```

#### 2c. Modify `_run()` (lines 627-724)

**Remove full shared_before snapshot** at line 638. Replace:
```python
shared_before = dict(shared) if (self.trace or self.metrics) else None
```
With:
```python
shared_keys_before = set(shared.keys()) if (self.trace or self.metrics) else None
```

**Modify `_record_trace()` calls** at lines 703 and 718. Replace `shared_before, dict(shared)` with the new parameters (see 2d below).

At line 703 (success path), replace:
```python
self._record_trace(duration_ms, shared_before, dict(shared), success=trace_success)
```
With:
```python
self._record_trace(duration_ms, shared, shared_keys_before, success=trace_success)
```

At line 718 (error path), replace:
```python
self._record_trace(duration_ms, shared_before, dict(shared), success=False, error=str(e))
```
With:
```python
self._record_trace(duration_ms, shared, shared_keys_before, success=False, error=str(e))
```

#### 2d. Rewrite `_record_trace()` (lines 388-423)

New signature and implementation:
```python
def _record_trace(
    self,
    duration_ms: float,
    shared: dict[str, Any],
    shared_keys_before: set[str] | None,
    success: bool,
    error: str | None = None,
) -> None:
    if not self.trace:
        return

    actual_node_class = self._get_actual_node_class()

    # Get template resolutions from wrapper chain
    template_wrapper = self._find_template_wrapper()
    template_resolutions = template_wrapper.last_resolutions if template_wrapper else {}

    # Get node params (original, before resolution)
    node_params = self._get_node_params() or {}

    # Get node output (just this node's namespace, not full store)
    node_output = shared.get(self.node_id)
    if isinstance(node_output, dict):
        node_output = dict(node_output)  # shallow copy
    elif node_output is not None:
        node_output = {"value": node_output}
    else:
        node_output = {}

    # Compute mutations from key sets
    shared_keys_after = set(shared.keys())
    mutations = {
        "added": sorted(shared_keys_after - shared_keys_before) if shared_keys_before is not None else [],
        "removed": sorted(shared_keys_before - shared_keys_after) if shared_keys_before is not None else [],
        "modified": [],  # Can't detect value changes without full snapshot — acceptable tradeoff
    }

    # Check for nested trace data (batch items, sub-workflow events)
    batch_or_wf_type, batch_or_wf_node = self._find_batch_or_workflow_node()
    batch_items = None
    sub_workflow_events = None
    if batch_or_wf_type == "batch" and hasattr(batch_or_wf_node, "_trace_items"):
        batch_items = batch_or_wf_node._trace_items
    elif batch_or_wf_type == "workflow" and hasattr(batch_or_wf_node, "_child_trace_events"):
        sub_workflow_events = batch_or_wf_node._child_trace_events

    self.trace.record_node_execution(
        node_id=self.node_id,
        node_type=actual_node_class.__name__,
        duration_ms=duration_ms,
        success=success,
        error=error,
        node_params=node_params,
        template_resolutions=template_resolutions,
        node_output=node_output,
        mutations=mutations,
        batch_items=batch_items,
        sub_workflow_events=sub_workflow_events,
    )
```

**Note on mutations**: We lose `modified` detection (which required comparing values in before/after snapshots). This is an acceptable tradeoff — the report cares about what each node produced (`node_output`), not which existing keys it changed. `added` and `removed` are still computed from key set difference.

### 3. `src/pflow/runtime/workflow_trace.py`

**Goal**: New trace format 2.0.0. Remove truncation. New `record_node_execution` signature. Simplified `_filter_shared` (now just for internal key hygiene on `node_output`).

#### 3a. Update constants (lines 15-24)

Remove truncation constants (lines 15-21). Change format version (line 24):
```python
TRACE_FORMAT_VERSION = "2.0.0"
```

#### 3b. Update `record_node_execution()` signature (lines 55-90)

New signature:
```python
def record_node_execution(
    self,
    node_id: str,
    node_type: str,
    duration_ms: float,
    success: bool,
    error: Optional[str] = None,
    node_params: Optional[dict[str, Any]] = None,
    template_resolutions: Optional[dict[str, Any]] = None,
    node_output: Optional[dict[str, Any]] = None,
    mutations: Optional[dict[str, list[str]]] = None,
    batch_items: Optional[list[dict[str, Any]]] = None,
    sub_workflow_events: Optional[list[dict[str, Any]]] = None,
) -> None:
```

Build event dict with new fields:
```python
event = {
    "node_id": node_id,
    "node_type": node_type,
    "duration_ms": round(duration_ms, 2),
    "success": success,
    "timestamp": datetime.now().isoformat(),
}
if error:
    event["error"] = error
if node_params:
    event["node_params"] = self._sanitize_for_json(node_params)
if template_resolutions:
    event["template_resolutions"] = self._sanitize_for_json(template_resolutions)
if node_output:
    event["node_output"] = self._sanitize_for_json(node_output)
if mutations:
    event["mutations"] = mutations
if batch_items:
    event["batch_items"] = batch_items
if sub_workflow_events:
    event["sub_workflow_events"] = sub_workflow_events

# Add LLM data (prompt/response/usage) — keep existing _add_llm_data logic
# but read from node_output instead of shared_after
self._add_llm_data(event, node_id, node_output or {})

self.events.append(event)
```

#### 3c. Replace `_filter_shared()` with `_sanitize_for_json()`

Remove `_filter_shared()` (lines 286-329) and replace with:
```python
def _sanitize_for_json(self, data: Any) -> Any:
    """Make data JSON-serializable. No truncation — just hygiene."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Skip internal keys
            if key.startswith("__") and key not in ("__llm_calls__", "__metrics__"):
                continue
            if key in ("_trace_collector", "_debug_context"):
                continue
            result[key] = self._sanitize_for_json(value)
        return result
    elif isinstance(data, bytes):
        return f"<binary data: {len(data)} bytes>"
    elif isinstance(data, list):
        return [self._sanitize_for_json(item) for item in data]
    else:
        return data
```

#### 3d. Remove `_build_base_event()`, `_calculate_mutations()`

These are no longer needed — event building is inline in `record_node_execution()`, mutations are computed in `InstrumentedNodeWrapper._record_trace()`.

#### 3e. Update `_add_llm_data()` (lines 125-151)

Change the `shared_after` parameter name to `node_output` and update the lookup logic. The `_extract_llm_usage()` and `_extract_llm_response()` methods should look in `node_output` directly (no namespaced lookup needed since `node_output` IS the namespace):

```python
def _add_llm_data(self, event: dict, node_id: str, node_output: dict[str, Any]) -> None:
    # Look for llm_usage directly in node_output
    llm_usage = node_output.get("llm_usage") if isinstance(node_output, dict) else None
    if isinstance(llm_usage, dict):
        event["llm_call"] = llm_usage

    # Look for prompt via interception first, then node_output
    prompt = self.llm_prompts.get(node_id)
    if not prompt and isinstance(node_output, dict):
        prompt = node_output.get("prompt")
    if isinstance(prompt, str):
        event["llm_prompt"] = prompt  # No truncation

    # Look for response in node_output
    response = node_output.get("response") if isinstance(node_output, dict) else None
    if isinstance(response, str):
        event["llm_response"] = response  # No truncation
```

Remove `_add_truncated_field()`, `_find_llm_prompt()`, `_find_prompt_in_llm_calls()`, `_find_prompt_in_shared_before()`, `_extract_llm_usage()`, `_extract_llm_response()` — their logic is consolidated above.

#### 3f. Update `save_to_file()` (lines 388-470)

Minor: the `nodes` field stays as `self.events` (which now contains tree-structured events). No change to file-writing logic except removing the `llm_calls` parameter and computing `llm_summary` from events only.

Update signature: `def save_to_file(self) -> Path:` (remove `llm_calls` param).

For `llm_summary`, scan all events recursively (including nested `batch_items` and `sub_workflow_events`) to count LLM calls. Add helper:

```python
def _collect_llm_summary(self, events: list[dict]) -> dict[str, Any]:
    """Recursively collect LLM call data from tree-structured events."""
    total_calls = 0
    total_tokens = 0
    models = set()
    for event in events:
        if "llm_call" in event:
            total_calls += 1
            total_tokens += event["llm_call"].get("total_tokens", 0)
            model = event["llm_call"].get("model")
            if model:
                models.add(model)
        # Recurse into batch items
        for item in event.get("batch_items", []):
            sub = self._collect_llm_summary(item.get("events", []))
            total_calls += sub.get("total_calls", 0)
            total_tokens += sub.get("total_tokens", 0)
            models.update(sub.get("models_used", []))
        # Recurse into sub-workflow events
        sub_events = event.get("sub_workflow_events", [])
        if sub_events:
            sub = self._collect_llm_summary(sub_events)
            total_calls += sub.get("total_calls", 0)
            total_tokens += sub.get("total_tokens", 0)
            models.update(sub.get("models_used", []))
    return {"total_calls": total_calls, "total_tokens": total_tokens, "models_used": sorted(models)}
```

#### 3g. Add `enable_llm_interception` flag

Add to `__init__` (after line 52):
```python
self.enable_llm_interception = True  # Set False for child collectors
```

Modify `setup_llm_interception()` (line 472) to check this flag:
```python
def setup_llm_interception(self, node_id: str) -> None:
    if not self.enable_llm_interception:
        return
    # ... rest of existing code
```

#### 3h. Fix `_current_node` threading bug

In `setup_llm_interception()`, use `threading.local()` for `_current_node`. Add class variable:
```python
_thread_local: ClassVar[threading.local] = threading.local()
```

Replace `self._current_node = node_id` (line 481) with:
```python
WorkflowTraceCollector._thread_local.current_node = node_id
```

In the `intercept_prompt` closure (line 503-507), replace `collector._current_node` with:
```python
current_node = getattr(WorkflowTraceCollector._thread_local, 'current_node', None)
```

### 4. `src/pflow/runtime/wrappers/batch_node.py`

**Goal**: Capture per-item trace events using the `__llm_calls__` shared-list pattern.

#### 4a. Add trace accumulator in `prep()` (after line 252)

After the existing `__llm_calls__` initialization (line 251-252), add:
```python
# Initialize batch trace accumulator (same pattern as __llm_calls__)
if "_batch_trace" not in shared:
    shared["_batch_trace"] = {}
shared["_batch_trace"][self.node_id] = []
```

Note: Using `_batch_trace` (single underscore) instead of `__batch_trace__` to avoid the dunder key filter in `_sanitize_for_json()`.

#### 4b. Add per-item trace capture in `_exec_single()` (after line 402)

After `self._capture_item_llm_usage(item_shared, idx)` (line 402), add:
```python
self._capture_item_trace(item_shared, idx, item, duration_ms=None, error=None)
```

Then at the return points — after computing `duration_ms` (line 433), before returning on both success (line 438) and error (line 436), call:
```python
# Before the return statements, capture trace with timing
self._capture_item_trace(item_shared, idx, item, duration_ms, error_info)
```

Actually, simpler: capture ONCE before the return, after `duration_ms` is computed. Add before line 434 (before the error/success branching):

```python
self._capture_item_trace(item_shared, idx, item, duration_ms, error_info if error_info else None)
```

Remove the earlier call after line 402 (that one didn't have duration_ms yet).

Similarly update `_exec_single_with_node()` — add the same call before the return points (before line 524).

#### 4c. Add `_capture_item_trace()` method (new, after `_capture_item_llm_usage` at line 370)

```python
def _capture_item_trace(
    self, item_shared: dict[str, Any], idx: int, item: Any,
    duration_ms: float | None, error: dict[str, Any] | None,
) -> None:
    """Capture per-item trace event, following __llm_calls__ pattern."""
    trace_list = self._shared.get("_batch_trace", {}).get(self.node_id)
    if trace_list is None:
        return

    # Build per-item event
    item_event: dict[str, Any] = {
        "index": idx,
        "item": item,
        "success": error is None,
        "duration_ms": round(duration_ms, 2) if duration_ms else 0,
    }
    if error:
        item_event["error"] = error.get("error", str(error))

    # Capture item's node output
    node_output = item_shared.get(self.node_id)
    if isinstance(node_output, dict):
        item_event["node_output"] = dict(node_output)

    # Capture template resolutions from the inner node chain
    # The deep-copied thread_node is still alive at this point
    current = self.inner_node  # or thread_node for parallel path
    while current:
        if hasattr(current, "last_resolutions") and current.last_resolutions:
            item_event["template_resolutions"] = current.last_resolutions
            break
        if hasattr(current, "inner_node"):
            current = current.inner_node
        elif hasattr(current, "_inner_node"):
            current = current._inner_node
        else:
            break

    # Capture child sub-workflow events if inner node is WorkflowExecutor
    current = self.inner_node
    while current:
        if hasattr(current, "_child_trace_events") and current._child_trace_events:
            item_event["events"] = current._child_trace_events
            break
        if hasattr(current, "inner_node"):
            current = current.inner_node
        elif hasattr(current, "_inner_node"):
            current = current._inner_node
        else:
            break

    # LLM data from item output
    if isinstance(node_output, dict):
        llm_usage = node_output.get("llm_usage")
        if isinstance(llm_usage, dict):
            item_event["llm_call"] = llm_usage
        response = node_output.get("response")
        if isinstance(response, str):
            item_event["llm_response"] = response
        prompt = node_output.get("prompt")
        if isinstance(prompt, str):
            item_event["llm_prompt"] = prompt

    trace_list.append(item_event)  # GIL-protected for parallel
```

**For the parallel path** (`_exec_single_with_node`): The deep-copied `thread_node` is still alive when this runs. But `self.inner_node` is the ORIGINAL (not the copy). We need to traverse `thread_node` instead. Modify `_exec_single_with_node()` to pass the `thread_node` reference, or better: add a `node` parameter to `_capture_item_trace`:

```python
def _capture_item_trace(
    self, item_shared: dict[str, Any], idx: int, item: Any,
    duration_ms: float | None, error: dict[str, Any] | None,
    node_chain: Any = None,  # For parallel: the deep-copied chain
) -> None:
```

And use `node_chain or self.inner_node` for traversal.

In `_exec_single()`: call with `node_chain=self.inner_node`
In `_exec_single_with_node()`: call with `node_chain=thread_node`

Wait — `_exec_single_with_node` doesn't have `thread_node` in scope. Looking at the code: `thread_node` is a parameter of `_exec_single_with_node(self, idx, item, item_shared, thread_node)` at line 464. So it IS available.

#### 4d. Make trace items available to InstrumentedNodeWrapper

In `post()` (after line 868 where `shared[self.node_id]` is written), add:
```python
# Store batch trace items for InstrumentedNodeWrapper to read
batch_trace = shared.get("_batch_trace", {}).get(self.node_id, [])
if batch_trace:
    self._trace_items = batch_trace
```

The `_trace_items` attribute is read by `InstrumentedNodeWrapper._record_trace()` via `_find_batch_or_workflow_node()`.

### 5. `src/pflow/runtime/workflow_executor.py`

**Goal**: Propagate trace collector to child workflows, create child collectors, store child events.

#### 5a. Add `_trace_collector` to `_PROPAGATED_KEYS` (line 67-73)

```python
_PROPAGATED_KEYS = (
    "__registry__",
    "__llm_calls__",
    "__progress_callback__",
    "__mcp_pool__",
    "__warnings__",
    "_trace_collector",  # NEW: for child workflow trace propagation
)
```

#### 5b. Modify `exec()` (lines 107-163)

After getting `parent_shared` from `prep_res` (line ~109 area), add trace collector creation:

```python
# Create child trace collector for sub-workflow visibility
parent_trace = prep_res["parent_shared"].get("_trace_collector")
child_trace = None
if parent_trace:
    from pflow.runtime.workflow_trace import WorkflowTraceCollector
    child_trace = WorkflowTraceCollector(
        workflow_name=str(prep_res.get("workflow_path", "sub-workflow"))
    )
    child_trace.enable_llm_interception = False  # Prompts captured via template_resolutions
```

Modify the `compile_ir_to_flow()` call (lines 128-133) to pass the child collector:
```python
sub_flow = compile_ir_to_flow(
    workflow_ir,
    registry=registry,
    initial_params=child_params,
    validate=True,
    trace_collector=child_trace,  # NEW
)
```

After `sub_flow.run(child_storage)` completes (around line 141), store child events:
```python
# Store child trace events for parent InstrumentedNodeWrapper to embed
if child_trace and child_trace.events:
    self._child_trace_events = child_trace.events
```

Also initialize in `__init__` or at class level: `_child_trace_events = None`

#### 5c. Trace collector already in shared store — NO additional injection needed

`executor_service.py:99-102` ALREADY injects `_trace_collector` into the shared store:
```python
if trace_collector:
    shared_store["_trace_collector"] = trace_collector
```
Adding `"_trace_collector"` to `_PROPAGATED_KEYS` (step 5a) is the ONLY change needed for propagation to work.

### 6. `src/pflow/runtime/compilation/compiler.py`

**No changes needed** — `compile_ir_to_flow()` already accepts `trace_collector` parameter and passes it through to `InstrumentedNodeWrapper`. The child collector created in `WorkflowExecutor.exec()` flows through the same path.

### ~~8. `src/pflow/execution/executor_service.py`~~ — NO CHANGES NEEDED

Already injects `_trace_collector` at lines 99-102. Remove from files modified list.

### 7. `src/pflow/cli/main.py`

**Goal**: Add `--report` flag, move trace save to `finally`, store trace collector in shared store.

#### 7a. Add `--report` flag

Add `@click.option` between lines 1461-1462 (after `--no-trace`, before `--validate-only`):
```python
@click.option("--report", "report_path", default=None, is_flag=False, flag_value="auto",
              help="Generate execution report (directory of .md files). Optionally specify output path.")
```

Add `report_path` parameter to `workflow_command` function signature (line 1464).

#### 7b. Store in context

In `_initialize_context()` (around line 874), add:
```python
ctx.obj["report"] = report_path
```

#### 7c. ~~Store trace collector in shared store~~ — ALREADY DONE

`executor_service.py:99-102` already handles this. No changes needed in main.py for this.

#### 7c (actual). Handle `--report` + `--no-trace` interaction

In `_validate_workflow_flags()` or early in the execution path, add:
```python
if ctx.obj.get("report") and not ctx.obj.get("trace"):
    click.echo("cli: --report requires tracing, enabling trace", err=True)
    ctx.obj["trace"] = True
```

#### 7d. Move trace save to `finally` block

Remove trace save from the 4 handler functions (lines 218, 247, 294, 487). Consolidate into the `finally` block.

Add a `_trace_saved` flag to prevent double-save. In `execute_json_workflow()`:

Before the try block (after line 761 where `workflow_trace` is created), add:
```python
trace_saved = False
shared_storage_ref = None  # Will be set if execution starts
```

In the try block, after `execute_workflow()` returns the result (line 780), capture a reference:
```python
shared_storage_ref = result.shared_after
```

Replace the `finally` block (lines 828-829) with:
```python
finally:
    # Save trace (survives Ctrl+C — SystemExit triggers finally but not except Exception)
    if workflow_trace and not trace_saved:
        trace_file = workflow_trace.save_to_file()
        if trace_file:
            _echo_trace(ctx, f"📊 Workflow trace saved: {trace_file}")
            # Generate report if requested
            report_path = ctx.obj.get("report")
            if report_path and trace_file:
                from pflow.core.trace_report import generate_report
                report_dir = generate_report(trace_file, report_path)
                if report_dir:
                    _echo_trace(ctx, f"📋 Execution report: {report_dir}")
        trace_saved = True
    _cleanup_workflow_resources(workflow_trace, stdin_data, verbose)
```

In the existing handlers (`_handle_workflow_success`, `_handle_workflow_error`, `_handle_workflow_exception`, `_handle_compilation_error`), remove the `workflow_trace.save_to_file()` calls and instead set `trace_saved = True` if they save (or just let the finally handle it).

Actually, simpler: just remove ALL trace saves from the handlers and let `finally` handle it exclusively. The `trace_saved` flag prevents double-save. Set it in `finally` after saving. Since `finally` always runs (even after handlers), this works cleanly.

But there's a subtlety: the handlers call `ctx.exit(1)` which raises `SystemExit`. This triggers `finally`. So the flow is: handler saves trace → calls ctx.exit(1) → finally runs → would save again. With the guard flag, this is fine IF we set `trace_saved = True` in each handler... but we're removing the saves from handlers. So just let finally do it all.

**One complication**: `_handle_workflow_success` currently calls `save_to_file(llm_calls=shared_storage.get("__llm_calls__"))`. Keep the `llm_calls` parameter as an **optional fallback** — when provided, use it for `llm_summary` (authoritative, includes sub-workflow calls via `__llm_calls__` propagation). When not provided, fall back to recursive event scanning. This allows incremental implementation.

In the `finally` block, pass `llm_calls` if `shared_storage_ref` is available:
```python
if workflow_trace and not trace_saved:
    llm_calls = shared_storage_ref.get("__llm_calls__") if shared_storage_ref else None
    trace_file = workflow_trace.save_to_file(llm_calls=llm_calls)
```

### 8. UPDATE FILE: `src/pflow/core/trace_report.py`

**This file already exists with the skeleton code.** Update it to handle format version checking and improve error handling.

```python
"""Generate execution report from trace files.

Reads a tree-structured trace JSON and produces a navigable directory
of markdown files — one file per node, with summaries at each level.
"""

from pathlib import Path
import json
from typing import Any


def generate_report(trace_path: str | Path, output_path: str | None = None) -> Path | None:
    """Generate report directory from a trace file.

    Args:
        trace_path: Path to the trace JSON file
        output_path: Output directory. "auto" or None = ~/.pflow/reports/{name}/

    Returns:
        Path to the report directory, or None on error
    """
    trace_path = Path(trace_path)
    if not trace_path.exists():
        return None

    with open(trace_path) as f:
        trace = json.load(f)

    # Determine output directory
    if output_path is None or output_path == "auto":
        name = trace.get("workflow_name", "workflow")
        report_dir = Path.home() / ".pflow" / "reports" / name
    else:
        report_dir = Path(output_path)

    report_dir.mkdir(parents=True, exist_ok=True)

    # Generate summary.md
    summary = _build_summary(trace)
    (report_dir / "summary.md").write_text(summary)

    # Generate per-node files
    events = trace.get("nodes", [])
    _write_node_files(events, report_dir, node_index=1)

    return report_dir


def _write_node_files(events: list[dict], parent_dir: Path, node_index: int) -> int:
    """Recursively write node files. Returns next available index."""
    idx = node_index
    for event in events:
        node_id = event.get("node_id", f"node-{idx}")
        prefix = f"{idx:02d}"

        batch_items = event.get("batch_items")
        sub_events = event.get("sub_workflow_events")

        if batch_items or sub_events:
            # This is a container node — create a directory
            node_dir = parent_dir / f"{prefix}-{node_id}"
            node_dir.mkdir(exist_ok=True)

            # Write container summary
            (node_dir / "summary.md").write_text(_build_node_summary(event))

            if batch_items:
                for item in batch_items:
                    item_idx = item.get("index", 0)
                    item_events = item.get("events", [])
                    if item_events:
                        # Sub-workflow batch item — create item directory
                        item_dir = node_dir / f"item-{item_idx}"
                        item_dir.mkdir(exist_ok=True)
                        (item_dir / "summary.md").write_text(_build_batch_item_summary(item))
                        _write_node_files(item_events, item_dir, node_index=1)
                    else:
                        # Simple batch item — single file
                        (node_dir / f"item-{item_idx}.md").write_text(_build_batch_item_file(item, event))

            if sub_events:
                _write_node_files(sub_events, node_dir, node_index=1)
        else:
            # Leaf node — single file
            (parent_dir / f"{prefix}-{node_id}.md").write_text(_build_node_file(event))

        idx += 1
    return idx


def _build_summary(trace: dict) -> str:
    """Build top-level summary.md content."""
    lines = [f"# Execution Report: {trace.get('workflow_name', 'workflow')}", ""]
    lines.append(f"- Status: {trace.get('final_status', 'unknown')}")
    lines.append(f"- Duration: {trace.get('duration_ms', 0) / 1000:.1f}s")
    lines.append(f"- Nodes: {trace.get('nodes_executed', 0)}")

    llm = trace.get("llm_summary")
    if llm:
        lines.append(f"- LLM calls: {llm.get('total_calls', 0)}")
        lines.append(f"- Tokens: {llm.get('total_tokens', 0):,}")
        lines.append(f"- Models: {', '.join(llm.get('models_used', []))}")

    lines.append(f"- Generated: {trace.get('end_time', '')}")
    lines.append("")

    # Pipeline table
    lines.append("## Pipeline")
    lines.append("")
    lines.append("| # | Node | Type | Time | Status |")
    lines.append("|---|------|------|------|--------|")
    for i, event in enumerate(trace.get("nodes", []), 1):
        node_id = event.get("node_id", "?")
        node_type = event.get("node_type", "?")
        duration = event.get("duration_ms", 0)
        status = "ok" if event.get("success") else "FAILED"
        lines.append(f"| {i} | {node_id} | {node_type} | {duration:.0f}ms | {status} |")

    lines.append("")
    lines.append(f"*Full trace: {trace.get('_source_path', 'N/A')}*")
    return "\n".join(lines)


def _build_node_file(event: dict) -> str:
    """Build a single node's markdown file."""
    node_id = event.get("node_id", "unknown")
    node_type = event.get("node_type", "unknown")
    lines = [f"# {node_id}", ""]

    # Metadata
    lines.append(f"- Type: {node_type}")
    lines.append(f"- Time: {event.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if event.get('success') else 'failed'}")

    llm_call = event.get("llm_call")
    if llm_call:
        lines.append(f"- Model: {llm_call.get('model', '?')}")
        tokens_in = llm_call.get("input_tokens", llm_call.get("prompt_tokens", 0))
        tokens_out = llm_call.get("output_tokens", llm_call.get("completion_tokens", 0))
        lines.append(f"- Tokens: {tokens_in:,} in / {tokens_out:,} out")
        cost = llm_call.get("cost_usd")
        if cost:
            lines.append(f"- Cost: ${cost:.4f}")

    error = event.get("error")
    if error:
        lines.append(f"- Error: {error}")

    lines.append("")

    # Template resolutions — show rendered prompt/command
    resolutions = event.get("template_resolutions", {})
    if "prompt" in resolutions:
        lines.append("## Prompt")
        lines.append("")
        lines.append(resolutions["prompt"].get("resolved", ""))
        lines.append("")
    elif event.get("llm_prompt"):
        lines.append("## Prompt")
        lines.append("")
        lines.append(event["llm_prompt"])
        lines.append("")

    if "command" in resolutions:
        lines.append("## Command")
        lines.append("")
        lines.append(f"```bash\n{resolutions['command'].get('resolved', '')}\n```")
        lines.append("")

    # Response / Output
    if event.get("llm_response"):
        lines.append("## Response")
        lines.append("")
        lines.append(event["llm_response"])
        lines.append("")
    elif event.get("node_output"):
        output = event["node_output"]
        # Show stdout/stderr for shell nodes
        if "stdout" in output:
            lines.append("## stdout")
            lines.append("")
            lines.append(f"```\n{output['stdout']}\n```")
            lines.append("")
        if "stderr" in output:
            lines.append("## stderr")
            lines.append("")
            lines.append(f"```\n{output['stderr']}\n```")
            lines.append("")
        if "result" in output:
            lines.append("## Result")
            lines.append("")
            result = output["result"]
            if isinstance(result, (dict, list)):
                lines.append(f"```json\n{json.dumps(result, indent=2, default=str)}\n```")
            else:
                lines.append(str(result))
            lines.append("")

    return "\n".join(lines)


def _build_node_summary(event: dict) -> str:
    """Build summary for a container node (batch or sub-workflow)."""
    node_id = event.get("node_id", "unknown")
    lines = [f"# {node_id}", ""]
    lines.append(f"- Type: {event.get('node_type', '?')}")
    lines.append(f"- Time: {event.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if event.get('success') else 'failed'}")

    batch_items = event.get("batch_items", [])
    if batch_items:
        succeeded = sum(1 for i in batch_items if i.get("success"))
        lines.append(f"- Items: {len(batch_items)} ({succeeded}/{len(batch_items)} succeeded)")
        lines.append("")
        lines.append("## Items")
        lines.append("")
        lines.append("| # | Time | Status |")
        lines.append("|---|------|--------|")
        for item in batch_items:
            idx = item.get("index", "?")
            dur = item.get("duration_ms", 0)
            status = "ok" if item.get("success") else "FAILED"
            lines.append(f"| {idx} | {dur:.0f}ms | {status} |")

    return "\n".join(lines)


def _build_batch_item_file(item: dict, parent_event: dict) -> str:
    """Build file for a simple batch item (no sub-workflow)."""
    idx = item.get("index", "?")
    lines = [f"# {parent_event.get('node_id', '?')} — Item {idx}", ""]
    lines.append(f"- Time: {item.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")

    llm_call = item.get("llm_call")
    if llm_call:
        lines.append(f"- Model: {llm_call.get('model', '?')}")
        cost = llm_call.get("cost_usd")
        if cost:
            lines.append(f"- Cost: ${cost:.4f}")

    error = item.get("error")
    if error:
        lines.append(f"- Error: {error}")
    lines.append("")

    # Show rendered prompt if available
    resolutions = item.get("template_resolutions", {})
    if "prompt" in resolutions:
        lines.append("## Prompt")
        lines.append("")
        lines.append(resolutions["prompt"].get("resolved", ""))
        lines.append("")
    elif item.get("llm_prompt"):
        lines.append("## Prompt")
        lines.append("")
        lines.append(item["llm_prompt"])
        lines.append("")

    if item.get("llm_response"):
        lines.append("## Response")
        lines.append("")
        lines.append(item["llm_response"])
        lines.append("")

    node_output = item.get("node_output", {})
    if node_output and not item.get("llm_response"):
        lines.append("## Output")
        lines.append("")
        lines.append(f"```json\n{json.dumps(node_output, indent=2, default=str)}\n```")
        lines.append("")

    return "\n".join(lines)


def _build_batch_item_summary(item: dict) -> str:
    """Build summary for a batch item that contains sub-workflow events."""
    idx = item.get("index", "?")
    lines = [f"# Item {idx}", ""]
    lines.append(f"- Time: {item.get('duration_ms', 0):.0f}ms")
    lines.append(f"- Status: {'success' if item.get('success') else 'failed'}")
    lines.append("")
    return "\n".join(lines)
```

### 9. `src/pflow/cli/commands/trace.py` (ALREADY EXISTS — update if needed)

**This file and the `trace` command group already exist**, including `pflow trace report` with auto-detect latest trace. The routing in `main_wrapper.py` already handles the `trace` subcommand. May need minor updates to match the new trace format:

```python
"""Trace report command — generate report from existing trace files."""
import click
from pathlib import Path


@click.command("report")
@click.argument("trace_path", required=False, default=None)
@click.option("--output", "-o", "output_path", default=None, help="Output directory")
def trace_report(trace_path: str | None, output_path: str | None) -> None:
    """Generate execution report from a trace file.

    If no trace path given, uses the most recent trace.
    """
    from pflow.core.trace_report import generate_report

    if trace_path is None:
        # Auto-detect latest trace
        debug_dir = Path.home() / ".pflow" / "debug"
        if not debug_dir.exists():
            click.echo("No trace files found in ~/.pflow/debug/", err=True)
            raise SystemExit(1)
        traces = sorted(debug_dir.glob("workflow-trace-*.json"), key=lambda p: p.stat().st_mtime)
        if not traces:
            click.echo("No trace files found in ~/.pflow/debug/", err=True)
            raise SystemExit(1)
        trace_path = str(traces[-1])
        click.echo(f"Using latest trace: {trace_path}", err=True)

    report_dir = generate_report(trace_path, output_path or "auto")
    if report_dir:
        click.echo(f"Report generated: {report_dir}", err=True)
    else:
        click.echo("Failed to generate report", err=True)
        raise SystemExit(1)
```

Register in `src/pflow/cli/main_wrapper.py` — add `"trace"` to the subcommand routes dict, pointing to a new trace command group. Or add as a subcommand of an existing group.

---

## Test Updates

### Tests to modify (17 tests across 4 files)

#### `tests/test_runtime/test_workflow_trace.py`

Update `record_node_execution()` calls to use new signature (remove `shared_before`/`shared_after`, add `node_params`/`template_resolutions`/`node_output`/`mutations`).

**Tests asserting on `shared_before`/`shared_after`**: Replace with assertions on `node_output` and `template_resolutions`.

**Tests for `_filter_shared` (truncation)**: Replace with tests for `_sanitize_for_json` (key hygiene only, no truncation).

**Tests for `_add_truncated_field`**: Remove (no truncation).

**Tests for `save_to_file`**: Update to check new format_version (2.0.0) and new event structure.

#### `tests/test_integration/test_metrics_integration.py`

Update `test_trace_file_saved_without_flag`: Replace `"shared_before" in event` / `"shared_after" in event` with checks for new fields (`"node_output"`, etc.).

#### `tests/test_runtime/test_instrumented_wrapper.py`

Update `test_trace_recorded_on_error` and `test_trace_collector_integration`: Change expected kwargs in `trace.record_node_execution` mock assertions.

#### `tests/test_runtime/test_batch_node.py`

Update `test_batch_metadata_captured_in_trace`: Change to use new trace event structure.

### New tests to write

1. **Template resolution capture**: Test that `TemplateAwareNodeWrapper.last_resolutions` is populated correctly after `_run()`.
2. **Per-batch-item trace events**: Test that `_batch_trace` accumulates events for each item.
3. **Sub-workflow trace propagation**: Test that child collector events are embedded in parent events.
4. **Report generator**: Test `generate_report()` produces correct directory structure and file contents.
5. **`_sanitize_for_json`**: Test internal key filtering and binary replacement (no truncation).
6. **`_collect_llm_summary`**: Test recursive LLM call counting across tree structure.
7. **Trace save in finally**: Test that SIGINT (Ctrl+C) still produces a trace file.

---

## Verification

1. **Run `make check`** — all linting and type checks pass
2. **Run `make test`** — all tests pass (updated + new)
3. **Manual test with a simple workflow**:
   ```bash
   uv run pflow examples/hello-world.pflow.md --report
   # Check ~/.pflow/reports/hello-world/ for summary.md and node files
   ```
4. **Manual test with a batch workflow** (if available in examples):
   ```bash
   uv run pflow examples/batch-example.pflow.md --report
   # Check that batch items appear as sub-files/directories
   ```
5. **Post-hoc report from existing trace**:
   ```bash
   uv run pflow trace report
   # Should auto-detect latest trace and generate report
   ```
6. **Verify trace format**:
   ```bash
   cat ~/.pflow/debug/workflow-trace-*.json | python -m json.tool | head -50
   # Should show format_version: "2.0.0", no shared_before/shared_after
   ```
7. **Verify Ctrl+C produces trace**: Start a long-running workflow, Ctrl+C it, verify trace file exists.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `src/pflow/runtime/wrappers/template_wrapper.py` | Add `last_resolutions` attribute, add to `wrapper_attrs` |
| `src/pflow/runtime/wrappers/instrumented_wrapper.py` | Rewrite `_record_trace()`, add `_find_template_wrapper()`, `_find_batch_or_workflow_node()`, remove full shared store snapshots |
| `src/pflow/runtime/workflow_trace.py` | Format 2.0.0, new `record_node_execution` signature, remove truncation, add `_sanitize_for_json`, `_collect_llm_summary`, `enable_llm_interception` flag, fix threading bug |
| `src/pflow/runtime/wrappers/batch_node.py` | Add `_capture_item_trace()`, init trace accumulator in `prep()`, store `_trace_items` in `post()` |
| `src/pflow/runtime/workflow_executor.py` | Add `_trace_collector` to `_PROPAGATED_KEYS`, create child collectors in `exec()` |
| `src/pflow/cli/main.py` | Add `--report` flag, move trace save to `finally`, remove 4 scattered save calls, handle `--report`+`--no-trace` |
| `src/pflow/core/trace_report.py` | Update report generator for format 2.0.0 (file already exists) |
| `src/pflow/cli/commands/trace.py` | Minor updates if needed (file already exists with `pflow trace report`) |

**NOT modified** (no changes needed):
- `src/pflow/execution/executor_service.py` — already injects `_trace_collector` at lines 99-102
- `src/pflow/runtime/compilation/compiler.py` — already accepts and passes `trace_collector`
- `src/pflow/cli/main_wrapper.py` — already routes `trace` subcommand

## Files with Test Updates

| File | Tests affected |
|------|---------------|
| `tests/test_runtime/test_workflow_trace.py` | ~13 tests |
| `tests/test_integration/test_metrics_integration.py` | ~1 test |
| `tests/test_runtime/test_instrumented_wrapper.py` | ~2 tests |
| `tests/test_runtime/test_batch_node.py` | ~1 test |
