# Undeclared prompt_cache Name

## Inputs

### article

The article text.

- type: string
- required: true

## Cache

```cache
The article:

${article}
```

## Steps

### summarize

Summarize the article.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [typo]

```prompt
Summarize: ${article}
```

## Outputs

### summary

The summary.

- source: ${summarize.response}
- type: string
