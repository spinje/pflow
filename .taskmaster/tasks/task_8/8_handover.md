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
The CLI ALREADY detects stdin with `not sys.stdin.isatty()` and reads it with `sys.stdin.read().strip()`. However, it treats stdin as **workflow input** (JSON/natural language), not as **data for nodes**.

**Your job**: Modify this to also populate `shared["stdin"]` when stdin contains data.

## 🎯 The Core Challenge

You need to **bridge two worlds**:

1. **Current behavior**: stdin = workflow definition
2. **New behavior**: stdin = data for workflow execution

The shell-pipes.md doc shows this vision:
```bash
cat data.txt | pflow process  # stdin contains DATA, not workflow
```

But we also need to preserve:
```bash
echo '{"ir_version": "0.1.0", ...}' | pflow  # stdin contains WORKFLOW
```

## 🚨 Architecture Insights You Must Know

### 1. The Shared Store is King
From Task 3's discovery: **Everything communicates through shared_storage dict**. Nodes read `shared["content"]`, `shared["file_path"]`, etc. The magic happens at **line 89** in main.py:

```python
shared_storage: dict[str, Any] = {}  # THIS is where you inject stdin
```

### 2. Reserved Key Pattern
The docs mention `shared["stdin"]` as a **reserved key**. This follows the established pattern:
- `shared["content"]` - file content with line numbers
- `shared["written"]` - write success messages
- `shared["stdin"]` - piped input (your addition)

### 3. Node Fallback Convention
From the docs: nodes should check `shared["stdin"]` if their primary input key isn't found. Example:
```python
def prep(self, shared):
    content = shared.get("content") or shared.get("stdin")
    if not content:
        raise ValueError("No content to process")
```

## 🔍 Current State Analysis

### What Already Exists (DO NOT REIMPLEMENT)
- ✅ stdin detection: `not sys.stdin.isatty()`
- ✅ stdin reading: `sys.stdin.read().strip()`
- ✅ Signal handling: `handle_sigint()` function (lines 18-22)
- ✅ Exit code propagation: proper `ctx.exit(1)` calls
- ✅ Error handling: comprehensive try/catch in execution
- ✅ Verbose mode: `--verbose` flag support

### What's Missing (YOUR WORK)
- ❌ Populating `shared["stdin"]` with piped data
- ❌ Streaming support for large inputs
- ❌ Intelligent workflow vs data detection
- ❌ stdout handling for node output

## 💡 Strategic Implementation Approach

### Phase 1: Minimal Viable Pipe Support
**Goal**: Make `cat data.txt | pflow some-workflow.json` work

1. **Modify the execution pipeline** (around line 89):
   ```python
   shared_storage: dict[str, Any] = {}

   # NEW: If we have stdin data AND we're executing a workflow, inject it
   if stdin_data and input_source != "stdin":  # workflow came from file/args
       shared_storage["stdin"] = stdin_data

   result = flow.run(shared_storage)
   ```

2. **Modify input detection logic** (lines 38-62):
   - Currently: stdin XOR workflow args
   - New: stdin AND workflow source (file/args)

### Phase 2: Smart Detection
**Goal**: Distinguish between `echo "workflow" | pflow` vs `cat data | pflow workflow`

Use heuristics:
- JSON with "ir_version" = workflow
- Everything else = data

### Phase 3: Streaming & Polish
- Chunk processing for large inputs
- stdout output for chaining
- Better error messages

## 🪨 Pitfalls to Avoid

### 1. Don't Break Current Behavior
The CLI currently works for:
- `pflow --file workflow.json`
- `pflow "natural language"`
- `echo workflow | pflow`

**Preserve all of these.** Only ADD pipe support.

### 2. The CliRunner Testing Trap
From Task 3's discovery: `click.testing.CliRunner` **cannot** test stdin behavior reliably. You'll need:
- Real subprocess tests: `subprocess.run(['pflow', ...], input=data)`
- Mock `sys.stdin.isatty()` for unit tests
- Integration tests with actual pipes

### 3. Shared Storage Assumptions
Don't assume nodes expect specific keys. The beauty of the shared store is **natural interfaces**. Let nodes decide what keys they check.

## 📁 Key Files to Understand

### Critical Reading (READ THESE FIRST)
- `src/pflow/cli/main.py` - Current CLI implementation (focus on lines 38-110)
- `docs/features/shell-pipes.md` - Complete specification of what you're building
- `docs/core-concepts/shared-store.md` - How data flows between nodes

### Reference for Patterns
- Simon Willison's `llm` CLI source code (mentioned in task description)
- Task 3 integration tests: `tests/test_integration/test_e2e_workflow.py`
- Error handling patterns from Task 3 discoveries

### Implementation Location
Create `src/pflow/core/shell_integration.py` per the task spec, but **the main integration happens in `main.py`**.

## 🎁 Task 3 Gift: Working Foundation

Task 3 solved these problems for you:
- ✅ Flow execution and error propagation
- ✅ Shared store communication between nodes
- ✅ Registry integration
- ✅ Comprehensive error handling
- ✅ Testing patterns for integration

**Your job is to extend this foundation, not rebuild it.**

## 🔬 Testing Strategy

### From Task 3's Learnings
- Use **direct flow execution** for shared store verification
- Create **custom test nodes** for behavior verification
- **Platform-specific tests** need conditional execution

### For Shell Integration
```python
# Test stdin population
flow = compile_ir_to_flow(workflow, registry)
shared_storage = {"stdin": "test data"}  # Simulate piped input
result = flow.run(shared_storage)
assert "stdin" in shared_storage
```

### Real Pipeline Tests
```bash
echo "test data" | python -m pflow.cli.main workflow.json
# Verify stdout contains expected output
```

## ⚡ Quick Wins

1. **Start with the happy path**: `shared_storage["stdin"] = stdin_data`
2. **Use existing error patterns**: Task 3 established all the error handling
3. **Leverage existing tests**: Copy integration test patterns from Task 3
4. **Follow the docs**: shell-pipes.md is comprehensive and well-thought-out

## 🚫 Scope Boundaries

**IN SCOPE** (MVP):
- Basic stdin detection and injection
- Exit code propagation (already works)
- Signal handling (already works)
- Simple streaming (read in chunks)

**OUT OF SCOPE** (Future):
- Complex workflow generation from piped data
- Advanced content type detection
- Interactive prompting for missing data
- Performance optimization

## 💪 Success Criteria

You'll know you're done when:
```bash
echo "Hello world" | pflow --file examples/process.json
# Populates shared["stdin"] with "Hello world"
# Workflow processes the piped data
# Output goes to stdout for chaining
```

The foundation is solid. Build on Task 3's work and you'll succeed. 🚀

---

**REMEMBER**: Read the existing code thoroughly, understand the current flow, then extend—don't rebuild.
