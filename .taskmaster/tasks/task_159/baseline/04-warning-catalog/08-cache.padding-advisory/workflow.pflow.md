# Padding Advisory

## Inputs

### a

Stable input A.

- type: string
- required: true

### b

Stable input B.

- type: string
- required: true

### c

Stable input C.

- type: string
- required: true

## Cache

```cache
The first stable value:

${a}

The second stable value:

${b}

The third stable value:

${c}
```

## Steps

### producer

Producer of the first cache write — references all three (largest subset).

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [a, b, c]

```prompt
Acknowledge.
```

### consumer

Consumer that uses only [c] — could pad to [a, b, c] to hit upstream cache.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt_cache: [c]

```prompt
Use only c.
```

## Outputs

### producer-out

Producer output.

- source: ${producer.response}
- type: string

### consumer-out

Consumer output.

- source: ${consumer.response}
- type: string
