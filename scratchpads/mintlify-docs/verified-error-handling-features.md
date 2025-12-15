# Verified Error Handling Features

Research date: 2025-12-12

These are VERIFIED features from codebase research. Only document what's confirmed below.

---

## 1. Smart Exit Codes (Shell Node)

**Source**: `src/pflow/nodes/shell/shell.py` lines 164-229

### Verified Auto-Handled Patterns

These non-zero exit codes are treated as **success**:

| Pattern | Detection | Exit Code | Reason |
|---------|-----------|-----------|--------|
| `ls *.txt` (no matches) | Command starts with `ls`, contains glob chars (`*?[]`), stderr has "No such file" | Normalized to 1 | Empty glob matches are valid |
| `grep pattern file` (no matches) | Command contains `grep`, exit code 1 | 1 | grep returns 1 when no matches |
| `rg pattern` (no matches) | Command contains `rg`, exit code 1 | 1 | ripgrep returns 1 when no matches |
| `which nonexistent` | Command starts with `which`, non-zero exit | Normalized to 1 | Existence check |
| `command -v nonexistent` | Command contains `command -v`, non-zero exit | Normalized to 1 | Existence check |
| `type nonexistent` | Command starts with `type`, output contains "not found" | Normalized to 1 | Existence check |

### Important Caveats

- **Binary output exemption**: If stdout/stderr is binary, smart pattern detection is SKIPPED entirely (lines 636-642)
- **Platform normalization**: Different OSes return different exit codes; pflow normalizes to exit code 1 for consistency

### Docstring (lines 27-35)

```
Smart Error Handling:
The shell node automatically treats certain non-zero exits as success:
- ls with glob patterns that match no files (e.g., ls *.txt)
- grep/rg that find no matches
- which/command -v/type checking for non-existent commands
- find returning no results

These are treated as empty results, not errors. Use ignore_errors=true
for other cases where you want to continue despite failures.
```

---

## 2. User-Friendly Error Messages

**Source**: `src/pflow/core/user_errors.py`

### Verified Format Structure (lines 10-82)

Three-part format:
1. **WHAT** - Brief title
2. **WHY** - Plain language explanation
3. **HOW** - Actionable suggestions

### Display Format

```
Error: {title}

{explanation}

To fix this:
  1. {suggestion 1}
  2. {suggestion 2}

Run with --verbose for technical details.
```

### Verified Active Error Classes

| Class | Status | Used For |
|-------|--------|----------|
| `UserFriendlyError` | Base class | Foundation for all user errors |
| `MCPError` | ✅ ACTIVE | MCP tool unavailability |
| `PlannerError` | ✅ ACTIVE | Planner failures |
| `CompilationError` | ✅ ACTIVE | Workflow compilation errors |

### Defined But NOT Used (as of research date)

These classes exist but are never raised in the codebase:
- `NodeNotFoundError` - Has "Did you mean?" logic but unused
- `MissingParametersError` - Shows missing params but unused
- `TemplateVariableError` - Shows variable errors but unused

---

## 3. Trace Files

**Source**: `src/pflow/runtime/workflow_trace.py`, `src/pflow/cli/main.py`

### Verified Path

```
~/.pflow/debug/workflow-trace-{name}-YYYYMMDD-HHMMSS.json
```

Or if no workflow name:
```
~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json
```

### When Traces Are Saved

- **Default**: ALWAYS saved on both success AND failure
- **Disable**: `--no-trace` flag (verified - main.py lines 3414-3418)
- **Planner traces**: Saved with `--trace-planner` flag OR automatically on planner failure

### --no-trace Flag (VERIFIED)

**Definition** (main.py lines 3414-3418):
```python
@click.option(
    "--no-trace",
    is_flag=True,
    help="Disable workflow execution trace saving (enabled by default)",
)
```

**How it works**:
- Default: traces enabled (`no_trace=False`)
- With `--no-trace`: `trace_enabled=False` → `workflow_trace=None` → no file saved

### Verified Trace Structure (format_version 1.2.0)

```json
{
  "format_version": "1.2.0",
  "execution_id": "uuid-string",
  "workflow_name": "workflow-name",
  "start_time": "ISO8601",
  "end_time": "ISO8601",
  "duration_ms": 1234.56,
  "final_status": "success|degraded|failed",
  "nodes_executed": 5,
  "nodes_failed": 0,
  "nodes": [
    {
      "node_id": "...",
      "start_time": "...",
      "duration_ms": 123.45,
      "success": true,
      "outputs": {...},
      "llm_call": {...}
    }
  ],
  "llm_summary": {
    "total_calls": 3,
    "total_tokens": 5000,
    "models_used": ["model-name"]
  },
  "json_output": {...}
}
```

### Tri-State Status

- `success` - All nodes completed
- `degraded` - Completed with warnings (non-fatal issues)
- `failed` - Workflow failed

---

## 4. Validation-Only Mode

**Source**: `src/pflow/cli/main.py` line 3436

### Verified Flag

```python
@click.option("--validate-only", is_flag=True, help="Validate workflow without executing")
```

### What Gets Validated

| Check | Source File |
|-------|-------------|
| Schema compliance | `ir_schema.py` |
| Data flow (execution order, no cycles) | `workflow_data_flow.py` |
| Template structure (`${variable}` references) | `template_validator.py` |
| Node types exist | Registry lookup |

### What's NOT Validated

- Runtime values (actual data)
- API credentials
- File existence
- Network connectivity

### Auto-Normalization

Missing fields are auto-added to reduce friction:
- `ir_version` defaults to `"0.1.0"`
- `edges` defaults to `[]`

### Exit Codes

- `0` = Valid
- `1` = Invalid

### Test Proof (test_validate_only.py lines 70-98)

Test creates shell node that would write a file, runs with `--validate-only`, and asserts file was NOT created. This proves nodes are NEVER executed.

### JSON Output

Supports `--output-format json` for structured validation results.

---

## Summary: What's Safe to Document

| Feature | Confidence | Notes |
|---------|------------|-------|
| Smart exit codes | HIGH | 6 patterns verified with source |
| User-friendly format | MEDIUM | Format verified, but many classes unused |
| Trace files | HIGH | Path, structure, flags all verified |
| Validation-only | HIGH | Flag, checks, exit codes all verified |
