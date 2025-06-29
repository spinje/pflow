# Task 15 Replacement Insights for Task 12

## Summary

This document captures the key insights from our analysis of Task 15 and why it should be replaced/merged with Task 12.

## Key Finding: Task 15 is Redundant

After thorough analysis, we discovered that:
1. **Task 12** ("Implement general LLM node") - Creates the user-facing LLM node for workflows
2. **Task 15** ("Implement LLM API client") - Was meant to create utility functions for the planner

However, the planner should use the `llm` library directly, making Task 15 unnecessary.

## Critical Understanding: User-Facing Nodes vs Internal Implementation

### User-Facing Node (Task 12)
- A PocketFlow node that users can include in their workflows
- Accessed via CLI: `pflow llm --prompt="..."`
- Discovered by the registry
- Used by the planner when generating workflows

Example workflow:
```bash
# User types:
pflow "summarize the file data.txt"

# Planner generates:
read-file --path=data.txt >> llm --prompt="Summarize this: $content"
```

### Internal Implementation (What Task 15 tried to be)
- The planner's own code uses `llm` library directly
- No wrapper needed - direct usage is cleaner
- Following the library's own patterns

## Why Direct Usage is Better

From the external patterns research:
- Even `llm` itself doesn't wrap its own API
- Simple pattern: `llm.get_model()` → `model.prompt()` → `response.text()`
- Adding wrappers violates YAGNI principle
- Direct usage = less code to maintain

## Implementation Pattern for Task 12

The LLM node should:
1. Inherit from `pocketflow.Node` (or `BaseNode`)
2. Use the shared store pattern
3. Wrap the `llm` library for workflow usage
4. Provide a natural interface

```python
class LLMNode(Node):
    name = "llm"  # Important for registry

    def prep(self, shared):
        # Get inputs from shared store
        return {
            "prompt": shared.get("prompt"),
            "model": shared.get("model", "gpt-4o-mini"),
            # ... other parameters
        }

    def exec(self, prep_res):
        # Use llm library
        model = llm.get_model(prep_res["model"])
        response = model.prompt(prep_res["prompt"])
        return response.text()

    def post(self, shared, prep_res, exec_res):
        # Write to shared store
        shared["response"] = exec_res
        return "default"
```

## Task Dependencies Update

- Task 17 (Workflow Planner) currently depends on Task 15
- Should be updated to depend on Task 12 instead
- The planner needs the LLM node to exist in the registry

## Lessons Learned

1. **Clear distinction needed** between:
   - Nodes that users interact with (Task 12)
   - Internal implementation details (direct library usage)

2. **PocketFlow nodes are for workflows**, not internal utilities

3. **Follow the library's patterns** - if `llm` doesn't wrap its own API, neither should we

4. **One source of truth** - Task 12 is THE LLM node, no duplicates needed

## Action Items

1. Delete Task 15 from tasks.json
2. Update Task 17 dependencies (remove 15, ensure 12 is included)
3. Implement Task 12 with insights from both analyses
4. Document clearly that internal components use `llm` directly
