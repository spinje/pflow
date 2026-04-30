# Attack A5 — ABSENT chunk via branch-not-taken

A workflow with conditional branching where the LLM call's `prompt_cache:`
references a chunk whose `${var}` is the output of a node that didn't execute.

Verifies:
1. The ABSENT chunk is filtered symmetrically (hash-side + prep-side).
2. `cache_chunks_skipped` records the skipped chunk name in trace.
3. The LLM call still succeeds (skipping ABSENT chunks is graceful).

## Inputs

### route

Which path to take.

- type: string
- required: true

## Cache

- ttl: 5m

```cache
The route taken (always present):

${route}

Path A's specialty data (only present when route=A):

${path-a.stdout}

Path B's specialty data (only present when route=B):

${path-b.stdout}
```

## Steps

### router

Route to A or B based on input.

- type: code
- inputs:
    route: ${route}

```python code
route: str

if route == 'A':
    next: str = 'path-a'
elif route == 'B':
    next: str = 'path-b'
else:
    next: str = 'path-a'  # default
```

### path-a

Path A — only runs when route=A.

- type: shell
- next: emit

```shell command
echo "Path A specialty content"
```

### path-b

Path B — only runs when route=B.

- type: shell
- next: emit

```shell command
echo "Path B specialty content"
```

### emit

LLM call referencing all three chunks. Path A's chunk OR path B's chunk
will be ABSENT (depending on route).

- type: llm
- prompt_cache: [route, path-a.stdout, path-b.stdout]
- model: anthropic/claude-haiku-4-5
- max_tokens: 20

```prompt
Just say "ok" and nothing else.
```
