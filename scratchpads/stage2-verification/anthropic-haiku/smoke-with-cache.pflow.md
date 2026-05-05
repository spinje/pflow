# Anthropic Haiku Cache Smoke (with `## Cache`)

Six LLM calls sharing the MERIDIAN reference via `## Cache`. First run:
1 cache write + 5 cache reads. Rerun within TTL: 6 cache reads.

Spec target on this shape:
- First run: ~60% reduction (1 write at 1.25× + 5 reads at 0.1× vs 6 full)
- Rerun within TTL: ~90% reduction (6 reads at 0.1× vs 6 full)

## Inputs

### context

Stable reference body cached as system prefix.

- type: string
- required: true

## Cache

- ttl: 1h

```cache
The following is a stable reference document. Treat it as authoritative
context for any questions in this conversation.

${context}
```

## Steps

### answer-1

Asks the magic value question. On first cached run this writes the cache; subsequent calls read it.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: What is the magic value of a MERIDIAN frame and which byte offset carries it?

Answer in one sentence using the reference document.
```

### answer-2

Asks about error code grouping. Reads the cache populated by answer-1.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: How are MERIDIAN error codes grouped by class?

Answer in one sentence using the reference document.
```

### answer-3

Asks about the HEARTBEAT payload. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: What does a HEARTBEAT frame carry in its payload, and within what timeout must the receiver echo it back?

Answer in one sentence using the reference document.
```

### answer-4

Asks about the congestion-window starting value. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: What is the default congestion window starting value for MERIDIAN, expressed in MSS units?

Answer in one sentence using the reference document.
```

### answer-5

Asks about the RTO floor/cap. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: What is the recommended floor and cap for the RTO timer per RFC 6298?

Answer in one sentence using the reference document.
```

### answer-6

Asks about MERIDIAN version migration timing. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [context]
- max_tokens: 80

```prompt
Question: When migrating from MERIDIAN v1.0 or v1.1 to v1.2, how long should mixed-version traffic run before older versions are disabled?

Answer in one sentence using the reference document.
```

## Outputs

### a1
source: answer-1.response

### a2
source: answer-2.response

### a3
source: answer-3.response

### a4
source: answer-4.response

### a5
source: answer-5.response

### a6
source: answer-6.response
