# Analyze-Cache Surfaces Undeclared prompt_cache (regression for external review fix)

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

Summarize. References a chunk `typo` not declared in `## Cache`.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [typo]

```prompt
Summarize: ${article}
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
