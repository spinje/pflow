# Template Variables with Path Support: MVP Implementation Guide

## Executive Summary

This document provides the implementation guide for template variable support in pflow's MVP. Template variables enable the "Plan Once, Run Forever" philosophy by allowing workflows to be parameterized and reused with different values.

**Key MVP Feature**: Template variables support path-based access (e.g., `$issue_data.user.login`), eliminating the need for complex data mappings in most workflows.

## What You're Building

A template variable resolution system that:
1. Detects template variables in node parameters: `$variable` or `${variable}`
2. Supports path-based access to nested data: `$issue_data.user.login`
3. Resolves variables at runtime from two sources:
   - CLI parameters (higher priority)
   - Shared store values (lower priority)
4. Converts all values to strings
5. Works transparently without modifying existing nodes

**Example**:
```json
// Workflow definition:
{"params": {"prompt": "Fix issue #$issue_data.number by $issue_data.user.login"}}

// Runtime resolution:
// shared["issue_data"] = {"number": 1234, "user": {"login": "john"}}
// Node sees: {"prompt": "Fix issue #1234 by john"}
```

## Critical PocketFlow Constraints

Understanding these constraints is essential for implementation:

### 1. Parameters Are Immutable During Execution
```python
# Once set_params() is called:
node.set_params({"file": "data.txt"})
# Node accesses params directly - we CANNOT intercept:
file_path = self.params["file"]  # No proxy possible here!
```

### 2. The Only Interception Point
```python
def _run(self, shared):  # <-- We can only intercept here
    # This is where we can modify node.params before execution
```

### 3. Nodes Are Copied Before Execution
```python
# PocketFlow does this internally:
curr = copy.copy(node)  # Fresh copy for each execution
curr.set_params(params)
curr._run(shared)       # Our interception point
```

## The Fallback Pattern Foundation

Every pflow node implements this pattern:
```python
# In EVERY node's prep() method:
value = shared.get("key") or self.params.get("key")
```

This enables template variables in params to work as dynamic values.

## Implementation Design

### Core Components

1. **TemplateResolver**: Detects and resolves template variables with path support
2. **TemplateAwareNodeWrapper**: Wraps nodes to provide transparent resolution
3. **Compiler Integration**: Wraps nodes that have template parameters

### Resolution Process

1. Detect template variables in parameters
2. At runtime, build context from shared store + CLI params
3. Resolve paths by traversing nested objects
4. Replace templates with string values
5. Update node params before execution

## Code Implementation

### Phase 1: Template Resolver

```python
# src/pflow/runtime/template_resolver.py

import re
from typing import Dict, Set, Any, Optional

class TemplateResolver:
    """Handles template variable detection and resolution with path support."""

    # Updated pattern to support paths like $var.field.subfield
    TEMPLATE_PATTERN = re.compile(r'\$\{?(\w+(?:\.\w+)*)\}?')

    @staticmethod
    def has_templates(value: Any) -> bool:
        """Check if value contains template variables."""
        return isinstance(value, str) and '$' in value

    @staticmethod
    def extract_variables(value: str) -> Set[str]:
        """Extract all template variable names (including paths)."""
        return set(TemplateResolver.TEMPLATE_PATTERN.findall(value))

    @staticmethod
    def resolve_value(var_name: str, context: Dict[str, Any]) -> Optional[Any]:
        """Resolve a variable name (possibly with path) from context."""
        if '.' in var_name:
            # Handle path traversal
            parts = var_name.split('.')
            value = context
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return None
            return value
        else:
            # Simple variable
            return context.get(var_name)

    @staticmethod
    def resolve_string(template: str, context: Dict[str, Any]) -> str:
        """Resolve all template variables in a string."""
        result = template

        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
            var_name = match.group(1)
            value = TemplateResolver.resolve_value(var_name, context)

            if value is not None:
                # Convert to string and replace both $var and ${var} formats
                value_str = str(value)
                result = result.replace(f'${{{var_name}}}', value_str)
                result = result.replace(f'${var_name}', value_str)

        return result
```

### Phase 2: Node Wrapper

```python
# src/pflow/runtime/node_wrapper.py

from typing import Dict, Any, Optional
from .template_resolver import TemplateResolver

class TemplateAwareNodeWrapper:
    """Wraps nodes to provide transparent template resolution."""

    def __init__(self, inner_node, node_id: str, initial_params: Optional[Dict[str, Any]] = None):
        self.inner_node = inner_node
        self.node_id = node_id
        self.initial_params = initial_params or {}  # CLI parameters
        self.template_params = {}
        self.static_params = {}

    def set_params(self, params: Dict[str, Any]):
        """Separate template params from static params."""
        self.template_params.clear()
        self.static_params.clear()

        for key, value in params.items():
            if TemplateResolver.has_templates(value):
                self.template_params[key] = value
            else:
                self.static_params[key] = value

        # Set only static params on inner node
        self.inner_node.set_params(self.static_params)

    def _run(self, shared: Dict[str, Any]) -> Any:
        """Execute with template resolution."""
        # Skip if no templates
        if not self.template_params:
            return self.inner_node._run(shared)

        # Build resolution context: shared store + CLI params
        # CLI params have higher priority (come second in update)
        context = dict(shared)  # Start with shared store values
        context.update(self.initial_params)  # CLI params override

        # Resolve all template parameters
        resolved_params = {}
        for key, template in self.template_params.items():
            resolved_params[key] = TemplateResolver.resolve_string(template, context)

        # Temporarily update inner node params
        original_params = self.inner_node.params
        merged_params = {**self.static_params, **resolved_params}
        self.inner_node.params = merged_params

        try:
            # Execute with resolved params
            return self.inner_node._run(shared)
        finally:
            # Restore original (though node copy will be discarded)
            self.inner_node.params = original_params

    def __getattr__(self, name):
        """Delegate all other attributes to inner node."""
        return getattr(self.inner_node, name)
```

### Phase 3: Compiler Integration

```python
# Modifications to src/pflow/runtime/compiler.py

def compile_ir_to_flow(
    ir_dict: Dict[str, Any],
    registry: Registry,
    initial_params: Optional[Dict[str, Any]] = None
) -> Flow:
    """Compile IR with template variable support.

    Args:
        ir_dict: The workflow IR
        registry: Node registry
        initial_params: CLI parameters for template resolution
    """
    flow = Flow()
    nodes = {}
    initial_params = initial_params or {}

    # Create nodes
    for node_spec in ir_dict['nodes']:
        node_id = node_spec['id']
        node_type = node_spec['type']
        params = node_spec.get('params', {})

        # Get node class and instantiate
        node_class = registry.get(node_type)
        node = node_class()

        # Check if any parameters contain templates
        has_templates = any(TemplateResolver.has_templates(v) for v in params.values())

        if has_templates:
            # Wrap node for template support
            node = TemplateAwareNodeWrapper(node, node_id, initial_params)

        # Set parameters (wrapper will separate template vs static)
        node.set_params(params)
        nodes[node_id] = node
        flow.add_node(node_id, node)

    # Add edges
    for edge in ir_dict.get('edges', []):
        flow.add_edge(edge['from'], edge.get('action', 'default'), edge['to'])

    # Set start node
    if 'start_node' in ir_dict:
        flow.set_start(ir_dict['start_node'])

    return flow
```

## Testing Strategy

### Core Tests

```python
# tests/test_runtime/test_template_resolver.py

def test_path_based_template_resolution():
    """Test template resolution with nested paths."""
    context = {
        "issue_data": {
            "number": 1234,
            "user": {
                "login": "john",
                "email": "john@example.com"
            },
            "labels": ["bug", "urgent"]
        }
    }

    assert TemplateResolver.resolve_string(
        "Issue #$issue_data.number by $issue_data.user.login",
        context
    ) == "Issue #1234 by john"

def test_mixed_paths_and_simple_vars():
    """Test mixing path-based and simple variables."""
    context = {
        "project": "pflow",
        "issue": {
            "id": 42,
            "status": "open"
        }
    }

    assert TemplateResolver.resolve_string(
        "$project issue #$issue.id is $issue.status",
        context
    ) == "pflow issue #42 is open"

def test_missing_path_components():
    """Test behavior with non-existent paths."""
    context = {"data": {"exists": "yes"}}

    # Non-existent path should leave template unchanged
    result = TemplateResolver.resolve_string(
        "Value: $data.does.not.exist",
        context
    )
    assert result == "Value: $data.does.not.exist"

def test_cli_param_priority():
    """Test that CLI params override shared store values."""
    wrapper = TemplateAwareNodeWrapper(
        TestNode(),
        "test",
        initial_params={"version": "2.0"}  # CLI param
    )
    wrapper.set_params({"message": "Version $version"})

    shared = {"version": "1.0"}  # Shared store value
    result = wrapper._run(shared)
    assert "Version 2.0" in result  # CLI param wins
```

### Integration Tests

```python
def test_complete_workflow_with_paths():
    """Test full workflow execution with path-based templates."""
    ir = {
        "nodes": [
            {
                "id": "display",
                "type": "echo",
                "params": {
                    "message": "User $user.name (ID: $user.id) from $user.address.city"
                }
            }
        ]
    }

    initial_params = {
        "user": {
            "name": "Alice",
            "id": 12345,
            "address": {
                "city": "New York",
                "country": "USA"
            }
        }
    }

    flow = compile_ir_to_flow(ir, registry, initial_params)
    shared = {}
    flow.run(shared)
    # Verify the echo node received the resolved message
```

## Common Pitfalls and Solutions

### 1. Type Loss Through String Conversion
**Problem**: `$count` with value 3 becomes "3" (string)
**Solution**: Document this MVP limitation. All template values become strings.

### 2. Non-existent Paths
**Problem**: `$data.field.missing` when path doesn't exist
**Solution**: Leave template unchanged, optionally log warning

### 3. Array Access
**Problem**: User wants `$items.0.name` for array access
**Solution**: Not supported in MVP. Document as future enhancement.

### 4. Missing Variables
**Problem**: Template references variable not in CLI params or shared store
**Solution**: Leave template unchanged rather than failing

### 5. Complex Objects
**Problem**: `$user` where user is a complex object
**Solution**: Converts to string representation (e.g., "[object Object]")

## Success Criteria

The implementation is complete when:

1. **Path-based access works**:
   ```json
   {"prompt": "Fix $issue.title by $issue.user.login"}
   ```

2. **CLI parameters work**:
   ```bash
   pflow my-workflow --api_key=secret --model=gpt-4
   # Templates $api_key and $model resolve correctly
   ```

3. **Dynamic values work**:
   - Templates can reference shared store values from previous nodes
   - Nested paths traverse objects correctly

4. **Nodes remain unmodified**:
   - Existing nodes work without changes
   - Template resolution is transparent

## MVP Limitations

Document these clearly for users:
1. All values convert to strings
2. No array indexing (`$items.0`)
3. No complex expressions or transformations
4. No fallback values or defaults
5. Missing paths leave template unchanged

## Implementation Checklist

- [ ] Implement TemplateResolver with path support
- [ ] Create comprehensive test suite for path traversal
- [ ] Implement TemplateAwareNodeWrapper
- [ ] Integrate with compiler
- [ ] Test with real pflow nodes
- [ ] Document template syntax for users
- [ ] Add examples with nested paths
- [ ] Test edge cases (missing paths, null values)

This implementation provides powerful template variable support with path traversal, enabling most workflow parameterization needs without the complexity of proxy mappings.
