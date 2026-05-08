# Opaque Prompt

## Inputs

### article

Article.

- type: string
- required: true

## Steps

### shape

Build the prompt body from a code node.

- type: code

```python code
result = f"Summarize: {article}"
```

### summarize

LLM with opaque prompt — body is one ${ref} pointing at a code node.

- type: llm
- model: anthropic/claude-sonnet-4-5

```prompt
${shape.result}
```

## Outputs

### summary

Summary.

- source: ${summarize.response}
- type: string
