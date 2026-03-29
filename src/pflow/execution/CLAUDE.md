# Execution Module

Unified execution system. Provides a display-agnostic abstraction between CLI/MCP and the runtime layer.

## File Structure

```
src/pflow/execution/
├── __init__.py              # Exports: OutputInterface, DisplayManager, ExecutionResult, WorkflowExecutorService
├── output_interface.py      # Protocol for display abstraction (CLI, MCP, etc.)
├── display_manager.py       # UX logic (context-aware messages, progress tracking)
├── executor_service.py      # Core execution service (compilation, error extraction)
├── workflow_execution.py    # THE unified execution function (validate→execute→return)
├── null_output.py           # Silent output (default when no OutputInterface)
├── execution_state.py       # Per-node execution state building (shared CLI/MCP)
└── formatters/              # Shared output formatters (return strings/dicts, NEVER print)
    ├── error_formatter.py
    ├── success_formatter.py
    ├── node_output_formatter.py
    ├── validation_formatter.py
    └── ... (13 formatters total, see formatters/CLAUDE.md)
```

**Internal functions** (require direct import): `execute_workflow()`.

## OutputInterface Protocol

Methods: `show_progress()`, `show_result()`, `show_error()`, `show_success()`, `show_warning()`, `create_node_callback()`, `is_interactive()`.

Implementations: `CliOutput` (cli/cli_output.py), `NullOutput` (null_output.py for MCP server).

## ExecutionResult (Canonical Reference)

```python
@dataclass
class ExecutionResult:
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
```

## Error Structure (Canonical Reference)

```python
{
    "source": "runtime",              # Where error originated
    "category": "api_validation",     # Error type
    "message": "Field 'title' required",
    "node_id": "create-issue",        # Which node failed

    # Rich context (extracted from shared_store[node_id] by executor_service)
    "status_code": 400,               # HTTP node
    "raw_response": {...},            # HTTP node: full response body
    "response_headers": {...},        # HTTP node
    "response_time": 1.234,           # HTTP node
    "mcp_error_details": {...},       # MCP node
    "mcp_error": {...},               # MCP node: result.error object
    "shell_command": "...",           # Shell node: command that failed
    "shell_exit_code": 1,            # Shell node: exit code
    "shell_stdout": "...",           # Shell node: stdout
    "shell_stderr": "...",           # Shell node: stderr
    "available_fields": [...]         # Template errors: available keys (max 20)
}
```

Rich error context extracted once in `_build_error_list()` (executor_service.py), available in CLI display, JSON output, and trace files.

## Execution Flow

1. Upfront validation
2. Direct execution
3. Fail fast on first error — return ExecutionResult

## Shared Formatters

**Pattern**: Formatters return strings or dicts, **never print**. Consumers (CLI, MCP) handle display. See `formatters/CLAUDE.md` for details.

Key formatters:
- `format_execution_errors()` — error formatting with sanitization
- `format_execution_success()` — success results with metrics
- `build_execution_steps()` (in `execution_state.py`) — per-node state including:
  - Shell metadata: `has_stderr`, `stderr`, `smart_handled`, `smart_handled_reason`
  - **Batch metadata**: `is_batch`, `batch_total`, `batch_success`, `batch_errors`, `batch_error_details` (capped at 5), `batch_errors_truncated` — added when node output contains `batch_metadata` key

**Progress indicators**: ✓ success (green), ❌ error (red), ⚠️ warning (stderr on exit 0), ↻ cached (blue/dimmed). Shell smart handling: [no matches] (grep/rg), [not found] (which/type).

## Integration

**CLI**: `cli/main.py` calls `execute_workflow()` with CliOutput. Key params: `workflow_ir`, `execution_params`, `output`, `workflow_manager`, `stdin_data`, `metrics_collector`, `trace_collector`.

**MCP Server**: `mcp_server/services/execution_service.py` calls `execute_workflow()` with NullOutput. Uses shared formatters for CLI/MCP parity.

**Runtime**: `executor_service.py` calls `compile_ir_to_flow()`. See `runtime/CLAUDE.md` for wrapper chain, reserved keys, and error categorization details.

**MCP Connection Pool**: `executor_service._initialize_shared_store()` creates `MCPConnectionPool()` and stores it in `shared["__mcp_pool__"]`. Shutdown happens in the `finally` block of `execute_workflow()`. MCP nodes look up this pool from shared store to reuse server connections across workflow steps.

**Memoization Cache**: `executor_service._initialize_shared_store()` creates `MemoizationCache()` and stores it in `shared["__memoization_cache__"]`. Consumed by `InstrumentedNodeWrapper._run()` for cross-run node output caching. The `--no-cache` flag (`__no_cache__` in execution_params) is **popped** before the shared store update and controls `read_enabled` on the cache instance. The `--only` flag (`__only_node__`) is **filtered** from the shared store update (not popped — the compiler reads it from `execution_params` as `initial_params`). This asymmetric handling is because `__no_cache__` is consumed by `_initialize_shared_store()` while `__only_node__` must survive for the compiler.

## Testing

**Mock points**: `OutputInterface`, `compile_ir_to_flow()` (main mock for execution tests), `model.prompt()` (LLM calls), `Registry`/`WorkflowManager`.

**Critical scenarios**: Successful execution, validation failure, runtime failure with rich error context, API warning detection, cache invalidation on parameter change.

## Gotchas

- **Display-agnostic**: Never import Click or add CLI concerns here. Use OutputInterface.
- **Don't cache errors**: Never cache nodes that return "error" action.
- **Exception re-raise**: `executor_service` re-raises `CompilationError` and `RuntimeError` (not caught). Other exceptions are caught and wrapped in error dicts. Callers must handle these two.
- **MCPNode error detection**: `MCPNode.post()` returns "default" action even on errors (workaround for missing error edges). Formatters also check for `"error"` key in outputs/shared_store.
