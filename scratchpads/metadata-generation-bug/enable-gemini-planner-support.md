# Task: Enable Gemini/OpenAI Support for Planner Nodes

## Problem Statement

Currently, the planner only works with Anthropic models. When using Gemini or OpenAI models, the planner fails with schema-related errors:

```
Invalid JSON payload received. Unknown name "$defs" at 'generation_config.response_schema'
Invalid JSON payload received. Unknown name "$ref" at 'generation_config.response_schema.properties[1].value.items'
Invalid JSON payload received. Unknown name "additionalProperties" at 'generation_config.response_schema.properties[4].value.any_of[0]'
```

### Root Cause

1. **Pydantic V2 Schema Generation**: When using nested Pydantic models (like `FlowIR` which contains `NodeIR` and `EdgeIR`), Pydantic generates JSON schemas with `$defs` and `$ref` references:

```json
{
  "$defs": {
    "EdgeIR": {...},
    "NodeIR": {...}
  },
  "properties": {
    "edges": {
      "items": {"$ref": "#/$defs/EdgeIR"}
    }
  }
}
```

2. **Gemini API Limitations**: Google's Gemini API doesn't support:
   - `$defs` (schema definitions)
   - `$ref` (schema references)
   - `additionalProperties` in schemas

3. **Current Implementation**: All 8 planner nodes pass `schema=FlowIR` (or other Pydantic models) to `model.prompt()`, which works for Anthropic but fails for Gemini/OpenAI.

## What We Already Fixed

**Repair service** (`src/pflow/execution/repair_service.py`) was successfully updated to support both Anthropic and non-Anthropic models:

```python
# Check model type
is_anthropic = repair_model and (
    repair_model.startswith("anthropic/")
    or repair_model.startswith("claude-")
    or "claude" in repair_model.lower()
)

if is_anthropic:
    # Use structured output with schema
    llm_kwargs = {
        "schema": FlowIR,
        "cache_blocks": cache_blocks,
        "temperature": 0.0,
        "thinking_budget": 0,
    }
    response = model.prompt(prompt, **llm_kwargs)
    result = parse_structured_response(response, FlowIR)
    # ... validate and convert with by_alias=True
else:
    # Use text mode, extract JSON manually
    llm_kwargs = {"temperature": 0.0}
    response = model.prompt(prompt, **llm_kwargs)
    response_text = response.text() if callable(response.text) else response.text
    result = _extract_workflow_from_response(response_text)
```

**Key insights from the fix:**
- Anthropic models work with structured output (schema parameter)
- Non-Anthropic models need text mode (no schema parameter)
- JSON must be extracted from text response for Gemini/OpenAI
- Existing helper function `_extract_workflow_from_response()` can parse JSON from text

## What Needs to Be Done

Update all 8 LLM-powered planner nodes to detect model type and use appropriate prompting strategy.

### Affected Nodes (in `src/pflow/planning/nodes.py`)

1. **WorkflowDiscoveryNode** (line ~866)
   - Currently: `model.prompt(prompt, schema=WorkflowSearchResult, cache_blocks=...)`
   - Schema: `WorkflowSearchResult` (has nested models)

2. **ComponentBrowsingNode** (line ~1057)
   - Currently: `model.prompt(prompt, schema=ComponentBrowsingResult, cache_blocks=...)`
   - Schema: `ComponentBrowsingResult` (has nested models)

3. **ParameterDiscoveryNode** (line ~1260)
   - Currently: `model.prompt(prompt, schema=ParameterDiscoveryResult, cache_blocks=...)`
   - Schema: `ParameterDiscoveryResult` (has nested models)

4. **RequirementsAnalysisNode** (line ~1447)
   - Currently: `model.prompt(prompt, schema=RequirementsResult, cache_blocks=...)`
   - Schema: `RequirementsResult`

5. **PlanningNode** (line ~1663)
   - Currently: `model.prompt(prompt, schema=PlanningResult, cache_blocks=...)`
   - Schema: `PlanningResult`

6. **ParameterMappingNode** (line ~1791)
   - Currently: `model.prompt(prompt, schema=ParameterMappingResult, cache_blocks=...)`
   - Schema: `ParameterMappingResult`

7. **WorkflowGeneratorNode** (line ~2092)
   - Currently: `model.prompt(prompt, schema=FlowIR, cache_blocks=...)`
   - Schema: `FlowIR` (has nested `NodeIR` and `EdgeIR`)

8. **MetadataGenerationNode** (line ~2238)
   - Currently: `model.prompt(prompt, schema=WorkflowMetadata, cache_blocks=...)`
   - Schema: `WorkflowMetadata`

### Implementation Pattern for Each Node

For each node's `exec()` method, replace the current single-path implementation with a dual-path approach:

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute node with model-specific prompting strategy."""

    # ... existing prep code ...

    model = llm.get_model(prep_res["model_name"])

    # Detect model type
    model_name = prep_res["model_name"]
    is_anthropic = model_name and (
        model_name.startswith("anthropic/")
        or model_name.startswith("claude-")
        or "claude" in model_name.lower()
    )

    if is_anthropic:
        # Path 1: Structured output for Anthropic
        response = model.prompt(
            prompt,
            schema=ExpectedSchema,  # Keep existing schema
            cache_blocks=blocks,    # Keep existing cache_blocks
            temperature=prep_res["temperature"],
            thinking_budget=prep_res.get("thinking_budget", 0),
        )
        # Parse structured response (existing code)
        result = parse_structured_response(response, ExpectedSchema)
    else:
        # Path 2: Text mode for Gemini/OpenAI
        response = model.prompt(
            prompt,
            temperature=prep_res["temperature"],
            # NO schema, NO cache_blocks, NO thinking_budget
        )
        # Extract JSON from text
        response_text = response.text() if callable(response.text) else response.text
        result = _extract_json_from_text(response_text, ExpectedSchema)

    # ... rest of existing post-processing code ...
```

### Helper Function Needed

Create a reusable JSON extraction function in `src/pflow/planning/utils/llm_helpers.py`:

```python
def extract_json_from_text(text: str, expected_schema: type[BaseModel]) -> dict[str, Any]:
    """Extract and validate JSON from LLM text response.

    Args:
        text: Raw text response from LLM
        expected_schema: Pydantic model for validation

    Returns:
        Parsed and validated dict

    Raises:
        ValueError: If JSON cannot be extracted or validated
    """
    # Try to find JSON in response (look for {...} or [...])
    import json
    import re

    # Find JSON block
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if not json_match:
        raise ValueError(f"No JSON found in response: {text[:200]}")

    # Parse JSON
    try:
        data = json.loads(json_match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in response: {e}")

    # Validate with Pydantic (optional but recommended)
    try:
        validated = expected_schema.model_validate(data)
        return validated.model_dump(by_alias=True, exclude_none=True)
    except Exception as e:
        logger.warning(f"Schema validation failed, using raw data: {e}")
        return data
```

Note: You can also reuse the existing `_extract_workflow_from_response()` function from `repair_service.py` - consider moving it to `llm_helpers.py` for reuse.

### Additional Considerations

1. **Cache Blocks**: Only pass `cache_blocks` to Anthropic models. Gemini/OpenAI don't support this parameter.

2. **Thinking Budget**: Only pass `thinking_budget` to Anthropic models.

3. **Prompt Updates**: The prompts should already instruct the LLM to return JSON. Verify each prompt ends with clear JSON format instructions.

4. **Error Handling**: Ensure graceful degradation if JSON extraction fails.

5. **Testing**: Test each node individually with both Anthropic and Gemini models to ensure both paths work.

## Verification Steps

After implementing the changes:

1. **Test Gemini Planner**:
```bash
uv run pflow --planner-model gemini-2.5-flash-lite "create a workflow that echoes hello world"
```

2. **Test Anthropic Planner** (should still work):
```bash
uv run pflow --planner-model anthropic/claude-sonnet-4-5 "create a workflow that echoes hello world"
```

3. **Test Complex Workflow**:
```bash
uv run pflow --planner-model gemini-2.5-flash-lite "call an llm to write a joke about cats then save it to a file named cat.md"
```

4. **Verify Repair Still Works**:
```bash
# Test with intentionally broken workflow
uv run pflow --planner-model gemini-2.5-flash-lite test3-multi-node.json
```

## Success Criteria

- ✅ All 8 planner nodes work with Gemini models
- ✅ All 8 planner nodes still work with Anthropic models
- ✅ Planner can generate complete workflows with Gemini
- ✅ Repair continues to work with both model types
- ✅ No regressions in existing Anthropic functionality

## Files to Modify

1. **`src/pflow/planning/nodes.py`** - Update all 8 node exec() methods
2. **`src/pflow/planning/utils/llm_helpers.py`** - Add JSON extraction helper (optional, can reuse existing)

## Files to Reference

1. **`src/pflow/execution/repair_service.py`** (lines 67-103) - Working example of dual-path implementation
2. **`src/pflow/planning/utils/llm_helpers.py`** - Existing `parse_structured_response()` function
3. **`src/pflow/execution/repair_service.py`** (line 605) - `_extract_workflow_from_response()` function that works

## Notes

- This is a **refactoring task**, not a new feature
- The logic for each node stays the same, only the LLM prompting strategy changes
- Gemini will not have schema validation during generation (only after parsing), but this is acceptable
- The fix follows the same pattern already proven to work in the repair service
