# Cross-Workflow Cache Test (child)

Receives `${shared_doc}` from parent. Makes its own LLM call referencing
the same value. Tests whether cache from parent boundary is visible here.

## Inputs

### shared_doc

The shared reference document, passed from parent.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The reference document, shared across the workflow:

${shared_doc}
```

## Steps

### child-call

LLM call referencing shared_doc. Same model as parent's call so cache
namespace matches.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt_cache: [shared_doc]
- max_tokens: 80

```prompt
Question: How are MERIDIAN error codes grouped by class?

Answer in one sentence.
```

## Outputs

### child_answer
source: child-call.response
