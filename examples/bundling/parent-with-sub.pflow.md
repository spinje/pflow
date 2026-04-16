# Parent With Sub-Workflow

Parent workflow that delegates to a sub-workflow via file reference. Tests bundling of sub-workflow dependencies.

## Inputs

### input

Text to process.

- type: string
- required: true

## Steps

### process

Convert input to uppercase using sub-workflow.

- type: workflow
- workflow: ./sub-echo.pflow.md
- inputs:
    text: ${input}

## Outputs

### result

Processed text.

- source: ${process.result}
