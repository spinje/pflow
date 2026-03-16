# Runtime Module

Compilation and execution infrastructure. Transforms workflow IR into executable PocketFlow Flow objects via a multi-layer wrapper architecture for template resolution, namespacing, and instrumentation.

## File Structure

```
src/pflow/runtime/
├── __init__.py              # Exports: compile_ir_to_flow(), import_node_class(), CompilationError
├── compiler.py              # Main IR→Flow compiler (~1042 lines)
├── batch_node.py            # Batch processing wrapper (sequential/parallel)
├── instrumented_wrapper.py  # Metrics, tracing, caching, API error detection (~1168 lines)
├── node_wrapper.py          # Template resolution wrapper (~680 lines)
├── namespaced_wrapper.py    # Collision prevention wrapper (~95 lines)
├── namespaced_store.py      # Namespaced store proxy (~156 lines)
├── template_resolver.py     # Template variable resolution engine
├── template_validator.py    # Validation orchestrator + output extraction (~500 lines)
├── template_path_validation.py  # Pass 5: path existence, nested path traversal (~650 lines)
├── template_type_validation.py  # Passes 6+7: type matching, shell command types (~350 lines)
├── batch_item_validation.py     # Pass 8: ${item.field} validation (~250 lines)
├── validation_utils.py          # Shared validation infrastructure (~250 lines)
├── workflow_executor.py     # Nested workflow executor node
├── workflow_trace.py        # Trace collection with thread-safe LLM interception
├── workflow_validator.py    # IR validation and input preparation
├── output_resolver.py       # Output declaration resolver
├── error_context.py         # Upstream error context extraction
└── type_checker.py          # Runtime type checking utilities
```

## Compilation Pipeline

`compile_ir_to_flow()` is the main entry point (called by `execution/executor_service.py` and internally by `workflow_executor.py` for nested workflows):

1. Parse IR dict
2. Validate structure, inputs, outputs
3. Instantiate nodes with registry lookup
4. Apply wrapper chain (template → namespace → batch → instrumentation)
5. Wire nodes using edges
6. Create Flow object with start node

**CompilationError** fields: `phase`, `node_id`, `node_type`, `details`, `suggestion` — provides structured context for debugging.

**Non-obvious compiler behaviors**:
- **LLM default model injection**: LLM nodes without `model` param get auto-injected default from `get_default_workflow_model()`. Fails with helpful message if no model configured anywhere.
- **Source line threading**: `_source_lines` from markdown parser are threaded into params as `_<key>_source_line` — enables nodes to reference `.pflow.md` line numbers in errors.
- **Flow.run monkey-patching**: When workflow declares outputs, compiler wraps `flow.run` to call `populate_declared_outputs()` after successful execution. Output resolution raises `OutputResolutionError` for non-coalesce failures; coalesce (`??`) expressions with all-absent operands are silently skipped.
- **Template resolution mode**: Can come from IR `template_resolution_mode` field OR global settings fallback. Stored in `initial_params["__template_resolution_mode__"]`.

## Wrapper Architecture

### Application Order (CRITICAL)

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

### _run() Interception Chain

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

### set_params() Flow

```
InstrumentedNodeWrapper.set_params()
  └─> NamespacedNodeWrapper (delegates via __getattr__)
      └─> TemplateAwareNodeWrapper.set_params()
          ├─ Separates template/static params
          └─> ActualNode.set_params(static_only)
```

### InstrumentedNodeWrapper (`instrumented_wrapper.py`)

Outermost wrapper. Provides:
- **Checkpoint system**: MD5-based configuration caching (skip re-execution on resume)
- **API warning detection**: 3-tier priority system with 73 validation + 20 resource patterns. **Unwraps MCP nested responses** (JSON string `result`, `data` field, HTTP `response`+`status_code`) before checking. **When error matches both validation and resource patterns, defaults to repairable** (validation wins).
- **LLM usage capture**: Token tracking and cost attribution
- **Progress callbacks**: Real-time execution feedback via OutputInterface
- **Cache hit tracking**: Records which nodes used cache in `shared["__cache_hits__"]`

### NamespacedNodeWrapper (`namespaced_wrapper.py`)

Automatic collision prevention:
- Redirects writes to `shared[node_id][key]`
- **Reads check both namespace and root level** (so nodes can read upstream data)
- Special keys (`__*__`) bypass namespacing for framework coordination
- Transparent to nodes — they don't know about namespacing

### TemplateAwareNodeWrapper (`node_wrapper.py`)

Template resolution at runtime:
- Separates template vs static parameters at `set_params()` time
- Resolves `${variable}` syntax during `_run()`
- **Bidirectional type coercion**: (1) str→dict/list auto-parse when expected type is structured, (2) dict/list→str auto-serialize via `coerce_to_declared_type` when expected type is str. Both use registry interface metadata. This enables shell→MCP and MCP→shell patterns.
- Partial resolution detection via set intersection (Task 85)
- **Strict mode** (default): Template/type errors are fatal ValueError → triggers repair
- **Permissive mode**: Warnings only, stores errors in `shared["__template_errors__"]`
- **Params temporarily mutated**: `inner_node.params` is swapped to resolved params during `_run()`, restored in `finally` block. Critical for understanding parallel batch execution.

### PflowBatchNode (`batch_node.py`)

Batch processing wrapper. **Inherits from `Node`, not PocketFlow's `BatchNode`** — avoids `self.cur_retry` race condition in parallel mode by using local retry variables instead.

- Sequential and parallel execution modes
- Isolated item context (shallow copy of shared store per item)
- Deep copies node chain for parallel mode (thread safety). **Collectors (metrics/trace) are NOT deep-copied** — shared across all batch copies.
- Per-item retry logic with configurable wait
- `fail_fast` or `continue` error handling modes. **fail_fast is best-effort for parallel**: already-running LLM/HTTP calls can't be interrupted.
- **`items` can be an inline array** (not just a template reference) — resolved via `resolve_nested()`
- **Auto-JSON parsing**: If items template resolves to a string, tries `json.loads()`. Enables shell→batch patterns.
- **`__index__`**: 0-based index injected into each item's shared store — nodes can know which item they're processing
- **`item` is a reserved field** in batch results: inner node output `item` key is silently overwritten with original batch input (warning logged). Potential data loss.

**Critical — LLM cost tracking**: Batch initializes `__llm_calls__` in `prep()` and captures `llm_usage` from each item's isolated context via `_capture_item_llm_usage()`. Captures from both root (`item_shared["llm_usage"]`) and namespaced (`item_shared[node_id]["llm_usage"]`) locations. Without this, LLM costs are lost when item context is discarded.

## Template System

### TemplateResolver (`template_resolver.py`)

**Regex**: `r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"`

**Path support**: `${data.user.name}`, `${items[0].title}`, `${data[5].users[2]}`

**Escape syntax**: `$${var}` (double dollar) prevents template resolution via regex negative lookbehind. **However**, the escape is half-implemented: it prevents resolution but does NOT strip the extra `$` — output will contain the literal string `$${var}`, not `${var}`. There is currently no way to produce a literal `${...}` in output. Also note: `has_templates("$${var}")` returns `True` (naive `${` substring check) even though `extract_variables("$${var}")` returns empty set — this inconsistency is harmless but can confuse debugging.

**Nested index templates**: `${results[${item.index}].response}` — inner `${...}` is resolved first (e.g., to `${results[0].response}`). Only **one level** of nesting is supported. Enables dynamic array indexing in batch processing where the index comes from `${__index__}` or `${item.field}`.

**JSON auto-parsing**: When traversing paths like `${node.stdout.field}`, if `stdout` is a JSON string, it's auto-parsed for traversal. **Critical**: only dict/list results from `json.loads()` are used — numeric strings like Discord snowflake IDs (`"1458059302022549698"`) are deliberately preserved as strings, not parsed to int.

**Type behavior**:
- **Simple templates** (`${var}`): Preserve original type (int, bool, None, dict, list)
- **Complex templates** (`"Hello ${name}"`): Always return strings
- **Inline objects** (`{"key": "${dict_var}"}`): Preserve inner types (no double-serialization)
- **Type conversion**: None→"", False→"False", True→"True", 0→"0", []→"[]", {}→"{}", dicts/lists→JSON serialized
- **Unresolved templates**: Remain as-is for debugging visibility
- **Template errors**: Fatal ValueError triggers repair in strict mode

**Resolution priority**:
1. `initial_params` (from planner/CLI)
2. Shared store (runtime data from upstream nodes)
3. Workflow inputs

> For JSON auto-parsing and type coercion details, see `architecture/core-concepts/data-type-coercion.md`.

### Template Validation (split across 5 files)

Pre-execution validation with rich error suggestions, split by validation concern. Each file owns both detection logic AND error formatting for its concern.

**Entry point**: `validate_workflow_templates()` in `template_validator.py` — orchestrates all passes.

**File structure**:
- `template_validator.py` — Orchestrator, output extraction, template extraction, simple passes (malformed, unused inputs)
- `template_path_validation.py` — Pass 5: path existence, namespaced output, nested path traversal + all path error formatting
- `template_type_validation.py` — Passes 6+7: type matching + shell command type safety
- `batch_item_validation.py` — Pass 8: `${item.field}` validation against inferred item structure
- `validation_utils.py` — Shared: `split_template_path`, `sanitize_for_display`, `find_similar_paths`, `flatten_output_structure`, `build_paths_from_entries`, `get_node_ids`, `ValidationWarning`, display constants

**Dependency graph** (no cycles):
```
template_validator.py (orchestrator)
  ├── template_path_validation → validation_utils
  ├── template_type_validation → type_checker
  └── batch_item_validation → template_path_validation, validation_utils
```

**Public API**:
- `validate_workflow_templates(workflow_ir, available_params, registry)` — main entry point
- `extract_node_outputs(workflow_ir, registry)` — builds node_outputs dict (also used by compiler.py)
- `ValidationWarning` — re-exported from validation_utils for backward compat

**Key behaviors**:
- Validates all templates have sources using registry metadata for node outputs
- Detects unused declared inputs
- Flattens nested output structures showing array access patterns
- "Did you mean X?" suggestions for typos (substring matching)
- Shows all available paths (limit 20) with types
- **Shell command validation**: Blocks dict/list templates in shell `command` params. Fix options: access specific fields, use stdin, or use the **single-quote escape hatch**: `'${var}'`

**Error format example**:
```
Node 'fetch-messages' (mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY)
does not have output 'msg'

Available outputs from this node:
  - result: dict
  - result.messages: array
  - result.messages[0].text: string

Did you mean one of these?
  - result.messages (array)

Common fix: Change ${fetch-messages.msg} to ${fetch-messages.result.messages}
```

## Other Components

### WorkflowExecutor (`workflow_executor.py`)

Runtime node for nested workflow execution. Uses the **same syntax as any other node** — non-reserved params are child inputs, child outputs auto-expose via namespace.

```markdown
### process_title
- type: workflow
- workflow: ./child.pflow.md
- text: ${title}
```
Downstream: `${process_title.result}`

- **`workflow` param**: unified — file paths (contains `/`, starts with `.`, ends `.pflow.md`) or saved workflow names
- **`workflow_ir` param**: inline IR dict (via yaml code block)
- **Params-as-inputs**: all non-reserved params (`RESERVED_PARAMS` frozenset) become child inputs
- **Auto-outputs**: child's `## Outputs` declarations exposed via namespace. If no declarations, all non-internal keys exposed.
- **Storage modes**: `mapped` (default, child sees only passed params) and `shared` (child uses parent storage directly)
- **Circular dependency detection** via `_pflow_stack` execution stack
- **Max depth enforcement** via `_pflow_depth` (default 10)
- **Relative paths resolve from parent workflow directory** via `_pflow_workflow_file`, not CWD
- **Child input validation**: compares provided params against child's `## Inputs`, gives actionable error with "You provided X, Available inputs: Y"

### WorkflowTraceCollector (`workflow_trace.py`)

- **Thread-safe LLM interception**: Reference counting + thread-local collectors
- **Configurable limits**: 5 env vars (`PFLOW_TRACE_*_MAX`)
- **Multi-source prompt capture**: Interceptor → `__llm_calls__` → shared store
- Repair tracking with attempt numbers, errors, workflow diffs
- Mutation analysis: added/removed/modified keys

### Validation Utilities (`workflow_validator.py`)

**Warning**: Two `workflow_validator.py` files exist — `runtime/workflow_validator.py` (compiler-time, used here) and `core/workflow_validator.py` (pre-execution unified pipeline, 7+ external consumers). Don't confuse them.

- `validate_ir_structure()` — basic IR validation
- `prepare_inputs()` — input validation, defaults, and **type coercion** (converts CLI string values to declared types)
- **Only one `stdin: true` input allowed** — validated at compile time
- **Input resolution precedence** (5-tier): CLI args → `os.environ` → `settings.env` → workflow `default` → error if required

### Output Resolver (`output_resolver.py`)

`populate_declared_outputs()` — maps namespaced outputs to root level based on workflow output declarations. Raises `OutputResolutionError` (from `core/user_errors.py`) for non-coalesce output sources that cannot be resolved (e.g., node didn't execute on the taken branch). Coalesce expressions (`??`) where all operands are absent are silently skipped — this is the expected pattern for branch-dependent outputs.

### Error Context (`error_context.py`)

Extracts diagnostic context from upstream nodes when downstream fails. Surfaces stderr from shell nodes referenced in template variables.

```
Batch items must be an array, got str. Template '${extract.stdout}' resolved to: ''

  ⚠️  Upstream node 'extract' stderr:
     grep: invalid option -- P
     usage: grep [-abcdDEFGHhIiJLlMmnOopqRSsUVvwXxZz] ...
```

Used by `batch_node.py` (batch item resolution errors) and `node_wrapper.py` (unresolved template errors).

## Reserved Shared Store Keys (Canonical Reference)

```python
# Execution tracking (managed by InstrumentedNodeWrapper)
shared["__execution__"] = {
    "completed_nodes": [],     # Successfully executed nodes
    "node_actions": {},        # Actions returned by each node
    "node_hashes": {},         # MD5 config hashes for cache validation
    "failed_node": None,       # Node that caused workflow failure
    "node_visit_counts": {},   # Per-node visit counter (loop guard)
}

# System keys
shared["__llm_calls__"] = []              # LLM usage tracking (initialize as empty list!)
shared["__progress_callback__"] = func    # Progress updates from OutputInterface
shared["__non_repairable_error__"] = bool # Skip repair flag (API errors)
shared["__warnings__"] = {}               # Node warnings → triggers DEGRADED status
shared["__modified_nodes__"] = []         # Nodes changed during repair
shared["__cache_hits__"] = []             # Nodes that used cached results
shared["__template_errors__"] = {}        # Template/type errors in permissive mode
shared["__mcp_pool__"] = MCPConnectionPool  # MCP server connection pool (see mcp/pool.py)
shared["__is_planner__"] = bool            # Cost attribution flag for planner nodes
shared["__index__"] = int                  # 0-based batch item index (injected by PflowBatchNode)

# Nested workflow keys (different prefix — _pflow_ not __)
shared["_pflow_depth"] = int               # Current nesting depth
shared["_pflow_stack"] = list[str]         # Execution stack for circular detection
shared["_pflow_workflow_file"] = str       # Current workflow file path
```

## Node Metadata Shape (from Registry)

```python
{
    "module": "pflow.nodes.file.read_file",
    "class_name": "ReadFileNode",
    "type": "core",              # core/user/mcp
    "file_path": "/path/to/node.py",  # for user nodes only
    "interface": {...}           # Input/output metadata from docstrings
}
```

## Critical Behaviors

### Cache Invalidation

Cache used when: node in `completed_nodes` AND config hash matches AND no error action returned. Invalidated on parameter change (hash mismatch).

### Error Categorization

**Repairable** (repair attempted):
- `validation_error` — parameter format issues (73 patterns checked)
- `template_error` — unresolved variables (triggers ValueError)

**Non-repairable** (workflow stops, sets `__non_repairable_error__`):
- `resource_error` — not found, forbidden (20 patterns)
- API warnings: Slack `"ok": false`, Discord errors, GraphQL `"errors": []`
- HTTP status codes: 401, 403, 404, 429

**Ambiguity rule**: When an error matches BOTH validation and resource patterns, it's treated as **repairable** (validation wins). Default for unknown errors is also repairable — loop detection is the safety net.

### MCP Node Handling

- Node type format: `mcp-<server>-<tool>`
- **Server names can contain dashes** — uses greedy longest match algorithm to parse
- Parameters injected: `__mcp_server__`, `__mcp_tool__`
- Virtual path marker: `"virtual://mcp"` distinguishes from real file-based nodes
- Validation skipped when registry has no real nodes for this type
- Error suggestions: 3-tier system (no tools → similar tools → available servers)

## Registry Integration

`import_node_class()` handles 4 node types differently:
- **Core nodes**: Standard Python `importlib.import_module()`
- **User nodes**: Direct file import via `spec_from_file_location`
- **MCP nodes**: Virtual nodes with server/tool injection via special params
- **Workflow nodes**: Registry injected as parameter for nested execution

## Testing

**Key mock points**: `Registry.load()`, `importlib.import_module()`, `importlib.util.spec_from_file_location()`, `WorkflowManager`, `MCPServerManager.list_servers()`.

**Node type testing**: Core nodes use real test nodes from `src/pflow/nodes/test_node*.py`. MCP nodes mock with `"virtual://mcp"` file path. Enable test nodes with `PFLOW_INCLUDE_TEST_NODES=true`.

**Critical test scenarios**: Template resolution with array indices, cache invalidation via hash mismatch, API warning detection patterns, circular workflow detection, MCP server names with dashes (greedy match), wrapper chain attribute delegation (`inner_node` vs `_inner_node`), thread-safe LLM interception.

## Cross-Module Dependencies

Key runtime modules used outside `runtime/`:
- **`TemplateResolver`** (`template_resolver.py`): Used by `cli/read_fields.py`, `execution/formatters/`, `mcp_server/services/`, `planning/nodes.py` — not runtime-internal only.
- **`coerce_to_declared_type`** (`core/param_coercion.py`): Used by `node_wrapper.py` for dict/list→str serialization. **Don't confuse** with `coerce_input_to_declared_type` (same file) which has a full dispatch table for CLI input coercion (str→int/float/bool etc.) — used by `runtime/workflow_validator.py`.
- **`try_parse_json`** (`core/json_utils.py`): Used by `template_resolver.py`, `node_wrapper.py`, `batch_node.py`. Returns `(bool, Any)` tuple. 10MB security limit. Only parses to dict/list (not primitives) for type safety.
- **`__is_planner__`**: Set by `planning/debug.py`, read by `instrumented_wrapper.py` → routes to `core/metrics.py` for planner vs workflow cost separation.
- **`_pflow_depth`**: Set by `workflow_executor.py`, also read by `instrumented_wrapper.py` and `batch_node.py` for progress callback indentation depth.

## Gotchas

- **Wrapper chain order matters** — instrumentation must be outermost, batch must be outside namespace
- **Fresh Registry instance** — always pass a new one to `compile_ir_to_flow()` per execution
- **`__` prefixed params are reserved** — never use for user parameters
- **Don't modify `__execution__` structure** — checkpoint integrity is critical for resume
- **Cache assumes immutability** — don't modify cached node state
- **`validate=False` only for testing** — skipping validation breaks repair
