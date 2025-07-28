# Current Workflow Capabilities in pflow

This report provides a comprehensive overview of how workflows currently function in the pflow codebase, based on analysis of the implementation and underlying PocketFlow framework.

## Executive Summary

The pflow system successfully implements single-level workflow execution through a clean architecture that separates workflow definition (IR), compilation, and runtime execution. While the underlying PocketFlow framework supports nested workflows, this capability is not exposed through the pflow CLI interface.

## Core Architecture

### 1. PocketFlow Framework Foundation

The system is built on PocketFlow (`pocketflow/__init__.py`), a 100-line Python framework that provides:

- **BaseNode/Node**: Core building blocks with a three-phase lifecycle:
  - `prep(shared)`: Read and prepare data from shared storage
  - `exec(prep_res)`: Execute core logic (retryable)
  - `post(shared, prep_res, exec_res)`: Write results and return action string

- **Flow**: Orchestrator that connects nodes into a graph
  - Inherits from BaseNode (can be used as a node itself)
  - Manages node execution sequence based on action strings
  - Supports conditional routing via action-based transitions

- **Shared Store**: In-memory dictionary for inter-node communication
  - All nodes in a flow share the same storage
  - Keeps data handling separate from computation logic

### 2. Workflow Definition (IR Schema)

Workflows are defined using JSON Intermediate Representation (IR) with:

```json
{
  "ir_version": "1.0",
  "start_node": "node1",  // Optional, defaults to first node
  "nodes": [
    {
      "id": "node1",
      "type": "package.module.NodeClass",
      "params": {
        "key": "value",
        "template": "$variable"  // Template support
      }
    }
  ],
  "edges": [
    {
      "source": "node1",
      "target": "node2",
      "action": "default"  // Optional, for conditional routing
    }
  ],
  "mappings": {}  // Optional proxy mappings for NodeAwareSharedStore
}
```

### 3. Compilation Process

The compiler (`src/pflow/runtime/compiler.py`) transforms IR to executable PocketFlow objects:

1. **Parse and Validate**: Load JSON IR and validate structure
2. **Template Resolution**: Resolve `$variable` templates with provided parameters
   - Validates template paths against Node IR metadata (Task 19)
   - Accurate validation using pre-computed node interfaces
3. **Node Instantiation**:
   - Dynamically import node classes from registry metadata
   - Wrap template-aware nodes in `TemplateAwareNodeWrapper`
   - Set node parameters via `node.set_params()`
4. **Graph Construction**:
   - Wire nodes using PocketFlow's `>>` operator
   - Support action-based routing with `-` operator
5. **Flow Creation**: Return configured Flow object with start node

### 4. Runtime Execution

Workflow execution follows this pattern:

1. **CLI Integration** (`pflow run`):
   - Parse command-line arguments and pipe syntax
   - Read stdin data if available
   - Initialize shared storage with stdin data

2. **Flow Execution**:
   - Call `flow.run(shared_storage)`
   - Sequential node execution following edges
   - Action-based routing between nodes
   - Continue until no next node found

3. **Output Handling**:
   - Extract results from shared storage
   - Write to stdout if requested
   - Support verbose mode for debugging

### 5. Node Registry System

The registry provides node discovery and management:

- **Dynamic Discovery**: Scan Python modules for node classes
- **Metadata Extraction**: Parse docstrings for interface definitions at scan time (Task 19)
- **Node IR Storage**: Store complete interface metadata in registry to avoid runtime imports
- **Import Metadata**: Store module paths for dynamic loading
- **Interface Validation**: Validate node inputs/outputs/params using pre-computed metadata

### 6. Current Capabilities

#### Supported Features:
- ✅ Linear workflow execution with multiple nodes
- ✅ Conditional routing based on node actions
- ✅ Template variable substitution in node parameters
- ✅ Shell pipe integration (stdin/stdout)
- ✅ Dynamic node discovery and loading
- ✅ Shared storage for inter-node communication
- ✅ Error propagation through flow execution
- ✅ Verbose execution mode for debugging
- ✅ File operation nodes (read, write, copy, move, delete)
- ✅ Natural language workflow planning

#### Workflow Patterns:
- Sequential pipelines (A → B → C)
- Conditional branching (A → B or C based on action)
- Error handling flows (main path vs error path)
- Data transformation pipelines
- File processing workflows

### 7. Integration Points

- **CLI Interface**: Primary user interaction through `pflow` command
- **LLM Planning**: Natural language to workflow IR conversion
- **Shell Integration**: Unix pipe compatibility
- **Node Packages**: Extensible node ecosystem

## Architecture Strengths

1. **Clean Separation of Concerns**: IR definition, compilation, and runtime are independent
2. **Framework Flexibility**: PocketFlow supports advanced patterns (batch, async, nested)
3. **Extensible Design**: Easy to add new node types and packages
4. **Template System**: Flexible parameter substitution
5. **Standard Patterns**: Consistent node lifecycle and communication

## Current Limitations

1. **Single-Level Workflows Only**: No nested workflow support in IR/compiler
2. **Synchronous Execution**: No async node support in MVP
3. **Limited Flow Control**: No loops or complex control structures
4. **No Workflow Reuse**: Workflows cannot be saved and referenced as components
5. **Flat Registry**: Only tracks individual nodes, not composite workflows

## Conclusion

The current pflow implementation successfully delivers a functional workflow execution system with a solid architectural foundation. The system can compile and execute linear workflows with conditional routing, making it suitable for many automation tasks. The underlying PocketFlow framework provides the capability for more advanced features, setting up a clear path for future enhancements.
