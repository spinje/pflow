# Batch Prewarm Lower-Bound Opportunity

## Inputs

### context

Optional upstream object intentionally omitted by this baseline.

- type: object
- required: false

## Steps

### scoring

Batch without a `prewarm` decision. The literal prompt prefix is already above
Anthropic Sonnet's provider minimum; `${context.detail}` is unresolved at
analysis time and must be verified before declaring `prewarm: true`.

- type: llm
- model: anthropic/claude-sonnet-4-5

```yaml batch
items:
  - text: alpha
  - text: beta
  - text: gamma
parallel: true
```

```prompt
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable
stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable stable

${context.detail}

Score this item:
${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
