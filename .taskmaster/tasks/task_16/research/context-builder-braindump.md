# Task 16: Planning Context Builder - Implementation Braindump

## Overview

The planning context builder is a **critical bridge component** that transforms raw node metadata from Task 7 into LLM-optimized context for Task 17. Think of it as a "menu generator" that presents available nodes to the AI planner in the most effective format for intelligent workflow composition.

## Core Purpose

**What it does**: Takes registry metadata and formats it into structured text that LLMs can understand and reason about effectively.

**Why it matters**: The quality of this context directly impacts the planner's ability to:
- Select appropriate nodes for workflows
- Understand node compatibility
- Make intelligent chaining decisions
- Avoid invalid combinations

## Key Design Decisions

### 1. Text-Based, Not JSON

While it might be tempting to pass JSON to the LLM, **structured text works better** for reasoning:
- LLMs are trained on natural language patterns
- Markdown-like formatting aids comprehension
- Easier to include examples and explanations
- More token-efficient for large node libraries

### 2. Progressive Detail Levels

Not all nodes need the same level of detail in the context:
- **Common nodes** (read-file, write-file): Brief descriptions
- **Complex nodes** (claude-code): Detailed interface info
- **Platform nodes** (github-*): Group by category

### 3. Interface-First Design

The most important information for the planner is:
1. What data nodes read (inputs)
2. What data nodes produce (outputs)
3. How nodes connect (shared store keys)

Parameters are secondary - they're for configuration, not flow logic.

## Implementation Architecture

```python
class PlannerContextBuilder:
    """Format node metadata for LLM-based workflow planning."""

    def __init__(self, registry_metadata: Dict[str, Any]):
        self.registry = registry_metadata
        self.metadata_cache = {}

    def build_context(self,
                     available_nodes: List[str] = None,
                     categories: List[str] = None,
                     include_examples: bool = True) -> str:
        """Build LLM-optimized context from node metadata."""
        # Implementation details below
```

## Context Format Design

### Recommended Format (Structured Markdown)

```markdown
# Available pflow Nodes

## File Operations

**read-file**: Read content from a file and add line numbers
- Reads: shared["file_path"] (required), shared["encoding"] (optional)
- Writes: shared["content"], shared["error"]
- Actions: default (success), error (failure)

**write-file**: Write content to a file
- Reads: shared["content"] (required), shared["file_path"] (required)
- Writes: shared["written"], shared["error"]
- Actions: default, error

## GitHub Operations

**github-get-issue**: Retrieve GitHub issue details
- Reads: shared["issue_number"], shared["repo"]
- Writes: shared["issue"], shared["issue_title"], shared["issue_body"]
- Actions: default, not_found

## Text Processing

**llm**: General-purpose text processing with LLM
- Reads: shared["prompt"] (required)
- Writes: shared["response"]
- Actions: default, error
- Note: This is the primary node for all AI text tasks
```

### Why This Format Works

1. **Hierarchical Organization**: Categories make it easy to find relevant nodes
2. **Consistent Structure**: Each node follows the same pattern
3. **Natural Key Names**: `shared["file_path"]` is self-documenting
4. **Action Context**: Shows possible outcomes for conditional flows
5. **Concise but Complete**: All essential info without overwhelming detail

## Critical Implementation Considerations

### 1. Node Ordering Strategy

Present nodes in order of likely usage:
1. Common operations (file I/O)
2. Platform integrations (GitHub, Git)
3. Processing nodes (LLM, data transformation)
4. Specialized nodes (claude-code)

### 2. Shared Store Key Patterns

Emphasize natural naming patterns:
```
File operations use: file_path, content, encoding
GitHub operations use: repo, issue, pr, commit
Git operations use: branch, message, commit_hash
LLM operations use: prompt, response
```

This helps the planner infer connections without explicit mapping.

### 3. Parameter Handling

**Don't over-emphasize parameters** in the context. The planner should focus on data flow (shared store), not node configuration:

```markdown
# Good (focuses on data flow)
**read-file**: Read content from a file
- Reads: shared["file_path"]
- Writes: shared["content"]

# Less Good (clutters with params)
**read-file**: Read content from a file
- Reads: shared["file_path"]
- Writes: shared["content"]
- Params: encoding (default: utf-8), strip_whitespace (default: false)
```

### 4. Handling Missing Metadata

When nodes have incomplete metadata from Task 7:
- Use sensible defaults
- Clearly mark as "metadata incomplete"
- Don't exclude from context (planner might still need them)

## Performance Optimization

### 1. Context Size Management

For large node libraries:
- Implement category filtering
- Use relevance scoring based on user query
- Cache formatted context between calls
- Consider token limits (aim for <2000 tokens base context)

### 2. Smart Truncation

If context gets too large:
1. Keep all input/output info (critical for chaining)
2. Truncate descriptions first
3. Remove examples next
4. Never remove interface data

### 3. Caching Strategy

```python
def build_context(self, cache_key: str = None):
    if cache_key and cache_key in self.context_cache:
        return self.context_cache[cache_key]

    context = self._build_context_internal()

    if cache_key:
        self.context_cache[cache_key] = context

    return context
```

## Integration Points

### 1. With Task 7 (Metadata Extractor)

The context builder consumes output from Task 7:
```python
# From Task 7
metadata = {
    'description': 'Read content from a file',
    'inputs': ['file_path', 'encoding'],
    'outputs': ['content', 'error'],
    'params': ['file_path', 'encoding'],
    'actions': ['default', 'error']
}

# Context builder transforms to:
"**read-file**: Read content from a file\n" +
"- Reads: shared[\"file_path\"], shared[\"encoding\"]\n" +
"- Writes: shared[\"content\"], shared[\"error\"]\n"
```

### 2. With Task 17 (Natural Language Planner)

The planner will use this context in prompts:
```python
planner_prompt = f"""
{context_builder.build_context()}

User request: {user_query}

Generate a workflow using the available nodes above.
"""
```

### 3. With Task 5 (Registry)

Pull from registry's stored metadata:
```python
def load_registry_metadata(self):
    registry = Registry()
    nodes = registry.list_all_with_metadata()
    return {node['name']: node['metadata'] for node in nodes}
```

## Common Pitfalls to Avoid

### 1. Over-Engineering the Format

**Don't**:
- Create complex hierarchical structures
- Use custom DSLs or notation
- Try to encode all possible relationships

**Do**:
- Keep it simple and readable
- Use familiar markdown patterns
- Let the LLM infer relationships

### 2. Including Code Examples

**Don't**:
```markdown
**read-file**: Read content from a file
Example:
  node = ReadFileNode()
  node.set_params({"file_path": "data.txt"})
  result = node.run(shared)
```

**Do**:
```markdown
**read-file**: Read content from a file
- Reads: shared["file_path"]
- Writes: shared["content"]
```

The planner doesn't need implementation details, just interfaces.

### 3. Assuming Perfect Metadata

Real nodes might have:
- Missing docstrings
- Incomplete Interface sections
- Inconsistent formatting

Build defensively:
```python
def format_node(self, name: str, metadata: dict) -> str:
    description = metadata.get('description', f'Node: {name}')
    inputs = metadata.get('inputs', [])
    outputs = metadata.get('outputs', [])

    # Always provide something useful
    if not inputs and not outputs:
        return f"**{name}**: {description} (interface not documented)\n"
```

## Testing Strategy

### 1. Unit Tests

Test individual formatting functions:
```python
def test_format_single_node():
    metadata = {
        'description': 'Test node',
        'inputs': ['input1', 'input2'],
        'outputs': ['output1']
    }
    result = builder.format_node('test-node', metadata)
    assert 'shared["input1"]' in result
    assert 'shared["output1"]' in result
```

### 2. Integration Tests

Test with real registry data:
```python
def test_build_context_with_registry():
    builder = PlannerContextBuilder.from_registry()
    context = builder.build_context()

    # Verify key nodes are present
    assert 'read-file' in context
    assert 'github-get-issue' in context
    assert 'llm' in context
```

### 3. LLM Compatibility Tests

Actually test with an LLM to ensure the format works:
```python
def test_context_enables_planning():
    context = builder.build_context()
    test_query = "read a file and summarize it"

    # Use a small model to verify context is usable
    response = llm.generate(f"{context}\n\nPlan: {test_query}")

    # Should mention read-file and llm nodes
    assert 'read-file' in response
    assert 'llm' in response
```

## Examples of Good Context Output

### Minimal but Effective
```markdown
# Available Nodes

**read-file**: Read file content
- Reads: shared["file_path"]
- Writes: shared["content"]

**llm**: Process text with AI
- Reads: shared["prompt"]
- Writes: shared["response"]

**write-file**: Write content to file
- Reads: shared["content"], shared["file_path"]
- Writes: shared["written"]
```

### Detailed with Categories
```markdown
# Available pflow Nodes

## File Operations
Nodes for reading and writing files.

**read-file**: Read content from a file and add line numbers
- Reads: shared["file_path"] (required), shared["encoding"] (optional, default: utf-8)
- Writes: shared["content"] on success, shared["error"] on failure
- Actions: default (success), error (file not found or read error)

## AI Processing
Nodes for AI-powered text processing.

**llm**: General-purpose LLM for any text task
- Reads: shared["prompt"] (required)
- Writes: shared["response"]
- Actions: default
- Note: Use for analysis, generation, transformation, Q&A
```

## Future Enhancements (Post-MVP)

### 1. Query-Aware Context

Filter nodes based on user query:
```python
def build_context(self, user_query: str = None):
    if user_query and 'github' in user_query.lower():
        # Prioritize GitHub nodes
        relevant_nodes = self.filter_by_category('github')
```

### 2. Capability Summaries

Add high-level capability descriptions:
```markdown
## Capabilities Overview
- File Operations: Read, write, copy, move, delete files
- GitHub Integration: Issues, PRs, commits, releases
- AI Processing: Text analysis, generation, transformation
- Git Operations: Commit, push, branch, merge
```

### 3. Connection Hints

Explicitly show common node combinations:
```markdown
## Common Patterns
- File → LLM → File: Read, process, and save
- GitHub → LLM → GitHub: Analyze issue and create PR
- Git → GitHub: Commit changes and create PR
```

## Decision Points for Implementation

### 1. Static vs Dynamic Context

**Static**: Pre-generate context for all nodes
- Pros: Fast, cacheable
- Cons: Can't adapt to query

**Dynamic**: Generate based on query
- Pros: Relevant, concise
- Cons: Slower, more complex

**Recommendation**: Start static, add dynamic in v2.

### 2. Format Versioning

The context format might evolve. Consider:
```python
def build_context(self, format_version: str = "1.0"):
    if format_version == "1.0":
        return self._build_v1_context()
    # Future versions...
```

### 3. Metadata Completeness Requirements

How complete must metadata be to include a node?
- Minimum: Has description
- Recommended: Has inputs/outputs
- Ideal: Full interface documentation

**Recommendation**: Include all nodes, mark incomplete ones.

## Code Snippets for Quick Start

### Basic Builder Structure
```python
from typing import Dict, List, Any, Optional

class PlannerContextBuilder:
    def __init__(self, registry_metadata: Dict[str, Dict[str, Any]]):
        self.registry = registry_metadata
        self.categories = self._organize_by_category()

    def build_context(self,
                     include_categories: Optional[List[str]] = None,
                     max_tokens: int = 2000) -> str:
        """Build formatted context for LLM consumption."""
        lines = ["# Available pflow Nodes\n"]

        for category, nodes in self.categories.items():
            if include_categories and category not in include_categories:
                continue

            lines.append(f"\n## {category}\n")

            for node_name, metadata in nodes.items():
                lines.append(self._format_node(node_name, metadata))

        return "\n".join(lines)

    def _format_node(self, name: str, metadata: Dict[str, Any]) -> str:
        """Format a single node's metadata."""
        desc = metadata.get('description', 'No description')

        parts = [f"**{name}**: {desc}"]

        # Format inputs
        inputs = metadata.get('inputs', [])
        if inputs:
            input_str = ", ".join([f'shared["{i}"]' for i in inputs])
            parts.append(f"- Reads: {input_str}")

        # Format outputs
        outputs = metadata.get('outputs', [])
        if outputs:
            output_str = ", ".join([f'shared["{o}"]' for o in outputs])
            parts.append(f"- Writes: {output_str}")

        # Format actions if not default
        actions = metadata.get('actions', ['default'])
        if actions != ['default']:
            parts.append(f"- Actions: {', '.join(actions)}")

        return "\n".join(parts) + "\n"
```

### Category Organization
```python
def _organize_by_category(self) -> Dict[str, Dict[str, Any]]:
    """Organize nodes by category based on naming patterns."""
    categories = {
        'File Operations': {},
        'GitHub Operations': {},
        'Git Operations': {},
        'AI Processing': {},
        'CI/Testing': {},
        'Other': {}
    }

    for node_name, metadata in self.registry.items():
        if node_name.startswith('read-') or node_name.startswith('write-'):
            categories['File Operations'][node_name] = metadata
        elif 'github' in node_name:
            categories['GitHub Operations'][node_name] = metadata
        elif 'git' in node_name:
            categories['Git Operations'][node_name] = metadata
        elif node_name == 'llm' or 'claude' in node_name:
            categories['AI Processing'][node_name] = metadata
        elif 'test' in node_name or 'ci' in node_name:
            categories['CI/Testing'][node_name] = metadata
        else:
            categories['Other'][node_name] = metadata

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}
```

## Final Thoughts

The context builder is deceptively simple but critically important. It's the lens through which the AI planner sees available capabilities. A well-formatted context leads to better workflow generation, while a poor context leads to confusion and errors.

Key takeaways:
1. **Simplicity wins** - Clear, consistent formatting beats complex schemas
2. **Interface-first** - Focus on inputs/outputs, not implementation
3. **Natural patterns** - Use intuitive shared store key names
4. **Progressive detail** - Start minimal, add detail where needed
5. **Test with LLMs** - Verify the format actually helps planning

Remember: You're building a bridge between static metadata and dynamic AI reasoning. Make it sturdy, simple, and effective.

## References

- Task 7 output format: See `.taskmaster/tasks/task_7/7_handover.md`
- Planner requirements: See `docs/features/planner.md`
- Shared store patterns: See `docs/core-concepts/shared-store.md`
- Node examples: See `src/pflow/nodes/file/*.py` for docstring formats

---

*This braindump reflects the current understanding as of Task 16 planning. Update as implementation reveals new insights.*
