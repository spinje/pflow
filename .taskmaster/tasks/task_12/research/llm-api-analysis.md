# LLM API Analysis for Task 12 Implementation

## Overview

This document analyzes Simon Willison's `llm` library API to inform the implementation of Task 12 (general LLM node). Based on exploration of the source code and clarifications from the project lead, we will implement minimal integration for the MVP.

## Core LLM API

### Basic Usage Pattern
```python
import llm

# Get a model
model = llm.get_model("claude-sonnet-4-20250514")  # or model alias

# Execute a prompt
response = model.prompt(
    "Your prompt here",
    system="Optional system prompt",
    temperature=0.7
)

# Get the response text
text = response.text()
```

### Key Objects and Methods

1. **Model Selection**
   - `llm.get_model(name)` - Get model by ID or alias
   - `llm.get_models()` - List all available models
   - Default model: `claude-sonnet-4-20250514` if not configured

2. **Response Object**
   - Lazy evaluation - prompt only executes when `text()` is called
   - `response.text()` - Get the response text
   - `response.usage` - Token usage information (optional)

3. **Model Parameters**
   - `system` - System prompt (optional)
   - `temperature` - Sampling temperature
   - `max_tokens` - Maximum response tokens
   - Additional model-specific parameters via kwargs

## Advanced Features (Not in MVP)

### 1. Attachments (Multi-modal Input) - FUTURE
```python
response = model.prompt(
    "Describe these images",
    attachments=[
        llm.Attachment(path="image.jpg"),
        llm.Attachment(url="https://example.com/image.png"),
        llm.Attachment(content=b"binary_content")
    ]
)

# Check supported types
if "image/jpeg" in model.attachment_types:
    # Model supports JPEG images
```

### 2. Tools (Function Calling) - FUTURE
```python
def search(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

response = model.prompt(
    "What's the weather in SF?",
    tools=[search]
)

# Check if model wants to call tools
for tool_call in response.tool_calls():
    result = tool_call.execute()
```

### 3. Structured Output - FUTURE
```python
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int

response = model.prompt(
    "Extract person data from: John is 30 years old",
    schema=Person
)
# response.text() returns JSON matching the schema
```

### 4. Conversations - NOT SUPPORTED
```python
conversation = model.conversation()
response1 = conversation.prompt("Hello")
response2 = conversation.prompt("What did I just say?")
# Maintains context across prompts
```

### 5. Templates and Fragments - FUTURE
```python
# Templates for reusable prompts
template = llm.Template("Summarize this: {text}")
response = template.execute(text="Long content...")

# Fragments for modular prompts
fragment = llm.Fragment("You are a helpful assistant")
```

## Integration Depth Decision Matrix

### Minimal Integration (MVP - CONFIRMED)
Only expose core functionality:
- ✅ Basic prompt execution
- ✅ System prompts
- ✅ Model selection
- ✅ Temperature control
- ✅ Max tokens
- ❌ Attachments
- ❌ Tools
- ❌ Structured output
- ❌ Conversations (Never - stateful not supported in pflow)
- ❌ Templates

**Pros**: Simple, focused, easy to test
**Cons**: Limited functionality (acceptable for MVP)

### Medium Integration (Future v2.0)
Add commonly useful features:
- ✅ Everything from minimal
- ✅ Attachments for multi-modal
- ✅ Structured output (JSON mode)
- ❌ Tools
- ❌ Conversations (Never - stateful not supported in pflow)
- ❌ Templates

**Pros**: Covers most use cases
**Cons**: More complex interface

### Deep Integration (Future v3.0+)
Expose most LLM features:
- ✅ Everything from medium
- ✅ Tools (function calling)
- ❌ Conversations (Never - stateful not supported in pflow)
- ✅ Templates
- ✅ Custom model parameters

**Pros**: Maximum flexibility
**Cons**: Complex, harder to maintain

## Decision: Minimal Integration for MVP

### Phase 1 (MVP) - Minimal Integration
```python
class LLMNode(Node):
    name = "llm"

    def prep(self, shared):
        # Check shared store first, then fall back to parameters
        prompt = shared.get("prompt") or self.params.get("prompt")

        if not prompt:
            raise ValueError("LLM node requires 'prompt' in shared store or parameters")

        return {
            "prompt": prompt,
            "model": self.params.get("model", "claude-sonnet-4-20250514"),
            "temperature": self.params.get("temperature", 0.7),
            "system": self.params.get("system"),
            "max_tokens": self.params.get("max_tokens")
        }

    def exec(self, prep_res):
        model = llm.get_model(prep_res["model"])

        kwargs = {"temperature": prep_res["temperature"]}
        if prep_res["system"] is not None:
            kwargs["system"] = prep_res["system"]
        if prep_res["max_tokens"] is not None:
            kwargs["max_tokens"] = prep_res["max_tokens"]

        response = model.prompt(prep_res["prompt"], **kwargs)
        result = response.text()

        return {"response": result}
```

### Phase 2 (v2.0) - Add Multi-modal and Structured Output
- Add attachment support for images/documents
- Detect attachment types from shared store
- Validate against model capabilities
- Add JSON mode for structured output (parse JSON from response text)

### Phase 3 (v3.0+) - Advanced Features
- Structured output with Pydantic schemas
- Tool/function calling support
- Template integration
- Note: Conversations never supported (pflow is stateless)

## Key Implementation Insights

1. **Model Management**
   - Use `llm.get_model()` for all model access
   - Support both model IDs and aliases
   - Let llm handle model resolution
   - Default model: claude-sonnet-4-20250514

2. **Error Handling**
   - `UnknownModelError` for invalid models → wrap with helpful message
   - `NeedsKeyException` for missing API keys → guide to llm keys command
   - Let llm handle retries internally
   - Pocketflow Node handles retry orchestration

3. **Response Handling**
   - Responses are lazy - only execute on `text()` call
   - Force evaluation with response.text() in exec()
   - MVP returns text only (no usage tracking)
   - Future: JSON parsing for structured output

4. **Configuration**
   - API keys via environment variables or `llm keys` command
   - Model aliases via `llm aliases` command
   - Parameters via set_params() method
   - Fallback pattern: shared store → params

## Testing Considerations

1. **Mock the LLM library**
   ```python
   import pytest
   from unittest.mock import Mock, patch

   @patch('llm.get_model')
   def test_llm_node(mock_get_model):
       mock_response = Mock()
       mock_response.text.return_value = "Test response"
       mock_model = Mock()
       mock_model.prompt.return_value = mock_response
       mock_get_model.return_value = mock_model
   ```

2. **Test error cases**
   - Missing prompt
   - Invalid model
   - API failures
   - JSON parsing errors

3. **Integration tests**
   - Use VCR for recording real API calls
   - Test with different models
   - Verify parameter passing

## Conclusion

The `llm` library provides a clean, well-designed API that we should leverage directly. For the MVP, implement minimal integration focusing on core prompt execution. This provides immediate value while keeping the implementation simple and maintainable. Future phases can add advanced features based on user needs.
