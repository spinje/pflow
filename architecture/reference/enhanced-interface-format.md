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

#### Union Types

Union types allow you to specify that a value can be one of multiple types using the pipe (`|`) operator:

```python
# Basic union type
- Writes: shared["response"]: dict|str  # Response data (parsed JSON or raw text)

# Three-way union
- Writes: shared["result"]: dict|str|int  # Result value (varies by mode)

# Union with any
- Writes: shared["data"]: any|str  # Data of unknown structure or string
```

**Validation Behavior:**
- If ANY type in the union supports nested access (`dict`, `object`, `any`), nested template access is allowed
- Example: `dict|str` allows `${node.response.field}` because dict supports it
- Example: `str|int` rejects `${node.value.field}` because neither type supports nested access
- Unions containing `any` generate validation warnings for nested access

**Common Patterns:**
- `dict|str` - API responses (parsed JSON or raw text)
- `dict|list` - Flexible data structures
- `str|int` - Values that can be text or numeric
- `any|str` - Unknown structure with string fallback

**Naming Convention:**
- Use lowercase type names: `dict|str` ✅ not `Dict|Str` ❌
- No spaces around pipe: `dict|str` ✅ not `dict | str` ❌ (though both work)

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

## The Params Pattern

**Important**: All node inputs come from `self.params`. The template system handles wiring shared store data into params before execution.

### Example: Node Parameters

```python
Interface:
- Params: content: str  # Content to write (required)
- Params: file_path: str  # Destination file path (required)
- Params: append: bool  # Append mode (default: false)
- Writes: shared["success"]: bool  # True if written successfully
```

In this example:
- `content`, `file_path`, and `append` are all in Params
- The node reads from `self.params.get("content")`, `self.params.get("file_path")`, etc.
- Template variables like `${previous_node.output}` resolve into params before execution

## Structure Documentation

For complex types like `dict` and `list`, structure can be documented using indentation:

```python
Interface:
- Writes: shared["issue_data"]: dict  # GitHub issue information
    - number: int  # Issue number
    - title: str  # Issue title
    - user: dict  # Author information
      - login: str  # GitHub username
      - id: int  # User ID
    - labels: list  # Array of labels
      - name: str  # Label text
      - color: str  # Hex color code
```

### How Structure Documentation Works

The parser automatically detects indented structure definitions and extracts nested field information. When these structured outputs are displayed in planning contexts, they appear in a dual format optimized for LLM comprehension:

**Structure (JSON format):**
```json
{
  "issue_data": {
    "number": "int",
    "title": "str",
    "user": {
      "login": "str",
      "id": "int"
    },
    "labels": [
      {
        "name": "str",
        "color": "str"
      }
    ]
  }
}
```

**Available paths:**
- issue_data.number (int) - Issue number
- issue_data.title (str) - Issue title
- issue_data.user.login (str) - GitHub username
- issue_data.user.id (int) - User ID
- issue_data.labels[].name (str) - Label text
- issue_data.labels[].color (str) - Hex color code

This dual representation enables the workflow planner to:
1. **Understand data relationships** using the JSON structure
2. **Generate proxy mappings** by copying paths directly (e.g., `"author": "issue_data.user.login"`)

### Structure Documentation Rules

1. **Indentation is significant**: Use 2 or 4 spaces consistently
2. **Follow the same format**: `- field_name: type  # Description`
3. **Nest properly**: Child fields must be indented under their parent
4. **Support for lists**: Use `list` type and document item structure underneath
5. **Maximum depth**: Structures can be nested up to 5 levels deep

### Supported Structure Types

- **dict**: Object/dictionary structures with named fields
- **list**: Arrays where all items have the same structure
- **Primitive types**: str, int, float, bool (no further nesting)

### Example: Complete Node with Structures

```python
class GitHubIssueNode(Node):
    """
    Fetch GitHub issue data with full metadata.

    Interface:
    - Reads: shared["issue_number"]: int  # Issue number to fetch
    - Reads: shared["repo"]: str  # Repository name (owner/repo format)
    - Writes: shared["issue_data"]: dict  # Complete issue information
        - number: int  # Issue number
        - title: str  # Issue title
        - body: str  # Issue description
        - state: str  # Issue state (open, closed)
        - user: dict  # Issue author
          - login: str  # GitHub username
          - id: int  # User ID
          - avatar_url: str  # Profile picture URL
        - labels: list  # Issue labels
          - name: str  # Label name
          - color: str  # Label color (hex)
          - description: str  # Label description
        - milestone: dict  # Milestone info (may be null)
          - id: int  # Milestone ID
          - title: str  # Milestone title
          - due_on: str  # Due date (ISO format)
    - Writes: shared["error"]: str  # Error message if request failed
    - Params: include_comments: bool  # Include issue comments (default: false)
    - Actions: default (success), error (API error)
    """
```

This documentation will be parsed and displayed in the planning context as both JSON structure and available paths, enabling accurate workflow generation.

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

The current parser has some known limitations that you should be aware of:

### Critical Limitations

1. **Single quotes not supported**: Use `shared["key"]` ✅, not `shared['key']` ❌
   ```python
   # Works
   - Reads: shared["file_path"]: str  # File path

   # Breaks parser
   - Reads: shared['file_path']: str  # File path
   ```

2. **Empty components break parser**: Always include content after declarations
   ```python
   # Breaks parser
   - Reads:
   - Writes: shared["data"]: str

   # Works
   - Reads: shared["input"]: str  # Input data
   - Writes: shared["data"]: str  # Output data
   ```

3. **Commas in descriptions can break parsing**: Use alternative phrasing
   ```python
   # May break
   - Reads: shared["config"]: dict  # Config object, with settings, and defaults

   # Better
   - Reads: shared["config"]: dict  # Config object with settings and defaults
   ```

### Minor Limitations

4. **Very long lines**: Lines over 1000 characters may hit regex limits
5. **Indentation must be consistent**: Use 2 or 4 spaces consistently within a structure
6. **Maximum nesting depth**: Structures support up to 5 levels of nesting

### Workarounds and Best Practices

- **For commas**: Use "and" or rephrase to avoid comma-separated lists in descriptions
- **For quotes**: Always use double quotes in `shared["key"]` syntax
- **For empty sections**: Include at least one item or omit the section entirely
- **For long descriptions**: Break into multiple sentences or use simpler language

### What Works Reliably

The parser handles these cases well:
- Multi-line interface sections
- Nested structures up to 5 levels deep
- All supported types (str, int, float, bool, dict, list)
- Unicode characters in descriptions
- Mixed simple and enhanced format in the same interface

These limitations are well-documented and the parser works reliably for normal use cases. The enhanced format provides significant value despite these constraints.

## Current Features Summary

✅ **Implemented in Current Version:**
- Enhanced interface format with type annotations
- Multi-line interface documentation
- **Full structure parsing** for nested dict and list types
- **Structure display** in dual JSON + paths format for planning contexts
- Exclusive params pattern (params not in Reads)
- Parser support for all basic types (str, int, float, bool, dict, list)

## Future Enhancements

The following features are planned for future versions:

1. **Type validation**: Validate that types are valid Python types at parse time
2. **Enum types**: Support for enumerated values like `Literal['fast', 'slow']`
3. **Optional syntax**: Explicit `Optional[str]` syntax for optional parameters
4. **Custom types**: Support for domain-specific types
5. **Parser improvements**: Better error messages and more flexible quote handling

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
