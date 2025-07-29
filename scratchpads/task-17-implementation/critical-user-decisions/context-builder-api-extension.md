# Context Builder API Extension Decision - Importance 4/5

The planner needs structured workflow data access that the context builder currently doesn't provide through its public API. This blocks task 17 implementation.

## Context:

The context builder provides markdown-formatted discovery and planning contexts for LLM consumption. However, the planner also needs programmatic access to workflow metadata after the LLM makes selections.

Currently:
- `build_discovery_context()` returns markdown string showing workflows
- `_load_saved_workflows()` loads the actual workflow data but is private
- No public way to get workflow IR after LLM selects one

The planner's WorkflowDiscoveryNode needs to:
1. Show workflows to LLM (✅ supported via discovery context)
2. Get selected workflow's full data (❌ no public method)
3. Return workflow IR to CLI (❌ blocked by #2)

## Options:

- [x] **Option A: Add minimal public methods to context_builder.py**
  ```python
  def get_workflow_metadata(workflow_name: str) -> Optional[dict]:
      """Get metadata for a specific workflow by name."""

  def get_all_workflows_metadata() -> List[dict]:
      """Get all saved workflow metadata."""
  ```
  - Pros: Clean API, follows existing patterns, minimal changes
  - Cons: Modifies existing module (but it's an extension, not breaking change)

- [ ] **Option B: Have planner access private methods**
  ```python
  from pflow.planning.context_builder import _load_saved_workflows
  workflows = _load_saved_workflows()  # Access private method
  ```
  - Pros: No changes needed to context builder
  - Cons: Fragile coupling to internals, violates encapsulation, bad practice

- [ ] **Option C: Create separate workflow loader module**
  ```python
  # New file: src/pflow/planning/workflow_loader.py
  def load_workflow_metadata(name: str) -> dict:
      # Duplicate workflow loading logic
  ```
  - Pros: Doesn't touch context builder
  - Cons: Code duplication, maintenance burden, inconsistency risk

- [ ] **Option D: Parse markdown to extract data**
  ```python
  # Parse the markdown returned by build_discovery_context()
  workflow_data = parse_markdown_to_extract_workflow_info(markdown)
  ```
  - Pros: No API changes needed
  - Cons: Extremely fragile, complex parsing, error-prone

**Recommendation**: Option A - Add minimal public methods. This is the cleanest approach that maintains proper encapsulation while enabling the planner to function. The context builder already loads this data; we're just exposing it through a proper API.

## Implementation Impact:

With Option A, the planner can cleanly separate concerns:
```python
# 1. Get markdown for LLM
discovery_md = build_discovery_context()

# 2. LLM selects workflow
selected = llm.select(discovery_md)

# 3. Get structured data
if selected == "fix-issue":
    workflow = get_workflow_metadata("fix-issue")  # New public method
    return {"workflow_ir": workflow["ir"], ...}
```

This unblocks task 17 implementation with minimal, backwards-compatible changes.
