# Task 166 Review: Declarative Stateful Loop Primitive (`carry:` + `until:`)

## Metadata

- **Implementation Date:** 2026-06-05
- **Branch:** `feat/declarative-stateful-loop` (staged; not yet committed/PR'd at review time)
- **Provenance:** Plan authored + implementation reviewed + architectural refactor performed by Claude;
  the bulk of the feature code was first written by Codex, then reviewed against the plan, quality-gated,
  and refactored. Every claim below was verified against the actual staged source, not the plan.
- **Companion docs (read for *why*):** `implementation/implementation-plan.md` (the spec, with `[review-fix]`
  markers), `implementation/progress-log.md` (the journey — Phases 0–9, including the design convergence,
  the run-proven substrate spikes, the plan review, and the post-implementation refactor).

## Executive Summary

Extended the existing `loop:` node *modifier* with **carried state** (`carry:`) and a second
polarity keyword (`until:`), so stateful loops (tournament, evaluator-optimizer, validate-fix, poll)
are expressible in ONE node — no sibling-counter / backward-edge workaround. The mechanism is a thin
surface over the already-verified loop self-reference substrate: on iteration N>1 the node's `inputs:`
are overridden by the carry references **inside `plan_node`** (so resolution, config-hash, and
execution stay consistent), with a strict runtime guard that makes an unresolved carried input fail
loud in any template-resolution mode.

## Implementation Overview

### What Was Built

- **`carry:`** — a map `{ body_input_name: ${this-loop-node.output} }` on the `loop:` block. Round 1
  uses the node's normal `inputs:` (the *seed*); from round 2 on, `carry:` overrides the carried keys
  with the loop node's prior output. Works uniformly across ALL body types (code, workflow, llm, shell).
- **`until:`** — sibling of `while:`, mutually exclusive, exactly-one-required. `while: X` re-runs while
  X truthy; `until: X` re-runs while X falsy. Polarity-in-keyword kills the silent "poll until done →
  runs once and exits" bug.
- **Validation** across the two parity layers + a typed layer; a typo'd carry output is a validate-time
  error (precise for workflow/code bodies), not a silent stale-state run.

### Deviations from the plan (both are load-bearing — do not "simplify" away)

1. **Compiler builds a `TemplateConfig` for carry loops even when all round-1 seeds are literals.**
   The original compiler set `template_config = None` when no param contained `${...}`. A carry loop
   with an all-literal seed (e.g. `inputs: { state: 0 }`) would then never enter the resolution path,
   making the carry override **silently inert**. Fixed in `compiler._create_node_and_config`:
   `template_config` is built when `template_params OR (loop_config and loop_config.carry)`. This was a
   genuine gap in the plan; the implementer caught it.
2. **The carry override lives in `plan_node`, NOT in `engine._execute_node`.** The plan (and the first
   implementation) put it in the engine. It was relocated during review — see *Architectural Decisions*.
   A future agent reading the code will find the override in `plan_node` → `carry_effective_config`.

## Files Modified/Created

### Core Changes

- `src/pflow/runtime/engine/types.py` — `LoopConfig` gains `until_template: Optional[str]` and
  `carry: dict[str,str]`, appended *after* the existing fields; `while_template` is now `Optional`
  (was required). **Field order matters** — appending keeps positional construction sites working.
- `src/pflow/core/ir_schema.py` — `LOOP_CONFIG_SCHEMA` adds `until` (same `^\$\{.+\}$` shape as `while`)
  and `carry` (object → `${...}`-pattern string values); `required` relaxed to `[]`;
  `additionalProperties: False` kept (it is the *only* thing catching a `whlie:` typo).
- `src/pflow/runtime/compilation/compiler.py` — `_build_loop_config` split into `_extract_loop_polarity`
  (calls shared `check_loop_polarity` → `CompilationError`) and `_extract_loop_carry` (dict/string-shape
  validation). Plus the `template_config`-for-carry fix above.
- `src/pflow/core/workflow/loop_validation.py` — **NEW**. One pure function `check_loop_polarity(loop_data)
  -> Optional[str]` shared by the compiler (run path) and `data_flow.py` (validate/save path) so the
  exactly-one-of rule can't drift between them.
- `src/pflow/runtime/engine/loop_control.py` — `apply_carry_overrides(template_config, carry)` (builds a
  FRESH `TemplateConfig`, never mutates), `is_carry_iteration(config, shared)` (the shared gate),
  `carry_effective_config(config, shared)` (the override entry point), and a restructured
  `evaluate_loop_condition(..., *, until=False)`.
- `src/pflow/runtime/engine/plan_node.py` — calls `carry_effective_config(config, shared)` at the top
  of `plan_node`, **before** `_resolve_for_plan` and `compute_config_hash`. THE override site.
- `src/pflow/runtime/engine/engine.py` — `_assert_carried_inputs_resolved(config, resolved_params)`
  (the permissive-mode strict guard, called after `plan_node` gated on `is_carry_iteration`); the
  `until`/`while`/neither branch in `_loop_should_reenter` (neither → `LoopConditionError`).
  *The engine no longer rebinds `config` or imports `dataclasses` — that was removed in the refactor.*
- `src/pflow/core/exceptions.py` — `LoopCarryError(PflowError)`. Mirrors `LoopConditionError`'s
  `to_diagnostics` shape exactly (`source="runtime"`, `context={"category":"validation","node_id":...}`)
  — keep it that way.
- `src/pflow/core/workflow/data_flow.py` — `_validate_loop_dict_rules` (polarity first, then cap, then
  carry shape), `_validate_loop_carry_shape` (carry-key-needs-seed + carry-value-self-ref), the `until`
  forward-ref walk in `_validate_node_params`, and `_make_loop_*` diagnostic builders.
- `src/pflow/runtime/template_validation/validator.py` — `_validate_loop_conditions` now iterates
  `("while","until")` with the field name threaded into BOTH the diagnostic `path` AND message text;
  `_validate_loop_carry_refs` (carry-output typo, namespaced-key-only, precise-only for workflow/code,
  gated to self-refs); `_validate_loop_carry_prompt_usage` (the llm/shell carried-but-unreferenced
  WARNING); `until` added to `_node_template_value_sources`.

### Docs/Examples

- `docs/how-it-works/loops.mdx` (NEW) + `docs/docs.json` nav entry; `src/pflow/guide/features/branching.md`
  (carry/until/seed, llm-shell caveat, until-absent + `--only` notes); `examples/core/stateful-loop-tournament.pflow.md`
  + `examples/core/stateful-loop-judge-round.pflow.md` (runnable demo; auto-schema-validated by
  `tests/test_docs/test_example_validation.py` via rglob).

### Test Files (critical ones flagged)

- `tests/test_integration/test_loop_config.py` — the big one. **CRITICAL:**
  `test_carry_tournament_threads_previous_survivors_into_next_round` (asserts the *carried content*
  per round — the only test that catches the dead-hook regression),
  `test_until_absent_runtime_source_continues_to_cap`,
  `test_permissive_mode_still_raises_for_unresolved_carry`,
  `test_no_carry_loop_without_inputs_does_not_trip_carry_guard` (mutation-verified gate guard),
  `test_carry_loop_error_action_archives_failed_iteration_for_on_error`.
- `tests/test_runtime/test_loop_control.py` — `evaluate_loop_condition` polarity matrix +
  `apply_carry_overrides` mutation-safety (identity asserts) + all-static→template move.
- `tests/test_core/test_loop_validation.py` — every diagnostic (polarity both/neither, seed, self-ref,
  bare-alias, typo, shell-unreferenced).
- `tests/test_integration/test_loop_carry_substrate.py` — REGRESSION-only: the manual `${self.x ?? seed}`
  substrate the feature is built on (proves it stays intact). Not carry-keyword coverage.

## Integration Points & Dependencies

### `plan_node` is now load-bearing for carry

`plan_node(node, config, shared)` is the single authority for template resolution + config hashing
(both the engine and the dry-run planner call it). The carry override is the FIRST thing `plan_node`
does. **Any future change to how carried inputs resolve MUST go here, not in `engine._execute_node`.**
The engine never reads `config.template_config` after `plan_node` on the loop path (the only post-plan
reads are in `_execute_single_node`, the batch-only callback that loop nodes never reach).

### The shared gate: `is_carry_iteration(config, shared)`

Used in TWO places — inside `carry_effective_config` (plan_node path, to apply the override) and in
`engine._execute_node` (to run the strict guard). Both must agree; that's why it's one function.
Signal = `config.loop_config.carry` non-empty AND `shared["__iteration__"] > 1`.

### Substrate reused (no new storage)

- `shared[node_id]` persists across loop iterations (issue #445 substrate); template context is
  `dict(shared)` with **no self-exclusion**, so a loop node reads its own prior output as
  `${node-id.field}`. Carry is a surface over this — it adds NO new shared-store key.
- `shared["__iteration__"]` (1-based, set by `loop_runtime_scope`) is the gate signal. The planner sets
  `iteration=1` for its single loop-body walk, which is why carry is inert during planning *for free*.
- `enforce_loop_guard` clears in-process completion + bypasses memo on revisit; `__loop_active__`
  suppresses memo reads during the loop. Carry inherits all of this unchanged.

### Validation layer split (know which layer can see what)

- `data_flow.py` (validate/save path, never compiles) — pure-IR shape: polarity, carry self-ref,
  carry-key-has-seed. NO access to `node_outputs`.
- `template_validation/validator.py` (Pass 10) — has `node_outputs`: typed `while`/`until` gate,
  carry-output typo check. Precision is type-dependent (declared `## Outputs` / code `result` → precise;
  llm/shell/dynamic-workflow → best-effort skip).
- `compiler.py` (run path) — mirrors the *shape* rules (polarity via `check_loop_polarity`, carry
  dict-shape). **Any new loop rule must be added to BOTH compiler and data_flow or workflows pass
  `pflow validate` and fail at runtime (or vice-versa).**

## Architectural Decisions & Tradeoffs

- **Override in `plan_node`, not the engine** (refactored during review). The invariant (runtime/CLAUDE.md)
  is "template resolution + cache-key MUST live in `plan_node`." First impl rebound `config` in
  `_execute_node`; that (a) flirted with the invariant and (b) needed a "don't wire into plan.py" caveat.
  Moving it into `plan_node` honored the invariant, deleted the engine `config` rebind + `dataclasses`
  import + a mypy-narrowing hack, and made the planner inert-by-construction (iteration=1). Net code
  removal. Engine/planner parity (`test_plan_drift`/`test_plan_classify`) still green.
- **Explicit `carry:` over implicit coupling / desugar-to-coalesce.** The override always uses the carry
  ref on round N>1, so an absent/typo'd carried output is loud. Desugaring to `${ref ?? seed}` would
  silently re-seed if the body omitted the field a round — the exact silent-coupling failure the task
  exists to kill.
- **Strict-on-carry-always** (`LoopCarryError`). Permissive template mode does NOT raise on an unresolved
  `${...}` — it leaves the literal string and DEGRADES. Carry is structural plumbing, so
  `_assert_carried_inputs_resolved` raises regardless of mode (via `contains_unresolved_template`).
- **`until` + absent source → CONTINUE (bounded by cap), not stop.** `evaluate_loop_condition` was
  restructured so absent/unresolved becomes a falsy *value* and polarity applies uniformly. Stop-on-absent
  for `until` would resurrect the "runs once and exits" bug for a body that omits the field while
  not-yet-done. Malformed-template and string-value still hard-stop/raise for both polarities.
- **`inputs:` is the seed; no `seed:` field. `${node-id.field}` refs; no `${body}`/`${acc}` reserved
  word. Loop stays a modifier; no `type: loop`.** (Settled in design; see plan.)

### Technical Debt / Not Done

- **Phase 7 acceptance gate not run** — fresh agents authoring tournament/poll/validate-fix from the new
  guide text (the plan's "real definition of done"). Guide + examples are in place to support it.
- No per-iteration carried-state trace field (would help a future flow view / Task 155). Out of scope.

## Testing Implementation

The make-or-break test is **content-asserting, not count-asserting**:
`test_carry_tournament_threads_previous_survivors_into_next_round` logs the contenders fed into the
child each round and asserts `rounds == [["ada","beck","cy","dee"], ["ada","cy"]]`. Under the dead-hook
bug (override never fires) round 2 would re-receive the seed and this fails. **Any future refactor of
the carry path must keep a content-asserting integration test — unit tests on `apply_carry_overrides`
pass even when the feature is end-to-end inert.**

`test_no_carry_loop_without_inputs_does_not_trip_carry_guard` was **mutation-tested**: dropping the
`carry` conjunct from `is_carry_iteration` makes it fail with the exact `LoopCarryError`; correct code
passes. This is the template for guarding the gate's specificity.

## Unexpected Discoveries / Gotchas

- **`_execute_single_node` is a dead end for loop nodes.** It is ONLY the batch per-item callback; since
  batch+loop are mutually exclusive, a loop node resolves via `_execute_node` → `plan_node`. The first
  implementation hooked the override into `_execute_single_node` — it would have *silently never fired*.
  This is the #1 trap for anyone touching per-node execution for loops. (A stale `engine/CLAUDE.md:160`
  claim led to it.)
- **`inputs:` is all-or-nothing across `static_params` / `template_params`** (`split_params`): if ANY
  input value has `${...}`, the WHOLE `inputs` dict goes to `template_params`; else all to `static_params`.
  `apply_carry_overrides` merges both, routes the result through `template_params`, and strips `inputs`
  from `static_params` (so resolved inputs win the `merged_params = {**static, **resolved}` merge).
- **All-literal-seed carry loops** need a `TemplateConfig` or the override is inert (see deviation #1).
- **Permissive mode silently passes the literal `"${...}"` string** on an unresolved ref — hence the
  strict guard. For llm/shell/dynamic bodies the carry-typo validator is best-effort, so the runtime
  guard is the only backstop there.
- **carry-typo check uses the NAMESPACED `{node_id}.{field}` key only.** Workflow outputs register under
  BOTH `node_outputs["run-rounds.survivors"]` AND a bare `node_outputs["survivors"]`; checking the bare
  alias would let a missing-prefix carry (`${survivors}`) pass the typo check while failing the self-ref
  check. The typo check also skips non-self-ref values (`root != node_id`) so the self-ref diagnostic owns them.
- **llm/shell carry into `inputs:` is inert** unless the resolved `prompt`/`system`/`command` text
  references `${key}` — those nodes don't read `params["inputs"]` at exec time. Hence the WARNING.
- **`if loop_data is None` (not `if not loop_data`)** in compiler + data_flow: an empty `loop: {}` now
  errors (no polarity) instead of being silently ignored. More correct.

## Patterns Established (reuse these)

- **Shared pure-function for cross-validator parity** — `check_loop_polarity` in `core/workflow/loop_validation.py`,
  imported by compiler (run path) and data_flow (validate path). Use this any time a rule must hold in
  BOTH the compile path and the no-compile validate/save path.
- **Per-iteration config transformation in `plan_node`** — `carry_effective_config` returns an effective
  `NodeConfig` for the current iteration. Future per-iteration features (resume state, approval state)
  that need a node's inputs to vary by iteration should follow this shape and let the planner's
  `iteration=1` make it inert during planning automatically.
- **Strict-resolution guard for structural plumbing** — `_assert_carried_inputs_resolved` +
  `LoopCarryError`. When a feature's references are a contract (not user-facing prose), fail loud
  regardless of `template_resolution_mode` via `contains_unresolved_template`.
- **Validation precision tiers** — precise against declared outputs (`## Outputs` / code `result`),
  best-effort skip for loose/dynamic types, with the runtime guard as the backstop. Mirrors the
  pre-existing `while:` typed-output validation.

### Anti-patterns to avoid

- Don't put per-iteration resolution logic in `engine._execute_node` (wrong layer; and the obvious
  callback `_execute_single_node` is batch-only → inert for loops).
- Don't treat an absent condition source uniformly across `while`/`until` — polarity matters for absent.
- Don't rely on permissive mode to surface a structural-reference failure.
- Don't add a loop rule to only one of compiler / data_flow.

## AI Agent Guidance

### Quick Start for Related Tasks

Read first, in order: `runtime/engine/loop_control.py` (`carry_effective_config`, `is_carry_iteration`,
`apply_carry_overrides`, `evaluate_loop_condition`), `runtime/engine/plan_node.py` (the override call
site + why hashing sees it), the plan's **Validation matrix** section, and
`core/workflow/loop_validation.py` (the parity helper). Then the tournament + until-absent +
permissive-strict tests in `test_integration/test_loop_config.py`.

Mental model: **carry = override the node's `inputs:` for iteration N>1, inside `plan_node`, gated by
`is_carry_iteration`.** Everything else (resolution, hashing, memo, the substrate) is unchanged.

### Common Pitfalls

- Hooking per-node loop behavior into `_execute_single_node` (dead code for loops).
- Forgetting the compiler↔data_flow parity for a new loop rule.
- A carry test that asserts iteration *count* but not carried *content* (passes while the feature is inert).
- Assuming `template_config` exists — it's `None` for a node with no templates *unless* it's a carry loop.

### Test-First Recommendations

When modifying the carry path: run `tests/test_integration/test_loop_config.py` (esp. the tournament
content-assert) + `tests/test_execution/test_plan_drift.py` + `test_plan_classify.py` (engine/planner
parity) + `tests/test_runtime/test_loop_control.py`. Then `make check` (mypy + ruff) — the gate that
the first implementation pass skipped.

## Post-Review Addendum (Phase 10 — agent-UX fixes)

A `/code-review` of the branch + `/evaluate-review` of two PR reviews surfaced six findings; all were
verified against source and the real ones fixed. See progress-log Phase 10 for the full account. Two
corrections to claims made **above** in this document:

- **"Strict-on-carry-always" / `_assert_carried_inputs_resolved` "raises regardless of mode"** — this was
  an *overstatement at review time*: a source trace proved the strict (default) path re-raised the generic
  `template_exception` at `engine.py:824` **before** the carry guard at `:868`, so the carry-specific
  `LoopCarryError` only fired in permissive mode. **Now corrected in code** — the guard runs before that
  re-raise and is carry-aware in both modes, so the claim is now literally true. The message also names
  "loop node 'X'" (not "loop body"), lists the loop node's available outputs, and gives a `${node.output}`
  example.
- **The `until:` cap advisory** (`engine._emit_loop_cap_advisory`) was hard-coded for `while:` polarity —
  for an `until:` loop it printed backwards guidance naming the wrong keyword. Now polarity-aware.

Also fixed: the carry-typo validator falsely rejecting coalesce carry values (`${c.x ?? "y"}`), the
prompt-usage WARNING false-positiving on nested refs (`${state.summary}`) — both were rolled-own template
parsing, now reusing `TemplateResolver`; and the carry-typo diagnostic now offers did-you-mean + available
outputs. `make check` green; broad sweep 5546 passed, 1 skipped.

---

*Generated from the implementation + review + refactor context of Task 166.*
