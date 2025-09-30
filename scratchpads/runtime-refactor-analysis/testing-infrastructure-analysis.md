# Testing Infrastructure Analysis for Runtime Refactoring

This document analyzes the current testing infrastructure to identify critical boundaries and interfaces that must be preserved during the Task 68 refactoring of runtime validation and workflow execution.

## Executive Summary

The refactoring must preserve these critical test boundaries:
1. **CLI Mock Interface**: `compile_ir_to_flow()` function signature and return type
2. **Validation Interface**: `validate_ir()` function interface
3. **Error Boundaries**: Exit codes, error message formats, and exception types
4. **Output Testing**: JSON/text format structures and output key behavior
5. **Integration Boundaries**: Direct function calls in integration tests

## 1. CLI Test Mocking Patterns

### 1.1 Primary Mock: `compile_ir_to_flow()`

**Location**: Tests mock `pflow.cli.main.compile_ir_to_flow`

**Current Interface**:
```python
def compile_ir_to_flow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    validate: bool = True,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> Flow
```

**Mock Expectations** (from `test_workflow_output_handling.py`):
```python
# Mock returns a Flow object with:
flow.run(shared_storage) -> str  # Action string ("success", "error", etc.)

# Mock side effect function signature:
def compile_with_ir(ir_data, registry, initial_params=None, validate=True,
                   metrics_collector=None, trace_collector=None) -> Flow
```

**Critical**: The mock stores `ir_data` in `mock._last_ir` for test node parameter extraction.

### 1.2 Validation Mock: `validate_ir()`

**Location**: Tests mock `pflow.cli.main.validate_ir`

**Current Interface**:
```python
def validate_ir(data: Union[dict[str, Any], str]) -> None
    # Raises ValidationError on failure
    # Returns None on success
```

**Mock Pattern**:
```python
with patch("pflow.cli.main.validate_ir") as mock:
    mock.return_value = None  # Always passes validation in tests
```

### 1.3 Registry Mock Pattern

**Location**: Tests mock `pflow.cli.main.Registry`

**Mock Structure**:
```python
mock_registry = Mock()
mock_registry.load.return_value = {node_type: node_data}
mock_registry.get_nodes_metadata = Mock(side_effect=metadata_function)
mock_registry.registry_path = Mock(exists=lambda: True)
```

## 2. Integration Test Patterns

### 2.1 Direct Function Calls

Integration tests bypass CLI and call functions directly:

```python
# From test_template_system_e2e.py:
from pflow.runtime.compiler import compile_ir_to_flow
flow = compile_ir_to_flow(workflow_ir, registry, initial_params=params)
result = flow.run({})
```

**Critical**: These tests expect the actual `compile_ir_to_flow` implementation, not mocks.

### 2.2 Registry Usage

Integration tests use real Registry instances:
```python
from pflow.registry import Registry
registry = Registry()
registry.scan()  # Discover actual nodes
```

### 2.3 WorkflowExecutor Integration

Several tests import and use `WorkflowExecutor`:
```python
from pflow.runtime.workflow_executor import WorkflowExecutor
# Tests expect specific parameter interfaces and behavior
```

## 3. Error Testing Boundaries

### 3.1 CLI Exit Codes

**Success Cases**: `assert result.exit_code == 0`
**Error Cases**: `assert result.exit_code != 0` or `assert result.exit_code == 1`

### 3.2 Error Message Formats

**JSON Syntax Errors**:
```python
assert "Invalid JSON syntax" in result.output
assert "Error at line" in result.output
assert "Fix the JSON syntax error" in result.output
```

**Compilation Errors**:
```python
assert "❌ Planning failed:" in result.output
assert "non-existent-node" in result.output  # Node type in error
```

### 3.3 Exception Types

**CompilationError**: Used throughout runtime system
```python
class CompilationError(Exception):
    def __init__(self, message, phase="unknown", node_id=None,
                 node_type=None, details=None, suggestion=None)
```

**ValidationError**: Used in IR validation
```python
# Raised by validate_ir() function
```

## 4. Output Testing Patterns

### 4.1 Text Output Format

**Success Messages**:
- `"Workflow executed successfully"` (when no specific output found)
- Direct output values for declared outputs or fallback keys

**Fallback Key Priority**: `response > output > result > text`

### 4.2 JSON Output Format

**Structure**:
```python
# Single output:
{"key": "value"}

# Multiple outputs:
{"key1": "value1", "key2": "value2"}

# Empty result:
{}

# Wrapped format (some tests expect):
{"result": {"key": "value"}}
```

### 4.3 Output Key Behavior

**Declared Outputs**: From workflow IR `outputs` section
**Override**: `--output-key` flag overrides all auto-detection
**Verbose Mode**: Shows descriptions and warnings for missing outputs

## 5. Test Node Patterns

### 5.1 MockOutputNode Behavior

Used by CLI output tests:
```python
# Node behavior based on params:
if "output_key" in params:
    shared[params["output_key"]] = params.get("output_value", "test value")
if "add_keys" in params:
    for key, value in params["add_keys"].items():
        shared[key] = value
```

### 5.2 Registry Test Nodes

Integration tests use actual test nodes:
- `"test-node"` → `MockOutputNode`
- `"echo"` → Echo node
- `"shell"` → Shell node
- etc.

## 6. Planner Blocking in CLI Tests

### 6.1 Planner Block Mechanism

**Location**: `tests/shared/planner_block.py` → `tests/test_cli/conftest.py`

**Effect**: Makes planner import fail, triggering fallback behavior
```python
# Expected fallback outputs:
"Collected workflow from args: ..."
"Collected workflow from file: ..."
```

**Critical**: CLI tests expect blocked planner behavior, not actual planning.

## 7. Critical Preservation Requirements

### 7.1 Function Signatures

**Must Preserve**:
- `compile_ir_to_flow()` parameter names, types, and defaults
- `validate_ir()` interface
- Return types (Flow object with `.run()` method)

### 7.2 Mock Interfaces

**Must Preserve**:
- Mock side effect function signatures
- `mock._last_ir` storage pattern for test parameter extraction
- Registry mock structure and methods

### 7.3 Error Boundaries

**Must Preserve**:
- Exit code patterns (0 for success, 1 for errors)
- Error message formats and content
- Exception types and inheritance

### 7.4 Output Formats

**Must Preserve**:
- JSON structure and field names
- Text output patterns and success messages
- Output key resolution logic and priority

## 8. Refactoring Strategy Implications

### 8.1 Safe Changes

- Internal implementation details of `compile_ir_to_flow()`
- Internal workflow execution logic
- Internal validation implementation
- Code organization and module structure

### 8.2 Breaking Changes to Avoid

- Function signatures of public interfaces
- Mock interface requirements
- Error message formats expected by tests
- Output structure and field names
- Exit code behavior

### 8.3 Test Validation Strategy

1. Run CLI tests first - they're most sensitive to interface changes
2. Run integration tests - they test actual implementations
3. Run runtime tests - they test internal behavior
4. Focus on error cases - they often have strict format requirements

## 9. Key Files for Interface Preservation

### 9.1 Primary Interfaces
- `src/pflow/runtime/compiler.py::compile_ir_to_flow()`
- `src/pflow/core/ir_schema.py::validate_ir()`
- `src/pflow/runtime/workflow_executor.py::WorkflowExecutor`

### 9.2 Test Boundary Files
- `tests/test_cli/test_workflow_output_handling.py` (most sensitive)
- `tests/test_cli/test_json_error_handling.py` (error formats)
- `tests/test_integration/test_template_system_e2e.py` (direct calls)
- `tests/test_integration/test_workflow_manager_integration.py` (WorkflowExecutor)

### 9.3 Mock Definition Files
- `tests/test_cli/conftest.py` (planner blocking)
- `tests/shared/planner_block.py` (planner mock mechanism)

## 10. Testing Checklist for Refactor

- [ ] All CLI tests pass (especially output handling)
- [ ] All integration tests pass (direct function calls)
- [ ] All error message formats preserved
- [ ] All output formats (JSON/text) unchanged
- [ ] Exit codes match expected patterns
- [ ] Mock interfaces still work correctly
- [ ] Planner blocking still functions
- [ ] Exception types and messages preserved

This analysis provides the foundation for safely refactoring the runtime validation and workflow execution system while maintaining all critical test boundaries.
