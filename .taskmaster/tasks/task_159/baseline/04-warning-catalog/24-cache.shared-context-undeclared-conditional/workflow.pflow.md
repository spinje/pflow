# Shared Context Conditional

## Inputs

### article

Article text. The baseline passes a tiny smoke value so the structural
opportunity is real but the current resolved value is below the provider
minimum.

- type: string
- required: true

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-haiku-4-5

```prompt
Summarize this article: ${article}
```

### translate

Translate.

- type: llm
- model: anthropic/claude-haiku-4-5

```prompt
Translate this article to Spanish: ${article}
```

### tag

Tag.

- type: llm
- model: anthropic/claude-haiku-4-5

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
