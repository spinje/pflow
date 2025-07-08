# Critical User Decisions for Task 8: Shell Pipe Integration

## 1. Streaming Architecture for Large Files - Importance: 4/5

The documentation mentions streaming support for large files but doesn't specify the implementation approach. This is critical for handling multi-GB log files without memory exhaustion.

### Options:

- [x] **Option A: Stream to Temporary File**
  - Write stdin to a temp file, store path in `shared["stdin_path"]` alongside raw content in `shared["stdin"]`
  - Pros: Simple, works with existing node patterns, allows multiple reads
  - Cons: Disk I/O overhead, requires cleanup, not true streaming
  - Implementation: Use tempfile.NamedTemporaryFile with automatic cleanup

- [ ] **Option B: True Streaming with Generators**
  - Implement a streaming reader that yields chunks, store generator in shared store
  - Pros: True streaming, minimal memory footprint
  - Cons: Complex implementation, breaks shared store serialization, nodes need special handling
  - Note: Likely incompatible with pocketflow's execution model

- [ ] **Option C: Chunked Processing in Nodes**
  - Store stdin normally but provide utilities for nodes to read in chunks
  - Pros: Backward compatible, opt-in for nodes that need it
  - Cons: Doesn't solve initial memory spike, requires node modifications

**Recommendation**: Option A - Use temporary files for large inputs. This maintains compatibility with the existing system while providing a practical solution. We can detect large inputs (>10MB) and automatically use temp files.

## 2. Binary vs Text Data Handling - Importance: 3/5

The current implementation uses `sys.stdin.read().strip()` which assumes text. Simon's llm uses `sys.stdin.buffer.read()` for binary attachments.

### Options:

- [x] **Option A: Auto-detect and Store Appropriately**
  - Try text decode first, fall back to binary if it fails
  - Store text as `shared["stdin"]` (string) or binary as `shared["stdin_binary"]` (bytes)
  - Pros: Handles both cases automatically, clear distinction in shared store
  - Cons: Two different keys to check, slight complexity

- [ ] **Option B: Always Store as Bytes**
  - Read as binary, let nodes decode as needed
  - Store in `shared["stdin"]` as bytes always
  - Pros: Consistent handling, nodes control decoding
  - Cons: Breaking change, most use cases expect text

- [ ] **Option C: Configuration Flag**
  - Add `--binary-stdin` flag to control behavior
  - Pros: Explicit control, no guessing
  - Cons: User needs to know data type in advance

**Recommendation**: Option A - Auto-detect with separate keys. This provides the best developer experience while maintaining clarity about data types.

## 3. Output Source for stdout - Importance: 3/5

When a workflow completes, what should be sent to stdout for pipe chaining?

### Options:

- [x] **Option A: Configurable Output Key**
  - Default to `shared["response"]` or `shared["output"]`
  - Allow `--output-key=xxx` to specify which shared store key to output
  - Pros: Flexible, works with any workflow, explicit control
  - Cons: Users need to know internal key names

- [ ] **Option B: Last Node's Output**
  - Automatically output whatever the last node produced
  - Pros: Intuitive for simple flows
  - Cons: Ambiguous for complex flows, what if last node produces multiple keys?

- [ ] **Option C: Explicit Output Node**
  - Require flows to use a special "output" node
  - Pros: Very explicit, no ambiguity
  - Cons: Adds complexity, breaks existing flows

**Recommendation**: Option A - Use configurable output key with smart defaults. Check for common keys like "response", "output", "result", "text" in that order.

## 4. Interactive vs Batch Mode - Importance: 2/5

The spec mentions both batch mode (fail fast) and interactive mode (prompt for missing data).

### Options:

- [x] **Option A: Batch Mode by Default**
  - Fail fast when stdin is detected (assumes non-interactive context)
  - Add `--interactive` flag for prompting behavior
  - Pros: Safe default for automation, explicit opt-in for interaction
  - Cons: None significant

- [ ] **Option B: Auto-detect Based on TTY**
  - Interactive when TTY detected, batch when piped
  - Pros: Automatic behavior
  - Cons: Can be surprising, harder to test

**Recommendation**: Option A - Default to batch mode with explicit `--interactive` flag. This follows Unix conventions and prevents hanging in automated scripts.

## Summary of Recommendations

1. **Streaming**: Use temporary files for large inputs (>10MB)
2. **Binary Data**: Auto-detect and use separate keys (`stdin` vs `stdin_binary`)
3. **Output**: Configurable key with smart defaults
4. **Mode**: Batch by default, `--interactive` flag for prompting

These decisions maintain backward compatibility while providing the flexibility needed for real-world usage.
