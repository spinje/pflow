# Sub-Workflow With Own ## Cache (Happy Path — Parent)

## Inputs

### article

Long article text.

- type: string
- required: true

## Steps

### child

Invoke a child sub-workflow that declares its own `## Cache`.

- type: workflow
- workflow: ./sub/child.pflow.md
- inputs:
    article: ${article}

## Outputs

### result

Result.

- source: ${child.summary}
- type: string
