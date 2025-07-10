# Evaluation for 8.5

## Ambiguities Found

### 1. Output Key Detection Strategy - Severity: 3

**Description**: The task mentions checking for 'response', 'output', 'result', 'text' in order, but what if multiple keys exist? Should we output the first match or have a different strategy?

**Why this matters**: If a workflow sets both `shared["text"]` and `shared["response"]`, which one should be output? Wrong choice could output intermediate data instead of final result.

**Options**:
- [x] **Option A**: Output the first matching key in priority order
  - Pros: Simple, predictable, matches the task description
  - Cons: Might miss the "real" output if multiple keys exist
  - Similar to: Common Unix tools that use first match

- [ ] **Option B**: Output the last modified key
  - Pros: Likely to be the final result
  - Cons: Complex to track modification order
  - Risk: Requires significant changes to shared store

**Recommendation**: Option A - Simple and matches the specified behavior. Users can use --output-key for control.

### 2. Binary Output Handling - Severity: 4

**Description**: If the selected output key contains binary data (bytes), how should we handle it?

**Why this matters**: Binary data could corrupt terminal output or cause encoding errors. With stdin now supporting binary (from 8.4), nodes might produce binary output.

**Options**:
- [ ] **Option A**: Write binary directly to stdout.buffer
  - Pros: Preserves binary data integrity for piping
  - Cons: Could corrupt terminal display
  - Similar to: How `cat` handles binary files

- [x] **Option B**: Skip binary output with a warning to stderr
  - Pros: Safe, prevents terminal corruption
  - Cons: User might expect binary output
  - Risk: Silent data loss if user expects output

- [ ] **Option C**: Base64 encode binary data
  - Pros: Safe for terminal display
  - Cons: Not useful for piping, unexpected format
  - Risk: Breaks Unix pipe expectations

**Recommendation**: Option B for MVP - Skip binary with warning. Can add --binary flag in future.

### 3. Output Only When Piped - Severity: 3

**Description**: Should we output to stdout always, or only when stdout is piped (not a TTY)?

**Why this matters**: If we always output, it could interfere with the success message and clutter terminal. But silent behavior change based on TTY detection could be confusing.

**Options**:
- [x] **Option A**: Always output when key exists (remove success message)
  - Pros: Consistent behavior, predictable
  - Cons: No success confirmation in terminal
  - Similar to: Most Unix tools (echo, cat, etc.)

- [ ] **Option B**: Output only when piped, show success message when TTY
  - Pros: Clean terminal experience, good for piping
  - Cons: Different behavior based on context
  - Risk: User confusion about when output appears

**Recommendation**: Option A - Consistent behavior is more important than pretty terminal output.

### 4. Exit Code Source - Severity: 2

**Description**: How should nodes communicate non-zero exit codes? Current code only checks for "error" prefix in return value.

**Why this matters**: Nodes might need to signal different exit codes (not just 0 or 1) for shell script compatibility.

**Options**:
- [x] **Option A**: Keep current pattern (error prefix = exit 1)
  - Pros: No changes needed, backward compatible
  - Cons: Limited to binary success/failure
  - Similar to: Current implementation

- [ ] **Option B**: Add shared["exit_code"] convention
  - Pros: Flexible, nodes can set any exit code
  - Cons: New convention to document
  - Risk: Nodes might not set it

- [ ] **Option C**: Parse return value for "error:N" pattern
  - Pros: Backward compatible extension
  - Cons: Parsing complexity
  - Risk: Ambiguous format

**Recommendation**: Option A for MVP - Current pattern is sufficient. Can extend later if needed.

## Conflicts with Existing Code/Decisions

### 1. Success Message Conflict
- **Current state**: Line 256 prints "Workflow executed successfully"
- **Task assumes**: Stdout should contain only the output value for piping
- **Resolution needed**: Remove success message when outputting, or move to stderr

### 2. SIGPIPE Platform Issue
- **Current state**: No SIGPIPE handling
- **Task assumes**: Unix-style signal handling
- **Resolution needed**: Add platform check for Windows compatibility

## Implementation Approaches Considered

### Approach 1: Minimal MVP Implementation
- Description: Add --output-key option, output selected key, basic signal handling
- Pros: Simple, meets requirements, easy to test
- Cons: Limited flexibility
- Decision: **Selected** - Matches MVP scope

### Approach 2: Full Shell Integration Enhancement
- Description: Binary output support, format options, complex exit codes
- Pros: More powerful, handles all cases
- Cons: Over-engineering for MVP
- Decision: Rejected - Save for v2.0

### Approach 3: Automatic Output Detection Only
- Description: No --output-key option, just check default keys
- Pros: Even simpler
- Cons: Less user control
- Decision: Rejected - Task specifically mentions --output-key option
