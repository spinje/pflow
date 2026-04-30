# Attack A7 — child workflow with its own ## Cache

Tests sub-workflow cache isolation: child has its own ## Cache, independent
from parent's.

## Inputs

### concept

The concept passed from parent.

- type: string
- required: true

## Outputs

### result

The child's result.

- source: ${child-emit.response}

## Cache

- ttl: 5m

```cache
Child workflow's local cache. Concept it received:

${concept}
```

## Steps

### child-emit

LLM call inside the child.

- type: llm
- prompt_cache: [concept]
- model: anthropic/claude-haiku-4-5
- max_tokens: 30

```prompt
Just say "child-ok" and nothing else.
```
