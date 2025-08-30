# CLI Integration Context for Named Workflow Execution

This document provides essential implementation context for Task 22 (Implement named workflow execution) based on deep understanding of the current CLI architecture and shell integration implementation.

## Current CLI Architecture

### Workflow Input Processing Flow

The current CLI processes workflow input through three possible sources, determined by `get_input_source()` (lines 150-181 in `src/pflow/cli/main.py`):

1. **File source** (`--file` option): `read_workflow_from_file()` reads from disk
2. **Stdin source**: When stdin contains valid workflow JSON
3. **Args source**: Command-line arguments (currently just collected, not processed)

```python
# Line 443 in main():
raw_input, source, stdin_data = get_input_source(file, workflow)
```

### Execution Flow

The complete flow from CLI entry to workflow execution:

1. **main()** (line 376) - Entry point
2. **get_input_source()** (line 150) - Determines workflow source
3. **process_file_workflow()** (line 324) - Handles JSON parsing
4. **execute_json_workflow()** (line 249) - Validates and executes
5. **flow.run(shared_storage)** (line 295) - Actual execution

### Key Integration Points for Named Workflows

Named workflows would integrate at line 463-469 where source routing happens:

```python
# Current implementation (line 463):
if source in ("file", "stdin"):
    process_file_workflow(ctx, raw_input, stdin_data)
else:
    # This is where named workflow handling would go
    click.echo(f"Collected workflow from {source}: {raw_input}")
```

## Specific Code References

### Critical Functions and Their Roles

1. **`_determine_workflow_content()`** (lines 89-107)
   - Currently returns workflow content based on source
   - Named workflows would need new branch here

2. **`process_file_workflow()`** (lines 324-359)
   - Parses JSON and calls `execute_json_workflow()`
   - Could be reused for named workflows after loading from disk

3. **`execute_json_workflow()`** (lines 249-322)
   - Takes parsed IR data dictionary
   - Already accepts `output_key` parameter (line 253)
   - Handles all validation, compilation, and execution

### Shared Storage Initialization

Shared storage is created at line 289:
```python
shared_storage: dict[str, Any] = {}
```

Stdin data injection happens at line 292:
```python
_inject_stdin_data(shared_storage, stdin_data, verbose)
```

## Context Object Structure

The Click context object (`ctx.obj`) stores (lines 456-460):

```python
ctx.obj["raw_input"] = raw_input      # Original workflow content
ctx.obj["input_source"] = source      # "file", "stdin", or "args"
ctx.obj["stdin_data"] = stdin_data    # Piped data (str or StdinData)
ctx.obj["verbose"] = verbose          # Verbose flag
ctx.obj["output_key"] = output_key    # Output key for stdout
```

Named workflows would need to add:
- Workflow name
- Runtime parameters
- Potentially workflow metadata (description, author, etc.)

## Template Variable Implementation

According to `architecture/reference/cli-reference.md` (lines 130-145), template variables use `$variable` syntax:

### Resolution Order
1. Check shared store for key
2. Check environment variables
3. Error if not found

### Example Usage
```bash
pflow llm --prompt="Summarize this: $content"
```

For named workflows with parameters:
```bash
pflow fix-issue --issue=1234
# Would populate shared["issue"] = "1234" before template resolution
```

## File System Conventions

### Expected Workflow Storage Location

Task 22 description specifies: `~/.pflow/workflows/<name>.json`

This aligns with the pattern from lockfile storage which uses `~/.pflow/lockfiles/`.

### Workflow File Structure

Based on current IR validation (line 277), workflows must have:
- `ir_version` (semantic version like "0.1.0")
- `nodes` array (at least one node)
- `edges` array (can be empty)
- Optional: `start_node`, `description`, `metadata`

### Registry Integration

Registry is loaded at line 269:
```python
registry = Registry()
if not registry.registry_path.exists():
    # Error handling
```

Named workflows need the same registry for node resolution.

## Integration Considerations

### 1. Source Detection Enhancement

Modify `get_input_source()` to detect named workflow pattern:
```python
# Pseudo-code for detection
if workflow and workflow[0] doesn't contain "=>":
    # Could be named workflow
    return workflow[0], "named", stdin_data
```

### 2. Parameter Passing Pattern

Current `--output-key` pattern (line 374) shows how to add workflow-specific options:
```python
@click.option("--output-key", "-o", "output_key", help="...")
```

Named workflows need dynamic parameter collection.

### 3. Output Key Handling

Output handling already works through `_handle_workflow_output()` (line 214-231):
- Checks for specified key or auto-detects
- Works with any workflow that populates shared store

### 4. Error Message Requirements

Current error patterns to follow:
- File not found: Lines 62-66 show proper error formatting
- Invalid JSON: Line 337-339
- Validation errors: Lines 341-346
- Missing registry: Lines 271-274

All use `click.echo(..., err=True)` for stderr output.

### 5. Stdin Data Compatibility

Named workflows must support stdin data injection:
- Text stdin goes to `shared["stdin"]`
- Binary stdin goes to `shared["stdin_binary"]`
- Large files go to `shared["stdin_path"]`

This happens automatically through `_inject_stdin_data()`.

## Implementation Hooks

### Where to Add Named Workflow Loading

The cleanest integration point is in the main routing logic (line 463):

```python
if source in ("file", "stdin"):
    process_file_workflow(ctx, raw_input, stdin_data)
elif source == "named":  # New branch
    process_named_workflow(ctx, workflow_name, params, stdin_data)
else:
    # Current args handling
```

### Reusing Existing Infrastructure

After loading the workflow JSON from disk, can reuse:
1. `execute_json_workflow()` - Handles all execution logic
2. `_inject_stdin_data()` - Handles stdin injection
3. `_handle_workflow_output()` - Handles output selection

### Parameter Injection Timing

Parameters should be injected into shared storage after stdin but before execution:
1. Create shared storage (line 289)
2. Inject stdin data (line 292)
3. **Inject named workflow parameters** (new)
4. Execute workflow (line 295)

## Useful Patterns from Shell Integration

### Reserved Shared Store Keys

From shell integration implementation:
- `stdin`, `stdin_binary`, `stdin_path` - Reserved for piped input
- `response`, `output`, `result`, `text` - Common output keys

Named workflow parameters should avoid these keys.

### Exit Code Handling

Current pattern (lines 298-301) checks for "error" prefix in result.
Named workflows should maintain this convention.

## Summary

The current CLI architecture is well-structured for adding named workflow execution. The key integration points are clear, and most of the execution infrastructure can be reused. The main work involves:

1. Detecting named workflow invocation pattern
2. Loading workflow from `~/.pflow/workflows/<name>.json`
3. Parsing and injecting runtime parameters
4. Reusing existing execution pipeline

The implementation should maintain compatibility with all existing features including stdin handling, output keys, and verbose mode.
