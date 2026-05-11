# Finding: analyze-cache silently misses cross-node mixed-model cache fragmentation

> **Audience**: A future agent who will design + implement the fix.
> **Status**: Filed (not implemented). Documented from empirical Stage 2.1
> verification on 2026-05-05.
> **Companion docs**:
> - `./REPORT.md` (Finding #11 — co-located in same reports/ folder)
> - `../implementation-progress-log.md`

---

## TL;DR

When a workflow's nodes use **different exact models** (e.g.,
`gemini/gemini-2.5-flash` on some nodes, `anthropic/claude-haiku-4-5` on
others, or `gemini-2.5-flash-lite` vs `gemini-2.5-flash` even within the
same provider) AND those nodes share cached chunk references via
`## Cache`, **each model writes its own cache. Bytes are never shared
across the model boundary.** A workflow author paying for a 5,000-token
cached system prefix on 6 calls might assume a 6× write-amortization
benefit; if 3 calls use Model A and 3 use Model B, they actually pay
TWO 1.25× cache writes (one per model) and the amortization is over
3 calls per model — not 6.

**The analyzer doesn't warn about this.** It tracks `models_in_use`, it
detects per-batch-item heterogeneity (`model: ${item.model}`), but it
silently skips the most common case: **different exact models declared
on different nodes in the same workflow**.

The fix is a new catalog entry — same shape as existing entries like
`cache.prompt-body-duplicates-cache` or `cache.shared-context-undeclared`.

---

## The intuition (why this matters)

Picture a workflow with 4 LLM nodes, all referencing the same `${concept}`
via `## Cache`:

```
node-A (model: gemini-2.5-flash)     ─┐
node-B (model: anthropic-haiku-4-5)  ─┤  all have prompt_cache: [concept]
node-C (model: gemini-2.5-flash)     ─┤  concept = ~5000 tokens
node-D (model: anthropic-haiku-4-5)  ─┘
```

What the workflow author intuitively expects:
> "I declared `concept` in `## Cache`. It's 5000 tokens. It's used by
> 4 nodes. The cache writes once and is read 3 times. Net win."

What actually happens:
> Gemini gets its OWN cache for `concept`. Anthropic gets its OWN cache.
> Each provider charges:
> - 1 cache_creation × 1.25× rate (the first call to that provider)
> - N-1 cache_read × 0.1× rate (subsequent calls to that provider)
>
> So we pay TWO cache writes (one per provider) instead of one. The
> "savings" projection assumes 1 write + 3 reads but reality is 2 writes
> + 2 reads.

Worse case — when a model has only ONE call in the workflow, declaring
`## Cache` for that model **costs MORE** than no cache (single write at
1.25×, no read to amortize). See companion finding
`cache.first-call-write-penalty`.

---

## Why "exact model" matters, not "provider"

A common mistake when writing this warning would be to group by
provider (`anthropic/...` vs `gemini/...`). That's WRONG.

**Cache namespaces are scoped per EXACT model identifier**, not per
provider. Concrete examples that DO NOT share cache:

| Model A | Model B | Same cache? |
|---|---|---|
| `gemini/gemini-2.5-flash` | `gemini/gemini-2.5-flash-lite` | ✗ NO |
| `gemini/gemini-2.5-flash` | `gemini/gemini-3-flash-preview` | ✗ NO |
| `anthropic/claude-haiku-4-5` | `anthropic/claude-sonnet-4-5` | ✗ NO |
| `gemini/gemini-2.5-flash` | `gemini/gemini-2.5-flash` | ✓ YES |
| `gemini/gemini-2.5-flash` (date-versioned) | `gemini/gemini-2.5-flash@v2` | ✗ NO |

**The grouping must be on the literal model string after pflow's
normalization, not on the LiteLLM provider prefix.**

The `chorus-chooser/generate-chorus-options` node is the canonical
production example: it ran 8 batch items split across THREE exact models
(gemini-2.5-flash-lite × 4, gemini-3-flash-preview × 4, sometimes
anthropic-haiku via default). Each model's cache namespace is independent.

---

## What the analyzer DOES detect today

These cases work:

- **Per-batch-item heterogeneity** (`model: ${item.model}` on a single
  node, with each batch item picking a different model). Surfaced via:
  - `summary.heterogeneous_model_node_count: int`
  - `summary.heterogeneous_model_node_paths: list[str]`
  - `per_call[].model_is_heterogeneous: bool`
  - Header line: "+ generate-chorus-options (model varies per batch item)"
- **Mixed providers in the workflow** (mentioned in the header line):
  "2 LLM nodes using 2 models: anthropic/claude-haiku-4-5,
  gemini/gemini-2.5-flash"
- **Per-row threshold check** (each LLM node's cache content evaluated
  against `get_min_cache_tokens(row.model)` — model-aware threshold).

## What the analyzer DOES NOT detect

The case the user identified — and the one that bites real workflows:

- **Cross-node mixed exact-model fragmentation**. When node A and node B
  reference the same `## Cache` chunk(s) but use DIFFERENT exact models,
  the cache fragments. No warning. No estimated cost. Agent may not
  realize they're paying for redundant cache writes.

Search confirms it's missing:
```bash
grep -rn "heterogeneous\|model.fragment\|cross.model" \
  src/pflow/core/cache_analysis/warning_catalog.py
# (empty — no entry exists)
```

---

## The proposed catalog entry

### ID: `cache.heterogeneous-models-fragment-cache`

**Severity**: WARNING (info-tier alternative is acceptable; warning
draws more attention)

**Source**: `analyze` (analyzer-emitted, surfaces in
`pflow analyze-cache` and `MCP analyze_cache` tool)

**Trigger conditions** (all of):
1. `summary.models_in_use` has > 1 distinct EXACT model string
2. At least 2 nodes (different `node_path`) reference at least one
   common cached chunk via their `prompt_cache:` declarations
3. The shared cached chunks are above each model's
   `get_min_cache_tokens()` threshold (otherwise the chunks no-op
   anyway and `cache.below-min-tokens` already fires)

**Rendering** (text format, mirrors existing recommendation patterns):

```
Cache fragmented across N exact models — declared chunks written N times,
never shared.

Workflow declares ${concept}, ${concept_brief} (~6,500 tokens combined)
in ## Cache. These flow to:

  • anthropic/claude-haiku-4-5 (3 nodes): creative-direction,
    song-architecture, easter-eggs
  • gemini/gemini-2.5-flash-lite (1 node): generate-chorus-options[0-3]
  • gemini/gemini-3-flash-preview (1 node): generate-chorus-options[4-7]

Each EXACT model has a separate cache namespace. Bytes are written
~3 times instead of 1. Estimated additional cost vs single-model:
~$0.012/run on first call (3 cache_creation writes × 6500 tokens ×
~$1.25/M = $0.024 vs single $0.008). On reruns within TTL, savings
fragment proportionally — only N-1 reads per group.

→ Consolidate to one model, OR ensure each model has enough calls
  in the workflow to amortize its own cache write (≥3 calls per
  model is a reasonable rule of thumb).
```

**JSON shape** (additive to summary):
```json
{
  "summary": {
    ...
    "heterogeneous_models_fragment_cache": {
      "shared_chunks": ["concept", "concept_brief"],
      "shared_chunk_tokens": 6500,
      "groups": [
        {
          "model": "anthropic/claude-haiku-4-5",
          "node_paths": ["creative-direction", "song-architecture", "easter-eggs"],
          "cache_creation_cost_per_run_usd": 0.0081
        },
        {
          "model": "gemini/gemini-2.5-flash-lite",
          "node_paths": ["generate-chorus-options"],
          "cache_creation_cost_per_run_usd": 0.0024
        }
      ],
      "estimated_redundant_writes_cost_usd": 0.012,
      "estimated_savings_if_consolidated_usd": 0.012
    }
  }
}
```

---

## Detection algorithm (sketch)

Pseudocode at the level of `_compute_recommended_actions` in `analyze.py`:

```python
def _detect_heterogeneous_model_fragmentation(
    per_call_rows: list[PerCallRow],
    cache_block: CacheBlock | None,
) -> Optional[Diagnostic]:
    if cache_block is None:
        return None  # no ## Cache declared, no fragmentation possible

    # Group nodes by their exact model string (skip rows with model unresolved
    # or rows where model_is_heterogeneous=True — those are batch-internal
    # heterogeneity, already covered).
    by_model: dict[str, list[PerCallRow]] = defaultdict(list)
    for row in per_call_rows:
        if not row.model or row.model_is_heterogeneous:
            continue
        if not row.declared_prompt_cache:
            continue  # node doesn't reference cache
        by_model[row.model].append(row)

    if len(by_model) < 2:
        return None  # only one model, no fragmentation

    # Find chunks shared across models
    chunks_by_model = {
        model: set(chain.from_iterable(r.declared_prompt_cache for r in rows))
        for model, rows in by_model.items()
    }
    shared_chunks = set.intersection(*chunks_by_model.values())
    if not shared_chunks:
        return None  # different models reference different chunks, not fragmented

    # Calculate redundant write cost
    # (each model writes the shared chunks once, but only one write would be
    # needed if they all used the same model)
    shared_token_count = _estimate_chunk_tokens(shared_chunks, cache_block)

    redundant_writes = len(by_model) - 1
    redundant_cost = sum(
        shared_token_count * _cache_creation_rate(model)
        for model in list(by_model.keys())[1:]  # all but the "would-have-been-shared" first
    )

    return make_diagnostic(
        id="cache.heterogeneous-models-fragment-cache",
        affected_workflow=cache_block.workflow_path,
        context={
            "shared_chunks": sorted(shared_chunks),
            "shared_chunk_tokens": shared_token_count,
            "groups": [
                {
                    "model": model,
                    "node_paths": [r.node_path for r in rows],
                }
                for model, rows in sorted(by_model.items())
            ],
            "estimated_redundant_writes_cost_usd": redundant_cost,
        },
    )
```

---

## Edge cases to think through during implementation

### 1. Single-call-per-model amortization

If a model has only ONE call in the workflow declaring `prompt_cache`,
the cache write is unamortized — `cache.first-call-write-penalty`
should fire INSTEAD of (or in ADDITION to) the fragmentation warning.
Decide: do they coexist? My intuition: both fire, with the penalty
being a per-model child of the fragmentation warning.

### 2. Sub-workflow boundaries

Cross-workflow cache is workflow-scoped (cache_keys differ). If parent
declares `## Cache` and child also does, the chunks fragment across
parent/child even if both use the SAME model. This is a separate
problem (Finding #21 in the main report) but interacts:

- Same model, same chunks, different workflows → cache_key differs →
  fragmented (different problem, different diagnostic
  `cache.cross-workflow-cache-not-shared`)
- Different models, same chunks, same workflow → fragmented
  (this finding's problem)
- Different models, same chunks, different workflows → BOTH problems

Suggestion: keep the diagnostics separate; agents can read both and
understand each independently.

### 3. Heterogeneous batches that already have detection

Per-batch-item heterogeneity (`model: ${item.model}`) is already
detected. The new diagnostic should NOT double-fire on batch-internal
heterogeneity. Skip rows where `model_is_heterogeneous=True` — they're
covered by the existing surface.

But: a batch node where `model: ${item.model}` runs with 8 items split
across 2 exact models could ALSO trip this fragmentation warning. The
existing detection only flags the heterogeneity; it doesn't compute
the savings cost. Worth deciding: does the new warning cover this case
too, OR does the existing surface get extended to include cost
projection?

My suggestion: keep them separate. Existing surface = "batch is
heterogeneous, may not cache uniformly". New surface = "different
nodes/items use different exact models, cache fragments".

### 4. Cost projection for Gemini's implicit cache

Gemini's IMPLICIT cache fires on stable prefixes regardless of
`## Cache` declaration. So a workflow with 4 Gemini calls + 4
Anthropic calls might still get implicit savings on the Gemini side
even if explicit cache fragments. **The savings projection should
account for this** by either:
- Showing two numbers ("~$X.XX/run with explicit cache only;
  Gemini implicit cache may add additional savings")
- OR using Anthropic-only cost in the calculation since that's the
  one that genuinely fragments

I'd lean toward the second — model the worst case clearly.

### 5. False positives

Two models that LOOK different but actually share cache (LiteLLM
aliasing, model-version pinning) might trip a false positive. E.g., if
a user writes `gemini-2.5-flash` and another writes
`models/gemini-2.5-flash` — same Google API model, different strings.
**Mitigation**: normalize model strings via LiteLLM's
`litellm.utils.get_model_info(model)["key"]` before grouping. Two
inputs that resolve to the same canonical key share cache.

---

## Empirical evidence from Stage 2.1

**Test workflow**: `scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md`
(2 LLM nodes — `gemini-call`, `haiku-call` — sharing `${context}` via
`## Cache`).

**analyze-cache output (post-run, with trace)**:
```
2 LLM nodes using 2 models: anthropic/claude-haiku-4-5, gemini/gemini-2.5-flash

Actually paid (trace):       ~$0.0069 (trace)
Cost without caching:        ~$0.01
Cost on rerun (within TTL):  ~$0.0062
Estimated savings if applied: ~$0.0041/run (first run); ~$0.0057/run on rerun

1 opportunity (0 warnings, 1 info)

## Recommended actions
  1. Cache hit discrepancy on haiku-call — Cannot attribute discrepancy
     to known causes (predicted=100%, actual=0%); inspect trace events
     for haiku-call
```

Note what's MISSING: no warning that the 2 models prevent cache sharing.
The "Cache hit discrepancy" finding is misleading — it's not a discrepancy,
it's a structural consequence of mixed models that the analyzer doesn't
know to call out. (Discrepancy attribution should learn `first-write` as
a known cause too, but that's a separate small fix.)

**Per-call evidence**:
```json
[
  {"node": "gemini-call", "model": "gemini/gemini-2.5-flash",
   "cache_creation": 0, "cache_read": 4699, "cost": 0.00033},
  {"node": "haiku-call", "model": "anthropic/claude-haiku-4-5",
   "cache_creation": 4929, "cache_read": 0, "cost": 0.0066}
]
```

The haiku-call paid 1.25× rate for 4929 tokens of cache_creation. If
both nodes had used Anthropic Haiku, the second call would have READ
those 4929 tokens at 0.1× rate instead. Fragmentation cost: ~$0.005/run
on a 2-call workflow — a third of the total spend.

**On a real production workflow**: lyrics-generator's chorus-chooser
sub-workflow has `generate-chorus-options` running 8 batch items split
across `gemini-2.5-flash-lite` × 4 and `gemini-3-flash-preview` × 4.
Each model gets its own cache namespace. None of them currently get
cache because chorus-chooser doesn't declare `## Cache`, but if it
did, the rubric-prefix would fragment 2 ways.

---

## Suggested implementation order

1. **Add the catalog entry** in `warning_catalog.py` with placeholder
   text and JSON shape.
2. **Add detection logic** in analyze.py (sketch above).
3. **Test against the existing fixture** (`mixed-model.pflow.md`) and
   confirm the warning fires.
4. **Test against negative case** (single-model workflow + the
   `gemini-smoke` workflows) and confirm no false positive.
5. **Test against heterogeneous-batch-only case** (the
   `chorus-chooser/generate-chorus-options` shape) and confirm only
   the new warning fires (not the existing batch heterogeneity flag
   doubling up).
6. **Add MCP server tool docstring entry** (per the existing pattern in
   `execution_tools.py` — keep the catalog-id list synced).
7. **Tests**: 4-6 unit tests covering the scenarios above, mirroring
   `test_cache_analysis_warnings.py` shape.

Estimated effort: ~150 LOC + tests, 2-3 hours.

---

## Why this is high-ROI

1. **It's invisible currently**. Users with mixed-model workflows are
   silently paying the fragmentation cost. They have no way to discover
   the issue until they read the trace by hand.
2. **The fix shape is well-trodden**. It mirrors existing catalog entries
   (`cache.below-min-tokens`, `cache.unused-chunk`, etc.) — same
   detection-plus-recommendation pattern.
3. **The savings are quantifiable**. Unlike some recommendations
   (`Cross-boundary value undeclared` → "savings unavailable"), this
   one has clean per-token math.
4. **Real production code already has the issue** (lyrics-generator,
   per Stage 2.1 verification — chorus-chooser's heterogeneous
   internals).

---

## Out of scope (explicitly)

- The `cache.first-call-write-penalty` warning is its own filing
  (Finding #12 in the main report). They're related but distinct.
- The model-context-aware auto-load fix (Finding #8) is also separate
  but interacts: the discrepancy attribution path needs to learn
  "trace from different model context" before this warning's accuracy
  can be relied upon when traces are auto-loaded.
- The provider-aware text update for `cache.below-min-tokens`
  (Finding #10) is independent.
