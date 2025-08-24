# Task 38: Support Branching in Generated Workflows

## Overview

Enable the pflow planner to generate workflows with conditional branching using PocketFlow's existing action-based transition support. The runtime already supports branching through the `node - "action" >> target` syntax, but the planner's workflow generator prompt explicitly prohibits it.

## Current State Analysis

### What Already Works ✅

1. **Runtime Support**: The compiler (`src/pflow/runtime/compiler.py`) already handles action-based transitions:
   ```python
   # Line 374-378 in compiler.py
   if action == "default":
       source >> target
   else:
       source - action >> target
   ```

2. **PocketFlow Framework**: Fully supports conditional transitions via:
   - `node >> target` for default transitions
   - `node - "action" >> target` for conditional transitions
   - Action strings returned from `post()` method control flow

3. **IR Schema**: Already supports action field in edges:
   ```json
   {"from": "node1", "to": "node2", "action": "error"}
   ```

4. **Example Files**: `examples/core/error-handling.json` demonstrates working branching

### What's Missing ❌

1. **Planner Restrictions**: The workflow generator prompt (`src/pflow/planning/prompts/workflow_generator.md:189`) explicitly states:
   ```
   - Linear execution only (no branching)
   ```

2. **Test Coverage**: Branching tests exist but are incomplete:
   - `test_runtime/test_compiler_integration.py` has branching fixtures
   - Tests don't verify actual branching behavior

3. **Documentation Conflicts**:
   - `CLAUDE.md:98` lists conditional transitions as "Excluded from MVP"
   - `CLAUDE.md:143` mentions "action-based transitions" in Execution Engine
   - `mvp-implementation-guide.md:480` states "Linear before conditional - No branching logic in MVP"

### The Problem

As discovered in Task 28's analysis (`branching-analysis.md`), the LLM naturally creates branching workflows because:

1. **User requests imply parallelism**: "analyze data AND generate visualizations"
2. **Efficiency**: Why serialize operations that could branch?
3. **JSON structure allows it**: Multiple edges from one node is valid
4. **Real-world workflows need it**: Error handling, retries, conditional logic

Current test failures show the LLM creates branching in ~30% of complex workflows despite being told not to.

## Scope of Task 38

### In Scope ✅

1. **Enable Simple Branching**: Allow workflows where:
   - One node can have multiple outgoing edges with different actions
   - Actions control which path is taken at runtime
   - Example: `node - "error" >> error_handler` and `node >> success_path`

2. **Update Planner Prompts**:
   - Remove "Linear execution only" restriction
   - Add examples of proper branching patterns
   - Document which actions nodes commonly return

3. **Add Comprehensive Tests**:
   - Test actual branching execution (not just compilation)
   - Verify correct path selection based on actions
   - Test error handling and retry patterns

4. **Update Documentation**:
   - Clarify that conditional branching IS supported in MVP
   - Document the action-based transition pattern
   - Add branching examples to workflow documentation

### Out of Scope ❌

1. **Parallel Execution**: PocketFlow can't execute multiple branches simultaneously:
   ```python
   # This overwrites - only one path executes
   node >> target1
   node >> target2  # Overwrites previous edge!
   ```

2. **Complex DAGs**: No support for:
   - Reconverging branches (diamond patterns)
   - True parallel processing
   - Async/await patterns

3. **New Runtime Features**: No changes to PocketFlow or compiler needed

## Implementation Plan

### Phase 1: Update Workflow Generator Prompt

1. **Remove Linear-Only Restriction** (`workflow_generator.md`)
   - Delete "Linear execution only (no branching)" constraint
   - Add section on conditional transitions

2. **Add Branching Examples**:
   ```json
   {
     "edges": [
       {"from": "process", "to": "success", "action": "default"},
       {"from": "process", "to": "retry", "action": "retry"},
       {"from": "process", "to": "error_log", "action": "error"}
     ]
   }
   ```

3. **Document Common Action Patterns**:
   - "default" - Normal flow continuation
   - "error" - Error handling path
   - "retry" - Retry logic
   - "skip" - Conditional skipping
   - Custom actions from node implementations

### Phase 2: Enhance Test Coverage

1. **Fix Existing Branching Tests** (`test_compiler_integration.py`)
   - Actually verify which path was taken
   - Test all action types

2. **Add Planner Tests**:
   - Test that generator creates appropriate branching
   - Verify action fields are properly set
   - Test error handling workflows

3. **End-to-End Tests**:
   - Complete workflow with error handling
   - Retry patterns
   - Conditional processing

### Phase 3: Update Documentation

1. **Fix Documentation Conflicts**:
   - Update CLAUDE.md to show branching IS in MVP
   - Update mvp-implementation-guide.md
   - Add branching to feature list

2. **Add Usage Examples**:
   - Error handling patterns
   - Retry logic
   - Conditional processing
   - Decision trees

## Success Criteria

1. **Planner generates branching workflows** when appropriate (error handling, retries, conditions)
2. **All branching tests pass** including actual execution verification
3. **Documentation is consistent** - no more conflicts about MVP scope
4. **Complex test cases pass** like `data_analysis_pipeline` that naturally need branching

## Technical Considerations

### PocketFlow Limitations

- Only ONE path executes per run (determined by action string)
- No parallel execution (can't run multiple branches simultaneously)
- Last edge wins if multiple edges have same action

### Best Practices for Branching

1. **Always include default path**: Ensure there's a fallback
2. **Document action meanings**: Clear what triggers each branch
3. **Test all paths**: Each branch needs test coverage
4. **Keep branches simple**: Avoid complex reconverging patterns

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Users expect parallel execution | High | Clear documentation that branches are conditional, not parallel |
| Complex DAGs attempted | Medium | Validation to reject reconverging branches |
| Action string typos | Low | Runtime warnings for unmatched actions |

## Dependencies

- No external dependencies
- Builds on existing runtime support
- Compatible with current IR schema

## Estimated Effort

- **Low Complexity**: Runtime already supports it
- **Main Work**: Prompt updates and testing
- **Time Estimate**: 2-4 hours

## Notes from Task 28 Analysis

The LLM creates branching because it makes logical sense. Instead of fighting this natural tendency, we should embrace it within PocketFlow's capabilities. The runtime already supports conditional branching - we just need to allow the planner to use it.

Key insight: "Linear only" was likely a simplification for initial implementation, but the infrastructure for branching has been there all along.
