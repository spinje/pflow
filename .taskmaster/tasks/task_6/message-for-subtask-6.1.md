# Message for Agent Implementing Subtask 6.1

## Critical Context for Success

Hello! You're about to implement the JSON IR schema, which is a foundational component for pflow. Here are the key insights from my task analysis:

### 1. Schema Design Decisions (Already Made)
The research files contain critical decisions that have already been analyzed and decided:
- Use standard JSON Schema format (not Pydantic models)
- Use 'type' field for nodes (not 'registry_id' as shown in some docs)
- Make start_node optional with default to first node
- Include action field in edges with "default" as default value
- Keep template variables as simple strings in params (no special handling in MVP)

### 2. Key Implementation Notes
- The IR is pure data, not code - it gets compiled TO pocketflow objects
- Nodes are stored as an array with 'id' field (not as dict keys)
- Follow the "test-as-you-go" pattern - write tests alongside implementation
- Focus on clear validation error messages from the start

### 3. Documentation Conflicts to Be Aware Of
- Task description uses 'type' but docs show 'registry_id' - we're using 'type' per the decision
- Some docs show complex envelope structure - keep it minimal for MVP
- Template variable resolution is deferred to runtime, not part of schema

### 4. Resources You Should Read
- The project context briefing has all the architectural understanding
- The research files have specific implementation patterns (especially pocketflow-patterns.md)
- Check `docs/core-concepts/schemas.md` for the full vision (but simplify for MVP)

### 5. Testing Focus
- Start with the simplest possible valid IR (single node, no edges)
- Build up to complex examples incrementally
- Each new schema constraint should have a corresponding test

Good luck! The schema you create will be the foundation for all workflow representation in pflow.

## Quick Reference of Decisions Made

```python
# Minimal schema structure decided:
{
    "ir_version": "0.1.0",  # Minimal versioning
    "nodes": [...],         # Required array
    "edges": [...],         # Optional array (default [])
    "start_node": "...",    # Optional (default to nodes[0].id)
    "mappings": {...}       # Optional (default {})
}

# Node structure:
{
    "id": "n1",            # Required
    "type": "read-file",   # Required (NOT registry_id)
    "params": {...}        # Optional (default {})
}

# Edge structure:
{
    "from": "n1",          # Required
    "to": "n2",            # Required
    "action": "default"    # Optional (default "default")
}
```

Do NOT start the implementation yet. The user will ask you to do so after you have read this message and answered that you are ready to start.
