# Below Min Rendered

## Inputs

### article

Article text.

- type: string
- required: true

## Cache

```cache
Article:

${article}
```

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
