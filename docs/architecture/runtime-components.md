# Runtime Components

This document explains the distinction between user-facing nodes and internal runtime components in pflow.

## Overview

The pflow architecture separates concerns between:
- **Nodes**: User-facing features that perform specific tasks (e.g., reading files, calling LLMs)
- **Runtime Components**: Internal infrastructure that executes workflows

This separation allows the runtime to evolve independently from the user-facing API.

## User-Facing Nodes vs Runtime Components

### User-Facing Nodes

These are the building blocks users work with directly:
- Defined in `src/pflow/nodes/`
- Discoverable via the registry
- Have metadata describing their interface
- Appear in workflow JSON with their `type` field
- Examples: `read-file`, `write-file`, `llm`, etc.

### Runtime Components

These are internal implementation details:
- Defined in `src/pflow/runtime/`
- Not exposed in the registry
- Handle workflow execution infrastructure
- Users don't interact with them directly
- Examples: `WorkflowExecutor`, `Compiler`, etc.

## Example: WorkflowExecutor

The `WorkflowExecutor` is a prime example of a runtime component:

### What Users See
```json
{
  "id": "run_subflow",
  "type": "workflow",
  "params": {
    "workflow_ref": "path/to/workflow.json",
    "param_mapping": {
      "input": "$data"
    }
  }
}
```

Users simply specify `type: "workflow"` and provide parameters. They don't need to know about WorkflowExecutor.

### What Happens Internally

1. The runtime sees `type: "workflow"` in the IR
2. It instantiates a `WorkflowExecutor` (not a regular node)
3. The executor handles:
   - Loading the sub-workflow
   - Setting up storage isolation
   - Parameter mapping
   - Recursive execution
   - Output mapping
   - Error context preservation

### Why This Separation?

1. **Simplicity**: Users only need to know about the `workflow` type
2. **Evolution**: We can improve WorkflowExecutor without changing the user API
3. **Safety**: Runtime components can have special privileges that regular nodes shouldn't have
4. **Performance**: Runtime components can be optimized differently than user nodes

## Other Runtime Components

### Compiler (`runtime/compiler.py`)

Transforms JSON IR into executable PocketFlow objects:
- Validates workflow structure
- Resolves node references
- Builds execution graph
- Handles special node types (like `workflow`)

### Future Components

As pflow evolves, more runtime components may be added:
- **Scheduler**: For parallel execution (v2.0)
- **Cache Manager**: For intelligent caching
- **Resource Manager**: For cloud execution limits
- **Security Manager**: For sandboxing and permissions

## Design Principles

1. **Transparent to Users**: Users shouldn't need to understand runtime internals
2. **Clear Boundaries**: Runtime components live in `runtime/`, nodes in `nodes/`
3. **Special Handling**: Runtime can treat certain node types specially (like `workflow`)
4. **No Registry Pollution**: Runtime components don't appear in node discovery

## For Developers

When implementing new functionality, ask:
- Is this a user-facing feature? → Create a node in `nodes/`
- Is this execution infrastructure? → Create a runtime component in `runtime/`
- Does it need special privileges? → Probably a runtime component

### Adding Runtime Components

1. Place in `src/pflow/runtime/`
2. Don't inherit from `BaseNode` or `Node`
3. Document the component's role clearly
4. Handle errors with good context
5. Write comprehensive tests

### Special Node Types

Some node types (like `workflow`) are handled specially by the runtime:
1. User specifies them like any other node
2. Runtime intercepts and uses specialized components
3. This is transparent to the user

## Summary

The separation between nodes and runtime components is a key architectural decision that:
- Keeps the user API simple and stable
- Allows the runtime to evolve and optimize
- Maintains clear boundaries in the codebase
- Enables special handling for complex features

Users work with nodes. The runtime makes them work.
