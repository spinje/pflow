# Dotted-Path Cache Chunk (Bug #2 Vector)

## Inputs

### article

Article text.

- type: string
- required: true

## Cache

```cache
The producer's response (dotted path through NamespacedSharedStore proxy):

${produce.response}
```

## Steps

### produce

Producer of the cached value. Outputs `response` field that the cache chunk
references via dotted path `${produce.response}`.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Echo the article: ${article}
```

### consume-1

Consumer 1 — uses the cached `produce.response`.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [produce.response]

```prompt
Summarize.
```

### consume-2

Consumer 2 — uses the same cached chunk.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [produce.response]

```prompt
Translate.
```

## Outputs

### summary

Summary.

- source: ${consume-1.response}
- type: string

### translation

Translation.

- source: ${consume-2.response}
- type: string
