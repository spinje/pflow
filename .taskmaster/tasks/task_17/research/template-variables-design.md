# Template Variables Design

## Core Concept

Template variables enable workflows to be reusable by parameterizing values that change between executions. They follow a simple `$variable` or `${variable}` syntax and are resolved at runtime.

## Why Template Variables Matter

Without templates:
```json
{
  "nodes": [{
    "id": "get-issue",
    "type": "github-get-issue",
    "params": {
      "issue_number": 123,  // Hardcoded!
      "repo": "myrepo"      // Hardcoded!
    }
  }]
}
```

With templates:
```json
{
  "nodes": [{
    "id": "get-issue",
    "type": "github-get-issue",
    "params": {
      "issue_number": "$issue_number",  // Runtime parameter
      "repo": "$repo"                    // Runtime parameter
    }
  }]
}
```

## Template Syntax

### Basic Variables
- `$variable` - Simple variable reference
- `${variable}` - Explicit boundaries (useful in strings)

### String Interpolation
```json
{
  "prompt": "Analyze issue ${issue_number} in repo ${repo}"
}
```

### Escaping
- `$$variable` → `$variable` (literal dollar sign)

### Default Values (Future)
- `${variable:-default}` - Use default if variable not provided

## Implementation

### Resolution Function
```python
def resolve_template(template_str: str, available_vars: Dict[str, Any]) -> str:
    """
    Resolve template variables in a string.
    This is a SIMPLE regex-based substitution, not a full template engine.
    """
    import re

    def replacer(match):
        var_name = match.group(1) or match.group(2)
        if var_name not in available_vars:
            raise ValueError(f"Template variable ${var_name} not provided")
        return str(available_vars[var_name])

    # Match $var or ${var} but not $$var
    pattern = r'(?<!\$)\$([a-zA-Z_]\w*)|(?<!\$)\$\{([a-zA-Z_]\w*)\}'
    result = re.sub(pattern, replacer, template_str)

    # Handle escaped variables
    result = result.replace('$$', '$')

    return result
```

### Where Templates Are Used

1. **Node Parameters**
   ```json
   {
     "params": {
       "file_path": "$input_file",
       "encoding": "${encoding:-utf-8}"
     }
   }
   ```

2. **Shared Store Values**
   ```json
   {
     "shared_defaults": {
       "repo": "$github_repo",
       "branch": "$target_branch"
     }
   }
   ```

3. **Prompt Templates**
   ```json
   {
     "params": {
       "prompt": "Analyze the $document_type for $customer_name"
     }
   }
   ```

## Variable Sources

1. **CLI Parameters**
   ```bash
   pflow analyze-churn --customer-segment=enterprise --period="last month"
   # Creates: {customer_segment: "enterprise", period: "last month"}
   ```

2. **Natural Language Extraction**
   ```bash
   pflow "analyze churn for enterprise customers last month"
   # Planner extracts: {customer_segment: "enterprise", period: "last month"}
   ```

3. **Interactive Prompts**
   ```bash
   pflow analyze-churn
   # Missing required parameter: customer_segment
   # Enter customer_segment: enterprise
   ```

4. **Environment Variables** (Future)
   ```bash
   GITHUB_REPO=myrepo pflow fix-issue --issue=123
   ```

## Planner Integration

The planner generates workflows with appropriate template variables:

```python
def generate_workflow_with_templates(user_input: str, nodes: List[Node]) -> Dict:
    """Generate workflow using template variables for dynamic values."""

    # Identify values that should be parameterized
    parameters = extract_parameters(user_input)

    # Generate workflow with template variables
    workflow = {
        "nodes": [],
        "parameters": list(parameters.keys()),
        "parameter_defaults": {}
    }

    # Use template variables in node configs
    for node in planned_nodes:
        node_config = {
            "id": node.id,
            "type": node.type,
            "params": {}
        }

        # Replace literal values with template variables
        for param, value in node.params.items():
            if param in parameters:
                node_config["params"][param] = f"${param}"
            else:
                node_config["params"][param] = value

        workflow["nodes"].append(node_config)

    return workflow
```

## Resolution Process

1. **Collection Phase**: Gather all available variables
   - CLI arguments
   - Natural language extraction
   - Environment variables
   - Defaults

2. **Validation Phase**: Check required variables are present
   - Identify missing required parameters
   - Prompt for missing values if interactive
   - Fail fast if non-interactive

3. **Resolution Phase**: Replace all template variables
   - Process each node's parameters
   - Process shared store defaults
   - Handle string interpolation

4. **Execution Phase**: Run with resolved values

## Best Practices

1. **Meaningful Names**: Use descriptive variable names
   - Good: `$customer_segment`, `$analysis_period`
   - Bad: `$var1`, `$param`

2. **Document Parameters**: Include in workflow metadata
   ```json
   {
     "parameters": {
       "customer_segment": {
         "description": "Customer segment to analyze",
         "type": "string",
         "examples": ["enterprise", "smb", "startup"]
       }
     }
   }
   ```

3. **Validate Early**: Check all variables before execution
4. **Provide Defaults**: Where sensible (but don't hide requirements)
5. **Keep It Simple**: This is not a full templating language

## Anti-Patterns to Avoid

1. **Complex Logic**: No conditionals or loops in templates
2. **Nested Variables**: No `${$var}` or computed names
3. **Side Effects**: Templates are pure string substitution
4. **Type Coercion**: Keep types simple (strings/numbers)

## Testing Templates

```python
def test_template_resolution():
    template = "Analyze issue ${issue_number} in ${repo}"
    vars = {"issue_number": 123, "repo": "myrepo"}

    result = resolve_template(template, vars)
    assert result == "Analyze issue 123 in myrepo"

def test_missing_variable():
    template = "Analyze ${missing}"
    vars = {}

    with pytest.raises(ValueError, match="missing"):
        resolve_template(template, vars)
```

## Future Enhancements

1. **Type Validation**: Ensure variables match expected types
2. **Computed Variables**: `${issue_number + 1}`
3. **Conditionals**: `${debug ? '--verbose' : ''}`
4. **Lists/Arrays**: `${files[*]}`

But for MVP: Keep it simple! Just string substitution.
