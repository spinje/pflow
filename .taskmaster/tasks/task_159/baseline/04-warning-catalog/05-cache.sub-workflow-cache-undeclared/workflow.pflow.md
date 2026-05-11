# Sub-Workflow Cache Undeclared (Parent)

## Inputs

### article

Article text.

- type: string
- required: true

## Steps

### child

Pass article into child for multi-node reuse.

- type: workflow
- workflow: ./sub/child.pflow.md
- inputs:
    article: ${article}

## Outputs

### result

Result.

- source: ${child.summary}
- type: string
