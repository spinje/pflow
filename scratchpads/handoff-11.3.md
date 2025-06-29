# Handoff Memo: Subtask 11.3 - Polish with Comprehensive Error Handling

## Critical Context You MUST Know

### What I Built (11.2)
- `CopyFileNode`, `MoveFileNode`, and `DeleteFileNode` in `/src/pflow/nodes/file/`
- All three follow the established patterns from 11.1 perfectly
- Tests are in `/tests/test_file_nodes.py` (15 new tests added)

### The Safety Flag Discovery That Changes Everything
```python
# THIS IS THE PATTERN FOR ALL DESTRUCTIVE OPS:
if "confirm_delete" not in shared:
    raise ValueError("Missing required 'confirm_delete' in shared store. "
                   "This safety flag must be explicitly set in shared store.")

confirm_delete = shared["confirm_delete"]
# NEVER fallback to self.params for safety flags!
```

I discovered this pattern is CRITICAL for DeleteFileNode. It prevents accidental deletions from config files or default params. This pattern should be applied to ANY destructive operation in 11.3.

### Cross-Filesystem Move Complexity
MoveFileNode has this special handling:
```python
try:
    shutil.move(source_path, dest_path)
except OSError as e:
    if "cross-device link" in str(e).lower():
        # Handle cross-filesystem move
        return self._cross_device_move(source_path, dest_path)
```

The string matching is crude but works. In 11.3, you might want to make this more robust.

### Patterns Already Established (DO NOT BREAK THESE)

1. **All file nodes use `Node` base class** (not BaseNode) for retry logic
2. **Tuple returns everywhere**: `(message, success_bool)`
3. **Error differentiation**:
   - FileNotFoundError → return tuple immediately
   - PermissionError → return tuple immediately
   - Other exceptions → raise RuntimeError for retry
4. **Idempotent delete**: File not found = success (this was intentional)

### What 11.3 Likely Needs to Polish

Based on the implementation details, here's what's probably missing:

1. **Better cross-platform handling** - Windows vs Unix differences
2. **Symbolic link handling** - Currently we just follow them (shutil default)
3. **Large file handling** - No progress indication for big copies
4. **Better error messages** - Some are generic like "Error: {e!s}"
5. **Race conditions** - What if file is deleted between existence check and operation?
6. **Disk space checks** - We don't check if destination has space
7. **Atomic operations** - Copy isn't atomic, could leave partial files

### Hidden Complexity I Discovered

1. **Empty strings and truthiness**: Still a problem! But booleans are fine:
   ```python
   # This is OK for booleans:
   overwrite = shared.get("overwrite", self.params.get("overwrite", False))
   # But NOT for strings (use the pattern from 11.1)
   ```

2. **Warning propagation**: I implemented partial success with warnings:
   ```python
   if "warning:" in message.lower():
       warning_start = message.lower().find("warning:")
       shared["warning"] = message[warning_start:]
   ```
   This could be more robust in 11.3.

3. **Directory permissions**: We create parent dirs but don't handle permission failures well

### Files You MUST Read

1. `/src/pflow/nodes/file/delete_file.py` - Shows the safety flag pattern
2. `/src/pflow/nodes/file/move_file.py` - Shows cross-device handling
3. `/tests/test_file_nodes.py` - Shows all the edge cases we test
4. `/.taskmaster/knowledge/patterns.md` - I added the safety flag pattern here

### Documentation That Actually Helps

- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_11/subtask_11.1/implementation/subtask-review.md` - Has the truthiness bug details
- `/Users/andfal/projects/pflow/pocketflow/cookbook/Tutorial-Cursor/utils/` - Has simpler file operation patterns
- `/Users/andfal/projects/pflow/docs/features/simple-nodes.md` - The bible for node patterns

### What I Didn't Test (But You Should)

1. **Cross-filesystem moves** - I couldn't test without mocking OSError
2. **Concurrent file access** - What if two nodes try to move the same file?
3. **Very large files** - All my tests use tiny files
4. **Network drives** - Retry logic might not be enough
5. **Permission edge cases** - Like read-only filesystems

### Architecture Decision I Made

I made DeleteFileNode idempotent (file not found = success) even though the cookbook pattern treats it as error. This was intentional for workflow robustness. Don't change this unless you have a good reason.

### My Recommendation for 11.3

Focus on:
1. **Race condition handling** - Use proper file locking or atomic checks
2. **Better error messages** - Include context about what operation failed
3. **Progress indication** - For large file operations
4. **Disk space checks** - Prevent partial copies
5. **Consistent warning system** - Not just string parsing

Don't waste time on:
- Rewriting the basic logic (it works well)
- Adding async support (not in MVP)
- Complex retry strategies (current one is fine)

### The Subtle Bug That Might Bite You

In `move_file.py`, the cross-device move fallback does copy+delete. If the copy succeeds but delete fails, we return success with a warning. This is by design (best-effort approach) but could surprise users who expect atomic moves.

## Final Words

The foundation from 11.1 and 11.2 is solid. Don't overthink the polishing - focus on the real edge cases that would break in production. The safety flag pattern is your friend for any destructive operations.

## Read and Understand

DO NOT begin implementing. Just read this memo and say you are ready to begin.
