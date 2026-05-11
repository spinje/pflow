# Sub-Workflow With Own ## Cache (Child)

## Inputs

### article

Long article text from parent.

- type: string
- required: true

## Cache

```cache
The article (cached locally in this sub-workflow):

${article}
```

## Steps

### summarize

Summarize using cache.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

### translate

Translate using same cache.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Translate to Spanish.
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
