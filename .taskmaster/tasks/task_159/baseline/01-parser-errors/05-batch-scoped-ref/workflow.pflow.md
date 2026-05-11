# Batch-Scoped Reference In Cache

## Inputs

### items

List of items to score.

- type: array
- required: true

## Cache

```cache
The current item being processed:

${item.text}
```

## Steps

### scoring

Score each item in the batch.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [item.text]

```yaml batch
items: ${items}
parallel: true
```

```prompt
Score this item.
```

## Outputs

### scores

The scored items.

- source: ${scoring}
- type: array
