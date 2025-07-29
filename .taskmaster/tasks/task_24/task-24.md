# Task 24: Implement Workflow Manager

## ID
24

## Title
Implement Workflow Manager

## Description
Create a centralized service that manages the complete workflow lifecycle including saving, loading, discovery, and name resolution. This service consolidates scattered workflow management logic across the codebase and bridges the format gap between how workflows are stored (with metadata wrapper) versus how they're executed (raw IR only). The WorkflowManager enables the "Plan Once, Run Forever" philosophy by finally implementing the missing save functionality.

## Status
not started

## Dependencies
- Task 21: Implement Workflow Input Declaration - WorkflowManager leverages the new input/output declarations in the IR for interface-based discovery and validation. The format changes from Task 21 (inputs/outputs in IR) must be handled correctly.

## Priority
high

## Details
The WorkflowManager addresses critical architectural gaps discovered during Task 17 (Natural Language Planner) analysis. Currently, workflow management is fragmented across multiple components with no central authority, and crucially, there's no way to save workflows after generation.

### Core Problems Being Solved
1. **No Save Functionality**: Workflows can be generated but not persisted
2. **Scattered Loading Logic**: 4 different implementations across components
3. **Format Mismatch**: Context Builder expects metadata wrapper, WorkflowExecutor expects raw IR
4. **No Name Resolution**: Components use file paths directly instead of workflow names
5. **Missing Lifecycle Management**: No way to list, delete, or check workflow existence

### Implementation Requirements
The WorkflowManager will be implemented as a new class in `src/pflow/core/workflow_manager.py` with these methods:
- `save(name: str, workflow_ir: dict, description: Optional[str] = None) -> str`: Save workflow with metadata wrapper
- `load(name: str) -> dict`: Load complete workflow with metadata
- `load_ir(name: str) -> dict`: Load just the IR for execution
- `get_path(name: str) -> str`: Get file path for a workflow name
- `list_all() -> List[WorkflowMetadata]`: List all saved workflows
- `exists(name: str) -> bool`: Check if workflow exists
- `delete(name: str) -> None`: Remove a workflow

### Storage Format (Leveraging Task 21)
Workflows will be stored in `~/.pflow/workflows/` as JSON files with this structure:
```json
{
  "name": "fix_issue",
  "description": "Fixes GitHub issues and creates PR",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {  // Task 21 addition
      "issue_number": {
        "description": "GitHub issue number",
        "required": true,
        "type": "string"
      }
    },
    "outputs": {  // Task 21 addition
      "pr_url": {
        "description": "Created pull request URL",
        "type": "string"
      }
    },
    "nodes": [...],
    "edges": [...]
  },
  "created_at": "2025-01-30T10:00:00Z",
  "updated_at": "2025-01-30T10:00:00Z",
  "version": "1.0.0"
}
```

### Integration Points
1. **Context Builder**: Replace `_load_saved_workflows()` with `workflow_manager.list_all()`
2. **CLI**: Implement workflow saving after user approval using `workflow_manager.save()`
3. **WorkflowExecutor**: Add support for `workflow_name` parameter using `workflow_manager.load_ir()`
4. **Natural Language Planner**: Use workflow names directly, WorkflowManager handles resolution

### Key Design Decisions
- **Metadata Wrapper for Storage**: Preserves workflow identity and enables rich discovery
- **Dual Loading Methods**: `load()` for discovery, `load_ir()` for execution handles format mismatch
- **Name Uniqueness**: Workflow names must be unique (no versioning in MVP)
- **Snake Case Convention**: "fix-issue" becomes "fix_issue" automatically
- **Validation on Load**: Skip invalid files with warnings rather than crashing

### Future Enhancement Opportunities
- Workflow versioning support
- Tag-based discovery
- Interface-based search (find by inputs/outputs)
- Import/export functionality
- Dependency tracking

## Test Strategy
Comprehensive testing will ensure WorkflowManager handles all scenarios reliably:

### Unit Tests
- Save new workflow with metadata wrapper and timestamps
- Prevent duplicate workflow names with WorkflowExistsError
- Load complete workflow with metadata
- Load just IR for execution
- Handle missing workflows with WorkflowNotFoundError
- List all workflows, skipping invalid files
- Check workflow existence
- Delete existing workflows
- Name normalization (hyphens to underscores)
- Path expansion with tilde handling

### Integration Tests
- Full save/load/execute cycle
- Context Builder integration with list_all()
- WorkflowExecutor with workflow_name parameter
- CLI workflow saving after planner generation

### Edge Cases
- Empty workflow directory
- Corrupted JSON files
- Missing required fields
- Permission errors
- Concurrent access (document as known limitation)

### Validation Tests
- Missing ir field raises ValidationError
- Invalid workflow structure detection
- Proper error messages for debugging
