# Prompt Engineering and Error Recovery Strategies for Natural Language Planner

## Overview

This document provides critical implementation guidance for prompt engineering and error recovery in Task 17. While the PocketFlow implementation provides the orchestration framework, the success of the natural language planner depends heavily on well-crafted prompts and robust error handling.

## Prompt Engineering Guidelines

### 1. System Prompt Design

The system prompt must establish clear boundaries and output format expectations:

```python
SYSTEM_PROMPT = """You are a workflow planner for pflow, a deterministic workflow compiler.

Your role:
1. Convert natural language requests into structured workflows
2. Use ONLY the nodes available in the provided registry
3. Generate template-driven workflows with $variables for reusability
4. Output valid JSON IR format without explanations

Key principles:
- Workflows must be deterministic and reproducible
- Use template variables ($var) for any user-specific values
- Chain nodes using the shared store pattern
- Prefer simple, linear flows over complex branching
- Every workflow must have clear input/output semantics
"""
```

### 2. Few-Shot Examples

Include 2-3 carefully crafted examples that demonstrate key patterns:

```python
FEW_SHOT_EXAMPLES = [
    {
        "request": "fix github issue 123",
        "workflow": {
            "nodes": [
                {"id": "get_issue", "type": "github-get-issue", "params": {"issue": "$issue"}},
                {"id": "analyze", "type": "claude-code", "params": {"prompt": "Fix this issue: $issue_data"}},
                {"id": "create_pr", "type": "github-create-pr", "params": {"title": "Fix issue #$issue"}}
            ],
            "edges": [
                {"from": "get_issue", "to": "analyze"},
                {"from": "analyze", "to": "create_pr"}
            ],
            "template_vars": {"issue": "123"}
        }
    },
    # Add 2 more examples covering different patterns
]
```

### 3. Context Building Strategy

The context provided to the LLM must be comprehensive yet focused:

```python
def build_planning_context(registry: dict, user_request: str) -> str:
    """Build optimized context for LLM planning."""

    # 1. Filter registry to relevant nodes (based on keywords)
    relevant_nodes = filter_relevant_nodes(registry, user_request)

    # 2. Group nodes by category for better organization
    grouped_nodes = {
        "file_operations": [],
        "git_operations": [],
        "github_operations": [],
        "ai_operations": [],
        "data_processing": []
    }

    # 3. Format with clear structure
    context = "## Available Nodes\n\n"
    for category, nodes in grouped_nodes.items():
        if nodes:
            context += f"### {category.replace('_', ' ').title()}\n"
            for node in nodes:
                context += format_node_entry(node)

    return context
```

### 4. Progressive Prompt Enhancement

When initial generation fails, enhance prompts progressively:

```python
PROMPT_ENHANCEMENTS = [
    # Level 1: Add clarification
    "Please ensure all nodes exist in the registry provided above.",

    # Level 2: Add constraints
    "Use only simple node types. Complex operations should use 'claude-code' node.",

    # Level 3: Simplify request
    "If the workflow seems complex, break it into smaller steps.",

    # Level 4: Provide template
    "Follow this structure: input → process → output. Map the request to these phases."
]
```

## Error Classification and Recovery

### 1. Error Types and Handlers

```python
class WorkflowGenerationError:
    """Base class for workflow generation errors."""

    RECOVERABLE_ERRORS = {
        "missing_node": {
            "pattern": r"Unknown node type: (\w+)",
            "recovery": "suggest_alternative_node",
            "max_retries": 3
        },
        "invalid_json": {
            "pattern": r"Invalid JSON|Expected.*got",
            "recovery": "request_json_only",
            "max_retries": 2
        },
        "circular_dependency": {
            "pattern": r"Circular dependency|Loop detected",
            "recovery": "simplify_flow",
            "max_retries": 2
        },
        "missing_template_var": {
            "pattern": r"Undefined variable: \$(\w+)",
            "recovery": "add_template_var",
            "max_retries": 1
        }
    }

    FATAL_ERRORS = {
        "rate_limit": "Please try again later",
        "context_too_long": "Request too complex, please simplify",
        "no_matching_nodes": "No suitable nodes found for this task"
    }
```

### 2. Recovery Strategies

```python
class RecoveryStrategies:
    @staticmethod
    def suggest_alternative_node(error_context, registry):
        """Find similar nodes when exact match fails."""
        missing_node = error_context["missing_node"]

        # Use fuzzy matching or semantic similarity
        alternatives = find_similar_nodes(missing_node, registry)

        enhancement = f"The node '{missing_node}' doesn't exist. "
        if alternatives:
            enhancement += f"Did you mean: {', '.join(alternatives)}?"
        else:
            enhancement += "Use 'claude-code' for complex operations."

        return enhancement

    @staticmethod
    def request_json_only(error_context, previous_response):
        """Handle JSON parsing errors."""
        # Extract any JSON-like content from response
        json_match = re.search(r'\{[\s\S]*\}', previous_response)

        if json_match:
            return "Extract and return ONLY the JSON part: " + json_match.group()
        else:
            return "Output ONLY valid JSON. Start with { and end with }. No other text."

    @staticmethod
    def simplify_flow(error_context, original_request):
        """Break complex flows into simpler ones."""
        return (
            "The workflow is too complex. Create a simpler linear flow: "
            "1) First, gather/read inputs "
            "2) Then, process with claude-code if needed "
            "3) Finally, write/send outputs"
        )
```

### 3. Retry Budget Management

```python
class RetryBudget:
    def __init__(self, token_budget=10000, cost_budget=0.50):
        self.token_budget = token_budget
        self.cost_budget = cost_budget
        self.tokens_used = 0
        self.cost_incurred = 0

    def can_retry(self, estimated_tokens, model="gpt-4o-mini"):
        """Check if we have budget for another attempt."""
        estimated_cost = self.estimate_cost(estimated_tokens, model)

        return (
            self.tokens_used + estimated_tokens <= self.token_budget and
            self.cost_incurred + estimated_cost <= self.cost_budget
        )

    def update(self, tokens_used, model):
        """Update budget after each attempt."""
        self.tokens_used += tokens_used
        self.cost_incurred += self.estimate_cost(tokens_used, model)
```

## Performance Optimization

### 1. Token Usage Optimization

```python
def optimize_prompt_tokens(prompt: str) -> str:
    """Reduce token usage while maintaining clarity."""
    optimizations = [
        # Remove redundant whitespace
        (r'\s+', ' '),
        # Compress node descriptions
        (r'This node is used to', ''),
        # Use abbreviations for common terms
        (r'repository', 'repo'),
        (r'pull request', 'PR'),
    ]

    for pattern, replacement in optimizations:
        prompt = re.sub(pattern, replacement, prompt)

    return prompt.strip()
```

### 2. Response Caching

```python
class WorkflowCache:
    """Cache generated workflows for similar requests."""

    def __init__(self, cache_dir=Path.home() / ".pflow" / "cache"):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)

    def get_cached_workflow(self, request: str, threshold=0.85):
        """Find cached workflow for similar request."""
        request_embedding = self.get_embedding(request)

        for cached_file in self.cache_dir.glob("*.json"):
            cached = json.loads(cached_file.read_text())
            similarity = cosine_similarity(
                request_embedding,
                cached["embedding"]
            )

            if similarity >= threshold:
                return cached["workflow"]

        return None
```

## Testing Strategies

### 1. Prompt Effectiveness Testing

```python
TEST_SCENARIOS = [
    {
        "category": "file_operations",
        "requests": [
            "read the error log and summarize issues",
            "copy all .py files to backup folder",
            "find and replace API_KEY in all config files"
        ],
        "expected_nodes": ["read-file", "llm", "write-file"]
    },
    {
        "category": "github_workflows",
        "requests": [
            "review open PRs and comment on them",
            "create issue for each TODO in code",
            "close stale issues older than 30 days"
        ],
        "expected_nodes": ["github-list-prs", "github-add-comment"]
    }
]
```

### 2. Error Recovery Testing

```python
def test_error_recovery():
    """Test each recovery strategy with synthetic errors."""
    test_cases = [
        {
            "error": "Unknown node type: github-fix-issue",
            "expected_recovery": "suggest using github-get-issue + claude-code"
        },
        {
            "error": "Invalid JSON: Unexpected token",
            "expected_recovery": "request clean JSON output"
        }
    ]
```

## Implementation Checklist

- [ ] Implement system prompt with clear boundaries
- [ ] Create few-shot example library (10-15 examples)
- [ ] Build context filtering based on request keywords
- [ ] Implement all recovery strategies
- [ ] Add retry budget management
- [ ] Create prompt token optimizer
- [ ] Build workflow caching system
- [ ] Design comprehensive test suite
- [ ] Add performance monitoring
- [ ] Document prompt versioning strategy

## Critical Success Factors

1. **Prompt Stability**: Version all prompts and track performance metrics
2. **Fast Failures**: Detect unrecoverable errors early
3. **User Feedback Loop**: Learn from approval/rejection patterns
4. **Cost Management**: Monitor and optimize token usage
5. **Graceful Degradation**: Always have a fallback strategy

This document provides the essential prompt engineering and error recovery knowledge needed to build a robust natural language planner that can reliably convert user requests into executable workflows.
