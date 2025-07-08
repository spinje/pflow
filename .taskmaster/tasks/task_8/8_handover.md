# Task 8 Handoff Memo: Shell Pipe Integration

**TO THE IMPLEMENTING AGENT**: Read this entire memo before starting. When done, acknowledge you're ready to begin - DO NOT start implementing immediately.

## 🏗️ Your Solid Foundation: Completed Tasks

Before diving into shell integration, understand what's already built and working:

### ✅ Task 1: Package Setup & CLI Entry Point (DONE)
- **What it gives you**: Working `pflow` command, proper package structure
- **Your dependency**: CLI framework is ready, focus on extending not rebuilding

### ✅ Task 2: Basic CLI Argument Collection (DONE)
- **What it gives you**: Advanced input handling (stdin, file, args), Click framework
- **Critical insight**: CLI already detects stdin with `not sys.stdin.isatty()` - **BUILD ON THIS**

### ✅ Task 3: Workflow Execution Pipeline (DONE)
- **What it gives you**: Complete workflow execution from JSON → Registry → Compiler → Flow execution
- **Your dependency**: **THIS IS YOUR FOUNDATION** - the execution model you extend

### ✅ Task 5: Node Discovery & Registry (DONE)
- **What it gives you**: Working registry system, node scanning, persistent storage at `~/.pflow/registry.json`
- **Your dependency**: Registry integration already works, don't rebuild it

### ✅ Task 6: JSON IR Schema (DONE)
- **What it gives you**: Complete IR validation, schema definitions, error handling
- **Your dependency**: Workflow structure is defined and validated

### ✅ Task 4: IR-to-Flow Compiler (DONE)
- **What it gives you**: JSON workflows → PocketFlow object compilation
- **Your dependency**: Compilation pipeline is complete and tested

### ✅ Task 11: File Nodes (DONE)
- **What it gives you**: Working `read-file` and `write-file` nodes with shared store integration
- **Critical for testing**: Use these nodes to test your pipe integration

## 🔥 Critical Context from Task 3

Task 3 just completed the core workflow execution pipeline. **THIS IS YOUR FOUNDATION.** The execution model you need to build on:

### Working Execution Pipeline (src/pflow/cli/main.py:88-102)
```python
shared_storage: dict[str, Any] = {}  # Empty dict
result = flow.run(shared_storage)    # Execute workflow
if result and isinstance(result, str) and result.startswith("error"):
    # Handle failure
else:
    # Success
```

**Key insight**: The CLI creates an empty `shared_storage` dict and passes it to `flow.run()`. **This is where you inject stdin content.**

### Current stdin Detection (lines 48-56)
The CLI ALREADY detects stdin with `not sys.stdin.isatty()` and reads it with `sys.stdin.read().strip()`. Currently, it treats stdin as **workflow input** (JSON/natural language) only.

**Important**: Lines 52-55 contain validation that prevents using stdin when command arguments are provided. This needs to be modified to support the new use case.

## 🎯 The Core Challenge

You need to enable **two distinct stdin behaviors**:

1. **Workflow mode** (current): stdin contains workflow definition
   ```bash
   echo '{"ir_version": "0.1.0", ...}' | pflow  # stdin = workflow JSON
   ```

2. **Data mode** (new): stdin contains data for workflow execution
   ```bash
   cat data.txt | pflow --file workflow.json  # stdin = data, workflow from file
   ```

## 🚨 Critical Design Decisions

### 1. stdin + Arguments Validation
**Current**: The CLI rejects stdin when command arguments are provided (lines 52-55)
**Recommendation**: Modify this validation to allow stdin data when workflow comes from `--file`

```python
# Current validation prevents: cat data | pflow workflow.json
# Modify to allow: cat data | pflow --file workflow.json
```

### 2. Workflow vs Data Detection
**Clear detection rules**:
- If `--file` is provided → stdin is data (if present)
- If no `--file` and stdin contains valid JSON with `"ir_version"` → stdin is workflow
- If no `--file` and stdin contains other content → ERROR (ambiguous)
- If command args provided → stdin must be data (not workflow)

### 3. Implementation Architecture
**Module responsibilities**:
- `src/pflow/core/shell_integration.py`: Core utilities for stdin/stdout handling
  - `detect_stdin()`: Check if stdin is piped
  - `read_stdin()`: Read stdin content (with streaming support)
  - `setup_signal_handlers()`: Signal handling setup
- `src/pflow/cli/main.py`: Integration logic
  - Modify `get_input_source()` to handle dual-mode stdin
  - Inject stdin data into shared_storage before flow execution

### 4. MVP Scope Clarification
**IN SCOPE**:
- Basic stdin detection and injection into `shared["stdin"]`
- Support for `cat data | pflow --file workflow.json`
- Exit code propagation (already works)
- Signal handling (already works via `handle_sigint`)
- Basic streaming (read stdin in chunks for large files)

**OUT OF SCOPE** (for MVP):
- Interactive prompting for missing data
- Natural language workflow with piped data
- Complex content type detection
- stdout handling for node output (future enhancement)

## 🔍 Current State Analysis

### What Already Exists (DO NOT REIMPLEMENT)
- ✅ stdin detection: `not sys.stdin.isatty()`
- ✅ stdin reading: `sys.stdin.read().strip()`
- ✅ Signal handling: `handle_sigint()` function (lines 18-22)
- ✅ Exit code propagation: proper `ctx.exit(1)` calls
- ✅ Error handling: comprehensive try/catch in execution

### What's Missing (YOUR WORK)
- ❌ Dual-mode stdin handling (workflow vs data)
- ❌ Populating `shared["stdin"]` with piped data
- ❌ Streaming support for large inputs
- ❌ Modified validation logic

## 💡 Strategic Implementation Approach

### Phase 1: Enable Basic Data Piping
**Goal**: Make `cat data.txt | pflow --file workflow.json` work

1. **Modify validation in `get_input_source()`**:
   ```python
   # Allow stdin when --file is provided
   if workflow and not file:  # Only reject if no --file
       raise click.ClickException(...)
   ```

2. **Detect stdin mode**:
   ```python
   # In get_input_source or new helper
   if file and not sys.stdin.isatty():
       # stdin contains data for the workflow
       stdin_data = sys.stdin.read().strip()
       # Return this separately or store in context
   ```

3. **Inject stdin data** (around line 89):
   ```python
   shared_storage: dict[str, Any] = {}

   # NEW: If we have stdin data, inject it
   if ctx.obj.get("stdin_data"):
       shared_storage["stdin"] = ctx.obj["stdin_data"]

   result = flow.run(shared_storage)
   ```

### Phase 2: Add Streaming Support
Implement in `shell_integration.py`:
```python
def read_stdin_stream(chunk_size=8192):
    """Read stdin in chunks for large files."""
    chunks = []
    while True:
        chunk = sys.stdin.buffer.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
    return b''.join(chunks).decode('utf-8')
```

## 🚨 Architecture Insights You Must Know

### 1. The Shared Store is King
From Task 3's discovery: **Everything communicates through shared_storage dict**. The magic happens at **line 89** in main.py where you can inject stdin data.

### 2. Reserved Key Pattern
The docs specify `shared["stdin"]` as a **reserved key**. This follows the established pattern:
- `shared["content"]` - file content
- `shared["stdin"]` - piped input (your addition)

### 3. Node Conventions
Nodes should check `shared["stdin"]` as a fallback if their primary input isn't found:
```python
def prep(self, shared):
    content = shared.get("content") or shared.get("stdin")
    if not content:
        raise ValueError("No content to process")
```

## 📁 Key Files to Understand

### Critical Reading (READ THESE FIRST)
- `src/pflow/cli/main.py` - Current CLI implementation (focus on lines 38-110)
- `docs/features/shell-pipes.md` - Complete specification
- `docs/core-concepts/shared-store.md` - How data flows between nodes

### Reference for Patterns
- Task 3 integration tests: `tests/test_integration/test_e2e_workflow.py`
- File nodes for testing: `src/pflow/nodes/file/*.py`

## 🔬 Testing Strategy

### Unit Tests with Mocks
For `shell_integration.py` functions:
```python
def test_detect_stdin(monkeypatch):
    # Mock isatty() to return False (piped)
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert detect_stdin() is True
```

### Integration Tests with Subprocess
For end-to-end behavior:
```python
def test_piped_data_workflow():
    # Use subprocess to test real pipe behavior
    result = subprocess.run(
        ['pflow', '--file', 'test_workflow.json'],
        input='test data',
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
```

### Shared Store Verification
```python
# Test that stdin data is properly injected
flow = compile_ir_to_flow(workflow, registry)
shared_storage = {"stdin": "test data"}
result = flow.run(shared_storage)
# Verify nodes can access stdin data
```

## ⚡ Quick Wins

1. **Start with --file mode**: Get `cat data | pflow --file workflow.json` working first
2. **Use existing patterns**: Copy error handling from Task 3
3. **Keep it simple**: Basic stdin injection before streaming
4. **Test with file nodes**: They already work with shared store

## 💪 Success Criteria

You'll know you're done when:
```bash
# Basic data piping works
echo "Hello world" | pflow --file examples/echo-stdin.json
# Outputs: "Hello world" (from a workflow that reads stdin)

# Large file streaming works
cat large_file.txt | pflow --file process.json
# Processes without loading entire file into memory

# Exit codes work
echo "test" | pflow --file failing-workflow.json || echo "Failed correctly"
# Shows "Failed correctly" when workflow fails
```

## 🎁 Example Test Workflow

Create this for testing (`examples/echo-stdin.json`):
```json
{
    "ir_version": "0.1.0",
    "id": "echo-stdin",
    "description": "Echo stdin content",
    "nodes": [
        {
            "id": "echo",
            "type": "write-file",
            "params": {
                "file_path": "/dev/stdout"
            }
        }
    ],
    "edges": [],
    "start_node": "echo"
}
```

This workflow will read from `shared["stdin"]` (via write-file's fallback to stdin) and output to stdout.

The foundation is solid. Build on Task 3's work and you'll succeed. 🚀

---

**REMEMBER**: Read the existing code thoroughly, understand the current flow, then extend—don't rebuild.


---

Decision document:

# Critical User Decisions: Task 8 Shell Pipe Integration Ambiguities

This document outlines critical ambiguities and inconsistencies found in the Task 8 handover document that require user decisions before implementation can proceed.

## 1. stdin Behavior Conflict - Importance: 5/5 ⚠️

The handover describes supporting `cat data.txt | pflow some-workflow.json` but the current CLI explicitly prevents this pattern.

**Current CLI validation (lines 52-55 in main.py):**
```python
if workflow:
    raise click.ClickException(
        "cli: Cannot use stdin input when command arguments are provided..."
    )
```

**Handover suggestion (lines 124-129):**
```python
if stdin_data and input_source != "stdin":  # workflow came from file/args
    shared_storage["stdin"] = stdin_data
```

### Options:

- [x] **Option A: Remove the validation that prevents stdin + args combination**
  - Allows patterns like `cat data | pflow --file workflow.json`
  - Enables piping data into workflows specified by file or name
  - More flexible and aligns with Unix philosophy
  - Requires careful detection of workflow vs data mode

- [ ] **Option B: Keep current validation, change the design**
  - Only support patterns like `echo workflow | pflow` (stdin as workflow)
  - Simpler implementation but less useful
  - Would need different approach for data piping

**Recommendation**: Option A - This enables the core value proposition of shell pipe integration.

## 2. Implementation Location - Importance: 4/5

Where should different parts of the shell integration be implemented?

### Options:

- [x] **Option A: Hybrid approach**
  - `shell_integration.py`: Core functions (detect_stdin, read_stdin, stream_stdin)
  - `main.py`: Integration logic (populating shared["stdin"], modifying input detection)
  - Clear separation of concerns

- [ ] **Option B: Everything in shell_integration.py**
  - All stdin handling in one module
  - Requires passing CLI context to shell module
  - Less clear integration with existing CLI flow

**Recommendation**: Option A - Keeps shell utilities separate while integrating at the appropriate layer.

## 3. Data vs Workflow Detection - Importance: 5/5 ⚠️

How to distinguish between stdin containing workflow definition vs data?

### Options:

- [x] **Option A: Content-based heuristics**
  - If JSON with "ir_version" field → workflow
  - If starts with "pflow" or contains "=>" → CLI syntax workflow
  - Everything else → data for nodes
  - Simple and covers most cases

- [ ] **Option B: Explicit mode flag**
  - Add `--stdin-mode=data|workflow` flag
  - More explicit but less convenient
  - Breaks Unix pipe simplicity

- [ ] **Option C: Context-based detection**
  - If workflow specified via --file or args → stdin is data
  - If no workflow specified → stdin is workflow
  - Most intuitive behavior

**Recommendation**: Option C with Option A as fallback - This provides the most natural Unix-like behavior.

## 4. Interactive Mode Scope - Importance: 3/5

Should interactive prompting for missing data be included in MVP?

### Options:

- [ ] **Option A: Include interactive mode**
  - Prompt for missing required inputs
  - Better user experience
  - More complex implementation

- [x] **Option B: Batch mode only (fail fast)**
  - Missing inputs cause immediate failure with clear error
  - Simpler MVP implementation
  - Interactive mode can be added later

**Recommendation**: Option B - Keep MVP simple, add interactivity in v2.0.

## 5. Testing Strategy - Importance: 4/5

The handover gives conflicting testing advice.

### Options:

- [x] **Option A: Layered testing approach**
  - Unit tests: Mock sys.stdin with pytest fixtures
  - Integration tests: Use subprocess for real pipe behavior
  - Best of both worlds

- [ ] **Option B: Subprocess only**
  - All tests use real processes
  - More realistic but slower and harder to debug

**Recommendation**: Option A - Use appropriate testing method for each layer.

## 6. stdout Handling Design - Importance: 3/5

How should nodes write output to stdout for pipeline chaining?

### Options:

- [x] **Option A: Explicit stdout key in shared store**
  - Nodes write to `shared["stdout"]`
  - CLI checks this key and outputs to stdout after execution
  - Clear and controllable

- [ ] **Option B: Direct stdout writing by nodes**
  - Nodes use print() or sys.stdout.write()
  - Simpler but less controlled
  - Harder to test and trace

**Recommendation**: Option A - Maintains separation of concerns and testability.

## 7. Workflow Invocation Pattern - Importance: 4/5

What patterns should be supported for combining piped data with workflows?

### Options:

- [x] **Option A: Support multiple patterns**
  - `cat data | pflow --file workflow.json`
  - `cat data | pflow workflow-name`
  - `cat data | pflow "natural language"`
  - Maximum flexibility

- [ ] **Option B: Single pattern only**
  - Only support `cat data | pflow --file workflow.json`
  - Simpler but less useful

**Recommendation**: Option A - Support all reasonable patterns for better UX.

## Summary of Recommendations

1. **Remove stdin + args validation** to enable piping data into workflows
2. **Use hybrid implementation** with core functions in shell_integration.py
3. **Context-based detection** for workflow vs data mode
4. **Batch mode only** for MVP (no interactive prompts)
5. **Layered testing** with both mocks and subprocess tests
6. **Explicit stdout handling** via shared["stdout"]
7. **Support multiple invocation patterns** for flexibility

These decisions will enable a clean, Unix-friendly implementation that delivers the core value of shell pipe integration while keeping the MVP scope manageable.
