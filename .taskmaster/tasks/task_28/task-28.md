# Task 28: Improve Performance of Planner Prompts

## Description
Systematically improve all planner node prompts for accuracy, clarity, and cost-effectiveness. Refine corresponding test suites to focus on decision correctness with parallel execution support. Integrate with the prompt accuracy tracking system (`tools/test_prompt_accuracy.py`) to measure improvements quantitatively.

## Status
done

## Completed
2025-08-24

## Dependencies
- Task 33: Extract Planner Prompts to Markdown Files - Prompts must be in markdown format for testing
- Task 34: Prompt Accuracy Tracking System - Provides measurement infrastructure
- Task 17: Natural Language Planner System - The planner that uses these prompts

## Priority
high

## Details

The planner's effectiveness depends on the quality of prompts used by each node. Initial testing showed poor accuracy (52.6% for discovery), indicating prompts need systematic improvement. This task improves both prompts and their test suites to achieve >80% accuracy across all planner nodes.

### Core Problems Being Solved

1. **Poor Prompt Accuracy**: Discovery at 52.6%, others untested
2. **Insufficient Context**: Prompts lack critical information for decisions
3. **Test Quality Issues**: Tests focus on wrong metrics (confidence scores vs decisions)
4. **Test Efficiency**: Serial execution takes too long for iteration
5. **Unclear Instructions**: Prompts have contradictory or vague guidance

### Prompts to Improve

Located in `src/pflow/planning/prompts/`:

1. **discovery.md** ✅ - Improved from 52.6% to 100%
2. **component_browsing.md** ✅ - Improved from 16.7% to 91.7%
3. **parameter_discovery.md** ✅ - Achieved 85.7% (gpt-5-nano) / 100% (Claude) with HARD tests
4. **parameter_mapping.md** ✅ - Achieved 80% accuracy
5. **workflow_generator.md** ✅ - Improved from 53.8% to 100% (with test fixes)
6. **metadata_generation.md** ✅ - Achieved 90% accuracy

### Improvement Strategy

#### Phase 1: Discovery Prompt (COMPLETED)
- **Problem**: LLM matching workflows with minimal context
- **Solution**: Added node flows, capabilities, use cases to context
- **Architecture Fix**: Separated metadata from IR for clean storage
- **Test Refinement**: 19 → 12 high-quality tests, focus on decisions
- **Result**: 52.6% → 100% accuracy

#### Phase 2: Component Browsing (COMPLETED)
- **Problem**: Poor component selection accuracy
- **Solution**: Domain awareness + workflow pattern recognition
- **Test Refinement**: 19 → 12 focused test cases
- **Result**: 16.7% → 91.7% accuracy

#### Phase 3: Metadata Generation (COMPLETED)
- **Problem**: Specific values leaking into metadata
- **Solution**: Parameter transformation + purpose fields + rich context
- **Architecture**: Added purpose field to nodes, implemented parameter transformation
- **Test Fix**: Tests now simulate full pipeline with extracted_params
- **Result**: Achieved 90% accuracy

#### Phase 4: Parameter Prompts (COMPLETED)

**Critical Insight**: Test quality matters more than quantity. Created HARD tests that actually challenge the system.

- **parameter_discovery.md**:
  - Created 7 HARD tests for challenging scenarios (ambiguity, boundaries, vague quantifiers)
  - Result: 85.7% (gpt-5-nano), 100% (Claude Sonnet)

- **parameter_mapping.md**:
  - Strict parameter mapping with exact names
  - Result: 80% accuracy (both models)

#### Phase 5: Workflow Generator (COMPLETED)

**Key Discovery**: LLMs naturally generate parallel workflows, which revealed the need for future Tasks 38 & 39.

- **workflow_generator.md**:
  - Added explicit sequential execution requirements
  - Fixed test design issues (ambiguous inputs, conflicting context)
  - Result: 53.8% → 100% accuracy (after test improvements)

For each prompt:

1. **Analyze Current Performance**
   - Run accuracy tests to establish baseline
   - Identify failure patterns
   - Determine what information is missing

2. **Improve Context Provision**
   - Add relevant structured data (like node flows for discovery)
   - Remove ambiguous instructions
   - Add clear decision criteria

3. **Refine Test Suite**
   - Quality over quantity (aim for 10-15 tests)
   - Focus on decision correctness
   - Remove redundant tests
   - Add clear rationales

4. **Enable Parallel Testing**
   - Use pytest parametrization
   - Implement immediate failure reporting
   - Support PARALLEL_WORKERS environment variable

### Test Framework Requirements

Each test file must:

1. **Support Parallel Execution**
```python
@pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
def test_scenario(self, fixture, test_case):
    # Individual test execution
```

2. **Report Failures Immediately**
```python
FAILURE_OUTPUT_FILE = os.environ.get("PFLOW_TEST_FAILURE_FILE")

def report_failure(test_name: str, failure_reason: str):
    if FAILURE_OUTPUT_FILE:
        failure_data = {"test": test_name, "reason": failure_reason, "timestamp": time.time()}
        with open(FAILURE_OUTPUT_FILE, 'a') as f:
            f.write(json.dumps(failure_data) + '\n')
```

3. **Focus on Decisions, Not Scores**
```python
# Primary: Check decision correctness
decision_correct = actual_decision == expected_decision

# Secondary: Log confidence for info
logger.info(f"{test_name}: confidence={confidence:.2f}")

# Don't fail on confidence ranges
test_passed = decision_correct  # Not confidence_correct
```

### Prompt Improvement Patterns

#### Pattern 1: Structured Decision Process
```markdown
## Your Task
[Clear role definition]

## Decision Process
### Step 1: [Understand Input]
### Step 2: [Examine Evidence]
### Step 3: [Make Decision]

## Return X when:
[Clear criteria]

## Return Y when:
[Clear criteria]
```

#### Pattern 2: Evidence-First Approach
```markdown
The **[Primary Evidence]** field shows [what it means].
This is your PRIMARY evidence for decisions.

Supporting evidence:
- **[Secondary]**: [what it confirms]
- **[Tertiary]**: [additional context]
```

#### Pattern 3: Concrete Examples
Instead of abstract rules, provide specific examples:
```markdown
## Return false when:
- User needs X but workflow only has Y
- Wrong data source (e.g., PRs when flow uses issues)
- Request too vague (e.g., "analyze data")
```

### Integration with test_prompt_accuracy.py

The tool provides:
- Automatic accuracy tracking in frontmatter
- Cost tracking per test run
- Model override for testing (`--model gpt-5-nano`)
- Parallel execution support
- Version management when prompts change

Usage:
```bash
# Test with default model (expensive but accurate)
uv run python tools/test_prompt_accuracy.py discovery

# Test with cheap model (fast iteration)
uv run python tools/test_prompt_accuracy.py discovery --model gpt-5-nano

# Dry run without updating metrics
uv run python tools/test_prompt_accuracy.py discovery --dry-run
```

### Success Metrics

For each prompt:
- **Accuracy**: >80% on test suite
- **Test Quality**: Each test validates something distinct
- **Performance**: <10 seconds with parallel execution
- **Cost**: <$0.01 per test run with gpt-5-nano

### Implementation Order

1. ✅ **discovery.md** - Workflow matching (100% accuracy)
2. ✅ **component_browsing.md** - Node/workflow selection (91.7% accuracy)
3. ✅ **parameter_discovery.md** - Parameter extraction (85.7-100% accuracy)
4. ✅ **parameter_mapping.md** - Parameter assignment (80% accuracy)
5. ✅ **workflow_generator.md** - IR generation (100% accuracy)
6. ✅ **metadata_generation.md** - Metadata creation (90% accuracy)

## Patterns Established

### Key Architectural Improvements
1. **Purpose Fields**: Added to nodes for semantic understanding at creation time
2. **Parameter Transformation**: Replace values with [parameter_name] placeholders to prevent leakage
3. **Test Pipeline Simulation**: Tests must include extracted_params to simulate real pipeline
4. **Context > Instructions**: Better data provision beats better prompt wording

### Discovery Prompt Improvements
1. **Rich Context**: Added node flows, capabilities, use cases
2. **Clean Architecture**: Metadata separated from IR
3. **Flow-First**: Node flow as primary evidence
4. **Pragmatic Tests**: Decision correctness over confidence

### Metadata Generation Improvements
1. **Parameter Transformation**: Prevents specific value leakage elegantly
2. **Purpose + Flow + Inputs**: Complete semantic understanding
3. **Test Fix**: Include extracted_params to simulate ParameterMappingNode output
4. **90% Accuracy**: Excellent metadata generation achieved

### Workflow Generator Improvements
1. **Sequential Enforcement**: Clear visual examples of linear vs parallel
2. **Test Philosophy Change**: Test instruction-following, not improvisation
3. **Context Filtering**: Validation recovery tests only see browsed nodes
4. **100% Accuracy**: Perfect workflow generation after test fixes

### Test Improvements
1. **Quality Over Quantity**: 10-15 high-quality tests per prompt
2. **Semantic Matching**: Accept variations like "prioritize" for "priority"
3. **Pipeline Simulation**: Tests must match real data flow
2. **Parallel Execution**: 120s → 10s execution time
3. **Real-Time Feedback**: Immediate failure reporting
4. **Focus on Decisions**: Not confidence scores

### Context Builder Improvements
1. **Compact Format**: Readable but efficient
2. **Full Information**: No truncation
3. **Structured Display**: Clear hierarchy of information

## Current Progress

### Completed
- Discovery prompt improved (52.6% → 83%)
- Component browsing improved (16.7% → 91.7%)
- Parameter discovery achieved (85.7-100% with HARD tests)
- Parameter mapping achieved (80% accuracy)
- Metadata generation achieved (100% accuracy)
- Test framework supports parallel execution
- Context builder provides rich information
- Clean metadata architecture

### Key Achievement
Created HARD tests that actually challenge the system and differentiate model quality, proving that test quality matters more than test quantity.

## Key Lessons

1. **Context is Critical**: LLMs need rich, structured information
2. **Tests Should Measure Decisions**: Not confidence scores
3. **Quality Over Quantity**: 12 good tests > 19 mediocre ones
4. **HARD Tests Reveal Truth**: Easy tests give false confidence; hard tests show real capability
5. **Node Flows Are Truth**: Show what actually happens
6. **Clean Architecture Matters**: Separate concerns properly

## Files to Modify

### Prompts
- `src/pflow/planning/prompts/*.md` - Each prompt file

### Tests
- `tests/test_planning/llm/prompts/test_*_prompt.py` - Each test file

### Supporting
- `src/pflow/planning/context_builder.py` - If more context needed
- `tools/test_prompt_accuracy.py` - Already supports all prompts

## Validation

Each improved prompt must:
1. Pass its test suite with >80% accuracy
2. Complete in <10 seconds with parallel execution
3. Cost <$0.01 per test run with gpt-5-nano
4. Have clear, non-contradictory instructions
5. Focus on observable decisions, not internal confidence

## Future Opportunities

- A/B testing different prompt versions
- Automated prompt optimization
- Cross-model compatibility testing
- Prompt compression for cost reduction
