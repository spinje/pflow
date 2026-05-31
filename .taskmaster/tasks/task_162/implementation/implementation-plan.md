# Plan: `loop:` config block for condition-terminated iteration (issue #445)

## Context

Condition-terminated iteration ("repeat a step until its output drains, capped at N")
is a real, recurring need — the shipped `examples/agent-orchestration/parallel-planner-review/orchestrate.pflow.md`
expresses it today as a **three-node** hand-rolled loop (`tick` counter + `run-cycle`
worker + `check-progress` checker + a backward edge + `?? 1` seeding), and the file's
own prose apologizes for the ceremony. `batch` cannot express this (it needs the count
up front and never stops early). This feature adds a `loop:` config block — sibling to
`batch:` — that collapses that ceremony.

**Outcome:** an author writes one node with a 2-field `- loop:` block; the engine re-runs
that node until a truthiness condition over its own typed output goes falsy or a cap is hit.

This plan was adversarially verified by 6 codebase searchers and hardened by a 4-agent
plan review (validation-consistency, silent-failures, feature-interactions, structure).
The "Review-hardened specifics" notes below are the load-bearing corrections from that review.

## Architecture (decided — see `context/adr/0001-445-loop-engine-reentry.md`)

**Engine re-entry, NOT desugar-to-two-nodes.** After a loop-configured node runs, the engine
evaluates the condition against the node's fresh output; if truthy and under the cap, it
`continue`s with the same `curr` (re-running it) instead of advancing. Re-entry is byte-for-byte
identical to a backward-edge revisit, so it reuses the existing visit-guard + revisit-cache-bypass
and keeps it one node end-to-end.

**Authoring surface** (inline `- loop:` is canonical; fenced ```` ```yaml loop ```` also supported):
```markdown
### run-cycle
- type: workflow
- workflow: ./run-cycle/run-cycle.pflow.md
- inputs: { base_branch: ${base_branch} }
- loop:
    while: ${run-cycle.issues_planned}   # typed output (list/number/bool); falsy → stop; do-while
    max_iterations: ${max_cycles}        # int OR ${template}; cap = INFO advisory + structured marker
```
`${__iteration__}` (1-based) is available in the body, mirroring batch's `${__index__}`.
`loop:` and `batch:` are mutually exclusive on one step.

## Locked decisions

- **Condition = typed-output truthiness, belt-and-suspenders.** Parse-time: reject only a
  *known-string* `while:` source (catches `shell.stdout`; **allows `any`/un-inferable** so the
  motivating sub-workflow example isn't false-rejected). Runtime: after resolving, if the value
  is *still a `str`*, **raise** (don't `bool()` it). Both are required; neither alone is safe.
- **Condition resolution uses `variable_exists()` + `resolve_value()`** — NEVER `resolve_template()`
  (which returns the truthy literal on absent → infinite loop).
- **`${__iteration__}`** dunder (collision-immune; rides the `__index__` machinery); **cleared on
  loop exit** so it can't leak to post-loop nodes.
- **Cache-staleness guard** built in v1 (gated behind Phase 0); lifecycle via try/finally save-restore.
- **`max_iterations`**: literal AND template branches both validated `≥1` and `≤ MAX_NODE_VISITS`;
  the cap counts the loop's *own* iterations (not the shared visit counter).
- **Cap-hit** = stays SUCCESS/exit 0, emits a `Severity.INFO` advisory **plus** a structured marker
  on the loop node output (`loop_stopped: "condition" | "max_iterations"`), surfaced on JSON/MCP too.
- **`storage_mode: shared`** loop bodies are **rejected** at validation (root `__iteration__`/`__execution__`
  collision; matches the existing unsupported-combo precedent).

## Implementation phases (test-as-you-go)

### Phase 0 — De-risk (read-only) — PREREQUISITE GATE for Phase 5
- Empirically resolve "can a node read its own prior output" (Searcher #3 vs #6) — Phase 5's mechanism
  depends on the answer; do not start Phase 5 until resolved.
- Confirm `_default_cache_for_node_type` is llm-only (`compilation/compiler.py:367`).

### Phase 1 — Authoring surface + schema
- `core/markdown_parser.py`: register `loop` in the tag map (~`:103`); route ```` ```yaml loop ```` to
  `node["loop"]` (`_route_code_blocks_to_node` ~`:1178`); hoist inline `- loop:` (`_build_node_dict` ~`:1587`).
  Mirror `batch` exactly (top-level, escapes the params-only unknown-key walk).
- `core/ir_schema.py`: add `LOOP_CONFIG_SCHEMA` beside `BATCH_CONFIG_SCHEMA` (`:80-140`) — `while` (required,
  template pattern), `max_iterations` (`oneOf:[{integer,minimum:1},{template string}]`), `additionalProperties:false`
  (this is the ONLY thing that catches a `whlie:` typo, since `loop` is top-level); wire into the node schema (`:170`).

### Phase 2 — Config object + compile
- `runtime/engine/types.py`: `LoopConfig` dataclass beside `BatchConfig` (`:25-36`); `NodeConfig.loop_config` (`:45`).
- `runtime/compilation/compiler.py::_create_node_and_config` (`:337-362`): build `LoopConfig`; coerce + validate
  the literal `max_iterations` with fail-fast `_coerce_int` (`:452-519`) against `instrumentation.MAX_NODE_VISITS`
  (not literal 100). **Also enforce batch/loop mutual-exclusion here** (raise `CompilationError`) reading
  top-level `node["batch"]`/`node["loop"]` — this covers BOTH the compile path and the validate path.

### Phase 3 — Validation carve-outs ⚠️ (highest silent-drift area)
- `core/workflow/data_flow.py`:
  - Compute `loop_node_ids` (~`:413-418`); thread through `_validate_node_params → _check_param_value →
    _validate_template_reference → _check_forward_reference`.
  - **Self-reference carve-out** in `_check_forward_reference` (`:116-155`): `if ref_node_id == node_id and
    node_id in loop_node_ids: return None`. (A `while:` referencing a *different downstream* node must still be rejected.)
  - **Thread `loop.while` INTO the data-flow ref walk** (`_check_param_value`) so non-existent-node / forward-ref
    checks fire on the condition source (else `while: ${typo.x}` passes silently). *(Review C3 — plan originally missed this.)*
  - Register `"__iteration__"` in `valid_simple_refs` (`:411-425`) when loop nodes exist (global, like `__index__`).
- `core/types.py`: exclude `__iteration__` in `is_template_reserved_internal_key` (`:208-216`) — **must land in the
  same change** as the registration, or the reserved-key ERROR (`data_flow.py:185`) fires first. Add the symmetric
  `${__iteration__.x}` path-access rejection mirroring `__index__` (`data_flow.py:166-218`).
- `runtime/template_validation/validator.py`:
  - Register `__iteration__` in `node_outputs` (model on `_register_batch_item_variables` `:630-651`).
  - **Thread `loop.while` into `_iter_template_operands` (`:371-397`)** so it's path-validated AND so an input used
    only in `while:` isn't false-flagged "unused input". *(Review C3.)*
  - **Typed-output gate (belt half 1):** reject `while:` only when `infer_template_type` returns a *known string*;
    allow `any`/`None`. **Operator rejection:** reject `>`/`<`/`==`/arithmetic in `while:` with a targeted message
    (model on the `${__index__.x}` rejection).

### Phase 4 — Engine re-entry + condition eval + `${__iteration__}` ⚠️
- `runtime/engine/engine.py::_run_inner`: re-entry `continue` between `:396` and `:399`, **normal-return path only**
  (never when `last_action` starts with `error`). Rule: `while:` truthy → re-enter (ignore the node's action);
  falsy → fall through to existing successor routing (loop-then-branch-on-exit works for free). Confirm the `continue`
  re-enters the `while curr:` top so `enforce_loop_guard` fires for visit N+1 (its revisit cache/failure clear is
  load-bearing). **Invariant to document:** the condition is read at this seam precisely because `shared[node_id]`
  holds the just-completed output here, before the next visit's `NamespacedSharedStore.__init__` resets it.
- **Condition evaluator (new small helper):** `variable_exists(path, dict(shared))` → if absent, falsy → stop.
  If present, `resolve_value` (preserves type) → if the result is still `str`, raise a clear diagnostic
  (belt half 2) → else `bool()`. NEVER use `resolve_template`.
- **`max_iterations`:** resolve the template once at loop entry against `dict(shared)`; route the resolved value
  through the SAME `_coerce_int` + `≥1` + `≤ MAX_NODE_VISITS` path as the literal branch (handle `bool`→`int`,
  `0`/neg/non-int with a visible runtime error). Enforce the cap on the loop's own iteration count *before* the
  hard visit guard; resolve against the live `instrumentation.MAX_NODE_VISITS` (env-overridable).
- **`${__iteration__}`:** write `shared["__iteration__"] = <1-based count>` raw-root before each visit
  (mirror `batch_executor.py:330`); **clear it on loop exit** (try/finally) so post-loop nodes can't read it.
- **Cap-hit:** emit a `Severity.INFO` advisory (reuse `partition_surfaced_diagnostics` /
  `execution/formatters/success_formatter.py`) AND set `loop_stopped: "max_iterations"` on the loop node's output
  (`"condition"` on a clean drain); ensure the advisory reaches the JSON/MCP response, not just CLI text.

### Phase 5 — Cache-staleness guard (gated behind Phase 0)
- Reject `loop:` on a `storage_mode: shared` workflow body at validation (Phase 3 sibling check).
- `runtime/engine/engine.py`: set a loop-scoped flag in `shared` (e.g. `__loop_active__`, a depth counter for
  nested loops) before executing a loop body; **clear on ALL exit paths via try/finally**, mirroring the existing
  `__pflow_prompt_cache__`/`__trace_collector__` save-restore (`engine.py:350-361`).
- `runtime/workflow_executor.py`: add the flag to `_PROPAGATED_KEYS` (`:126-134`) so child sub-workflows see it
  (`_create_child_storage` `:677-711`).
- `runtime/engine/instrumentation.py::memo_cache_lookup` (`:213`): suppress inner-node memo reads under the flag,
  **scoped to the loop subtree only** (not run-global). Name the precedence vs an inner `cache: true` override and
  the interaction with prompt-cache (re-installed per child run) and the cross-run SQLite path.

### Phase 6 — Dry-run / `plan.py` parity ⚠️ (rewritten per review C1)
- `plan.py` is a discriminated-union state machine with a `visited_edges` stop-guard (`:432-435`) — re-entry is NOT
  an edge, so a bare "mirror" stops after one pass. Add an explicit loop handling per the documented extension
  contract (new `PlanEntry.status` / `_classify` case / `_advance` arm): plan the body once, **multiply the
  single-pass estimate by the resolved `max_iterations` upper bound** (mark `cost_basis`), including the nested
  sub-plan rollup for a `type: workflow` body. Do NOT rely on `enforce_loop_guard` to drive iteration.
- Tests: keep `test_plan_drift.py` AND `test_plan_classify.py` green; add a **parity test that runs the engine N×
  and asserts the planner predicts N×** (no existing test exercises repeats).

### Phase 7 — Docs + worked example
- `guide/features/branching.md` + `sub-workflows.md`: document `loop:` (inline form canonical); reconcile the three
  "how to loop" stories (fixed-count → `batch`; stop-on-condition → `loop:`; manual backward-edge → "under the hood").
- Port `orchestrate.pflow.md`: honest **3 nodes → 2** (the `loop:` body + a small status node), because the `summary`
  output sourced from the eliminated `check-progress.result.status` (the loop emits no "why it stopped" string —
  the structured `loop_stopped` marker + advisory carry that now). Declare the child's `issues_planned` output as
  `array` so the flagship `while:` source is positively typed. Add a regression test (model on
  `tests/test_integration/test_loop_example.py`).

### Mid-implementation checkpoint
Run `/code-review` (staged) **after Phase 4** — Phases 3–5 are the cross-layer, highest-bug-density work; catch
re-entry/namespace/cache bugs before Phase 5 builds on them.

## Verification

- `make test` and `make check` clean.
- **Unit**: parser (both forms → `node["loop"]`); schema (valid + `whlie:` typo + bad `max_iterations`); compiler
  (`LoopConfig` built; literal AND template `max_iterations > MAX_NODE_VISITS`/`0`/neg/non-int rejected; both/batch+loop → `CompilationError`).
- **Validation matrix** (`--validate-only`): valid loop passes; `while: ${shell.stdout}` rejected (known-string);
  `while: ${child_wf.untyped_output}` **passes** (`any`); `while: ${x} > 0` rejected (operator); self-ref in `while:`
  passes for the loop node, still rejected for a non-loop node and for a different downstream node; `${__iteration__.x}` rejected;
  `loop:` on `storage_mode: shared` rejected; input used only in `while:` NOT flagged "unused".
- **Integration** (`WorkflowRunner`): drain-to-empty (stops on falsy); **first-iteration present-absent key → stops after 1**
  (the resolver's absent path); single-iteration (present-but-falsy); error-mid-loop (stops, FAILED in `failed_node_ids`);
  loop-then-branch (custom exit action routes; intermediate iterations don't leak it); `${__iteration__}` 1-based in body;
  **post-loop node cannot read `${__iteration__}`**; runtime str-condition raises (not silent loop); cap-hit (SUCCESS/exit 0,
  INFO advisory present in JSON, `loop_stopped: "max_iterations"` on output); cap-hit with lowered `PFLOW_MAX_NODE_VISITS`.
- **Cache** (Phase 5): nested staleness repro converges (activation); **a sibling cached node AFTER the loop still caches** (deactivation).
- **Dry-run**: `test_plan_drift` + `test_plan_classify` pass; engine-N× == planner-N× parity test; loop reports upper-bound cost.
- **End-to-end**: run the ported `orchestrate.pflow.md`; confirm it loops, converges, and the structured marker is present.
