# WorkflowNode Edge Cases and Error Scenarios Analysis

## Executive Summary

This document provides a comprehensive analysis of all edge cases and error scenarios for the proposed WorkflowNode implementation. Each scenario is traced through the exact error path, identifying where it would be caught, the impact on the parent workflow, and whether error context is preserved.

## Edge Case Categories

### 1. File System Errors

#### 1.1 Workflow File Doesn't Exist

**Scenario**: `workflow_ref` points to a non-existent file

**Error Path**:
```python
WorkflowNode.prep() → _load_workflow() → Path.exists() check
```

**Exact Code Location** (line 170-171):
```python
if not path.exists():
    raise FileNotFoundError(f"Workflow file not found: {path}")
```

**Where Caught**: In `prep()` method, wrapped with WorkflowExecutionError
**Impact**: Parent workflow execution stops
**Context Preserved**: Yes - full execution path in `workflow_path`
**Mitigation**: None needed - fail-fast is appropriate

#### 1.2 Invalid File Permissions

**Scenario**: Workflow file exists but cannot be read

**Error Path**:
```python
WorkflowNode.prep() → _load_workflow() → open() → PermissionError
```

**Where Caught**: Not explicitly caught - would bubble up as PermissionError
**Impact**: Parent workflow crashes
**Context Preserved**: No - raw Python exception
**Recommendation**: Add try/except in `_load_workflow()`:

```python
try:
    with open(path) as f:
        return json.load(f)
except (PermissionError, IOError) as e:
    raise WorkflowExecutionError(
        f"Cannot read workflow file: {path}",
        workflow_path=self.execution_context,
        original_error=e
    )
```

### 2. JSON/IR Errors

#### 2.1 Malformed Workflow IR

**Scenario**: Workflow file contains invalid JSON

**Error Path**:
```python
WorkflowNode.prep() → _load_workflow() → json.load() → JSONDecodeError
```

**Where Caught**: Not explicitly - JSONDecodeError would bubble up
**Impact**: Parent workflow crashes
**Context Preserved**: No
**Recommendation**: Catch JSONDecodeError in `_load_workflow()`:

```python
try:
    with open(path) as f:
        return json.load(f)
except json.JSONDecodeError as e:
    raise WorkflowExecutionError(
        f"Invalid JSON in workflow file: {path}",
        workflow_path=self.execution_context,
        original_error=e
    )
```

#### 2.2 Invalid IR Structure

**Scenario**: Valid JSON but missing required IR fields (nodes, edges)

**Error Path**:
```python
WorkflowNode.prep() → compile_ir_to_flow() → _validate_ir_structure() → CompilationError
```

**Where Caught**: In `prep()` try/except block (line 86-91)
**Impact**: Wrapped as WorkflowExecutionError, parent workflow stops
**Context Preserved**: Yes - full context maintained
**Status**: ✅ Properly handled

### 3. Circular Dependencies

#### 3.1 Direct Circular Reference

**Scenario**: Workflow A references Workflow A

**Error Path**: Would need detection in `prep()` method

**Current Implementation**: No circular dependency detection
**Impact**: Stack overflow or infinite recursion
**Context Preserved**: N/A - crash
**Critical Fix Needed**:

```python
def prep(self, shared):
    # Check for circular references
    execution_stack = shared.get("__workflow_stack__", [])
    current_ref = self.params.get("workflow_ref") or self.params.get("id", "inline")

    if current_ref in execution_stack:
        raise WorkflowExecutionError(
            f"Circular workflow reference detected",
            workflow_path=self.execution_context + [current_ref],
            original_error=None
        )

    # Add to stack for child workflows
    shared["__workflow_stack__"] = execution_stack + [current_ref]
```

#### 3.2 Indirect Circular Reference

**Scenario**: A → B → C → A

**Error Path**: Same as direct, but detected deeper in stack
**Impact**: Same as above
**Recommendation**: The stack-based approach handles this

### 4. Compilation Failures

#### 4.1 Child Workflow Compilation Fails

**Scenario**: Child workflow has invalid node types, missing nodes, etc.

**Error Path**:
```python
WorkflowNode.prep() → compile_ir_to_flow() → CompilationError
```

**Where Caught**: Lines 86-91 in `prep()`
**Impact**: Properly wrapped and parent stops
**Context Preserved**: Yes
**Status**: ✅ Properly handled

#### 4.2 Template Validation Failures

**Scenario**: Child workflow has unresolvable templates

**Error Path**:
```python
compile_ir_to_flow() → TemplateValidator.validate_workflow_templates() → ValueError
```

**Where Caught**: Would be caught in the same try/except
**Impact**: Parent workflow stops
**Context Preserved**: Yes
**Status**: ✅ Handled by existing error wrapping

### 5. Execution Failures

#### 5.1 Child Workflow Execution Fails

**Scenario**: Child workflow throws exception during run

**Error Path**:
```python
WorkflowNode.exec() → child_workflow.run() → Exception
```

**Where Caught**: Lines 127-132 in `exec()`
**Impact**: Wrapped as WorkflowExecutionError
**Context Preserved**: Yes - full execution path
**Status**: ✅ Properly handled

#### 5.2 Child Node Returns Error Action

**Scenario**: A node in child workflow returns "error" action

**Error Path**:
```python
WorkflowNode.post() → checks child_result == "error"
```

**Where Caught**: Lines 152-154 in `post()`
**Impact**: Returns configured `error_action` (default: "error")
**Context Preserved**: Yes
**Status**: ✅ Properly handled

### 6. Resource Exhaustion

#### 6.1 Deep Nesting (Stack Overflow)

**Scenario**: Workflows nested 100+ levels deep

**Current Implementation**: No depth limit
**Impact**: Python recursion limit hit, RecursionError
**Critical Fix Needed**:

```python
# In prep() method:
current_depth = len(shared.get("__workflow_stack__", []))
MAX_WORKFLOW_DEPTH = 10  # Configurable

if current_depth >= MAX_WORKFLOW_DEPTH:
    raise WorkflowExecutionError(
        f"Maximum workflow nesting depth ({MAX_WORKFLOW_DEPTH}) exceeded",
        workflow_path=self.execution_context,
        original_error=None
    )
```

#### 6.2 Memory Exhaustion

**Scenario**: Loading extremely large workflow files

**Current Implementation**: No file size limits
**Impact**: MemoryError
**Recommendation**: Add file size check:

```python
# In _load_workflow():
MAX_WORKFLOW_SIZE = 10 * 1024 * 1024  # 10MB

file_size = path.stat().st_size
if file_size > MAX_WORKFLOW_SIZE:
    raise WorkflowExecutionError(
        f"Workflow file too large: {file_size} bytes (max: {MAX_WORKFLOW_SIZE})",
        workflow_path=self.execution_context,
        original_error=None
    )
```

### 7. Parameter Mapping Errors

#### 7.1 Parameter References Non-existent Keys

**Scenario**: `param_mapping` references `$missing_key`

**Error Path**:
```python
WorkflowNode.prep() → _resolve_parameters() → resolve_templates()
```

**Current Behavior**: Template resolver returns empty string or original template
**Impact**: Child workflow gets incorrect parameters
**Recommendation**: The template validator should catch this at compile time

#### 7.2 Invalid Parameter Types

**Scenario**: Child expects string, gets complex object

**Current Implementation**: No type checking
**Impact**: Runtime error in child node
**Status**: This is a node implementation concern, not WorkflowNode's

### 8. Output Mapping Failures

#### 8.1 Output Mapping References Non-existent Keys

**Scenario**: `output_mapping` tries to map non-existent child key

**Error Path**:
```python
WorkflowNode.post() → output_mapping loop → key not in child_shared
```

**Current Implementation**: Silently skips missing keys (line 148-149)
**Impact**: Parent doesn't get expected output
**Status**: ✅ Safe behavior - no crash

#### 8.2 Output Key Conflicts

**Scenario**: Output mapping overwrites important parent keys

**Current Implementation**: Direct assignment, would overwrite
**Impact**: Could overwrite important data
**Recommendation**: Consider warning or prefixing

### 9. Storage Mode Issues

#### 9.1 Invalid Storage Mode

**Scenario**: `storage_mode: "invalid"`

**Error Path**:
```python
WorkflowNode.exec() → storage_mode check → ValueError
```

**Where Caught**: Line 122 raises ValueError
**Impact**: Would need to be caught
**Fix Needed**: Wrap in try/except or validate in `prep()`

#### 9.2 Scoped Storage Missing Prefix

**Scenario**: Scoped mode but no data with expected prefix

**Current Implementation**: Creates empty child storage
**Impact**: Child workflow runs with no data
**Status**: ✅ Safe behavior

### 10. Reserved Key Conflicts

#### 10.1 Child Modifies Reserved Keys

**Scenario**: Child workflow writes to `__workflow_context__`

**Current Implementation**: No protection
**Impact**: Could corrupt execution tracking
**Recommendation**: Document reserved keys, consider read-only wrapper:

```python
RESERVED_KEYS = {"__workflow_context__", "__workflow_stack__", "__registry__"}

# In post(), before mapping outputs:
for key in output_mapping.values():
    if key in RESERVED_KEYS:
        logger.warning(f"Skipping reserved key in output mapping: {key}")
        continue
```

### 11. Security Concerns

#### 11.1 Path Traversal

**Scenario**: `workflow_ref: "../../etc/passwd"`

**Current Implementation**: No path validation
**Impact**: Could read arbitrary files
**Critical Fix Needed**:

```python
# In _load_workflow():
# Resolve to absolute path and check it's within allowed directories
allowed_dirs = [
    Path.home() / ".pflow" / "workflows",
    Path.cwd() / "workflows"
]

resolved_path = path.resolve()
if not any(resolved_path.is_relative_to(allowed) for allowed in allowed_dirs):
    raise WorkflowExecutionError(
        f"Workflow path outside allowed directories: {path}",
        workflow_path=self.execution_context,
        original_error=None
    )
```

#### 11.2 Registry ID Injection

**Scenario**: Malicious registry IDs

**Current Implementation**: Not implemented yet
**Recommendation**: Validate registry IDs when implemented

### 12. Concurrent Execution

#### 12.1 Same Workflow Executed Concurrently

**Scenario**: Two parent workflows reference same child

**Current Implementation**: Each gets fresh instance
**Impact**: No issues - proper isolation
**Status**: ✅ Safe design

#### 12.2 Shared Storage Mode Race Conditions

**Scenario**: Multiple children with `storage_mode: "shared"`

**Current Implementation**: Direct shared storage access
**Impact**: Race conditions possible
**Status**: Document as unsafe for concurrent use

## Summary of Critical Fixes Needed

1. **Circular Dependency Detection** (High Priority)
   - Add workflow stack tracking
   - Check for cycles before compilation

2. **Maximum Depth Limit** (High Priority)
   - Prevent stack overflow
   - Configurable limit

3. **File Error Handling** (Medium Priority)
   - Catch PermissionError, IOError
   - Catch JSONDecodeError
   - Add file size limits

4. **Path Traversal Security** (High Priority)
   - Validate workflow paths
   - Restrict to allowed directories

5. **Reserved Key Protection** (Low Priority)
   - Document reserved keys
   - Skip in output mapping

6. **Storage Mode Validation** (Medium Priority)
   - Validate in prep() or catch in exec()

## Implementation Recommendations

### Error Handling Strategy

```python
class WorkflowNode(BaseNode):
    # Class-level configuration
    MAX_WORKFLOW_DEPTH = 10
    MAX_WORKFLOW_SIZE = 10 * 1024 * 1024  # 10MB
    RESERVED_KEYS = {"__workflow_context__", "__workflow_stack__", "__registry__"}

    def prep(self, shared):
        """Enhanced prep with all safety checks."""
        try:
            # 1. Circular dependency check
            self._check_circular_dependency(shared)

            # 2. Depth check
            self._check_nesting_depth(shared)

            # 3. Load and validate workflow
            workflow_ir = self._load_workflow_safely()

            # 4. Validate storage mode early
            storage_mode = self.params.get("storage_mode", "mapped")
            if storage_mode not in ["mapped", "isolated", "scoped", "shared"]:
                raise ValueError(f"Invalid storage_mode: {storage_mode}")

            # ... rest of prep logic

        except WorkflowExecutionError:
            # Already wrapped, re-raise
            raise
        except Exception as e:
            # Wrap any other exceptions
            raise WorkflowExecutionError(
                f"Failed to prepare child workflow",
                workflow_path=self.execution_context,
                original_error=e
            )
```

### Testing Strategy

Each edge case should have a dedicated test:

```python
# Example test structure
def test_circular_dependency_direct():
    """Test direct circular reference A→A"""

def test_circular_dependency_indirect():
    """Test indirect circular reference A→B→C→A"""

def test_max_depth_exceeded():
    """Test workflows nested beyond limit"""

def test_malformed_json():
    """Test invalid JSON in workflow file"""

def test_missing_workflow_file():
    """Test non-existent workflow reference"""

def test_path_traversal_attack():
    """Test path traversal prevention"""
```

## Conclusion

The WorkflowNode design is fundamentally sound, but needs several critical safety features added:
1. Circular dependency detection
2. Maximum nesting depth
3. Path validation for security
4. Better error handling for file operations

With these additions, WorkflowNode will be robust enough for production use while maintaining clear error messages and proper context preservation throughout the execution hierarchy.
