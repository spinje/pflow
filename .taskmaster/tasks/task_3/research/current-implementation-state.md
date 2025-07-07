# Current Implementation State Summary

## Overview

This document summarizes the current implementation state of the pflow project as it relates to Task 3 (Natural Language to IR Planner).

## Implemented Components

### 1. JSON IR Schema (Task 6)
- **Location**: `src/pflow/core/ir_schema.py`
- **Key Features**:
  - Complete JSON schema definition
  - `validate_ir()` function with custom ValidationError
  - Business logic validation (node references, duplicate IDs)
  - Helpful error messages with paths and suggestions

**IR Structure**:
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "n1", "type": "read-file", "params": {"path": "input.txt"}}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "action": "default"}
  ],
  "start_node": "n1"  // optional
}
```

### 2. IR to PocketFlow Compiler (Task 4)
- **Location**: `src/pflow/runtime/compiler.py`
- **Main Function**: `compile_ir_to_flow(ir_json, registry) -> Flow`
- **Features**:
  - Dynamic node import from registry
  - Rich CompilationError with phases
  - Support for both edge formats (source/target, from/to)
  - Comprehensive logging

### 3. Node Discovery System (Task 5)
- **Location**: `src/pflow/registry/scanner.py` and `registry.py`
- **Scanner Features**:
  - `scan_for_nodes(directories)` finds BaseNode subclasses
  - Automatic kebab-case naming
  - Metadata extraction
- **Registry Features**:
  - Persistent JSON storage at `~/.pflow/registry.json`
  - Load/save operations
  - Node name as dictionary key

### 4. Simple Platform Nodes
- **Location**: `src/pflow/nodes/file/`
- **Implemented Nodes**:
  - ReadFileNode
  - WriteFileNode
  - CopyFileNode
  - MoveFileNode
  - DeleteFileNode
- **Pattern**: Heavy use of shared store for I/O

### 5. CLI Foundation
- **Location**: `src/pflow/cli/main.py`
- **Current State**:
  - Collects raw input from args/stdin/file
  - Stores in context object
  - Placeholder output: "Collected workflow from {source}: {input}"
  - Ready for planner integration

## Missing Components for Task 3

1. **Planner Module**: No planner implementation exists yet
2. **LLM Integration**: No LLM library integration
3. **Syntax Detection**: No logic to differentiate CLI vs natural language
4. **CLI Parser**: No parser for `=>` operator syntax
5. **Prompt Engineering**: No prompts for LLM-based planning

## Integration Points Ready

1. **Registry Available**:
   ```python
   from pflow.registry import Registry
   registry = Registry()
   nodes = registry.load()
   ```

2. **Validation Ready**:
   ```python
   from pflow.core import validate_ir
   validate_ir(ir_dict)
   ```

3. **Compiler Ready**:
   ```python
   from pflow.runtime import compile_ir_to_flow
   flow = compile_ir_to_flow(ir_dict, registry)
   ```

4. **CLI Context Ready**:
   - Input available in `ctx.obj["raw_input"]`
   - Source type in `ctx.obj["input_source"]`

## Node Communication Pattern

All nodes use shared store for communication:
- Input: Read from `shared[key]` or `self.params[key]`
- Output: Write to `shared[key]`
- Errors: Set `shared["error"]` and return "error" action

Example from ReadFileNode:
```python
def prep(self, shared: dict):
    file_path = shared.get("file_path") or self.params.get("file_path")

def post(self, shared: dict, prep_res, exec_res):
    if success:
        shared["content"] = content
        return "default"
    else:
        shared["error"] = error_msg
        return "error"
```

## Project Structure Relevant to Task 3

```
src/pflow/
├── __init__.py
├── cli/
│   ├── __init__.py
│   └── main.py           # CLI entry point, needs planner integration
├── core/
│   ├── __init__.py
│   └── ir_schema.py      # IR validation
├── registry/
│   ├── __init__.py
│   ├── registry.py       # Node registry
│   └── scanner.py        # Node discovery
├── runtime/
│   ├── __init__.py
│   └── compiler.py       # IR to Flow compiler
├── nodes/                # Platform nodes
└── planner/             # TO BE CREATED
    ├── __init__.py
    ├── planner.py       # Main planning logic
    ├── syntax_detector.py
    ├── cli_parser.py
    ├── nl_planner.py
    └── prompts.py
```

## Key Decisions for Task 3

1. **LLM Library**: Use Simon Willison's `llm` library (already in dependencies)
2. **Syntax Detection**: Simple heuristic - presence of `=>` indicates CLI syntax
3. **Error Recovery**: Retry with better prompts on LLM failures
4. **Node Matching**: Use registry metadata and docstrings for intent mapping

## Next Implementation Steps

1. Create planner module structure
2. Implement syntax detection
3. Build CLI parser for `=>` syntax
4. Create LLM-based natural language planner
5. Integrate with CLI main
6. Add comprehensive tests
