# Greenfield Workflow (no ## Cache)

## Inputs

### article

The article to analyze. This same value is referenced by 3 LLM nodes — a
classic shared-context pattern that should trigger
`cache.shared-context-undeclared`.

- type: string
- required: true

## Steps

### summarize

Summarize the article.

- type: llm
- model: anthropic/claude-haiku-4-5

```prompt
Summarize this article: ${article}
```

### translate

Translate the article.

- type: llm
- model: anthropic/claude-haiku-4-5

```prompt
Translate this article to Spanish: ${article}
```

### tag

Generate tags for the article.

- type: llm
- model: anthropic/claude-haiku-4-5

```prompt
Generate 5 tags for this article: ${article}
```

## Outputs

### summary

The summary.

- source: ${summarize.response}
- type: string

### translation

The translation.

- source: ${translate.response}
- type: string

### tags

The tags.

- source: ${tag.response}
- type: string
