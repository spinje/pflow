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
    - prompt or text or stdin: The input text
    - system (optional): System prompt
    - images (optional): List of image paths for multimodal models
    - schema (optional): JSON schema for structured output

    Writes to shared store:
    - response: The LLM's response text
    - text: Same as response (for chaining)
    - llm_usage: Token usage statistics
    - llm_model: Model actually used
    - total_tokens: Cumulative token count
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
        """Extract prompt and context from shared store."""
        # Natural interface - check multiple possible keys
        prompt = (
            shared.get("prompt") or
            shared.get("text") or
            shared.get("stdin", "")
        )

        if not prompt:
            raise ValueError(
                "No prompt found in shared store. "
                "Checked keys: 'prompt', 'text', 'stdin'. "
                "Please provide input text in one of these keys."
            )

        # System prompt can come from shared or node config
        system = shared.get("system", self.default_system)

        # Handle attachments for multimodal models
        attachments = []
        if "images" in shared:
            images = shared["images"]
            # Handle both single image and list
            if isinstance(images, str):
                images = [images]

            for img_path in images:
                try:
                    # llm.Attachment from llm-main/llm/models.py:52
                    attachments.append(llm.Attachment(path=img_path))
                except Exception as e:
                    # Log warning but don't fail
                    if shared.get('verbose', False):
                        print(f"Warning: Could not load image {img_path}: {e}")

        # Extract JSON schema if provided
        schema = shared.get("schema")

        return {
            "prompt": prompt,
            "system": system,
            "attachments": attachments,
            "schema": schema
        }

    def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """Execute LLM call using llm library - isolated from shared store."""
        try:
            # Get model from llm library (llm-main/llm/__init__.py:325)
            model = llm.get_model(self.model_name)

            # Build prompt arguments
            prompt_args = {
                "prompt": prep_res["prompt"],
                **self.options
            }

            if prep_res["system"]:
                prompt_args["system"] = prep_res["system"]

            if prep_res["attachments"]:
                prompt_args["attachments"] = prep_res["attachments"]

            if prep_res["schema"]:
                prompt_args["schema"] = prep_res["schema"]

            # Execute prompt (llm-main/llm/models.py:1747)
            response = model.prompt(**prompt_args)

            # Extract all useful information
            # response.text() from llm-main/llm/models.py:996
            # response.usage() from llm-main/llm/models.py:1108 returns Usage dataclass
            usage = response.usage()
            result = {
                "text": response.text(),
                "usage": {
                    "input": usage.input,
                    "output": usage.output,
                    "details": usage.details
                } if usage else {},
                "model": str(model.model_id)
            }

            # Add structured output if schema was used
            if prep_res["schema"]:
                try:
                    # response.json() from llm-main/llm/models.py:1096
                    result["json"] = response.json()
                except:
                    result["json"] = None

            return result

        except llm.UnknownModelError as e:
            # UnknownModelError from llm-main/llm/__init__.py:290
            # Provide helpful error message
            available = [m.model_id for m in llm.get_models()]
            raise ValueError(
                f"Unknown model: {self.model_name}\n"
                f"Available models: {', '.join(available[:5])}...\n"
                f"Run 'llm models' to see all available models.\n"
                f"Install plugins for additional providers: pip install llm-claude-3"
            ) from e

    def exec_fallback(self, prep_res: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
        """Fallback strategy - try a simpler model on rate limits."""
        error_msg = str(exc).lower()

        # Only fallback on rate limits or quota errors
        if any(term in error_msg for term in ['rate limit', 'quota', 'capacity']):
            if self.model_name != "gpt-4o-mini":
                # Try fallback model (claude -> gpt-4o-mini as lighter alternative)
                original = self.model_name
                self.model_name = "gpt-4o-mini"

                try:
                    result = self.exec(prep_res)
                    result["model"] = f"{result['model']} (fallback from {original})"
                    result["fallback_reason"] = str(exc)
                    return result
                except Exception:
                    # Restore original model name and re-raise
                    self.model_name = original
                    raise exc

        # No fallback available or not a rate limit error
        raise exc

    def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
             exec_res: Dict[str, Any]) -> str:
        """Store results in shared store following natural patterns."""
        # Primary output
        shared["response"] = exec_res["text"]

        # Also store as 'text' for easy chaining
        shared["text"] = exec_res["text"]

        # Metadata
        # Usage object from llm-main/llm/models.py:45 has input/output/details fields
        shared["llm_usage"] = exec_res["usage"]
        shared["llm_model"] = exec_res["model"]

        # Store structured output if available
        if "json" in exec_res and exec_res["json"]:
            shared["llm_json"] = exec_res["json"]

        # Track cumulative token usage for cost tracking (pflow-specific feature)
        # Note: llm's Usage object has separate input/output fields
        usage = exec_res["usage"]
        if usage.get("input") and usage.get("output"):
            total = usage["input"] + usage["output"]
            shared["total_tokens"] = shared.get("total_tokens", 0) + total

        # Store fallback info if it happened
        if "fallback_reason" in exec_res:
            shared["llm_fallback"] = exec_res["fallback_reason"]

        # Return default action for flow control
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

        # Test prompt extraction priority
        shared = {"prompt": "Test prompt"}
        prep_res = node.prep(shared)
        assert prep_res["prompt"] == "Test prompt"

        # Test fallback to text
        shared = {"text": "Test text"}
        prep_res = node.prep(shared)
        assert prep_res["prompt"] == "Test text"

        # Test fallback to stdin
        shared = {"stdin": "Piped input"}
        prep_res = node.prep(shared)
        assert prep_res["prompt"] == "Piped input"

        # Test missing prompt
        shared = {}
        with pytest.raises(ValueError, match="No prompt found"):
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

        assert "text" in exec_res
        assert "Hello, World!" in exec_res["text"]
        assert "usage" in exec_res
        assert exec_res["model"] == "claude-sonnet-4-20250514"

    def test_post_phase(self):
        """Test storing results in shared store."""
        node = LLMNode()
        shared = {}

        exec_res = {
            "text": "LLM response",
            "usage": {"input": 20, "output": 80, "details": None},
            "model": "gpt-4o-mini"
        }

        action = node.post(shared, {}, exec_res)

        # Check all keys are set correctly
        assert shared["response"] == "LLM response"
        assert shared["text"] == "LLM response"  # For chaining
        assert shared["llm_usage"]["input"] == 20
        assert shared["llm_usage"]["output"] == 80
        assert shared["llm_model"] == "gpt-4o-mini"
        assert shared["total_tokens"] == 100  # 20 + 80
        assert action == "default"

    def test_multimodal_support(self):
        """Test image attachment handling."""
        node = LLMNode(model="gpt-4-vision-preview")

        shared = {
            "prompt": "What's in this image?",
            "images": ["/path/to/image.jpg"]
        }

        prep_res = node.prep(shared)
        assert len(prep_res["attachments"]) == 1

    def test_structured_output(self):
        """Test JSON schema support."""
        node = LLMNode()

        shared = {
            "prompt": "Extract person data",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "number"}
                }
            }
        }

        prep_res = node.prep(shared)
        assert prep_res["schema"] is not None
```

## Common Pitfalls to Avoid

1. **Don't access shared in exec()**: Only in prep() and post()
2. **Don't hardcode API keys**: Use environment variables
3. **Don't skip error messages**: Provide helpful model suggestions
4. **Remember retries**: Node base class handles retry logic
5. **Check for images carefully**: Handle both string and list formats

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
llm = LLMNode(model="claude-3-5-sonnet-latest", temperature=0.7)
write_file = WriteFileNode()

flow = Flow(start=read_file)
read_file >> llm >> write_file

# Shared store flow:
# read_file: puts content in shared["content"]
# llm: reads shared["content"] as fallback to shared["text"]
# llm: writes shared["response"] and shared["text"]
# write_file: reads shared["text"] and writes to file
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
