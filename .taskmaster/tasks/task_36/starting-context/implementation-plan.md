# Task 36: Update Context Builder for Automatic Namespacing Clarity

## Executive Summary

With automatic namespacing enabled by default (Task 9), the context builder's presentation of node information has become misleading. It shows "Inputs" as if nodes can read them directly from the shared store, but with namespacing, ALL data must be passed explicitly through params using template variables. This task updates ONLY the context builder to present node information in a way that accurately reflects the namespaced reality.

## Problem Statement

### The Core Issue
After Task 9 (Automatic Namespacing), the mental model for how nodes work has fundamentally changed:
- **Before**: Nodes could read inputs directly from shared store
- **After**: Nodes can only access data passed explicitly via params

However, the context builder still presents nodes using the old mental model, causing confusion for the LLM planner.

### Current Misleading Presentation
```markdown
### read-file
**Inputs**:
- `file_path: str` - Path to the file to read

**Outputs**:
- `content: str` - File contents

**Parameters**: none  ❌ MISLEADING!
```

This suggests `read-file` has no parameters, when in fact `file_path` MUST be passed as a parameter!

### Impact
The LLM planner receives confusing signals:
1. "Inputs" suggests nodes read from shared store (they can't with namespacing)
2. "Parameters: none" suggests no params are needed (wrong!)
3. Inconsistent presentation between nodes with/without exclusive params
4. No clear examples of how to actually connect nodes

## Current State Analysis

### How Context Builder Currently Works

1. **Inputs Section**: Shows all items from node's `interface.inputs`
2. **Outputs Section**: Shows all items from node's `interface.outputs`
3. **Parameters Section**: Shows ONLY "exclusive params" (params NOT in inputs)
4. **Template Variables**: Shows only when exclusive params exist

### The "Exclusive Params" Pattern
The system follows an "exclusive params" pattern where:
- Parameters that duplicate inputs are hidden
- Only params that are NOT inputs are shown
- This made sense when nodes could read from shared store
- With namespacing, this distinction is confusing

### Example of Current Inconsistency

**Node with exclusive params (llm):**
```markdown
**Inputs**: prompt, system
**Parameters**: model, temperature  ← Only "exclusive" params shown
**Template Variable Usage**: [JSON example]
```

**Node without exclusive params (read-file):**
```markdown
**Inputs**: file_path, encoding
**Parameters**: none  ← Misleading!
```

## Proposed Solution

### Design Principles
1. **Minimal Change**: Update ONLY context_builder.py
2. **No System Changes**: Keep all other components unchanged
3. **Factual Only**: Present structure, not instructions
4. **Consistency**: Same format for all nodes

### New Presentation Format

```markdown
### read-file
Read content from a file and add line numbers for display.

**Parameters** (all go in params field):
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (optional, default: utf-8)

**Outputs** (available as ${node_id.output_key}):
- `content: str` - File contents with line numbers
- `error: str` - Error message if operation failed

**Example usage**:
```json
{"id": "read", "type": "read-file", "params": {"file_path": "${input_file}"}}
```
```

### Key Changes
1. **Rename "Inputs" → "Parameters"**: Makes it clear everything goes in params
2. **Show ALL parameters**: No more "exclusive params" distinction
3. **Clarify output access**: Show how to reference outputs with namespacing
4. **Always show example**: Concrete usage pattern for every node
5. **Remove separate Parameters section**: Consolidate into one place

## Implementation Details

### Files to Modify
- `src/pflow/planning/context_builder.py` - Main changes
- `tests/test_planning/test_context_builder_phases.py` - Update tests

### Functions to Update

1. **`_format_node_section()`**
   - Change "Inputs" heading to "Parameters"
   - Add clarification about params field
   - Update output formatting to show access pattern

2. **`_format_exclusive_parameters()`**
   - Remove this function or repurpose
   - No longer need exclusive params distinction

3. **`_format_template_variables()`**
   - Always show usage examples
   - Use concrete examples, not "${key}"
   - Show as "Example usage" section

4. **New: `_format_usage_example()`**
   - Generate concrete JSON example for each node
   - Show realistic param values
   - Include both user inputs and node outputs

### Implementation Steps

1. **Update node section formatting**:
```python
def _format_node_section(node_type: str, node_data: dict) -> str:
    lines = [f"### {node_type}"]
    lines.append(node_data.get("description", ""))
    lines.append("")

    # Show ALL parameters (formerly "inputs")
    lines.append("**Parameters** (all go in params field):")
    for param in node_data["interface"]["inputs"]:
        lines.append(f"- `{param['key']}: {param['type']}` - {param.get('description', '')}")

    # Add any exclusive params that aren't in inputs
    for param in node_data.get("params", []):
        if param not in [i['key'] for i in inputs]:
            lines.append(f"- `{param}: any` - Configuration parameter")

    # Show outputs with access pattern
    lines.append("")
    lines.append("**Outputs** (available as ${node_id.output_key}):")
    for output in node_data["interface"]["outputs"]:
        lines.append(f"- `{output['key']}: {output['type']}` - {output.get('description', '')}")

    # Always show usage example
    lines.append("")
    lines.append("**Example usage**:")
    lines.append("```json")
    lines.append(_generate_usage_example(node_type, node_data))
    lines.append("```")

    return "\n".join(lines)
```

2. **Generate realistic examples**:
```python
def _generate_usage_example(node_type: str, node_data: dict) -> str:
    example = {
        "id": node_type.replace("-", "_"),
        "type": node_type,
        "params": {}
    }

    # Add example values for each input
    for inp in node_data["interface"]["inputs"]:
        key = inp["key"]
        if "file" in key.lower():
            example["params"][key] = "${input_file}"
        elif "content" in key.lower():
            example["params"][key] = "${previous_node.content}"
        else:
            example["params"][key] = f"${{{key}}}"

    return json.dumps(example, indent=2)
```

## Testing Strategy

### Unit Tests
1. **Test parameter formatting**: Verify all params shown, not just exclusive
2. **Test example generation**: Ensure examples are valid JSON
3. **Test output formatting**: Check ${node_id.key} pattern shown
4. **Test consistency**: All nodes use same format

### Integration Tests
1. **Generate context for real nodes**: Verify format is clear
2. **Test with complex nodes**: Ensure nested structures handled
3. **Test with workflows**: Verify workflow section unchanged
4. **Compare before/after**: Document the improvement

### Manual Validation
```python
# Test script to see output
from pflow.planning.context_builder import build_planning_context
from pflow.registry import Registry

registry = Registry()
context = build_planning_context(
    selected_node_ids=["read-file", "write-file", "llm"],
    selected_workflow_names=[],
    registry_metadata=registry.load()
)
print(context)
```

## Success Criteria

### Must Have
- [x] All parameters shown (not just exclusive)
- [x] Clear that everything goes in params field
- [x] Concrete usage examples for every node
- [x] Consistent format for all nodes
- [x] No breaking changes to other systems

### Should Have
- [x] Output access pattern clear (${node_id.key})
- [x] Optional params marked clearly
- [x] Complex structures still shown in JSON format
- [ ] Existing tests updated to match

### Nice to Have
- [ ] Better example value generation
- [ ] Parameter types shown more clearly
- [ ] Default values displayed

## Risk Assessment

### Low Risk
- Changes isolated to one file
- No impact on node execution
- No schema changes
- Easy to revert

### Potential Issues
- Tests may need updating
- Documentation may reference old format
- LLM prompts may need minor adjustments

## Rollback Plan
If issues arise:
1. Revert context_builder.py changes
2. Tests will pass again immediately
3. No data migration needed
4. No user impact

## Dependencies

### Depends On
- Task 9: Automatic Namespacing (already complete)

### Impacts
- Task 17: Natural Language Planner (will see clearer context)
- Any future tasks that use context builder

## Timeline Estimate
- Implementation: 1-2 hours
- Testing: 1 hour
- Documentation: 30 minutes
- Total: ~3 hours

## Validation Questions

Before implementation, verify:
1. Are we keeping the workflow section unchanged? (Yes)
2. Should we show parameter defaults? (Nice to have)
3. Do we need to update planner prompts? (No, context only)
4. Should complex structures still show JSON? (Yes)

## Example Comparison

### Before (Confusing)
```markdown
### write-file
**Inputs**:
- `content: str` - Content to write
- `file_path: str` - Path to the file

**Parameters**:
- `append: bool` - Append mode

**Template Variable Usage**: [Complex JSON]
```

### After (Clear)
```markdown
### write-file
Write content to a file with automatic directory creation.

**Parameters** (all go in params field):
- `content: str` - Content to write
- `file_path: str` - Path to the file
- `append: bool` - Append mode (optional, default: false)

**Outputs** (available as ${node_id.output_key}):
- `written: bool` - Success status
- `error: str` - Error message if failed

**Example usage**:
```json
{
  "id": "save_result",
  "type": "write-file",
  "params": {
    "content": "${process.result}",
    "file_path": "${output_file}",
    "append": false
  }
}
```
```

## Implementation Notes

### Key Insight
The context builder is our translation layer between node metadata and LLM understanding. By fixing this translation, we solve the entire namespacing confusion without touching any other part of the system.

### Why This Works
1. Node metadata remains unchanged
2. IR schema unchanged
3. Node implementations unchanged
4. Only the presentation layer updates

### Critical Decision
We're eliminating the "exclusive params" distinction entirely. With namespacing, this distinction is confusing rather than helpful. ALL parameters should be shown clearly in one place.

## Conclusion

This task makes a surgical change to the context builder that dramatically improves clarity for the LLM planner. By presenting nodes in a way that matches how they actually work with namespacing, we eliminate a major source of confusion without any system-wide changes.