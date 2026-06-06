# Multi Output Batch Fan

Exercise Mermaid fan-out from a literal workflow batch whose child workflow declares multiple outputs.

## Steps

### review-items

Run the same child workflow for several literal items.

- type: workflow
- workflow: ${item.workflow}
- next: combine

```yaml batch
items:
  - name: alpha
    workflow: ./review-item.pflow.md
  - name: beta
    workflow: ./review-item.pflow.md
  - name: gamma
    workflow: ./review-item.pflow.md
  - name: delta
    workflow: ./review-item.pflow.md
  - name: epsilon
    workflow: ./review-item.pflow.md
parallel: true
```

### combine

Consume the batch output fan.

- type: code

```python code
result: dict = {"combined": True}
```
