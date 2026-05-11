# Prompt Body Shadows Cache

## Inputs

### article

The article text.

- type: string
- required: true

## Cache

```cache
The article being analyzed:

${article}
```

## Steps

### summarize

Summarize the article.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
The article being analyzed:

${article}

Now summarize it.
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
