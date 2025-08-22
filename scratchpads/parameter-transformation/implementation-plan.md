# Parameter Transformation Implementation Plan

## Executive Summary

Transform user input strings by replacing discovered parameter values with their mapped parameter names in brackets, enabling generic metadata generation and preventing specific value leakage.

## Problem Statement

### Current Issue
When MetadataGenerationNode generates metadata, it sees the raw user input like:
```
"generate changelog from last 30 closed issues in pflow repo"
```

This causes:
1. **Value Leakage**: Specific values (30, pflow) appear in metadata, hurting reusability
2. **Poor Generalization**: Descriptions become too specific to the original request
3. **Discovery Problems**: Workflows created with "30 issues" won't match searches for "50 issues"

### Root Cause
MetadataGenerationNode has access to:
- `user_input`: The raw request with specific values
- `discovered_params`: Raw parameter discoveries ({"count": "30", "repo": "pflow"})
- But NOT `extracted_params`: The mapped values ({"issue_count": 30, "repo_name": "pflow"})

## Solution Overview

### Core Idea
Transform the user input by replacing parameter values with their mapped names:
```
Before: "generate changelog from last 30 closed issues in pflow repo"
After:  "generate changelog from last [issue_count] closed issues in [repo_name] repo"
```

### Why This Works
1. **Prevents Value Leakage**: LLM can't include "30" or "pflow" because they're not in the input
2. **Natural Generalization**: Descriptions naturally become generic
3. **Clear Parameterization**: Shows exactly what's configurable

## Implementation Strategy

### Phase 1: Data Access (Low Risk)
1. Update MetadataGenerationNode.prep() to access extracted_params
2. Pass extracted_params to _build_metadata_prompt()
3. No behavior change yet - just making data available

### Phase 2: Transformation Logic (Medium Risk)
1. Create _transform_user_input_with_params() method
2. Replace parameter values with [name] placeholders
3. Handle edge cases (multiple occurrences, partial matches)

### Phase 3: Prompt Integration (Low Risk)
1. Use transformed input in prompt
2. Update prompt template variable
3. Test with various inputs

## Detailed Implementation Steps

### Step 1: Update prep() Method
```python
# In MetadataGenerationNode.prep()
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow": shared.get("generated_workflow", {}),
        "user_input": shared.get("user_input", ""),
        "planning_context": shared.get("planning_context", ""),
        "discovered_params": shared.get("discovered_params", {}),
        "extracted_params": shared.get("extracted_params", {}),  # NEW
        "model_name": self.params.get("model", "anthropic/claude-sonnet-4-0"),
        "temperature": self.params.get("temperature", 0.3),
    }
```

### Step 2: Create Transformation Method
```python
def _transform_user_input_with_params(self, user_input: str, extracted_params: dict) -> str:
    """Replace parameter values in user input with [parameter_name] placeholders.

    Args:
        user_input: Original user request (e.g., "30 issues from pflow repo")
        extracted_params: Mapped parameters (e.g., {"issue_count": 30, "repo_name": "pflow"})

    Returns:
        Transformed input (e.g., "[issue_count] issues from [repo_name] repo")
    """
    if not extracted_params:
        return user_input

    transformed = user_input

    # Sort by value length (longest first) to handle overlapping values
    # e.g., "2024" before "24" to avoid partial replacements
    sorted_params = sorted(
        extracted_params.items(),
        key=lambda x: len(str(x[1])),
        reverse=True
    )

    for param_name, param_value in sorted_params:
        if param_value is None:
            continue

        # Convert value to string for replacement
        value_str = str(param_value)

        # Replace all occurrences of the value
        if value_str in transformed:
            transformed = transformed.replace(value_str, f"[{param_name}]")

    return transformed
```

### Step 3: Update _build_metadata_prompt()
```python
def _build_metadata_prompt(self, workflow: dict, user_input: str, discovered_params: dict) -> str:
    # ... existing code ...

    # Get extracted params from prep
    extracted_params = self.prep_res.get("extracted_params", {})

    # Transform user input
    transformed_input = self._transform_user_input_with_params(user_input, extracted_params)

    # ... rest of prompt building ...

    return format_prompt(
        prompt_template,
        {
            "user_input": transformed_input,  # Use transformed instead of raw
            # ... other variables ...
        },
    )
```

## Test Cases

### Test Case 1: Basic Replacement
```python
Input: "generate changelog from last 30 closed issues in pflow repo"
Extracted: {"issue_count": 30, "repo_name": "pflow"}
Expected: "generate changelog from last [issue_count] closed issues in [repo_name] repo"
```

### Test Case 2: Multiple Occurrences
```python
Input: "copy files from /home/user to /home/user/backup"
Extracted: {"source_path": "/home/user", "dest_path": "/home/user/backup"}
Expected: "copy files from [source_path] to [dest_path]"
```

### Test Case 3: No Parameters
```python
Input: "do something generic"
Extracted: {}
Expected: "do something generic"
```

### Test Case 4: Overlapping Values
```python
Input: "process 2024 records from year 2024"
Extracted: {"count": 2024, "year": 2024}
Expected: "process [count] records from year [year]"
```

## Success Criteria

### Functional Requirements
1. ✅ User input is transformed correctly with parameter placeholders
2. ✅ Original behavior preserved when no parameters available
3. ✅ All existing tests continue to pass
4. ✅ Metadata no longer contains forbidden specific values

### Performance Requirements
1. ✅ Transformation adds <10ms to metadata generation
2. ✅ No additional LLM calls required

### Quality Requirements
1. ✅ Generated metadata is more generic and reusable
2. ✅ Descriptions reference parameters by name
3. ✅ Keywords don't include specific values

## Risk Analysis

### Low Risk
- Adding data to prep() - just makes data available
- Prompt template update - backward compatible

### Medium Risk
- String replacement logic - need careful testing for edge cases
- Order of replacements matters for overlapping values

### Mitigation
- Sort replacements by length (longest first)
- Comprehensive test suite
- Fallback to original input if transformation fails

## Rollback Plan

If issues occur:
1. Remove `extracted_params` from prep()
2. Use original `user_input` instead of transformed
3. No schema or structural changes to revert

## Future Enhancements

1. **Apply to Other Prompts**:
   - discovery.md - Match parameterized patterns
   - parameter_mapping.md - Show clear mappings
   - workflow_generator.md - Understand parameterization

2. **Smart Replacement**:
   - Handle partial matches (e.g., "pflow/repo" → "[repo_owner]/[repo_name]")
   - Context-aware replacements

3. **Validation**:
   - Ensure all workflow inputs have corresponding extracted params
   - Warn if values remain that should be parameterized