# Execution Reference

> **Navigation**: [Index](../index.md) → Execution Reference

## Overview

This document is the authoritative reference for pflow's execution model and runtime behavior. It covers the execution flow, error handling, retry mechanisms, validation, and performance optimizations.

## Table of Contents

- [Core Execution Principles](#core-execution-principles)
- [Execution Flow](#execution-flow)
- [Node Safety Model](#node-safety-model)
- [Error Handling](#error-handling)
- [Retry Mechanisms](#retry-mechanisms)
- [Validation Pipeline](#validation-pipeline)
- [Flow Immutability](#flow-immutability)
- [Runtime Integration](#runtime-integration)
- [Performance Considerations](#performance-considerations)
- [Testing Framework](#testing-framework)

## Core Execution Principles

### Static Execution Model

pflow uses a **static execution model** where:

- Flows are immutable after creation
- No dynamic topology changes during execution
- Predictable, deterministic behavior
- Cacheable at the node level

### Fail-Fast Behavior

All flows follow fail-fast semantics:

```python
# Any node failure aborts the entire flow
flow = node1 >> node2 >> node3
# If node2 fails, node3 never executes
```

This ensures:
- Clear error attribution
- No partial state corruption
- Simplified debugging
- Consistent flow state

## Execution Flow

The complete execution pipeline consists of 7 steps:

### 1. Parse CLI Arguments
```python
args = parse_cli_args(sys.argv)
# Extract nodes, flags, natural language
```

### 2. Plan (if needed)
```python
if args.is_natural_language:
    ir = planner.plan(args.prompt)
else:
    ir = cli_to_ir(args.nodes, args.flags)
```

### 3. Validate
```python
# Structural validation
validate_ir_schema(ir)

# Node availability
for node in ir.nodes:
    registry.validate_node_exists(node)

# Interface compatibility
validate_node_interfaces(ir)
```

### 4. Resolve Nodes
```python
nodes = []
for node_spec in ir.nodes:
    node_class = registry.get_node(
        node_spec.registry_id,
        node_spec.version
    )
    nodes.append(node_class)
```

### 5. Build Flow
```python
# Generate flow code with proxy if needed
flow_code = generate_flow_code(nodes, ir)

# Example generated code:
flow = (
    ReadFileNode()
        .set_params({"path": "input.txt"}) >>
    LLMNode()
        .set_params({"model": "gpt-4"})
        .with_proxy({"text": "content"})  # If mapping needed
)
```

### 6. Execute
```python
shared = {}

# Inject CLI values
for key, value in cli_injections.items():
    shared[key] = value

# Run the flow
result = flow.run(shared)
```

### 7. Output Results
```python
# Format based on output flags
if args.output_format == "json":
    print(json.dumps(shared))
else:
    print(shared.get("output", result))
```

## Node Safety Model

pflow implements an **opt-in purity model** for safe node caching:

### The `@flow_safe` Decorator

```python
@flow_safe
class ReadFileNode(Node):
    """Pure node - same inputs always produce same outputs"""

    def exec(self, path):
        # No side effects beyond reading
        with open(path) as f:
            return f.read()
```

### Safety Requirements

A node is `@flow_safe` if it:
- Is deterministic (same inputs → same outputs)
- Has no side effects (or idempotent ones)
- Doesn't depend on external state
- Doesn't modify global state

### Non-Safe Nodes

```python
class WriteFileNode(Node):
    """Not flow_safe - has side effects"""

    def exec(self, path, content):
        # Side effect: writes to filesystem
        with open(path, 'w') as f:
            f.write(content)
```

## Error Handling

### Error Categories

Errors are namespaced by origin:

| Namespace | Example | Description |
|-----------|---------|-------------|
| `cli` | `cli:invalid-syntax` | Command parsing errors |
| `planner` | `planner:ambiguous` | Planning failures |
| `registry` | `registry:not-found` | Node resolution errors |
| `runtime` | `runtime:timeout` | Execution errors |
| `node` | `node:validation` | Node-specific errors |

### Common Error Types

```python
# CLI errors
cli:missing-required-flag
cli:invalid-flag-value
cli:syntax-error

# Planner errors
planner:no-matching-nodes
planner:ambiguous-intent
planner:resource-limit

# Runtime errors
runtime:node-failure
runtime:timeout
runtime:memory-limit
runtime:cache-corruption

# Node errors
node:missing-input
node:invalid-parameter
node:execution-failure
```

### Error Context

All errors include structured context:

```json
{
  "error": "node:missing-input",
  "node": "llm-process",
  "details": {
    "missing_key": "prompt",
    "available_keys": ["text", "url"],
    "suggestion": "Did you mean to use 'text' instead?"
  },
  "trace": "..."
}
```

## Retry Mechanisms

### Retry Configuration

Nodes can specify retry behavior:

```python
{
  "execution": {
    "max_retries": 3,
    "retry_delay": 1.0,
    "retry_backoff": 2.0,
    "retry_on": ["timeout", "rate_limit"]
  }
}
```

### Retry Logic

```python
def execute_with_retry(node, inputs, config):
    attempt = 0
    delay = config.retry_delay

    while attempt <= config.max_retries:
        try:
            return node.exec(inputs)
        except Exception as e:
            if not should_retry(e, config.retry_on):
                raise

            attempt += 1
            if attempt > config.max_retries:
                raise

            time.sleep(delay)
            delay *= config.retry_backoff
```

### Retry Eligibility

Only transient errors are retryable:
- Network timeouts
- Rate limiting
- Temporary unavailability
- Connection errors

Non-retryable errors:
- Validation failures
- Missing inputs
- Logic errors
- Permission denied

## Validation Pipeline

### 1. Schema Validation

```python
# Validate IR structure
jsonschema.validate(ir, FLOW_IR_SCHEMA)
```

### 2. Node Validation

```python
for node in ir.nodes:
    # Node exists in registry
    assert registry.has_node(node.registry_id)

    # Version is available
    assert registry.has_version(
        node.registry_id,
        node.version
    )

    # Parameters are valid
    metadata = registry.get_metadata(node.registry_id)
    validate_params(node.params, metadata.params)
```

### 3. Interface Validation

```python
# Check data flow compatibility
for edge in ir.edges:
    source = get_node(edge.source)
    target = get_node(edge.target)

    # Ensure source produces what target needs
    validate_interface_compatibility(
        source.interface.writes,
        target.interface.reads
    )
```

### 4. Flow-Level Validation

```python
# No cycles
assert is_acyclic(ir)

# Connected graph
assert is_connected(ir)

# Single entry/exit
assert len(get_entry_nodes(ir)) == 1
assert len(get_exit_nodes(ir)) == 1
```

## Flow Immutability

### Benefits of Static Execution

1. **Predictability**: Know exactly what will run
2. **Cacheability**: Deterministic cache keys
3. **Debuggability**: Reproducible failures
4. **Optimization**: Static analysis possible
5. **Security**: No code injection risks

### Prohibited at Runtime

- Adding/removing nodes
- Changing edges
- Modifying parameters
- Altering execution order
- Dynamic code generation

### Allowed at Runtime

- Shared store mutations
- CLI flag overrides
- Environment variable resolution
- Template variable expansion

## Runtime Integration

### Execution Engine Configuration

```python
from pocketflow import Flow
from pflow.runtime import ExecutionContext

# Runtime wraps pocketflow with pflow features
context = ExecutionContext(
    cache_dir="~/.pflow/cache",
    trace_enabled=True,
    debug_mode=False
)

# Execute with context
result = context.execute(flow, shared)
```

### IR to Flow Compilation

```python
def compile_ir_to_flow(ir):
    """Generate executable flow from IR"""

    nodes = []
    for node_spec in ir.nodes:
        # Get node class
        NodeClass = registry.get_node_class(
            node_spec.registry_id
        )

        # Instantiate with params
        node = NodeClass()
        node.set_params(node_spec.params)

        # Add proxy if mappings exist
        if node_spec.id in ir.mappings:
            mappings = ir.mappings[node_spec.id]
            node = node.with_proxy(mappings)

        nodes.append(node)

    # Chain nodes with >> operator
    flow = nodes[0]
    for node in nodes[1:]:
        flow = flow >> node

    return flow
```

### Execution Hooks

```python
class ExecutionContext:
    def pre_node_hook(self, node, shared):
        """Called before each node execution"""
        if self.trace_enabled:
            log_node_start(node, shared)

    def post_node_hook(self, node, shared, result):
        """Called after each node execution"""
        if self.trace_enabled:
            log_node_complete(node, result)

        if self.cache_enabled and is_flow_safe(node):
            cache_result(node, shared, result)
```

## Performance Considerations

### Execution Overhead

| Operation | Typical Time | Notes |
|-----------|-------------|-------|
| IR parsing | < 1ms | JSON parsing |
| Validation | 1-5ms | Depends on flow size |
| Node resolution | < 1ms | Registry lookup |
| Flow compilation | < 1ms | Code generation |
| Per-node overhead | < 0.1ms | Method calls |

### Memory Usage

- Shared store: O(data size)
- Flow structure: O(nodes + edges)
- Cache entries: O(cached results)
- Typical flow: < 10MB overhead

### Optimization Strategies

1. **Node-level caching** for expensive operations
2. **Lazy evaluation** where possible
3. **Streaming** for large data
4. **Connection pooling** for APIs
5. **Batch processing** support

## Testing Framework

### Unit Testing Nodes

```python
from pflow.testing import NodeTestCase

class TestLLMNode(NodeTestCase):
    def test_execution(self):
        node = LLMNode()
        node.set_params({"model": "gpt-4"})

        shared = {"prompt": "Hello"}
        result = self.execute_node(node, shared)

        self.assertIn("response", shared)
        self.assertEqual(result, "default")
```

### Integration Testing Flows

```python
from pflow.testing import FlowTestCase

class TestGitHubFlow(FlowTestCase):
    def test_issue_fix_flow(self):
        flow = self.build_flow([
            "github-get-issue --issue=123",
            "llm --prompt='Generate fix'",
            "github-create-pr"
        ])

        result = self.execute_flow(flow)
        self.assertSuccess(result)
        self.assertCreatedPR(result)
```

### Mocking External Services

```python
from pflow.testing import mock_node

@mock_node("github/get-issue")
def mock_github_issue(shared):
    shared["issue"] = {
        "title": "Test Issue",
        "body": "Test description"
    }
    return "default"
```

## Future Features

### Execution Checkpointing (v2.0)

```python
# Save execution state
checkpoint = context.checkpoint(flow, shared)

# Resume from checkpoint
result = context.resume(checkpoint)
```

### Parallel Execution (v2.0)

```python
# Execute independent nodes in parallel
flow = source >> [process_a, process_b] >> merge
```

### Streaming Execution (v3.0)

```python
# Process data as it arrives
for chunk in flow.stream(data_source):
    process(chunk)
```

## See Also

- [Node Reference](node-reference.md) - Node implementation details
- [CLI Reference](cli-reference.md) - How CLI commands execute
- [Runtime](../core-concepts/runtime.md) - Caching and safety specifics
- [Schemas](../core-concepts/schemas.md) - IR validation schemas
- [Architecture](../architecture/architecture.md) - System design overview
