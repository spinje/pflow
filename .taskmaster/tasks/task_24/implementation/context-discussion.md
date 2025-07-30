# Task 24: WorkflowManager Context Discussion

## Key Findings from Context Gathering

### 1. Format Mismatch is Real and Critical

The investigation confirms a fundamental format incompatibility:

**Context Builder expects (metadata wrapper)**:
```json
{
  "name": "workflow-name",
  "description": "Description",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {...},
    "outputs": {...},
    "nodes": [...],
    "edges": [...]
  },
  "created_at": "2024-01-15T10:30:00Z",
  "version": "1.0.0"
}
```

**WorkflowExecutor expects (raw IR)**:
```json
{
  "ir_version": "0.1.0",
  "inputs": {...},
  "outputs": {...},
  "nodes": [...],
  "edges": [...]
}
```

This mismatch means workflows saved by Context Builder cannot be directly executed by WorkflowExecutor.

### 2. Scattered Implementations Confirmed

Found 4 different workflow loading implementations:
1. `context_builder._load_saved_workflows()` - expects metadata wrapper
2. `workflow_executor._load_workflow_file()` - expects raw IR
3. `cli.read_workflow_from_file()` - just reads text
4. No save functionality exists anywhere

### 3. Integration Points Identified

**Context Builder**:
- Lines 375, 506: Replace `_load_saved_workflows()` with `workflow_manager.list_all()`
- Function is private, blocking planner access

**CLI**:
- Line 468: After planner generates workflow, need to add save functionality
- No current save implementation

**WorkflowExecutor**:
- Currently only supports `workflow_ref` (file path)
- Needs enhancement to support `workflow_name` parameter
- Does NOT expand tilde (~) in paths

### 4. Task 21 Format Already Adopted

Context Builder already expects Task 21's format with inputs/outputs in the IR itself. No need to support the old format.

## Clarifying Questions

### 1. Workflow Name Validation

The spec mentions "snake_case, max 50 chars" for workflow names, but kebab-case is more natural for CLI usage. Should we:
- [ ] **Option A**: Enforce snake_case (Python convention)
- [ ] **Option B**: Auto-convert kebab-case to snake_case
- [x] **Option C**: Use kebab-case natively (e.g., "fix-issue")
- [ ] **Option D**: Allow both, normalize to one format

**Recommendation**: Option C - Kebab-case is more CLI-friendly and easier to type

### 2. Directory Creation Behavior

When ~/.pflow/workflows/ doesn't exist:
- [x] **Option A**: Create it automatically (matches Context Builder behavior)
- [ ] **Option B**: Fail with clear error message
- [ ] **Option C**: Ask user for confirmation

**Recommendation**: Option A - Consistent with existing behavior

### 3. Concurrent Access Handling

The spec notes concurrent access as an unknown. For MVP:
- [x] **Option A**: Document as known limitation, no locking
- [ ] **Option B**: Implement file locking
- [ ] **Option C**: Use atomic write operations

**Recommendation**: Option A - Keep it simple for MVP

## Design Decisions

### 1. WorkflowManager Location

- [x] **Option A**: Create new `src/pflow/core/workflow_manager.py`
- [ ] **Option B**: Add to existing `src/pflow/core/` module
- [ ] **Option C**: Create new `src/pflow/workflow/` package

**Recommendation**: Option A - As specified, follows existing patterns

### 2. Error Handling Strategy

For missing workflows:
- [x] **Option A**: Raise exceptions (WorkflowNotFoundError)
- [ ] **Option B**: Return None
- [ ] **Option C**: Return Result[T] type

**Recommendation**: Option A - Clear errors as spec requires

### 3. Metadata Preservation

For unknown fields in saved workflows:
- [x] **Option A**: Preserve all fields (current Context Builder behavior)
- [ ] **Option B**: Strip unknown fields
- [ ] **Option C**: Validate against strict schema

**Recommendation**: Option A - Forward compatibility

## Potential Risks

### 1. Breaking Context Builder

Risk: Changing from `_load_saved_workflows()` to WorkflowManager might break existing functionality.

**Mitigation**: Ensure WorkflowManager returns exact same format for `list_all()`.

### 2. Path Resolution in WorkflowExecutor

Risk: WorkflowExecutor resolves relative paths from parent workflow location. Adding name support might break this.

**Mitigation**: Keep both `workflow_ref` and `workflow_name` parameters, don't break existing behavior.

### 3. Format Migration

Risk: Existing workflow files might not match expected format.

**Mitigation**: Follow Context Builder's forgiving approach - skip invalid files with warnings.

## Recommended Approach

### Core Implementation Strategy

1. **Create WorkflowManager with dual-format support**:
   - `load()` returns metadata wrapper for Context Builder
   - `load_ir()` returns raw IR for WorkflowExecutor
   - `save()` wraps IR in metadata before storing

2. **Handle name validation**:
   - Accept kebab-case names (e.g., "fix-issue")
   - Enforce max length and valid characters for filenames
   - No auto-conversion needed

3. **Integration approach**:
   - Start with WorkflowManager core
   - Update Context Builder to use it
   - Add save to CLI after planner
   - Enhance WorkflowExecutor last

### API Design

```python
class WorkflowManager:
    def __init__(self, workflows_dir: Optional[Path] = None):
        """Initialize with custom dir or default ~/.pflow/workflows/"""

    def save(self, name: str, workflow_ir: dict, description: Optional[str] = None) -> str:
        """Save workflow with metadata wrapper, return path"""

    def load(self, name: str) -> dict:
        """Load full workflow with metadata wrapper"""

    def load_ir(self, name: str) -> dict:
        """Load just the IR for execution"""

    def list_all(self) -> List[dict]:
        """List all workflows with metadata"""

    def exists(self, name: str) -> bool:
        """Check if workflow exists"""

    def delete(self, name: str) -> None:
        """Delete workflow"""

    def get_path(self, name: str) -> str:
        """Get absolute path for workflow"""
```

## Next Steps

Once you confirm the design decisions above, I'll:
1. Create detailed implementation plan
2. Implement WorkflowManager with comprehensive tests
3. Integrate with existing components
4. Ensure all tests pass

Please review the options marked with checkboxes and confirm if my recommendations align with your vision for the system.
