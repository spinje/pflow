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
pflow analyze-cache workflow.pflow.md                    # auto-loads most recent matching trace
pflow analyze-cache workflow.pflow.md --format=json
pflow analyze-cache workflow.pflow.md --no-trace-autoload # skip auto-load; static analysis only
pflow analyze-cache workflow.pflow.md --from-trace <path> # explicit trace (any path)
```

Trace files live at `~/.pflow/debug/workflow-trace-<hash>-<name>-<timestamp>.json`; auto-load matches by workflow path, so the explicit `--from-trace` form is only needed when pointing at a trace from another workflow or location.

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

Allowed values are exactly `5m` and `1h`; other TTLs are rejected. Omit `ttl`
for the default `5m` behavior.

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

## Python-Assembled Prompts

When an LLM node's `prompt:` is just a single `${...}` reference whose source is a `type: code` node, static analysis cannot inspect what's inside the assembled prompt. Cache opportunities (shared prefixes, prewarm candidates) go undetected. `pflow analyze-cache` emits `cache.opaque-prompt` for this pattern.

This commonly looks like one of these shapes:

```markdown
### prepare-items
- type: code
- inputs:
    rubric: ${rubric}
```python code
items = []
for x in dataset:
    items.append({
        "prompt": f"{rubric}\n\nProcess this: {x}",  # static prefix + dynamic tail
        ...
    })
result: list = items
```

### process-items
- type: llm
- batch:
    items: ${prepare-items.result}
- prompt: ${item.prompt}     # opaque to static analysis
```

When the assembly produces a stable prefix + per-item dynamic tail, refactor the LLM node to consume the dynamic data directly and inline the stable bytes:

```markdown
### prepare-items
- type: code
- inputs:
    dataset: ${dataset}
```python code
# Code node now produces only per-item dynamic data — no prompt assembly.
result: list = [{"input_text": x} for x in dataset]
```

### process-items
- type: llm
- batch:
    items: ${prepare-items.result}
- prompt: |
    [stable rubric / instructions / persona — same bytes for every item]
    ${rubric}

    Process this: ${item.input_text}
```

After the refactor the static walkers see the prompt template directly:
- `cache.batch-prewarm-recommended` fires on the stable prefix when savings ≥ 5%
- `cache.shared-context-undeclared` detects shared `${var}` references for declaration in `## Cache`
- `cache.dynamic-before-static` flags ordering issues that would block caching

**When refactoring doesn't apply.** If each per-item prompt is structurally different (different sections, different ordering, content that varies based on per-item branching), the prompts are inherently uncacheable — provider-level prefix caching needs byte-identical prefixes across calls. In that case the code-node assembly is the right shape; `cache.opaque-prompt` is honestly telling you no caching opportunity is detectable, not that the workflow is broken.

## Sub-Workflows

Each `.pflow.md` declares its own `## Cache` block. Sub-workflows render their own cache; they do NOT inherit the parent's. If a child workflow reuses an input across multiple LLM nodes, declare that input in the child workflow's own `## Cache` and add it to the child nodes' `prompt_cache:` lists.

Matching prose labels, exact model, and prefix ordering can help incidental provider-level cache hits across workflow boundaries. That is byte-level alignment, not inheritance; every workflow that reuses a value still needs its own cache declaration.

`pflow analyze-cache` walks across workflow boundaries (Tier 2) and warns about:

- **Renames**: parent passes `${concept_brief}` to a child input named `creative_brief`.
- **Prose mismatches**: parent and child both declare `concept` but with different prose-before.

## Provider-Specific Notes

- **Anthropic**: per-model minimum cache size; rendered cache content below the threshold silently no-ops at the provider, so pflow emits `cache.below-min-tokens`. Thresholds (canonical source: `src/pflow/core/llm_capabilities.py`):

  | Threshold | Models |
  |---|---|
  | 1024 tokens | Sonnet 4.5, Sonnet 4, Sonnet 3.7, Opus 4, Opus 4.1 |
  | 2048 tokens | Sonnet 4.6, Haiku 3.5 |
  | 4096 tokens | Opus 4.5, Opus 4.6, Opus 4.7, Haiku 4.5 |

  Unknown models fall back to a 4096-token conservative floor. Cache writes cost 1.25× base (5-min TTL) or 2× base (1h TTL); reads cost 0.1× base.
- **OpenAI**: automatic at ≥1024 tokens. Markers are no-ops; `prompt_cache_key` (auto-emitted) improves hit rate on parallel batches. `prompt_cache_retention: "24h"` is set on `- ttl: 1h` workflows.
- **Gemini**: explicit caching via LiteLLM's `cachedContents`. Telemetry caveat — `cache_creation_input_tokens` is 0/absent even when caching is working; verify via `cache_read_input_tokens` on subsequent calls.

`llm_usage.input_tokens` is normalized to total prompt/input tokens, including cached prefixes. Use `uncached_input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` to inspect the split.

## Catalog of Warning IDs

| ID | Severity | Triggered by |
|---|---|---|
| `cache.order-mismatch` | error | per-node `prompt_cache:` order ≠ `## Cache` declaration |
| `cache.unused-chunk` | warning | declared chunk no node references |
| `cache.invalid-on-non-llm` | error | `prompt_cache:` or `prewarm:` on a non-LLM node |
| `cache.shared-context-undeclared` | info | analyzer found shared context not in any `## Cache` |
| `cache.sub-workflow-cache-undeclared` | info | child workflow reuses an input but lacks its own `## Cache` chunk |
| `cache.batch-prewarm-recommended` | warning | batch ≥5% cacheable, no explicit `prewarm:` |
| `cache.dynamic-before-static` | warning | `${var}` precedes the cacheable prefix in a prompt |
| `cache.padding-advisory` | info | extending `prompt_cache:` would unlock prefix hits |
| `cache.below-min-tokens` | warning | declared cache content below provider minimum |
| `cache.cross-workflow-rename-detected` | info | parent value name ≠ child input name across boundary |
| `cache.cross-workflow-prose-mismatch` | info | same chunk identifier, different prose across files |
| `cache.discrepancy` | info | `--from-trace` mode found predicted ≠ actual hit ratio |
| `cache.prewarm-no-prefix` | info | `prewarm: true` declared but no static prefix exists |
| `cache.consolidate-to-root-recommended` | info | sub-path cache chunks are below threshold but their root value would cache |
| `cache.heterogeneous-models-fragment-cache` | warning | shared cached chunks are declared across multiple exact models |
| `cache.first-call-write-penalty` | info | one exact-model call declares `prompt_cache:` with no later reads to amortize the write |
| `cache.system-prompts-fragment-cache` | warning | shared cached chunks declared across nodes with distinct `system:` instructions |
| `cache.opaque-prompt` | info | LLM node's prompt is a single `${var}` ref to a `type: code` node — refactor inline for cache detection |
| `cache.prompt-body-duplicates-cache` | error | prompt body repeats a value already supplied by `prompt_cache:` |
| `cache.prompt-body-shadows-cache` | warning | prompt body overlaps a cached chunk by parent/sub-path |
| `llm.thinking-temperature-mismatch` | error | Anthropic `reasoning_effort` is combined with `temperature` other than 1.0 |

`cache.opportunities-available` is the dry-run nudge ID (separate from the catalog).

### Cross-node cache sharing requires uniform `system:`

Provider cache prefixes include the `system:` content. When two LLM nodes share
`prompt_cache:` chunks but declare different `system:` instructions, each node
creates its own cache namespace. Cross-node sharing does not fire. Each node
still benefits from cross-invocation cache reads, such as parallel batch
fan-out, but workflow-wide savings are lower than if `system:` were uniform.

`pflow analyze-cache` surfaces this pattern as
`cache.system-prompts-fragment-cache`. To unlock cross-node sharing, move
role-specific text from `system:` into the `prompt:` body and keep `system:`
uniform across nodes that share cache chunks.
