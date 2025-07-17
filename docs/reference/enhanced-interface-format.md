# Enhanced Interface Format Specification

This document provides the complete specification for the Enhanced Interface Format used in pflow nodes. The enhanced format adds type annotations and semantic descriptions to node interfaces, enabling better understanding by the workflow planner.

## Overview

The Enhanced Interface Format extends the original simple format with:
- **Type annotations** for all inputs, outputs, and parameters
- **Semantic descriptions** using inline comments
- **Multi-line support** for better readability
- **Structure hints** for complex types (future enhancement)

## Format Syntax

### Basic Structure

```python
"""
Node description here.

Interface:
- Reads: shared["key"]: type  # Description
- Writes: shared["key"]: type  # Description
- Params: param: type  # Description
- Actions: action_name (description)
"""
```

### Type Annotations

All components support type annotations using Python's built-in types:

#### Supported Types
- `str` - String values
- `int` - Integer numbers
- `float` - Floating-point numbers
- `bool` - Boolean values (true/false)
- `dict` - Dictionary/object structures
- `list` - List/array structures
- `any` - Any type (default when not specified)

#### Type Syntax
```python
# Input with type
- Reads: shared["file_path"]: str

# Output with type
- Writes: shared["result"]: dict

# Parameter with type
- Params: timeout: int
```

### Semantic Descriptions

Descriptions are added using `#` comments after the type:

```python
# Basic description
- Reads: shared["file_path"]: str  # Path to the file to read

# Description with details
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)

# Complex description with punctuation
- Writes: shared["data"]: str  # Data: formatted as "key: value" pairs

# Description with valid values
- Params: mode: str  # Processing mode ('fast', 'accurate', or 'balanced')
```

### Multi-line Format

Each input, output, or parameter can be on its own line for clarity:

```python
Interface:
- Reads: shared["config"]: dict  # Configuration object
- Reads: shared["data"]: list  # Data array to process
- Reads: shared["mode"]: str  # Processing mode
- Writes: shared["results"]: list  # Processed results
- Writes: shared["stats"]: dict  # Processing statistics
- Writes: shared["error"]: str  # Error message if failed
- Params: validate: bool  # Validate input data (default: true)
- Actions: default (success), error (failure)
```

### Single-line Format (Backward Compatible)

Multiple items can still be comma-separated on one line:

```python
Interface:
- Reads: shared["x"]: int, shared["y"]: int  # Coordinates
- Writes: shared["sum"]: int, shared["product"]: int  # Results
```

## The Exclusive Params Pattern

**Important**: Parameters that are already listed in `Reads` should NOT be repeated in `Params`. Every input is automatically available as a parameter fallback.

### Example: Exclusive Parameters

```python
Interface:
- Reads: shared["content"]: str  # Content to write
- Reads: shared["file_path"]: str  # Destination file path
- Writes: shared["success"]: bool  # True if written successfully
- Params: append: bool  # Append mode (default: false)
# Note: content and file_path are NOT in Params - they're automatic fallbacks!
```

In this example:
- `content` and `file_path` are inputs AND automatic parameter fallbacks
- Only `append` is listed in Params because it's not an input
- The node can be called with `params={"file_path": "...", "content": "...", "append": True}`

## Structure Documentation (Future Enhancement)

For complex types like `dict` and `list`, structure can be documented using indentation:

```python
Interface:
- Writes: shared["issue_data"]: dict  # GitHub issue information
    - number: int  # Issue number
    - title: str  # Issue title
    - user: dict  # Author information
      - login: str  # GitHub username
      - id: int  # User ID
    - labels: list[dict]  # Array of labels
      - name: str  # Label text
      - color: str  # Hex color code
```

**Note**: Structure parsing is not yet implemented. The parser currently recognizes `dict` and `list` types and sets a `_has_structure` flag, but does not parse the indented structure details.

## Migration from Simple Format

### Old Format
```python
Interface:
- Reads: shared["input1"], shared["input2"]
- Writes: shared["output"], shared["error"]
- Params: input1, input2, extra_param
- Actions: default, error
```

### Enhanced Format
```python
Interface:
- Reads: shared["input1"]: str  # First input value
- Reads: shared["input2"]: int  # Second input value
- Writes: shared["output"]: dict  # Processing result
- Writes: shared["error"]: str  # Error message if failed
- Params: extra_param: bool  # Additional parameter (not in Reads)
- Actions: default (success), error (failure)
```

## Best Practices

### 1. Always Add Types
Even for simple string values, explicitly add `: str` for clarity:
```python
# Good
- Reads: shared["name"]: str  # User's name

# Avoid
- Reads: shared["name"]  # Will default to 'any' type
```

### 2. Write Clear Descriptions
Focus on semantics, not just the type:
```python
# Good
- Reads: shared["timeout"]: int  # Request timeout in seconds

# Too vague
- Reads: shared["timeout"]: int  # Timeout value
```

### 3. Document Valid Values
When applicable, mention valid values or ranges:
```python
- Reads: shared["priority"]: int  # Task priority (1-5, higher is more urgent)
- Writes: shared["status"]: str  # Status code ('pending', 'running', 'complete', 'failed')
```

### 4. Use Multi-line for Clarity
When you have more than 2-3 items, use multi-line format:
```python
# Good - Easy to read
Interface:
- Reads: shared["source"]: str  # Source file path
- Reads: shared["target"]: str  # Target file path
- Reads: shared["overwrite"]: bool  # Overwrite if exists
- Writes: shared["copied"]: bool  # True if successful
- Writes: shared["error"]: str  # Error message if failed

# Harder to read
Interface:
- Reads: shared["source"]: str  # Source file path, shared["target"]: str  # Target file path, shared["overwrite"]: bool  # Overwrite if exists
```

### 5. Apply Exclusive Params Pattern
Only list parameters that aren't already inputs:
```python
# Good - Only exclusive params
Interface:
- Reads: shared["data"]: str  # Data to process
- Params: format: str  # Output format ('json' or 'xml')

# Redundant - Avoid
Interface:
- Reads: shared["data"]: str  # Data to process
- Params: data: str, format: str  # data is redundant!
```

## Common Patterns

### File Operations
```python
Interface:
- Reads: shared["file_path"]: str  # Path to the file
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents
- Writes: shared["error"]: str  # Error message if operation failed
- Actions: default (success), error (failure)
```

### API Calls
```python
Interface:
- Reads: shared["endpoint"]: str  # API endpoint URL
- Reads: shared["method"]: str  # HTTP method (GET, POST, etc.)
- Reads: shared["data"]: dict  # Request payload (optional)
- Writes: shared["response"]: dict  # API response data
- Writes: shared["status_code"]: int  # HTTP status code
- Writes: shared["error"]: str  # Error message if request failed
- Params: timeout: int  # Request timeout in seconds (default: 30)
- Actions: default (success), error (failure)
```

### Data Processing
```python
Interface:
- Reads: shared["input_data"]: list  # Data to process
- Reads: shared["config"]: dict  # Processing configuration
- Writes: shared["results"]: list  # Processed results
- Writes: shared["metrics"]: dict  # Processing metrics
- Params: batch_size: int  # Processing batch size (default: 100)
- Actions: default
```

## Parser Limitations

The current parser has some known limitations:

1. **Empty components**: Empty lines like `- Reads:` with no content may cause parsing issues
2. **Very long lines**: Extremely long lines may not parse correctly
3. **Malformed syntax**: Invalid enhanced format may produce unexpected results
4. **Structure parsing**: Indented structure documentation is recognized but not yet parsed

These limitations are acceptable for the MVP as the parser works well for normal use cases.

## Future Enhancements

The following features are planned for future versions:

1. **Full structure parsing**: Parse and validate nested structure documentation
2. **Type validation**: Validate that types are valid Python types
3. **Enum types**: Support for enumerated values like `Literal['fast', 'slow']`
4. **Optional syntax**: Explicit `Optional[str]` syntax for optional parameters
5. **Custom types**: Support for domain-specific types

## Examples

### Complete Node Example

```python
class ProcessDataNode(pocketflow.Node):
    """
    Process data with configurable options.

    Interface:
    - Reads: shared["input_file"]: str  # Path to input data file
    - Reads: shared["output_dir"]: str  # Output directory path
    - Reads: shared["config"]: dict  # Processing configuration
    - Writes: shared["processed_file"]: str  # Path to processed file
    - Writes: shared["statistics"]: dict  # Processing statistics
    - Writes: shared["error"]: str  # Error message if processing failed
    - Params: validate: bool  # Validate input before processing (default: true)
    - Params: compress: bool  # Compress output file (default: false)
    - Actions: default (success), error (failure)
    """

    def exec(self, prep_res):
        # Implementation here
        pass
```

This example demonstrates:
- Multiple inputs with different types
- Clear semantic descriptions
- Exclusive parameters (not repeating inputs)
- Proper action documentation

## Validation

To validate your Interface format:

1. **Parser test**: The metadata extractor will parse your format
2. **Context builder**: Check how your node appears in the planning context
3. **Integration test**: Verify the planner can use your type information

## Summary

The Enhanced Interface Format provides a clear, type-safe way to document node interfaces. By following this specification, you ensure that:
- The workflow planner understands your node's data types
- Other developers can easily understand your node's interface
- The system can provide better error messages and validation
- Future enhancements can build on this foundation
