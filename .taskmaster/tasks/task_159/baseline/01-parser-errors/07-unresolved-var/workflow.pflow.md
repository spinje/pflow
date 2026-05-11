# Unresolved Variable In Cache

## Inputs

### article

The article text.

- type: string
- required: true

## Cache

```cache
The thing that does not exist:

${nonexistent}
```

## Steps

### summarize

Summarize the article.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [nonexistent]

```prompt
Summarize: ${article}
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
