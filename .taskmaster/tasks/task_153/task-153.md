# Task 153: Close Parent→Child Input Boundary + IR Cache Heterogeneous-Batch Fix

## Description

Closes the parent→child sub-workflow input boundary so undeclared extras are rejected at parse time, symmetric with the existing missing-required check. Bundles the IR-cache heterogeneous-batch bug fix because it blocks the motivating use case (parallel fan-out over heterogeneous child workflows). Collapses the dual input-passing mechanism into a single canonical form (`- inputs:` dict) and removes the `workflow_ir` inline-IR escape hatch.

## Status

completed

## Priority

medium

## Problem

Two coupled bugs at the parent→child sub-workflow boundary.

**Bug A — silent drop of undeclared inputs.** Passing an input to a `type: workflow` node that the child has not declared in its `## Inputs` was silently dropped. No error, no warning, no log line at any verbosity tier. A typo (`lyric:` instead of `lyrics:`) survived validate, execution, and trace inspection. The worst possible failure mode for an agent generating workflows: validates fine, runs fine, produces plausible-but-wrong output the user discovers in production.

**Bug B — IR cache reuses wrong child across heterogeneous batches.** `WorkflowExecutor._cached_loaded_ir` was a scalar keyed on `self`. In a batch where `${item.workflow}` varies per iteration, item 2 inherited item 1's cached IR — both sequential (same instance reused) and parallel (pre-warm + deepcopy). Reproducible: item 2 fails with "missing required input a ... you provided: b" because it loaded child-a's IR but received child-b's inputs.

Bugs couple: the heterogeneous-batch pattern is the motivating use case that kept the leniency in place (see `scratchpads/undeclared-workflow-input-drop/bug-report.md`). Fixing A alone produces a migration target (per-item `inputs:`) that still doesn't work because B. Both must land together.

## Solution

- **One canonical form** for parent→child value passing: the `- inputs:` dict on workflow nodes. No more top-level free-form child-input forwarding.
- **Closed top-level schema** on the workflow node via a class-attribute allowlist. The existing validator Step 7 (currently skipped for workflow nodes because they bypass the registry) reads the allowlist and rejects unknown top-level fields with fuzzy "did you mean" suggestions.
- **Symmetric input-shape check** at the parent→child boundary: both missing-required and undeclared-extra directions enforced by `WorkflowValidator._check_required_inputs` at parse time and `WorkflowExecutor._validate_child_params` at runtime (defense-in-depth).
- **IR cache keyed by resolved workflow path**: heterogeneous batches naturally get different keys per iteration.
- **Remove `workflow_ir`** (inline-IR escape hatch) entirely. Zero public doc mentions; one test used it — converted to a fixture file.
- **Delete `RESERVED_PARAMS`** frozenset: its sole job (filtering framework keys from open-ended top-level forwarding) has no purpose once the schema is closed.

## Design Decisions

**D1 — Canonical form: `inputs:` dict only.** Rationale: agent-first; one pattern to learn; matches code/llm nodes; eliminates the blocklist-filter mental model; enables schema closure. The kwargs-style "looks like a function call" ergonomic was rejected as a human-aesthetic argument that trades against fail-fast signal.

**D2 — Closed schema via `ALLOWED_PARAMS` class attribute, not scanner registration or a targeted validator method.** Three alternatives were considered:
- *Option A — register workflow node in the scanner.* Rejected: `WorkflowExecutor` lives in `runtime/` to avoid a circular import with `compile_workflow`; relocating it is an architectural change for a single node.
- *Option B — targeted `_validate_unknown_workflow_params` method in the validator.* Rejected: leaves a permanent special case that a future refactor must remove.
- *Option D (chosen) — `ClassVar[frozenset[str]]` on the class; validator Step 7 reads it directly.* Mechanism-agnostic: any future schema-declaration refactor (Pydantic / decorator / `__init_subclass__`) either generates `ALLOWED_PARAMS` or replaces it cheaply. Workflow is the first migrant to the forward-compatible pattern.

Rationale-of-rationale: the user is already planning a broader refactor to replace the docstring-`Interface:` regex-parsing mechanism. D is the smallest possible step that's forward-compatible with any direction that refactor takes. Scheduled as a separate follow-up task after this work lands.

**D3 — Remove `workflow_ir` entirely (W3).** Three options considered (keep-and-document / keep-undocumented / remove). Removed because: zero public doc mentions, one test authored it in markdown (converted to fixture), it works against every property pflow tries to enable (child not independently runnable, discoverable, or skill-publishable).

**D4 — IR cache keyed by resolved workflow path.** Replaces scalar `_cached_loaded_ir` with `_loaded_ir_cache: dict[str, tuple[...]]`. Heterogeneous batches get different keys per iteration; homogeneous batches hit the cache on item 2 onward. Compile cache follows the same shape.

**D5 — Defense in depth: parse + runtime.** Matches the existing missing-required pattern (parse-time `Diagnostic` + runtime `ValueError`). The runtime check specifically protects the opaque-template case (`inputs: ${item}`) where parse-time can't statically see keys, and any programmatic API that bypasses `WorkflowValidator`. Runtime wording deliberately *not* aligned with parse-time wording — the existing missing-required path has the same divergence, and aligning only extras would be a local inconsistency.

**Coupling A+B in one PR.** Fixing A alone ships a design whose motivating use case (heterogeneous batch) provably still doesn't work. Fixing B alone leaves the typo footgun open.

## Dependencies

- **Task 136: Recursive Sub-Workflow Validation at Parse Time** — Added the missing-required direction of the input-shape check and `WorkflowExecutor.RESERVED_PARAMS` in its current form. Task 153 completes the asymmetry by adding the extras direction and collapses `RESERVED_PARAMS` entirely.

## Requirements

### Schema closure
- Workflow node top-level fields are exactly `{workflow, inputs, error_action, storage_mode, max_depth}`. Anything else at the top level is rejected at parse time with a structured diagnostic naming the unknown field, listing allowed fields, and (when close) offering a fuzzy "did you mean" suggestion.
- The allowlist is declared on the class, not hardcoded in the validator — so a future schema-declaration refactor has one obvious seam.

### Input-shape symmetry
- Every key inside a parent's `- inputs:` dict must correspond to a declared input on the child. Missing-required and undeclared-extra are enforced by the same method family, at both parse time (structured `Diagnostic`) and runtime (`ValueError`).
- The existing child-side rule ("declared input never used as template variable") remains unchanged. The parent and child sides of the boundary now agree.
- When `inputs:` is an opaque template (e.g. `${item}`), parse-time defers to runtime because keys are not statically knowable; the runtime check catches mismatches once the template resolves.

### IR cache correctness
- `_loaded_ir_cache` is keyed by the raw workflow reference string. Heterogeneous batches (`${item.workflow}` varies per iteration) naturally produce different keys per item; homogeneous batches hit the cache from item 2 onward. Both sequential and parallel modes must be correct.

### `workflow_ir` removal
- No user-visible surface authoring inline IR. No XOR logic. `resolve_sub_workflow` accepts only file path or saved name. Any test that authored inline IR is converted to a file-based fixture.

### Migration
- Every existing `.pflow.md` in the repo using top-level child-input params converts to the `inputs:` dict form. Every Python test fixture constructing workflow-node markdown with top-level child-input params converts similarly. The old form no longer validates.

### Infrastructure cleanup
- `RESERVED_PARAMS` frozenset is deleted (not shrunk). `_extract_child_inputs` collapses to a single-line read of `self.params["inputs"]`.

## Implementation Notes

Full implementation plan, commit-by-commit order, and file-level changes live in `implementation/implementation-plan.md`. Implementation retrospective, scope surprises, and meta-lessons in `implementation/progress-log.md`.

Key implementation surprises worth surfacing in the spec itself:

- **`workflow_ir` removal scope was 6× the searcher's estimate.** The searcher audited "who authors `- workflow_ir:` in markdown" (1 site). It did not audit "who constructs Python dicts with `\"workflow_ir\"` as a key in tests" (32 additional sites). Both populations matter — future W-style removals should grep both shapes in the planning phase.
- **Mermaid visualizer regression.** Migrating child-input passing to `inputs:` broke the visualizer's fidelity — it traces templates in top-level string params, not inside dict values. Goldens regenerated (coarser diagrams shipped), fix filed as issue #283 with root-cause and pointer to the existing `_collect_param_refs` reuse precedent. Scope discipline: do not fix in this task.
- **`"<inline>"` sentinel in `prep_res["workflow_path"]`** now means "saved name with no on-disk file" (an edge case), not "inline IR". The name is misleading. Rename cascades into `exec()`, `post()`, trace recording, and the compile cache's cacheable-check. Tracked as a follow-up, not a blocker.

## Verification

### Automated
- Full pytest suite passes (4760 tests after this task vs 4641 baseline).
- `make check` clean (ruff, ruff-format, mypy, deptry).
- Four regression-test clusters added:
  - IR cache key correctness + end-to-end heterogeneous batch (sequential + parallel).
  - Parse-time extras rejection (top-level via Step 7; inside `inputs:` via sub-workflow validator).
  - Opaque-template deferral (`inputs: ${item}` skips parse-time, catches at runtime).
  - Runtime defense-in-depth for the programmatic-API / opaque-template path.

### Manual
- `uv run pflow scratchpads/undeclared-workflow-input-drop/repro-files/parent-extra.pflow.md --validate-only` — exits non-zero with structured diagnostic naming the extra field and listing declared inputs.
- `uv run pflow scratchpads/undeclared-workflow-input-drop/repro-files/parent-batch-hetero.pflow.md` — both child workflows produce their own per-child output (Bug B fix verified).

## References

- `implementation/implementation-plan.md` — ordered commits, file-level changes, function pointers.
- `implementation/progress-log.md` — retrospective, scope surprises, meta-lessons.
- Task 136 (`.taskmaster/tasks/task_136/`) — direct predecessor; added missing-required check, this task completes the asymmetry.
- `scratchpads/undeclared-workflow-input-drop/bug-report.md` — original bug report with repro probes and observability audit.
- `scratchpads/undeclared-workflow-input-drop/proposed-fix.md` — earlier design exploration (partly superseded by Design Decisions above).
- GitHub issue #283 — mermaid visualizer fidelity regression follow-up.
- Future task (to be created) — schema-declaration refactor (Pydantic / decorator / `__init_subclass__`) that replaces the docstring-`Interface:` regex-parsing mechanism. `ALLOWED_PARAMS` is the forward-compatible seam for this refactor.
