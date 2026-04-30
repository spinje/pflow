# Attack A5c — control: same as A5b but with underscore instead of hyphen

If `path-a.stdout` was reported ABSENT but `path_a.stdout` resolves correctly,
the bug is in how hyphenated node IDs interact with the cache resolver.

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

Path data:

${path_a.stdout}
```

## Steps

### path_a

Underscore-named shell node.

- type: shell

```shell command
echo "Path A specialty content"
```

### emit

LLM call referencing both chunks.

- type: llm
- prompt_cache: [topic, path_a.stdout]
- model: anthropic/claude-haiku-4-5
- max_tokens: 20

```prompt
Just say "ok".
```
