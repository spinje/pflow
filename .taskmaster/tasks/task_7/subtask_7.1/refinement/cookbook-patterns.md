# PocketFlow Cookbook Patterns for Subtask 7.1

## Relevant Patterns from PocketFlow Analysis

### 1. Node Inheritance Validation Pattern

**From**: PocketFlow core framework understanding

**Pattern**: Check inheritance using `issubclass()` with proper error handling
```python
import pocketflow

def is_node_class(cls):
    try:
        return issubclass(cls, pocketflow.BaseNode)
    except TypeError:
        # Not a class or other type error
        return False
```

**Application**: Use this pattern to validate input before processing

### 2. Safe Attribute Access Pattern

**From**: General Python best practices seen in cookbook examples

**Pattern**: Use `getattr()` with defaults for safe attribute access
```python
# Safe docstring extraction
docstring = inspect.getdoc(node_class) or ""

# Safe class name extraction
class_name = getattr(node_class, '__name__', 'UnknownNode')
```

**Application**: Prevents AttributeError when accessing class properties

### 3. Class vs Instance Detection

**From**: Type checking patterns in framework

**Pattern**: Use `inspect.isclass()` to ensure we have a class, not instance
```python
import inspect

if not inspect.isclass(node_class):
    raise ValueError("Expected a class, got an instance")
```

**Application**: Early validation prevents confusing errors later

### 4. Description Extraction Pattern

**From**: Common docstring handling in Python

**Pattern**: Extract first line, handling edge cases
```python
def extract_description(docstring):
    if not docstring:
        return "No description"

    # Split into lines and get first non-empty line
    lines = docstring.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line:
            return line

    return "No description"
```

**Application**: Robust extraction of description from various docstring formats

### 5. Module Import Context Pattern

**From**: Task 5's scanner implementation

**Pattern**: When working with dynamically imported classes, maintain import context
```python
# The class already has its module context
module_name = node_class.__module__
class_name = node_class.__name__
# Can be used for error messages or logging
```

**Application**: Helpful for debugging and error messages

## Testing Patterns

### 1. Real Import Testing

**From**: Task 5 lessons about mocking limitations

**Pattern**: Test with actual imports rather than mocks
```python
def test_real_node():
    from src.pflow.nodes.file.read_file import ReadFileNode
    metadata = extractor.extract_metadata(ReadFileNode)
    assert metadata['description'] == "Read file contents from the filesystem."
```

**Application**: Ensures extractor works with real-world nodes

### 2. Edge Case Coverage

**From**: Previous task reviews emphasizing comprehensive testing

**Pattern**: Test all variations systematically
```python
# Test cases to cover:
# - Valid Node subclass
# - Valid BaseNode subclass
# - Class without docstring
# - Non-node class
# - None input
# - Instance instead of class
# - Empty docstring
# - Multiline docstring
```

**Application**: Prevents surprises in production usage
