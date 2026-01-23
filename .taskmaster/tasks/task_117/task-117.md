# Task 117: Comprehensive JSON Error Output for CLI

## Description

Make ALL CLI error paths respect `--output-format json` with a unified error structure. Currently, ~72% of error-related functions output plain text even when JSON is requested, and the errors that do output JSON use inconsistent structures.

## Status

not started

## Priority

high

## Problem

### Problem 1: Most errors ignore `--output-format json`

When users specify `--output-format json`, they expect ALL output to be valid JSON. Currently:

- **Only 11 of 39 error-related functions** in main.py check `output_format` (28%)
- **28 functions** output text unconditionally regardless of format setting
- **Other CLI modules** (registry.py, registry_run.py, workflow.py) have similar or worse issues

Example of broken behavior:
```bash
# User expects JSON, gets plain text
echo "data" | uv run pflow --output-format json workflow-no-stdin.json
# Output: ❌ Piped input cannot be routed to workflow (WRONG - should be JSON)
```

### Problem 2: Inconsistent JSON structures

Errors that DO output JSON use different structures:

**Validation errors:**
```json
{
  "success": false,
  "error": "Workflow validation failed",
  "validation_errors": ["..."],
  "metadata": {"action": "unsaved", "name": "..."}
}
```

**Runtime errors:**
```json
{
  "success": false,
  "status": "failed",
  "error": "Workflow execution failed",
  "is_error": true,
  "errors": [{"source": "runtime", "category": "...", "message": "...", "node_id": "..."}],
  "failed_node": "...",
  "execution": {...},
  "duration_ms": ...,
  "metrics": {...}
}
```

This inconsistency means:
- Consumers must handle multiple structures
- Field names differ (`validation_errors` vs `errors`, `metadata` vs `workflow`)
- Some fields only exist in certain structures

### Problem 3: Cross-module inconsistency

Each CLI module handles errors differently:

| Module | JSON Flag? | Error JSON Support | Notes |
|--------|------------|-------------------|-------|
| `main.py` | `--output-format json` | Partial (11/39 functions) | Inconsistent structures |
| `registry.py` | `--json` on some commands | Partial (scan only) | Bug: line 426 outputs to stdout not stderr |
| `registry_run.py` | `--output-format json` | **NONE** | All 8 error outputs ignore format |
| `workflow.py` | `--json` on `list` only | **NONE** | Bug: lines 48-55 output to stdout not stderr |

### Problem 4: Pre-initialization errors

**Critical**: Some errors can occur BEFORE `ctx.obj` is populated (line 3863 in `workflow_command()`).

Specifically, `_inject_settings_env_vars()` at line 3859 can fail before context initialization. Any central error function that accesses `ctx.obj["output_format"]` will fail with `KeyError` or `TypeError`.

---

## Solution

### 1. Unified JSON Error Structure

All errors output the same base structure:

```json
{
  "success": false,
  "error": "Human readable summary",
  "error_type": "validation" | "runtime" | "compilation" | "cli",
  "errors": [
    {
      "message": "Detailed error message",
      "path": "inputs.data",           // Optional - location in workflow/config
      "suggestion": "How to fix",      // Optional
      "node_id": "node1",              // Optional - for runtime errors
      "category": "missing_input"      // Optional - specific error category
    }
  ],
  "workflow": {
    "name": "workflow-name",
    "source": "file" | "saved" | "planner" | null
  },

  // Runtime-only fields (omitted for validation/cli errors)
  "duration_ms": 1234,
  "metrics": {...},
  "execution": {
    "nodes_executed": 3,
    "steps": [...]
  }
}
```

**Design decisions:**
- Optional fields are **omitted** (not null) when not applicable
- `error_type` distinguishes error category at top level
- `errors` array always present (even for single error)
- `workflow` always present (may have null values for early CLI errors)

### 2. Central Error Output Infrastructure

Create a central function that ALL error output flows through, with safe handling for pre-initialization errors:

```python
def _output_cli_error(
    ctx: click.Context | None,
    error_type: str,
    summary: str,
    errors: list[dict],
    text_display: Callable[[], None] | None = None,
    workflow_metadata: dict | None = None,
    metrics: dict | None = None,
    execution: dict | None = None,
    output_format: str | None = None,  # Override for pre-init errors
    verbose: bool | None = None,       # Override for pre-init errors
) -> NoReturn:
    """Central error output respecting output_format.

    Handles three cases:
    1. Post-initialization: ctx.obj is populated, use it
    2. Pre-initialization: ctx.obj is None/empty, use overrides or defaults
    3. No context: ctx is None, use overrides or defaults

    Args:
        ctx: Click context (may be None for very early errors)
        error_type: Category (validation, runtime, compilation, cli)
        summary: Human-readable one-line summary
        errors: List of structured error dicts
        text_display: Function for rich text output (emojis, examples)
        workflow_metadata: Workflow name/source info
        metrics: Runtime metrics (optional)
        execution: Execution state (optional)
        output_format: Override for pre-initialization errors
        verbose: Override for pre-initialization errors
    """
    # Safe extraction with fallbacks for pre-initialization
    if ctx and ctx.obj:
        _output_format = ctx.obj.get("output_format", "text")
        _verbose = ctx.obj.get("verbose", False)
    else:
        _output_format = output_format or "text"
        _verbose = verbose or False

    if _output_format == "json":
        error_output = {
            "success": False,
            "error": summary,
            "error_type": error_type,
            "errors": errors,
            "workflow": workflow_metadata or {"name": None, "source": None},
        }
        # Add optional runtime fields
        if metrics:
            error_output["metrics"] = metrics
        if execution:
            error_output["execution"] = execution
            error_output["duration_ms"] = execution.get("duration_ms")

        click.echo(json.dumps(error_output, indent=2 if _verbose else None))
    else:
        # Rich text output
        if text_display:
            text_display()
        else:
            # Fallback: simple text
            click.echo(f"❌ {summary}", err=True)
            for err in errors:
                click.echo(f"   {err['message']}", err=True)
                if err.get("suggestion"):
                    click.echo(f"   👉 {err['suggestion']}", err=True)

    if ctx:
        ctx.exit(1)
    else:
        sys.exit(1)
```

**Key features:**
- Handles pre-initialization errors (ctx.obj not populated)
- Handles no-context errors (ctx is None)
- Preserves rich text formatting via `text_display` callback
- Standardizes JSON structure automatically
- Single place to maintain/audit

### 3. Error Helper Dataclass

```python
@dataclass
class CliErrorDetail:
    """Structured error detail for JSON output."""
    message: str
    path: str | None = None
    suggestion: str | None = None
    node_id: str | None = None
    category: str | None = None

    def to_dict(self) -> dict:
        result = {"message": self.message}
        if self.path:
            result["path"] = self.path
        if self.suggestion:
            result["suggestion"] = self.suggestion
        if self.node_id:
            result["node_id"] = self.node_id
        if self.category:
            result["category"] = self.category
        return result
```

---

## Implementation Plan

### Phase 1: Infrastructure

1. Create `CliErrorDetail` dataclass in `src/pflow/cli/error_output.py`
2. Create `_output_cli_error()` central function with pre-init handling
3. Add unit tests for the infrastructure (including pre-init scenarios)

### Phase 2: main.py Migration (High Priority)

Migrate error sites in priority order:

**Functions that already check output_format (11 - need structure unification):**

| Function | Line | Current Status |
|----------|------|----------------|
| `_handle_workflow_output` | 275 | Has format check |
| `_handle_compilation_error` | 1356 | Has format check |
| `_handle_workflow_error` | 1576 | Has format check |
| `_handle_workflow_success` | 1605 | Has format check |
| `_execute_workflow_and_handle_result` | 1717 | Has format check |
| `_handle_workflow_exception` | 1826 | Has format check |
| `_display_validation_results` | 1993 | Has format check |
| `_handle_validate_only_mode` | 2039 | Has format check |
| `_show_stdin_routing_error` | 3112 | Has format check (Task 115) |
| `_output_validation_errors` | 3152 | Has format check (Task 115) |
| `_handle_named_workflow` | 3394 | Has format check |

**Functions that DON'T check output_format (28 - need migration):**

| Priority | Function | Line | Error Type |
|----------|----------|------|------------|
| P1 | `_show_json_syntax_error` | 131 | JSON parse errors |
| P1 | `_handle_workflow_not_found` | 3454 | Workflow not found |
| P1 | `_handle_planning_failure` | 2756 | Planning errors |
| P2 | `_display_single_error` | 1477 | Individual errors (called from text handler) |
| P2 | `_display_api_error_response` | 1440 | API errors |
| P2 | `_display_mcp_error_details` | 1461 | MCP errors |
| P2 | `_display_shell_error_details` | 1535 | Shell errors |
| P2 | `_show_timeout_help` | 2381 | Timeout errors |
| P3 | `_display_batch_errors` | 721 | Batch processing errors |
| P3 | `_display_stderr_warnings` | 745 | Hidden pipeline errors |
| P3 | `_format_compilation_error_text` | 1665 | Compilation (text mode) |
| P4 | Other display/status functions | Various | Lower priority |

### Phase 3: Other CLI Modules

**registry.py** (11 error outputs, 3 check format):
- Line 272: `list` exception handler - add JSON
- Line 380: `describe` node not found - add JSON
- Line 415: `describe` exception handler - add JSON
- Line 426: **BUG FIX** - `_handle_nonexistent_path` outputs to stdout, should be stderr
- Line 532: `scan` exception handler - already has JSON
- Lines 636-639: `discover` validation - add JSON (needs `--json` flag first)
- Lines 850, 857: `describe_nodes` errors - add JSON (needs `--json` flag first)

**registry_run.py** (8 error outputs, 0 check format):
- Line 77-78: `_validate_parameters` - add JSON
- Line 191: `_prepare_node_execution` - add JSON
- Line 286: Cache failure warning - add JSON
- Line 312: MCPError display - add JSON
- Line 377: `_handle_ambiguous_node` - add JSON, add output_format param
- Line 386: `_handle_unknown_node` - add JSON, add output_format param
- Line 395: `_handle_execution_error` - add JSON, add output_format param

**workflow.py** (14 error outputs, 0 check format):
- Lines 48-55: **BUG FIX** - Filter message to stdout, should be stderr
- Line 76-80: `_handle_workflow_not_found` - add JSON
- Lines 209, 213-214: `_validate_discovery_query` - add JSON (needs `--json` flag first)
- Lines 237, 240: `_load_and_normalize_workflow` - add JSON (needs `--json` flag first)
- Line 270: Metadata warning - add JSON
- Lines 311-312, 315, 318: Save errors - add JSON (needs `--json` flag first)
- Lines 342-344: Delete warning - add JSON
- Line 371: Name validation - add JSON (needs `--json` flag first)

### Phase 4: Testing & Documentation

1. Add tests for JSON output of each error category
2. Test pre-initialization error handling
3. Test that text output is unchanged (preserves emojis, formatting)
4. Document the JSON error format in user docs

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/pflow/cli/error_output.py` | **NEW** - Central error output infrastructure |
| `src/pflow/cli/main.py` | Migrate 28 functions to central function, unify 11 existing |
| `src/pflow/cli/registry.py` | Add JSON error support to 8 error paths, fix stdout bug |
| `src/pflow/cli/registry_run.py` | Add JSON error support to all 8 error paths |
| `src/pflow/cli/commands/workflow.py` | Add `--json` flag to commands, add JSON error support, fix stdout bug |
| `tests/test_cli/test_json_errors.py` | **NEW** - Comprehensive JSON error tests |

---

## Bugs to Fix (Discovered During Investigation)

| File | Line | Bug | Fix |
|------|------|-----|-----|
| `registry.py` | 426 | `_handle_nonexistent_path` outputs errors to stdout | Add `err=True` |
| `workflow.py` | 48-55 | Filter message outputs to stdout | Add `err=True` |

---

## Error Categories Reference

| error_type | category | When |
|------------|----------|------|
| `validation` | `stdin_routing` | Piped input can't be routed |
| `validation` | `multiple_stdin` | Multiple stdin: true inputs |
| `validation` | `missing_input` | Required input not provided |
| `validation` | `invalid_template` | Template reference error |
| `validation` | `unknown_node` | Node type not in registry |
| `compilation` | `import_error` | Node class can't be imported |
| `compilation` | `schema_error` | Workflow IR invalid |
| `runtime` | `execution_failure` | Node execution failed |
| `runtime` | `api_error` | HTTP/API call failed |
| `runtime` | `shell_error` | Shell command failed |
| `runtime` | `mcp_error` | MCP tool call failed |
| `cli` | `json_syntax` | Invalid JSON in workflow file |
| `cli` | `file_not_found` | Workflow file doesn't exist |
| `cli` | `permission_denied` | Can't read workflow file |
| `cli` | `workflow_not_found` | Saved workflow doesn't exist |
| `cli` | `invalid_params` | Invalid CLI parameters |
| `cli` | `planning_failed` | Natural language planning failed |

---

## Verification

```bash
# All these should output valid JSON with the same base structure:

# Validation error (stdin routing)
echo "data" | uv run pflow --output-format json workflow-no-stdin.json

# Validation error (missing input)
uv run pflow --output-format json workflow.json

# Compilation error (unknown node)
uv run pflow --output-format json bad-node-workflow.json

# Runtime error (node failure)
uv run pflow --output-format json failing-workflow.json

# CLI error (file not found)
uv run pflow --output-format json nonexistent.json

# CLI error (JSON syntax)
uv run pflow --output-format json malformed.json

# Registry error
uv run pflow registry describe nonexistent-node --json

# Registry run error
uv run pflow registry run nonexistent-node --output-format json

# All should parse with: jq '.success, .error_type, .errors'
```

---

## Acceptance Criteria

- [ ] Central `_output_cli_error()` function created with pre-init handling
- [ ] All 39 error-related functions in main.py use central function
- [ ] All 11 error paths in registry.py use central function
- [ ] All 8 error paths in registry_run.py use central function
- [ ] All 14 error paths in workflow.py use central function
- [ ] Single unified JSON structure for all error types
- [ ] Rich text formatting preserved for text mode
- [ ] Pre-initialization errors handled correctly
- [ ] Bugs fixed (registry.py line 426, workflow.py lines 48-55)
- [ ] Tests verify JSON output for each error category
- [ ] Tests verify text output unchanged
- [ ] `make check` passes
- [ ] `make test` passes

---

## Design Decisions

### Decided

1. **Optional fields omitted** (not null) - Cleaner JSON, easier parsing
2. **Rich text via callback** - Preserves emojis, examples, formatting
3. **Single `errors` array** - Consistent structure, `error_type` distinguishes category
4. **workflow field always present** - May have null values for early CLI errors
5. **Handle pre-init errors** - Function accepts overrides for output_format/verbose

### Open Questions

1. **Should we version the JSON format?** - Probably not needed since no users yet
2. **Backward compatibility?** - Not needed, project is pre-release

---

## Dependencies

- Task 115: Automatic Stdin Routing (completed) — Added stdin routing error, partially fixed

## Related Work

- Task 115 partially addressed this by adding JSON support to `_show_stdin_routing_error()` and `_output_validation_errors()`
- This task completes and generalizes that work

---

## Investigation Notes

Verified 2026-01-23:
- main.py has 39 error-related functions, 11 check output_format (28%)
- registry.py has 11 error outputs, 3 check output_json (partial support)
- registry_run.py has 8 error outputs, 0 check output_format (no support)
- workflow.py has 14 error outputs, 0 check output format (no support, only `list` has `--json`)
- ctx.obj is populated at line 3863, errors before this can occur
- Line numbers verified accurate as of this date
