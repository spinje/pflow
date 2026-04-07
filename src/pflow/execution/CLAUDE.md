# Execution Module

Unified execution system. Both CLI and MCP call `WorkflowRunner().run()` which owns the full execution pipeline: resolution → validation → compilation → execution → resource lifecycle → error boundary.

## File Structure

```
src/pflow/execution/
├── __init__.py              # Exports: WorkflowRunner, ExecutionResult, RunnerConfig, etc.
├── runner.py                # THE shared execution pipeline (resolve→validate→compile→execute→return)
├── result.py                # Result types: ExecutionResult, ValidationResult, RunnerConfig, ResolvedWorkflow
├── workflow_resolver.py     # Unified workflow resolution (file, library, markdown, dict → ResolvedWorkflow)
├── executor_service.py      # Internal utility: error extraction helpers (_build_error_list, etc.)
├── execution_state.py       # Per-node execution state building (shared CLI/MCP)
└── formatters/              # Shared output formatters (return strings/dicts, NEVER print)
    ├── error_formatter.py
    ├── success_formatter.py
    ├── node_output_formatter.py
    ├── validation_formatter.py
    └── ... (13 formatters total, see formatters/CLAUDE.md)
```

## WorkflowRunner — Primary Entry Point

```python
class WorkflowRunner:
    def run(workflow, params, config, *, progress_callback=None, workflow_manager=None, workflow_name=None) -> ExecutionResult
    def validate(workflow, params, *, source_file_path=None) -> ValidationResult
```

**Stateless**: fresh instance per call. No mutable state on instance.

**Pipeline** (inside `run()`):
1. `_resolve()` — unified resolver (file, library, markdown, dict → `ResolvedWorkflow`)
2. `_resolve_file_references()` — external file refs in IR
3. `_fill_declared_defaults()` — fills declared inputs with defaults or placeholders so validation doesn't flag them as missing. Stripped before compilation.
4. `_validate()` — `WorkflowValidator.validate()`, once per execution
5. Create per-execution resources (MetricsCollector, TraceCollector, MCPConnectionPool, MemoizationCache)
6. `_compile_and_execute()` — `compile_workflow()` + `WorkflowEngine.run()`
7. `_cleanup()` — MCP pool shutdown, LLM interception cleanup, metrics end (in `finally`)

**Exception boundary**: `run()` catches ALL exceptions, wraps into `ExecutionResult`. Only `KeyboardInterrupt`/`SystemExit` propagate.

**Resource lifecycle**: Resources created in `run()` scope (not inside helpers) so `finally` always has them for cleanup. This prevents MCP server subprocess leaks.

## Result Types (result.py)

```python
@dataclass(frozen=True)
class RunnerConfig:
    trace_enabled: bool = True
    cache_enabled: bool = True
    verbose: bool = False
    only_node: Optional[str] = None

@dataclass(frozen=True)
class ResolvedWorkflow:
    ir: dict[str, Any]
    source: str  # "file", "library", "content", "direct"
    file_path: Optional[str] = None
    diagnostics: tuple[Diagnostic, ...] = ()

@dataclass
class ValidationResult:
    valid: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]: ...

    @property
    def warnings(self) -> list[Diagnostic]: ...

@dataclass
class ExecutionResult:
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    trace: Optional[Any] = None
    metrics: Optional[Any] = None

    @property
    def errors(self) -> list[Diagnostic]: ...

    @property
    def warnings(self) -> list[Diagnostic]: ...
```

## Unified Resolver (workflow_resolver.py)

`resolve_workflow(identifier: str | dict, wm=None) -> ResolvedWorkflow`

Merges CLI and MCP resolvers. Input types:
- `dict` → passthrough as `source="direct"`
- String with `\n` → parse as markdown, `source="content"`
- File path → load + parse, `source="file"`, `file_path=absolute_path`
- Saved name → load from library, `source="library"`, `file_path=absolute_path`

Raises `WorkflowNotFoundError` (with `similar_names` for suggestions) on not-found.

## Error Structure (Canonical Reference)

```python
Diagnostic(
    severity=Severity.ERROR,
    source="runtime",               # Where error originated
    message="Field 'title' required",
    node_id="create-issue",         # Which node failed
    context={
        "category": "api_validation",
        # Rich context from shared_store[node_id] — see executor_service.build_error_list()
    },
)
```

## Integration

**CLI**: `cli/main.py:execute_json_workflow()` calls `WorkflowRunner().run()`, passing `progress_callback=output_controller.create_progress_callback()` when progress is enabled. Handles: stdin routing, logging suppression, trace saving, display.

**MCP Server**: `mcp_server/services/execution_service.py` calls `WorkflowRunner().run()` without a progress callback (defaults to `None`). Three methods: `execute_workflow()`, `validate_workflow()`, `run_registry_node()`.

**Registry run**: `run_registry_node()` builds synthetic single-node IR, resolves `${ENV_VAR}` from env/settings, and routes through `WorkflowRunner().run()` with `RunnerConfig(cache_enabled=False)`.

## Testing

**Mock points**: `WorkflowRunner.run` (CLI/MCP tests), `WorkflowRunner._compile_and_execute` (bypass resolution/validation), `compile_workflow()` (compilation tests), `WorkflowValidator.validate` (warning plumbing).

**Key test files**:
- `tests/test_execution/test_runner.py` — Runner pipeline behavior
- `tests/test_integration/test_cli_mcp_parity.py` — CLI/MCP equivalence
- `tests/test_mcp_server/test_mcp_warnings.py` — validation warnings propagation

## Gotchas

- **Display-agnostic**: Never import Click or add CLI concerns here. Progress events flow through the optional `progress_callback` stored under `shared_store["__progress_callback__"]`.
- **Don't cache errors**: Never cache nodes that return "error" action.
- **Dict passthrough skips file ref guard**: When Runner receives dict input, `_check_inline_file_references()` is bypassed. CLI/MCP callers who pre-resolve to dict must handle this.
- **MCPNode error detection**: `MCPNode.post()` returns "default" action even on errors (workaround for missing error edges). Formatters also check for `"error"` key in outputs/shared_store.
- **`executor_service.py` is an internal utility**: Contains standalone error extraction functions (`build_error_list`, `determine_error_category`, etc.). The Runner delegates to these via `_build_errors()`. Not part of public API.
