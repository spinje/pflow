# Child3Deep

3-deep child cache-analysis fixture.

## Inputs

### brief
The brief.
- type: string

## Steps

### draft

Child draft.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Child ${brief}
```

### call-grandchild

Call grandchild.

- type: workflow
- workflow: ./grandchild.pflow.md
- inputs:
    context: ${draft.response}
