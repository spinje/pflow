# Prose Mismatch (Child)

## Inputs

### shared

Shared value.

- type: string
- required: true

## Cache

```cache
Casual reference document — note the different prose-before-var than parent:

${shared}
```

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [shared]

```prompt
Summarize.
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
