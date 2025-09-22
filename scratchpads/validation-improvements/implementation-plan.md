# Validation System Improvements - Implementation Plan

## Executive Summary

We're improving the pflow validation system to:
1. **Remove artificial restrictions** that serve no technical purpose
2. **Auto-fix structural issues** that don't require user decisions
3. **Reduce retry cycles** by 10-20 seconds per workflow generation

## Changes to Implement

### 1. Remove Python Identifier Validation for Input/Output Names

**Current State**:
- System rejects input names like `my-input`, `user.email`, `api-key`
- Error: "must be a valid Python identifier"
- This restriction is **completely artificial** - names are only used as dictionary keys and in templates

**Change**:
- Remove all `isidentifier()` validation checks
- Allow any reasonable string as input/output names
- Keep minimal validation: non-empty, no shell special chars (`$`, `|`, `>`, etc.)

**Impact**:
- ✅ Users can use natural parameter names: `api-key`, `user-email`, `file.path`
- ✅ Aligns with template regex that already supports hyphens
- ✅ Matches conventions from other CLI tools and APIs
- ✅ Backward compatible - existing workflows continue to work

### 2. Auto-Fix Unused Input Declarations

**Current State**:
- LLM often declares inputs "just in case" but never uses them
- Error: "Declared input(s) never used as template variable: X, Y, Z"
- Requires retry cycle (10-20 seconds) for non-functional issue

**Change**:
- Auto-remove unused inputs in `_post_process_workflow()`
- Clean up before validation runs
- Log what was removed for transparency

**Impact**:
- ✅ Eliminates unnecessary retry cycles
- ✅ Cleaner generated workflows
- ✅ Zero functional impact (unused inputs don't affect execution)

### 3. Auto-Fix Missing Edges for Single-Node Workflows

**Current State**:
- Error: "Missing 'edges' key in IR"
- Single-node workflows don't need edges but validation requires the key

**Change**:
- Auto-add `"edges": []` ONLY when workflow has exactly 1 node
- Multi-node workflows without edges remain an error (likely LLM mistake)

**Impact**:
- ✅ Single-node workflows work without boilerplate
- ✅ Multi-node workflows still validated for edge correctness
- ✅ Prevents masking real workflow structure issues

## Implementation Details

### Phase 1: Remove Python Identifier Validation

**Files to Modify**:
1. `src/pflow/runtime/workflow_validator.py` (~line 110)
2. `src/pflow/runtime/compiler.py` (~line 872)
3. `src/pflow/cli/main.py` (~line 2322)

**New Validation Function**:
```python
def is_valid_parameter_name(name: str) -> bool:
    """Check if a parameter name is valid.

    Allows most strings except:
    - Empty strings
    - Strings with shell special characters
    - Strings that could cause security issues
    """
    if not name or not name.strip():
        return False

    # Disallow shell special characters that could cause issues
    dangerous_chars = ['$', '|', '>', '<', '&', ';', '`', '\n', '\r', '\0']
    return not any(char in name for char in dangerous_chars)
```

**Changes**:
```python
# OLD (workflow_validator.py:110)
if not input_name.isidentifier():
    errors.append(...)

# NEW
if not is_valid_parameter_name(input_name):
    errors.append((
        f"Invalid input name '{input_name}' - contains special characters",
        f"inputs.{input_name}",
        "Avoid shell special characters like $, |, >, <, &, ;",
    ))
```

### Phase 2: Auto-Fix Structural Issues in Post-Processing

**File to Modify**: `src/pflow/planning/nodes.py` (WorkflowGeneratorNode)

**Enhanced Post-Processing Method**:
```python
def _post_process_workflow(self, workflow: dict) -> dict:
    """Post-process the generated workflow to fix structural issues.

    Handles:
    - Adding ir_version (always)
    - Removing unused inputs (cleanup)
    - Adding empty edges for single-node workflows
    """
    if not workflow:
        return workflow

    # 1. Always set IR version (existing)
    workflow["ir_version"] = "1.0.0"

    # 2. Remove unused inputs
    workflow = self._remove_unused_inputs(workflow)

    # 3. Add empty edges for single-node workflows
    workflow = self._fix_missing_edges(workflow)

    return workflow

def _remove_unused_inputs(self, workflow: dict) -> dict:
    """Remove declared inputs that are never used in templates."""
    if "inputs" not in workflow or not workflow["inputs"]:
        return workflow

    # Find all template variables used in the workflow
    used_vars = set()
    template_pattern = re.compile(r'\$\{([^}]+)\}')

    # Search through all node parameters
    for node in workflow.get("nodes", []):
        params = node.get("params", {})
        self._find_templates_in_value(params, template_pattern, used_vars)

    # Check workflow outputs too
    for output in workflow.get("outputs", {}).values():
        if isinstance(output, dict) and "node_id" in output:
            # Format: ${node_id.output_key}
            continue
        elif isinstance(output, str):
            matches = template_pattern.findall(output)
            for match in matches:
                # Extract base variable (before any dots)
                base_var = match.split('.')[0]
                used_vars.add(base_var)

    # Find unused inputs
    declared_inputs = set(workflow["inputs"].keys())
    unused = declared_inputs - used_vars

    # Remove unused inputs
    if unused:
        import logging
        logging.info(f"Auto-removing unused inputs: {', '.join(sorted(unused))}")
        for input_name in unused:
            del workflow["inputs"][input_name]

        # Remove inputs key entirely if now empty
        if not workflow["inputs"]:
            del workflow["inputs"]

    return workflow

def _find_templates_in_value(self, value: Any, pattern: re.Pattern, used_vars: set):
    """Recursively find template variables in a value."""
    if isinstance(value, str):
        matches = pattern.findall(value)
        for match in matches:
            # Extract base variable (before any dots or paths)
            base_var = match.split('.')[0]
            used_vars.add(base_var)
    elif isinstance(value, dict):
        for v in value.values():
            self._find_templates_in_value(v, pattern, used_vars)
    elif isinstance(value, list):
        for item in value:
            self._find_templates_in_value(item, pattern, used_vars)

def _fix_missing_edges(self, workflow: dict) -> dict:
    """Add empty edges array for single-node workflows."""
    # Only auto-fix if there's exactly one node
    nodes = workflow.get("nodes", [])
    if len(nodes) == 1 and "edges" not in workflow:
        import logging
        logging.info("Auto-adding empty edges array for single-node workflow")
        workflow["edges"] = []

    return workflow
```

### Phase 3: Update Template Resolver Pattern (Optional Enhancement)

**File**: `src/pflow/runtime/template_resolver.py`

Since the template pattern already supports hyphens, we might want to expand it further:

```python
# Current pattern supports: word chars + hyphens
TEMPLATE_PATTERN = re.compile(r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}")

# Could expand to support more (numbers at start, etc.)
TEMPLATE_PATTERN = re.compile(r"(?<!\$)\$\{([^}]+)\}")  # Most permissive
```

## Testing Strategy

### 1. Unit Tests for Parameter Name Validation

**New test file**: `tests/test_runtime/test_parameter_validation.py`

```python
def test_parameter_name_validation():
    """Test the new parameter name validation rules."""
    # Valid names (should pass)
    assert is_valid_parameter_name("my-input")
    assert is_valid_parameter_name("user.email")
    assert is_valid_parameter_name("api_key")
    assert is_valid_parameter_name("123-start")
    assert is_valid_parameter_name("firstName")

    # Invalid names (should fail)
    assert not is_valid_parameter_name("")
    assert not is_valid_parameter_name("  ")
    assert not is_valid_parameter_name("my$var")
    assert not is_valid_parameter_name("cmd|pipe")
    assert not is_valid_parameter_name("file>output")
```

### 2. Unit Tests for Auto-Fix Logic

**New test file**: `tests/test_planning/test_workflow_post_processing.py`

```python
def test_remove_unused_inputs():
    """Test automatic removal of unused inputs."""
    workflow = {
        "inputs": {
            "used_input": {"type": "string"},
            "unused_input": {"type": "string"},
            "another_unused": {"type": "string"}
        },
        "nodes": [{
            "id": "node1",
            "type": "test",
            "params": {
                "value": "${used_input}"
            }
        }]
    }

    processed = node._remove_unused_inputs(workflow)
    assert "used_input" in processed["inputs"]
    assert "unused_input" not in processed["inputs"]
    assert "another_unused" not in processed["inputs"]

def test_fix_missing_edges_single_node():
    """Test auto-adding edges for single-node workflows."""
    workflow = {
        "nodes": [{"id": "only_node", "type": "test"}]
        # Note: no edges key
    }

    processed = node._fix_missing_edges(workflow)
    assert "edges" in processed
    assert processed["edges"] == []

def test_fix_missing_edges_multi_node():
    """Test that multi-node workflows are NOT auto-fixed."""
    workflow = {
        "nodes": [
            {"id": "node1", "type": "test"},
            {"id": "node2", "type": "test"}
        ]
        # Note: no edges key - this is an error!
    }

    processed = node._fix_missing_edges(workflow)
    assert "edges" not in processed  # Should NOT auto-add
```

### 3. Integration Tests

**Update**: `tests/test_planning/integration/test_planner_retry_behavior.py`

Test that workflows with:
- Hyphenated input names work end-to-end
- Unused inputs are automatically removed
- Single-node workflows don't require edges

### 4. Regression Tests

Ensure existing workflows continue to work:
- Run full test suite with `make test`
- Verify all existing integration tests pass
- Check that backward compatibility is maintained

## Implementation Order

### Step 1: Remove Python Identifier Validation (30 min)
1. Create `is_valid_parameter_name()` function
2. Update validation in 3 files
3. Add unit tests
4. Run existing tests to ensure compatibility

### Step 2: Implement Auto-Fix for Unused Inputs (45 min)
1. Add `_remove_unused_inputs()` method
2. Integrate into `_post_process_workflow()`
3. Add comprehensive tests
4. Test with real planner workflows

### Step 3: Implement Auto-Fix for Missing Edges (20 min)
1. Add `_fix_missing_edges()` method
2. Integrate into `_post_process_workflow()`
3. Add tests for single vs multi-node cases
4. Verify with integration tests

### Step 4: Full Integration Testing (30 min)
1. Run complete test suite
2. Test with example workflows
3. Verify planner behavior improvements
4. Check performance impact

## Risk Assessment

### Low Risk ✅
- **Removing identifier validation**: Only makes system more permissive
- **Removing unused inputs**: No functional impact
- **Adding edges for single nodes**: Clear, unambiguous case

### Mitigations
- Comprehensive test coverage before deployment
- Logging for all auto-fixes for transparency
- Careful validation that multi-node workflows still require edges
- Keep some parameter validation (no shell special chars)

## Success Metrics

1. **Reduced retry rates**: Fewer workflows need retry cycles
2. **Faster generation**: 10-20 second reduction per affected workflow
3. **Better UX**: Natural parameter names like `api-key` work
4. **No regressions**: All existing workflows continue to function

## Documentation Updates

1. Update workflow documentation to show new parameter naming flexibility
2. Document auto-fix behavior in architecture docs
3. Update error messages to reflect new validation rules
4. Add examples with hyphenated parameter names

## Future Considerations

1. **Track auto-fix metrics**: Log what gets auto-fixed for analysis
2. **User preferences**: Could add settings to disable auto-fixes if needed
3. **Expand auto-fixes**: Other structural issues that could be auto-corrected
4. **Smarter validation**: Contextual validation based on node types

## Summary

These changes will:
- **Save 10-20 seconds** per workflow generation that has these issues
- **Remove artificial restrictions** that frustrate users
- **Clean up generated workflows** automatically
- **Maintain safety** by only auto-fixing unambiguous structural issues

The implementation is straightforward, risk is low, and the benefits are significant.