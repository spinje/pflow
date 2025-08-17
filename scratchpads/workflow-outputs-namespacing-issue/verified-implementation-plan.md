# Verified Implementation Plan: Fix Workflow Outputs with Namespacing

## Verified Facts (from codebase research)

1. **CLI Execution Flow**:
   - Line 566: `flow.run(shared_storage)` executes the workflow
   - Line 578: Workflow IR dict (`ir_data`) is available after execution
   - Line 290-329: `_try_declared_outputs()` handles output extraction

2. **Current Bug Location**:
   - Line 311-312 in `_try_declared_outputs()`: Only checks `shared_storage[output_name]` at root
   - With namespacing, values are at `shared[node_id][key]`, not root
   - This is why outputs fail with namespacing enabled

3. **TemplateResolver Availability**:
   - Located at `src/pflow/runtime/template_resolver.py`
   - Static method: `resolve_value(var_name: str, context: dict[str, Any])`
   - Can handle paths like `node_id.key.subkey`
   - Returns None for missing keys (doesn't throw)

4. **Source Field Status**:
   - Already added to schema at `ir_schema.py` lines 213-216
   - Not used anywhere in the codebase yet
   - Ready to be implemented

## Simplified Implementation Plan

### Phase 1: Modify Existing Output Extraction ✅ VERIFIED APPROACH

Instead of creating a new function, we'll enhance `_try_declared_outputs()`:

```python
# In src/pflow/cli/main.py

# 1. Import TemplateResolver at top of file
from pflow.runtime.template_resolver import TemplateResolver

# 2. Modify _try_declared_outputs() function (lines 290-329)
def _try_declared_outputs(shared_storage, workflow_ir, verbose):
    # ... existing validation ...

    for output_name, output_config in declared_outputs.items():
        value = None

        # NEW: Check for source field first
        if isinstance(output_config, dict) and "source" in output_config:
            source_expr = output_config["source"]
            # Remove ${ and } if present
            if source_expr.startswith("${") and source_expr.endswith("}"):
                source_expr = source_expr[2:-1]

            # Resolve using TemplateResolver
            value = TemplateResolver.resolve_value(source_expr, shared_storage)

            if value is None and verbose:
                click.echo(f"Warning: Could not resolve source '{source_expr}' for output '{output_name}'", err=True)

        # FALLBACK: Check root level (backward compatibility)
        if value is None and output_name in shared_storage:
            value = shared_storage[output_name]

        if value is not None:
            # ... existing output handling ...
```

### Phase 2: Add Comprehensive Tests

Create `tests/test_cli/test_workflow_outputs_with_namespacing.py`:

```python
def test_outputs_with_source_field_and_namespacing():
    """Test that outputs with source field work with namespacing enabled."""
    workflow = {
        "ir_version": "0.1.0",
        "enable_namespacing": True,  # Explicit
        "nodes": [
            {
                "id": "generate",
                "type": "test-node",
                "params": {"output_key": "result", "output_value": "Hello World"}
            }
        ],
        "outputs": {
            "final_result": {
                "description": "The generated result",
                "source": "${generate.result}"  # NEW: source field
            }
        }
    }
    # Run workflow and verify output is extracted correctly

def test_backward_compatibility_without_source():
    """Test that outputs without source still work (if at root level)."""
    # Test existing behavior is preserved

def test_missing_source_warning():
    """Test that missing sources produce warnings, not failures."""
    # Verify graceful degradation
```

### Phase 3: Update Planner Prompt

Modify `src/pflow/planning/prompts/workflow_generator.md`:

Add clear instruction after the outputs section:
```markdown
### Workflow Outputs (With Namespacing)

When automatic namespacing is enabled (default), you MUST specify the source for each output:

```json
"outputs": {
  "story_content": {
    "description": "The generated story",
    "source": "${generate_story.response}"  // REQUIRED - maps namespaced value
  },
  "file_saved": {
    "description": "Confirmation file was saved",
    "source": "${save_story.written}"  // REQUIRED - maps namespaced value
  }
}
```

Without the source field, outputs cannot access namespaced node values.
```

### Phase 4: Integration Testing

Test the original failing case:
```bash
uv run pflow "create a workflow that uses an llm to create a very short story about llamas and saves it to a file"
```

Expected behavior:
1. Planner generates IR with source fields in outputs
2. Workflow executes successfully
3. Outputs are correctly extracted from namespaced locations
4. Story content is returned to user

## Implementation Steps (in order)

1. **Import TemplateResolver** in CLI (1 line)
2. **Modify _try_declared_outputs()** (~20 lines of changes)
3. **Run existing tests** to ensure no regression
4. **Add new test file** with namespacing + outputs tests
5. **Update workflow_generator.md** prompt
6. **Test with original workflow**
7. **Run full test suite**: `make test && make check`

## Risk Mitigation

### What could go wrong?

1. **TemplateResolver import fails**
   - Mitigation: Already verified it exists and is importable

2. **Source expression parsing issues**
   - Mitigation: Strip `${}` wrapper if present
   - TemplateResolver handles the rest

3. **Backward compatibility breaks**
   - Mitigation: Only use source if present, fallback to root lookup
   - Existing tests will catch any regression

4. **Planner doesn't use source field**
   - Mitigation: Clear examples in prompt
   - Explicit instruction that it's REQUIRED with namespacing

## Success Metrics

✅ Original failing workflow executes successfully
✅ All existing tests pass (backward compatibility)
✅ New tests pass (source field functionality)
✅ No performance regression
✅ Clear error messages for debugging

## Why This Approach Works

1. **Minimal Changes**: Modifying existing function instead of adding new ones
2. **Backward Compatible**: Falls back to root-level lookup
3. **Uses Existing Infrastructure**: TemplateResolver already handles paths
4. **Clear Data Flow**: Explicit source mapping
5. **Graceful Degradation**: Warnings instead of failures

This is the simplest, most robust solution that aligns with existing patterns.