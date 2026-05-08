# prompt_cache Empty List (Valid)

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

Summarize the article. Intentionally opts out of declared cache via empty list.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: []

```prompt
Summarize: ${article}
```

## Outputs

### summary

The summary.

- source: ${summarize.response}
- type: string
