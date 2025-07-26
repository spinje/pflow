# New Patterns Discovered - Task 18 Implementation

## 1. Transparent Node Wrapper Pattern

### Problem
Need to modify node behavior (add template resolution) without changing existing node implementations.

### Solution
```python
class NodeWrapper:
    def __init__(self, inner_node):
        self.inner_node = inner_node

    def _run(self, shared):
        # Intercept and modify behavior
        modified_state = self.prepare_state()
        try:
            result = self.inner_node._run(shared)
            return self.process_result(result)
        finally:
            self.cleanup_state()

    def __getattr__(self, name):
        # Delegate everything else transparently
        return getattr(self.inner_node, name)
```

### Key Insights
- Only wrap `_run()` - it's the single execution path
- Use `__getattr__` for transparent delegation
- Always cleanup in finally block
- PocketFlow's node copying makes this safe

### When to Use
- Adding logging/debugging to nodes
- Implementing cross-cutting concerns
- Runtime behavior modification
- Feature flags or A/B testing

## 2. Just-In-Time Resolution Pattern

### Problem
Need to resolve values that depend on runtime state, not compile-time knowledge.

### Solution
```python
class JITResolver:
    def __init__(self, templates, static_context):
        self.templates = templates  # Store for later
        self.static_context = static_context

    def resolve(self, runtime_context):
        # Merge contexts with priority
        context = dict(runtime_context)
        context.update(self.static_context)  # Higher priority

        # Resolve only when needed
        resolved = {}
        for key, template in self.templates.items():
            resolved[key] = self.resolve_template(template, context)
        return resolved
```

### Key Insights
- Separate detection from resolution
- Store templates until execution time
- Merge multiple contexts with clear priority
- Resolution happens at the last possible moment

### When to Use
- Dynamic configuration systems
- Runtime parameter binding
- Environment-specific values
- User-provided runtime values

## 3. Type-Safe Wrapper Pattern

### Problem
Mypy can't infer that wrapped nodes are valid where BaseNode is expected.

### Solution
```python
from typing import Union

# Update all type signatures
NodeType = Union[BaseNode, NodeWrapper]

def process_nodes(nodes: dict[str, NodeType]) -> None:
    # Explicitly handle both types
    pass

# In wrapper, ensure protocol compatibility
class NodeWrapper:
    def __init__(self, inner: BaseNode):
        # Copy interface attributes
        self.params = inner.params
        self.successors = inner.successors
```

### When to Use
- Any dynamic wrapper/proxy implementation
- Protocol-based type checking
- Runtime type modifications

## 4. Validation Heuristic Pattern

### Problem
Need to categorize parameters without perfect information.

### Solution
```python
class HeuristicValidator:
    # Common patterns that indicate type
    SHARED_STORE_NAMES = {"content", "result", "output", "data"}

    def categorize(self, param_name: str) -> str:
        # Apply heuristics in priority order
        if "." in param_name:
            return "shared_store"  # Path traversal
        if param_name in self.SHARED_STORE_NAMES:
            return "shared_store"  # Common outputs
        return "cli_param"  # Default assumption
```

### Key Insights
- Perfect classification isn't always possible
- Use domain knowledge to build heuristics
- Provide clear documentation of assumptions
- Allow override mechanisms

### When to Use
- Parameter classification
- Type inference
- Intent detection
- Default behavior selection

## 5. Defensive State Restoration Pattern

### Problem
Need to modify object state temporarily without side effects.

### Solution
```python
def with_temporary_state(obj, temp_state):
    original = obj.state
    obj.state = temp_state
    try:
        yield obj
    finally:
        obj.state = original  # Always restore

# Usage
with with_temporary_state(node, new_params):
    result = node.execute()
```

### Key Insights
- Always capture original state
- Use try/finally for guaranteed cleanup
- Consider context managers for clarity
- Document why restoration is needed

### When to Use
- Temporary configuration changes
- Testing with modified state
- Safe execution contexts
- Isolation of side effects

## 6. Fallback Chain Pattern

### Problem
Multiple sources of configuration with clear precedence.

### Solution
```python
def get_value(key, *sources):
    """Get value from first source that has it."""
    for source in sources:
        if key in source:
            return source[key]
    return None

# Usage with priority
value = get_value("config",
    runtime_overrides,   # Highest priority
    initial_params,      # Medium priority
    defaults            # Lowest priority
)
```

### Key Insights
- Order determines priority
- First non-None wins
- Document precedence clearly
- Consider None vs missing keys

### When to Use
- Configuration management
- Default value chains
- Override mechanisms
- Multi-source resolution

## Pattern Combinations

These patterns work well together:

1. **Wrapper + JIT Resolution**: Wrap nodes to add runtime resolution
2. **Validation + Fallback**: Validate available params, fallback for missing
3. **Type-Safe Wrapper + State Restoration**: Maintain type safety while modifying state

## Anti-Patterns to Avoid

1. **Deep Wrapping**: Don't wrap wrappers - compose behavior instead
2. **State Leakage**: Always restore original state
3. **Silent Failures**: Log when resolution fails
4. **Over-Engineering**: Start simple, add complexity only when needed

These patterns are reusable across many tasks and provide a foundation for extending pflow's capabilities without modifying core code.
