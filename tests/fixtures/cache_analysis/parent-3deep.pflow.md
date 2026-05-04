# Parent3Deep

3-deep parent cache-analysis fixture (parent → child → grandchild).

## Inputs

### topic
The topic.
- type: string

## Steps

### draft

Parent draft.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Parent ${topic}
```

### call-child

Call child.

- type: workflow
- workflow: ./child-3deep.pflow.md
- inputs:
    brief: ${draft.response}
