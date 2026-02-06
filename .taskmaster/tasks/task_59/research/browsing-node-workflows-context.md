# ComponentBrowsingNode: Workflows Context Commented Out

**Date**: 2026-02-06
**Context**: Discovered during investigation of workflow discovery score regression

## Finding

In `src/pflow/planning/nodes.py`, `ComponentBrowsingNode._build_cache_blocks()` (line 632-634), the workflows context is commented out in the cached code path:

```python
if workflows_context:
    # TODO: Uncomment this when nested workflows are supported
    # context_parts.append(f"\n<available_workflows>\n{workflows_context}\n</available_workflows>")
    pass
```

Meanwhile the prompt template (`planning/prompts/component_browsing.md`) references `<available_workflows>` and instructs the LLM to select workflows as building blocks.

## Current Impact: None

- `pflow registry discover` uses `cache_planner=False`, so the non-cached path runs (which includes workflows via template variable substitution)
- Even when included, LLM workflow selections are cleared on line 717-723 since nested workflows aren't supported
- The planner is gated (Task 107), so the cached path is unreachable in production

## Action Required When Implementing Nested Workflows (Task 59)

When nested workflows are enabled:

1. **Uncomment line 633** to include workflows context in the cached path
2. **Remove the clearing logic** on lines 717-723 that discards workflow selections
3. **Verify the workflows context format** — it now includes Inputs, Optional, and node-ID-based Flow fields (changed in commit `2abeac2`), which should give the LLM good signal for selecting workflows as building blocks
4. **Test both cached and non-cached paths** to ensure parity
