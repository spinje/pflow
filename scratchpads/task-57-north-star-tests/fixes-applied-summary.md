# Summary of Fixes Applied to Workflow Definitions

## The Problem We Fixed

The test failure for "generate a changelog for version 1.4" revealed a critical test design issue: **workflows had incorrectly defined inputs that didn't match the IR schema requirements**.

### What Was Wrong

#### 1. Incorrect Input Format
```json
// ❌ WRONG - Just a string description
"inputs": {"limit": "Number of issues to include (default: 20)"}

// ❌ WRONG - String for outputs too
"outputs": {"pr_url": "URL of created pull request"}
```

#### 2. Missing Version Parameter
The generate-changelog workflow didn't have a `version` input, so when the test tried to extract version from "generate a changelog for version 1.4", it correctly failed because the workflow couldn't accept that parameter!

## The Fix Applied

### Proper Input Schema Format
According to `src/pflow/core/ir_schema.py`, inputs must be objects with properties:

```json
"inputs": {
    "version": {
        "description": "Version number for the changelog",
        "required": false,
        "type": "string"
    },
    "limit": {
        "description": "Number of issues to include",
        "required": false,
        "type": "string",
        "default": "20"
    },
    "output_path": {
        "description": "Path to write the changelog file",
        "required": false,
        "type": "string",
        "default": "CHANGELOG.md"
    }
}
```

## Workflows Fixed

### 1. generate-changelog
- ✅ Added `version` input parameter
- ✅ Added `limit` with proper schema and default "20"
- ✅ Added `output_path` with default "CHANGELOG.md"
- ✅ Updated nodes to use `${version}` and `${output_path}` template variables

### 2. issue-triage-report
- ✅ Added `limit` with default "50"
- ✅ Added `output_path` with default "triage-report.md"
- ✅ Updated nodes to use template variables

### 3. create-release-notes
- ✅ Added `version` input parameter
- ✅ Added `limit` with default "30"
- ✅ Added `output_path` with default "RELEASE_NOTES.md"
- ✅ Updated commit message to use `${version}`

### 4. summarize-github-issue
- ✅ Fixed `issue_number` to be required with proper schema
- ✅ Added `output_path` with default "summary.md"
- ✅ Updated write node to use `${output_path}`

## Key Lessons Learned

### 1. Test Design Must Match System Capabilities
We can't test parameter extraction for parameters that don't exist in the workflow definition!

### 2. IR Schema Compliance is Critical
All inputs must follow the exact schema format:
- Object with properties (not string descriptions)
- Each property must have `description`, `required`, `type`
- Optional `default` value

### 3. Template Variables Must Match Inputs
If a workflow has an input like `version`, nodes should use `${version}` to reference it.

### 4. Path A vs Path B Behavior Difference
- **Path A (reuse)**: Can only extract parameters the workflow defines
- **Path B (generation)**: Can discover any parameters from the prompt and create a new workflow that uses them

## Test Results

✅ All 11 tests in TestNorthStarWorkflowDiscovery now pass!

## Files Modified

1. `tests/test_planning/integration/test_happy_path_mocked.py` - Fixed all 4 workflow definitions
2. `tests/test_planning/llm/integration/test_north_star_realistic_e2e.py` - DELETED (duplicate tests moved to test_generator_north_star.py)

## Why the Original Test "Failure" Was Actually Correct

The ParameterMappingNode was behaving correctly by only extracting parameters that the workflow actually accepts. Since the workflow didn't have a `version` input, it couldn't extract version from "generate a changelog for version 1.4".

This wasn't a bug in pflow - it was a test design issue where we expected parameter extraction for a non-existent parameter!

## Going Forward

When writing tests:
1. Always ensure workflow inputs are properly defined using the correct schema
2. Only test parameter extraction for parameters that actually exist in the workflow
3. Use template variables in nodes that correspond to defined inputs
4. Remember that Path A can only work with existing workflow capabilities