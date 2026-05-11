# Duplicate Chunk Identifier

## Inputs

### article

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

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

## Outputs

### summary

- source: ${summarize.response}
- type: string
