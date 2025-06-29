# Cookbook Patterns for Subtask 5.1

## Relevant PocketFlow Examples

### 1. Minimal Node Implementation (pocketflow-hello-world)
**Location**: pocketflow/cookbook/pocketflow-hello-world/
**Pattern**: Simple node with clear prep/exec/post separation
**Application**: Use as template for test_node.py

```python
class TestNode(BaseNode):
    def prep(self, shared):
        """Prepare by reading input from shared store."""
        return shared.get("input", "default")

    def exec(self, input_data):
        """Process the input (pure computation)."""
        return f"Processed: {input_data}"

    def post(self, shared, prep_res, exec_res):
        """Store result in shared store."""
        shared["output"] = exec_res
```

### 2. Node with Retry Logic (pocketflow-node examples)
**Location**: pocketflow/cookbook/pocketflow-node/
**Pattern**: Node class adds retry capabilities
**Application**: Use for test_node_retry.py

```python
class TestNodeRetry(Node):  # Note: Node, not BaseNode
    # Same implementation, but with built-in retry logic
    def exec(self, input_data):
        """Process with potential for retry."""
        # Simulate work that might fail
        return f"Processed with retry support: {input_data}"
```

### 3. Proper Docstring Format
**Location**: Throughout cookbook examples
**Pattern**: Class and method docstrings for documentation
**Application**: Ensure test nodes have proper docstrings for scanner testing

```python
class ExampleNode(BaseNode):
    """
    Example node for testing scanner functionality.

    This node demonstrates proper docstring format that will be
    extracted by the scanner. It includes multiple lines and
    special characters to test edge cases.

    Interface:
    - Reads: shared["test_input"]
    - Writes: shared["test_output"]
    - Actions: default, error
    """
```

## Import Patterns from Cookbook

### Dynamic Module Loading Pattern
While not directly from cookbook, similar to how flows dynamically instantiate nodes:

```python
# Pattern for safe dynamic imports
def safe_import(module_path):
    try:
        return importlib.import_module(module_path)
    except ImportError as e:
        logger.warning(f"Failed to import {module_path}: {e}")
        return None
```

## Key Adaptations Needed

1. **Scanner doesn't create flows** - Just discovers and inspects classes
2. **No execution needed** - Only metadata extraction
3. **Focus on inheritance** - Detect BaseNode subclasses specifically
4. **Handle various import styles**:
   - `from pocketflow import BaseNode`
   - `import pocketflow` then `class X(pocketflow.BaseNode)`
   - `from pocketflow import BaseNode as Base`

## Testing Patterns from Cookbook

### Mock Node for Testing
Create nodes that test edge cases:

```python
# Node with no docstring (edge case)
class NoDocstringNode(BaseNode):
    pass

# Node with explicit name attribute
class NamedNode(BaseNode):
    """Node with explicit name."""
    name = "custom-name"

# Not a node (for negative testing)
class NotANode:
    """Regular class, not a node."""
    pass
```

## Security Considerations

Add clear warning as seen in pocketflow execution:

```python
# SECURITY WARNING: This function executes Python code via importlib.
# Only use with trusted source directories. In future versions with
# user-provided nodes, additional sandboxing will be required.
```
