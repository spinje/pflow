# LLM Node Advanced Features (v2.0+)

This document captures all the advanced features and patterns that were intentionally deferred from the MVP implementation of the LLM node. These features represent natural evolution paths based on user needs and usage patterns.

## Dynamic Output Pattern

### The Vision

The LLM node should support a "dynamic output" pattern where the output type changes based on input parameters:

```python
# Text output (default)
{"type": "llm", "params": {"prompt": "Summarize this"}}
# Output: shared["response"] = "Summary text..."

# Structured output
{"type": "llm", "params": {"prompt": "Extract data", "format": "json"}}
# Output: shared["response"] = {"name": "John", "age": 30}

# With schema validation
{"type": "llm", "params": {"prompt": "Extract", "schema": PersonSchema}}
# Output: shared["response"] = PersonModel(name="John", age=30)
```

### Why This Matters

1. **Planner Compatibility**: The planner could use the same LLM node for both text and structured data extraction
2. **Type Safety**: Workflows could guarantee structured outputs when needed
3. **Single Node**: Avoids proliferation of format-specific nodes (llm-json, llm-yaml, etc.)

### Implementation Challenges

1. **Output Type Variability**: shared["response"] could be string, dict, or Pydantic model
2. **Downstream Node Compatibility**: Nodes expecting text might break with dict input
3. **Validation Complexity**: Schema validation adds error modes
4. **Type Information**: How do downstream nodes know the output type?

### Proposed Solution (v2.0)

```python
def exec(self, prep_res):
    # ... LLM call ...

    if prep_res.get("format") == "json":
        result = self._parse_json_response(response.text())
        return {"response": result, "response_type": "dict"}
    elif prep_res.get("schema"):
        result = self._validate_schema(response.text(), prep_res["schema"])
        return {"response": result, "response_type": "pydantic"}
    else:
        return {"response": response.text(), "response_type": "str"}

def post(self, shared, prep_res, exec_res):
    shared["response"] = exec_res["response"]
    shared["response_type"] = exec_res["response_type"]
```

## Deferred Features Catalog

### 1. JSON Format Support

**What**: Built-in JSON parsing with markdown code block handling

```python
def _parse_json_response(self, text: str) -> Dict[str, Any]:
    """Extract and parse JSON from LLM response."""
    # Remove markdown code blocks if present
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end != -1:
            text = text[start:end].strip()

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from LLM: {e}")
```

**Why Deferred**: Adds complexity, error modes, and changes output type contract

### 2. Usage Tracking

**What**: Token usage information for cost tracking and monitoring

```python
# In exec()
usage_info = getattr(response, "usage", None)

# In post()
if usage_info:
    shared["llm_usage"] = {
        "input": usage_info.input_tokens,
        "output": usage_info.output_tokens,
        "total": usage_info.total_tokens
    }
    # Cumulative tracking
    shared["total_tokens"] = shared.get("total_tokens", 0) + usage_info.total_tokens
```

**Why Deferred**: Not essential for core functionality, adds shared store complexity

### 3. Multimodal Support

**What**: Image and file attachments for vision models

```python
# In prep()
attachments = []
if "images" in shared:
    for image_path in shared["images"]:
        attachments.append(llm.Attachment(path=image_path))
if "files" in shared:
    for file_info in shared["files"]:
        attachments.append(llm.Attachment(
            content=file_info["content"],
            mime_type=file_info["mime_type"]
        ))

# In exec()
if attachments and hasattr(model, 'attachment_types'):
    # Validate attachment types
    for att in attachments:
        if att.mime_type not in model.attachment_types:
            raise ValueError(f"Model doesn't support {att.mime_type}")

    response = model.prompt(prompt, attachments=attachments)
```

**Why Deferred**: Requires model capability detection, complex validation

### 4. Structured Output with Schemas

**What**: Pydantic model validation for guaranteed output structure

```python
# Using Simon Willison's llm library schema support
if "schema" in prep_res:
    response = model.prompt(
        prep_res["prompt"],
        schema=prep_res["schema"]  # Pydantic model class
    )
    # response.text() returns validated JSON matching schema
```

**Why Deferred**: Requires Pydantic dependency, complex error handling

### 5. Extended Shared Store Outputs

**What**: Multiple output keys for comprehensive LLM information

```python
# MVP: Simple
shared["response"] = "text"

# v2.0: Comprehensive
shared["response"] = "text"          # Primary output
shared["text"] = "text"              # Alias for chaining compatibility
shared["llm_model"] = "claude-3"     # Which model was actually used
shared["llm_usage"] = {...}          # Token usage details
shared["llm_metadata"] = {           # Additional metadata
    "temperature": 0.7,
    "finish_reason": "stop",
    "response_time_ms": 1234
}
```

**Why Deferred**: Violates simple interface principle, may confuse users

### 6. Conversation Management

**What**: Stateful conversations across multiple prompts

```python
# In prep()
if "conversation_id" in shared:
    conversation = self.conversations.get(shared["conversation_id"])
    if not conversation:
        conversation = model.conversation()
        self.conversations[shared["conversation_id"]] = conversation
else:
    conversation = None

# In exec()
if conversation:
    response = conversation.prompt(prep_res["prompt"])
else:
    response = model.prompt(prep_res["prompt"])
```

**Why Deferred**: Requires state management, violates stateless node principle

### 7. Tool/Function Calling

**What**: LLM-driven function execution

```python
# Define available tools
tools = [
    {
        "name": "search",
        "description": "Search the web",
        "parameters": {...}
    }
]

# In exec()
response = model.prompt(
    prep_res["prompt"],
    tools=tools
)

# Handle tool calls
for tool_call in response.tool_calls():
    result = execute_tool(tool_call)
    # Continue conversation with results
```

**Why Deferred**: Complex control flow, requires tool execution framework

### 8. Streaming Responses

**What**: Real-time token streaming for long responses

```python
# In exec()
if prep_res.get("stream"):
    response = model.prompt_stream(prep_res["prompt"])

    # Store generator in shared for downstream processing
    shared["response_stream"] = response

    # Or collect into full response
    full_text = ""
    for chunk in response:
        full_text += chunk
        # Could emit progress events here

    return {"response": full_text}
```

**Why Deferred**: Changes execution model, requires event system

### 9. Template Integration

**What**: Reusable prompt templates with variable substitution

```python
# In prep()
if "template" in shared:
    template = self.template_registry.get(shared["template"])
    if not template:
        raise ValueError(f"Unknown template: {shared['template']}")

    # Substitute variables
    prompt = template.format(**shared.get("template_vars", {}))
else:
    prompt = shared["prompt"]
```

**Why Deferred**: Requires template registry, adds configuration complexity

### 10. Advanced Error Recovery

**What**: Smart fallbacks and retry strategies

```python
def exec_with_fallback(self, prep_res):
    try:
        return self._try_primary_model(prep_res)
    except RateLimitError:
        # Try fallback model
        fallback_model = self.get_fallback_model(prep_res["model"])
        return self._try_model(fallback_model, prep_res)
    except ModelOverloadedError:
        # Try with reduced context
        reduced_prompt = self._reduce_context(prep_res["prompt"])
        return self._try_model(prep_res["model"], {...prep_res, "prompt": reduced_prompt})
```

**Why Deferred**: Complex logic, requires fallback configuration

## Implementation Strategy for v2.0

### Phase 1: Format Support (v2.1)
- JSON parsing with code block handling
- YAML support
- Basic format parameter

### Phase 2: Structured Output (v2.2)
- Pydantic schema validation
- Type information in shared store
- Dynamic output pattern

### Phase 3: Multimodal (v2.3)
- Image attachments
- Document processing
- Model capability detection

### Phase 4: Advanced Features (v2.4+)
- Conversation management
- Tool calling
- Streaming
- Templates

## Design Principles for Future Features

1. **Backward Compatibility**: All features must be optional
2. **Progressive Enhancement**: Basic usage remains simple
3. **Clear Documentation**: Each feature needs examples
4. **Error Messages**: Enhanced features need enhanced errors
5. **Type Safety**: Consider TypedDict or similar for outputs

## Migration Considerations

When implementing these features:

1. **Shared Store Contract**: Document how output types change
2. **Node Compatibility**: Ensure downstream nodes handle new types
3. **Performance**: Monitor impact of validation/parsing
4. **Testing**: Each feature needs comprehensive tests
5. **Documentation**: Update both code and user docs

## Usage Examples (Future)

```bash
# JSON extraction
pflow llm --prompt="Extract name and age" --format=json

# Schema validation
pflow llm --prompt="Extract person data" --schema=PersonSchema

# Multimodal
pflow llm --prompt="Describe this image" --image=photo.jpg

# Conversation
pflow llm --prompt="Hello" --conversation=chat1
pflow llm --prompt="What did I just say?" --conversation=chat1

# Templates
pflow llm --template=summarize --template-vars='{"style": "bullet points"}'
```

## Conclusion

These advanced features were deferred from MVP to maintain simplicity and focus. Each represents a natural evolution based on real user needs. The dynamic output pattern, in particular, enables powerful workflows while maintaining the single LLM node principle.

The key insight is that complexity should be opt-in: basic text processing remains simple, while power users can access advanced features through parameters.
