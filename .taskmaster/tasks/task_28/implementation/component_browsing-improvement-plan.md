# Component Browsing Prompt Improvement Plan

## Current State Analysis

### Baseline Metrics
- **Accuracy**: 0.0% (no proper behavioral tests)
- **Test Structure**: 1 basic integration test, not parametrized
- **Test Cost**: $0.0010 (test ran but no accuracy measurement)
- **Test Duration**: 12.2s (not optimized for parallel execution)

### Root Cause Analysis

**Problem Layers Identified:**

1. **Test Infrastructure Issue** (Primary)
   - No parametrized test cases for accuracy measurement
   - Missing behavioral tests focusing on component selection decisions
   - No real-time failure reporting for parallel execution

2. **Prompt Structure Issue** (Secondary)
   - Vague, unstructured instructions ("BE OVER-INCLUSIVE")
   - No decision process or evidence hierarchy
   - No concrete examples or selection criteria
   - Basic "select everything" approach without guidance

3. **Context Provision Issue** (Potential)
   - `nodes_context` may lack rich details (interfaces, capabilities)
   - Unlike discovery prompt which shows "node flows", component browsing only has descriptions
   - May need enhanced node metadata for better selection decisions

## Improvement Strategy

### Phase 1: Test Suite Creation (Priority 1)
**Goal**: Create proper behavioral test suite following test_discovery_prompt.py pattern

**Actions**:
1. Replace current basic integration test with parametrized behavioral tests
2. Create 10-15 focused test cases covering different selection scenarios:
   - **Core Selections**: Clear node/workflow matches
   - **Edge Cases**: Ambiguous requests requiring judgment
   - **Over-inclusion Tests**: Verify over-inclusive approach works correctly
   - **Context Tests**: Test with different available components
   - **Integration Tests**: Test with both nodes and workflows

3. Implement required infrastructure:
   - `@pytest.mark.parametrize` pattern
   - `get_test_cases()` function with TestCase dataclass
   - `report_failure()` for real-time feedback
   - Behavioral assertions (selected components, not confidence scores)

**Test Categories Planned**:
- **File Operations**: "copy files" → should select file nodes
- **Data Processing**: "analyze CSV" → should select file + llm nodes
- **GitHub Workflows**: "create PR" → should select github nodes + existing workflows
- **Complex Projects**: "full pipeline" → should select multiple node types
- **Ambiguous Requests**: "process data" → test over-inclusive selection

### Phase 2: Context Investigation (If Needed)
**Goal**: Determine if nodes_context needs enrichment like discovery prompt

**Actions**:
1. Run initial test suite to see specific failure patterns
2. Analyze if failures are due to insufficient node information
3. Compare nodes_context with workflows_context richness
4. If needed, enhance build_nodes_context() to include:
   - Node interfaces (inputs/outputs like workflow flows)
   - Node capabilities (what they can do)
   - Use case examples (when to use them)

**Decision Criteria**: Only enhance if test failures show LLM can't distinguish between node purposes

### Phase 3: Prompt Improvement (Core Focus)
**Goal**: Apply proven patterns from discovery prompt improvement

**Actions**:
1. **Structured Decision Process**:
   ```markdown
   ## Your Task
   [Clear role as "component selector" for workflow generation]

   ## Selection Process
   ### Step 1: Understand the Request
   ### Step 2: Examine Available Components
   ### Step 3: Make Selections
   ```

2. **Evidence Hierarchy**:
   ```markdown
   The **Available Nodes** section shows individual building blocks.
   The **Available Workflows** section shows complete solutions you can reuse.

   Primary evidence: Direct capability match
   Supporting evidence: Complementary functionality
   ```

3. **Concrete Selection Criteria**:
   ```markdown
   Include nodes when:
   - Request directly mentions the functionality (e.g., "read file" → read-file)
   - Node provides supporting capability (e.g., error handling, logging)
   - Request implies the need (e.g., "analyze" → llm node)

   Include workflows when:
   - Workflow partially matches request (can be building block)
   - Workflow demonstrates relevant patterns
   ```

4. **Over-inclusive Guidance**:
   Replace vague "BE OVER-INCLUSIVE" with specific guidance:
   ```markdown
   Selection Philosophy: Better to include extra components than miss critical ones.
   When uncertain: Include the component and explain why in reasoning.
   ```

### Phase 4: Test Execution and Iteration (Validation)
**Goal**: Achieve >80% accuracy through test-driven improvement

**Actions**:
1. Run test suite with gpt-5-nano for fast iteration
2. Identify failure patterns and iterate on prompt
3. Enhance context if needed based on failures
4. Refine test cases based on real behavior
5. Final validation with better model

**Success Metrics**:
- >80% accuracy on behavioral test suite
- <10 seconds test execution with parallel workers
- <$0.01 cost per test run with gpt-5-nano
- Clear decision-making process observable in test results

## Implementation Order

### Step 1: Create Test Suite (Immediate)
- Write test_component_browsing_prompt.py following exact pattern from test_discovery_prompt.py
- Define TestCase dataclass for component selection scenarios
- Implement get_test_cases() with 10-15 diverse scenarios
- Add report_failure() and parametrization infrastructure

### Step 2: Run Initial Tests (Debug Phase)
- Execute tests with current prompt to establish real baseline
- Document specific failure patterns
- Identify if context enhancement needed

### Step 3: Improve Prompt (Core Work)
- Apply structured decision process pattern
- Add concrete selection criteria and examples
- Replace vague guidance with specific instructions
- Test iteratively with gpt-5-nano

### Step 4: Context Enhancement (If Needed)
- Only if tests show context is insufficient
- Enhance build_nodes_context() with richer information
- Follow pattern from discovery prompt success

### Step 5: Final Validation (Achievement)
- Validate >80% accuracy with test suite
- Confirm performance and cost metrics
- Document improvement patterns for other prompts

## Risk Mitigation

### Risk 1: Test Suite Complexity
**Mitigation**: Start with 10 simple test cases, expand based on failures
**Fallback**: Focus on core scenarios first, add edge cases later

### Risk 2: Context Enhancement Required
**Mitigation**: Test current context first, enhance only if needed
**Fallback**: Use discovery prompt enhancement pattern if needed

### Risk 3: Prompt Over-complexity
**Mitigation**: Apply "simple beats clever" principle from epistemic manifesto
**Fallback**: Prefer clear, boring instructions over sophisticated logic

## Expected Timeline

- **Test Suite Creation**: 2-3 hours
- **Initial Testing & Analysis**: 1 hour
- **Prompt Improvement**: 2-3 hours
- **Context Enhancement** (if needed): 1-2 hours
- **Final Validation**: 1 hour

**Total**: 6-10 hours depending on context enhancement needs

## Success Definition

**Must Achieve**:
- >80% accuracy on component selection test suite
- <10 second parallel test execution
- <$0.01 test cost with gpt-5-nano
- Proper parametrized test structure
- Real-time failure reporting

**Should Achieve**:
- Clear selection reasoning in test results
- Over-inclusive approach working correctly
- Test cases covering diverse scenarios
- Pattern established for other prompt improvements

This plan follows the proven methodology from discovery prompt improvement while addressing the specific needs of component browsing functionality.