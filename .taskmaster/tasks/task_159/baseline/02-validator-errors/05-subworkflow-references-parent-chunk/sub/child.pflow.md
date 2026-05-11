# Child Workflow

## Inputs

### article

The article text passed in from the parent.

- type: string
- required: true

## Steps

### summarize

Summarize the article using the parent's `article` chunk by name.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
