# Level 2

## Inputs

### article

Long article from parent.

- type: string
- required: true

## Cache

```cache
The article (level 2 cache):

${article}
```

## Steps

### preprocess

Preprocess at level 2 with own cache.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [article]

```prompt
Extract key entities.
```

### grandchild

Invoke level-3 grandchild.

- type: workflow
- workflow: ./level3/level3.pflow.md
- inputs:
    article: ${article}
    entities: ${preprocess.response}

## Outputs

### summary

Summary from grandchild.

- source: ${grandchild.summary}
- type: string
