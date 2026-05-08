# Cross-Workflow Rename (Parent)

## Inputs

### concept_brief

Original named value in parent.

- type: string
- required: true

## Cache

```cache
The concept brief:

${concept_brief}
```

## Steps

### parent_use

Use cache.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [concept_brief]

```prompt
Use it.
```

### child

Pass with RENAME — same value, new name.

- type: workflow
- workflow: ./sub/child.pflow.md
- inputs:
    creative_brief: ${concept_brief}

## Outputs

### parent_out

Parent output.

- source: ${parent_use.response}
- type: string

### child_out

Child output.

- source: ${child.summary}
- type: string
