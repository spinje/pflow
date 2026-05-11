# Level 3

## Inputs

### article

Long article from upstream.

- type: string
- required: true

### entities

Extracted entities.

- type: string
- required: true

## Cache

```cache
The article (level 3 cache):

${article}
```

## Steps

### summarize

Summarize using level-3 cache + the upstream entities.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Summarize using these entities: ${entities}
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
