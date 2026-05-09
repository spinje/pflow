# Task 159 N-7 follow-up — input-passthrough fallback for sub-workflow cache savings

> **Status**: Plan, not implemented. Self-contained for an isolated agent.
> **Estimated effort**: ~30-50 LOC + 1-2 new tests + 1-3 baseline regenerations.
> **Prerequisite**: Task 159 Cluster C / N-7 v1 has shipped (see "What's already in place" below).

---

## TL;DR

`pflow analyze-cache` now names the affected child nodes inline on
`cache.sub-workflow-cache-undeclared` recommendations and projects a `savings_usd`
dollar tag when the parent value can be honestly resolved. The dollar tag fires
for **node-output-rooted** boundary values (e.g. `${creative.direction}`) but
NOT for **workflow-input passthroughs** (e.g. `${concept}` that travels parent →
child → grandchild as an input parameter).

The lyrics-generator canonical capture is the second case — its savings tag stays
"savings unavailable" even after Cluster C / N-7 v1.

This follow-up adds **one more resolution tier**: when the parent value is an
input passthrough, look up the parent's *workflow-node trace event* and read the
resolved input mapping from `event["template_resolutions"]`. That gives us the
runtime-bound value flowing across the boundary.

After this lands, the lyrics-generator capture (and similar real-world workflows)
will gain real `saves ~$X.XX/run` tags, the `(ordered by impact)` qualifier
auto-flips on, and rank ordering reflects per-recommendation impact.

---

## Why this exists

### The motivating capture

`.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
shows:

```
## Recommended actions

  1. Sub-workflow cache undeclared — add `concept` in chorus-chooser.pflow.md's ## Cache  savings unavailable
     chorus-chooser.pflow.md
     `concept` flows into `chorus-chooser.pflow.md` as `concept` and is used by 2 LLM nodes there (`score-choruses`, `select-chorus`). ...
```

`(score-choruses, select-chorus)` is the inline-named-nodes part of N-7 v1.
`savings unavailable` is the gap this follow-up closes.

### The data flow

The lyrics-generator workflow chain is:

```
lyrics-generator.pflow.md
  └─ curate-briefs (code)            # produces ${concepts} (a list)
  └─ batch fanout to song-creator    # passes ${item.concept} per item
       └─ song-creator.pflow.md
            ├─ receives `concept` as INPUT
            └─ child-call (workflow node) → chorus-chooser.pflow.md
                 └─ inputs: {concept: ${concept}}   # passes its OWN input onward
```

The walker reports a boundary `song-creator → chorus-chooser` with
`parent_value_expr = "concept"` and `child_input_name = "concept"`. To project
savings, the analyzer needs the **token size of the value flowing across that
boundary**.

### Why N-7 v1 can't see it

`_estimate_parent_value_tokens` (`analyze.py:3349-3371`, the post-N-7-v1
location) does:

1. **Tier 1**: memo cache lookup for node `concept` in `song-creator.pflow.md`.
   No hit — `concept` isn't a node, it's a workflow input. Memo only stores
   node outputs.
2. **Tier 2**: trace lookup for an event with `node_id == "concept"` in
   `song-creator.pflow.md`. No hit — there's no such event because `concept`
   isn't a node.
3. → Returns `None` → honest unmeasurable → `"savings unavailable"`.

This is correct given the existing tiers. The fix is adding a tier that
understands the workflow-node case.

---

## What's already in place (post-N-7-v1)

These are the load-bearing facts you should NOT have to re-discover.

### Cluster C / N-7 v1 shipped

Files touched in Cluster C / N-7 v1 (commit on `feat/prompt-caching` branch
following commit `34e3c222`):

- **`src/pflow/core/cache_analysis/analyze.py`** (~100 LOC added):
  - Renamed `_count_llm_nodes_referencing_path` → `_collect_llm_nodes_referencing_path` (returns `list[str]` not `int`).
  - `_SubWorkflowCacheCandidate` gains `child_node_ids: tuple[str, ...]`.
  - New helpers: `_resolve_value_in_workflow_memo`, `_trace_node_output_for`,
    `_resolve_value_in_workflow_trace`, `_estimate_parent_value_tokens`,
    `_project_sub_workflow_cache_savings`, `_format_child_node_ids_csv`.
  - `_emit_sub_workflow_cache_findings` now takes `rows_by_node_path`, `ctx`,
    and `cw_result`.
  - `_build_cross_workflow_findings` plumbs `per_call_rows` and `ctx` from the
    single caller at `analyze.py:679`.
- **`src/pflow/core/cache_analysis/warning_catalog.py`**: catalog template body
  appends `({child_node_ids_csv})`; required key `child_node_ids_csv: str` added.
- Tests at `tests/test_core/test_cache_analysis_per_id_emission.py` lines ~290,
  ~349, ~440, ~510 (positive memo, positive trace, negative no-data, negative
  unpriced).

### Architecture facts you can rely on

- **`Diagnostic.context["savings_usd"]` flows automatically** to
  `RecommendedAction.estimated_savings_usd` via `view_helpers.py:163, 172, 193`.
  No renderer change is needed when this follow-up populates savings — the
  existing `_format_savings_usd` tri-state at `render_text.py:788-812` flips
  the tag, and the section qualifier predicate at `render_text.py:669-670`
  flips automatically when any action has `estimated_savings_usd > 0`.
- **`_estimate_token_savings_usd(model, tokens, calls)`** at `analyze.py:3023`
  is the canonical math primitive. Returns `None` when `_input_rate(model)` is
  None (unpriced model). Already mirrored by `cache.batch-prewarm-recommended`,
  `cache.dynamic-before-static`, `cache.shared-context-undeclared`. Don't
  reinvent.
- **`AnalysisContext.trace`** is a `TraceTree` instance, built once at
  `context.py:80-86` from the loaded trace JSON. Available everywhere `ctx` is
  threaded.
- **`TraceTree.walk(edges=..., workflow_path=...)`** yields `WalkEvent(event,
  owner_node_id, tier, workflow_path)`. `edges` from `_edge_child_paths(cw_result)`
  (`analyze.py:1024-1030`) attribute sub-workflow events to their proper
  workflow_path. **Last match wins** for loop-recovery semantics (mirror what
  `_trace_node_output_for` already does).
- **The trace event schema** for any node carries:
  - `event["node_id"]`, `event["node_type"]` — identity.
  - `event["node_params"]` — **ORIGINAL params, BEFORE template resolution**
    (literal `${...}` strings).
  - `event["template_resolutions"]` — **RESOLVED values from template
    expansion** (the `last_resolutions` dict from `resolve_templates`). This
    is what we'll read.
  - `event["node_output"]` — the node's output dict (post-execution).
  - `event["sub_workflow_events"]` — child events for workflow nodes.

  Source: `src/pflow/runtime/workflow_trace.py:200-260`,
  `src/pflow/runtime/engine/instrumentation.py:548-561`,
  `src/pflow/runtime/CLAUDE.md` (search "Format 2.x shape").

### What `template_resolutions` carries — the load-bearing assumption

For a workflow node `child-call` declared like:

```yaml
- id: child-call
  type: workflow
  params:
    workflow: ./chorus-chooser.pflow.md
    inputs:
      concept: ${concept}
```

the engine's `resolve_templates` resolves `${concept}` against the parent's
shared store and produces `last_resolutions["concept"] = <actual value>`. That
dict ends up at `event["template_resolutions"]`.

**LOAD-BEARING — VERIFY BEFORE IMPLEMENTING**: confirm the keying. Is
`template_resolutions` keyed by:

- The **template variable name** (e.g., `concept`)? — most likely.
- The **outer parameter path** (e.g., `inputs.concept`)?
- Something else?

The verification step is in "Pre-flight verifications" below.

If the keying is by template variable name, then for boundary edge with
`parent_value_expr = "concept"`, the lookup is
`event["template_resolutions"]["concept"]`. Done.

If keying is something else, adjust the lookup accordingly. **Do not guess
— inspect a real trace.**

---

## The fix

### High-level shape

Add a third resolution tier to `_estimate_parent_value_tokens`:

```
Tier 1: memo cache (existing)
Tier 2: trace via node_id (existing — for node-output-rooted refs)
Tier 3: trace via parent workflow-node template_resolutions (NEW — for input passthroughs)
Tier 4: None — honest unmeasurable (existing)
```

The new tier needs:
- `parent_node_id` — the workflow-node ID that invoked the child. Already on
  `_SubWorkflowCacheCandidate.parent_node_id`.
- `parent_workflow` — already on the candidate.
- `child_input_name` — already on the candidate. This is the key in the parent
  workflow node's `inputs:` dict.
- The walker output is the value we tokenize.

The lookup ref is **the child input name**, NOT the `parent_value_expr`.
Reasoning: `parent_value_expr` is the source-side ref (`concept` referencing
song-creator's input). `child_input_name` is the destination name (`concept`
inside chorus-chooser). The parent's workflow-node `inputs:` mapping is keyed
by `child_input_name` — that's how you tell the runtime which child input gets
which parent value.

For the lyrics-generator case both are `"concept"`, but the contract is
expressed against `child_input_name` (the destination — that's what the
workflow-node carries).

### Helper signature

```python
def _resolve_input_at_workflow_node_invocation(
    *,
    parent_node_id: str,
    parent_workflow: str,
    child_input_name: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> Any | None:
    """Read the resolved value of a child input from the parent's workflow-node trace event.

    For sub-workflow boundaries where the parent passes a workflow-input value
    (passthrough) rather than a node output, neither memo nor the by-node-id
    trace lookup will find the value. This helper reads it from the parent's
    workflow-node ``template_resolutions`` recorded at the runtime invocation
    site.

    Last match wins (loop-recovery semantics — mirrors ``_trace_node_output_for``).
    Returns the raw value, or None when the trace doesn't have the event or
    doesn't record the resolution.
    """
    if ctx.trace is None:
        return None
    edges = _edge_child_paths(cw_result)
    resolved_value: Any = None
    for we in ctx.trace.walk(edges=edges, workflow_path=ctx.workflow_path):
        if we.workflow_path != parent_workflow:
            continue
        if we.event.get("node_id") != parent_node_id:
            continue
        resolutions = we.event.get("template_resolutions")
        if not isinstance(resolutions, Mapping):
            continue
        # See "Pre-flight verification 1" — confirm keying.
        # Most likely: by template variable name.
        candidate_value = resolutions.get(child_input_name)
        if candidate_value is None:
            continue
        resolved_value = candidate_value
    return resolved_value
```

### Integration into `_estimate_parent_value_tokens`

Current shape (`analyze.py:3349-3371`):

```python
def _estimate_parent_value_tokens(
    ref: str,
    *,
    workflow_path: str,
    model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> int | None:
    if "??" in ref:
        return None
    value = _resolve_value_in_workflow_memo(ref, workflow_path=workflow_path, ctx=ctx)
    if value is None:
        value = _resolve_value_in_workflow_trace(
            ref, workflow_path=workflow_path, ctx=ctx, cw_result=cw_result
        )
    if value is None:
        return None
    return estimate_tokens(model, deterministic_serialize(value))[0]
```

Problem: this signature doesn't have access to `parent_node_id` or
`child_input_name`. The simplest fix is to **change the helper to take the
candidate** and have it pass through to the new tier:

```python
def _estimate_parent_value_tokens(
    candidate: _SubWorkflowCacheCandidate,
    *,
    model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> int | None:
    """Tokens for the parent value flowing across a sub-workflow boundary.

    Tier 1: memo cache (cross-workflow scoped, by node_id at the parent_value_expr root).
    Tier 2: trace by-node-id (same scope as Tier 1, for node-output-rooted refs).
    Tier 3: parent workflow-node ``template_resolutions`` (NEW — input passthroughs).
    Tier 4: ``None`` (honest unmeasurable).

    Coalesce expressions (``${a ?? b}``) are not handled — return None.
    """
    ref = candidate.parent_value_expr
    if "??" in ref:
        return None
    workflow_path = candidate.parent_workflow

    # Tier 1: memo cache
    value = _resolve_value_in_workflow_memo(ref, workflow_path=workflow_path, ctx=ctx)
    # Tier 2: trace by node_id
    if value is None:
        value = _resolve_value_in_workflow_trace(
            ref, workflow_path=workflow_path, ctx=ctx, cw_result=cw_result
        )
    # Tier 3: NEW — parent workflow-node template_resolutions
    if value is None:
        value = _resolve_input_at_workflow_node_invocation(
            parent_node_id=candidate.parent_node_id,
            parent_workflow=workflow_path,
            child_input_name=candidate.child_input_name,
            ctx=ctx,
            cw_result=cw_result,
        )
    if value is None:
        return None
    return estimate_tokens(model, deterministic_serialize(value))[0]
```

Update the single caller at `_project_sub_workflow_cache_savings` (`analyze.py:3373-3409`):

```python
# OLD:
tokens = _estimate_parent_value_tokens(
    candidate.parent_value_expr,
    workflow_path=candidate.parent_workflow,
    model=first_row.model,
    ctx=ctx,
    cw_result=cw_result,
)

# NEW:
tokens = _estimate_parent_value_tokens(
    candidate,
    model=first_row.model,
    ctx=ctx,
    cw_result=cw_result,
)
```

That's the entire production change.

---

## Pre-flight verifications (do these BEFORE writing code)

### 1. Verify `template_resolutions` keying for workflow nodes

This determines whether the helper signature works as drafted. Run:

```bash
# 1. Find or capture a real trace with a workflow node.
ls ~/.pflow/debug/*.json | head
# OR run the lyrics-generator workflow once and read its trace.
# OR inspect the existing fixture:
cat .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json \
    | python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps([e for e in d.get('nodes',[]) if e.get('node_type','').endswith('WorkflowExecutor')][:1], indent=2))"
```

Inspect the workflow-node event's `template_resolutions` dict. Confirm:

- Is `concept` a key, with the value being the actual concept content?
- OR is the key `inputs.concept`?
- OR `inputs` (with the value being a dict)?

If the keying is by template variable name, the draft helper works as written.
If keying is path-prefixed, adjust the lookup. **Reflect the actual shape, do
not guess.**

If `template_resolutions` is *missing* on workflow-node events (sanitization
filtered it, the engine doesn't capture it for this node type, etc.) — STOP.
The fallback might need a different data source. Bring this back to the user
before proceeding.

### 2. Verify the "last match wins" rule applies cleanly

For a workflow node invoked multiple times in a loop, multiple events will
match. Confirm `final_events_by_node` semantics (`workflow_trace.py:101-127`)
apply here too — last event's resolutions are the canonical "current value."

### 3. Confirm the test fixture model is priced

The new test will need a model that's **priced in LiteLLM** so
`_estimate_token_savings_usd` doesn't return None (which would mask the value
lookup). Verify:

```bash
uv run python -c "import litellm; print(litellm.model_cost.get('gemini/gemini-2.5-flash'))"
```

`gemini/gemini-2.5-flash` was confirmed priced in N-7 v1's check. Use it (or
`anthropic/claude-sonnet-4-5`).

Note: `tests/test_core/test_cache_analysis_per_id_emission.py:79-92` has an
autouse fixture `deterministic_tokens` that patches `_input_rate` to always
return None. Override locally per the existing pattern at lines 178, 416 etc.:
`monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)`.

---

## Test plan

### One new positive test

File: `tests/test_core/test_cache_analysis_per_id_emission.py`. Place near
the existing `test_sub_workflow_cache_undeclared_savings_populated_from_trace`
(around line 470).

```python
def test_sub_workflow_cache_undeclared_savings_populated_from_workflow_node_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N-7 v2: when the parent value is a workflow-input passthrough (no
    upstream node output to look up), the analyzer reads the resolved value
    from the parent's workflow-node ``template_resolutions``. This closes
    the lyrics-generator-shape canonical case (concept passed parent → child
    → grandchild as input parameter).

    Mutation contract: drop the new
    ``_resolve_input_at_workflow_node_invocation`` tier in
    ``_estimate_parent_value_tokens`` → this fails (savings drops to None
    because neither memo nor by-node-id trace lookup finds ``concept``).
    """
    # Override autouse _input_rate (see sibling test for rationale).
    analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
    monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)

    cross_module = importlib.import_module("pflow.core.cache_analysis.cross_workflow")
    parent_ir = {
        "nodes": [
            {
                "id": "child-call",
                "type": "workflow",
                "params": {
                    "workflow": "./child.pflow.md",
                    "inputs": {"concept": "${concept}"},
                },
            },
        ]
    }
    child_ir = {
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Draft ${concept}"},
            },
            {
                "id": "review",
                "type": "llm",
                "model": "gemini/gemini-2.5-flash",
                "params": {"prompt": "Review ${concept}"},
            },
        ]
    }
    monkeypatch.setattr(
        cross_module,
        "resolve_sub_workflow",
        lambda _params, _base_path: SubWorkflowResult(child_ir, None, ()),
    )

    # Synthetic trace with the parent's child-call event recording the
    # resolved input mapping. NO event for a node id "concept" — that's the
    # whole point: input passthrough means the value isn't a node output.
    import json as _json
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        trace_path = Path(tmpdir) / "trace.json"
        trace_path.write_text(
            _json.dumps({
                "format_version": "2.2.0",
                "workflow_path": "parent.pflow.md",
                "final_status": "success",
                "nodes": [
                    {
                        "node_id": "child-call",
                        "node_type": "WorkflowExecutor",
                        "duration_ms": 100,
                        "success": True,
                        "cached": False,
                        # The resolved value of ${concept} at runtime.
                        # Adjust the keying based on Pre-flight 1 verification.
                        "template_resolutions": {
                            "concept": "shared concept content " * 200,
                        },
                        "sub_workflow_events": [],
                    },
                ],
            }),
            encoding="utf-8",
        )

        result = analyze(
            parent_ir,
            workflow_path="parent.pflow.md",
            auto_load_trace=False,
            memo_cache=None,
            trace_path=trace_path,
        )
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0
```

### Mutation contract verification

For each of the three mutations below, run the relevant tests, confirm the
expected one fails, and revert the mutation:

1. **Drop the new tier in `_estimate_parent_value_tokens`** (remove the Tier 3
   `if value is None: value = _resolve_input_at_workflow_node_invocation(...)`
   block) → `test_sub_workflow_cache_undeclared_savings_populated_from_workflow_node_invocation`
   fails.
2. **Replace the new tier's `child_input_name` with `parent_value_expr`** —
   this should still pass for the test where they're identical (`concept`),
   but a future test where they diverge would fail. NOTE: only add this
   second test if a real motivating case appears. Don't fabricate divergence
   for the sake of a test.
3. **Confirm the existing four tests still pass** — Tier 3 is purely additive,
   should not regress Tier 1 or 2 behavior.

### Don't forget

- This file has an autouse `deterministic_tokens` fixture that patches
  `_input_rate=None`. Your test MUST override locally (see line 178, 416
  etc. precedent).
- Don't construct `Diagnostic` objects directly (Pitfall #19). Drive
  `analyze(...)` end-to-end. The fixture pattern in this file is the right
  shape.

---

## Baseline drift

Run `./.taskmaster/tasks/task_159/baseline/verify.sh` after the implementation
to see exactly what drifts. Expected:

### Likely drifts (memo-empty, trace-rich workflows)

These are the cases where the new tier flips the savings tag from
"unavailable" to a real number:

- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt` —
  the canonical lyrics-generator capture. Should gain `saves ~$X.XX/run` on
  recommendation #1 (currently `savings unavailable`), `(ordered by impact)`
  qualifier appears in the section header, rank ordering may shift.

- Any other baseline whose trace fixture contains a workflow-node event with
  resolved input mappings AND the corresponding boundary's `parent_value_expr`
  is currently unresolved by Tiers 1-2.

### Likely UNCHANGED

- `.taskmaster/tasks/task_159/baseline/04-warning-catalog/05-cache.sub-workflow-cache-undeclared/`
  — the synthetic per-id baseline doesn't have a real trace; Tier 3 finds
  nothing; behavior unchanged.
- Cases without trace data — Tier 3 needs trace; falls through to None.

### Regenerate command

```bash
cd .taskmaster/tasks/task_159/baseline
./regenerate.sh 10-live-recordings/05-gemini-lyrics-generator
# Inspect the diff.
git diff 10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt
# Verify final state.
./verify.sh
```

Expected: 65/65 pass, only the cases where Tier 3 fires drift.

### Show the user the diff before committing

The lyrics-generator capture's diff is the load-bearing artifact for this PR.
Run:

```bash
git diff .taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt
```

The user wants to see the actual numbers (the dollar tag specifically) before
sign-off — Cluster B's history shows that headline numbers have a way of
needing reframing.

---

## Verification gates

Run in this order. Each MUST be green before moving to the next.

```bash
# 1. Touched-file lint + types
uv run ruff check src/pflow/core/cache_analysis/analyze.py tests/test_core/test_cache_analysis_per_id_emission.py
uv run ruff format --check src/pflow/core/cache_analysis/analyze.py tests/test_core/test_cache_analysis_per_id_emission.py
uv run mypy src/pflow/core/cache_analysis/analyze.py

# 2. Sub-workflow tests
uv run pytest tests/test_core/test_cache_analysis_per_id_emission.py -k "sub_workflow" --tb=short

# 3. Full cache-analysis suite
uv run pytest tests/test_core/test_cache_analysis_*.py --tb=short

# 4. Full default suite (excludes e2e)
uv run pytest -m "not e2e" --ignore=tests/test_docs --tb=short -q

# 5. Baseline harness
./.taskmaster/tasks/task_159/baseline/verify.sh
# Regenerate drifted baselines, eyeball the diffs, re-verify.
```

Expected counts (for reference; +1 from this follow-up):
- Cache-analysis suite: ~426 tests passing.
- Default suite: ~6,426 tests passing, ~10 skipped.
- Baselines: 65/65.

---

## What NOT to do

1. **Don't add a new catalog ID.** DD#29 closed the cache.* catalog; field
   enrichment is in scope, new IDs need user/spec design review.
2. **Don't replace `_estimate_token_savings_usd`'s 0.9 shortcut with per-provider
   pricing.** It already mirrors the codebase's existing chunk-level pattern.
   If accuracy becomes a problem for non-Anthropic providers, fix the shared
   helper — not in this PR.
3. **Don't read `event["node_params"]`** (it's PRE-resolution literals).
   Read `event["template_resolutions"]` (POST-resolution values).
4. **Don't assume the `template_resolutions` keying** without verifying. See
   Pre-flight 1.
5. **Don't fabricate when memo + all trace tiers fall through.** Returning None
   is the load-bearing convention. The renderer's tri-state handles
   "unavailable" correctly (`_format_savings_usd` at `render_text.py:788-812`).
6. **Don't add new helpers to `AnalysisContext`** unless the new tier is also
   useful elsewhere. Keep `_resolve_input_at_workflow_node_invocation` private
   to `analyze.py` for now — it's a sub-workflow-cache-emit-only concern. If
   the next agent finds another caller, refactor THEN.
7. **Don't forget the autouse `deterministic_tokens` fixture override** in the
   test. Without it, your assertion that `savings_usd > 0` will fail because
   `_input_rate` returns None for everything.
8. **Don't extend the test to construct synthetic Diagnostics directly.**
   Drive `analyze(...)` end-to-end (Pitfall #19 — has bitten this branch 8+
   times).
9. **Don't bump `JSON_FORMAT_VERSION`.** Pre-merge branch, additive context
   field, no version bump per the existing branch discipline (POLISH-PLAN.md
   line 577).

---

## Open questions to ask the user

Three items where the plan made a choice but the user might prefer different.
Don't proceed silently — ask if you hit any of these.

1. **Pre-flight 1 reveals `template_resolutions` is missing for workflow-node
   events** (or keyed differently than expected). Bring back the actual shape
   you found and ask how to proceed. Possible answers: extend the engine to
   capture it (out of scope here), use a different data source, accept the
   gap as v1.x and revisit.

2. **Lyrics-generator's dollar tag comes back implausibly high or low** after
   regenerating the baseline. The `_estimate_token_savings_usd` math is
   `0.9 × tokens × calls × input_rate`. If the diff shows e.g. `$15.00/run`
   on a workflow that paid `$2.31`, something's off — bring the numbers to
   the user before committing the baseline.

3. **A baseline you didn't expect drifts.** This means a workflow you didn't
   anticipate has a workflow-node event with usable template_resolutions. If
   the diff looks correct, ship it. If it looks wrong, debug before
   regenerating.

---

## References

### Files you will touch

- `src/pflow/core/cache_analysis/analyze.py` — add new helper, change
  `_estimate_parent_value_tokens` signature, update the single caller in
  `_project_sub_workflow_cache_savings`.
- `tests/test_core/test_cache_analysis_per_id_emission.py` — one new test.
- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
  (regenerated) — and possibly a few others; harness will tell you which.

### Files to read for context (in order)

1. **This document** — full briefing.
2. `.taskmaster/tasks/task_159/baseline/POLISH-PLAN.md` — ONLY the Cluster C section
   for context on N-7's framing.
3. `src/pflow/core/cache_analysis/analyze.py:3260-3410` — current state of the
   helpers you'll be modifying. Specifically:
   - `_resolve_value_in_workflow_memo` (~3260)
   - `_trace_node_output_for` (~3290)
   - `_resolve_value_in_workflow_trace` (~3320)
   - `_estimate_parent_value_tokens` (~3349)
   - `_project_sub_workflow_cache_savings` (~3373)
   (Line numbers approximate; locate by name.)
4. `src/pflow/runtime/workflow_trace.py:200-260` — trace event schema.
5. `src/pflow/runtime/engine/instrumentation.py:548-561` —
   `template_resolutions` capture site.
6. `src/pflow/runtime/CLAUDE.md` — search "Format 2.x shape" for the
   trace-format invariants.
7. `tests/test_core/test_cache_analysis_per_id_emission.py:79-92` — autouse
   fixture; lines 290+ existing sub-workflow tests; line 178+ the local
   `_input_rate` override pattern.

### Files you should NOT need to touch

- `warning_catalog.py` — catalog spec already accepts `savings_usd: float | None`.
  No template change needed; the existing catalog already renders the body
  correctly when savings populates.
- `render_text.py` / `render_json.py` — no rendering change. The tri-state
  `_format_savings_usd` and `(ordered by impact)` qualifier already handle
  the `savings_usd > 0` case.
- `view_helpers.py` — `Diagnostic.context["savings_usd"]` already flows through
  to `RecommendedAction.estimated_savings_usd`.
- `cross_workflow.py` — walker output already has everything we need (the
  parent_node_id was already on `_SubWorkflowCacheCandidate` in N-7 v1).

---

## Confidence breakdown

| Claim | Confidence | Why |
|---|---|---|
| `template_resolutions` is the right field to read | High | Documented at `workflow_trace.py:220`, captured at `instrumentation.py:555`, schema is stable. |
| Keying is by template variable name | **Medium** | Most likely from reading `template_resolution.py`'s `last_resolutions` shape, but **NOT verified end-to-end**. Pre-flight 1 mandatory. |
| Lyrics-generator capture will gain a real dollar tag | **Medium** | Depends on the trace fixture having `template_resolutions` on the song-creator → child-call event AND the keying matching the assumption. Inspect the fixture before claiming the win. |
| `_estimate_token_savings_usd`'s 0.9 factor produces accurate Gemini numbers | High | LiteLLM's `gemini/gemini-2.5-flash` has explicit `cache_read_input_token_cost: 3e-08` and `input_cost_per_token: 3e-07` (0.1× ratio). Verified by direct lookup. |
| The new tier doesn't regress existing tiers | High | Purely additive; old tests assert specific Tier 1/Tier 2 behavior and will keep passing. |

---

## Done state

- New helper `_resolve_input_at_workflow_node_invocation` in `analyze.py`.
- `_estimate_parent_value_tokens` signature changed to take the candidate;
  Tier 3 wired in.
- Single caller in `_project_sub_workflow_cache_savings` updated.
- One new production-shape test passing with a verified mutation contract.
- All 4 existing sub-workflow savings tests still pass.
- Full default suite green (~6,426 passing).
- Baselines regenerated for whichever cases drifted; 65/65 verify.
- Lyrics-generator capture's recommendation #1 shows `saves ~$X.XX/run` (real
  number, not "savings unavailable"); `(ordered by impact)` qualifier appears
  in the section header.
- The diff for the lyrics-generator capture shown to the user before commit.

---

> **Final note for the implementing agent**: this plan is detailed because the
> trace-event-shape question is the only real risk. If Pre-flight 1 surfaces
> something unexpected, STOP and ask the user before improvising. Everything
> else is mechanical.
