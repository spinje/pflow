# Implemented pflow Components

This document provides a factual inventory of completed components in the pflow system. It serves as a reference for all agents working on tasks to understand what infrastructure already exists.

*Last Updated: Task 17 Research Phase*

## Core Infrastructure

### 1. JSON IR Schema (Task 6)
- **Location**: `src/pflow/core/ir_schema.py`
- **Key Components**:
  - `FLOW_IR_SCHEMA` - Complete JSON schema definition
  - `validate_ir()` - Validation function with helpful error messages
  - `ValidationError` - Custom exception with path and suggestions
- **Features**:
  - Validates structure, types, and references
  - Checks for duplicate node IDs
  - Verifies edge references exist
  - Supports template variables (`$variable` syntax)

### 2. IR to PocketFlow Compiler (Task 4)
- **Location**: `src/pflow/runtime/compiler.py`
- **Key Function**: `compile_ir_to_flow(ir_dict, registry) -> Flow`
- **Features**:
  - Converts JSON IR to executable PocketFlow objects
  - Dynamic node import from registry
  - Rich error handling with compilation phases
  - Supports action-based routing (edges)

### 3. Node Registry System (Task 5)
- **Location**: `src/pflow/registry/`
- **Components**:
  - `Registry` - Central registry class
  - `Scanner` - Finds nodes via filesystem scanning
  - `MetadataExtractor` - Extracts metadata from docstrings
- **Storage**: `~/.pflow/registry.json`
- **Features**:
  - Automatic node discovery
  - Persistent metadata caching
  - Node naming (explicit or kebab-case conversion)

### 4. Context Builder (Tasks 15/16)
- **Location**: `src/pflow/planning/context_builder.py`
- **Key Functions**:
  - `build_discovery_context()` - Lightweight browsing (names/descriptions only)
  - `build_planning_context()` - Detailed interface info for selected components
- **Features**:
  - Two-phase approach (discovery vs planning)
  - Workflow loading from `~/.pflow/workflows/`
  - Structure documentation support for proxy mappings
  - Handles both nodes and workflows

### 5. Shell Integration (Task 8)
- **Location**: `src/pflow/core/shell_integration.py`
- **Key Components**:
  - `StdinData` - Handles text/binary/file inputs
  - `read_stdin_enhanced()` - Smart stdin reading
  - `determine_stdin_mode()` - Detects workflow vs data
- **Features**:
  - Handles piped input elegantly
  - Binary data support via temp files
  - Automatic mode detection

## Platform Nodes

### 6. File Operation Nodes (Task 11)
- **Location**: `src/pflow/nodes/file/`
- **Implemented Nodes**:
  - `ReadFileNode` - Reads file content
  - `WriteFileNode` - Writes content to file
  - `CopyFileNode` - Copies files
  - `MoveFileNode` - Moves files
  - `DeleteFileNode` - Deletes files
- **Pattern**: All use shared store with natural keys

## CLI Foundation

### 7. CLI Entry Point
- **Location**: `src/pflow/cli/main.py`
- **Current State**:
  - Collects input from args/stdin/file
  - Stores in Click context object
  - Can execute JSON workflows
  - Handles broken pipes gracefully
- **Context Keys**:
  - `ctx.obj["raw_input"]` - User's input
  - `ctx.obj["input_source"]` - Where input came from
  - `ctx.obj["stdin_data"]` - Any piped data

## Testing Infrastructure

### 8. Comprehensive Test Suite
- **Location**: `tests/`
- **Coverage**:
  - Unit tests for all components
  - Integration tests for workflows
  - Performance benchmarks
  - Example validation

## Documentation

### 9. Extensive Documentation
- **Location**: `docs/`
- **Key Documents**:
  - Architecture overview
  - Component specifications
  - API references
  - Implementation guides

## Development Tools

### 10. Build and Development
- **Makefile**: Development automation
- **pyproject.toml**: Dependency management
- **pre-commit**: Code quality hooks

---

## How to Access These Components

### Registry Usage
```python
from pflow.registry import Registry
registry = Registry()
available_nodes = registry.load()  # Returns dict of metadata
```

### IR Validation
```python
from pflow.core import validate_ir, ValidationError
try:
    validate_ir(workflow_dict)
except ValidationError as e:
    print(f"Error at {e.path}: {e.message}")
```

### Compilation
```python
from pflow.runtime import compile_ir_to_flow
flow = compile_ir_to_flow(validated_ir, registry)
result = flow.run(shared_dict)
```

### Context Building
```python
from pflow.planning.context_builder import build_discovery_context
context = build_discovery_context(registry_metadata=registry.load())
```

---

*Note: This is a living document. Update it as new components are implemented.*
