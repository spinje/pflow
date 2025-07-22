# Unified Proxy Implementation: NodeAwareSharedStore with Template Resolution

## Executive Summary

This document outlines the implementation of a unified proxy system that solves two critical problems:
1. **Proxy Mappings**: Allowing incompatible nodes to work together by redirecting shared store keys
2. **Template Resolution**: Enabling dynamic parameter values through `$variable` substitution

Both features are implemented through a single, elegant proxy that preserves node atomicity.

## The Two Problems

### Problem 1: Interface Mismatch (Proxy Mappings)
```python
# Node A writes:
shared["transcript"] = "video content"

# Node B expects:
prompt = shared["prompt"]  # Doesn't exist!

# Solution: Proxy mapping
mappings = {"input_mappings": {"prompt": "transcript"}}
```

### Problem 2: Dynamic Parameters (Template Variables)
```python
# Workflow defines:
params = {"prompt": "Summarize: $content"}

# Need to resolve:
$content → shared["content"] at runtime

# But nodes can't access shared in params!
```

## The Unified Solution

Instead of two separate systems, we implement one proxy that handles both concerns:

```python
class NodeAwareSharedStore(dict):
    """A proxy that provides both key mapping and template resolution."""

    def __init__(self, shared_store, node=None, input_mappings=None, output_mappings=None):
        """
        Args:
            shared_store: The actual shared dictionary
            node: The node instance (needed for template resolution)
            input_mappings: Dict mapping node's expected keys to actual keys
            output_mappings: Dict mapping node's output keys to different keys
        """
        self._shared = shared_store
        self._node = node
        self._input_mappings = input_mappings or {}
        self._output_mappings = output_mappings or {}
        self._resolved_params = None

    def _resolve_templates(self, value):
        """Resolve $variables in a string using current shared store state."""
        if not isinstance(value, str) or '$' not in value:
            return value

        resolved = value
        # Find all $variable or ${variable} patterns
        import re
        variables = re.findall(r'\$\{?(\w+)\}?', value)

        for var in variables:
            if var in self._shared:
                # Replace both $var and ${var} formats
                resolved = resolved.replace(f'${var}', str(self._shared[var]))
                resolved = resolved.replace(f'${{{var}}}', str(self._shared[var]))

        return resolved

    @property
    def resolved_params(self):
        """Lazily resolve all template parameters."""
        if self._resolved_params is None and self._node:
            self._resolved_params = {}
            for key, value in self._node.params.items():
                self._resolved_params[key] = self._resolve_templates(value)
        return self._resolved_params

    def __getitem__(self, key):
        """Handle both proxy mapping AND template resolution."""
        # Check if node is accessing its own params via special key
        if key == "__resolved_params__":
            return self.resolved_params

        # Handle input mappings (node reads)
        actual_key = self._input_mappings.get(key, key)
        return self._shared[actual_key]

    def __setitem__(self, key, value):
        """Handle output mappings (node writes)."""
        actual_key = self._output_mappings.get(key, key)
        self._shared[actual_key] = value

    def __contains__(self, key):
        """Check if key exists (considering mappings)."""
        actual_key = self._input_mappings.get(key, key)
        return actual_key in self._shared

    def get(self, key, default=None):
        """Safe get with mapping support."""
        try:
            return self[key]
        except KeyError:
            return default

    # Implement other dict methods as needed
    def keys(self):
        # Return keys as the node expects them
        mapped_keys = set()
        for real_key in self._shared.keys():
            # Reverse map to what node expects
            for expected, actual in self._input_mappings.items():
                if actual == real_key:
                    mapped_keys.add(expected)
                    break
            else:
                mapped_keys.add(real_key)
        return mapped_keys

    def items(self):
        # Return items with mapped keys
        for key in self.keys():
            yield key, self[key]
```

## Runtime Integration

### Enhanced Node Wrapper

To make template resolution transparent, we need a thin wrapper:

```python
class TemplateAwareNodeWrapper:
    """Wrapper that injects resolved params without node awareness."""

    def __init__(self, node):
        self._inner_node = node
        self._original_params = node.params.copy()

    def _run(self, shared):
        # If shared is our proxy, it can resolve templates
        if isinstance(shared, NodeAwareSharedStore):
            # Temporarily replace params with resolved ones
            self._inner_node.params = shared.resolved_params
            try:
                return self._inner_node._run(shared)
            finally:
                # Restore original params
                self._inner_node.params = self._original_params
        else:
            # No proxy, run normally
            return self._inner_node._run(shared)

    def __getattr__(self, name):
        """Delegate all other attributes to inner node."""
        return getattr(self._inner_node, name)
```

### Runtime Executor

The runtime brings it all together:

```python
class PflowRuntime:
    """Runtime that handles both proxy mappings and template resolution."""

    def execute_flow(self, flow, ir_dict, initial_params=None):
        """Execute a flow with full proxy support."""
        # Phase 1: Substitute initial parameters (CLI args)
        if initial_params:
            ir_dict = self._substitute_initial_params(ir_dict, initial_params)

        # Phase 2: Prepare node wrappers and mappings
        node_configs = self._prepare_node_configs(flow, ir_dict)

        # Phase 3: Execute with proxy support
        shared = {}

        # Inject initial params into shared for template resolution
        if initial_params:
            for key, value in initial_params.items():
                shared[f"_param_{key}"] = value

        return self._execute_with_proxies(flow, shared, node_configs)

    def _execute_with_proxies(self, flow, shared, node_configs):
        """Execute flow with proxy mappings and template resolution."""
        # We need to intercept the flow execution
        # This is tricky without modifying PocketFlow...

        # One approach: Wrap all nodes before flow starts
        for node_id, config in node_configs.items():
            node = config['node']
            wrapped = TemplateAwareNodeWrapper(node)
            config['wrapped_node'] = wrapped

            # Replace node in flow with wrapped version
            # This requires flow introspection...
```

### Simpler Approach: Monkey-Patch During Execution

Since we control the shared store passed to the flow, we can use a special shared store that wraps nodes on-the-fly:

```python
class ProxyManagedSharedStore(dict):
    """Shared store that creates proxies for each node dynamically."""

    def __init__(self, node_mappings, initial_params=None):
        super().__init__()
        self.node_mappings = node_mappings  # {node_id: {"input_mappings": {...}, ...}}
        self.initial_params = initial_params or {}
        self._current_node = None
        self._proxies = {}  # Cache proxies per node

    def set_current_node(self, node, node_id):
        """Called by runtime before each node executes."""
        self._current_node = node_id

        # Create proxy if needed
        if node_id not in self._proxies:
            mappings = self.node_mappings.get(node_id, {})
            self._proxies[node_id] = NodeAwareSharedStore(
                shared_store=self,
                node=node,
                input_mappings=mappings.get('input_mappings'),
                output_mappings=mappings.get('output_mappings')
            )

    def get_proxy_for_current_node(self):
        """Return the proxy for the current node."""
        if self._current_node and self._current_node in self._proxies:
            return self._proxies[self._current_node]
        return self  # No proxy needed
```

But this still requires flow execution interception...

## The Practical Implementation

Given PocketFlow's constraints, here's the most practical approach:

### 1. Compile-Time Node Wrapping

```python
def compile_ir_to_flow_with_proxies(ir_dict, registry, initial_params=None):
    """Compile IR to Flow with proxy support built-in."""

    # Extract mappings from IR
    mappings = ir_dict.get('mappings', {})

    # Create flow
    flow = Flow()
    nodes = {}

    for node_spec in ir_dict['nodes']:
        node_id = node_spec['id']
        node_type = node_spec['type']
        params = node_spec.get('params', {})

        # Create base node
        node_class = registry.get_node_class(node_type)
        node = node_class()

        # Check if node needs proxy support
        has_templates = any('$' in str(v) for v in params.values())
        has_mappings = node_id in mappings

        if has_templates or has_mappings:
            # Create wrapped node
            node = ProxyEnabledNode(
                inner_node=node,
                node_id=node_id,
                mappings=mappings.get(node_id, {}),
                initial_params=initial_params
            )

        node.set_params(params)
        nodes[node_id] = node

    # Build flow structure...
    return flow, nodes
```

### 2. The ProxyEnabledNode

```python
class ProxyEnabledNode:
    """Node wrapper that applies both mappings and template resolution."""

    def __init__(self, inner_node, node_id, mappings=None, initial_params=None):
        self.inner_node = inner_node
        self.node_id = node_id
        self.mappings = mappings or {}
        self.initial_params = initial_params or {}
        self._templates = {}  # Extracted during set_params

    def set_params(self, params):
        """Store templates separately, set static params on inner node."""
        static_params = {}

        for key, value in params.items():
            if isinstance(value, str) and '$' in value:
                self._templates[key] = value
            else:
                static_params[key] = value

        self.inner_node.set_params(static_params)

    def _run(self, shared):
        """Execute with proxy shared store."""
        # Create proxy with both features
        proxy = NodeAwareSharedStore(
            shared_store=shared,
            node=self,  # Pass self so proxy can access templates
            input_mappings=self.mappings.get('input_mappings'),
            output_mappings=self.mappings.get('output_mappings')
        )

        # Add initial params to shared for resolution
        for key, value in self.initial_params.items():
            proxy._shared[f"_param_{key}"] = value

        # Resolve templates and merge with static params
        if self._templates:
            resolved = {}
            for key, template in self._templates.items():
                resolved[key] = proxy._resolve_templates(template)

            # Temporarily update inner node params
            original_params = self.inner_node.params.copy()
            self.inner_node.params.update(resolved)

            try:
                return self.inner_node._run(proxy)
            finally:
                self.inner_node.params = original_params
        else:
            # No templates, just run with proxy
            return self.inner_node._run(proxy)

    # Delegate all other attributes
    def __getattr__(self, name):
        return getattr(self.inner_node, name)

    @property
    def params(self):
        # Return combined params for introspection
        combined = self.inner_node.params.copy()
        combined.update(self._templates)
        return combined
```

## Complete Example

Let's trace through a workflow that uses both features:

```python
# IR with both mappings and templates
ir = {
    "nodes": [
        {
            "id": "fetch",
            "type": "youtube-transcript",
            "params": {"url": "$video_url"}  # Template from CLI
        },
        {
            "id": "analyze",
            "type": "llm",
            "params": {"prompt": "Summarize: $transcript"}  # Template from shared
        }
    ],
    "mappings": {
        "analyze": {
            "input_mappings": {"prompt": "transcript"}  # LLM expects 'prompt'
        }
    }
}

# Initial params from CLI
initial_params = {"video_url": "https://youtube.com/watch?v=123"}

# Execution flow:
1. fetch node executes:
   - Proxy resolves $video_url → "https://youtube.com/watch?v=123"
   - Node fetches transcript
   - Node writes shared["transcript"] = "video content..."

2. analyze node executes:
   - Proxy resolves $transcript → "video content..."
   - Node reads shared["prompt"] (mapped to shared["transcript"])
   - Node gets prompt: "Summarize: video content..."
```

## Testing Strategy

```python
def test_unified_proxy():
    """Test both mapping and template features."""
    # Create a simple node
    class TestNode(Node):
        def exec(self, shared, prep_res):
            # Read input
            input_value = shared.get("input_key")

            # Use param with template
            template = self.params.get("template")

            # Write output
            shared["output_key"] = f"{template}: {input_value}"

    # Set up proxy
    shared = {"actual_input": "test data", "var1": "hello"}
    node = TestNode()
    node.params = {"template": "Processed $var1"}

    proxy = NodeAwareSharedStore(
        shared_store=shared,
        node=node,
        input_mappings={"input_key": "actual_input"},
        output_mappings={"output_key": "actual_output"}
    )

    # Test read mapping
    assert proxy["input_key"] == "test data"

    # Test template resolution
    assert proxy.resolved_params["template"] == "Processed hello"

    # Test write mapping
    proxy["output_key"] = "result"
    assert shared["actual_output"] == "result"
```

## Integration Points

1. **Compiler**: Wrap nodes during IR compilation
2. **Runtime**: Pass initial params to wrapped nodes
3. **Nodes**: Remain completely unaware of proxies
4. **Testing**: Test both features independently and together

## Key Benefits

1. **Single Solution**: One proxy handles both problems
2. **Node Atomicity**: Nodes remain unaware of both features
3. **Composable**: Works with existing PocketFlow patterns
4. **Testable**: Each feature can be tested independently
5. **Minimal Changes**: Only affects pflow's compilation layer

This unified approach elegantly solves both the proxy mapping and template resolution challenges while maintaining the simplicity and atomicity that makes PocketFlow powerful.
