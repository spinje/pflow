# Prewarm Explicit False

## Inputs

### items

Items.

- type: array
- required: true

## Steps

### scoring

Batch with explicit prewarm: false.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prewarm: false

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
