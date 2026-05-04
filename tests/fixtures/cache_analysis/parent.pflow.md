# Parent

Parent cache-analysis fixture.

## Inputs

### topic
The topic.
- type: string

## Cache

```cache
The topic:

${topic}
```

## Steps

### draft

Parent draft.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [topic]

```prompt
Parent ${topic}
```

### call-child

Call child.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    brief: ${draft.response}
    topic: ${topic}
