# Attack A2 — `prompt_cache: []` empty list (edge case)

Per DD#19 + spec edge cases: empty `prompt_cache: []` should be valid and
equivalent to absence — no cache markers, no `prompt_cache` key in config hash.

## Inputs

### subject

The subject.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The subject for context:

${subject}
```

## Steps

### no-cache-opt-in

LLM node with explicit empty `prompt_cache: []` — should NOT render cache.

- type: llm
- prompt_cache: []
- model: anthropic/claude-haiku-4-5
- max_tokens: 50

```prompt
Just say "ok" and nothing else.
```
