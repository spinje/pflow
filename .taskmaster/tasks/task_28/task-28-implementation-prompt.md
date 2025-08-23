# Task 28: Improve Performance of Planner Prompts - Agent Instructions

## The Problem You're Solving

The planner's prompts have poor accuracy, leading to incorrect decisions and failed workflow generation. Users experience frustration when the planner misunderstands their intent or makes wrong choices. The prompts need systematic improvement to achieve reliable, predictable behavior with >80% accuracy on their test suites.

## Your Mission

Select and improve one planner prompt to achieve >80% accuracy by enhancing its context provision, clarifying instructions, and refining its test suite to focus on decision correctness rather than confidence scores.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_28/task-28.md`

**Purpose**: High-level overview of improving planner prompts, the systematic approach, and success metrics. This document provides the framework for understanding what makes a good prompt and how to measure improvement.

**Why read second**: This gives you the big picture of prompt improvement methodology before diving into specific prompt work.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_28/starting-context/`

**Files to read (if they exist):**
- Any documentation about prompt improvement patterns
- Previous implementation logs or summaries
- Test framework documentation
- Important: READ ALL FILES YOURSELF, dont outsource this to a subagents!

**Instructions**: Read EACH file if present. The task overview document is your primary guide for the improvement methodology.

## What You're Building

You're improving one of the six planner prompts to make better decisions with higher accuracy. The prompts are:

1. **discovery.md** - Determines if existing workflows match user requests
2. **component_browsing.md** - Selects nodes/workflows for generation
3. **parameter_discovery.md** - Extracts parameters from user input
4. **parameter_mapping.md** - Maps parameters to workflow inputs
5. **workflow_generator.md** - Generates workflow IR from components
6. **metadata_generation.md** - Creates searchable workflow metadata

Example of what improvement looks like:
```markdown
# Before: Vague instructions
Analyze the request and make a decision.

# After: Structured decision process
## Your Task
[Clear role definition]

## Decision Process
### Step 1: Understand the Input
[Specific analysis steps]

### Step 2: Examine the Evidence
[What to look for and how to evaluate]

### Step 3: Make the Decision
[Clear criteria for each outcome]
```

## Key Outcomes You Must Achieve

### Prompt Improvement
- Baseline accuracy measured and documented
- Context provision enhanced with necessary information
- Instructions clarified with structured decision process
- Contradictions and ambiguity removed
- Concrete examples added where helpful

### Test Suite Enhancement
- Tests refactored to focus on decision correctness
- Redundant tests removed (quality over quantity)
- Parallel execution support added
- Real-time failure reporting implemented
- Target: 10-15 high-quality test cases

### Performance Metrics
- Accuracy: >80% on the test suite
- Execution time: <10 seconds with parallel testing
- Cost: <$0.01 per test run with gpt-5-nano model
- All tests measure observable decisions, not internal confidence

## Implementation Strategy

### Phase 1: Analysis and Baseline (1-2 hours)
1. Select which prompt to improve (coordinate if multiple agents working)
2. Run baseline accuracy test using tools/test_prompt_accuracy.py
3. Analyze test failures to identify patterns
4. Examine what context the prompt currently receives
5. Document baseline metrics in your progress log

### Phase 2: Context Investigation (1-2 hours)
1. Trace the data flow to the prompt
2. Identify what information is missing for good decisions
3. Check if context builder needs enhancement
4. Verify data actually reaches the prompt
5. Document any architectural issues found

### Phase 3: Prompt Improvement (2-3 hours)
1. Apply structured decision process pattern
2. Add evidence hierarchy (primary, secondary, supporting)
3. Include concrete examples of decisions
4. Remove contradictions and ambiguity
5. Make decision criteria explicit and clear

### Phase 4: Test Refinement (2-3 hours)
1. Review existing tests for quality and redundancy
2. Refactor to focus on decision correctness
3. Implement pytest parametrization for parallel execution
4. Add immediate failure reporting
5. Reduce to 10-15 high-quality test cases

### Phase 5: Validation (1 hour)
1. Run accuracy tests with multiple models
2. Verify performance metrics are met
3. Document improvements achieved
4. Create summary of patterns that worked

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Prompt Location and Structure
All prompts are in `src/pflow/planning/prompts/` as markdown files with YAML frontmatter:
```yaml
---
name: prompt_name
test_path: tests/test_planning/llm/prompts/test_prompt_name.py::TestClass
test_command: uv run python tools/test_prompt_accuracy.py prompt_name
version: 1.0
latest_accuracy: XX.X
# ... other metrics maintained by test tool
---

[Prompt content here with {{variables}}]
```

### Test Framework Integration
The `tools/test_prompt_accuracy.py` tool:
- Automatically tracks accuracy in frontmatter
- Supports model override with `--model gpt-5-nano`
- Handles parallel execution with PARALLEL_WORKERS env var
- Updates metrics automatically (unless --dry-run)

### Context Builder Pattern
Context is built in `src/pflow/planning/context_builder.py`:
```python
def build_[context_type]_context(...) -> str:
    # Returns formatted context string for prompt
```

### Test File Structure
Tests must support parallel execution:
```python
@pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
def test_scenario(self, fixture, test_case):
    # Individual test execution

def report_failure(test_name: str, failure_reason: str):
    # Real-time failure reporting
```

## Critical Warnings from Experience

### Data Flow Is Critical
Before improving any prompt, verify the data flow:
- What context does the node's prep() method build?
- Is all necessary information reaching the prompt?
- Are there architectural issues preventing good context?

Never assume data is available - always verify the complete pipeline from source to prompt.

### Test Quality Over Quantity
Fewer high-quality tests are better than many mediocre ones:
- Each test should validate something distinct
- Focus on decision correctness, not confidence scores
- Remove redundant tests (e.g., 5 performance tests → 1)
- Clear rationales for what each test validates

### Context Is King
Most prompt failures stem from insufficient context:
- Rich, structured information enables good decisions
- Show concrete data, don't just describe it
- Multiple signals (primary, secondary, supporting) improve accuracy
- Consider what the LLM needs to see to make the right choice

## Key Decisions Already Made

1. **Test Philosophy**: Focus on decision correctness, not confidence scores
2. **Parallel Execution**: All tests must support pytest parametrization
3. **Model Testing**: Use gpt-5-nano for cheap iteration, validate with better models
4. **Quality Standard**: >80% accuracy is the minimum acceptable
5. **Architecture**: Keep metadata separate from IR, maintain clean concerns
6. **Test Count**: Aim for 10-15 high-quality tests per prompt

**📋 Note on Specifications**: The improvement patterns in task-28.md are guidelines. Adapt them to the specific needs of each prompt while maintaining the core philosophy of clarity, structure, and measurable decisions.

## Success Criteria

Your implementation is complete when:

- ✅ Baseline accuracy documented
- ✅ Prompt achieves >80% accuracy on test suite
- ✅ Tests complete in <10 seconds with parallel execution
- ✅ Test cost <$0.01 with gpt-5-nano
- ✅ All tests focus on decision correctness
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Clear documentation of what improved accuracy

## Common Pitfalls to Avoid

1. **Improving prompt without checking context** - Verify data flow first
2. **Adding complexity instead of clarity** - Simpler, structured prompts work better
3. **Testing confidence instead of decisions** - Focus on what matters
4. **Keeping redundant tests** - Quality over quantity
5. **Not using parallel execution** - Speed matters for iteration
6. **Skipping baseline measurement** - Can't prove improvement without it
7. **Modifying frontmatter manually** - Let test_prompt_accuracy.py manage it

## 📋 Create Your Implementation Plan FIRST

Before improving any prompt, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that ensures systematic improvement.

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Current Prompt Analysis**
   - Task: "Analyze src/pflow/planning/prompts/[prompt_name].md structure and identify improvement areas"
   - Task: "Review the test file and identify what decisions are being tested"

2. **Data Flow Analysis**
   - Task: "Trace how [Node]Node in planning/nodes.py builds context for this prompt"
   - Task: "Identify what information reaches the prompt and what's missing"

3. **Test Pattern Analysis**
   - Task: "Examine the test file structure and identify redundancies"
   - Task: "Find patterns in test failures to understand common issues"

4. **Context Builder Review**
   - Task: "Check if context_builder.py has methods for this prompt's context"
   - Task: "Identify opportunities to enhance context provision"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_28/implementation/improvement-plan.md`

Your plan should include:

1. **Current state analysis** - Baseline metrics and identified issues
2. **Improvement strategy** - Specific changes to make
3. **Test refinement plan** - Which tests to keep/remove/modify
4. **Risk identification** - What could break
5. **Validation approach** - How to verify improvement

## Your Implementation Order

### 0. Read full Progress Log (FIRST!)

Continuously update the shared progress log: `.taskmaster/tasks/task_28/implementation/progress-log.md`

```markdown
# Task 28 - [Prompt Name] Improvement Progress Log

## [Timestamp] - Starting Implementation
Selected [prompt_name] for improvement.
Current accuracy: [baseline] (from frontmatter or initial test)
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Select and claim your prompt (coordinate if multiple agents)
2. Run baseline accuracy test
3. Analyze failure patterns
4. Investigate context provision
5. Create improvement plan
6. Enhance context if needed
7. Improve prompt structure
8. Refine test suite
9. Validate improvements
10. Document lessons learned

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code/Prompt that worked:
```markdown
# Actual prompt snippet
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original approach didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test decision correctness (found/not_found, selected/not_selected)
- Test edge cases where prompts typically fail
- Create diverse scenarios that cover different decision paths
- Document only interesting test discoveries in your progress log

**What to test**:
- **Decision outcomes**: The actual decision made
- **Edge cases**: Ambiguous or tricky inputs
- **Data variations**: Different input formats/structures
- **Error scenarios**: How prompt handles invalid input

**What NOT to test**:
- Exact confidence scores
- Specific wording of responses
- Internal reasoning steps
- Implementation details

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed pattern
Tests failing on ambiguous inputs like "analyze data".
Need clearer prompt guidance for vague requests.
```

**Remember**: Tests that validate correct decisions > tests that check confidence

## What NOT to Do

- **DON'T** manually edit the YAML frontmatter in prompt files
- **DON'T** focus on confidence scores instead of decisions
- **DON'T** add more than 15 test cases
- **DON'T** skip baseline measurement
- **DON'T** improve prompts without checking context provision first
- **DON'T** make prompts more complex - clarity wins
- **DON'T** ignore the test cost and performance metrics

## Getting Started

1. Choose your prompt to improve (coordinate if multiple agents working)
2. Run baseline test: `uv run python tools/test_prompt_accuracy.py [prompt_name] --model gpt-5-nano`
3. Analyze the results and create your improvement plan
4. Start with context investigation before touching the prompt

## Final Notes

- Each prompt has unique challenges - adapt the patterns to fit
- The test framework is your friend - use it for rapid iteration
- Document everything in your progress log
- Small, clear improvements often beat major rewrites
- Context provision is usually the key to accuracy improvement

## Remember

You're improving the brain of the planner - these prompts determine whether pflow understands user intent correctly. Every percentage point of accuracy improvement means fewer user frustrations and more successful workflow generations.

The patterns in task-28.md are proven - structured decision processes, clear evidence hierarchies, and concrete examples work. Apply them thoughtfully to your chosen prompt.

Good luck! Your improvements will directly impact the reliability and usability of pflow's natural language interface.