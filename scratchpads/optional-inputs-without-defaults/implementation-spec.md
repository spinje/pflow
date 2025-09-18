# Implementation Specification: Optional Workflow Inputs Without Defaults

## Problem Statement

Currently, when optional workflow inputs are not provided and have no default value, template variables remain unresolved (e.g., `${repo_name}` stays as literal string). This prevents nodes from detecting "not provided" and applying their own smart defaults.

## Solution Overview

Skip passing unresolved template parameters to nodes entirely, allowing nodes' built-in smart default logic to activate naturally.

## Technical Specification

### 1. Core Change: Template Resolution in NodeWrapper

**File**: `src/pflow/runtime/node_wrapper.py`

**Current Behavior** (lines 124-131):
```python
if simple_var_match:
    var_name = simple_var_match.group(1)
    resolved_value = TemplateResolver.resolve_value(var_name, context)
    if resolved_value is not None:
        resolved_params[key] = resolved_value
    else:
        # Variable not found, keep template as-is
        resolved_params[key] = template  # ❌ Passes literal "${variable}"
```

**New Behavior**:
```python
if simple_var_match:
    var_name = simple_var_match.group(1)
    resolved_value = TemplateResolver.resolve_value(var_name, context)
    if resolved_value is not None:
        resolved_params[key] = resolved_value
    # else: Skip adding to resolved_params entirely
    # This allows nodes to use their smart defaults
```

### 2. Add Variable Existence Check to TemplateResolver

**File**: `src/pflow/runtime/template_resolver.py`

**New Method**:
```python
@staticmethod
def variable_exists(var_name: str, context: dict) -> bool:
    """Check if a variable exists in context (distinct from being None).

    Args:
        var_name: Variable name (may include paths like 'user.name')
        context: Dictionary to search in

    Returns:
        True if variable exists (even if None), False if not found
    """
    if "." in var_name:
        # Check path exists and is traversable
        parts = var_name.split(".")
        current = context
        for part in parts[:-1]:  # All but last part must be dict
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        # Check last part exists
        return isinstance(current, dict) and parts[-1] in current
    else:
        return var_name in context
```

### 3. Enhanced Template Resolution with Existence Check

**Modified resolve_value**:
```python
@staticmethod
def resolve_value(var_name: str, context: dict) -> Optional[Any]:
    """Resolve a variable to its value, returning None if not found.

    NOTE: Cannot distinguish between 'variable is None' and 'variable not found'.
    Use variable_exists() to check existence separately if needed.
    """
    # Existing implementation unchanged
    # But callers can now use variable_exists() for distinction
```

### 4. Update NodeWrapper Resolution Logic

**Enhanced resolution with debug logging**:
```python
def _resolve_templates(self, context: dict) -> dict:
    """Resolve template parameters, skipping unresolved optional ones."""
    resolved_params = {}

    for key, template in self.template_params.items():
        if isinstance(template, str) and "${" in template:
            simple_var_match = re.match(r"^\$\{([^}]+)\}$", template)

            if simple_var_match:
                var_name = simple_var_match.group(1)

                # Check if variable exists in context
                if TemplateResolver.variable_exists(var_name, context):
                    # Variable exists - resolve it (even if None)
                    resolved_value = TemplateResolver.resolve_value(var_name, context)
                    resolved_params[key] = resolved_value
                else:
                    # Variable doesn't exist - skip parameter entirely
                    logger.debug(
                        f"Skipping parameter '{key}' - template variable "
                        f"'${{{var_name}}}' not found in context (will use node's default)"
                    )
            else:
                # Complex template - resolve as string
                resolved_value = TemplateResolver.resolve_string(template, context)
                if resolved_value != template:  # Was resolved
                    resolved_params[key] = resolved_value
                else:
                    # Contains unresolved variables - skip
                    logger.debug(
                        f"Skipping parameter '{key}' - template '{template}' "
                        f"contains unresolved variables"
                    )
        else:
            # Non-template parameter - pass through
            resolved_params[key] = template

    return resolved_params
```

### 5. Validation Improvements (Optional)

**File**: `src/pflow/runtime/template_validator.py`

Add warnings for optional inputs referenced in templates:
```python
def validate_workflow_templates(workflow_ir: dict) -> List[str]:
    """Validate templates with awareness of optional inputs."""
    errors = []
    warnings = []

    # ... existing validation ...

    # Check for optional inputs without defaults used in templates
    for input_name in workflow_ir.get("inputs", {}):
        input_spec = workflow_ir["inputs"][input_name]
        is_required = input_spec.get("required", True)
        has_default = "default" in input_spec

        if not is_required and not has_default:
            # Check if this input is used in any template
            template_pattern = f"${{{input_name}}}"
            if _is_template_used_in_workflow(template_pattern, workflow_ir):
                warnings.append(
                    f"Optional input '{input_name}' has no default value. "
                    f"Parameters using this input will be skipped if not provided, "
                    f"allowing nodes to use their smart defaults."
                )

    # Log warnings but don't fail validation
    for warning in warnings:
        logger.info(f"Template validation info: {warning}")

    return errors  # Return only errors, not warnings
```

## Test Updates Required

### 1. Update Failing Tests

**File**: `tests/test_runtime/test_template_resolver.py`

```python
def test_preserves_unresolved_templates():
    """Test that unresolved templates are handled correctly."""
    context = {"found": "yes"}
    template = "Found: ${found}, Missing: ${missing}"
    # Old assertion: == "Found: yes, Missing: ${missing}"
    # New assertion:
    assert TemplateResolver.resolve_string(template, context) == "Found: yes, Missing: ${missing}"
    # Note: This still preserves unresolved in complex templates for debugging
```

**File**: `tests/test_runtime/test_node_wrapper.py`

```python
def test_unresolved_templates_skipped():
    """Test that unresolved template parameters are skipped entirely."""
    # Old: expects params["missing"] == "${undefined}"
    # New: expects "missing" not in params
    wrapper = TemplateAwareNodeWrapper(...)
    wrapper.template_params = {"missing": "${undefined}"}
    result = wrapper._resolve_templates({})
    assert "missing" not in result  # Parameter skipped entirely
```

### 2. Add New Tests

**File**: `tests/test_runtime/test_optional_inputs.py`

```python
def test_optional_input_without_default_not_provided():
    """Test optional input without default when not provided."""
    workflow_ir = {
        "inputs": {
            "repo": {
                "description": "Repository",
                "required": False
                # No default specified
            }
        },
        "nodes": [{
            "id": "list",
            "type": "github-list-issues",
            "params": {"repository": "${repo}"}
        }]
    }

    # Compile without providing repo
    flow = compile_ir_to_flow(workflow_ir, initial_params={})

    # Node should not receive repository parameter
    # Will use its smart default (current repo)
    assert "repository" not in flow.nodes[0].params

def test_optional_input_with_null_default():
    """Test optional input with explicit null default."""
    workflow_ir = {
        "inputs": {
            "repo": {
                "description": "Repository",
                "required": False,
                "default": None  # Explicit null
            }
        },
        "nodes": [{
            "id": "list",
            "type": "github-list-issues",
            "params": {"repository": "${repo}"}
        }]
    }

    # Compile without providing repo
    flow = compile_ir_to_flow(workflow_ir, initial_params={})

    # Node should receive None
    assert flow.nodes[0].params["repository"] is None

def test_optional_input_with_empty_default():
    """Test optional input with empty string default."""
    workflow_ir = {
        "inputs": {
            "repo": {
                "description": "Repository",
                "required": False,
                "default": ""  # Empty string
            }
        },
        "nodes": [{
            "id": "list",
            "type": "github-list-issues",
            "params": {"repository": "${repo}"}
        }]
    }

    # Compile without providing repo
    flow = compile_ir_to_flow(workflow_ir, initial_params={})

    # Node should receive empty string
    assert flow.nodes[0].params["repository"] == ""
```

### 3. GitHub Node Tests

**File**: `tests/test_nodes/test_github/test_smart_defaults.py`

```python
def test_github_node_uses_current_repo_when_not_provided():
    """Test that GitHub nodes use current repo when parameter not provided."""
    node = ListIssuesNode()
    node.params = {}  # No repository parameter

    # Mock subprocess to verify gh command
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.stdout = '[]'
        node.exec({})

        # Verify gh was called WITHOUT --repo flag
        call_args = mock_run.call_args[0][0]
        assert "--repo" not in call_args
        # gh will use current directory's repo
```

## Implementation Order

### Phase 1: Core Changes (Day 1)
1. ✅ Add `variable_exists()` method to TemplateResolver
2. ✅ Modify node_wrapper.py to skip unresolved parameters
3. ✅ Add debug logging for skipped parameters
4. ✅ Update the 2 failing tests

### Phase 2: Testing (Day 1-2)
1. ✅ Add comprehensive test suite for optional inputs
2. ✅ Test GitHub nodes with smart defaults
3. ✅ Run full test suite to ensure no regressions
4. ✅ Test with real workflows

### Phase 3: Validation & Documentation (Day 2)
1. ✅ Add informational warnings for optional inputs without defaults
2. ✅ Update documentation about optional input behavior
3. ✅ Create examples showing smart default usage

## Backwards Compatibility

### Breaking Changes
- Workflows that relied on seeing literal `${variable}` strings will no longer work
- Debug workflows that displayed unresolved templates will show empty values instead

### Migration Path
- Most workflows unaffected (95%+ use proper inputs/outputs)
- For debugging: Use pflow logging instead of output inspection
- For template generation: Use escape sequences or different syntax

### Risk Assessment
- **Low Risk**: No production users, pre-1.0 software
- **Improved UX**: Workflows run instead of failing
- **Clear Benefits**: Smart defaults work as intended

## Success Criteria

1. ✅ Optional inputs without defaults don't cause validation errors
2. ✅ Nodes receive no parameter instead of `${variable}` string
3. ✅ Smart defaults activate correctly (e.g., GitHub current repo)
4. ✅ Debug logging shows which parameters were skipped
5. ✅ All existing tests pass (after updates)
6. ✅ New test coverage for optional parameter scenarios

## Example Workflows

### Before (Would Fail)
```json
{
  "inputs": {
    "repo": {"required": false}
  },
  "nodes": [{
    "type": "github-list-issues",
    "params": {"repository": "${repo}"}
  }]
}
```
Error: `gh --repo "${repo}"` - invalid repository

### After (Works with Smart Default)
```json
{
  "inputs": {
    "repo": {"required": false}
  },
  "nodes": [{
    "type": "github-list-issues",
    "params": {"repository": "${repo}"}
  }]
}
```
Success: `gh issue list` - uses current repository

## Security Considerations

- No security impact - reducing surface area by not passing unresolved strings
- Prevents potential injection if `${variable}` was ever executed
- Maintains all existing validation and sanitization

## Performance Impact

- Negligible - one additional dict lookup per template variable
- Slightly faster execution by skipping unresolved parameters
- No additional memory overhead