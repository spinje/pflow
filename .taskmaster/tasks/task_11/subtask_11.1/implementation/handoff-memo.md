# Implementation Handoff Memo for Subtask 11.1

## Why This Matters
These aren't just file nodes - they're the **foundation for all file operations** in pflow. Every future file manipulation (copy, move, delete) will follow the patterns you establish here. Get this wrong, and you'll create tech debt that haunts the project.

## Critical Non-Obvious Decisions

### 1. Node vs BaseNode - The Real Story
The task says "BaseNode" but I chose "Node" because:
- File operations fail for stupid reasons (temp locks, network hiccups)
- Node gives you retry logic for free
- The handoff memo from task 4 warned about this exact confusion
- **Risk**: If you use BaseNode, file ops will be fragile in real workflows

### 2. The Tuple Pattern - More Than Error Handling
I chose `(result, success_bool)` from Tutorial-Cursor because:
- It forces explicit success/failure handling in post()
- Enables graceful degradation without exceptions
- **Hidden complexity**: You must unpack in post() and convert to actions
- **Pattern**: `content, success = exec_res` then branch on success

### 3. Line Numbers - A Deliberate Trade-off
Adding line numbers by default seems wrong (modifies content!) but:
- Primary use case is displaying files for analysis
- Tutorial-Cursor does this and users expect it
- **Risk**: Someone will use read-file expecting raw content and get surprised
- **Future**: Consider raw_content flag in v2

### 4. The Import Hell Pattern
Every node in the codebase does this ugly thing:
```python
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from pocketflow import Node
```
**You must follow this pattern** or imports will fail. Yes, it's gross. No, don't try to fix it.

## Patterns You're Inheriting

### From Tutorial-Cursor (Critical)
- The `(result, success)` tuple is EVERYWHERE in their utils
- Line numbers are 1-indexed (not 0-indexed!)
- Error messages include the file path for context
- `os.makedirs(exist_ok=True)` prevents a common failure mode

### From Test Nodes (Follow Exactly)
- Class naming: `ReadFileNode` (not `ReadFile` or `FileReader`)
- The docstring Interface section is parsed by the scanner
- Don't add complex logic - nodes are dumb by design

## Pitfalls That Will Bite You

### 1. The "filename" Logging Trap
**NEVER** use `extra={"filename": ...}` in logging. It's a reserved field that causes KeyError. Use `"file_path"` instead. Task 4 lost 30 minutes to this.

### 2. The __init__.py Is Not Optional
Without `src/pflow/nodes/file/__init__.py` exposing your nodes, the registry scanner won't find them. This isn't a nice-to-have - it's required for discovery.

### 3. Don't Overthink Shared Store
- Check shared first: `shared.get("file_path") or self.params.get("path")`
- Don't validate types - let it fail naturally
- Don't add complex key transformations

### 4. Test-As-You-Go Is Mandatory
Previous tasks established: tests ship WITH implementation, not after. Create `tests/test_file_nodes.py` in the same commit. Use tempfile for all file operations in tests.

## Hidden Complexities

### Encoding Edge Cases
- UTF-8 is the default but encoding IS configurable
- Binary files will explode - we're accepting this for MVP
- Document this limitation clearly

### Path Handling
- Both absolute and relative paths must work
- Don't assume working directory
- Let Python's path resolution do its thing

### Error Action Flow
The "error" action you return affects flow control:
- Downstream nodes can react to "error" transitions
- This isn't just logging - it's program flow
- Make error messages actionable

## Risk Factors

1. **Security**: These nodes can read/write ANYWHERE. We're not adding path validation in MVP. Document this loudly.

2. **Performance**: Large files will load entirely into memory. No streaming in MVP. Another loud documentation point.

3. **Binary Files**: Will fail with encoding errors. Text-only for MVP.

4. **The Append Mode**: Easy to forget but explicitly required. Check `self.params.get("append", False)`.

## Things That MUST Not Be Overlooked

1. Create the directory: `src/pflow/nodes/file/`
2. Three files minimum: `read_file.py`, `write_file.py`, `__init__.py`
3. The __init__.py must export: `from .read_file import ReadFileNode` etc.
4. Use `Node` not `BaseNode` as the base class
5. Follow the sys.path.insert pattern exactly
6. Write comprehensive tests immediately
7. Document security implications in docstrings

## The One Weird Thing
The refined spec talks about `shared["written"]` for write-file output. This might seem odd (why not just boolean?) but it follows the pattern of providing useful context in outputs. Set it to something like `f"Successfully wrote to {file_path}"`.

## Final Wisdom
These nodes are deceptively simple. The complexity is in getting the patterns right because every future file node will copy what you do here. When in doubt, look at Tutorial-Cursor's file utils - they've solved these problems already.

Remember: You're not just implementing two nodes. You're establishing the file I/O patterns for the entire project.
