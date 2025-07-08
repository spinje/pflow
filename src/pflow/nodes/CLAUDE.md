# Node Implementation Guide

This directory contains all pflow nodes. **CRITICAL**: All nodes MUST follow the PocketFlow retry pattern.

## 🚨 Critical Pattern: PocketFlow Node Error Handling

**This is non-negotiable** - violating this pattern disables automatic retries, severely impacting reliability.

### The Pattern

```python
from pocketflow import Node  # NOT BaseNode!
from .exceptions import NonRetriableError

class ExampleNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=0.1)
    
    def prep(self, shared: dict) -> Any:
        """Validate inputs and prepare for execution."""
        # Validation logic here
        return prep_data
    
    def exec(self, prep_res: Any) -> Any:
        """Execute main logic - NO try/except blocks!"""
        # Let ALL exceptions bubble up for retry mechanism
        result = some_operation()  # If this fails, it will retry
        return result  # Only return success value
    
    def exec_fallback(self, prep_res: Any, exc: Exception) -> Any:
        """Handle errors AFTER all retries exhausted."""
        if isinstance(exc, SpecificError):
            return "Error: Specific error message"
        else:
            return f"Error: Operation failed: {exc!s}"
    
    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
        """Process results and determine next action."""
        if isinstance(exec_res, str) and exec_res.startswith("Error:"):
            shared["error"] = exec_res
            return "error"
        else:
            shared["result"] = exec_res
            return "default"
```

### Key Rules

1. **NO try/except in exec()** - Let exceptions bubble up!
2. **Use NonRetriableError** for validation errors that shouldn't retry
3. **Return only success values** from exec()
4. **Handle errors in exec_fallback()** after retries exhausted
5. **Check for errors in post()** by looking for "Error:" prefix

### Examples

#### ✅ CORRECT - Enables Retry
```python
def exec(self, prep_res):
    file_path = prep_res
    # No try/except - exceptions bubble up!
    with open(file_path) as f:
        return f.read()
```

#### ❌ WRONG - Breaks Retry
```python
def exec(self, prep_res):
    file_path = prep_res
    try:
        with open(file_path) as f:
            return f.read()
    except Exception as e:
        # This prevents retry!
        return f"Error: {e}"
```

### Testing Retry Behavior

Always test that your nodes retry correctly:

```python
def test_node_retries_on_failure():
    node = YourNode()
    shared = {"input": "test"}
    
    with patch("some.operation") as mock_op:
        # Fail twice, then succeed
        mock_op.side_effect = [
            Exception("Temporary failure"),
            Exception("Still failing"),
            "Success!"
        ]
        
        action = node.run(shared)
        
        assert action == "default"
        assert mock_op.call_count == 3
```

## Node Categories

- **file/** - File operations (read, write, copy, move, delete)
- **llm/** - Language model interactions
- **data/** - Data processing and transformation
- **network/** - HTTP requests and API calls
- **system/** - System operations

## Creating New Nodes

1. Copy the pattern above
2. Inherit from `Node` (not `BaseNode`)
3. NO try/except in exec()
4. Use `NonRetriableError` for validation failures
5. Test retry behavior
6. Document parameters in docstrings

## Common Mistakes

1. **Catching exceptions in exec()** - This is the #1 anti-pattern!
2. **Returning error tuples** - Return only success values
3. **Forgetting exec_fallback()** - Needed for error messages
4. **Not testing retries** - Always verify retry behavior

## References

- Full pattern documentation: `/.taskmaster/knowledge/patterns.md` - "PocketFlow Node Error Handling"
- Anti-pattern to avoid: `/.taskmaster/knowledge/pitfalls.md` - "Catching Exceptions in exec()"
- Architectural decision: `/.taskmaster/knowledge/decisions.md` - "All pflow Nodes Must Follow PocketFlow Retry Pattern"
- PocketFlow documentation: `/pocketflow/docs/core_abstraction/node.md`

## Quick Checklist

Before committing any node:

- [ ] Inherits from `Node` (not `BaseNode`)?
- [ ] No try/except blocks in `exec()`?
- [ ] Returns only success values from `exec()`?
- [ ] Has `exec_fallback()` for error handling?
- [ ] Uses `NonRetriableError` for validation errors?
- [ ] Tests verify retry behavior?
- [ ] `post()` checks for "Error:" prefix?

Remember: **Let exceptions bubble up!** The framework handles retries for you.