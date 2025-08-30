# Task 17: JSON IR Generation Validation - Recommendation

**Note**: This document complements the broader Pydantic vs JSONSchema decision (`architecture/future-version/pydantic-vs-jsonschema-decision.md`) It focuses specifically on how the planner should generate JSON IR using a hybrid approach: Pydantic models for type-safe generation with Simon Willison's LLM library, followed by JSONSchema validation for comprehensive checking.

## Executive Summary

After extensive research into Simon Willison's LLM library and PocketFlow cookbook patterns, I recommend using **structured outputs with Pydantic models** for generation, validated by the existing **JSONSchema infrastructure**. This hybrid approach leverages the library's native capabilities for reliable JSON generation while maintaining our robust validation system.

## Updated Recommendation: Hybrid Validation Approach

### Why This Approach

1. **Type-Safe Generation**: Pydantic models provide type safety and IDE support during IR construction
2. **Native LLM Support**: Simon Willison's LLM library has first-class support for Pydantic schemas
3. **Comprehensive Validation**: JSONSchema validation ensures complete correctness beyond type safety
4. **No Replacement**: This complements, not replaces, the existing JSONSchema validation
5. **Best of Both Worlds**: Pydantic for generation, JSONSchema for validation

### Implementation Strategy

#### 1. Use Pydantic Models with LLM Library

```python
import llm
import json
from pocketflow import Node
from src.pflow.core import validate_ir  # JSONSchema validation
from src.pflow.planning.ir_models import FlowIR  # Pydantic models

class WorkflowGeneratorNode(Node):
    def exec(self, shared, prep_res):
        model = llm.get_model("claude-sonnet-4-20250514")

        # Generate workflow using Pydantic schema for type safety
        response = model.prompt(
            prompt=shared["planning_prompt"],
            schema=FlowIR,  # Pydantic model for generation
            system="You are a workflow generator. Generate valid JSON matching the schema."
        )

        # Parse the structured output
        workflow_dict = json.loads(response.text())

        # Validate with JSONSchema for comprehensive checking
        validate_ir(workflow_dict)  # Existing validation infrastructure

        # Additional business logic validation
        self._validate_nodes_exist(workflow_dict, shared["registry"])
        self._validate_connections(workflow_dict)

        return workflow_dict
```

#### 2. Error Handling and Retry Pattern

```python
def exec(self, shared, prep_res):
    max_attempts = 3
    errors = []

    model = llm.get_model("claude-sonnet-4-20250514")
    base_prompt = shared["planning_prompt"]

    for attempt in range(max_attempts):
        try:
            # Add error context for retries
            prompt = base_prompt
            if errors:
                prompt += f"\n\nPrevious attempt failed. Please fix these issues:\n"
                prompt += "\n".join(f"- {err}" for err in errors[-1])

            response = model.prompt(
                prompt=prompt,
                schema=WorkflowIR,
                system="Generate a valid workflow. Ensure all node types exist and connections are valid."
            )

            workflow_dict = json.loads(response.text())

            # Validate business logic
            self._validate_workflow(workflow_dict, shared["registry"])

            return workflow_dict

        except json.JSONDecodeError as e:
            errors.append([f"JSON parsing error: {str(e)}"])

        except ValidationError as e:
            # Convert Pydantic errors to readable format
            error_messages = []
            for err in e.errors():
                loc = " -> ".join(str(p) for p in err["loc"])
                error_messages.append(f"{loc}: {err['msg']}")
            errors.append(error_messages)

        except WorkflowValidationError as e:
            errors.append([str(e)])

    # All attempts failed
    raise WorkflowGenerationError(
        f"Failed to generate valid workflow after {max_attempts} attempts",
        errors=errors
    )
```

#### 3. Prompt Design for Structured Output

```python
def build_generation_prompt(user_request: str, context: dict) -> str:
    """Build prompt optimized for structured JSON output"""

    return f"""Generate a workflow for: {user_request}

Available nodes:
{context['available_nodes']}

Requirements:
1. Use only nodes from the available list
2. Create template variables ($variable) for user-provided values
3. Ensure proper data flow between nodes via shared store
4. Generate valid JSON matching the WorkflowIR schema

Example structure:
{{
  "ir_version": "0.1.0",
  "nodes": [
    {{
      "id": "fetch-issue",
      "type": "github-get-issue",
      "params": {{"issue_number": "$issue"}}
    }}
  ],
  "edges": [
    {{"from": "fetch-issue", "to": "analyze-issue"}}
  ],
  "mappings": {{
    "analyze-issue": {{
      "input_mappings": {{"prompt": "issue_data.body"}}
    }}
  }}
}}

Remember: Use template variables ($variable) for dynamic values, not hardcoded values."""
```

### Key Implementation Details

#### 1. Schema Definition Approach

Create Pydantic models in the planning module (NOT in core/ir_schema.py):

```python
# src/pflow/planning/ir_models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class NodeIR(BaseModel):
    """Node representation for IR generation."""
    id: str = Field(..., description="Unique node identifier")
    type: str = Field(..., description="Node type from registry")
    params: Dict[str, Any] = Field(default_factory=dict)

class EdgeIR(BaseModel):
    """Edge representation for IR generation."""
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    action: Optional[str] = Field(default="default")

class FlowIR(BaseModel):
    """Flow IR for planner output generation."""
    ir_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    nodes: List[NodeIR] = Field(..., min_items=1)
    edges: Optional[List[EdgeIR]] = Field(default_factory=list)
    start_node: Optional[str] = None
    mappings: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None

    def to_dict(self) -> dict:
        """Convert to dict for JSONSchema validation."""
        return self.model_dump(by_alias=True, exclude_none=True)
```

**Important**: These models are separate from the JSONSchema in `core/ir_schema.py`. They serve different purposes:
- **Pydantic models**: For type-safe IR generation with the LLM
- **JSONSchema**: For comprehensive validation of the final IR

#### 2. Alternative: Dictionary Schema

For simpler cases or when Pydantic models aren't suitable:

```python
workflow_schema = {
    "type": "object",
    "properties": {
        "ir_version": {
            "type": "string",
            "pattern": "^\\d+\\.\\d+\\.\\d+$"
        },
        "nodes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "params": {"type": "object"}
                },
                "required": ["id", "type"]
            }
        }
    },
    "required": ["ir_version", "nodes"]
}

response = model.prompt(prompt, schema=workflow_schema)
```

#### 3. Fallback Strategy

If structured output fails consistently, implement a fallback:

```python
def exec(self, shared, prep_res):
    try:
        # Try structured output first
        return self._generate_with_schema(shared)
    except WorkflowGenerationError:
        # Fallback to text parsing with markers
        return self._generate_with_text_parsing(shared)

def _generate_with_text_parsing(self, shared):
    """Fallback method using text markers"""
    response = model.prompt(
        shared["planning_prompt"],
        system="Generate JSON between ```json and ``` markers"
    )

    # Extract JSON from markers
    json_match = re.search(r'```json\n(.*?)\n```', response.text(), re.DOTALL)
    if not json_match:
        raise ValueError("No JSON found in response")

    workflow_dict = json.loads(json_match.group(1))
    # Validate with Pydantic
    workflow = WorkflowIR(**workflow_dict)
    return workflow.model_dump()
```

### When to Use Each Approach

1. **Pydantic + JSONSchema (Recommended)**:
   - Use Pydantic models for structured output generation
   - Validate with JSONSchema for comprehensive checking
   - Best reliability and type safety

2. **Dictionary Schema (Alternative)**:
   - When you can't use Pydantic models
   - For simpler schemas
   - Still validate with JSONSchema afterward

3. **Text Parsing (Fallback)**:
   - Only when structured output repeatedly fails
   - Extract JSON from markdown code blocks
   - Emergency fallback for edge cases

**Not Recommended**:
- **YAML**: Adds unnecessary conversion complexity
- **Pydantic-only**: Missing comprehensive validation
- **JSONSchema-only for generation**: No type safety during construction

### Testing Strategy

```python
import pytest
from unittest.mock import Mock, patch

def test_workflow_generation_with_retry():
    """Test that retry logic works correctly"""
    node = WorkflowGeneratorNode()

    # Mock LLM to fail twice then succeed
    mock_model = Mock()
    mock_model.prompt.side_effect = [
        Mock(text=lambda: '{"invalid": "json"'),  # First attempt - invalid JSON
        Mock(text=lambda: '{"ir_version": "bad"}'),  # Second attempt - invalid schema
        Mock(text=lambda: '{"ir_version": "0.1.0", "nodes": [...]}')  # Success
    ]

    with patch('llm.get_model', return_value=mock_model):
        result = node.exec({"planning_prompt": "test"}, None)
        assert mock_model.prompt.call_count == 3
```

### Migration Path

1. **Phase 1**: Implement structured output with existing Pydantic models
2. **Phase 2**: Add retry logic with error feedback
3. **Phase 3**: Implement fallback strategies if needed
4. **Phase 4**: Optimize prompts based on real-world usage

### Benefits of This Approach

1. **Simplicity**: Direct JSON generation without conversion steps
2. **Reliability**: Schema validation at model level
3. **Performance**: No parsing overhead from YAML
4. **Maintainability**: Single source of truth (Pydantic models)
5. **Flexibility**: Easy to add fields or modify schema
6. **Debugging**: Clear error messages from schema validation

### Potential Pitfalls and Mitigations

1. **Complex Nested Structures**:
   - Mitigation: Flatten schema where possible
   - Use clear examples in prompts

2. **Template Variable Handling**:
   - Mitigation: Explicit instructions about `$variable` syntax
   - Post-process to ensure variables aren't hardcoded

3. **Model Limitations**:
   - Mitigation: Test with target model early
   - Have fallback parsing strategy ready

### Conclusion

The hybrid approach of using Pydantic models for generation with JSONSchema validation is optimal for the pflow planner. This strategy:

1. **Leverages LLM capabilities**: Uses structured outputs with type-safe Pydantic models
2. **Maintains existing validation**: JSONSchema continues to be the authoritative validator
3. **Provides best developer experience**: Type hints during development, comprehensive validation at runtime
4. **Follows separation of concerns**: Generation models in planning module, validation in core module

This approach gives us the reliability needed for production use while maintaining clean, maintainable code.
