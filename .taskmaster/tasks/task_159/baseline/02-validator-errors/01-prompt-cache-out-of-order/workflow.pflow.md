# Out-Of-Order prompt_cache

## Inputs

### article

The article text.

- type: string
- required: true

### topic

The topic.

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

Summarize the article and topic.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [topic, article]

```prompt
Summarize.
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
