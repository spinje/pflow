# Shared Context Undeclared

## Inputs

### article

Long article text.

- type: string
- required: true

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Summarize this article: ${article}
```

### translate

Translate.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Translate this article to Spanish: ${article}
```

### tag

Tag.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
Generate 5 tags for this article: ${article}
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string

### translation

Translation.

- source: ${translate.response}
- type: string

### tags

Tags.

- source: ${tag.response}
- type: string
