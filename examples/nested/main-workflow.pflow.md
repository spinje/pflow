# Main Workflow

Process a document's title and body through nested text processing workflows.
Demonstrates nested workflow invocation with parameter and output mapping.

## Steps

### process_title

Process the document title using the text normalization sub-workflow.

- type: workflow
- workflow_ref: ./process-text.pflow.md

```yaml param_mapping
text: ${document_title}
mode: title
```

```yaml output_mapping
normalized_text: processed_title
```

### process_body

Process the document body with scoped storage mode.

- type: workflow
- workflow_ref: ./process-text.pflow.md
- storage_mode: mapped

```yaml param_mapping
text: ${document_body}
mode: lower
```

```yaml output_mapping
normalized_text: processed_body
```
