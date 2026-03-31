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

## compiler.py

The orchestrator. `compile_workflow()` is the primary entry point: parse IR dict, validate, instantiate bare nodes with configs, wire edges, build `CompiledWorkflow`.

**CompilationError** — Rich exception (in `core/exceptions.py`) with `phase`, `node_id`, `node_type`, `details`, `suggestion`. Re-exported from `compiler.py` for backward compat.

**Key functions**:
- `compile_workflow()` — primary pipeline. Returns `CompiledWorkflow` (no runtime state baked in).
- `_create_node_and_config()` — creates bare node + `NodeConfig`. Calls `split_params()` to separate template/static, builds `TemplateConfig` and `BatchConfig`.
- `_instantiate_nodes_for_workflow()` — loops nodes, returns `(nodes_dict, configs_dict)`.
- `inject_special_parameters()` — injects `__registry__` for workflow nodes, `__mcp_server__`/`__mcp_tool__` for MCP nodes.
- `_parse_ir_input()` — parses IR from JSON string or passes through dict.
- `_wire_nodes()` — connects bare nodes via `>>` and `-` operators.
- `_get_start_node()` — identifies entry point.

**Non-obvious behaviors**:
- LLM nodes without `model` get auto-injected default from `get_default_workflow_model()`.
- Source lines from markdown parser are threaded into params as `_<key>_source_line` for error reporting.
- Template resolution mode: from IR `template_resolution_mode` field OR global settings fallback.
- **`only_node`** is an engine parameter (not a compiler parameter). The Runner passes it to `WorkflowEngine`.

## compile_validation.py

Pre-compilation validation. Called once from `compile_workflow()` via `_prepare_compilation()`.

- `_prepare_compilation()` — orchestrates: structure validation -> template mode -> input prep -> output validation. Returns `(initial_params, warnings, resolved_defaults, env_param_names)` — template warnings are empty (template validation moved to WorkflowValidator in Task 138).
- ~~`display_validation_warnings()`~~ — Removed (Task 138). Validation warnings now route through `ExecutionResult.validation_warnings` via the Runner.
- `_validate_outputs()` — validates output declarations trace to node outputs.
- Lazy imports `CompilationError` from `compiler.py` to avoid circular dep.

## mcp_resolution.py

MCP node type parsing and validation.

- `_parse_mcp_node_type()` — greedy longest-match parser for `mcp-<server>-<tool>` (handles dashes in server names). Also consumed by `mcp_server/services/execution_service.py` via lazy import (acknowledged boundary violation).
- `_check_registry_for_mcp()` — checks if registry has real nodes; skips validation for test/mock registries.
- `_create_mcp_error_suggestion()` — 3-tier error suggestion: no tools -> similar tools -> available servers.

## node_loader.py

Dynamic node class importing via `import_node_class()`. Four import paths:
1. **Workflow**: special-cased to `WorkflowExecutor`
2. **User**: file-based via `spec_from_file_location`
3. **Core**: standard `importlib.import_module()`
4. **MCP**: virtual nodes (`"virtual://mcp"` file path)

## ir_preparation.py

IR structure validation and input preparation. Renamed from `workflow_validator.py`.

- `validate_ir_structure()` — validates basic IR shape (nodes/edges arrays).
- `prepare_inputs()` — validates inputs, resolves from fallback sources, coerces types. **5-tier precedence**: CLI args -> `os.environ` -> `settings.env` -> workflow default -> error if required.
- Only one `stdin: true` input allowed (validated here).

**WARNING**: A DIFFERENT `validator.py` exists at `core/workflow/validator.py` (pre-execution 8-step orchestrator, 7+ external consumers). Don't confuse them.

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
  └── ../template_validation.{ValidationWarning, extract_node_outputs, validate_workflow_templates}

Lazy imports (historical, could be cleaned up — see #185):
  compile_validation.py → compiler.CompilationError
  mcp_resolution.py     → compiler.CompilationError
  node_loader.py        → compiler.CompilationError
  ir_preparation.py     → compiler.CompilationError
```

## External Consumers

| Consumer | Symbols used |
|----------|-------------|
| `cli/main.py` | `prepare_inputs` |
| `cli/commands/registry_run.py` | `inject_special_parameters`, `import_node_class` |
| `execution/runner.py` | `compile_workflow`, `CompilationError` (via `runtime/__init__.py`) |
| `runtime/workflow_executor.py` | `compile_workflow`, `CompilationError` |

## Testing

Tests live in `tests/test_runtime/`:
- `test_compiler_basic.py` — imports `CompilationError`, `_parse_ir_input` from `compiler`
- `test_compiler_llm_model.py` — imports `_create_node_and_config` from `compiler`
- `test_compiler_template_wrapping.py` — tests `split_params` from `engine/template_resolution`
- `test_flow_construction.py` — imports `_get_start_node`, `_instantiate_nodes_for_workflow`, `_wire_nodes`
- `test_output_validation.py` — imports `_validate_outputs` from `compile_validation`
- `test_prepare_inputs_coercion.py`, `test_settings_env_integration.py` — import `prepare_inputs`
- `test_mcp/test_metadata_injection.py` — imports `inject_special_parameters`

## Known Issues

- **`_parse_mcp_node_type` placement**: Conceptually belongs in `mcp/` but raises `CompilationError`, anchoring it here.
- **Template validation stripped from compiler (Task 138)**: `validate_workflow_templates()` + `display_validation_warnings()` removed from `_prepare_compilation()`. Template validation now runs in WorkflowValidator (called by the Runner before compilation).

## Gotchas

- All four leaf modules (`compile_validation`, `mcp_resolution`, `node_loader`, `ir_preparation`) lazy-import `CompilationError` from `compiler.py` — moving `CompilationError` elsewhere would require updating all four.
- `inject_special_parameters` is a public name (no underscore) despite being prefixed with `_` pre-decomposition — renamed during extraction.
- `display_validation_warnings` was removed in Task 138 (validation warnings now in `ExecutionResult.validation_warnings`).
