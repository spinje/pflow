# Patterns Discovered

## Pattern: Truthiness-Safe Parameter Fallback
**Context**: When you need to support valid falsy values (empty string, 0, False) in parameters
**Solution**: Check for key existence explicitly instead of using `or` operator
**Why it works**: Python's `or` treats empty strings, 0, False as falsy, causing incorrect fallbacks
**When to use**: Always when dealing with parameters that could have valid falsy values
**Example**:
```python
# WRONG - treats empty string as missing
content = shared.get("content") or self.params.get("content")

# CORRECT - properly handles empty string
if "content" in shared:
    content = shared["content"]
elif "content" in self.params:
    content = self.params["content"]
else:
    raise ValueError("Missing required 'content'")
```

## Pattern: Retryable vs Non-Retryable Errors
**Context**: When implementing Node.exec() with retry logic
**Solution**: Return tuple for non-retryable errors, raise exception for retryable ones
**Why it works**: Node base class catches exceptions and retries, but tuple returns exit immediately
**When to use**: File operations, network requests, any operation with transient failures
**Example**:
```python
def exec(self, prep_res):
    try:
        # File missing is not retryable - return error tuple
        if not os.path.exists(file_path):
            return f"Error: File {file_path} does not exist", False

        # Permission error is not retryable
        with open(file_path, 'r') as f:
            content = f.read()
    except PermissionError:
        return f"Error: Permission denied", False
    except Exception as e:
        # Other errors might be transient - raise for retry
        raise RuntimeError(f"Error reading file: {str(e)}")
```

## Pattern: Line Number Display Formatting
**Context**: When displaying file contents for human readability and debugging
**Solution**: Add 1-indexed line numbers with consistent formatting
**Why it works**: Matches user expectations (editors use 1-indexing) and aids debugging
**When to use**: Any time you display multi-line content from files
**Example**:
```python
# Read file lines
with open(file_path, 'r') as f:
    lines = f.readlines()

# Add 1-indexed line numbers
numbered_lines = [f"{i+1}: {line}" for i, line in enumerate(lines)]
content = ''.join(numbered_lines)
```
