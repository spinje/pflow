# Sub-Workflow Child (no ## Cache despite multi-node reuse)

## Inputs

### article

Article text from parent. Reused across 2 LLM nodes — should trigger
cache.sub-workflow-cache-undeclared on the parent's analyze-cache because the
child has no ## Cache declaration.

- type: string
- required: true

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Summarize: ${article}
```

### translate

Translate.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Translate: ${article}
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
