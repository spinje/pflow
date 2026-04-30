# Attack A3 — chunk vars resolving to non-string complex values

Tests deterministic-JSON serialization for dict / list / nested. Hash-vs-prep
byte-identity hinges on `_deterministic_serialize` producing the same bytes at
both call sites.

## Inputs

### dict_input

A dict input.

- type: object
- default:
    a: 1
    z: 2

### list_input

A list input.

- type: array
- default: [hello, world]

## Cache

- ttl: 5m

```cache
A dict (sorted-keys serialized):

${dict_input}

A list:

${list_input}
```

## Steps

### use-complex-cache

LLM node referencing both complex-typed chunks.

- type: llm
- prompt_cache: [dict_input, list_input]
- model: anthropic/claude-haiku-4-5
- max_tokens: 30

```prompt
Just say "ok" and nothing else.
```
