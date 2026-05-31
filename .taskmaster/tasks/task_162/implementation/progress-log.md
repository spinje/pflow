# `loop:` config for condition-terminated iteration (issue #445) — implementation handoff

**Status: COMPLETE.** `make check` clean (ruff + ruff-format + mypy + deptry).
Full suite: **7358 passed, 1 skipped**. NOT committed (per repo policy — leave to user).

Branch: `feat/loop-config-condition-iteration`. ADR: `context/adr/0001-445-loop-engine-reentry.md`.

---

## 1. What the feature does

Adds a `loop:` config block (sibling to `batch:`, mutually exclusive with it) on a single
node. The engine **re-enters** that node — re-running it — until a truthiness condition over
its **own typed output** (`while: ${node.output}`) goes falsy, or a `max_iterations` cap is hit.
It is a **do-while**: body runs once, then the condition is checked.

Authoring (inline canonical; fenced ```` ```yaml loop ```` also works):
```markdown
### run-cycle
- type: workflow
- workflow: ./run-cycle/run-cycle.pflow.md
- inputs: { base_branch: ${base_branch} }
- loop:
    while: ${run-cycle.issues_planned}   # typed output (list/number/bool); falsy → stop
    max_iterations: ${max_cycles}        # int OR ${template}; optional (defaults to MAX_NODE_VISITS)
```
- `${__iteration__}` (1-based) available in the body, mirrors batch's `${__index__}`.
- Cap-hit = stays SUCCESS, emits a non-degrading `Severity.INFO` advisory, and stamps
  `loop_stopped: "max_iterations"` on the node output (`"condition"` on a clean drain).

## 2. Architecture decision (the load-bearing one)

**Engine re-entry, NOT desugar-to-two-nodes.** The issue proposed desugaring `loop:` into a
worker/checker backward-edge pair. We rejected that (ADR 0001): re-entry reuses the engine's
existing visit-guard + revisit-cache-bypass so it is **byte-for-byte identical to a
backward-edge revisit**, and keeps it ONE authored node end-to-end (no synthesized node leaking
into trace/report/mermaid/progress). The whole feature is a `continue` in the graph walk plus
config/validation/condition machinery.

**Why re-entry works (the seam):** after `_execute_node` returns, `shared[node_id]` holds the
node's fresh output. `NamespacedSharedStore.__init__` only creates `parent[ns] = {}` when the
namespace is ABSENT — it does NOT reset an existing dict — so on re-entry the node overwrites
its own output keys, exactly like a backward-edge revisit. The condition is read at this seam.

## 3. Implementation by phase (all complete)

- **P1 Authoring + schema** — `markdown_parser.py`: `"loop"` in tag map (:103), route fenced
  block to `node["loop"]` in `_route_code_blocks_to_node`, hoist inline `- loop:` in
  `_build_node_dict`. `ir_schema.py`: `LOOP_CONFIG_SCHEMA` (required `while` template-pattern,
  `max_iterations` oneOf[int>=1, template], `additionalProperties:false`) wired into node schema.
- **P2 Config + compile** — `engine/types.py`: `LoopConfig` dataclass (`while_template`,
  `max_iterations` literal OR `max_iterations_template`); `NodeConfig.loop_config`.
  `compiler.py::_build_loop_config`: builds it, validates literal cap to `[1, MAX_NODE_VISITS]`
  via `_coerce_loop_cap_int` + `_validate_loop_cap`, enforces batch/loop mutual exclusion.
- **P3 Validation carve-outs** (highest-risk) — see §4.
- **P4 Engine re-entry** — `engine/loop_control.py` (new): `evaluate_loop_condition`,
  `resolve_loop_cap`, and `loop_runtime_scope` (a `@contextmanager` shared with the planner —
  see §11). `engine.py::_run_inner`: per-node loop counter + cap dicts, sets `${__iteration__}`
  inline + wraps node execution in `loop_runtime_scope(...)`, re-entry `continue`,
  `_loop_should_reenter` / `_mark_loop_stopped` / `_emit_loop_cap_advisory`.
- **P5 Cache-staleness guard** — `__loop_active__` depth counter (managed by `loop_runtime_scope`)
  suppresses inner-node memo READS (keeps writes); in `_PROPAGATED_KEYS` so sub-workflow children
  inherit it.
- **P6 Dry-run parity** — `plan.py`: `PlanEntry.loop_iterations`, `_annotate_loop_entry`,
  summary multiplies cost/duration by the cap (upper_bound), planner mirrors `__iteration__=1`
  + `__loop_active__` via the same `loop_runtime_scope` (clear_iteration_on_exit=True).
- **P7 Docs + example** — branching.md (3-loop-story table), sub-workflows.md, flagship
  `orchestrate.pflow.md` ported 3 nodes → 2, guide topic auto-detection for `loop:`.

## 4. Critical decisions & insights (READ before modifying)

### Condition evaluation is belt-and-suspenders (validation + runtime), and BOTH are required
- **Validation half** (`template_validation/validator.py::_validate_loop_conditions`): rejects a
  `while:` whose `infer_template_type` is a **known string** (`"string"`/`"str"`, e.g.
  `${shell.stdout}` — a non-empty string like `"0\n"` is truthy → never stops). Allows
  `any`/un-inferable so the motivating sub-workflow example isn't false-rejected. Also rejects
  comparison/arithmetic operators (`> < = ! + * / %` — hyphen EXCLUDED because node ids contain
  it, `?` excluded so coalesce survives).
- **Runtime half** (`loop_control.evaluate_loop_condition`): uses `variable_exists` +
  `resolve_value` (type-preserving), **NEVER `resolve_template`** (which returns the truthy
  literal on absent → infinite loop). Absent → falsy → stop. If the resolved value is STILL a
  `str`, **raise `LoopConditionError`** — do not `bool()` it.
- Neither alone is safe: validation can't see dynamic/`any` outputs that turn out to be strings
  at runtime; runtime alone gives no pre-execution diagnostic.

### `${__iteration__}` is a NEW dunder, not reused `__index__` (asked & answered)
Batch/loop are mutually exclusive on one node, so reuse is *technically* possible — but rejected
because (1) `__index__` is 0-based (array indexing), loop counter is 1-based; (2) the
reserved-key error messages must say different things per context; (3) collision-immunity under
nesting (loop body containing a batch). It **reuses `__index__`'s machinery** (raw-root `__*__`
write, reserved-key handling, validation registration) but is a distinct key.
`is_template_reserved_internal_key` (core/types.py) excludes BOTH `__index__` and `__iteration__`.

### Order in `_loop_should_reenter` is load-bearing
Condition checked FIRST (falsy → clean `"condition"` drain), THEN cap (truthy + at-cap →
`"max_iterations"` advisory). A loop that drains on the same iteration it would hit the cap is
correctly labeled `"condition"` (drain wins). The cap counts the loop's OWN iterations
(`loop_counts`), separate from the hard `node_visit_counts` guard, and is always `<= MAX_NODE_VISITS`,
so the loop stops before the hard guard would raise `MaxNodeVisitsError`.

### Cache guard: suppress the READ, not the WRITE (subtle, cost an iteration to find)
`instrumentation.memo_cache_lookup` returns `(False, cache_key, None)` under `__loop_active__` —
suppressing the hit but RETURNING the key so `write_memo_cache` still populates the cache.
**First attempt returned `(False, None, None)`** which killed the cache_key → `write_memo_cache`
skipped → no history → planner parity broke. The guard MUST sit AFTER cache_key computation,
right before `memo_cache.get_with_age`. Scoped to the loop subtree: `__loop_active__` is a depth
counter cleared on loop exit, so a sibling cached node AFTER the loop reads normally
(deactivation). Wins over an inner `cache: true` override.

### `loop_stopped` is engine-injected but registered as a validation output
`_mark_loop_stopped` stamps `shared[node_id]["loop_stopped"]`. It's NOT a declared child output,
so `${loop-node.loop_stopped}` would fail path validation. Fix: `extract_node_outputs` registers
`{loop_id}.loop_stopped` (type string) for loop nodes — **gated on `enable_namespacing`** (see §5).

### Planner must mirror the engine's loop modeling exactly (parity)
`plan.py` walker sets `__iteration__=1` AND raises `__loop_active__` while planning a loop node
(via the shared `loop_runtime_scope`, clear_iteration_on_exit=True so neither leaks at plan time).
Without `__iteration__`, `${__iteration__}`-using bodies hit a template error at plan time.
Without `__loop_active__`, the planner reports the loop node as a memo HIT (cached) while the engine
actually re-executes it — a parity break. `loop_iterations` (resolved cap, with
`LoopConditionError`→MAX_NODE_VISITS fallback for unresolvable template caps) multiplies the
single-pass cost/duration in `_compute_totals` (per-level) and `_summarize` (nested sub_plan
rollup); cost_basis flips to `upper_bound`. Verified engine-N == planner loop_iterations x per-iter.

### The `__iteration__` / `__loop_active__` lifecycle lives in ONE place: `loop_runtime_scope`
Both the engine walk and the planner walk wrap node execution in
`loop_control.loop_runtime_scope(shared, is_loop, iteration=..., clear_iteration_on_exit=...)`.
On enter it sets `${__iteration__}` (if given) and raises `__loop_active__`; on exit it decrements
the depth and (when `clear_iteration_on_exit`) pops `${__iteration__}`. The asymmetry is real and
intentional: the **engine** keeps `${__iteration__}` across re-entry (clears it only when the loop
ends, in the re-entry logic / outer finally) so passes `False`; the **planner** walks the body once
and must not leak it to later nodes so passes `True`. Before the refactor this was two near-identical
inline try/finally blocks; if you touch the depth-counter logic, touch it here only.

## 5. Deviations from the plan

- **Added `LoopConditionError`** (`core/exceptions.py`, a `PflowError` subclass) for the runtime
  str-condition / bad-template-cap raise. The plan said "raise a clear diagnostic" without naming
  a type; no existing exception fit cleanly, so a focused one with `to_diagnostics()` was added.
- **Reject `loop:` under `enable_namespacing: false`** (`data_flow.py::_make_loop_namespacing_diagnostic`).
  NOT in the plan. Found in self-review after the silent-failures agent: with namespacing off the
  `while: ${node.output}` self-reference can't resolve, so the loop would silently single-pass
  (it actually surfaced as a confusing generic "no valid source" error). Explicit up-front
  rejection with an actionable message. Sibling to the planned `storage_mode: shared` rejection.
- **`loop_stopped` registration gated on `enable_namespacing`** — review-driven; keeps
  validation/runtime in agreement (engine can't stamp the marker under namespacing-off).
- **Coalesce `while: ${a ?? b}` now type-gated per-operand** — review-driven. Original code
  skipped the string-type check for any coalesce (`is_coalesce_expression` → continue), so a
  coalesce string source was caught only by the runtime belt. Now each non-literal operand is
  type-inferred and rejected if known-string.
- **`${__iteration__}` cleared on the error-exit path too** — the re-entry block originally only
  popped it on the clean (falsy/cap) exit; the error path (action="error" → on-error) fell through
  without popping, so an on-error handler could read a stale value. Now popped on all non-re-entry
  exits (the outer try/finally was already a backstop for `shared_after`).
- **MAX_NODE_VISITS referenced as `instrumentation.MAX_NODE_VISITS`** (module attr, not a bound
  import) in compiler + loop_control so tests can monkeypatch it live.

## 6. Deliberate NON-fixes (judged not worth it; flagged honestly)

- **Templated `storage_mode: ${x}` resolving to `"shared"`** bypasses the literal loop+shared
  rejection (rejection checks `== "shared"` literally). Narrow/exotic; literal form covered+tested.
  A runtime guard would add engine complexity for marginal value. (feature-interactions #5)
- **Coalesce operator false-reject**: `while: ${a ?? "x>y"}` — a `>` inside a string literal trips
  the operator scan. Fails SAFE (rejects at validation, never mis-loops). Fixing needs stripping
  quoted literals before the scan; not worth the surface for an exotic input.
- **`${__iteration__}` registered globally** when any loop exists → a non-loop node referencing it
  passes validation but resolves absent at runtime (strict → error). Intentional, mirrors
  `__index__` (batch) which the plan endorsed. Validation/runtime asymmetry by design.

## 7. Cannot verify in CI

The flagship `examples/agent-orchestration/parallel-planner-review/orchestrate.pflow.md` is
validated (`test_example_validation.py`) but never EXECUTED — needs `gh` + Claude Code + live LLM.
Equivalent runnable integration tests exercise the same machinery (sub-workflow loop,
`${__iteration__}`→child inputs, `loop_stopped` downstream read, cache guard). The literal
flagship run is a manual step. Recommend the billed `/code-review ultra` cloud pass too
(touches the engine graph-walk hot path; user-triggered).

## 8. File map (source)

```
core/markdown_parser.py        tag map + _route_code_blocks_to_node + _build_node_dict
core/ir_schema.py              LOOP_CONFIG_SCHEMA + node-schema wiring
core/types.py                  is_template_reserved_internal_key excludes __iteration__
core/exceptions.py             LoopConditionError (new)
core/workflow/data_flow.py     loop_node_ids, self-ref carve-out (_check_forward_reference),
                               __iteration__ in valid_simple_refs + reserved-key path rejection,
                               loop+namespacing and loop+shared rejections, loop.while threaded
                               into the ref walk (_validate_node_params)
runtime/engine/types.py        LoopConfig, NodeConfig.loop_config
runtime/compilation/compiler.py _build_loop_config / _coerce_loop_cap_int / _validate_loop_cap
runtime/engine/loop_control.py (NEW) evaluate_loop_condition, resolve_loop_cap, _coerce_runtime_cap,
                               loop_runtime_scope (contextmanager, shared by engine + planner)
runtime/engine/engine.py       _run_inner re-entry (uses loop_runtime_scope), _loop_should_reenter,
                               _mark_loop_stopped, _emit_loop_cap_advisory
runtime/engine/instrumentation.py memo_cache_lookup __loop_active__ read-suppression;
                               _compute_memo_cache_key (extracted batch/non-batch key computation)
runtime/workflow_executor.py   __loop_active__ in _PROPAGATED_KEYS
runtime/template_validation/validator.py _validate_loop_conditions (typed gate + operator +
                               coalesce per-operand), __iteration__ + loop_stopped registration,
                               loop.while threaded into _iter_template_operands
execution/result.py            PlanEntry.loop_iterations
execution/plan.py              _annotate_loop_entry, planner __iteration__/__loop_active__ mirror,
                               cost/duration multiplication in _compute_totals + _summarize
guide/__init__.py              detect_topics_from_ir: loop → branching
guide/features/branching.md, sub-workflows.md   docs
```

Reserved shared-store keys added: `shared["__iteration__"]` (int, 1-based, cleared on loop exit),
`shared["__loop_active__"]` (int depth counter, cleared at depth 0). Both filtered from trace
(`__` prefix). Document them in `runtime/CLAUDE.md` "Reserved Shared Store Keys" if updating docs.

## 9. Tests (all green)

```
tests/test_core/test_loop_parsing_schema.py    parser both forms, schema typo/bad-max
tests/test_runtime/test_loop_compiler.py        _build_loop_config branches, mutual exclusion, cap bounds
tests/test_core/test_loop_validation.py         validation matrix (typed gate, operator, coalesce,
                                                 self-ref, __iteration__, shared+namespacing rejection,
                                                 input-only-in-while not flagged unused)
tests/test_runtime/test_loop_control.py          (NEW) condition eval + cap coercion belt, error branches
tests/test_integration/test_loop_config.py       engine matrix: drain, single, 1-based iteration,
                                                 cap-hit advisory, post-loop isolation, lowered-env cap,
                                                 error-action→on-error, ${__iteration__}→child inputs,
                                                 templated cap (valid + bad-value-fails-run), nested loops,
                                                 loop_stopped downstream read, cache guard activation +
                                                 deactivation
tests/test_execution/test_loop_plan.py           dry-run parity (engine N× == planner loop_iterations ×)
```

GOTCHA for future test authors: **code nodes output ONLY `result`.** Any other annotated
module-level var (`keep: list = ...`) is parsed as an INPUT annotation and errors. Use a dict
`result` (`result: dict = {"keep": [...], "len": ...}`) when a loop body needs both a condition
list and a separate value. Also: every node AND output declaration needs a description prose line
(parser rejects bare headings) — bit me twice while writing the integration tests.

## 10. Review round summary

Three local review agents run (validation-consistency, silent-failures, feature-interactions).
**feature-interactions found NO interaction bugs** — architecture sound (reuses existing
boundaries, single memo read-site, shared plan_node primitive keeps engine/planner in parity).
All substantive findings fixed (see §5). Remaining items are the §6 deliberate non-fixes and the
§7 can't-run-in-CI flagship.

## 11. Complexity / code organization — ZERO `noqa: C901` added

Early in this work I suppressed 9 `C901` (mccabe complexity > 10, ruff default) warnings with
`# noqa` because the loop additions tipped already-near-threshold functions over. That was the
wrong call — splitting along a cohesive seam into a well-named helper reads better (for humans and
for an AI agent reasoning about a function in isolation). All 9 were instead REFACTORED; no
`noqa: C901` was added by this feature (the 5 pre-existing ones in these files predate it).

The extractions (each behavior-preserving, full suite green after):
- `engine._run_inner` + `plan._build_plan_with_shared` → both now use the shared
  `loop_control.loop_runtime_scope` contextmanager (removed two near-identical inline try/finally
  blocks — a net DRY win, see §4).
- `instrumentation.memo_cache_lookup` → extracted `_compute_memo_cache_key` (batch/non-batch key).
- `validator._validate_loop_conditions` → extracted `_loop_condition_diagnostic`; unified the
  coalesce/simple paths into one operand loop (`operands = split or [var]`).
- `validator._iter_template_operands` → extracted `_node_template_value_sources`.
- `validator.extract_node_outputs` → extracted `_register_loop_node_outputs`.
- `data_flow.validate_data_flow` → extracted `_validate_loop_node_combos` (namespacing + shared).
- `markdown_parser._build_node_dict` → collapsed 5 sequential `if K in params: pop(K)` hoists into
  one loop over a tuple (loop var named `top_level_field` to avoid shadowing dataclasses `field`).
- `guide.detect_topics_from_ir` → extracted `_node_topics`.

Principle for the next agent: prefer extraction over `noqa: C901`. The only honest reason to keep
`noqa` is when a split would thread many mutable locals through a wide helper signature or fragment
a tightly-sequenced stateful loop — none of these did. If you add a branch to one of these and it
re-trips C901, extract a cohesive helper rather than re-suppressing.

---

## 12. Post-implementation review round + CLI verification (2nd agent)

A 5-agent staged review (silent-failures, validation-consistency, feature-interactions,
test-fidelity, concurrency) ran on the staged diff, followed by adversarial **real-CLI**
verification. Net: the core engine/runtime/cache/concurrency is solid (test-fidelity ran 11
mutations, all caught). Findings were all small, validation-layer or planner. Status after this
round: **`make check` clean; full suite 7363 passed, 1 skipped.**

### Fixes landed this round (#3, #4, #5)

- **#3 batch+loop on the VALIDATE path** (`data_flow._validate_loop_node_combos`). The compiler's
  `_build_loop_config` raised `CompilationError`, but `--validate-only`/`save` never compile, so the
  combo slipped through there. Added the check to the shared data_flow validator (covers both paths).
  Side effect: on the compile path, data_flow now catches it FIRST (one compiler test updated to
  expect the earlier, generic data_flow rejection; the specific "mutually exclusive" message is still
  asserted by the `_build_loop_config` unit test + the new validate-path test). **This was a PLAN
  mistake**: the plan said to put mutual-exclusion in the compiler and claimed it "covers both paths" —
  it doesn't. data_flow is the shared home.
- **#4 literal `max_iterations > MAX_NODE_VISITS` on the VALIDATE path** — same shape, same fix
  location (`_validate_loop_node_combos`, deferred import of `instrumentation.MAX_NODE_VISITS` so it
  honors the env override; `type(raw) is int` excludes bool). Plan under-specified this for the
  validate path.
- **#5 nested-loop test** — the shipped `test_nested_loops_both_converge` was MISLABELED (its outer
  level had no `loop:`). Renamed it to `test_inner_loop_inside_subworkflow_converges`; added a REAL
  depth-2 test (`test_nested_loops_both_converge`): an outer `loop:` node whose sub-workflow body
  itself loops. It **passes** — confirming the `__loop_active__` depth counter and `${__iteration__}`
  mapped-isolation are correct at depth 2 (previously zero coverage there).

### #2 (bare-node `while:`) — INVESTIGATED, then REVERTED as redundant

The silent-failures reviewer claimed `while: ${node}` (bare, no field) "passes validation, loops to
the cap" (a silent failure). I first added a loop-specific rejection. **Real-CLI verification proved
the premise FALSE**: a bare `${c}` `while:` is *already* rejected (exit 1) by the pre-existing generic
template error — *"Invalid template ${c} — this is a node ID. Use ${c.output_key}"* — plus a data_flow
"undefined input" error. My loop-specific message was a redundant THIRD error. Per "simplest final
code", I **removed it** (validator `_make_loop_bare_node_diagnostic` + the operand check). Kept a
regression test pinning that bare-node `while:` is rejected (via the generic mechanism) and that bare
*input* refs are NOT rejected. Lesson: the reviewer mis-diagnosed; the CLI was the arbiter, not the
green test that asserted my own (now-removed) message.

### #1 (planner cost under-report) — NOW IMPLEMENTED (follow-up session)

**Implemented** after a 4-agent re-verification confirmed the bug, the fix location, and a
narrow blast radius (only `llm`/`cache:true` inner nodes; no cost gate exists, so nothing is
bypassed). Chosen shape = the engine-parity mirror, not the minimal one-site patch:
`create_planner_shared` gained a `loop_active: int = 0` kwarg that seeds `shared["__loop_active__"]`
(mirroring the engine's `_PROPAGATED_KEYS` in `_create_child_storage`); `_build_plan_with_shared`
threads `_loop_active` as a recursion kwarg (next to `_depth`/`_force_downstream`); and **all three**
recursion sites pass `shared.get("__loop_active__", 0)` — site 1101 (sub-workflow) AND the two batch
sites (1510/1619), closing the batch-nested-in-loop parity gap the one-site patch would have left.
Regression test `test_planner_models_looped_subworkflow_inner_cache_as_execute` (test_loop_plan.py):
a looped sub-workflow body with a `cache: true` inner node → planner must mark it `execute`.
**Empirically verified it FAILS without the seed** (reports `cached`) — a true regression test, not
vacuous. `runtime/CLAUDE.md:113` `_PROPAGATED_KEYS` doc updated to list `__loop_active__`. Full suite
7364 passed, 1 skipped; `make check` clean. (Original plan-only writeup retained below for context.)

---

**Original plan-only writeup:**

Confirmed real: the engine propagates `__loop_active__` into a looped sub-workflow's child store
(via `_PROPAGATED_KEYS`) so inner cached nodes re-execute; the **planner** (`create_planner_shared`)
builds a fresh child store WITHOUT it, so `--dry-run` reports inner cacheable nodes as cached and
under-reports cost for the loop × sub-workflow × cache triple (the flagship shape). **Plan mistake**:
Phase 6 specified the iteration multiplier + nested rollup but never said the planner must propagate
the cache-suppression flag across the sub-workflow boundary. Surgical fix (simplest final code): add
an optional `loop_active` seed to `create_planner_shared` (the single planner-store builder — the
analog of the engine's `_create_child_storage`), forward it through `_build_plan_with_shared`, and
pass `shared.get("__loop_active__", 0)` at the ONE pre-boundary `_plan_sub_workflow` call site
(plan.py:1101). The other two `_build_plan_with_shared` sites (1510/1619) are batch per-item — and
batch+loop is mutually exclusive, so they don't need it; downstream/BFS mode already forces "execute".
Plus a regression test in `test_loop_plan.py` (seed inner-node cache → plan a looped sub-workflow →
assert inner shows `execute`, not `cached`). The cost MULTIPLIER already exists; the bug is only that
the inner per-pass cost is ~$0.

### CLI verification matrix (what actually ran through `uv run pflow`, not just the test suite)

All ✓ end-to-end via the real CLI:
- drain-to-empty (single-node code body AND `type: workflow` body); both authoring forms
  (inline `- loop:` AND fenced ```` ```yaml loop ````).
- cap-hit: SUCCESS + INFO advisory in **text** (`ℹ️ Advisories:`) AND **JSON** (`advisories[]` +
  `diagnostics[]`, stable id `loop.max-iterations-reached`, `warnings: []`, exit 0). Agents can detect
  "capped, work remained" programmatically.
- no `max_iterations` → stops at the default cap (100) with the advisory, NO `MaxNodeVisitsError` crash.
- runtime string-guard (belt-half-2): a `${c.result.s}` that is `any` at validation but a STRING at
  runtime → `--validate-only` PASSES, run RAISES a clean `LoopConditionError` (exit 1, JSON
  `success:false status:failed`, actionable message). The belt validation can't see, working + loud.
- error mid-loop → fails cleanly (exit 1, source line).
- `${__iteration__}` 1-based; `loop_stopped` marker readable downstream (`condition` branch verified).
- loop-then-branch: `work` loops, exits to `done`, `giveup` `not_executed` — intermediate actions
  correctly ignored, final action routes the exit.
- rejections exit 1 on BOTH `--validate-only` AND run: batch+loop, over-cap, string `while:`,
  operator `while:`, bare-node `while:`, `max_iterations: 0` (schema).
- `--dry-run` flips the plan to `cost_basis: upper_bound`.
- flagship `orchestrate.pflow.md` + `run-cycle.pflow.md` validate clean.

Not reproducible via CLI without LLM cost history (hence the #1 plan + unit-test gap): the sub-workflow
loop-body cost under-report. `--dry-run` cost multiplication for a code-node loop is invisible
(3 × $0 = $0) but the `upper_bound` basis confirms the multiplier engaged.

---

## 13. PR-review response round (PR #453 review comment → `/evaluate-review`)

A code-review comment on PR #453 raised 9 findings (1 critical, 4 warnings, 4 suggestions). Each was
verified against HEAD (3 parallel codebase-searchers + direct reads) before acting — the review was
written against a **pre-fix snapshot**, so its line numbers and one finding were stale. Net: the
implementation was sound; the actionable items were polish + one genuine (narrow) silent-failure to close.
Full suite after this round: **7369 passed, 1 skipped**; `make check` clean. Still committed-not-pushed by
the user's call (this round is `[skip review]`).

**Disputed / no-op:**
- **#1 (sed BSD-only test bug — the only "Critical"):** ALREADY FIXED at HEAD. `tail -n +2 … > tmp && mv`
  is in place (commit `d57a8a9a`); no `sed -i` remains. The review predated the fix.
- **#8 (`type(x) is int`) as a *bug*:** disputed — the code was functionally correct (it deliberately
  excludes bool, which `isinstance(x, int)` would not). Real point was a *style* inconsistency, fixed below.

**Fixed this round:**
- **#6 — multi-reference `while:` silently single-passed (the one real gap).** `while: ${a}${b}` passes the
  broad schema pattern `^\$\{.+\}$`, and BOTH layers deferred to the other — the validator `return None`d
  ("schema constrains shape") and the runtime `return False`d ("validation rejects this shape"); neither
  actually rejected it, so it ran once and reported SUCCESS. **Root cause was the deferral, not the runtime
  branch** — so the fix makes ONE layer own it: `validator._make_loop_shape_diagnostic` now rejects a
  non-single-`${...}` `while:` at parse time, and the runtime comment is corrected to "validator rejects
  this; backstop for programmatic IR." Regression test `test_multi_reference_while_rejected`. (Chose the
  validation fix over the reviewer's "raise at runtime" — failing loud at validate time is simpler and
  catches it before any execution.)
- **#3 — `--only <loop-node>` runs one iteration, undocumented.** Behavior is correct (the `is_only_target`
  break precedes re-entry); documented it in the `--only` help text (`run.py`) and the Loops guide
  (`branching.md`). No behavior change.
- **#4 — `engine/CLAUDE.md` didn't mention `loop_control.py` or loop re-entry.** Added the module to the
  file-structure listing and a step 17.6 to the lifecycle diagram.
- **#7 — `loop_runtime_scope` asymmetry had no direct test.** Added 4 unit tests in `test_loop_control.py`
  pinning the `clear_iteration_on_exit` contract (engine keeps `__iteration__`, planner clears it),
  the `__loop_active__` depth-counter (nested), and the inactive no-op.
- **#5 — cap memoization undocumented.** One-line docstring note on `_loop_should_reenter`: the cap is
  resolved once and memoized in `loop_caps`; a per-iteration-varying `${template}` cap uses its first value
  (a loop's cap is fixed by design).
- **#2 — `_emit_loop_cap_advisory` unconditional `__warnings__[node_id]` write.** Reviewer's proposed
  `if node_id not in __warnings__` guard was **rejected** — it inverts precedence and would drop the cap
  advisory (the more important "why it stopped" signal) in favor of a pre-existing warning. Kept
  cap-advisory-wins; corrected the docstring to honestly note the one coexisting writer (an `llm` loop body's
  own non-error advisory on the capping iteration) and that the cap advisory intentionally wins. No behavior change.
- **#8 (cosmetic) — `type(raw_max) is int` → `isinstance(raw_max, int) and not isinstance(raw_max, bool)`**
  in `data_flow.py`, matching the codebase convention (the type SSoT `TypeSpec.accepts` and the sibling
  prewarm check in the same file). Behavior-identical.
- **#9 (cosmetic) — `raise … from None` → `from exc`** in `_coerce_runtime_cap`'s str branch, preserving the
  underlying `ValueError` context for debugging.

**Files touched:** `runtime/template_validation/validator.py` (#6 builder + branch), `runtime/engine/loop_control.py`
(#6 comment, #9), `runtime/engine/engine.py` (#5, #2 docstrings), `core/workflow/data_flow.py` (#8),
`cli/commands/run.py` (#3), `guide/features/branching.md` (#3), `runtime/engine/CLAUDE.md` (#4),
`tests/test_runtime/test_loop_control.py` (#7), `tests/test_core/test_loop_validation.py` (#6).
