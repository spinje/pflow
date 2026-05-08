# Two Vars In One Chunk

## Inputs

### article

The article text.

- type: string
- required: true

### topic

The topic of the article.

- type: string
- required: true

## Cache

```cache
The article ${article} is about ${topic}.
```

## Steps

### summarize

Summarize the article.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article, topic]

```prompt
Summarize.
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
