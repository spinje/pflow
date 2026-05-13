# Batch Prewarm Prefix Below Provider Minimum

## Inputs

### items

Items to score.

- type: array
- required: true

## Steps

### scoring

Batch with `prewarm: true` but the static prefix before `${item.X}` is
well below Anthropic Sonnet's 1024-token cache minimum. The `cache_control`
marker pflow emits will silently no-op at the provider as configured.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prewarm: true

```yaml batch
items: ${items}
parallel: true
```

```prompt
Score the following item.

${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
