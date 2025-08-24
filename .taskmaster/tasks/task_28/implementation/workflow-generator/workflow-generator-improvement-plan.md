# Task 28: Workflow Generator Improvement Plan

## Current State Analysis

### Baseline Performance
- **Current Accuracy**: 85.7% (6/7 tests passing)
- **Test Duration**: 38.4s
- **Cost**: $0.0060 with gpt-5-nano
- **Status**: Already exceeds 80% target!

### Test Suite Issues
The current test suite (`test_generator_prompts.py`) has critical problems:
1. **Not parametrized**: Tests don't follow the required pattern for test_prompt_accuracy.py
2. **No behavioral test cases**: Tests check prompt mechanics, not workflow generation quality
3. **No real-time failure reporting**: Missing `report_failure()` function
4. **Tests timeout**: Some tests like `test_prompt_universal_defaults_not_specific` timeout
5. **Not focused on decision correctness**: Tests check implementation details rather than outcomes

### Prompt Analysis
The workflow_generator prompt is already comprehensive but has some areas for improvement:

**Strengths**:
1. Clear distinction between user inputs and node outputs
2. Good examples showing proper template usage
3. Purpose field requirements already included
4. Emphasis on linear workflows
5. Clear validation error handling

**Weaknesses**:
1. Very long and dense - could benefit from clearer structure
2. Multiple overlapping warnings about the same concepts
3. Examples could be more diverse (not just joke generation)
4. Missing guidance on common workflow patterns
5. Could better emphasize the most critical requirements upfront

## Improvement Strategy

### Phase 1: Create Proper Test Suite (Priority 1)
**Why**: Can't properly measure or improve without good tests

1. Create `test_workflow_generator_prompt.py` following test_discovery_prompt.py pattern
2. Focus on behavioral test cases:
   - Template variable usage (no hardcoding)
   - Linear workflow generation (no branching)
   - Purpose field generation
   - Input/output parameter handling
   - Node output references
   - Error recovery from validation failures

3. Test categories:
   - **Core Generation** (3-4 tests): Basic workflow creation
   - **Template Handling** (3-4 tests): Variable usage, no hardcoding
   - **Complex Workflows** (2-3 tests): Multi-step with node references
   - **Edge Cases** (2-3 tests): Error handling, validation recovery

Total: 10-14 high-quality behavioral tests

### Phase 2: Prompt Refinement (If Needed)
Since we're already at 85.7%, only minor refinements:

1. **Restructure for clarity**:
   - Move critical requirements to top
   - Group related concepts
   - Reduce redundancy

2. **Enhance examples**:
   - Add GitHub workflow example (north star)
   - Add data processing example
   - Show node output chaining clearly

3. **Simplify instructions**:
   - Combine overlapping warnings
   - Use clearer section headers
   - Add visual separation

### Phase 3: Validation
1. Run new test suite with multiple models
2. Ensure 85%+ accuracy maintained
3. Verify performance <10s with parallel execution
4. Document improvements in progress log

## Key Insights from Other Prompts

From the handover documents, these patterns have proven successful:

1. **Context is King**: Rich context matters more than prompt wording
2. **Show Don't Tell**: Examples beat descriptions
3. **Test What Matters**: Focus on workflow validity, not format
4. **Gradual Enhancement**: Purpose field shows this works
5. **Quality Over Quantity**: 10 good tests > 20 mediocre ones

## Specific Test Cases to Include

Based on north star examples and common failures:

1. **changelog_generation**: GitHub → LLM → file → git workflow
2. **issue_triage**: GitHub → analysis → report generation
3. **data_processing**: Read → transform → write pattern
4. **simple_task**: Single node with parameters
5. **no_hardcoding**: Verify dynamic values use templates
6. **node_chaining**: Proper ${node.output} references
7. **purpose_quality**: Meaningful purpose fields
8. **input_declaration**: All template vars declared
9. **validation_recovery**: Fix errors on retry
10. **linear_only**: No branching attempted

## Success Criteria

- ✅ Maintain or exceed 85% accuracy
- ✅ Tests complete in <10 seconds with parallel execution
- ✅ Test cost <$0.01 with gpt-5-nano
- ✅ All tests focus on behavioral correctness
- ✅ Real-time failure reporting implemented
- ✅ Tests properly integrated with test_prompt_accuracy.py

## Risk Assessment

**Low Risk**: We're already above target
- Current prompt is working well
- Only need test suite improvements
- Minor prompt refinements are optional

**Mitigation**:
- Keep prompt changes minimal and surgical
- Focus mainly on test quality
- Preserve what's working

## Next Steps

1. Create new parametrized test suite
2. Run baseline with new tests
3. Make minor prompt improvements if patterns emerge
4. Validate improvements
5. Update progress log

The workflow_generator prompt is already performing well. Our main task is to create a proper test suite that accurately measures its capabilities and ensures it continues to work correctly.