# Prompt Caching with Multiple Cache Chunks

Declares three `## Cache` chunks ordered **stable-to-volatile**. On Anthropic,
every declared chunk becomes its own independently cacheable boundary (up to
4 per request), so each chunk's cache covers everything before it and you
get per-chunk reuse instead of a single all-or-nothing cache.

* Flow: `summarize` and `translate` each read all three cached chunks
* Run static analysis: `pflow analyze-cache examples/core/prompt-caching-multi-chunk.pflow.md`
* Reference: `pflow guide caching` (see "Order chunks stable-to-volatile")

When `${article}` changes between calls, the `system_prompt` + `knowledge_ref`
+ `session_context` caches all still hit. When the session changes,
`system_prompt` + `knowledge_ref` still hit. Reversing the order — putting
the most volatile chunk first — would invalidate every cache on each change.

## Inputs

### article

The article text to analyze.

- type: string
- required: true

### session_id

A per-session identifier used to scope session-level context. Changing
this invalidates only the session chunk and below.

- type: string
- required: true

## Cache

Three chunks declared stable-to-volatile:

1. `system_prompt` — base instructions, rarely changes
2. `knowledge_ref` — domain glossary, occasionally updated
3. `session_context` — per-session data

Default TTL is 5 minutes; use `- ttl: 1h` for hour-long sessions.

```cache
System role and overall task definition:
${system_prompt}

Domain glossary and reference material:
${knowledge_ref}

Session context:
${session_context}
```

## Steps

### system_prompt

The most stable chunk producer: a fixed task definition.

- type: shell

```command
echo "You are a careful editor. Cite specific terms from the article when answering."
```

### knowledge_ref

Occasionally-updated glossary content.

- type: shell

```command
echo "Glossary: 'lede' = first sentence; 'nut graf' = thesis paragraph; 'kicker' = closing line."
```

### session_context

Per-session context, scoped by ${session_id}.

- type: shell

```command
echo "Session ${session_id}: editorial style is concise, formal, no emoji."
```

### summarize

Reads all three cached chunks plus the per-call article.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [system_prompt, knowledge_ref, session_context]

```prompt
Summarize this article in three sentences, applying the glossary terms
where they fit. Article: ${article}
```

### translate

Reads the same three cached chunks. Under Anthropic multi-breakpoint, the
second call reuses each per-chunk prefix independently.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [system_prompt, knowledge_ref, session_context]

```prompt
Translate the article to formal Spanish. Article: ${article}
```

## Outputs

### summary

Three-sentence editorial summary.

- source: ${summarize.response}
- type: string

### translation

Formal Spanish translation.

- source: ${translate.response}
- type: string
