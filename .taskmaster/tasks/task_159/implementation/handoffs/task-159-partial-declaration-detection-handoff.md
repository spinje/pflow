# Handoff: Partial-Declaration Detection + Cross-Workflow Per-Call Candidate Plumbing

> **Status**: Deferred. The prior PR (column refactor + batch-alias propagation)
> has landed. Several hard constraints originally listed here are now resolved
> by follow-up commits — see "Status update (2026-05-10)" below before relying
> on the rest of this doc.
>
> **Originally authored**: 2026-05-09. **Revised**: 2026-05-09 after a
> 4-agent code review (review-plan, review-silent-failures,
> review-feature-interactions, review-impact-completeness) refined scope and
> surfaced additional hard constraints. **Status updated**: 2026-05-10 after
> the prior PR landed and a follow-up review-driven commit shipped.
>
> **Audience**: An agent picking up this work fresh, after the prior PR.
> Read this fully before opening any source file.

---

## Status update (2026-05-10) — what's landed since this was written

The prior PR landed plus a review-driven follow-up commit. Net state:

**Landed (no longer your concern)**:

- Per-call column refactor (`cacheable=` → `cached_now` / `could_cache`).
- Batch-alias parameter propagation (`_resolve_child_input_value` takes the
  edge directly; binds `items[0]` exemplar before resolution).
- Trace-batch fallback (uses `trace.batch_items[*].item` when memo can't
  resolve `batch.items` — needed for the lyrics-generator canary's trimmed
  `zip-concepts-with-briefs.result`).
- **Static-prefix projection for batch nodes** (`_estimate_batch_prefix_cacheable_tokens`).
  This was an unplanned addition during implementation. It scans the prompt's
  literal static prefix before the first `${alias.X}` ref and multiplies by
  observed call count. Fires only when the node has its own `batch:` config.
  Surfaces `score-choruses`-class opportunities at agent-actionable scale.
- **New `cacheable_data_source = "batch_prefix"` tier label** (distinct from
  `"parameters"`). Explicit branch in `_cell_could_cache`. Confidence footer
  has a dedicated message ("projects savings from the prompt's static prefix
  repeated across observed calls").
- **Cost-projection gate** (`_per_call_rerun_cost` now skips
  `cacheable_tokens_estimated` for rows without `declared_prompt_cache`).
  This resolves constraint C2 in the design space below.
- Visibility filter (`_row_has_real_data`) extended to include
  `cacheable_data_source != "unavailable"`.
- Section-explainer text now notes that "values aggregate across all calls
  when calls > 1".

**Still deferred (yours to handle)**:

- **Defect 1 (partial-declaration detection)** — workflows where `## Cache`
  is declared and a node has `prompt_cache: [a, b]` whose prompt also
  references `${c}` shared elsewhere. Empirical sweep found 0 baselines hit
  this shape today. The motivating user scenario (Q3) still applies.
- **Defect 2 (cross-workflow plumbing for declared-cache workflows)** —
  narrowed but NOT eliminated by the prior PR. The prefix-projection covers
  batch-node opportunities (the lyrics-generator canary's score-choruses).
  But sub-workflow declared-cache cases where cross-workflow refs flow into
  ≥2 LLM nodes — and the intra-walker is gated out by `## Cache` presence —
  remain unaddressed.

**Hard constraints whose status changed**:

- **C2 (cost-projection contradiction)** — RESOLVED. The follow-up commit
  gated `_per_call_rerun_cost` on `declared_prompt_cache`. Future cross-
  workflow plumbing on undeclared rows won't shrink the rerun hypothetical
  unless the gate is removed.
- **C3 (semantic conflation: would-cache-today vs would-cache-after-edit)**
  — PARTIALLY RESOLVED for batch-prefix paths (the projection scans literal
  prompt bytes, so it represents "would cache today if you declared, no
  prompt edit needed"). STILL APPLIES to cross-workflow root-name injection:
  if you wire `concept` (root) into per-call candidates for a child whose
  prompt only has `${concept.title}` literally, the projected cacheable
  represents "would cache after extending the child's prompt to use bare
  `${concept}`" — different action shape from the rest of `could_cache`.

**Coordination point**: a separate handoff doc was added for two real
agent-UX gaps that intersect with this work:
`select-chorus-and-tier2-scope-gap-handoff.md` (read it before designing —
the cases overlap structurally).

---

## TL;DR

This handoff covers two related defects that share a common implementation
boundary and were originally split between this future PR and the prior PR.
The 4-reviewer code review showed they're best handled together, so they're
merged into ONE deferred PR's scope:

### Defect 1: partial-declaration detection (the original Q3 scenario)

The cache analyzer has a deliberate blind spot: when a workflow declares
`## Cache` AND a node has `prompt_cache: [a, b]` AND the node's prompt also
references `${c}` (shared with other LLM nodes), the analyzer **does not
detect `c`**. No warning, no recommendation, no suggestion — the agent
never learns about the missed opportunity.

### Defect 2: cross-workflow walker findings → per-call candidate plumbing

The cross-workflow walker (`cross_workflow.py`) has per-(child_workflow,
child_input_name) → consumer_node_ids data inside `_emit_sub_workflow_cache_findings`,
but that data never reaches per-call row construction. So when the
recommendation says "add `concept` to chorus-chooser's ## Cache (saves
~$0.20/run)", the per-call row for `score-choruses` doesn't reflect it (in
workflows where the intra-walker is gated out by a `## Cache` block in the
same file).

Both defects share the same implementation surface (per-call candidate
detection + cross-workflow walker output) and the same hard constraints
(Diagnostic dedup, sub-path-aware dedup, cost-projection contradiction).

Closing these gaps is a real feature addition with non-trivial design
weight (DD#29 closed-catalog territory). It is NOT a pure bug fix —
empirical sweep across 65 baselines found ZERO baselines exercise the
partial-declaration shape today. The decision to ship is a **product
decision** the user must own.

This handoff captures the full investigation, the option space, the hard
constraints (especially the cost-projection contradiction discovered during
review), and the questions you must answer before writing code.

---

## The motivating scenario

User asked, verbatim: *"what about if some cache blocks are declared for
an LLM node but the prompt still contains template variables that are
used in other prompts?"*

Concrete shape (Defect 1):
- Workflow has `## Cache` with chunks `[a, b, c, ...]`.
- Node X declares `prompt_cache: [a, b]`.
- Node X's prompt body also references `${c}`.
- Node Y also references `${c}` in its prompt body.
- `c` IS in the workflow's `## Cache` items but X didn't include it in
  its `prompt_cache:` list.

What the agent expects: "X is sending `c` uncached on every call. You
should add `c` to X's `prompt_cache:` (and Y's, if Y omitted it too)."

What the analyzer currently does: silently drops the signal.

For Defect 2, the canonical example is in lyrics-generator:
- `score-choruses` and `select-chorus` both reference `${concept.title}`
  and `${concept.core_idea}` in chorus-chooser.pflow.md.
- chorus-chooser DOES NOT have `## Cache` declared, so the intra-walker
  fires and finds those candidates. After the prior PR ships, Tier 2 will
  resolve them via batch-alias propagation, populating `could_cache` on
  the per-call row.
- BUT: in workflows where the parent declares `## Cache`, the intra-walker
  bails entirely (`analyze.py:1366` greenfield gate), and cross-workflow
  candidates that the walker correctly identified never reach the per-call
  row. song-creator.pflow.md is exactly this case: it has `## Cache`, and
  shared refs flowing into it from cross-workflow boundaries don't surface
  in its per-call rows.

---

## What the prior PR DID ship (read it first)

Before starting this work, read the prior PR's diff. The prior PR's plan
file lives at:
`.taskmaster/tasks/task_159/implementation/fix-plans/per-call-column-split-and-batch-alias-propagation-plan.md`

What it shipped:

1. **Per-call column refactor** — `cacheable=` column split into
   `cached_now` (Tier 1 active) + `could_cache` (Tier 2 projection).
   `src=` column dropped; replaced with confidence footer. Notes column
   consolidates `opaque-prompt`, `[unexecuted]`, `observed_models=`,
   `batch_items=N`. Header + divider emitted ONCE GLOBALLY. Em-dash
   semantic documented in `_per_call_scope_explainer`.

2. **Batch-alias parameter propagation** — `_resolve_child_input_value`
   takes the edge directly; when `edge.is_batch_alias_root`, resolves
   parent's batch `items:` expression, takes items[0] as exemplar, binds
   into shared store before TemplateResolver. Try/except wraps the items
   resolution. The signature change updated the single caller in
   `_build_parameters_by_workflow` in lockstep.

3. **`_row_has_real_data` predicate extended** — visibility filter now
   consults `cacheable_data_source` so greenfield Tier 2 firings aren't
   hidden.

What the prior PR explicitly DID NOT ship (and is yours to handle):

- Cross-workflow walker findings → per-call candidate injection.
- Partial-declaration detection (the deliberate blind spot at
  `analyze.py:1366-1367` for nodes whose prompt has shared refs not
  covered by their own `prompt_cache:`).

Verify what the prior PR actually merged before you start — the
implementer may have made adjustments. Re-read
`_resolve_child_input_value`, the `_format_per_call_row` cell helpers,
and the `_per_call_confidence_footer`'s gating before designing your
extensions.

---

## Why these defects exist — verified current behavior

### The greenfield gate is workflow-scoped (Defect 1)

`src/pflow/core/cache_analysis/analyze.py:1356-1375`
(`_detect_candidate_subsets`):

```python
def _detect_candidate_subsets(workflow_ir: dict[str, Any]) -> dict[str, list[str]]:
    if _cache_item_names(workflow_ir):
        return {}
    ...
```

The gate at line 1366 is keyed on `_cache_item_names(workflow_ir)`,
which checks `workflow_ir["cache"]["items"]`
(`analyze.py:2967-2978`) — **workflow-level `## Cache` block presence,
not per-node `prompt_cache:`**. The moment ANY node anywhere in the
workflow has `## Cache` declared, candidates return `{}` for **every**
node in that workflow — including:

- Nodes that didn't declare `prompt_cache:` themselves.
- Nodes that partially declared `prompt_cache:` (the user's scenario).
- Nodes where the un-declared shared ref isn't covered by any other
  node's `prompt_cache:` either.

The docstring at `analyze.py:1362-1364` confirms this is intentional:
*"declared subsets win at Tier 1/2; candidates don't apply when
prompt_cache: is set."* The author treated `## Cache` declaration as a
binary signal of completeness.

### Two walkers don't share their data (Defect 2)

The cross-workflow walker (`cross_workflow.py`) is invoked at
`analyze.py:549-554`. It produces `CrossWorkflowResult` with `edges`
(per-(parent, child) value-flow boundaries) and `irs_by_workflow` (all
visited IRs). Inside `_emit_sub_workflow_cache_findings`
(`analyze.py:3578-3629`), the analyzer calls
`_collect_llm_nodes_referencing_path(child_ir, child_input_name)` to find
which LLM nodes in the child workflow consume the cross-boundary input.
That per-(child_workflow, child_input_name) → consumer_node_ids mapping
is stored in `_SubWorkflowCacheCandidate.child_node_ids`
(`analyze.py:3157-3173`) and used to render the recommendation message
("used by 2 LLM nodes there").

But that mapping is **never propagated back to per-call row construction**.
`_build_per_call_rows_and_warnings` calls only `_detect_candidate_subsets`
(intra-workflow walker), not the cross-workflow walker's per-node info.

### No existing detector covers either case

Per Investigator 3's catalog sweep (21 IDs in
`warning_catalog.py:176-667`):

- **No catalog ID** like `cache.partial-declaration`,
  `cache.under-declared`, or `cache.missing-from-prompt-cache`.
- `src/pflow/core/cache_overlap.py` detects only the **opposite**
  direction: "you cached this AND it's still in the prompt body"
  (duplicate/shadow ERRORs).
- `cache.shared-context-undeclared` exists for the greenfield case (no
  `## Cache` at all) but is gated out the moment any chunk is declared
  via `_skip_suggested_blocks_for_declared_cache` (`analyze.py:2129-2137`).
- `cache.consolidate-to-root-recommended` only fires when declared
  sub-paths fail thresholds; doesn't surface undeclared refs.
- `cache.sub-workflow-cache-undeclared` is for cross-workflow boundaries
  emission only — its data is unavailable to per-call rows.

---

## What's been verified

**12 parallel investigations + 4-agent code review** grounded these
claims. Cite file:line if you carry forward; verify before treating as
fact (codebase moves).

### Verified facts

1. **Greenfield gate is workflow-scoped, not per-node**
   (`analyze.py:1366-1367`). Confirmed by Investigator 3.

2. **Diagnostic dedup hash is `(severity, source, node_id, id)` — context
   is excluded** (`core/diagnostic.py`, identity tuple). For
   workflow-level findings (`node_id=None`), greenfield and
   partial-declaration emissions sharing one ID would silently collapse
   to one Diagnostic and lose the other. **This is the load-bearing
   constraint on Option A.** Confirmed by Investigator 7.

3. **Blast radius for Defect 1 is zero in the current 65-baseline corpus.**
   Across all 45 workflow files declaring `## Cache`, NONE have ≥2 LLM
   nodes sharing a `${ref}` in prompt bodies where any node omits the ref
   from its `prompt_cache:`. The shape doesn't exist in the regression
   bed. Confirmed by Investigator 9. (For Defect 2, the prior PR's canary
   test will exercise the cross-workflow plumbing partially via
   chorus-chooser.)

4. **`_collect_llm_template_references`** (`analyze.py:2242-2261`) only
   scans `nodes[*].params.prompt`. It does NOT walk `system`, batch
   sub-workflow params, or other text fields. Match rule:
   `operand == ref OR operand.startswith(f"{ref}.")` — so `concept`
   matches `${concept}`, `${concept.title}`, but NOT `${concepts}`
   (suffix-safe). Confirmed by Investigator 6.

5. **`cache.shared-context-undeclared` spec**
   (`warning_catalog.py:229-247`):
   - Severity: `INFO`. Priority: 10.
   - `headline_template`: `"Shared context undeclared — declare
     {shared_chunks_short} in ## Cache"`.
   - `message_template`: `"Used by {node_count} LLM nodes. Chunks:
     {shared_chunks_csv}.{savings_clause}"`.
   - `path_template`: `"workflows[path={affected_workflow}]"`
     (workflow-level → `node_id=None` → dedup risk).
   - **The contract is "paste this block."** Reusing it for "extend an
     existing block" is a UX mismatch on top of the dedup risk.

6. **Cross-workflow walker output already carries the per-(child_workflow,
   child_input_name) → consumer_node_ids mapping** —
   `_SubWorkflowCacheCandidate.child_node_ids: tuple[str, ...]`
   at `analyze.py:3157-3173, 3199-3214`. Computed by
   `_collect_llm_nodes_referencing_path` (`analyze.py:3632-3671`).
   Currently consumed only by the recommendation emitter; can be hoisted
   to a shared helper consumed by both per-call row construction AND the
   recommendation. Confirmed by Investigator 2.

7. **Hard constraint: sub-path-aware dedup is required** for any
   per-call candidate merge. The intra-walker keys on full dotted refs
   (`concept.core_idea`); the cross-walker keys on root names (`concept`).
   String-equality dedup keeps both → `_sum_resolved_chunk_tokens` sums
   them independently → Tier 2 double-counts. The lyrics-generator canary
   would pass arithmetically only because `min(cacheable, input_tokens)`
   clamp masks the bug. Required: collapse any candidate `X.foo` when
   `X` is also in the list (or vice versa). Confirmed by review-impact-completeness
   and review-feature-interactions.

8. **Hard constraint: cost-projection contradiction**
   (`cost_estimation.py:267-281` `_per_call_rerun_cost`). This function
   reads `row.cacheable_tokens_estimated or 0` for ALL priced rows,
   ungated by `declared_prompt_cache`. If your fix populates
   `cacheable_tokens_estimated` on undeclared rows (via cross-workflow
   candidates), `rerun_within_ttl_hypothetical_usd` SHRINKS for the
   workflow. But `_aggregate_first_run_savings`
   (`cost_estimation.py:500-535`) gates on `if row.declared_prompt_cache`
   — savings projections IGNORE undeclared rows. Result: internal
   contradiction `actually_paid_usd - rerun_within_ttl_hypothetical_usd ≠
   first_run_delta.amount_usd`. Confirmed by review-impact-completeness.

9. **Recent precedent (Cluster C / N-7 commits `cd6b3a6a`,
   `dd2a3542`)**: extending `cache.sub-workflow-cache-undeclared` with
   additive context (`child_node_ids_csv`, `below_threshold_clause`)
   without bumping the catalog. The pattern: parameterize message via
   always-present optional clause + helper, keep ID stable. **But that
   precedent works because the cases were mutually exclusive by gate
   logic** — not because the catalog allowed two emission paths to
   share an ID. The dedup constraint still applies. Confirmed by
   Investigator 7.

### Things investigators couldn't verify

- **Partial-declaration impact in real-world (non-baseline) workflows.**
  The 65-baseline corpus has zero cases. The user's Q3 scenario is
  theoretically possible but not yet observed. Worth confirming you'll
  surface real value before committing time.

- **Whether the cross-workflow plumbing (Defect 2) actually moves the
  needle on real workflows beyond the chorus-chooser case.** chorus-chooser
  is handled by the prior PR via the intra-walker. The unique value of
  Defect 2's fix is for cases where the workflow's own `## Cache` gates
  the intra-walker. Identifying real cases is part of what you should
  verify.

---

## The design space

The two defects share an implementation boundary but have different
emission shapes. Decide them as a pair.

### Sub-question A: how to detect partial-declaration cases (Defect 1)

**Option A1 — Per-(node, ref) gate in `_detect_candidate_subsets`**

Replace the workflow-scoped greenfield gate at `analyze.py:1366-1367`
with per-(node, ref) filtering: emit a candidate ref for node N on ref
R unless R (or any prefix of R) is already in N's own `prompt_cache:`.

- **Pros**: smallest change to existing data flow. Surfaces immediately
  in per-call rows when paired with sub-question B's plumbing.
- **Cons**: requires careful prefix-matching to avoid false positives
  (already declared `concept` covers all sub-paths).

**Option A2 — New emission path in `_emit_sub_workflow_cache_findings` analog**

Add a new walker (`_emit_partial_declaration_findings`?) that runs after
the existing greenfield gate, specifically for the partial case.

- **Pros**: clean separation; doesn't touch the intra-walker.
- **Cons**: more code; risks divergence between the two walkers.

### Sub-question B: how to surface the detection (catalog ID choice)

**Option B1 — Extend `cache.shared-context-undeclared`**

Add `partial_declaration: bool` (or `partial_declaration_clause: str`)
to `required_context_keys`; relax the
`_skip_suggested_blocks_for_declared_cache` gate to allow partial cases
through; parameterize message + headline + suggestions.

**Hard constraint**: greenfield emission and partial-declaration
emission MUST be mutually exclusive at the gate level — same workflow
cannot fire both for the same shared ref, OR the dedup hash collapses
them to one diagnostic. Currently the gate guarantees mutex (greenfield
case is gated out the moment `## Cache` exists). The proposed change
removes that guarantee, so you must add EXPLICIT per-case gating in
the emit site.

- **Pros**: matches N-7 precedent; no DD#29 review.
- **Cons**: message/headline/suggestion contracts diverge between
  cases ("paste a block" vs "extend a block"); dedup risk; debt.

**Option B2 — New catalog ID `cache.partial-declaration-detected`**

Independent severity, headline, priority, message, suggestions.
**DD#29 review required.**

- **Pros**: clean semantics; tailored UX; no dedup risk.
- **Cons**: catalog grows; precedent is the opposite direction; new
  test surface.

**Option B3 — Per-node ID `cache.declared-ref-coverage-incomplete`**

Frame as a per-LLM-node finding (`path_template:
"nodes[id={node_id}].prompt_cache"`).

- **Pros**: actionability is per-node; reuses existing per-node
  helpers; per-node `node_id` in dedup hash means no collision risk.
- **Cons**: also DD#29 territory; risks N×M warning fan-out; loses
  cross-node "shared opportunity" framing.

### Sub-question C: how to plumb cross-workflow candidates into per-call rows (Defect 2)

This is the formerly-Step-2 work from the prior PR. The 4-reviewer code
review surfaced multiple correctness risks that justified deferring it.

**Constraint C1: sub-path-aware dedup MUST be implemented.**
`concept.core_idea` (intra-walker) and `concept` (cross-walker) cannot
both be in the same `candidate_subsets_by_node[nid]` list.
`_sum_resolved_chunk_tokens` sums independently → double-counts. Use
`_template_root_segment` (existing at `analyze.py:2264-2278`) to detect
prefix overlaps; collapse to the broader (root) ref since that's what
the cross-walker recommends declaring.

**Constraint C2: cost-projection isolation.** Either:
- (a) Gate `_per_call_rerun_cost` (`cost_estimation.py:267-281`) on
  `row.declared_prompt_cache` to mirror `_aggregate_first_run_savings`
  semantics. Simplest.
- (b) Add a separate field to `PerCallRow` (e.g.,
  `cacheable_tokens_for_display: int | None`) that's consumed only by
  the renderer; keep `cacheable_tokens_estimated` consumed by cost.
  More structural but cleaner separation.

Without one of these, JSON consumers comparing
`actually_paid_usd - rerun_within_ttl_hypothetical_usd` against
`first_run_delta.amount_usd` will see internal contradictions.

**Constraint C3: framing.** The per-call row's `could_cache` value for
a cross-workflow candidate represents "tokens that would cache after
declaration AND a prompt edit (since `${concept.core_idea}` is in the
prompt, not `${concept}`)." This is structurally different from "tokens
that would cache today if you just declare." Either:
- Surface only refs literally in the node's prompt body (don't inject
  cross-walker root candidates that aren't already prompt refs).
- Add a marker indicating "would cache after declaration + prompt edit."

The per-call row's column header `could_cache` doesn't disambiguate
these. Pick one or the other.

**Constraint C4: greenfield-gate symmetry.** Decide whether
cross-workflow candidates are filtered when the analyzed workflow has
`## Cache` (mirroring the intra-walker's greenfield gate) OR not. The
"not" case is what makes Defect 2 fire — it's the partial case for
cross-boundary refs. But it must be deliberate, not accidental.

### Recommendation (mine, not the user's)

For sub-question A: **A1 (per-(node, ref) gate)** with prefix-aware
sub-path detection. Smallest semantic shift.

For sub-question B: **B2 (new catalog ID)**. Despite DD#29 cost,
cleaner agent-facing semantics. The dedup risk in B1 is hard to engineer
around without explicit mutex gating.

For sub-question C: implement with constraint C2 option (a) (gate
`_per_call_rerun_cost` on `declared_prompt_cache`). It's the smallest
change that resolves the cost contradiction. Sub-path-aware dedup is
non-negotiable.

But this is a product call. Bring tradeoffs to the user with an explicit
ASK before committing.

---

## What you must verify before committing

These are the load-bearing assumptions. Verify each before writing code.

### 1. The prior PR's actual state

Read the prior PR's diff. Confirm:

- `_resolve_child_input_value` signature is `(edge, parent_ctx)` (not
  the old `(value, parent_ctx)`).
- `_resolve_first_batch_item` exists with try/except wrapper.
- Per-call row uses `cached_now` / `could_cache` / `notes` columns; `src=`
  column is gone.
- `_row_has_real_data` consults `cacheable_data_source`.
- `_per_call_confidence_footer` checks both `data_source` and
  `cacheable_data_source`.

If any of these don't match, your scope shifts.

### 2. Sub-path-aware dedup proof

Before committing to the cross-workflow plumbing, build a concrete test
case (preferably in the existing chorus-chooser-shape fixture) where:

- Intra-walker emits `{score-choruses: ["concept.title", "concept.core_idea"]}`
- Cross-walker emits `{score-choruses: ["concept"]}`
- After your dedup, `score-choruses` candidate list is **either** `["concept"]`
  (collapsed to root, recommendation-aligned) **or**
  `["concept.title", "concept.core_idea"]` (stays at sub-paths).

Pick one and document. Verify `_sum_resolved_chunk_tokens` doesn't
double-count.

### 3. Cost-projection contradiction proof

Before shipping, generate a workflow where:

- A node has `declared_prompt_cache=None` AND
- Your fix populates `cacheable_tokens_estimated` (via cross-workflow
  candidate) AND
- The node has trace-recorded cost.

Compute `actually_paid_usd - rerun_within_ttl_hypothetical_usd` and
verify it matches `first_run_delta.amount_usd`. If they diverge,
constraint C2 isn't resolved.

### 4. Dedup behavior (Option B1 only)

If committing to Option B1 (extend existing ID), prove the dedup
constraint with a concrete test: workflow where greenfield AND partial
cases COULD both fire on the same shared ref. Mock-emit both, assert
either (a) only one survives the dedup hash, or (b) the mutex gate at
the emission site prevents both. Without this proof, Option B1 ships
latent.

### 5. Blast radius beyond baselines

Investigator 9 confirmed zero current baselines exercise the
partial-declaration shape. But:

- Do any internal pflow examples (`examples/`) hit the shape?
- Do any agent-authored workflows captured in any internal log carry
  the shape?
- If you ship without a proof of real-world impact, the new advisory
  surfaces nothing for existing users.

### 6. New baseline is mandatory

**Add a new baseline case** with each shape:

- Defect 1: 2 LLM nodes both reading `${article}` in prompts, only node A
  declares `prompt_cache: [article]`.
- Defect 2: a workflow with `## Cache` declared + a cross-workflow input
  flowing into ≥2 LLM nodes in a child, where the input isn't in any
  declared prompt_cache.

Without these, regressions in the new gate's trigger condition would
silently pass the existing 65 baselines.

### 7. Threshold semantics

Should the new advisory fire when the un-declared ref is below the
model's min cache threshold?

- Greenfield `cache.shared-context-undeclared` uses
  `_suggested_block_non_actionable_note` to suppress when threshold
  unmet (`analyze.py:2140-2168`).
- N-7's threshold gate uses `_below_threshold_clause` (helper at
  `analyze.py:3528-3556`) which keeps the recommendation visible but
  drops `savings_usd` and adds an explanatory clause.

Pick the same shape for consistency.

### 8. Interaction with the prior PR's column shape

The prior PR's column shape (cached_now / could_cache) was designed
assuming mutual exclusivity per row in the current PR's scope, but
explicitly noted that the partial-declaration case (this PR) makes the
"both populated" case possible. Verify:

- For a partially-declared node (declared `[a, b]`, prompt has `${c}`),
  `cached_now` shows tokens from declared chunks AND `could_cache` shows
  tokens from the un-declared `c`. Both populated, same row.
- The em-dash semantic doesn't lie — neither column is `—` when both
  have data.
- The `_per_call_scope_explainer` text covers this case (might need
  another sentence).

### 9. JSON shape impact

Per the prior PR, JSON shape was unchanged. Your additions need to:

- Either preserve the `cacheable_tokens_estimated` field's existing
  semantics (use a new field for partial-declaration data).
- Or document the semantic drift and bump `JSON_FORMAT_VERSION` (currently
  `"4.1"`, see `cache_analysis/__init__.py:32`).

Pre-merge branch — additive within the same minor is OK if the field's
meaning doesn't change. If meaning changes, bump.

---

## Reference: file:line index

Read these in order when you start.

### Core files

| Path | Why |
|---|---|
| `src/pflow/core/cache_analysis/analyze.py:1356-1375` | `_detect_candidate_subsets` — gate to modify (Defect 1) |
| `src/pflow/core/cache_analysis/analyze.py:1309-1353` | `_build_per_call_rows_and_warnings` — site for cross-workflow injection (Defect 2) |
| `src/pflow/core/cache_analysis/analyze.py:2129-2137` | `_skip_suggested_blocks_for_declared_cache` |
| `src/pflow/core/cache_analysis/analyze.py:2140-2168` | `_suggested_block_non_actionable_note` |
| `src/pflow/core/cache_analysis/analyze.py:2083-2090` | existing emit site for `cache.shared-context-undeclared` |
| `src/pflow/core/cache_analysis/analyze.py:2242-2261` | `_collect_llm_template_references` (intra-walker) |
| `src/pflow/core/cache_analysis/analyze.py:2264-2278` | `_template_root_segment` (for prefix dedup) |
| `src/pflow/core/cache_analysis/analyze.py:3528-3556` | `_below_threshold_clause` (reusable) |
| `src/pflow/core/cache_analysis/analyze.py:3157-3173` | `_SubWorkflowCacheCandidate.child_node_ids` (the data to plumb) |
| `src/pflow/core/cache_analysis/analyze.py:3193-3215` | `_sub_workflow_cache_candidate` (precedent for filters) |
| `src/pflow/core/cache_analysis/analyze.py:3578-3629` | `_emit_sub_workflow_cache_findings` (where the data is computed) |
| `src/pflow/core/cache_analysis/analyze.py:3632-3671` | `_collect_llm_nodes_referencing_path` |
| `src/pflow/core/cache_analysis/cost_estimation.py:267-281` | `_per_call_rerun_cost` (cost-projection contradiction site) |
| `src/pflow/core/cache_analysis/cost_estimation.py:500-535` | `_aggregate_first_run_savings` (gates on `declared_prompt_cache`) |
| `src/pflow/core/cache_analysis/warning_catalog.py:229-247` | `cache.shared-context-undeclared` spec |
| `src/pflow/core/cache_analysis/warning_catalog.py:753-787` | `RECOMMENDED_ACTION_PRIORITY` |
| `src/pflow/core/cache_analysis/render_text.py` | per-call rendering (post-prior-PR shape) |
| `src/pflow/core/cache_analysis/token_estimation.py:174` | `_sum_resolved_chunk_tokens` precedence (`declared OR candidate`) |
| `src/pflow/core/cache_overlap.py:35-179` | what already gets detected (opposite direction) |
| `src/pflow/core/diagnostic.py` | identity tuple → dedup constraint |

### Test files

| Path | Why |
|---|---|
| `tests/test_core/test_cache_analysis_analyze.py:3648` | closest end-to-end test of candidate-path firing |
| `tests/test_core/test_cache_analysis_per_id_emission.py:290+` | `cache.sub-workflow-cache-undeclared` tests (precedent) |
| `tests/test_core/test_cache_analysis_per_id_coverage.py` | catalog round-trip — if Option B2, add row here |
| `tests/test_core/test_cache_analysis_warnings.py` | cross-cutting warning tests |

### Recent commits to study

- `cd6b3a6a` Cluster C N-7 — extending `cache.sub-workflow-cache-undeclared`
  with `child_node_ids_csv`. Pattern reference.
- `dd2a3542` threshold gate — extending the same ID with
  `below_threshold_clause`. Pattern reference.
- The prior PR's commit (when it lands) — read it to understand the
  current cross-workflow data flow.

---

## Test fixtures the implementer must add

Minimum surface (regardless of options chosen):

1. **End-to-end positive (Defect 1)**: workflow has `## Cache: [a, b, c]`,
   node X declares `prompt_cache: [a, b]` and references `${c}` in
   prompt body, node Y also references `${c}`. Assert the new finding
   fires. `analyze()` end-to-end, NOT synthetic-fixture. Pitfall #19
   defended.

2. **End-to-end positive (Defect 2)**: workflow has `## Cache` declared
   + cross-workflow input flowing into ≥2 LLM nodes in child. Assert
   per-call row's `could_cache` cell populates AND the recommendation
   fires.

3. **End-to-end negative — fully declared**: same shape as (1) but X
   declares `[a, b, c]`. Assert no finding fires.

4. **End-to-end negative — single consumer**: only X references
   `${c}`. Assert no finding (mirror existing `≥2 nodes` rule).

5. **End-to-end negative — fully greenfield (no `## Cache`)**: existing
   `cache.shared-context-undeclared` fires; new ID does NOT. Mutex
   coverage.

6. **End-to-end below-threshold**: shared ref token count below the
   model's min cache threshold. Assert behavior matches the chosen
   threshold semantics (suppressed OR visible-with-clause).

7. **Sub-path dedup proof (Defect 2)**: chorus-chooser-shape fixture
   with intra-walker `{n: ["concept.title"]}` + cross-walker
   `{n: ["concept"]}`. Assert deduped result is the policy choice
   (root or sub-paths, not both).

8. **Cost-projection consistency**: workflow with the partial case +
   trace data. Assert `actually_paid_usd -
   rerun_within_ttl_hypothetical_usd ≈ first_run_delta.amount_usd`.

9. **Mutation contract for each test**: docstring describing what
   reverting the production fix would break.

10. **NEW BASELINE cases** under
    `.taskmaster/tasks/task_159/baseline/04-warning-catalog/` —
    captures the new advisory's text + JSON envelope. This is the
    regression bed for the feature.

---

## Coordination with other future work

- **Task 160** is the cache analyzer architectural refactor. It will
  restructure section ordering and probably mass-drift baselines. Land
  this PR BEFORE Task 160 starts, OR coordinate to ride along.
- **The catalog is closed in v1 (DD#29)**. Adding a new ID needs
  user/spec design review.
- **Pitfall #19**: every regression test drives `analyze()` end-to-end
  with real state. Don't write synthetic-dict-fixture tests for
  emission paths. Search "Pitfall #19" in the progress log for the
  catalog of past instances.

---

## Decision points for the user (escalate before coding)

Before writing any code, surface these to the user:

1. **Ship at all?** Empirically zero baselines hit Defect 1's shape.
   Real-world impact is theoretical until proved. Counter: the user's Q3
   question shows fresh agents would benefit from the detection. Defect
   2 has more concrete value (the chorus-chooser case is real, but
   handled by the prior PR for `## Cache`-undeclared workflows; Defect 2
   adds value for `## Cache`-declared workflows).

2. **Sub-question A: A1 / A2?** Per-(node, ref) gate vs new emission
   path. Recommend A1.

3. **Sub-question B: B1 / B2 / B3?** Catalog choice. Recommend B2 with
   spec writeup.

4. **Sub-question C: cost-projection isolation strategy?** C2 (a) or
   (b). Recommend (a) — simpler.

5. **Threshold semantics**: suppress sub-threshold or surface with
   clause? Mirror N-7's helper for consistency.

6. **Severity**: INFO (matches `cache.shared-context-undeclared`) or
   bumped?

7. **Priority slot**: where in `RECOMMENDED_ACTION_PRIORITY` does the
   new ID go?

8. **Naming (Option B2/B3)**: `cache.partial-declaration-detected` vs
   `cache.declared-ref-coverage-incomplete` vs other.

---

## Honest confidence breakdown

| Claim | Confidence | Why |
|---|---|---|
| Defect 1 (partial-declaration blind spot) exists | 100% | Source-grounded by Investigator 3 |
| Defect 2 (walker-data-not-plumbed) exists | 100% | Source-grounded by Investigator 2; the data is locked in `_emit_sub_workflow_cache_findings` |
| Sub-path-aware dedup is required for Defect 2 | 95% | Verified via `_sum_resolved_chunk_tokens` reading + lyrics-generator structure analysis |
| Cost-projection contradiction is a real correctness gap | 95% | Verified via `cost_estimation.py:267-281` reading + `_aggregate_first_run_savings` gate comparison |
| Defect 1 blast radius in current baselines is zero | 95% | Investigator 9 swept all 45 `## Cache` workflows |
| Dedup hash excludes context | 100% | Investigator 7 cited identity tuple |
| Option A1 (per-(node, ref) gate) is feasible | 85% | Mechanically yes; semantically clean once prefix-aware |
| Option B2 (new ID) is the right call | 70% | Cleaner UX but adds catalog row; user should own |
| Combined LOC ~150-250 | 70% | Depends on options chosen; cost-projection isolation adds 20-50 |

Treat this handoff's complexity estimates as 70% confidence. Spot-check
before committing time. The investigation was thorough but the codebase
moves; verify file:line claims before relying on them.

---

## What I'd tell myself starting over

1. **Read the prior PR's diff first**, fully. The current handoff was
   written immediately after the prior PR's plan was approved — verify
   what shipped vs what was planned. The cross-workflow plumbing scope
   was REMOVED from the prior PR after the 4-reviewer code review; if
   the implementer reverses that, your scope shifts.

2. **The two defects share a boundary; treat them as ONE PR.** They
   touch the same files, share the same hard constraints, and benefit
   from the same dedup/cost-isolation work. Splitting them creates
   redundant work.

3. **The cost-projection contradiction (constraint C2) is the
   least-obvious correctness risk.** Any fix that populates
   `cacheable_tokens_estimated` on undeclared rows MUST also resolve the
   cost-projection contradiction. Don't ship the renderer fix without
   the cost gate.

4. **Run `pflow analyze-cache` on a real partially-declared workflow**
   before committing to a fix shape. Hand-author one if the corpus
   doesn't have one. The shape of the new advisory's text and JSON
   should be designed against real output, not imagined output.

5. **Don't reach for the clever single-ID extension** unless you've
   convinced yourself the dedup risk is closed by explicit gating.
   Investigator 7 flagged this as the load-bearing constraint;
   ignoring it ships latent bugs.

6. **The user prefers concrete impact over framework debates.** Show
   before/after captures of a partial-declaration workflow with the
   new advisory firing. The user's "is there really 0 opportunities?"
   moment that triggered this whole investigation came from reading
   real output.

7. **Sub-path-aware dedup uses `_template_root_segment`**, which already
   exists. Don't reinvent it. The intra-walker keys on full dotted refs
   and the cross-walker on root names — collapse them via prefix-aware
   reduction.

---

## Appendix: glossary for fresh readers

- **Greenfield workflow**: no `## Cache` block declared. Analyzer's
  candidate walker fires here today.
- **Steady-state workflow**: `## Cache` declared + ≥1 node has
  `prompt_cache:`. Analyzer relies on declared subsets; candidate
  walker is gated out.
- **Partial declaration**: `## Cache` declared, but some nodes either
  don't opt in or opt in for only a subset of the relevant refs. The
  user's Q3 scenario.
- **Tier 1 / Tier 2 / Tier 3**: the three tiers of
  `estimate_cacheable_tokens`. Tier 1 = trace ground truth (declared +
  fired). Tier 2 = projection from memo or parameters. Tier 3 =
  unmeasurable.
- **Intra-walker**: `_detect_candidate_subsets` (`analyze.py:1356-1375`).
  Per-IR; finds refs shared across ≥2 LLM nodes within one workflow.
- **Cross-workflow walker**: `walk_cross_workflow` in `cross_workflow.py`.
  Walks parent → child boundaries; emits edges with input-name renames.
- **DD#29**: design decision documenting the closed catalog policy.
  Adding new IDs requires user/spec review.
- **Pitfall #19**: synthetic-fixture tests hide bugs that real
  end-to-end fixtures catch. Bitten 8+ times in this branch.
- **Diagnostic identity tuple**: `(severity, source, node_id, id or
  message)`. Dedup key. Excludes `context`, which is why two emissions
  with the same ID + same `node_id=None` collapse to one even if
  contexts differ.
- **`_sum_resolved_chunk_tokens`**: at `token_estimation.py:190-208`.
  Iterates each chunk and SUMS via `_estimate_ref_tokens`. The site
  where sub-path-blind dedup causes double-counting.
- **`_per_call_rerun_cost`**: at `cost_estimation.py:267-281`. Reads
  `row.cacheable_tokens_estimated or 0` ungated by `declared_prompt_cache`.
  The site where populated cacheable on undeclared rows breaks
  internal cost consistency.

Done. If anything is unclear when you start, ASK rather than guess —
the user's epistemic manifesto applies: ambiguity is a STOP signal.
