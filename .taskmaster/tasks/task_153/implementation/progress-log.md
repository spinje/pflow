# Implementation progress log — silent drop of undeclared sub-workflow inputs + IR cache heterogeneous-batch bug

**Branch**: `fix/silent-drop-undeclared-inputs`
**Plan file**: `/Users/andfal/.claude/plans/linked-discovering-haven.md`
**Outcome**: three commits (initial implementation + two review-cycle follow-ups); 4763 tests pass, `make check` clean; both motivating bugs fixed; the full parent→child silent-failure surface closed (including non-dict `inputs:` shape); GitHub issue #283 filed for mermaid visualizer follow-up.

**Commits on this branch**:
- `9eedbd1f` — core fix (schema closure, W3, IR cache, migration).
- `2daee665` — review cycle part 1 (11 silently-passing test sites migrated, 4 cleanups).
- `80776a24` — review cycle part 2 (non-dict `inputs:` parse-time + runtime diagnostic, stale comment).

This log captures **insights and decisions made during implementation AND the subsequent code-review cycle** — not a blow-by-blow diff narrative. The goal: help a future reader (possibly me) understand *why* the final code looks the way it does and what cost-benefit trade-offs were made.

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

## Post-implementation review cycle

After the initial 5-commit implementation landed, a code-review pass deployed **4 specialist agents** (not the full 7-agent battery): `review-impact-completeness`, `review-feature-interactions`, `review-validation-consistency`, `review-test-fidelity`. Skipped: `review-silent-failures` (this PR IS the silent-failure fix — low marginal signal), `review-agent-ux` (diagnostics already reviewed manually in-conversation), `review-concurrency-safety` (parallel batch covered by explicit regression tests). Choice worked: all four deployed agents produced distinct findings with no redundant coverage, and between them they surfaced issues neither the plan nor the implementer caught.

The review cycle produced **two additional commits** that addressed everything actionable before merge.

### Scope surprise — second wave: 11 more silently-passing test sites

The Commit-3 "33-site miss" (documented under Scope surprises) was real but *incomplete*. The review pass found **11 additional test sites that passed the green suite but no longer exercised what they claimed to test**. Three distinct failure modes:

- **7 sites in `tests/test_runtime/test_template_validation/`** (6 in `test_validator.py`, 1 in `test_batch_item_validation.py`) — same pattern as the 33-site miss (dict literal with `"workflow_ir"` as key), different directory. Post-W3, `_resolve_child_workflow_outputs` returned `None` for `workflow_ir`-only nodes, silently taking the permissive skip-results-structure fallback. Mutation-verified: `${process-all.results[0].BOGUS}` produced 0 errors. Tests claimed to guard child-output field validation; they guarded nothing.
- **3 sites in `tests/test_integration/test_unused_inputs.py`** — a DIFFERENT failure mode: the tests called `split_validator_diagnostics(...)` *without* the `registry=` argument, which silently skipped Step 7 (`if registry is not None` short-circuit at `validator.py:131`). Tests diverged from production validation. Not a "removed feature" issue — an "optional parameter silently disables a validator step" API issue.
- **1 site in `tests/test_runtime/test_workflow_executor/test_integration.py::test_file_workflow_execution`** — a THIRD failure mode: bypassed `WorkflowValidator` entirely by calling `compile_workflow` directly. Passed `test_input` as top-level param (silently dropped post-task-153), only assertion was `result == "default"` which passed regardless of whether any input flow occurred. Exact pattern the task-59 retrospective flagged ("tests that only check execution flow, not actual mapping").

**Meta-lesson (deepened from the original Commit-3 lesson)**: test-fidelity audits for a removed feature need to grep **three** shapes, not just the one the initial searcher covered:

1. **Authoring shape** — markdown fixtures referencing the feature.
2. **Dict-construction shape** — Python dicts using the string key as a test convenience, across **ALL** test directories (runtime-executor + template-validation + any tree touching the same IR shape).
3. **Bypass-path shape** — tests that skip the validator entirely (via `compile_workflow` directly, OR via optional-parameter omission that silently disables a validator step).

The original audit covered (1) fully and (2) partially. The review cycle caught the remainder of (2) and all of (3). Next time: global-grep the raw string key across every test directory upfront, and additionally audit test-helper call sites for optional-parameter omission that disables validation.

Fix for all 11 sites (commit `2daee665`) was mechanical: file-backed child fixtures with `inputs:` dict form. Mutation re-check confirmed the critical test (`test_workflow_batch_inner_outputs_in_results`) now actually fails on `BOGUS`.

### Judgment call: folded the non-dict `inputs:` diagnostic into this PR

`review-validation-consistency` found three angles (W-2, S-1, S-3) on the same gap: when `inputs:` is set but isn't a dict (literal typo `- inputs: foo`, or `inputs: ${item}` resolving to a list/string/number), today's code silently discards it and downstream fires a misleading "missing required input" error that blames the *child's declarations*, not the *parent's `inputs:` shape*.

Scope discipline argued for deferring — the original bug report didn't ask for this. Folded in anyway (commit `80776a24`) because:

1. **Same surface as Bug A.** Task 153's stated goal is closing silent-failure at the parent→child boundary. This is another silent-failure on the same surface.
2. **Fix is small**: ~10 lines of code + 4 new tests. Two-tier defense (parse-time for literals, runtime for templates resolving to wrong shape) matches the established PR pattern.
3. **Splitting to stay "scope-pure" is fake discipline when the in-spirit fix is small and caught by the same review cycle**. A separate PR would mean two review rounds for what one caught.

**Meta-rule (new)**: when a review surfaces a diagnostic gap **in the surface you just fixed**, fold it in unless the fix is big. The anti-pattern is reflexive "defer to follow-up" which creates lost context and duplicate work. Counter-rule (when NOT to fold): if the fix touches a different subsystem, OR depends on a future refactor's shape (see `framework_keys` below), defer is correct.

**Wording divergence between parse-time and runtime is deliberate**: parse-time blames the literal (`"must be a dict, got str"`), runtime hints at the template (`"resolved to str, expected dict"`). Matches the existing parse/runtime wording divergence for missing-required and extras. Future unification belongs in a dedicated runtime-errors-→-structured-Diagnostics sweep, not this task.

### Deferrals — what review surfaced but did NOT land in this PR

- **`framework_keys = frozenset({"inputs"})` at `validator.py:583` is defensive-but-doing-no-work** (validation-consistency W-1). Every node type that uses `inputs:` declares it in its Interface; the safety net never triggers today. Deferred to the planned **schema-declaration refactor task** because fixing it cleanly depends on knowing the refactor's shape (is `inputs` always framework-provided? Always node-declared? Both paths?). Folding in now would likely double-work when the refactor lands. *This is the counter-example to the "fold in diagnostic gaps" meta-rule above — the difference is that this one depends on a future decision.*
- **Mermaid visualizer fidelity** — GH #283, filed during initial implementation. Visualizer traces templates in top-level string params; doesn't descend into `inputs:` dict values. Structural issue, separate PR.
- **`"<inline>"` sentinel rename** — progress-log tracked above.
- **Minor nits** deemed not worth a commit: MCP `workflow` dict-arg vs removed node-param `workflow_ir` distinction (doc nit), `_loaded_ir_cache` attribute probe in tests (reviewer said acceptable as diagnostic-on-failure), pre-warm O(K) compile-budget docstring note (current text already accurate), changelog v0.12.0 entry (release-time).

### Third review round — post-rebase PR comment caught a real `None`-handling gap

After the rebase onto main (which added one commit, `a7494d6d`, for stdout routing), the PR's code-review bot commented with a warning: `_validate_child_params` — now that task 153 removed its early-return on empty declarations — crashes with `AttributeError` if `workflow_ir["inputs"] = None`. Reviewer suggested one-line `or {}` hardening matching the defensive pattern at `validator.py:403`.

My first-pass analysis over-engineered it. I pattern-matched into "the WHOLE codebase has this crash class, let's sweep all consumer sites" (mapped 9 crash sites across runtime/template_validation/formatters/mermaid/data_flow). Proposed three options: narrow fix (reviewer's scope), consumer sweep (all 9), or upstream normalization in `normalize_ir`.

The user pushed back: *"we should prioritize simplicity of the final code — what's the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"*

That forced a re-verification, which flipped two of my claims:

- **Parser does NOT produce `inputs: None`**. My earlier "empirical test" used `.get("inputs")` without a default, which returned `None` from the missing-default fallback — not from an explicit `None` value. The key is simply ABSENT when `## Inputs` has no declarations, so `.get("inputs", {})` correctly returns `{}`. User-authored markdown is not affected.
- **The IR schema already rejects `inputs: null` cleanly.** At `ir_schema.py:225`, `inputs` is declared `type: object`. Step 1 of the validation pipeline produces `"Validation error at inputs: None is not of type 'object'. Change type from 'NoneType' to 'object'"` before any downstream consumer sees `None`. This is the top-10% "typed boundary" pattern already in place for user-authored IR.

**The actual gap**: programmatic callers (MCP server, direct Python API, tests constructing executors with crafted IR) bypass `WorkflowValidator.validate` entirely. They reach `_validate_child_params` with whatever `workflow_ir` shape they built. Before task 153 the early-return absorbed the `None` case; after task 153 it crashes.

**Top-10% answer**: boundary coerces, body trusts. The schema is the typed boundary for user-authored IR; the runtime `_validate_child_params` is the typed boundary for bypass callers. Both must coerce `None → {}` at their input, then the body can trust `dict[str, Any]`. The 9 "crash sites" I mapped are downstream of the schema boundary — they're already guaranteed not to see `None` from user-authored paths. Sweeping them would be "every consumer defends against its own type violations," the anti-pattern typed boundaries are supposed to eliminate.

**Fix applied**: two-character `or {}` edits at the runtime boundary (`workflow_executor.py:493`) and its parse-time sibling (`validator.py:769`); one regression test verifying that a crafted `workflow_ir["inputs"] = None` with extras raises `ValueError: undeclared input(s)` (clean diagnostic, not `AttributeError`); mermaid known-regression comment hoisted from above `@parametrize` into the test function docstring so it surfaces in pytest verbose output when goldens next regenerate. Mutation-verified: reverting the runtime fix makes the new test fail with `AttributeError` immediately.

**Meta-lessons from this round**:

- **Distrust your own "empirical" claims. Verify the verification.** My `.get("inputs")` output (`None`) looked like proof the parser produces `None`, but it was proof of nothing — the missing-default fallback returns `None` when the key is absent. One extra line (`"inputs" in ir`) would have caught it. When claiming "I empirically verified X," double-check the primitive actually tests what you think it does.
- **When pattern-matching into a sweep, check whether the structural boundary already handles it.** IR schema validation + Step 1 was ALREADY the "top 10%" structural fix. I proposed a redundant parallel fix at `normalize_ir` and a 9-site consumer sweep without first checking that the boundary already catches it. The user's "top 10%" question was the forcing function that made me recheck.
- **"Boundary coerces, body trusts" is the right architectural frame** — the schema boundary and the runtime-bypass boundary BOTH need tolerance at their input edges, but their bodies (and every layer below) can assume a clean `dict[str, Any]`. This is the actual answer to the top-10% question for this class of problem.

### Small cognitive-debt cleanups folded into the review-cycle commits

- Regex tightening: `match="undeclared input"` → `match=r"undeclared input\(s\)"` — anchors on the exact token so a wording drift to a *different* error category doesn't still pass.
- Post-W3 comment drift on `test_inputs_dict_values_forwarded`: "Also reserved" was a pre-task-153 phrasing; updated to describe the post-task-153 semantics (top-level fields never leak into inputs).
- Pre-existing-debt tests with never-valid param keys (`workflow_ref`, `output_mapping`, `workflow_path`): replaced with canonical `workflow:` references. These keys were never valid; the closed schema made them *stranded*, so fixing them matches the schema-closure direction.
- Stale `__`-prefix comment on `ALLOWED_PARAMS` rewritten to describe actual behavior (framework keys are compiler-injected into params, not honored via a prefix convention by Step 7).
- `test_ir_cache_hits_on_same_ref` gets a one-line comment documenting why each `prep()` call uses a fresh `shared` dict (parser-diagnostic double-propagation prevention).

---

## Verification evidence

### Automated
- **4763 tests pass** post-review-cycle (4641 baseline + 9 net new + 11 migrated [not net-new; replacing silently-passing sites with ones that actually test their contract]).
- `make check` clean (ruff, mypy, deptry).
- Regression-test additions across the three commits:
  - **Implementation commit** — Bug A + Bug B coverage:
    - `test_ir_cache_hits_on_same_ref`, `test_ir_cache_miss_on_different_ref` — cache key correctness (Bug B).
    - `test_heterogeneous_batch_loads_correct_child_ir`, `test_heterogeneous_batch_parallel` — end-to-end Bug B fix.
    - `TestUndeclaredExtras::test_workflow_extras_top_level_rejected`, `test_workflow_extras_in_inputs_rejected`, `test_workflow_extras_with_template_inputs_deferred` — Bug A parse-time.
    - `test_undeclared_extras_in_inputs_dict_rejected_at_runtime`, `test_runtime_extras_not_raised_when_all_keys_declared` — Bug A runtime defense-in-depth.
  - **Review-cycle commit 1 (`2daee665`)** — 11 silently-passing sites migrated to file-backed fixtures + `inputs:` dict form; mutation-verified the critical `test_workflow_batch_inner_outputs_in_results` now actually fails on `BOGUS`.
  - **Review-cycle commit 2 (`80776a24`)** — 4 new tests for non-dict `inputs:` shape handling:
    - `TestNonDictInputsShape::test_non_dict_inputs_literal_string_rejected`, `test_non_dict_inputs_list_rejected` — parse-time.
    - `test_inputs_non_dict_raises_shape_error`, `test_inputs_none_treated_as_no_inputs` — runtime `_extract_child_inputs` behavior.
    - Plus assertion extension on `test_workflow_extras_with_template_inputs_deferred` to verify opaque template doesn't trigger the new shape diagnostic.

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

- **Non-dict `inputs:` parse-time diagnostic fires** (review-cycle commit 2):
  ```
  $ uv run pflow /tmp/task153-shape-check/bad-inputs.pflow.md --validate-only
  ✗ Validation failed (1 error):
  Step 'call-child': 'inputs:' on workflow node './child.pflow.md' must be a dict of child inputs, got str.
    At: node 'call-child', nodes[id=call-child].params.inputs
    → Use a mapping: ``- inputs:\n    key: value``
  ```

- **Non-dict `inputs:` runtime diagnostic fires** when an opaque template resolves to the wrong shape:
  ```
  $ uv run pflow /tmp/task153-shape-check/bad-template.pflow.md
  Workflow node's 'inputs:' resolved to str, expected dict of child inputs.
  ```

---

## Delta from plan

| Plan estimate | Actual | Reason |
|---|---|---|
| ~5 Python test fixture sites to migrate | ~33 test sites in implementation + 11 more found in review | Searcher's audit covered dict-IR-construction in one test tree but not across all test directories; see Scope surprises (first wave) and Post-implementation review cycle (second wave). |
| ~150 LoC net changes | Unknown — too many files | Mostly offset by deletions (`RESERVED_PARAMS`, XOR checks, inline-IR branches, `_extract_child_inputs` collapse). |
| 5 commits | **3 commits** delivered (core + 2 review-cycle follow-ups) | Plan had 5 phased commits; reality squashed the implementation into one coherent commit and added 2 review-cycle commits. Final ordering = `core fix` → `review test-fidelity fixes` → `review diagnostic improvements`. |
| "One mechanical pass" migration | Mechanical but not trivial per-file | Each test file needed a local helper + per-test conversion; review pass found 11 more sites in the same shape that the initial pass missed. |
| Mermaid golden updates trivial | Trivial but revealed fidelity regression | Issue #283 filed during implementation. |
| No post-implementation code review scoped in the plan | Review cycle surfaced a critical test-fidelity cluster (11 silently-passing sites) + a diagnostic-quality gap worth folding in | The plan treated "`make check` + `pytest` green" as sufficient verification. Mutation-resistant code review found issues neither static analysis nor the test suite could surface. Future plans of this size should scope a specialist-agent review pass as a standard phase. |

---

## Files touched (summary)

### Implementation commit (`9eedbd1f`) — code

- `src/pflow/runtime/workflow_executor.py` — `ALLOWED_PARAMS` declared; `RESERVED_PARAMS` deleted; `_extract_child_inputs` collapsed to one line; runtime extras check added; IR cache keyed by path; `_compile_sub_workflow` cache logic simplified; `workflow_ir` support removed.
- `src/pflow/core/workflow/validator.py` — Step-7 workflow-node branch reading `ALLOWED_PARAMS`; `_check_required_inputs` grown inverse extras loop with fuzzy suggestions; `workflow_ir` branch in `_load_child_workflow` removed.
- `src/pflow/core/workflow/sub_workflow_resolver.py` — inline-IR resolution path removed.
- `src/pflow/runtime/template_validation/validator.py` — `workflow_ir` output-resolution branch removed.
- `src/pflow/core/workflow/mermaid/_context.py` — `"workflow_ir"` removed from `_RESERVED_PARAMS`.
- `src/pflow/runtime/engine/batch_executor.py` — pre-warm cache uses new attribute names; docstring updated.
- Docs: `src/pflow/guide/features/sub-workflows.md`, `src/pflow/runtime/CLAUDE.md`, `src/pflow/core/workflow/CLAUDE.md` — new canonical form + heterogeneous-batch named example + Step 7/8 coverage notes.

### Implementation commit — migrations (10 nodes across 8 `.pflow.md` + 5 Python fixture sites)

All `.pflow.md` examples under `examples/nested/`, `examples/bundling/`, and the scratchpad repros rewritten to `inputs:` form.

### Implementation commit — new test files / additions

- `tests/test_runtime/test_workflow_executor/test_ir_cache.py` (new file) — cache-key correctness + end-to-end heterogeneous batch.
- `tests/test_core/test_sub_workflow_validation.py::TestUndeclaredExtras` (new class, 3 tests) — Bug A parse-time coverage.
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — 2 new runtime-extras tests alongside existing `_validate_child_params` tests.

### Implementation commit — deletions

- `test_integration/test_workflow_manager_integration.py::test_workflow_executor_mutual_exclusivity` — tested removed XOR.
- `test_core/test_sub_workflow_resolver.py::test_inline_ir` — tested removed feature.
- `test_runtime/test_workflow_executor/test_workflow_name.py::test_workflow_and_workflow_ir_raises_error` — tested removed XOR.
- `test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py::test_workflow_ir_only`, `test_both_parameters_provided`, `test_malformed_child_ir_context` — tested removed inline-IR path.
- `test_core/test_sub_workflow_validation.py::TestInlineWorkflowIR` (class) — tested removed recursive inline-IR validation.

### Review-cycle commit 1 (`2daee665`) — 11 silently-passing test sites + 4 cleanups

- `tests/test_runtime/test_template_validation/test_validator.py` — 6 sites converted from `workflow_ir`-dict-literal to file-backed fixtures via a new `_write_child_with_outputs` class helper. Mutation-verified `${process-all.results[0].BOGUS}` now caught.
- `tests/test_runtime/test_template_validation/test_batch_item_validation.py` — 1 site converted (line 526); separate migration at line 598 moved `input:` from top-level to `inputs:` dict.
- `tests/test_integration/test_unused_inputs.py` — 3 sites migrated to `inputs:` form AND given explicit `registry=Registry()` so Step 7 runs like production.
- `tests/test_runtime/test_workflow_executor/test_integration.py::test_file_workflow_execution` — converted `test_input` top-level to `inputs: {test_input:}`; added strong assertion on auto-exposed child output (`"Processed: Hello from file"`) that catches regression into silent drop.
- Cleanups: regex tightening, post-W3 comment drift, pre-existing-debt never-valid-param-key replacements in `tests/test_core/test_workflow_validator.py:186` and `tests/test_runtime/test_compiler_interfaces.py:381`.

### Review-cycle commit 2 (`80776a24`) — non-dict `inputs:` diagnostic + stale comment

- `src/pflow/core/workflow/validator.py::_check_required_inputs` — narrowed the non-dict guard; emits a structured Diagnostic for literal non-dict (string / list / number / bool) while still deferring opaque `${...}` templates to runtime.
- `src/pflow/runtime/workflow_executor.py::_extract_child_inputs` — replaced silent `{}` fallback with `ValueError` for non-None non-dict, naming the actual type.
- `tests/test_core/test_sub_workflow_validation.py::TestNonDictInputsShape` (new class, 2 tests) — parse-time rejection with structured-context assertions.
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — `test_inputs_non_dict_raises_shape_error` (runtime) and `test_inputs_none_treated_as_no_inputs` (null still valid); replaces the old silent-behavior `test_inputs_non_dict_not_forwarded`.
- Stale comment on `ALLOWED_PARAMS` rewritten to describe actual framework-key handling (`__registry__` is compiler-injected, not user-authored via a prefix convention).
- `tests/test_runtime/test_workflow_executor/test_ir_cache.py::test_ir_cache_hits_on_same_ref` — one-line comment documenting the fresh-dict-per-call intent.

### GitHub artifacts
- [Issue #283](https://github.com/spinje/pflow/issues/283) filed for mermaid visualizer fidelity regression with full root-cause analysis and proposed fix.

---

## What I'd do differently

1. **Mutation-test the runtime check earlier**. I wrote `_validate_child_params`'s extras loop in Commit 4 but didn't verify it was reachable by any test until after the user asked "should we fix the runtime test loose end?" Writing the positive test at Commit-4 time (not as a follow-up) would have caught any dead-code issue immediately.

2. **Verify searcher scope estimates with a spike before committing to the plan.** Before Commit 3, run a `grep -rn "workflow_ir" tests/` and eyeball the output for 30 seconds. Would have surfaced the 33-site blast radius in the planning phase, not the implementation phase.

3. **Check visualizer / tooling output against canonical-shape changes as part of migration, not as an afterthought.** The mermaid regression would have been caught in the plan-review phase if "what downstream tools parse this shape?" had been an explicit planning checkpoint.

4. **Global-grep across ALL test directories, not just the adjacent one.** The initial 33-site audit covered `tests/test_runtime/test_workflow_executor/` but missed `tests/test_runtime/test_template_validation/` — same `workflow_ir` dict-literal pattern, 7 additional sites the review cycle had to catch. Lesson: when removing a feature, grep the raw string key across `tests/`, `examples/`, `docs/`, and `scripts/` as a single pass — don't trust "here's the main test file for this subsystem."

5. **Audit test-helper APIs for silently-disabling-validation optional parameters.** Three sites in `test_unused_inputs.py` called `split_validator_diagnostics(...)` without `registry=`, which silently skipped Step 7. No structural grep would catch this — only mutation testing proves the validator actually ran. Lesson: when a validator has a Step that short-circuits on a missing argument (`if registry is not None`), audit every test call site to confirm full arguments are passed; flag any helper that makes "skip Step N" invisibly trivial.

6. **Scope an explicit specialist-agent review pass into the plan.** The plan treated green CI + green pytest as sufficient verification. Mutation-resistant review found 11 silently-passing test sites and a diagnostic-quality gap. For PRs of this size (30+ files, schema change, migration), a code-review phase with 4 specialist agents is ~15 minutes of wall time and catches issues static analysis can't.

7. **Verify the verification.** My claim "parser produces `inputs: None`" was "empirically confirmed" by a `.get("inputs")` call that returned `None` from the missing-default fallback, not from an explicit `None`. Two different causes, one output. Next time: when using `.get(k)` to verify a value, follow with `k in d` to disambiguate missing-key from explicit-None. A claim built on an ambiguous primitive is a claim worth nothing.

8. **Before proposing a sweep, check the structural boundary.** I mapped 9 consumer sites as crash candidates and proposed a normalize-upstream fix without first checking whether IR schema validation already rejected the invalid state. It did — cleanly, at Step 1 — meaning my proposed "sweep all consumers" was redundant with an existing top-10% boundary. The user's "top 10% codebase?" pushback was the forcing function; without it I'd have shipped over-engineering.

## What I got right

1. **Per-commit verification gate** contained the scope surprise in Commit 3. Catastrophic if Commits 3+4 had been batched.

2. **Choosing `ALLOWED_PARAMS` (Option D) over scanner registration (A) or validator method (B).** The user's "final state simplicity" directive was the decisive tiebreaker, and the choice compounds well with the planned schema-declaration refactor.

3. **Deleting `RESERVED_PARAMS` entirely rather than shrinking it.** The frozenset's existence *was* the symptom of the dual-mechanism problem. Collapsing to `inputs:`-only made it vestigial. Seeing the shrink → delete opportunity required following the "simplicity of final code" directive past the minimum-viable fix.

4. **Filing issue #283 rather than attempting to also fix the mermaid visualizer.** Scope discipline. Visualizer fidelity is a real UX cost but belongs in its own contained PR with its own tests and its own golden-file regeneration.

5. **Running the "easy wins" pass after the user asked.** The prep_res-key rename and cache-logic simplification were small but real final-state improvements. Without the explicit prompt I would have shipped the code with the cognitive debt.

6. **Deploying 4 targeted review agents, not the full 7.** Choosing `review-impact-completeness`, `review-feature-interactions`, `review-validation-consistency`, `review-test-fidelity` — and skipping `review-silent-failures` (redundant with the PR's theme), `review-agent-ux` (already reviewed in-conversation), `review-concurrency-safety` (covered by explicit parallel tests) — produced no redundant findings and the full cluster of test-fidelity issues no single agent would have caught alone.

7. **Folding the non-dict `inputs:` diagnostic into this PR instead of deferring.** Scope discipline would've split it off; correctness instincts said "same surface as Bug A, small fix, caught by the same review." Folding in avoided two review cycles for one cluster of findings. Counter-example kept honest: `framework_keys` was NOT folded in because it depends on the future refactor's shape — folding in there would have been speculative work.

8. **Accepted the user's "top 10%" pushback and re-verified instead of defending.** When my sweep proposal looked shaky to the user, the defensive move would have been to justify the scope with elaboration. Instead I went back to the code, re-ran the primitives, and discovered I'd misread the parser output + missed that the IR schema already handled the case. Changing my mind out loud — and being honest about the misread — produced the correct narrow fix. The review bot got the right answer; I would have over-engineered without the user's forcing function.
