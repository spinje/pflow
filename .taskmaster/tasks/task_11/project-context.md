# Project Context for Task 11: Implement File I/O Nodes

## Task Overview
Implement basic file I/O nodes for the pflow system that enable reading, writing, and manipulating files through the PocketFlow framework. These nodes will serve as fundamental building blocks for file-based workflows.

## Core Requirements
Create five file operation nodes in `src/pflow/nodes/file/`:
- `read_file.py` - Read file contents into shared store
- `write_file.py` - Write content from shared store to files
- `copy_file.py` - Copy files between locations
- `move_file.py` - Move files between locations
- `delete_file.py` - Delete files with safety checks

Each node must:
- Inherit from `pocketflow.BaseNode`
- Follow the prep→exec→post lifecycle
- Use natural shared store keys
- Include safety checks for destructive operations
- Fail fast with clear error messages
- Have comprehensive unit tests

## PocketFlow Framework Understanding

### BaseNode Lifecycle
Nodes inherit from `BaseNode` and implement three methods:
1. **`prep(self, shared)`** - Read from shared store, validate inputs
2. **`exec(self, prep_res)`** - Pure computation, no side effects
3. **`post(self, shared, prep_res, exec_res)`** - Write results to shared store, return action

### Node Class Hierarchy
- **BaseNode**: Basic node without retry capabilities
- **Node**: Extends BaseNode with retry logic and fallback handling
- For MVP, inherit from `Node` to get retry capabilities

### Communication Pattern
All inter-node communication happens through the shared store:
```python
# In prep(): Read inputs
file_path = shared.get("file_path")

# In post(): Write outputs
shared["content"] = file_content
return "default"  # or "error" for failures
```

## Simple Node Architecture Pattern

### Design Principles
1. **Single Responsibility**: Each node does exactly one thing
2. **No Internal Routing**: No action dispatch or complex logic
3. **Predictable Interfaces**: Clear, documented inputs/outputs
4. **Isolation**: Nodes have no awareness of other nodes
5. **Fail Fast**: Clear errors on missing required inputs

### Interface Documentation
Each node must have a comprehensive docstring:
```python
"""
Brief description of the node.

Extended explanation of functionality.

Interface:
- Reads: shared["key"] - description
- Writes: shared["key"] - description
- Actions: default, error
- Params: param_name - description (optional)
"""
```

## Shared Store Conventions

### Natural Key Names for File Operations
- `shared["file_path"]` - Path to file
- `shared["content"]` - File contents
- `shared["text"]` - Alternative for text content
- `shared["source_path"]` - Source for copy/move
- `shared["dest_path"]` - Destination for copy/move
- `shared["encoding"]` - File encoding (default: utf-8)

### Best Practices
1. Check shared store first, then params:
   ```python
   file_path = shared.get("file_path") or self.params.get("path")
   ```
2. Use descriptive keys that self-document
3. Store errors in shared for downstream handling
4. Validate all inputs in prep()

## Implementation Patterns from Cookbook

### File Operation Patterns (Tutorial-Cursor)
The cookbook provides production-ready file utilities:

1. **Error Handling**: Return tuples `(result, success_bool)`
2. **Encoding**: Always specify UTF-8 for text files
3. **Path Handling**: Support both absolute and relative paths
4. **Directory Creation**: Use `os.makedirs(exist_ok=True)`
5. **Line Numbers**: When displaying content, prepend line numbers
6. **Validation**: Check existence before operations
7. **Graceful Failures**: Provide clear error messages

### Example Pattern
```python
class ReadFileNode(Node):
    def prep(self, shared):
        file_path = shared.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path' in shared store")
        return file_path

    def exec(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read(), True
        except Exception as e:
            return str(e), False

    def post(self, shared, prep_res, exec_res):
        content, success = exec_res
        if success:
            shared["content"] = content
            return "default"
        else:
            shared["error"] = content
            return "error"
```

## Applied Knowledge from Previous Tasks

### Patterns to Apply
1. **Test-As-You-Go Development**: Write tests immediately with implementation
2. **Graceful Error Handling**: Handle missing files, permissions, encoding errors
3. **Structured Logging**: Use phase tracking for debugging
4. **Foundation-Integration-Polish**: Decompose into logical phases

### Architectural Decisions
1. Use traditional Python functions for file operations (not PocketFlow internally)
2. Keep implementations simple and accessible
3. Tests and code must be committed together
4. Follow existing node patterns from test_node.py

### Common Pitfalls to Avoid
1. Don't use "filename" in logging extra dict (use "file_path")
2. Ensure comprehensive error handling for all edge cases
3. Don't create separate test tasks - integrate testing

## Node-Specific Requirements

### read-file Node
- Interface: `shared["file_path"]` → `shared["content"]`
- Handle missing files gracefully
- Support encoding parameter
- Add line numbers for debugging

### write-file Node
- Interface: `shared["content"]` + `shared["file_path"]`
- Create directories if needed
- Support append mode via params
- Validate content before writing

### copy-file Node
- Interface: `shared["source_path"]` + `shared["dest_path"]`
- Verify source exists
- Handle directory creation
- Preserve file attributes

### move-file Node
- Interface: `shared["source_path"]` + `shared["dest_path"]`
- Atomic operation when possible
- Fallback to copy+delete
- Safety checks for overwrites

### delete-file Node
- Interface: `shared["file_path"]`
- Confirm file exists
- Safety parameter for confirmation
- Clear error on missing file

## Testing Requirements
- Test all file operations thoroughly
- Include permission error handling
- Test safety validations
- Verify fail-fast behavior
- Test with various file types and sizes
- Include edge cases (empty files, special characters)

## Documentation References
These documents are essential for implementation:
- `docs/features/simple-nodes.md` - Simple node architecture pattern
- `docs/core-concepts/shared-store.md` - Shared store conventions
- `pocketflow/docs/core_abstraction/node.md` - Node lifecycle details
- `pocketflow/cookbook/Tutorial-Cursor/utils/` - File operation examples

## Key Implementation Considerations
1. All nodes must be discoverable by the registry scanner
2. Follow kebab-case naming convention (class name conversion)
3. Include comprehensive docstrings for scanner extraction
4. Use `Node` base class for retry capabilities
5. Return appropriate action strings for flow control
6. Maintain consistency with existing platform nodes
