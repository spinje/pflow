# Test LLM Templates

Demonstrate LLM node with template variable resolution in prompts,
using workflow inputs with defaults.

## Inputs

### topic

Topic to write about.

- type: string
- required: true

### style

Writing style.

- type: string
- required: false
- default: professional

### max_words

Maximum word count.

- type: number
- required: false
- default: 50

## Steps

### generate

Generate text about a topic in the specified style and word count.

- type: llm
- model: claude-3.5-haiku
- temperature: 0.7
- max_tokens: 200

```prompt
Write a ${style} explanation about ${topic} in exactly ${max_words} words. Be concise and clear.
```

## Outputs

### response

The LLM's response.

- type: string

### llm_usage

Token usage information.

- type: object
