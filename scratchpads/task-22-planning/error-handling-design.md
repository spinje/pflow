# Error Handling Design for Named Workflow Execution

## Core Principles (Based on Research)

1. **User-Friendly Messages**: Use "cli:" prefix, clear language, actionable guidance
2. **Helpful Suggestions**: Show available options, examples, and next steps
3. **Consistent Format**: Follow established patterns for errors and warnings
4. **Graceful Degradation**: Fall back to planner when unsure

## Error Scenarios and Handling

### 1. Workflow Resolution Errors

#### Workflow Not Found
```python
# When user types: pflow my-workflow
if not workflow_found:
    # Get list of available workflows for suggestions
    available = wm.list_all()
    similar = find_similar_names(workflow_name, available)

    if similar:
        raise click.ClickException(
            f"cli: Workflow '{workflow_name}' not found.\n"
            f"Did you mean one of these?\n" +
            "\n".join(f"  - {name}" for name in similar[:3]) +
            f"\n\nUse 'pflow workflow list' to see all available workflows."
        )
    else:
        raise click.ClickException(
            f"cli: Workflow '{workflow_name}' not found.\n"
            f"Use 'pflow workflow list' to see available workflows.\n"
            f"Or use natural language: pflow \"your request here\""
        )
```

#### File Not Found (with .json extension)
```python
# When user types: pflow ./my-workflow.json
if path_looks_like_file and not exists:
    raise click.ClickException(
        f"cli: File not found: '{file_path}'.\n"
        f"Check the file path and try again.\n"
        f"Or use --file flag: pflow --file {file_path}"
    )
```

#### Ambiguous Input
```python
# When something could be either a workflow or natural language
if ambiguous:
    click.echo(
        f"cli: '{input}' is ambiguous.\n"
        f"To run a saved workflow: pflow workflow run {input}\n"
        f"For natural language: pflow \"{input}\"",
        err=True
    )
    # Continue with planner as fallback
```

### 2. Parameter Validation Errors

#### Missing Required Parameters
```python
# When workflow needs params that weren't provided
if missing_required:
    click.echo(f"❌ Workflow '{workflow_name}' requires parameters:", err=True)
    for param, info in missing_params.items():
        desc = info.get('description', 'No description')
        click.echo(f"   - {param}: {desc}", err=True)

    # Show example usage
    example_params = ' '.join(f'{p}=<value>' for p in missing_params)
    click.echo(f"\n👉 Usage: pflow {workflow_name} {example_params}", err=True)
    ctx.exit(1)
```

#### Invalid Parameter Types
```python
# When parameter value doesn't match expected type
try:
    converted_value = convert_type(value, expected_type)
except ValueError:
    raise click.ClickException(
        f"cli: Invalid value for '{param}': '{value}'\n"
        f"Expected {expected_type}.\n"
        f"Example: {param}={get_example_value(expected_type)}"
    )
```

#### Unknown Parameters
```python
# When user provides params not declared in workflow
if unknown_params:
    click.echo(
        f"⚠️  Warning: Unknown parameters will be ignored: "
        f"{', '.join(unknown_params)}",
        err=True
    )
    if verbose:
        click.echo(
            f"cli: Use 'pflow workflow describe {workflow_name}' "
            f"to see accepted parameters",
            err=True
        )
```

### 3. Discovery Command Errors

#### Describe Non-Existent Workflow
```python
# pflow workflow describe unknown
if not wm.exists(workflow_name):
    available = wm.list_all()
    similar = find_similar_names(workflow_name, available)

    if similar:
        raise click.ClickException(
            f"cli: Workflow '{workflow_name}' not found.\n"
            f"Did you mean: {similar[0]}?"
        )
    else:
        raise click.ClickException(
            f"cli: Workflow '{workflow_name}' not found.\n"
            f"Use 'pflow workflow list' to see available workflows."
        )
```

#### Empty Workflow List
```python
# pflow workflow list (when no workflows saved)
if not workflows:
    click.echo("No workflows saved yet.\n")
    click.echo("To save a workflow:")
    click.echo('  1. Create a workflow: pflow "your task here"')
    click.echo('  2. When prompted, choose to save it')
    click.echo('\nOr load from file:')
    click.echo('  pflow --file path/to/workflow.json')
```

## Error Message Templates

### Standard Error Format
```
cli: <error description>
<guidance on how to fix>
<example or command to run>
```

### Warning Format
```
⚠️  Warning: <warning description>
<optional guidance in verbose mode>
```

### Success with Hints
```
✅ <success message>
<optional next steps>
```

## Fallback Strategy

When we can't determine user intent:
1. Log what we tried (in verbose mode)
2. Fall back to natural language planner
3. Let planner provide its own error if it fails

```python
if verbose:
    click.echo(
        f"cli: '{input}' not recognized as workflow. "
        f"Trying natural language planner...",
        err=True
    )
# Continue to planner
```

## JSON Output Mode

When `--output-format json` is used:
```python
{
    "success": false,
    "error": "Workflow 'unknown' not found",
    "error_type": "WorkflowNotFoundError",
    "suggestions": ["similar-workflow-1", "similar-workflow-2"]
}
```

## Exit Codes

- `0`: Success
- `1`: General error (missing params, not found, etc.)
- `2`: Invalid usage (bad command syntax)
- `130`: User interrupt (Ctrl+C)

## Helper Functions Needed

```python
def find_similar_names(name: str, available: list[str], max_results: int = 3) -> list[str]:
    """Find similar workflow names using substring matching."""
    # Simple substring matching (like registry)
    matches = [n for n in available if name.lower() in n.lower()]
    if not matches:
        # Try reverse - is name a superstring?
        matches = [n for n in available if n.lower() in name.lower()]
    return matches[:max_results]

def get_example_value(type_hint: str) -> str:
    """Get example value for a type."""
    examples = {
        "string": "example-text",
        "int": "42",
        "float": "3.14",
        "bool": "true",
        "array": '["item1","item2"]',
        "object": '{"key":"value"}'
    }
    return examples.get(type_hint, "value")
```