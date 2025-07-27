# Node IR Implementation: Critical Information for Planner Development

## Executive Summary

**What Changed**: We implemented "Node IR" (Node Intermediate Representation) - moving interface parsing from runtime to scan-time, storing fully parsed node metadata in the registry.

**Why It Matters to You**: The planner can now generate workflows using ANY variable names that nodes actually write, not just a "magic list" of common names. This eliminates false validation failures that would frustrate users.

## The Problem We Solved

### Before Node IR (The Bug)

The template validator used hardcoded heuristics to guess which variables came from the shared store:

```python
# Old validator's "magic list"
common_outputs = {
    "result", "output", "summary", "content", "response",
    "data", "text", "error", "status", "report", "analysis"
}
```

**Real User Impact**:
1. Planner generates workflow: `api-caller` writes `$api_config` → `processor` reads `$api_config`
2. Validator sees `$api_config` (not in magic list)
3. Validator assumes it's a CLI parameter: "Missing required parameter: --api_config"
4. User frustrated: "But api-caller writes that variable!"

### After Node IR (The Fix)

Validator now checks what nodes ACTUALLY write by looking at their parsed interface data in the registry.

## What This Means for the Planner

### 1. Use Any Variable Name

**Before**: You had to guess which names would pass validation
**Now**: Check the registry to see exactly what each node writes

```python
# You can now safely generate:
- $api_configuration
- $github_webhook_data
- $llm_response_structured
- $my_custom_variable_name
# Any name that appears in a node's outputs will validate correctly
```

### 2. Support Complex Data Paths

Nodes often write structured data. You can now generate paths into that structure:

```python
# If github-get-issue writes:
# outputs: [{"key": "issue_data", "type": "dict", "structure": {...}}]

# You can generate templates like:
- $issue_data.user.login
- $issue_data.labels[0].name
- $issue_data.milestone.title
```

### 3. Better Error Messages

When validation fails, users now see:
- ❌ Old: "Missing required parameter: --api_config"
- ✅ New: "Template variable $api_config has no valid source - either not provided in initial_params or path doesn't exist in node outputs"

## Technical Details: Using the New Registry Data

### Registry Structure

Each node now has an `interface` field with parsed metadata:

```json
{
  "github-get-issue": {
    "module": "pflow.nodes.github.get_issue",
    "class_name": "GitHubGetIssueNode",
    "interface": {
      "description": "Fetch issue details from GitHub",
      "inputs": [
        {"key": "repo", "type": "str", "description": "Repository name"},
        {"key": "issue_number", "type": "int", "description": "Issue number"}
      ],
      "outputs": [
        {
          "key": "issue_data",
          "type": "dict",
          "description": "Complete issue information",
          "structure": {
            "number": {"type": "int", "description": "Issue number"},
            "title": {"type": "str", "description": "Issue title"},
            "user": {
              "type": "dict",
              "description": "Issue author",
              "structure": {
                "login": {"type": "str", "description": "Username"},
                "id": {"type": "int", "description": "User ID"}
              }
            },
            "labels": {
              "type": "list[dict]",
              "description": "Issue labels",
              "structure": {
                "name": {"type": "str", "description": "Label name"},
                "color": {"type": "str", "description": "Label color"}
              }
            }
          }
        }
      ],
      "params": ["token"],
      "actions": ["default", "error"]
    }
  }
}
```

### What the Planner Should Check

1. **Node Outputs**: What variables will be written to shared store
2. **Output Types**: To generate appropriate consumers
3. **Output Structures**: For nested data access
4. **Node Inputs**: What variables the node expects to read

### Validation Rules

The validator checks template variables in this order:
1. **Initial Parameters** (from planner/CLI) - highest priority
2. **Node Outputs** - what nodes write to shared store

For nested paths (`$var.field.subfield`):
- Validates full path exists in structure
- Fails if trying to access fields on primitive types (str, int)
- Handles list access notation (`$items[0].name`)

## Concrete Example: Before vs After

### Scenario: GitHub to Slack Workflow

**Planner generates**:
```json
{
  "nodes": [
    {
      "id": "fetch",
      "type": "github-get-issue",
      "params": {"repo": "owner/repo", "issue_number": 123}
    },
    {
      "id": "notify",
      "type": "slack-send",
      "params": {
        "message": "Issue #$issue_data.number: $issue_data.title by @$issue_data.user.login",
        "channel": "#alerts"
      }
    }
  ]
}
```

**Before Node IR**:
- ❌ Validation fails: "Missing required parameter: --issue_data"
- Planner would need to use `$data` or `$result` (magic names)
- No way to access nested fields safely

**After Node IR**:
- ✅ Validation passes: Validator sees github-get-issue writes `issue_data`
- ✅ Path validation works: `issue_data.user.login` verified against structure
- ✅ Clear errors if wrong: "Template variable $issue_data.wrong.path has no valid source"

## Key Takeaways for Planner Implementation

1. **Read the Registry Interface Data**: Don't guess what nodes write - check their interface
2. **Generate Meaningful Variable Names**: No more forcing everything to be `$result`
3. **Use Structure Information**: Generate paths into complex data confidently
4. **Trust the Validation**: If a node's interface says it writes something, it will validate
5. **Provide Clear Initial Params**: Anything the workflow needs from outside should be in initial_params

## Breaking Changes

- All nodes now MUST have interface field in registry (no fallbacks)
- Old heuristic validation is completely removed
- Template error messages have changed format

## Practical Usage Guide for Planner Implementation

### Step 1: Load and Query the Registry

```python
from pflow.registry import Registry

# Load registry with interface data
registry = Registry()
registry_data = registry.load()

# Get specific node's interface
def get_node_interface(node_type: str) -> dict:
    """Get the interface data for a specific node type."""
    if node_type in registry_data:
        return registry_data[node_type].get("interface", {})
    return None

# Get what a node writes to shared store
def get_node_outputs(node_type: str) -> list[dict]:
    """Get list of outputs a node writes."""
    interface = get_node_interface(node_type)
    return interface.get("outputs", []) if interface else []

# Get what a node reads from shared store
def get_node_inputs(node_type: str) -> list[dict]:
    """Get list of inputs a node reads."""
    interface = get_node_interface(node_type)
    return interface.get("inputs", []) if interface else []
```

### Step 2: Check Node Compatibility

```python
def can_nodes_connect(producer_type: str, consumer_type: str, registry_data: dict) -> dict:
    """Check if producer's outputs can satisfy consumer's inputs.

    Returns:
        Dict with 'compatible' bool and 'connections' list of valid mappings
    """
    producer_outputs = get_node_outputs(producer_type)
    consumer_inputs = get_node_inputs(consumer_type)

    connections = []

    # For each consumer input, check if producer provides it
    for input_spec in consumer_inputs:
        input_key = input_spec["key"]
        input_type = input_spec.get("type", "any")

        # Find matching output from producer
        for output_spec in producer_outputs:
            output_key = output_spec["key"]
            output_type = output_spec.get("type", "any")

            # Check if keys match (or could be mapped)
            if output_key == input_key:
                # Check type compatibility (simplified)
                if output_type == input_type or "any" in [output_type, input_type]:
                    connections.append({
                        "output": output_key,
                        "input": input_key,
                        "type": output_type
                    })
                    break

    return {
        "compatible": len(connections) > 0,
        "connections": connections,
        "missing_inputs": [inp["key"] for inp in consumer_inputs
                          if not any(c["input"] == inp["key"] for c in connections)]
    }
```

### Step 3: Generate Valid Template Strings

```python
def generate_template_reference(variable_name: str, path: list[str] = None) -> str:
    """Generate a template reference like $var or $var.field.subfield.

    Args:
        variable_name: Base variable name (e.g., "api_config")
        path: Optional path components (e.g., ["endpoint", "url"])

    Returns:
        Template string (e.g., "$api_config.endpoint.url")
    """
    if path:
        return f"${variable_name}.{'.'.join(path)}"
    return f"${variable_name}"

def get_available_paths(node_type: str, output_key: str, registry_data: dict) -> list[str]:
    """Get all valid paths for a node's output.

    Returns:
        List of valid template paths (e.g., ["$data", "$data.user", "$data.user.login"])
    """
    outputs = get_node_outputs(node_type)
    paths = []

    for output in outputs:
        if output["key"] == output_key:
            # Add base path
            paths.append(f"${output_key}")

            # Add nested paths if structure exists
            if "structure" in output:
                def traverse_structure(structure: dict, prefix: str):
                    for field, info in structure.items():
                        field_path = f"{prefix}.{field}"
                        paths.append(field_path)

                        # Recurse if nested structure
                        if isinstance(info, dict) and "structure" in info:
                            traverse_structure(info["structure"], field_path)

                traverse_structure(output["structure"], f"${output_key}")
            break

    return paths
```

### Step 4: Validate Template During Planning

```python
def validate_template_usage(template: str, available_outputs: dict, initial_params: list[str]) -> bool:
    """Check if a template will be valid at runtime.

    Args:
        template: Template string without $ prefix (e.g., "api_config.endpoint.url")
        available_outputs: Dict of {variable_name: output_spec} from previous nodes
        initial_params: List of parameter names provided to workflow

    Returns:
        True if template will validate, False otherwise
    """
    parts = template.split(".")
    base_var = parts[0]

    # Check initial params first (higher priority)
    if base_var in initial_params:
        return True  # Initial params are trusted to exist

    # Check node outputs
    if base_var not in available_outputs:
        return False

    # For simple variable reference
    if len(parts) == 1:
        return True

    # For nested path, check structure
    output_spec = available_outputs[base_var]
    current_structure = output_spec.get("structure", {})

    # If no structure info but type is dict/object, optimistically allow
    if not current_structure and output_spec.get("type") in ["dict", "object", "any"]:
        return True

    # Validate each path component exists
    for part in parts[1:]:
        if part not in current_structure:
            return False

        # Move deeper into structure
        if isinstance(current_structure[part], dict):
            current_structure = current_structure[part].get("structure", {})
        else:
            # Reached a leaf, no more traversal possible
            break

    return True
```

### Step 5: Complete Workflow Generation Example

```python
def plan_workflow(task_description: str, registry: Registry) -> dict:
    """Example of planning a workflow using Node IR.

    This is simplified - real planner would use LLM.
    """
    # Example: "Get GitHub issue and send to Slack"

    # 1. Identify needed nodes
    nodes_needed = ["github-get-issue", "slack-send-message"]

    # 2. Check what github-get-issue outputs
    github_outputs = get_node_outputs("github-get-issue")
    # Returns: [{"key": "issue_data", "type": "dict", "structure": {...}}]

    # 3. Check what slack-send-message needs
    slack_inputs = get_node_inputs("slack-send-message")
    # Returns: [{"key": "message", "type": "str"}, {"key": "channel", "type": "str"}]

    # 4. Build available outputs map
    available_outputs = {}
    for output in github_outputs:
        available_outputs[output["key"]] = output

    # 5. Generate workflow with valid templates
    workflow = {
        "nodes": [
            {
                "id": "fetch_issue",
                "type": "github-get-issue",
                "params": {
                    "repo": "$repo",  # From initial_params
                    "issue_number": "$issue_number"  # From initial_params
                }
            },
            {
                "id": "notify",
                "type": "slack-send-message",
                "params": {
                    # Use actual paths from issue_data structure
                    "message": f"Issue #{generate_template_reference('issue_data', ['number'])}: "
                              f"{generate_template_reference('issue_data', ['title'])} "
                              f"by @{generate_template_reference('issue_data', ['user', 'login'])}",
                    "channel": "$slack_channel"  # From initial_params
                }
            }
        ],
        "initial_params": {
            "repo": "owner/repo",
            "issue_number": 123,
            "slack_channel": "#alerts"
        }
    }

    # 6. Verify all templates are valid
    for node in workflow["nodes"]:
        for param_value in node["params"].values():
            if isinstance(param_value, str) and "$" in param_value:
                # Extract and validate each template...
                pass  # Validation logic here

    return workflow
```

### Common Patterns for Planner

#### Pattern 1: Direct Variable Mapping
```python
# Node A writes "result", Node B reads "input"
# Generate: Node B with params: {"input": "$result"}
```

#### Pattern 2: Nested Data Access
```python
# Node writes complex structure
# Access specific fields: "$user_data.profile.email"
```

#### Pattern 3: Multiple Outputs
```python
# Node writes multiple variables
# Can reference any: "$output1", "$output2", "$error"
```

#### Pattern 4: Conditional Paths
```python
# Use node actions to handle different outcomes
# "default" action when success, "error" action when failed
```

### Debugging Template Validation

When validation fails, the error message tells you exactly what's wrong:

```python
# Error: "Template variable $api_config.wrong.field has no valid source"
# This means either:
# 1. No node writes "api_config"
# 2. api_config exists but doesn't have path "wrong.field"

# To debug:
api_outputs = get_available_paths("api-node", "api_config", registry_data)
print(api_outputs)
# Shows: ["$api_config", "$api_config.endpoint", "$api_config.endpoint.url", ...]
```

## Summary

Node IR fixes the fundamental disconnect between what the planner could generate and what the validator would accept. You can now generate workflows that use the actual variable names and structures that nodes provide, making the system more intuitive and less error-prone.

The registry is now your source of truth for what variables and paths are valid in workflows. Use the provided functions to query node interfaces, check compatibility, and generate valid template references.
