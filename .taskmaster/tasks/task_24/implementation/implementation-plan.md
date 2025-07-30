# Task 24 Implementation Plan

## Context Summary

### Workflow Loading Patterns Found
1. **Context Builder**: Expects metadata wrapper format with `name`, `description`, `ir` fields
2. **WorkflowExecutor**: Expects raw IR format (just `ir_version`, `nodes`, `edges`, etc.)
3. **CLI**: Reads text, parses as JSON, expects raw IR format
4. **No save functionality exists**

### Format Differences
**Metadata Wrapper (Context Builder, saved workflows):**
```json
{
  "name": "fix-issue",
  "description": "Fixes GitHub issues",
  "ir": { /* actual workflow */ },
  "created_at": "2025-01-29T10:00:00Z",
  "version": "1.0.0"
}
```

**Raw IR (WorkflowExecutor, CLI, examples):**
```json
{
  "ir_version": "0.1.0",
  "nodes": [...],
  "edges": [...],
  "inputs": {...},
  "outputs": {...}
}
```

### Integration Points
- Context Builder lines 375, 506: Replace `_load_saved_workflows()` with `workflow_manager.list_all()`
- CLI line 468: Add workflow saving after planner approval
- WorkflowExecutor: Add `workflow_name` parameter support

## Implementation Steps

### Phase 1: Core WorkflowManager (Parallel Execution Possible)

#### Task 1A: Create WorkflowManager Class (Subagent A)
**Files:** `src/pflow/core/workflow_manager.py`
**Dependencies:** None
**Description:** Implement the core WorkflowManager class with all methods

**Implementation details:**
- Create class with `__init__` that sets up workflows directory (~/.pflow/workflows/)
- Implement `save(name, workflow_ir, description)` - wrap IR in metadata, add timestamps
- Implement `load(name)` - return full metadata wrapper format
- Implement `load_ir(name)` - return just the IR field for execution
- Implement `get_path(name)` - return absolute path for workflow file
- Implement `list_all()` - read all valid workflows, skip invalid with warnings
- Implement `exists(name)` - check if workflow file exists
- Implement `delete(name)` - remove workflow file
- Use kebab-case names directly (e.g., "fix-issue.json")
- Validate workflow names: max 50 chars, valid filename chars
- Expand tilde (~) in all path operations
- Create directory if missing
- Add proper logging for warnings

#### Task 1B: Create Custom Exceptions (Subagent B)
**Files:** `src/pflow/core/exceptions.py`
**Dependencies:** None
**Description:** Add WorkflowManager-specific exceptions

**Implementation details:**
- Add `WorkflowExistsError` - raised when saving with existing name
- Add `WorkflowNotFoundError` - raised when loading/deleting missing workflow
- Add `WorkflowValidationError` - raised for invalid workflow structure
- Inherit from appropriate base exceptions
- Include helpful error messages

#### Task 1C: Create WorkflowManager Tests (Subagent C)
**Files:** `tests/test_core/test_workflow_manager.py`
**Dependencies:** WorkflowManager implementation (can write tests first)
**Description:** Comprehensive test suite for WorkflowManager

**Test scenarios:**
- Test save with new name creates file with metadata wrapper
- Test save with existing name raises WorkflowExistsError
- Test save adds timestamps (created_at, updated_at) and version
- Test load returns complete metadata structure
- Test load with missing workflow raises WorkflowNotFoundError
- Test load_ir returns only IR contents (no metadata)
- Test get_path returns expanded absolute path
- Test list_all returns all valid workflows
- Test list_all skips invalid JSON with warning (use caplog)
- Test exists returns True/False correctly
- Test delete removes file
- Test delete with missing workflow raises WorkflowNotFoundError
- Test workflow name validation (max length, valid chars)
- Test directory auto-creation
- Test format transformation between metadata and IR
- Use tmp_path fixture for isolated tests
- Mock file operations where appropriate

### Phase 2: Integration (Sequential - Depends on Phase 1)

#### Task 2A: Update Context Builder Integration (Subagent D)
**Files:** `src/pflow/planning/context_builder.py`
**Dependencies:** WorkflowManager must be complete
**Description:** Replace direct file loading with WorkflowManager

**Implementation details:**
- Import WorkflowManager at top of file
- In `__init__`, create `self.workflow_manager = WorkflowManager()`
- Replace `self._load_saved_workflows()` calls (lines 375, 506) with `self.workflow_manager.list_all()`
- Remove or deprecate `_load_saved_workflows()` method
- Ensure format compatibility (list_all returns same format)
- Update any tests that mock `_load_saved_workflows`

#### Task 2B: Add Workflow Saving to CLI (Subagent E)
**Files:** `src/pflow/cli/main.py`
**Dependencies:** WorkflowManager must be complete
**Description:** Implement workflow saving after planner generates

**Implementation details:**
- Import WorkflowManager at top
- After natural language planning (around line 468), check if workflow should be saved
- Prompt user: "Save this workflow? (y/n): "
- If yes, prompt for name: "Workflow name: "
- Validate name, use WorkflowManager.save()
- Show success message with saved path
- Handle errors (duplicate names, invalid names)
- For now, just save after showing the workflow - full planner integration comes in Task 17

#### Task 2C: Enhance WorkflowExecutor for Name Support (Subagent F)
**Files:** `src/pflow/runtime/workflow_executor.py`
**Dependencies:** WorkflowManager must be complete
**Description:** Add workflow_name parameter support

**Implementation details:**
- Import WorkflowManager at top
- In `exec()`, check for `workflow_name` parameter
- If workflow_name provided:
  - Create WorkflowManager instance
  - Use `workflow_manager.load_ir(workflow_name)` to get IR
  - Validate and compile the workflow
- Keep existing `workflow_ref` support for backward compatibility
- Priority: workflow_name > workflow_ref > workflow_ir
- Update docstring to document new parameter
- Add debug logging for workflow resolution

#### Task 2D: Integration Tests (Subagent G)
**Files:** `tests/test_integration/test_workflow_manager_integration.py`
**Dependencies:** All integrations complete
**Description:** Test WorkflowManager integration with other components

**Test scenarios:**
- Test Context Builder uses WorkflowManager for loading
- Test CLI workflow saving flow (mock user input)
- Test WorkflowExecutor with workflow_name parameter
- Test full cycle: save → list → load → execute
- Test format compatibility between components

### Phase 3: Validation (Sequential - After Phase 2)

#### Task 3A: Run Tests and Fix Issues
**Description:** Ensure all tests pass
- Run `make test`
- Fix any failing tests
- Run `make check` for linting/type checking
- Fix any issues found

#### Task 3B: Update Documentation
**Files:** Various documentation files
**Description:** Document WorkflowManager and workflow lifecycle
- Update CLAUDE.md with new component
- Add workflow lifecycle documentation
- Update examples if needed

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|--------------------|
| Format mismatch bugs | Comprehensive tests for load vs load_ir |
| Breaking Context Builder | Test Context Builder after migration |
| File corruption | Use atomic writes (write to temp, then rename) |
| Invalid workflow names | Strict validation with clear errors |
| Missing directory | Auto-create with proper permissions |

## Validation Strategy

1. **Unit Testing**: Each component tested in isolation
2. **Integration Testing**: Components work together correctly
3. **Format Testing**: Verify format transformation works
4. **Error Testing**: All error cases handled gracefully
5. **Manual Testing**: Run example workflows through full cycle

## Subagent Task Assignments

### Parallel Phase 1 (Can run simultaneously):
- **Subagent A**: WorkflowManager implementation
- **Subagent B**: Custom exceptions
- **Subagent C**: WorkflowManager tests

### Sequential Phase 2 (Must run in order):
- **Subagent D**: Context Builder integration
- **Subagent E**: CLI save functionality
- **Subagent F**: WorkflowExecutor enhancement
- **Subagent G**: Integration tests

### Final Phase 3:
- Run tests and fix issues
- Update documentation

## Success Criteria

- [x] WorkflowManager can save, load, list, and delete workflows
- [x] Format transformation works correctly (load vs load_ir)
- [x] Context Builder uses WorkflowManager instead of direct file loading
- [x] CLI can save workflows after generation
- [x] WorkflowExecutor can use workflow names
- [x] All existing tests still pass
- [x] New comprehensive tests for WorkflowManager
- [x] `make test` passes
- [x] `make check` passes
