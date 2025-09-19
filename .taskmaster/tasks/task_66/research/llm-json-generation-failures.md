# LLM JSON Generation Failures - Research for Task 66

## Issue Discovery

**Date**: 2025-01-19
**Context**: User encountered template variables appearing literally in Slack messages
**Root Cause**: Weak LLM models failing to generate proper JSON structure

## Problem Description

When using weaker models (e.g., `gemini-2.5-flash-lite`), the LLM node can fail to generate the expected JSON structure, causing downstream template resolution failures.

### Failure Cascade

1. **Prompt requests specific JSON structure**:
   ```json
   {
     "slack_message": "Your response",
     "sheets_data": [["date", "question", "answer"]]
   }
   ```

2. **Weak model fails to comply**:
   - Returns plain text instead of JSON
   - Returns JSON with wrong field names
   - Returns malformed JSON
   - Returns empty or incomplete JSON

3. **Template resolution fails**:
   - `${analyze_and_respond.response.slack_message}` can't find field
   - Template resolver leaves unresolved variables as-is (by design)
   - Literal template string sent to downstream services

4. **User sees template variables**:
   - Slack shows: `${analyze_and_respond.response.slack_message}`
   - Instead of actual message content

## Current Behavior

### LLM Node JSON Parsing (`src/pflow/nodes/llm/llm.py`)

```python
def parse_json_response(response: str) -> Union[Any, str]:
    """Parse JSON from LLM response if possible."""
    # Attempts to parse JSON
    # Returns original string if parsing fails
    # No validation of expected structure
```

### Template Resolution (`src/pflow/runtime/template_resolver.py`)

```python
# Unresolved templates are left unchanged for debugging visibility
if var_name not in context:
    logger.debug(f"Template variable '${{{var_name}}}' could not be resolved")
    # Returns original ${variable} string
```

## Impact

- **User Experience**: Confusing template variables appear in output
- **Debugging**: Hard to distinguish between template bugs vs LLM failures
- **Reliability**: Workflows fail silently with weak models
- **Model Selection**: No guidance on which models support JSON generation

## Proposed Solutions for Task 66

### 1. Structured Output Support (Primary Solution)

Implement proper structured output using:
- **JSON Schema validation**: Define expected structure
- **Model capability detection**: Check if model supports structured output
- **Fallback strategies**: Retry with stronger model if needed
- **OpenAI-style function calling**: For models that support it

### 2. Immediate Mitigations (Can implement now)

#### A. Better Error Messages
```python
def post(self, shared, prep_res, exec_res):
    parsed = self.parse_json_response(exec_res["response"])

    # Validate expected structure if JSON
    if isinstance(parsed, dict) and self.params.get("expected_fields"):
        missing = set(self.params["expected_fields"]) - set(parsed.keys())
        if missing:
            logger.warning(f"LLM response missing expected fields: {missing}")

    shared["response"] = parsed
```

#### B. Template Resolution Warnings
```python
# In template_resolver.py
if var_name not in context:
    # Check if it's a common LLM output pattern
    if ".response." in var_name:
        logger.warning(
            f"Template '${{{var_name}}}' not found. "
            f"This often indicates the LLM didn't generate expected JSON fields."
        )
```

#### C. Model Strength Hints
```python
# In llm.py
MODELS_WITH_JSON_SUPPORT = {
    "strong": ["gpt-4", "claude-3", "gemini-2.5-flash", "gemini-2.5-pro"],
    "moderate": ["gpt-3.5-turbo", "claude-instant"],
    "weak": ["gemini-2.5-flash-lite", "llama-7b"]
}

def prep(self, shared):
    model = self.params.get("model", "gemini-2.5-flash-lite")

    # Warn if using weak model with JSON expectations
    if "json" in str(self.params.get("prompt", "")).lower():
        if model in MODELS_WITH_JSON_SUPPORT["weak"]:
            logger.warning(
                f"Model '{model}' has limited JSON generation capabilities. "
                f"Consider using a stronger model for reliable structured output."
            )
```

## Related Issues

1. **No JSON schema validation**: Can't specify expected structure
2. **No retry with stronger model**: Failures aren't recovered
3. **Silent failures**: Users see template variables instead of errors
4. **Model selection guidance**: No documentation on JSON capabilities

## Test Cases Needed

1. **Weak model JSON generation**:
   - Test with `gemini-2.5-flash-lite`
   - Verify warning messages appear
   - Check fallback behavior

2. **Template resolution with missing fields**:
   - Test `${node.response.missing_field}`
   - Verify helpful error messages

3. **Structured output validation**:
   - Define schema
   - Validate response matches schema
   - Handle validation failures

## Implementation Priority

1. **Immediate** (Now): Add warning messages for debugging
2. **Short-term** (Task 66): Implement JSON schema validation
3. **Long-term** (Task 66): Full structured output with model capabilities

## Code References

- LLM node: `/src/pflow/nodes/llm/llm.py`
- Template resolver: `/src/pflow/runtime/template_resolver.py`
- Failed workflow: `/Users/andfal/.pflow/workflows/slack-ai-qa-logger.json`

## Lessons Learned

1. **Model defaults matter**: Defaulting to weakest model causes issues
2. **Silent failures are confusing**: Template variables in output are cryptic
3. **JSON generation varies widely**: Not all models can reliably generate JSON
4. **Structured output is critical**: Many workflows depend on specific JSON structure

## Recommendations

### For Current Implementation

1. Change default model to `gemini-2.5-flash` (more reliable)
2. Add warnings when JSON parsing fails
3. Log when template resolution fails on `.response.` patterns
4. Document model JSON capabilities

### For Task 66

1. Implement proper structured output with schemas
2. Add model capability detection
3. Support OpenAI function calling format
4. Provide automatic retries with stronger models
5. Clear error messages when structure validation fails