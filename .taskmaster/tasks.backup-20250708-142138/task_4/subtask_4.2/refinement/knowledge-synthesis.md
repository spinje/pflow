# Knowledge Synthesis for Subtask 4.2

## Relevant Patterns from Previous Tasks

### Context Manager for Dynamic Imports (Task 5.1)
- **Where it was used**: Scanner implementation for loading node modules
- **Why it's relevant**: We need to manage sys.path properly when importing nodes dynamically
- **Key insight**: Always restore sys.path even on errors using context manager pattern

### Structured Logging with Phases (Task 4.1)
- **Where it was used**: compile_ir_to_flow foundation
- **Why it's relevant**: We should continue using the same logging pattern with phase tracking
- **Example**: `logger.debug("Looking up node in registry", extra={"phase": "node_resolution"})`

### CompilationError with Rich Context (Task 4.1)
- **Where it was used**: Foundation error handling
- **Why it's relevant**: We must use the same error class with proper phase, node_id, node_type, details, suggestion
- **Example**: `CompilationError(phase="node_import", node_id="node1", node_type="read-file", details="Module not found")`

### Module Pattern with Clean Separation (Task 1)
- **Where it was used**: CLI module structure
- **Why it's relevant**: Keep import logic in compiler.py, not __init__.py
- **Benefit**: Clean separation of concerns

### Test with Mocks for Dynamic Imports (Task 5)
- **Where it was used**: Scanner tests for dangerous operations
- **Why it's relevant**: We should mock importlib to avoid real imports during testing
- **Pattern**: Use unittest.mock to simulate both success and failure cases

## Known Pitfalls to Avoid

### Assuming Registry Contains Class References (Task 4 project context)
- **Where it failed**: This is a conceptual pitfall noted in project context
- **How to avoid**: Always use registry metadata (module path + class name) with importlib
- **Registry provides**: `{"module": "pflow.nodes.file_nodes", "class_name": "ReadFileNode"}`

### Broad Exception Catching (Task 5)
- **Where it failed**: Scanner initially caught Exception too broadly
- **How to avoid**: Catch specific exceptions (ImportError, AttributeError) for better debugging
- **Our case**: Handle ImportError, AttributeError, and inheritance validation separately

### Not Verifying Inheritance (Task 5)
- **Where it failed**: Early scanner versions didn't verify BaseNode inheritance
- **How to avoid**: Always use issubclass() to verify the imported class inherits from BaseNode
- **Important**: Check for both BaseNode and Node (Node inherits from BaseNode)

## Established Conventions

### Error Namespace Convention (Task 2)
- **Where decided**: CLI error handling
- **Must follow**: Use "compiler:" prefix for all error messages
- **Example**: Error messages should start with "compiler: Failed to import..."

### Test Coverage Standards (Task 1)
- **Where decided**: Initial test setup
- **Must follow**: Aim for >90% coverage with meaningful tests
- **Our case**: Test all error paths, mock dangerous operations

### Import from pocketflow (Task 4 project context)
- **Where decided**: Architectural decision for direct pocketflow usage
- **Must follow**: Import BaseNode from pocketflow, not create wrappers
- **Code**: `from pocketflow import BaseNode`

## Codebase Evolution Context

### Registry Format Stabilized (Task 5)
- **What changed**: Registry format is now stable with metadata-only approach
- **When**: Task 5 completion
- **Impact on this task**: We can rely on consistent structure with module/class_name fields

### Foundation Layer Established (Task 4.1)
- **What changed**: CompilationError and helper functions now exist
- **When**: Just completed in subtask 4.1
- **Impact on this task**: We build on top of existing error handling and logging patterns

### Traditional Function Approach Confirmed (Task 4 project context)
- **What changed**: Decision to use traditional functions, not PocketFlow nodes for compiler
- **When**: Task 4 architectural decision
- **Impact on this task**: Continue with simple function implementation, no Node abstractions
