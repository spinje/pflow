# Workflow Manager Design - Importance 5/5

The investigation reveals that workflow management is scattered across the codebase with no central authority. This affects Task 17's ability to reference workflows and the overall system's workflow lifecycle management.

## Context:

### Current Scattered Functionality
- **Loading**: 4 different implementations across components
- **Saving**: Not implemented anywhere (critical gap!)
- **Validation**: Multiple validators but no central coordination
- **Reference Resolution**: No name-to-path mapping exists

### The Architectural Gap
Every component handles workflows differently:
- Context builder loads from disk for discovery
- CLI reads files for execution
- WorkflowExecutor loads by path
- Planner needs names but gets paths

This fragmentation causes:
1. Code duplication
2. Inconsistent behavior
3. Missing features (save!)
4. The planner's reference problem

## Options:

- [x] **Option A: Create Minimal WorkflowManager**
  ```python
  class WorkflowManager:
      def save(name: str, workflow_ir: dict) -> str
      def load(name: str) -> dict
      def get_path(name: str) -> str
      def list_all() -> List[WorkflowMetadata]
      def exists(name: str) -> bool
  ```
  - Pros: Solves immediate needs, clean API, extensible
  - Cons: New component to implement and test

- [ ] **Option B: Extend Existing Components**
  Add workflow methods to Registry or create WorkflowRegistry
  - Pros: Follows existing patterns
  - Cons: Registry is for nodes, mixing concerns

- [ ] **Option C: Quick Fixes Only**
  Just add save to CLI, patch WorkflowExecutor for names
  - Pros: Minimal changes
  - Cons: Perpetuates scattered design, technical debt

- [ ] **Option D: Full Workflow Registry Service**
  Complete workflow lifecycle management with versioning, search, etc.
  - Pros: Future-proof, powerful
  - Cons: Over-engineering for MVP, complex

**Recommendation**: Option A - Create a minimal WorkflowManager. This provides a clean foundation that solves immediate needs while allowing future enhancement.

## Implementation Location:

Where should WorkflowManager live?

- [x] `src/pflow/core/workflow_manager.py` - Core functionality
- [ ] `src/pflow/registry/workflow_manager.py` - Near registry
- [ ] `src/pflow/storage/workflows.py` - Storage focus
- [ ] `src/pflow/workflow/manager.py` - New package

## Integration Plan:

### Phase 1: Core Implementation
1. Create WorkflowManager with basic operations
2. Implement save functionality for CLI
3. Replace context builder's loading with manager
4. Add name resolution to WorkflowExecutor

### Phase 2: Task 17 Integration
1. Planner uses workflow names in generated IR
2. WorkflowManager resolves names to paths
3. Clean separation of concerns

### Phase 3: Future Enhancements
- Workflow versioning
- Tagging and search
- Import/export
- Dependency tracking

## Critical Benefits:

1. **Unblocks Task 17**: Natural name-based workflow references
2. **Implements Save**: Critical missing feature for "Plan Once, Run Forever"
3. **Consolidates Logic**: Single source of truth for workflows
4. **Enables Growth**: Clean API that can be extended

## API Design:

```python
# For Task 17 planner
workflow = workflow_manager.load("fix-issue")

# For CLI saving
workflow_manager.save("fix-issue", workflow_ir)

# For WorkflowExecutor
if "workflow_name" in params:
    params["workflow_ref"] = workflow_manager.get_path(params["workflow_name"])

# For context builder
workflows = workflow_manager.list_all()
```

This design provides a clean, minimal API that solves immediate needs while leaving room for future enhancements.
