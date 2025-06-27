# External Patterns for Task 15: Implement LLM API client

## Summary
**Critical Recommendation**: DELETE this task entirely. Use Simon Willison's `llm` library directly instead of building a custom LLM client. This is a thin wrapper that adds no value.

Key insights:
- **Direct Usage**: The planner can import and use `llm` directly
- **No Abstraction Needed**: Adding a wrapper just adds complexity
- **Maintenance Burden**: Why maintain code that duplicates `llm`?

## Recommended Implementation

### Pattern: Direct LLM Usage in Planner

Instead of creating `src/pflow/planning/llm_client.py`, use `llm` directly:

```python
# src/pflow/planning/workflow_compiler.py
import llm
import json
from typing import Optional

def generate_workflow_ir(user_request: str, node_context: str) -> dict:
    """Generate workflow IR from natural language request."""

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

        model = llm.get_model("gpt-4o-mini")  # Fallback model
        response = model.prompt(retry_prompt, temperature=0.3)

        return json.loads(response.text().strip())

    except Exception as e:
        # Log error and raise
        raise RuntimeError(f"Failed to generate workflow: {e}")
```

### Pattern: Configuration for Planning

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
        """Get configured model."""
        model_name = cls.FALLBACK_MODEL if fallback else cls.PRIMARY_MODEL
        return llm.get_model(model_name)
```

## What This Task Should Have Been

If we were to keep this task, it should be minimal utilities:

```python
# src/pflow/planning/utils.py
import llm
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

## Testing Without a Wrapper

```python
# tests/test_planning.py
import pytest
import vcr
from pflow.planning.workflow_compiler import generate_workflow_ir

class TestPlanning:
    @vcr.use_cassette('fixtures/planning/simple_workflow.yaml')
    def test_generate_simple_workflow(self):
        """Test workflow generation from natural language."""
        node_context = """
- read-file: Reads file from disk
  Inputs: file_path
  Outputs: content
- llm: Process text with LLM
  Inputs: prompt
  Outputs: response
"""

        request = "Read file data.txt and summarize it"

        ir = generate_workflow_ir(request, node_context)

        assert "nodes" in ir
        assert len(ir["nodes"]) >= 2
        assert any(n["type"] == "read-file" for n in ir["nodes"])
        assert any(n["type"] == "llm" for n in ir["nodes"])
```

## Why Direct Usage is Better

1. **Less Code**: No wrapper to maintain
2. **Direct Access**: All `llm` features available immediately
3. **Better Errors**: `llm` has good error messages already
4. **Automatic Updates**: New features available instantly
5. **No Abstraction Leak**: Wrapper would just pass through anyway

## Migration if Wrapper Already Exists

```python
# OLD: Using wrapper
from pflow.planning.llm_client import call_llm
response = call_llm(prompt, model="claude-3-5-sonnet")

# NEW: Direct usage
import llm
model = llm.get_model("claude-3-5-sonnet-latest")
response = model.prompt(prompt)
```

## Common Pitfalls to Avoid

1. **Don't create unnecessary abstractions**: Use `llm` directly
2. **Don't wrap what doesn't need wrapping**: Thin wrappers add no value
3. **Don't hide the power**: `llm` has many features you might want later
4. **Don't duplicate retry logic**: `llm` handles retries already

## The Right Abstraction Level

The only abstraction needed is at the workflow generation level:
- `generate_workflow_ir()` - Domain-specific function
- `parse_json_response()` - Reusable utility
- Direct `llm` usage - No wrapper needed

## References
- IMPLEMENTATION-GUIDE.md: Task 15 recommendation
- FINAL-ANALYSIS.md: Why wrapping is unnecessary
- LLM docs: Direct usage examples
- Design principle: YAGNI (You Aren't Gonna Need It)
