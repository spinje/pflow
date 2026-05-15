# Optimal Batch Cache Dry Run

## Inputs

### context

Long stable reference doc — cached as a system block via `prompt_cache:`.

- type: string
- required: true

### rubric

Long stable scoring instructions — placed in the prompt body BEFORE the
per-item ref so `prewarm: true`'s auto batch-prefix marker has substantial
bytes to cache. Distinct from `${context}` (no shadowing).

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

Batch with declared cache and explicit prewarm. The cached `${context}`
goes to system blocks; `${rubric}` is the user-message stable prefix that
`prewarm: true` caches independently.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [context]
- prewarm: true

```yaml batch
items: ${items}
parallel: true
```

```prompt
${rubric}

Score this item using the reference document and rubric above:
${item.text}
```

## Outputs

### scores

Scores.

- source: ${scoring}
- type: array
