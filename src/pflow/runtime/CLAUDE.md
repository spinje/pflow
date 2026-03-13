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
├── template_validator.py    # Pre-execution template validation with rich errors
├── workflow_executor.py     # Nested workflow executor node
├── workflow_trace.py        # Trace collection with thread-safe LLM interception
├── workflow_validator.py    # IR validation and input preparation
├── output_resolver.py       # Output declaration resolver
├── error_context.py         # Upstream error context extraction
└── type_checker.py          # Runtime type checking utilities
```

## Compilation Pipeline

`compile_ir_to_flow()` is the main entry point (called by `executor_service.py`):

1. Parse IR dict
2. Validate structure, inputs, outputs
3. Instantiate nodes with registry lookup
4. Apply wrapper chain (template → namespace → batch → instrumentation)
5. Wire nodes using edges
6. Create Flow object with start node

**CompilationError** fields: `phase`, `node_id`, `node_type`, `details`, `suggestion` — provides structured context for debugging.

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
- **API warning detection**: 3-tier priority system with 73 validation + 20 resource patterns
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
- Type validation prevents dict/list → str mismatches (uses registry metadata, shows fix suggestions)
- Partial resolution detection via set intersection (Task 85)
- **Strict mode** (default): Template/type errors are fatal ValueError → triggers repair
- **Permissive mode**: Warnings only, stores errors in `shared["__template_errors__"]`

### PflowBatchNode (`batch_node.py`)

Batch processing wrapper:
- Sequential and parallel execution modes
- Isolated item context (shallow copy of shared store per item)
- Deep copies node chain for parallel mode (thread safety)
- Per-item retry logic with configurable wait
- `fail_fast` or `continue` error handling modes

**Critical — LLM cost tracking**: Batch initializes `__llm_calls__` in `prep()` and captures `llm_usage` from each item's isolated context via `_capture_item_llm_usage()`. Captures from both root (`item_shared["llm_usage"]`) and namespaced (`item_shared[node_id]["llm_usage"]`) locations. Without this, LLM costs are lost when item context is discarded.

## Template System

### TemplateResolver (`template_resolver.py`)

**Regex**: `r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"`

**Path support**: `${data.user.name}`, `${items[0].title}`, `${data[5].users[2]}`

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

### TemplateValidator (`template_validator.py`)

Pre-execution validation with rich error suggestions:
- Validates all templates have sources using registry metadata for node outputs
- Detects unused declared inputs
- Flattens nested output structures showing array access patterns
- "Did you mean X?" suggestions for typos (substring matching)
- Shows all available paths (limit 20) with types

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

Runtime node for nested workflow execution:
- Loads workflows by name, path (`.pflow.md`), or inline IR
- Parameter mapping with template resolution
- **Storage isolation modes**: mapped/isolated/scoped/shared
- Circular dependency detection via execution stack
- Registry propagation to sub-workflows

### WorkflowTraceCollector (`workflow_trace.py`)

- **Thread-safe LLM interception**: Reference counting + thread-local collectors
- **Configurable limits**: 5 env vars (`PFLOW_TRACE_*_MAX`)
- **Multi-source prompt capture**: Interceptor → `__llm_calls__` → shared store
- Repair tracking with attempt numbers, errors, workflow diffs
- Mutation analysis: added/removed/modified keys

### Validation Utilities (`workflow_validator.py`)

- `validate_ir_structure()` — basic IR validation
- `prepare_inputs()` — input validation, defaults, and **type coercion** (converts CLI string values to declared types)

### Output Resolver (`output_resolver.py`)

`populate_declared_outputs()` — maps namespaced outputs to root level based on workflow output declarations.

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
    "failed_node": None        # Node that caused workflow failure
}

# System keys
shared["__llm_calls__"] = []              # LLM usage tracking (initialize as empty list!)
shared["__progress_callback__"] = func    # Progress updates from OutputInterface
shared["__non_repairable_error__"] = bool # Skip repair flag (API errors)
shared["__warnings__"] = {}               # Node warnings → triggers DEGRADED status
shared["__modified_nodes__"] = []         # Nodes changed during repair
shared["__cache_hits__"] = []             # Nodes that used cached results
shared["__template_errors__"] = {}        # Template/type errors in permissive mode
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

## Gotchas

- **Wrapper chain order matters** — instrumentation must be outermost, batch must be outside namespace
- **Fresh Registry instance** — always pass a new one to `compile_ir_to_flow()` per execution
- **`__` prefixed params are reserved** — never use for user parameters
- **Don't modify `__execution__` structure** — checkpoint integrity is critical for resume
- **Cache assumes immutability** — don't modify cached node state
- **`validate=False` only for testing** — skipping validation breaks repair
