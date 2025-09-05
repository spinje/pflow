# Analysis: Why "generate a changelog for version 1.4" Doesn't Extract Version

## The Problem

**Input**: `"generate a changelog for version 1.4"`
**Expected**: Extract version = "1.4"
**Actual**: Only extracted `{"limit": "20", "output_path": "CHANGELOG.md"}` (defaults)

## Root Cause: Workflow Input Definition Mismatch

### The generate-changelog Workflow Has Different Input Definitions

#### In test_happy_path_mocked.py (line 76):
```json
"inputs": {"limit": "Number of issues to include (default: 20)"}
```
**Problem**: This is a STRING description, not a proper input schema!

#### In test_north_star_realistic_e2e.py (line 96):
```json
"inputs": {
    "limit": {"default": "20"},
    "output_path": {"default": "CHANGELOG.md"}
}
```
**Problem**: No `version` input defined! Only `limit` and `output_path`.

## Why Parameter Extraction Failed

The ParameterMappingNode tries to extract parameters for the workflow's defined inputs. Since the workflow doesn't have a `version` input defined, the LLM can't extract it!

### What the Workflow Actually Accepts:
- `limit` - Number of issues (default: 20)
- `output_path` - Where to write (default: CHANGELOG.md)

### What the Brief Prompt Provides:
- `version 1.4` - But there's no `version` input in the workflow!

## The Real Issue

The test expects version extraction, but the workflow doesn't have a version parameter! The workflow is designed to:
1. List last N issues (`limit` parameter)
2. Generate changelog from them
3. Write to a file (`output_path` parameter)

There's no version handling in the workflow definition.

## Solutions

### Option 1: Fix the Workflow Definition
Add a `version` input to the workflow:
```json
"inputs": {
    "version": {"required": false, "description": "Version for the changelog"},
    "limit": {"default": "20"},
    "output_path": {"default": "CHANGELOG.md"}
}
```

### Option 2: Fix the Test Expectation
Don't expect version extraction if the workflow doesn't support it:
```python
# Instead of:
assert "1.4" in str(extracted.values())

# Check what the workflow actually supports:
assert "limit" in extracted or "output_path" in extracted
```

### Option 3: Use a Different Workflow
Create a workflow that actually uses version as a parameter, perhaps in the commit message or file path:
```json
"nodes": [
    {"id": "write", "type": "write-file", "params": {"file_path": "CHANGELOG-${version}.md"}},
    {"id": "commit", "type": "git-commit", "params": {"message": "Update changelog for version ${version}"}}
]
```

## Why Verbose Prompts Work

The verbose prompt:
```
"generate a changelog for version 1.3 from the last 20 closed issues from github..."
```

Works because in Path B (generation), the LLM:
1. Discovers parameters from the prompt: version=1.3, limit=20
2. Creates a NEW workflow that uses these parameters
3. The generated workflow includes version in its inputs

But in Path A (reuse), it's trying to map to an EXISTING workflow that doesn't have a version input!

## Conclusion

The test failure is actually correct behavior! The workflow doesn't have a `version` input, so the ParameterMappingNode can't extract a version parameter. The LLM is correctly only extracting parameters that the workflow actually uses: `limit` and `output_path`.

This is a test design issue, not a bug in the system.