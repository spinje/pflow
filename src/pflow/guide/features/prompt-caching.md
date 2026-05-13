# Prompt Caching

Use prompt caching when one workflow sends the same long context, rubric,
instructions, source text, or parent value to multiple LLM calls or batch
items.

This guide covers LLM provider prompt caching:

- `## Cache` declares reusable prompt prefix chunks once per workflow.
- `prompt_cache: [...]` tells an LLM node which declared chunks to send before
  its prompt.
- `prewarm: true` lets batch nodes write the shared prefix once before parallel
  reads.

This is separate from pflow's local memo cache. `--no-cache` only bypasses
local memo-cache reads; it does not disable `## Cache`, `prompt_cache:`, or
`prewarm:`.

## First Action

Before editing cache fields, run:

```bash
pflow analyze-cache workflow.pflow.md
```

Read `## Recommended actions` first. It tells you exactly what to edit:

- add or extend `## Cache`
- add missing `prompt_cache: [...]`
- add `prewarm: true` for cacheable batches
- move stable prompt text before per-item data
- run per-child analysis commands for sub-workflows

Useful variants:

```bash
pflow analyze-cache workflow.pflow.md --no-trace-autoload # static analysis only
pflow analyze-cache workflow.pflow.md --from-trace <path> # inspect a specific run
pflow analyze-cache workflow.pflow.md --format=json       # machine-readable output
```

Trace files live at
`~/.pflow/debug/workflow-trace-<hash>-<name>-<timestamp>.json`. The default
command auto-loads the most recent matching trace when one exists.

`pflow run --dry-run` emits a one-line prompt-cache nudge when actionable
opportunities exist. It stays silent when the workflow already looks optimal.

## Minimal Pattern

````markdown
# Song Creator

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

Decide creative direction from the cached concept.

- type: llm
- prompt_cache: [concept]
- prompt: "Pick a creative direction for the cached concept."

### write-lyrics

Write lyrics using the cached concept and cached creative direction.

- type: llm
- prompt_cache: [concept, creative-direction.response]
- prompt: "Write lyrics from the cached concept and creative direction."
````

Important: do not repeat cached values in the prompt body. If
`prompt_cache: [concept]` sends `${concept}` as cached prefix text, then
`prompt:` should refer to the cached concept in prose, not include
`${concept}` again.

## Rules

`prompt_cache: [...]` items must match `## Cache` declaration order. This is a
hard validation error:

````markdown
## Cache

```cache
First:
${a}

Second:
${b}
```

### use-cache
- type: llm
- prompt_cache: [b, a]  # wrong: out of order
````

Fix by reordering the node field:

```markdown
- prompt_cache: [a, b]
```

Keep stable bytes first. Provider prompt caches work on shared prefixes, so
dynamic per-item text should come after stable instructions and cached chunks.

## TTL

Default TTL is 5 minutes. Omit `ttl` for the default `5m` behavior, or set
`1m` through `60m`; `1h` is accepted as an alias for `60m`.

````markdown
## Cache

- ttl: 11m

```cache
...
```
````

Gemini supports minute-level TTLs through pflow. Anthropic and OpenAI only
support pflow's discrete `5m` and `1h` behaviors today; pflow errors instead
of silently rounding an unsupported value.

## Batch Nodes

For `type: llm` nodes with `batch:`, add `prewarm: true` when the stable
text before the first per-item reference is large enough for the provider's
prompt cache minimum (1k–4k tokens depending on the model):

````markdown
### score-each-chorus

Score every chorus against a multi-page rubric.

- type: llm
- prewarm: true
- batch:
    items: ${choruses}
    parallel: true

```prompt
You are evaluating song choruses against the rubric below.

${rubric}

---

Score this chorus:
${item.text}
```
````

`${rubric}` here is a placeholder for substantial stable text — detailed
scoring criteria, reference materials, etc. — repeated identically across
every batch call. With `prewarm`, the first item writes that prefix to the
provider's cache, then the remaining items fan out as reads.

**The cache prefix ends at the first per-item reference.** Everything
before `${item.text}` — including static refs like `${rubric}` — is
resolved into the cached prefix. If you mix per-item refs into the middle,
the cached prefix is cut short, so put `${item.X}` content last.

If the analyzer doesn't recommend `prewarm: true`, adding it won't help —
the static prefix is below the provider's minimum or doesn't exist.

`prewarm: false` is a **marker for the analyzer**, not a runtime toggle —
runtime treats it the same as omitting the field. Use it to record that you've
considered prewarming and decided against it; the analyzer will then stop
recommending it on that node.

### Combining `## Cache` with prewarm

`## Cache` (declared chunks) and `prewarm: true` (auto batch-prefix) are
**orthogonal** — they place cache markers in different message regions and
can fire together. Pick by the shape of your workflow:

- **Only `prewarm: true`** when the stable bytes are confined to one batch
  node's template and don't appear elsewhere in the workflow.
- **Only `## Cache` + `prompt_cache: [chunk]`** when a value (rubric,
  reference document, instructions) is used by **multiple LLM nodes** that
  should share the cache, but no individual node is a batch.
- **Both** when a batch node uses a shared value AND has additional stable
  instruction text before the first per-item ref — declare the shared
  value in `## Cache` so other nodes also cache it, and add `prewarm: true`
  so the extra template text caches across batch items.

## Python-Assembled Prompts

Prompt caching works best when stable prompt text is visible in the LLM node's
`prompt:` field. If a code node builds a complete prompt string and the LLM
node only says `prompt: ${item.prompt}`, the analyzer cannot inspect the stable
prefix.

Opaque shape:

````markdown
### prepare-items

Assemble full per-item prompts in code.

- type: code
- inputs:
    rubric: ${rubric}
    dataset: ${dataset}
```python code
rubric: str
dataset: list
result: list = []
for text in dataset:
    result.append({"prompt": f"{rubric}\n\nProcess this: {text}"})
```

### process-items

Process prompts assembled by the code node.

- type: llm
- batch:
    items: ${prepare-items.result}
- prompt: ${item.prompt}
````

Prefer this shape when each item shares the same prefix:

````markdown
### prepare-items

Return only per-item dynamic data.

- type: code
- inputs:
    dataset: ${dataset}
```python code
dataset: list
result: list = [{"input_text": text} for text in dataset]
```

### process-items

Inline the stable prompt prefix in the LLM node.

- type: llm
- batch:
    items: ${prepare-items.result}

```prompt
Use this rubric:
${rubric}

Process this:
${item.input_text}
```
````

If each per-item prompt has different structure, different ordering, or
branch-specific sections, keep the code-node assembly. Provider prompt caching
needs byte-identical prefixes; not every prompt shape should be refactored.

## Sub-Workflows

Each `.pflow.md` declares its own `## Cache` block. Sub-workflows do not
inherit the parent's cache declaration.

When a child workflow reuses an input across multiple LLM nodes:

1. Open the child workflow.
2. Add that input to the child's own `## Cache`.
3. Add the chunk name to the child LLM nodes' `prompt_cache: [...]`.
4. Run the per-child command printed by `pflow analyze-cache`.

If both parent and child cache the same value, use the same prose label around
that value when practical. Matching prose, exact model, and prefix order can
help provider cache reads across files. Different variable names alone are not
a reason to edit; the provider sees rendered text, not pflow variable names.

## Provider Notes

- Anthropic: cache content must cross the model's minimum token threshold. If
  a declared prefix is too small, add more stable context, switch only if the
  analyzer recommends it, or leave it uncached.
- OpenAI: prompt caching is automatic for long prefixes. pflow still uses
  `prompt_cache:` to keep provider routing and retention aligned.
- Gemini: cache reads are the clearest proof that caching is working. Creation
  telemetry can be absent even when later calls read from the cache.

## Common Analyzer Findings

When the analyzer names one of these findings, apply the corresponding edit:

| Finding | What to do |
|---|---|
| `cache.shared-context-undeclared` | Add the suggested `## Cache` block or chunk. |
| `cache.prompt-cache-incomplete` | Add the missing chunk names to the listed LLM nodes. |
| `cache.sub-workflow-cache-undeclared` | Edit the child workflow; add its own `## Cache` and `prompt_cache:` entries. |
| `cache.batch-prewarm-recommended` | Add `prewarm: true` to the batch LLM node. |
| `cache.dynamic-before-static` | Move stable instructions/context before dynamic `${...}` text. |
| `cache.below-min-tokens` | Include more stable context or leave that small prefix uncached. |
| `cache.opaque-prompt` | Inline the stable prompt prefix into the LLM node when the prompt shape is uniform. |
| `cache.system-prompts-fragment-cache` | Keep `system:` uniform across nodes that should share the same cached prefix. |
| `cache.prompt-body-duplicates-cache` | Remove the duplicated value from `prompt:`; it already arrives through `prompt_cache:`. |
| `cache.prompt-body-shadows-cache` | Rewrite the prompt so cached content is not repeated by a parent/sub-path reference. |

## Other Findings You May See

These IDs can appear in validator output, trace-mode checks, or less common
cache-shape advisories:

| Finding | What to do |
|---|---|
| `cache.order-mismatch` | Reorder `prompt_cache: [...]` to match the order of chunks in `## Cache`. |
| `cache.invalid-on-non-llm` | Remove `prompt_cache:` or `prewarm:` from non-LLM nodes; those fields only apply to `type: llm`. |
| `cache.unsupported-provider-ttl` | Use `5m`/`1h`, or switch cached LLM nodes to Gemini for minute-level TTLs. |
| `cache.unused-chunk` | Remove the unused chunk from `## Cache`, or add it to a node's `prompt_cache: [...]` list. |
| `cache.padding-advisory` | Extend the node's `prompt_cache: [...]` list to include the earlier chunks the analyzer suggests. |
| `cache.prewarm-no-prefix` | Move stable instructions before the first `${item...}` reference, or remove `prewarm: true`. |
| `cache.consolidate-to-root-recommended` | Cache the larger root value instead of small sub-path chunks when the sub-paths are below the provider minimum. |
| `cache.heterogeneous-models-fragment-cache` | Use one exact model for nodes that should share a cache, or accept that each model writes its own cache. |
| `cache.first-call-write-penalty` | Remove `prompt_cache:` from one-off calls when no later call reads that cache. |
| `cache.cross-workflow-prose-mismatch` | Use the same prose around the cached value in both workflows when you want cross-file cache reuse. |
| `cache.discrepancy` | In trace mode, compare the reported cause: skipped chunks or runtime value changes. |

`cache.cross-workflow-rename-detected` is informational. Different variable
names alone do not break provider cache hits; edit names only when it improves
workflow readability.

The analyzer output is the source of truth for what to edit. Prefer its
paste-ready recommendations over manually guessing chunk names or order.
