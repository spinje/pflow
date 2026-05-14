# Cache Analysis Output Format — v3

> **DEPRECATED — historical artifact.** This document captured the design synthesis that produced the locked-in format. **All contract-level content has been folded into `task-159.md`** (Stable Warning ID Catalog, Output Format — Text, Output Format — JSON, Confidence Labeling Algorithm, Cross-Workflow Walker, Token Estimation Strategy, Per-Model Capabilities Table, Diagnostic Extension subsections; plus DD#26–35). **Future agents should read `task-159.md`, not this file.** Specifically, vocabulary in this doc may be stale: confidence labels were later refined from 3-level (`low_no_trace` / `medium_mixed` / `high_from_trace`) to 4-level per-call + 3-level aggregate (`trace` / `memo` / `estimator` / `heuristic`; `high_from_trace` / `medium_from_memo` / `low_no_data`); prewarm thresholds were later replaced with savings-ratio-based tiering. See task-159.md DD#33–35 for the locked semantics.

This document supersedes `output-draft-alt-1.md` and `output-draft-alt-2.md`. It synthesizes the best parts of both, drops what neither got right, and anchors every decision to the actual lyrics-generator workflow tree (verified by reading the source). It is the format spec the Phase F implementation builds against.

## Status

Locked-in design pending one user confirmation: that the Phase B prerequisite (single new field on `Diagnostic`) is acceptable. No other open decisions block writing the implementation plan.

---

## Design principles baked in

1. **Agent-first text output.** Markdown-formatted, scannable, sectioned. JSON (`--format=json`) is secondary — for tooling that needs structured access. Both share the same data model; text is a rendering of JSON.
2. **No silent estimates.** Every cost, token count, and savings figure carries a confidence label tied to its data source (trace / token-counter estimator / character heuristic).
3. **Tier 2 (cross-workflow) is in-by-default**, deferred only where structurally hard. JSON schema reserves the shape; text section appears when non-empty and disappears when empty.
4. **Verbosity hides details, not modes.** No `--verbose` flag that changes output structure. Per-call rows with no warnings collapse by default; full table available via `--all-rows`.
5. **No new diagnostic machinery beyond what's necessary.** One new field on `Diagnostic` (`id`); existing `suggestions: list[str]` for prose; existing `context: dict` for raw structured data. No `FixAction` substructure — that's overkill until pflow auto-applies fixes (deferred to v1b).

---

## Phase B prerequisite: extend `Diagnostic` with `id` field

**Required for v1.** Adds ~10 LOC to `core/diagnostic.py`.

```python
@dataclass
class Diagnostic:
    severity: Severity
    message: str
    id: str | None = None              # NEW — stable warning ID, e.g. "cache.shared-context-undeclared"
    title: str | None = None
    suggestions: list[str] | None = None
    node_id: str | None = None
    source: str = ""
    context: dict[str, Any] | None = None
    see_also: list[str] | None = None
```

**Identity tuple update**: `(severity, source, node_id, message)` → `(severity, source, node_id, id or message)`. When `id` is present, it's the dedup key; otherwise fall back to `message` (preserves identity for diagnostics not yet migrated).

**Rationale**: top-10% diagnostic systems (mypy, rustc, ruff, eslint, clippy, TypeScript) all have stable IDs as first-class top-level fields. Used for filtering, suppression, agent dispatch. Cache analysis is the first user; future categories get the convention for free.

**Not extended**: no `FixAction` field, no typed fix dispatch, no `applicability` enum. pflow analyze-cache doesn't auto-apply fixes (Level 3 deferred to v1b). For v1, prose suggestions plus structured `context` data is sufficient — the mypy pattern, not the rustc pattern. If `pflow cache apply` ever ships, that's when we revisit.

---

## Vocabulary

### Severity

Matches existing `Severity` enum: `error` / `warning` / `info`. Note: the value is `warning`, not `warn`.

- `error` blocks `pflow run` (e.g. `cache.batch-prewarm-required` for large unprewarmed batches).
- `warning` allows execution but flags a real issue (e.g. `cache.below-min-predicted` — markers will silently no-op).
- `info` is advisory (e.g. `cache.padding-advisory` — opportunity to save more).

### Confidence

Two-axis labeling:

**Per-call confidence** (on each row of the per-call table):

| Label | Meaning |
|---|---|
| `trace` | Token counts from the most recent trace's `llm_usage` for this node. Authoritative. |
| `estimator` | Token counts from `litellm.token_counter(model, text)` against the resolved prompt. Model-aware, offline, ±5%. |
| `heuristic` | Fallback `len(text) // 4` when no model is set or token-counter fails. ±20%. |

**Aggregate confidence** (on the SUMMARY block):

| Label | Meaning |
|---|---|
| `high_from_trace` | All per-call rows have `trace` confidence (i.e. workflow has been run). |
| `medium_mixed` | Some rows from trace, others from estimator. |
| `low_no_trace` | All rows from estimator or heuristic. Workflow has never been run. |

The dry-run nudge (`pflow run --dry-run`) inherits the same labeling; it uses whatever data is available from the planner's `MemoizationCache.get_latest_for_node()` calls.

### Stable warning ID catalog (v1)

Closed list. New IDs land in v1b or later via design review. Namespace prefix is `cache.`.

| ID | Severity | Triggers when... |
|---|---|---|
| `cache.shared-context-undeclared` | `info` | Static analysis finds N≥2 LLM calls sharing a context object that isn't in any `## Cache` block. Suggests adding it. |
| `cache.batch-prewarm-required` | `error` | Batch size > 10 AND detected static prefix > 2k tokens, with no explicit `prewarm:` decision. Blocks `pflow run`. |
| `cache.batch-prewarm-recommended` | `info` | Batch size between thresholds where prewarm is net-positive but not required. Optional latency-vs-cost tradeoff. |
| `cache.dynamic-before-static` | `warning` | A node's prompt has a `${var}` reference high up that prevents the rest of the prompt (which IS stable) from caching. Highest-leverage individual fix when it appears. |
| `cache.padding-advisory` | `info` | A node's `prompt_cache:` subset doesn't start at position 1 of the master order; padding would unlock prefix hits at 0.1× read rate, net-positive. |
| `cache.below-min-predicted` | `warning` | Declared cache content for a node is below the provider's minimum token threshold. Markers will silently no-op. |
| `cache.unused-chunk` | `warning` | A `## Cache` block declares a chunk that no node's `prompt_cache:` references. Suggests removal. |
| `cache.order-mismatch` | `error` | A node's `prompt_cache:` list doesn't match `## Cache` declaration order. Blocks `pflow run`. |
| `cache.cross-workflow-prose-mismatch` | `info` | Tier 2: parent and child both declare a chunk with the same identifier but different prose-before-the-`${var}`. Cross-workflow byte-level cache hit won't fire. |
| `cache.cross-workflow-rename-detected` | `info` | Tier 2: parent passes a value into a child's input under a different name (e.g. `concept_brief → creative_brief`). Yellow flag for divergent prose between the two cache blocks. |

---

## Text output

Three modes. Same structure; sections appear/disappear based on data.

### Mode 1: Greenfield (no `## Cache` declared)

Anchored to `lyrics-generator.pflow.md`, single source, 4 song concepts. Plausible figures; actuals depend on a real run.

```
$ pflow analyze-cache workflows/lyrics-generator/lyrics-generator.pflow.md \
    sources='["https://example.com/article"]'

# Cache Analysis: lyrics-generator.pflow.md

  4 concepts · ~252 LLM calls across 8 workflow files · 3 models in use
  Confidence: low_no_trace (estimates from litellm.token_counter; no run history)

## Summary

  Current cost per run:        ~$2.18
  Optimized cost per run:      ~$0.84   (-61%)
  Cost on rerun (within 1h):   ~$0.39   (-82%)

  4 opportunities · 1 error blocks `pflow run`

## Recommended actions (ordered by impact)

  1. [cache.dynamic-before-static]                              -$0.31/run
     chorus-chooser/build-scoring-items: ${chorus_text} appears at line 3
     of the prompt template; the ~1,640-token scoring rubric falls AFTER
     it, so 136 scoring calls per run cache nothing.
     Action: move the "## The Chorus" section to the END of the prompt,
             after the rubric and output format. Projected cache ratio: 87%.

  2. [cache.shared-context-undeclared]                          -$0.78/run
     song-creator.pflow.md: 5 stable contexts (concept, concept_brief,
     creative-direction.response, song-architecture.response,
     easter-eggs.response) flow through 15 sequential LLM calls per song
     path × 4 parallel paths.
     Action: paste the suggested ## Cache block (below) into
             song-creator.pflow.md.

  3. [cache.batch-prewarm-required]    ERROR — blocks `pflow run`
     chorus-chooser.score-choruses: 34-item batch with ~2.1k-token static
     prefix has no prewarm decision. Without prewarm, all 34 calls write
     cache simultaneously.
     Action: add `- prewarm: true` (-$0.12/run) or `- prewarm: false`
             (explicit opt-out) to the score-choruses node.

  4. [cache.padding-advisory]                                   -$0.04/run
     song-creator/review-narrative could pad its `prompt_cache:` subset
     to hit upstream cache writes from write-lyrics.
     Action: extend [song-architecture.response] to
             [concept, creative-direction.response, song-architecture.response].

## Suggested ## Cache block — song-creator/song-creator.pflow.md

  Paste between ## Inputs and ## Steps:

  ## Cache

  - ttl: 5m

  ```cache
  <DESCRIBE THE CONCEPT — appears verbatim in cached system prefix>

  ${concept}

  <DESCRIBE THE CONCEPT BRIEF (per-concept material palette)>

  ${concept_brief}

  <DESCRIBE THE CREATIVE DIRECTION DECISIONS>

  ${creative-direction.response}

  <DESCRIBE THE SONG ARCHITECTURE>

  ${song-architecture.response}

  <DESCRIBE THE EASTER EGGS CONTEXT>

  ${easter-eggs.response}

  <DESCRIBE THE WINNING CHORUS — fixed creative constraint>

  ${choose-chorus.winning_chorus}
  ```

  Per-node prompt_cache: assignments:

    write-lyrics:        [concept, concept_brief, creative-direction.response,
                          song-architecture.response, easter-eggs.response,
                          choose-chorus.winning_chorus]
    rewrite-emotional:   [concept, concept_brief, creative-direction.response,
                          song-architecture.response]
    rewrite-craft:       [creative-direction.response, song-architecture.response]
    generate-suno-prompt:[creative-direction.response]

    For sub-workflows in emotional-reviews/ and craft-reviews/, see the
    "Suggested ## Cache block" entries below for each review file.

## Cross-workflow alignment (Tier 2)

  ▸ [cache.cross-workflow-rename-detected]
    song-creator → chorus-chooser passes `concept_brief` as input named
    `creative_brief` (line 77 of song-creator.pflow.md). The same logical
    value now has two names across the workflow boundary.

    Risk: when both files declare ## Cache blocks, divergent prose labels
    (likely, given the rename) will produce different bytes for the same
    value. Cross-workflow cache hits won't fire even though the value is
    identical.

    Action: pick one prose label and use it in both files' ## Cache blocks.
    See: pflow guide caching § cross-workflow

  ▸ Verified clean: lyrics-generator → song-creator preserves names
    (concept, concept_brief). No prose-mismatch risk at this boundary.

## Per-call cache report (showing 8 of 23 LLM nodes; all-clean rows hidden)

  node                                       model                              tokens  cacheable  ratio   confidence  notes
  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  chorus-chooser.score-choruses (×34)        anthropic/claude-sonnet-4-5         1.9k       0.1k     4%   estimator    cache.dynamic-before-static
  chorus-chooser.generate-chorus-options(×8) gemini-3-flash-preview              3.5k       2.6k    74%   estimator    no marker; small batch
  song-creator.write-lyrics                  gemini/gemini-3.1-pro-preview      14.2k      11.8k    83%   estimator
  song-creator.rewrite-emotional             gemini/gemini-3.1-pro-preview      18.1k      15.4k    85%   estimator
  song-creator.rewrite-craft                 gemini/gemini-3.1-pro-preview      19.6k      16.9k    86%   estimator
  song-creator.review-narrative              anthropic/claude-sonnet-4-5        10.5k       3.4k    32%   estimator    cache.padding-advisory
  song-creator.review-stranger-summary       anthropic/claude-sonnet-4-5         3.2k       0.6k    19%   estimator    isolated by design
  curate-briefs (×4)                         anthropic/claude-sonnet-4-5         8.6k       2.5k    29%   estimator

  Hidden: 15 nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows).
  Total estimated cacheable: 47.3k / 78.1k input tokens (61%)

## All warnings

  error    cache.batch-prewarm-required        chorus-chooser.score-choruses
  warning  cache.dynamic-before-static         chorus-chooser.build-scoring-items
  info     cache.shared-context-undeclared     song-creator.pflow.md
  info     cache.padding-advisory              song-creator.review-narrative
  info     cache.cross-workflow-rename-detected song-creator → chorus-chooser

## Notes

  · Sub-workflow per-invocation scoping: song-creator runs 4× in parallel
    (one per concept). Each invocation has independent cache entries — no
    cross-path sharing. Caching applies WITHIN each path's 15+ sequential
    LLM calls.

  · Mixed-model context: write-lyrics, rewrite-emotional, rewrite-craft use
    Gemini Pro; reviews and direction use Anthropic Sonnet. Anthropic and
    Gemini cache entries are independent — declaring a chunk benefits both
    independently, not jointly.

  · Estimates use litellm.token_counter against resolved prompts. For
    actuals, run the workflow once, then:
      pflow analyze-cache --from-trace ~/.pflow/debug/<trace>.json

  · For machine-readable output: --format=json
```

### Mode 2: Steady-state (`## Cache` declared)

Same overall structure; the per-call table now shows declared subsets and per-chunk hit projections. The "Suggested ## Cache block" section is replaced by a "Declared cache plan" section.

```
# Cache Analysis: song-creator.pflow.md

  Confidence: high_from_trace (run history available, last run 23 min ago)

## Summary

  Current cost per run:    ~$0.42  (cache plan applied)
  Cost on rerun (within 1h): ~$0.18 (-57%)

  Cache plan: 6 chunks declared, 5 actively used, 1 unused
  No actionable opportunities at this time.

## Declared cache plan (## Cache block)

  ttl: 5m  (default)

  chunk                              size      used by                referenced by
  ─────────────────────────────────────────────────────────────────────────────────
  concept                            ~620 tok  write-lyrics, ...      6 nodes ✓
  concept_brief                    ~3,100 tok  write-lyrics, ...      4 nodes ✓
  creative-direction.response      ~2,400 tok  write-lyrics, ...      8 nodes ✓
  song-architecture.response       ~1,900 tok  write-lyrics, ...      6 nodes ✓
  easter-eggs.response             ~1,200 tok  write-lyrics           1 node  ✓
  choose-chorus.winning_chorus       ~480 tok  write-lyrics           1 node  ✓
  unused-deprecated-context          ~840 tok  (none)                 0 nodes ⚠ unused

## Per-call cache report (last run)

  node                  cache_creation  cache_read  hit_ratio  source
  ────────────────────────────────────────────────────────────────────
  creative-direction              892           0     N/A     trace  (first call writes)
  song-architecture                 0       2,996      85%    trace
  easter-eggs                       0       3,888      82%    trace
  write-lyrics                      0       9,720      89%    trace
  review-narrative                  0       4,300      72%    trace
  ...

## All warnings

  warning  cache.unused-chunk  unused-deprecated-context

## Notes

  · Cache plan is performing well: 5 of 6 declared chunks are active.
  · Run `pflow analyze-cache --from-trace <trace>.json` to compare predicted
    vs actual cache behavior across the most recent runs.
```

### Mode 3: Already-optimal (no actionable opportunities)

```
# Cache Analysis: workflow.pflow.md

  Confidence: high_from_trace
  Cache plan is optimal — no actionable opportunities detected.

  Run 'pflow analyze-cache --from-trace <trace>.json' to verify against
  actual provider-reported cache hits.
```

That's the entire output. No empty sections, no placeholders.

### Mode 4: `--from-trace` (Tier 3)

Compares predicted (static) cache plan to actual provider-reported cache behavior. Same structure as the matching baseline mode, but every per-call row gains a delta column showing where prediction missed.

```
$ pflow analyze-cache workflows/lyrics-generator/lyrics-generator.pflow.md \
    --from-trace ~/.pflow/debug/lyrics-generator-trace-20260427-1530.json

# Cache Analysis: lyrics-generator.pflow.md (--from-trace mode)

  Trace: lyrics-generator-trace-20260427-1530.json (format 2.1.0)
  Workflow run: 2026-04-27 15:30:42  ·  Total LLM calls: 248
  Confidence: high_from_trace

## Summary

  Predicted cost per run:  ~$0.84
  Actual cost per run:      $0.91   (+8.3% vs prediction)
  Predicted cache ratio:    61%
  Actual cache ratio:       54%     (-7pp vs prediction)

  3 prediction discrepancies flagged below.

## Discrepancies

  ▸ [cache.discrepancy] song-creator.review-narrative (path: songs[1])
    Predicted hit_ratio: 72%   Actual: 0%
    Root cause: cache_age_sec = 3,847s (>1h TTL); upstream write expired
                before this read fired.
    Action: consider `- ttl: 1h` on the song-creator ## Cache block.

  ▸ [cache.discrepancy] chorus-chooser.score-choruses (path: songs[3])
    Predicted hit_ratio: 87%   Actual: 0%
    Root cause: parallel-write race — all 34 calls fired without prewarm,
                each wrote its own cache entry.
    Action: add `- prewarm: true` on score-choruses (recommended in
            non-trace mode as cache.batch-prewarm-required).

  ▸ [cache.discrepancy] song-creator.write-lyrics (path: songs[2])
    Predicted hit_ratio: 89%   Actual: 64%
    Root cause: cache_key mismatch with prediction — likely template
                resolution drift (an upstream output value differed
                between predicted state and actual state).
    Action: investigate; may indicate non-determinism in an upstream node.

## Per-call cache report (showing rows with discrepancies)

  node                              predicted  actual  delta   reason
  ─────────────────────────────────────────────────────────────────────────
  song-creator.review-narrative          72%      0%   -72pp   ttl_expired
  chorus-chooser.score-choruses          87%      0%   -87pp   parallel_race
  song-creator.write-lyrics              89%     64%   -25pp   key_mismatch

  All other 245 LLM calls matched prediction within ±5pp.

## Notes

  · Trace format 2.0.0 traces are also accepted but with reduced
    discrepancy analysis (cache_key correlation requires 2.1.0).
  · Gemini caveat: cached_tokens populates for both implicit (free) and
    explicit (cache_control) hits and cannot be distinguished from the
    API response alone.
```

---

## `--dry-run` nudge wording

Single line emitted by `pflow run --dry-run` when actionable opportunities exist. Silent when cache plan is already optimal.

```
ℹ Cache: 4 design opportunities available (estimated -$1.34/run, -61%).
  Run 'pflow analyze-cache' for details.
```

When `--dry-run --format=json` is used, the same data emits as a Severity.INFO Diagnostic in the plan's `diagnostics` array:

```json
{
  "severity": "info",
  "id": "cache.opportunities-available",
  "message": "Cache: 4 design opportunities available (estimated -$1.34/run, -61%).",
  "suggestions": ["Run 'pflow analyze-cache' for details."],
  "context": {
    "category": "cache_advisory",
    "opportunity_count": 4,
    "estimated_savings_usd": 1.34,
    "estimated_savings_pct": 61
  },
  "see_also": ["caching"]
}
```

---

## JSON output (`--format=json`)

Full schema for the greenfield case. Tier 2 sections (`cross_workflow.*`) are present-when-non-empty; otherwise omitted.

```json
{
  "format_version": "1.0",
  "workflow_path": "/abs/path/lyrics-generator.pflow.md",
  "analyzed_at": "2026-04-27T15:42:18Z",
  "estimate_confidence": "low_no_trace",
  "trace_path": null,

  "summary": {
    "current_cost_per_run_usd": 2.18,
    "optimized_cost_per_run_usd": 0.84,
    "rerun_cost_per_run_usd": 0.39,
    "savings_pct_first_run": 61,
    "savings_pct_rerun": 82,
    "blocking_errors": 1,
    "actionable_opportunities": 4,
    "total_llm_calls_estimated": 252,
    "total_input_tokens_estimated": 78100,
    "total_cacheable_tokens_estimated": 47300,
    "models_in_use": [
      "anthropic/claude-sonnet-4-5",
      "gemini/gemini-3.1-pro-preview",
      "gemini-3-flash-preview"
    ]
  },

  "recommended_actions": [
    {
      "rank": 1,
      "warning_id": "cache.dynamic-before-static",
      "node_id": "chorus-chooser.build-scoring-items",
      "estimated_savings_usd": 0.31
    },
    {
      "rank": 2,
      "warning_id": "cache.shared-context-undeclared",
      "node_id": null,
      "target_file": "song-creator/song-creator.pflow.md",
      "estimated_savings_usd": 0.78
    },
    {
      "rank": 3,
      "warning_id": "cache.batch-prewarm-required",
      "node_id": "chorus-chooser.score-choruses",
      "estimated_savings_usd": 0.12
    },
    {
      "rank": 4,
      "warning_id": "cache.padding-advisory",
      "node_id": "song-creator.review-narrative",
      "estimated_savings_usd": 0.04
    }
  ],

  "suggested_blocks": [
    {
      "target_file": "song-creator/song-creator.pflow.md",
      "ttl": "5m",
      "chunks": [
        {"name": "concept", "var": "${concept}", "size_tokens_est": 620, "prose_placeholder": "<DESCRIBE THE CONCEPT — appears verbatim in cached system prefix>"},
        {"name": "concept_brief", "var": "${concept_brief}", "size_tokens_est": 3100, "prose_placeholder": "<DESCRIBE THE CONCEPT BRIEF (per-concept material palette)>"},
        {"name": "creative-direction.response", "var": "${creative-direction.response}", "size_tokens_est": 2400, "prose_placeholder": "<DESCRIBE THE CREATIVE DIRECTION DECISIONS>"},
        {"name": "song-architecture.response", "var": "${song-architecture.response}", "size_tokens_est": 1900, "prose_placeholder": "<DESCRIBE THE SONG ARCHITECTURE>"},
        {"name": "easter-eggs.response", "var": "${easter-eggs.response}", "size_tokens_est": 1200, "prose_placeholder": "<DESCRIBE THE EASTER EGGS CONTEXT>"},
        {"name": "choose-chorus.winning_chorus", "var": "${choose-chorus.winning_chorus}", "size_tokens_est": 480, "prose_placeholder": "<DESCRIBE THE WINNING CHORUS — fixed creative constraint>"}
      ],
      "per_node_assignments": {
        "write-lyrics": ["concept", "concept_brief", "creative-direction.response", "song-architecture.response", "easter-eggs.response", "choose-chorus.winning_chorus"],
        "rewrite-emotional": ["concept", "concept_brief", "creative-direction.response", "song-architecture.response"],
        "rewrite-craft": ["creative-direction.response", "song-architecture.response"],
        "generate-suno-prompt": ["creative-direction.response"]
      },
      "estimated_savings_usd": 0.78
    }
  ],

  "per_call": [
    {
      "node_path": "chorus-chooser.score-choruses",
      "model": "anthropic/claude-sonnet-4-5",
      "is_batch": true,
      "batch_size_estimated": 34,
      "input_tokens_estimated": 1900,
      "cacheable_tokens_estimated": 100,
      "cache_ratio_pct": 4,
      "data_source": "estimator",
      "declared_prompt_cache": null,
      "warnings": ["cache.dynamic-before-static", "cache.batch-prewarm-required"]
    },
    {
      "node_path": "song-creator.write-lyrics",
      "model": "gemini/gemini-3.1-pro-preview",
      "is_batch": false,
      "input_tokens_estimated": 14200,
      "cacheable_tokens_estimated": 11800,
      "cache_ratio_pct": 83,
      "data_source": "estimator",
      "declared_prompt_cache": null,
      "warnings": []
    }
  ],

  "cross_workflow": {
    "boundaries_analyzed": 8,
    "rename_detections": [
      {
        "warning_id": "cache.cross-workflow-rename-detected",
        "parent_workflow": "song-creator/song-creator.pflow.md",
        "child_workflow": "song-creator/chorus-chooser/chorus-chooser.pflow.md",
        "parent_value": "${concept_brief}",
        "child_input_name": "creative_brief",
        "line_in_parent": 77,
        "risk": "Divergent prose labels likely will break cross-workflow byte-level cache match."
      }
    ],
    "prose_mismatches": [],
    "value_flow_opportunities": []
  },

  "warnings": [
    {
      "id": "cache.batch-prewarm-required",
      "severity": "error",
      "node_id": "chorus-chooser.score-choruses",
      "message": "Large batch (34 items) with ~2,100-token static prefix has no explicit prewarm decision.",
      "suggestions": [
        "Add `- prewarm: true` to opt in (-$0.12/run).",
        "OR add `- prewarm: false` to opt out explicitly."
      ],
      "context": {
        "category": "cache_failure",
        "batch_size": 34,
        "prefix_tokens_estimated": 2100,
        "estimated_cost_if_prewarm_true_usd": 0.02,
        "estimated_cost_if_prewarm_false_usd": 0.14,
        "estimated_savings_usd": 0.12
      },
      "see_also": ["caching", "batch"]
    },
    {
      "id": "cache.dynamic-before-static",
      "severity": "warning",
      "node_id": "chorus-chooser.build-scoring-items",
      "message": "${chorus_text} appears at line 3 of the prompt template; the ~1,640-token scoring rubric falls AFTER it, so 136 scoring calls per run cache nothing.",
      "suggestions": [
        "Move the '## The Chorus\\n{chorus_text}' section to the END of the prompt, after the rubric and output format. Projected post-fix cache ratio: 87%."
      ],
      "context": {
        "category": "cache_advisory",
        "dynamic_var": "${chorus_text}",
        "dynamic_var_position_line": 3,
        "static_suffix_tokens_estimated": 1640,
        "calls_affected_per_run": 136,
        "projected_post_fix_ratio_pct": 87,
        "estimated_savings_usd": 0.31
      },
      "see_also": ["caching"]
    }
  ],

  "notes": [
    "Sub-workflow per-invocation scoping: song-creator runs 4× in parallel (one per concept). Each invocation has independent cache entries — no cross-path sharing.",
    "Mixed-model context: Anthropic and Gemini cache entries are independent. Declaring a chunk benefits both independently, not jointly.",
    "Estimates use litellm.token_counter against resolved prompts. Run with --from-trace for actuals."
  ]
}
```

### JSON schema notes

- **`format_version`** starts at `"1.0"`. Major bump for breaking changes; minor for additive fields.
- **`per_call[].data_source`** mirrors the per-call confidence labels from text mode.
- **`cross_workflow.*`** arrays are always present in the JSON; empty arrays mean "no findings." Text mode hides the section entirely when all arrays are empty.
- **`warnings[].context.category`** uses `cache_failure` / `cache_warning` / `cache_advisory` constants (Phase B adds these to `core/diagnostic.py::CATEGORY_TITLES`).
- **`per_call[].declared_prompt_cache`** is `null` in greenfield mode; an array of chunk names in steady-state mode.

---

## Confidence labeling rules

Per-call data source determined by:

1. If a trace is provided (`--from-trace`): all rows from the trace are `trace`. Rows for nodes not in the trace fall back to `estimator`.
2. If no trace: query `MemoizationCache.get_latest_for_node(node_id, workflow_path=...)` for each LLM node.
   - If it returns a recent entry (within 24h) AND that entry contains `llm_usage.input_tokens`: `trace` (the cache stored prior-run usage).
   - Otherwise: try `litellm.token_counter(model=node.model, text=resolved_prompt)`. Success → `estimator`.
   - Failure (unknown model, token-counter raises): fall back to `len(resolved_prompt) // 4`. Source → `heuristic`.

Aggregate confidence:
- All rows `trace` → `high_from_trace`.
- Mix of `trace` + others → `medium_mixed`.
- All rows `estimator` or `heuristic` → `low_no_trace`.

When the aggregate is `low_no_trace`, the SUMMARY section explicitly suggests running the workflow once and then `pflow analyze-cache --from-trace` for ground truth.

---

## Per-call table rules

- **Default rendering**: only rows with warnings OR rows in the bottom 50% of cache ratios are shown explicitly. All-clean rows are summarized as `Hidden: N nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows).`
- **`--all-rows` flag**: shows every node, sorted by token volume descending. Useful for full inventory.
- **Sort order (default)**: rows with `error` warnings first, then `warning`, then `info`, then by `input_tokens_estimated` descending.
- **Batch nodes** are shown as one row with `(×N)` annotation; the per-call ratio reflects a single call (not the batch aggregate).
- **Sub-workflow nodes** use full path notation: `song-creator.review-narrative` (parent.child notation), not just `review-narrative`.

---

## Padding-advisory sensitivity

To prevent advisory drown:

- Skip individual `cache.padding-advisory` warnings worth less than `$0.005`.
- Skip when total cumulative padding savings across all advisory candidates is less than `$0.05`.
- When in doubt, surface — agents prefer over-information to silence.

---

## Decisions locked

| Decision | Choice |
|---|---|
| Diagnostic extension | Add `id: str | None` field. Nothing else. |
| Stable warning IDs | Closed catalog of 10 `cache.*` IDs for v1. New IDs need design review. |
| Severity vocabulary | `error` / `warning` / `info` (matching existing Severity enum exactly). |
| Confidence per call | `trace` / `estimator` / `heuristic`. |
| Confidence aggregate | `high_from_trace` / `medium_mixed` / `low_no_trace`. |
| Token estimation | `litellm.token_counter` for greenfield; cached `llm_usage.input_tokens` for run history. Char-heuristic fallback only when token-counter fails. |
| Per-call default rendering | Hide all-clean rows; show on `--all-rows`. |
| Tier 2 in JSON | Always present, empty arrays when no findings. |
| Tier 2 in text | Section appears when non-empty; absent when empty. |
| Suggested blocks | Plural — array, one per target file. Each chunk has `<DESCRIBE...>` prose placeholders (honest about static-analysis limits). |
| Provider capabilities table | New module in Phase B (`core/llm_capabilities.py` or extend `llm_providers.py`). Hardcoded per-model min-cache-token thresholds for Anthropic Sonnet/Opus (1024), Anthropic Haiku (2048), Gemini Pro/Flash (1024 implicit / 4k explicit), OpenAI (1024). LiteLLM `model_cost` integration deferred to v1.x if its data is found sufficient. |
| Cross-workflow walker | New module (~50 LOC) using `resolve_sub_workflow` as primitive. Mirrors mermaid renderer's traversal pattern. Lives at `core/cache_analysis/cross_workflow.py`. |
| `pflow cache apply` | Out of v1. v1b decision based on observed analyze-cache adoption. |
| `FixAction` typed structure | Out of v1. Out of v1b unless `cache apply` ships. |

---

## Open questions for plan-writing (Phase F)

1. **Tier 2 prose-mismatch detection algorithm.** When parent and child both declare a chunk with the same identifier, comparing prose-before-the-`${var}` is straightforward. When the names differ (the `concept_brief → creative_brief` case), detecting the same logical value requires walking the input mapping. Algorithm shape needs to be locked during Phase F (probably: trace `${child_input}` back through `node.params.inputs[child_input] = ${parent_value}`).
2. **`cache.cross-workflow-prose-mismatch` heuristic for "which prose wins?"** v1: emit the warning, don't suggest a fix. v1b: heuristic for which prose to canonicalize on. (Per earlier discussion, ship the warning without the auto-fix suggestion in v1.)
3. **Padding-advisory algorithm.** v1 surfaces opportunities where padding is unambiguously net-positive at current sizes. Cross-call optimization (full prefix-tree) deferred to v1b.
4. **Per-batch-item Tier 2 walking.** When a parent invokes a sub-workflow inside a `batch:` block with `${item.workflow}` (heterogeneous batch), each item resolves to a different child file. v1 treats each unique resolved child as one Tier 2 edge. Plan needs to confirm `WorkflowValidator._enumerate_child_calls` is reused.
5. **Trace 2.0.0 vs 2.1.0 fallback in `--from-trace` mode.** 2.0.0 traces lack `cache_key`, `cache_age_sec`, `cache_source`, `workflow_path`. The discrepancy section degrades: TTL-expiry root-cause attribution is unavailable. v1 emits an info note when reading 2.0.0 traces; full discrepancy analysis requires 2.1.0.

---

## What's deliberately NOT in v1

- **Per-tier savings projection** (1st / 2nd / 3rd run). Current vs rerun is enough.
- **Per-provider cost breakdown**. Agents don't act on Anthropic-cost vs Gemini-cost differently from total.
- **Graph visualization**. Text only. Use `pflow visualize` separately.
- **`--diff` mode**. Compare two runs of analyze-cache. v1b if real demand emerges.
- **Auto-applied suggestions** (`pflow cache apply`). v1b.
- **Cross-workflow prose-canonicalization auto-suggestion**. v1 emits the warning; v1b suggests a canonical prose.
- **Implicit-opportunity n-gram detection** (finding 4k blocks shared across files but not declared). v1 only catches explicit-shared cases (declared in one file, missed in another).
- **Per-item TTL**. Block-level only.
- **`cache.below-min-predicted` fix suggestions**. v1 warns; remediation is "add more context or remove `prompt_cache:`."

---

## File layout for implementation (Phase F)

For grounding the plan-writing work:

```
src/pflow/
├── core/
│   ├── diagnostic.py                      # +id field (Phase B)
│   ├── llm_capabilities.py                # NEW — per-model min-cache-tokens (Phase B)
│   └── cache_analysis/                    # NEW package (Phase F)
│       ├── __init__.py
│       ├── analyze.py                     # full analysis (analyze-cache CLI consumer)
│       ├── summarize.py                   # one-line nudge for --dry-run
│       ├── cross_workflow.py              # Tier 2 walker
│       ├── token_estimation.py            # litellm.token_counter wrapper
│       ├── padding_advisor.py
│       ├── warning_catalog.py             # the closed list of warning IDs
│       └── render_text.py                 # text output renderer (markdown-formatted)
└── cli/commands/
    └── analyze_cache.py                   # NEW — CLI entry point (Phase F)
```

Tests live at `tests/test_cli/test_analyze_cache.py`, `tests/test_cli/test_analyze_cache_from_trace.py`, `tests/test_core/test_cache_analysis_*.py`.

---

## Next steps

1. User confirms Phase B prerequisite (Diagnostic `id` field) is acceptable.
2. Plan-writing for Phase B–G begins, using this format spec as the locked target.
3. Phase B introduces `id` field + `cache_*` category constants + `core/llm_capabilities.py`.
4. Phase F implements the analyze-cache machinery against this spec.
5. Spec drift check: any deviation from this format during implementation requires updating this document.
