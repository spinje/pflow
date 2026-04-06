# Review Aspect

Review a summary from a single critical perspective.

## Inputs

### summary

The research summary to review.

- type: string
- required: true

### aspect

The review perspective to apply.

- type: string

## Steps

### critique

Review the summary from the given perspective.

- type: llm
- prompt: Review this research summary for ${aspect}: ${summary}

## Outputs

### review_text

The review text from this perspective.

- source: ${critique.response}
