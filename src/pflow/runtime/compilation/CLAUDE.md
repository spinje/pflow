# Compilation Package

Transforms workflow IR dicts into executable PocketFlow Flow objects. Decomposed from a single `compiler.py` (1,310 lines) into focused modules.

## File Structure

```
compilation/
├── __init__.py              # Re-exports 7 public symbols
├── compiler.py             ~725 lines — core orchestrator (parse→validate→create→wire→Flow)
├── compile_validation.py   ~320 lines — pre-compilation validation orchestration
├── mcp_resolution.py       ~170 lines — MCP node type parsing and error suggestions
├── node_loader.py          ~155 lines — dynamic node class importing (4 paths)
└── ir_preparation.py       ~320 lines — IR structure validation and input preparation
```

## Public API (via `__init__.py`)

`CompilationError`, `compile_ir_to_flow`, `inject_special_parameters`, `import_node_class`, `prepare_inputs`, `validate_ir_structure`

Also re-exported through `runtime/__init__.py`: `CompilationError`, `compile_ir_to_flow`, `import_node_class`.

## compiler.py

The orchestrator. `compile_ir_to_flow()` is the main entry point: parse IR dict, validate, instantiate nodes, wire edges, build Flow.

**CompilationError** — Rich exception with `phase`, `node_id`, `node_type`, `details`, `suggestion`. The only `CompilationError` in the codebase is this one (the vestigial copy in `core/user_errors.py` was removed in Task 137).

**Key functions**:
- `compile_ir_to_flow()` — main pipeline. Delegates to extracted helpers for run hooks and --only behavior.
- `_apply_run_hooks(flow, ir_dict, only_node=None)` — monkey-patches `flow.run` for output resolution, visit count reset, and `--only` metadata. When `only_node` is set: stores `__execution__["only_node"]` and skips `populate_declared_outputs()` (prevents `OutputResolutionError` from unresolved downstream outputs). Extracted from `compile_ir_to_flow()` for C901 complexity.
- `_apply_only_node_stop(flow, only_node_id, nodes)` — monkey-patches `flow.get_next_node` to return None after target node (implements `--only` CLI flag). Validates target exists, raises `CompilationError` with available node names on invalid target.
- `inject_special_parameters()` — injects `__registry__` for workflow nodes, `__mcp_server__`/`__mcp_tool__` for MCP nodes. Delegates to `mcp_resolution` for MCP validation.
- `_create_single_node()` — full node factory: import class, instantiate, apply wrapper chain (template -> namespace -> batch -> instrumentation), inject special params.
- `_parse_ir_input()` — parses IR from JSON string or passes through dict.

**Non-obvious behaviors**:
- LLM nodes without `model` get auto-injected default from `get_default_workflow_model()`.
- Source lines from markdown parser are threaded into params as `_<key>_source_line` for error reporting.
- Template resolution mode: from IR `template_resolution_mode` field OR global settings fallback.
- **`only_node`** is passed as an explicit parameter to `compile_ir_to_flow()` by the Runner. The compiler passes it through to `_apply_run_hooks()` and `_apply_only_node_stop()`. It never enters `initial_params` or the shared store.

## compile_validation.py

Pre-compilation validation. Called once from `compile_ir_to_flow()` via `_prepare_compilation()`.

- `_prepare_compilation()` — orchestrates: structure validation -> template mode -> input prep -> output validation. Returns `(initial_params, [])` — template warnings are empty (template validation moved to WorkflowValidator in Task 138).
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
  ├── compile_validation._prepare_compilation
  ├── mcp_resolution.{_check_registry_for_mcp, _create_mcp_error_suggestion, _parse_mcp_node_type}
  ├── node_loader.import_node_class
  ├── ../template_resolver.TemplateResolver
  └── ../wrappers.{NamespacedNodeWrapper, TemplateAwareNodeWrapper}

compile_validation.py
  ├── ir_preparation.{prepare_inputs, validate_ir_structure}
  └── ../template_validation.{ValidationWarning, extract_node_outputs, validate_workflow_templates}

Lazy imports (break cycles):
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
| `execution/runner.py` | `compile_ir_to_flow`, `CompilationError` (via `runtime/__init__.py`) |
| `mcp_server/services/execution_service.py` | (none — routes through WorkflowRunner now) |

## Testing

Tests live in `tests/test_runtime/`:
- `test_compiler_basic.py` — imports `CompilationError`, `_parse_ir_input` from `compiler`; `validate_ir_structure` from `ir_preparation`
- `test_compiler_llm_model.py` — imports `_create_single_node` from `compiler`
- `test_compiler_template_wrapping.py` — imports `_apply_template_wrapping` from `compiler`
- `test_flow_construction.py` — imports `_get_start_node`, `_instantiate_nodes`, `_wire_nodes` from `compiler`
- `test_output_validation.py` — imports `_validate_outputs` from `compile_validation`
- `test_prepare_inputs_coercion.py`, `test_settings_env_integration.py` — import `prepare_inputs` from `ir_preparation`
- `test_mcp/test_metadata_injection.py` — imports `inject_special_parameters` from `compiler`

## Known Issues

- **`_parse_mcp_node_type` placement**: Conceptually belongs in `mcp/` but raises `CompilationError`, anchoring it here.
- **Template validation stripped from compiler (Task 138)**: `validate_workflow_templates()` + `display_validation_warnings()` removed from `_prepare_compilation()`. Template validation now runs in WorkflowValidator (called by the Runner before compilation).

## Gotchas

- All four leaf modules (`compile_validation`, `mcp_resolution`, `node_loader`, `ir_preparation`) lazy-import `CompilationError` from `compiler.py` — moving `CompilationError` elsewhere would require updating all four.
- `inject_special_parameters` is a public name (no underscore) despite being prefixed with `_` pre-decomposition — renamed during extraction.
- `display_validation_warnings` was removed in Task 138 (validation warnings now in `ExecutionResult.validation_warnings`).
