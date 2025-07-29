# Context Builder Findings Summary

## Current State

The context builder provides **almost everything** the planner needs, with only minor gaps:

### What Works Well ✅

1. **Discovery Phase Support**
   - `build_discovery_context()` shows all workflows with names/descriptions
   - Perfect format for LLM to browse and select
   - Includes both nodes and workflows in unified format

2. **Planning Phase Support**
   - `build_planning_context()` provides detailed interfaces
   - Shows inputs, outputs, parameters for selected components
   - Handles both nodes and workflows

3. **Workflow Loading Infrastructure**
   - `_load_saved_workflows()` correctly loads all workflow metadata
   - Robust error handling, validation, and logging
   - Returns exactly the data structure the planner needs

### Critical Gaps ❌

1. **No Public Access to Workflow Objects**
   - After LLM selects "fix-issue", no way to get its metadata
   - `_load_saved_workflows()` is private (underscore prefix)
   - Planner needs the full workflow IR to return to CLI

2. **No Single Workflow Getter**
   - Need to load all workflows to get one
   - Inefficient for Path A (reuse existing workflow)

3. **Workflow Output Structure**
   - Nodes show output structure for template validation
   - Workflows don't (minor issue, can be deferred)

## Alternative Patterns Found

1. **WorkflowExecutor Pattern**
   - Has `_load_workflow_file()` but it's also private
   - Designed for runtime execution, not discovery
   - Loads single file by path, not by name

2. **No Other Public APIs**
   - Context builder is the only module that loads from `~/.pflow/workflows/`
   - No existing public API for structured workflow access

## Recommended Solution

Add 2 minimal public functions to context_builder.py:

```python
def get_workflow_metadata(workflow_name: str) -> Optional[dict]:
    """Get metadata for a specific workflow by name.

    Returns workflow dict with name, description, inputs, outputs, ir.
    Returns None if workflow not found.
    """
    workflows = _load_saved_workflows()
    return next((w for w in workflows if w["name"] == workflow_name), None)

def get_all_workflows_metadata() -> list[dict]:
    """Get all saved workflow metadata.

    Public wrapper for _load_saved_workflows().
    """
    return _load_saved_workflows()
```

## Why This Matters

Without these methods, the planner would have to:
1. **Use private methods** - Fragile, violates encapsulation
2. **Parse markdown** - Complex, error-prone, fragile
3. **Duplicate loading logic** - Maintenance burden, inconsistency risk

The context builder already has all the logic. We just need to expose it properly.

## Usage in Planner

With these additions:

```python
# WorkflowDiscoveryNode
discovery_context = build_discovery_context()  # For LLM
selected = llm.select(discovery_context, user_input)
if selected == "fix-issue":
    workflow = get_workflow_metadata("fix-issue")  # NEW!
    return {"found_workflow": workflow}

# ParameterMappingNode
workflow = shared["found_workflow"]
required_inputs = workflow["inputs"]  # Direct access to structure
```

This enables clean separation:
- Markdown for LLM consumption
- Structured data for planner logic
- No parsing or private method access needed
