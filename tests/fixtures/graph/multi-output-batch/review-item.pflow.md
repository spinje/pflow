# Review Item

Child workflow with multiple declared outputs.

## Steps

### score

Produce two output fields.

- type: code

```python code
result: dict = {"summary": "ok", "score": 1}
```

## Outputs

### summary

The summary output.

- source: ${score.result.summary}

### score

The score output.

- source: ${score.result.score}
