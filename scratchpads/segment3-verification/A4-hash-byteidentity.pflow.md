# Attack A4 — hash byte-identity invariant (load-bearing)

This workflow gets run twice byte-identical (memo HIT). Then I modify ONE byte
of prose in `## Cache` — must be a memo MISS. The hash-vs-prep render symmetry
hinges on this.

## Inputs

### topic

The topic.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The topic to write about - exact prose matters for hash:

${topic}
```

## Steps

### emit

LLM call referencing the cache.

- type: llm
- prompt_cache: [topic]
- model: anthropic/claude-haiku-4-5
- max_tokens: 30

```prompt
Just say "ok" and nothing else.
```
