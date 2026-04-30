# Attack A5b — control: same chunks, no branching

Identical to A5 but no branching. Verifies node outputs ARE reachable as cache chunks.

## Inputs

### topic

The topic.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The topic:

${topic}

Path A specialty data:

${path-a.stdout}
```

## Steps

### path-a

Path A — runs unconditionally.

- type: shell

```shell command
echo "Path A specialty content"
```

### emit

LLM call referencing both chunks.

- type: llm
- prompt_cache: [topic, path-a.stdout]
- model: anthropic/claude-haiku-4-5
- max_tokens: 20

```prompt
Just say "ok".
```
