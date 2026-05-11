# Grandchild

Grandchild cache-analysis fixture.

## Inputs

### context
The context.
- type: string

## Steps

### draft

Grandchild draft.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Grandchild ${context}
```
