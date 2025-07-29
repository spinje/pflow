# Workflow Management Architecture Analysis

## Current State: Scattered Responsibilities

Currently, workflow management is fragmented across components:

1. **Context Builder**: Loads workflows from `~/.pflow/workflows/` for discovery
2. **CLI**: Should save workflows (not implemented)
3. **WorkflowExecutor**: Loads workflows by file path for execution
4. **Planner**: Needs to reference workflows but can't resolve names to paths

## The Missing Piece: Workflow Management Service

A centralized service could handle the entire workflow lifecycle:

```python
class WorkflowManager:
    """Centralized workflow management service."""

    def save(self, name: str, workflow_ir: dict) -> str:
        """Save workflow to disk, return path."""
        # Validates name uniqueness
        # Adds metadata (created_at, version, etc.)
        # Saves to ~/.pflow/workflows/{name}.json

    def load(self, name: str) -> dict:
        """Load workflow by name."""
        # Resolves name to path
        # Loads and validates JSON
        # Returns workflow IR + metadata

    def get_path(self, name: str) -> str:
        """Get file path for workflow name."""
        # For WorkflowExecutor compatibility

    def list_all(self) -> List[WorkflowMetadata]:
        """List all saved workflows."""
        # For context builder

    def exists(self, name: str) -> bool:
        """Check if workflow exists."""

    def delete(self, name: str) -> None:
        """Delete a workflow."""
```

## Integration Points

### 1. CLI Layer (After Planner)
```python
# After user approves generated workflow
if user_approves:
    workflow_manager = WorkflowManager()
    suggested_name = planner_output["workflow_metadata"]["suggested_name"]

    if click.confirm(f"Save as '{suggested_name}'?"):
        try:
            path = workflow_manager.save(suggested_name, workflow_ir)
            click.echo(f"Saved to {path}")
        except WorkflowExistsError:
            # Handle name conflicts
```

### 2. Context Builder
```python
def build_discovery_context():
    workflow_manager = WorkflowManager()
    workflows = workflow_manager.list_all()  # Instead of _load_saved_workflows()
    # Format for LLM consumption
```

### 3. WorkflowExecutor Enhancement
```python
# Add name resolution support
if "workflow_name" in params:
    workflow_manager = WorkflowManager()
    params["workflow_ref"] = workflow_manager.get_path(params["workflow_name"])
```

### 4. Planner Generated IR
```python
# Planner can now use names!
{
    "type": "workflow",
    "params": {
        "workflow_name": "fix-issue",  # Natural name reference
        "param_mapping": {...}
    }
}
```

## Benefits of Centralization

1. **Single Source of Truth**: All workflow operations go through one service
2. **Consistent Validation**: Name uniqueness, format validation in one place
3. **Future Features**: Easy to add versioning, tagging, search
4. **Clean Architecture**: Each component has clear responsibilities
5. **Name-Based References**: Natural API throughout the system

## Implementation Considerations

### Option 1: Minimal WorkflowManager
- Just name↔path resolution
- Save/load/list operations
- No complex features

### Option 2: Full Workflow Registry
- Metadata tracking (created, updated, tags)
- Version management
- Dependency tracking
- Search capabilities

### Option 3: Hybrid Approach
- Start with minimal manager
- Keep door open for registry features
- Use consistent API that can grow

## Design Questions

1. **Should WorkflowManager be a singleton or instantiated?**
   - Singleton: Global state, easier access
   - Instance: More testable, explicit dependencies

2. **Where should it live in the codebase?**
   - `src/pflow/workflow/manager.py`?
   - `src/pflow/storage/workflows.py`?
   - `src/pflow/registry/workflows.py`?

3. **Should it handle workflow validation?**
   - Just storage or also semantic validation?
   - Duplicate workflow detection?
   - Dependency cycle detection?

4. **How to handle concurrent access?**
   - File locking for saves?
   - Read consistency?

## Recommendation

Implement a minimal WorkflowManager that:
1. Centralizes all workflow file operations
2. Provides name-based API
3. Handles save/load/list/resolve operations
4. Can be enhanced later without breaking changes

This would:
- Unblock the planner (name-based references)
- Implement missing save functionality
- Clean up scattered workflow logic
- Provide foundation for future features
