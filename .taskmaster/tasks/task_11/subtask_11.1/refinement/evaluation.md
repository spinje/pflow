# Evaluation for Subtask 11.1

## Ambiguities Found

### 1. BaseNode vs Node Inheritance Choice - Severity: 3

**Description**: The main task description says "inherit from pocketflow.BaseNode" but the handoff memo and analysis suggest using "pocketflow.Node" for retry capabilities.

**Why this matters**: File operations can fail due to transient issues (file locks, temporary permission issues), so retry logic could be valuable.

**Options**:
- [x] **Option A: Use `Node` (with retry capabilities)**
  - Pros: Built-in retry logic for transient failures, more robust for file operations
  - Cons: Slightly more complex, may retry on permanent failures
  - Similar to: test_node_retry.py pattern

- [ ] **Option B: Use `BaseNode` (without retry)**
  - Pros: Simpler, follows main task description exactly
  - Cons: No automatic retry on transient failures
  - Similar to: test_node.py pattern

**Recommendation**: Option A - The handoff memo correctly identifies that file operations benefit from retry logic, and Node extends BaseNode so it satisfies the requirement.

### 2. Error Handling Strategy - Severity: 2

**Description**: Should nodes use the tuple pattern `(result, success_bool)` from Tutorial-Cursor or raise exceptions?

**Why this matters**: This affects how downstream nodes handle errors and the overall error propagation model.

**Options**:
- [x] **Option A: Use tuple pattern in exec(), convert to actions in post()**
  - Pros: Consistent with Tutorial-Cursor, explicit error handling, graceful degradation
  - Cons: More complex than exceptions
  - Similar to: Tutorial-Cursor file utilities

- [ ] **Option B: Raise exceptions and let PocketFlow handle them**
  - Pros: Simpler code, natural Python pattern
  - Cons: Less control over error messages
  - Risk: May not provide enough context for debugging

**Recommendation**: Option A - The tuple pattern provides better control and aligns with established cookbook patterns.

### 3. Line Numbers in read-file Output - Severity: 1

**Description**: Should read-file add line numbers to the output content?

**Why this matters**: Line numbers aid debugging but modify the original content.

**Options**:
- [x] **Option A: Add line numbers by default**
  - Pros: Helpful for debugging, matches Tutorial-Cursor pattern
  - Cons: Modifies original content
  - Similar to: Tutorial-Cursor display pattern

- [ ] **Option B: Return raw content, add line numbers as optional param**
  - Pros: Preserves original content
  - Cons: Less helpful for debugging by default

**Recommendation**: Option A - Line numbers are valuable for the primary use case of displaying files for analysis.

## Conflicts with Existing Code/Decisions

### 1. No Existing File Node Directory
- **Current state**: `src/pflow/nodes/file/` doesn't exist
- **Task assumes**: Directory structure will be created
- **Resolution needed**: None - will create as part of implementation

### 2. Import Path Pattern
- **Current state**: Test nodes use relative imports with sys.path manipulation
- **Task assumes**: Standard imports should work
- **Resolution needed**: Follow existing pattern from test_node.py

## Implementation Approaches Considered

### Approach 1: Tutorial-Cursor Pattern with Tuple Returns
- Description: Implement file operations returning (result, success) tuples
- Pros: Robust error handling, clear success/failure signaling, cookbook precedent
- Cons: More complex than simple exceptions
- Decision: **Selected** - Best balance of robustness and clarity

### Approach 2: Simple Exception-Based Pattern
- Description: Let Python file operations raise natural exceptions
- Pros: Simpler code, Pythonic
- Cons: Less control over error messages, harder to handle gracefully
- Decision: **Rejected** - Less flexible for workflow scenarios

### Approach 3: Hybrid with exec_fallback
- Description: Use exceptions but implement exec_fallback methods
- Pros: Clean code with fallback options
- Cons: More complex node implementation
- Decision: **Rejected** - Overly complex for MVP

## Additional Clarifications Needed

### 1. Encoding Parameter Support
The shared store pattern shows `shared["encoding"]` as optional. Should we:
- Support encoding parameter with UTF-8 default?
- Only support UTF-8 for MVP?

**Recommendation**: Support encoding parameter for flexibility, default to UTF-8.

### 2. File Path Validation
Should nodes validate paths (e.g., prevent directory traversal)?
- Current examples don't show security validation
- Could be important for production use

**Recommendation**: No path validation for MVP - document security considerations.

### 3. Binary File Support
Should read-file detect and handle binary files?
- Not mentioned in requirements
- Could fail on binary files with current UTF-8 approach

**Recommendation**: Text files only for MVP - document limitation.

## Test Strategy Decisions

Based on patterns from previous tasks:
1. Use tempfile for test file creation
2. Test success paths, missing files, permission errors
3. Test shared store and parameter inputs
4. Verify line number formatting
5. Test empty files and special characters
6. Include integration tests with real flows
