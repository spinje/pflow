# PocketFlow Interface Guide for Non-PocketFlow Tasks

This guide is for implementers working on traditional (non-PocketFlow) components that need to interface with PocketFlow-based components.

## Key Concepts You Need to Know

### 1. The Shared Store

PocketFlow uses a shared dictionary for all inter-component communication. When your traditional code needs to interact with PocketFlow components, you'll pass data through this shared store.

```python
# Example: Calling a PocketFlow-based compiler from traditional code
from pflow.flows.compiler import create_compiler_flow

def compile_workflow(ir_json, registry):
    """Traditional function that uses PocketFlow compiler."""
    # Create the flow
    compiler_flow = create_compiler_flow(registry)

    # Initialize shared store with your data
    shared = {
        "ir_json": ir_json,
        "registry": registry,
        "compile_options": {
            "validate": True,
            "optimize": False
        }
    }

    # Run the flow
    result = compiler_flow.run(shared)

    # Extract what you need from the result
    if "compiled_flow" in result:
        return result["compiled_flow"]
    elif "error" in result:
        raise CompilationError(result["error"])
```

### 2. Expected Keys in Shared Store

Each PocketFlow component documents its interface through shared store keys:

#### Input Keys (what you need to provide):
- Read the component's documentation to find required input keys
- Example: The compiler might expect `shared["ir_json"]` and `shared["registry"]`

#### Output Keys (what you can expect back):
- Success case: Look for result keys like `shared["result"]`, `shared["compiled_flow"]`, etc.
- Error case: Usually `shared["error"]` with error details

### 3. Error Handling

PocketFlow components handle errors internally but communicate failures through the shared store:

```python
# Your traditional code
result = flow.run(shared)

# Check for errors
if "error" in result:
    # Handle the error
    error_msg = result["error"]
    error_type = result.get("error_type", "unknown")

    if error_type == "validation":
        # Handle validation errors
        pass
    else:
        # Generic error handling
        pass
```

### 4. Integration Points

The 6 PocketFlow components you'll interface with:

#### Task 4: IR Compiler (`pflow.flows.compiler`)
```python
# Input: ir_json, registry
# Output: compiled_flow or error
from pflow.flows.compiler import compile_ir_to_flow
flow = compile_ir_to_flow(ir_json, registry)
```

#### Task 8: Shell Integration (`pflow.flows.shell`)
```python
# Input: (checks stdin automatically)
# Output: stdin content in shared["stdin"]
from pflow.flows.shell import process_shell_input
shared = process_shell_input()
```

#### Task 17: Workflow Planner (`pflow.flows.planner`)
```python
# Input: user_input, registry
# Output: generated_workflow or error
from pflow.flows.planner import plan_workflow
workflow = plan_workflow(user_query, registry)
```

#### Task 20: Approval System (`pflow.flows.approval`)
```python
# Input: generated_workflow
# Output: approved_workflow, workflow_name
from pflow.flows.approval import approve_and_save
result = approve_and_save(workflow)
```

#### Task 22: Workflow Execution (`pflow.flows.execution`)
```python
# Input: workflow_name, parameters
# Output: execution_result
from pflow.flows.execution import execute_named_workflow
result = execute_named_workflow("fix-issue", {"issue": "123"})
```

#### Task 23: Execution Tracing (`pflow.flows.tracing`)
```python
# Input: flow_to_trace, trace_options
# Output: execution_result with trace data
from pflow.flows.tracing import execute_with_tracing
result = execute_with_tracing(flow, {"verbosity": "normal"})
```

## Common Patterns

### Pattern 1: Wrapping PocketFlow in Traditional API

```python
class WorkflowCompiler:
    """Traditional class wrapping PocketFlow compiler."""

    def __init__(self, registry):
        self.registry = registry
        self.compiler_flow = create_compiler_flow(registry)

    def compile(self, ir_json: dict) -> PocketFlowObject:
        """Clean API hiding PocketFlow details."""
        shared = {
            "ir_json": ir_json,
            "registry": self.registry
        }

        result = self.compiler_flow.run(shared)

        if "error" in result:
            raise CompilationError(result["error"])

        return result["compiled_flow"]
```

### Pattern 2: Async Wrapper for Sync PocketFlow

```python
async def compile_workflow_async(ir_json, registry):
    """Async wrapper for sync PocketFlow component."""
    loop = asyncio.get_event_loop()

    # Run in thread pool to avoid blocking
    result = await loop.run_in_executor(
        None,
        lambda: compile_workflow(ir_json, registry)
    )

    return result
```

### Pattern 3: Configuration Passing

```python
def execute_with_options(workflow_name, params, **options):
    """Pass configuration through shared store."""
    shared = {
        "workflow_name": workflow_name,
        "parameters": params,
        # Pass any additional options
        "trace_enabled": options.get("trace", False),
        "cache_enabled": options.get("cache", True),
        "timeout": options.get("timeout", 300)
    }

    flow = create_execution_flow()
    return flow.run(shared)
```

## What You DON'T Need to Know

1. **Internal Node Structure**: You don't need to understand how nodes work internally
2. **Flow Orchestration**: The `>>` operator and flow construction is handled internally
3. **Retry Logic**: PocketFlow handles retries automatically
4. **Node Lifecycle**: The prep/exec/post lifecycle is internal to PocketFlow

## Testing Your Integration

When testing traditional code that calls PocketFlow components:

```python
def test_my_traditional_component():
    # Mock the PocketFlow component
    mock_flow = Mock()
    mock_flow.run.return_value = {
        "compiled_flow": Mock(),
        "metadata": {"node_count": 5}
    }

    with patch('pflow.flows.compiler.create_compiler_flow', return_value=mock_flow):
        # Test your code
        result = my_function_that_uses_compiler()

        # Verify the flow was called correctly
        mock_flow.run.assert_called_once()
        call_args = mock_flow.run.call_args[0][0]
        assert "ir_json" in call_args
```

## Summary

When working with PocketFlow components from traditional code:
1. **Prepare data** in a dictionary (shared store)
2. **Call the flow** with `.run(shared)`
3. **Extract results** from the returned dictionary
4. **Handle errors** by checking for "error" key
5. **Don't worry** about PocketFlow internals

The interface is intentionally simple - just dictionaries in, dictionaries out!
