# Task 36: Update Context Builder for Namespacing Clarity - Agent Instructions

## The Problem You're Solving

With automatic namespacing enabled by default (Task 9), nodes can NO LONGER read inputs directly from the shared store - everything must be passed via params using template variables. However, the context builder still presents nodes with misleading "Inputs" sections and "Parameters: none" messages, causing the LLM planner to generate incorrect workflows with missing parameters.

## Your Mission

Update ONLY the context builder (`src/pflow/planning/context_builder.py`) to present node information in a way that clearly reflects how nodes work with automatic namespacing - showing that ALL data must be passed via the params field using template variables.

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
**File**: `.taskmaster/tasks/task_36/task-36.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_36/starting-context/`

**Files to read (in this order):**
1. `task-36-spec.md` - The specification (FOLLOW THIS PRECISELY)
2. `README.md` - Quick summary and key insight about the translation layer
3. `problem-analysis.md` - Deep dive into the mental model mismatch and concrete examples
4. `implementation-plan.md` - Complete implementation strategy with new format examples
5. `code-implementation-guide.md` - Exact code changes needed, function by function
6. `testing-validation-guide.md` - Comprehensive testing strategy and validation

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-36-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY. The code implementation guide (`code-implementation-guide.md`) contains the exact functions to modify and add.

### 4. CRITICAL: Read the Handoff
**File**: `.taskmaster/tasks/task_36/handoffs/36-handover.md`

**Purpose**: Contains critical discoveries and warnings from investigation phase, including:
- The "exclusive params" anti-pattern that's causing the problem
- Exact line numbers in the code to examine
- The trap of adding instructions instead of just presenting data
- Why previous attempts failed

**Why read this**: This handoff contains hard-won insights that will save you hours of debugging.

## What You're Building

You're updating the context builder to transform this misleading format:

**Current (WRONG)**:
```markdown
### read-file
**Inputs**:
- `file_path: str` - Path to the file to read

**Parameters**: none  ❌ MISLEADING!
```

Into this clear format:

**New (CORRECT)**:
```markdown
### read-file
Read content from a file and add line numbers for display.

**Parameters** (all go in params field):
- `file_path: str` - Path to the file to read
- `encoding: str` - File encoding (optional, default: utf-8)

**Outputs** (access as ${node_id.output_key}):
- `content: str` - File contents with line numbers
- `error: str` - Error message if operation failed

**Example usage**:
```json
{
  "id": "read_file",
  "type": "read-file",
  "params": {
    "file_path": "${input_file}"
  }
}
```
```

## Key Outcomes You Must Achieve

### 1. Core Implementation (Per Spec Rules 1-15)
- Replace "Inputs" section heading with "Parameters" in node formatting
- Show all parameters in single Parameters section regardless of exclusive status
- Add clarification text "(all go in params field)" to Parameters header
- Include output access pattern "(access as ${node_id.output_key})" in Outputs header
- Generate JSON usage example for every node with realistic values
- Remove _format_exclusive_parameters and _format_template_variables functions
- Create new formatting functions: _format_all_parameters, _format_outputs_with_access, _format_usage_example
- Update _format_node_section_enhanced to use new formatting functions
- Preserve complex structure display for nested types
- Maintain consistent format across all node types

### 2. Test Updates
- Update test assertions in `test_context_builder_phases.py`
- Ensure all 15 test criteria from the spec pass
- Validate that the planner can use the new context successfully

### 3. Non-Functional Requirements
- Context generation time ≤ 100ms for 50 nodes
- Memory usage increase ≤ 5% compared to current implementation
- Output remains valid markdown
- JSON examples are syntactically valid

## Implementation Strategy

### Phase 1: Add New Helper Functions (30 minutes)
1. Create `_format_all_parameters()` to replace the problematic exclusive params logic
2. Create `_format_outputs_with_access()` to show namespaced output access
3. Create `_format_usage_example()` to generate concrete JSON examples

### Phase 2: Update Core Formatting (30 minutes)
1. Modify `_format_node_section_enhanced()` to use the new helper functions
2. Remove or comment out `_format_exclusive_parameters()`
3. Remove or comment out `_format_template_variables()`
4. Ensure all nodes use the enhanced format consistently

### Phase 3: Update Tests and Validate (30 minutes)
1. Update test assertions in `test_context_builder_phases.py`
2. Run tests to ensure no regressions
3. Create before/after comparison to verify improvement
4. Test with real workflow generation

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> **CRITICAL**: Always use the `pflow-codebase-searcher` agent FIRST to verify any assumptions, resolve ambiguities, and validate technical details before implementation!
> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### The "Exclusive Params" Anti-Pattern
The current code has `_format_exclusive_parameters()` that ONLY shows params NOT in the inputs list. This made sense pre-namespacing but is now actively harmful:
```python
# WRONG approach (current):
exclusive_params = [p for p in params if p not in input_keys]
if not exclusive_params:
    lines.append("**Parameters**: none")  # MISLEADING!
```

### What "Inputs" Really Means Now
With namespacing:
- Nodes CAN'T read from shared store directly (`shared.get("key")` returns None)
- Everything is namespaced: `shared["node_id"]["key"]`
- ALL data MUST come through params: `self.params.get("key")`
- "Inputs" in metadata means "what the node expects in params"

### The Context Output Is Pure Data
The context goes into `<available_nodes>` tags in prompts. It should be FACTUAL DATA only:
- ❌ WRONG: "With namespacing enabled, you must pass all inputs via params"
- ✅ RIGHT: Just show the structure clearly with good examples

### Key Functions to Modify
From `src/pflow/planning/context_builder.py`:
- `_format_node_section_enhanced()` (lines ~781-831) - Main formatting function
- `_format_all_parameters()` (lines ~676-703) - Currently shows misleading info
- `_format_template_variables()` (lines ~729-753) - Shows unhelpful placeholders

## Critical Warnings from Experience

### Don't Add Instructions or Explanations
The context builder output is DATA, not a tutorial. The workflow generator prompt already has all the instructions. Just present the node structure clearly.

### The Test That Will Break
`tests/test_planning/test_context_builder_phases.py` line ~783 tests for `"**Parameters**: none"`. This assertion MUST be updated to match the new format.

### Don't Overthink This
It's a simple presentation change in one file. Don't modify:
- Node implementations
- IR schemas
- Compiler logic
- Any other system components

### Performance Matters
The context builder is called frequently during planning. Don't add expensive operations or complex logic. Keep it simple and efficient.

## Key Decisions Already Made

1. **Only modify context_builder.py** - This is a surgical change to the presentation layer only
2. **Eliminate "exclusive params" distinction** - With namespacing, this concept is confusing and harmful
3. **Always show usage examples** - Concrete examples eliminate ambiguity
4. **Keep output factual** - No explanations or instructions in the context output
5. **Maintain consistent format** - All nodes use the same clear structure

## Success Criteria

Your implementation is complete when:

- ✅ All 15 test criteria from the spec pass:
  1. Parameters section present for all nodes with correct header format
  2. No "Inputs" section appears in any node output
  3. No "Parameters: none" for nodes with input requirements
  4. All parameters shown including exclusive params
  5. Output section includes namespacing access pattern
  6. JSON example present for every node
  7. JSON examples are valid JSON syntax
  8. Template variables use realistic values not "${key}"
  9. Optional parameters marked with "(optional)"
  10. Default values shown with "(default: value)"
  11. Complex structures display JSON format
  12. Test file assertions updated for new format
  13. Context size remains under 200KB limit
  14. All existing tests pass after changes
  15. Planner can generate valid workflows with new format
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Before/after comparison shows clear improvement

## Common Pitfalls to Avoid

1. **Don't add explanatory text** - The context is data, not documentation
2. **Don't modify node metadata** - Only change how it's presented
3. **Don't change the IR schema** - This is presentation only
4. **Don't forget to update tests** - They expect the old format
5. **Don't make it complex** - Simple, clear presentation is the goal

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### ⚠️ CRITICAL: Verify EVERYTHING Before Planning

**MAKE NO ASSUMPTIONS!** Before creating your plan, you MUST verify all information using the `pflow-codebase-searcher` agent. This is non-negotiable.

Deploy the `pflow-codebase-searcher` agent to verify:
- Any inconsistencies you notice in the documentation
- Ambiguous requirements or specifications
- Unverified technical details
- Current implementation patterns
- Actual function signatures and line numbers
- Test structure and assertions
- Dependencies between components

**Example verification tasks for pflow-codebase-searcher:**
```markdown
1. "Verify the exact implementation of _format_exclusive_parameters in context_builder.py and confirm it only shows non-input params"
2. "Find and verify all test assertions related to 'Parameters: none' in the test suite"
3. "Confirm that no other components besides the planner consume the context builder output"
4. "Verify the actual structure of node metadata and how 'inputs' vs 'params' are stored"
```

**DO NOT PROCEED** with planning until you have verified all critical information. If something seems unclear or contradictory, deploy the searcher to investigate.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

After verifying critical information with pflow-codebase-searcher, deploy parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Current Implementation Analysis**
   - Task: "Analyze the current _format_node_section_enhanced and _format_all_parameters functions in context_builder.py"
   - Task: "Find all places in context_builder.py that reference 'exclusive params' or similar concepts"

2. **Test Analysis**
   - Task: "Examine test_context_builder_phases.py and identify all assertions about parameter formatting"
   - Task: "Find integration tests that might be affected by context format changes"

3. **Usage Pattern Discovery**
   - Task: "Check how the planner uses the context builder output in workflow generation"
   - Task: "Verify no other components depend on the current format"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_36/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every function to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Implementation Plan Template

```markdown
# Task 36 Implementation Plan

## Context Gathered

### Current Implementation Issues
- _format_exclusive_parameters shows only non-input params
- "Parameters: none" misleads the LLM
- Template examples use unhelpful "${key}" placeholders

### Test Dependencies
- test_context_builder_phases.py expects old format
- [Other affected tests]

## Implementation Steps

### Phase 1: Add New Functions (Can be parallelized)
1. **Create _format_all_parameters** (Subagent A)
   - Location: Add after line 675
   - Purpose: Show ALL parameters clearly

2. **Create _format_outputs_with_access** (Subagent B)
   - Location: Add new function
   - Purpose: Show namespaced output access

3. **Create _format_usage_example** (Subagent C)
   - Location: Add new function
   - Purpose: Generate concrete JSON examples

### Phase 2: Update Core Function (Sequential)
1. **Modify _format_node_section_enhanced**
   - Dependencies: Phase 1 complete
   - Changes: Use new helper functions

### Phase 3: Testing (Use test-writer-fixer)
1. Update test assertions
2. Verify format improvements
3. Test with real workflow generation

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Breaking tests | Update assertions first |
| Performance impact | Keep logic simple |

## Validation Strategy

- Compare before/after output
- Run full test suite
- Test workflow generation
```

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_36/implementation/progress-log.md`

```markdown
# Task 36 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 0.5 Verify ALL Information (SECOND!)

Before creating your implementation plan, deploy `pflow-codebase-searcher` to verify:
- The exact current implementation of context_builder.py functions
- All test assertions that will need updating
- Any other components that consume context builder output
- The actual node metadata structure

**DO NOT make assumptions** - verify everything that seems unclear or could have multiple interpretations.

### 1. Capture current output for comparison
Run the test script to see what the format looks like now

### 2. Add the new helper functions
Create the three new formatting functions with clear logic

### 3. Update _format_node_section_enhanced
Modify to use the new helpers instead of old logic

### 4. Comment out old functions
Remove _format_exclusive_parameters and _format_template_variables

### 5. Update test expectations
Fix assertions in test_context_builder_phases.py

### 6. Run tests and validate
Ensure everything passes and format is improved

### 7. Create before/after comparison
Document the improvement clearly

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```python
# Actual code snippet
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
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
- Test that parameters are shown correctly
- Test that examples are valid JSON
- Test that output format includes access pattern
- Test that old misleading format is gone

**What to test**:
- **Format consistency**: All nodes use same structure
- **Example validity**: JSON examples are syntactically correct
- **No regressions**: Existing functionality still works
- **Integration**: Planner can use new format

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed edge case
Nodes with no parameters were showing empty Parameters section.
Added check to handle this case gracefully.
```

## What NOT to Do

- **DON'T** modify any node implementations
- **DON'T** change the workflow IR structure
- **DON'T** add explanatory text to the context output
- **DON'T** make the logic complex - keep it simple
- **DON'T** touch any files except context_builder.py and its tests
- **DON'T** add features not specified - stick to the plan

## Getting Started

1. **FIRST**: Deploy `pflow-codebase-searcher` to verify all technical details and resolve any ambiguities
2. Run `python capture_current_context.py` to see current format
3. Read the handoff document carefully - it has critical warnings
4. Create your implementation plan based on VERIFIED information
5. Start with Phase 1: Add the new helper functions
6. Test frequently: `pytest tests/test_planning/test_context_builder_phases.py -xvs`

## Final Notes

- This is a surgical change to ONE file's presentation logic
- The code implementation guide has the exact functions to modify
- Focus on clarity over cleverness - simple is better
- The goal is to eliminate confusion, not add features

## Remember

You're fixing a critical confusion point that's been causing workflow generation failures. The solution is simple: present ALL parameters clearly in one place with good examples. Don't overthink it - the implementation guide has everything you need.

This fix will immediately improve the LLM planner's ability to generate correct workflows. Every workflow that uses nodes will benefit from this clarity. Good luck!