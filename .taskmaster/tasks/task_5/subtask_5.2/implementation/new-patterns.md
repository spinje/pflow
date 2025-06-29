# Patterns Discovered

## Pattern: Registry Storage Without Key Duplication
**Context**: When storing a dictionary keyed by an identifier that's also in the values
**Solution**: Remove the identifier from the value before storing to avoid duplication
**Why it works**: The key already provides the identifier, storing it again in the value is redundant
**When to use**: Any time you're converting a list of objects to a dictionary keyed by an object property
**Example**:
```python
# Convert list to dict, removing 'name' from values
nodes = {}
for item in items:
    name = item.get("name")
    # Store without the key field
    node_data = {k: v for k, v in item.items() if k != "name"}
    nodes[name] = node_data
```

## Pattern: Graceful JSON Loading with Fallbacks
**Context**: When loading JSON that might be missing, empty, or corrupt
**Solution**: Chain multiple fallbacks with specific error handling for each case
**Why it works**: Provides resilience without crashing the application
**When to use**: Any user-editable or potentially missing configuration files
**Example**:
```python
def load(self) -> dict:
    if not self.path.exists():
        logger.debug(f"File not found at {self.path}")
        return {}

    try:
        content = self.path.read_text()
        if not content.strip():
            logger.debug("File is empty")
            return {}

        data = json.loads(content)
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON: {e}")
        return {}
```
