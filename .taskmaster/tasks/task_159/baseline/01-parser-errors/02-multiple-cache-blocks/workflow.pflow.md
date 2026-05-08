# Multiple Cache Blocks

## Inputs

### article

- type: string
- required: true

## Cache

```cache
First cacheable thing:

${article}
```

```cache
Second cacheable thing:

${article}
```

## Steps

### summarize

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

## Outputs

### summary

- source: ${summarize.response}
- type: string
