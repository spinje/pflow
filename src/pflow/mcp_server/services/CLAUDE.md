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

## Services (7)

- **BaseService** — Pattern enforcement via `@ensure_stateless` decorator
- **DiscoveryService** — Wraps `discover_workflow()` and `discover_components()` plain functions
- **ExecutionService** — Execute, validate, save workflows + run registry nodes (largest service)
- **FieldService** — Read cached fields from previous `registry_run` via ExecutionCache + TemplateResolver. **Not exported from `__init__.py`** — imported directly in execution_tools.py.
- **RegistryService** — Node describe, list/search via `build_component_context()` and `Registry.search()`
- **WorkflowService** — Workflow list/describe with shared formatters, "did you mean" suggestions
- **SettingsService** — Environment variable CRUD via SettingsManager (used by disabled settings_tools)

## Discovery Integration (DiscoveryService)

Discovery services call plain functions that return typed dataclasses:

```python
from pflow.core.workflow.discovery import discover_workflow
result = discover_workflow(query, workflow_manager=WorkflowManager())
# result is WorkflowMatch(found, workflow_name, confidence, reasoning, workflow)
```

Model defaults to `get_model_for_feature("discovery")`.

## Error Handling

Services raise exceptions — tools layer lets MCP handle conversion automatically.

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

### Use `import_node_class()` for Node Loading

Registry stores `{"module": "path.to.file", "class_name": "NodeClass"}`. Don't try raw `importlib` — use the proven helper:

```python
from pflow.runtime.compiler import import_node_class
NodeClass = import_node_class(node_type, registry)
```

### Dummy Parameters for Validation

Validation fails on templates without parameter values. Use `generate_dummy_parameters()` to create `__validation_placeholder__` values:

```python
dummy = generate_dummy_parameters(workflow_ir.get("inputs", {}))
errors, warnings = WorkflowValidator.validate(workflow_ir, extracted_params=dummy)
```

### ExecutionResult Field Sync (Hard-Won)

When `format_execution_success()` adds new parameters, **both** CLI and MCP call sites must be updated:
- CLI: `cli/main.py` (search for `format_execution_success`)
- MCP: `execution_service.py` (search for `format_execution_success`)

Example from Task 85: `status` and `warnings` fields were added. Missing either call site causes silent data loss.

## Testing

Mock at service layer (service methods return predictable results). Integration tests use real Registry/WorkflowManager. See `mcp_server/CLAUDE.md` for test file listing.

## When Adding New Service Methods

1. Signature: `@classmethod` + `@ensure_stateless` + return type annotation
2. Fresh instances: `WorkflowManager()`, `Registry()` inside method body
3. Local formatter imports: `from pflow.execution.formatters.X import format_Y`
4. Validate inputs: check existence, include "did you mean" suggestions via `format_did_you_mean()`
5. Use shared formatters for output: `return format_Y(result)`
6. Let exceptions propagate — tool layer handles conversion to MCP errors
