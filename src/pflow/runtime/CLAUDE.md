# Runtime Module

Compilation and execution infrastructure. Compiles workflow IR into `CompiledWorkflow` (bare nodes + per-node configs), then executes via `WorkflowEngine`.

## File Structure

```
src/pflow/runtime/
├── __init__.py              # Exports: compile_workflow(), WorkflowEngine, CompiledWorkflow, etc.
├── compilation/             # IR→CompiledWorkflow compiler (see compilation/CLAUDE.md)
├── engine/                  # Orchestration engine (see engine/CLAUDE.md)
├── cache.py                 # Persistent memoization cache (SQLite, cross-run)
├── template_resolver.py     # Template variable detection and resolution
├── template_validation/     # Template validation package (see template_validation/CLAUDE.md)
├── workflow_executor.py     # Nested workflow executor node (with compile-once cache)
├── workflow_trace.py        # Trace collection with thread-safe LLM interception
└── output_resolver.py       # Output declaration resolver
```

## Compilation Pipeline

`compile_workflow()` is the primary entry point (called by `execution/runner.py` and `workflow_executor.py`):

1. Parse IR dict
2. Resolve external file references
3. Validate structure, inputs, outputs (`ir_preparation.py`, `compile_validation.py`)
4. Instantiate **bare nodes** + build `NodeConfig` per node
5. Wire nodes using edges (PocketFlow `>>` and `-` operators)
6. Return `CompiledWorkflow(start_node, node_configs, outputs, resolved_defaults, ...)`

`compile_ir_to_flow()` was removed (shim deleted after full migration). All callers use `compile_workflow()` + `WorkflowEngine` directly.

**CompilationError** (in `core/exceptions.py`): fields `phase`, `node_id`, `node_type`, `details`, `suggestion`.

## Execution Engine

`WorkflowEngine` (in `engine/engine.py`) walks the node graph and handles all runtime concerns per node. See `engine/CLAUDE.md` for full architecture.

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

**Resolution**: Shared store is the single source of runtime data. `resolved_defaults` (from `prepare_inputs()`) are seeded into shared store before engine starts. User-provided params are seeded by the Runner via `_initialize_shared_store()`. No `initial_params` override.

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
- **Cross-cutting key propagation**: `_PROPAGATED_KEYS` tuple defines which keys flow from parent to child storage in mapped mode (`__registry__`, `__progress_callback__`, `__mcp_pool__`, `__warnings__`, `_trace_collector`). Execution-scoped keys (`__execution__`, `__cache_hits__`, `__template_errors__`) are deliberately NOT propagated — children get their own.

### MemoizationCache (`cache.py`)

Persistent cross-run caching of node outputs. When an AI agent iterates on a workflow (edit prompt, re-run, evaluate, repeat), unchanged nodes serve cached results instead of re-executing.

- **Storage**: SQLite at `~/.pflow/cache/cache.db`, WAL journal mode, zlib-compressed output BLOBs
- **Cache key**: `md5(config_hash + resolved_inputs)` for non-batch nodes. Batch nodes add `semantic_batch_config + resolved_items`. Keys are content-addressed — no collision risk across workflows or nesting levels.
- **TTL**: Default 24 hours. Checked inline on `get()` (expired entries deleted). Periodic eviction on `put()` every 50 writes.
- **`read_enabled=False`**: For `--no-cache` mode — writes still happen (seeds cache for next run), reads return None.
- **Graceful degradation**: All SQLite/zlib/JSON operations wrapped in try/except with debug logging. Cache failures never crash workflows.
- **Test isolation**: `tests/conftest.py::isolate_pflow_config` monkey-patches `MemoizationCache.__init__` to use temp paths. Without this, tests pollute the real cache DB and cause cross-test hits.

**Integration point**: Created by `execution/runner.py::_initialize_shared_store()`, stored as `shared["__memoization_cache__"]`. Consumed by `engine/instrumentation.py::check_memo_cache()`. Propagated to child workflows via `_PROPAGATED_KEYS` in `workflow_executor.py`.

**What the config hash includes** (from `engine/instrumentation.py::compute_node_config()`):
- Node type (class name of the bare node)
- Static params (`_source_line` keys filtered out)
- Template params (raw `${...}` template strings from `NodeConfig.template_config`)
- Batch semantic config (`items_template`, `item_alias`, `error_handling`, `max_retries`) — but NOT operational config (`parallel`, `max_concurrent`, `retry_wait`)

**Side-effecting nodes ARE cached**: `write-file`, `shell` nodes with deterministic config+inputs will return cached output on second run (file won't be re-written, command won't re-execute). This is intentional for the iteration loop use case. `--no-cache` provides an escape hatch.

### WorkflowTraceCollector (`workflow_trace.py`)

- **Format 2.0.0**: Tree-structured events with `node_output`, `template_resolutions`, `node_params`, `batch_items`, `sub_workflow_events` (no `shared_before`/`shared_after` snapshots, no value truncation)
- **Thread-safe LLM interception**: Reference counting + per-thread collector lookup for top-level workflows. Child collectors skip interception (`enable_llm_interception=False`) — prompts captured via `template_resolutions` instead.
- **Prompt capture**: Interceptor (ground truth for top-level) → `node_output["prompt"]` fallback. Child workflow prompts in `template_resolutions["prompt"]["resolved"]`.
- **Batch item tracing**: Per-item events collected via `_batch_trace` shared-store accumulator (GIL-safe for parallel), sanitized by `_sanitize_batch_items()`.
- **Sub-workflow tracing**: Child collectors created by `WorkflowExecutor`, events embedded in parent trace as `sub_workflow_events`.
- Mutation analysis: key-level added/removed (no value-change detection — requires full snapshots removed in 2.0.0)

### IR Preparation (`compilation/ir_preparation.py`)

**Warning**: Two validation files exist — `compilation/ir_preparation.py` (compiler-time, used here) and `core/workflow/validator.py` (pre-execution unified pipeline, 7+ external consumers). Don't confuse them.

- `validate_ir_structure()` — basic IR validation
- `prepare_inputs()` — input validation, defaults, and **type coercion** (converts CLI string values to declared types)
- **Only one `stdin: true` input allowed** — validated at compile time
- **Input resolution precedence** (5-tier): CLI args → `os.environ` → `settings.env` → workflow `default` → error if required

### Output Resolver (`output_resolver.py`)

`populate_declared_outputs()` — maps namespaced outputs to root level based on workflow output declarations. Raises `OutputResolutionError` (from `core/user_errors.py`) for non-coalesce output sources that cannot be resolved (e.g., node didn't execute on the taken branch). Coalesce expressions (`??`) where all operands are absent are silently skipped — this is the expected pattern for branch-dependent outputs.

### Error Context (`engine/error_context.py`)

Extracts diagnostic context from upstream nodes when downstream fails. See `engine/CLAUDE.md`.

## Reserved Shared Store Keys (Canonical Reference)

```python
# Execution tracking (managed by engine/instrumentation.py)
shared["__execution__"] = {
    "completed_nodes": [],     # Successfully executed nodes
    "node_actions": {},        # Actions returned by each node
    "node_hashes": {},         # MD5 config hashes for cache validation
    "failed_node": None,       # Node that caused workflow failure
    "node_visit_counts": {},   # Per-node visit counter (loop guard)
    "only_node": None,         # --only target node ID (set by engine, read by display layer)
}

# System keys
shared["_trace_collector"] = trace_collector  # WorkflowTraceCollector instance (always created, even with --no-trace)
shared["__progress_callback__"] = func    # Progress updates from OutputInterface
shared["__warnings__"] = {}               # Node warnings → triggers DEGRADED status
shared["__cache_hits__"] = []             # Nodes that used cached results
shared["__template_errors__"] = {}        # Template/type errors in permissive mode
shared["__mcp_pool__"] = MCPConnectionPool  # MCP server connection pool (see mcp/pool.py)
shared["__memoization_cache__"] = MemoizationCache  # Cross-run node output cache (see cache.py)
shared["__index__"] = int                  # 0-based batch item index (injected by batch_executor)

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

**Critical test scenarios**: Template resolution with array indices, cache invalidation via hash mismatch, API warning detection patterns, circular workflow detection, MCP server names with dashes (greedy match), thread-safe LLM interception, compile-once for sub-workflows in batch.

## Cross-Module Dependencies

Key runtime modules used outside `runtime/`:
- **`TemplateResolver`** (`template_resolver.py`): Used by `cli/commands/read_fields.py`, `execution/formatters/`, `mcp_server/services/` — not runtime-internal only.
- **`coerce_to_declared_type`** (`core/param_coercion.py`): Used by `engine/template_resolution.py` for dict/list→str serialization. **Don't confuse** with `coerce_input_to_declared_type` (same file) which has a full dispatch table for CLI input coercion (str→int/float/bool etc.) — used by `compilation/ir_preparation.py`.
- **`try_parse_json`** (`core/json_utils.py`): Used by `template_resolver.py`, `engine/template_resolution.py`, `engine/batch_executor.py`. Returns `(bool, Any)` tuple. 10MB security limit. Only parses to dict/list (not primitives) for type safety.
- **`_pflow_depth`**: Set by `workflow_executor.py`, also read by `engine/instrumentation.py` and `engine/batch_executor.py` for progress callback indentation depth.

## Gotchas

- **Batch nodes skip top-level template resolution** — engine guards on `not config.batch_config`; per-item resolution handled by batch executor
- **Fresh Registry instance** — always pass a new one to `compile_workflow()` per execution
- **`__` prefixed params are reserved** — never use for user parameters
- **Don't modify `__execution__` structure** — checkpoint integrity is critical for resume
- **Cache assumes immutability** — don't modify cached node state
- **`_source_line` keys NOT filtered in split_params** — `python_code.py` reads them for error line numbers
- **Compile-once `id()` check** — only works for static `workflow_ir`; template expressions create new dicts per item
