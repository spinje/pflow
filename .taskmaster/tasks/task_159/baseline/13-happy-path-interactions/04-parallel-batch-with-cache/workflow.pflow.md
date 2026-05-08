# Parallel Batch With prompt_cache

## Inputs

### context

Stable shared context.

- type: string
- required: true

### items

Items.

- type: array
- required: true

## Cache

```cache
The shared context:

${context}
```

## Steps

### scoring

Parallel batch with prompt_cache: [context]. Each parallel call sends the
same cached prefix → after the first call writes, subsequent calls read at
0.1×. With OpenAI this also emits prompt_cache_key for sticky-routing.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [context]

```yaml batch
items: ${items}
parallel: true
max_concurrent: 4
```

```prompt
Score this item: ${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
