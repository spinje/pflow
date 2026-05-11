# Sub-Workflow Child (no ## Cache despite multi-node reuse)

## Inputs

### article

Article object from parent. Subpaths are reused across 2 LLM nodes — should
trigger cache.sub-workflow-cache-undeclared with a cleanup hint because the
child has no ## Cache declaration.

- type: object
- required: true

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Summarize: ${article.title}
```

### translate

Translate.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Translate: ${article.body}
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
