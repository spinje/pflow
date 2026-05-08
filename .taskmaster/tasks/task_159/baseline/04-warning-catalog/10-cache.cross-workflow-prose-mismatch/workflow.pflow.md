# Cross-Workflow Prose Mismatch (Parent)

## Inputs

### shared

Shared value.

- type: string
- required: true

## Cache

```cache
The shared document, in formal prose:

${shared}
```

## Steps

### parent_use

Use cache here.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [shared]

```prompt
Use shared.
```

### child

Pass into child.

- type: workflow
- workflow: ./sub/child.pflow.md
- inputs:
    shared: ${shared}

## Outputs

### parent_out

Parent output.

- source: ${parent_use.response}
- type: string

### child_out

Child output.

- source: ${child.summary}
- type: string
