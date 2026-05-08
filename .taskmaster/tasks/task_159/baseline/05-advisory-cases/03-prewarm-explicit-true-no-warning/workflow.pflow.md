# Prewarm Explicit True

## Inputs

### items

Items.

- type: array
- required: true

## Steps

### scoring

Batch with explicit prewarm: true.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prewarm: true

```yaml batch
items: ${items}
parallel: true
```

```prompt
A long stable rubric to make the savings ratio favorable. Lots of fixed
guidance text. Score: ${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
