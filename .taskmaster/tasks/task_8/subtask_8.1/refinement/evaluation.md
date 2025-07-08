# Evaluation for Subtask 8.1

## Ambiguities Found

### 1. Module Location - Severity: 2

**Description**: Should shell_integration.py be in `src/pflow/core/` or `src/pflow/cli/`?

**Why this matters**: Module organization affects import paths and conceptual clarity.

**Options**:
- [x] **Option A**: Place in `src/pflow/core/shell_integration.py`
  - Pros: Indicates it's a core utility, not CLI-specific
  - Cons: Creates new `core/` directory
  - Similar to: IR schema is in `core/`

- [ ] **Option B**: Place in `src/pflow/cli/shell_integration.py`
  - Pros: Shell integration is primarily used by CLI
  - Cons: Might be needed by other components later
  - Risk: Limits reusability

**Recommendation**: Option A - The handoff memo and project context both specify `src/pflow/core/shell_integration.py`. This also aligns with the module being a foundational utility.

### 2. Error Handling Approach - Severity: 3

**Description**: How should the module handle errors (exceptions vs return values)?

**Why this matters**: Affects how CLI integrates with the module and error propagation.

**Options**:
- [x] **Option A**: Raise exceptions for errors
  - Pros: Pythonic, clear error types, stack traces preserved
  - Cons: Caller must handle exceptions
  - Similar to: File nodes raise exceptions in exec()

- [ ] **Option B**: Return None or error values
  - Pros: No exception handling needed by caller
  - Cons: Less information about errors, not Pythonic
  - Risk: Silent failures possible

**Recommendation**: Option A - Follow Python conventions and existing patterns. Raise specific exceptions with clear messages.

### 3. Empty stdin Handling - Severity: 4

**Description**: How to handle empty stdin (piped but no content)?

**Why this matters**: CliRunner and real shells behave differently. Empty stdin could mean "no data" or could be intentional empty input.

**Options**:
- [x] **Option A**: Return None for empty stdin (treat as no input)
  - Pros: Simplifies downstream logic, matches handoff guidance
  - Cons: Can't distinguish between no stdin and empty stdin
  - Similar to: Current CLI behavior

- [ ] **Option B**: Return empty string for empty stdin
  - Pros: Preserves the distinction
  - Cons: Complicates downstream handling
  - Risk: Nodes might misinterpret empty string

**Recommendation**: Option A - The handoff memo explicitly states to return None for empty stdin. This simplifies integration.

## Conflicts with Existing Code/Decisions

### 1. stdin Usage Conflict

- **Current state**: stdin is used exclusively for workflow input (lines 52-55 validate against this)
- **Task assumes**: stdin should also carry data for workflows
- **Resolution needed**: This is already resolved in project context - dual-mode handling is the solution

### 2. Encoding Assumption

- **Current state**: CLI uses `sys.stdin.read().strip()` (assumes text)
- **Task assumes**: Need to handle both text and binary
- **Resolution needed**: For this subtask, focus on text only. Binary support comes in subtask 8.4

## Implementation Approaches Considered

### Approach 1: Minimal Text-Only Implementation

- Description: Implement only the four core functions with text support
- Pros: Simple, focused, meets subtask requirements exactly
- Cons: No streaming, no binary support
- Decision: **Selected** - This matches the subtask scope perfectly

### Approach 2: Include Basic Streaming

- Description: Add generator-based streaming from the start
- Pros: More complete solution
- Cons: Beyond subtask scope, adds complexity
- Decision: **Rejected** - Streaming is for subtask 8.4

### Approach 3: Full Signal Handling

- Description: Include SIGINT and SIGPIPE handlers
- Pros: More robust
- Cons: Signal handling might interfere with CLI
- Decision: **Rejected** - Signal handling is beyond this subtask's scope

## Design Decisions Made

1. **Text-only for now**: Binary support explicitly deferred to subtask 8.4
2. **No streaming yet**: Simple read-all approach for this subtask
3. **Return None for empty stdin**: Simplifies downstream logic
4. **Raise exceptions for errors**: Pythonic and informative
5. **UTF-8 encoding with error handling**: Handle decode errors gracefully
6. **No side effects on import**: All functions must be explicitly called

## Module API Design

```python
def detect_stdin() -> bool:
    """Check if stdin is piped (not a TTY)."""

def read_stdin() -> str | None:
    """Read all stdin content if available. Returns None if no stdin or empty."""

def determine_stdin_mode(content: str) -> str:
    """Determine if stdin contains workflow JSON or data. Returns 'workflow' or 'data'."""

def populate_shared_store(shared: dict, content: str) -> None:
    """Add stdin content to shared store at shared['stdin']."""
```

## Test Requirements

1. Test with real stdin using subprocess
2. Test with mocked stdin using io.StringIO
3. Test empty stdin behavior
4. Test JSON detection for workflow mode
5. Test various text encodings
6. Test error cases (decode errors, etc.)

All ambiguities have been resolved based on the handoff memo and project context.
