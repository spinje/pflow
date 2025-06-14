# Shared Store vs Params Architecture Analysis

## Overview

This document analyzes patterns from pocketflow cookbook examples to establish clear architectural guidelines for when to use shared store vs params in pflow nodes. It also addresses the design of reusable LLM nodes to reduce clutter and improve maintainability.

## Key Patterns from Pocketflow Examples

### 1. Shared Store Usage Patterns

From analyzing the cookbook examples, shared store is used for:

**Data Flow Between Nodes:**
```python
# pocketflow-agent example
shared["question"] = "What Nobel prizes were awarded in 2024?"
shared["context"] = "Previous search results..."
shared["search_query"] = "Nobel prizes 2024"
shared["answer"] = "Final generated answer"

# pocketflow-workflow example
shared["topic"] = "AI Safety"
shared["sections"] = ["Introduction", "Challenges", "Strategies"]
shared["draft"] = "Combined article content"
shared["final_article"] = "Styled article"
```

**Intermediate State Management:**
```python
# pocketflow-mcp example
shared["tools"] = available_tools_list
shared["tool_name"] = "add"
shared["parameters"] = {"a": 5, "b": 10}
shared["tool_info"] = formatted_tool_descriptions
```

### 2. Params Usage Patterns

From the examples, params are used for:

**Node Configuration:**
```python
# pocketflow-structured-output example
parser_node = ResumeParserNode(max_retries=3, wait=10)

# pocketflow-workflow (implied)
summarize_node.set_params({"temperature": 0.7})

# pocketflow-mcp (implied)
decide_node.set_params({"model": "gpt-4", "temperature": 0.5})
```

**Behavioral Settings:**
- LLM parameters (temperature, max_tokens, model)
- Retry logic (max_retries, wait)
- Format options (output format, style preferences)
- API configurations (endpoints, keys)

### 3. Action-Based Pattern Observations

The pocketflow-agent example demonstrates action-based flow control:
```python
# DecideAction node returns action strings
return exec_res["action"]  # Returns "search" or "answer"

# Flow transitions based on actions
decide_node - "search" >> search_node
decide_node - "answer" >> answer_node
search_node - "decide" >> decide_node  # Loop back
```

## Clear Rules for Shared Store vs Params

### Use Shared Store When:

1. **Data flows between nodes**
   - Input/output data that transforms through the pipeline
   - Results that subsequent nodes need to process
   - Accumulated context or state

2. **Content is dynamic**
   - User inputs
   - API responses
   - Generated content
   - Search results

3. **Data has workflow-level significance**
   - The data is part of the workflow's core purpose
   - Multiple nodes may need access to it
   - It represents the "work" being done

### Use Params When:

1. **Configuration is static**
   - Model selection
   - Temperature settings
   - API endpoints
   - Retry policies

2. **Settings are node-specific**
   - Behavioral configuration that doesn't affect other nodes
   - Implementation details (timeouts, formats)
   - Resource limits

3. **Values are operational**
   - How the node operates, not what it operates on
   - Performance tuning
   - Error handling configuration

## Reusable LLM Node Design

### Problem: LLM Node Proliferation

Without a reusable design, we end up with many similar nodes:
```python
# Anti-pattern: Many specific LLM nodes
AnalyzeIssueNode, ImplementSolutionNode, ReviewCodeNode,
ExplainConceptNode, SummarizeTextNode, GenerateTestsNode...
```

### Solution: Action-Based LLM Node

Following the action-based pattern from pflow's architecture:

```python
class LLMNode(Node):
    """General-purpose LLM node with action dispatch.

    Interface:
    - Reads: shared["input"] - input data for the LLM
    - Reads: shared["context"] - optional additional context
    - Writes: shared["output"] - LLM response
    - Params: action, model, temperature, system_prompt, max_tokens
    """

    def prep(self, shared):
        # Gather inputs based on action
        action = self.params.get("action", "generate")

        if action in ["analyze", "review", "explain"]:
            # These actions typically need both input and context
            return {
                "input": shared.get("input", ""),
                "context": shared.get("context", ""),
                "action": action
            }
        else:
            # Default actions just need input
            return {
                "input": shared.get("input", ""),
                "action": action
            }

    def exec(self, prep_res):
        action = prep_res["action"]

        # Build prompt based on action
        if action == "analyze":
            prompt = self._build_analysis_prompt(prep_res)
        elif action == "implement":
            prompt = self._build_implementation_prompt(prep_res)
        elif action == "review":
            prompt = self._build_review_prompt(prep_res)
        elif action == "summarize":
            prompt = self._build_summary_prompt(prep_res)
        else:
            # Generic prompt construction
            prompt = prep_res["input"]

        # Add system prompt if provided
        system = self.params.get("system_prompt")

        # Call LLM with params
        return call_llm(
            prompt=prompt,
            system=system,
            model=self.params.get("model", "gpt-4"),
            temperature=self.params.get("temperature", 0.7),
            max_tokens=self.params.get("max_tokens", 1000)
        )

    def post(self, shared, prep_res, exec_res):
        # Store result in shared store
        shared["output"] = exec_res

        # Return action for flow control if needed
        return self.params.get("next_action", "default")
```

### Usage Examples

```bash
# CLI usage with action dispatch
pflow llm --action=analyze --model=gpt-4 --temperature=0.3
pflow llm --action=implement --system="You are a Python expert"
pflow llm --action=review --max_tokens=2000

# In flows
github --action=get-issue >>
llm --action=analyze >>
llm --action=implement >>
llm --action=review

# MVP usage with templates
pflow llm --prompt_template="Analyze this issue: {issue}"
pflow llm --prompt_template="Create outline for article about {topic}"
pflow llm --system="You are a helpful assistant" --model=claude-3-opus

# Future: Direct integration with Simon Willison's llm CLI
pflow llm --model=gpt-4-turbo --prompt_template="{input}"
# Will use llm's model aliases and plugin system
```

### Benefits of This Approach

1. **Reduced Node Count**: One LLM node instead of dozens
2. **Consistent Interface**: Always reads `input`, writes `output`
3. **Flexible Configuration**: Action-specific prompting logic
4. **Maintainable**: Centralized LLM interaction patterns
5. **Discoverable**: `pflow describe llm` shows all actions

## Alternative LLM Node Designs

### Design 1: LLM Node with Simon Willison's LLM Integration (Recommended for MVP)

```python
class LLMNode(Node):
    """General-purpose LLM node wrapping Simon Willison's llm functionality.

    This node will integrate with Simon Willison's llm CLI tool, providing
    access to multiple LLM providers through a unified interface.

    Interface:
    - Reads: shared["prompt"] OR builds from template
    - Writes: shared["response"]
    - Params: prompt_template, model, temperature, system, max_tokens

    Future integration with llm CLI features:
    - Model aliases from llm CLI config
    - Plugin support for additional models
    - Conversation management
    - Token counting and cost tracking
    """

    def prep(self, shared):
        # If explicit prompt provided, use it
        if "prompt" in shared:
            return shared["prompt"]

        # Otherwise, build from template
        template = self.params.get("prompt_template", "{input}")

        # Simple template substitution from shared store
        prompt = template
        for key, value in shared.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))

        return prompt

    def exec(self, prompt):
        # MVP: Direct LLM call
        # Future: Use Simon Willison's llm library
        # import llm
        # model = llm.get_model(self.params.get("model", "gpt-4"))
        # response = model.prompt(
        #     prompt,
        #     system=self.params.get("system"),
        #     temperature=self.params.get("temperature", 0.7),
        #     max_tokens=self.params.get("max_tokens")
        # )

        # For now, use simple call_llm utility
        return call_llm(
            prompt=prompt,
            model=self.params.get("model", "gpt-4"),
            temperature=self.params.get("temperature", 0.7),
            system=self.params.get("system"),
            max_tokens=self.params.get("max_tokens")
        )

    def post(self, shared, prep_res, exec_res):
        shared["response"] = exec_res
        return "default"
```

### Design 2: Purpose-Specific Nodes (Current Approach)

Keep specific nodes but ensure they follow consistent patterns:
```python
class AnalyzeNode(Node):
    """Analyzes input data."""
    # Reads: shared["input"], shared["context"]
    # Writes: shared["analysis"]

class ImplementNode(Node):
    """Implements solution based on analysis."""
    # Reads: shared["analysis"], shared["requirements"]
    # Writes: shared["implementation"]
```

## Recommendations

### 1. For MVP Implementation

Use a simple `llm` node (Design 1) that:
- Accepts either explicit prompts or templates
- Provides consistent LLM access
- Reduces initial node complexity
- Wraps Simon Willison's llm functionality (future integration)

### 2. Shared Store vs Params Guidelines

**Document these rules clearly:**

```python
# SHARED STORE: Workflow data
shared = {
    "input_file": "data.csv",        # Input data
    "processed_data": {...},         # Intermediate results
    "analysis": "...",               # Node outputs
    "final_report": "..."            # Final results
}

# PARAMS: Node configuration
node.set_params({
    "model": "gpt-4",               # LLM selection
    "temperature": 0.7,             # Generation settings
    "max_retries": 3,               # Error handling
    "output_format": "markdown"     # Formatting options
})
```

### 3. Action-Based Evolution Path

For v2.0, consider migrating to action-based LLM node:
- Maintains backward compatibility
- Reduces cognitive load
- Aligns with platform node patterns
- Enables better discovery

### 4. Clear Node Interface Documentation

Every node should clearly document:
```python
class NodeName(Node):
    """Brief description.

    Interface:
    - Reads: shared["key1"] - description
    - Reads: shared["key2"] - description (optional)
    - Writes: shared["key3"] - description
    - Params: param1, param2, param3
    - Actions: action1, action2 (if action-based)
    """
```

## Conclusion

The pocketflow examples demonstrate clear patterns:
1. **Shared store** is for workflow data that flows between nodes
2. **Params** are for node-specific configuration
3. **Action-based patterns** reduce node proliferation
4. **Consistent interfaces** improve discoverability

For pflow's MVP, adopting these patterns with a simple `llm` node will provide:
- A solid foundation that wraps Simon Willison's llm functionality
- Reduced node clutter by replacing many specific LLM nodes
- Future extensibility for action-based designs
- Compatibility with the broader llm ecosystem and plugins

## Example: Shared Store vs Params in Practice

```python
# Dynamic data from workflow - use shared store
shared["issue_number"] = extract_from_url(url)  # Dynamic extraction
shared["issue_number"] = user_input             # User provided

# Static configuration - use params
node.set_params({
    "issue_number": 123,    # Fixed for testing
    "repo": "owner/repo",   # Configuration
    "token": api_token      # Credentials
})

# Best practice: Check both (shared store takes precedence)
issue_number = shared.get("issue_number") or self.params.get("issue_number")
```
