# pflow Constraints

Repo conventions that carry ADR weight — don't re-litigate or contradict them in proposals.

## Layering & enforcement

- **No import-linter exists.** Layering ("core must not import runtime", "execution/ never imports Click") is convention, stated in directory CLAUDE.md files. The mechanically-enforced invariants are **meta-tests** — pflow's native leverage mechanism: litellm importable only via `core/litellm_runtime.py` (AST-scan, `tests/test_core/test_litellm_runtime.py`), the CLI import chain must stay litellm-free (subprocess test, `tests/test_cli/test_lazy_imports.py`), nodes must not store execution state on `self` (`tests/test_nodes/test_node_stateless_invariant.py`), registry type strings lowercase (`tests/test_registry/test_type_string_conventions.py`). A deepening that establishes an invariant should ship it as a meta-test; never break existing ones.
- **Drift-detection-for-free seams** (raise recommendation strength for candidates touching them): the IR schema (`core/ir_schema.py`), the GraphModel (ADR-0003/0004 — structural `NodeId`, primitive-only), the litellm seam, and `tests/test_docs/` — every `examples/**/*.pflow.md` and every guide-embedded workflow is validated (and partly executed) by the suite.
- **Errors**: producers build `Diagnostic`s at the detection site (`PflowError` subclasses, never vanilla exceptions); agent-facing text speaks the authoring surface, never runtime internals (`core/CLAUDE.md`). Don't propose error layers beside this pipeline.

## Testing (overrides DEEPENING.md categories)

- Category 4 (true external): LLM is **always** mocked, via the autouse `mock_llm_client` at the adapter seam (`pflow.core.llm_client.complete`); HTTP mocked at `requests.request`; MCP mocked only at the external server boundary; claude SDK stubbed via `sys.modules`.
- Category 2 (local-substitutable): shell/subprocess and filesystem run **real** (in tmp dirs) — never propose mocking them, and never mock node primitives or the shared store (`tests/CLAUDE.md` sacred rules).
- "Tests at the deepened module's interface" = `WorkflowRunner().run()` asserting on `result.shared_after`/`result.diagnostics` (cross-layer features *require* one such test), `compile_and_run()` (`tests/shared/engine_utils.py`), `node.run(shared)`, and `CliRunner`. `e2e` is a pytest *marker* for subprocess/pipe tests (excluded from `make test`), not a directory.

## Deliberate shapes — don't "fix"

- **Engine re-entry for loops** (ADR-0001) and **trace-sourced `--only` snapshots** (ADR-0002) were chosen over desugaring/memo-cache alternatives — don't re-propose the rejected options.
- `runtime/engine/batch_executor.py` and `loop_control.py` are deliberately **module-level functions, not classes** (`execute_batch`, no `BatchExecutor`).
- Validation and compile-time checks share `validate_data_flow()` — keep validation/runtime in sync via shared layers, not parallel logic; the validator is a 10-step pipeline (`core/workflow/CLAUDE.md`).
- The GraphModel carries no runtime state and no pattern interpretation (ADR-0004); renderers derive what they need from it.

## Execution handoff for an agreed design

Two real paths (the user picks): **(a)** capture as a task — `/create-task-spec <id>` writes the spec under `.taskmaster/tasks/task_N/`, then `/start-work` produces the implementation plan and dispatches inline briefs to `code-implementer`/`test-writer-fixer`, logging to `implementation/progress-log.md` and closing with `task-review.md`; or **(b)** plan directly in-session (scratchpads under `scratchpads/`). The `plan-breakdown` skill splits large plans across agents. (`/refactor` no longer exists — it was replaced by this skill.)
