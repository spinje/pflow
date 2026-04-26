Here's a mockup based on the spec + my current understanding. Using lyrics-generator (the motivating workflow) and assuming Case 1 (no `## Cache` block declared yet — the most useful "greenfield" agent flow).

## Text output (default)

```
$ pflow analyze-cache lyrics-generator.pflow.md
```

```
# Cache Analysis: lyrics-generator.pflow.md

Confidence: low (no trace data — estimates from static analysis only)

## Summary

  Current cost per run:        ~$0.45
  Optimized cost per run:      ~$0.18  (-60%)
  Cost on rerun (within TTL):  ~$0.10  (-78%)

  3 opportunities  •  1 hard error blocks running

## Top opportunities

  1. [cache.shared-context-undeclared]
     Add ## Cache block — 4 high-reuse contexts shared across 15 LLM calls
     Saves: ~$0.27/run
     Affects: write-lyrics, review-narrative, review-emotional, suno-prompt, +11 more
     Action: paste the suggested block below into song-creator.pflow.md

  2. [cache.batch-prewarm-required]  ERROR — blocks `pflow run`
     chorus-chooser.score-choruses: 34-item batch with 2.1k-token static prefix
     has no prewarm decision. Without prewarm, all 34 calls write cache
     simultaneously (~$0.12/run wasted).
     Action: add `- prewarm: true` (recommended) or `- prewarm: false` to the node.

  3. [cache.padding-advisory]
     review-narrative could pad subset for prefix hits (~$0.03/run).
     Add [concept, creative-direction.response] before existing
     [song-architecture.response] to hit upstream cache writes at 0.1× read.

## Suggested ## Cache block

  Paste between ## Inputs and ## Steps in song-creator.pflow.md:

  ## Cache

  - ttl: 5m

  ```cache
  <DESCRIBE THE CONCEPT — appears verbatim in cached system prefix>

  ${concept}

  <DESCRIBE THE CREATIVE DIRECTION>

  ${creative-direction.response}

  <DESCRIBE THE SONG ARCHITECTURE>

  ${song-architecture.response}

  <DESCRIBE THE EASTER EGGS CONTEXT>

  ${easter-eggs.response}
  ```

  Per-node prompt_cache: additions:
    write-lyrics:     [concept, creative-direction.response, song-architecture.response, easter-eggs.response]
    review-narrative: [concept, creative-direction.response, song-architecture.response]
    suno-prompt:      [concept, song-architecture.response]
    ... (12 more — see --format=json for full list)

## Per-call cache report

  node                             model                          in_tok  cacheable  ratio
  ──────────────────────────────────────────────────────────────────────────────────────────
  creative-direction               anthropic/claude-sonnet-4-5     8.5k      4.2k     49%
  song-architecture                anthropic/claude-sonnet-4-5     9.8k      6.1k     62%
  easter-eggs                      anthropic/claude-sonnet-4-5     8.8k      5.9k     67%
  chorus-chooser.score-choruses    anthropic/claude-sonnet-4-5     3.1k      2.1k     68%   error: no prewarm
  write-lyrics                     anthropic/claude-opus-4-5      14.2k     11.8k     83%
  review-narrative                 anthropic/claude-sonnet-4-5    10.5k      3.4k     32%   info: padding available
  ... (8 more rows)

  Total estimated cacheable: 47.3k / 78.1k input tokens (61%)

## All warnings

  error  cache.batch-prewarm-required  chorus-chooser.score-choruses
         Fix: add `- prewarm: true` or `- prewarm: false`

  warn   cache.below-min-tokens        review-stranger-summary
         Declared cache content (640 tokens) below sonnet-4-5 minimum (1024).
         Markers will silently no-op. Remove prompt_cache: or add more context.

  info   cache.padding-advisory        review-narrative
         Padding subset would unlock prefix hits worth ~$0.03/run.

## Notes

  Estimates use cached node outputs from prior runs when available; otherwise
  rough heuristics. Run the workflow once, then:
    pflow analyze-cache --from-trace ~/.pflow/debug/<trace>.json
  for ground-truth comparison against actual provider-reported cache hits.

  --format=json for machine-readable output with stable IDs.
```

## JSON output (`--format=json`)

```json
{
  "format_version": "1.0",
  "workflow_path": "/abs/path/lyrics-generator.pflow.md",
  "estimate_confidence": "low_no_trace",
  "summary": {
    "current_cost_per_run_usd": 0.45,
    "optimized_cost_per_run_usd": 0.18,
    "rerun_cost_per_run_usd": 0.10,
    "savings_pct_first_run": 60,
    "savings_pct_rerun": 78,
    "blocking_errors": 1,
    "actionable_warnings": 3,
    "total_input_tokens_estimated": 78100,
    "total_cacheable_tokens_estimated": 47300
  },
  "per_call": [
    {
      "node_id": "creative-direction",
      "model": "anthropic/claude-sonnet-4-5",
      "input_tokens_estimated": 8500,
      "cacheable_tokens_estimated": 4200,
      "cache_ratio_pct": 49,
      "declared_prompt_cache": null,
      "warnings": []
    },
    {
      "node_id": "chorus-chooser.score-choruses",
      "model": "anthropic/claude-sonnet-4-5",
      "input_tokens_estimated": 3100,
      "cacheable_tokens_estimated": 2100,
      "cache_ratio_pct": 68,
      "declared_prompt_cache": null,
      "is_batch": true,
      "batch_size_estimated": 34,
      "warnings": ["cache.batch-prewarm-required"]
    }
  ],
  "shared_context_candidates": [
    {
      "chunk_id": "song-architecture.response",
      "size_tokens_estimated": 3400,
      "referenced_by": ["write-lyrics", "review-narrative", "review-emotional", "suno-prompt"],
      "estimated_savings_per_run_usd": 0.08
    }
  ],
  "suggested_block": {
    "target_file": "song-creator/song-creator.pflow.md",
    "ttl": "5m",
    "chunks": [
      {"name": "concept", "var": "${concept}", "prose_placeholder": "<DESCRIBE THE CONCEPT...>"},
      {"name": "creative-direction.response", "var": "${creative-direction.response}", "prose_placeholder": "..."},
      {"name": "song-architecture.response", "var": "${song-architecture.response}", "prose_placeholder": "..."},
      {"name": "easter-eggs.response", "var": "${easter-eggs.response}", "prose_placeholder": "..."}
    ],
    "per_node_assignments": {
      "write-lyrics": ["concept", "creative-direction.response", "song-architecture.response", "easter-eggs.response"],
      "review-narrative": ["concept", "creative-direction.response", "song-architecture.response"],
      "suno-prompt": ["concept", "song-architecture.response"]
    }
  },
  "warnings": [
    {
      "id": "cache.batch-prewarm-required",
      "severity": "error",
      "node": "chorus-chooser.score-choruses",
      "message": "Large batch (34 items) with 2.1k-token static prefix has no explicit prewarm decision.",
      "details": {
        "batch_size": 34,
        "prefix_tokens_estimated": 2100,
        "estimated_cost_if_prewarm_true_usd": 0.02,
        "estimated_cost_if_prewarm_false_usd": 0.14,
        "wasted_savings_usd": 0.12
      },
      "fix": {
        "action": "add_node_field",
        "field": "prewarm",
        "recommended_value": true,
        "description": "Add `- prewarm: true` to opt in (-$0.12/run) or `- prewarm: false` to opt out explicitly."
      },
      "see_also": ["caching", "batch"]
    },
    {
      "id": "cache.padding-advisory",
      "severity": "info",
      "node": "review-narrative",
      "message": "Padding the subset would unlock prefix cache hits at 0.1× read rate.",
      "details": {
        "current_subset": ["song-architecture.response"],
        "suggested_subset": ["concept", "creative-direction.response", "song-architecture.response"],
        "estimated_savings_per_run_usd": 0.03
      },
      "fix": {
        "action": "extend_prompt_cache_subset",
        "current": ["song-architecture.response"],
        "suggested": ["concept", "creative-direction.response", "song-architecture.response"],
        "description": "Add earlier chunks to the prompt_cache: list to hit upstream cache writes."
      },
      "see_also": ["caching"]
    }
  ]
}
```

## Design choices baked into this mockup

- **Stable warning IDs use dotted hierarchy**: `cache.<category>-<specific>`. Greppable, namespace-clean, suppressable. Examples: `cache.shared-context-undeclared`, `cache.batch-prewarm-required`, `cache.padding-advisory`, `cache.below-min-tokens`, `cache.unused-chunk`.
- **Severity levels match pflow's existing Diagnostic**: `error` / `warn` / `info`. ERRORs block `pflow run` (validation-level); warnings and info don't.
- **Confidence indicator at the top**: never hidden. `low_no_trace` vs `high_from_trace`.
- **Cost numbers always have unit and magnitude visible**: `~$0.45/run`, `-60%`. Never bare numbers.
- **Suggested block is paste-ready** but uses `<DESCRIBE...>` prose placeholders rather than synthesized prose (we can detect the values, not write good labels for them).
- **Per-call table uses light formatting** (no box-drawing characters) — agents handle plain text well, terminal users can read it, easy to copy.
- **JSON includes `details` per warning** with the numbers — agents reasoning about cost can act on them without re-parsing the text.
- **Fix actions are typed** (`add_node_field`, `extend_prompt_cache_subset`, `paste_block`) — programmatic consumers can implement them; humans get the prose `description`.

## What I'm uncertain about / would refine in Phase F

1. **Per-call table threshold for inclusion.** A 90-LLM-call workflow shouldn't dump all 90. Default top-15 by token volume? Or always-show-with-warnings + truncate the rest?
2. **Suggested block target file when workflow has sub-workflows.** Above I assumed `song-creator.pflow.md`. The algorithm needs to pick the right file based on where the chunks logically live. Plan-time decision.
3. **`shared_context_candidates` vs `suggested_block`** — currently both exist. Probably `suggested_block` is the synthesis and `shared_context_candidates` is the raw analysis. Could collapse.
4. **`--from-trace` mode formatting.** Same shape but adds an "actual vs predicted" column / `actual_cache_ratio_pct` field. Worth showing in a separate mockup before Phase F.
5. **Padding advisory density.** If 8 nodes have padding opportunities each worth $0.001, the output drowns. Need a sensitivity floor (e.g., suppress < $0.005 per opportunity, or $0.05 cumulative).
6. **Empty-cache case.** If the analysis finds no opportunities (already optimal), what does the output look like? Probably one-liner: `Cache optimal — no actionable opportunities. Run with --from-trace to verify against runtime data.`
7. **Multi-workflow analysis** (the Tier 2 cross-workflow case). Out of v1 scope but worth knowing the JSON would extend cleanly with a `cross_workflow` section.

If you want this locked in now, I can format-test it against your saved `feedback_design_philosophy` (verbosity hides details not modes, agent-actionable output) and incorporate it into the spec or a separate `output-format.md` reference. Or we defer to Phase F. Your call.