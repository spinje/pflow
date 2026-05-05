# Finding 1 validator smoke test

Triggers `llm.thinking-temperature-mismatch`.

## Inputs

### user_question

The user's question.

- type: string
- required: true

## Steps

### score-choruses

Score the chorus options.

- type: llm
- model: anthropic/claude-haiku-4-5
- reasoning_effort: low
- temperature: 0.3
- prompt: |
    Answer this: ${user_question}
