# Consolidate To Root Recommended

## Inputs

### concept

A structured object with sub-fields. Individual fields are below the
provider threshold; the whole object would clear it.

- type: object
- required: true

## Cache

```cache
The core idea:

${concept.core_idea}

The title:

${concept.title}
```

## Steps

### writer

Use both sub-paths.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [concept.core_idea, concept.title]

```prompt
Write something.
```

## Outputs

### output

Result.

- source: ${writer.response}
- type: string
