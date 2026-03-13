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
    └── ... (13 formatters total, see formatters/CLAUDE.md)
```

**Internal functions** (require direct import): `execute_workflow()`, `repair_workflow()`, `repair_workflow_with_validation()`, `compute_workflow_diff()`.

## OutputInterface Protocol

Methods: `show_progress()`, `show_result()`, `show_error()`, `show_success()`, `show_warning()`, `create_node_callback()`, `is_interactive()`.

Implementations: `CliOutput` (cli/cli_output.py), `NullOutput` (null_output.py for MCP server).

## ExecutionResult (Canonical Reference)

```python
@dataclass
class ExecutionResult:
    success: bool                                          # Keep for backward compat
    status: WorkflowStatus = WorkflowStatus.SUCCESS        # Tri-state: SUCCESS/DEGRADED/FAILED
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)  # api_warning, template_resolution
    action_result: Optional[str] = None                    # Flow action (e.g., "error")
    node_count: int = 0
    duration: float = 0.0
    output_data: Optional[str] = None                      # Extracted output
    metrics_summary: Optional[dict[str, Any]] = None       # LLM usage metrics
    repaired_workflow_ir: Optional[dict] = None             # Repaired workflow if applicable
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
    "shell_command": "...",           # Shell node: command that failed
    "shell_exit_code": 1,            # Shell node: exit code
    "shell_stdout": "...",           # Shell node: stdout
    "shell_stderr": "...",           # Shell node: stderr
    "available_fields": [...]         # Template errors: available keys (max 20)

    # After repair attempt
    "repair_attempted": True,
    "repair_reason": "Could not fix",
}
```

Rich error context extracted once in `_build_error_list()` (executor_service.py), available in CLI display, JSON output, repair service, and trace files.

## Execution Flows

### Default (without --auto-repair)

1. Upfront validation
2. Direct execution
3. Fail fast on first error — return ExecutionResult

### With Repair Enabled (currently GATED at CLI/MCP layer — Task 107)

> **Gating location**: `execute_workflow()` defaults to `enable_repair=True`, but CLI forces it to `False` (cli/main.py ~line 3045, `--auto-repair` flag is hidden) and MCP server also passes `False`. The function itself is not gated.

1. **Validation phase**: Validate, repair if needed (up to 3 attempts)
2. **Execution phase**: Execute with checkpoint tracking
3. **Repair loop**: On failure → repair IR → resume from checkpoint (up to 3 loops × 3 internal attempts)
4. **Loop detection**: Normalizes error messages (removes timestamps, IDs), compares signatures between attempts, stops if same error persists

**Key innovation**: `execute_workflow()` is a single function where repair is just a boolean flag, not a separate code path.

**Checkpoint resume**: Uses `shared["__execution__"]` structure from runtime (see `runtime/CLAUDE.md` for reserved key reference). Completed nodes skip re-execution via MD5 hash matching.

## Repair Service (`repair_service.py`)

- Model: auto-detected via `get_default_llm_model()`, falls back to `anthropic/claude-sonnet-4-5`. Configurable via `repair_model` param.
- Leverages planner cache chunks (`__planner_cache_chunks__`) for context continuity
- Validates repairs before returning
- **Flow-centric philosophy**: "The error occurred at one node, but the fix might be in a different node"
- **Depends on planning module**: Imports `FlowIR` from `pflow.planning.ir_models` for structured output schema

**Dual model handling** (different code paths):
- **Anthropic models**: Structured output via FlowIR Pydantic schema, temperature=0.0, thinking_budget=0, cache_blocks
- **Non-Anthropic models** (Gemini, OpenAI): Text mode, JSON extracted from response via regex/parsing
- **GPT-5 special case**: Forces temperature=1.0, disables streaming (organization verification issues)

**Error categories**: `api_validation`, `template_error`, `execution_failure`, `static_validation`, `edge_format`, `invalid_node_type`.

**Repair vs warning** (determined by runtime error categorization — see `runtime/CLAUDE.md`):
- Validation/template errors → always repair
- API business errors → warning only (non-repairable)
- Resource errors → warning only

**Validation errors capped at 3** per repair attempt to keep LLM context focused.

## Workflow Diff (`workflow_diff.py`)

`compute_workflow_diff()` compares two workflow IRs, returns `node_id → list of changes`. Detects: parameter additions, command modifications, prompt updates, node additions/removals, type changes. Used for `[repaired]` visual indicator.

## Output Extraction Priority

`executor_service._extract_default_output()` tries 3 strategies in order:
1. **Declared outputs** from workflow IR (`outputs` field)
2. **Common keys** in shared store: `result`, `output`, `response`, `data`
3. **Last node's namespace** — looks for `result`, `output`, `response` in `shared[last_node_id]`

If "why isn't my output showing?" — check this chain.

## Shared Formatters

**Pattern**: Formatters return strings or dicts, **never print**. Consumers (CLI, MCP) handle display. See `formatters/CLAUDE.md` for details.

Key formatters:
- `format_execution_errors()` — error formatting with sanitization
- `format_execution_success()` — success results with metrics
- `build_execution_steps()` (in `execution_state.py`) — per-node state including:
  - Shell metadata: `has_stderr`, `stderr`, `smart_handled`, `smart_handled_reason`
  - **Batch metadata**: `is_batch`, `batch_total`, `batch_success`, `batch_errors`, `batch_error_details` (capped at 5), `batch_errors_truncated` — added when node output contains `batch_metadata` key

**Progress indicators**: ✓ success (green), ❌ error (red), ⚠️ warning (stderr on exit 0), ↻ cached (blue/dimmed), [repaired] modified (cyan). Shell smart handling: [no matches] (grep/rg), [not found] (which/type).

## Integration

**CLI**: `cli/main.py` calls `execute_workflow()` with CliOutput. Key params: `workflow_ir`, `execution_params` (includes `__planner_cache_chunks__`), `enable_repair`, `output`, `workflow_manager`, `stdin_data`, `metrics_collector`, `trace_collector`.

**MCP Server**: `mcp_server/services/execution_service.py` calls `execute_workflow()` with NullOutput. Uses shared formatters for CLI/MCP parity.

**Runtime**: `executor_service.py` calls `compile_ir_to_flow()`. See `runtime/CLAUDE.md` for wrapper chain, reserved keys, and error categorization details.

**MCP Connection Pool**: `executor_service._initialize_shared_store()` creates `MCPConnectionPool()` and stores it in `shared["__mcp_pool__"]`. Shutdown happens in the `finally` block of `execute_workflow()`. MCP nodes look up this pool from shared store to reuse server connections across workflow steps.

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
- **Exception re-raise**: `executor_service` re-raises `CompilationError` and `RuntimeError` (not caught). Other exceptions are caught and wrapped in error dicts. Callers must handle these two.
- **MCPNode error detection**: `MCPNode.post()` returns "default" action even on errors (workaround for missing error edges). Formatters also check for `"error"` key in outputs/shared_store.
