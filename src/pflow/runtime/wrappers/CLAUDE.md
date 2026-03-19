# Wrappers Module

Execution wrapper chain that intercepts node `_run()` to add template resolution, namespacing, batch processing, and instrumentation. Assembled by `compiler.py` in `_create_single_node()`.

## File Structure

```
src/pflow/runtime/wrappers/
├── __init__.py                # Docstring only (no external src/ consumers)
├── instrumented_wrapper.py    # Outermost: metrics, tracing, caching, callbacks (~810 lines)
├── template_wrapper.py        # Template resolution wrapper (~710 lines)
├── batch_node.py              # Batch processing (sequential/parallel, ~861 lines)
├── namespaced_wrapper.py      # Collision prevention wrapper (~94 lines)
├── namespaced_store.py        # Namespaced store proxy (~183 lines)
├── api_warning_detector.py    # API error classification (~450 lines, extracted from instrumented_wrapper)
├── template_errors.py         # Template error formatting (~390 lines, extracted from template_wrapper)
└── error_context.py           # Upstream stderr extraction (~92 lines)
```

## Application Order (CRITICAL)

```python
node = node_class()                              # 1. Base node
node = TemplateAwareNodeWrapper(node, ...)       # 2. Template resolution (conditional)
node = NamespacedNodeWrapper(node, ...)          # 3. Namespacing (if enabled)
node = PflowBatchNode(node, ...)                 # 4. Batch processing (if batch config)
node = InstrumentedNodeWrapper(node, ...)        # 5. Instrumentation (ALWAYS applied)
```

**Order constraints**:
- Template wrapper only applied if params contain `${...}` templates
- Batch wrapper only applied if node has `batch` config in IR
- **Batch wrapper MUST be outside namespace** — injects item alias at root level
- Instrumentation is ALWAYS outermost

## _run() Interception Chain

```
InstrumentedNodeWrapper._run()
  ├─ Check cache, setup callbacks
  └─ Call: inner_node._run()
       ↓
  PflowBatchNode._run() [if batch configured]
  ├─ For each item: create isolated context, execute inner node
  └─ Capture LLM usage from each item context before discarding
       ↓
  NamespacedNodeWrapper._run()
  └─ Call: inner_node._run(NamespacedSharedStore)
       ↓
  TemplateAwareNodeWrapper._run()
  ├─ Resolve templates (including ${item} from batch)
  └─ Call: inner_node._run()
       ↓
  ActualNode._run()
```

## set_params() Flow

```
InstrumentedNodeWrapper.set_params()
  └─> NamespacedNodeWrapper (delegates via __getattr__)
      └─> TemplateAwareNodeWrapper.set_params()
          ├─ Separates template/static params
          └─> ActualNode.set_params(static_only)
```

## InstrumentedNodeWrapper (`instrumented_wrapper.py`)

Outermost wrapper. Provides:
- **Checkpoint system**: MD5-based configuration caching (skip re-execution on resume)
- **API warning detection**: Delegates to `api_warning_detector.py` (see below)
- **LLM usage capture**: Token tracking and cost attribution
- **Progress callbacks**: Real-time execution feedback via OutputInterface
- **Cache hit tracking**: Records which nodes used cache in `shared["__cache_hits__"]`

## API Warning Detector (`api_warning_detector.py`)

Extracted from `InstrumentedNodeWrapper`. Standalone functions for detecting API errors in node output.

Entry point: `detect_api_warning(node_id, shared) -> Optional[str]`

3-tier priority system:
1. Error codes (most reliable signal) — 14 validation codes, 16 resource codes
2. Validation patterns (73 patterns) — defer to normal error handling
3. Resource patterns (20 patterns) — surface as API warning

**When error matches both validation and resource patterns, validation wins.**

**Unwraps MCP nested responses** (JSON string `result`, `data` field, HTTP `response`+`status_code`) before checking.

## NamespacedNodeWrapper (`namespaced_wrapper.py`)

Automatic collision prevention:
- Redirects writes to `shared[node_id][key]`
- **Reads check both namespace and root level** (so nodes can read upstream data)
- Special keys (`__*__`) bypass namespacing for framework coordination
- Transparent to nodes — they don't know about namespacing

## TemplateAwareNodeWrapper (`template_wrapper.py`)

Template resolution at runtime:
- Separates template vs static parameters at `set_params()` time
- Resolves `${variable}` syntax during `_run()`
- **Bidirectional type coercion**: (1) str->dict/list auto-parse when expected type is structured, (2) dict/list->str auto-serialize via `coerce_to_declared_type` when expected type is str. Both use registry interface metadata.
- Partial resolution detection via set intersection
- **Strict mode** (default): Template/type errors are fatal ValueError
- **Permissive mode**: Warnings only, stores errors in `shared["__template_errors__"]`
- **Params temporarily mutated**: `inner_node.params` is swapped to resolved params during `_run()`, restored in `finally` block. Critical for understanding parallel batch execution.
- Error messages delegated to `template_errors.py` (see below)

## Template Errors (`template_errors.py`)

Extracted from `TemplateAwareNodeWrapper`. Standalone functions for building actionable error messages.

- `build_type_error_message()` — type mismatch (dict/list where str expected) with fix suggestions
- `build_json_parse_error_message()` — malformed JSON with detected issues
- `build_enhanced_template_error()` — unresolved template with context keys, suggestions, JSON hints
- `diagnose_coalesce()` — per-operand status for coalesce expressions

All pure functions: (param_key, template, context) -> formatted string. No class dependency.

## PflowBatchNode (`batch_node.py`)

Batch processing wrapper. **Inherits from `Node`, not PocketFlow's `BatchNode`** — avoids `self.cur_retry` race condition in parallel mode by using local retry variables instead.

- Sequential and parallel execution modes
- Isolated item context (shallow copy of shared store per item)
- Deep copies node chain for parallel mode (thread safety). **Collectors (metrics/trace) are NOT deep-copied** — shared across all batch copies.
- Per-item retry logic with configurable wait
- `fail_fast` or `continue` error handling modes. **fail_fast is best-effort for parallel**: already-running LLM/HTTP calls can't be interrupted.
- **`items` can be an inline array** (not just a template reference) — resolved via `resolve_nested()`
- **Auto-JSON parsing**: If items template resolves to a string, tries `json.loads()`. Enables shell->batch patterns.
- **`__index__`**: 0-based index injected into each item's shared store
- **`item` is a reserved field** in batch results: inner node output `item` key is silently overwritten with original batch input (warning logged).

**Critical — LLM cost tracking**: Batch initializes `__llm_calls__` in `prep()` and captures `llm_usage` from each item's isolated context via `_capture_item_llm_usage()`. Captures from both root and namespaced locations. Without this, LLM costs are lost when item context is discarded.

## Error Context (`error_context.py`)

Extracts diagnostic context from upstream nodes when downstream fails. Surfaces stderr from shell nodes referenced in template variables.

Used by `batch_node.py` (batch item resolution errors) and `template_wrapper.py` (unresolved template errors).

## Cross-Module Dependencies

- `template_resolver.py` (parent `runtime/`): Used by `template_wrapper.py`, `batch_node.py`, `error_context.py`, `template_errors.py` via `..template_resolver`
- `core/json_utils.py`: Used by `template_wrapper.py`, `batch_node.py`
- `core/param_coercion.py`: Used by `template_wrapper.py`
- `core/llm_pricing.py`: Used by `instrumented_wrapper.py`, `batch_node.py`
- `pocketflow.Node`: Used by `batch_node.py` (inheritance)

## Gotchas

- **Wrapper chain order matters** — instrumentation must be outermost, batch must be outside namespace
- **Don't modify `__execution__` structure** — checkpoint integrity is critical for resume
- **Cache assumes immutability** — don't modify cached node state
- **`validate=False` only for testing** — skipping validation bypasses safety checks
