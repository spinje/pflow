# Implementation Plan: Fix Workflow Outputs with Namespacing

## Problem Summary
Workflow outputs cannot access namespaced node outputs. With namespacing enabled (default), nodes write to `shared[node_id][key]`, but workflow outputs expect root-level keys. There's no mechanism to map namespaced values to declared outputs.

## Solution Overview
Add a `source` field to workflow outputs that uses template expressions to specify where to get the output value from. This creates an explicit mapping from namespaced values to workflow outputs.

## Implementation Plan

### Phase 1: Schema Update ✅ COMPLETED
- Added `source` field to outputs schema in `ir_schema.py`
- Field is optional to maintain backward compatibility
- Accepts template expressions like `${node_id.output_key}`

### Phase 2: Output Population Logic (CLI-side)

#### 2.1 Create Output Population Function
**Location**: `src/pflow/cli/main.py`

Create a new function `_populate_workflow_outputs()` that:
1. Takes the workflow IR and shared store after execution
2. For each declared output with a `source` field:
   - Use TemplateResolver to resolve the source expression
   - Write the resolved value to `shared[output_name]` at root level
3. Handle missing sources gracefully (warn, don't fail)
4. Return the populated shared store

**Why CLI-side?**
- The compiler only creates the Flow, doesn't execute it
- The CLI is where execution happens (`flow.run(shared)`)
- The CLI already handles output extraction logic
- Keeps the compiler focused on compilation, not execution

#### 2.2 Integration Points
Modify the `run` command flow:
1. Execute workflow: `flow.run(shared_storage)`
2. **NEW**: Populate outputs: `_populate_workflow_outputs(ir_dict, shared_storage)`
3. Extract outputs: `_try_declared_outputs()` (existing, will now find populated values)

### Phase 3: Template Resolution Context

#### 3.1 Prepare Resolution Context
The template resolution context needs:
- The full shared store (including all namespaces)
- Initial params (workflow inputs)
- Special handling for nested paths like `${node.key.subkey}`

#### 3.2 Error Handling Strategy
- **Missing source**: Log warning, skip output (don't fail workflow)
- **Invalid template**: Log warning with details, skip output
- **Circular reference**: Unlikely but check for it
- **Type mismatch**: Just copy the value as-is

### Phase 4: Testing Strategy

#### 4.1 Unit Tests
**File**: `tests/test_cli/test_workflow_output_population.py`
- Test output population with valid sources
- Test missing source handling
- Test invalid template handling
- Test nested path resolution
- Test backward compatibility (outputs without source)

#### 4.2 Integration Tests
**File**: `tests/test_integration/test_outputs_with_namespacing.py`
- Full workflow with namespacing and outputs
- Multiple nodes writing to same keys (collision scenario)
- Nested workflows with output mapping
- CLI pipe integration with populated outputs

#### 4.3 Edge Cases to Test
1. Output source references non-existent node
2. Output source references non-existent key
3. Output without source field (backward compat)
4. Multiple outputs from same source
5. Complex template expressions
6. Binary data in outputs

### Phase 5: Planner Prompt Updates

#### 5.1 Update workflow_generator.md
Add clear instructions:
```markdown
When declaring workflow outputs, you MUST specify where each output comes from using the 'source' field:

"outputs": {
  "result": {
    "description": "The final result",
    "source": "${node_id.output_key}"  // REQUIRED with namespacing
  }
}
```

#### 5.2 Add Examples
Show concrete examples of:
- Single node output: `"source": "${generate.response}"`
- Nested path: `"source": "${fetch.data.title}"`
- Multiple outputs from different nodes

### Phase 6: Documentation Updates

#### 6.1 Update automatic-namespacing.md
Add section on workflow outputs explaining:
- The need for explicit source mapping
- How to use the source field
- Migration guide for existing workflows

#### 6.2 Create workflow-outputs.md
Comprehensive guide covering:
- Output declaration syntax
- Source field usage
- Integration with namespacing
- Best practices

### Phase 7: Verification

#### 7.1 Test Original Failing Workflow
```bash
uv run pflow "create a workflow that uses an llm to create a very short story about llamas and saves it to a file"
```
Should now:
1. Generate valid IR with source fields
2. Execute successfully
3. Populate outputs correctly
4. Return story content and file confirmation

#### 7.2 Test Suite Execution
```bash
make test
make check
```
Ensure no regressions in existing functionality.

## Implementation Order

1. **First**: Implement output population logic (Phase 2)
   - Core functionality to make outputs work

2. **Second**: Add comprehensive tests (Phase 4)
   - Verify the solution works correctly

3. **Third**: Update planner prompts (Phase 5)
   - Enable LLM to generate correct IR

4. **Fourth**: Test with original workflow (Phase 7)
   - Validate end-to-end fix

5. **Finally**: Documentation (Phase 6)
   - Document the feature for users

## Risk Mitigation

### Backward Compatibility
- Outputs without `source` continue to work (look for root-level keys)
- Add deprecation warning for outputs without source when namespacing is enabled
- Provide clear migration path in documentation

### Performance Impact
- Template resolution is already optimized
- Output population happens once after execution
- Minimal overhead (milliseconds for typical workflows)

### Error Recovery
- Never fail workflow due to output issues
- Always log clear warnings with actionable fixes
- Provide debug mode for detailed output tracing

## Success Criteria

1. ✅ Workflows with namespaced outputs execute successfully
2. ✅ LLM generates valid IR with source fields
3. ✅ All existing tests pass
4. ✅ New tests cover edge cases
5. ✅ Documentation clearly explains the feature
6. ✅ Original failing workflow works correctly

## Alternative Approaches Considered

### 1. Auto-Detection (Rejected)
Try to automatically find outputs in namespaces.
- **Pro**: No schema change needed
- **Con**: Ambiguous with multiple nodes, magical behavior

### 2. Disable Namespacing (Rejected)
Make namespacing opt-in instead of default.
- **Pro**: Outputs work as originally designed
- **Con**: Loses collision prevention, major breaking change

### 3. Output Nodes (Rejected)
Require special nodes to write outputs.
- **Pro**: Explicit control
- **Con**: Adds complexity, breaks existing patterns

### 4. Compiler-Side Population (Rejected)
Populate outputs in the compiler.
- **Pro**: Centralized logic
- **Con**: Compiler doesn't execute flows, wrong layer

## Conclusion

The `source` field approach is the cleanest solution because it:
- Makes data flow explicit and traceable
- Aligns with the LLM's intuition
- Mirrors existing patterns (nested workflow output_mapping)
- Maintains backward compatibility
- Solves the problem completely

This plan addresses the root cause while maintaining system coherence and user experience.