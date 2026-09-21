# Compilation Package

`compile_workflow` transforms IR into bare nodes plus per-node configuration in
a `CompiledWorkflow`. Execution belongs to the engine.

## Find the owner

| Change or failure | File / symbol |
|---|---|
| Compile entry point | `compiler.py::compile_workflow` |
| Node construction/configuration | `compiler.py::_create_node_and_config` |
| Edges or start node | `compiler.py::_wire_nodes`, `_get_start_node` |
| Compile-time validation | `compile_validation.py::_prepare_compilation` |
| Input/default/environment resolution | `ir_preparation.py::prepare_inputs` |
| Dashed MCP server/tool name split | `mcp_resolution.py::_parse_mcp_node_type` |
| Dynamic node importing | `node_loader.py::import_node_class` |
| Cache defaults or side-effect classification | `compiler.py::_default_cache_for_node_type`, `is_side_effecting` |

## Construction constraints

`_create_node_and_config` installs the dynamic `node_id` attribute; `BaseNode`
does not provide it. Bare nodes receive static params at compilation and resolved
params during execution. Inject workflow/MCP special params **before**
`split_params` so they remain available in static configuration.
`inject_special_parameters` also serves `cli/commands/_probe_impl.py`.

Preserve parser source-line metadata through parameter splitting: code nodes
need it for error attribution. Cache hashing filters it later in
`runtime/engine/instrumentation.py::compute_node_config`.

A carry loop needs `TemplateConfig` even if round-one inputs are entirely static;
later rounds substitute carried templates. Batch and loop configurations are
mutually exclusive. Invalid batch bool/int/float values must raise
`CompilationError`, not silently use defaults.

Programmatic callers can bypass the normal pre-execution validator. Retry and
approval extraction therefore mirror the shared schema/gate checks. When changing
those contracts, inspect `_validate_retry_config`, `_extract_approval`, and their
shared validation owners rather than changing just one entry path.

## Validation and input boundaries

`core/workflow/validator.py::WorkflowValidator` owns pre-execution template
validation. This package uses `extract_node_outputs` for output checking but
does not run the template-validation passes. `_prepare_compilation` still owns
structure, data-flow, input, and output checks; compilation is not validation-free.
Its output-declaration checks can warn about dynamic outputs without rejecting them.

`_validate_data_flow_at_compile_time` passes `check_inputs=False`, since supplied
compiler params need not be declared IR inputs. Structured validation errors
cross this boundary through `CompilationError(wrapped_diagnostics=...)`; do not
flatten their paths, available fields, and suggestions into message strings.

Normal file/library resolution already resolves file references, but
`compile_workflow` retains idempotent resolution for direct callers, using
`initial_params['_pflow_workflow_file']` for the base directory.

`prepare_inputs` does not mutate supplied params. Its returned `defaults` contains
missing-input values **and coerced overrides of supplied values**. Resolution order
is supplied values → process environment → settings.env → declared default →
missing-required error; workflow-input coercion is lenient and warns on failure.
`_prepare_compilation` merges that mapping into `initial_params` and exposes it as
`resolved_defaults`; the runner applies it to shared storage. Child compile-cache
reuse must not overwrite current item inputs with a previous item's coerced values:
see `runtime/workflow_executor.py::WorkflowExecutor.exec` for its guarded seeding
and current limitation that per-item coercion is not rerun.
`only_node` belongs to the engine, not the compiler.

## Loading boundaries

Workflow host nodes bypass the registry and resolve directly to `WorkflowExecutor`;
they therefore do not appear as ordinary registry nodes. MCP entries use the
`virtual://mcp` marker. Server names can contain dashes, so MCP type parsing chooses
the longest known server match rather than splitting at the first dash.

Import `CompilationError` directly from `pflow.core.exceptions`, not through a
heavy compiler/runtime module. Re-exports exist for callers; they are not the
exception's ownership location.

## Focused tests

Under `tests/test_runtime/`: `test_compiler_basic.py` and
`test_flow_construction.py` cover compilation/wiring;
`test_compiler_llm_model.py` covers model injection;
`test_output_validation.py` covers output checks;
`test_prepare_inputs_coercion.py` and `test_settings_env_integration.py` cover
input boundaries. `tests/test_mcp/test_metadata_injection.py` covers special params.
