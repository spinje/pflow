# Cookbook Patterns for Subtask 11.1

## Relevant PocketFlow Cookbook Examples

### 1. Tutorial-Cursor File Operations (Primary Reference)
**Location**: `pocketflow/cookbook/Tutorial-Cursor/utils/`

**Key Patterns**:
- File operations return `(result, success_bool)` tuples
- Comprehensive error handling with descriptive messages
- Line number formatting for display
- Directory creation for write operations

**Applicable Code Pattern**:
```python
def read_file(target_file: str) -> Tuple[str, bool]:
    try:
        if not os.path.exists(target_file):
            return f"Error: File {target_file} does not exist", False

        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
            formatted_lines = [f"{i+1}: {line}" for i, line in enumerate(lines)]
            return '\n'.join(formatted_lines), True
    except Exception as e:
        return f"Error reading file: {str(e)}", False
```

### 2. Node Lifecycle Pattern (Multiple Examples)
**Location**: Throughout cookbook examples

**Key Pattern**: Separation of concerns in node methods
```python
class FileNode(Node):
    def prep(self, shared):
        # Validate inputs from shared store
        file_path = shared.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path'")
        return file_path

    def exec(self, file_path):
        # Pure computation - file operation
        return read_file(file_path)  # Returns (content, success)

    def post(self, shared, prep_res, exec_res):
        # Update shared store based on result
        content, success = exec_res
        if success:
            shared["content"] = content
            return "default"
        else:
            shared["error"] = content
            return "error"
```

### 3. Error Handling Patterns
**Location**: Various cookbook examples

**Patterns Found**:
1. **Graceful Degradation**: Return error action instead of raising
2. **Retry Logic**: Use Node base class for automatic retries
3. **Detailed Context**: Include file paths and operation type in errors

### 4. Shared Store Conventions
**Location**: Communication examples

**Key Patterns**:
- Natural key names: `file_path`, `content`, `encoding`
- Check shared store first, params second
- Store both success and error states in shared

## Adaptation Strategy for pflow

### 1. Combine Tuple Pattern with Node Actions
- Use Tutorial-Cursor's tuple return in `exec()`
- Convert success/failure to actions in `post()`
- Store appropriate data in shared store

### 2. Line Number Formatting
- Apply Tutorial-Cursor's line numbering approach
- Use 1-based indexing for user-friendliness
- Format as "line_number: content"

### 3. Error Message Standards
- Include file path in all error messages
- Specify the operation that failed
- Provide actionable information

### 4. Directory Handling
- Use `os.makedirs(exist_ok=True)` pattern
- Handle both absolute and relative paths
- Don't assume working directory

## Implementation Checklist

Based on cookbook analysis:
- [ ] Implement tuple return pattern in exec methods
- [ ] Add line numbers to read-file output
- [ ] Create parent directories for write-file
- [ ] Use UTF-8 encoding by default
- [ ] Support encoding parameter from shared store
- [ ] Handle missing files gracefully
- [ ] Provide detailed error messages
- [ ] Follow Node class retry pattern
- [ ] Document security considerations
- [ ] Test with tempfile as shown in examples
