# LLM Node Package Specification

> **Prerequisites**: Before implementing or using this node, read the [Node Implementation Reference](../reference/node-reference.md) for common patterns and best practices.

> **Note**: This package contains a single general-purpose `llm` node as a smart exception to the simple nodes pattern.

This node is an intentional exception to our [simple node philosophy](../features/simple-nodes.md) - instead of creating dozens of specific prompt-based nodes, we provide one flexible `llm` node that handles all text processing tasks.

## Overview

The `LLM` node is pflow's **general-purpose language model processing node**. It serves as a smart exception to our "one node, one purpose" philosophy by replacing what would otherwise be dozens of specific prompt-based nodes (`analyze-code`, `write-content`, `explain-concept`, etc.).

This single, flexible node handles all text generation and processing tasks through a simple prompt interface.

---

## ✅ Purpose

The `LLM` node provides:

* **General-purpose text processing** - handles any prompt-based task
* **Consistent interface** - always reads `prompt`, writes `response`
* **Future Simon Willison integration** - will wrap the `llm` CLI for model management
* **Smart exception design** - prevents proliferation of similar prompt nodes
* **Simple MVP implementation** - just `--prompt` parameter, templates come later

---

## 🔧 Interface

| Interface  | Type  | Key in Shared Store | Description                          |
| ---------- | ----- | ------------------- | ------------------------------------ |
| **Input**  | `str` | `prompt`            | The prompt text to send to the model |
| **Output** | `str` | `response`          | The model-generated output text      |


### Natural Usage Pattern
```python
# In shared store before LLM node
shared["prompt"] = "Analyze this code for potential issues"

# After LLM node execution
shared["response"] = "The code has the following potential issues..."
```

---

## 🔐 Parameters

| Param         | Type    | Default    | Description                                                    |
| ------------- | ------- | ---------- | -------------------------------------------------------------- |
| `model`       | `str`   | `"claude-sonnet-4-20250514"`  | Model name to use                                             |
| `temperature` | `float` | `0.7`      | Sampling temperature for creativity control                    |
| `system`      | `str?`  | `None`     | Optional system prompt for behavior guidance                   |
| `max_tokens`  | `int?`  | `None`     | Optional output limit (model-dependent)                       |


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

For complete implementation details, see [Node Reference](../reference/node-reference.md#common-node-templates).

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
pflow llm --prompt="Review this code for bugs" --temperature=0.1 --model=claude-sonnet-4-20250514

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

## 🔮 Future Integration: Simon Willison's LLM CLI

The LLM node is designed for future integration with [Simon Willison's `llm` CLI](https://github.com/simonw/llm):

### Planned Features (Post-MVP)
- **Model Management**: Use `llm`'s model aliases and plugin system
- **Multi-Provider Support**: OpenAI, Anthropic, local models, etc.
- **Template System**: Advanced prompt templating capabilities
- **Plugin Ecosystem**: Access to LLM plugins and extensions

### Current MVP vs Future
```bash
# MVP (simple)
pflow llm --prompt="Summarize this text"

# Future (with llm CLI integration)
pflow llm --model=claude-sonnet-4-20250514 --template=summary --input=text
```

---

## 🧱 Design Rationale

| Design Decision | Rationale |
|-----------------|-----------|
| **General-purpose approach** | Prevents node proliferation while maintaining flexibility |
| **Simple prompt interface** | Keeps MVP focused, templates can come later |
| **Shared store + params pattern** | Enables both dynamic and static configuration |
| **Future llm CLI integration** | Leverages existing ecosystem instead of rebuilding |
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
        "model": "claude-sonnet-4-20250514",
        "temperature": 0.5
    })

    shared = {"prompt": "Explain machine learning in one sentence"}
    node.run(shared)

    assert "response" in shared
    assert len(shared["response"]) > 0
    assert "machine learning" in shared["response"].lower()
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
- Input: `shared["prompt"]`
- Output: `shared["response"]`
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

- **Design Philosophy**: [Simple Nodes Pattern](../features/simple-nodes.md) - Why this is a smart exception
- **Interface Format**: [Node Metadata Schema](../core-concepts/schemas.md#node-metadata-schema) - How node interfaces are defined
- **Communication**: [Shared Store Pattern](../core-concepts/shared-store.md) - Inter-node data flow
- **Node Registry**: [Registry System](../core-concepts/registry.md) - How nodes are discovered and managed
- **Related Nodes**:
  - [Claude Nodes](./claude-nodes.md) - Comprehensive development "super node" (more complex alternative)
  - [GitHub Nodes](./github-nodes.md) - Platform integration nodes
  - [CI Nodes](./ci-nodes.md) - Testing and deployment nodes
