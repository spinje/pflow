# Gemini Cache Smoke (with `## Cache`)

Two LLM calls sharing a stable reference body via `## Cache`. Run twice
within TTL to verify rerun behavior on Gemini 2.5 Flash.

Expected on first run: call 1 writes cache (`cache_creation_input_tokens > 0`,
`cache_read_input_tokens == 0`); call 2 reads cache (`cache_read_input_tokens > 0`,
`cache_creation_input_tokens == 0`).

Note: Gemini telemetry caveat — `cache_creation_input_tokens` may be 0/absent
even when caching works. Verify primarily via `cache_read_input_tokens` on
call 2 + total cost reduction vs no-cache baseline.

Expected on rerun within TTL: BOTH calls show `cache_read_input_tokens > 0`,
`cache_creation_input_tokens == 0`.

## Inputs

### context

Stable reference body (cached system prefix).

- type: string
- required: true

### question_a

Question for the first LLM call.

- type: string
- required: false
- default: What is the magic value of a MERIDIAN frame, and which byte offset carries it?

### question_b

Question for the second LLM call.

- type: string
- required: false
- default: How are MERIDIAN error codes grouped by class?

## Cache

- ttl: 5m

```cache
The following is a stable reference document. Treat it as authoritative
context for any questions in this conversation.

${context}
```

## Steps

### answer-a

First LLM call. Writes the cache on first run; reads it on rerun.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: ${question_a}

Answer in one sentence using the reference document.
```

### answer-b

Second LLM call. Reads the cache populated by answer-a (same subset).

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: ${question_b}

Answer in one sentence using the reference document.
```

## Outputs

### answer_a
source: answer-a.response

### answer_b
source: answer-b.response
