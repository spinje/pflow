# Alternative Approach: Null as Explicit "Use Smart Default" Signal

## The Proposal

Allow optional inputs to explicitly use `null` as a default value to signal "use node's smart default":

```json
{
  "inputs": {
    "repo_name": {
      "type": "string",
      "description": "GitHub repository",
      "required": false,
      "default": null  // Explicit null = "use smart default"
    }
  }
}
```

## Why This Is Better

### 1. **Explicit Intent** ✅
```json
// Clear: I want the smart default
"default": null

// Clear: I want empty string
"default": ""

// Clear: I want a specific default
"default": "owner/repo"

// Clear: This is required
"required": true  // No default needed
```

The workflow author explicitly states their intent.

### 2. **No Silent Failures** ✅
```json
{
  "params": {
    "repo": "${repo_naem}"  // Typo!
  }
}
```
Result: **Validation error** - `Template variable ${repo_naem} not found`

The typo is caught because `repo_naem` doesn't exist as an input.

### 3. **Preserves Debugging** ✅
- Validation still catches unresolved templates
- Debug output shows: `"repo": null` (clear that it's intentionally null)
- No ambiguity about what happened

### 4. **Consistent Behavior** ✅
- `null` always means "use smart default"
- Empty string `""` means "explicitly empty"
- Missing required inputs = error
- Templates must resolve or validation fails

### 5. **Already Partially Supported** ✅
The current code already handles null defaults:

```python
# From workflow_validator.py
default_value = input_spec.get("default")
if default_value is not None:  # This allows null!
    defaults[input_name] = default_value
```

## Implementation Requirements

### 1. **Template Resolution for Null Values**

Current behavior when variable is `null`:
```python
# TemplateResolver._convert_to_string()
if value is None or value == "":
    return ""  # ❌ Converts null to empty string
```

**Need to change for simple templates**:
```python
# In node_wrapper.py
if simple_var_match:
    var_name = simple_var_match.group(1)
    resolved_value = TemplateResolver.resolve_value(var_name, context)
    # Preserve null as null (don't convert to string)
    resolved_params[key] = resolved_value  # Keep null as null
```

### 2. **Node Behavior with Null**

Nodes already handle this well:
```python
# Current pattern in all nodes
repo = shared.get("repo") or self.params.get("repo")
# If params["repo"] is null, this evaluates to None
# Nodes already treat None as "use default"
```

### 3. **Update String Conversion**

For complex templates, null should still become empty string:
```python
# Complex template: "Repo: ${repo_name}"
# If repo_name is null: "Repo: " (empty string for null part)

# Simple template: "${repo_name}"
# If repo_name is null: null (preserve the null value)
```

## Example Workflows

### Workflow with Smart Default
```json
{
  "inputs": {
    "repo": {
      "description": "Repository (uses current if not provided)",
      "required": false,
      "default": null  // Explicit null default
    }
  },
  "nodes": [{
    "type": "github-list-issues",
    "params": {
      "repository": "${repo}"  // Gets null if not provided
    }
  }]
}
```

**User doesn't provide `repo`**:
- Input gets `null` as default
- Template resolves to `null`
- Node receives `params["repository"] = null`
- Node uses smart default (current repo)

### Workflow with Empty String Default
```json
{
  "inputs": {
    "prefix": {
      "description": "Prefix for issue titles",
      "required": false,
      "default": ""  // Explicit empty string
    }
  }
}
```

**User doesn't provide `prefix`**:
- Input gets `""` as default
- Template resolves to `""`
- Node receives `params["prefix"] = ""`
- Node uses empty string (no prefix)

## Benefits Over Original Proposal

| Aspect | Original (Skip Unresolved) | Null Default Approach |
|--------|----------------------------|----------------------|
| **Typo Detection** | ❌ Silent failure | ✅ Validation error |
| **Explicit Intent** | ❌ Implicit | ✅ Explicit `default: null` |
| **Debugging** | ❌ Parameter missing | ✅ `param: null` visible |
| **Consistency** | ❌ Different for simple/complex | ✅ Consistent behavior |
| **Breaking Change** | ❌ Yes | ✅ No (additive) |
| **User Control** | ❌ No | ✅ Yes (choose null, "", or value) |

## Implementation Steps

### Minimal Changes Needed

1. **Fix `_convert_to_string()` for simple templates**:
```python
# In node_wrapper.py, for simple templates only
if simple_var_match:
    var_name = simple_var_match.group(1)
    resolved_value = TemplateResolver.resolve_value(var_name, context)
    # Don't convert null to string for simple templates
    resolved_params[key] = resolved_value  # Preserve type
```

2. **Document the pattern**:
```markdown
## Optional Inputs with Smart Defaults

To allow nodes to use their built-in smart defaults, set `default: null`:

```json
"inputs": {
  "repo": {
    "required": false,
    "default": null  // Node will use its smart default
  }
}
```
```

3. **Add tests**:
```python
def test_null_default_preserves_null():
    """Test that null defaults pass null to nodes."""
    workflow_ir = {
        "inputs": {
            "repo": {"required": false, "default": None}
        },
        "nodes": [{
            "params": {"repository": "${repo}"}
        }]
    }

    flow = compile_ir_to_flow(workflow_ir, {})
    assert flow.nodes[0].params["repository"] is None
```

## Potential Issues

### 1. **Type Confusion**
Some nodes might not expect `null` in string fields:
```python
# Potential issue
repo: str = self.params["repo"]  # Could be None now
```

**Solution**: Nodes already use `.get()` pattern which handles this.

### 2. **JSON vs Python None**
JSON `null` becomes Python `None`. Need to ensure consistency.

**Solution**: Already handled by current JSON loading.

### 3. **Complex Templates with Null**
What about: `"Repo: ${repo_name}/issues"` when repo_name is null?

**Solution**: Complex templates convert null to empty string (current behavior).

## My Assessment

**This is a MUCH better approach than skipping unresolved templates!**

✅ **Explicit intent** - Users choose null for smart defaults
✅ **No silent failures** - Typos still caught by validation
✅ **Backward compatible** - Additive change only
✅ **Clear semantics** - null = use default, "" = empty, value = use value
✅ **Minimal code changes** - Mostly already works!

## Recommendation

**Yes, implement this approach!** It solves the original problem (enabling smart defaults) while avoiding all the issues with the skip-unresolved approach.

The key insight: **`default: null` is an explicit instruction to use smart defaults**, not a missing value or error state.