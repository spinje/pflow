# Empty Cache Block

## Inputs

### article

- type: string
- required: true

## Cache

```cache
```

## Steps

### summarize

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
Summarize: ${article}
```

## Outputs

### summary

- source: ${summarize.response}
- type: string
