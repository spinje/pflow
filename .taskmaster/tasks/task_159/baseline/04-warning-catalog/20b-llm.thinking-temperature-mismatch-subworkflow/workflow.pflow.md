# Thinking Temperature Mismatch — Sub-Workflow Parent

Parent invokes a child workflow whose LLM node violates the
Anthropic-thinking+temperature constraint. The validator emits the
diagnostic and `_add_child_provenance` prefixes it with "In step '...'
sub-workflow:" so the agent sees which child step is the offender.

## Inputs

### article

Article text.

- type: string
- required: true

## Steps

### invoke-child

Pass article into the child sub-workflow.

- type: workflow
- workflow: ./sub/child.pflow.md
- inputs:
    article: ${article}

## Outputs

### result

Result.

- source: ${invoke-child.summary}
- type: string
