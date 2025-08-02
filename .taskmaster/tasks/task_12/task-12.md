# Task 12: Implement General LLM Node

## ID
12

## Title
Implement General LLM Node

## Description
Create a general-purpose LLM node that wraps Simon Willison's `llm` library for text processing in pflow workflows. This is the ONLY LLM node in pflow - a smart exception to the simple nodes philosophy that prevents proliferation of prompt-specific nodes like analyze-code, write-content, or explain-concept.

## Status
not started

## Dependencies
None

## Priority
high

## Details
The LLM node is critical infrastructure that enables the planner (Task 17) to generate meaningful workflows. Without it, the planner examples and testing would be severely limited to basic file operations that don't showcase pflow's value proposition.

### Core Implementation Requirements
- Create `LLMNode` class in `src/pflow/nodes/llm/llm.py`
- Must have `name = "llm"` class attribute for registry discovery
- Implement PocketFlow pattern: prep(), exec(), post(), exec_fallback()
- NO try/except in exec() - let exceptions bubble up for retry mechanism
- Support parameter fallback pattern (shared store first, then params)

### Interface Design
The node follows a simple prompt → response pattern:
- **Inputs**: `prompt` (required), `system` (optional)
- **Outputs**: `response` (text), `llm_usage` (metrics)
- **Parameters**: `model`, `temperature`, `max_tokens`
- **Default model**: `claude-sonnet-4-20250514`

### Usage Tracking
Critical for demonstrating pflow's "Plan Once, Run Forever" efficiency:
- Track input/output tokens for cost analysis
- Include cache metrics (cache_creation_input_tokens, cache_read_input_tokens)
- Store as structured dict in `shared["llm_usage"]`
- Empty dict {} when usage data unavailable

### Template Variable Support
The node receives already-resolved template variables from the runtime:
- User workflow: `{"prompt": "Summarize: $content"}`
- Runtime resolves: `$content` → actual file contents
- Node receives: `{"prompt": "Summarize: [actual text]"}`

### Library Integration
- Use pip-installed `llm` package (NOT the llm-main/ reference directory)
- Call `llm.get_model()` and `model.prompt()`
- Force evaluation with `response.text()` (responses are lazy)
- Extract usage with `response.usage()` (may return None)

### Error Handling
Transform specific exceptions to helpful messages in exec_fallback():
- UnknownModelError → "Run 'llm models' to see available models"
- NeedsKeyException → "Set up with 'llm keys set <provider>'"
- General failures → Include retry count and model info

### Temperature Clamping
Temperature must be clamped to [0.0, 2.0] range:
```python
temperature = max(0.0, min(2.0, temperature))
```

## Test Strategy
Comprehensive testing with 22 specific test criteria from the spec:

### Unit Tests (Mock Everything)
- Mock `llm.get_model()` and entire response chain
- Test prompt extraction from shared vs params
- Test parameter handling (model, temperature, system, max_tokens)
- Test temperature clamping at boundaries
- Test error transformation in exec_fallback()
- Test usage data extraction and storage

### Integration Tests (Use VCR)
- Record actual API calls for reproducible testing
- Test with real responses but avoid repeated API costs
- Verify token usage tracking with actual API data

### Key Test Scenarios
1. Prompt in shared → extracted correctly
2. Prompt in params (fallback) → extracted correctly
3. Missing prompt → ValueError with helpful message
4. Temperature < 0.0 → clamped to 0.0
5. Temperature > 2.0 → clamped to 2.0
6. System parameter provided → included in kwargs
7. System parameter None → not in kwargs
8. response.usage() returns data → stored with correct structure
9. response.usage() returns None → empty dict stored
10. Empty response → empty string stored (not error)

### Enhanced Interface Docstring
Must include type annotations and follow the established format for registry metadata extraction.
