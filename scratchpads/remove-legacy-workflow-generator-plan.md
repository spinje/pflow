# Plan to Remove Legacy workflow_generator.md Path

## Current State Analysis

### Usage Locations
1. **WorkflowGeneratorNode.exec()** (src/pflow/planning/nodes.py:1598-1620)
   - Legacy fallback when no `planner_extended_context` or `planner_accumulated_context`
   - Uses `_build_prompt()` method which loads `workflow_generator.md`
   - Logs warning when triggered

2. **_build_prompt() method** (src/pflow/planning/nodes.py:1765-1830)
   - Loads the old `workflow_generator.md` prompt
   - Builds prompt with planning_context and discovered_params
   - Only called from legacy fallback path

### Files to Move
1. `src/pflow/planning/prompts/workflow_generator.md` → `archive/`
2. `tests/test_planning/llm/prompts/test_workflow_generator_prompt.py` → `archive/`

## Implementation Steps

### Step 1: Create Archive Directories
```bash
mkdir -p src/pflow/planning/prompts/archive
mkdir -p tests/test_planning/llm/prompts/archive
```

### Step 2: Move Files to Archive
```bash
# Move the old prompt
git mv src/pflow/planning/prompts/workflow_generator.md \
       src/pflow/planning/prompts/archive/workflow_generator.md

# Move the old test
git mv tests/test_planning/llm/prompts/test_workflow_generator_prompt.py \
       tests/test_planning/llm/prompts/archive/test_workflow_generator_prompt.py
```

### Step 3: Update WorkflowGeneratorNode

Remove the legacy fallback path and `_build_prompt` method:

```python
# In src/pflow/planning/nodes.py, WorkflowGeneratorNode.exec()

# REMOVE lines ~1598-1620 (the else block)
else:
    # FALLBACK: Legacy path for backward compatibility
    logger.warning(...)
    if not prep_res["planning_context"]:
        raise ValueError(...)
    prompt = self._build_prompt(prep_res)
    ...

# REPLACE WITH:
else:
    # No context available - this should not happen in normal flow
    raise ValueError(
        "WorkflowGeneratorNode requires either planner_extended_context "
        "or planner_accumulated_context from PlanningNode. "
        "Ensure the workflow goes through PlanningNode first."
    )

# REMOVE the entire _build_prompt method (lines ~1765-1830)
```

### Step 4: Add README to Archive Folders

Create `src/pflow/planning/prompts/archive/README.md`:
```markdown
# Archived Prompts

This directory contains prompts that are no longer used in production but are kept for historical reference.

## workflow_generator.md
- **Deprecated**: Task 52 (2025-09-10)
- **Replaced by**: workflow_generator_instructions.md and workflow_generator_retry.md
- **Reason**: Moved to cache-optimized context architecture with PlannerContextBuilder
- **Last used in**: Legacy fallback path for direct WorkflowGeneratorNode usage
```

Create `tests/test_planning/llm/prompts/archive/README.md`:
```markdown
# Archived Tests

This directory contains tests for deprecated prompts.

## test_workflow_generator_prompt.py
- **Deprecated**: Task 52 (2025-09-10)
- **Replaced by**: test_workflow_generator_context_prompt.py
- **Reason**: Tests the new cache-optimized context architecture
- **Note**: Original test used legacy prompt without context blocks
```

### Step 5: Update Imports (if any)

Check and update any imports:
```bash
# These should return nothing after the move:
grep -r "from.*test_workflow_generator_prompt" tests/
grep -r "import.*test_workflow_generator_prompt" tests/
```

### Step 6: Test the Changes

1. Run the planning tests to ensure nothing breaks:
```bash
make test TEST_PATH=tests/test_planning/
```

2. Run the new workflow generator tests:
```bash
RUN_LLM_TESTS=1 uv run pytest tests/test_planning/llm/prompts/test_workflow_generator_context_prompt.py -n auto
```

3. Verify planner flow still works:
```bash
uv run pflow run "create a changelog from github issues"
```

## Benefits of Removal

1. **Cleaner Code**: Removes ~65 lines of legacy code
2. **Single Path**: Forces all workflow generation through the new context architecture
3. **Better Error Messages**: Clear error if context is missing
4. **Consistency**: All generation uses the same prompt structure
5. **Maintainability**: One less code path to maintain

## Rollback Plan

If issues arise:
1. Git revert the commit
2. Move files back from archive
3. Restore the legacy fallback code

## Notes

- The legacy path was a safety net during Task 52 implementation
- Now that the new context architecture is tested and working (100% test accuracy), it's safe to remove
- The archived files remain available for reference if needed