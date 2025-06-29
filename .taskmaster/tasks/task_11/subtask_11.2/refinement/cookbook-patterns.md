# Cookbook Patterns for Subtask 11.2

## Relevant PocketFlow Examples

### 1. Tutorial-Cursor File Utilities Pattern
**Location**: `/Users/andfal/projects/pflow/pocketflow/cookbook/Tutorial-Cursor/utils/delete_file.py`

**Key Pattern**: Tuple return with consistent error handling
```python
def delete_file(target_file: str) -> Tuple[str, bool]:
    try:
        if not os.path.exists(target_file):
            return f"File {target_file} does not exist", False

        os.remove(target_file)
        return f"Successfully deleted {target_file}", True

    except Exception as e:
        return f"Error deleting file: {str(e)}", False
```

**Application**: All three nodes (copy, move, delete) should follow this exact pattern

### 2. Node Integration with Tuple Pattern
**Adapted from**: ReadFileNode and WriteFileNode in subtask 11.1

**Key Pattern**: Proper integration of tuple returns with Node lifecycle
```python
def exec(self, prep_res: Tuple[str, str]) -> Tuple[str, bool]:
    source_path, dest_path = prep_res
    # Operation returns (message, success)
    return self._perform_operation(source_path, dest_path)

def post(self, shared, prep_res, exec_res):
    message, success = exec_res
    if success:
        shared["result"] = message
        return "default"
    else:
        shared["error"] = message
        return "error"
```

### 3. Directory Creation Pattern
**From**: WriteFileNode implementation and Tutorial-Cursor patterns

**Key Pattern**: Always ensure parent directories exist
```python
parent_dir = os.path.dirname(os.path.abspath(dest_path))
if parent_dir:
    os.makedirs(parent_dir, exist_ok=True)
```

**Application**: Both CopyFileNode and MoveFileNode need this before operations

### 4. Error Differentiation Pattern
**From**: Subtask 11.1 learnings

**Key Pattern**: Distinguish retryable vs non-retryable errors
```python
# In exec method:
try:
    # Operation
except FileNotFoundError:
    # Non-retryable - return immediately
    return f"Error: Source file {path} not found", False
except PermissionError:
    # Non-retryable - return immediately
    return f"Error: Permission denied for {path}", False
except OSError as e:
    if "cross-device link" in str(e):
        # Handle special case for move
        return self._cross_device_move(source, dest)
    # Other OS errors might be retryable
    raise RuntimeError(f"Temporary error: {e}") from e
```

### 5. Parameter Handling Pattern
**From**: Subtask 11.1 truthiness bug fix

**Key Pattern**: Explicit key existence checking
```python
def prep(self, shared):
    # For parameters that could be empty strings
    if "source_path" in shared:
        source_path = shared["source_path"]
    elif "source_path" in self.params:
        source_path = self.params["source_path"]
    else:
        raise ValueError("Missing required 'source_path'")
```

## Recommended Adaptations

### For CopyFileNode
1. Use `shutil.copy2()` to preserve metadata (following cookbook convention)
2. Implement overwrite safety check using shared["overwrite"] flag
3. Create destination directory before copy
4. Return descriptive success/error messages

### For MoveFileNode
1. Use `shutil.move()` for cross-filesystem support
2. Handle the special case where move fails across devices
3. Implement same overwrite safety as copy
4. Consider partial success scenario (copy succeeds, delete fails)

### For DeleteFileNode
1. Follow the exact pattern from `delete_file.py` in cookbook
2. Add safety confirmation via shared["confirm_delete"] flag
3. Make "file not found" a success case (idempotent)
4. Log deletion for audit trail (using structured logging pattern)

## Testing Patterns to Apply

From test_file_nodes.py:
1. Use `tempfile.TemporaryDirectory()` for all test files
2. Test both shared store and params fallback
3. Test permission errors explicitly
4. Include integration tests showing nodes working together
5. Test edge cases: empty paths, non-existent files, permission issues

## Documentation Patterns

From existing nodes:
```python
"""
Brief one-line description.

Extended explanation of functionality and use cases.

Interface:
- Reads: shared["key"] - description of what it's for
- Writes: shared["key"] - what gets written and when
- Actions: default (success), error (failure)
- Params: param_name - description and default if applicable

Security Note: Warnings about destructive operations.
"""
```
