# Execution Module

Unified execution and repair system. Provides a display-agnostic abstraction between CLI/MCP and the runtime layer. Implements checkpoint-based resume and LLM-powered repair.

**Core principle**: Resume-based repair avoids re-executing successful nodes by checkpointing and resuming from failure points.

## File Structure

```
src/pflow/execution/
├── __init__.py              # Exports: OutputInterface, DisplayManager, ExecutionResult, WorkflowExecutorService
├── output_interface.py      # Protocol for display abstraction (CLI, MCP, etc.)
├── display_manager.py       # UX logic (context-aware messages, progress tracking)
├── executor_service.py      # Core execution service (compilation, error extraction)
├── workflow_execution.py    # THE unified execution function (validation→repair→resume)
├── repair_service.py        # LLM-based workflow repair
├── null_output.py           # Silent output (default when no OutputInterface)
├── workflow_diff.py         # Workflow modification tracking for [repaired] indicator
├── execution_state.py       # Per-node execution state building (shared CLI/MCP)
└── formatters/              # Shared output formatters (return strings/dicts, NEVER print)
    ├── error_formatter.py
    ├── success_formatter.py
    ├── node_output_formatter.py
    ├── validation_formatter.py
    └── ... (10 formatters total)
```

**Internal functions** (require direct import): `execute_workflow()`, `repair_workflow()`, `repair_workflow_with_validation()`, `compute_workflow_diff()`.

## OutputInterface Protocol

Methods: `show_progress()`, `show_result()`, `show_error()`, `show_success()`, `create_node_callback()`, `is_interactive()`.

Implementations: `CliOutput` (cli/cli_output.py), `NullOutput` (null_output.py for MCP server).

## ExecutionResult (Canonical Reference)

```python
@dataclass
class ExecutionResult:
    success: bool
    shared_after: dict[str, Any]      # Final shared store state
    errors: list[dict[str, Any]]      # Structured error data (see error structure below)
    action_result: Optional[str]       # Flow action (e.g., "error")
    node_count: int                    # Number of nodes executed
    duration: float                    # Total execution time
    output_data: Optional[str]         # Extracted output
    metrics_summary: Optional[dict]    # LLM usage metrics
    repaired_workflow_ir: Optional[dict]  # Repaired workflow if applicable
    status: str                       # Tri-state: "success"/"degraded"/"failed"
    warnings: dict[str, str]           # Node warnings for degraded status
```

## Error Structure for Repair (Canonical Reference)

```python
{
    "source": "runtime",              # Where error originated
    "category": "api_validation",     # Error type → determines repair strategy
    "message": "Field 'title' required",
    "node_id": "create-issue",        # Which node failed
    "fixable": True,                  # Whether repair should attempt

    # Rich context (extracted from shared_store[node_id] by executor_service)
    "status_code": 400,               # HTTP node
    "raw_response": {...},            # HTTP node: full response body
    "response_headers": {...},        # HTTP node
    "response_time": 1.234,           # HTTP node
    "mcp_error_details": {...},       # MCP node
    "mcp_error": {...},               # MCP node: result.error object
    "available_fields": [...]         # Template errors: available keys (max 20)

    # After repair attempt
    "repair_attempted": True,
    "repair_reason": "Could not fix",
}
```

Rich error context extracted once in `_format_errors_for_result()` (executor_service.py), available in CLI display, JSON output, repair service, and trace files.

## Execution Flows

### Default (without --auto-repair)

1. Upfront validation
2. Direct execution
3. Fail fast on first error — return ExecutionResult

### With Repair Enabled (--auto-repair, currently GATED — Task 107)

1. **Validation phase**: Validate, repair if needed (up to 3 attempts)
2. **Execution phase**: Execute with checkpoint tracking
3. **Repair loop**: On failure → repair IR → resume from checkpoint (up to 3 loops × 3 internal attempts)
4. **Loop detection**: Normalizes error messages (removes timestamps, IDs), compares signatures between attempts, stops if same error persists

**Key innovation**: `execute_workflow()` is a single function where repair is just a boolean flag, not a separate code path.

**Checkpoint resume**: Uses `shared["__execution__"]` structure from runtime (see `runtime/CLAUDE.md` for reserved key reference). Completed nodes skip re-execution via MD5 hash matching.

## Repair Service (`repair_service.py`)

- Uses `anthropic/claude-sonnet-4-0` model
- Leverages planner cache chunks (`__planner_cache_chunks__`) for context continuity
- Validates repairs before returning
- **Flow-centric philosophy**: "The error occurred at one node, but the fix might be in a different node"

**Error categories**: `api_validation`, `template_error`, `execution_failure`, `static_validation`.

**Repair vs warning** (determined by runtime error categorization — see `runtime/CLAUDE.md`):
- Validation/template errors → always repair
- API business errors → warning only (non-repairable)
- Resource errors → warning only

## Workflow Diff (`workflow_diff.py`)

`compute_workflow_diff()` compares two workflow IRs, returns `node_id → list of changes`. Detects: parameter additions, command modifications, prompt updates, node additions/removals, type changes. Used for `[repaired]` visual indicator.

## Shared Formatters

**Pattern**: Formatters return strings or dicts, **never print**. Consumers (CLI, MCP) handle display.

Key formatters:
- `format_execution_errors()` — error formatting with sanitization
- `format_execution_success()` — success results with metrics
- `build_execution_steps()` (in `execution_state.py`) — per-node state including shell metadata: `has_stderr`, `stderr`, `smart_handled`, `smart_handled_reason`

**Progress indicators**: ✓ success (green), ❌ error (red), ⚠️ warning (stderr on exit 0), ↻ cached (blue/dimmed), [repaired] modified (cyan). Shell smart handling: [no matches] (grep/rg), [not found] (which/type).

## Integration

**CLI**: `cli/main.py` calls `execute_workflow()` with CliOutput. Key params: `workflow_ir`, `execution_params` (includes `__planner_cache_chunks__`), `enable_repair`, `output`, `workflow_manager`, `stdin_data`, `metrics_collector`, `trace_collector`.

**MCP Server**: `mcp_server/services/execution_service.py` calls `execute_workflow()` with NullOutput. Uses shared formatters for CLI/MCP parity.

**Runtime**: `executor_service.py` calls `compile_ir_to_flow()`. See `runtime/CLAUDE.md` for wrapper chain, reserved keys, and error categorization details.

## Testing

**Mock points**: `OutputInterface`, `compile_ir_to_flow()` (main mock for execution tests), `model.prompt()` (LLM calls), `Registry`/`WorkflowManager`.

**Critical scenarios**: Successful execution, validation repair → success, runtime repair → resume → success, loop detection (same error twice), API warning detection (skip repair), cache invalidation on parameter change, checkpoint persistence.

## Gotchas

- **Display-agnostic**: Never import Click or add CLI concerns here. Use OutputInterface.
- **Repair fixes upstream nodes**: The failing node isn't always where the fix goes. The repair service modifies the full IR.
- **Loop detection matters**: Without it, repair can attempt up to 27 times (3 validation × 3 runtime × 3 internal). Always check error signatures.
- **Don't cache errors**: Never cache nodes that return "error" action.
- **Don't modify checkpoint during resume**: `__execution__` is read-only during resume.
- **Track modified nodes**: Always record nodes changed during repair for `[repaired]` UI feedback.
