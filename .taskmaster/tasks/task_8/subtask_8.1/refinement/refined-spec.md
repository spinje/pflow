# Refined Specification for Subtask 8.1

## Clear Objective
Create a standalone shell integration utility module that provides core functions for detecting, reading, and categorizing stdin input, enabling dual-mode stdin handling in pflow.

## Context from Knowledge Base
- Building on: CLI input handling patterns from Task 2, shared store patterns from Task 3/11
- Avoiding: Empty string handling pitfalls, CliRunner stdin detection quirks
- Following: Error namespace conventions, module organization patterns, test-as-you-go strategy
- **Cookbook patterns to apply**: None directly applicable - this is a utility module, not a PocketFlow node

## Technical Specification

### Module Location
`src/pflow/core/shell_integration.py`

### Inputs
- System stdin stream (detected via `sys.stdin.isatty()`)
- Text data only (UTF-8 encoded)
- Empty stdin treated as no input

### Outputs
Four core functions with specific signatures:

```python
def detect_stdin() -> bool:
    """Check if stdin is piped (not a TTY).

    Returns:
        True if stdin is piped, False if interactive terminal
    """

def read_stdin() -> str | None:
    """Read all stdin content if available.

    Returns:
        Content string if stdin has data, None if no stdin or empty

    Raises:
        UnicodeDecodeError: If stdin contains invalid UTF-8
    """

def determine_stdin_mode(content: str) -> str:
    """Determine if stdin contains workflow JSON or data.

    Args:
        content: The stdin content to analyze

    Returns:
        'workflow' if content is valid JSON with 'ir_version' key, 'data' otherwise
    """

def populate_shared_store(shared: dict, content: str) -> None:
    """Add stdin content to shared store.

    Args:
        shared: The shared store dictionary
        content: The stdin content to store

    Side Effects:
        Sets shared['stdin'] = content
    """
```

### Implementation Constraints
- Must use: `sys.stdin.isatty()` for detection, UTF-8 encoding
- Must avoid: Side effects on import, Click dependencies, binary handling
- Must maintain: Pythonic error handling (exceptions not return codes)

## Success Criteria
- [x] All four functions implemented with exact signatures
- [x] Empty stdin returns None (not empty string)
- [x] JSON workflow detection checks for 'ir_version' key
- [x] Module has no import side effects
- [x] Comprehensive tests pass
- [x] No dependencies beyond standard library
- [x] Type hints on all functions
- [x] Clear docstrings following project style

## Test Strategy
- Unit tests: Mock stdin with io.StringIO and patched isatty()
- Integration tests: None for this subtask (that's 8.2)
- Manual verification: Test with actual piped input in shell

### Test Cases
1. No stdin (interactive terminal) - returns appropriate values
2. Empty stdin (echo "" | ...) - returns None
3. Text stdin - reads correctly
4. Invalid UTF-8 - raises UnicodeDecodeError
5. Valid workflow JSON - detects as 'workflow'
6. Invalid JSON - detects as 'data'
7. JSON without ir_version - detects as 'data'

## Dependencies
- Requires: Python 3.9+ (for type union syntax)
- Impacts: Will be imported by CLI in subtask 8.2

## Decisions Made
- Module location: `src/pflow/core/` (per project context)
- Error handling: Raise exceptions (Pythonic approach)
- Empty stdin: Return None (per handoff memo)
- Encoding: UTF-8 only for this subtask
- No streaming: Simple read-all approach
- No binary support: Deferred to subtask 8.4

## Implementation Notes
1. The "validation trap" at lines 52-55 in main.py is not our concern in this subtask
2. Focus purely on utility functions - no CLI integration
3. Keep functions pure where possible (except populate_shared_store)
4. Ensure testability with dependency injection patterns

## Example Usage
```python
from pflow.core.shell_integration import read_stdin, determine_stdin_mode

content = read_stdin()
if content:
    mode = determine_stdin_mode(content)
    if mode == "data":
        shared["stdin"] = content
```
