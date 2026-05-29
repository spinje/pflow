# Compilation Package

Transforms workflow IR dicts into `CompiledWorkflow` — bare nodes + per-node `NodeConfig` metadata.

## File Structure

```
compilation/
├── __init__.py              # Re-exports public symbols
├── compiler.py              # Core orchestrator (parse→validate→create→wire→CompiledWorkflow)
├── compile_validation.py    # Pre-compilation validation orchestration
├── mcp_resolution.py        # MCP node type parsing and error suggestions
├── node_loader.py           # Dynamic node class importing (4 paths)
└── ir_preparation.py        # IR structure validation and input preparation
```

## Public API (via `__init__.py`)

`CompilationError`, `compile_workflow`, `inject_special_parameters`, `import_node_class`, `prepare_inputs`, `validate_ir_structure`

Also re-exported through `runtime/__init__.py`: `CompilationError`, `compile_workflow`, `import_node_class`, `CompiledWorkflow`, `WorkflowEngine`.

## compiler.py — The Orchestrator

### `compile_workflow()` pipeline

1. Parse IR (JSON string → dict, or pass through dict)
2. **Resolve external file references** (`code: @./code.py` → file contents). Uses `_pflow_workflow_file` from `initial_params` for relative path resolution. Idempotent on already-resolved IR (parent-side resolution now happens at the `resolve_workflow` / `resolve_sub_workflow` boundary).
3. `_prepare_compilation()` — validate structure, data flow, resolve inputs, validate outputs. Returns `(initial_params, warnings, resolved_defaults, env_param_names)`.
4. `_instantiate_nodes_for_workflow()` — create bare nodes + `NodeConfig` per node
5. `_wire_nodes()` — connect nodes via `>>` and `-` operators
6. `_get_start_node()` — first node in IR, or explicit `start_node` field
7. `_build_cache_block(ir_dict)` — promotes the optional top-level `## Cache` section into a frozen `CacheBlockIR` on `CompiledWorkflow.cache_block`. None when the workflow declares no `## Cache`.
8. Build and return `CompiledWorkflow`

### `_create_node_and_config()` — order matters

This is where bare nodes get created and configured. The step order is load-bearing:

1. Extract `node_id`, `node_type`, `params` from IR
2. Thread `_source_line` metadata into params (for error line numbers in code nodes)
3. Inject default LLM model if `node_type == "llm"` and no `model` in params
4. `import_node_class(node_type, registry)` → get class, `node_class()` → instantiate (no-arg constructor)
5. Set `node_instance.node_id = node_id` (engine uses this for config lookup — `BaseNode` doesn't define `node_id`, it's a dynamic attribute)
6. Extract `interface_metadata` from registry (for type validation)
7. Extract `optional_input_keys` for code nodes (AST scan of Python source for `T | None` annotations)
8. **`inject_special_parameters()`** — MUST happen before `split_params()`:
   - Workflow nodes: injects `__registry__` (the Registry instance)
   - MCP nodes: injects `__mcp_server__`, `__mcp_tool__` (server/tool names)
   - These go into `static_params` since they don't contain `${...}`
9. `split_params(params, expected_types)` → `(template_params, static_params)`
10. `node.set_params(static_params)` — node gets ONLY static params at compile time
11. Build `TemplateConfig` (if any templates) and `BatchConfig` (if batch)
12. Extract per-node cache fields (LLM nodes only): `_extract_prompt_cache_items` reads top-level `prompt_cache:` into a tuple of chunk names (rejects non-list and `tuple("string")` silent-splat); `_extract_prewarm` reads top-level `prewarm:` strict-bool. Both feed `NodeConfig.prompt_cache_items` / `NodeConfig.prewarm` (defaults: empty tuple / False).
13. Build and return `NodeConfig`

### Other functions

- `inject_special_parameters()` — public (used by `cli/commands/_probe_impl.py`). Injects `__registry__` for workflow nodes, `__mcp_server__`/`__mcp_tool__` for MCP nodes.
- `_wire_nodes()` — supports both `source`/`target` and `from`/`to` edge field names.
- `_get_start_node()` — uses IR `start_node` field if present, otherwise first node in array.
- `_coerce_bool/int/float()` — batch config type coercion. **Fail-fast**: invalid values raise `CompilationError` (e.g., `max_concurrent: "abc"` is a compile error, not a silent default).

### Non-obvious behaviors

- **Per-node cache default is type-based** — `NodeConfig.cache_enabled` is set from `node_data.get("cache", _default_cache_for_node_type(node_type))`. `_default_cache_for_node_type` returns `True` only for `node_type == "llm"`; every other type defaults to `False` (side-effecting or external-state, unsafe to memoize). Explicit `cache:` always wins. Single source of truth — don't recompute the default elsewhere.
- **`only_node` is NOT a compiler parameter** — it's an engine parameter. The Runner passes it to `WorkflowEngine`.
- **`resolved_defaults` vs `initial_params`**: After `_prepare_compilation`, `initial_params` contains ALL values (user-provided + defaults + `__template_resolution_mode__`). `resolved_defaults` contains ONLY the defaults from `prepare_inputs()` (not user-provided values). This distinction matters: when seeding the shared store, defaults must not override user values. The Runner seeds user params first, then `resolved_defaults`.

## compile_validation.py

Pre-compilation validation. Called once from `compile_workflow()` via `_prepare_compilation()`.

- `_prepare_compilation()` — orchestrates: structure validation → data flow → template mode → input prep → output validation. Returns `(initial_params, warnings, resolved_defaults, env_param_names)`. Warnings are always `[]` (template validation is a pre-execution concern, owned by `WorkflowValidator`, not the compiler).
- `_validate_outputs()` — validates output declarations trace to node outputs. Warnings only, not errors (nodes may write dynamic keys).
- `_validate_data_flow_at_compile_time()` — passes `check_inputs=False` because the compiler has `initial_params` containing variables not declared in IR inputs. Filters `validate_data_flow()` output to `Severity.ERROR` explicitly before raising (guards against future warning-severity producers in `data_flow.py`).
- `_get_template_resolution_mode()` — reads from IR `template_resolution_mode` field, falls back to global settings.

**Rich diagnostic pass-through across the compile boundary**: when `_validate_data_flow_at_compile_time()` finds errors, it raises `CompilationError(..., wrapped_diagnostics=errors)`. `CompilationError.to_diagnostics()` returns `wrapped_diagnostics` verbatim when set (instead of producing a single generic compilation diagnostic), so the structured path/similar_names/available_fields/suggestions from the data-flow producers reach the user unchanged. Any new compiler-time validation that produces a list of structured diagnostics should use this kwarg rather than flattening to a bullet-list message string.

## mcp_resolution.py

MCP node type parsing and validation.

- **Node type format**: `mcp-<server>-<tool>`. Server names can contain dashes — `_parse_mcp_node_type()` uses greedy longest-match against known servers to find the split point.
- **Virtual path marker**: `"virtual://mcp"` in registry metadata distinguishes MCP nodes from real file-based nodes.
- **Parameters injected**: `__mcp_server__` and `__mcp_tool__` added to node params by `inject_special_parameters()` in `compiler.py`.
- **Validation skip**: When registry has no real nodes for this MCP type (test/mock registries), validation is skipped — `_check_registry_for_mcp()`.
- **Error suggestions**: 3-tier system via `_create_mcp_error_suggestion()` — no MCP tools registered → similar tool names → available servers.
- **Boundary violation**: `_parse_mcp_node_type()` also consumed by `mcp_server/services/execution_service.py` via lazy import.

## node_loader.py

Dynamic node class importing via `import_node_class()`. Four import paths:
1. **Workflow**: `node_type == "workflow"` → returns `WorkflowExecutor` directly, **bypasses registry entirely**. This means `workflow` type nodes never appear in the registry.
2. **User**: `type == "user"` with real `file_path` → `spec_from_file_location`
3. **Core**: standard `importlib.import_module()`
4. **MCP**: virtual nodes with `"virtual://mcp"` file path → standard import (MCP nodes are regular Python classes)

All paths validate the loaded class inherits from `BaseNode`. Raises `CompilationError` with phase-specific context on failure.

## ir_preparation.py

IR structure validation and input preparation.

- `validate_ir_structure()` — validates basic IR shape (nodes/edges arrays). Compiler prerequisite — without it, `ir_dict["nodes"]` crashes.
- `prepare_inputs()` — validates inputs, resolves from fallback sources, coerces types. Returns `(errors, defaults, env_param_names)`. **Does NOT mutate `provided_params`** — returns defaults to be applied by the caller.
  - **5-tier precedence**: CLI args → `os.environ` → `settings.env` → workflow default → error if required
  - Only one `stdin: true` input allowed
  - Type coercion via `coerce_workflow_input()` — lenient (warns on failure, doesn't error)

**WARNING**: A DIFFERENT `validator.py` exists at `core/workflow/validator.py` (pre-execution 10-step orchestrator, 7+ external consumers). Don't confuse them.

## Dependency Graph (no cycles at import time)

```
compiler.py
  ├── core.exceptions.CompilationError
  ├── runtime.engine.types.{BatchConfig, CompiledWorkflow, NodeConfig, TemplateConfig}
  ├── compile_validation._prepare_compilation
  ├── mcp_resolution.{_check_registry_for_mcp, _create_mcp_error_suggestion, _parse_mcp_node_type}
  ├── node_loader.import_node_class
  └── runtime.engine.template_resolution.{build_type_cache, split_params}

compile_validation.py
  ├── ir_preparation.{prepare_inputs, validate_ir_structure}
  └── ../template_validation.{extract_node_outputs}

All four sibling modules import CompilationError directly from core.exceptions (module-level):
  compile_validation.py → core.exceptions.CompilationError
  mcp_resolution.py     → core.exceptions.CompilationError
  node_loader.py        → core.exceptions.CompilationError
  ir_preparation.py     → core.exceptions.CompilationError
```

## External Consumers

| Consumer | Symbols used |
|----------|-------------|
| `cli/commands/_probe_impl.py` | `inject_special_parameters`, `import_node_class` |
| `execution/runner.py` | `compile_workflow`, `CompilationError` (via `runtime/__init__.py`) |
| `runtime/workflow_executor.py` | `compile_workflow`, `CompilationError` |

## Testing

Tests in `tests/test_runtime/`:
- `test_compiler_basic.py` — `CompilationError`, `_parse_ir_input`
- `test_compiler_llm_model.py` — `_create_node_and_config`
- `test_compiler_template_wrapping.py` — `split_params` from `engine/template_resolution`
- `test_flow_construction.py` — `_get_start_node`, `_instantiate_nodes_for_workflow`, `_wire_nodes`
- `test_output_validation.py` — `_validate_outputs`
- `test_prepare_inputs_coercion.py`, `test_settings_env_integration.py` — `prepare_inputs`
- `test_mcp/test_metadata_injection.py` — `inject_special_parameters`

## Gotchas

- **`CompilationError` lives in `core/exceptions.py`** — `compiler.py` and `runtime/__init__.py` re-export it. All four sibling modules in this package import it directly from `core.exceptions` at module level. `core/exceptions.py` is a leaf module with only stdlib imports, so module-level imports are always safe — do not lazy-import exception classes from it.
- **`node.node_id` is a dynamic attribute** — `BaseNode.__init__` doesn't define it. The compiler sets it after instantiation (`node_instance.node_id = node_id`). If a node enters the graph without this attribute, the engine raises a clear error.
- **`_parse_mcp_node_type` placement**: Conceptually belongs in `mcp/` but raises `CompilationError`, anchoring it in the compilation package.
- **Batch config coercion is fail-fast**: `_coerce_bool/int/float` raise `CompilationError` on invalid values. Invalid `max_concurrent: "abc"` is a compile error, not a silent default.
- **`prepare_inputs` and `validate_ir_structure` are re-exported** from `__init__.py` for test code that imports them directly. In production, only `compile_validation.py` calls them.
