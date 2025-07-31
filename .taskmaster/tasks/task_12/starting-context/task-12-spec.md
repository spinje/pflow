# Feature: implement_llm_node

## Objective

Create general-purpose LLM node wrapping Simon Willison's library.

## Requirements

- Must have `llm` library dependency installed
- Must have pocketflow Node base class available
- Must support Claude Sonnet model as default
- Must integrate with shared store pattern
- Must be discoverable by registry scanner

## Scope

- Does not include multimodal attachments
- Does not include tool/function calling
- Does not include conversation management
- Does not include streaming responses
- Does not include structured output schemas

## Inputs

- `shared`: dict - Shared store dictionary containing:
  - `prompt`: str - Text prompt to send to model (required)
  - `system`: str - System prompt for behavior guidance (optional)
- `params`: the nodes parameters (not in shared)
  - `model`: str - Model identifier or alias (optional)
  - `temperature`: float - Sampling temperature 0.0-2.0 (optional)
  - `max_tokens`: int - Maximum response tokens (optional)

## Outputs

Side effects:
- Writes `response` (str) to shared store containing model output
- Returns action string: "default" always

## Structured Formats

```json
{
  "node_class": {
    "name": "llm",
    "location": "src/pflow/nodes/llm/llm.py",
    "class_name": "LLMNode",
    "parent": "pocketflow.Node"
  },
  "shared_store_keys": {
    "inputs": ["prompt"],
    "outputs": ["response"]
  },
  "parameters": {
    "model": {"type": "str", "default": "claude-sonnet-4-20250514"},
    "temperature": {"type": "float", "default": 0.7, "range": [0.0, 2.0]},
    "system": {"type": "Optional[str]", "default": null},
    "max_tokens": {"type": "Optional[int]", "default": null}
  }
}
```

## State/Flow Changes

- None

## Constraints

- `prompt` must be non-empty string
- `temperature` must be between 0.0 and 2.0
- `model` must be valid llm library model identifier
- Node must handle UnknownModelError from llm library
- Node must handle NeedsKeyException from llm library

## Rules

1. If `prompt` not in shared and not in params then raise ValueError with helpful message
2. Get prompt from shared["prompt"] first, then fall back to self.params.get("prompt")
3. Get model from self.params.get("model") with default "claude-sonnet-4-20250514"
4. Get temperature from self.params.get("temperature") with default 0.7
5. Get system from self.params.get("system") with default None
6. Get max_tokens from self.params.get("max_tokens") with default None
7. Call llm.get_model() with model parameter
8. Build kwargs dict with temperature always included
9. Add system to kwargs only if not None
10. Add max_tokens to kwargs only if not None
11. Call model.prompt() with prompt string and kwargs
12. Call response.text() to force evaluation
13. Store response text in shared["response"]
14. Return "default" action string
15. If UnknownModelError then raise ValueError with model list suggestion
16. If NeedsKeyException then raise ValueError with API key setup suggestion
17. If any other exception then raise ValueError with retry count and model info

## Edge Cases

- Empty prompt string → raise ValueError
- Model not found → catch UnknownModelError and provide helpful message
- Missing API key → catch NeedsKeyException and guide to llm keys command
- Temperature < 0.0 → clamp to 0.0
- Temperature > 2.0 → clamp to 2.0
- Response is empty string → store empty string in shared["response"]

## Error Handling

- Missing prompt → raise ValueError("LLM node requires 'prompt' in shared store or parameters")
- Invalid model → raise ValueError with "Run 'llm models' to see available models"
- Missing API key → raise ValueError with "Set up with 'llm keys set <provider>'"
- General failure → raise ValueError with retry count and original error

## Non-Functional Criteria

- API calls complete within 60 seconds
- Node handles retries via pocketflow base class
- Clear error messages guide users to solutions

## Examples

### Basic usage
```python
shared = {"prompt": "Say hello"}
node = LLMNode()
node.run(shared)
# shared["response"] = "Hello! How can I help you today?"
```

### With parameters
```python
node = LLMNode()
node.set_params({
    "model": "claude-3-opus-20240229",
    "temperature": 0.2,
    "system": "You are a helpful assistant"
})
shared = {"prompt": "Explain quantum computing"}
node.run(shared)
```

## Test Criteria

1. prompt in shared → prompt extracted correctly
2. prompt not in shared but in params → prompt extracted from params
3. prompt missing entirely → ValueError raised
4. model parameter used → llm.get_model called with correct model
5. temperature set to 0.0 → temperature=0.0 in kwargs
6. temperature set to 2.0 → temperature=2.0 in kwargs
7. system parameter provided → system in kwargs
8. system parameter None → system not in kwargs
9. max_tokens provided → max_tokens in kwargs
10. max_tokens None → max_tokens not in kwargs
11. model.prompt() called → response.text() returns "Test response"
12. response stored → shared["response"] equals response text
13. action returned → run() returns "default"
14. UnknownModelError raised → ValueError with "llm models" message
15. NeedsKeyException raised → ValueError with "llm keys" message
16. Generic exception → ValueError with retry count
17. Empty prompt → ValueError raised
18. Temperature < 0.0 → clamped to 0.0
19. Temperature > 2.0 → clamped to 2.0
20. Empty response → empty string stored in shared["response"]

## Notes (Why)

- Single LLM node prevents proliferation of prompt-specific nodes
- Direct llm library usage avoids unnecessary abstraction layers
- Shared store pattern enables natural workflow composition
- Parameter fallback enables both CLI and programmatic usage
- Clear error messages reduce user frustration and support requests

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
|--------|---------------------------|
| 1      | 3                         |
| 2      | 1, 2                      |
| 3      | 4                         |
| 4      | 5, 6, 18, 19              |
| 5      | 7, 8                      |
| 6      | 9, 10                     |
| 7      | 4                         |
| 8      | 5, 6                      |
| 9      | 7, 8                      |
| 10     | 9, 10                     |
| 11     | 11                        |
| 12     | 11                        |
| 13     | 12                        |
| 14     | 13                        |
| 15     | 14                        |
| 16     | 15                        |
| 17     | 16                        |

## Versioning & Evolution

- v1.0.0 — Initial MVP implementation with text-only support
- v2.0.0 — (Future) Add attachment support for multimodal inputs
- v3.0.0 — (Future) Add structured output with JSON schemas
- v4.0.0 — (Future) Add tool calling and function support

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes llm library handles internal retries and rate limiting
- Assumes claude-sonnet-4-20250514 remains available as default model
- Unknown optimal default temperature for general use cases
- Unknown typical max_tokens requirements across use cases

### Conflicts & Resolutions

- Task 12 research showed BaseNode usage → Resolution: Use Node per clarification
- Research showed constructor parameters → Resolution: Use set_params() method per clarification
- Task 15 overlap identified → Resolution: Task 15 removed, planner uses llm directly

### Decision Log / Tradeoffs

- Chose parameter fallback pattern over strict shared-store-only for CLI usability
- Chose to always include temperature in kwargs for consistent behavior
- Chose to handle clamping for temperature rather than strict validation
- Chose "default" action always over conditional actions for simplicity

### Ripple Effects / Impact Map

- Registry will discover and expose this node
- Planner can generate workflows containing llm nodes
- CLI users can invoke directly: pflow llm --prompt="..."
- Future nodes can compose with llm for complex workflows

### Residual Risks & Confidence

- Risk: API key configuration complexity for new users; Mitigation: Clear error messages
- Risk: Model deprecation breaks defaults; Mitigation: Configurable default
- Risk: Token limits exceeded silently; Mitigation: Rely on llm library handling
- Confidence: High for MVP scope, Medium for error handling completeness

### Epistemic Audit (Checklist Answers)

1. Assumed llm library stability and retry behavior not explicitly verified
2. If assumptions wrong: May need custom retry logic or error handling
3. Prioritized robustness (clear errors) over elegance (terse implementation)
4. All rules have corresponding tests; all edge cases covered
5. Ripple effects include registry, planner, CLI, and future node composition
6. Remaining uncertainty on optimal defaults and token limit handling; Confidence: High for core functionality
