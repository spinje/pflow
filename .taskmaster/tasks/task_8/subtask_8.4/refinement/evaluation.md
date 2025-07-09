# Evaluation for Subtask 8.4

## Ambiguities Found

### 1. Binary Detection Method - Severity: 4

**Description**: How should we detect if stdin contains binary data?

**Why this matters**: Wrong detection could corrupt binary data or fail to handle text properly

**Options**:
- [x] **Option A**: Check for null bytes in first 8KB sample
  - Pros: Fast, works for most binary formats, standard approach
  - Cons: Some text files might have null bytes (rare)
  - Similar to: Common Unix tools like `file` command

- [ ] **Option B**: Try UTF-8 decode and catch exception
  - Pros: Guaranteed to detect non-UTF8 data
  - Cons: Expensive for large files, misses valid UTF-8 binary data
  - Risk: Performance impact on large files

- [ ] **Option C**: Use magic bytes/file signatures
  - Pros: Most accurate for known formats
  - Cons: Complex, needs maintenance, misses unknown formats
  - Risk: Over-engineering for MVP

**Recommendation**: Option A because it's simple, fast, and follows Unix conventions. We can enhance later if needed.

### 2. Memory Threshold for Streaming - Severity: 3

**Description**: At what size should we switch from memory to temp file storage?

**Why this matters**: Too low wastes disk I/O, too high risks memory exhaustion

**Options**:
- [x] **Option A**: 10MB default with environment variable override
  - Pros: Reasonable default, configurable, matches common practice
  - Cons: Arbitrary number
  - Similar to: Many streaming tools use 10-50MB thresholds

- [ ] **Option B**: 100MB fixed threshold
  - Pros: Simple, handles most use cases
  - Cons: Not configurable, might be too high for low-memory systems
  - Risk: OOM on resource-constrained systems

- [ ] **Option C**: Dynamic based on available memory
  - Pros: Adaptive to system resources
  - Cons: Complex, non-deterministic behavior
  - Risk: Over-engineering for MVP

**Recommendation**: Option A because it provides a sensible default while allowing customization via `PFLOW_STDIN_MEMORY_LIMIT` env var.

### 3. Temp File Cleanup Strategy - Severity: 5

**Description**: How do we ensure temp files are always cleaned up?

**Why this matters**: Leaked temp files will accumulate and fill up disk space

**Options**:
- [x] **Option A**: Context manager with try/finally cleanup
  - Pros: Pythonic, handles exceptions well, explicit cleanup
  - Cons: Requires careful implementation
  - Similar to: Standard Python file handling patterns

- [ ] **Option B**: atexit handlers
  - Pros: Guaranteed cleanup on normal exit
  - Cons: Doesn't handle SIGKILL, complex with multiple files
  - Risk: Cleanup might not run on crashes

- [ ] **Option C**: OS auto-cleanup (tempfile defaults)
  - Pros: Simple, OS handles it
  - Cons: Platform-dependent, might leak on crashes
  - Risk: Unreliable cleanup

**Recommendation**: Option A with tempfile.NamedTemporaryFile(delete=False) and explicit cleanup in finally blocks.

### 4. Shared Store Key Design - Severity: 2

**Description**: How should we structure the shared store keys for different stdin types?

**Why this matters**: Poor design will complicate node implementations and break existing nodes

**Options**:
- [x] **Option A**: Multiple keys with type indicator
  - Keys: `stdin` (text), `stdin_binary` (bytes), `stdin_path` (temp file)
  - Pros: Clear separation, backward compatible, explicit types
  - Cons: Nodes need to check multiple keys
  - Similar to: Current pattern with single stdin key

- [ ] **Option B**: Single key with metadata object
  - Structure: `stdin = {"type": "text|binary|file", "data": ...}`
  - Pros: Single key to check, extensible
  - Cons: Breaks backward compatibility, complex for simple cases
  - Risk: All existing nodes would break

- [ ] **Option C**: Type prefix in key names
  - Keys: `stdin.text`, `stdin.binary`, `stdin.file`
  - Pros: Namespace-like organization
  - Cons: Non-standard Python dict key format
  - Risk: Confusing dot notation

**Recommendation**: Option A because it maintains backward compatibility and provides clear type separation.

## Conflicts with Existing Code/Decisions

### 1. UnicodeDecodeError Handling
- **Current state**: `read_stdin()` raises UnicodeDecodeError for non-UTF8
- **Task assumes**: We should handle binary data gracefully
- **Resolution needed**: Catch and handle decode errors for binary detection

### 2. Memory-Based Design
- **Current state**: Entire stdin loaded into memory at once
- **Task assumes**: Large files need streaming
- **Resolution needed**: Add streaming path while keeping simple path for small inputs

## Implementation Approaches Considered

### Approach 1: Minimal Enhancement to Existing Module
- Description: Add binary detection and streaming to existing functions
- Pros: Minimal code changes, easy to review
- Cons: Functions become more complex
- Decision: **Selected** - Maintains module cohesion

### Approach 2: Separate Streaming Module
- Description: Create new module for streaming functionality
- Pros: Clean separation of concerns
- Cons: Over-engineering for 2-3 functions
- Decision: **Rejected** - Too much structure for MVP

### Approach 3: Class-Based Stdin Handler
- Description: Create StdinHandler class with different strategies
- Pros: Extensible, clean OOP design
- Cons: Departure from current functional style
- Decision: **Rejected** - Inconsistent with existing patterns

## Critical Decisions Made

1. **Binary Detection**: Use null byte detection in first 8KB
2. **Memory Threshold**: 10MB default with env var override
3. **Cleanup Strategy**: Context managers with explicit cleanup
4. **Shared Store Keys**: Separate keys for backward compatibility
5. **Module Structure**: Enhance existing module, don't create new ones

These decisions prioritize simplicity, reliability, and backward compatibility while meeting the streaming requirements.
