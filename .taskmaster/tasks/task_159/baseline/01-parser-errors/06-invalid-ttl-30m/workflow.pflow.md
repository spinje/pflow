# Invalid TTL Value

## Inputs

### article

- type: string
- required: true

## Cache

- ttl: 30m

```cache
The article to summarize:

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
