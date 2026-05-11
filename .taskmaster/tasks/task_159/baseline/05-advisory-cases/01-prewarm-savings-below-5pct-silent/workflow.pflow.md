# Prewarm Savings Below 5%

## Inputs

### items

Items.

- type: array
- required: true

## Steps

### scoring

Batch with mostly-dynamic prompt — small static prefix.

- type: llm
- model: anthropic/claude-sonnet-4-5

```yaml batch
items: ${items}
parallel: true
```

```prompt
${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
