# Rename (Child)

## Inputs

### creative_brief

Renamed value from parent (originally concept_brief).

- type: string
- required: true

## Cache

```cache
The creative brief:

${creative_brief}
```

## Steps

### summarize

Summarize.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [creative_brief]

```prompt
Summarize.
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
