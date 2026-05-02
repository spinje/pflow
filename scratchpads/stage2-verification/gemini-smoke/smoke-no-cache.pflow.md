# Gemini Cache Smoke (no `## Cache` — control)

Two LLM calls with the same prompts as `smoke-with-cache.pflow.md` but no
`## Cache` declaration. Used as the baseline for cost comparison on
Gemini 2.5 Flash.

Expected: both calls show `cache_creation_input_tokens == 0` and
`cache_read_input_tokens == 0`. Full input cost on every call.

## Inputs

### context

Stable reference body. Inlined into prompts uncached.

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

## Steps

### answer-a

First LLM call. No cache — pays full input cost on context.

- type: llm
- model: gemini/gemini-2.5-flash
- max_tokens: 80

```prompt
The following is a stable reference document. Treat it as authoritative
context for any questions in this conversation.

${context}

Question: ${question_a}

Answer in one sentence using the reference document.
```

### answer-b

Second LLM call. No cache — pays full input cost on context again.

- type: llm
- model: gemini/gemini-2.5-flash
- max_tokens: 80

```prompt
The following is a stable reference document. Treat it as authoritative
context for any questions in this conversation.

${context}

Question: ${question_b}

Answer in one sentence using the reference document.
```

## Outputs

### answer_a
source: answer-a.response

### answer_b
source: answer-b.response
