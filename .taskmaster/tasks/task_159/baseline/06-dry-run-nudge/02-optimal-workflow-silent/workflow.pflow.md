# Optimal Batch Cache Dry Run

## Inputs

### context

Long stable reference doc.

- type: string
- required: true

### items

Items to process.

- type: array
- required: true

## Cache

```cache
The reference document:

${context}
```

## Steps

### scoring

Batch with declared cache and explicit prewarm.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [context]
- prewarm: true

```yaml batch
items: ${items}
parallel: true
```

```prompt
Score this item using the reference document: ${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
