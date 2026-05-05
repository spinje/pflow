# Unused-chunk test

`## Cache` declares two chunks but the LLM node only uses one. Should
warn `cache.unused-chunk` for the unused chunk.

## Inputs

### used_chunk

Chunk that gets used.

- type: string
- required: true

### unused_chunk

Chunk declared but never used.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
${used_chunk}

${unused_chunk}
```

## Steps

### test-call

Only references used_chunk — unused_chunk is dead in cache.

- type: llm
- prompt_cache: [used_chunk]

```prompt
Use this content: ${used_chunk}

What does it say?
```
