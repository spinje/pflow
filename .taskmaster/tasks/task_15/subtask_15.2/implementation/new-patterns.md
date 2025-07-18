# Patterns Discovered

## Pattern: Optional Dependency Injection
**Context**: When you need to use an external service/singleton that may not always be available
**Solution**: Accept the dependency as an optional parameter with a fallback to load it if not provided
**Why it works**: Provides flexibility for testing and different usage contexts
**When to use**: When building functions that depend on external services or registries
**Example**:
```python
def build_discovery_context(
    node_ids: Optional[list[str]] = None,
    workflow_names: Optional[list[str]] = None,
    registry_metadata: Optional[dict[str, dict[str, Any]]] = None
) -> str:
    # Get registry metadata if not provided
    if registry_metadata is None:
        from pflow.registry import Registry
        registry = Registry()
        registry_metadata = registry.load()
```

## Pattern: Structured Error Return
**Context**: When you need to handle missing/invalid components in a way that enables recovery
**Solution**: Return a structured error dict instead of raising exceptions or returning partial results
**Why it works**: Caller can inspect what's missing and retry with corrections
**When to use**: When building validation or planning functions where recovery is possible
**Example**:
```python
if missing_nodes or missing_workflows:
    return {
        "error": error_msg.strip(),
        "missing_nodes": missing_nodes,
        "missing_workflows": missing_workflows,
    }
```

## Pattern: Combined Format Display for LLM
**Context**: When you need to show complex data structures to an LLM for processing
**Solution**: Provide both JSON representation and flattened path list
**Why it works**: LLMs can use JSON for understanding structure and paths for direct copying
**When to use**: When building contexts for LLM consumption that involve nested data
**Example**:
```markdown
Structure (JSON format):
```json
{
  "user_data": {
    "id": "str",
    "profile": {
      "name": "str"
    }
  }
}
```

Available paths:
- user_data.id (str) - User ID
- user_data.profile.name (str) - Full name
```
