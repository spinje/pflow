# Prompt Caching

**Use when**: Multiple LLM calls share large stable context (15k+ tokens). Provider-level prompt caching cuts input cost 50-90% on shared prefixes.

pflow has **two cache layers**:

| Layer | Field | What it does |
|-------|-------|--------------|
| pflow memo cache | `cache: false` (per node) | Disables pflow's local re-execution cache. Independent of LLM provider caches. |
| LLM provider cache | `prompt_cache: [...]` (per node) + `## Cache` (per workflow) | Enables Anthropic/OpenAI/Gemini server-side prompt caching. Cuts input cost on shared prefixes. |

`--no-cache` flag disables ONLY the memo layer; LLM provider caching still fires when declared.

## Quick Start

````markdown
# Song Creator

A workflow with cross-call cached context.

## Inputs

### concept

The song concept to build around.

- type: string

## Cache

- ttl: 5m

```cache
The concept we are building this song around:

${concept}

The creative direction decisions:

${creative-direction.response}
```

## Steps

### creative-direction

Decide creative direction based on the concept.

- type: llm
- prompt_cache: [concept]
- prompt: "Pick a creative direction for: ${concept}"

### write-lyrics

Write lyrics using the cached concept + creative direction.

- type: llm
- prompt_cache: [concept, creative-direction.response]
- prompt: "Write lyrics."
````

The `## Cache` block declares stable context shared across LLM calls. Each `prompt_cache: [...]` opt-in lists a subset of declared chunks **in declaration order** (out-of-order is a hard error).

## Discovering Opportunities

Run `pflow analyze-cache` to find cache opportunities, predict savings, and check declarations:

```bash
pflow analyze-cache workflow.pflow.md
pflow analyze-cache workflow.pflow.md --format=json
pflow analyze-cache workflow.pflow.md --from-trace ~/.pflow/debug/trace.json
```

Outputs include: per-node cache ratio, recommended actions, suggested ## Cache block (greenfield), warnings about misordered declarations, padding advisories.

`pflow run --dry-run` emits a one-line nudge when actionable opportunities exist; silent on optimal plans.

## Order Invariant

`prompt_cache: [a, b, c]` items MUST match `## Cache` declaration order. Out-of-order is a hard error:

```
ERROR: Node 'review' prompt_cache order doesn't match ## Cache declaration
  expected:  [concept, concept_brief]
  you wrote: [concept_brief, concept]
  fix:       reorder the `prompt_cache:` field to match ## Cache declaration order
```

## Order Invariant — Why

Prefix-based caching requires bytes-identical prefix across calls. Reordering breaks that. pflow validates declaration order rigidly; the workflow file is the source of truth for what the LLM will see.

## TTL Opt-In

Default TTL is 5 minutes (provider default). Long-running workflows or reruns benefit from `- ttl: 1h`:

```markdown
## Cache

- ttl: 1h

```cache
...
```
```

Extended TTL costs 2× on cache writes (vs 1.25× on 5-min) — opt in only when ≥3 reads will fire within the hour. `pflow analyze-cache` recommends when net-positive.

## Auto Batch-Prefix Caching

For `type: llm` nodes with `batch:`, add `- prewarm: true` to:
1. Run the first item synchronously (writing the cache).
2. Fan out the remaining N-1 items in parallel as cache reads.

```markdown
### score-each-chorus

Score every chorus against the rubric.

- type: llm
- prewarm: true
- prompt: "${rubric}\n\nScore: ${item.text}"
- batch:
    items: ${choruses}
    parallel: true
```

Without `prewarm`, all N items race to write the cache simultaneously and pay the write cost without reads. `pflow analyze-cache` emits `cache.batch-prewarm-recommended` when prewarming would save ≥5%.

## Sub-Workflows

Each `.pflow.md` declares its own `## Cache` block. Sub-workflows render their own cache; they do NOT inherit the parent's. Cross-workflow cache hits happen incidentally at the byte level when prose labels match across boundaries.

`pflow analyze-cache` walks across workflow boundaries (Tier 2) and warns about:

- **Renames**: parent passes `${concept_brief}` to a child input named `creative_brief`.
- **Prose mismatches**: parent and child both declare `concept` but with different prose-before.

## Provider-Specific Notes

- **Anthropic**: per-model minimum cache size (1024 tokens for Sonnet 4.5; 2048 for Sonnet 4.6 / Haiku 3.5; 4096 for Opus 4.5+, Haiku 4.5). Cache writes 1.25× (5-min) or 2× (1h); reads 0.1×.
- **OpenAI**: automatic at ≥1024 tokens. Markers are no-ops; `prompt_cache_key` (auto-emitted) improves hit rate on parallel batches. `prompt_cache_retention: "24h"` is set on `- ttl: 1h` workflows.
- **Gemini**: explicit caching via LiteLLM's `cachedContents`. Telemetry caveat — `cache_creation_input_tokens` is 0/absent even when caching is working; verify via `cache_read_input_tokens` on subsequent calls.

## Catalog of Warning IDs

| ID | Severity | Triggered by |
|---|---|---|
| `cache.order-mismatch` | error | per-node `prompt_cache:` order ≠ `## Cache` declaration |
| `cache.unused-chunk` | warning | declared chunk no node references |
| `cache.invalid-on-non-llm` | error | `prompt_cache:` or `prewarm:` on a non-LLM node |
| `cache.shared-context-undeclared` | info | analyzer found shared context not in any `## Cache` |
| `cache.batch-prewarm-recommended` | warning | batch ≥5% cacheable, no explicit `prewarm:` |
| `cache.dynamic-before-static` | warning | `${var}` precedes the cacheable prefix in a prompt |
| `cache.padding-advisory` | info | extending `prompt_cache:` would unlock prefix hits |
| `cache.below-min-tokens` | warning | declared cache content below provider minimum |
| `cache.cross-workflow-rename-detected` | info | parent value name ≠ child input name across boundary |
| `cache.cross-workflow-prose-mismatch` | info | same chunk identifier, different prose across files |
| `cache.discrepancy` | info | `--from-trace` mode found predicted ≠ actual hit ratio |
| `cache.prewarm-no-prefix` | info | `prewarm: true` declared but no static prefix exists |

`cache.opportunities-available` is the dry-run nudge ID (separate from the catalog).
