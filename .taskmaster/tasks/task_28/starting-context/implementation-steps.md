# Task 28 Implementation Steps

## Pattern for Improving Each Prompt

Based on the successful discovery prompt improvement (52.6% → 83%), follow these steps for each remaining prompt:

### Phase 1: Analysis and Baseline

1. **Establish Baseline Accuracy**
   ```bash
   # Run accuracy test to get current performance
   uv run python tools/test_prompt_accuracy.py [prompt_name] --model gpt-5-nano
   ```

2. **Analyze Test Failures**
   ```bash
   # Run specific failing tests to understand patterns
   RUN_LLM_TESTS=1 PFLOW_TEST_MODEL=gpt-5-nano uv run pytest tests/test_planning/llm/prompts/test_[prompt]_prompt.py -v
   ```

3. **Examine Context Provision**
   - What data does the node receive in prep()?
   - What context is built for the prompt?
   - What information is missing for good decisions?

### Phase 2: Context Enhancement

4. **Identify Missing Information**
   - For discovery: node flows, capabilities, use cases were missing
   - For other prompts: determine what's needed

5. **Enhance Context Builder (if needed)**
   - Add structured data to context
   - Make information easily parseable
   - Use consistent formatting

6. **Verify Data Flow**
   - Ensure data reaches the prompt
   - Check for architectural issues (like metadata not being saved)
   - Fix any data pipeline problems

### Phase 3: Prompt Improvement

7. **Apply Improvement Patterns**

   **Pattern A: Structured Decision Process**
   ```markdown
   ## Your Task
   [Clear role]

   ## Decision Process
   ### Step 1: Understand [Input]
   ### Step 2: Examine [Evidence]
   ### Step 3: Make [Decision]
   ```

   **Pattern B: Evidence Hierarchy**
   ```markdown
   The **[Primary Evidence]** field is your MAIN guide.
   Supporting evidence:
   - **[Secondary]**: [what it confirms]
   ```

   **Pattern C: Concrete Examples**
   ```markdown
   Return X when:
   - [Specific scenario 1]
   - [Specific scenario 2]
   ```

8. **Remove Contradictions**
   - Eliminate conflicting instructions
   - Make decision criteria clear
   - Prefer "false" when uncertain

### Phase 4: Test Refinement

9. **Analyze Test Quality**
   - Are tests redundant?
   - Do they focus on the right metrics?
   - Is each test distinct?

10. **Refine Test Suite**
    - Remove redundant tests (like 5 performance tests → 1)
    - Focus on decision correctness
    - Add clear rationales
    - Aim for 10-15 high-quality tests

11. **Enable Parallel Execution**
    ```python
    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_scenario(self, fixture, test_case):
        # Test implementation
    ```

12. **Implement Failure Reporting**
    ```python
    def report_failure(test_name: str, failure_reason: str):
        # Real-time failure reporting for parallel execution
    ```

### Phase 5: Validation

13. **Run Accuracy Tests**
    ```bash
    # Test with cheap model for iteration
    uv run python tools/test_prompt_accuracy.py [prompt_name] --model gpt-5-nano

    # Validate with better model
    uv run python tools/test_prompt_accuracy.py [prompt_name]
    ```

14. **Verify Performance**
    - Should complete in <10 seconds with parallel execution
    - Cost should be <$0.01 with gpt-5-nano

15. **Document Changes**
    - Update progress log with results
    - Note what patterns worked
    - Record lessons learned

## Specific Considerations per Prompt

### component_browsing.md
- Needs clear node/workflow descriptions
- Should understand capabilities
- May need enhanced registry metadata

### parameter_discovery.md
- Needs to identify implicit parameters
- Should handle various phrasings
- May need examples of parameter patterns

### parameter_mapping.md
- Needs clear parameter schemas
- Should understand type compatibility
- May need validation rules

### workflow_generator.md
- Most complex prompt
- Needs clear node interfaces
- Should understand edge creation rules
- May need step-by-step generation process

### metadata_generation.md
- Needs understanding of workflow purpose
- Should extract keywords effectively
- May need capability detection patterns

## Success Criteria

Each improved prompt must achieve:
- ✅ >80% accuracy on test suite
- ✅ <10 second test execution
- ✅ <$0.01 test cost with gpt-5-nano
- ✅ Clear, non-contradictory instructions
- ✅ Focus on measurable decisions