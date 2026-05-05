# Mixed Model Cache Test

Two LLM calls referencing the SAME `${context}` chunk via `## Cache`, but each
call uses a different provider (Gemini Flash + Anthropic Haiku). Tests:

1. Does analyzer correctly compute savings per-provider (cache cannot share
   across provider namespaces)?
2. Does analyzer surface a "consolidate models" recommendation since
   declaring the cache benefits each provider in isolation?

## Inputs

### context

Stable reference body, same across both calls.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The following is the reference document. Treat it as authoritative.

${context}
```

## Steps

### gemini-call

LLM call on Gemini Flash, references shared `${context}` via cache.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: What is the magic value of a MERIDIAN frame?

Answer in one sentence.
```

### haiku-call

LLM call on Anthropic Haiku, references the SAME shared `${context}`.
Cannot share cache with `gemini-call` because they're different providers.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: How are MERIDIAN error codes grouped by class?

Answer in one sentence.
```

## Outputs

### gemini_answer
source: gemini-call.response

### haiku_answer
source: haiku-call.response
