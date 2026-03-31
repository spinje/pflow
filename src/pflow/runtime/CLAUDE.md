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

See `compilation/CLAUDE.md` for details. Quick summary:

`compile_workflow()` → parse IR → resolve file refs → validate → instantiate bare nodes + `NodeConfig` → wire edges → `CompiledWorkflow`.

**CompilationError** (in `core/exceptions.py`): fields `phase`, `node_id`, `node_type`, `details`, `suggestion`.

## Execution Engine

See `engine/CLAUDE.md` for full architecture. Quick summary:

`WorkflowEngine(metrics, trace, only_node).run(workflow, shared)` → walks graph, handles template resolution, namespacing, batch, caching, tracing, progress per node.

## Template System

### TemplateResolver (`template_resolver.py`)

**Regex**: `r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"`

**Path support**: `${data.user.name}`, `${items[0].title}`, `${data[5].users[2]}`

**Escape syntax**: `$${var}` prevents resolution via regex negative lookbehind. Half-implemented: prevents resolution but does NOT strip the extra `$`. `has_templates("$${var}")` returns `True` (naive `${` check) but `extract_variables("$${var}")` returns empty set.

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

## Other Components

### WorkflowExecutor (`workflow_executor.py`)

Runtime node for nested workflow execution. Same syntax as any other node — non-reserved params are child inputs, child outputs auto-expose via namespace.

- **`workflow` param**: file paths or saved workflow names. **`workflow_ir`**: inline IR dict.
- **Params-as-inputs**: all non-reserved params become child inputs
- **Auto-outputs**: child's `## Outputs` exposed via namespace. No declarations → all non-internal keys exposed.
- **Storage modes**: `mapped` (default, isolated) and `shared` (parent storage directly)
- **Compile-once cache**: `_cached_workflow` + `_cached_workflow_ir_id` — compiles once per batch, reuses for sequential items
- **Circular detection** via `_pflow_stack`, **max depth** via `_pflow_depth` (default 10)
- **Relative paths** resolve from parent workflow directory via `_pflow_workflow_file`
- **Cross-cutting key propagation**: `_PROPAGATED_KEYS` — `__registry__`, `__progress_callback__`, `__mcp_pool__`, `__warnings__`, `_trace_collector`. Execution-scoped keys (`__execution__`, `__cache_hits__`, `__template_errors__`) NOT propagated.

### MemoizationCache (`cache.py`)

Persistent cross-run caching. SQLite at `~/.pflow/cache/cache.db`, WAL journal, zlib-compressed BLOBs.

- **Cache key**: `md5(config_hash + resolved_inputs)`. Batch nodes add semantic config + resolved items.
- **TTL**: 24h. **`read_enabled=False`**: writes still happen, reads return None (`--no-cache`).
- **Side-effecting nodes ARE cached** — intentional for iteration loop. `--no-cache` escape hatch.
- **Test isolation**: `conftest.py::isolate_pflow_config` monkey-patches to temp paths.
- **Integration**: Created by Runner, stored as `shared["__memoization_cache__"]`, consumed by `engine/instrumentation.py`.

### WorkflowTraceCollector (`workflow_trace.py`)

- **Format 2.0.0**: Tree-structured events with `node_output`, `template_resolutions`, `node_params`, `batch_items`, `sub_workflow_events`
- **Thread-safe LLM interception**: Reference counting + per-thread collector lookup. Child collectors skip interception.
- **Batch item tracing**: via `_batch_trace` shared-store accumulator (GIL-safe for parallel)
- **Sub-workflow tracing**: Child collectors created by `WorkflowExecutor`, events embedded as `sub_workflow_events`

### Output Resolver (`output_resolver.py`)

`populate_declared_outputs()` — maps namespaced outputs to root level. Raises `OutputResolutionError` for non-coalesce sources that can't be resolved. Coalesce (`??`) with all absent operands silently skipped.

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
- **Compile-once `id()` check** — only works for static `workflow_ir`
- **Two validation files** — `compilation/ir_preparation.py` (compiler-time) vs `core/workflow/validator.py` (pre-execution). Don't confuse them.
