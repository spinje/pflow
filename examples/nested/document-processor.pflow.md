# Document Processor

Process a document's title and body through nested sub-workflows.
Demonstrates nested workflow invocation with the simple syntax.

## Inputs

### title
The document title.
- type: string

### body
The document body.
- type: string

## Steps

### process_title

Convert the title to uppercase using a sub-workflow.

- type: workflow
- workflow: ./to-uppercase.pflow.md
- inputs:
    text: ${title}

### process_body

Convert the body to uppercase using the same sub-workflow.

- type: workflow
- workflow: ./to-uppercase.pflow.md
- inputs:
    text: ${body}

### combine

Combine the processed title and body.

- type: shell

```command
printf "Title: %s\nBody: %s" "${process_title.result}" "${process_body.result}"
```
