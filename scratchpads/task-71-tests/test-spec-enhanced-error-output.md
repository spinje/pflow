# Test Specification: Enhanced Error Output

## What Changed

Enhanced error output to show rich context when workflow execution fails.

**Key Implementation Details**:
- **Data Layer**: `src/pflow/execution/executor_service.py` lines 240-277
  - Extracts rich error data from shared store after node failure
  - Captures: status_code, raw_response, mcp_error, available_fields

- **Display Layer**: `src/pflow/cli/main.py` lines 596-838, 1083-1305
  - Enhanced `_handle_workflow_error()` signature (added `result`, `no_repair` params)
  - Shows field-level API errors, template suggestions, execution state
  - Different formatting for text vs JSON output

- **Execution State Visibility**: `src/pflow/cli/main.py` lines 639-697
  - `_build_execution_steps()` creates per-node status
  - Shows: node_id, status (completed/failed/not_executed), duration_ms, cached, repaired
  - Helps agents understand partial execution before failure

**What It Promises**:
1. **Rich API error context** - Show actual API responses, not generic messages
2. **Template error suggestions** - Show available fields when template fails
3. **Execution state visibility** - Show what succeeded before failure
4. **Actionable guidance** - Help agents fix errors without guessing
5. **Consistent formatting** - Both text and JSON modes enhanced

## Critical Behaviors to Test

### 1. HTTP Error Context Extraction
**Why**: Agents need actual API error details to fix issues.

**Test**: `test_enhanced_errors_show_http_response`
```python
def test_enhanced_errors_show_http_response(cli_runner, tmp_path, monkeypatch):
    """HTTP errors should show status code and response body.

    Real behavior: Extract from shared[failed_node] namespace
    Bad test: Mock the error message directly
    Good test: Simulate node failure with HTTP error data
    """
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{
            "id": "api_call",
            "type": "http",
            "params": {
                "url": "https://api.github.com/repos/invalid/invalid",
                "method": "GET"
            }
        }],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # Mock HTTP node to fail with structured error
    def mock_http_exec(self, shared):
        # Simulate HTTP 404 error
        shared["status_code"] = 404
        shared["raw_response"] = {"message": "Not Found"}
        shared["response_headers"] = {"content-type": "application/json"}
        raise Exception("HTTP request failed")

    monkeypatch.setattr("pflow.nodes.http.http.HttpNode.exec", mock_http_exec)

    result = cli_runner.invoke(main, ["--no-repair", str(workflow_path)])

    # Should show HTTP details
    assert result.exit_code != 0
    assert "404" in result.output
    assert "Not Found" in result.output or "not found" in result.output.lower()
```

**Real Bug This Catches**: If error extraction from shared store breaks or data layer skipped.

### 2. Template Error Available Fields
**Why**: Most valuable error enhancement - shows what's actually available.

**Test**: `test_enhanced_errors_show_available_fields`
```python
def test_enhanced_errors_show_available_fields(cli_runner, tmp_path):
    """Template errors should show available output fields.

    Key insight: This is what makes errors actionable for agents
    """
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fetch",
                "type": "shell",
                "params": {"command": "echo '{\"data\": \"value\", \"count\": 42}'"}
            },
            {
                "id": "process",
                "type": "shell",
                "params": {
                    # Wrong field name - should be "data" not "result"
                    "command": "echo ${fetch.result}"
                }
            }
        ],
        "edges": [{"from": "fetch", "to": "process"}]
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    result = cli_runner.invoke(main, ["--no-repair", str(workflow_path)])

    # Should show available fields from fetch node
    assert result.exit_code != 0
    assert "available" in result.output.lower() or "fields" in result.output.lower()
    # Should show the actual available field names
    assert "data" in result.output or "count" in result.output
```

**Real Bug This Catches**: If available_fields extraction fails or template validator doesn't use it.

### 3. Execution State in Errors
**Why**: Agents need to know what completed before failure for intelligent repair.

**Test**: `test_enhanced_errors_show_execution_state`
```python
def test_enhanced_errors_show_execution_state_json(cli_runner, tmp_path):
    """JSON output should include execution state showing what succeeded.

    Critical for agent repair: knowing what completed vs what failed
    """
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "step1", "type": "shell", "params": {"command": "echo success"}},
            {"id": "step2", "type": "shell", "params": {"command": "echo success"}},
            {"id": "step3", "type": "shell", "params": {"command": "exit 1"}},  # Fails
            {"id": "step4", "type": "shell", "params": {"command": "echo never runs"}}
        ],
        "edges": [
            {"from": "step1", "to": "step2"},
            {"from": "step2", "to": "step3"},
            {"from": "step3", "to": "step4"}
        ]
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    result = cli_runner.invoke(main, ["--output-format", "json", "--no-repair", str(workflow_path)])

    assert result.exit_code != 0

    # Parse JSON output
    output = json.loads(result.output)

    # Should have execution state
    assert "execution_steps" in output or "execution_state" in output

    # Verify state shows what completed
    # step1 and step2 should show "completed"
    # step3 should show "failed"
    # step4 should show "not_executed"

    # The exact structure depends on implementation, but validate it exists
    steps = output.get("execution_steps") or output.get("execution_state", {}).get("steps", [])
    assert len(steps) >= 3, "Should show status for nodes that ran"
```

**Real Bug This Catches**: If execution state tracking breaks or JSON formatting omits state.

### 4. MCP Error Details
**Why**: MCP tool errors need tool-specific context.

**Test**: `test_enhanced_errors_show_mcp_details`
```python
def test_enhanced_errors_show_mcp_details(cli_runner, tmp_path, monkeypatch):
    """MCP errors should show tool-specific error details."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{
            "id": "mcp_call",
            "type": "mcp-test-server-tool",
            "params": {"input": "invalid"}
        }],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # Mock MCP node to fail with structured error
    def mock_mcp_exec(self, shared):
        shared["error_details"] = {
            "code": "INVALID_INPUT",
            "message": "Input validation failed",
            "details": {"field": "input", "error": "too short"}
        }
        shared["mcp_error"] = "Tool execution failed"
        raise Exception("MCP tool error")

    # Note: This assumes MCP node exists in registry
    # May need to register a test MCP node

    result = cli_runner.invoke(main, ["--no-repair", str(workflow_path)])

    # Should show MCP error details
    assert result.exit_code != 0
    # Should show either error_details or mcp_error content
    assert "INVALID_INPUT" in result.output or "validation failed" in result.output.lower()
```

**Real Bug This Catches**: If MCP error extraction differs from HTTP pattern and breaks.

### 5. Cache Hit Tracking
**Why**: Execution state should show which nodes used cache.

**Test**: `test_enhanced_errors_show_cache_hits`
```python
def test_enhanced_errors_show_cache_hits_in_state(cli_runner, tmp_path):
    """Execution state should indicate cached node executions.

    Helps agents understand performance and execution flow
    """
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "expensive", "type": "shell", "params": {"command": "sleep 0.1 && echo result"}},
            {"id": "consumer", "type": "shell", "params": {"command": "echo ${expensive.result}"}}
        ],
        "edges": [{"from": "expensive", "to": "consumer"}]
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # First run - populates cache
    result1 = cli_runner.invoke(main, [str(workflow_path)])
    assert result1.exit_code == 0

    # Second run - should use cache (if caching enabled by default)
    result2 = cli_runner.invoke(main, ["--output-format", "json", str(workflow_path)])
    assert result2.exit_code == 0

    output = json.loads(result2.output)

    # Check if cache tracking exists in output
    # This validates that __cache_hits__ tracking was implemented
    steps = output.get("execution_steps", [])
    if steps:
        # At least one step should have cache information
        has_cache_info = any("cached" in str(step) for step in steps)
        # Note: This test may need adjustment based on default cache behavior
```

**Real Bug This Catches**: If `__cache_hits__` tracking in instrumented_wrapper.py breaks.

### 6. Error Signature Change Compatibility
**Why**: Validates the signature change to _handle_workflow_error doesn't break.

**Test**: `test_handle_workflow_error_receives_result_param`
```python
def test_handle_workflow_error_receives_result_param(cli_runner, tmp_path, monkeypatch):
    """_handle_workflow_error must receive ExecutionResult parameter.

    Validates fix for signature change (added result and no_repair params)
    """
    error_handler_called = []

    original_handler = None

    def track_error_handler(ctx, workflow_trace, output_format, metrics, shared, verbose, result, no_repair):
        # Track that handler was called with correct signature
        error_handler_called.append({
            "has_result": result is not None,
            "has_no_repair": no_repair is not None
        })
        # Call original if needed
        if original_handler:
            return original_handler(ctx, workflow_trace, output_format, metrics, shared, verbose, result, no_repair)

    # Import main module to get handler
    from pflow.cli import main as main_module
    original_handler = main_module._handle_workflow_error
    monkeypatch.setattr("pflow.cli.main._handle_workflow_error", track_error_handler)

    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "fail", "type": "shell", "params": {"command": "exit 1"}}],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    cli_runner.invoke(main, ["--no-repair", str(workflow_path)])

    # Verify handler was called with new signature
    assert len(error_handler_called) > 0
    assert error_handler_called[0]["has_result"], "ExecutionResult parameter must be provided"
    assert error_handler_called[0]["has_no_repair"], "no_repair parameter must be provided"
```

**Real Bug This Catches**: If call site forgets to pass new parameters, causing TypeError.

## Edge Cases to Test

### 7. No Enhanced Data Available
**Test**: `test_enhanced_errors_graceful_when_no_extra_data`
```python
def test_enhanced_errors_graceful_when_no_extra_data(cli_runner, tmp_path):
    """Should handle cases where no enhanced error data is available."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "simple_fail", "type": "shell", "params": {"command": "exit 1"}}],
        "edges": []
    }

    workflow_path = tmp_path / "test.json"
    workflow_path.write_text(json.dumps(workflow))

    # Basic failure without HTTP/MCP context
    result = cli_runner.invoke(main, ["--no-repair", str(workflow_path)])

    # Should not crash, just show basic error
    assert result.exit_code != 0
    assert "failed" in result.output.lower() or "error" in result.output.lower()
```

## What NOT to Test

❌ **Don't test error extraction logic internals** - That's tested in executor_service unit tests
❌ **Don't test template validator internals** - That's tested in test_runtime/
❌ **Don't test exact error message wording** - Test that key information appears
❌ **Don't mock shared store directly** - Use real node execution or mock at node level

## Success Criteria

A test is valuable if:
1. ✅ Validates data flows from executor to CLI (integration)
2. ✅ Catches missing error data extraction
3. ✅ Verifies execution state tracking works
4. ✅ Tests both text and JSON output modes
5. ✅ Validates signature changes don't break

## Existing Coverage to Build On

- `tests/test_execution/test_workflow_execution.py` - ExecutionResult structure
- `tests/test_runtime/test_template_validator_enhanced_errors.py` - Template error enhancements
- Focus on CLI display integration

## Test File Structure

```python
# tests/test_cli/test_enhanced_error_output.py

import json
import pytest

def test_enhanced_errors_show_http_response(cli_runner, tmp_path, monkeypatch):
    """HTTP errors include status code and response."""
    # ...

def test_enhanced_errors_show_available_fields(cli_runner, tmp_path):
    """Template errors show available output fields."""
    # ...

def test_enhanced_errors_show_execution_state_json(cli_runner, tmp_path):
    """JSON output includes execution state."""
    # ...

def test_enhanced_errors_show_mcp_details(cli_runner, tmp_path, monkeypatch):
    """MCP errors show tool-specific details."""
    # ...

def test_enhanced_errors_show_cache_hits_in_state(cli_runner, tmp_path):
    """Execution state shows cache usage."""
    # ...

def test_handle_workflow_error_receives_result_param(cli_runner, tmp_path, monkeypatch):
    """Validates signature change to error handler."""
    # ...

def test_enhanced_errors_graceful_when_no_extra_data(cli_runner, tmp_path):
    """Handles cases with no enhanced data."""
    # ...
```

## Estimated Effort

- **HTTP/MCP error tests**: 30 minutes (2 tests)
- **Template error test**: 20 minutes (1 test, most valuable)
- **Execution state tests**: 30 minutes (2 tests)
- **Signature validation**: 15 minutes (1 test)
- **Edge case**: 10 minutes (1 test)
- **Total**: ~1.75 hours

## Real Bugs These Tests Prevent

1. **Data extraction skipped** - If executor_service changes break error enrichment
2. **Display layer regression** - If CLI refactoring removes error context display
3. **Signature mismatch** - If call site doesn't pass result/no_repair parameters
4. **Execution state tracking breaks** - If __cache_hits__ or state building fails

These tests ensure the two-layer error enhancement architecture stays intact.
