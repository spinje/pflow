# TTL Expiry Test

Variant of gemini-smoke with `ttl: 1m` (instead of 5m default). Run twice
with > 60s wait between to force cache expiry. Verifies analyzer's
`cache.discrepancy.ttl_expiry` attribution.

## Inputs

### context

Stable reference body.

- type: string
- required: true

## Cache

- ttl: 1m

```cache
The reference document:

${context}
```

## Steps

### answer-a

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: What is the magic value of a MERIDIAN frame?

Answer in one sentence.
```

### answer-b

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: How are MERIDIAN error codes grouped by class?

Answer in one sentence.
```

## Outputs

### answer_a
source: answer-a.response

### answer_b
source: answer-b.response
