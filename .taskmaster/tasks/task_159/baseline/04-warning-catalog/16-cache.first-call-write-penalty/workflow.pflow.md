# First Call Write Penalty

## Inputs

### article

Long article text.

- type: string
- required: true

## Cache

```cache
The reference article:

${article}
```

## Steps

### summarize

Sole user of declared chunk — pays write cost without amortization.

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
