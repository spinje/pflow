# Cookbook Patterns for Subtask 4.2

## Relevant PocketFlow Patterns

### 1. Dynamic Import Pattern
**Source**: `pocketflow/cookbook/pocketflow-visualization/visualize.py`
**Pattern**: Using importlib for dynamic module loading
```python
module = importlib.import_module(module_path)
flow = getattr(module, flow_variable)
```
**Application**: This exact pattern applies to our node class loading
**Adaptation**: We'll check inheritance after getting the class

### 2. Error Handling for Dynamic Imports
**Source**: Various cookbook examples
**Pattern**: Catch specific exceptions, not broad Exception
```python
try:
    module = importlib.import_module(module_path)
except ImportError as e:
    # Handle missing module
```
**Application**: We'll catch ImportError and AttributeError separately
**Enhancement**: Add CompilationError with rich context

### 3. Type Checking Pattern
**Source**: Multiple cookbook examples checking Flow types
**Pattern**: Use isinstance() or issubclass() for type validation
```python
if not isinstance(obj, Flow):
    raise ValueError("Not a Flow")
```
**Application**: We'll use issubclass(cls, BaseNode) for validation
**Note**: Check against BaseNode, not Node, for maximum compatibility

## Patterns NOT Applicable

### Factory Pattern
- PocketFlow nodes are instantiated directly, not through factories
- We return the class, not create instances

### Context Manager Pattern
- Used in Task 5 for sys.path manipulation
- Not needed here since we have full module paths from registry

## Key Insights from Cookbook

1. **Simplicity First**: PocketFlow examples favor direct, simple approaches
2. **Natural Errors**: Let Python's import machinery provide natural error messages
3. **No Over-Validation**: Trust that properly inherited nodes will work
4. **Direct Usage**: No wrapper patterns - use pocketflow classes directly
