# Prompt File Reference Test

Test that a prompt can be loaded from an external file.

## Inputs

### input

Text to analyze.

- type: string
- required: true

## Steps

### analyze

Analyze input using an external prompt file.

- type: llm
- prompt: ./prompts/analyze.prompt.md
