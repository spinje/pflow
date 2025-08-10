# Natural Language Planner - LLM Integration Debugging Journey

## 🚀 TL;DR - 30-Second Summary

**Problem**: Natural Language Planner was failing to generate valid workflows - LLM wasn't using template variables correctly.

**Root Causes**:
1. Validation happened BEFORE parameter extraction (checking `$variables` against empty {})
2. Context builder told LLM "Parameters: none" when nodes actually accepted params

**Solution**: Reordered flow + fixed misleading context = 100% working planner

**Quick Fix Check**: Run `python scripts/debug/planner-flow/verify_planner_fixes.py`

## Executive Summary

This document consolidates the comprehensive investigation and resolution of critical LLM integration test failures in Task 17's Natural Language Planner system. What began as mysterious test failures evolved into the discovery and fix of two fundamental design issues, ultimately resulting in a fully functional natural language to workflow generation system.

## 📋 Prerequisites

Before using the debug scripts:
```bash
# Install pflow dependencies
uv pip install -e .

# For LLM-based scripts, set API key:
export ANTHROPIC_API_KEY="your-key"  # or
export OPENAI_API_KEY="your-key"

# Ensure you're in the pflow root directory
cd /path/to/pflow
```

## The Problem Discovery Timeline

### Phase 1: Missing End-to-End Tests (2024-12-10)
**Initial Question**: "Do we have any actual LLM tests that run the entire flow as the CLI would invoke it?"

**Discovery**:
- ✅ Individual node tests with real LLMs existed (`tests/test_planning/llm/`)
- ✅ Complete flow tests with mocked LLMs existed (`tests/test_planning/integration/`)
- ❌ **NO tests combining both**: Complete flow + Real LLM calls
- **Critical Gap**: The CLI would invoke `create_planner_flow()` with real LLMs, but we had no tests simulating this

**Solution**: Created `tests/test_planning/llm/integration/test_planner_e2e_real_llm.py`

### Phase 2: Test Failures Reveal Design Issues

When running the new end-to-end tests with real LLMs:

#### Path A (Workflow Reuse): ✅ SUCCESS
- Successfully discovered existing workflows
- Correctly extracted parameters from natural language
- Complete execution without errors

#### Path B (Workflow Generation): ❌ MULTIPLE FAILURES
1. **Missing Parameters**: "Missing required parameters: input_file"
2. **Structural Validation Errors**: "outputs.extraction_usage: '$extract_first_column.llm_usage' is not of type 'object'"
3. **Unused Template Variables**: "Declared input(s) never used as template variable: input_file_path, output_file_path"

### 🔴 What Was Actually Happening (Before vs After)

#### Example: User says "Read data.csv and write to output.txt"

**❌ BEFORE - What LLM Generated (BROKEN):**
```json
{
  "inputs": {
    "input_file": {
      "description": "File to read",
      "type": "string",
      "required": true
    }
  },
  "nodes": [{
    "id": "read",
    "type": "read-file",
    "params": {}  // ← WRONG! Empty params, not using $input_file
  }]
}
```
Result: Validation error - "Declared input(s) never used as template variable: input_file"

**✅ AFTER - What LLM Generates (FIXED):**
```json
{
  "inputs": {
    "input_file": {
      "description": "File to read",
      "type": "string",
      "required": true
    }
  },
  "nodes": [{
    "id": "read",
    "type": "read-file",
    "params": {
      "file_path": "$input_file"  // ← CORRECT! Using template variable
    }
  }]
}
```
Result: Validation passes, workflow executes successfully

## Root Cause Analysis

### Initial (Incorrect) Hypothesis
**Assumption**: The LLM doesn't understand how to use template variables properly.

**Actions Taken**:
- Enhanced WorkflowGeneratorNode prompt with detailed template variable guidance
- Added "Exclusive Params" pattern explanation
- Provided extensive examples showing `$variable` syntax

**Result**: ❌ Problem persisted - this was NOT the root cause!

### Real Root Cause #1: Validation Order Issue

**Discovery**: Template validation was happening BEFORE parameter extraction!

#### Visual Flow Diagram

```
🔴 OLD FLOW (BROKEN):
┌─────────────┐    ┌──────────────┐    ┌──────────┐    ┌─────────────────┐
│  Generate   │───►│  Validate    │───►│ Metadata │───►│ ParameterMapping│
│  Workflow   │    │ (empty {})   │    │          │    │   (too late!)   │
└─────────────┘    └──────────────┘    └──────────┘    └─────────────────┘
                         ❌ FAILS: $input_file not in {}

🟢 NEW FLOW (FIXED):
┌─────────────┐    ┌─────────────────┐    ┌──────────────┐    ┌──────────┐
│  Generate   │───►│ ParameterMapping│───►│   Validate   │───►│ Metadata │
│  Workflow   │    │ (extracts params)│   │ (with params)│    │          │
└─────────────┘    └─────────────────┘    └──────────────┘    └──────────┘
                                                ✅ PASSES: $input_file found in params
```

**Impact**:
- Validator was checking `$input_file` against empty {} dictionary
- ALL workflows with required inputs failed validation
- Retry mechanism was futile - regenerating didn't fix the missing parameter values

### Real Root Cause #2: Context Builder Misleading LLM

**Discovery**: The context builder was providing contradictory information to the LLM.

**What the LLM Saw**:
```markdown
### read-file
**Inputs**:
- file_path: str - Path to the file to read
**Parameters**: none  ← ❌ MISLEADING!
```

**What the Prompt Said**:
"You CAN use params with template variables"

**The Reality**:
All nodes support the fallback pattern:
```python
file_path = shared.get("file_path") or self.params.get("file_path")
```

**Why This Happened**:
- `_format_exclusive_parameters()` only showed params NOT in inputs
- For nodes with no exclusive params, it showed "none"
- LLM received contradictory information about parameter availability

## The Fixes Implemented

### Fix 1: Validation Flow Redesign
**File**: [`src/pflow/planning/flow.py`](../../../src/pflow/planning/flow.py)

Changed the flow connection order:
```python
# OLD (BROKEN):
workflow_generator - "validate" >> validator
validator - "valid" >> metadata_generator

# NEW (FIXED):
workflow_generator - "validate" >> parameter_mapping
parameter_mapping - "params_complete_validate" >> validator
validator - "valid" >> metadata_generator
```

And updated ParameterMappingNode routing:
```python
def post(self, shared, prep_res, exec_res):
    if shared.get("generated_workflow"):
        # Path B: Route to validator with extracted params
        return "params_complete_validate"
    else:
        # Path A: Continue to parameter preparation
        return "params_complete"
```

### Fix 2: Context Builder Enhancement
**File**: [`src/pflow/planning/context_builder.py`](../../../src/pflow/planning/context_builder.py)

Changed misleading "Parameters: none" to show template variable guidance:
```python
# OLD (MISLEADING):
if exclusive_params:
    lines.append("**Parameters**:")
    lines.extend(exclusive_params)
else:
    lines.append("**Parameters**: none")  # ← Misleading!

# NEW (CLEAR):
if exclusive_params:
    lines.append("**Parameters**:")
    lines.extend(exclusive_params)
else:
    # Show template variable usage for inputs
    lines.append("**Template Variables**: Use $variables in params field for inputs:")
    for input_key in input_keys:
        lines.append(f'- {input_key}: "${input_key}"')
```

### Fix 3: Enhanced Prompt Template
**File**: `src/pflow/planning/nodes.py` (WorkflowGeneratorNode)

Added comprehensive template variable guidance:
- "Use template variables ($variable) for ALL dynamic values"
- "NEVER hardcode values like '1234' - use $issue_number instead"
- "IMPORTANT: Nodes can accept template variables for ANY of their input keys!"
- "Even if a node shows 'Parameters: none' in the component list"

## 🔍 Quick Troubleshooting Guide

### Which Debug Script Should I Use?

```
Is the planner failing to generate workflows?
├─ YES → Is it a template variable issue?
│   ├─ YES → Run: verify_template_prompts.py
│   └─ NO → Run: debug_workflow_generation.py
│
└─ NO → Is the context missing information?
    ├─ YES → Are nodes missing parameters?
    │   ├─ YES → Run: analyze_node_docstrings.py
    │   └─ NO → Run: debug_planning_context.py
    │
    └─ NO → Is validation failing unexpectedly?
        ├─ YES → Run: verify_planner_fixes.py
        └─ NO → Check registry: debug_registry_metadata.py
```

### Common Issues & Quick Fixes

| Symptom | Likely Cause | Debug Script | Quick Fix |
|---------|-------------|--------------|-----------|
| "Declared input never used" | Template variables not being used | `verify_template_prompts.py` | Check node params documentation |
| "Parameters: none" in context | Missing Params in docstring | `analyze_node_docstrings.py` | Add Params section to node |
| Validation fails with empty {} | Wrong flow order | `verify_planner_fixes.py` | Ensure param extraction before validation |
| LLM generates hardcoded values | Misleading context | `debug_planning_context.py` | Fix context builder output |

## Debug Scripts Reference

The following debug scripts were created during the investigation and have been preserved in `scripts/debug/planner-flow/`:

### 1. `debug_workflow_generation.py`
**Purpose**: Direct testing of WorkflowGeneratorNode with detailed analysis
- Tests basic workflow generation
- Tests retry scenarios with validation errors
- Analyzes generated workflows for template variable usage
- Verifies prompt contains all critical guidance

**Usage**:
```bash
export ANTHROPIC_API_KEY="your-key"
RUN_LLM_TESTS=1 python scripts/debug/planner-flow/debug_workflow_generation.py
```

### 2. `debug_planning_context.py`
**Purpose**: Examines the planning context sent to the LLM
- Shows what node parameter information is included
- Identifies missing parameter documentation
- Verifies context builder output

**Usage**:
```bash
python scripts/debug/planner-flow/debug_planning_context.py
```

### 3. `analyze_node_docstrings.py`
**Purpose**: Analyzes node docstrings to identify parameter documentation issues
- Checks for missing Params sections
- Compares read-file vs llm node documentation
- Shows what the LLM actually sees

**Usage**:
```bash
python scripts/debug/planner-flow/analyze_node_docstrings.py
```

### 4. `debug_registry_metadata.py`
**Purpose**: Examines what the registry captures about node parameters
- Tests metadata extraction
- Shows registry content for specific nodes
- Identifies gaps in parameter documentation

**Usage**:
```bash
python scripts/debug/planner-flow/debug_registry_metadata.py
```

### 5. `verify_template_prompts.py`
**Purpose**: Verifies all template variable guidance is present in prompts
- Checks for critical template guidance elements
- Verifies JSON examples are complete
- Tests retry error handling
- Confirms parameter hints integration

**Usage**:
```bash
python scripts/debug/planner-flow/verify_template_prompts.py
```

### 6. `verify_planner_fixes.py`
**Purpose**: Comprehensive verification that all fixes work together
- Tests validation redesign (parameters extracted before validation)
- Verifies context builder shows template guidance
- Tests realistic workflow generation
- Confirms both Path A and Path B work correctly

**Usage**:
```bash
python scripts/debug/planner-flow/verify_planner_fixes.py
```

## Key Learnings

### 1. Not Always an LLM Problem
Initial assumption that the LLM didn't understand template variables was wrong. The real issues were:
- System design flaw (validation order)
- Misleading documentation (context builder)

### 2. Context Must Match Reality
The context shown to LLM must accurately reflect how the system works:
- All inputs can be template variables
- The params field accepts ANY input as a template
- "Parameters: none" was misleading

### 3. Flow Order Matters
Extracting parameters BEFORE validation is critical:
- Allows validation with real values
- Prevents futile retry loops
- Enables workflows with required inputs

### 4. Test Coverage Gaps
Missing end-to-end tests with real LLMs masked issues:
- Individual components worked
- Mocked integration worked
- But real end-to-end had problems

## Impact of Fixes

### Observed Improvements

| Aspect | Before Fixes | After Fixes |
|--------|-------------|-------------|
| Path B Workflow Generation | Frequently failed with validation errors | Successfully generates valid workflows |
| Retry Behavior | Multiple retries often failed to fix issues | Retries successfully fix issues when needed |
| Template Variable Usage | Often empty params {} or hardcoded values | Correctly uses $variable syntax |
| Test Workarounds | Triple generation mocks required | Single generation mock sufficient |
| Integration Tests | 9 tests failing | All tests passing |

### Before Fixes:
- ❌ Workflows with required inputs failed validation
- ❌ LLM generated unusable workflows with empty params or hardcoded values
- ❌ Triple mock workarounds needed in tests
- ❌ Path B (generation) mostly broken
- ❌ Confusion about template variable usage

### After Fixes:
- ✅ Template validation works with real values
- ✅ LLM generates proper workflows with `$variables`
- ✅ Single generation attempt sufficient
- ✅ Both Path A and Path B fully functional
- ✅ Clear, consistent template variable guidance
- ✅ All integration tests passing

## Testing the Fixes

To verify the Natural Language Planner works correctly:

```bash
# Set up API key
export ANTHROPIC_API_KEY="your-key-here"

# Run end-to-end tests with real LLMs
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_planner_e2e_real_llm.py -xvs

# Test specific scenarios
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_planner_e2e_real_llm.py::TestPlannerE2ERealLLM::test_path_a_workflow_reuse_with_real_llm -xvs

# Run debug scripts
python scripts/debug/planner-flow/debug_workflow_generation.py
python scripts/debug/planner-flow/verify_planner_fixes.py
```

## ⚠️ Common Pitfalls to Avoid

### 1. **Don't Assume LLM Issues First**
- ❌ "The LLM doesn't understand" - Check your system design first!
- ✅ Verify what context/information the LLM actually receives

### 2. **Parameter Documentation Gaps**
- ❌ Documenting only in `Reads:` section for shared store
- ✅ Also document in `Params:` section for template variable support

### 3. **Validation Timing**
- ❌ Validating before you have the data to validate against
- ✅ Extract parameters → Then validate with those parameters

### 4. **Misleading Simplifications**
- ❌ Showing "Parameters: none" when fallback params exist
- ✅ Always show what parameters CAN be used, even if optional

### 5. **Test Coverage Blind Spots**
- ❌ Testing components in isolation + mocked integration only
- ✅ Also test complete flow with real external dependencies

## ❓ Frequently Asked Questions

**Q: Why didn't the LLM use template variables even with good prompts?**
A: The context builder was showing "Parameters: none" which contradicted the prompt instructions. LLMs trust the context over general instructions.

**Q: How do I know if my node supports template variables?**
A: Check if the node uses the pattern: `shared.get("key") or self.params.get("key")`. If yes, it supports template variables for that key.

**Q: What's the "Exclusive Params" pattern?**
A: It's when a node's inputs (from shared store) can also be provided as parameters. The node checks shared store first, then falls back to params.

**Q: Why did you need to reorder the flow?**
A: Template validation needs actual parameter values. We were validating `$input_file` against an empty dictionary before extracting "input_file" from user input.

**Q: How long do the debug scripts take to run?**
A: Non-LLM scripts run quickly (typically seconds). LLM-based scripts depend on API response times and may take longer.

## Recommendations for Future Development

### 1. Always Create End-to-End Tests
- Test with real external dependencies
- Don't rely solely on mocked tests
- Verify the complete user journey

### 2. Documentation Accuracy
- Ensure documentation shown to LLMs matches actual system behavior
- Avoid misleading simplifications
- Test with actual LLM comprehension in mind

### 3. Flow Design Considerations
- Consider operation order carefully (extraction before validation)
- Design for retry and error recovery
- Make dependencies explicit

### 4. Debug Tooling
- Create focused debug scripts during development
- Preserve valuable debugging tools
- Document the investigation process

### 5. When Adding New Nodes
- ✅ Document ALL parameters in `Params:` section
- ✅ Test with the Natural Language Planner
- ✅ Verify template variable support works
- ✅ Run `verify_planner_fixes.py` after changes

## Conclusion

The LLM integration testing effort revealed and fixed two fundamental issues in the Natural Language Planner:

1. **Validation happening before parameter extraction** - Fixed by reordering the flow
2. **Context builder misleading the LLM** - Fixed by showing proper template variable guidance

These fixes transformed the planner from a system that frequently failed with template validation errors to one that reliably generates and validates workflows with template variables. The Natural Language Planner is now production-ready and can handle real-world workflow generation scenarios.

## Files Modified

### Core Implementation:
- [`src/pflow/planning/flow.py`](../../../src/pflow/planning/flow.py) - Flow reordering for validation redesign
- [`src/pflow/planning/nodes.py`](../../../src/pflow/planning/nodes.py) - Enhanced prompts and routing logic
- [`src/pflow/planning/context_builder.py`](../../../src/pflow/planning/context_builder.py) - Template variable guidance

### Key Tests to Reference:
- [`tests/test_planning/llm/integration/test_planner_e2e_real_llm.py`](../../../tests/test_planning/llm/integration/test_planner_e2e_real_llm.py) - End-to-end tests with real LLMs
- [`tests/test_planning/integration/test_planner_integration.py`](../../../tests/test_planning/integration/test_planner_integration.py) - Complete flow integration tests
- [`tests/test_planning/integration/test_flow_structure.py`](../../../tests/test_planning/integration/test_flow_structure.py) - Flow ordering verification

### Tests Updated:
- 69 integration tests updated for new flow order
- All triple generation mock workarounds removed
- Realistic workflows with required inputs now used

### Documentation:
- This comprehensive report
- Debug scripts preserved for future use
- Test documentation updated in [`tests/test_planning/integration/CLAUDE.md`](../../../tests/test_planning/integration/CLAUDE.md)

---

*Report compiled: 2024-12-10*
*Task 17: Natural Language Planner - LLM Integration Testing*