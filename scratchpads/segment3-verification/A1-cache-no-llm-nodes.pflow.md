# Attack A1 — `## Cache` declared but ZERO LLM nodes

A workflow that declares `## Cache` but has only a shell node. Should not crash;
should warn `cache.unused-chunk` for every chunk. Verifies runtime doesn't choke
when there's nothing to render.

## Inputs

### subject

The subject.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The subject we are processing:

${subject}
```

## Steps

### no-llm-step

A shell node — no LLM, no cache rendering.

- type: shell

```shell command
echo "subject was: ${subject}"
```
