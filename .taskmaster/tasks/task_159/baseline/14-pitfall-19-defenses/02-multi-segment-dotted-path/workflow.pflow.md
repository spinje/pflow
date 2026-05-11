# Multi-Segment Dotted Path

## Inputs

### concept

Structured concept (object with sub-fields).

- type: object
- required: true

## Cache

```cache
The core idea (sub-path through dict):

${concept.core_idea}

The structured details (deeper sub-path):

${concept.details.body}
```

## Steps

### writer

Use both sub-paths.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [concept.core_idea, concept.details.body]

```prompt
Write something based on the concept.
```

## Outputs

### output

The result.

- source: ${writer.response}
- type: string
