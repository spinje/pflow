# PRESERVATION REQUIREMENTS - CLI Refactoring

This document identifies all requirements that **MUST BE PRESERVED** during the CLI refactoring to maintain compatibility and expected behavior.

## 1. Function Signatures That Cannot Change (CRITICAL)

### Main CLI Command Entry Point

**Function:** `workflow_command()`
**Location:** `src/pflow/cli/main.py:2695`
**MUST PRESERVE:**
```python
@click.command(context_settings={"allow_interspersed_args": False})
@click.pass_context
@click.option("--version", is_flag=True, help="Show the pflow version")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution output")
@click.option("--output-key", "-o", "output_key", help="Shared store key to output to stdout (default: auto-detect)")
@click.option("--output-format", type=click.Choice(["text", "json"], case_sensitive=False), default="text", help="Output format: text (default) or json")
@click.option("-p", "--print", "print_flag", is_flag=True, help="Force non-interactive output (print mode)")
@click.option("--trace", is_flag=True, help="Save workflow execution trace to file")
@click.option("--trace-planner", is_flag=True, help="Save planner execution trace to file")
@click.option("--planner-timeout", type=int, default=60, help="Timeout for planner execution (seconds)")
@click.option("--save/--no-save", default=True, help="Save generated workflow (default: save)")
@click.option("--cache-planner", is_flag=True, help="Enable cross-session caching for planner LLM calls (reduces cost for repeated runs)")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def workflow_command(
    ctx: click.Context,
    version: bool,
    verbose: bool,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    trace: bool,
    trace_planner: bool,
    planner_timeout: int,
    save: bool,
    cache_planner: bool,
    workflow: tuple[str, ...],
) -> None:
```

**Rationale:** This is the public CLI interface. Any changes break user scripts and integrations.

### Critical Handler Functions (Parameter Order Must Be Preserved)

**Function:** `_handle_workflow_success()`
**Location:** `src/pflow/cli/main.py:1049`
**MUST PRESERVE EXACT PARAMETER ORDER:**
```python
def _handle_workflow_success(
    ctx: click.Context,
    workflow_trace: Any | None,
    shared_storage: dict[str, Any],
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
) -> None:
```

**Function:** `_handle_workflow_error()`
**Location:** `src/pflow/cli/main.py:1020`
**MUST PRESERVE EXACT PARAMETER ORDER:**
```python
def _handle_workflow_error(
    ctx: click.Context,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
```

**Function:** `_handle_workflow_exception()`
**Location:** `src/pflow/cli/main.py:1330`
**MUST PRESERVE EXACT PARAMETER ORDER:**
```python
def _handle_workflow_exception(
    ctx: click.Context,
    e: Exception,
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
) -> None:
```

**Rationale:** These functions are called from multiple locations with positional arguments. Changing parameter order breaks existing calls.

### Output Handling Function

**Function:** `_handle_workflow_output()`
**Location:** `src/pflow/cli/main.py:291`
**MUST PRESERVE SIGNATURE:**
```python
def _handle_workflow_output(
    shared_storage: dict[str, Any],
    output_key: str | None,
    workflow_ir: dict[str, Any] | None = None,
    verbose: bool = False,
    output_format: str = "text",
    metrics_collector: Any | None = None,
    print_flag: bool = False,
    workflow_metadata: dict[str, Any] | None = None,
    workflow_trace: Any | None = None,
) -> bool:
```

**Rationale:** Complex function with many optional parameters. Existing callers depend on specific parameter names and positions.

## 2. Output Format Requirements (STRICT CONTRACTS)

### Text Output Format

**MUST PRESERVE:**
- Plain text to stdout (using `click.echo()`)
- Binary data is skipped with warning: `"cli: Skipping binary output (use --output-key with text values)"`
- String values output directly with `click.echo(value)`
- Non-string values converted with `str(value)`
- Returns `True` if output was produced, `False` otherwise

**Warning Messages (exact text):**
- Missing output key: `f"cli: Warning - output key '{output_key}' not found in shared store"`
- Output to stderr using `click.echo(..., err=True)`

### JSON Output Format (EXACT STRUCTURE)

**Success Response Structure:**
```json
{
  "success": true,
  "result": { /* outputs */ },
  "workflow": { /* workflow metadata */ },
  "duration_ms": 1234,
  "total_cost_usd": 0.01,
  "nodes_executed": 3,
  "metrics": { /* detailed metrics */ }
}
```

**Error Response Structure:**
```json
{
  "success": false,
  "error": {
    "type": "ErrorType",
    "message": "Error message",
    "details": "Optional details",
    "suggestion": "Optional suggestion"
  },
  "workflow": { /* workflow metadata */ },
  "duration_ms": 1234,
  "total_cost_usd": 0.01,
  "nodes_executed": 3,
  "metrics": { /* detailed metrics */ }
}
```

**MUST PRESERVE FIELDS:**
- `success` (boolean) - Required top-level field
- `result` (object) - Required on success, contains outputs
- `error` (object) - Required on failure, contains error details
- `workflow` (object) - Always present, contains metadata
- `duration_ms` (number|null) - When metrics available
- `total_cost_usd` (number|null) - When metrics available
- `nodes_executed` (number) - When metrics available
- `metrics` (object) - When metrics available

**Rationale:** External tools and CI/CD systems depend on this exact JSON structure for parsing results.

### Print Flag (-p) Behavior

**MUST PRESERVE:**
- Suppresses all warning messages when `-p` flag is set
- Affects only warning output, not actual results
- Used for: `verbose and not print_flag` conditions in warning logic
- Changes `effective_verbose = verbose and not print_flag and output_format != "json"`

**Rationale:** Critical for programmatic usage and CI/CD integration where warnings would break parsing.

## 3. Exit Code Patterns (STRICT)

**MUST PRESERVE EXIT CODES:**

- **Exit 0:** Only when `--version` flag is used (`ctx.exit(0)` at line 2758)
- **Exit 1:** All error cases (17 different locations call `ctx.exit(1)`)
- **Exit 0 (implicit):** Successful completion (Python default when no explicit exit)

**Special Exit Handling:**
- Broken pipe: `os._exit(0)` (immediate exit, no cleanup)
- SIGINT: `os._exit(0)` via signal handler

**Rationale:** Shell scripts and CI/CD systems depend on these exit codes for error detection and flow control.

## 4. Click-Specific Patterns (FRAMEWORK DEPENDENCY)

### Context Object Structure (`ctx.obj`)

**MUST PRESERVE KEYS:**
```python
ctx.obj = {
    "verbose": bool,
    "output_key": str | None,
    "output_format": str,  # "text" or "json"
    "print_flag": bool,
    "trace": bool,
    "trace_planner": bool,
    "planner_timeout": int,
    "save": bool,
    "cache_planner": bool,
    "output_controller": OutputController,
    "workflow_metadata": dict | None,  # Set during execution
    "workflow_text": str,  # Set during natural language processing
}
```

**Rationale:** Multiple functions access these keys by name. Changing names breaks the execution flow.

### Click Echo Usage Patterns

**MUST PRESERVE:**
- `click.echo(message)` for stdout output
- `click.echo(message, err=True)` for stderr messages
- Never use `print()` for user-facing output
- Handle `BrokenPipeError` with `os._exit(0)`

**Rationale:** Click echo provides proper pipe handling and cross-platform compatibility.

### Context Settings

**MUST PRESERVE:**
```python
@click.command(context_settings={"allow_interspersed_args": False})
```

**Rationale:** This setting affects how Click parses arguments and is critical for proper command-line parsing.

## 5. Special Cases and Edge Behaviors

### Stdin Data Handling

**MUST PRESERVE:**
- Text data injection to shared store
- Binary data handling with temporary files
- Size logging: `f"Injecting stdin data ({len(stdin_text)} chars) into shared['stdin']"`
- Temp file cleanup via `_cleanup_temp_files()`

### Interactive vs Non-Interactive Detection

**MUST PRESERVE:**
- `effective_verbose = verbose and not print_flag and output_format != "json"`
- MCP server output visibility control
- Progress display suppression in JSON mode

### Auto-Save Workflow Behavior

**MUST PRESERVE:**
- Workflow metadata creation patterns
- Named workflow handling (`reused` vs `unsaved` vs auto-generated)
- Save flag default behavior (`--save/--no-save`, default=True)

### Signal Handling

**MUST PRESERVE:**
- SIGINT handler: `signal.signal(signal.SIGINT, handle_sigint)`
- Clean exit: `os._exit(0)` in signal handler
- No cleanup on interrupt (immediate exit)

### Error Message Prefixes

**MUST PRESERVE EXACT TEXT:**
- `"cli: Warning - ..."` for warnings
- `"cli: Workflow execution failed - Node returned error action"` for workflow errors
- `"cli: Check node output above for details"` for error details
- `"cli: Workflow execution completed"` for success (verbose mode)

**Rationale:** Users and scripts may parse these specific message formats.

## 6. JSON Output Contract Details

### Workflow Metadata Structure

**MUST PRESERVE:**
```python
{
    "name": str | None,      # Workflow name or None
    "action": str,           # "reused", "unsaved", "generated", etc.
    "saved": bool,           # Whether workflow was saved
    "path": str | None,      # File path if saved
}
```

### Metrics Integration Requirements

**MUST PRESERVE:**
- LLM calls extraction: `shared_storage.get("__llm_calls__", [])`
- Node count calculation: Only workflow nodes, not planner nodes
- Cost and duration tracking from metrics collector
- Metrics included in both success and error responses

### Trace File Integration

**MUST PRESERVE:**
- JSON output stored in trace: `workflow_trace.set_json_output(result)`
- Trace saving after output handling
- Trace file path echoing: `f"📊 Workflow trace saved: {trace_file}"`

## 7. Validation Requirements

### Input Validation Order

**MUST PRESERVE:**
1. Click argument parsing and validation
2. Workflow structure validation (`_validate_workflow_structure()`)
3. Registry loading and node validation
4. Template validation before execution
5. Runtime parameter validation

### Error Propagation Patterns

**MUST PRESERVE:**
- UserFriendlyError formatting with CLI-specific display
- PlannerError special handling with suggestions
- Generic exception fallback behavior
- Error context preservation through the call stack

## 8. Dependencies That Cannot Change

### External Tool Integration

**MUST PRESERVE:**
- LLM CLI tool integration patterns
- MCP server discovery and management
- Git/GitHub operation consistency
- Shell pipe and redirection handling

### File System Interactions

**MUST PRESERVE:**
- Workflow save/load paths
- Trace file naming and location patterns
- Temporary file creation and cleanup
- Configuration file handling

## Summary

These requirements represent the **public contract** of the pflow CLI that external users, scripts, and integrations depend on. Any deviation from these specifications will break existing workflows and violate user expectations.

The refactoring MUST maintain these interfaces while improving internal organization and maintainability.
