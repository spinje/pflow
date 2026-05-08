# Order Mismatch

## Inputs

### article

Article text.

- type: string
- required: true

### topic

Topic.

- type: string
- required: true

## Cache

```cache
The article:

${article}

The topic:

${topic}
```

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [topic, article]

```prompt
Summarize.
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
