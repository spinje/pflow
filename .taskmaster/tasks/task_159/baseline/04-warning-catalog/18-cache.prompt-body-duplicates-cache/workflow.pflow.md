# Prompt Body Duplicates Cache

## Inputs

### article

Article text.

- type: string
- required: true

## Cache

```cache
The article:

${article}
```

## Steps

### summarize

Summarize, but body redundantly references the cached value.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
Summarize this article: ${article}
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
