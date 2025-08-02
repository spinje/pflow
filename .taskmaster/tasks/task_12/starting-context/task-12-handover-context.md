# Task 12 Handover Context: Implement General LLM Node

## 🚨 CRITICAL: READ BEFORE IMPLEMENTING

**DO NOT START IMPLEMENTING IMMEDIATELY**. Read this entire document and the task specification (`.taskmaster/tasks/task_12/task-12-spec.md`) first. Once you understand everything, say "I'm ready to implement Task 12" and begin.

## Core Mission

Create a general-purpose LLM node that wraps Simon Willison's `llm` library. This is the ONLY LLM node in pflow - a smart exception to the simple nodes philosophy that prevents proliferation of prompt-specific nodes.

## 🎯 Key Outcomes & Deliverables

### What You're Building
1. **File**: `src/pflow/nodes/llm/llm.py` - The LLMNode class
2. **File**: `src/pflow/nodes/llm/__init__.py` - Module exports
3. **Tests**: `tests/test_nodes/test_llm.py` - Comprehensive test coverage
4. **Update**: `pyproject.toml` - Add `llm>=0.19.0` dependency

### What Success Looks Like
- Users can run: `pflow llm --prompt="Hello world"`
- Planner can include this node when generating workflows
- Registry discovers the node automatically via `name = "llm"` attribute
- Token usage is tracked in shared["llm_usage"] for cost analysis (empty dict {} if unavailable)
- All 22 test criteria from the spec pass (including usage tracking)

### Real-World Usage Context
When the planner generates workflows, your LLM node will be used like this:
```bash
# User types:
pflow "summarize the file data.txt"

# Planner generates workflow with your node:
read-file --path=data.txt >> llm --prompt="Summarize this: $content"
```

This shows why the shared store pattern matters - `$content` comes from the previous node's output (read-file writes to shared["content"]), and the runtime substitutes it before your node executes. Your node just receives the actual resolved text.

### Why Token Usage Tracking Matters
pflow's key advantage is "Plan Once, Run Forever" - we track token usage to demonstrate:
- Initial planning cost (higher tokens for workflow generation)
- Execution cost (minimal tokens for rerunning saved workflows)
- Cache benefits (Anthropic's prompt caching reduces costs by ~90% for cached tokens)
- ROI calculation: After ~3-5 runs, pflow becomes cheaper than re-analyzing with AI agents each time

The `llm_usage` data enables comparing pflow's efficiency against tools like Claude-Code that re-analyze everything on each run. Cache tracking is especially important - when workflows reuse the same prompts/contexts, cached tokens cost 10x less than regular tokens.

## 🔧 Critical Implementation Details

### Library Integration Pattern
```python
import llm  # From pip-installed package, NOT llm-main/

# Basic usage pattern:
model = llm.get_model("claude-sonnet-4-20250514")  # Accepts model ID or alias
response = model.prompt("Your prompt", temperature=0.7)
text = response.text()  # Force evaluation - responses are lazy!

# CRITICAL: The llm library handles its own internal retries for API failures.
# Our PocketFlow retry mechanism (max_retries=3) is for complete node failures only.
# Do NOT implement additional retry logic for API calls.
```

### Node Structure (MUST FOLLOW)
```python
from pocketflow import Node  # NOT BaseNode - that was old documentation
import llm
from typing import Dict, Any

class LLMNode(Node):
    """
    General-purpose LLM node for text processing.

    Interface:
    - Reads: shared["prompt"]: str  # Text prompt to send to model
    - Reads: shared["system"]: str  # System prompt (optional)
    - Writes: shared["response"]: str  # Model's text response
    - Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
        # Structure when available:
        # {
        #   "model": "claude-sonnet-4-20250514",
        #   "input_tokens": 150,
        #   "output_tokens": 75,
        #   "total_tokens": 225,
        #   "cache_creation_input_tokens": 0,
        #   "cache_read_input_tokens": 0
        # }
    - Params: model: str  # Model to use (default: claude-sonnet-4-20250514)
    - Params: temperature: float  # Sampling temperature (default: 0.7)
    - Params: max_tokens: int  # Max response tokens (optional)
    - Actions: default (always)
    """

    name = "llm"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        # Extract from shared store with parameter fallback
        prompt = shared.get("prompt") or self.params.get("prompt")

        if not prompt:
            raise ValueError(
                "LLM node requires 'prompt' in shared store or parameters. "
                "Please ensure previous nodes set shared['prompt'] "
                "or provide --prompt parameter."
            )

        # System also uses fallback pattern
        system = shared.get("system") or self.params.get("system")

        # Temperature with clamping
        temperature = self.params.get("temperature", 0.7)
        temperature = max(0.0, min(2.0, temperature))

        return {
            "prompt": prompt,
            "model": self.params.get("model", "claude-sonnet-4-20250514"),
            "temperature": temperature,
            "system": system,
            "max_tokens": self.params.get("max_tokens")
        }

    def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        # Use llm library directly - NO try/except! Let exceptions bubble up
        model = llm.get_model(prep_res["model"])

        kwargs = {"temperature": prep_res["temperature"]}

        # Only add optional parameters if not None
        if prep_res["system"] is not None:
            kwargs["system"] = prep_res["system"]
        if prep_res["max_tokens"] is not None:
            kwargs["max_tokens"] = prep_res["max_tokens"]

        # Let exceptions bubble up for retry mechanism
        response = model.prompt(prep_res["prompt"], **kwargs)

        # CRITICAL: Force evaluation with text()
        text = response.text()

        # Capture usage data (may return None)
        usage_obj = response.usage()

        return {
            "response": text,
            "usage": usage_obj,  # Pass raw object or None
            "model": prep_res["model"]
        }

    def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
             exec_res: Dict[str, Any]) -> str:
        shared["response"] = exec_res["response"]

        # Store usage metrics matching spec structure exactly
        usage_obj = exec_res.get("usage")
        if usage_obj:
            # Extract cache metrics from details if available
            details = getattr(usage_obj, 'details', {}) or {}
            cache_creation = details.get('cache_creation_input_tokens', 0)
            cache_read = details.get('cache_read_input_tokens', 0)

            shared["llm_usage"] = {
                "model": exec_res.get("model", "unknown"),
                "input_tokens": usage_obj.input,
                "output_tokens": usage_obj.output,
                "total_tokens": usage_obj.input + usage_obj.output,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read
            }
        else:
            # Empty dict per spec when usage unavailable
            shared["llm_usage"] = {}

        return "default"  # Always return "default"

    def exec_fallback(self, prep_res: Dict[str, Any], exc: Exception) -> None:
        # Enhanced error messages
        error_msg = str(exc)

        if "UnknownModelError" in error_msg:
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
            raise ValueError(
                f"LLM call failed after {self.max_retries} attempts. "
                f"Model: {prep_res['model']}, Error: {exc}"
            )
```

## ⚠️ Critical Patterns & Pitfalls

### MUST DO:
1. **Use `name = "llm"`** - Required class attribute for registry discovery
2. **Parameters via `set_params()`** - NOT constructor arguments (for testing)
3. **Force evaluation with `response.text()`** - Responses are lazy
4. **Check for None before adding to kwargs** - Don't pass None values
5. **Use parameter fallback pattern** - Check shared store first, then params (for both prompt and system)
6. **Temperature clamping** - Clamp to [0.0, 2.0] range using max(0.0, min(2.0, temp))
7. **Follow PocketFlow retry pattern** - NO try/except in exec(), let exceptions bubble up
8. **Use enhanced Interface docstring** - With type annotations and proper formatting

### MUST NOT DO:
1. **Don't access `shared` in exec()** - Only in prep() and post()
2. **Don't hardcode API keys** - Use environment variables
3. **Don't create custom retry logic** - Base class handles it
4. **Don't wrap llm exceptions** - Transform them to helpful ValueError messages
5. **Don't implement advanced features** - No attachments, tools, structured output for MVP

## 🧪 Testing Strategy

### Unit Tests (Mock Everything)
```python
import pytest
from unittest.mock import Mock, patch

@patch('llm.get_model')
def test_successful_execution(mock_get_model):
    # Mock the entire chain
    mock_response = Mock()
    mock_response.text.return_value = "Test response"

    mock_model = Mock()
    mock_model.prompt.return_value = mock_response
    mock_get_model.return_value = mock_model

    # Test the node
    node = LLMNode()
    shared = {"prompt": "Test prompt"}
    action = node.run(shared)

    assert shared["response"] == "Test response"
    assert action == "default"
```

### Integration Tests (Use VCR)
```python
import vcr

@vcr.use_cassette('fixtures/llm/simple_prompt.yaml')
def test_real_api_call():
    """Test with real API (recorded)."""
    node = LLMNode()
    node.set_params({"temperature": 0.1})
    shared = {"prompt": "Say hello in 3 words"}
    node.run(shared)

    assert "response" in shared
```

### All 22 Test Criteria from Spec
The spec lists 22 specific test cases - implement ALL of them. They cover:
- Prompt extraction from shared vs params
- Model parameter usage
- Temperature handling and clamping
- Optional parameter handling (system, max_tokens)
- Error cases (UnknownModelError, NeedsKeyException)
- Edge cases (empty prompt, empty response)

## 📦 Dependencies & Environment

### Add to pyproject.toml:
```toml
[project]
dependencies = [
    "llm>=0.19.0",  # Simon Willison's LLM library
    "pocketflow>=0.1.0",
    # ... existing dependencies
]
```

### API Keys Setup:
```bash
# Via environment variables
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."

# Or via llm CLI
llm keys set anthropic
llm keys set openai
```

## 🔗 Critical File References

### Must Read:
- **Spec**: `.taskmaster/tasks/task_12/task-12-spec.md` - The formal specification
- **LLM Docs**: `docs/core-node-packages/llm-nodes.md` - Design philosophy and examples
- **Node Reference**: `docs/reference/node-reference.md` - Node implementation patterns
- **llm Source**: `llm-main/` directory - The llm library source (in this repo)

### Related Code:
- **Example Node**: `src/pflow/nodes/file/read_file.py` - Similar structure
- **Base Class**: `pocketflow/__init__.py` - Node base class definition
- **Registry**: `src/pflow/registry/` - How nodes are discovered

## 🚀 Implementation Order

1. **Create directory structure**:
   ```bash
   mkdir -p src/pflow/nodes/llm
   touch src/pflow/nodes/llm/__init__.py
   touch src/pflow/nodes/llm/llm.py
   ```

2. **Implement LLMNode class** following the pattern above

3. **Update `src/pflow/nodes/llm/__init__.py`**:
   ```python
   from pflow.nodes.llm.llm import LLMNode

   __all__ = ["LLMNode"]
   ```

4. **Create comprehensive tests** covering all 22 criteria

5. **Update pyproject.toml** with llm dependency

6. **Manual testing**:
   ```bash
   # After implementation
   pflow llm --prompt="Hello world"
   echo "Test content" | pflow llm --prompt="Summarize this"
   ```

## 🎓 Key Insights from Research

### Why This Design?
1. **One LLM node vs many** - Prevents nodes like analyze-code, write-content, explain-concept
2. **Direct library usage** - Even llm doesn't wrap its own API, neither should we
3. **Natural interface** - `prompt` → `response` is intuitive for users
4. **Progressive enhancement** - Start minimal, add features based on usage

### Task 15 Was Redundant
- Task 15 was going to create LLM utilities for the planner
- But the planner should use `llm` library directly
- Task 12 creates the user-facing node
- Clear distinction: nodes are for workflows, not internal utilities

### Default Model Choice
- `claude-sonnet-4-20250514` is the default per project decision
- Not latest/newest - a specific stable model
- Users can override via --model parameter

## ⚡ Risks & Edge Cases

### Temperature Clamping
The spec requires clamping temperature to [0.0, 2.0]:
```python
temperature = max(0.0, min(2.0, prep_res["temperature"]))
```

### Empty Response Handling
If LLM returns empty string, store it - don't treat as error.

### Model Deprecation
Risk: Default model gets deprecated
Mitigation: Make default configurable (future enhancement)

## 🎯 Success Criteria

You've succeeded when:
1. ✅ `pflow llm --prompt="Hello"` works
2. ✅ Registry auto-discovers the node
3. ✅ All 22 test cases pass
4. ✅ Error messages are helpful (point to solutions)
5. ✅ Planner can include this node in generated workflows

## Final Critical Reminders

- The `llm-main/` directory is for reference only - use pip-installed `llm` package
- This is the ONLY LLM node - no need for specific prompt nodes
- Keep it simple for MVP - no advanced features yet
- The planner (Task 17) depends on this node existing
- Parameters come from `self.params`, not constructor

---

**Remember**: Read this entire document AND the spec before starting. When ready, acknowledge understanding and begin implementation.
