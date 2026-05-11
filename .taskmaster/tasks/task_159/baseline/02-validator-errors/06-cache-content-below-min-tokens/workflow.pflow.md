# Cache Content Below Provider Minimum

## Inputs

### article

The article text.

- type: string
- required: true

## Cache

```cache
Tiny:

${article}
```

## Steps

### summarize

Summarize the article. Uses sonnet which has a 1024-token min cache threshold.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
