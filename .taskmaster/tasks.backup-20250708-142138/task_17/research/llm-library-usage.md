# LLM Library Usage for Task 17

## Context

Task 15 ("Implement LLM API client") has been removed from the project. Task 17 (Workflow Generation Engine) now depends on Task 12 (general LLM node) instead.

## Key Change: Direct LLM Library Usage

The workflow generation engine should use Simon Willison's `llm` library directly for its internal LLM calls, not through any wrapper.

### Why Direct Usage?

1. **Follows library patterns** - Even `llm` itself doesn't wrap its own API
2. **Simpler code** - No unnecessary abstraction layers
3. **Better maintainability** - One less component to maintain
4. **Clear separation** - Internal implementation vs user-facing nodes

## Implementation Pattern

```python
# src/pflow/planning/workflow_compiler.py
import llm
import json
from typing import Dict, Optional

def generate_workflow_ir(user_request: str, node_context: str) -> dict:
    """Generate workflow IR from natural language request.

    This function uses the llm library directly for planning.
    It does NOT use the LLM node from Task 12 - that's for user workflows.
    """

    # System prompt for workflow generation
    system_prompt = """You are a workflow planner for pflow.
Generate valid JSON IR format for workflows.
Only output JSON, no explanations."""

    # Build the full prompt
    prompt = f"""Available nodes:
{node_context}

User request: {user_request}

Generate a workflow as JSON IR with this structure:
{{
    "nodes": [
        {{"id": "n1", "type": "node-name", "params": {{...}}}},
        ...
    ],
    "edges": [
        {{"from": "n1", "to": "n2", "action": "default"}},
        ...
    ],
    "start_node": "n1"
}}
"""

    try:
        # Use llm directly - no wrapper needed!
        model = llm.get_model("claude-3-5-sonnet-latest")
        response = model.prompt(
            prompt,
            system=system_prompt,
            temperature=0.7
        )

        # Parse JSON from response
        result = response.text().strip()

        # Handle markdown-wrapped JSON
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()

        return json.loads(result)

    except json.JSONDecodeError:
        # Retry with more explicit instructions
        retry_prompt = prompt + "\n\nIMPORTANT: Output ONLY valid JSON, no other text."

        # Fallback to different model if needed
        model = llm.get_model("gpt-4o-mini")
        response = model.prompt(retry_prompt, temperature=0.3)

        return json.loads(response.text().strip())

    except Exception as e:
        # Log error and raise
        raise RuntimeError(f"Failed to generate workflow: {e}")
```

## Configuration Pattern

```python
# src/pflow/planning/config.py
import os

class PlannerConfig:
    """Configuration for the workflow planner."""

    # Model preferences for planning
    PRIMARY_MODEL = os.getenv("PFLOW_PLANNER_MODEL", "claude-3-5-sonnet-latest")
    FALLBACK_MODEL = os.getenv("PFLOW_PLANNER_FALLBACK", "gpt-4o-mini")

    # Temperature settings
    CREATIVE_TEMP = 0.7  # For initial generation
    PRECISE_TEMP = 0.3   # For retries and JSON fixing

    # Retry settings
    MAX_RETRIES = 3

    @classmethod
    def get_model(cls, fallback=False):
        """Get configured model using llm's standard API."""
        model_name = cls.FALLBACK_MODEL if fallback else cls.PRIMARY_MODEL
        # llm.get_model() is the standard API - no wrappers needed
        return llm.get_model(model_name)
```

## Utility Functions

If needed, create minimal utility functions for common operations:

```python
# src/pflow/planning/utils.py
import json

def parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response text."""
    # Remove markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    return json.loads(text.strip())

def validate_workflow_ir(ir: dict) -> bool:
    """Validate that IR has required structure."""
    required = {"nodes", "edges", "start_node"}
    return all(key in ir for key in required)
```

## Important Distinction

### What Task 17 Uses
- **Direct `llm` library calls** for its own planning logic
- No wrappers, just `llm.get_model()` → `model.prompt()` → `response.text()`

### What Task 17 Generates
- Workflows that include the **LLM node from Task 12**
- Example generated IR:
```json
{
    "nodes": [
        {"id": "n1", "type": "read-file", "params": {"path": "data.txt"}},
        {"id": "n2", "type": "llm", "params": {"prompt": "Summarize: $content"}}
    ],
    "edges": [
        {"from": "n1", "to": "n2", "action": "default"}
    ],
    "start_node": "n1"
}
```

## Testing Approach

```python
import pytest
from unittest.mock import patch, Mock

@patch('llm.get_model')
def test_workflow_generation(mock_get_model):
    """Test that planner uses llm library directly."""
    # Mock the llm library response
    mock_response = Mock()
    mock_response.text.return_value = '{"nodes": [], "edges": [], "start_node": "n1"}'

    mock_model = Mock()
    mock_model.prompt.return_value = mock_response
    mock_get_model.return_value = mock_model

    # Test workflow generation
    from pflow.planning.workflow_compiler import generate_workflow_ir

    result = generate_workflow_ir("test request", "node context")

    # Verify llm was called directly
    mock_get_model.assert_called_with("claude-3-5-sonnet-latest")
    assert "nodes" in result
```

## Summary

Task 17 should:
1. Import and use `llm` library directly
2. Not create or use any wrapper functions
3. Generate workflows that may include the LLM node from Task 12
4. Keep LLM interaction code simple and direct

This approach maintains clean separation between:
- **Internal implementation** (direct llm usage)
- **User-facing components** (nodes in workflows)
