# Prewarm No Prefix

## Inputs

### items

Items.

- type: array
- required: true

## Steps

### scoring

Score each item.

- type: llm
- model: anthropic/claude-haiku-4-5
- prewarm: true

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
