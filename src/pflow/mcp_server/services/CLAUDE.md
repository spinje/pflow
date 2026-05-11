# MCP Services Layer

Stateless business logic layer that bridges async MCP tools with synchronous pflow core. All methods are classmethods that create fresh instances per request, ensuring thread safety without locks.

## Stateless Pattern

**Every service MUST:**
1. Inherit from `BaseService`
2. Use `@classmethod` + `@ensure_stateless` decorator
3. Create fresh instances inside method body (never reuse)
4. Never store instance variables

**What breaks it** (all of these cause stale data or race conditions):
- Module-level singletons: `_registry = Registry()`
- Instance variables: `self._cache = {}`
- Reusing instances: `_manager = WorkflowManager()` at class level

See `mcp_server/CLAUDE.md` for detailed explanation of why this matters.

## Services (6)

- **BaseService** — Pattern enforcement via `@ensure_stateless` decorator
- **DiscoveryService** — Wraps `find_workflow()` and `find_components()` plain functions
- **ExecutionService** — Execute, validate, plan, save, analyze-cache workflows + run registry nodes (largest service). `analyze_cache(workflow, parameters)` mirrors `pflow analyze-cache --format=json`; returns the `render_json(analyze(...))` payload as a dict.
- **FieldService** — Read cached fields from previous `registry_run` via ExecutionCache + TemplateResolver. **Not exported from `__init__.py`** — imported directly in execution_tools.py.
- **RegistryService** — Node describe, list/search via `build_component_context()` and `Registry.search()`
- **WorkflowService** — Workflow list/describe with shared formatters, "did you mean" suggestions

## Discovery Integration (DiscoveryService)

Discovery services call plain functions that return typed dataclasses:

```python
from pflow.core.workflow.discovery import find_workflow
result = find_workflow(query, workflow_manager=WorkflowManager())
# result is WorkflowMatch(found, workflow_name, confidence, reasoning, workflow)
```

Model defaults to `get_model_for_feature("discovery")`.

## Error Handling

Services raise exceptions. Self-describing exceptions (anything with `to_diagnostics()` — all `PflowError` subclasses plus `MaxNodeVisitsError`) are rendered by the `PflowMCP.call_tool` override (`server.py`) via the shared `exception_to_diagnostics()` + `format_diagnostic()` pipeline, producing structured `CallToolResult(isError=True)` output. Bare `ValueError` / `RuntimeError` / `TypeError` / `FileExistsError` with pre-formatted message text pass through FastMCP's default handling to preserve existing rich output. Producer bugs (`AttributeError`, `KeyError`, etc.) are always rendered.

**Exception types used:**
- `ValueError` — Invalid input, not found, validation failures
- `FileExistsError` — Workflow name conflicts (save without force)
- `RuntimeError` — Execution failures
- `TypeError` — Unexpected data types (formatter safety)

**Always include suggestions**: When raising ValueError for "not found", use `format_did_you_mean()` to suggest alternatives.

## Critical Rules

### Type Narrow Before Calling Formatters

Formatters expect specific types and crash on wrong input. Always `isinstance()` check before calling:

```python
if not isinstance(result, dict):
    raise TypeError(f"Expected dict, got {type(result)}")
return format_discovery_result(result)  # Now safe
```

This pattern appears in discovery_service.py and is required anywhere formatters are used.

### Consistent Return Types

Service methods must return one type consistently. Never return dict from one branch and str from another when the signature says `-> str`.

### Workflow Execution / Planning via WorkflowRunner

Service methods no longer import node classes directly. Execution routes through `WorkflowRunner().run()`, validation through `WorkflowRunner().validate()`, and dry-run planning through `WorkflowRunner().plan()`. `plan_workflow()` must return the CLI dry-run JSON shape via `format_plan_json(plan)`. For `run_registry_node()`, build a single-node IR dict and call the Runner — the compilation pipeline handles node loading internally.

### Dummy Parameters for Validation

Validation fails on templates without parameter values. Use `generate_dummy_parameters()` to create `__validation_placeholder__` values:

```python
from pflow.core.diagnostic import Severity

dummy = generate_dummy_parameters(workflow_ir.get("inputs", {}))
diagnostics = WorkflowValidator.validate(workflow_ir, extracted_params=dummy)
errors = [d for d in diagnostics if d.severity == Severity.ERROR]
```

### CLI/MCP parity — formatter call sites come in pairs

Every shared formatter has two call sites: CLI (`cli/main.py`) and MCP (`execution_service.py`). Adding a new parameter to a formatter WITHOUT updating both sides causes silent output divergence — the CLI gets the new field, MCP doesn't, and the error surfaces as "MCP output is missing X". Grep both files for the formatter name when modifying its signature.

Same rule for rendering exceptions: the MCP `save_workflow` path relies on `save_workflow_with_options()` for parse + validation + save, then catches `WorkflowValidationError` and renders it via `format_validation_failure(e.validation_errors)` — parity with the CLI save/validate paths. `WorkflowValidationError.validation_warnings` is a constructor kwarg (not a dynamic attribute), so warnings survive the exception boundary without special plumbing.

## Testing

Mock at service layer (service methods return predictable results). Integration tests use real Registry/WorkflowManager. See `mcp_server/CLAUDE.md` for test file listing.

## When Adding New Service Methods

1. Signature: `@classmethod` + `@ensure_stateless` + return type annotation
2. Fresh instances: `WorkflowManager()`, `Registry()` inside method body
3. Local formatter imports: `from pflow.execution.formatters.X import format_Y`
4. Validate inputs: check existence, include "did you mean" suggestions via `format_did_you_mean()`
5. Use shared formatters for output: `return format_Y(result)`
6. Let exceptions propagate — `PflowMCP.call_tool` renders self-describing exceptions via the shared Diagnostic pipeline and passes hand-rolled rich-text exceptions through unchanged.
