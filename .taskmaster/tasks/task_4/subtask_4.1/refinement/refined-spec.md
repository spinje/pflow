# Refined Specification for Subtask 4.1

## Clear Objective
Create the foundation for the IR-to-PocketFlow compiler with robust IR loading, validation, and error handling infrastructure.

## Context from Knowledge Base
- Building on: Layered validation pattern from Task 6, error namespace convention from Task 2
- Avoiding: Over-engineering early (Task 5 lesson), missing error context
- Following: Module organization conventions, test-driven development pattern
- **No PocketFlow patterns needed**: This is foundation setup only, not orchestration

## Technical Specification

### Module Structure
```
src/pflow/runtime/
├── __init__.py          # Export compile_ir_to_flow
└── compiler.py          # Main implementation
```

### Main Function Signature
```python
def compile_ir_to_flow(ir_json: Union[str, dict], registry: Registry) -> Flow:
    """
    Compile JSON IR to executable pocketflow.Flow object.

    Args:
        ir_json: JSON string or dict representing the workflow IR
        registry: Registry instance for node metadata lookup

    Returns:
        Executable pocketflow.Flow object

    Raises:
        CompilationError: With rich context about what failed
    """
```

### CompilationError Class
```python
class CompilationError(Exception):
    """Error during IR compilation with rich context."""

    def __init__(self,
                 message: str,
                 phase: str = "unknown",
                 node_id: Optional[str] = None,
                 node_type: Optional[str] = None,
                 details: Optional[dict] = None,
                 suggestion: Optional[str] = None):
        self.phase = phase
        self.node_id = node_id
        self.node_type = node_type
        self.details = details or {}
        self.suggestion = suggestion

        # Build comprehensive error message
        parts = [f"compiler: {message}"]
        if phase != "unknown":
            parts.append(f"Phase: {phase}")
        if node_id:
            parts.append(f"Node ID: {node_id}")
        if node_type:
            parts.append(f"Node Type: {node_type}")
        if suggestion:
            parts.append(f"Suggestion: {suggestion}")

        super().__init__("\n".join(parts))
```

### Helper Functions
```python
def _parse_ir_input(ir_json: Union[str, dict]) -> dict:
    """Parse IR from string or pass through dict."""

def _validate_ir_structure(ir_dict: dict) -> None:
    """Validate basic IR structure (nodes, edges arrays)."""
```

### Logging Setup
```python
import logging

logger = logging.getLogger(__name__)

# In compile_ir_to_flow:
logger.debug("Starting IR compilation", extra={"phase": "init"})
logger.debug("IR structure validated", extra={"phase": "validation", "node_count": len(ir_dict["nodes"])})
```

## Success Criteria
- [x] Module created at src/pflow/runtime/compiler.py with proper imports
- [x] compile_ir_to_flow function accepts both string and dict inputs
- [x] CompilationError class includes all context attributes
- [x] Basic structure validation checks for 'nodes' and 'edges' keys
- [x] Structured logging configured and used
- [x] All tests in tests/test_compiler_foundation.py pass
- [x] Function raises appropriate errors with helpful messages
- [x] Clean separation between parsing and validation

## Test Strategy
- **File**: tests/test_compiler_foundation.py
- **Test valid inputs**: Both JSON strings and dicts
- **Test invalid inputs**:
  - Malformed JSON (JSONDecodeError)
  - Missing 'nodes' key
  - Missing 'edges' key
  - Invalid types for nodes/edges
- **Test CompilationError**:
  - Verify all attributes accessible
  - Check error message formatting
  - Test with/without optional fields
- **Test logging**:
  - Use caplog fixture to verify log messages
  - Check structured extra data
- **Mock compilation logic**: Since this is foundation only

## Dependencies
- Requires: Registry class from Task 5 (for type hints)
- Requires: pocketflow.Flow for return type hint
- Impacts: All future compiler subtasks will build on this foundation

## Decisions Made
- **Logging approach**: Python standard logging with structured extra data (User confirmed via evaluation)
- **Error structure**: Rich context with phase, node info, and suggestions (User confirmed via evaluation)
- **Directory creation**: Implementation will create src/pflow/runtime/ as needed (User confirmed via evaluation)
