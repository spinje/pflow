# Three-Level Nesting (Top)

## Inputs

### article

Long article text.

- type: string
- required: true

## Steps

### child

Invoke level-2 child.

- type: workflow
- workflow: ./level2/level2.pflow.md
- inputs:
    article: ${article}

## Outputs

### result

Final result.

- source: ${child.summary}
- type: string
