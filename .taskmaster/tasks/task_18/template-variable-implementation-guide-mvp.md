# Template Variables and Proxy Mappings: MVP Implementation Guide

## Executive Summary

This document provides the definitive implementation guide for template variable support in pflow's MVP. Template variables enable the "Plan Once, Run Forever" philosophy by allowing workflows to be parameterized and reused.

The implementation must handle two orthogonal but complementary features:
1. **Template Variables**: Dynamic parameter substitution from shared store and CLI
2. **Proxy Mappings**: Key redirection to avoid shared store collisions

## Critical Context: PocketFlow Constraints

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
    # This is where we can provide a proxy shared store
    # And temporarily modify node.params
```

### 3. Nodes Are Copied Before Execution
```python
# PocketFlow does this internally:
curr = copy.copy(node)  # Fresh copy for each execution
curr.set_params(params)
curr._run(shared)       # Our interception point
```

## The Fallback Pattern Foundation

Every pflow node implements this universal pattern:
```python
# In EVERY node's prep() method:
value = shared.get("key") or self.params.get("key")
```

This enables powerful flexibility:
- Any input can come from shared store (dynamic)
- Any input can come from params (static or template)
- Dramatically reduces need for proxy mappings

## Why Dynamic Resolution is Critical

Template variables MUST be resolved at execution time, not compile time:

```python
# Example workflow execution:
Node1 executes:
  - Writes shared["issue_data"] = "Bug in login"

Node2 executes:
  - Has param: {"prompt": "Fix: $issue_data"}
  - Must see: "Fix: Bug in login"

Node3 executes:
  - Updates shared["issue_data"] = "Critical: Bug in login"

Node4 executes:
  - Has param: {"report": "Status: $issue_data"}
  - Must see: "Status: Critical: Bug in login"  # NOT the old value!
```

## Two Orthogonal Features

### 1. Template Variables (Primary Focus)
Enable dynamic parameter values through `$variable` substitution:

```json
// Definition:
{"params": {"prompt": "Analyze $content from $source"}}

// Runtime resolution from BOTH sources:
// CLI params: {"source": "youtube"}
// shared["content"] = "transcript text"
// Node sees: {"prompt": "Analyze transcript text from youtube"}
```

**Resolution Sources** (in priority order):
1. **CLI parameters**: `--issue_number=123` → `$issue_number`
2. **Shared store**: Previous node writes → `$issue_data`

**MVP Limitations**:
- String conversion only (integers become "3", booleans become "true")
- Simple variable names only (`$var` or `${var}`)
- No path-based access (`$data.user.name` not supported)

### 2. Proxy Mappings (Existing Feature)
Redirect shared store keys to avoid collisions:

```json
{
  "mappings": {
    "api1": {"output_mappings": {"response": "api1_response"}},
    "api2": {"output_mappings": {"response": "api2_response"}}
  }
}
```

**Primary Use Case**: Output collision avoidance
**Secondary Use Cases**: Type preservation, complex transformations

## Implementation Architecture

### Single-Phase Runtime Resolution

**Key Design Decision**: ALL template resolution happens at runtime. There is no compile-time substitution. This ensures consistent behavior whether a template variable appears as a complete value or embedded in a string.

**Why Single-Phase?** A two-phase approach (some substitution at compile time, some at runtime) would create inconsistent behavior:
- `"$issue"` → Would be replaced at compile time
- `"Fix issue $issue"` → Would fail at runtime (no access to CLI params)

With single-phase resolution, both work identically because all templates are resolved with the complete context (shared store + CLI params) available.

```json
// Both of these work identically:
{"issue": "$issue_number"}              // Complete value
{"prompt": "Fix issue $issue_number"}   // Embedded in string
```

### Order of Operations (Critical!)

1. **Proxy mappings applied FIRST** (renames keys in shared store)
2. **Template resolution applied SECOND** (uses renamed keys with full context)

```
api1 writes to shared["response"]
  ↓ (proxy mapping)
Becomes shared["api1_response"]
  ↓ (template resolution with CLI params + shared store)
$api1_response resolves to actual value
```

### Implementation Choice: Unified vs Separated

Both approaches are technically valid:

#### Option A: Separated Components
```
NodeAwareSharedStore (handles mappings only)
  +
TemplateResolver (handles templates only)
  +
NodeWrapper (coordinates both)
```

**Pros**: Clear separation of concerns, easier testing
**Cons**: More coordination code

#### Option B: Unified Implementation
```
EnhancedNodeAwareSharedStore (handles both)
  +
Simple NodeWrapper (updates params)
```

**Pros**: Single source of truth, simpler coordination
**Cons**: Larger single component

**Recommendation**: Start with separated components for clarity, refactor to unified if complexity grows.

## Practical Implementation

### Phase 1: Template Detection and Resolution

```python
# src/pflow/runtime/template_resolver.py

import re
from typing import Dict, Set, Any

class TemplateResolver:
    """Handles template variable detection and resolution."""

    TEMPLATE_PATTERN = re.compile(r'\$\{?(\w+)\}?')

    @staticmethod
    def has_templates(value: Any) -> bool:
        """Check if value contains template variables."""
        return isinstance(value, str) and '$' in value

    @staticmethod
    def extract_variables(value: str) -> Set[str]:
        """Extract all template variable names."""
        return set(TemplateResolver.TEMPLATE_PATTERN.findall(value))

    @staticmethod
    def resolve_string(template: str, context: Dict[str, Any]) -> str:
        """Resolve template variables in a string."""
        result = template

        for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
            var_name = match.group(1)
            if var_name in context:
                # Replace both $var and ${var} formats
                value_str = str(context[var_name])  # Always convert to string
                result = result.replace(f'${{{var_name}}}', value_str)
                result = result.replace(f'${var_name}', value_str)

        return result
```

### Phase 2: Node Wrapper Implementation

```python
# src/pflow/runtime/node_wrapper.py

class TemplateAwareNodeWrapper:
    """Wraps nodes to provide transparent template resolution."""

    def __init__(self, inner_node, node_id: str, initial_params: Optional[Dict[str, Any]] = None):
        self.inner_node = inner_node
        self.node_id = node_id
        self.initial_params = initial_params or {}
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
        context = dict(shared)  # Shared store values (lower priority)
        context.update(self.initial_params)  # CLI params override shared store

        # Resolve templates
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
        """Delegate all other attributes."""
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
    """Compile IR with template and proxy support.

    Note: ALL template resolution happens at runtime. We don't modify
    the IR at compile time - instead we pass initial_params to the
    node wrappers for runtime resolution.
    """
    flow = Flow()
    nodes = {}
    mappings = ir_dict.get('mappings', {})
    initial_params = initial_params or {}

    # Create nodes
    for node_spec in ir_dict['nodes']:
        node_id = node_spec['id']
        node_type = node_spec['type']
        params = node_spec.get('params', {})

        # Get node class
        node_class = registry.get(node_type)
        node = node_class()

        # Check if wrapping needed
        has_templates = any(TemplateResolver.has_templates(v) for v in params.values())
        has_mappings = node_id in mappings

        if has_templates:
            # Wrap for template support, passing initial params
            node = TemplateAwareNodeWrapper(node, node_id, initial_params)

        if has_mappings:
            # Create proxy shared store for this node
            # This is handled during execution, not here
            # Store mapping info for runtime
            pass

        node.set_params(params)
        nodes[node_id] = node

    # Build flow structure...
    return flow
```

### Phase 4: Runtime Execution

```python
# Runtime execution that coordinates both features

def execute_with_features(node, shared, node_mappings):
    """Execute node with both proxy mappings and templates."""

    # Layer 1: Apply proxy mappings
    if node_mappings:
        proxy_shared = NodeAwareSharedStore(
            shared,
            input_mappings=node_mappings.get('input_mappings'),
            output_mappings=node_mappings.get('output_mappings')
        )
    else:
        proxy_shared = shared

    # Layer 2: Template resolution happens in wrapper
    # (if node is wrapped)
    return node._run(proxy_shared)
```

## Testing Strategy

### Unit Tests

```python
def test_template_resolution():
    """Test basic template resolution."""
    assert TemplateResolver.resolve_string(
        "Hello $name from $city",
        {"name": "Alice", "city": "NYC"}
    ) == "Hello Alice from NYC"

def test_node_wrapper_templates():
    """Test wrapper resolves templates correctly."""
    class TestNode(Node):
        def exec(self, shared, prep_res):
            return f"Prompt: {self.params['prompt']}"

    node = TestNode()
    initial_params = {"user": "Alice"}
    wrapper = TemplateAwareNodeWrapper(node, "test", initial_params)
    wrapper.set_params({"prompt": "Hello $user, analyze $data"})

    shared = {"data": "important info"}
    result = wrapper._run(shared)
    assert result == "Prompt: Hello Alice, analyze important info"

def test_priority_order():
    """Test CLI params override shared store values."""
    class TestNode(Node):
        def exec(self, shared, prep_res):
            return self.params['value']

    node = TestNode()
    initial_params = {"key": "from_cli"}
    wrapper = TemplateAwareNodeWrapper(node, "test", initial_params)
    wrapper.set_params({"value": "$key"})

    shared = {"key": "from_shared"}
    result = wrapper._run(shared)
    assert result == "from_cli"  # CLI param wins

def test_consistent_resolution():
    """Test that templates work the same in complete values and embedded strings."""
    class TestNode(Node):
        def exec(self, shared, prep_res):
            return (self.params['complete'], self.params['embedded'])

    node = TestNode()
    initial_params = {"issue": "123"}
    wrapper = TemplateAwareNodeWrapper(node, "test", initial_params)
    wrapper.set_params({
        "complete": "$issue",                # Complete value
        "embedded": "Fix issue $issue"       # Embedded in string
    })

    shared = {}
    complete, embedded = wrapper._run(shared)
    assert complete == "123"
    assert embedded == "Fix issue 123"
    # Both forms of $issue work identically!
```

### Integration Tests

```python
def test_complete_workflow():
    """Test workflow with both features."""
    ir = {
        "nodes": [
            {"id": "fetch", "type": "api-call", "params": {"url": "$endpoint"}},
            {"id": "process", "type": "transform", "params": {"format": "$output_format"}}
        ],
        "mappings": {
            "fetch": {"output_mappings": {"response": "api_data"}}
        }
    }

    initial_params = {"endpoint": "https://api.example.com", "output_format": "json"}
    flow = compile_ir_to_flow(ir, registry, initial_params)

    # Verify execution works correctly
    shared = {}
    flow.run(shared)

    # Check results
    assert "api_data" in shared  # Mapped output
    assert "response" not in shared  # Original key not used
```

## Common Pitfalls and Solutions

### 1. Type Loss Through String Conversion
**Problem**: `$retry_count` becomes "3" not 3
**Solution**: For MVP, document this limitation. Post-MVP: detect when entire value is template

### 2. Missing Template Variables
**Problem**: Template references variable not in CLI params or shared store
**Solution**: Document clearly, provide helpful error messages. Consider defaulting to empty string or keeping literal "$var"

### 3. Collision Between Features
**Problem**: Template variable references unmapped key
**Solution**: Apply mappings first, then resolve templates

### 4. Priority Confusion
**Problem**: User expects shared store value but gets CLI param
**Solution**: Document clearly that CLI params override shared store values with same name

## Success Criteria

The implementation succeeds when:

1. **Workflows are reusable**:
   ```bash
   pflow fix-issue --issue_number=123
   pflow fix-issue --issue_number=456  # Same workflow, different params
   ```

2. **Dynamic values work**:
   - Nodes can reference values written by previous nodes
   - Templates see the current state of shared store

3. **Both features compose**:
   - Proxy mappings prevent collisions
   - Templates work with mapped keys

4. **Nodes remain atomic**:
   - No awareness of templates or mappings
   - No modifications to existing nodes

## Next Steps

1. Implement TemplateResolver with comprehensive tests
2. Create TemplateAwareNodeWrapper
3. Integrate with compiler
4. Test with real workflows
5. Document limitations for users
6. Plan post-MVP enhancements

## Conclusion

This implementation provides template variable support while maintaining pflow's architectural principles. By understanding PocketFlow's constraints and leveraging the interception point at _run(), we can add powerful parameterization without compromising node atomicity.

The combination of the fallback pattern, template variables, and proxy mappings creates a flexible system where most workflows need minimal configuration while complex scenarios remain possible.
