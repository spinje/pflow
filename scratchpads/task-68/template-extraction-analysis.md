# Understanding RuntimeValidationNode's Template Extraction

## What It Does

The sophisticated template extraction in RuntimeValidationNode provides **intelligent error context** when workflows fail. Instead of just saying "template not found", it tells you exactly what IS available.

## The Key Innovation

When a workflow fails with `${http.response.username}` not found, RuntimeValidationNode doesn't just report the error. It:

1. **Navigates to the parent level** (`http.response`)
2. **Lists available fields** at that level (e.g., `["login", "bio", "email"]`)
3. **Creates rich error context**:
```json
{
    "source": "template",
    "node_id": "http",
    "category": "missing_template_path",
    "attempted": "${http.response.username}",
    "available": ["login", "bio", "email"],
    "message": "Template path '${http.response.username}' not found. Available at 'http.response': login, bio, email",
    "fixable": true
}
```

## Why This Is Brilliant for Repair

This gives the RepairGeneratorNode exactly what it needs to fix the workflow:
- **What failed**: `${http.response.username}`
- **Why it failed**: Field doesn't exist
- **How to fix it**: Use `login` instead of `username`

The LLM can immediately understand: "Oh, GitHub changed their API from 'username' to 'login', I'll update the template."

## The Technical Implementation

### 1. Template Extraction (`_extract_templates_from_ir`)
- Uses `TemplateValidator._extract_all_templates()` to find ALL template references
- Handles nested structures and array notation (`${items[0].name}`)

### 2. Navigation (`_navigate_shared_store`)
- Splits template path into node_id and field_path
- Recursively navigates the shared store
- Handles array indexing (`[0]`, `[1]`, etc.)

### 3. Context Building (`_get_available_paths`)
- Given a partial path, returns available keys at that level
- For dicts: returns keys
- For arrays: returns `["[0]", "[1]", "[2]"]`

### 4. Error Enrichment (`_collect_missing_template_errors`)
- For each missing template, builds a detailed error dict
- Includes both what was attempted AND what's available
- Marks as "fixable" to indicate repair is possible

## Should We Port This to WorkflowExecutorNode?

**My Recommendation: YES, but simplified for MVP**

Here's why:
1. **Critical for effective repair** - Without knowing what fields ARE available, the LLM is guessing blind
2. **Already proven to work** - This code has been tested in RuntimeValidationNode
3. **Not that complex** - We can port the core logic without all the edge cases

**Simplified MVP Version**:
```python
def _analyze_partial_execution(self, workflow_ir: dict, shared_after: dict) -> dict:
    """Analyze partial execution for template mismatches."""
    from pflow.runtime.template_validator import TemplateValidator

    templates = TemplateValidator._extract_all_templates(workflow_ir)
    missing_contexts = []

    for template in templates:
        if not self._template_exists(template, shared_after):
            # Extract node_id and field from template
            parts = template.split(".", 1)
            if len(parts) == 2:
                node_id, field_path = parts
                # Get what's actually available at parent level
                available = self._get_available_fields(shared_after, node_id)
                missing_contexts.append({
                    "template": template,
                    "available_fields": available
                })

    return {"missing_templates": missing_contexts} if missing_contexts else None
```

This gives repair the context it needs without the full complexity.

---

# My Recommendations for Remaining Questions

## 2. Model Selection for RepairGeneratorNode

**Recommendation: Use a faster, cheaper model for repair**

- **Primary choice**: `anthropic/claude-3-haiku` - Fast, cheap, good enough for repairs
- **Fallback option**: `anthropic/claude-3-5-sonnet` - If Haiku fails
- **Rationale**:
  - Repair is simpler than generation (fixing vs creating)
  - We want fast iteration (3 attempts possible)
  - Cost matters when doing multiple attempts
  - Haiku is sufficient for template fixes and parameter adjustments

## 3. Caching in Shared Store vs WorkflowExecutorService

**Recommendation: Use shared store for cache storage**

This is the PocketFlow way and most flexible:

```python
class WorkflowExecutorService:
    def execute_workflow(self, workflow_ir, params, shared_store=None):
        if shared_store is None:
            shared_store = {}

        # Check for existing cache in shared store
        cache = shared_store.get("__execution_cache__")
        if cache is None:
            cache = NodeExecutionCache()
            shared_store["__execution_cache__"] = cache

        # Use cache during execution...
```

Benefits:
- Follows PocketFlow pattern (shared store for all data)
- Cache naturally persists across repair attempts
- Can be inspected/debugged via shared store
- Repair nodes can access cache directly if needed

The unified repair flow then becomes:
```python
def execute_with_auto_repair(workflow_ir, params):
    shared = {}  # Single shared store for entire repair session

    # First execution
    executor = WorkflowExecutorService()
    result = executor.execute_workflow(workflow_ir, params, shared)
    # Cache is now in shared["__execution_cache__"]

    if not result.success:
        # Repair attempts use same shared store
        for attempt in range(3):
            repaired_ir = repair_workflow(workflow_ir, result.errors)
            # Same shared store = same cache!
            result = executor.execute_workflow(repaired_ir, params, shared)
            if result.success:
                break

    return result
```

## Summary of Decisions

1. **Template extraction**: Port simplified version to WorkflowExecutorNode for rich error context
2. **Model for repair**: Use claude-3-haiku (fast/cheap) with sonnet fallback
3. **Cache storage**: Use shared store with key `__execution_cache__`
4. **Test strategy**: Mock at llm.get_model() level (established pattern)

This gives us a clean, PocketFlow-aligned implementation that reuses proven patterns.