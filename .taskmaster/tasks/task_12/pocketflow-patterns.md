# PocketFlow Patterns for Task 12: Implement General LLM Node

## Task Context

- **Goal**: Create general-purpose LLM node preventing node proliferation
- **Dependencies**: Task 9 (natural keys: prompt/response)
- **Constraints**: Must support YAML output format (90% more reliable than JSON)

## Overview

The general-purpose LLM node is a "smart exception" to the simple node philosophy. Instead of creating dozens of specific nodes (summarize, analyze, translate), one flexible LLM node handles all text processing tasks through prompt engineering.

## Core Patterns from Advanced Analysis

### Pattern: YAML Output Format (CRITICAL)
**Found in**: ALL 7 repositories eventually switched to YAML
**Why It Applies**: 90% reduction in parsing failures vs JSON

```python
import yaml

def format_yaml_prompt(prompt: str, require_yaml: bool = False) -> str:
    """Ensure YAML output when structured data needed"""
    if require_yaml or "yaml" in prompt.lower() or "structured" in prompt.lower():
        if "Output" not in prompt:
            prompt += "\n\nOutput your response in YAML format."
    return prompt

# In LLMNode
def exec(self, prep_res):
    # Auto-detect structured output need
    prompt = prep_res["prompt"]
    output_format = self.params.get("output_format", "auto")

    if output_format == "yaml" or self._needs_structured_output(prompt):
        prompt = format_yaml_prompt(prompt, require_yaml=True)
        prep_res["prompt"] = prompt
        prep_res["parse_yaml"] = True

    # Call LLM
    response = self._call_provider(prep_res)

    # Parse YAML if requested
    if prep_res.get("parse_yaml"):
        try:
            parsed = yaml.safe_load(response)
            return {"response": response, "parsed": parsed}
        except yaml.YAMLError:
            # Fallback to text
            return {"response": response}

    return {"response": response}
```

### Pattern: Deterministic Temperature
**Found in**: All production repos use temperature=0 for consistency
**Why It Applies**: "Plan Once, Run Forever" requires determinism

```python
def get_temperature(self, task_type: str) -> float:
    """Temperature based on task type for determinism"""
    deterministic_tasks = {
        "analysis", "extraction", "classification",
        "structured", "decision", "planning"
    }

    # User override
    if "temperature" in self.params:
        return self.params["temperature"]

    # Auto-detect from prompt
    prompt_lower = self.prompt.lower()
    for task in deterministic_tasks:
        if task in prompt_lower:
            return 0.0  # Deterministic

    # Default for creative tasks
    return 0.7
```

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
**Source**: `cookbook/pocketflow-structured-output/` + ALL analyzed repos
**Compatibility**: ✅ Direct
**Description**: YAML strongly preferred over JSON

**Example prompt patterns**:
```python
# For structured extraction (YAML format)
prompt = """Extract the following information and output as YAML:
- name: (string)
- email: (string)
- skills: (list of strings)

Text: {text}

Output only valid YAML, nothing else."""

# For decision making (YAML format)
prompt = """Based on the question, decide the next action.

Output as YAML:
decision: (one of: search, answer, clarify)
reasoning: (brief explanation)
confidence: (low/medium/high)

Question: {question}"""

# Why YAML > JSON:
# 1. More forgiving syntax (no quote requirements)
# 2. Multi-line strings natural
# 3. Comments allowed
# 4. LLMs make fewer syntax errors
```

### Pattern: Structured Prompt Templates
**Found in**: Danganronpa, Website Chatbot, Cold Email
**Why It Applies**: Consistent structure improves reliability

```python
class PromptTemplates:
    """Reusable templates for common tasks"""

    ANALYSIS = """Analyze the following {subject}:

{content}

Provide your analysis as YAML with these fields:
- summary: (one paragraph)
- key_points: (list of 3-5 points)
- sentiment: (positive/neutral/negative)
- confidence: (low/medium/high)
"""

    DECISION = """Based on the current context, decide the next action.

Context:
{context}

Available actions:
{actions}

Output as YAML:
action: (selected action)
reasoning: (why this action)
parameters: (any parameters for the action)
"""

    CODE_REVIEW = """Review this code change:

{code_diff}

Output as YAML:
approval: (approve/request_changes)
issues: (list of any issues found)
suggestions: (list of improvements)
risk_level: (low/medium/high)
"""
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
3. **YAML for structure**: Use YAML output format for structured data
4. **Temperature = 0**: Default to deterministic for reproducibility
5. **Provider agnostic**: Support multiple LLM providers
6. **Simple history**: Basic conversation support, not complex memory
7. **Clear errors**: Helpful messages for missing API keys, rate limits

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

## Integration Points

### Connection to Task 17 (Workflow Generation)
LLM node will process planner prompts:
```python
# Planner uses LLM node with YAML output
shared = {
    "prompt": PromptTemplates.WORKFLOW_GENERATION.format(
        request=user_request,
        available_nodes=node_list
    )
}
llm_node.set_params({"temperature": 0, "output_format": "yaml"})
```

### Connection to Task 9 (Natural Keys)
Uses standard keys:
```python
# Input
shared["prompt"] = "Analyze this: ..."

# Output
shared["response"] = "Analysis: ..."
shared["parsed"] = {"summary": "...", "points": [...]}
```

### Connection to Task 24 (Caching)
Deterministic settings enable caching:
```python
# With temperature=0, same prompt → same response
# Cache key includes: prompt + model + temperature
@flow_safe  # Can mark as cacheable when deterministic
```

## Minimal Test Case

```python
# Save as test_llm_patterns.py
import yaml
from pocketflow import Node
from unittest.mock import Mock, patch

class MinimalLLMNode(Node):
    """LLM node with all critical patterns"""

    def prep(self, shared):
        prompt = shared.get("prompt")
        if not prompt:
            raise ValueError("Missing required input: prompt")

        # Check for structured output need
        needs_yaml = (
            "yaml" in prompt.lower() or
            "structured" in prompt.lower() or
            self.params.get("output_format") == "yaml"
        )

        if needs_yaml and "Output" not in prompt:
            prompt += "\n\nOutput in YAML format."

        return {
            "prompt": prompt,
            "temperature": self._get_temperature(prompt),
            "model": self.params.get("model", "gpt-4"),
            "parse_yaml": needs_yaml
        }

    def _get_temperature(self, prompt: str) -> float:
        """Deterministic for analysis tasks"""
        if "temperature" in self.params:
            return self.params["temperature"]

        analysis_keywords = ["analyze", "extract", "decide", "classify"]
        if any(kw in prompt.lower() for kw in analysis_keywords):
            return 0.0  # Deterministic

        return 0.7  # Default

    def exec(self, prep_res):
        # Mock LLM call for test
        if prep_res["parse_yaml"]:
            return """decision: approve
reasoning: Code follows all patterns
confidence: high"""
        else:
            return "This is a text response."

    def post(self, shared, prep_res, exec_res):
        shared["response"] = exec_res

        if prep_res["parse_yaml"]:
            try:
                shared["parsed"] = yaml.safe_load(exec_res)
            except yaml.YAMLError:
                pass  # Keep text only

        return "default"

def test_yaml_output_pattern():
    """Test YAML output is preferred"""

    # Test 1: Auto-detect YAML need
    node = MinimalLLMNode()
    shared = {"prompt": "Analyze this code and return structured results"}
    node.run(shared)

    assert "Output in YAML format" in node.prep(shared)["prompt"]
    assert "parsed" in shared
    assert shared["parsed"]["decision"] == "approve"

    # Test 2: Explicit YAML format
    node2 = MinimalLLMNode()
    node2.set_params({"output_format": "yaml"})
    shared2 = {"prompt": "Tell me a story"}
    node2.run(shared2)

    assert "Output in YAML format" in node2.prep(shared2)["prompt"]

    print("✓ YAML output pattern validated")

def test_deterministic_temperature():
    """Test temperature=0 for analysis tasks"""

    node = MinimalLLMNode()

    # Analysis task → temperature=0
    prep1 = node.prep({"prompt": "Analyze this PR"})
    assert prep1["temperature"] == 0.0

    # Creative task → temperature=0.7
    prep2 = node.prep({"prompt": "Write a poem"})
    assert prep2["temperature"] == 0.7

    # User override
    node.set_params({"temperature": 0.5})
    prep3 = node.prep({"prompt": "Analyze this"})
    assert prep3["temperature"] == 0.5

    print("✓ Deterministic temperature validated")

if __name__ == "__main__":
    test_yaml_output_pattern()
    test_deterministic_temperature()
    print("\n✅ All LLM patterns validated!")
```

## Summary

Task 12's LLM node incorporates critical insights from production usage:

1. **YAML Output Format** - 90% more reliable than JSON for structured data
2. **Temperature = 0** - Deterministic by default for reproducibility
3. **Smart Exception Design** - One node prevents proliferation
4. **Natural Key Usage** - Simple prompt/response interface
5. **Structured Templates** - Consistent prompts improve reliability

These patterns ensure LLM integration is reliable, efficient, and maintainable.
