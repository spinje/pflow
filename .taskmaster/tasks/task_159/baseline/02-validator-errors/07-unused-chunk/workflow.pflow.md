# Unused Cache Chunk

## Inputs

### article

The article text.

- type: string
- required: true

### topic

The topic.

- type: string
- required: true

## Cache

```cache
The article:

${article}

The topic:

${topic}
```

## Steps

### summarize

Summarize the article. References `article` (cached) and uses `topic` ONLY in
the prompt body — `topic` is declared in ## Cache but unreferenced by any
prompt_cache:, so `cache.unused-chunk` should fire.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [article]

```prompt
Summarize this on the topic of ${topic}.
```

## Outputs

### summary

The summary text.

- source: ${summarize.response}
- type: string
