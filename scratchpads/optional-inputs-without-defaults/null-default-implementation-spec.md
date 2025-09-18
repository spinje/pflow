# Implementation Specification: Null Defaults for Smart Node Defaults

## Overview

Enable optional workflow inputs to use `null` as an explicit default value that signals nodes to use their built-in smart defaults (e.g., GitHub nodes using current repository).

## Problem Statement

Currently, when workflow inputs have `null` as default value, the template resolver converts them to empty strings. This prevents nodes from detecting the "use smart default" signal.

## Solution

Preserve `null` values through template resolution for simple template variables, allowing nodes to receive `null` and apply their smart defaults.

## Technical Specification

### 1. Current Behavior Analysis

**Workflow Input Declaration**:
```json
{
  "inputs": {
    "repo": {
      "description": "GitHub repository",
      "required": false,
      "default": null  // Currently supported in schema
    }
  }
}
```

**Current Template Resolution Path**:
1. `workflow_validator.py`: Applies `null` default → ✅ Works
2. `node_wrapper.py`: Resolves template → ✅ Gets `null`
3. `template_resolver.py`: Converts to string → ❌ `null` becomes `""`

### 2. Required Change: Preserve Null in Simple Templates

**File**: `src/pflow/runtime/node_wrapper.py`

**Location**: `_run` method, lines 115-140

**Current Code**:
```python
if simple_var_match:
    var_name = simple_var_match.group(1)
    resolved_value = TemplateResolver.resolve_value(var_name, context)
    if resolved_value is not None:
        # Use the resolved value with its original type preserved
        resolved_params[key] = resolved_value
    else:
        # Variable not found, keep template as-is
        resolved_params[key] = template
```

**Problem**: This already preserves type! The issue is elsewhere...

**Real Issue**: After further investigation, the problem is in how we check for `None`:
```python
if resolved_value is not None:  # This excludes null values!
```

**Fix**:
```python
if simple_var_match:
    var_name = simple_var_match.group(1)

    # Check if variable exists in context (new distinction)
    if var_name in context or "." in var_name:
        # Variable exists, use its value (including None/null)
        resolved_value = TemplateResolver.resolve_value(var_name, context)
        resolved_params[key] = resolved_value
    else:
        # Variable doesn't exist, keep template for debugging
        resolved_params[key] = template
```

### 3. Add Variable Existence Check

**File**: `src/pflow/runtime/template_resolver.py`

**New Helper Method**:
```python
@staticmethod
def variable_exists(var_name: str, context: dict) -> bool:
    """Check if a variable exists in context, regardless of its value.

    Args:
        var_name: Variable name, may include dots for nested access
        context: The context dictionary

    Returns:
        True if variable exists (even if None), False otherwise
    """
    if "." in var_name:
        parts = var_name.split(".")
        current = context

        # Navigate to parent
        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
            if current is None:
                return False  # Can't traverse through None

        # Check final part
        return isinstance(current, dict) and parts[-1] in current
    else:
        return var_name in context
```

### 4. Updated Node Wrapper Logic

**Complete fix for `_run` method**:
```python
# Around line 124-140 in node_wrapper.py
for key, template in self.template_params.items():
    if isinstance(template, str) and "${" in template:
        # Check for simple variable reference
        simple_var_match = re.match(r"^\$\{([^}]+)\}$", template)

        if simple_var_match:
            # Simple variable - preserve original type
            var_name = simple_var_match.group(1)

            # Check if variable exists (including null values)
            if TemplateResolver.variable_exists(var_name, context):
                resolved_value = TemplateResolver.resolve_value(var_name, context)
                resolved_params[key] = resolved_value  # Preserves null

                logger.debug(
                    f"Resolved template parameter '{key}': "
                    f"${{{var_name}}} -> {resolved_value!r} ({type(resolved_value).__name__})"
                )
            else:
                # Variable doesn't exist - keep template for debugging
                resolved_params[key] = template
                logger.debug(
                    f"Template parameter '{key}' unresolved: "
                    f"variable '${{{var_name}}}' not found in context"
                )
        else:
            # Complex template - must resolve to string
            resolved_value = TemplateResolver.resolve_string(template, context)
            resolved_params[key] = resolved_value
    else:
        # Not a template
        resolved_params[key] = template
```

## Behavior Examples

### Example 1: Null Default for Smart Default
```json
{
  "inputs": {
    "repo": {
      "required": false,
      "default": null
    }
  },
  "nodes": [{
    "params": {"repository": "${repo}"}
  }]
}
```
**Result**: Node receives `params["repository"] = None` → Uses current repo

### Example 2: Empty String Default
```json
{
  "inputs": {
    "repo": {
      "required": false,
      "default": ""
    }
  }
}
```
**Result**: Node receives `params["repository"] = ""` → Uses empty string

### Example 3: Complex Template with Null
```json
{
  "inputs": {
    "repo": {
      "required": false,
      "default": null
    }
  },
  "nodes": [{
    "params": {"message": "Repo: ${repo}"}
  }]
}
```
**Result**: Node receives `params["message"] = "Repo: "` (null → "" in strings)

### Example 4: Missing Variable (Typo)
```json
{
  "nodes": [{
    "params": {"repository": "${repo_typo}"}
  }]
}
```
**Result**: Validation error - `Template variable ${repo_typo} not found`

## Test Coverage

### 1. New Test File: `tests/test_runtime/test_null_defaults.py`

```python
import pytest
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.runtime.template_resolver import TemplateResolver

class TestNullDefaults:
    """Test null default handling for smart defaults."""

    def test_null_default_preserves_none(self):
        """Test that null defaults pass None to nodes."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{
                "id": "test",
                "type": "test-node",
                "params": {"repo": "${repository}"}
            }],
            "inputs": {
                "repository": {
                    "description": "Repository",
                    "required": False,
                    "default": None
                }
            }
        }

        # Compile without providing repository
        flow = compile_ir_to_flow(workflow_ir, initial_params={})

        # Node should receive None (not empty string)
        assert flow.nodes["test"].params["repo"] is None

    def test_empty_string_default(self):
        """Test that empty string defaults are preserved."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{
                "id": "test",
                "type": "test-node",
                "params": {"repo": "${repository}"}
            }],
            "inputs": {
                "repository": {
                    "description": "Repository",
                    "required": False,
                    "default": ""
                }
            }
        }

        flow = compile_ir_to_flow(workflow_ir, initial_params={})
        assert flow.nodes["test"].params["repo"] == ""

    def test_null_in_complex_template(self):
        """Test that null becomes empty string in complex templates."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{
                "id": "test",
                "type": "test-node",
                "params": {"message": "Repository: ${repository}"}
            }],
            "inputs": {
                "repository": {
                    "required": False,
                    "default": None
                }
            }
        }

        flow = compile_ir_to_flow(workflow_ir, initial_params={})
        # Null should become empty string in complex template
        assert flow.nodes["test"].params["message"] == "Repository: "

    def test_variable_exists_check(self):
        """Test the variable_exists helper method."""
        context = {
            "present": "value",
            "null_value": None,
            "nested": {"field": "value", "null_field": None}
        }

        # Present variables
        assert TemplateResolver.variable_exists("present", context) is True
        assert TemplateResolver.variable_exists("null_value", context) is True
        assert TemplateResolver.variable_exists("nested.field", context) is True
        assert TemplateResolver.variable_exists("nested.null_field", context) is True

        # Missing variables
        assert TemplateResolver.variable_exists("missing", context) is False
        assert TemplateResolver.variable_exists("nested.missing", context) is False

        # Can't traverse through None
        assert TemplateResolver.variable_exists("null_value.field", context) is False
```

### 2. Integration Test: `tests/test_nodes/test_github/test_null_defaults.py`

```python
def test_github_node_with_null_repo():
    """Test that GitHub nodes handle null repo parameter correctly."""
    from pflow.nodes.github.list_issues import ListIssuesNode

    node = ListIssuesNode()
    node.params = {"repository": None}  # Explicit None

    # Mock subprocess to verify command
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.stdout = '[]'
        mock_run.return_value.returncode = 0

        result = node.exec({"repository": None})

        # Verify gh was called WITHOUT --repo flag
        call_args = mock_run.call_args[0][0]
        assert "gh" in call_args
        assert "issue" in call_args
        assert "list" in call_args
        assert "--repo" not in call_args  # No repo flag = use current
```

## Implementation Plan

### Phase 1: Core Implementation (2-3 hours)
1. ✅ Add `variable_exists()` method to TemplateResolver
2. ✅ Update node_wrapper.py to use existence check
3. ✅ Add debug logging for null vs missing distinction
4. ✅ Ensure null preservation for simple templates

### Phase 2: Testing (2-3 hours)
1. ✅ Create comprehensive test file for null defaults
2. ✅ Add integration tests for GitHub nodes
3. ✅ Verify existing tests still pass
4. ✅ Test with real workflows

### Phase 3: Documentation (1 hour)
1. ✅ Document null default pattern in user guide
2. ✅ Add examples to workflow documentation
3. ✅ Update docstrings for affected methods

## Documentation

### User Guide Addition

```markdown
## Optional Inputs with Smart Defaults

When defining optional workflow inputs, you can use `null` as the default value to signal that nodes should use their built-in smart defaults:

```json
{
  "inputs": {
    "repository": {
      "description": "GitHub repository (uses current if not provided)",
      "type": "string",
      "required": false,
      "default": null  // Tells node to use its smart default
    }
  }
}
```

### Default Value Semantics

- `"default": null` - Node uses its smart default behavior
- `"default": ""` - Node receives an empty string
- `"default": "value"` - Node receives the specified value
- No `default` with `required: false` - Must be provided by user

### Example: GitHub Node Smart Defaults

```json
{
  "inputs": {
    "repo": {
      "description": "Repository to query",
      "required": false,
      "default": null  // Use current repo if not provided
    },
    "limit": {
      "description": "Maximum issues to fetch",
      "required": false,
      "default": 30  // Explicit default of 30
    }
  },
  "nodes": [{
    "id": "list",
    "type": "github-list-issues",
    "params": {
      "repository": "${repo}",  // Gets null → uses current repo
      "limit": "${limit}"        // Gets 30 if not provided
    }
  }]
}
```
```

## Benefits of This Approach

1. **No Breaking Changes**: Additive enhancement only
2. **Explicit Intent**: Clear signal for smart defaults
3. **Type Safety**: Preserves actual null vs string values
4. **Validation Works**: Typos still caught as errors
5. **Debug Visibility**: Can see `null` in debug output
6. **Minimal Code Changes**: ~20 lines of code change

## Success Criteria

1. ✅ Workflows can use `default: null` for optional inputs
2. ✅ Nodes receive `None` instead of empty string
3. ✅ GitHub nodes use current repo when given `None`
4. ✅ Validation still catches typos and missing variables
5. ✅ Complex templates convert null to empty string
6. ✅ All existing tests pass
7. ✅ Clear documentation for users

## Risk Assessment

- **Low Risk**: Non-breaking, additive change
- **No Migration**: Existing workflows unchanged
- **Clear Semantics**: Explicit null = smart default
- **Node Compatibility**: Nodes already handle None