# Patterns Discovered

## Pattern: Safety Flags Must Come From Shared Store
**Context**: When you need to enforce safety for destructive operations
**Solution**: Check for the flag only in shared store, not params
**Why it works**: Prevents accidental operations from default parameters or config files
**When to use**: Any operation that could cause data loss or is irreversible
**Example**:
```python
# In prep() method
if "confirm_delete" not in shared:
    raise ValueError("Missing required 'confirm_delete' in shared store. "
                   "This safety flag must be explicitly set in shared store.")

confirm_delete = shared["confirm_delete"]
# Note: We do NOT fallback to self.params here
```

## Pattern: Cross-Device Move Handling
**Context**: When moving files might cross filesystem boundaries
**Solution**: Catch specific OSError and fallback to copy+delete
**Why it works**: shutil.move() raises OSError with "cross-device link" message
**When to use**: Any file move operation that could cross filesystems
**Example**:
```python
try:
    shutil.move(source_path, dest_path)
except OSError as e:
    if "cross-device link" in str(e).lower():
        # Handle cross-filesystem move
        return self._cross_device_move(source_path, dest_path)
    # Other OS errors are non-retryable
    return f"Error moving file: {e!s}", False
```

## Pattern: Partial Success with Warning
**Context**: When an operation partially succeeds but has a non-critical failure
**Solution**: Return success but store a warning in shared store
**Why it works**: Users get the primary benefit while being informed of issues
**When to use**: Multi-step operations where later steps are optional
**Example**:
```python
# In post() method
if success:
    shared["moved"] = message
    # Check if there's a warning in the message
    if "warning:" in message.lower():
        # Extract warning part
        warning_start = message.lower().find("warning:")
        shared["warning"] = message[warning_start:]
    return "default"
```
