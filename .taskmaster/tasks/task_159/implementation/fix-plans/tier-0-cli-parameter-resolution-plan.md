# Tier 0 — CLI Parameter Resolution for Sub-Workflow Cache Savings

> **Atomic implementation plan.** Self-contained for an isolated agent. Do not require reading other handoff documents — every fact below has been independently verified by parallel `pflow-codebase-searcher` investigations and is cited with file:line.

---

## Context

`pflow analyze-cache <workflow.pflow.md> article="..."` is the canonical first-contact agent flow: the agent is planning a workflow before they've run it, so they pass sample inputs on the CLI to get realistic recommendations.

**The analyzer doesn't currently use those CLI parameters when projecting tokens at sub-workflow boundaries.** The `cache.sub-workflow-cache-undeclared` recommendation's `savings_usd` and threshold-warning clause stay silent until the agent has run the workflow at least once (populating memo) or supplies a trace explicitly.

The fix adds **Tier 0** to `_estimate_parent_value_tokens` (`src/pflow/core/cache_analysis/analyze.py:3390`): a parameter-resolution helper that mirrors the existing sibling pattern (`_resolve_value_in_workflow_memo`, `_resolve_value_in_workflow_trace`, `_resolve_input_at_workflow_node_invocation`). After this lands, a fresh agent running `pflow analyze-cache root.pflow.md article="..."` gets a real `saves ~$X.XX/run` tag (or a real `Note: below threshold` warning) on first contact — no run-then-reanalyze loop required.

**Estimated effort**: ~25 LOC + 3 tests (~120 LOC) + 1 baseline regeneration.

---

## Pre-implementation context (all verified, file:line cited)

### Fact 1 — Cascade integration site is unambiguous

`_estimate_parent_value_tokens` lives at `src/pflow/core/cache_analysis/analyze.py:3390-3429`. Current shape:

```python
def _estimate_parent_value_tokens(
    candidate: _SubWorkflowCacheCandidate,
    *,
    model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> int | None:
    """Tier 1: memo / Tier 2: trace by node_id / Tier 3: invocation event / Tier 4: None"""
    ref = candidate.parent_value_expr
    if "??" in ref:
        return None
    workflow_path = candidate.parent_workflow
    value = _resolve_value_in_workflow_memo(ref, workflow_path=workflow_path, ctx=ctx)        # Tier 1
    if value is None:
        value = _resolve_value_in_workflow_trace(ref, workflow_path=workflow_path, ctx=ctx, cw_result=cw_result)  # Tier 2
    if value is None:
        value = _resolve_input_at_workflow_node_invocation(...)                              # Tier 3
    if value is None:
        return None
    return estimate_tokens(model, deterministic_serialize(value))[0]
```

Tier 0 inserts as a fourth `if value is None:` step, BEFORE the memo call.

### Fact 2 — Sibling helpers form an established pattern at module level

All three sibling helpers live in `analyze.py`:
- `_resolve_value_in_workflow_memo` — `analyze.py:3241-3275`
- `_trace_node_output_for` — `analyze.py:3278-3307` (helper for the next one)
- `_resolve_value_in_workflow_trace` — `analyze.py:3310-3337`
- `_resolve_input_at_workflow_node_invocation` — `analyze.py:3340-3387`

Each takes `ref: str, *, workflow_path: str, ctx: AnalysisContext` (some with `cw_result`) and returns `Any | None`. The new Tier 0 helper mirrors this signature exactly.

### Fact 3 — Walker-derived `parameters_by_workflow` is the cross-workflow scoping primitive

`AnalysisContext.parameters_for_workflow(workflow_path)` at `context.py:140-144`:
```python
def parameters_for_workflow(self, workflow_path: str | None) -> Mapping[str, Any]:
    if workflow_path == self.workflow_path:
        return self.parameters       # CLI dict for root
    return self.parameters_by_workflow.get(workflow_path, {})  # walker-resolved for children
```

`parameters_by_workflow` is populated in production by `_build_parameters_by_workflow` at `analyze.py:1246-1288`. The walker:
1. Seeds `params_by_workflow[root_workflow_path] = root_parameters` (the CLI dict).
2. Walks `cw_result.edges`. For each edge with `parent_workflow` already in `params_by_workflow`, builds a parent-scoped `AnalysisContext` and resolves `edge.parent_input_value` (the `${var}` expression in the parent's `inputs:` mapping) against parent params via `_resolve_child_input_value` → `TemplateResolver`.
3. Writes resolved value to `params_by_workflow[child_workflow][child_input_name]`.
4. Repeats until no progress (handles multi-level nesting like `lyrics-generator → song-creator → chorus-chooser`).

**Implication**: For ANY boundary, `parameters_for_workflow(boundary.parent_workflow)` returns the parent's resolved param dict — the SAME values the runtime would actually pass to that parent. Tier 0 reading from this primitive is honest (not fabrication).

### Fact 4 — CLI → `ctx.parameters` is verbatim post-`infer_type`

`pflow analyze-cache wf.pflow.md key=value` data path:
1. Click captures `params: tuple[str, ...]` at `cli/commands/analyze_cache.py:42-43,78`.
2. `parse_workflow_params(params)` at `cli/param_parsing.py:49-65` splits on `=` and runs `infer_type(value)` per arg. **Type-blind heuristic** (no `inputs:` consultation): `"42"` → int, `"true"` → bool, `"[1,2,3]"` → list (via `json.loads`), else string.
3. Forwarded to `analyze(parameters=parsed_params)` at `analyze_cache.py:141-148`.
4. Stored verbatim into `ctx.parameters` via `AnalysisContext.build` at `context.py:87-89`.
5. Missing CLI param: simply absent from the dict. Helper's `if root not in params` guard handles this correctly.

For typical use (`article="long string"`), the value reaches `ctx.parameters["article"]` as a raw string — exact passthrough.

### Fact 5 — `_normalize_empty` is the load-bearing convention for "we have nothing"

`context.py:231-242` returns `None` for empty string / dict / list / tuple / set; passes through other values. Used by all three sibling helpers to push the cascade to Tier-4 unavailable rather than fabricating `~0 tokens`. The new Tier 0 helper MUST end with `_normalize_empty(resolved)`.

### Fact 6 — Imports already in place

In `analyze.py`:
- Line 70: `from .context import AnalysisContext, _normalize_empty`
- Line 62: `from pflow.runtime.template_resolver import TemplateResolver` (module-level, NOT lazy)

No new imports required.

### Fact 7 — `_SubWorkflowCacheCandidate` carries everything Tier 0 needs

Defined at `analyze.py:3156-3173`. Frozen dataclass; fields: `parent_workflow`, `parent_value_expr`, `parent_node_id`, `line_in_parent`, `child_workflow`, `child_input_name`, `child_count`, `child_node_ids`. The four fields Tier 0 reads (`parent_workflow`, `parent_value_expr`) are present and stable.

---

## The change

### One new helper in `src/pflow/core/cache_analysis/analyze.py`

Place IMMEDIATELY AFTER `_resolve_value_in_workflow_memo` (i.e., insert at the boundary between line 3275 and the blank line before `_trace_node_output_for` at 3278). Sibling helpers cluster together; readers find Tier 0 next to Tier 1.

```python
def _resolve_value_in_workflow_parameters(
    ref: str,
    *,
    workflow_path: str,
    ctx: AnalysisContext,
) -> Any | None:
    """Resolve ``ref`` against workflow-scoped parameters (Tier 0).

    Cross-workflow analog to ``AnalysisContext._resolve_from_parameters`` (which
    keys on ``self.workflow_path``). For sub-workflow boundary findings the
    parent value lives in the parent workflow, not the root.

    Reads from ``ctx.parameters_for_workflow(workflow_path)`` — for the
    analyzed root that is the agent's CLI ``--inputs``; for nested children
    that is the walker-resolved param dict (see ``_build_parameters_by_workflow``
    at ``analyze.py:1246``). Both are honest signals: the walker resolves
    edge ``${ref}`` expressions through the same ``TemplateResolver`` the
    runtime would use, so the value here equals what the runtime would pass
    to that boundary on a real run.

    Placement (Tier 0, BEFORE memo) mirrors the documented "parameters WIN
    over memo for input refs" precedence in
    ``AnalysisContext.resolve_ref_value`` (``context.py:150-182``): the agent's
    CURRENT --inputs represent their CURRENT question; memo from a prior run
    with different inputs MUST NOT override.
    """
    params = ctx.parameters_for_workflow(workflow_path)
    if not params:
        return None
    root = TemplateResolver.extract_root_node_id(ref)
    if not root:
        return None
    if root not in params:
        return None
    try:
        resolved = TemplateResolver.resolve_template(f"${{{ref}}}", {root: params[root]})
    except Exception:
        logger.debug("parameters resolve failed for %s in %s", ref, workflow_path, exc_info=True)
        return None
    if isinstance(resolved, str) and resolved == f"${{{ref}}}":
        return None  # ref didn't navigate (e.g. dotted path missed) — fall through
    return _normalize_empty(resolved)
```

### Integration in `_estimate_parent_value_tokens` (`analyze.py:3390`)

Replace the existing function body. Add Tier 0 call BEFORE the memo call. Update docstring to renumber tiers (1→2, 2→3, 3→4, etc., with new Tier 0 at top).

```python
def _estimate_parent_value_tokens(
    candidate: _SubWorkflowCacheCandidate,
    *,
    model: str,
    ctx: AnalysisContext,
    cw_result: Any,
) -> int | None:
    """Tokens for the parent value flowing across a sub-workflow boundary.

    Tier 0: workflow parameters (CLI ``--inputs`` for the analyzed root, or
    walker-propagated values for nested children). Mirrors the
    "parameters WIN over memo" convention from
    ``AnalysisContext.resolve_ref_value`` so that ``pflow analyze-cache
    root.pflow.md input=<sample>`` produces real token estimates on first
    contact (no run-then-reanalyze loop).
    Tier 1: memo cache (cross-workflow scoped, by ``parent_value_expr`` root).
    Tier 2: trace by node_id — for node-output-rooted refs (e.g.
    ``${creative.direction}`` where ``creative`` is a node id in the parent).
    Tier 3: parent workflow-node ``node_params['inputs'][child_input_name]``
    — closes the input-passthrough case (e.g. ``${concept}`` where ``concept``
    is the parent's own workflow input). Reads from the runtime invocation
    site rather than reconstructing via the upstream node lookup.
    Tier 4: ``None`` (honest unmeasurable — never fabricate).

    Coalesce expressions (``${a ?? b}``) are not handled — too ambiguous
    which operand sourced the value at runtime; returning None keeps the
    rest of the projection honest.
    """
    ref = candidate.parent_value_expr
    if "??" in ref:
        return None
    workflow_path = candidate.parent_workflow
    value = _resolve_value_in_workflow_parameters(ref, workflow_path=workflow_path, ctx=ctx)
    if value is None:
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

### Total source change: ~25 LOC of new helper + ~5 LOC of integration + docstring update.

---

## Critical design decision: NO scope guard

The earlier braindump (`scratchpads/handoffs/task-159-tier-0-cli-parameter-resolution-braindump.md`) proposed a defensive guard `if workflow_path != ctx.workflow_path: return None` to restrict Tier 0 to the analyzed root only. **This plan deliberately omits that guard.** Reasoning:

1. **`parameters_for_workflow` IS the scoping primitive.** It already returns `{}` for unmapped sub-workflows. Adding the guard duplicates the scope semantics in two places.
2. **Walker-derived per-child params are honest, not fabricated.** `_build_parameters_by_workflow` (`analyze.py:1246`) resolves each edge's `${ref}` through the parent's own `AnalysisContext`. The values it writes to `params_by_workflow[child]` equal what the runtime would pass on a real run. Reading them in Tier 0 is the same evidence basis as Tier 1 reading from memo.
3. **The lyrics-generator canonical case benefits.** With the scope guard, only the top-level boundary can use Tier 0. Without it, the deeper `song-creator → chorus-chooser` boundary picks up walker-derived `concept` value when the agent passes `concept=...` on the CLI to greenfield analysis. Tier 3 already handles this in trace mode; Tier 0 closes the same gap in greenfield mode.
4. **Future-proof.** If a future caller populates `parameters_by_workflow` for sub-workflows directly, behavior is correct without code changes. The guard would silently block such cases.

If the implementer encounters a failing test that suggests the guard is needed, STOP — the failing case is a bug in either the walker, the test fixture, or this plan; do not add the guard as a workaround.

---

## Top-10% alternative briefly considered

**Extending `AnalysisContext.resolve_ref_value` to accept an optional `workflow_path` kwarg** would unify Tier 0+1 into a single primitive call and eliminate `_resolve_value_in_workflow_memo` as a parallel helper. mypy / rustc / ruff have similar single-resolver patterns.

**Rejected for this PR** because:
- The sibling-helper pattern (`_resolve_value_in_workflow_*`) already exists and is consistent. New helper completes the pattern; refactoring breaks it.
- `resolve_ref_value`'s `declared_inputs` check uses the root IR, not per-workflow IRs (which `AnalysisContext` doesn't carry). Generalizing requires either skipping that check or threading `irs_by_workflow` through. Wider change, broader review.
- Smaller diff = easier mutation-contract verification.

If the cascade grows beyond 4 tiers or if a future task touches the resolution path heavily, revisit during task 160 (the analyzer architectural refactor).

---

## Edge-case behavior table

All cases verified against the helper code above. "Tier" column says which cascade tier handles the case.

| Case | Input | Behavior | Tier |
|---|---|---|---|
| Top-level boundary, CLI passes string | `params={"article": "long text"}`, `parent_value_expr="article"` | `params["article"]` → resolved; tokens estimated | 0 |
| Top-level boundary, CLI passes int | `params={"x": 42}` (post `infer_type`), `parent_value_expr="x"` | `deterministic_serialize(42)` → `"42"`; ~1 token; below threshold note fires | 0 |
| Top-level boundary, CLI passes list | `params={"items": [1,2,3]}`, `parent_value_expr="items"` | `deterministic_serialize([1,2,3])` → JSON; tokens estimated from JSON length | 0 |
| Top-level boundary, CLI passes empty string | `params={"article": ""}` | `_normalize_empty("")` → None; falls to Tier 1 (memo) | 0→1 |
| Top-level boundary, CLI omits the param | `params={}`, `parent_value_expr="article"` | `params` is empty (or root not in params); falls to Tier 1 | 0→1 |
| Nested boundary, walker propagated value | `lyrics-generator → song-creator → chorus-chooser`, CLI passes `concept`, walker resolved each hop | `parameters_for_workflow(song-creator-path)["concept"]` returns walker's value; tokens estimated | 0 |
| Nested boundary, walker couldn't resolve (e.g. node-output ref upstream) | walker's `_resolve_child_input_value` returned None; key absent from per-workflow params | `if root not in params` returns None; falls to Tier 1 | 0→1 |
| `parent_value_expr` is a coalesce: `${a ?? b}` | — | Early `if "??" in ref: return None` (preserved); no tier fires | guard |
| `parent_value_expr` is a node-output ref: `${draft.response}` | params has no `draft` key (CLI doesn't supply node outputs) | `if root not in params` returns None; falls to Tier 1 | 0→1 |
| `parent_value_expr` is a dotted-path on input: `${concept.core_idea}` | `params={"concept": {"core_idea": "..."}}` | `TemplateResolver.resolve_template` navigates `.core_idea`; tokens estimated | 0 |
| `parent_value_expr` is a dotted-path miss: `${concept.bogus}` | `params={"concept": {"core_idea": "..."}}` | `resolved == f"${{{ref}}}"` (echo); helper returns None; falls to Tier 1 | 0→1 |
| Memo populated with a different value than CLI | `params={"x": "B"}`, memo has `x="A"` | Tier 0 wins; "B" used. Documented "parameters WIN" precedence | 0 |
| No CLI, no memo, no trace, no invocation event | all four tiers return None | `_estimate_parent_value_tokens` returns None; `savings_usd=None`; renderer shows `savings unavailable` | 4 |

---

## Brownfield / greenfield matrix

| Scenario | Tier 0 fires? | Behavior |
|---|---|---|
| Greenfield (no memo, no trace), CLI passes input | YES | Real `saves ~$X.XX/run` or `Note: below threshold` on first contact. **The agent-UX win.** |
| Greenfield, no CLI param | NO (params absent) | Falls through to Tiers 1-4 (all empty) → `savings unavailable`. Unchanged from today. |
| Brownfield (memo populated), CLI passes same input | YES (Tier 0 wins) | Same value either way; no observable change. |
| Brownfield, CLI passes DIFFERENT input than memo | YES (Tier 0 wins) | Recommendations reflect CURRENT question, not stale prior run. **Documented precedence.** |
| Brownfield, CLI passes no input | NO | Falls to Tier 1 (memo) → savings populated from prior run. Unchanged from today. |
| Trace mode, CLI passes input | YES (Tier 0 wins) | Tier 0 value = walker-resolved CLI value = trace value (in correct runs). No observable difference. |
| Trace mode, CLI passes input that DIFFERS from trace | YES (Tier 0 wins) | Recommendations reflect CURRENT question. Trace is historical evidence; CLI is the agent's current ask. |

Net: Tier 0 is purely additive — never reduces signal, occasionally produces signal where there was none.

---

## Tests to add

All in `tests/test_core/test_cache_analysis_per_id_emission.py`. Place after the existing `test_sub_workflow_cache_undeclared_savings_none_when_unpriced_model` (line 627 today; will shift if other tests landed since).

The autouse `deterministic_tokens` fixture (line 80) patches `analyze_module._input_rate` to `lambda _model: None`. Tests that assert positive `savings_usd` MUST override:
```python
analyze_module = importlib.import_module("pflow.core.cache_analysis.analyze")
monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)
```

Mirror the pattern from existing tests (e.g., `test_sub_workflow_cache_undeclared_savings_populated_from_memo` at line 357 → override at line 373).

### Test 1 (mandatory) — Tier 0 fires from CLI parameters at top-level boundary

```python
def test_sub_workflow_cache_undeclared_savings_populated_from_workflow_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 0 (N-7 v3): when the analyzed workflow IS the boundary's parent
    and CLI --inputs supplies the value, the analyzer estimates tokens from
    the parameter directly. No memo, no trace, no invocation event needed.

    Closes the canonical first-contact agent flow:
    ``pflow analyze-cache root.pflow.md input=<sample>`` produces real savings
    on first call (no run-then-reanalyze loop).

    Mutation contract: drop the new ``_resolve_value_in_workflow_parameters``
    Tier 0 call in ``_estimate_parent_value_tokens`` → this fails (savings
    drops to None; no other tier has the value in this fixture).
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

### Test 2 (mandatory) — Tier 0 wins over memo (precedence lock)

```python
def test_sub_workflow_cache_undeclared_parameters_win_over_memo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Locks the documented precedence: when both CLI parameters AND memo
    have a value for the same key, parameters WIN. The agent's --inputs
    represent their CURRENT question; stale memo from a prior run with
    different inputs MUST NOT override.

    Mutation contract: reorder Tier 0 to AFTER Tier 1 in
    ``_estimate_parent_value_tokens`` → this fails (the savings figure
    reflects the SHORT memo value instead of the LONG CLI value).
    """
    # See test 1 for fixture shape — same parent_ir / child_ir, same
    # resolve_sub_workflow patch, same _input_rate override.
    # Differences:
    #   - Pre-populate memo cache with concept="short" (small token count).
    #   - CLI passes concept="long content " * 500 (large token count).
    #   - Assert savings_usd > threshold corresponding to the LONG value
    #     (not the short value).
    # Use MemoizationCache from src/pflow/runtime/cache.py directly, scoped
    # to tmp_path via PFLOW_HOME monkeypatch (existing pattern in this file).
    ...  # [Implementer: follow the test_sub_workflow_cache_undeclared_savings_populated_from_memo pattern at line 357 for memo setup; layer CLI params on top.]
```

### Test 3 (recommended — proves no scope guard regression) — Tier 0 fires for nested boundary via walker propagation

```python
def test_sub_workflow_cache_undeclared_savings_populated_via_walker_propagated_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 0 fires for a NESTED boundary when the walker has propagated
    the CLI param down through ``_build_parameters_by_workflow``.

    Three-level fixture: root → middle → leaf, with leaf consuming
    ``${shared}`` which roots on middle's input declaration. CLI passes
    ``shared=<value>`` at root. Walker resolves root → middle (shared:
    ${shared}) and middle → leaf (shared: ${shared}), so
    ``parameters_for_workflow(middle.pflow.md)["shared"]`` is populated.
    Tier 0 on the middle → leaf boundary uses that walker-derived value.

    Mutation contract: re-add a scope guard ``if workflow_path !=
    ctx.workflow_path: return None`` to ``_resolve_value_in_workflow_parameters``
    → this fails (the middle → leaf boundary's savings drops to None
    because the guard rejects the non-root scope).
    """
    # Three-level fixture with shared input flowing through all levels.
    # Patch resolve_sub_workflow to dispatch by workflow path, returning
    # middle_ir for "./middle.pflow.md" and leaf_ir for "./leaf.pflow.md".
    # Assert: the cache.sub-workflow-cache-undeclared diagnostic emitted
    # for the middle → leaf boundary has savings_usd > 0.
    ...
```

### Total test cost: ~150-200 LOC (test 1 ~70 LOC, test 2 ~60 LOC, test 3 ~80 LOC).

---

## Verification gates (run in order; each MUST be green before next)

```bash
# 1. Touched-file lint + types
uv run ruff check src/pflow/core/cache_analysis/analyze.py tests/test_core/test_cache_analysis_per_id_emission.py
uv run ruff format --check src/pflow/core/cache_analysis/analyze.py tests/test_core/test_cache_analysis_per_id_emission.py
uv run mypy src/pflow/core/cache_analysis/analyze.py

# 2. Sub-workflow tests (focused)
uv run pytest tests/test_core/test_cache_analysis_per_id_emission.py -k "sub_workflow" --tb=short

# 3. Full cache-analysis suite
uv run pytest tests/test_core/test_cache_analysis_*.py --tb=short

# 4. Full default suite (~6,436+ tests today; +3 from this work)
make test

# 5. Quality gate
make check

# 6. Baseline harness — pre-fix capture, then post-fix verify
bash .taskmaster/tasks/task_159/baseline/verify.sh
# Expected drift: 1 case (see "Baseline drift" section). Regenerate per below.

# 7. Manual smoke (THE CRITICAL VERIFICATION; gate 6 only catches what's already in baselines)
# 7a. Recreate the smoke fixture if /tmp/smoke-cache/ doesn't exist:
mkdir -p /tmp/smoke-cache
cat > /tmp/smoke-cache/parent.pflow.md <<'EOF'
# Parent

## Inputs

- article: string

## Steps

### child-call
- type: workflow
- workflow: ./child.pflow.md
- inputs:
    article: ${article}
EOF

cat > /tmp/smoke-cache/child.pflow.md <<'EOF'
# Child

## Inputs

- article: string

## Steps

### draft
- type: llm
- model: claude-sonnet-4-6
- prompt: |
    Draft based on: ${article}

### review
- type: llm
- model: claude-sonnet-4-6
- prompt: |
    Review draft about: ${article}
EOF

# 7b. Smoke (small input → below-threshold note)
uv run pflow analyze-cache /tmp/smoke-cache/parent.pflow.md \
    --no-trace-autoload article="hello world this is a tiny article"
# Expected post-fix: cache.sub-workflow-cache-undeclared recommendation
# now shows "Note: ~7 tokens estimated, below claude-sonnet-4-6's 1024-token minimum".

# 7c. Smoke (large input → real dollar tag)
uv run pflow analyze-cache /tmp/smoke-cache/parent.pflow.md \
    --no-trace-autoload article="$(python -c "print('shared content ' * 1000)")"
# Expected post-fix: cache.sub-workflow-cache-undeclared recommendation
# shows real "saves ~$X.XX/run" dollar tag.
```

If gate 7 doesn't show the expected behavior, STOP. The Tier 0 wiring is broken even if gates 1-6 passed (they may be passing on synthetic fixtures).

---

## Baseline drift handling

### Confirmed drift: ONE case

`/.taskmaster/tasks/task_159/baseline/04-warning-catalog/05-cache.sub-workflow-cache-undeclared/`

Pre-fix: `expected-stdout.txt` shows the recommendation with `savings_usd: null`, `estimated_savings_usd: null`, `below_threshold_clause: ""` (rendered as `savings unavailable`).

Post-fix: `command.sh` passes `article="$LONG"` (~1700 tokens). Top-level boundary `child` workflow node has `inputs: article: ${article}`. Tier 0 fires; `savings_usd` populates; rendered text gains a real dollar tag (or `Note: below threshold` if 1700 happens to fall under the threshold for the model used).

### Cases verified to NOT drift

- All `12-real-world-lyrics-generator/0[1234]/` cases (no CLI params passed → Tier 0 falls through immediately).
- `10-live-recordings/05-gemini-lyrics-generator/` (passes `sources=...` but no `cache.sub-workflow-cache-undeclared` finding fires on `fetch-sources` boundary).
- `04-warning-catalog/10-cache.cross-workflow-prose-mismatch/`, `04-warning-catalog/11-cache.cross-workflow-rename-detected/`, `13-happy-path-interactions/0[23]/`: child workflows declare the relevant chunk in `## Cache`, so `cache.sub-workflow-cache-undeclared` doesn't fire (predicate fails).

If MORE than one case drifts, STOP — there's a missed scenario; bring the diff to the user before regenerating.

### Regenerate procedure

```bash
cd .taskmaster/tasks/task_159/baseline
./verify.sh                                                # confirms 64/65 + 1 DRIFT
./run-case.sh 04-warning-catalog/05-cache.sub-workflow-cache-undeclared --diff
# Inspect the diff. Confirm: savings_usd populates with a plausible number,
# below_threshold_clause appears with sensible model + threshold + token gap,
# rendered text changes "savings unavailable" → "saves ~$X.XX/run" OR
# "Note: ~N tokens estimated, below {model}'s {threshold}-token minimum".
./regenerate.sh 04-warning-catalog/05-cache.sub-workflow-cache-undeclared
./verify.sh                                                # confirms 65/65
```

### Strict-improvement audit

Confirm for the regenerated case:
- `savings_usd` is a plausible number (article ≈1700 tokens × N callsites × Sonnet input rate × 0.9 cache_read_factor — roughly cents to single dollars).
- Threshold clause (if rendered) names the model + threshold (1024 for Sonnet 4.5, 2048 for Sonnet 4.6, etc. — see `src/pflow/core/llm_capabilities.py::get_min_cache_tokens`).

If the dollar tag looks implausibly high (e.g., $50/run on a 1700-token article) or low (sub-cent), STOP and bring the numbers to the user before committing.

---

## What NOT to do

1. **Don't add a new catalog ID.** Per DD#29 (closed-list invariant), `cache.sub-workflow-cache-undeclared` is the existing ID and accepts `savings_usd: float | None`. This is field enrichment, not a new ID.
2. **Don't add a scope guard.** See "Critical design decision" above. The walker's per-workflow scoping is the correct primitive; duplicating it in the helper hurts the lyrics-generator nested case without adding safety.
3. **Don't change `cache.sub-workflow-cache-undeclared`'s message template, headline template, or required context keys.** The threshold-clause infrastructure already handles the populated case via `_below_threshold_clause`.
4. **Don't replace `_estimate_parent_value_tokens` with `ctx.resolve_ref_value(ref)`.** That method is scoped to `ctx.workflow_path` only (`context.py:172`); it would silently produce wrong results for cross-workflow boundaries.
5. **Don't reach into `AnalysisContext._resolve_from_parameters` (private).** Inline the same `TemplateResolver` pattern in your new helper; cheaper byte cost than coupling cache_analysis to context internals.
6. **Don't fabricate when parameters supply an empty value.** `_normalize_empty` returns None for empty string/dict/list — that's the right behavior. Empty CLI parameter is "we don't have it" → fall through, not "tokens=0".
7. **Don't bump `JSON_FORMAT_VERSION`.** Pre-merge branch, additive context only. Per the existing branch discipline, version bumps happen at minor for semantic shifts.
8. **Don't construct synthetic Diagnostics directly in tests.** Drive `analyze(...)` end-to-end. Pitfall #19 has bitten this branch 8+ times. The fixture pattern in `test_cache_analysis_per_id_emission.py` is the right shape (driven by `analyze()` with `resolve_sub_workflow` patched).
9. **Don't forget the autouse `deterministic_tokens` fixture override in tests** asserting positive savings. Without `monkeypatch.setattr(analyze_module, "_input_rate", lambda _model: 1.0)`, savings_usd computes to None and the assertion fails for the wrong reason.
10. **Don't refactor the cascade.** The 4-tier pattern is established. Tier 0 is a strict prepend, not a redesign. If you find yourself wanting to refactor into a registry/strategy pattern, STOP — that's task 160 territory.

---

## Files to modify

| File (absolute path) | Change |
|---|---|
| `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py` | Add `_resolve_value_in_workflow_parameters` helper after line 3275 (~25 LOC). Update `_estimate_parent_value_tokens` body at lines 3411-3429 to insert Tier 0 call + update docstring. |
| `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_core/test_cache_analysis_per_id_emission.py` | Add 2-3 new tests after existing `test_sub_workflow_cache_undeclared_savings_none_when_unpriced_model` (line 627). |
| `/Users/andfal/projects/pflow-feat-prompt-caching/.taskmaster/tasks/task_159/baseline/04-warning-catalog/05-cache.sub-workflow-cache-undeclared/expected-stdout.txt` | Regenerate after implementation (1 baseline drift; verify it's a strict improvement before committing). |

## Files to read for context (in order, only what you need)

1. **This plan file.** Self-contained.
2. `src/pflow/core/cache_analysis/analyze.py` — read lines 3241-3429 (the cascade + sibling helpers + integration site).
3. `src/pflow/core/cache_analysis/context.py` — read lines 140-145 (`parameters_for_workflow`) and 184-203 (`_resolve_from_parameters` — the inspiration pattern).
4. `src/pflow/core/cache_analysis/analyze.py` — read lines 1246-1306 (`_build_parameters_by_workflow` + `_resolve_child_input_value`) to confirm the walker's resolution semantics.
5. `tests/test_core/test_cache_analysis_per_id_emission.py` — read lines 80-100 (autouse fixture) and 357-650 (existing N-7 tests) for fixture/pattern reuse.
6. `src/pflow/core/cache_analysis/CLAUDE.md` — search for "AnalysisContext", "parameters", and "Disambiguation" sections.

## Files you should NOT need to touch

- `warning_catalog.py` — catalog spec already accepts `savings_usd: float | None` and `below_threshold_clause: str`. No template change.
- `render_text.py` / `render_json.py` — no rendering change. Existing tri-state and threshold-clause rendering already handles the populated case.
- `view_helpers.py` — `Diagnostic.context["savings_usd"]` already flows through to `RecommendedAction.estimated_savings_usd`.
- `cross_workflow.py` — walker output is already what we need (this PR consumes existing primitive).
- `context.py` — Tier 0 inlines the resolution pattern; no need to reach into context internals or add new methods.
- `cli/commands/analyze_cache.py` / `cli/param_parsing.py` — CLI wiring already lands `key=value` at `ctx.parameters` verbatim (verified end-to-end).

---

## What "done" looks like

- `_resolve_value_in_workflow_parameters` helper added in `analyze.py` after line 3275, mirroring sibling helper signatures.
- `_estimate_parent_value_tokens` updated to call it as Tier 0 (before memo); docstring tier list updated.
- 2-3 new tests in `test_cache_analysis_per_id_emission.py`, each with a verified mutation contract (drop the production change → matching test fails; restore → passes).
- All existing sub-workflow savings tests still pass (Tier 0 is purely additive).
- `make test` green (~6,439+ passing).
- `make check` clean.
- 1 baseline regenerated as a strict-improvement diff (`04-warning-catalog/05-cache.sub-workflow-cache-undeclared/`); 65/65 baselines pass.
- Manual smoke (gate 7) shows below-threshold note on small input AND real dollar tag on large input.

---

## Out-of-scope cleanups noticed during investigation (do NOT include in this PR)

- `src/pflow/core/cache_analysis/context.py:43-47` docstring falsely claims `AnalysisContext.parameters` arrive post-`coerce_workflow_input`. Untrue on the analyze-cache path (only `infer_type` heuristic runs at `cli/param_parsing.py:9-46`). File later as a doc-only fix.
- The `_template_root_segment` helper (`analyze.py:2264-2278`) is a 1-line wrapper over `ref.split(".", 1)[0].split("[", 1)[0]`. Not used by Tier 0 (Tier 0 uses `TemplateResolver.extract_root_node_id` to match the sibling-helper pattern). No change needed; just noting that two root-extraction primitives exist in this module.
