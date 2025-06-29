# Patterns Discovered

## Pattern: Reserved Logging Field Names
**Context**: When you need to add structured logging with extra fields
**Solution**: Avoid using reserved field names that conflict with LogRecord attributes
**Why it works**: Python's logging module has built-in attributes like 'module', 'filename', 'funcName' that cannot be overridden
**When to use**: Always when adding extra dict to logging calls
**Example**:
```python
# BAD - will raise KeyError
logger.debug("message", extra={"module": module_path})

# GOOD - use a different field name
logger.debug("message", extra={"module_path": module_path})
```

## Pattern: Type Annotations for Dynamic Imports
**Context**: When dynamically importing classes and need type safety
**Solution**: Use `cast()` from typing module to satisfy mypy
**Why it works**: Dynamic imports return Any type, but we know the type after validation
**When to use**: After verifying inheritance/type of dynamically imported objects
**Example**:
```python
from typing import cast

# After validating with issubclass()
if not issubclass(node_class, BaseNode):
    raise Error(...)

# Cast to satisfy mypy
return cast(type[BaseNode], node_class)
```

## Pattern: Exception Chaining for Better Debugging
**Context**: When re-raising exceptions with additional context
**Solution**: Use `from e` or `from None` in raise statements
**Why it works**: Preserves original traceback or explicitly suppresses it
**When to use**: Always when catching and re-raising exceptions
**Example**:
```python
try:
    module = importlib.import_module(path)
except ImportError as e:
    # Preserve original traceback
    raise CustomError("Failed to import") from e

try:
    value = getattr(obj, name)
except AttributeError:
    # Suppress original traceback (it's not helpful)
    raise CustomError("Attribute not found") from None
```
