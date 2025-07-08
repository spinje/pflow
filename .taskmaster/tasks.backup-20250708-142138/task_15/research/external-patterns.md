# External Patterns for Task 15: Implement LLM API client

## Summary
**Critical Recommendation**: DELETE this task entirely. Use Simon Willison's `llm` library directly instead of building a custom LLM client. This is a thin wrapper that adds no value.

Key insights:
- **Direct Usage**: The planner can import and use `llm` directly
- **No Abstraction Needed**: Adding a wrapper just adds complexity (confirmed: llm-main uses no internal wrappers)
- **Maintenance Burden**: Why maintain code that duplicates `llm`?
- **llm-main Pattern**: Even llm itself doesn't wrap its own API - it uses `model.prompt()` directly

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
        # This is the exact pattern used in llm's own documentation
        model = llm.get_model("claude-3-5-sonnet-latest")
        response = model.prompt(
            prompt,
            system=system_prompt,
            # Note: temperature is passed as a keyword argument, not in options
            temperature=0.7
        )

        # Parse JSON from response
        # response.text() is the standard llm API pattern
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

        # Fallback pattern from llm docs - get_model() with different model
        model = llm.get_model("gpt-4o-mini")
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
        """Get configured model using llm's standard API."""
        model_name = cls.FALLBACK_MODEL if fallback else cls.PRIMARY_MODEL
        # llm.get_model() is the standard API - no wrappers needed
        return llm.get_model(model_name)
```

## What This Task Should Have Been

If we were to keep this task, it should be minimal utilities.

**Important**: Even llm-main itself has no "LLM client" abstraction layer. The core API is simply:
- `llm.get_model()` - Get a model instance
- `model.prompt()` - Execute a prompt
- `response.text()` - Get the response text

No wrapper classes, no client objects, just direct function calls.

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
        """Test workflow generation from natural language.

        This follows llm's testing patterns - direct API usage, no wrappers.
        """
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
# OLD: Using wrapper (DON'T DO THIS)
from pflow.planning.llm_client import call_llm
response = call_llm(prompt, model="claude-3-5-sonnet")

# NEW: Direct usage (CORRECT - matches llm documentation)
import llm
model = llm.get_model("claude-3-5-sonnet-latest")
response = model.prompt(prompt)
# Access the text exactly as shown in llm docs
text = response.text()
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

## Actual llm API Usage

From llm's Python API documentation (docs/python-api.md):

```python
# Basic usage pattern from llm docs
import llm

model = llm.get_model("gpt-4o-mini")
response = model.prompt(
    "Five surprising names for a pet pelican",
    system="Answer like GlaDOS"
)
print(response.text())
```

Key observations from llm-main codebase:
1. **No internal wrappers**: Even llm itself calls `model.prompt()` directly
2. **Simple API**: `get_model()` → `prompt()` → `text()` is the complete flow
3. **Options as kwargs**: Temperature, system prompts, etc. are keyword arguments
4. **Lazy evaluation**: Response text is only generated when `text()` is called

## References
- `docs/implementation-details/simonw-llm-patterns/IMPLEMENTATION-GUIDE.md`: Task 15 recommendation
- `docs/implementation-details/simonw-llm-patterns/FINAL-ANALYSIS.md`: Why wrapping is unnecessary
- `llm-main/llm-main/docs/python-api.md`: Official Python API documentation
- `llm-main/llm-main/llm/__init__.py`: Core API exports (no client wrapper)
- Design principle: YAGNI (You Aren't Gonna Need It)
