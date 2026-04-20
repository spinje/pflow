# Code Missing Result Annotation (Invalid)

Demonstrates validate-time enforcement of the code-node output/routing
annotation requirement. This workflow must fail validation because the code
block declares neither `result: <type>` nor `next: str` — the runtime would
reject this, and Pass 9 surfaces it at validate-time so `--validate-only` and
`--dry-run` agree with runtime.

## Steps

### split

Missing `result:` / `next:` annotation in the code block.

- type: code

```python code
items = [1, 2, 3]
```

## Outputs

### out
Output source.
- source: ${split.result}
