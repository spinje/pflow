# Implementation Briefing for Subtask 4.1: Compiler Foundation

## Critical Architecture Decision: Traditional Function Implementation (Option A)
**Important**: We are using a traditional function-based approach, NOT PocketFlow orchestration. This was a deliberate decision - the compiler is a simple transformation function that doesn't need the complexity of PocketFlow nodes and flows.

## Your Mission
Create the foundation for the IR-to-PocketFlow compiler using a straightforward function-based approach. This is pure setup - no actual compilation logic yet.

## Essential Reading (in order)
1. `/Users/andfal/projects/pflow/.taskmaster/tasks/task_4/subtask_4.1/refinement/refined-spec.md` - Your complete specification
2. `/Users/andfal/projects/pflow/src/pflow/core/ir_schema.py` - See the IR structure you'll be loading
3. `/Users/andfal/projects/pflow/src/pflow/registry/__init__.py` - Understand Registry class for type hints

## What to Build

### 1. Module Structure
```
src/pflow/runtime/
├── __init__.py          # Must export: from .compiler import compile_ir_to_flow
└── compiler.py          # Your main work goes here
```

### 2. Core Function (Traditional Implementation)
```python
def compile_ir_to_flow(ir_json: Union[str, dict], registry: Registry) -> Flow:
    """
    Compile JSON IR to executable pocketflow.Flow object.

    Note: This is a traditional function implementation, not a PocketFlow-based
    compiler. We transform IR → Flow objects directly.
    """
    # For now, just:
    # 1. Parse input (string → dict)
    # 2. Validate structure
    # 3. Log steps
    # 4. Raise NotImplementedError("Compilation not yet implemented")
```

### 3. CompilationError Class
```python
class CompilationError(Exception):
    def __init__(self, message: str, phase: str = "unknown",
                 node_id: Optional[str] = None, node_type: Optional[str] = None,
                 details: Optional[dict] = None, suggestion: Optional[str] = None):
        # Store ALL attributes
        # Build error message with "compiler:" prefix
        # Include all context in message
```

### 4. Helper Functions
```python
def _parse_ir_input(ir_json: Union[str, dict]) -> dict:
    """Handle both JSON strings and dicts."""

def _validate_ir_structure(ir_dict: dict) -> None:
    """Check 'nodes' and 'edges' exist and are lists."""
```

### 5. Logging
```python
import logging
logger = logging.getLogger(__name__)

# Use like:
logger.debug("Starting IR compilation", extra={"phase": "init"})
```

## Critical Implementation Details

### Must Have:
- Accept BOTH string and dict inputs
- Check that 'nodes' key exists and is a list
- Check that 'edges' key exists and is a list
- Use "compiler:" prefix in error messages
- Include phase in all log messages
- Create the runtime directory if needed

### Must NOT Have:
- Any actual compilation logic
- Any node imports or instantiation
- Any PocketFlow Flow construction
- Complex validation beyond basic structure

### Error Handling Examples:
```python
# Bad JSON
if isinstance(ir_json, str):
    try:
        ir_dict = json.loads(ir_json)
    except json.JSONDecodeError as e:
        raise CompilationError(
            f"Invalid JSON: {e}",
            phase="parsing",
            suggestion="Check JSON syntax"
        )

# Missing keys
if "nodes" not in ir_dict:
    raise CompilationError(
        "Missing 'nodes' key in IR",
        phase="validation",
        suggestion="IR must contain 'nodes' array"
    )
```

## Test Requirements

Create `tests/test_compiler_foundation.py`:

### Test Cases:
1. Test both string and dict inputs work
2. Test malformed JSON raises JSONDecodeError (let it bubble up)
3. Test missing 'nodes' raises CompilationError
4. Test missing 'edges' raises CompilationError
5. Test CompilationError has all attributes
6. Test logging output (use pytest's caplog)
7. Test that compile_ir_to_flow raises NotImplementedError at the end

### Example Test:
```python
def test_compile_ir_string_input():
    registry = MagicMock()  # Don't need real registry yet
    ir_string = '{"nodes": [], "edges": []}'

    with pytest.raises(NotImplementedError):
        compile_ir_to_flow(ir_string, registry)
```

## Patterns to Follow

### From Previous Tasks:
- **Module pattern (Task 1)**: Separate __init__.py and implementation file
- **Error pattern (Task 2)**: "module:" prefix for errors
- **Test pattern (All tasks)**: Create tests alongside implementation
- **Validation pattern (Task 6)**: Helper functions for validation steps

### What NOT to Do:
- Don't over-engineer (Task 5 lesson)
- Don't create fixtures yet
- Don't worry about performance
- Don't add features not in spec
- Don't use PocketFlow for the compiler itself (we're using Option A: Traditional Function)

## Quick Checklist

Before marking complete:
- [ ] src/pflow/runtime/compiler.py exists with all functions
- [ ] CompilationError class has ALL specified attributes
- [ ] Both string and dict inputs handled
- [ ] Basic structure validation works
- [ ] Logging is structured with extra data
- [ ] tests/test_compiler_foundation.py has good coverage
- [ ] All tests pass
- [ ] Function ends with NotImplementedError

## Final Note
This is foundation only. You're setting up the structure for subtasks 4.2-4.4 to build upon. Keep it simple, clean, and well-tested. The actual compilation magic comes later.
