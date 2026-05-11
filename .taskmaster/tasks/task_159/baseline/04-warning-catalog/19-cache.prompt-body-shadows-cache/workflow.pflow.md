# Prompt Body Shadows Cache

## Inputs

### article

Article text.

- type: string
- required: true

## Cache

```cache
The article:

${article}
```

## Steps

### summarize

Summarize. The body has a `${article}` reference — same name AND same identity
as the cached chunk; this overlaps with `cache.prompt-body-duplicates-cache`.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Summarize ${article} please.
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
