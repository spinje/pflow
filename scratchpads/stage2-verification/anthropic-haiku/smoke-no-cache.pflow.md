# Anthropic Haiku Cache Smoke (no `## Cache`)

Six LLM calls each independently asking different questions about the
MERIDIAN reference. No `## Cache` block — every call sends the full
reference inline. This is the true zero-cache baseline (Anthropic has
no implicit cache).

## Inputs

### context

Stable reference body sent inline in every call.

- type: string
- required: true

## Steps

### answer-1

Asks the magic value question. On first cached run this writes the cache; subsequent calls read it.

- type: llm
- model: anthropic/claude-haiku-4-5
- max_tokens: 80

```prompt
Reference document:

${context}

Question: What is the magic value of a MERIDIAN frame and which byte offset carries it?

Answer in one sentence.
```

### answer-2

Asks about error code grouping. Reads the cache populated by answer-1.

- type: llm
- model: anthropic/claude-haiku-4-5
- max_tokens: 80

```prompt
Reference document:

${context}

Question: How are MERIDIAN error codes grouped by class?

Answer in one sentence.
```

### answer-3

Asks about the HEARTBEAT payload. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- max_tokens: 80

```prompt
Reference document:

${context}

Question: What does a HEARTBEAT frame carry in its payload, and within what timeout must the receiver echo it back?

Answer in one sentence.
```

### answer-4

Asks about the congestion-window starting value. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- max_tokens: 80

```prompt
Reference document:

${context}

Question: What is the default congestion window starting value for MERIDIAN, expressed in MSS units?

Answer in one sentence.
```

### answer-5

Asks about the RTO floor/cap. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- max_tokens: 80

```prompt
Reference document:

${context}

Question: What is the recommended floor and cap for the RTO timer per RFC 6298?

Answer in one sentence.
```

### answer-6

Asks about MERIDIAN version migration timing. Reads the cache.

- type: llm
- model: anthropic/claude-haiku-4-5
- max_tokens: 80

```prompt
Reference document:

${context}

Question: When migrating from MERIDIAN v1.0 or v1.1 to v1.2, how long should mixed-version traffic run before older versions are disabled?

Answer in one sentence.
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
