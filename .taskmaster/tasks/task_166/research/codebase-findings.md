# Task 166 — Verified codebase findings

> Compiled from a parallel codebase audit (7 focused searches reading current source).
> Each item is marked **VERIFIED** (read from code, with file:line) or **SUSPECTED / UNVERIFIED**.
> These are the facts the loop design is built on — the implementer should rely on them but
> re-confirm the file:line anchors, which may drift.

## 1. Loop mechanism & the "self-reference" substrate (most load-bearing)

- **VERIFIED — `loop:` is a node *modifier*, not a node type.** A top-level node field (sibling to `batch:`), parsed at `src/pflow/core/markdown_parser.py:1187`, compiled via `_build_loop_config` (`runtime/compilation/compiler.py:352-353`) into a `LoopConfig` (`runtime/engine/types.py:38-51`). Re-entry is in the engine walk loop `engine.py:442-490` (`_loop_should_reenter` at `:581-620`); condition/cap primitives in `runtime/engine/loop_control.py`.
- **VERIFIED — re-entry clears in-process completion and bypasses the memo cache per iteration**, but does **not** delete `shared[node_id]`. `enforce_loop_guard` (`instrumentation.py:52-81`) clears `completed_nodes`/`node_actions`/`node_hashes`/`__failures__`; memo reads suppressed while `__loop_active__ > 0` (`instrumentation.py:256-276`). `clear_node_failure` (`node_state.py:185-203`) leaves `shared[node_id]` intact.
- **VERIFIED — there is NO self-namespace exclusion.** Template resolution context is `context = dict(shared)` (`runtime/engine/template_resolution.py:325`) with nothing removed. So a loop node's own previous-iteration output **is** readable as `${node-id.field}` during the next iteration's input resolution. The data-flow validator explicitly blesses a loop node's self-reference (`core/workflow/data_flow.py:130-136`, scoped to `loop_node_ids`). **This is why carry-via-reference is feasible with no new storage mechanism — the prior output already persists and is already resolvable.**
- **VERIFIED — `${__iteration__}` (1-based) exists**, injected/cleared in `loop_control.py:27-60` / `engine.py:460-494`.
- **VERIFIED — visit guard caps runaway:** `MAX_NODE_VISITS` (default 100, env `PFLOW_MAX_NODE_VISITS`) in `instrumentation.py:21-24`, enforced `:63-66`; the loop cap is bounded by it.
- **VERIFIED — `while:` already rejects raw-string sources.** `template_validation/validator.py:207-263` rejects a `while:` whose inferred type is string (`_make_loop_string_type_diagnostic`), and rejects operator/arithmetic shapes (`_LOOP_OPERATOR_CHARS`). Runtime also raises if the resolved condition is a `str` (`loop_control.evaluate_loop_condition`). Workflow-node `while:` referencing a child's declared `## Outputs` is supported.

## 2. Template / expression resolution

- **VERIFIED — `${...}` is path-lookup + `??` ONLY. No expression evaluation anywhere.** `${x > 0}` / `${count(x) <= 1}` are not even recognized as templates (the var-name grammar `template_resolver.py:28` excludes operator chars) and pass through verbatim. So conditions must be field references; computed booleans live in the body. (Confirms "no guard-expression language" — there is no evaluator to extend.)
- **VERIFIED — `??` coalesce** (`template_resolver.py:310-366`): left-to-right; falls through when a node didn't run OR a field is absent; accepts JSON literals as a final default; a string literal cannot itself contain `??`.
- **VERIFIED — auto-JSON parsing** for simple templates only; complex templates (prefix/suffix/quoted) stay strings.

## 3. Batch & composition (the symmetry to preserve)

- **VERIFIED — `batch:` is node-type-agnostic and works on `type: workflow` nodes** (`runtime/engine/batch_executor.py` + `runtime/workflow_executor.py` co-handle it). So composition (a `loop:` over a `workflow` body whose child uses `batch:`) needs no engine change.
- **VERIFIED — `batch:` and `loop:` are mutually exclusive, per-node, enforced in two places:** `compiler.py:388-395` and `core/workflow/data_flow.py:579-580`. (Keep this; loop stays a sibling modifier of batch.)
- **VERIFIED — batch `results` holds only successful items under `error_handling: continue`** (`batch_executor.py:945-946`); use `original_index` to realign. Sub-workflow batch loses per-item numeric coercion (issue #188).

## 4. Branching / routing (context, not directly changed)

- **VERIFIED — routing edges are computed at parse, wired at compile, followed at runtime** (`engine.py:486` `successors.get(action or "default")`).
- **VERIFIED — document-order fallthrough into/out of branch targets is REJECTED at parse time** (`markdown_parser.py:1439/1494/1329`) — not a silent runtime bug. (Corrects an earlier assumption.)
- **VERIFIED — `raise` in a code node → `action="error"` → hard-stops only when there is no `on-error` successor; with a handler it routes there and the run is DEGRADED** (`engine.py:486`, step 17.5 `:952-963`; status in `execution/runner.py`). Relevant to the adjacent error-model issue #471, not to this task directly.

## 5. Node-type cost (why "modifier" not "type")

- **VERIFIED — a new node *type* is cheap (1 file, auto-discovered by `registry/scanner.py:239`)**, BUT control-flow mechanisms (batch/loop) live in the *engine*, not as node files. A loop is engine behavior, correctly expressed as a modifier — making it a `type:` would add a node type AND break batch-symmetry for no gain.
- **VERIFIED — patterns are 0-file** (saved `.pflow.md` recipes). Reinforces "patterns are library recipes, primitives are engine work."

## 6. Validator & diagnostics (reuse target)

- **VERIFIED — detection is cleanly separable from rendering.** Validators build structured `Diagnostic` objects (`src/pflow/core/diagnostic.py`); a single `format_diagnostic()` (`core/diagnostic_render.py`) renders them; dependency is one-way. A new detection front-end (e.g. carry/until checks) just emits `Diagnostic`s with the right `context` keys and inherits text/JSON/dedup/CLI/MCP rendering. The cache analyzer is precedent.
- **VERIFIED — the validator is a 10-step pipeline (`core/workflow/validator.py:179-243`), recursive on sub-workflows.** Code-node input type-checking ("Pass 9", `runtime/template_validation/type_validation.py:728`) is the existing model for the carry/output type checks. Loop/batch/next are validated across parser + `data_flow.py` + schema.

## 7. Trace & graph model (for the future human/visual view — out of scope here)

- **VERIFIED — the trace (`runtime/workflow_trace.py`, format 2.5.0) captures per-iteration loop events and per-item batch events** with counts/cost/branch-taken — enough to reconstruct a runtime graph. Loop iteration # and branch identity are *derived* (count events per `node_id`), not stored fields.
- **VERIFIED — there is no reusable graph model;** `visualize` is ad-hoc Mermaid string-building from static IR (`core/workflow/mermaid/_render.py`). A graph-model layer is **Task 155** (not started), specced from IR (would need a trace overlay for a runtime view). Not required for this task.

## Retry / status facts (adjacent — for issue #471, noted for completeness)

- **VERIFIED — retry is hardcoded per node type** (`Node.__init__(max_retries=1, wait=0)`, `core/node.py:76`; per-type constructor defaults: http/llm/file=3, claude=2, shell/code=1) and only settable in `.pflow.md` via `batch:` `max_retries`/`retry_wait` (`ir_schema.py:122-134`). **No exponential backoff exists.** Three run states only (SUCCESS/DEGRADED/FAILED, `core/workflow/status.py`); `on-error` recovery always DEGRADES (no "recovered-cleanly" path). These belong to issue #471, not this task.

## Caveats

- Line numbers are from the audit snapshot and may drift — treat them as starting anchors.
- Items in §1 (substrate persistence) and §2 (no expression language) are the load-bearing ones; re-confirm before building the carry-override.
