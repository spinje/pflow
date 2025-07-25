# LLM Patterns Guidance for Task 12: Implement general LLM node

## Summary
**Critical Decision**: Wrap Simon Willison's `llm` library instead of building from scratch. This saves weeks of development and provides battle-tested LLM integration.

Key patterns to leverage:
- **LLM Library Integration**: Use `llm` as a dependency (from llm-main codebase)
- **Pocketflow Node Pattern**: Proper prep/exec/post separation
- **Natural Interface**: Intuitive shared store keys
- **Error Handling**: Graceful fallbacks and retries
- **Multi-Provider Support**: Automatic via `llm` plugins

## llm Library Features vs pflow-specific Features

### From llm library (llm-main):
- `llm.get_model()` - Model resolution and loading
- `llm.Attachment` - Image/file attachment handling
- `model.prompt()` - Core prompt execution
- `response.text()`, `response.usage()`, `response.json()` - Response data access
- `llm.UnknownModelError` - Error handling
- Multi-provider support via plugins

### pflow-specific additions:
- Pocketflow Node pattern (prep/exec/post)
- Shared store integration
- Multiple input key fallbacks (prompt/text/stdin)
- Cumulative token tracking across flows
- Fallback model strategy on rate limits
- Natural key naming for chaining

## Specific Implementation

### Pattern: Complete LLM Node Using `llm` Library

```python
# src/pflow/nodes/llm.py
from pocketflow import Node
import llm  # From llm-main library
from typing import Optional, Dict, Any

class LLMNode(Node):
    """
    General-purpose LLM node using Simon Willison's llm library.

    Reads from shared store:
    - prompt: The prompt text to send to the model (required)

    Writes to shared store:
    - response: The model-generated output text

    Parameters (not from shared store):
    - model: Model name to use (default: "claude-sonnet-4-20250514")
    - temperature: Sampling temperature (default: 0.7)
    - system: Optional system prompt
    - max_tokens: Optional output limit
    """

    def __init__(self,
                 model: str = "claude-sonnet-4-20250514",
                 system: Optional[str] = None,
                 temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None,
                 max_retries: int = 3,
                 **kwargs):
        # Initialize with pocketflow's retry mechanism
        super().__init__(max_retries=max_retries)

        self.model_name = model
        self.default_system = system
        self.options = {}

        if temperature is not None:
            self.options['temperature'] = temperature
        if max_tokens is not None:
            self.options['max_tokens'] = max_tokens

        # Store any additional model-specific options
        self.options.update(kwargs)

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Extract prompt from shared store."""
        if "prompt" not in shared:
            raise ValueError(
                "LLM node requires 'prompt' in shared store. "
                "Please ensure previous nodes set shared['prompt'] "
                "or provide --prompt parameter."
            )

        return {
            "prompt": shared["prompt"]
        }

    def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """Execute LLM call using llm library."""
        # Get model from llm library
        model = llm.get_model(self.model_name)

        # Build prompt arguments
        prompt_args = {
            "prompt": prep_res["prompt"],
            **self.options
        }

        # Add system prompt if configured
        if self.default_system:
            prompt_args["system"] = self.default_system

        # Execute prompt
        response = model.prompt(**prompt_args)

        # Return response text
        return {
            "response": response.text()
        }

    def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
             exec_res: Dict[str, Any]) -> str:
        """Store response in shared store."""
        shared["response"] = exec_res["response"]
        return "default"
```

### Pattern: Configuration and Setup

Add to `pyproject.toml`:
```toml
[project]
dependencies = [
    "llm>=0.19.0",  # Simon Willison's LLM library
    "pocketflow>=0.1.0",
    # ... other dependencies
]

[project.optional-dependencies]
providers = [
    "llm-claude-3",     # Anthropic models
    "llm-gemini",       # Google models
    "llm-mistral",      # Mistral models
]
```

Environment setup:
```bash
# Set API keys
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Or use llm's key management
llm keys set openai
llm keys set claude
```

## Testing Approach

```python
# tests/test_llm_node.py
import pytest
from pflow.nodes.llm_node import LLMNode
import vcr

class TestLLMNode:
    def test_prep_phase(self):
        """Test extraction from shared store."""
        node = LLMNode(model="claude-sonnet-4-20250514")

        # Test prompt extraction
        shared = {"prompt": "Test prompt"}
        prep_res = node.prep(shared)
        assert prep_res["prompt"] == "Test prompt"

        # Test missing prompt
        shared = {}
        with pytest.raises(ValueError, match="requires 'prompt'"):
            node.prep(shared)

    @vcr.use_cassette('fixtures/llm_node_exec.yaml')
    def test_exec_phase(self):
        """Test LLM execution with recorded response."""
        node = LLMNode(model="claude-sonnet-4-20250514", temperature=0)

        prep_res = {
            "prompt": "Say 'Hello, World!' and nothing else.",
            "system": None,
            "attachments": [],
            "schema": None
        }

        exec_res = node.exec(prep_res)

        assert "response" in exec_res
        assert "Hello, World!" in exec_res["response"]

    def test_post_phase(self):
        """Test storing results in shared store."""
        node = LLMNode()
        shared = {}

        exec_res = {
            "response": "LLM response"
        }

        action = node.post(shared, {}, exec_res)

        # Check response is set correctly
        assert shared["response"] == "LLM response"
        assert action == "default"

    # Future enhancement tests would go here
    # def test_multimodal_support(self):
    #     """Test image attachment handling - FUTURE FEATURE."""
    #     pass
    #
    # def test_structured_output(self):
    #     """Test JSON schema support - FUTURE FEATURE."""
    #     pass
```

## Future Enhancements (Post-MVP)

These features are planned for future versions but NOT included in the initial implementation:

1. **Multimodal Support**: Image attachments and other media types
2. **Structured Output**: JSON schema validation and Pydantic model support
3. **Advanced Features**: Tool calling, conversations, templates
4. **Extended Outputs**: Usage tracking, model information, token counts

The MVP focuses on simple text-in, text-out functionality.

## Common Pitfalls to Avoid

1. **Don't access shared in exec()**: Only in prep() and post()
2. **Don't hardcode API keys**: Use environment variables
3. **Don't skip error messages**: Provide helpful model suggestions
4. **Remember retries**: Node base class handles retry logic
5. **Parameter handling**: Parameters are set via set_params() method, not constructor

## Benefits of Using `llm` Library

1. **Instant Multi-Provider Support**: OpenAI, Anthropic, Google, local models
2. **Automatic Updates**: New models added via plugins
3. **Battle-Tested**: Handles rate limits, errors, retries
4. **Cost Tracking**: Built-in token usage tracking
5. **Future Features**: Streaming, tools, embeddings (when needed)

## Migration Path

If currently building custom LLM integration:
1. Add `llm` to dependencies
2. Replace custom API calls with `llm` library
3. Keep same shared store interface
4. Remove custom retry logic (library handles it)

## Real-World Usage

```python
# In a flow
read_file = ReadFileNode()
llm = LLMNode()
llm.set_params({"model": "claude-sonnet-4-20250514", "temperature": 0.7})
write_file = WriteFileNode()

flow = Flow(start=read_file)
read_file >> llm >> write_file

# Shared store flow:
# read_file: puts content in shared["content"]
# llm: reads shared["prompt"] (needs to be set from content)
# llm: writes shared["response"]
# write_file: reads shared["content"] and writes to file
```

## References
- `docs/implementation-details/simonw-llm-patterns/IMPLEMENTATION-GUIDE.md`: Complete LLM node implementation (pflow-specific)
- `docs/implementation-details/simonw-llm-patterns/FINAL-ANALYSIS.md`: Architecture alignment with pocketflow
- LLM library source: llm-main/ directory in this codebase
- LLM docs: https://llm.datasette.io/
- Available models: Run `llm models` after installing

## Key llm-main Source Files Referenced
- `llm-main/llm/__init__.py`: get_model(), UnknownModelError
- `llm-main/llm/models.py`: Attachment, Usage, Response methods, Model.prompt()
- Model resolution and plugin system from llm library
