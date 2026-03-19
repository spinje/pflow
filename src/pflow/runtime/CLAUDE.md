# Runtime Module

Compilation and execution infrastructure. Transforms workflow IR into executable PocketFlow Flow objects via a multi-layer wrapper architecture for template resolution, namespacing, and instrumentation.

## File Structure

```
src/pflow/runtime/
├── __init__.py              # Exports: compile_ir_to_flow(), import_node_class(), CompilationError
├── compiler.py              # Main IR→Flow compiler (~1310 lines)
├── template_resolver.py     # Template variable resolution engine
├── wrappers/                # Execution wrapper chain (see wrappers/CLAUDE.md)
├── template_validation/     # Template validation package (see template_validation/CLAUDE.md)
├── workflow_executor.py     # Nested workflow executor node
├── workflow_trace.py        # Trace collection with thread-safe LLM interception
├── workflow_validator.py    # IR validation and input preparation
└── output_resolver.py       # Output declaration resolver
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

Multi-layer wrapper chain for template resolution, namespacing, batch processing, and instrumentation. See `wrappers/CLAUDE.md` for full details including application order, interception chain, and per-wrapper documentation.

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
- **Template errors**: Fatal ValueError in strict mode

**Resolution priority**:
1. `initial_params` (from CLI)
2. Shared store (runtime data from upstream nodes)
3. Workflow inputs

> For JSON auto-parsing and type coercion details, see `architecture/core-concepts/data-type-coercion.md`.

### Template Validation (`template_validation/`)

Pre-execution validation of template variables. Extracted to its own package — see `template_validation/CLAUDE.md` for full details.

**Import**: `from pflow.runtime.template_validation import validate_workflow_templates, extract_node_outputs, ValidationWarning`

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
- **Cross-cutting key propagation**: `_PROPAGATED_KEYS` tuple defines which `__dunder__` keys flow from parent to child storage in mapped mode (`__registry__`, `__llm_calls__`, `__progress_callback__`, `__mcp_pool__`, `__warnings__`). Execution-scoped keys (`__execution__`, `__cache_hits__`, `__template_errors__`) are deliberately NOT propagated — children get their own.

### WorkflowTraceCollector (`workflow_trace.py`)

- **Thread-safe LLM interception**: Reference counting + thread-local collectors
- **Configurable limits**: 5 env vars (`PFLOW_TRACE_*_MAX`)
- **Multi-source prompt capture**: Interceptor → `__llm_calls__` → shared store
- Repair tracking with attempt numbers, errors, workflow diffs
- Mutation analysis: added/removed/modified keys

### Validation Utilities (`workflow_validator.py`)

**Warning**: Two `workflow_validator.py` files exist — `runtime/workflow_validator.py` (compiler-time, used here) and `core/workflow/validator.py` (pre-execution unified pipeline, 7+ external consumers). Don't confuse them.

- `validate_ir_structure()` — basic IR validation
- `prepare_inputs()` — input validation, defaults, and **type coercion** (converts CLI string values to declared types)
- **Only one `stdin: true` input allowed** — validated at compile time
- **Input resolution precedence** (5-tier): CLI args → `os.environ` → `settings.env` → workflow `default` → error if required

### Output Resolver (`output_resolver.py`)

`populate_declared_outputs()` — maps namespaced outputs to root level based on workflow output declarations. Raises `OutputResolutionError` (from `core/user_errors.py`) for non-coalesce output sources that cannot be resolved (e.g., node didn't execute on the taken branch). Coalesce expressions (`??`) where all operands are absent are silently skipped — this is the expected pattern for branch-dependent outputs.

### Error Context (`wrappers/error_context.py`)

Extracts diagnostic context from upstream nodes when downstream fails. See `wrappers/CLAUDE.md`.

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
shared["__warnings__"] = {}               # Node warnings → triggers DEGRADED status
shared["__cache_hits__"] = []             # Nodes that used cached results
shared["__template_errors__"] = {}        # Template/type errors in permissive mode
shared["__mcp_pool__"] = MCPConnectionPool  # MCP server connection pool (see mcp/pool.py)
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

### Error Categorization (API Warning Detection)

**Validation errors** (parameter format issues, 73 patterns checked):
- `validation_error` — bad request, invalid parameter, schema error
- `template_error` — unresolved variables (triggers ValueError)

**Resource errors** (external state, 20 patterns):
- `resource_error` — not found, forbidden
- API warnings: Slack `"ok": false`, Discord errors, GraphQL `"errors": []`
- HTTP status codes: 401, 403, 404, 429

**Ambiguity rule**: When an error matches BOTH validation and resource patterns, it's treated as **validation** (validation wins).

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
- **`TemplateResolver`** (`template_resolver.py`): Used by `cli/read_fields.py`, `execution/formatters/`, `mcp_server/services/` — not runtime-internal only.
- **`coerce_to_declared_type`** (`core/param_coercion.py`): Used by `wrappers/template_wrapper.py` for dict/list→str serialization. **Don't confuse** with `coerce_input_to_declared_type` (same file) which has a full dispatch table for CLI input coercion (str→int/float/bool etc.) — used by `runtime/workflow_validator.py`.
- **`try_parse_json`** (`core/json_utils.py`): Used by `template_resolver.py`, `wrappers/template_wrapper.py`, `wrappers/batch_node.py`. Returns `(bool, Any)` tuple. 10MB security limit. Only parses to dict/list (not primitives) for type safety.
- **`_pflow_depth`**: Set by `workflow_executor.py`, also read by `wrappers/instrumented_wrapper.py` and `wrappers/batch_node.py` for progress callback indentation depth.

## Gotchas

- **Wrapper chain order matters** — instrumentation must be outermost, batch must be outside namespace
- **Fresh Registry instance** — always pass a new one to `compile_ir_to_flow()` per execution
- **`__` prefixed params are reserved** — never use for user parameters
- **Don't modify `__execution__` structure** — checkpoint integrity is critical for resume
- **Cache assumes immutability** — don't modify cached node state
- **`validate=False` only for testing** — skipping validation bypasses safety checks
