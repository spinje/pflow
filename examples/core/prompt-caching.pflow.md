# Prompt Caching with Shared Context

Demonstrates the `## Cache` block and per-node `prompt_cache:` opt-in.
Three downstream LLM calls share one stable analysis chunk: the first
call writes it to the provider's prompt cache, the next two read it at
~10% of input cost.

* Flow: `extract` (writes cache) → `summarize` / `translate` / `tag` (read cache)
* Run static analysis: `pflow analyze-cache examples/core/prompt-caching.pflow.md`
* Reference: `pflow guide caching`

> Greenfield `analyze-cache` reports cacheable tokens as unavailable for
> chunks referencing upstream node outputs (here, `${extract.response}`).
> Run the workflow once to populate the memo cache, then re-run
> `analyze-cache` to see real cache projections.

## Inputs

### article

The article text to analyze.

- type: string
- required: true

## Cache

The structured analysis flows verbatim into the cacheable system prefix
of every node that lists it in `prompt_cache:`. Order in `prompt_cache:`
must match the declaration order below; out-of-order is a hard error
(`cache.order-mismatch`). Default TTL is 5 minutes; opt into 1h with
`- ttl: 1h` here for workflows that re-run within the hour.

```cache
The structured analysis of the article — key facts, themes, and entities
extracted by the upstream `extract` node:

${extract.response}
```

## Steps

### extract

Producer of the cached chunk. Itself uncached — it's the upstream that
populates the cache for downstream nodes to read.

- type: llm
- model: anthropic/claude-haiku-4-5
- temperature: 0.3

```prompt
Extract a structured analysis of this article: key facts (3–5 bullets),
themes (2–3), and named entities. Article: ${article}
```

### summarize

Reuses `extract.response` as cached context. The first call after
`extract` runs writes the provider cache; the next two readers
(`translate`, `tag`) hit it.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [extract.response]

```prompt
Write a 3-sentence summary suitable for a newsletter blurb.
```

### translate

Reads the cached `extract.response` to produce a Spanish translation
of the key facts.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [extract.response]

```prompt
Translate the key facts to Spanish, preserving entity names verbatim.
```

### tag

Reads the cached `extract.response` to produce CMS-style topical tags.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [extract.response]

```prompt
Generate exactly 5 topical tags suitable for a CMS taxonomy.
```

## Outputs

### summary

Newsletter-ready summary.

- source: ${summarize.response}
- type: string

### translation

Spanish translation of the key facts.

- source: ${translate.response}
- type: string

### tags

Five topical tags.

- source: ${tag.response}
- type: string
