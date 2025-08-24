# Test Suite Improvement Plan - Fixing Ambiguous Inputs

## The Core Problem

We're testing if the LLM can **improvise well** instead of testing if it can **follow instructions precisely**. This is backwards - tests should verify the system does exactly what was asked, not judge its creativity.

## Analysis of Current Test Inputs

### ✅ GOOD - Specific Instructions (10/13 tests)
These tests give clear, detailed instructions:
- **changelog_pipeline**: "Create changelog by fetching 30 closed issues from anthropic/pflow, categorize by type..."
- **data_analysis_pipeline**: "Read sales data from data/2024-sales.csv, filter Q4 records where revenue > 10000..."
- **content_generation_trap**: "Generate a blog post about Python testing best practices..."
- **parameter_vs_output**: "Fetch user profile for user_id 12345..."
- **full_release_pipeline**: Detailed 10-step pipeline
- **multi_source_weekly_report**: Comprehensive specification
- All others with specific requirements

### ❌ BAD - Vague Instructions (2/13 tests)
These are the EXACT tests that are failing:
1. **output_mapping_fix**: "Generate and save a report"
   - What kind of report? About what? In what format?
   - LLM reasonably creates project activity report
   - We penalize it for being helpful

2. **fix_validation_errors**: "Generate changelog from GitHub issues"
   - Which issues? How many? What format?
   - Missing critical details
   - LLM has to guess

### ⚠️ PROBLEMATIC - Design Issues (1/13 tests)
3. **multi_source_weekly_report**: Specific but has test design issues
   - Conflicting context (browsed vs available nodes)
   - Sometimes passes, sometimes fails (inconsistent)

## The Test Philosophy Problem

### Current (Wrong) Approach
```
Vague Input → LLM Improvises → Judge if improvisation is "correct"
```
This tests creativity, not correctness!

### Correct Approach
```
Specific Input → LLM Follows Instructions → Verify exact compliance
```
This tests if the system works as designed!

## Improvement Plan

### 1. Fix the Vague Validation Recovery Tests

#### Current `output_mapping_fix`:
```python
user_input="Generate and save a report"  # ❌ Too vague!
```

#### Improved:
```python
user_input="Generate a simple one-line status message saying 'System operational' and save it to status.txt"  # ✅ Specific!
```
This will generate 2-3 nodes as expected: llm → write-file

#### Current `fix_validation_errors`:
```python
user_input="Generate changelog from GitHub issues"  # ❌ Vague!
```

#### Improved:
```python
user_input="Fetch the last 20 closed issues from the repository and generate a simple bullet-point changelog, then save to changelog.txt"  # ✅ Specific!
```
This gives clear parameters and expectations.

### 2. Add Test Categories

```python
@dataclass
class WorkflowTestCase:
    ...
    test_category: str  # "core_behavior", "complex_workflow", "validation_recovery", "edge_case"
    ambiguity_level: str  # "specific", "moderate", "vague"
```

This helps us:
- Know what we're testing
- Set appropriate expectations
- Skip or adjust problematic categories

### 3. Fix the Conflicting Context Issue

For validation recovery tests, we need to either:

**Option A: Only pass browsed components**
```python
if test_case.validation_errors:  # It's a retry
    # Only show nodes that were selected
    prep_res["planning_context"] = filter_to_browsed_only(
        planning_context,
        browsed_components
    )
```

**Option B: Tell the prompt explicitly**
```python
if test_case.validation_errors:
    prep_res["prompt_addition"] = """
    NOTE: Use ONLY these nodes that were previously selected:
    {browsed_components}
    Ignore other nodes even if available.
    """
```

### 4. Adjust Node Count Flexibility

Current: Strict min/max (e.g., 2-3 nodes)
Proposed: Flexible based on ambiguity

```python
def get_node_count_flexibility(test_case):
    if test_case.ambiguity_level == "specific":
        return 1  # ±1 node
    elif test_case.ambiguity_level == "moderate":
        return 2  # ±2 nodes
    else:  # vague
        return 3  # ±3 nodes or skip count check
```

### 5. New Test Cases to Add

We should add tests that specifically verify:

**A. Instruction Following Test**
```python
WorkflowTestCase(
    name="precise_instruction_following",
    user_input="Read exactly the file 'input.txt', convert its content to uppercase using an LLM prompt that says 'Convert to uppercase:', and save the result to 'output.txt' with UTF-8 encoding",
    # This tests EXACT instruction following
)
```

**B. No Improvisation Test**
```python
WorkflowTestCase(
    name="no_extras_test",
    user_input="Only read the file config.json and save its content unchanged to backup.json",
    # Should generate EXACTLY 2 nodes, no analysis or enhancement
)
```

### 6. Remove or Fix Unrealistic Tests

**Validation Recovery Tests**: Either:
- Make inputs very specific (recommended)
- Remove them entirely
- Mark as "known limitations"

These tests expect "surgical fixes" which LLMs don't do - they regenerate solutions.

## Summary of Changes Needed

### Must Fix (Critical):
1. ✅ Make `output_mapping_fix` input specific
2. ✅ Make `fix_validation_errors` input specific
3. ✅ Resolve conflicting context issue (browsed vs available nodes)

### Should Fix (Important):
4. ✅ Add test categories and ambiguity levels
5. ✅ Implement flexible node count validation
6. ✅ Add "instruction following" test cases

### Consider (Nice to Have):
7. ⚠️ Split tests into "current capabilities" vs "future capabilities"
8. ⚠️ Add metrics for "follows instructions" vs "improvises helpfully"
9. ⚠️ Document what each test is actually validating

## The Key Principle

**Tests should verify the system does what it's told, not judge how well it guesses what you meant.**

Good tests have:
- Specific, unambiguous instructions
- Clear expected outcomes
- No room for "creative interpretation"
- Explicit requirements, not implicit expectations

This will give us meaningful test results that actually validate the system works correctly.