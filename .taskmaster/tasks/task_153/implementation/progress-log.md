# Implementation progress log — silent drop of undeclared sub-workflow inputs + IR cache heterogeneous-batch bug

**Branch**: `fix/silent-drop-undeclared-inputs`
**Plan file**: `/Users/andfal/.claude/plans/linked-discovering-haven.md`
**Outcome**: 4643 tests pass, `make check` clean, both motivating bugs fixed end-to-end, GitHub issue #283 filed for visualizer follow-up.

This log captures **insights and decisions made during implementation** — not a blow-by-blow diff narrative. The goal: help a future reader (possibly me) understand *why* the final code looks the way it does and what cost-benefit trade-offs were made.

---

## Scope surprises (where the plan diverged from reality)

### Commit 3 (`workflow_ir` removal) was 6x larger than the searcher estimated

The pflow-codebase-searcher's Phase-1 audit said: *"Exactly one place authors it in markdown (`test_conditional_branching.py:943-957`). Net test migration: ~5 Python fixture sites."* The plan was sized around that.

The reality: **33 test failures across 7 files** after removing `workflow_ir` support. Root cause the searcher missed — `workflow_ir` was used pervasively as a *convenience shortcut* in direct IR-dict construction inside test files, not just in the one markdown fixture:

```python
# Scattered across test_integration.py, test_workflow_executor_comprehensive.py,
# test_metrics_propagation.py, test_batch_node.py, test_cache_opt_out.py, etc.
executor.params = {"workflow_ir": ir_dict, ...}
```

The searcher correctly grep'd for *"places that author `- workflow_ir:` in markdown."* It did not grep for *"places that construct Python dicts with `\"workflow_ir\"` as a key."* Those two populations are wildly different.

**Resolution**: added a small `_write_child(tmp_path, ir_dict, name)` helper per affected test file and mechanically converted each site. Tests specifically testing removed XOR behavior (e.g. `test_workflow_and_workflow_ir_raises_error`, `test_workflow_ir_only`, `test_both_parameters_provided`) were deleted as obsolete rather than rewritten.

**Meta-lesson**: searcher estimates of migration scope are reliable for the *kind of use* they were asked about, not for *all kinds of use*. Next time a W-style removal is planned, ask two questions: "where is this feature authored by users" AND "where is this feature used as a test convenience." They're different.

### Migration (Commit 2) cascaded into Mermaid golden files

Migrating child-input passing from top-level params to `inputs:` dict broke the mermaid visualizer's fidelity — it only traces templates in top-level string params, not inside dict values. The golden files needed regeneration, which was expected. What was NOT expected: the regenerated diagrams were *materially less useful* (coarser edges). Not a bug per se — the visualizer just didn't cover the new canonical shape.

**Resolution**: regenerated goldens, shipped the coarser diagram, filed [issue #283](https://github.com/spinje/pflow/issues/283) with full root-cause analysis, before/after example, and proposed fix pointing at `_edges.py:216-252` and the existing `_collect_param_refs` helper at `_context.py:271` as reuse precedent.

**Meta-lesson**: any time a canonical shape for a user-authored construct changes, audit every consumer that parses that construct — not just the runtime. Visualizers, validators, and tooling that *read* the shape are easy to miss.

---

## Key implementation decisions (with alternatives considered)

### Closed schema via `ALLOWED_PARAMS` class attribute (Option D), not scanner registration (A) or targeted validator method (B)

The searcher's Phase-2 design exploration surfaced three options:

- **A** — Register `WorkflowExecutor` in the node scanner like every other node type. Would restructure the file's location (`runtime/` vs `nodes/`), risking circular imports with `compile_workflow`.
- **B** — Add a targeted `_validate_unknown_workflow_params` method in the validator. Small diff, permanent special case in validator forever.
- **D** — Declare allowed params via `ClassVar[frozenset[str]]` class attribute; validator Step 7 reads it directly.

The user's directive *"prioritize simplicity of the final code, not how easy it is to get there"* drove the choice:
- A touches an architectural boundary (file location / circular imports) for a single node type.
- B leaves a special case in the validator forever that a future refactor must remove.
- D is mechanism-agnostic — any future schema-declaration refactor (Pydantic / decorator / `__init_subclass__`) either generates `ALLOWED_PARAMS` or replaces it cheaply, and the validator branch becomes "legacy fallback" that also gets deleted.

**Why this is a load-bearing decision**: the user explicitly plans a broader refactor to replace the docstring-`Interface:` regex-parsing mechanism. D is the smallest possible step that's forward-compatible with any direction that refactor takes.

### Kept `RESERVED_PARAMS` frozenset — then deleted it entirely

Commit 3's plan was to *shrink* `RESERVED_PARAMS` (remove `workflow_ir`). Commit 4 then considered: since `inputs:` is the only canonical way to pass child inputs, does the frozenset still have a purpose?

Answer: no. The frozenset existed solely to distinguish "framework knob" from "user-provided child input" at the top level. With `_extract_child_inputs` simplified to `return dict(self.params.get("inputs", {}))`, there's no open-ended top-level forwarding to filter. Deleted entirely.

**Lesson**: the `RESERVED_PARAMS`-as-blocklist pattern was a symptom of having two mechanisms for the same job. Collapsing to one mechanism eliminated the blocklist's reason to exist. Future readers: if you see a `RESERVED_PARAMS`-style blocklist, check whether it's guarding against *multiple ways to do the same thing* — that's the real smell.

### Renamed internal `prep_res["workflow_ir"]` → `"child_ir"` only during "easy wins" cleanup, not in Commit 3

Commit 3 (user-facing `workflow_ir` removal) consciously left the *internal* `prep_res["workflow_ir"]` key untouched to contain scope. During the post-implementation honest-audit round, I flagged this as cognitive-debt (I had literally written a test comment explaining "this is an internal key, distinct from the removed user-facing param"). When the user asked "any easy wins here?", I did the rename.

**Lesson**: comments that explain naming collisions are a signal that the code could be renamed instead. Future readers who see a comment like "this field is distinct from the removed X param" should treat that as a latent rename opportunity.

### Simplified `_compile_sub_workflow` cache-key logic from fake-key trick to explicit `cacheable` flag

Original code used `cache_key: Any = workflow_path if cacheable else f"<inline:{id(workflow_ir)}>"` — a "fake key" for the un-cacheable edge case. Simplified to an explicit `cacheable` boolean gating three things consistently (cache read, `_pflow_workflow_file` injection, cache writeback). The edge case (saved name with no on-disk file) simply skips caching; compilation cost is negligible for that case.

**Lesson**: unified cache-key paths that require a fake sentinel value are usually less clear than a two-branch structure (cacheable / not cacheable) where the two branches are visually distinct.

### Did NOT align parse-time vs runtime error wording

Parse-time extras error (structured `Diagnostic`): `"Step 'X': sub-workflow 'Y' does not declare input 'Z' (passed via inputs: dict)."`

Runtime extras error (prose `ValueError`): `"Child workflow 'Y' was passed undeclared input(s): Z.\nThe child declares: a. Either declare..."`

Explicitly chose NOT to align these because:
1. The existing **missing-required** pattern already has the same shape divergence (parse = `Diagnostic`, runtime = `ValueError` prose). Aligning extras but not missing would be a *local* inconsistency.
2. Not a code simplification — purely rewording. No reduction in branches/concepts.
3. If a future refactor unifies runtime-error-raising patterns across the codebase, it'd sweep all of them at once. Fixing just extras-wording now would be undone.

**Lesson**: "inconsistency that mirrors an existing inconsistency" is not the same problem as "new inconsistency I just introduced." Resist the urge to locally fix the former.

### Added the runtime-extras test even though the validator normally catches extras first

The runtime check at `_validate_child_params` is defense-in-depth for:
- **Heterogeneous-batch opaque-template case** — `inputs: ${item}` resolves to a dict only at runtime; parse-time skips the static check; runtime is the ONLY line of defense.
- **Programmatic API callers** — code that constructs `WorkflowExecutor` directly without running `WorkflowValidator.validate` first.

Before the test, the docstring *claimed* defense-in-depth but no test verified the runtime loop ever fired. A future cleanup could have silently deleted the runtime loop as "unused" and introduced a silent regression for the opaque-template case.

**Lesson**: a code comment that claims "defense-in-depth against X" is a contract, and contracts without tests rot. The 15-line positive+negative-control test locks in the claim.

---

## Patterns that worked well

### Per-commit verification gate

Each of the 5 commits ran `uv run pytest` before moving to the next. Commit 3's 33 failures surfaced before Commit 4's work started, letting me contain the scope-surprise impact. If I had batched Commits 3+4 together, I'd have been debugging schema-closure issues inside a cascade of `workflow_ir`-removal failures.

### Tests that exercise behavior via the real execution pipeline (`WorkflowRunner`), not mocks

`tests/test_runtime/test_workflow_executor/test_ir_cache.py::test_heterogeneous_batch_loads_correct_child_ir` runs two different children through a real `WorkflowEngine` with `parallel: false` and asserts on distinct shell outputs per item. This caught the searcher's reproduced Bug B cleanly because it's end-to-end. Matching tests in parallel mode (`test_heterogeneous_batch_parallel`) cover the pre-warm deepcopy path.

Contrast with unit tests that mock `compile_workflow` — those verified the cache *mechanics* but didn't exercise the heterogeneous-batch *behavior* users actually care about. Both kinds are useful; the end-to-end ones are the regression guards that matter.

### Reusing existing diagnostic infrastructure for the new extras check

`validator._check_required_inputs` already produced structured `Diagnostic` objects with `available_fields`, `similar_names` (via `find_similar_items`), `path`, etc. The extras loop was a copy-paste of that shape in the inverse direction. No new rendering, no new renderer branches. Agents get the same "Did you mean X" fuzzy suggestion for extras as they do for missing required.

---

## Patterns to flag for future work

### Docstring `Interface:` regex parsing as schema declaration

The existing Step-7 mechanism depends on regex-parsing strings out of node docstrings. This is known tech debt (user wants to refactor). Fragile points:
- Metadata extractor sometimes parses `(optional, default: value)` as a separate `key: "default"` param (flagged in `src/pflow/guide/CLAUDE.md`).
- No static analyzer can catch docstring/implementation drift.
- Workflow node bypasses this mechanism entirely (hence this bug existed in the first place).

`ALLOWED_PARAMS` as a `ClassVar[frozenset[str]]` is the first migrant to a more introspectable pattern. A future refactor should sweep every node type onto a common mechanism (options: Pydantic models, `__init_subclass__` hooks, decorator-based registration). Until that sweep, **new node types should declare `ALLOWED_PARAMS` alongside their docstring Interface** so they inherit the forward-compat path.

### Mermaid visualizer fidelity ([issue #283](https://github.com/spinje/pflow/issues/283))

Filed separately. The visualizer only traces templates in top-level string params; it should descend into `inputs:` dicts to restore per-child-input edge fidelity. The existing `_collect_param_refs` helper at `_context.py:271` handles one level of nested dicts (for code nodes) and is the obvious reuse precedent.

### `"<inline>"` sentinel in `prep_res["workflow_path"]`

Post-W3 this label no longer means "inline IR" — it means "saved name with no on-disk file" (an edge case). The name is misleading. Renaming cascades into `exec()`, `post()`, trace recording, and the compile cache's cacheable-check. Medium-sized follow-up, not blocker.

---

## Verification evidence

### Automated
- **4643 tests pass** (4641 baseline + 2 new runtime-extras tests).
- `make check` clean (ruff, mypy, deptry).
- Four new regression tests specifically target the two motivating bugs:
  - `test_ir_cache_hits_on_same_ref`, `test_ir_cache_miss_on_different_ref` — cache key correctness (Bug B).
  - `test_heterogeneous_batch_loads_correct_child_ir`, `test_heterogeneous_batch_parallel` — end-to-end Bug B fix.
  - `TestUndeclaredExtras::test_workflow_extras_top_level_rejected`, `test_workflow_extras_in_inputs_rejected`, `test_workflow_extras_with_template_inputs_deferred` — Bug A parse-time.
  - `test_undeclared_extras_in_inputs_dict_rejected_at_runtime`, `test_runtime_extras_not_raised_when_all_keys_declared` — Bug A runtime defense-in-depth.

### Manual end-to-end
- **Bug A reproduction failed at parse time as expected**:
  ```
  $ uv run pflow scratchpads/undeclared-workflow-input-drop/repro-files/parent-extra.pflow.md --validate-only
  ✗ Validation failed (1 error):
  Error 1: Validation Error
  Step 'call-child': sub-workflow './child-minimal.pflow.md' does not declare input 'b' (passed via inputs: dict).
    At: node 'call-child', nodes[id=call-child].params.inputs.b
    Sub-workflow: ./child-minimal.pflow.md
    Available declared inputs (showing 1 of 1): - a
  ```

- **Bug B heterogeneous batch produces per-child output**:
  ```
  $ uv run pflow scratchpads/undeclared-workflow-input-drop/repro-files/parent-batch-hetero.pflow.md
  ✓ Workflow completed in 0.026s
  [{"result": "a=shared_a_value", ...}, {"result": "a=shared_a_value b=shared_b_value", ...}]
  ```
  Child A correctly received only `a`; child B correctly received both `a` and `b`.

---

## Delta from plan

| Plan estimate | Actual | Reason |
|---|---|---|
| ~5 Python test fixture sites to migrate | ~33 test sites | Searcher missed dict-IR-construction sites; see Scope surprises above. |
| ~150 LoC net changes | Unknown — too many files | Mostly offset by deletions (`RESERVED_PARAMS`, XOR checks, inline-IR branches, `_extract_child_inputs` collapse). |
| 5 commits | 5 commits delivered | Order preserved. |
| "One mechanical pass" migration | Mechanical but not trivial per-file | Each test file needed a local helper + per-test conversion. |
| Mermaid golden updates trivial | Trivial but revealed fidelity regression | Issue #283 filed. |

---

## Files touched (summary)

### Code (10 source files)
- `src/pflow/runtime/workflow_executor.py` — `ALLOWED_PARAMS` declared; `RESERVED_PARAMS` deleted; `_extract_child_inputs` collapsed to one line; runtime extras check added; IR cache keyed by path; `_compile_sub_workflow` cache logic simplified; `workflow_ir` support removed.
- `src/pflow/core/workflow/validator.py` — Step-7 workflow-node branch reading `ALLOWED_PARAMS`; `_check_required_inputs` grown inverse extras loop with fuzzy suggestions; `workflow_ir` branch in `_load_child_workflow` removed.
- `src/pflow/core/workflow/sub_workflow_resolver.py` — inline-IR resolution path removed.
- `src/pflow/runtime/template_validation/validator.py` — `workflow_ir` output-resolution branch removed.
- `src/pflow/core/workflow/mermaid/_context.py` — `"workflow_ir"` removed from `_RESERVED_PARAMS`.
- `src/pflow/runtime/engine/batch_executor.py` — pre-warm cache uses new attribute names; docstring updated.
- Four docs files: `src/pflow/guide/features/sub-workflows.md`, `src/pflow/runtime/CLAUDE.md`, `src/pflow/core/workflow/CLAUDE.md` — new canonical form + heterogeneous-batch named example + Step 7/8 coverage notes.

### Migrations (10 nodes across 8 `.pflow.md` + 5 Python fixture sites)
See `files_touched` in the plan. All `.pflow.md` examples under `examples/nested/`, `examples/bundling/`, and the scratchpad repros rewritten to `inputs:` form.

### New test files / additions
- `tests/test_runtime/test_workflow_executor/test_ir_cache.py` (new file) — cache-key correctness + end-to-end heterogeneous batch.
- `tests/test_core/test_sub_workflow_validation.py::TestUndeclaredExtras` (new class, 3 tests) — Bug A parse-time coverage.
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — 2 new runtime-extras tests alongside existing `_validate_child_params` tests.

### Deletions
- `test_integration/test_workflow_manager_integration.py::test_workflow_executor_mutual_exclusivity` — tested removed XOR.
- `test_core/test_sub_workflow_resolver.py::test_inline_ir` — tested removed feature.
- `test_runtime/test_workflow_executor/test_workflow_name.py::test_workflow_and_workflow_ir_raises_error` — tested removed XOR.
- `test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py::test_workflow_ir_only`, `test_both_parameters_provided`, `test_malformed_child_ir_context` — tested removed inline-IR path.
- `test_core/test_sub_workflow_validation.py::TestInlineWorkflowIR` (class) — tested removed recursive inline-IR validation.

### GitHub artifacts
- [Issue #283](https://github.com/spinje/pflow/issues/283) filed for mermaid visualizer fidelity regression with full root-cause analysis and proposed fix.

---

## What I'd do differently

1. **Mutation-test the runtime check earlier**. I wrote `_validate_child_params`'s extras loop in Commit 4 but didn't verify it was reachable by any test until after the user asked "should we fix the runtime test loose end?" Writing the positive test at Commit-4 time (not as a follow-up) would have caught any dead-code issue immediately.

2. **Verify searcher scope estimates with a spike before committing to the plan.** Before Commit 3, run a `grep -rn "workflow_ir" tests/` and eyeball the output for 30 seconds. Would have surfaced the 33-site blast radius in the planning phase, not the implementation phase.

3. **Check visualizer / tooling output against canonical-shape changes as part of migration, not as an afterthought.** The mermaid regression would have been caught in the plan-review phase if "what downstream tools parse this shape?" had been an explicit planning checkpoint.

## What I got right

1. **Per-commit verification gate** contained the scope surprise in Commit 3. Catastrophic if Commits 3+4 had been batched.

2. **Choosing `ALLOWED_PARAMS` (Option D) over scanner registration (A) or validator method (B).** The user's "final state simplicity" directive was the decisive tiebreaker, and the choice compounds well with the planned schema-declaration refactor.

3. **Deleting `RESERVED_PARAMS` entirely rather than shrinking it.** The frozenset's existence *was* the symptom of the dual-mechanism problem. Collapsing to `inputs:`-only made it vestigial. Seeing the shrink → delete opportunity required following the "simplicity of final code" directive past the minimum-viable fix.

4. **Filing issue #283 rather than attempting to also fix the mermaid visualizer.** Scope discipline. Visualizer fidelity is a real UX cost but belongs in its own contained PR with its own tests and its own golden-file regeneration.

5. **Running the "easy wins" pass after the user asked.** The prep_res-key rename and cache-logic simplification were small but real final-state improvements. Without the explicit prompt I would have shipped the code with the cognitive debt.
