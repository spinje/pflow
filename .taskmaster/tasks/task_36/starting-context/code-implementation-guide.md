# Task 36: Code Implementation Guide

## Overview

This guide provides the exact code changes needed to update the context builder for clarity with automatic namespacing.

## File: `src/pflow/planning/context_builder.py`

### Change 1: Update `_format_node_section()`

**Current Function (lines ~723-780):**
```python
def _format_node_section_enhanced(node_type: str, node_data: dict) -> str:
    """Format a node with enhanced structure display (JSON + paths)."""
    lines = [f"### {node_type}"]

    # Add description
    description = node_data.get("description", "").strip()
    if not description:
        description = "No description available"
    lines.append(description)
    lines.append("")

    # Format inputs
    inputs = node_data["inputs"]
    if inputs:
        lines.append("**Inputs**:")
        for inp in inputs:
            _format_interface_item(inp, "input", lines)
    else:
        lines.append("**Inputs**: none")
    lines.append("")

    # Format outputs
    outputs = node_data["outputs"]
    if outputs:
        lines.append("**Outputs**:")
        for out in outputs:
            _format_interface_item(out, "output", lines)
    else:
        lines.append("**Outputs**: none")

    # Format parameters (exclusive params only)
    _format_exclusive_parameters(node_data, inputs, lines)

    return "\n".join(lines)
```

**New Function:**
```python
def _format_node_section_enhanced(node_type: str, node_data: dict) -> str:
    """Format a node with clear parameter and output information."""
    lines = [f"### {node_type}"]

    # Add description
    description = node_data.get("description", "").strip()
    if not description:
        description = "No description available"
    lines.append(description)
    lines.append("")

    # Format ALL parameters (not just exclusive)
    _format_all_parameters(node_data, lines)
    lines.append("")

    # Format outputs with access pattern
    _format_outputs_with_access(node_data, lines)
    lines.append("")

    # Always add usage example
    _format_usage_example(node_type, node_data, lines)

    return "\n".join(lines)
```

### Change 2: Replace `_format_exclusive_parameters()` with `_format_all_parameters()`

**Current Function (lines ~673-696):**
```python
def _format_exclusive_parameters(node_data: dict, inputs: list, lines: list[str]) -> None:
    """Format parameters that are not in inputs (exclusive params)."""
    params = node_data["params"]
    input_keys = _extract_input_keys(inputs)

    exclusive_params = []
    for param in params:
        formatted_line = _format_param_line(param, input_keys)
        if formatted_line:
            exclusive_params.append(formatted_line)

    if exclusive_params:
        lines.append("**Parameters**:")
        lines.extend(exclusive_params)
    else:
        # Show template variable usage instead of misleading "none"
        _format_template_variables(inputs, lines)
```

**New Function:**
```python
def _format_all_parameters(node_data: dict, lines: list[str]) -> None:
    """Format ALL parameters for the node."""
    inputs = node_data.get("inputs", [])
    params = node_data.get("params", [])

    lines.append("**Parameters** (all go in params field):")

    # First, add all inputs as parameters
    for inp in inputs:
        if isinstance(inp, dict):
            key = inp["key"]
            type_str = inp.get("type", "any")
            desc = inp.get("description", "")
            default = inp.get("default")

            line = f"- `{key}: {type_str}` - {desc}"
            if default is not None:
                line += f" (default: {default})"
            lines.append(line)

            # Add structure display for complex types
            if type_str in ("dict", "list", "list[dict]") and "structure" in inp:
                _add_enhanced_structure_display(lines, key, inp["structure"])

    # Then add any exclusive params not in inputs
    input_keys = {inp["key"] if isinstance(inp, dict) else inp for inp in inputs}
    for param in params:
        if param not in input_keys:
            # This is an exclusive param (config parameter)
            lines.append(f"- `{param}: any` - Configuration parameter")
```

### Change 3: Add `_format_outputs_with_access()`

**New Function to Add:**
```python
def _format_outputs_with_access(node_data: dict, lines: list[str]) -> None:
    """Format outputs with clear access pattern for namespacing."""
    outputs = node_data.get("outputs", [])

    if outputs:
        lines.append("**Outputs** (access as ${node_id.output_key}):")
        for out in outputs:
            if isinstance(out, dict):
                key = out["key"]
                type_str = out.get("type", "any")
                desc = out.get("description", "")

                line = f"- `{key}: {type_str}` - {desc}"
                lines.append(line)

                # Add structure display for complex types
                if type_str in ("dict", "list", "list[dict]") and "structure" in out:
                    _add_enhanced_structure_display(lines, key, out["structure"])
            else:
                lines.append(f"- `{out}`")
    else:
        lines.append("**Outputs**: none")
```

### Change 4: Add `_format_usage_example()`

**New Function to Add:**
```python
def _format_usage_example(node_type: str, node_data: dict, lines: list[str]) -> None:
    """Generate a concrete usage example for the node."""
    import json

    lines.append("**Example usage**:")
    lines.append("```json")

    # Build example structure
    example = {
        "id": node_type.replace("-", "_"),
        "type": node_type,
        "params": {}
    }

    # Add example values for inputs
    inputs = node_data.get("inputs", [])
    for inp in inputs:
        if isinstance(inp, dict):
            key = inp["key"]
            # Generate contextual example values
            if "file" in key.lower() or "path" in key.lower():
                example["params"][key] = "${input_file}" if "input" in key else "${output_file}"
            elif "content" in key.lower() or "data" in key.lower():
                example["params"][key] = "${previous_node.content}"
            elif "prompt" in key.lower():
                example["params"][key] = "Process this: ${input_data}"
            elif "url" in key.lower():
                example["params"][key] = "${api_endpoint}"
            else:
                example["params"][key] = f"${{{key}}}"

    # Add example exclusive params
    params = node_data.get("params", [])
    input_keys = {inp["key"] if isinstance(inp, dict) else inp for inp in inputs}

    for param in params:
        if param not in input_keys:
            # Add config params with typical values
            if "model" in param.lower():
                example["params"][param] = "gpt-4o-mini"
            elif "temperature" in param.lower():
                example["params"][param] = 0.7
            elif "append" in param.lower():
                example["params"][param] = False
            # Don't add other config params to keep example clean

    lines.append(json.dumps(example, indent=2))
    lines.append("```")
```

### Change 5: Update the main formatting dispatcher

**Current Code (in build_planning_context, ~590-620):**
```python
# Format nodes
for node_type in sorted(selected_nodes.keys()):
    node_data = selected_nodes[node_type]

    # Use enhanced format for complex structures
    if _has_complex_structure(node_data):
        sections.append(_format_node_section_enhanced(node_type, node_data))
    else:
        sections.append(_format_node_section(node_type, node_data))
```

**Update to:**
```python
# Format nodes - always use enhanced format for consistency
for node_type in sorted(selected_nodes.keys()):
    node_data = selected_nodes[node_type]
    sections.append(_format_node_section_enhanced(node_type, node_data))
```

## File: `tests/test_planning/test_context_builder_phases.py`

### Update Test Expectations

**Find tests that check for "Parameters: none" and update:**

```python
# Old assertion
assert "**Parameters**: none" in context

# New assertion
assert "**Parameters** (all go in params field):" in context
```

**Find tests that check for "Inputs" and update:**

```python
# Old assertion
assert "**Inputs**:" in context

# New assertion - Inputs section no longer exists
assert "**Parameters** (all go in params field):" in context
```

**Add new test for example section:**

```python
def test_usage_example_always_present():
    """Test that usage examples are shown for all nodes."""
    context = build_planning_context(
        selected_node_ids=["read-file"],
        selected_workflow_names=[],
        registry_metadata=test_registry
    )

    assert "**Example usage**:" in context
    assert '{"id": "read_file"' in context
    assert '"type": "read-file"' in context
    assert '"params": {' in context
```

## Helper Functions (No Changes Needed)

These functions can remain unchanged:
- `_extract_input_keys()`
- `_add_enhanced_structure_display()`
- `_format_interface_item()`
- `_has_complex_structure()`

## Validation Script

Create this script to validate the changes:

```python
#!/usr/bin/env python3
"""Validate context builder output after changes."""

from pflow.planning.context_builder import build_planning_context
from pflow.registry import Registry

def validate_format():
    registry = Registry()
    metadata = registry.load()

    # Test with various node types
    test_nodes = ["read-file", "write-file", "llm", "github-get-issue"]

    context = build_planning_context(
        selected_node_ids=test_nodes,
        selected_workflow_names=[],
        registry_metadata={k: metadata[k] for k in test_nodes if k in metadata}
    )

    # Check for new format markers
    assert "**Parameters** (all go in params field):" in context
    assert "**Outputs** (access as ${node_id.output_key}):" in context
    assert "**Example usage**:" in context

    # Check that old format is gone
    assert "**Inputs**:" not in context
    assert "**Parameters**: none" not in context
    assert "**Template Variables**:" not in context

    print("✅ Format validation passed!")
    print("\nSample output:")
    print("=" * 80)
    # Show first node as example
    lines = context.split("\n")
    node_end = lines.index("", 10) if "" in lines[10:] else 50
    print("\n".join(lines[:node_end]))
    print("=" * 80)

if __name__ == "__main__":
    validate_format()
```

## Implementation Order

1. **Add new functions first:**
   - `_format_all_parameters()`
   - `_format_outputs_with_access()`
   - `_format_usage_example()`

2. **Update existing function:**
   - Modify `_format_node_section_enhanced()`

3. **Remove/deprecate:**
   - Comment out `_format_exclusive_parameters()`
   - Comment out `_format_template_variables()`

4. **Test incrementally:**
   - Run validation script after each change
   - Update tests as needed

## Edge Cases to Handle

### 1. Nodes with no inputs
```python
if not inputs:
    lines.append("**Parameters**: none")
    return
```

### 2. Complex nested structures
Ensure `_add_enhanced_structure_display()` still works:
```python
if type_str in ("dict", "list", "list[dict]") and "structure" in inp:
    _add_enhanced_structure_display(lines, key, inp["structure"])
```

### 3. Optional parameters
Mark them clearly:
```python
if not inp.get("required", True):
    line += " (optional)"
```

## Success Validation

After implementation, the output should look like:

```markdown
### read-file
Read content from a file and add line numbers for display.

**Parameters** (all go in params field):
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (optional, default: utf-8)

**Outputs** (access as ${node_id.output_key}):
- `content: str` - File contents with line numbers
- `error: str` - Error message if operation failed

**Example usage**:
```json
{
  "id": "read_file",
  "type": "read-file",
  "params": {
    "file_path": "${input_file}",
    "encoding": "utf-8"
  }
}
```
```

Compare this to the current confusing format to verify improvement!