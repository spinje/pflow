# Refined Specification for Subtask 11.2

## Clear Objective
Implement three file manipulation nodes (CopyFileNode, MoveFileNode, DeleteFileNode) following the patterns established in subtask 11.1, with appropriate safety mechanisms and comprehensive error handling.

## Context from Knowledge Base
- Building on: Tuple return pattern, Node inheritance, and truthiness-safe parameter handling from task 11.1
- Avoiding: The `or` operator bug for parameter fallback, reserved logging field names
- Following: Established shared store conventions, comprehensive docstring format, test-as-you-go development
- **Cookbook patterns to apply**: Tutorial-Cursor delete_file.py pattern, error handling with (message, bool) tuples

## Technical Specification

### CopyFileNode

#### Inputs
- `shared["source_path"]` (required) - Path to source file
- `shared["dest_path"]` (required) - Path to destination
- `shared["overwrite"]` (optional, default False) - Allow overwriting existing files
- Params can provide fallbacks for all shared store values

#### Outputs
- On success: `shared["copied"] = "Successfully copied {source} to {dest}"`
- On failure: `shared["error"] = "Error: {detailed message}"`
- Actions: "default" (success), "error" (failure)

#### Implementation Constraints
- Must use `shutil.copy2()` to preserve file metadata
- Must create parent directories with `os.makedirs(exist_ok=True)`
- Must check source existence before operation
- Must handle overwrite safety explicitly
- Must follow truthiness-safe parameter handling

### MoveFileNode

#### Inputs
- `shared["source_path"]` (required) - Path to source file
- `shared["dest_path"]` (required) - Path to destination
- `shared["overwrite"]` (optional, default False) - Allow overwriting existing files
- Params can provide fallbacks for all shared store values

#### Outputs
- On success: `shared["moved"] = "Successfully moved {source} to {dest}"`
- On failure: `shared["error"] = "Error: {detailed message}"`
- On partial success (copy ok, delete failed): `shared["warning"] = "File copied but source deletion failed: {reason}"`
- Actions: "default" (success), "error" (failure)

#### Implementation Constraints
- Must use `shutil.move()` for cross-filesystem support
- Must handle cross-device move failures gracefully
- Must create parent directories before operation
- Must follow same overwrite logic as CopyFileNode
- Best-effort approach: If delete fails after copy, log warning but return success

### DeleteFileNode

#### Inputs
- `shared["file_path"]` (required) - Path to file to delete
- `shared["confirm_delete"]` (optional, default False) - Safety confirmation flag
- Params can provide fallbacks for file_path only (confirm_delete must be explicit in shared)

#### Outputs
- On success: `shared["deleted"] = "Successfully deleted {path}"`
- On failure: `shared["error"] = "Error: {detailed message}"`
- Actions: "default" (success), "error" (failure)

#### Implementation Constraints
- Must check `confirm_delete` flag before deletion
- Must treat "file not found" as success (idempotent behavior)
- Must use structured logging to record deletions
- Must NOT retry on permission errors
- Safety flag must come from shared store only (not params)

## Success Criteria
- [ ] All three nodes implemented with proper Node inheritance and retry logic
- [ ] Comprehensive docstrings following established format
- [ ] Tuple return pattern correctly implemented in all exec() methods
- [ ] Safety mechanisms working as specified (overwrite checks, delete confirmation)
- [ ] Parent directory creation for copy/move operations
- [ ] All tests pass including edge cases
- [ ] No regressions in existing file node tests
- [ ] Nodes properly exported in __init__.py for registry discovery
- [ ] Cross-filesystem moves handled gracefully
- [ ] Truthiness-safe parameter handling throughout

## Test Strategy

### Unit Tests (add to test_file_nodes.py)
- **CopyFileNode**:
  - Successful copy with and without overwrite
  - Source not found error
  - Destination directory creation
  - Permission errors
  - Copy to existing file with overwrite=False

- **MoveFileNode**:
  - Successful move (same filesystem)
  - Cross-filesystem move simulation
  - Partial success case (copy ok, delete fails)
  - Source not found error
  - Overwrite safety checks

- **DeleteFileNode**:
  - Successful delete with confirmation
  - Rejection without confirmation
  - Delete non-existent file (should succeed)
  - Permission errors
  - Safety flag validation

### Integration Tests
- Copy → Move → Delete workflow
- Error propagation between nodes
- Shared store parameter precedence
- Registry discovery of new nodes

### Manual Verification
- Test with various file types and sizes
- Verify cross-platform behavior if possible
- Check that destructive operations are properly guarded

## Dependencies
- Requires: Node base class from pocketflow, established file node patterns
- Impacts: Node registry will include three new nodes after implementation

## Decisions Made
1. **Safety mechanisms**: Use boolean flags in shared store (shared["overwrite"], shared["confirm_delete"]) - provides consistency with existing patterns
2. **Cross-filesystem move failures**: Best-effort approach with warning - most useful for users
3. **Symbolic links**: Follow symlinks by default using shutil defaults - simplest for MVP
4. **Parameter naming**: Use source_path/dest_path for copy/move, file_path for delete - natural and self-documenting
