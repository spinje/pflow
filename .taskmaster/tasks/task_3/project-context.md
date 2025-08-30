# Task 3 Project Context Briefing

## Executive Summary

Task 3 "Execute a Hardcoded 'Hello World' Workflow" serves as the **first integration milestone** for pflow, proving that all Phase 1 components work together in a complete execution pipeline. This task integrates 6 previously completed tasks to demonstrate end-to-end workflow execution from JSON IR to actual file operations.

**IMPORTANT UPDATE**: Task 3 has been substantially implemented in commit `dff02c3 Fix Task 3 integration issues and enable workflow execution`. The workflow execution is functional, integration tests exist, and `hello_workflow.json` successfully executes. The focus has shifted from implementation to review, polish, and ensuring completeness.

## Task Position in Architecture

### Purpose
Task 3 validates the core execution pipeline by:
1. Loading a JSON workflow definition from file
2. Validating it against the IR schema (Task 6)
3. Looking up nodes in the registry (Task 5)
4. Compiling IR to PocketFlow objects (Task 4)
5. Executing file operations (Task 11)
6. Using the CLI infrastructure (Task 2)

### Critical Path
This is a **critical integration task** that:
- Proves all Phase 1 components work together
- Establishes the pattern for future workflow execution
- Validates the shared store communication model
- Tests the complete data flow from CLI to execution

## Current Implementation State

### CLI Structure (`src/pflow/cli/main.py`)
The CLI currently:
- Has a basic command structure with version support ✓
- Supports --file option for reading workflow definitions ✓
- Can detect and read from stdin ✓
- Has comprehensive error handling with helpful messages ✓
- **FULLY executes JSON workflows** ✓ (implemented in commit dff02c3)

Key integration points:
```python
# Lines 65-92: execute_json_workflow() - fully implements workflow execution
# Lines 83-88: Initializes shared store and runs the flow
# Lines 94-121: process_file_workflow() - handles file input with error handling
# Lines 127-195: main() - CLI entry point with --file option
```

### Existing Components Status

#### ✅ IR Schema & Validation (`src/pflow/core/ir_schema.py`)
- Complete JSON schema for workflow IR
- `validate_ir()` function with detailed error messages
- Support for template variables ($variable syntax)
- Node reference validation and duplicate ID checking

#### ✅ Registry System (`src/pflow/registry/`)
- Node discovery via filesystem scanning
- Registry persistence to `~/.pflow/registry.json`
- Metadata storage (module path, class name, docstring)
- Node naming: explicit `name` attribute or kebab-case conversion

#### ✅ IR Compiler (`src/pflow/runtime/compiler.py`)
- `compile_ir_to_flow()` - main compilation function
- Dynamic node import from registry metadata
- Node wiring with PocketFlow's >> operator
- Comprehensive error handling with context

#### ✅ File Nodes (`src/pflow/nodes/file/`)
- ReadFileNode: Reads files with line numbers
- WriteFileNode: Writes content with directory creation
- Natural interfaces using shared store
- Proper error handling and retry logic

## PocketFlow Framework Integration

### Core Concepts
PocketFlow (`pocketflow/__init__.py`) provides:
- **BaseNode/Node**: Base classes with prep/exec/post lifecycle
- **Flow**: Orchestrator that executes nodes sequentially
- **Shared Store**: Dictionary passed between nodes for communication
- **Operators**: `>>` for chaining, `-` for conditional routing

### Key Patterns from Cookbook
1. **Simple Sequential Flow** (`pocketflow-flow/`): Basic node chaining
2. **Shared Store Communication** (`pocketflow-communication/`): Data passing between nodes
3. **Node Lifecycle** (`pocketflow-node/`): prep → exec → post pattern
4. **Hello World Example** (`pocketflow-hello-world/`): Minimal implementation

### Integration Considerations
- Nodes inherit from `pocketflow.Node` (not BaseNode) for retry support
- Shared store is a simple dict passed to `flow.run(shared)`
- Node parameters set via `node.set_params(params)`
- Flow execution is synchronous in MVP

## Key Concepts and Terminology

### Workflow IR (Intermediate Representation)
JSON format that describes workflows:
```json
{
  "ir_version": "0.1.0",
  "nodes": [...],     // Array of node definitions
  "edges": [...],     // Connections between nodes
  "start_node": "...", // Optional, defaults to first node
  "mappings": {...}    // Optional proxy mappings (future)
}
```

### Node Naming Convention
- Registry keys use kebab-case: `"read-file"`, `"write-file"`
- Class names use PascalCase: `ReadFileNode`, `WriteFileNode`
- Explicit name attribute overrides auto-conversion

### Shared Store Pattern
- Nodes communicate via shared dictionary
- Natural interfaces: `shared["file_path"]`, `shared["content"]`
- Read in `prep()`, write in `post()`
- Pass-through pattern for data flow

### Execution Flow
1. CLI receives `--file workflow.json`
2. Load and parse JSON
3. Validate against IR schema
4. Load registry (must exist)
5. Compile IR → Flow object
6. Initialize empty shared store
7. Execute flow with shared store
8. Report success/failure

## Integration Points

### 1. CLI → IR Validation
```python
from pflow.core import ValidationError, validate_ir
# In execute_json_workflow():
validate_ir(ir_data)  # Raises ValidationError with details
```

### 2. CLI → Registry
```python
from pflow.registry import Registry
registry = Registry()
if not registry.registry_path.exists():
    # Error: registry not found
```

### 3. CLI → Compiler
```python
from pflow.runtime import CompilationError, compile_ir_to_flow
flow = compile_ir_to_flow(ir_data, registry)
```

### 4. CLI → Execution
```python
shared_storage: dict[str, Any] = {}
flow.run(shared_storage)
# Check shared_storage for results
```

## Relevant Documentation References

### Core Documentation
- `architecture/features/cli-runtime.md` - CLI and shared store integration
- `architecture/core-concepts/runtime.md` - Execution model (MVP simplified)
- `architecture/core-concepts/schemas.md` - IR schema and examples
- `architecture/reference/cli-reference.md` - CLI command reference

### PocketFlow Resources
- `pocketflow/__init__.py` - Framework source (100 lines)
- `pocketflow/docs/core_abstraction/` - Node, Flow, communication docs
- `pocketflow/cookbook/pocketflow-hello-world/` - Simplest example
- `pocketflow/cookbook/pocketflow-communication/` - Shared store patterns

### Implementation Guides
- `architecture/features/simple-nodes.md` - Node design philosophy
- `architecture/architecture/pflow-pocketflow-integration-guide.md` - Integration patterns
- `.taskmaster/tasks/task_3/research/` - Previous implementation analysis

## Known Issues and Considerations

### 1. Registry Population
Currently requires manual population via:
```bash
python scripts/populate_registry.py
```
This is temporary until Task 10 implements registry CLI commands.

### 2. PocketFlow Parameter Modification
A temporary modification was made to `pocketflow/__init__.py` (lines 101-107) to preserve node parameters. This is documented and will need revisiting for BatchFlow support.

### 3. Line Numbers in ReadFileNode
The ReadFileNode adds line numbers to content (design decision from Tutorial-Cursor pattern). This affects how content flows to WriteFileNode.

### 4. Error Message Quality
The CLI provides helpful error messages at each stage:
- Missing registry → instructions to populate
- Invalid JSON → clear parsing errors
- Missing nodes → available nodes listed
- Validation errors → field paths and suggestions

## Task 3 Specific Requirements

### Minimal Workflow Example (Already Implemented)
The `hello_workflow.json` file already exists in the project root:
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "read",
      "type": "read-file",
      "params": {"file_path": "input.txt"}
    },
    {
      "id": "write",
      "type": "write-file",
      "params": {"file_path": "output.txt"}
    }
  ],
  "edges": [
    {"from": "read", "to": "write"}
  ]
}
```

### Current Behavior (Working)
1. `pflow --file hello_workflow.json` loads the workflow ✓
2. Validates JSON structure and node references ✓
3. Looks up "read-file" and "write-file" in registry ✓
4. Compiles to Flow object with proper wiring ✓
5. Executes: reads input.txt → adds line numbers → writes to output.txt ✓
6. Reports success with "Workflow executed successfully" ✓

### Test Requirements (Partially Implemented)
The `tests/test_e2e_workflow.py` file already exists with:
- Valid workflow execution ✓
- Missing registry handling ✓
- Invalid JSON handling ✓
- Validation error handling ✓

Still need to verify/add:
- Missing input file handling
- Shared store verification
- Mock nodes for isolated testing
- Retry behavior testing

## Success Criteria

1. **Integration Works**: All components connect properly ✓ (proven by working execution)
2. **Error Handling**: Clear messages at each failure point ✓ (basic implementation exists)
3. **Tests Pass**: E2E tests validate the full pipeline ✓ (4 tests passing)
4. **Documentation**: Clear examples for users (needs review)
5. **Foundation Solid**: Pattern established for future tasks ✓ (proven by commit dff02c3)

## Next Steps After Task 3

Once Task 3 is complete, it enables:
- Task 8: Shell pipe integration (stdin handling)
- Task 9: Proxy mapping for complex flows
- Task 12: LLM node integration
- Task 17: Natural language planner
- Task 22: Named workflow execution

Task 3 is the foundation that proves the architecture works end-to-end.
