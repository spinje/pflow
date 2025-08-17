# Critical Design Gap: Workflow Outputs vs Automatic Namespacing

## Executive Summary

There is a fundamental incompatibility between workflow outputs and automatic namespacing in pflow. When namespacing is enabled (the default), nodes write to namespaced keys (`node_id.output_key`), but workflow outputs expect top-level keys. There is no mechanism to bridge this gap, causing the LLM to generate invalid IR by adding a `value` field to outputs.

## The Observed Problem

### User Command
```bash
uv run pflow "create a workflow that uses an llm to create a very short story about llamas and saves it to a file"
```

### Error
```
Structural validation failed: outputs.file_saved: Additional properties are not allowed ('value' was unexpected)
```

### What the LLM Generated
```json
"outputs": {
  "story_content": {
    "description": "The generated story content",
    "value": "${generate_story.response}"  // ❌ Not allowed by schema
  },
  "file_saved": {
    "description": "Confirmation that the story was saved to file",
    "value": "${save_story.written}"  // ❌ Not allowed by schema
  }
}
```

## The Root Cause

### 1. How Namespacing Works

With `enable_namespacing: true` (the default):
- Nodes write to `shared[node_id][output_key]`
- Example: `generate_story` node writes to `shared["generate_story"]["response"]`
- Templates access this as `${generate_story.response}`

### 2. How Workflow Outputs Are Supposed to Work

According to the schema:
```json
"outputs": {
  "story_content": {
    "description": "The generated story content",
    "type": "string"  // Optional type hint
    // NO value field allowed!
  }
}
```

Outputs are purely declarative - they document what the workflow produces but don't specify HOW.

### 3. The Fundamental Mismatch

**Question**: If `story_content` is declared as a workflow output, where does its value come from?

With namespacing disabled:
- Node could write directly to `shared["story_content"]`
- Workflow output `story_content` maps directly to this key
- Everything works!

With namespacing enabled (default):
- Node writes to `shared["generate_story"]["response"]`
- Workflow declares output `story_content`
- **There's no connection between these two!**
- How does `story_content` get populated? It doesn't!

## Why The LLM's Solution Makes Sense

The LLM is trying to solve a real problem by adding:
```json
"value": "${generate_story.response}"
```

This would create an explicit mapping:
- Workflow output `story_content` gets its value from `${generate_story.response}`
- This is actually a logical solution to bridge the namespacing gap!

## Current System Limitations

### 1. No Output Mapping Mechanism

Unlike nested workflows which have `output_mapping`:
```json
{
  "type": "workflow",
  "params": {
    "output_mapping": {
      "child_key": "parent_key"  // Maps child output to parent
    }
  }
}
```

Top-level workflows have no equivalent mechanism to map namespaced values to output keys.

### 2. Output Validation is Warning-Only

From `compiler.py:573`:
```python
logger.warning(
    f"Declared output '{output_name}' cannot be traced to any node in the workflow. "
    f"This may be fine if nodes write dynamic keys."
)
```

The system just warns that outputs can't be traced - it doesn't fail. This suggests the feature is incomplete.

### 3. Unclear Purpose of Outputs

The documentation doesn't explain:
- How workflow outputs actually get populated
- Whether they're just documentation or functional
- How they interact with namespacing
- How parent workflows access child workflow outputs

## Evidence This is a Design Gap

### 1. The Warning Message Itself
"This may be fine if nodes write dynamic keys" - This suggests uncertainty about how outputs should work.

### 2. No Tests for Namespaced Outputs
There don't appear to be tests verifying that declared outputs work correctly with namespacing enabled.

### 3. Nested Workflows Use output_mapping
Nested workflows have explicit `output_mapping` because they recognized this problem. But top-level workflows don't have this.

### 4. The LLM Keeps Making This "Mistake"
The LLM consistently tries to add `value` fields because it's trying to solve a real problem that humans haven't noticed yet.

## Possible Solutions

### Solution 1: Allow `value` Field (LLM's Approach)
```json
"outputs": {
  "story_content": {
    "description": "The generated story content",
    "value": "${generate_story.response}"  // Map namespaced value to output
  }
}
```

**Pros**:
- Explicit and clear
- Solves the namespacing problem
- Allows workflows to define their public interface

**Cons**:
- Requires schema change
- Adds complexity

### Solution 2: Auto-Promote Node Outputs
If a workflow declares output `story_content`, automatically check all nodes for an output with that name and promote it to top-level.

**Pros**:
- No schema change needed
- Works with existing workflows

**Cons**:
- Implicit and magical
- What if multiple nodes have the same output name?
- Doesn't work if output name differs from node output name

### Solution 3: Remove Outputs from Workflows
Just don't declare outputs - they're optional anyway.

**Pros**:
- Simplest solution
- No schema changes

**Cons**:
- Loses documentation value
- Parent workflows can't know what child workflows produce
- Reduces type safety and validation

### Solution 4: Disable Namespacing by Default
Make `enable_namespacing: false` the default.

**Pros**:
- Outputs work as originally designed
- Simpler mental model

**Cons**:
- Brings back collision problems
- Major breaking change
- Loses benefits of namespacing

## Implications

### 1. Current Workflows with Outputs Are Broken
Any workflow that:
- Has `enable_namespacing: true` (or relies on default)
- Declares outputs
- Expects those outputs to be accessible

Is fundamentally broken - the outputs won't be populated correctly.

### 2. The Planner is Smarter Than Expected
The LLM planner is actually identifying and trying to solve a real design problem. Its solution (adding `value` field) is quite reasonable.

### 3. This Affects Nested Workflows Too
Parent workflows can't reliably access child workflow outputs unless they use `output_mapping`, which only works for the workflow executor node type.

## Recommendations

### Immediate (Workaround)
1. **Update workflow_generator.md** to NOT generate outputs section at all
2. Document that outputs are not compatible with namespacing
3. Disable namespacing for workflows that need outputs

### Short-term (Fix)
1. **Adopt the LLM's solution**: Allow `value` field in outputs for explicit mapping
2. Update schema to support this
3. Update compiler to handle output value mapping

### Long-term (Design)
1. Rethink the relationship between namespacing and outputs
2. Consider if outputs should be:
   - Pure documentation (remove functional expectations)
   - Functional with explicit mapping (add `value` field)
   - Auto-detected from nodes (implicit mapping)
3. Ensure consistency between top-level and nested workflow output handling

## Conclusion

This is not a bug in the planner or a result of the template syntax migration. It's a fundamental design gap in pflow where two features (workflow outputs and automatic namespacing) were developed without considering their interaction. The LLM is actually being quite clever in trying to solve this problem with the `value` field.

The fact that this wasn't caught earlier suggests that:
1. Workflow outputs aren't being used much in practice
2. Most workflows either don't use namespacing or don't declare outputs
3. The feature was never fully implemented for the namespaced case

This needs to be addressed at the design level, not just patched in the planner prompts.