# LLM Node Package Specification

> **Prerequisites**: Before implementing or using this node, read the [Enhanced Interface Format](../reference/enhanced-interface-format.md) for common patterns and best practices.

> **Note**: This package contains a single general-purpose `llm` node as a smart exception to the simple nodes pattern.

This node is an intentional exception to our [simple node philosophy](../features/simple-nodes.md) - instead of creating dozens of specific prompt-based nodes, we provide one flexible `llm` node that handles all text processing tasks.

## Overview

The `LLM` node is pflow's **general-purpose language model processing node**. It serves as a smart exception to our "one node, one purpose" philosophy by replacing what would otherwise be dozens of specific prompt-based nodes (`analyze-code`, `write-content`, `explain-concept`, etc.).

This single, flexible node handles all text generation and processing tasks through a simple prompt interface.

---

## ✅ Purpose

The `LLM` node provides:

* **General-purpose text processing** - handles any prompt-based task
* **Consistent interface** - prompt via params, writes `response` and `llm_usage`
* **Simon Willison's llm library** - wraps the `llm` library for model management
* **Smart exception design** - prevents proliferation of similar prompt nodes
* **Auto-detection** - model is auto-detected via `llm` library when not specified

---

## 🔧 Interface

| Interface  | Type  | Key | Description                          |
| ---------- | ----- | --- | ------------------------------------ |
| **Params** | `str` | `prompt` | Text prompt to send to model |
| **Params** | `str` | `model` | Model identifier (optional, auto-detected via `llm` library) |
| **Params** | `float` | `temperature` | Sampling temperature (default: 0.7) |
| **Params** | `list[str]` | `images` | Image paths for multimodal (optional) |
| **Writes** | `any` | `shared["response"]` | Model response (auto-parsed JSON or string) |
| **Writes** | `dict` | `shared["llm_usage"]` | Token usage metrics |


### Natural Usage Pattern
```python
# Node params configure the request
node.set_params({
    "prompt": "Analyze this code for potential issues",
    "temperature": 0.5
})

# After LLM node execution
shared["response"] = "The code has the following potential issues..."
shared["llm_usage"] = {"input_tokens": 15, "output_tokens": 42, "model": "gpt-4o-mini"}
```

---

## 🔐 Parameters

| Param         | Type    | Default    | Description                                                    |
| ------------- | ------- | ---------- | -------------------------------------------------------------- |
| `model`       | `str`   | `"auto"`   | Auto-detected via `llm` library (uses default model)          |
| `temperature` | `float` | `0.7`      | Sampling temperature for creativity control                    |
| `system`      | `str?`  | `None`     | Optional system prompt for behavior guidance                   |
| `max_tokens`  | `int?`  | `None`     | Optional output limit (model-dependent)                       |
| `images`      | `list[str]?` | `None` | Optional image paths for multimodal models                    |


---

## 🎯 Why One LLM Node Instead of Many?

### ❌ Without LLM Node (Node Proliferation)
```python
# Many specific nodes for similar tasks
class AnalyzeCodeNode(Node): ...
class WriteContentNode(Node): ...
class ExplainConceptNode(Node): ...
class ReviewTextNode(Node): ...
class SummarizeNode(Node): ...
class GenerateOutlineNode(Node): ...
# ... dozens more
```

### ✅ With LLM Node (Smart Exception)
```bash
# One flexible node for all text processing
pflow llm --prompt="Analyze this code for potential issues"
pflow llm --prompt="Write an introduction paragraph about AI"
pflow llm --prompt="Explain this concept in simple terms"
pflow llm --prompt="Review this text for clarity and tone"
pflow llm --prompt="Summarize this article in 3 bullet points"
pflow llm --prompt="Create an outline for a technical blog post"
```

### Benefits of This Approach

1. **Maintainability**: Update LLM logic in one place
2. **Discoverability**: Users know to use `llm` for any text task
3. **Simplicity**: Just pass a prompt, no complex templates initially
4. **Consistency**: Same interface for all prompt operations
5. **Evolution**: Easy to add features like templates later

---

## 💻 Implementation Notes

The LLM node follows standard node patterns with:
- Input validation in `prep()` phase
- LLM API call in `exec()` phase
- Response storage in `post()` phase

For complete implementation details, see [Enhanced Interface Format](../reference/enhanced-interface-format.md).

---

## 🧪 Example Usage

### Simple Text Processing
```bash
# Summarization
pflow read-file data.txt => llm --prompt="Summarize this data in 3 bullet points"

# Analysis
pflow github-get-issue --issue=123 => llm --prompt="Analyze this issue and suggest a fix"

# Content Creation
echo "AI Safety" | pflow llm --prompt="Write an introduction paragraph about this topic"
```

### With Parameters
```bash
# Creative writing
pflow llm --prompt="Write a haiku about coding" --temperature=0.9

# Technical analysis (conservative)
pflow llm --prompt="Review this code for bugs" --temperature=0.1 --model=gpt-4o

# With system prompt
pflow llm --prompt="Explain quantum computing" --system="You are a physics professor"
```

### In Workflows
```bash
# Multi-step content pipeline
pflow read-file research.md => \
  llm --prompt="Extract key findings from this research" => \
  llm --prompt="Write a blog post based on these findings" => \
  write-file blog-post.md
```

---

## 🔮 Current Implementation: Simon Willison's LLM Library

The LLM node is built on [Simon Willison's `llm` library](https://github.com/simonw/llm):

### Implemented Features
- **Model Auto-Detection**: Uses `llm`'s default model when none specified
- **Multi-Provider Support**: OpenAI, Anthropic, local models, and more via plugins
- **Plugin Ecosystem**: Access to LLM plugins for additional models
- **Token Tracking**: Usage metrics captured in `shared["llm_usage"]`

### Usage Examples
```bash
# Simple (uses auto-detected default model)
pflow llm --prompt="Summarize this text"

# With explicit model
pflow llm --model=gpt-4o --prompt="Analyze this code"
```

### llm_usage Output
The node writes token usage metrics to `shared["llm_usage"]`:
```python
{
    "input_tokens": 150,    # Tokens in prompt
    "output_tokens": 42,    # Tokens in response
    "model": "gpt-4o-mini"  # Model used for generation
}
```

---

## 🧱 Design Rationale

| Design Decision | Rationale |
|-----------------|-----------|
| **General-purpose approach** | Prevents node proliferation while maintaining flexibility |
| **Simple prompt interface** | Keeps MVP focused, templates can come later |
| **Params-only pattern** | All inputs via params, outputs to shared store |
| **llm library integration** | Leverages existing ecosystem instead of rebuilding |
| **Conservative defaults** | Temperature 0.7 balances creativity and consistency |

---

## 🔄 Node Composition Examples

The LLM node composes naturally with other simple nodes:

```bash
# Data analysis pipeline
pflow read-file data.csv => \
  llm --prompt="Analyze this data and find patterns" => \
  llm --prompt="Create visualizations suggestions for this analysis" => \
  write-file analysis-report.md

# GitHub workflow
pflow github-get-issue --issue=123 => \
  github-get-files --paths="src/" => \
  llm --prompt="Review this issue and related code, suggest implementation" => \
  write-file implementation-plan.md

# Content pipeline
pflow web-fetch --url=example.com/article => \
  llm --prompt="Summarize this article" => \
  llm --prompt="Generate 5 discussion questions about this summary" => \
  slack-send-message --channel=book-club
```

---

## 🧪 Testing Pattern

```python
def test_llm_node():
    node = LLMNode()
    node.set_params({
        "prompt": "Explain machine learning in one sentence",
        "temperature": 0.5
    })

    shared = {}
    node.run(shared)

    assert "response" in shared
    assert len(shared["response"]) > 0
    assert "machine learning" in shared["response"].lower()
    assert "llm_usage" in shared
    assert "input_tokens" in shared["llm_usage"]
```

---

## 📈 Future Evolution

### Post-MVP Extensions
1. **Template System**: Support for reusable prompt templates
2. **Multi-turn Context**: Conversation-style interactions
3. **Structured Output**: JSON, YAML, and other format generation
4. **Tool Integration**: Function calling capabilities
5. **Batch Processing**: Handle multiple prompts efficiently

### Maintaining Simplicity
Even with future extensions, the core interface remains simple:
- Input: `prompt` param
- Output: `shared["response"]` and `shared["llm_usage"]`
- Configuration: via params

Additional features will be opt-in through parameters, keeping the basic usage straightforward.

---

## 📝 Summary

The LLM node represents a carefully designed exception to pflow's simple node philosophy. By consolidating all text processing tasks into one flexible, well-designed node, we:

- **Prevent node proliferation** while maintaining functionality
- **Provide consistent interfaces** across all text tasks
- **Enable natural composition** with other simple nodes
- **Build foundation** for future advanced features
- **Keep MVP simple** with just prompt-based usage

This approach delivers the benefits of simplicity (one interface to learn) with the power of flexibility (handles any text task).

## See Also

- [Simple Nodes](../features/simple-nodes.md) - Node design philosophy
- [Shared Store](../core-concepts/shared-store.md) - Inter-node data flow
- [Node Metadata](../reference/ir-schema.md#node-metadata-schema) - Interface format
