# Thinking Temperature Mismatch — Child

Child has the bad LLM shape: reasoning_effort + temperature ≠ 1.0 on
Anthropic. Validator catches this and propagates up to the parent.

## Inputs

### article

Article from parent.

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

### summary

Summary.

- source: ${deep-think.response}
- type: string
