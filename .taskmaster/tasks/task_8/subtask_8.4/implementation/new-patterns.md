# Patterns Discovered

## Pattern: Enhanced API Alongside Legacy
**Context**: When you need to enhance an existing API with new functionality that changes return types or behavior
**Solution**: Create a new function with "_enhanced" suffix that provides the new functionality while keeping the original function unchanged
**Why it works**: Preserves backward compatibility while allowing new features
**When to use**: Any time you need to change an API's return type or add breaking changes
**Example**:
```python
# Original function - keep unchanged
def read_stdin() -> str | None:
    """Original API - returns text only."""
    # ... original implementation

# Enhanced function - new functionality
def read_stdin_enhanced() -> StdinData | None:
    """Enhanced API - handles binary and large files."""
    # ... new implementation with richer return type
```

## Pattern: Stream Peek-Ahead Detection
**Context**: When processing streaming data where you need to decide handling strategy based on total size
**Solution**: Read up to threshold, then peek one more byte to detect if more data exists
**Why it works**: Avoids loading entire stream into memory just to check size
**When to use**: Large file detection, streaming data classification
**Example**:
```python
# Read up to limit
chunks = []
while total_size < max_size:
    chunk = stream.read(chunk_size)
    if not chunk:
        break
    chunks.append(chunk)
    total_size += len(chunk)

# Peek to see if there's more
peek = stream.read(1)
if peek:
    # More data exists - switch to streaming mode
    handle_large_file(chunks, peek, stream)
else:
    # All data fits in memory
    handle_small_file(chunks)
```

## Pattern: Multi-Level Resource Cleanup
**Context**: When creating temporary resources that must be cleaned up even if errors occur
**Solution**: Use try/finally blocks at both creation and usage points
**Why it works**: Ensures cleanup happens regardless of error location
**When to use**: Temp files, network connections, any resource that needs cleanup
**Example**:
```python
# Level 1: Creation with cleanup
temp_file = tempfile.NamedTemporaryFile(delete=False)
try:
    # Use temp file
    temp_file.write(data)
    temp_file.close()
    return temp_file.name
except Exception:
    # Cleanup on creation error
    temp_file.close()
    try:
        os.unlink(temp_file.name)
    except OSError:
        pass
    raise

# Level 2: Usage with cleanup
try:
    # Use the resource
    process_file(temp_path)
finally:
    # Cleanup after usage
    try:
        os.unlink(temp_path)
    except OSError:
        pass
```
