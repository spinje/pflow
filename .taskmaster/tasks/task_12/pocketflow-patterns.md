# PocketFlow Patterns for Task 12: Implement General LLM Node

## Overview

The general-purpose LLM node is a "smart exception" to the simple node philosophy. Instead of creating dozens of specific nodes (summarize, analyze, translate), one flexible LLM node handles all text processing tasks through prompt engineering.

## Relevant Cookbook Examples

- `cookbook/pocketflow-chat`: Basic LLM integration with conversation
- `cookbook/pocketflow-structured-output`: Prompt engineering for structured responses
- `cookbook/pocketflow-agent`: LLM decision making with YAML parsing
- `cookbook/pocketflow-supervisor`: Error handling and retry patterns

## Patterns to Adopt

### Pattern: Universal Text Processing Interface
**Source**: Multiple cookbook examples showing prompt-based flexibility
**Compatibility**: ✅ Direct
**Description**: One node, many uses through dynamic prompts

**Original PocketFlow Pattern** (from chat example):
```python
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_input}
    ],
)
```

**Adapted for pflow**:
```python
from pocketflow import Node
import os

class LLMNode(Node):
    def __init__(self):
        # LLM calls benefit from retry
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared):
        # Universal interface: prompt is required
        prompt = shared.get("prompt")
        if not prompt:
            raise ValueError("Missing required input: prompt")

        # Optional conversation history
        history = shared.get("conversation_history", [])

        # Parameters for LLM behavior (not data)
        return {
            "prompt": prompt,
            "history": history,
            "model": self.params.get("model", "gpt-4"),
            "temperature": self.params.get("temperature", 0.7),
            "max_tokens": self.params.get("max_tokens", 2000),
            "system_message": self.params.get(
                "system_message",
                "You are a helpful AI assistant."
            ),
            "provider": self.params.get("provider", "openai")
        }

    def exec(self, prep_res):
        # Route to appropriate provider
        if prep_res["provider"] == "openai":
            return self._call_openai(prep_res)
        elif prep_res["provider"] == "anthropic":
            return self._call_anthropic(prep_res)
        else:
            raise ValueError(f"Unknown provider: {prep_res['provider']}")

    def _call_openai(self, prep_res):
        from openai import OpenAI

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        messages = [{"role": "system", "content": prep_res["system_message"]}]
        messages.extend(prep_res["history"])
        messages.append({"role": "user", "content": prep_res["prompt"]})

        response = client.chat.completions.create(
            model=prep_res["model"],
            messages=messages,
            temperature=prep_res["temperature"],
            max_tokens=prep_res["max_tokens"]
        )

        return response.choices[0].message.content

    def _call_anthropic(self, prep_res):
        # Similar implementation for Claude
        pass

    def exec_fallback(self, prep_res, exc):
        # Handle rate limits gracefully
        if "rate_limit" in str(exc).lower():
            return "[LLM unavailable due to rate limits. Please try again later.]"
        raise exc

    def post(self, shared, prep_res, exec_res):
        # Universal output interface
        shared["response"] = exec_res

        # Optional: maintain conversation history
        if self.params.get("maintain_history", False):
            history = shared.get("conversation_history", [])
            history.append({"role": "user", "content": prep_res["prompt"]})
            history.append({"role": "assistant", "content": exec_res})
            shared["conversation_history"] = history

        return "default"
```

### Pattern: Smart Exception Philosophy
**Source**: Architecture decision to prevent node proliferation
**Compatibility**: ✅ Direct
**Description**: General node prevents dozens of specific nodes

**Why this matters**:
```python
# WITHOUT smart exception (bad):
pflow summarize-node --text="..." >>
pflow analyze-node --text="..." >>
pflow translate-node --text="..." --language="es"

# WITH smart exception (good):
pflow llm --prompt="Summarize: $content" >>
pflow llm --prompt="Analyze sentiment: $content" >>
pflow llm --prompt="Translate to Spanish: $content"
```

**The key insight**: Prompt engineering happens in the workflow, not in node code.

### Pattern: Template Variable Support
**Source**: Integration with planner patterns
**Compatibility**: ✅ Direct
**Description**: Prompts can reference other shared store values

**Implementation note**:
```python
# Template resolution happens BEFORE node execution
# By the time LLMNode sees the prompt, variables are resolved

# In workflow:
prompt = "Analyze this issue: $issue_description"

# After resolution:
prompt = "Analyze this issue: [actual issue content]"

# Node just processes the final prompt
```

### Pattern: Structured Output Support
**Source**: `cookbook/pocketflow-structured-output/`
**Compatibility**: ✅ Direct
**Description**: Support for YAML/JSON extraction through prompts

**Example prompt patterns**:
```python
# For structured extraction
prompt = """Extract the following as YAML:
- name
- email
- skills (as a list)

Text: {text}

Output only valid YAML, nothing else."""

# For decision making
prompt = """Based on the question, decide the next action.
Return one of: search, answer, clarify

Question: {question}
Decision:"""
```

### Pattern: Multi-Provider Support
**Source**: Best practices for flexibility
**Compatibility**: ✅ Direct
**Description**: Support multiple LLM providers through params

**Implementation approach**:
```python
# Provider routing in exec()
providers = {
    "openai": self._call_openai,
    "anthropic": self._call_anthropic,
    "llama": self._call_llama,
}

handler = providers.get(prep_res["provider"])
if not handler:
    raise ValueError(f"Unknown provider: {prep_res['provider']}")

return handler(prep_res)
```

## Patterns to Avoid

### Pattern: Provider-Specific Nodes
**Issue**: Creates node proliferation (OpenAINode, ClaudeNode, etc.)
**Alternative**: Single LLMNode with provider parameter

### Pattern: Task-Specific Nodes
**Issue**: SummarizeNode, AnalyzeNode, TranslateNode, etc.
**Alternative**: Prompt engineering in the workflow

### Pattern: Complex State Management
**Issue**: Embedding vector stores, complex memory
**Alternative**: Simple conversation history, leave advanced features for v2.0

### Pattern: Streaming Responses
**Source**: `pocketflow-llm-streaming`
**Issue**: Requires async, not in MVP
**Alternative**: Synchronous responses only

## Implementation Guidelines

1. **One node to rule them all**: This node handles ALL LLM tasks
2. **Prompt is king**: Everything is controlled through the prompt
3. **Provider agnostic**: Support multiple LLM providers
4. **Simple history**: Basic conversation support, not complex memory
5. **Clear errors**: Helpful messages for missing API keys, rate limits

## Usage Examples

### Example 1: Simple Text Processing
```python
# Summarization
shared = {"prompt": "Summarize this article in 3 bullet points: ..."}
llm_node = LLMNode()
llm_node.set_params({"temperature": 0.3, "model": "gpt-4"})

# Analysis
shared = {"prompt": "What is the sentiment of this review: ..."}
llm_node.set_params({"temperature": 0.1})  # Low temp for analysis

# Creative writing
shared = {"prompt": "Write a story about: ..."}
llm_node.set_params({"temperature": 0.9, "max_tokens": 1000})
```

### Example 2: With Template Variables
```python
# Workflow using templates
shared = {
    "issue_description": "User cannot log in",
    "error_log": "401 Unauthorized",
    "prompt": "Debug this issue:\nDescription: $issue_description\nError: $error_log"
}
# After resolution, the node receives the complete prompt
```

### Example 3: Structured Output
```python
shared = {
    "prompt": """Analyze this PR and return as YAML:
    - summary: (one line)
    - changes: (list of changes)
    - risk: (low/medium/high)

    PR Description: $pr_description
    """
}
llm_node.set_params({"temperature": 0.2})  # Low for structured output
```

## Testing Approach

```python
def test_llm_node_basic():
    node = LLMNode()
    shared = {"prompt": "Say hello"}

    # Mock the LLM call
    with patch.object(node, '_call_openai') as mock:
        mock.return_value = "Hello! How can I help you?"
        node.run(shared)

    assert shared["response"] == "Hello! How can I help you?"

def test_missing_prompt():
    node = LLMNode()
    shared = {}  # No prompt

    with pytest.raises(ValueError, match="Missing required input: prompt"):
        node.run(shared)

def test_rate_limit_handling():
    node = LLMNode()
    shared = {"prompt": "Test"}

    # Mock rate limit error
    with patch.object(node, '_call_openai') as mock:
        mock.side_effect = Exception("rate_limit_exceeded")
        node.run(shared)

    assert "rate limit" in shared["response"].lower()

def test_provider_routing():
    node = LLMNode()
    node.set_params({"provider": "anthropic"})

    with patch.object(node, '_call_anthropic') as mock:
        mock.return_value = "Claude response"
        shared = {"prompt": "Test"}
        node.run(shared)

    mock.assert_called_once()
```

This LLM node embodies pflow's philosophy: simple interfaces, powerful capabilities, and prevention of unnecessary complexity.
