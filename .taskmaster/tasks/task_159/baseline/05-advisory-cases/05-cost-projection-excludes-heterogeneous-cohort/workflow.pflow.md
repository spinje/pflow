# Heterogeneous Cohort Projection

## Inputs

### article

Long article text.

- type: string
- required: true

## Cache

```cache
The reference article:

${article}
```

## Steps

### priced

Priced model.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Summarize.
```

### unpriced

Custom unpriced model.

- type: llm
- model: ollama/llama3.2:8b
- prompt_cache: [article]

```prompt
Translate.
```

## Outputs

### priced_out

Priced output.

- source: ${priced.response}
- type: string

### unpriced_out

Unpriced output.

- source: ${unpriced.response}
- type: string
