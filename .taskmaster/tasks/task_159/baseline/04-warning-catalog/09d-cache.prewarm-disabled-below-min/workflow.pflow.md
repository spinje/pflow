# Prewarm Disabled Below Min

## Inputs

### items

Items to score.

- type: array
- required: true

## Steps

### score

Score each item.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prewarm: true

```yaml batch
items: ${items}
parallel: true
```

```prompt
Short stable prefix.

${item.text}
```

## Outputs

### scores

Scores.

- source: ${score.responses}
- type: array
