# Task 56 – Runtime Validation & Error Feedback Loop — Handoff Memo

This is a focused transfer of tacit knowledge before implementation begins. Read this first, then the spec and implementation plan. Do not start coding until you confirm you’re ready.

## Core outcomes and side effects to anchor on
- Planner gains a runtime self-correction loop via a new `RuntimeValidationNode` that executes the candidate workflow once, classifies runtime issues, and routes:
  - default → success
  - `runtime_fix` → back to generator with `shared["runtime_errors"]`
  - `failed_runtime` → terminal failure for runtime loop
- Attempts are capped at exactly 3 (`runtime_attempts` counter). Double execution (reruns) is accepted for MVP.
- HTTP node gains deterministic extraction with structured errors; MCP is supported by harvesting namespaced errors and missing downstream template paths.
- CLI behavior, autosave flow, and existing ValidatorNode remain unchanged.

## Assumptions (now design choices in spec)
- Execute all nodes during runtime validation (no read-only/dry-run gating). Side effects may occur on retries; accepted for MVP.
- HTTP extraction uses a simple dot/array subset (e.g., `$.field`, `$.nested.field`, `$.items[0].name`) — not full JSONPath.
- `RuntimeValidationError` is the dedicated exception type for HTTP extraction failures; it must be re-raised unchanged by HTTP `exec_fallback`.
- MCPNode does not raise on tool-level errors; it stores an `error` under its namespace and returns default. Runtime loop must detect this pattern.

## Discoveries / edge cases that changed approach
- Namespacing is enforced by `NamespacedNodeWrapper`: node outputs/errors live under `shared[node_id]`. Runtime loop must scan these namespaces to find `error` keys.
- `TemplateAwareNodeWrapper` resolves templates just-in-time; unresolved templates remain literal. Post-exec, we can detect missing downstream references by comparing IR templates (`${node_id.path}`) to the final shared store.
- MCPNode deliberately returns default even on tool error (writes `error`). This avoids planner “error edge” wiring crashes but means runtime validation must not rely on flow result alone.
- Planner nodes conventionally return structured dicts and route in `post()`; follow this in `RuntimeValidationNode` to avoid retry pattern conflicts.

## Patterns to reuse
- PocketFlow retry pattern: no try/except in `exec()` for nodes that need retries; use `exec_fallback` only after retries. For planner nodes, prefer returning structured results and classifying in `post()`.
- Compiler wraps nodes with templates, namespacing, and instrumentation automatically; rely on `compile_ir_to_flow` to get consistent behavior.
- Use `TemplateValidator._extract_all_templates(workflow_ir)` to enumerate `${...}` references; filter to `${node_id.*}` when auditing downstream output paths.

## Anti-patterns to avoid
- Don’t flatten/convert `RuntimeValidationError` to `ValueError` in HTTP; this erases structured payloads needed by the planner loop.
- Don’t re-run static validations in `RuntimeValidationNode`. Schema, data-flow, and template syntax checks belong to ValidatorNode.
- Don’t add a `raw` response key to HTTP exec results; keep existing `response` semantics and add `extracted` only when extraction succeeds.
- Don’t mutate shared in `exec()` in ways that obscure namespacing. Use a fresh shared store to run the candidate workflow; classify using the resulting store.

## Subtle bugs and caveats
- Flow result action is not a reliable error indicator for MCP; always scan namespaced errors.
- Template audits must ignore non-node references (e.g., plain inputs: `${input_value}` without a node_id prefix). Only treat `${node_id.*}` as downstream output paths.
- Keep the `runtime_attempts` counter separate from existing `generation_attempts`. Do not conflate or overwrite.
- Ensure HTTP extraction path resolver handles lists and nested dicts but fails cleanly (returning missing) when encountering non-dict traversal.
- Limit structure samples and available keys lists to bounded sizes to avoid bloating error messages.

## Shared interfaces / contracts introduced or changed
- New exception: `RuntimeValidationError` (in `pflow.core.exceptions`) with fields such as `source`, `node_type`, `category`, `attempted`, `available`, `sample`, `message`.
- HTTP exec result on success includes `extracted` (object) in addition to existing `response`, `status_code`, `headers`, `duration`. In `post()`, write `extracted` into namespaced shared when present.
- Runtime loop populates `shared["runtime_errors"]: list[dict]` on `runtime_fix`; this is consumed by the generator’s runtime-fix prompt.
- Planner wiring adds `RuntimeValidationNode` after metadata generation with actions: default, `runtime_fix`, `failed_runtime`.

## Relevant code touchpoints and reading order
- Planner:
  - `src/pflow/planning/flow.py` — wire `RuntimeValidationNode` after metadata_generation
  - `src/pflow/planning/nodes.py` — implement `RuntimeValidationNode`; update `WorkflowGeneratorNode` to consume `runtime_errors`
- Runtime/validation helpers:
  - `src/pflow/runtime/template_validator.py` — `_extract_all_templates`
  - `src/pflow/runtime/compiler.py` — `compile_ir_to_flow`, wrappers applied
  - `src/pflow/runtime/instrumented_wrapper.py` — tracing/metrics wrapper behavior
  - `src/pflow/runtime/namespaced_wrapper.py` and `namespaced_store.py` — namespacing mechanics
- Nodes:
  - `src/pflow/nodes/http/http.py` — add `extract`, raise `RuntimeValidationError`, re-raise in `exec_fallback`
  - `src/pflow/nodes/mcp/node.py` — note error storage pattern and default action
- PocketFlow core:
  - `pocketflow/__init__.py` — Node/Flow retry mechanics; action routing

## Docs/files worth having open
- Spec (source of truth): `.taskmaster/tasks/task_56/starting-context/task-56-spec.md`
- Impl plan: `.taskmaster/tasks/task_56/starting-context/task-56-implementation-plan.md`
- Task overview: `.taskmaster/tasks/task_56/task-56.md`
- Research (HTTP use cases/examples for tests): `.taskmaster/tasks/task_56/research/http-node-runtime-validation-usecase.md`

## Questions / TODOs to investigate during implementation
- Should `RuntimeValidationNode.exec()` use registry from context if available (for parity with CLI) or instantiate a new `Registry()`? Either is acceptable for MVP; prefer `Registry()` unless planner context already provides one.
- How verbose should `runtime_errors` entries be? Keep entries compact (attempted, available keys, sample) but ensure test assertions have deterministic substrings.
- Are there planner prompts to extend or do we add a new runtime-fix prompt file? If prompt files exist for other phases, mirror that pattern.

## Final reminder
Do not begin implementing yet. Read the spec and implementation plan, then confirm “Ready to begin” at the end of your review. This memo captures non-obvious context and pitfalls that the spec/plan may not make explicit.
