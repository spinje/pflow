# Task 36 Handoff: Context Builder Update for Namespacing

**⚠️ STOP: Read this entire handoff before implementing. When done, just say you're ready to begin.**

## The Core Problem You're Solving

With automatic namespacing enabled by default (Task 9), nodes can NO LONGER read inputs directly from the shared store. Everything must be passed via params using template variables. But the context builder still presents nodes as if they have "Inputs" that can be read from shared store. This is fundamentally misleading.

## Critical Discovery: The "Exclusive Params" Anti-Pattern

The current code has a function `_format_exclusive_parameters()` that only shows params that are NOT in the inputs list. This made sense pre-namespacing, but now it's actively harmful:

- Nodes like `read-file` show "**Parameters**: none" even though they REQUIRE params
- The LLM thinks some nodes have no parameters at all
- This causes workflow generation failures

**File to examine**: `/Users/andfal/projects/pflow/src/pflow/planning/context_builder.py` lines 673-696

## What Actually Happens Now (Post-Task 9)

```python
# What the context suggests happens:
file_path = shared.get("file_path")  # Read from shared store

# What ACTUALLY happens with namespacing:
file_path = shared.get("file_path")  # Returns None!
# Because it's actually at shared["node_id"]["file_path"]
# So nodes MUST get it via: self.params.get("file_path")
```

## The Solution Approach (Surgical Change)

**ONLY modify `context_builder.py`** - don't touch anything else:

1. Change "Inputs" → "Parameters" in the output
2. Show ALL parameters (not just exclusive ones)
3. Always show a usage example
4. Keep it FACTUAL - no explanations in the context output

## Files and Key Functions

**Primary file**: `/Users/andfal/projects/pflow/src/pflow/planning/context_builder.py`

Key functions to modify:
- `_format_exclusive_parameters()` (lines 673-696) - This is the main problem
- `_format_node_section()` or `_format_node_section_enhanced()` - Calls the above
- `_format_template_variables()` (lines 655-671) - Currently shows unhelpful "${key}"

## Test Files That Will Break

**Critical test**: `/Users/andfal/projects/pflow/tests/test_planning/test_context_builder_phases.py`
- Line 783: Tests for "**Parameters**: none" - this assertion MUST change
- The test expects exclusive params behavior - update it

Run this to verify: `uv run pytest tests/test_planning/test_context_builder_phases.py -xvs`

## The Trap: Don't Add Instructions

The context builder output goes into `<available_nodes>` tags in the prompt. It should be PURE DATA about nodes, not instructions. The workflow generator prompt (`/Users/andfal/projects/pflow/src/pflow/planning/prompts/workflow_generator.md`) already has all the instructions.

**Wrong**: "With namespacing enabled, you must pass all inputs via params"
**Right**: Just show the structure clearly

## Current vs Desired Output

Use this test file to see current output:
```python
# test_context_current.py (already exists in project root)
from pflow.planning.context_builder import build_planning_context
# ... see the file for full code
```

**Current (BAD)**:
```markdown
### read-file
**Inputs**:
- `file_path: str` - Path to file
**Parameters**: none  # WRONG! Makes it seem like no params accepted
```

**Desired (GOOD)**:
```markdown
### read-file
**Parameters**:
- `file_path: str` - Path to file
**Example**: {"params": {"file_path": "${input_file}"}}
```

## Edge Cases and Gotchas

1. **Complex nodes with structures** - Already handled well with JSON format, don't break this
2. **Nodes with no inputs** - Should still show "Parameters" section (might be empty)
3. **The term "Inputs"** - It's everywhere in the codebase but means different things:
   - In node metadata: What the node expects
   - In workflow IR: User-provided values
   - Post-namespacing: Must be passed via params

## Why Previous Attempts Failed

Earlier attempts tried to add explanations like "pass via params using template variables" in the context. This is wrong - the context should be data only. The instructions belong in the prompt templates.

## Performance Consideration

The context builder is called frequently during planning. Don't add expensive operations. The current implementation is efficient - keep it that way.

## Related Documentation

- **Task 9 Review**: `/.taskmaster/tasks/task_9/task-review.md` - Explains namespacing
- **Node interface format**: `/src/pflow/nodes/CLAUDE.md` - Shows the exclusive params pattern
- **Workflow generator prompt**: `/src/pflow/planning/prompts/workflow_generator.md` - Has the instructions

## Final Warning

The biggest risk is overthinking this. It's a simple change:
1. Show ALL parameters in one section
2. Call it "Parameters" not "Inputs"
3. Always show an example
4. Don't add explanations

The context builder's job is to present facts, not teach concepts.

---

**Remember**: Don't start implementing. First, read this handoff completely and confirm you understand the core issue and approach. Just say you're ready to begin.