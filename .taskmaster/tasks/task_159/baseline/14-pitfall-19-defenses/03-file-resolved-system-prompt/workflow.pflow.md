# File-Resolved Prompt (Path 1 Boundary)

## Inputs

### article

Article text.

- type: string
- required: true

## Cache

```cache
The article (cached so the long file-resolved prompt below stays focused
on the per-call dynamic content):

${article}
```

## Steps

### summarize

LLM with prompt loaded from external file. Path 1 boundary contract says
`ResolvedWorkflow.ir` arrives here with the prompt content already resolved
from disk — analyze-cache should tokenize the FILE CONTENTS, not the
literal `"./prompt.md"` filename string.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]
- prompt: ./long-system-prompt.md

## Outputs

### summary

The summary.

- source: ${summarize.response}
- type: string
