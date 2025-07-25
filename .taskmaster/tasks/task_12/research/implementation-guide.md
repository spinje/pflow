# Task 12 Implementation Guide: General LLM Node

## Overview

Task 12 implements the general-purpose LLM node that serves as the primary text processing component in pflow workflows. This node wraps Simon Willison's `llm` library to provide a consistent, user-friendly interface for LLM operations.

## Design Principles

1. **Smart Exception Pattern**: One flexible LLM node instead of many specific prompt nodes
2. **Natural Interface**: Uses shared store with intuitive keys (`prompt` → `response`)
3. **Progressive Enhancement**: Start minimal, add features based on usage
4. **Direct Library Usage**: Leverage `llm` library without unnecessary abstraction

## Implementation Specification

### File Location
`src/pflow/nodes/llm.py`

### Core Implementation (MVP)

```python
from pocketflow import Node
import llm
import json
from typing import Optional, Dict, Any

class LLMNode(Node):
    """General-purpose LLM node for text processing.

    This node serves as a smart exception to pflow's simple node philosophy,
    consolidating all prompt-based text processing into one flexible component.

    Uses Simon Willison's llm library for model management and execution.

    Shared Store Interface:
        Inputs:
            - prompt (required): The prompt text to send to the model
            - system (optional): System prompt for behavior guidance
            - model (optional): Model ID or alias (default: claude-sonnet-4-20250514)
            - temperature (optional): Sampling temperature (default: 0.7)
            - max_tokens (optional): Maximum response tokens
            - format (optional): "text" or "json" (default: text)

        Outputs:
            - response: The model's response (text or parsed JSON)
            - usage: Token usage information (when available)

    Example:
        shared["prompt"] = "Summarize this text in 3 bullet points"
        # After execution:
        shared["response"] = "• Point 1\n• Point 2\n• Point 3"
    """

    name = "llm"  # Registry name - critical for discovery

    def __init__(self, max_retries=3, wait=1):
        """Initialize with retry configuration.

        Args:
            max_retries: Number of attempts before failing
            wait: Seconds to wait between retries
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare inputs from shared store.

        Validates required inputs and extracts parameters.
        """
        # Fail fast on missing required input
        if "prompt" not in shared:
            raise ValueError(
                "LLM node requires 'prompt' in shared store. "
                "Please ensure previous nodes set shared['prompt'] "
                "or provide --prompt parameter."
            )

        # Extract all parameters with defaults
        return {
            "prompt": shared["prompt"],
            "system": shared.get("system"),
            "model": shared.get("model", "claude-sonnet-4-20250514"),
            "temperature": shared.get("temperature", 0.7),
            "max_tokens": shared.get("max_tokens"),
            "format": shared.get("format", "text")
        }

    def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the LLM call.

        Uses llm library directly for model management.
        """
        # Get model (may raise UnknownModelError)
        model = llm.get_model(prep_res["model"])

        # Build kwargs for prompt call
        kwargs = {
            "temperature": prep_res["temperature"]
        }

        # Only add optional parameters if provided
        if prep_res["system"] is not None:
            kwargs["system"] = prep_res["system"]
        if prep_res["max_tokens"] is not None:
            kwargs["max_tokens"] = prep_res["max_tokens"]

        # Execute prompt (lazy evaluation)
        response = model.prompt(prep_res["prompt"], **kwargs)

        # Force evaluation and get text
        result = response.text()

        # Handle JSON format request
        if prep_res["format"] == "json":
            result = self._parse_json_response(result)

        # Return both response and usage info
        return {
            "response": result,
            "usage": getattr(response, "usage", None)
        }

    def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
             exec_res: Dict[str, Any]) -> str:
        """Store results in shared store.

        Always writes response, optionally writes usage.
        """
        shared["response"] = exec_res["response"]

        # Only write usage if available
        if exec_res["usage"] is not None:
            shared["usage"] = exec_res["usage"]

        # Always return default action
        return "default"

    def exec_fallback(self, prep_res: Dict[str, Any], exc: Exception) -> None:
        """Provide helpful error messages on failure.

        Improves error messages for common failure modes.
        """
        error_msg = str(exc)

        # Enhance error messages
        if "JSONDecodeError" in error_msg:
            raise ValueError(
                f"Failed to parse JSON from LLM response. "
                f"Ensure the model supports JSON output or try a different model. "
                f"Original error: {exc}"
            )
        elif "UnknownModelError" in error_msg:
            raise ValueError(
                f"Unknown model: {prep_res['model']}. "
                f"Run 'llm models' to see available models. "
                f"Original error: {exc}"
            )
        elif "NeedsKeyException" in error_msg:
            raise ValueError(
                f"API key required for model: {prep_res['model']}. "
                f"Set up with 'llm keys set <provider>' or environment variable. "
                f"Original error: {exc}"
            )
        else:
            # Re-raise with context
            raise ValueError(
                f"LLM call failed after {self.max_retries} attempts. "
                f"Model: {prep_res['model']}, Error: {exc}"
            )

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM response.

        Handles markdown code blocks and other formatting.
        """
        # Remove markdown code blocks if present
        if "```json" in text:
            # Extract content between ```json and ```
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end != -1:
                text = text[start:end].strip()
        elif "```" in text:
            # Generic code block
            start = text.find("```") + 3
            end = text.find("```", start)
            if end != -1:
                text = text[start:end].strip()

        # Parse JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            # Include the problematic text in error for debugging
            raise json.JSONDecodeError(
                f"Invalid JSON from LLM: {e.msg}",
                text,
                e.pos
            )
```

### Parameter Support

The node supports parameters from both shared store and CLI:

```bash
# CLI parameters override shared store
pflow llm --prompt="Hello" --model=claude-3-opus --temperature=0.9

# Or use shared store from previous nodes
pflow read-file data.txt >> llm --prompt="Summarize: $content"
```

### Error Handling

1. **Missing Prompt**: Clear error with guidance
2. **Unknown Model**: Suggests running `llm models`
3. **Missing API Key**: Points to `llm keys` command
4. **JSON Parse Errors**: Shows what failed to parse
5. **General Failures**: Includes retry count and model info

## Testing Strategy

### Unit Tests

```python
import pytest
from unittest.mock import Mock, patch
from pflow.nodes.llm import LLMNode

class TestLLMNode:

    @patch('llm.get_model')
    def test_successful_execution(self, mock_get_model):
        # Mock the LLM response
        mock_response = Mock()
        mock_response.text.return_value = "Test response"
        mock_response.usage = {"input": 10, "output": 5}

        mock_model = Mock()
        mock_model.prompt.return_value = mock_response
        mock_get_model.return_value = mock_model

        # Test the node
        node = LLMNode()
        shared = {"prompt": "Test prompt"}

        action = node.run(shared)

        # Verify results
        assert shared["response"] == "Test response"
        assert shared["usage"]["input"] == 10
        assert action == "default"

        # Verify model was called correctly
        mock_model.prompt.assert_called_once_with(
            "Test prompt",
            temperature=0.7
        )

    def test_missing_prompt(self):
        node = LLMNode()
        shared = {}

        with pytest.raises(ValueError, match="requires 'prompt'"):
            node.run(shared)

    @patch('llm.get_model')
    def test_json_format(self, mock_get_model):
        # Mock JSON response
        mock_response = Mock()
        mock_response.text.return_value = '```json\n{"key": "value"}\n```'

        mock_model = Mock()
        mock_model.prompt.return_value = mock_response
        mock_get_model.return_value = mock_model

        # Test JSON parsing
        node = LLMNode()
        shared = {
            "prompt": "Return JSON",
            "format": "json"
        }

        node.run(shared)

        assert shared["response"] == {"key": "value"}

    @patch('llm.get_model')
    def test_error_handling(self, mock_get_model):
        # Test unknown model error
        from llm import UnknownModelError
        mock_get_model.side_effect = UnknownModelError("gpt-5")

        node = LLMNode()
        shared = {"prompt": "Test", "model": "gpt-5"}

        with pytest.raises(ValueError, match="Unknown model.*llm models"):
            node.run(shared)
```

### Integration Tests

```python
# tests/integration/test_llm_node_integration.py
import vcr
from pflow.nodes.llm import LLMNode

class TestLLMNodeIntegration:

    @vcr.use_cassette('fixtures/llm/simple_prompt.yaml')
    def test_real_api_call(self):
        """Test with real API (recorded with VCR)."""
        node = LLMNode()
        shared = {
            "prompt": "Say hello in 3 words",
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.1
        }

        node.run(shared)

        assert "response" in shared
        assert len(shared["response"].split()) <= 5  # Allow some flexibility
```

## Future Enhancements (Post-MVP)

### Phase 2: Attachments
```python
# Check for attachments in shared store
if "attachments" in shared:
    # Validate attachment types
    for att in shared["attachments"]:
        if att.mime_type not in model.attachment_types:
            raise ValueError(f"Model doesn't support {att.mime_type}")
```

### Phase 3: Structured Output
```python
# Support Pydantic schemas
if "schema" in shared:
    response = model.prompt(
        prep_res["prompt"],
        schema=shared["schema"]
    )
```

### Phase 4: Advanced Features
- Tool/function calling
- Conversation management
- Streaming responses
- Template integration

## Integration with Other Components

### Registry
- Automatically discovered via `name = "llm"` attribute
- Available to planner for workflow generation

### Planner Usage
When the planner generates workflows, it can include this node:
```python
# Planner generates IR like:
{
    "nodes": [
        {"id": "n1", "type": "llm", "params": {"prompt": "..."}}
    ]
}
```

### CLI Integration
```bash
# Direct usage
pflow llm --prompt="Hello world"

# In pipelines
pflow read-file readme.md >> llm --prompt="Summarize this"

# With all parameters
pflow llm \
  --prompt="Explain quantum computing" \
  --system="You are a physics teacher" \
  --model=claude-3-opus \
  --temperature=0.3 \
  --format=json
```

## Common Patterns

### Summarization
```bash
pflow read-file report.pdf >> \
  llm --prompt="Summarize key findings in 5 bullet points"
```

### Code Analysis
```bash
pflow read-file main.py >> \
  llm --prompt="Review this code for potential bugs" --temperature=0.1
```

### Content Generation
```bash
pflow llm --prompt="Write a blog post about $topic" \
  --model=claude-3-opus \
  --temperature=0.8
```

### Data Extraction
```bash
pflow read-file invoice.txt >> \
  llm --prompt="Extract: company, date, total amount" \
  --format=json
```

## Conclusion

Task 12 provides a flexible, well-designed LLM node that:
1. Prevents node proliferation through smart design
2. Leverages `llm` library without unnecessary abstraction
3. Provides clear error messages and guidance
4. Supports both simple and advanced use cases
5. Integrates naturally with pflow's architecture

This implementation balances simplicity for basic use with extensibility for future enhancements.
