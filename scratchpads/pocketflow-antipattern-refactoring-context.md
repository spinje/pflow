# PocketFlow Anti-Pattern Refactoring - Comprehensive Context

## Overview
This document captures the complete context of refactoring pflow's file operation nodes to comply with PocketFlow anti-patterns. This refactoring is CRITICAL for proper retry behavior and framework compliance.

## Background: What Are PocketFlow Anti-Patterns?

PocketFlow anti-patterns are documented practices that break the framework's design principles. The most critical anti-pattern we're fixing is:

**Anti-Pattern 2.1: Implementing Custom Error Handling in exec()**
- **Description**: Wrapping exec() logic in try...except blocks
- **Why It's Bad**: Bypasses PocketFlow's powerful retry mechanism
- **Impact**: Transient errors (like temporary file locks) never get retried

## The Problem We Discovered

All 5 file operation nodes in `/src/pflow/nodes/file/` violate this anti-pattern:
1. `ReadFileNode` - catches UnicodeDecodeError, PermissionError
2. `WriteFileNode` - catches PermissionError, OSError  
3. `CopyFileNode` - catches all file operation errors
4. `MoveFileNode` - catches all file operation errors
5. `DeleteFileNode` - catches all file operation errors

### Example of the Problem

```python
# WRONG - Current implementation
def exec(self, prep_res):
    try:
        with open(file_path, encoding=encoding) as f:
            lines = f.readlines()
    except UnicodeDecodeError as e:
        return (f"Error: Cannot read...", False)  # ❌ Bypasses retry!
    except PermissionError:
        return (f"Error: Permission denied...", False)  # ❌ Bypasses retry!
```

This means if a file is temporarily locked, it fails immediately instead of retrying!

## The Solution Pattern

### PocketFlow's Correct Pattern

```python
# CORRECT - Let exceptions bubble up
def exec(self, prep_res):
    # No try/except - let exceptions bubble up
    with open(file_path, encoding=encoding) as f:
        lines = f.readlines()
    return content  # Only return success

def exec_fallback(self, prep_res, exc):
    # Handle errors AFTER all retries exhausted
    if isinstance(exc, UnicodeDecodeError):
        return "Error: Cannot read with encoding..."
    elif isinstance(exc, PermissionError):
        return "Error: Permission denied..."
```

### Key Concepts

1. **exec() method**: Should ONLY handle success cases, let exceptions bubble up
2. **exec_fallback() method**: Handles errors AFTER retries are exhausted
3. **NonRetriableError**: New exception class for validation errors that shouldn't retry
4. **Return types changed**: From `tuple[str, bool]` to just `str`

## Changes Made to Each File

### 1. `/src/pflow/nodes/file/__init__.py`
Added `NonRetriableError` exception class:
```python
class NonRetriableError(Exception):
    """Exception for errors that should not be retried."""
    pass
```

### 2. `/src/pflow/nodes/file/read_file.py`
- Changed `exec()` return type from `tuple[str, bool]` to `str`
- Removed all try/except blocks, let exceptions bubble up
- Moved error handling to `exec_fallback()`
- Updated `post()` to check if result starts with "Error:"

### 3. `/src/pflow/nodes/file/write_file.py`
- Refactored `_ensure_parent_directory()` to raise exceptions
- Refactored `_check_disk_space()` to raise OSError
- Removed all error catching from `exec()` and `_atomic_write()`
- Added comprehensive `exec_fallback()` with specific error messages

### 4. `/src/pflow/nodes/file/copy_file.py`
- Added `from . import NonRetriableError`
- Changed validation methods to raise exceptions
- Used `NonRetriableError` for validation errors (not a file, destination exists)
- Removed all try/except from `_perform_copy()`

### 5. `/src/pflow/nodes/file/move_file.py`
- Similar changes to copy_file
- Special handling for cross-device moves (still returns success with warning)
- Validation errors use `NonRetriableError`

### 6. `/src/pflow/nodes/file/delete_file.py`
- Confirmation check raises `NonRetriableError` (won't retry)
- File not found returns success (idempotent behavior)
- Let PermissionError and OSError bubble up for retry

## Current Status: What's Broken

### 1. Linting Errors (`make check` fails)
```
src/pflow/nodes/file/__init__.py:14:1: E402 Module level import not at top of file
src/pflow/nodes/file/delete_file.py:152:82: F821 Undefined name `errno`
```

### 2. Test Failures (8 tests fail)
All tests were written for the old pattern where `exec()` returns `(message, success)` tuple.

Failed tests:
- `test_missing_file` - expects error tuple, gets FileNotFoundError
- `test_encoding_error` - expects error tuple, gets UnicodeDecodeError  
- `test_error_propagation` - expects error in shared store
- `test_copy_overwrite_protection` - expects error tuple, gets NonRetriableError
- etc.

### 3. Missing Test Coverage
No tests for:
- Retry behavior (does it actually retry?)
- NonRetriableError behavior (does it skip retries?)
- exec_fallback messages
- Full lifecycle with `node.run()`

## Critical Implementation Details

### 1. How PocketFlow Retry Works
When using `Node` (not `BaseNode`):
- `max_retries` parameter controls retry attempts
- `wait` parameter adds delay between retries
- `exec()` is called up to `max_retries` times
- Only after all retries fail, `exec_fallback()` is called

### 2. The Shared Store Pattern
Nodes communicate through a shared dictionary:
- Success: `shared["content"] = result`
- Error: `shared["error"] = error_message`
- Actions returned: "default" for success, "error" for failure

### 3. Why This Matters for pflow
pflow is a CLI workflow tool where file operations are CORE functionality. Having proper retry behavior means:
- Temporary file locks get retried automatically
- Network file systems work better
- Race conditions are handled gracefully
- Users get better reliability

## References to Key Files

### PocketFlow Documentation
- `/Users/andfal/projects/pflow/pocketflow/docs/core_abstraction/node.md` - Node lifecycle
- `/Users/andfal/projects/pflow/pocketflow/__init__.py` - Core framework (100 lines)
- `/Users/andfal/projects/pflow/pocketflow/tests/test_fall_back.py` - Example of testing retry/fallback

### Anti-Pattern Document
The original anti-pattern document provided by the user details all patterns to avoid.

### Test File
- `/Users/andfal/projects/pflow/tests/test_file_nodes.py` - All file node tests (needs updating)

## Key Insights That Are Hard to Conceptualize

1. **The Double Return Pattern**: 
   - Old: `exec()` returns `(message, success_bool)`
   - New: `exec()` returns just the success value, `exec_fallback()` returns error message
   - `post()` must detect if the result is an error by checking `result.startswith("Error:")`

2. **NonRetriableError vs Regular Exceptions**:
   - NonRetriableError: For validation errors that will NEVER succeed (wrong type, missing confirmation)
   - Regular exceptions: For operations that might succeed on retry (file locked, permission temporary)

3. **The Lifecycle Change**:
   - Old: Call `prep()`, `exec()`, `post()` manually and handle errors
   - New: Call `node.run(shared)` which handles the full lifecycle including retries

4. **Why exec_fallback Returns String**:
   - It must return the same type as successful exec()
   - This gets passed to post() which checks if it's an error
   - This maintains the node interface contract

5. **Cross-Device Move Special Case**:
   - When moving across filesystems, it's copy+delete
   - If copy succeeds but delete fails, we return success with warning
   - This is the only case where we catch an exception in exec()

## Common Pitfalls to Avoid

1. **Don't catch exceptions in exec()** - Let them bubble up!
2. **Don't forget to import errno** where needed
3. **Remember NonRetriableError** for validation errors
4. **Test with node.run()** not individual methods
5. **Check for "Error:" prefix** in post() to detect failures

## The Philosophy

PocketFlow's design philosophy is:
- **Explicit over magic**: But retry IS the magic that makes it powerful
- **Separation of concerns**: exec() computes, post() handles results
- **Framework handles complexity**: Don't reinvent retry logic
- **Fail loudly**: Let exceptions bubble up for framework to handle

This refactoring aligns pflow with these principles and unlocks the power of automatic retries.