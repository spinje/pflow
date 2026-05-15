# Batch + Cache + Prewarm Happy Path

## Inputs

### context

Long stable reference doc — cached as a system block via `prompt_cache:`.

- type: string
- required: true

### rubric

Long stable scoring instructions — placed in the prompt body BEFORE the
per-item ref so the auto batch-prefix marker (`prewarm: true`) has
substantial bytes to cache. Distinct from `${context}` (no shadowing).

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

Batch with declared cache + explicit prewarm: true. The cached chunk is
written ONCE by the serialized first call; remaining N-1 calls read at 0.1×.
The user-message prefix (rubric instructions) is captured separately by
`prewarm: true` and benefits from auto batch-prefix caching across items.

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
