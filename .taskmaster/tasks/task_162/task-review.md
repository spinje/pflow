# Task 162 Review: Loop Config — Condition-Terminated Iteration

## Metadata

- **Implementation date:** late May 2026; staged, **not committed** (repo policy leaves commits to the user). No PR yet.
- **Provenance (read this first — attribution matters for trust):**
  - **Bulk implementation (Phases 1–7):** a prior AI agent. Its first-person, per-phase account — gotchas, deviations, the two in-session review rounds, the full CLI verification matrix — is in `implementation/progress-log.md`. That is the authoritative as-built record; this review does **not** repeat it.
  - **Design + ADR + plan, independent verification, and the planner cost-parity follow-up fix:** the session that produced this review. The verification campaign and the follow-up fix below are first-person for *this* author; the Phase 1–7 internals are second-hand (verified against code, not lived).
- **Companion artifacts (don't duplicate — route to them):** `task-162.md` (what/why), `context/adr/0001-445-loop-engine-reentry.md` (the architecture decision + rejected alternatives), `implementation/implementation-plan.md` (the how), `implementation/progress-log.md` (as-built), `context/CONTEXT.md` → Iteration (Loop-vs-Batch glossary).

## Executive Summary

Added a `loop:` config block (sibling to `batch:`) that re-runs one node until a truthiness condition over its own typed output goes falsy or `max_iterations` is hit. Implemented via **engine re-entry** (a `continue` in the graph walk), *not* the desugar-to-two-nodes the issue proposed — so it reuses the existing visit-guard + revisit-cache-bypass and stays one authored node end-to-end. Full suite green (7364 passed, 1 skipped); `make check` clean.

## What Was Built vs. Planned

- **Architecture pivoted from the issue's plan.** Issue #445 specified parse-time desugaring into a worker/checker backward-edge pair. We rejected it (ADR 0001): the synthesized checker would leak into trace/report/mermaid/progress (pflow has no "internal node" seam), and a condition isn't naturally a node. Engine re-entry localizes loop control where it belongs and reuses proven machinery.
- **The issue's "zero new runtime" framing was false** — and that mattered. Even re-entry required: a typed-output truthiness condition evaluator, a self-reference validation carve-out, `${__iteration__}` injection + dual-validator registration, dry-run/planner parity, and a sub-workflow cache-staleness guard. Future agents: distrust "pure sugar" claims about anything touching the engine walk.
- **Deviations the implementer added (see progress-log §5):** a focused `LoopConditionError` (`core/exceptions.py:850`); explicit rejection of `loop:` under `enable_namespacing: false` and `storage_mode: shared`; per-operand type-gating of coalesce `while:` conditions; the `loop_runtime_scope` contextmanager (a DRY refactor unifying engine + planner iteration bookkeeping).
- **Follow-up added in the review session (progress-log §12 #1 → now done):** the dry-run planner under-reported cost for the loop × sub-workflow × cache shape. Fixed by mirroring the engine's `_PROPAGATED_KEYS` in `execution/plan.py::create_planner_shared` (a `loop_active` seed threaded at all three recursion sites). Regression test `test_planner_models_looped_subworkflow_inner_cache_as_execute` was **empirically verified to fail without the seed** (reported `cached`), so it is a true regression test, not a vacuous one.

## Load-Bearing Integration Points (the couplings that will bite)

1. **The re-entry seam is timing-critical.** The condition is evaluated *after* `_execute_node` returns but *before* the next visit (`engine.py` ~`:407` `loop_runtime_scope` wraps execution; re-entry decided at `_loop_should_reenter` ~`:426`). It reads `shared[node_id]`'s fresh output. `NamespacedSharedStore.__init__` only creates an *absent* namespace — it does NOT reset an existing one — so the node's own output survives until it overwrites it next visit. **Moving the condition eval later (past the next-visit namespace write) silently reads stale/wiped output.** This is why re-entry is byte-for-byte a backward-edge revisit.

2. **`loop_runtime_scope` is the SINGLE owner of `__iteration__` + `__loop_active__` lifecycle** (`runtime/engine/loop_control.py`), shared by **both** the engine walk and the planner walk. The `clear_iteration_on_exit` asymmetry is intentional: engine passes `False` (keeps `${__iteration__}` across re-entry, clears when the loop ends); planner passes `True` (walks the body once, must not leak to later nodes). Touch the depth-counter logic *here only* — two consumers depend on it.

3. **The cache guard suppresses the READ, keeps the WRITE.** `instrumentation.memo_cache_lookup` returns `(False, cache_key, None)` under `__loop_active__` — `cache_key` is preserved so `write_memo_cache` still populates history. Returning `(False, None, None)` (the implementer's first, reverted attempt) kills the write → no history → **planner parity breaks**. Inner sub-workflow nodes need this because their child engine resets `node_visit_counts={}`, so the ordinary `visit_count > 1` bypass never fires for them.

4. **Engine↔planner parity is an invariant, enforced unevenly.** `__loop_active__` crosses the sub-workflow boundary at runtime via `_PROPAGATED_KEYS["__loop_active__"]` (`workflow_executor.py:137`); the planner mirrors it via `create_planner_shared(loop_active=...)` (`execution/plan.py`). `test_plan_drift.py` pins control-flow parity but **does not** pin nested cost — which is exactly how the planner cost under-report hid. Adding any new engine walk-state key means mirroring it in `create_planner_shared`, or the dry-run diverges silently.

5. **The reserved-key trio must move together.** `${__iteration__}` requires three coordinated edits or it's rejected/unresolved: registration in `valid_simple_refs` (`data_flow.py:465`), exclusion from `is_template_reserved_internal_key` (`core/types.py:217`), and a `${__iteration__.x}` path-access rejection (`data_flow.py:232`). The reserved-key check runs *before* the valid-ref check, so omitting the `types.py` exclusion rejects a valid `${__iteration__}` even with the registration present.

## Reserved Shared-Store Keys (new)

- `shared["__iteration__"]` — int, 1-based, current loop iteration; cleared on loop exit (incl. the error path, `engine.py:441`). Mirrors batch's `__index__` machinery but is a *distinct* key (1-based vs 0-based; nesting collision-immunity).
- `shared["__loop_active__"]` — int *depth counter* (not a bool — supports nested loops), set around a loop body, cleared at depth 0. Propagated to sub-workflow children; read by `memo_cache_lookup` to suppress inner reads. Both are `__`-filtered from traces.

## The Verification Campaign (unique to this session — what it caught)

The design was hardened *before* coding by adversarial search + a multi-agent plan review. The catches worth remembering as a pattern:

- **Belt-and-suspenders condition validation** emerged from a *contradiction between two reviewers*. One said "reject string-typed `while:`"; another said "allow `any` or you false-reject the flagship" (sub-workflow outputs infer as `any`). Both were half-right. Resolution: **parse-time rejects only a *known* string type (allows `any`); runtime raises if the resolved value is *still* a `str`.** Neither layer alone is safe. This pattern — best-effort static gate + airtight runtime backstop — should be reused for any "the type might be wrong at runtime" validation.
- The plan-review caught **two real plan mistakes** the implementer then corrected (progress-log §12): mutual-exclusion and the literal-cap bound were specified for the compiler, but `--validate-only`/`save` never compile, so they had to move to the shared `data_flow` validator. **Lesson: validation that must cover save+run belongs in `data_flow`/the shared validator, never the compiler alone.**
- A reviewer's "bare-node `while:` silently loops" finding was **investigated and REFUTED via real CLI** — it was already rejected by the generic template error. The redundant loop-specific message was removed. Lesson: the CLI is the arbiter, not a green test asserting your own added message.

## Reusable Patterns

- **New node-config block = mirror `batch` end-to-end:** tag-map → `_route_code_blocks_to_node`/`_build_node_dict` (top-level `node["loop"]`, escapes the params-only unknown-key walk) → `LOOP_CONFIG_SCHEMA` (`additionalProperties:false` is the only typo guard for top-level blocks) → `LoopConfig` dataclass + `NodeConfig` field → `_create_node_and_config` → engine dispatch. The file map in progress-log §8 is the template.
- **Engine walk-state → planner must mirror** (point 4 above). Treat `_PROPAGATED_KEYS` and `create_planner_shared` as a matched pair.
- **Prefer extraction over `noqa: C901`** (progress-log §11): the implementer refactored 9 complexity-threshold trips into named helpers rather than suppressing — `loop_runtime_scope`, `_compute_memo_cache_key`, etc. Keep this norm.

## Dangerous Edges — what breaks if naively modified

- Swap the condition evaluator to `resolve_template` (instead of `variable_exists` + `resolve_value`) → returns the truthy literal `"${...}"` on an absent ref → **infinite loop to the visit-cap crash**.
- Make the typed-output gate a denylist (reject strings) instead of allow-`any`-plus-runtime-backstop → false-rejects the flagship, *or* lets `"0\n"`-style strings invert the loop.
- Set `max_iterations > MAX_NODE_VISITS` (default 100) → the hard guard raises `MaxNodeVisitsError` (a `RuntimeError`, NOT a `PflowError`) instead of the friendly INFO advisory. Validation bounds it; keep that bound (and reference `instrumentation.MAX_NODE_VISITS`, not a literal — it's env-overridable and monkeypatched in tests).
- Edit `loop_runtime_scope` depth math assuming a single consumer → desyncs the planner walk.

## Known Limitations / Deliberate Non-Fixes (progress-log §6 + review R2)

All fail-safe or exotic; documented honestly, not bugs:
- Templated `storage_mode: ${x}` resolving to `"shared"` bypasses the literal loop+shared rejection (narrow; literal form covered).
- `while: ${a ?? "x>y"}` false-rejects (a `>` inside a string literal trips the operator scan) — **fails safe** (rejects at validation, never mis-loops).
- `${__iteration__}` registered globally when any loop exists → a non-loop node referencing it passes validation but errors at runtime (mirrors `__index__`).
- **R2 (independent):** a templated `max_iterations` that can't resolve at plan time falls back to `MAX_NODE_VISITS` (100) and multiplies the dry-run upper bound by 100 — an honest ceiling, but alarming for an llm-heavy loop body. Not a correctness bug.

## AI Agent Guidance

**Quick start for related work:** read `loop_control.py` (the whole module is small and is the conceptual core), then the re-entry block in `engine.py` (~`:396-441`), then `progress-log.md §4` (critical decisions) and `§8` (file map). For validation work, read `data_flow.py` (carve-out + reserved-key trio + `loop.while` threaded into the ref walk) and `template_validation/validator.py::_validate_loop_conditions`.

**Common pitfalls:** (1) `loop.while` lives at the node *top level*, invisible to the params-only validator walks — it must be explicitly threaded into BOTH `data_flow`'s ref walk and `template_validation`'s `_iter_template_operands`, or typos pass silently and inputs used only in `while:` false-flag as "unused." (2) Code nodes output ONLY `result` — a body needing a condition list + a value must return a dict `result`. (3) Every node and output heading needs a prose description line or the parser rejects it.

**Test-first when modifying:** run `tests/test_integration/test_loop_config.py` (engine matrix incl. cache guard activation/deactivation + depth-2 nesting), `tests/test_execution/test_loop_plan.py` (dry-run parity), and `test_plan_drift.py` (the parity invariant) before and after. If you change cache or sub-workflow behavior, the cache-guard activation **and** deactivation tests are the ones that catch real regressions.

---

*Synthesized from the design/verification/extension context of this session plus the implementer's `progress-log.md`. Per-phase implementation detail and the full CLI verification matrix are in that log, by design — not repeated here.*
