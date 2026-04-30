# Attack A7 — parent invokes child via ## Cache

Parent has its own ## Cache; invokes child via type: workflow. Each file's
cache block is independent.

## Inputs

### topic

The topic.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
Parent workflow's local cache. Topic for context:

${topic}
```

## Steps

### parent-emit

Parent's LLM call referencing parent's cache.

- type: llm
- prompt_cache: [topic]
- model: anthropic/claude-haiku-4-5
- max_tokens: 30

```prompt
Just say "parent-ok" and nothing else.
```

### invoke-child

Invoke child sub-workflow.

- type: workflow
- workflow: ./A7-child.pflow.md
- inputs:
    concept: ${topic}
