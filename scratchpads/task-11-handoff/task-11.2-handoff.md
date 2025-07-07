# Handoff Memo: Subtask 11.2 - File Manipulation Nodes

## Critical Context You MUST Know

### What I Built (11.1)
- `ReadFileNode` and `WriteFileNode` in `/src/pflow/nodes/file/`
- Used `Node` base class (NOT BaseNode) for retry logic - this is CRITICAL for file ops
- Established the tuple pattern: `exec()` returns `(result, success_bool)`
- Line numbers are added to read content (this changes the data!)

### The Truthiness Trap That Will Bite You
```python
# THIS WILL FAIL WITH EMPTY STRINGS:
content = shared.get("content") or self.params.get("content")

# YOU MUST DO THIS:
if "content" in shared:
    content = shared["content"]
elif "content" in self.params:
    content = self.params["content"]
```

I lost 15 minutes to this bug. Empty strings are valid content but Python's `or` treats them as falsy.

### Patterns You're Inheriting

1. **Error Handling Pattern** (from Tutorial-Cursor):
   - Non-retryable errors (file not found): return tuple immediately
   - Retryable errors (network glitch): raise RuntimeError for Node retry
   - See `/src/pflow/nodes/file/read_file.py` lines 67-75

2. **Import Pattern** (ugly but required):
   ```python
   sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
   from pocketflow import Node
   ```

3. **Directory Creation** (from write_file.py):
   ```python
   parent_dir = os.path.dirname(os.path.abspath(file_path))
   if parent_dir:
       os.makedirs(parent_dir, exist_ok=True)
   ```

### Specific Guidance for Each Node

#### CopyFileNode
- Use `shutil.copy2()` to preserve metadata (not just `shutil.copy()`)
- Check source exists in `prep()`, not `exec()` - fail fast
- The spec mentions "safety check for overwriting" but doesn't specify behavior - you'll need to decide

#### MoveFileNode
- `os.rename()` is atomic ONLY on same filesystem
- Must catch `OSError` and fallback to copy+delete for cross-filesystem
- This is the most complex node - test cross-filesystem moves carefully
- Consider: what if copy succeeds but delete fails?

#### DeleteFileNode
- Spec mentions "safety parameter" but doesn't define it
- I suggest requiring `shared["confirm_delete"] = True` or similar
- Check if file exists first - deleting non-existent file should probably succeed (idempotent)
- Log the deletion somewhere - this is irreversible

### Test Patterns Already Established

See `/tests/test_file_nodes.py` for patterns:
- Use `tempfile.TemporaryDirectory()` for all tests
- Test both shared store and params fallback
- Test permission errors explicitly
- Integration test pattern at line 285 shows how nodes work together

### Registry Discovery

The `__init__.py` already imports ReadFileNode and WriteFileNode. You MUST add your nodes:
```python
from .copy_file import CopyFileNode
from .move_file import MoveFileNode
from .delete_file import DeleteFileNode

__all__ = ["ReadFileNode", "WriteFileNode", "CopyFileNode", "MoveFileNode", "DeleteFileNode"]
```

### Documentation That Actually Helps

- `/Users/andfal/projects/pflow/pocketflow/cookbook/Tutorial-Cursor/utils/` - Has file operation patterns
- `/Users/andfal/projects/pflow/.taskmaster/knowledge/patterns.md` - I added the truthiness pattern here
- `/Users/andfal/projects/pflow/src/pflow/nodes/file/write_file.py` - Shows the established patterns

### Hidden Complexity

1. **Atomic Operations**: Move is NOT always atomic. Windows and Unix behave differently.
2. **Symbolic Links**: The spec doesn't mention them. What should copy do with symlinks?
3. **Permissions**: What if source is readable but destination directory isn't writable?
4. **Large Files**: Consider progress indication for large file copies

### What The Spec Doesn't Say

- How to handle existing destination files (overwrite? error? prompt?)
- Whether to follow symbolic links or copy them as links
- How verbose logging should be
- Whether delete should work on directories (probably not)

### My Recommendation

Start with CopyFileNode - it's the simplest. Get the patterns right there, then MoveFileNode builds on it. DeleteFileNode is independent but needs the most safety consideration.

The handoff memo from task 4 warned about reserved logging fields. I didn't hit this, but watch out for "filename" in logging extras.

## Read and understand

DO NOT begin implementing. Just read this memo and say you are ready to begin.
