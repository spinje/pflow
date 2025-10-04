# Task: Fix Planner to Support Gemini/OpenAI Models (Schema Compatibility Issue)

## Problem Statement

The planner currently ONLY works with Anthropic models. When using Gemini or OpenAI models via `--planner-model gemini-2.5-flash-lite`, the planner fails with errors like:

```
❌ Planning aborted: Cannot determine workflow routing: Invalid request format or parameters
```

Or schema-related errors:

```
Invalid JSON payload received. Unknown name "$defs" at 'generation_config.response_schema'
Invalid JSON payload received. Unknown name "$ref" at 'generation_config.response_schema.properties[1].value.items'
Invalid JSON payload received. Unknown name "additionalProperties" at 'generation_config.response_schema.properties[2].value.items'
```

### Root Cause: JSON Schema Incompatibility

**The Problem:**
1. All planner nodes use `model.prompt(prompt, schema=FlowIR, ...)` for structured output
2. `FlowIR` is a Pydantic model with nested models (`NodeIR`, `EdgeIR`)
3. When Pydantic generates JSON schema for nested models, it uses `$defs` and `$ref`:
   ```json
   {
     "properties": {
       "edges": {
         "items": {
           "$ref": "#/$defs/EdgeIR"  // ← Gemini doesn't support this
         }
       }
     },
     "$defs": {
       "EdgeIR": { ... }  // ← Gemini doesn't support this
     }
   }
   ```

4. **Anthropic** handles this fine (via our monkey-patched `AnthropicLLMModel`)
5. **Gemini/OpenAI** reject schemas with `$defs`, `$ref`, and `additionalProperties`

### Why This Happens

The `llm` library passes Pydantic models to each provider's plugin:
- **llm-anthropic**: We intercept with `AnthropicLLMModel` (supports complex schemas)
- **llm-gemini**: Calls `model.model_json_schema()` which generates `$defs`/`$ref`
- **llm-openai**: Similar schema conversion issues

Gemini's structured output API is more restrictive and doesn't support JSON Schema Draft 7 features like `$defs`/`$ref`.

## Solution That Works (Already Implemented in Repair)

The **repair service** was successfully fixed to support both Anthropic and Gemini models. Here's how:

### Current Repair Implementation (src/pflow/execution/repair_service.py lines 67-103)

```python
# Check if this is an Anthropic model
is_anthropic = repair_model and (
    repair_model.startswith("anthropic/")
    or repair_model.startswith("claude-")
    or "claude" in repair_model.lower()
)

if is_anthropic:
    # Anthropic: Use full FlowIR with nested models (supports $defs/$ref and structured output)
    llm_kwargs = {
        "schema": FlowIR,
        "temperature": 0.0,
        "thinking_budget": 0,
        "cache_blocks": cache_blocks,
    }
    # Generate repair with structured output
    response = model.prompt(prompt, **llm_kwargs)

    # Parse structured response
    from pflow.planning.utils.llm_helpers import parse_structured_response
    result = parse_structured_response(response, FlowIR)
else:
    # Non-Anthropic (Gemini, OpenAI): Use text mode, no structured output
    llm_kwargs = {
        "temperature": 0.0,
    }
    # Generate repair in text mode
    response = model.prompt(prompt, **llm_kwargs)

    # Extract JSON from text response
    response_text = response.text() if callable(response.text) else response.text
    result = _extract_workflow_from_response(response_text)
    if not result:
        logger.error(f"Failed to extract JSON from LLM response: {response_text[:200]}")
        return False, None
```

**Key Differences:**
- **Anthropic path**: Uses `schema=FlowIR` for structured output + `cache_blocks` parameter
- **Non-Anthropic path**: Uses text mode (no schema), extracts JSON from response text

**Result Handling:**
- Anthropic: Returns structured data, needs `FlowIR.model_validate()` + `model_dump(by_alias=True)` to convert `from_node`/`to_node` → `from`/`to`
- Non-Anthropic: Returns dict from JSON extraction, already has correct format

## What Needs to Be Done

Apply the same pattern to **all 8 LLM-powered planner nodes**:

### Affected Planner Nodes (src/pflow/planning/nodes.py)

1. **WorkflowDiscoveryNode** (line ~866)
2. **ComponentBrowsingNode** (line ~1052)
3. **ParameterDiscoveryNode** (line ~1170)
4. **RequirementsAnalysisNode** (line ~1309)
5. **PlanningNode** (line ~1534)
6. **ParameterMappingNode** (line ~1684)
7. **WorkflowGeneratorNode** (line ~1942)
8. **MetadataGenerationNode** (line ~2186)

### Implementation Steps

For EACH node above:

#### Step 1: Detect Model Type in `exec()` method

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    # Get model name from prep_res
    model_name = prep_res.get("model_name") or prep_res.get("model")

    # Detect if Anthropic
    is_anthropic = model_name and (
        model_name.startswith("anthropic/")
        or model_name.startswith("claude-")
        or "claude" in model_name.lower()
    )

    # ... rest of implementation
```

#### Step 2: Branch Based on Model Type

**For Anthropic models** (keep existing behavior):
```python
if is_anthropic:
    # Use structured output with schema
    response = model.prompt(
        prompt,
        schema=ExpectedSchema,  # FlowIR, DiscoveryResult, etc.
        cache_blocks=cache_blocks,
        temperature=temp,
        thinking_budget=budget,
    )

    # Parse structured response
    result = parse_structured_response(response, ExpectedSchema)
```

**For Non-Anthropic models** (new text mode path):
```python
else:
    # Use text mode, no schema
    response = model.prompt(
        prompt,
        temperature=temp,
        # NO schema, NO cache_blocks, NO thinking_budget
    )

    # Extract JSON from text
    response_text = response.text() if callable(response.text) else response.text

    # Parse JSON (each node may need custom extraction)
    result = _extract_json_from_response(response_text)
    # OR use existing helper: _extract_workflow_from_response(response_text)
```

#### Step 3: Handle Result Conversion

**Important**: Each node has a different response schema:
- `WorkflowDiscoveryNode` → `DiscoveryResult`
- `ComponentBrowsingNode` → dict with `browsed_components`
- `ParameterDiscoveryNode` → dict with `parameters`
- `RequirementsAnalysisNode` → `RequirementsResult`
- `PlanningNode` → dict with `execution_plan`
- `ParameterMappingNode` → dict with `mapped_parameters`
- `WorkflowGeneratorNode` → `FlowIR`
- `MetadataGenerationNode` → `WorkflowMetadata`

For Anthropic results (if Pydantic model):
```python
if hasattr(result, "model_dump"):
    result = result.model_dump(by_alias=True, exclude_none=True)
```

For non-Anthropic results:
```python
# Already a dict from JSON parsing
# Just validate it has required fields
if not result or "expected_field" not in result:
    raise CriticalPlanningError(...)
```

#### Step 4: Update Prompts for JSON Clarity

For non-Anthropic models, the prompt should be VERY explicit about JSON format:

```python
if not is_anthropic:
    prompt += "\n\nIMPORTANT: Return your response as a valid JSON object with this exact structure:\n"
    prompt += "{\n"
    prompt += "  \"field1\": \"value\",\n"
    prompt += "  \"field2\": [...]\n"
    prompt += "}\n"
    prompt += "Do not include any markdown formatting or code blocks. Return ONLY the JSON object."
```

### Example: WorkflowDiscoveryNode Fix

**Current code** (line ~950 in nodes.py):
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    # ... setup code ...

    model = llm.get_model(prep_res["model_name"])

    response = model.prompt(
        prompt,
        schema=DiscoveryResult,
        cache_blocks=blocks,
        temperature=prep_res["temperature"],
        thinking_budget=thinking_budget,
    )

    result = parse_structured_response(response, DiscoveryResult)
```

**Fixed code**:
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    # ... setup code ...

    model_name = prep_res["model_name"]
    model = llm.get_model(model_name)

    # Detect model type
    is_anthropic = model_name and (
        model_name.startswith("anthropic/")
        or model_name.startswith("claude-")
        or "claude" in model_name.lower()
    )

    if is_anthropic:
        # Anthropic: structured output with schema
        response = model.prompt(
            prompt,
            schema=DiscoveryResult,
            cache_blocks=blocks,
            temperature=prep_res["temperature"],
            thinking_budget=thinking_budget,
        )
        result = parse_structured_response(response, DiscoveryResult)
    else:
        # Non-Anthropic: text mode
        response = model.prompt(
            prompt,
            temperature=prep_res["temperature"],
        )
        response_text = response.text() if callable(response.text) else response.text

        # Parse JSON from text
        import json
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                # Try to find raw JSON object
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    raise CriticalPlanningError(
                        node_name="WorkflowDiscoveryNode",
                        reason="Failed to parse LLM response as JSON",
                        original_error=None
                    )

    # Validate result has required structure
    if isinstance(result, dict):
        # Convert dict to DiscoveryResult if needed
        if "decision" not in result:
            raise CriticalPlanningError(...)
```

## Testing Strategy

### 1. Test Each Node Individually

Create test workflows that exercise each node:

```bash
# Test WorkflowDiscoveryNode
uv run pflow --planner-model gemini-2.5-flash-lite "list files in current directory"

# Test ComponentBrowsingNode
uv run pflow --planner-model gemini-2.5-flash-lite "create a workflow to read and process data"

# Test WorkflowGeneratorNode
uv run pflow --planner-model gemini-2.5-flash-lite "save hello world to test.txt"
```

### 2. Test Both Model Types

For each test case, run with both:
- Anthropic: `--planner-model anthropic/claude-sonnet-4-5`
- Gemini: `--planner-model gemini-2.5-flash-lite`
- OpenAI: `--planner-model gpt-4o-mini` (if available)

### 3. Verify Repair Works

The repair service already works with both models. Test:

```bash
# Create intentionally broken workflow
echo '{"ir_version":"0.1.0","nodes":[{"id":"test","type":"shell","params":{"command":"cat nonexistent.txt | jq .field"}}],"edges":[]}' > broken.json

# Test repair with Gemini
uv run pflow --planner-model gemini-2.5-flash-lite broken.json
```

### 4. Check Edge Cases

- Mixed node types in same workflow
- Nodes with thinking budgets (non-Anthropic should ignore)
- Nodes with cache blocks (non-Anthropic should not use)
- Error handling when JSON extraction fails

## Files to Modify

1. **src/pflow/planning/nodes.py** - Update all 8 LLM nodes
2. **Optional: Create helper function** in nodes.py:
   ```python
   def _prompt_with_model_detection(
       model: Any,
       model_name: str,
       prompt: str,
       schema: Optional[type],
       cache_blocks: Optional[list] = None,
       temperature: float = 0.0,
       thinking_budget: int = 0,
   ) -> dict:
       """Universal prompt function that handles Anthropic vs non-Anthropic models."""
       # Implementation here...
   ```

## Expected Outcome

After implementation:
- ✅ Planner works with Anthropic models (existing behavior preserved)
- ✅ Planner works with Gemini models (new text-mode path)
- ✅ Planner works with OpenAI models (new text-mode path)
- ✅ Repair continues to work with all models (already fixed)
- ✅ All tests pass for both model types

## Related Context

### Key Files
- `src/pflow/execution/repair_service.py` - Reference implementation (lines 67-121)
- `src/pflow/planning/nodes.py` - Nodes to fix (8 nodes, ~2400 lines total)
- `src/pflow/planning/ir_models.py` - Schema definitions (FlowIR, FlatFlowIR, etc.)
- `src/pflow/planning/utils/llm_helpers.py` - Helper functions for parsing

### Why We Have This Problem
1. Pydantic V2 always generates `$defs` for nested models
2. Gemini's API rejects `$defs`, `$ref`, and `additionalProperties`
3. The `llm` library doesn't handle this conversion automatically
4. Our Anthropic monkey-patch works around this for Claude models only

### Why Text Mode Works
- No schema validation during generation
- LLM returns JSON as text (in markdown or raw)
- We parse the JSON manually with fallbacks
- Less type safety but more provider compatibility

## Estimated Effort

- **Per node**: ~30-45 minutes
- **8 nodes total**: ~4-6 hours
- **Testing**: ~2 hours
- **Total**: ~6-8 hours

## Priority

**Medium-High** - Gemini models are significantly cheaper than Anthropic, and users expect `--planner-model` to work with any provider.

## References

- Original bug fix discussion: scratchpads/metadata-generation-bug/fix-metadata-generation-cache-blocks-error.md
- Repair implementation: src/pflow/execution/repair_service.py lines 67-121
- Gemini schema errors: https://ai.google.dev/gemini-api/docs/structured-output (doesn't support $defs/$ref)
