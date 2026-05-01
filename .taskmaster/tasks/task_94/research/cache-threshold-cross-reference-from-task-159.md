# Cache threshold visibility — cross-reference from Task 159

> **Filed during Task 159 Stage 2 planning (2026-05-01).** When Task 94 lands,
> please read this before locking the command surface. The Task 159 analyzer
> has a real UX gap that Task 94 is the natural place to close.

## The gap

Task 159 ships `pflow analyze-cache` with a `cache.below-min-tokens` warning
when declared `## Cache` content is below the provider's minimum cache token
threshold. The warning identifies the threshold for the node's current
model (e.g. "Gemini's minimum is 4096 tokens"), but agents reading this
output **cannot answer the natural follow-up question**:

> "Are there other models with my cost / latency / quality profile that
>  WOULD cache content of this size?"

Per-model cache thresholds vary materially:

| Provider/family | Explicit threshold | Implicit (auto) |
|---|---|---|
| Anthropic Sonnet 4.5, Opus 4.1, Opus 4, Sonnet 4, Sonnet 3.7 | 1024 | n/a |
| Anthropic Sonnet 4.6, Haiku 3.5 | 2048 | n/a |
| Anthropic Opus 4.7, 4.6, 4.5, Haiku 4.5 | 4096 | n/a |
| Gemini Flash, Pro | 4096 | 1024 |
| OpenAI GPT/o-series | 1024 | 1024 |

(Live source: `src/pflow/core/llm_capabilities.py::MODEL_CAPABILITIES`.)

Without filtered model discovery, an agent has to consult the table in
`src/pflow/guide/features/caching.md`, then manually intersect with cost
/ quality constraints. That's the kind of work the agent should be able
to delegate to a single CLI invocation.

## The proposed shape

When a `cache.below-min-tokens` warning fires (or when greenfield
`## Cache` analysis shows shared content too small for the workflow's
declared model), the analyzer's suggestion would point at:

```
pflow llm list --min-cache-tokens=<your-content-size>
```

That command answers exactly the agent's follow-up: "show me models
that would cache content of this size." Numeric filter; no
prose-parsing required.

This mirrors top-10% codebases:
- rustc: error code → `rustc --explain E0XXX`
- ruff: rule ID → `ruff rule <ID>`
- mypy: error code → `mypy --help-error-codes <code>`
- TypeScript: error codes link to handbook URLs

The pattern is **identifier + on-demand expansion**. The analyzer flags
the issue + identifies the threshold; the model command is the
authoritative source on per-model capabilities. Cross-reference rather
than duplicate.

## Why this matters for Task 94 specifically

Task 94's current spec scope is "show available models based on
configured API keys" — narrow but valuable. Adding **per-model cache
thresholds + filtering** to the same command is a natural extension
because:

1. Same data source — model capability table
2. Same audience — agents trying to pick a model
3. Same display surface — `pflow registry describe llm` / `pflow
   discover` would show "available models" anyway; cache thresholds
   are one more capability column
4. Avoids creating a parallel command surface (`pflow cache list-models`
   would duplicate Task 94's dispatch logic)

If Task 94 implements `pflow llm list` (or chooses to put the listing
under `pflow registry describe llm`), the cache-threshold + filter
extension piggybacks at near-zero cost.

## Specific design considerations for the implementing agent

### 1. Cache threshold isn't a single number per model

Gemini has 1024 implicit / 4096 explicit. OpenAI has 1024 auto-cache
(implicit-equivalent). Anthropic models have only an explicit threshold.

The filter semantics should be explicit about which path:

- **Default**: filter on the **explicit** threshold (matches what
  pflow's `cache_control` markers actually trigger today).
- Optional: `--includes-implicit` flag to also surface models with an
  implicit cache path that would activate automatically.

Output should expose BOTH thresholds (explicit + implicit) so agents
can reason about them independently.

### 2. Filter composition

Boolean and numeric filters should compose. Suggested set for v1:

| Filter | Type | Source |
|---|---|---|
| `--supports-prompt-caching` | bool | LiteLLM `model_cost.supports_prompt_caching` (existing field) |
| `--min-cache-tokens` | int | `core/llm_capabilities.py::get_min_cache_tokens` |
| `--max-input-cost-per-mtok` | float | LiteLLM `model_cost.input_cost_per_token * 1_000_000` |
| `--max-output-cost-per-mtok` | float | LiteLLM `model_cost.output_cost_per_token * 1_000_000` |
| `--min-context-window` | int | LiteLLM `model_cost.max_input_tokens` |
| `--provider` | str (anthropic / openai / gemini / ollama) | `core/llm_providers.py::detect_provider` |

`--max-input-cost-per-mtok` is load-bearing for the cache-threshold
case — agents need to know "would caching on Sonnet save more than
the cost of switching from Gemini Flash to Sonnet?" Filtering by cost
makes that comparison cheap.

### 3. JSON output for agents

`pflow llm list --format=json` mirrors `pflow analyze-cache
--format=json`. Single-format consumer-rule (`startswith("X.")`)
applies. Schema suggestion:

```json
{
  "format_version": "1.0",
  "models": [
    {
      "model_id": "anthropic/claude-sonnet-4-5",
      "provider": "anthropic",
      "cache_min_tokens_explicit": 1024,
      "cache_min_tokens_implicit": null,
      "supports_prompt_caching": true,
      "input_cost_per_mtok": 3.0,
      "output_cost_per_mtok": 15.0,
      "context_window": 200000,
      "available": true,
      "available_reason": null
    }
  ]
}
```

The `available` + `available_reason` fields close Task 94's existing
scope — "is the API key configured for this model's provider?"

### 4. Source of truth

Two viable approaches:

- **(a)** Extend `core/llm_capabilities.py::ModelCapability` with
  pricing + context-window fields. Hardcoded — fewer staleness
  landmines for cache-specific data; new models require a code
  change.
- **(b)** Wrap LiteLLM's `model_cost` dict (carries pricing,
  `supports_prompt_caching`, `max_input_tokens`) and merge with
  `core/llm_capabilities.py` for the cache-threshold data LiteLLM
  doesn't expose well.

Approach **(b) with hardcoded overrides for cache thresholds** is
probably right — pricing changes drive update churn that hardcoded
tables can't keep up with, but cache thresholds are sticky enough
that hardcoding remains correct.

### 5. Bidirectional cross-reference

When Task 94 ships, **both directions** of the cross-reference need
wiring:

- `pflow llm show <model>` should include `see_also` to the caching
  guide (`pflow guide caching`).
- `pflow analyze-cache`'s `cache.below-min-tokens` suggestion should
  reference `pflow llm list --min-cache-tokens=<N>`.

The analyzer side requires extending `cache.below-min-tokens`
suggestion in `src/pflow/core/cache_analysis/warning_catalog.py:355`
(the `suggestions_template` field). The greenfield analysis path in
`src/pflow/core/cache_analysis/analyze.py::_populate_suggested_blocks`
should also drop a Notes line pointing at the command — agents
authoring `## Cache` for the first time benefit most.

## Acceptance criteria — when Task 94 implements this

A `pflow analyze-cache` run that emits `cache.below-min-tokens`
should be one CLI invocation away from "pick a model that would
work":

```bash
$ pflow analyze-cache my-workflow.pflow.md
...
1. Cache content below provider minimum on score-choruses  savings unavailable
   score-choruses: declared cache content is ~1600 tokens, below
   gemini/gemini-3-flash-preview's minimum of 4096; cache_control
   markers will silently no-op at the provider
   → Increase cache content above 4096 tokens by adding more chunks to
     ## Cache, OR remove `prompt_cache:` from score-choruses since the
     cache won't fire anyway, OR run
     `pflow llm list --min-cache-tokens=1600 --max-input-cost-per-mtok=1.0`
     to see models that would cache this content size at comparable cost.

$ pflow llm list --min-cache-tokens=1600 --max-input-cost-per-mtok=1.0
model_id                                  cache_min  input_cost_per_mtok  available
anthropic/claude-sonnet-4-5               1024       3.00                 yes
anthropic/claude-haiku-3-5                2048       0.80                 yes
openai/gpt-4o-mini                        1024       0.15                 yes
...
```

(Exact column set + filter semantics are implementing-agent's call.)

## Code touch points when wiring up

- `src/pflow/core/cache_analysis/warning_catalog.py:355` —
  extend `cache.below-min-tokens` `suggestions_template` to add the
  command reference. Keep the existing two suggestions (add chunks /
  remove declaration); add the model-discovery option as a third.
- `src/pflow/core/cache_analysis/analyze.py::_populate_suggested_blocks` —
  add a Notes-section line in greenfield mode pointing at the command.
  The size of the suggested cache block is computable; embed it
  directly in the suggested filter for one-click usability.
- `src/pflow/core/cache_analysis/render_text.py` — if the existing
  text rendering doesn't naturally surface the new suggestion clause,
  extend the recommended-actions multi-line block to include it.
- `src/pflow/guide/features/caching.md` — replace the static
  per-model threshold table with a pointer at `pflow llm list`
  (the dynamic source of truth). Keep a small reference table in the
  guide for at-a-glance readers; cross-reference the command for
  authoritative live data.

## What NOT to do

- **Don't** add a separate `pflow cache list-models` command — would
  duplicate Task 94's dispatch logic.
- **Don't** inline the per-model threshold table in the
  `cache.below-min-tokens` warning context — inflates context with
  data most agents don't need; the filter command is the right
  interface.
- **Don't** prescribe a model swap from the analyzer side. Model
  choice is multi-dimensional (cost, quality, speed, capabilities).
  Surface threshold mismatches; let the agent reason about trade-offs.
  See "Why no model swap?" in `cache_threshold_visibility` discussion
  notes (referenced from the code comments at
  `core/cache_analysis/warning_catalog.py:340` and
  `core/llm_capabilities.py:33`).

## References

- Live data: `src/pflow/core/llm_capabilities.py::MODEL_CAPABILITIES`
  (per-model cache thresholds, DD#32 from Task 159).
- Warning emission: `src/pflow/core/cache_analysis/warning_catalog.py:340`
  (`cache.below-min-tokens` catalog entry).
- Emission gates:
  `src/pflow/core/cache_analysis/analyze.py::_per_node_warnings`
  (around line 764 — gates on `declared_prompt_cache`,
  `cacheable_data_source != "trace"`).
- Reference table:
  `src/pflow/guide/features/caching.md` ("Per-model thresholds at a
  glance").
- Task 159 spec DD#32:
  `.taskmaster/tasks/task_159/task-159.md` lines 105-110.
- Top-10% pattern (cross-reference identifier + on-demand expansion):
  rustc `--explain`, ruff `rule`, mypy `--help-error-codes`,
  TypeScript handbook URLs.
