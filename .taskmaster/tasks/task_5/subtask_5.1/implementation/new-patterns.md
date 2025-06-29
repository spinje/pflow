# Patterns Discovered

## Pattern: Context Manager for Dynamic sys.path Modification
**Context**: When you need to temporarily modify sys.path for dynamic imports
**Solution**: Use a context manager to ensure clean state restoration
**Why it works**: Guarantees sys.path is restored even if exceptions occur
**When to use**: Any time you need temporary path modifications for imports
**Example**:
```python
@contextmanager
def temporary_syspath(paths: List[Path]):
    """Temporarily add paths to sys.path for imports."""
    original_path = sys.path.copy()
    try:
        # Add paths at the beginning for priority
        for path in reversed(paths):
            sys.path.insert(0, str(path))
        yield
    finally:
        sys.path = original_path
```

## Pattern: Two-Tier Naming Strategy
**Context**: When you need flexible naming for dynamically discovered components
**Solution**: Check for explicit attribute first, then apply automatic conversion
**Why it works**: Provides both control and convenience
**When to use**: Any plugin/node discovery system where naming matters
**Example**:
```python
def get_node_name(cls) -> str:
    """Extract node name from class (explicit or kebab-case)."""
    # Check for explicit name attribute
    if hasattr(cls, 'name') and isinstance(cls.name, str):
        return cls.name

    # Convert class name to kebab-case
    class_name = cls.__name__
    if class_name.endswith('Node'):
        class_name = class_name[:-4]

    return camel_to_kebab(class_name)
```

## Pattern: Robust CamelCase to kebab-case Conversion
**Context**: When converting class names to identifiers
**Solution**: Handle consecutive capitals and special cases with regex
**Why it works**: Correctly handles edge cases like "LLMNode" -> "llm-node"
**When to use**: Any identifier conversion from CamelCase
**Example**:
```python
def camel_to_kebab(name: str) -> str:
    """Convert CamelCase to kebab-case."""
    # Handle consecutive capitals (e.g., "LLMNode" -> "LLM-Node")
    result = re.sub('([A-Z]+)([A-Z][a-z])', r'\1-\2', name)
    # Then handle normal case transitions
    result = re.sub(r'([a-z\d])([A-Z])', r'\1-\2', result)
    return result.lower()
```
