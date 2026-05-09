# Task 159 — Tier 0 CLI parameter resolution for sub-workflow cache savings

> **Status**: Plan + verified context, not implemented. Self-contained for an isolated agent.
> **Estimated effort**: ~15-25 LOC + 1-2 tests + 0-2 baseline regenerations.
> **Prerequisites already shipped**: Cluster C / N-7 v1 (named child nodes + savings projection) AND N-7 v2 / Tier 3 (`_resolve_input_at_workflow_node_invocation` from trace) AND the threshold-clause extension (the change just before this braindump).
> **Companion document**: `scratchpads/handoffs/task-159-n7-input-passthrough-fallback-plan.md` (Tier 3 follow-up — DIFFERENT tier, DIFFERENT data source). Read that AFTER this one if you want full historical context.

---

## TL;DR

`pflow analyze-cache <workflow.pflow.md> article="my real content"` is the canonical first-contact agent flow: the agent is planning before they've run the workflow, so they pass sample inputs on the CLI. **The analyzer doesn't currently use those CLI parameters when projecting tokens at sub-workflow boundaries.** The dollar tag and threshold warning on `cache.sub-workflow-cache-undeclared` recommendations stay silent until memo or trace data exists.

This is a real agent-UX gap that pflow already has the convention for fixing — `AnalysisContext.resolve_ref_value` already prioritizes parameters over memo for input-rooted refs (it's the documented "agent's --inputs represent their CURRENT question" rule). The gap is that `_estimate_parent_value_tokens` (the cross-boundary token estimator) is the one consumer that **never consults parameters at all**. Adding a Tier 0 lookup that mirrors the established convention closes the gap.

After this lands:
- A fresh agent running `pflow analyze-cache root.pflow.md article=...` on a top-level boundary gets a real `saves ~$X.XX/run` tag (or a real `Note: below threshold` warning) on first contact, no run-then-reanalyze loop required.
- The just-shipped threshold-clause extension becomes useful in greenfield-CLI mode.

---

## Why I (the previous agent) didn't ship this in the threshold-clause PR

Honest reasoning, recorded for calibration:

1. **Initial framing as "pre-existing limitation."** I noticed the gap during the smoke test of the threshold-clause change (small CLI-parameter article didn't trigger the warning). I labeled it a pre-existing limitation because Cluster C / N-7 had the same gap before my work. That label is technically accurate but operationally an undersell — pre-existing doesn't mean small. The user pushed back on this framing ("isnt the Token resolution doesn't use CLI parameters a big issue?") and re-grading the impact made me realize this is a real first-contact UX issue, not just a corner case.

2. **Scope discipline.** The threshold-clause PR was already 9 files + 296 LOC. Adding Tier 0 would have introduced a second concern (parameter-aware token estimation) into a PR scoped to threshold checking. Splitting keeps each PR's invariant clean. This is defensible — but the user could easily prefer combining; ASK before assuming.

3. **The fix is harder than it looks at first glance.** The "just call `ctx.resolve_ref_value(ref)`" intuition is wrong — that helper is scoped to `ctx.workflow_path` (the analyzed root). For cross-boundary calls where `candidate.parent_workflow != ctx.workflow_path`, it's the wrong scope. The fix needs a guard. Not hard, but not a one-liner.

The right way to think about this: the threshold-clause PR is correct and shippable as-is; this Tier 0 work is the immediate logical follow-up that unlocks both the dollar projection (existing Cluster C scope) AND the threshold check (just-shipped scope) in greenfield-CLI mode.

---

## Why this matters — the agent UX argument

### The flow this fixes

A typical first-contact agent flow:
```
1. workflow_discover or build a new workflow
2. pflow analyze-cache root.pflow.md article="<sample content>" topic="<sample>"
3. Read recommendations, decide what to declare
4. Edit the .pflow.md to add ## Cache blocks
5. pflow run root.pflow.md article="..." topic="..."
```

Today, step 2's recommendations show `savings unavailable` for sub-workflow boundaries because:
- No memo (workflow hasn't been run yet)
- No trace (workflow hasn't been run yet)
- No parent invocation site to read from (no trace → no event)
- CLI parameters ARE present but not consulted

Result: the agent edits without dollar-impact info and without the threshold warning the just-shipped change adds. They have to either:
- Run the workflow once (cost real money or time on a workflow they're still designing), then re-run analyze-cache
- Edit blind and hope the change makes a difference

After this fix, step 2 produces actionable recommendations on first contact for top-level boundaries.

### Verbatim user framing (priority signal)

From the conversation that produced this braindump:

> "the json is not important here, the text output and agent ux and correctness is what matters, and actionable and easy to understand information"

> "Are you FULLY happy with the implementation? Any loose ends?"

> "isnt the Token resolution doesn't use CLI parameters a big issue? or whats your take on this?"

The third quote is the trigger for this work. The user surfaced the gap by reading my smoke-test results carefully — I'd missed the magnitude.

---

## What is/isn't fixed by this Tier 0 change

### Fixed — top-level boundaries

For workflows with structure like:
```
root.pflow.md    (the analyzed file)
  └─ child-call (workflow node) → child.pflow.md
       └─ inputs: {article: ${article}}
```

When the agent runs `pflow analyze-cache root.pflow.md article="..."`, the cross-boundary ref `parent_value_expr = "article"` (rooted on `root.pflow.md`'s own input declaration) gets resolved from `ctx.parameters["article"]`. Tokens estimable. Both savings projection AND threshold clause work.

### NOT fixed — nested boundaries (deeper than top level)

For workflows with structure like:
```
root.pflow.md    (the analyzed file)
  └─ batch fanout to child.pflow.md
       └─ child.pflow.md
            ├─ receives `article` as INPUT
            └─ grandchild-call → grandchild.pflow.md
                 └─ inputs: {article: ${article}}
```

The cross-boundary `child → grandchild` has `parent_workflow = "child.pflow.md"`, NOT the analyzed root. The agent's CLI parameters apply to the root, not to deeper sub-workflows. Tier 0 should NOT consult CLI parameters here (the scope is wrong). The existing Tier 3 (trace-based parent invocation lookup) is the right path for deeper nesting; Tier 0 only helps when the analyzed file IS the parent of the boundary.

This is the lyrics-generator's case: `concept` flows `lyrics-generator → song-creator → chorus-chooser`. The boundary `song-creator → chorus-chooser` is NOT a top-level boundary from the analyzed root's perspective. Tier 0 won't help; Tier 3 (which already exists) is the right path.

### Status of the lyrics-generator canonical case AFTER this fix

**Probably no change.** Tier 0 is scope-guarded to `candidate.parent_workflow == ctx.workflow_path`, which doesn't match for the song-creator → chorus-chooser boundary when analyzed from the lyrics-generator root. The lyrics-generator capture's "savings unavailable" persists until either:
- The trace fixture's workflow-node event has `node_params.inputs.concept` populated and Tier 3 fires
- The user runs analyze-cache directly on song-creator.pflow.md (where song-creator IS the analyzed root, and Tier 0 would apply at the song-creator → chorus-chooser boundary IF song-creator had `concept` as its declared input AND the agent passed it on the CLI)

Worth confirming with a fresh inspection. The braindump for Tier 3 (`task-159-n7-input-passthrough-fallback-plan.md`) was written before Tier 3 shipped; reading the implemented Tier 3 vs the lyrics-generator trace fixture would clarify why the canonical case still says "savings unavailable" today.

---

## What's already in place (verified, do NOT re-discover)

### `AnalysisContext` already has parameter-aware resolution

File: `src/pflow/core/cache_analysis/context.py:140-228`

```python
def parameters_for_workflow(self, workflow_path: str | None) -> Mapping[str, Any]:
    """Return parameters scoped to one workflow in a cross-workflow analysis."""
    if workflow_path == self.workflow_path:
        return self.parameters
    return self.parameters_by_workflow.get(workflow_path, {})

def resolve_ref_value(self, ref: str) -> Any | None:
    """... For refs whose root is in workflow_ir["inputs"]: parameters WIN
    over memo. ..."""

def _resolve_from_parameters(self, ref: str, root: str) -> Any | None:
    """Resolve ``ref`` against ``self.parameters`` for a workflow-input root."""
    ...
    resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: self.parameters[root]})
    ...
    return _normalize_empty(resolved)
```

The `_resolve_from_parameters` private method at `context.py:184-203` IS the exact resolution shape we need. Reuses `TemplateResolver.resolve_template` for dotted-path application; normalizes empties.

**Reusing this is the cleanest implementation.** Either:
- Call `ctx._resolve_from_parameters(ref, root)` directly (private but in-package access is fine), OR
- Use `ctx.parameters_for_workflow(workflow_path)` to get the dict, then apply the same TemplateResolver pattern inline.

I lean toward the inline pattern because (a) it makes the helper self-contained, (b) it avoids cross-module reach into a private method.

### `_estimate_parent_value_tokens` current shape

File: `src/pflow/core/cache_analysis/analyze.py:3389-3428` (post-threshold-clause PR)

```python
def _estimate_parent_value_tokens(
    candidate: _SubWorkflowCacheCandidate,
    *,
    model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> int | None:
    """Tokens for the parent value flowing across a sub-workflow boundary.

    Tier 1: memo cache (cross-workflow scoped, by parent_value_expr root).
    Tier 2: trace by node_id — for node-output-rooted refs.
    Tier 3: parent workflow-node node_params['inputs'][child_input_name] —
    closes the input-passthrough case via trace.
    Tier 4: None (honest unmeasurable — never fabricate).
    """
    ref = candidate.parent_value_expr
    if "??" in ref:
        return None
    workflow_path = candidate.parent_workflow
    value = _resolve_value_in_workflow_memo(ref, workflow_path=workflow_path, ctx=ctx)
    if value is None:
        value = _resolve_value_in_workflow_trace(ref, workflow_path=workflow_path, ctx=ctx, cw_result=cw_result)
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

This is what you're extending.

### `_template_root_segment` helper exists

File: `src/pflow/core/cache_analysis/analyze.py:2263-2277`

```python
def _template_root_segment(ref: str) -> str:
    """Return the first segment of a template path.
    Examples:
        concept.core_idea → concept
        concept           → concept
        items[0].name     → items
    """
    return ref.split(".", 1)[0].split("[", 1)[0]
```

Use this to extract the root segment for the workflow-input lookup.

### TemplateResolver pattern for dotted-path application

Used at `context.py:195` and `analyze.py:3268, 3330`:

```python
from pflow.runtime.template_resolver import TemplateResolver
resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: value})
```

This wraps a single-key dict so the resolver can navigate `${ref}` (which may have a dotted path) against the value. Returns the resolved value (any type) or the original `${...}` string if unresolvable.

### `_normalize_empty` helper

File: `src/pflow/core/cache_analysis/context.py:231` (and re-exported)

Returns `None` for empty string / dict / list. The "unmeasurable" convention — distinct from "we have a real zero."

---

## The fix

### Tier 0 placement

Before Tier 1 (memo) — parameters represent the agent's CURRENT question, mirroring the existing `resolve_ref_value` convention. The `workflow_path == ctx.workflow_path` guard scopes the tier correctly.

### Helper signature

```python
def _resolve_value_from_workflow_parameters(
    ref: str,
    *,
    workflow_path: str,
    ctx: AnalysisContext,
) -> Any | None:
    """Resolve a parent_value_expr against ctx.parameters when the analyzed
    workflow IS the boundary's parent.

    Mirrors AnalysisContext.resolve_ref_value's "parameters WIN for input
    refs" convention, applied predictively at the cross-boundary site so
    `pflow analyze-cache <root.pflow.md> input=<value>` produces real token
    estimates on first contact (no run-then-reanalyze loop).

    Scope: only fires when ``workflow_path == ctx.workflow_path``. For
    deeper nested boundaries, CLI parameters apply to the root, not to
    intermediate sub-workflows; falling through to existing tiers is correct.

    Returns the raw resolved value, or None when:
    - The boundary's parent workflow isn't the analyzed root.
    - The ref's root isn't a declared workflow input.
    - The parameter isn't set.
    - The dotted-path tail doesn't navigate (e.g. ``${input.field}`` against
      a string-typed input — falls through; memo/trace tiers may have it).
    - The resolved value is empty (per ``_normalize_empty``).
    """
    if workflow_path != ctx.workflow_path:
        return None

    workflow_ir = ctx.workflow_ir
    if not isinstance(workflow_ir, Mapping):
        return None
    declared_inputs = workflow_ir.get("inputs")
    if not isinstance(declared_inputs, Mapping):
        return None

    root = _template_root_segment(ref)
    if root not in declared_inputs:
        return None

    params = ctx.parameters_for_workflow(workflow_path)
    if root not in params:
        return None

    from pflow.runtime.template_resolver import TemplateResolver

    try:
        resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: params[root]})
    except Exception:
        return None
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None  # ref didn't resolve; fall through to memo/trace tiers
    return _normalize_empty(resolved)
```

### Integration into `_estimate_parent_value_tokens`

Add Tier 0 BEFORE Tier 1 (memo). Update the docstring to reflect the new tier order:

```python
def _estimate_parent_value_tokens(
    candidate: _SubWorkflowCacheCandidate,
    *,
    model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> int | None:
    """Tokens for the parent value flowing across a sub-workflow boundary.

    Tier 0: ctx.parameters when the analyzed workflow IS the boundary's
    parent — the agent's CLI --inputs represent their CURRENT question.
    Mirrors AnalysisContext.resolve_ref_value's "parameters WIN for input
    refs" convention. NEW.
    Tier 1: memo cache (cross-workflow scoped, by parent_value_expr root).
    Tier 2: trace by node_id — for node-output-rooted refs.
    Tier 3: parent workflow-node node_params['inputs'][child_input_name] —
    closes the input-passthrough case via trace.
    Tier 4: None (honest unmeasurable — never fabricate).

    Coalesce expressions (${a ?? b}) are not handled — too ambiguous which
    operand sourced the value at runtime; returning None keeps the rest of
    the projection honest.
    """
    ref = candidate.parent_value_expr
    if "??" in ref:
        return None
    workflow_path = candidate.parent_workflow

    # Tier 0: CLI parameters (analyzed workflow IS the boundary parent)
    value = _resolve_value_from_workflow_parameters(
        ref, workflow_path=workflow_path, ctx=ctx
    )
    # Tier 1: memo
    if value is None:
        value = _resolve_value_in_workflow_memo(ref, workflow_path=workflow_path, ctx=ctx)
    # Tier 2: trace by node_id
    if value is None:
        value = _resolve_value_in_workflow_trace(ref, workflow_path=workflow_path, ctx=ctx, cw_result=cw_result)
    # Tier 3: parent workflow-node invocation site
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

### Why Tier 0 BEFORE memo (not after)

The `AnalysisContext.resolve_ref_value` precedent at `context.py:155-157`:
> The agent's --inputs represent their CURRENT question; memo from a prior run with different inputs MUST NOT override.

So if there's both a memo entry AND a CLI parameter, the parameter wins. Tier 0 first, memo second.

This matters for the agent flow: agent runs workflow with input `article=A` (populates memo), then re-runs analyze-cache with `article=B`. The recommendations should reflect `B` (current question), not `A` (stale memo).

### What this is NOT

- NOT a replacement for `ctx.resolve_ref_value`. That's scoped to the analyzed root only; this helper is for cross-workflow contexts.
- NOT a generalization to all `_estimate_*_tokens` paths. Other token estimators (`_estimate_chunk_tokens`, `_estimate_ref_tokens`) operate within the analyzed workflow already and use `ctx.resolve_ref_value` correctly. Don't reach into them.
- NOT a fix for nested boundaries. If `candidate.parent_workflow != ctx.workflow_path`, the helper falls through. Tier 3 (already shipped) is the trace-based path for deeper nesting.

---

## Pre-flight verifications (do these BEFORE writing code)

### 1. Reproduce the gap end-to-end

```bash
# Build the smoke fixture (already done in the threshold-clause PR's verification —
# /tmp/smoke-cache/parent.pflow.md and child.pflow.md should still exist)
ls /tmp/smoke-cache/  # parent.pflow.md, child.pflow.md
# If gone, recreate per the smoke-test in the threshold-clause PR's verification logs.

# Confirm the gap on current code
uv run pflow analyze-cache /tmp/smoke-cache/parent.pflow.md \
    --no-trace-autoload article="hello world this is a tiny article" 2>&1 | grep -A3 "Sub-workflow"
```

Expected pre-fix output:
```
1. Sub-workflow cache undeclared — add `article` in child.pflow.md's ## Cache  savings unavailable
   child.pflow.md
   `article` flows into `child.pflow.md` ...
   (NO threshold warning, NO dollar tag)
```

This is the canonical demonstration of the gap. After Tier 0 lands, the same command should produce either a real `saves ~$X.XX/run` (if tokens clear threshold) or a `Note: ~N tokens estimated, below ...` warning (if below).

### 2. Verify `_normalize_empty` import path

`_normalize_empty` is defined at `context.py:231` but used elsewhere too. Check that `analyze.py` already imports it — if not, you'll need to add an import. Grep:

```bash
grep -n "_normalize_empty" src/pflow/core/cache_analysis/analyze.py
```

If not imported, add: `from pflow.core.cache_analysis.context import _normalize_empty` (or wherever it's appropriately exposed). It's a private helper but reused across the analyze module.

### 3. Verify TemplateResolver import path in analyze.py

`analyze.py` already imports TemplateResolver (used at line 3268, 3330). Confirm the import is at module level. Grep:

```bash
grep -n "from pflow.runtime.template_resolver import\|import.*TemplateResolver" src/pflow/core/cache_analysis/analyze.py
```

If only lazy-imported inside specific functions, follow the existing pattern (lazy-import inside `_resolve_value_from_workflow_parameters` to avoid layer issues).

### 4. Confirm test fixture setup

The new test will need to override the autouse `deterministic_tokens` fixture's `_input_rate=None` patch (per existing pattern at lines 178, 416, etc.):

```python
analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
```

The autouse fixture also patches `get_min_cache_tokens=10` and `estimate_tokens=_word_count` (split-on-whitespace). This means CLI parameter content tokenizes via word count; ensure your fixture content gives tokens above 10 (default threshold) so savings populates and the dollar tag is the test signal — OR override threshold to a higher value if testing the below-threshold path.

---

## Test plan

### One new positive test (mandatory)

File: `tests/test_core/test_cache_analysis_per_id_emission.py`. Place after the existing `test_sub_workflow_cache_undeclared_savings_populated_from_workflow_node_invocation` (around line 624 today; will shift if other tests have been added since).

```python
def test_sub_workflow_cache_undeclared_savings_populated_from_workflow_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N-7 v3 (Tier 0): when the analyzed workflow is the boundary's parent
    and CLI --inputs supplies the value, the analyzer estimates tokens from
    the parameter directly. No memo, no trace, no parent invocation site
    needed. This closes the canonical first-contact agent flow:
    `pflow analyze-cache root.pflow.md input=<sample>` produces real savings
    on first call.

    Mutation contract: drop the new
    ``_resolve_value_from_workflow_parameters`` tier in
    ``_estimate_parent_value_tokens`` → this fails (savings drops to None;
    no other tier has the value).
    """
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
        ],
        # ``concept`` declared as a workflow input so the boundary ref roots
        # on the input declaration, not on a same-named node.
        "inputs": {"concept": {"type": "string"}},
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

    # NO memo, NO trace — only CLI parameters.
    result = analyze(
        parent_ir,
        workflow_path="parent.pflow.md",
        parameters={"concept": "shared concept content " * 200},
        auto_load_trace=False,
        memo_cache=None,
    )
    diag = next(d for d in result.warnings if d.id == "cache.sub-workflow-cache-undeclared")
    assert diag.context is not None
    assert diag.context["savings_usd"] is not None
    assert diag.context["savings_usd"] > 0.0
```

### Optional negative test (recommended)

Verify Tier 0 doesn't fire when `parent_workflow != ctx.workflow_path`. This locks the scope guard:

```python
def test_sub_workflow_cache_undeclared_tier_0_scoped_to_analyzed_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 0 only consults parameters when the analyzed workflow IS the
    boundary's parent. For deeper nested boundaries (parent_workflow !=
    ctx.workflow_path), CLI parameters apply to the root, not the
    intermediate sub-workflow — falling through to existing tiers is
    correct.

    Mutation contract: drop the ``workflow_path != ctx.workflow_path`` guard
    in ``_resolve_value_from_workflow_parameters`` → this might pass
    incorrectly (Tier 0 fires for a deeper boundary using root-level
    parameters). Build a fixture where the deeper boundary has a different
    parent_workflow than ctx.workflow_path; assert savings_usd remains None
    in that case despite parameters being populated.
    """
    # ... fixture: 3-level workflow with deeper boundary, no trace, only CLI params.
    # Assert: savings_usd is None for the deeper boundary.
```

Optional because the test fixture is more involved. The positive test + the scope guard's syntactic clarity may be enough. Use judgment.

### Mutation contracts to verify

For each:
1. Drop the entire Tier 0 call site → positive test fails.
2. Drop the `workflow_path != ctx.workflow_path` guard → if you wrote the negative test, it fails. Otherwise, this mutation is undetected (acceptable for v1, document the gap).
3. Drop the `root not in declared_inputs` guard → fixture with a node-output-rooted ref + populated parameters would silently consult parameters incorrectly. Hard to construct cleanly; mutation may be accepted as undetected if no clean fixture emerges.

---

## Baseline drift

### Prediction

After Tier 0 lands, run `verify.sh`. Expected drifts:

- **Cases where the analyzed workflow is the parent of a cross-boundary AND CLI parameters supply the boundary value AND no memo/trace was already filling it.** Hard to enumerate without running the harness. Likely candidates: any baseline case that:
  - Calls a workflow node passing a `${input}` via the parent's `inputs:` mapping
  - Doesn't have a corresponding memo seed or trace for that input
  - Has CLI parameters set in `command.sh`

- **Lyrics-generator capture probably UNCHANGED.** As argued earlier — the boundary `song-creator → chorus-chooser` is not top-level from `lyrics-generator.pflow.md`'s perspective. Tier 0 won't fire.

- **04-warning-catalog/05-cache.sub-workflow-cache-undeclared** — uses CLI parameter `article=$LONG`. Look at the workflow IR — is the parent `workflow.pflow.md` directly invoking the child via `inputs.article: ${article}`? If yes, Tier 0 fires; current "savings unavailable" → real dollar tag.

### Regenerate command

```bash
cd .taskmaster/tasks/task_159/baseline
./verify.sh
# For each DRIFT line, inspect the diff:
./run-case.sh <case-path> --diff
# After confirming each drift is a strict improvement:
./regenerate.sh <case-path>
# Re-verify:
./verify.sh
# Should show 65 passed.
```

### Strict-improvement audit

For each drifted baseline, confirm:
- Pre-fix: `savings unavailable` on the recommendation
- Post-fix: `saves ~$X.XX/run` (or `Note: ... below threshold` if tokens are small)
- The dollar number is plausible given the workflow's call counts × token estimate

If a baseline's dollar tag looks implausibly high or low (e.g. `$15.00/run` on a workflow that paid `$0.05`), STOP and bring the numbers to the user before committing.

### Show the user the diff

The diff is the load-bearing artifact for this PR. Show:
```bash
git diff .taskmaster/tasks/task_159/baseline/04-warning-catalog/05-cache.sub-workflow-cache-undeclared/expected-stdout.txt
```

Especially if the lyrics-generator capture DOES drift (unexpected!) — that means a Tier 0 path exists I didn't anticipate. Investigate before regenerating.

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

# 4. Full default suite
make test

# 5. make check (lint + format + mypy + deptry)
make check

# 6. Baseline harness
bash .taskmaster/tasks/task_159/baseline/verify.sh
# Regenerate any drifts as strict improvements; re-verify.

# 7. Manual smoke (THE CRITICAL VERIFICATION)
uv run pflow analyze-cache /tmp/smoke-cache/parent.pflow.md \
    --no-trace-autoload article="hello world this is a tiny article"
# Expected: recommendation now shows below-threshold warning (article tokens
# ≈ 7, below threshold). Confirms Tier 0 fires.

uv run pflow analyze-cache /tmp/smoke-cache/parent.pflow.md \
    --no-trace-autoload article="$(python -c "print('shared content ' * 1000)")"
# Expected: recommendation now shows real saves ~$X.XX/run (article tokens
# ≈ 2000, above any threshold).
```

If gate 7 doesn't show the expected behavior, STOP. The Tier 0 wiring is wrong and gates 1-6 may have been false-passing on synthetic fixtures.

---

## What NOT to do

1. **Don't add a new catalog ID.** DD#29 closed the cache.* catalog; this is field enrichment of an existing ID's emission path.

2. **Don't change `cache.sub-workflow-cache-undeclared`'s message template or required context keys.** The catalog already accepts `savings_usd: float | None` and the threshold-clause infrastructure is in place. Tier 0 only changes WHEN savings populates, not the diagnostic shape.

3. **Don't try to apply Tier 0 to deeper-than-top-level boundaries.** The `workflow_path == ctx.workflow_path` guard is load-bearing. Removing it would silently use root-level CLI parameters for nested workflow inputs that have nothing to do with the root — a fabrication, not unmeasurable.

4. **Don't fold this into a refactor of the resolution-tier architecture.** The current 4-tier pattern is established (memo → trace → invocation → None); Tier 0 is a strict prepend, not a redesign. If you find yourself wanting to refactor the tiers into a registry or strategy pattern, STOP — that's task 160 territory.

5. **Don't replace `_estimate_parent_value_tokens` with `ctx.resolve_ref_value(ref)`.** That helper is scoped to `ctx.workflow_path` only; it would silently produce wrong results for cross-workflow boundaries where `parent_workflow != ctx.workflow_path`. The boundaries-cross-workflows shape is precisely why this helper exists separately.

6. **Don't fabricate when parameters supply an empty/None value.** `_normalize_empty` returns None for empty strings/dicts/lists — that's the right behavior. Empty CLI parameter is "we don't have it" → fall through, not "tokens=0".

7. **Don't bump JSON_FORMAT_VERSION.** Pre-merge branch, no shape change, additive context. Per the existing branch discipline (POLISH-PLAN.md line 577).

8. **Don't reach into `_resolve_from_parameters` (private method on `AnalysisContext`).** It's reusable in spirit but architecturally private to the context module. Inline the same TemplateResolver pattern in your new helper; cheaper byte cost than coupling cache_analysis to context internals.

9. **Don't construct synthetic Diagnostics directly in tests.** Drive `analyze(...)` end-to-end. Pitfall #19 has bitten this branch 8+ times. The fixture pattern in `test_cache_analysis_per_id_emission.py` is the right shape.

10. **Don't forget the autouse `deterministic_tokens` fixture override in tests.** Without `monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)`, your assertion `savings_usd > 0` will fail because the autouse fixture patches `_input_rate=None`.

---

## Open questions to bring back to the user

Three items where the plan made a default choice but the user might prefer different. ASK before assuming:

1. **Tier 0 placement.** I placed it BEFORE Tier 1 (memo) per the documented "parameters WIN over memo for input refs" convention in `AnalysisContext.resolve_ref_value`. The user might prefer parameters AFTER memo (giving memo precedence as the "real measured" value). My read is the existing convention is the right precedent; if the user prefers memo-first, that's a deliberate semantic divergence worth understanding before committing.

2. **Optional negative scope-guard test.** I marked it as recommended-not-mandatory. The fixture is moderately involved (3-level workflow). The positive test plus syntactic clarity of the guard may be sufficient. Skip if it adds churn; add if you want belt-and-suspenders.

3. **What if a baseline drifts in an unexpected way.** If the lyrics-generator capture drifts (which I don't expect), it means there's a Tier 0 path I didn't anticipate. Investigate the path before regenerating. Bring the explanation to the user before committing the baseline.

---

## Confidence breakdown

Honest about what's grounded vs. assumed.

| Claim | Confidence | Why |
|---|---|---|
| The gap exists and CLI parameters aren't consulted today | **High** | Verified by reading `_estimate_parent_value_tokens` source (lines 3389-3428) and by smoke-test repro showing "savings unavailable" with CLI params populated. |
| `AnalysisContext.parameters_for_workflow` is the right scope primitive | **High** | Read the source at `context.py:140-144`; semantics match exactly what Tier 0 needs. |
| Tier 0 placement before Tier 1 (memo) is correct | **Medium-High** | The existing `AnalysisContext.resolve_ref_value` convention is documented at `context.py:155-157` ("parameters WIN over memo"). Mirroring it. The user could prefer memo-first; ask. |
| Tier 0 fix is ~15-25 LOC | **High** | Spec'd above, mostly mechanical. |
| The fix unblocks first-contact agent UX for top-level boundaries | **High** | Smoke test will demonstrate. |
| Lyrics-generator canonical capture stays unchanged | **Medium** | Argued the boundary is below the analyzed root; Tier 0's scope guard prevents it from firing. But baselines have surprised me before. |
| Gate 7 (manual smoke) reveals the right behavior | **High** | Same as the threshold-clause PR's smoke; just add Tier 0 and re-run. |
| The 04-warning-catalog/05 baseline drifts to a real dollar tag | **Medium** | Depends on the workflow.pflow.md fixture's exact shape. Inspect it before predicting. |
| Per-provider pricing is accurate enough for the dollar tag | **High** | Inherited from N-7 v1's verification (Anthropic 0.1× factor; Gemini cached_tokens rate confirmed in LiteLLM). |

---

## What "done" looks like

- New helper `_resolve_value_from_workflow_parameters` in `analyze.py`.
- `_estimate_parent_value_tokens` updated to call it as Tier 0 (before memo).
- One new positive test passing (`test_sub_workflow_cache_undeclared_savings_populated_from_workflow_parameters`).
- Optional negative test covering the scope guard.
- All existing sub-workflow savings tests still pass (Tier 0 is purely additive).
- Full default suite green (~6,435+ passing — depends on what else has shipped between now and your work).
- `make check` clean.
- Baselines: any drift is a strict improvement (savings unavailable → real dollar tag OR threshold warning).
- Manual smoke (gate 7) shows the agent-UX win on a tiny CLI-parameter workflow.
- The lyrics-generator and other affected baselines, if drifted, have been shown to the user before commit.

---

## Files you will touch

| File | What changes |
|---|---|
| `src/pflow/core/cache_analysis/analyze.py` | Add `_resolve_value_from_workflow_parameters` helper (~25 LOC). Update `_estimate_parent_value_tokens` to call it as Tier 0 (~5 LOC + docstring update). |
| `tests/test_core/test_cache_analysis_per_id_emission.py` | One new positive test (~50 LOC). Optional negative test (~50 LOC). |
| `.taskmaster/tasks/task_159/baseline/...` | Regenerated baselines for cases where Tier 0 fires. Likely 1-3 cases; harness will tell you. |

## Files to read for context (in order)

1. **This document** — full briefing.
2. `scratchpads/handoffs/task-159-n7-input-passthrough-fallback-plan.md` — companion plan for Tier 3 (already shipped). Useful for understanding the cross-tier framing.
3. `src/pflow/core/cache_analysis/context.py:140-228` — `AnalysisContext.parameters_for_workflow`, `resolve_ref_value`, `_resolve_from_parameters`. The reusable resolution pattern.
4. `src/pflow/core/cache_analysis/analyze.py:3389-3428` — current `_estimate_parent_value_tokens`.
5. `src/pflow/core/cache_analysis/analyze.py:2263-2277` — `_template_root_segment` helper.
6. `tests/test_core/test_cache_analysis_per_id_emission.py:79-92` — autouse `deterministic_tokens` fixture; lines 357+ existing sub-workflow tests; line 178+ the local `_input_rate` override pattern.
7. `src/pflow/core/cache_analysis/CLAUDE.md` — search for "AnalysisContext" and "parameters" sections.

## Files you should NOT need to touch

- `warning_catalog.py` — catalog spec already accepts `savings_usd: float | None` and `below_threshold_clause: str`. No template change.
- `render_text.py` / `render_json.py` — no rendering change. Existing tri-state and threshold-clause rendering already handles the populated case.
- `view_helpers.py` — `Diagnostic.context["savings_usd"]` already flows through to `RecommendedAction.estimated_savings_usd`.
- `cross_workflow.py` — walker output already has everything needed.
- `context.py` — Tier 0 inlines the resolution pattern; no need to reach into context internals.

---

> **Final note**: this is an agent-UX fix, not a correctness bug. The just-shipped threshold-clause change is correct as-is for cases where memo or trace data exists. Tier 0 unlocks the same correctness-and-actionability when CLI parameters are the only signal — i.e., on first contact, which is the most common agent flow. Ship it for the agent-UX win on first-contact analysis. Don't over-engineer; mirror the existing convention.
