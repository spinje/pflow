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
