# Code Annotation Type Mismatch (Invalid)

Demonstrates validate-time code-node input type checking. This workflow must
fail validation because the downstream annotation does not match its upstream
source type.

## Steps

### upstream

Produces a list.

- type: code

```python code
result: list = [1, 2, 3]
```

### downstream

Annotates dict but upstream is list.

- type: code
- inputs:
    x: ${upstream.result}

```python code
x: dict
result: str = str(x)
```

## Outputs

### final
Final result.
- source: ${downstream.result}
