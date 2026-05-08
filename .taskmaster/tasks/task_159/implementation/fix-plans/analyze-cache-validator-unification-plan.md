# Plan: Unify `pflow analyze-cache` Validation with `WorkflowValidator` Pipeline

**Branch**: `feat/prompt-caching` (Task 159 finalization before merge)
**Type**: Architectural unification + bug fix + cache-focus preservation
**Estimated scope**: ~120 LOC delete, ~110 LOC add, ~5 test fixes, 4 doc updates. Net: −10 LOC; substantial structural simplification.
**Reviewed by**: 5 specialized review agents (review-plan, review-validation-consistency, review-impact-completeness, review-silent-failures, review-agent-ux). Critical findings cross-confirmed by 4 verification searchers.

---

## Context

### The triggering bug

A workflow with `- thinking_effort: high` (the wrong canonical name; `reasoning_effort` is correct) on an LLM node behaves inconsistently across pflow CLI surfaces:

| Surface | Result |
|---|---|
| `pflow run` | ✅ Blocks: `Unknown parameter 'thinking_effort'... Did you mean 'reasoning_effort'?` |
| `pflow run --validate-only` | ✅ Same |
| `pflow run --dry-run` | ✅ Same (validation runs upstream of cache nudge) |
| `pflow save` | ✅ Same |
| `pflow analyze-cache` | ❌ **Silently accepts**, reports "0 opportunities (0 warnings, 0 info)" |

The original baseline-finding bug report claimed the validator silently dropped `thinking_effort` everywhere. Empirical verification proved this false: only `pflow analyze-cache` (and the MCP `analyze_cache` tool — same code path) skips this validation.

### The architectural smell

Today's `pflow.core.cache_analysis.analyze()` calls `validate_data_flow()` directly via an adapter (`_cache_validator_findings`), then filters the result to cache-only diagnostics via `_is_cache_related_diagnostic`. This is:

1. **A subset of validation** — `pflow run`, `--validate-only`, `pflow save` use the full `WorkflowValidator.validate()` (10-step pipeline). The analyzer skipped 9 of 10 steps.
2. **Filtering an already-filtered stream** — calls a partial validator, then filters its output to a smaller subset. Two abstractions doing what one entry would do.
3. **A unique code path** future contributors must learn.

### Design resolution

Top-10% codebase pattern (mypy/ruff/rustc): ONE pipeline, consumers differ in display. But preserve **domain focus** for derived signals:

- **ERRORs broaden universally** — typos and broken structure block execution; every CLI surface must show them. Surface as `blocking_errors[]`.
- **WARNINGs stay cache-scoped** — `analyze-cache`'s "Recommended actions" are *cache opportunities*. A shell node's memoization-cache lint warning belongs to a different concept (per `cache_analysis/CLAUDE.md` "Disambiguation"). Filter advisory findings to cache-related only.
- **Derived counts stay cache-focused** — `summary.actionable_opportunities` (drives the `--dry-run` nudge text "N cache opportunities available") must continue to mean *cache* opportunities, not all validator warnings.
- **Renderer untouched in dispatch shape** — severity-based dispatch already handles broader input. Add ONE field (`suggestions`) to `RecommendedAction` so agent UX parity with `pflow run` is preserved.

### Verified assumptions (from 16 searcher rounds + 4 critical-finding verifications)

| Assumption | Status |
|---|---|
| Step 9 of `WorkflowValidator.validate()` invokes `_validate_cache_block` on each child | ✅ Verified, no suppression flags |
| Renderer dispatches on `severity` axis (not catalog membership) | ✅ Verified |
| Only the cache analyzer reads `context["affected_workflow"]` | ✅ Verified clean |
| `WorkflowValidator.validate(registry=None)` default-constructs internally | ✅ Verified at validator.py:126-127, 132-133 |
| `extracted_params` and analyzer's `parameters` are shape-identical | ✅ Verified |
| `runner.validate()` and `save_service` use **dummies-only** (no real-param merge) | ✅ Verified — plan must match |
| Suggestions ARE dropped from blocking_errors[] under naive Path 2 | ✅ Verified — fix required |
| `_warnings_for_partial_trace` filter is severity-only (not catalog-aware) | ✅ Verified — fix required |
| `summary.actionable_opportunities` would inflate under naive Path 2 | ✅ Verified — fix required |
| `_validate_one_child_call` has 4 diagnostic emission sites (not 2) | ✅ Verified — stamp at function boundary |
| MCP `analyze_cache` inherits automatically | ✅ Verified — single call site |

---

## File changes summary

| # | File | Change |
|---|---|---|
| 1 | `src/pflow/core/workflow/validator.py` | Add module-level `replace` import; add `_stamp_affected_workflow` helper; call it at end of `_validate_one_child_call` (boundary stamping) |
| 2 | `src/pflow/core/cache_analysis/analyze.py` | Delete `_cache_validator_findings` + `_is_cache_related_diagnostic`. Add `_run_full_validation` helper. Update call site. Extend `RecommendedAction`. Update summary count to be catalog-aware. Update partial-trace filter to be catalog-aware. |
| 3 | `src/pflow/core/cache_analysis/view_helpers.py` | Update `_build_actions` to thread `message` + `suggestions` from Diagnostic into `RecommendedAction`. Update `build_recommended_actions` to filter WARNINGs to cache-focused only (preserves domain focus). |
| 4 | `src/pflow/core/cache_analysis/render_json.py` | Update `_action_to_dict` to emit `message` + `suggestions`. |
| 5 | `src/pflow/core/cache_analysis/render_text.py` | Update `_render_action_list` to render suggestions as bullets. Update "Recommended actions" section intro to acknowledge non-cache findings flowing through. |
| 6 | `tests/test_cli/test_analyze_cache.py` | Fix `_MINIMAL_VALID_WORKFLOW` fixture: add `cache: false` to silence step 10 inputless-shell warning. |
| 7 | `tests/test_core/test_cache_analysis_analyze.py` | Invert `test_analyze_filters_non_cache_data_flow_diagnostics` to assert non-cache diagnostics now surface. |
| 8 | `tests/test_core/test_cache_analysis_per_id_emission.py` | Update 2 stale mutation-contract docstrings (lines 3535, 3542, 3576). |
| 9 | `tests/test_core/test_cache_analysis_analyze.py` (new test) | Add architectural parity sentinel: `pflow run`'s validator and `analyze-cache` produce equivalent ERROR diagnostics for the same workflow. |
| 10 | `src/pflow/core/cache_analysis/CLAUDE.md` | Rewrite "Validator delegation" section. |
| 11 | `src/pflow/core/workflow/CLAUDE.md` (line 137) | Update cache_validator_findings adapter reference. |
| 12 | `src/pflow/runtime/compilation/compile_validation.py` (line 118) | Update docstring reference to `_cache_validator_findings`. |
| 13 | `src/pflow/mcp_server/tools/execution_tools.py` | Update `analyze_cache` docstring: broader diagnostic surface, provenance prefix format, updated catalog claim. |

---

## Implementation

### Change 1 — `validator.py`: stamp `affected_workflow` at boundary in step 9

**File**: `src/pflow/core/workflow/validator.py`

#### 1a. Add module-level `replace` import (currently function-local at line 40 only)

Locate the module-level imports (around lines 7-15). Add:

```python
from dataclasses import replace
```

#### 1b. Add the helper function

Insert immediately above `_add_child_provenance` (currently around line 20):

```python
def _stamp_affected_workflow(
    diagnostics: list[Diagnostic], workflow_path: str | None
) -> list[Diagnostic]:
    """Stamp ``context['affected_workflow']`` on diagnostics that don't have one.

    Read by the cache analyzer's renderer for cross-workflow scoping. Inert
    for other consumers — adding the key cannot regress them. Idempotent:
    preserves existing values (mirroring _add_child_provenance's
    first-write-wins semantics for child workflow context fields).

    Stamping at the function boundary in _validate_one_child_call means EVERY
    diagnostic emerging from that function path picks up affected_workflow,
    regardless of which internal sub-step emitted it (load errors, file ref
    errors, required-input errors, recursive child diagnostics, parser
    warnings).
    """
    if not workflow_path:
        return diagnostics
    enriched = []
    for diag in diagnostics:
        existing = dict(diag.context or {})
        # Skip if already stamped with a real value (preserves grandchild stamps
        # under recursion). Treat empty string and "<unknown>" as "not stamped".
        current = existing.get("affected_workflow")
        if not current or current == "<unknown>":
            existing["affected_workflow"] = workflow_path
        enriched.append(replace(diag, context=existing))
    return enriched
```

#### 1c. Wire the stamp at the function boundary in `_validate_one_child_call`

The function `_validate_one_child_call` (around lines 711–775) has FOUR diagnostic emission sites that flow into the local `diagnostics` list:

- `load_errors` from `_load_child_workflow` (around line 737)
- `file_ref_error` from `_resolve_child_file_refs` (around line 749)
- `required_input_errors` from `_check_required_inputs` (around line 754)
- `child_parser_warnings` and recursive `child_diagnostics` from `WorkflowValidator.validate()` (around lines 738 and 773)

The plan does NOT stamp at each individual site (that misses sites and risks future drift). Instead, **stamp once at the function boundary before returning**.

Find the function's terminal `return diagnostics` (or equivalent end). Replace with:

```python
diagnostics = _stamp_affected_workflow(
    diagnostics, str(child_path) if child_path else None
)
return diagnostics
```

`child_path` is in scope — assigned during the file resolution phase (around line 732). For inline-child cases where `child_path` is None, the helper short-circuits and returns the list unchanged.

**Note on `_add_child_provenance` interaction**: existing call sites at lines 738 and 773 already wrap diagnostics with `node_id` (NOT `step_id` — verify the exact variable name during implementation; the actual call is `_add_child_provenance(child_diagnostics, node_id, ref_label)` with three positional args). Stamping AFTER provenance wrapping is fine because:
- `_stamp_affected_workflow` only mutates `context["affected_workflow"]`
- `_add_child_provenance` only mutates `message` and `node_id`
- They are commutative — order doesn't affect output

The plan stamps AFTER all wrapping in one place at function exit, simplifying invariants.

### Change 2 — `analyze.py`: delete the adapter; add `_run_full_validation`

**File**: `src/pflow/core/cache_analysis/analyze.py`

#### 2a. Delete `_is_cache_related_diagnostic` (lines 2855–2887, ~33 LOC)

Verify before deleting: ensure no test file imports this symbol. The `_is_cache_related_diagnostic` is module-private (underscore prefix) and not exported from `__init__.py`.

#### 2b. Delete `_cache_validator_findings` (lines 2890–2926, ~37 LOC)

Same private-symbol verification.

#### 2c. Delete the import on line 59

```python
# DELETE this line:
from pflow.core.workflow.data_flow import validate_data_flow
```

After deletion, grep `validate_data_flow` in `analyze.py` to confirm zero remaining references.

#### 2d. Add new imports near the top of `analyze.py`

```python
from pflow.core.workflow.validator import WorkflowValidator
from pflow.core.validation_utils import generate_dummy_parameters
```

`from dataclasses import replace` is already imported at module top (line 28 — verify); reuse it.

#### 2e. Add `_run_full_validation` helper

Insert at the location vacated by `_cache_validator_findings` (around lines 2890+):

```python
def _run_full_validation(
    workflow_ir: dict[str, Any],
    *,
    workflow_path: str | None,
) -> list[Diagnostic]:
    """Run the unified ``WorkflowValidator.validate()`` 10-step pipeline.

    Replaces ``_cache_validator_findings``. Same role (validator-side findings
    for the analyzer) but runs the SAME pipeline used by ``pflow run``,
    ``--validate-only``, and ``pflow save`` — instead of the cache-only subset.

    Surfaces ALL validator findings (not just cache.*): typos in node params,
    broken templates, undeclared sub-workflow inputs, etc. Cache-related
    diagnostics still flow through their existing catalog IDs and render in
    the analyzer's cache sections; non-cache ERRORs flow into
    ``blocking_errors``; non-cache WARNINGs are filtered to cache-related only
    in ``view_helpers.build_recommended_actions`` (preserves analyze-cache's
    domain focus).

    Uses dummy parameters only (matches ``runner.validate()`` and
    ``save_service`` patterns). Real CLI parameters are passed to the analyzer
    for analytical passes via the existing ``parameters`` argument; they are
    NOT merged into ``extracted_params`` here, to avoid making analyze-cache
    *stricter* than ``--validate-only`` for parameterized template references
    into nested types.

    Best-effort contract on producer-bug exceptions: same as the prior adapter,
    but elevated visibility. Producer bugs in the 10-step pipeline raise rare
    `Exception`s; rather than silently returning ``[]`` and reporting "0
    opportunities" (which would erode agent trust), we log at WARNING and
    surface a structured Diagnostic so the user sees that validation failed.

    For inline workflows where ``workflow_path`` is a synthesized
    ``ir-hash:<md5>`` identifier (not a real path), pass ``workflow_file=None``
    to the validator so step 9's relative-path resolution doesn't silently
    resolve against CWD via ``Path("ir-hash:...").parent == Path(".")``.
    """
    inputs = workflow_ir.get("inputs") or {}
    validation_params = generate_dummy_parameters(inputs)
    # Intentionally NOT merging real `parameters` into validation_params. See
    # docstring; matches runner.validate() at runner.py:324-329 and
    # save_service.py:186-203.

    workflow_file: Path | None = None
    if workflow_path and not workflow_path.startswith("ir-hash:"):
        workflow_file = Path(workflow_path)

    try:
        diagnostics = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params=validation_params,
            workflow_file=workflow_file,
        )
    except Exception as e:
        # Producer bugs in the 10-step pipeline. Today's pre-Path-2 code
        # silently swallowed; under Path 2 the surface is 10x larger so we
        # surface a structured Diagnostic and log a warning.
        logger.warning(
            "WorkflowValidator.validate raised %s during analyze-cache; "
            "findings may be incomplete",
            type(e).__name__,
            exc_info=True,
        )
        return [
            Diagnostic(
                severity=Severity.WARNING,
                source="cache_analyzer",
                title="Validator Error",
                node_id=None,
                message=(
                    f"Validation pipeline failed during analyze-cache "
                    f"({type(e).__name__}). Cache analysis is best-effort; "
                    f"findings may be incomplete. Run `pflow run "
                    f"--validate-only <workflow>` to see the underlying error."
                ),
                context={
                    "category": "cache_analyzer",
                    "affected_workflow": workflow_path,
                    "exception_class": type(e).__name__,
                },
            )
        ]

    # Stamp affected_workflow on root-level diagnostics. Children are stamped
    # by validator.py::_stamp_affected_workflow inside step 9. Idempotent.
    enriched = []
    for diag in diagnostics:
        existing = dict(diag.context or {})
        current = existing.get("affected_workflow")
        if (not current or current == "<unknown>") and workflow_path:
            existing["affected_workflow"] = workflow_path
        enriched.append(replace(diag, context=existing))
    return enriched
```

#### 2f. Update the call site at line 649

Today reads:
```python
warnings.extend(_cache_validator_findings(workflow_ir, workflow_path=lookup_path))
```

Replace with:
```python
warnings.extend(_run_full_validation(workflow_ir, workflow_path=lookup_path))
```

`lookup_path` is computed at line 502 (`workflow_path or synthesize_inline_workflow_id(workflow_ir)`). For inline workflows it carries `"ir-hash:<md5>"`; the helper detects this and skips wrapping in `Path()`.

#### 2g. Extend `RecommendedAction` dataclass

Locate `RecommendedAction` (around line 187). Today it has `rank`, `warning_id`, `node_id`, `estimated_savings_usd`, `scope_workflow`, `message`, `headline`. Add:

```python
@dataclass(frozen=True)
class RecommendedAction:
    # ... existing fields ...
    suggestions: tuple[str, ...] = ()
```

Use `tuple` (frozen-friendly) and default `()` (matches `frozen=True` semantics; mirrors how the codebase already uses `field(default_factory=tuple)` patterns elsewhere — verify against existing dataclasses in this file).

#### 2h. Make `actionable_opportunities` and `blocking_errors` counts cache-focused

Locate `_build_summary` (around line 3822). Current logic (around line 3887):

```python
blocking_errors = sum(1 for d in warnings if d.severity == Severity.ERROR)
warnings_count  = sum(1 for d in warnings if d.severity == Severity.WARNING)
info_count      = sum(1 for d in warnings if d.severity == Severity.INFO)
actionable      = warnings_count + info_count
```

Replace the count site so cache-focused signals stay cache-focused:

```python
def _is_cache_focused(d: Diagnostic) -> bool:
    """Whether this diagnostic represents a cache-domain finding.

    Used by summary aggregates that drive the dry-run nudge ("N cache
    opportunities") and by the partial-trace filter. The renderer surfaces
    non-cache findings via blocking_errors / recommended_actions paths
    independently — this gate is purely about which findings count toward
    cache-domain headline numbers.
    """
    if d.id and d.id in CACHE_WARNING_CATALOG:
        return True
    # Un-IDed cache reference errors from data_flow.py:_validate_cache_block
    # carry context["path"] under cache.* or .prompt_cache. Mirrors the
    # historical _is_cache_related_diagnostic (now deleted from the validator
    # delegation path but resurrected here purely for derived-count semantics).
    path = (d.context or {}).get("path")
    if isinstance(path, str) and (path.startswith("cache.") or ".prompt_cache" in path):
        return True
    return False

cache_focused = [d for d in warnings if _is_cache_focused(d)]
blocking_errors = sum(1 for d in cache_focused if d.severity == Severity.ERROR)
warnings_count = sum(1 for d in cache_focused if d.severity == Severity.WARNING)
info_count = sum(1 for d in cache_focused if d.severity == Severity.INFO)
actionable = warnings_count + info_count
```

This preserves the dry-run nudge contract (`pflow run --dry-run` says "N cache opportunities") while letting non-cache findings flow through to the renderer's separate `blocking_errors[]` / `recommended_actions[]` views.

#### 2i. Update `_warnings_for_partial_trace` to be cache-focused

Locate `_warnings_for_partial_trace` (around line 4006-4008). Current:

```python
def _warnings_for_partial_trace(warnings: list[Diagnostic]) -> list[Diagnostic]:
    """Keep validity errors, suppress optimization advice for partial traces."""
    return [w for w in warnings if w.severity == Severity.ERROR]
```

Replace with:

```python
def _warnings_for_partial_trace(warnings: list[Diagnostic]) -> list[Diagnostic]:
    """Keep cache-related ERRORs, suppress optimization advice for partial traces.

    Pre-unification this function was severity-only because today's
    `_cache_validator_findings` upstream filter ensured every warning was
    cache-related. Under Path 2 (unified validator pipeline) non-cache
    validator ERRORs (cycles, broken templates) flow through `analysis.warnings`,
    so this filter must explicitly preserve cache focus.

    Non-cache ERRORs still surface through the analyzer's `blocking_errors`
    list (pre-partial-trace-filter aggregation) — the partial-trace filter is
    only about what stays in `analysis.warnings` for renderer display.
    """
    return [w for w in warnings if w.severity == Severity.ERROR and _is_cache_focused(w)]
```

(Reuses `_is_cache_focused` from 2h.)

### Change 3 — `view_helpers.py`: thread `suggestions`/`message` + filter recommended_actions

**File**: `src/pflow/core/cache_analysis/view_helpers.py`

#### 3a. Update `_build_actions` to thread suggestions and message

Locate `_build_actions` (around lines 100-152). Find the `RecommendedAction(...)` constructor call. Add the field:

```python
RecommendedAction(
    rank=rank,
    warning_id=d.id or "",
    node_id=d.node_id or "",
    estimated_savings_usd=estimated_savings_usd,
    scope_workflow=scope_workflow,
    message=d.message,
    headline=resolve_headline_for(d),
    suggestions=tuple(d.suggestions) if d.suggestions else (),  # NEW
)
```

#### 3b. Filter `build_recommended_actions` to cache-focused warnings

Locate `build_recommended_actions` (around line 96). Current:

```python
def build_recommended_actions(warnings):
    eligible = [
        d for d in warnings
        if d.severity != Severity.ERROR and not is_cross_workflow_alignment(d)
    ]
    return _build_actions(eligible)
```

Update to filter advisory findings to cache-related only:

```python
def build_recommended_actions(warnings):
    """Build advisory action list — cache-domain only.

    ERRORs are always universal (typos / broken structure block execution).
    But advisory findings ("Recommended actions") are scoped to analyze-cache's
    domain (provider prompt cache). Memoization-cache lint warnings (the step 10
    `_warn_inputless_shell_nodes` warning), template path-validation soft warnings,
    and other non-cache advisory findings belong to other CLI surfaces; they don't
    fit the "Recommended actions" section header which says "Each item below is
    a fix or cache-optimization opportunity."

    Per `cache_analysis/CLAUDE.md` "Disambiguation": memoization and provider
    prompt cache are independent concepts. Conflating them in advisory output
    confuses agents.
    """
    eligible = [
        d for d in warnings
        if d.severity != Severity.ERROR
        and not is_cross_workflow_alignment(d)
        and _is_cache_focused_for_advisory(d)
    ]
    return _build_actions(eligible)


def _is_cache_focused_for_advisory(d: Diagnostic) -> bool:
    """Mirror of _is_cache_focused (in analyze.py) for the advisory-list filter.

    Defined here to avoid circular import (analyze.py imports view_helpers,
    not vice versa). Future cleanup: extract to a shared helper module if a
    third site needs the same predicate.
    """
    if d.id and d.id.startswith("cache."):
        return True
    if d.id and d.id == "llm.thinking-temperature-mismatch":
        return True  # historically allowed in the cache catalog
    path = (d.context or {}).get("path")
    if isinstance(path, str) and (path.startswith("cache.") or ".prompt_cache" in path):
        return True
    return False
```

`build_blocking_errors` is UNCHANGED — ERROR-severity findings broaden universally as the design resolution states. A typo, a broken template, a cycle — these all block execution and the agent should see them.

### Change 4 — `render_json.py`: emit `message` and `suggestions`

**File**: `src/pflow/core/cache_analysis/render_json.py`

Locate `_action_to_dict` (around line 166-177). Today emits only: `rank`, `warning_id`, `node_id`, `estimated_savings_usd`, `scope_workflow`. Replace with:

```python
def _action_to_dict(action: RecommendedAction) -> dict[str, Any]:
    return {
        "rank": action.rank,
        "warning_id": action.warning_id,
        "node_id": action.node_id,
        "estimated_savings_usd": action.estimated_savings_usd,
        "scope_workflow": action.scope_workflow,
        "message": action.message,                                 # NEW
        "suggestions": list(action.suggestions) if action.suggestions else [],  # NEW
    }
```

`message` was always available in the dataclass but never serialized. `suggestions` is the new field from Change 2g. Empty list (not `null`) for absent suggestions — matches the rest of the JSON shape's "present-empty over absent-null" convention (see CLAUDE.md "Honest unmeasurable convention" — distinct from cost data; here we're indicating "no suggestions" which is structurally different from "unavailable").

### Change 5 — `render_text.py`: render suggestions; update intro text

**File**: `src/pflow/core/cache_analysis/render_text.py`

#### 5a. Render suggestions in `_render_action_list`

Locate `_render_action_list` (around lines 596-619+). Find the loop that renders each action's title, message, and savings. After the message rendering, add:

```python
if action.suggestions:
    for suggestion in action.suggestions:
        lines.append(f"     → {suggestion}")
```

(Use `→` to match the existing did-you-mean convention from `format_diagnostic` in `diagnostic_render.py` — verify the exact glyph during implementation.)

#### 5b. Update Recommended actions section intro

Locate the `## Recommended actions` section header rendering (search for `"Recommended actions"` or `"ordered by impact"` in render_text.py). Today's intro reads roughly:

```
## Recommended actions (ordered by impact)

  Each item below is one edit that unlocks LLM-provider caching.
  Declared values are sent once and reused at 0.1× input cost.
```

Update to:

```
## Recommended actions (ordered by impact)

  Each item below is a cache-optimization opportunity for this workflow.
  Declared values are sent once and reused at 0.1× input cost.
```

The wording is slightly tightened to acknowledge that this section is scoped to cache opportunities (after Change 3's filter). Non-cache validator findings flow to `blocking_errors` (errors that block execution) — they don't appear in this section.

### Change 6 — Fix `_MINIMAL_VALID_WORKFLOW` test fixture

**File**: `tests/test_cli/test_analyze_cache.py`

Locate `_MINIMAL_VALID_WORKFLOW` (around lines 33-49). Today the fixture has a shell node with `command: "echo hello"` and no `cache:` annotation. Step 10 of `WorkflowValidator.validate()` (`_warn_inputless_shell_nodes`) emits a warning for shell nodes with static-literal commands and no `cache: false` annotation.

This warning is filtered OUT of `build_recommended_actions` by Change 3 (memoization-cache concern, not provider prompt cache). So it doesn't surface in `recommended_actions`, but it DOES land in `analysis.warnings`. Tests that assert `len(analysis.warnings) == 0` would break.

**Fix**: Add `- cache: false` to the shell node in `_MINIMAL_VALID_WORKFLOW`. This both silences the warning AND makes the fixture's intent explicit (test fixtures should be exemplary).

```python
_MINIMAL_VALID_WORKFLOW = """\
# Minimal Valid Workflow

A minimal workflow used as the happy-path control.

## Steps

### echo

Print a hello.

- type: shell
- command: echo hello
- cache: false
"""
```

(Adjust to match the exact existing fixture format.)

The 6 affected tests (lines 271, 282, 546, 562, 572, 596) should then pass without further modification.

### Change 7 — Invert the negative-control test

**File**: `tests/test_core/test_cache_analysis_analyze.py`

Locate `test_analyze_filters_non_cache_data_flow_diagnostics` (around lines 1338–1370). Today asserts:

```python
assert all(d.id and d.id.startswith("cache.") for d in result.warnings)
```

Replace with the new contract:

```python
def test_analyze_surfaces_non_cache_validator_diagnostics():
    """Validator findings outside the cache catalog now surface in analyze() output.

    Locks the Path 2 unification: pflow analyze-cache uses the same validator
    pipeline as pflow run / --validate-only / save. Non-cache ERRORs (typos,
    broken templates, etc.) flow through `blocking_errors`. Cache-domain
    advisory findings (warnings) stay in `recommended_actions`; non-cache
    advisory findings are filtered out by build_recommended_actions to
    preserve analyze-cache's cache-domain focus.

    Mutation contract: reverting analyze.py to call validate_data_flow() with
    the catalog-membership filter makes this test fail (no Unknown parameter
    diagnostic surfaces).
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "deep-think",
                "type": "llm",
                "params": {
                    "prompt": "Think.",
                    "model": "anthropic/claude-opus-4-7",
                    "thinking_effort": "high",  # typo; canonical is reasoning_effort
                },
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir)

    # The unknown-param diagnostic should surface in result.warnings (with
    # severity=ERROR and the actionable suggestion preserved).
    unknown_param = [
        d for d in result.warnings
        if d.message and "thinking_effort" in d.message
    ]
    assert len(unknown_param) == 1, (
        f"Expected unknown-param diagnostic; got: "
        f"{[(d.severity, d.message) for d in result.warnings]}"
    )
    diag = unknown_param[0]
    assert diag.severity == Severity.ERROR
    assert any(
        "reasoning_effort" in s for s in (diag.suggestions or [])
    ), f"Expected 'reasoning_effort' suggestion; got: {diag.suggestions}"
```

### Change 8 — Update stale mutation-contract docstrings

**File**: `tests/test_core/test_cache_analysis_per_id_emission.py`

Locate the two test docstrings that reference deleted helpers (around lines 3535, 3542, 3576). Each contains text like `"the catalog-membership filter at _cache_validator_findings"` or `"revert _is_cache_related_diagnostic..."`.

The test bodies still assert the right behavior (un-IDed cache errors surface), but the mutation contracts in the docstrings name the wrong code path. Update the docstrings to point at the new helper:

```
Mutation contract: reverting analyze.py::_run_full_validation to call
validate_data_flow with the cache-only filter makes this test fail.
```

(Adjust each docstring individually to match its specific scenario.)

### Change 9 — Add architectural parity sentinel test

**File**: `tests/test_core/test_cache_analysis_analyze.py` (new test, append to the file)

```python
def test_analyze_diagnostics_match_workflow_validator_for_thinking_effort():
    """Architectural parity: analyze-cache and WorkflowValidator surface the
    same ERROR diagnostics for the same workflow.

    This pin guards future drift if someone adds a new validation step but
    only wires it into one of the entry points. The unification claim is:
    `pflow analyze-cache` runs the SAME validator as `pflow run` /
    `--validate-only` / `pflow save`.

    Mutation contract: removing _run_full_validation's call to
    WorkflowValidator.validate() (or restoring _cache_validator_findings's
    cache-only filter) makes this test fail with the validator's diagnostics
    being a strict superset of the analyzer's.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "deep-think",
                "type": "llm",
                "params": {
                    "prompt": "Think.",
                    "model": "anthropic/claude-opus-4-7",
                    "thinking_effort": "high",
                },
            }
        ],
        "edges": [],
    }

    # Direct validator output
    inputs = workflow_ir.get("inputs") or {}
    dummy = generate_dummy_parameters(inputs)
    validator_diags = WorkflowValidator.validate(
        workflow_ir=workflow_ir, extracted_params=dummy
    )
    validator_errors = {
        d.message for d in validator_diags if d.severity == Severity.ERROR
    }

    # Analyzer output
    analyzer_diags = analyze(workflow_ir).warnings
    analyzer_errors = {
        d.message for d in analyzer_diags if d.severity == Severity.ERROR
    }

    # Validator ERRORs must all surface in analyzer (cross-workflow scoping
    # may add affected_workflow context but doesn't change message text).
    assert validator_errors.issubset(analyzer_errors), (
        f"Validator ERRORs not in analyzer output. "
        f"Missing: {validator_errors - analyzer_errors}"
    )
```

### Change 10 — Update `cache_analysis/CLAUDE.md`

**File**: `src/pflow/core/cache_analysis/CLAUDE.md`

Locate the "Validator delegation" section. Replace with:

```markdown
## Validator delegation

`pflow analyze-cache` runs the same `WorkflowValidator.validate()` 10-step
pipeline as `pflow run`, `--validate-only`, and `pflow save`. There is no
separate "cache-only" validation subset.

**Domain focus is preserved** at the renderer/aggregator boundary, not at
the pipeline boundary:

- ERRORs broaden universally — typos and broken structure block execution,
  every CLI surface must show them. Surfaced via `blocking_errors[]`.
- WARNINGs stay cache-scoped — `build_recommended_actions` filters
  WARNING-severity findings to cache-related only (catalog-IDed or
  cache-pathed). Memoization-cache lint warnings, template-path advisory
  warnings, and other non-cache advisory findings flow through
  `analysis.warnings` but don't surface in the "Recommended actions" section
  (which is scoped to cache opportunities).
- Derived counts stay cache-focused — `summary.actionable_opportunities`
  (drives the `--dry-run` nudge text) and `summary.blocking_errors` (the
  cache-blocking-errors count) are computed over a cache-focused subset.

**`_run_full_validation`** in `analyze.py` is the seam — it calls the unified
validator with dummy-padded `extracted_params` (matching `runner.validate()`
and `save_service` patterns) and stamps `context['affected_workflow']` on
root-level diagnostics for cross-workflow scoping.

**Per-child scoping** is handled by the validator's step 9 itself —
`_stamp_affected_workflow` in `validator.py` enriches each child diagnostic
with `affected_workflow=child_path` at the function boundary in
`_validate_one_child_call` (covering all 4 emission sites: load errors, file
ref errors, required-input errors, recursive child diagnostics + parser
warnings).

**Producer-bug exception contract**: `_run_full_validation` wraps
`WorkflowValidator.validate()` in `try/except Exception` (matching today's
adapter contract). On exception, it logs at WARNING severity AND surfaces a
structured Diagnostic so users see when validation crashed. Today's silent
swallow gave the analyzer cover for one narrow validator (`validate_data_flow`);
the wider 10-step surface needs visible failure semantics.

| Warning ID | Defined in | Severity |
|---|---|---|
| `cache.invalid-on-non-llm` | `data_flow.py::_validate_cache_block` | ERROR |
| `cache.order-mismatch` | `data_flow.py::_validate_cache_block` | ERROR |
| `cache.unused-chunk` | `data_flow.py::_validate_cache_block` | WARNING |
| `cache.prompt-body-duplicates-cache` | `data_flow.py::_validate_cache_block` | ERROR |
| `cache.prompt-body-shadows-cache` | `data_flow.py::_validate_cache_block` | WARNING |
| `llm.thinking-temperature-mismatch` | `data_flow.py::_validate_thinking_temperature_compatibility` | ERROR |

Plus four un-IDed validation diagnostics in `data_flow.py` lines 816-934
(`_make_duplicate_chunk_diagnostic`, `_make_undeclared_chunk_diagnostic`,
`_make_chunk_resolution_diagnostic`, `_make_batch_scoped_rejection_diagnostic`)
that surface as ERROR severity with `context.path` under `cache.` or
`.prompt_cache`. Per the `_is_cache_focused` predicate in `analyze.py` and
`view_helpers.py`, these are treated as cache-domain by the aggregator.
```

### Change 11 — Update `core/workflow/CLAUDE.md`

**File**: `src/pflow/core/workflow/CLAUDE.md` (line 137)

Today line 137 references "the `_cache_validator_findings` adapter in
`core/cache_analysis/analyze.py`". Update to:

```
Both `WorkflowValidator` and the compile-time validator call
`validate_data_flow()`, so cache rules run at both entry points without
duplication. `pflow analyze-cache` consumes the same producer through the
unified `WorkflowValidator.validate()` pipeline (since Task 159 finalization
removed the cache-only adapter) — see `cache_analysis/CLAUDE.md` "Validator
delegation".
```

### Change 12 — Update `compile_validation.py` docstring

**File**: `src/pflow/runtime/compilation/compile_validation.py` (line 118)

Find the docstring reference to `_cache_validator_findings` (around line 118).
Update from:
```
... call sites: validator.py:278, analyze.py:_cache_validator_findings ...
```
To:
```
... call sites: validator.py:278, analyze.py:_run_full_validation (calls
WorkflowValidator.validate end-to-end since Task 159 finalization) ...
```

### Change 13 — Update MCP `analyze_cache` tool docstring

**File**: `src/pflow/mcp_server/tools/execution_tools.py`

Locate the `analyze_cache` docstring (around lines 355-525). Find the "Closed
catalog of warning IDs" paragraph (around line 424). Update to reflect the
broader diagnostic surface AND the provenance prefix format:

```markdown
**Validator finding parity**: `analyze_cache` runs the same 10-step
`WorkflowValidator` pipeline as `pflow run`, `--validate-only`, and
`pflow save`. ERROR findings appear in `blocking_errors[]` (ranked,
deduplicated, with `message` and `suggestions` preserved) and in `warnings[]`
(with `severity: "error"`).

New ERROR finding categories agents may now see (in addition to the cache
catalog above):

- IR schema errors (missing required fields, bad types)
- Stdin/stdout cardinality violations (>1 input/output marked stdin/stdout)
- Forward references and execution-order cycles
- Unresolvable `${...}` template variables
- Unknown node types (with `similar_names` in context for fuzzy matches)
- Unknown node parameters (with `suggestions: ["Did you mean 'X'?"]`)
- Sub-workflow input contract violations (missing required, undeclared extras)

WARNING-severity findings: only cache-domain WARNINGs flow into
`recommended_actions[]` (memoization-cache lint warnings and template-path
advisory warnings are filtered out — they belong to other CLI surfaces). All
WARNINGs still appear in raw `warnings[]` if needed.

**Sub-workflow provenance**: child-workflow findings have their `message`
prefixed with `In step '<parent_step_id>' sub-workflow: ` per nesting level.
The leaf workflow path is in each diagnostic's `context.affected_workflow`.
The `node_id` on the diagnostic is the deepest-nested node id (or the
parent step_id for un-IDed validators that bubbled up via
`_add_child_provenance`).

**`warnings[].id` shape**: was a closed catalog of 21 entries pre-Task-159
finalization. Now the value is **either** one of the 21 cache catalog entries,
**or** `None` (un-IDed validator findings — typos, schema errors, etc.). Use
`severity` for blocking-vs-advisory dispatch; use `id in CACHE_WARNING_CATALOG`
for cache-vs-other dispatch.
```

---

## Verification

### Pre-flight

```bash
# Confirm clean working tree
git status

# Confirm baseline test count (per task-review.md: 6342 passing on default suite)
make test
```

### After implementation

**1. Test suite passes** (allow for the new test plus updates):
```bash
make test
make check  # ruff + ruff-format + mypy + deptry
```
Expected delta: −1 inverted test + 1 new architectural parity test + ~3 other test/fixture updates per Changes 6-9. Total: ~6342 +/- 5.

**2. The triggering bug is closed AND the suggestion is delivered**:
```bash
cat > /tmp/test_thinking_effort.pflow.md << 'EOF'
# Test thinking_effort drop

## Inputs
### article
Article.
- type: string
- required: true

## Steps
### deep-think
- type: llm
- model: anthropic/claude-opus-4-7
- thinking_effort: high
- temperature: 0.3
```prompt
Think: ${article}
```

## Outputs
### result
- source: ${deep-think.response}
- type: string
EOF

# Text mode — should show "Did you mean 'reasoning_effort'?"
uv run pflow analyze-cache /tmp/test_thinking_effort.pflow.md --no-trace-autoload

# JSON mode — blocking_errors[0] should have message + suggestions populated
uv run pflow analyze-cache /tmp/test_thinking_effort.pflow.md --format=json --no-trace-autoload | jq '.blocking_errors[0]'
```

Expected JSON output structure for `blocking_errors[0]`:
```json
{
  "rank": 1,
  "warning_id": "",
  "node_id": "deep-think",
  "estimated_savings_usd": null,
  "scope_workflow": "/tmp/test_thinking_effort.pflow.md",
  "message": "Unknown parameter 'thinking_effort' on node 'deep-think' (type: llm).",
  "suggestions": ["Did you mean 'reasoning_effort'?"]
}
```

The `suggestions` field is the load-bearing assertion of the bug fix.

**3. Cache validation findings still flow correctly**:
```bash
uv run pflow analyze-cache .taskmaster/tasks/task_159/baseline/04-warning-catalog/01-cache.order-mismatch/workflow.pflow.md --no-trace-autoload
```
Expected: `blocking_errors` includes `cache.order-mismatch` (unchanged).

**4. Architectural parity sentinel passes**:
```bash
uv run pytest tests/test_core/test_cache_analysis_analyze.py::test_analyze_diagnostics_match_workflow_validator_for_thinking_effort -xvs
```

**5. Baseline cases still match oracle**:
```bash
cd .taskmaster/tasks/task_159/baseline
./verify.sh
```
Expected: clean pass for all 63 cases. If 1-3 cases mutate (residual risk on cross-workflow cases 05/10/11), inspect each, confirm correctness, regenerate via `./regenerate.sh <case-dir>`, commit alongside.

**6. MCP parity** (run via Claude Code's MCP integration or equivalent):
- Call MCP `analyze_cache` with the `thinking_effort` workflow.
- Assert `blocking_errors[0].suggestions == ["Did you mean 'reasoning_effort'?"]`.

**7. Real-world workflow** (lyrics-generator from baseline):
```bash
uv run pflow analyze-cache .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md --no-trace-autoload
```
Expected: pre-existing `cache.below-min-tokens` warnings still appear. No new noise from non-cache validator findings (since the workflow tree is structurally clean per Searcher B's verification).

**8. Test churn check** (pre-merge guard):
```bash
# Find any test asserting closed-form Diagnostic.context keysets that the new
# affected_workflow stamp would break:
rg -l "result\.warnings|\.warnings\s*\[|len\(.*\.warnings|d\.context\s*==" tests/test_core/test_cache_analysis_*.py tests/test_cli/test_analyze_cache.py
```
For each match, read the assertion. If it does closed-form equality on `.context`, update to use `.context.get(...)` checks for specific keys.

**9. Mutation contract verification for the inverted test**:
```bash
# After implementing all changes:
git stash  # restore old behavior
uv run pytest tests/test_core/test_cache_analysis_analyze.py::test_analyze_surfaces_non_cache_validator_diagnostics
# Should FAIL (old behavior = filter to cache-only)
git stash pop
uv run pytest tests/test_core/test_cache_analysis_analyze.py::test_analyze_surfaces_non_cache_validator_diagnostics
# Should PASS
```

---

## Edge Cases Documented for Implementing Agent

### Provenance message format

Child cache structural errors arrive with messages like:
```
"In step 'render-summary' sub-workflow: Node 'summarize' lists cache chunk 'a' before 'b' but prompt_cache lists [b, a]"
```
Consistent with `pflow run` sub-workflow error display (already standard pflow UX).

### Inline workflows (`workflow_path=None`)

`analyze()` computes `lookup_path = workflow_path or synthesize_inline_workflow_id(workflow_ir)` (line 502). For inline workflows, `lookup_path` is `"ir-hash:<md5>"`. `_run_full_validation` detects the `ir-hash:` prefix and passes `workflow_file=None` to the validator (avoids `Path("ir-hash:...").parent == Path(".")` silently resolving against CWD).

### Renderer per-call table for child cache diagnostics

`render_text.py::_warnings_by_row_key` filters on `node_id is not None AND id is not None`:
- **Catalog-IDed child diagnostics** (e.g., `cache.order-mismatch` emitted with `node_id="summarize"`): preserved through `_add_child_provenance` (preserves `d.node_id` when set). Row key `(child_path, "summarize")` → correct attribution.
- **Un-IDed child cache reference errors** (4 emitters in data_flow.py:816-934): no `id`, filtered out of per-call table. Surface in `blocking_errors` with provenance-wrapped messages — agent sees "In step 'X' sub-workflow: <error>" which is informative.

### `_add_child_provenance` argument signature

Verify during implementation: actual call uses `_add_child_provenance(diagnostics, node_id, ref_label)` (3 positional args; variable is `node_id`, not `step_id`). The Change 1 helper (`_stamp_affected_workflow`) is independent of `_add_child_provenance`'s signature — it's called at function exit, after all wrapping has happened.

### Test fixture audit before implementation

Before starting Changes 6 and 7, run the test churn check (Verification step 8). If any test does `assert d.context == {...}` (closed-form equality), it WILL break under Path 2's `affected_workflow` stamping. Update those tests to use specific-key assertions (`assert d.context.get("path") == "..."`).

---

## Out of Scope (Follow-ups to file as separate issues)

1. **Shared `_ir_cache` between `WorkflowValidator._validate_sub_workflows` and `cache_analysis.cross_workflow.walk_cross_workflow`**. Eliminates ~16 wasted sub-workflow file reads per analyze-cache invocation (today's pre-existing inefficiency; under Path 2 the cost stays the same since we don't add a separate validate-then-analyze pass). Performance optimization, not correctness.

2. **Catalog IDs for the 4 un-IDed cache emitters** in `data_flow.py:816-934`. Per spec DD#27/29 they were intentionally left un-IDed; promoting them requires design review. Cosmetic improvement (cleaner per-call table rendering) but not load-bearing.

3. **`pre_validated_diagnostics` parameter on `analyze()`** to optimize `pflow run --dry-run`'s second validation pass. Today's flow: runner._validate runs WorkflowValidator (validates), then _build_cache_nudge calls analyze() which runs WorkflowValidator AGAIN. Cost: ~10ms compute + up to 16 sub-workflow file reads on a complex tree. Acceptable for v1; addressable as follow-up if profiling shows it matters.

4. **Path() Windows compatibility** for synthetic identifiers and file paths with reserved characters. The Change 2e helper guards against `ir-hash:` prefix, but other Windows-reserved characters in workflow paths could still cause issues. Not a regression from today; pflow Windows support is generally limited (per Task 116 backlog).

5. **Update `tests/shared/diagnostic_helpers.py`** to optionally normalize away `affected_workflow` from comparison contexts — used by 30+ test files. Defensive cleanup if any test breaks under Path 2's stamping.

---

## Reference Materials

- **Spec**: `.taskmaster/tasks/task_159/task-159.md`
- **Task review**: `.taskmaster/tasks/task_159/task-review.md`
- **Baseline findings**: `.taskmaster/tasks/task_159/baseline/FINDINGS.md`
- **Verification report**: `scratchpads/task159-baseline-findings-report.md` (reframed: `thinking_effort` is a `pflow analyze-cache` gap, not a runtime gap)
- **Architecture context**: `src/pflow/core/cache_analysis/CLAUDE.md`, `src/pflow/core/workflow/CLAUDE.md`
- **Code review feedback** (folded into this plan): findings from review-plan, review-validation-consistency, review-impact-completeness, review-silent-failures, review-agent-ux. Cross-confirmed by 4 verification searchers on the highest-impact findings.

## Critical file paths (for implementing agent)

```
src/pflow/core/workflow/validator.py                — Add module-level replace import; add _stamp_affected_workflow; call at function boundary in _validate_one_child_call (Change 1)
src/pflow/core/cache_analysis/analyze.py            — Delete 2 helpers; add _run_full_validation; extend RecommendedAction; add _is_cache_focused; update partial-trace filter; update summary aggregator (Change 2)
src/pflow/core/cache_analysis/view_helpers.py       — Thread message+suggestions through _build_actions; filter recommended_actions to cache-focused (Change 3)
src/pflow/core/cache_analysis/render_json.py        — Emit message+suggestions in _action_to_dict (Change 4)
src/pflow/core/cache_analysis/render_text.py        — Render suggestions in _render_action_list; update intro text (Change 5)
src/pflow/core/validation_utils.py                  — Read-only (consume generate_dummy_parameters)
src/pflow/core/workflow/data_flow.py                — Read-only (no longer imported by analyze.py)

tests/test_cli/test_analyze_cache.py                — Fix _MINIMAL_VALID_WORKFLOW fixture (Change 6)
tests/test_core/test_cache_analysis_analyze.py      — Invert one test; add architectural parity sentinel (Changes 7, 9)
tests/test_core/test_cache_analysis_per_id_emission.py — Update 2 mutation-contract docstrings (Change 8)

src/pflow/core/cache_analysis/CLAUDE.md             — Rewrite "Validator delegation" section (Change 10)
src/pflow/core/workflow/CLAUDE.md                   — Update line 137 reference (Change 11)
src/pflow/runtime/compilation/compile_validation.py — Update line 118 docstring (Change 12)
src/pflow/mcp_server/tools/execution_tools.py       — Update analyze_cache docstring (Change 13)
```
