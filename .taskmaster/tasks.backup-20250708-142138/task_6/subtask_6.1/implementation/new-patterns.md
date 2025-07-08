# Patterns Discovered

## Pattern: Layered Validation with Custom Business Logic
**Context**: When you need to validate JSON data against a schema but also enforce business rules not expressible in JSON Schema
**Solution**: Use a three-layer validation approach:
```python
def validate_data(data):
    # Layer 1: Parse JSON if needed
    if isinstance(data, str):
        data = json.loads(data)

    # Layer 2: Schema validation
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        raise ValidationError(format_error(errors[0]))

    # Layer 3: Business logic validation
    _validate_custom_rules(data)
```
**Why it works**: Separates structural validation from business rules, making both easier to maintain
**When to use**: Any time JSON Schema alone isn't sufficient for your validation needs
**Example**: Validating node references exist, checking for duplicate IDs

## Pattern: User-Friendly Error Path Formatting
**Context**: When jsonschema provides error paths as lists that aren't user-friendly
**Solution**: Transform path components into readable notation:
```python
def _format_path(path: list) -> str:
    formatted = ""
    for i, component in enumerate(path):
        if isinstance(component, int):
            formatted += f"[{component}]"
        else:
            if i > 0 and not formatted.endswith("]"):
                formatted += "."
            formatted += str(component)
    return formatted or "root"
```
**Why it works**: Converts `['nodes', 0, 'type']` to readable `nodes[0].type`
**When to use**: Whenever displaying validation errors to users
