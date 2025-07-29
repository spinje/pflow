# Task 21: Implementation Examples and Code Snippets

## Workflow with Complete Interface Declaration

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "issue_number": {
      "description": "GitHub issue number to fix",
      "required": true,
      "type": "string"
    },
    "repo_name": {
      "description": "Repository name (owner/repo format)",
      "required": false,
      "type": "string",
      "default": "pflow/pflow"
    },
    "max_files": {
      "description": "Maximum files to modify",
      "required": false,
      "type": "number",
      "default": 5
    }
  },
  "outputs": {
    "pr_url": {
      "description": "URL of the created pull request",
      "type": "string"
    },
    "pr_number": {
      "description": "Pull request number",
      "type": "number"
    },
    "files_changed": {
      "description": "List of modified files",
      "type": "array"
    }
  },
  "nodes": [
    {
      "id": "fetch_issue",
      "type": "github-get-issue",
      "params": {
        "issue": "$issue_number",
        "repo": "$repo_name"
      }
    }
  ]
}
```

## Compiler Validation Examples

### Missing Required Input Error
```
ValidationError: Workflow requires input 'issue_number' (GitHub issue number to fix)
Path: inputs.issue_number
Suggestion: Provide this parameter in initial_params when compiling the workflow
```

### Invalid Input Name Error
```
ValidationError: Input name 'issue-number' is not a valid Python identifier
Path: inputs.issue-number
Suggestion: Use names that match Python identifier rules (letters, numbers, underscore)
```

### Output Warning (Not Error)
```
WARNING: Declared output 'dynamic_result' cannot be traced to any node in the workflow. This may be fine if nodes write dynamic keys.
```

## Context Builder Display

### Before (Metadata Level)
```
**Inputs**:
- `issue_number`
- `repo_name`

**Outputs**:
- `pr_url`
```

### After (IR Level)
```
**Inputs**:
- `issue_number: string` - GitHub issue number to fix
- `repo_name: string` - Repository name (owner/repo format) (optional, default: pflow/pflow)
- `max_files: number` - Maximum files to modify (optional, default: 5)

**Outputs**:
- `pr_url: string` - URL of the created pull request
- `pr_number: number` - Pull request number
- `files_changed: array` - List of modified files
```

## Python Implementation Snippets

### Input Validation in Compiler
```python
def _validate_inputs(
    workflow_ir: dict[str, Any], initial_params: dict[str, Any]
) -> None:
    """Validate initial parameters against declared inputs."""
    inputs_declaration = workflow_ir.get("inputs", {})
    if not inputs_declaration:
        return  # No validation needed

    for input_name, input_spec in inputs_declaration.items():
        # Validate identifier
        if not input_name.isidentifier():
            raise ValidationError(
                message=f"Input name '{input_name}' is not a valid Python identifier",
                path=f"inputs.{input_name}",
                suggestion="Use names that match Python identifier rules"
            )

        # Check required inputs
        if input_spec.get("required", True) and input_name not in initial_params:
            desc = input_spec.get("description", "No description provided")
            raise ValidationError(
                message=f"Workflow requires input '{input_name}' ({desc})",
                path=f"inputs.{input_name}",
                suggestion="Provide this parameter in initial_params"
            )

        # Apply defaults for optional inputs
        if input_name not in initial_params and not input_spec.get("required", True):
            if "default" in input_spec:
                initial_params[input_name] = input_spec["default"]
```

### Enhanced Template Error Messages
```python
def _get_input_description(variable: str, workflow_ir: dict[str, Any]) -> str:
    """Get description for an input variable if available."""
    inputs = workflow_ir.get("inputs", {})
    if variable in inputs:
        input_def = inputs[variable]
        parts = []

        # Add description
        if desc := input_def.get("description"):
            parts.append(desc)

        # Add type
        if type_hint := input_def.get("type"):
            parts.append(f"type: {type_hint}")

        # Add required/optional info
        if not input_def.get("required", True):
            if "default" in input_def:
                parts.append(f"optional, default: {input_def['default']}")
            else:
                parts.append("optional")
        else:
            parts.append("required")

        return f" ({', '.join(parts)})" if parts else ""
    return ""
```

## Testing Patterns

### Schema Validation Test
```python
def test_workflow_with_complete_interfaces(self):
    """Test workflow with both input and output declarations."""
    ir = {
        "ir_version": "0.1.0",
        "inputs": {
            "text": {
                "description": "Input text",
                "required": True,
                "type": "string"
            }
        },
        "outputs": {
            "summary": {
                "description": "Generated summary",
                "type": "string"
            }
        },
        "nodes": [{"id": "n1", "type": "test"}]
    }

    # Should validate successfully
    validated = validate_ir(ir)
    assert validated["inputs"]["text"]["required"] is True
    assert validated["outputs"]["summary"]["type"] == "string"
```

### Compiler Integration Test
```python
def test_missing_required_input_shows_description(self):
    """Test that error includes input description."""
    ir = {
        "ir_version": "0.1.0",
        "inputs": {
            "api_key": {
                "description": "API authentication key",
                "required": True,
                "type": "string"
            }
        },
        "nodes": [{"id": "n1", "type": "test"}]
    }

    with pytest.raises(ValidationError) as exc_info:
        compile_ir_to_flow(ir, registry, {})  # Missing api_key

    error = exc_info.value
    assert "API authentication key" in str(error)
    assert error.path == "inputs.api_key"
```

## Migration Examples

### Old Format (Metadata Level)
```json
{
  "name": "analyzer",
  "description": "Text analyzer workflow",
  "inputs": ["text", "language"],        // Simple arrays
  "outputs": ["summary", "word_count"],  // No type info
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [...]
  }
}
```

### New Format (IR Level Only)
```json
{
  "name": "analyzer",
  "description": "Text analyzer workflow",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {
      "text": {
        "description": "Text to analyze",
        "required": true,
        "type": "string"
      },
      "language": {
        "description": "Language code",
        "required": false,
        "type": "string",
        "default": "en"
      }
    },
    "outputs": {
      "summary": {
        "description": "Generated summary",
        "type": "string"
      },
      "word_count": {
        "description": "Number of words",
        "type": "number"
      }
    },
    "nodes": [...]
  }
}
```

## Usage in pflow CLI

```bash
# Valid execution with all inputs
pflow run workflow.json --param issue_number=123 --param repo_name=owner/repo

# Using defaults (repo_name will use default)
pflow run workflow.json --param issue_number=123

# Error case - missing required input
pflow run workflow.json
# Error: Workflow requires input 'issue_number' (GitHub issue number to fix)

# With debugging to see output warnings
PFLOW_LOG_LEVEL=DEBUG pflow run workflow.json --param issue_number=123
# WARNING: Declared output 'dynamic_key' cannot be traced to any node...
```
