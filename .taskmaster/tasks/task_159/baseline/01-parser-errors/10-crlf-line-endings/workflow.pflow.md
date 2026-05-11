# CRLF Duplicate Chunk

## Inputs

### article

The article text.

- type: string
- required: true

## Cache

```cache
First mention of the article:

${article}

Second mention of the article:

${article}
```

## Steps

### summarize

Summarize the article.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
