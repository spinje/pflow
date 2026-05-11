# Partial Trace Analyze Cache

Two LLM nodes with a failing shell node between them. The committed command
constructs a trace where `answer-a` executed, `blocker` failed, and `answer-b`
never ran.

## Inputs

### context

Stable reference body.

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

First LLM call. Writes the cache; second call would read it if reached.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 200

```prompt
Question: ${question_a}

Answer using the reference document.
```

### blocker

Fails after the first LLM call, leaving `answer-b` unexecuted.

- type: shell
- cache: false
- command: exit 1

### answer-b

Second LLM call. Reads the cache populated by answer-a when the workflow
completes normally.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [context]
- max_tokens: 200

```prompt
Question: ${question_b}

Answer using the reference document.
```
