# Thinking Temperature Mismatch

## Inputs

### article

Article.

- type: string
- required: true

## Steps

### deep-think

Use thinking with non-default temperature (Anthropic requires temp=1 with thinking).

- type: llm
- model: anthropic/claude-opus-4-7
- reasoning_effort: high
- temperature: 0.3

```prompt
Think deeply about: ${article}
```

## Outputs

### result

Result.

- source: ${deep-think.response}
- type: string
