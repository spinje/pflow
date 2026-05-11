# Prose-Only Cache Block

## Inputs

### article

- type: string
- required: true

## Cache

```cache
This block has only prose and no template variables at all.
It is just narrative text that does not reference anything.
```

## Steps

### summarize

- type: llm
- model: anthropic/claude-haiku-4-5

```prompt
Summarize: ${article}
```

## Outputs

### summary

- source: ${summarize.response}
- type: string
