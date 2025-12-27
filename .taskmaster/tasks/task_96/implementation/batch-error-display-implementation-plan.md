# Batch Error Display - Implementation Plan

**Date**: 2024-12-27
**Status**: Ready for implementation
**Based on**: Codebase analysis from 6 parallel searches

---

## Overview

Add user-friendly batch error display that:
1. Shows batch summary in node line: `⚠ process (31ms) - 8/10 items succeeded, 2 failed`
2. Shows error details section: `Batch 'process' errors: [1] Error message...`
3. Works for BOTH CLI and MCP (shared formatter layer)
4. Respects `-p` and `--output-format json` modes (no extra output)

---

## Architecture Decision

**Where to add batch display logic**: `success_formatter.py::format_success_as_text()`

**Why**: This is the SHARED layer used by both CLI and MCP. Changes here automatically benefit both consumers.

**NOT in `main.py`**: Would only affect CLI, MCP would miss the improvement.

---

## Files to Modify

| File | Purpose | Changes |
|------|---------|---------|
| `src/pflow/execution/execution_state.py` | Build execution steps | Add batch metadata to step dict |
| `src/pflow/execution/formatters/success_formatter.py` | Format success output | Batch-aware node lines + error section |
| `src/pflow/runtime/batch_node.py` | Batch node | Improve fail_fast error message |
| `src/pflow/cli/main.py` | CLI display | Remove `is_interactive()` from `_echo_trace()` |
| `tests/test_execution/formatters/test_success_formatter.py` | Tests | Add batch display tests |

---

## Step 1: Enhance Execution State Builder

**File**: `src/pflow/execution/execution_state.py`

**Current** `build_execution_steps()` returns:
```python
{
    "node_id": "process",
    "status": "completed",
    "duration_ms": 31,
    "cached": False,
    "repaired": False,
}
```

**After** - add batch detection:
```python
def build_execution_steps(
    workflow_ir: dict[str, Any],
    shared_storage: dict[str, Any],
    metrics_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    # ... existing code ...

    for node in workflow_ir["nodes"]:
        node_id = node["id"]

        # ... existing status determination ...

        step = {
            "node_id": node_id,
            "status": status,
            "duration_ms": node_timings.get(node_id, 0),
            "cached": node_id in cache_hits,
        }

        # NEW: Add batch metadata if this is a batch node
        node_output = shared_storage.get(node_id, {})
        if isinstance(node_output, dict) and "batch_metadata" in node_output:
            step["is_batch"] = True
            step["batch_total"] = node_output.get("count", 0)
            step["batch_success"] = node_output.get("success_count", 0)
            step["batch_errors"] = node_output.get("error_count", 0)
            # Include error details for display (capped)
            errors = node_output.get("errors") or []
            step["batch_error_details"] = errors[:5]  # Cap at 5
            step["batch_errors_truncated"] = len(errors) - 5 if len(errors) > 5 else 0

        steps.append(step)

    return steps
```

---

## Step 2: Update Success Formatter

**File**: `src/pflow/execution/formatters/success_formatter.py`

### 2.1 Add helper functions

```python
def _truncate_error_message(message: str, max_length: int = 200) -> str:
    """Truncate error message to max length with ellipsis."""
    if len(message) <= max_length:
        return message
    return message[:max_length - 3] + "..."


def _format_batch_node_line(step: dict[str, Any]) -> str:
    """Format a batch node's status line with summary.

    Examples:
        "  ✓ process (31ms) - 10/10 items succeeded"
        "  ⚠ process (31ms) - 8/10 items succeeded, 2 failed"
    """
    node_id = step["node_id"]
    duration = step.get("duration_ms", 0)
    total = step.get("batch_total", 0)
    success = step.get("batch_success", 0)
    errors = step.get("batch_errors", 0)

    timing = f"({duration}ms)" if duration < 1000 else f"({duration/1000:.1f}s)"

    if errors > 0:
        # Partial success - warning indicator
        return f"  ⚠ {node_id} {timing} - {success}/{total} items succeeded, {errors} failed"
    else:
        # Full success - checkmark
        return f"  ✓ {node_id} {timing} - {total}/{total} items succeeded"


def _format_batch_errors_section(steps: list[dict[str, Any]]) -> str:
    """Format batch errors section for all batch nodes with failures.

    Example:
        Batch 'process' errors:
          [1] Command failed with exit code 1
          [4] Connection timeout after 30s
          ...and 3 more errors
    """
    lines = []

    for step in steps:
        if not step.get("is_batch") or step.get("batch_errors", 0) == 0:
            continue

        node_id = step["node_id"]
        error_details = step.get("batch_error_details", [])
        truncated = step.get("batch_errors_truncated", 0)

        lines.append(f"\nBatch '{node_id}' errors:")
        for err in error_details:
            idx = err.get("index", "?")
            msg = _truncate_error_message(err.get("error", "Unknown error"))
            lines.append(f"  [{idx}] {msg}")

        if truncated > 0:
            lines.append(f"  ...and {truncated} more errors")

    return "\n".join(lines) if lines else ""
```

### 2.2 Update `format_success_as_text()`

Find the node line formatting section and update:

```python
def format_success_as_text(result: dict[str, Any]) -> str:
    """Format execution success dict as human-readable text."""
    lines = []

    # ... existing header formatting ...

    # Node execution summary
    execution = result.get("execution", {})
    steps = execution.get("steps", [])

    if steps:
        lines.append(f"Nodes executed ({len(steps)}):")
        for step in steps:
            if step.get("is_batch"):
                # NEW: Batch-aware formatting
                lines.append(_format_batch_node_line(step))
            else:
                # Existing: Regular node formatting
                indicator = _get_status_indicator(step["status"])
                node_id = step["node_id"]
                duration = step.get("duration_ms", 0)
                timing = f"({duration}ms)" if duration < 1000 else f"({duration/1000:.1f}s)"
                cached = " cached" if step.get("cached") else ""
                lines.append(f"  {indicator} {node_id} {timing}{cached}")

    # NEW: Batch errors section (after node list)
    batch_errors = _format_batch_errors_section(steps)
    if batch_errors:
        lines.append(batch_errors)

    # ... existing cost/output formatting ...

    return "\n".join(lines)
```

---

## Step 3: Improve fail_fast Error Message

**File**: `src/pflow/runtime/batch_node.py`

Find the fail_fast raise in `_exec_sequential()` (around line 367):

**Current**:
```python
raise RuntimeError(error["error"])
```

**After**:
```python
raise RuntimeError(f"Batch '{self.node_id}' failed at item [{idx}]: {error['error']}")
```

Similarly in `_exec_parallel()` and `_collect_parallel_results()`.

---

## Step 4: Always Show Trace File Location

**File**: `src/pflow/cli/main.py`

**Current** `_echo_trace()` (lines 93-105):
```python
def _echo_trace(ctx: click.Context, message: str) -> None:
    output_controller = _get_output_controller(ctx)
    if output_controller.is_interactive():
        click.echo(message, err=True)
```

**After** - remove interactive check:
```python
def _echo_trace(ctx: click.Context, message: str) -> None:
    """Output trace file location message.

    Always shown (to stderr) regardless of mode, as trace files
    are valuable for debugging in all contexts including CI/CD and agents.
    """
    click.echo(message, err=True)
```

---

## Step 5: Verify -p and JSON Mode Behavior

The batch error section is added in `format_success_as_text()`. We need to verify:

### 5.1 `-p` mode

Check `_handle_text_output()` in `main.py`:
- Line 482: `if metrics_collector and not print_flag:` - summary is skipped
- Line 359: `if print_flag:` - only raw output

**VERIFY**: Does `-p` mode call `format_success_as_text()`?

If YES: Need to pass a flag to suppress batch errors
If NO: Already correct behavior

### 5.2 `--output-format json` mode

Check `_handle_json_output()`:
- Returns structured dict with `execution.steps`
- Does NOT call `format_success_as_text()`

**VERIFY**: JSON output already includes batch metadata in steps?

If YES: Already correct - structured data available
If NO: Batch metadata added in Step 1 will flow through

---

## Step 6: Add Tests

**File**: `tests/test_execution/formatters/test_success_formatter.py`

```python
class TestBatchDisplay:
    """Tests for batch node display formatting."""

    def test_batch_full_success_shows_checkmark(self):
        """Batch with all items successful shows ✓ and count."""
        result = {
            "execution": {
                "steps": [{
                    "node_id": "process",
                    "status": "completed",
                    "duration_ms": 31,
                    "is_batch": True,
                    "batch_total": 10,
                    "batch_success": 10,
                    "batch_errors": 0,
                    "batch_error_details": [],
                }]
            }
        }
        text = format_success_as_text(result)
        assert "✓ process" in text
        assert "10/10 items succeeded" in text
        assert "failed" not in text

    def test_batch_partial_success_shows_warning(self):
        """Batch with some failures shows ⚠ and counts."""
        result = {
            "execution": {
                "steps": [{
                    "node_id": "process",
                    "status": "completed",
                    "duration_ms": 31,
                    "is_batch": True,
                    "batch_total": 10,
                    "batch_success": 8,
                    "batch_errors": 2,
                    "batch_error_details": [
                        {"index": 1, "error": "Error 1"},
                        {"index": 4, "error": "Error 2"},
                    ],
                }]
            }
        }
        text = format_success_as_text(result)
        assert "⚠ process" in text
        assert "8/10 items succeeded" in text
        assert "2 failed" in text

    def test_batch_errors_section_displayed(self):
        """Batch errors shown in separate section."""
        result = {
            "execution": {
                "steps": [{
                    "node_id": "process",
                    "status": "completed",
                    "is_batch": True,
                    "batch_total": 10,
                    "batch_success": 8,
                    "batch_errors": 2,
                    "batch_error_details": [
                        {"index": 1, "error": "Command failed"},
                        {"index": 4, "error": "Timeout"},
                    ],
                }]
            }
        }
        text = format_success_as_text(result)
        assert "Batch 'process' errors:" in text
        assert "[1] Command failed" in text
        assert "[4] Timeout" in text

    def test_batch_errors_capped_at_5(self):
        """More than 5 errors shows truncation message."""
        errors = [{"index": i, "error": f"Error {i}"} for i in range(8)]
        result = {
            "execution": {
                "steps": [{
                    "node_id": "process",
                    "status": "completed",
                    "is_batch": True,
                    "batch_total": 10,
                    "batch_success": 2,
                    "batch_errors": 8,
                    "batch_error_details": errors[:5],
                    "batch_errors_truncated": 3,
                }]
            }
        }
        text = format_success_as_text(result)
        assert "...and 3 more errors" in text

    def test_error_message_truncated_at_200_chars(self):
        """Long error messages truncated with ellipsis."""
        long_error = "x" * 300
        result = {
            "execution": {
                "steps": [{
                    "node_id": "process",
                    "status": "completed",
                    "is_batch": True,
                    "batch_total": 1,
                    "batch_success": 0,
                    "batch_errors": 1,
                    "batch_error_details": [{"index": 0, "error": long_error}],
                }]
            }
        }
        text = format_success_as_text(result)
        # Error line should be truncated
        assert "..." in text
        assert long_error not in text  # Full message not present

    def test_non_batch_node_unchanged(self):
        """Regular nodes still use standard formatting."""
        result = {
            "execution": {
                "steps": [{
                    "node_id": "fetch",
                    "status": "completed",
                    "duration_ms": 100,
                }]
            }
        }
        text = format_success_as_text(result)
        assert "✓ fetch" in text
        assert "items succeeded" not in text  # No batch summary
```

---

## Implementation Order

1. **Step 1: execution_state.py** (~15 min)
   - Add batch detection to `build_execution_steps()`
   - Run existing tests to verify no regression

2. **Step 2: success_formatter.py** (~30 min)
   - Add helper functions
   - Update `format_success_as_text()`
   - This is the core change

3. **Step 3: batch_node.py** (~10 min)
   - Improve fail_fast error messages

4. **Step 4: main.py** (~5 min)
   - Remove `is_interactive()` from `_echo_trace()`

5. **Step 5: Verify modes** (~15 min)
   - Test `-p` mode doesn't show batch errors
   - Test JSON mode has structured data

6. **Step 6: Add tests** (~30 min)
   - Batch display tests
   - Mode suppression tests

**Estimated total**: ~1.5-2 hours

---

## Verification Checklist

- [ ] `uv run pflow examples/batch-test.json` shows batch summary in node line
- [ ] `uv run pflow examples/batch-test.json` shows "Batch errors:" section
- [ ] `uv run pflow -p examples/batch-test.json` shows ONLY raw output
- [ ] `uv run pflow --output-format json examples/batch-test.json` shows structured JSON
- [ ] MCP `workflow_execute` tool returns batch summary in text
- [ ] Trace file location always shown (even in non-interactive)
- [ ] `make check` passes
- [ ] `make test` passes

---

## Output Specifications

### Interactive Mode (default)
```
✓ Workflow completed in 0.394s
Nodes executed (2):
  ✓ source (38ms)
  ⚠ process (31ms) - 8/10 items succeeded, 2 failed

Batch 'process' errors:
  [1] Command failed with exit code 1
  [4] Connection timeout after 30s

Trace: ~/.pflow/debug/workflow-trace-20251227-121041.json

Workflow output:
...
```

### Pipe Mode (`-p`)
```
{only the raw workflow output value}
```

### JSON Mode (`--output-format json`)
```json
{
  "success": true,
  "execution": {
    "steps": [
      {"node_id": "source", "status": "completed", ...},
      {
        "node_id": "process",
        "status": "completed",
        "is_batch": true,
        "batch_total": 10,
        "batch_success": 8,
        "batch_errors": 2,
        "batch_error_details": [...]
      }
    ]
  },
  "output": {...}
}
```

### MCP Tool Response
```
✓ Workflow completed in 0.394s
Nodes executed (2):
  ✓ source (38ms)
  ⚠ process (31ms) - 8/10 items succeeded, 2 failed

Batch 'process' errors:
  [1] Command failed with exit code 1
  [4] Connection timeout after 30s

Workflow output:
...
```

(Same as interactive - both use `format_success_as_text()`)
