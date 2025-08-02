# Feature: implement_llm_node

## Objective

Create general-purpose LLM node wrapping Simon Willison's library.

## Prerequisites

Before implementing, the agent MUST:
1. Read `/pocketflow/__init__.py` to understand Node base class and PocketFlow patterns
2. Read `/pocketflow/docs/core_abstraction/node.md` for Node lifecycle
3. Read `/src/pflow/nodes/file/read_file.py` as reference implementation
4. Read `/src/pflow/nodes/CLAUDE.md` for critical retry patterns and docstring format
5. Read `/docs/reference/enhanced-interface-format.md` for Interface documentation

## Requirements

- Must have `llm` library dependency installed (via pip, not llm-main/)
- Must have pocketflow Node base class available
- Must have `name = "llm"` class attribute for registry discovery
- Must support Claude Sonnet model as default
- Must integrate with shared store pattern
- Must be discoverable by registry scanner
- Must implement prep(), exec(), post(), exec_fallback() per PocketFlow pattern
- Must follow PocketFlow retry pattern (NO try/except in exec())
- Must use enhanced Interface docstring format with type annotations

## Scope

- Does not include multimodal attachments
- Does not include tool/function calling
- Does not include conversation management
- Does not include streaming responses
- Does not include structured output schemas

## Inputs

- `shared`: dict - Shared store dictionary containing:
  - `prompt`: str - Text prompt to send to model (required, fallback to params)
  - `system`: str - System prompt for behavior guidance (optional, fallback to params)
- `params`: the nodes parameters (set via set_params() method)
  - `prompt`: str - Text prompt if not in shared (fallback)
  - `system`: str - System prompt if not in shared (fallback)
  - `model`: str - Model identifier or alias (optional)
  - `temperature`: float - Sampling temperature 0.0-2.0 (optional)
  - `max_tokens`: int - Maximum response tokens (optional)

## Outputs

Side effects:
- Writes `response` (str) to shared store containing model output
- Writes `llm_usage` (dict) to shared store containing token usage metrics
- Returns action string: "default" always

Usage data structure:
```json
{
  "model": "claude-sonnet-4-20250514",
  "input_tokens": 150,
  "output_tokens": 75,
  "total_tokens": 225,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0
}
```
Note: Empty dict {} if usage data unavailable. Cache token fields default to 0 if not provided by the model.

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
    "inputs": ["prompt", "system"],
    "outputs": ["response", "llm_usage"]
  },
  "parameters": {
    "model": {"type": "str", "default": "claude-sonnet-4-20250514"},
    "temperature": {"type": "float", "default": 0.7, "range": [0.0, 2.0]},
    "system": {"type": "Optional[str]", "default": null},
    "max_tokens": {"type": "Optional[int]", "default": null}
  }
}
```

## Method Structure

The node must implement these methods per PocketFlow pattern:

```python
def prep(self, shared: dict) -> dict:
    """Extract and prepare inputs from shared store with parameter fallback."""
    # Return dict with prompt, model, temperature, system, max_tokens

def exec(self, prep_res: dict) -> dict:
    """Execute LLM call - NO try/except blocks! Let exceptions bubble up."""
    # Call llm.get_model() and model.prompt()
    # Return {"response": response.text()}

def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
    """Store results in shared store."""
    # Store shared["response"] = exec_res["response"]
    # Return "default"

def exec_fallback(self, prep_res: dict, exc: Exception) -> None:
    """Handle errors after all retries exhausted."""
    # Transform specific exceptions to helpful ValueError messages
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
4. Get temperature from self.params.get("temperature") with default 0.7, then clamp to [0.0, 2.0] using max(0.0, min(2.0, temperature))
5. Get system from shared["system"] first, then fall back to self.params.get("system") with default None
6. Get max_tokens from self.params.get("max_tokens") with default None
7. Call llm.get_model() with model parameter (let exceptions bubble up in exec())
8. Build kwargs dict with temperature always included (after clamping)
9. Add system to kwargs only if not None
10. Add max_tokens to kwargs only if not None
11. Call model.prompt() with prompt string and kwargs (let exceptions bubble up)
12. Call response.text() to force evaluation
13. Call response.usage() to get token usage (may return None)
14. Store response text in shared["response"] in post() method
15. Store usage data in shared["llm_usage"] in post() method (empty dict if None)
16. Return "default" action string from post() method
17. In exec_fallback(): If UnknownModelError then raise ValueError with model list suggestion
18. In exec_fallback(): If NeedsKeyException then raise ValueError with API key setup suggestion
19. In exec_fallback(): If any other exception then raise ValueError with retry count and model info

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

## Interface Documentation

The node MUST include this enhanced Interface docstring format:

```python
class LLMNode(Node):
    """
    General-purpose LLM node for text processing.

    Interface:
    - Reads: shared["prompt"]: str  # Text prompt to send to model
    - Reads: shared["system"]: str  # System prompt (optional)
    - Writes: shared["response"]: str  # Model's text response
    - Writes: shared["llm_usage"]: dict  # Token usage metrics
    - Params: model: str  # Model to use (default: claude-sonnet-4-20250514)
    - Params: temperature: float  # Sampling temperature (default: 0.7)
    - Params: max_tokens: int  # Max response tokens (optional)
    - Actions: default (always)
    """

    name = "llm"  # CRITICAL: Required for registry discovery
```

Note: prompt and system are NOT listed in Params since they're already in Reads (automatic fallback).

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

### Parameter setting for testing
```python
# For testing, parameters are set after instantiation:
node = LLMNode()
node.set_params({"temperature": 0.1, "model": "gpt-4"})
# NOT passed to constructor

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
21. response.usage() returns data → stored in shared["llm_usage"] with correct fields
22. response.usage() returns None → empty dict {} stored in shared["llm_usage"]

## Notes (Why)

- Single LLM node prevents proliferation of prompt-specific nodes
- Direct llm library usage avoids unnecessary abstraction layers
- Shared store pattern enables natural workflow composition
- Parameter fallback enables both CLI and programmatic usage
- Clear error messages reduce user frustration and support requests

## Compliance Matrix

| Rule # | Covered By Test Criteria # | Notes |
|--------|---------------------------|-------|
| 1      | 3                         | ValueError for missing prompt |
| 2      | 1, 2                      | Fallback pattern for prompt |
| 3      | 4                         | Model parameter |
| 4      | 5, 6, 18, 19              | Temperature with clamping |
| 5      | 7, 8                      | System fallback pattern (NEW) |
| 6      | 9, 10                     | Max tokens |
| 7      | 4                         | llm.get_model() call |
| 8      | 5, 6                      | Temperature in kwargs |
| 9      | 7, 8                      | System conditional |
| 10     | 9, 10                     | Max tokens conditional |
| 11     | 11                        | model.prompt() call |
| 12     | 11                        | response.text() |
| 13     | 12                        | Store in post() |
| 14     | 13                        | Return from post() |
| 15     | 14                        | exec_fallback() |
| 16     | 15                        | exec_fallback() |
| 17     | 16                        | exec_fallback() |

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
