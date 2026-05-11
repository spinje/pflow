# Gemini Cache Smoke (with `## Cache`)

Two LLM calls sharing a stable reference body via `## Cache`, using
Gemini's explicit `cachedContents`. The first call writes the cache;
the second reads it within the same run.

Expected on the recorded trace: call 1 has `cache_creation_input_tokens
> 0` (or 0 for Gemini's known telemetry caveat), `cache_read_input_tokens
== 0`; call 2 has `cache_read_input_tokens > 0`.

## Inputs

### context

Stable reference body (cached system prefix). Must be ≥ 4096 tokens to
clear Gemini's explicit `cachedContents` minimum.

- type: string
- required: true

### question_a

Question for the first LLM call.

- type: string
- required: false
- default: Summarize the reference document in three sentences.

### question_b

Question for the second LLM call.

- type: string
- required: false
- default: Translate the summary to Spanish.

## Cache

- ttl: 5m

```cache
The following is a stable reference document. Treat it as authoritative
context for any questions in this conversation.

${context}
```

## Steps

### answer-a

First LLM call. Writes the cache; second call reads it.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 200

```prompt
Question: ${question_a}

Answer using the reference document.
```

### answer-b

Second LLM call. Reads the cache populated by answer-a.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 200

```prompt
Question: ${question_b}

Answer using the reference document.
```

## Outputs

### answer_a
source: answer-a.response

### answer_b
source: answer-b.response
