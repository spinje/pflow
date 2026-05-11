# Prompt Cache Incomplete

## Inputs

### a

First stable reference.

- type: string
- required: true

### b

Second stable reference.

- type: string
- required: true

## Cache

```cache
Chunk A:

${a}

---

Chunk B:

${b}
```

## Steps

### draft

Draft.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [a]

```prompt
Draft from ${b}.
```

### review

Review.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [a]

```prompt
Review ${b}.
```

## Outputs

### draft_text

Draft text.

- source: ${draft.response}
- type: string
