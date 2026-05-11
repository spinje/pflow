# Cache Discrepancy

Minimal workflow for a trace-backed memo-key discrepancy. The command creates
an empty memo database so the analyzer predicts the node's current memo key,
then feeds a trace with a different recorded key.

## Steps

### gen

Generate from a stable literal prompt.

- type: llm
- model: anthropic/claude-sonnet-4-5
- max_tokens: 80

```prompt
Generate a deterministic answer from the stable prompt.
```

## Outputs

### answer

Generated answer.

- source: ${gen.response}
- type: string
