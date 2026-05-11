# Child

Child cache-analysis fixture.

## Inputs

### brief
The brief.
- type: string

### topic
The topic.
- type: string

## Cache

```cache
The brief:

${brief}
```

## Steps

### draft

Child draft.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [brief]

```prompt
Child draft ${brief}
```

### review

Child review.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [brief]

```prompt
Review ${brief} for ${topic}
```
