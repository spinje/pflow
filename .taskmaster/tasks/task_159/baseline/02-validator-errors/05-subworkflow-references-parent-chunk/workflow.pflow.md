# Parent Workflow

## Inputs

### article

The article text.

- type: string
- required: true

## Cache

```cache
The article being processed by the whole pipeline:

${article}
```

## Steps

### child

Invoke the child sub-workflow.

- type: workflow
- workflow: ./sub/child.pflow.md
- inputs:
    article: ${article}

## Outputs

### result

The result from the child.

- source: ${child.summary}
- type: string
