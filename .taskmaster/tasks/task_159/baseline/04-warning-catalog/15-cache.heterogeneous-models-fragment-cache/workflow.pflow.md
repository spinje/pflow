# Heterogeneous Models

## Inputs

### article

Long article text.

- type: string
- required: true

## Cache

```cache
The reference article:

${article}
```

## Steps

### summarize

Summarize with sonnet.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

### translate

Translate with haiku.

- type: llm
- model: anthropic/claude-haiku-4-5
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
