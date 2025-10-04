# Fix MetadataGenerationNode cache_blocks Parameter Error

## Problem Summary

The `MetadataGenerationNode` is failing when called from `pflow workflow save --generate-metadata` with a Pydantic validation error. The LLM call fails because it's passing `cache_blocks=None` to a model that doesn't accept this parameter.

## Error Details

### Full Error Trace
```python
pydantic_core._pydantic_core.ValidationError: 1 validation error for ClaudeOptionsWithThinking
cache_blocks
  Extra inputs are not permitted [type=extra_forbidden, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.11/v/extra_forbidden
```

### Where It Fails
**File**: `src/pflow/planning/nodes.py`
**Line**: 2594
**Node**: `MetadataGenerationNode.exec()`

```python
response = model.prompt(
    formatted_prompt,
    system=system_prompt,
    cache_blocks=cache_blocks if cache_planner else None,  # ← THIS LINE
)
```

### Context of Failure

The error occurs when:
1. User runs: `pflow workflow save <file> <name> <description> --generate-metadata`
2. The save command calls `MetadataGenerationNode` to generate rich metadata
3. Node tries to call LLM with `cache_blocks=None`
4. Pydantic validation rejects `None` as invalid for `cache_blocks` parameter

## Root Cause Analysis

### The Issue
The `MetadataGenerationNode.exec()` method unconditionally passes `cache_blocks` parameter to `model.prompt()`:

```python
cache_blocks=cache_blocks if cache_planner else None
```

**Problem**: When `cache_planner=False` (the default in CLI workflows), this becomes `cache_blocks=None`, which is invalid.

### Why It's Invalid
The Claude model's Pydantic options schema (`ClaudeOptionsWithThinking`) has `extra='forbid'`, meaning:
- ✅ Can pass `cache_blocks=[...]` (valid list)
- ❌ Cannot pass `cache_blocks=None` (explicitly forbidden)
- ✅ Should **omit the parameter entirely** when not caching

### Expected Behavior
When `cache_planner=False`, the parameter should be **omitted**, not set to `None`:

```python
# ✅ CORRECT
options = {"system": system_prompt}
if cache_planner and cache_blocks:
    options["cache_blocks"] = cache_blocks
response = model.prompt(formatted_prompt, **options)

# ❌ WRONG (current code)
response = model.prompt(
    formatted_prompt,
    system=system_prompt,
    cache_blocks=None  # Pydantic rejects this!
)
```

## How to Fix

### Step 1: Locate the Problem Code

**File**: `src/pflow/planning/nodes.py`
**Function**: `MetadataGenerationNode.exec()`
**Around line**: 2594

Find this code:
```python
response = model.prompt(
    formatted_prompt,
    system=system_prompt,
    cache_blocks=cache_blocks if cache_planner else None,
)
```

### Step 2: Apply the Fix

Replace with conditional parameter passing:

```python
# Build options dict conditionally
llm_options = {"system": system_prompt}

# Only add cache_blocks if we're actually caching
if cache_planner and cache_blocks:
    llm_options["cache_blocks"] = cache_blocks

# Call with unpacked options
response = model.prompt(formatted_prompt, **llm_options)
```

**Why this works**:
- When `cache_planner=False`, options only contains `{"system": ...}`
- When `cache_planner=True` AND `cache_blocks` exists, options contains `{"system": ..., "cache_blocks": [...]}`
- Never passes `None` which Pydantic rejects

### Step 3: Check for Similar Issues

Search for other instances in the same file where this pattern might exist:

```bash
grep -n "cache_blocks=cache_blocks if cache_planner else None" src/pflow/planning/nodes.py
```

Fix all occurrences using the same pattern.

### Step 4: Verify the Fix

Test the fix with:

```bash
# Create a test workflow
cat > /tmp/test-workflow.json << 'EOF'
{
  "nodes": [
    {
      "id": "test",
      "type": "test-node",
      "params": {"add_keys": {"result": "test"}}
    }
  ],
  "outputs": {
    "result": {"source": "${test.result}"}
  }
}
EOF

# Try saving with metadata generation
uv run pflow workflow save /tmp/test-workflow.json test-workflow-meta "Test workflow" --generate-metadata

# Should succeed without Pydantic errors
```

Expected output:
```
Generating rich metadata...
  Generated N keywords
  Generated N capabilities
✓ Saved workflow 'test-workflow-meta' to library
```

## Additional Context

### Where MetadataGenerationNode is Used

1. **Primary use**: `pflow workflow save --generate-metadata` (CLI command)
   - Location: `src/pflow/cli/commands/workflow.py`
   - Called when user wants AI-generated metadata

2. **Context setup**: The CLI sets `cache_planner=False` in shared store
   - This is why `cache_blocks` becomes `None`
   - Different from planner nodes which set `cache_planner=True`

### How Other Nodes Handle This

Check `WorkflowDiscoveryNode.exec()` or `ComponentBrowsingNode.exec()` for correct pattern:

They likely do something like:
```python
# Good pattern - only pass cache_blocks when needed
if cache_planner and cache_blocks:
    response = model.prompt(prompt, cache_blocks=cache_blocks)
else:
    response = model.prompt(prompt)
```

Or use the dict unpacking approach shown in the fix.

### Fallback Behavior

Currently, when metadata generation fails:
- Node catches the exception
- Falls back to static metadata (empty keywords/capabilities)
- Workflow still saves successfully
- User sees error but workflow is usable

After the fix:
- Metadata generation should succeed
- Rich AI-generated keywords and capabilities
- Better workflow discoverability

## Testing Checklist

After implementing the fix, verify:

- [ ] `pflow workflow save <file> <name> <desc> --generate-metadata` succeeds
- [ ] Metadata is actually generated (keywords, capabilities shown)
- [ ] No Pydantic validation errors in output
- [ ] Workflow is saved to `~/.pflow/workflows/<name>.json`
- [ ] Other planning nodes still work (discovery, browsing, etc.)
- [ ] Run unit tests: `uv run pytest tests/test_planning/unit/test_metadata_generation.py -v` (if exists)

## Expected Outcome

After fixing:

```bash
$ uv run pflow workflow save test.json my-workflow "Does a thing" --generate-metadata

Generating rich metadata...
  Generated 8 keywords
  Generated 3 capabilities
✓ Saved workflow 'my-workflow' to library
  Location: /Users/user/.pflow/workflows/my-workflow.json
  Execute with: pflow my-workflow
```

No errors, clean output, metadata successfully generated.

## Related Code References

### Key Files
- `src/pflow/planning/nodes.py` - Contains `MetadataGenerationNode` (line ~2594)
- `src/pflow/cli/commands/workflow.py` - Calls metadata generation (line ~305-336)
- LLM library location: `.venv/lib/python3.13/site-packages/llm/models.py` (line 1825)

### Pydantic Schema Reference
The error comes from the Claude model's options validation:
- Model: `ClaudeOptionsWithThinking`
- Setting: `extra='forbid'` (rejects unknown/None parameters)
- Location: llm library (not in pflow codebase)

### Search Commands for Investigation

```bash
# Find all cache_blocks usage
rg "cache_blocks" src/pflow/planning/nodes.py

# Find similar conditional parameter patterns
rg "if cache_planner" src/pflow/planning/nodes.py

# Check how other nodes handle this
rg -A 5 "model.prompt.*cache" src/pflow/planning/nodes.py
```

## Success Criteria

The fix is complete when:
1. ✅ `pflow workflow save --generate-metadata` runs without Pydantic errors
2. ✅ Rich metadata is generated (keywords, capabilities, use cases)
3. ✅ No fallback to static metadata occurs
4. ✅ All existing tests pass
5. ✅ Manually tested with various workflows

## Priority

**HIGH** - This breaks a user-facing feature (`--generate-metadata` flag) and creates a poor user experience with error traces.

## Estimated Effort

- **Investigation**: 5 minutes (you have all the info above)
- **Fix implementation**: 5 minutes (simple conditional logic)
- **Testing**: 5 minutes (run the test command)
- **Total**: ~15 minutes

## Notes for the Agent

- This is a **simple conditional parameter passing issue**
- The fix is **straightforward** - just use dict unpacking or conditional passing
- The error trace is **misleading** - it's not a Pydantic schema issue, it's about how we pass parameters
- **Don't modify** the Pydantic schema or LLM library - fix the calling code in `nodes.py`
- Check if **other nodes have the same pattern** and fix them too
- The **fallback works**, so this isn't breaking workflows, just degrading metadata quality
