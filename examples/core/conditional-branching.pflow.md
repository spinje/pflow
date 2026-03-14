# Conditional Branching

Demonstrates conditional branching patterns: error routing, dynamic
classification routing via Python code, and early termination.

## Steps

### fetch-data

Fetch input data for processing.

- type: shell

```shell command
echo '{"status": "ok", "items": [1, 2, 3]}'
```

### classify

Route to the appropriate handler based on the data.

- type: code
- on-error: handle-error
- inputs: { data: "${fetch-data.stdout}" }

```python code
data: dict

items = data.get("items", [])

if len(items) > 5:
    next: str = "process-large"
else:
    next: str = "process-small"
result: dict = data
```

### process-small

Handle small datasets directly.

- type: shell
- next: done

```shell command
echo "Processing small batch"
```

### process-large

Handle large datasets with more resources.

- type: shell
- next: done

```shell command
echo "Processing large batch"
```

### handle-error

Log and handle classification errors.

- type: shell
- next: end

```shell command
echo "Error occurred during classification" >&2
```

### done

Final reporting step.

- type: shell

```shell command
echo "Processing complete"
```
