# Task 138 Phase 1 — Design Review Synthesis

8 review agents analyzed the 10 design questions. This document consolidates their findings into consensus recommendations, conflicts, and new discoveries.

## Question Ordering (from review-plan)

Questions have dependencies. Recommended resolution order:

**Q4 first** (merged resolver return signature) — constrains Q10, Q9, error model
**Q1 second** (RunConfig shape) — constrains Q2, Q3, Q7
**Q2 third** (validate-only) — depends on Q1
**Q3, Q7, Q8 in parallel** — all about CLI/Runner boundary, independent of each other
**Q9 next** (exception wrapping) — depends on Q4's error model
**Q10 last** (resolver location) — follows from Q4
**Q5, Q6 nearly independent** — can be resolved anytime

---

## Q1: Runner Config Shape

### Consensus: Dataclass (7/8 agents agree)

| Agent | Recommendation |
|-------|---------------|
| Concurrency | Frozen dataclass for immutable scalars; mutable collaborators as `run()` kwargs |
| Validation | Dataclass — enforces complete contract, prevents MCP omission bugs |
| Silent Failures | Dataclass — but `__no_cache__` must be config-only, not popped from params |
| Agent UX | Dataclass — invisible to agents, enables consistent MCP/CLI defaults |
| Test Fidelity | Separate params easier to test; if dataclass, use factory in tests |
| Feature Interactions | Dataclass — one shape must cover all features (cache, trace, MCP pool, etc.) |
| Impact Completeness | `execute_json_workflow()` constructs full param set — Runner config must absorb it all |
| Plan | Dataclass — must be answered second (after Q4) |

### Key insight (concurrency)
Split config into two concerns:
- **Frozen dataclass** for immutable scalars: `trace_enabled`, `cache_enabled`, `verbose`, `only_node`, `output_format`
- **Per-call mutable collaborators** as explicit `run()` kwargs: `OutputInterface`, `MetricsCollector`, `TraceCollector`, `WorkflowManager`

This makes the concurrency contract visible: config is shareable, collaborators are per-call.

### New finding (silent failures)
`__no_cache__` is currently **popped** from `execution_params` (mutates caller's dict). If Runner config owns this flag, the pop disappears. Config should be the sole source — CLI strips `__no_cache__` before building config, not during execution.

### New finding (impact completeness)
`execute_json_workflow()` (1,383 lines) is the real consumer, not just `execute_workflow()`. It constructs `__no_cache__`, `__only_node__`, `__verbose__`, `__env_param_names__`, `cache_chunks`. Runner config must absorb ALL of these or the CLI stays a thick orchestrator.

---

## Q2: Validate-Only Mode

### Consensus: Separate method (6/8 agents agree)

| Agent | Recommendation |
|-------|---------------|
| Concurrency | Separate method — avoids mutation of shared params dict in validate path |
| Validation | **Separate method** — validate-only must NOT call `_prepare_compilation()` |
| Silent Failures | Flag risks routing validation through execution pipeline incorrectly |
| Agent UX | Flag — same JSON shape for validate and execute results |
| Test Fidelity | Either works — existing tests survive if exit codes preserved |
| Feature Interactions | Features behave differently in validate vs execute |
| Impact Completeness | `sys.exit()` coupling is deeper than spec acknowledges |
| Plan | Q1 constrains this — `_handle_validate_only_mode()` runs BEFORE enhanced_params exist |

### Critical finding (validation-consistency)
**Validate-only currently does NOT call `prepare_inputs()`.** This is intentional — it uses dummy params. A config flag risks accidentally running `prepare_inputs()` against dummy params, producing coercion errors that don't occur in real execution. Separate method makes this semantic distinction enforced at the API boundary.

### Conflict: agent-ux wants flag (same JSON shape), validation-consistency wants method (semantic safety)

**Resolution path**: Separate method (`runner.validate()`) that returns a `ValidationResult` (not `ExecutionResult`). The CLI converts `ValidationResult` to the same JSON shape agents expect, adding `"validated_only": true`. Best of both: semantic safety + consistent agent output.

### New finding (plan review)
`_handle_validate_only_mode()` is called BEFORE `_prepare_execution_environment()` in `execute_json_workflow()` (line 583-587). Validate-only exits before `enhanced_params`, `cli_output`, `display`, and `workflow_trace` are built. If the Runner implements validate-only as a flag, it needs all those objects — which validate-only currently doesn't need. This is *why* the current code uses `sys.exit()` — it's simpler than threading unused objects through.

---

## Q3: CLI vs Runner Boundary

### Consensus: Stdin routing logic moves to Runner, stdin *reading* stays in CLI

| Agent | Recommendation |
|-------|---------------|
| Concurrency | Move everything touching `initial_params`/`shared_store` to Runner |
| Validation | Stdin routing must happen BEFORE validation (ordering constraint) |
| Silent Failures | `UserFriendlyError` can be raised from Runner — no Click dependency |
| Agent UX | Stdin errors should be structured Runner errors, not Click-formatted |
| Plan | `UserFriendlyError` has no Click dependency — the coupling is only in the handler |

**Stays in CLI**: Reading stdin from OS (`read_stdin_content()`), flag validation (mutually exclusive flags), `run` prefix stripping, output format selection, `ctx.exit()`, trace file saving.

**Moves to Runner**: Stdin routing into params (`_route_stdin_to_params()`), `prepare_inputs()`, validation, compilation, execution, MCP pool lifecycle. Runner accepts `stdin_data: bytes | str | None` from CLI.

### New finding (validation-consistency)
Stdin routing happens BEFORE validation in current CLI flow. If stdin routing stays in CLI but validation moves to Runner, ordering breaks — `WorkflowValidator` template validation would fail on `${data}` templates referencing stdin input because the value isn't in params yet. **Solution**: CLI reads stdin and puts the value into the params dict *before* calling `runner.run()`.

---

## Q4: Merged `resolve_workflow()` Return Signature

### Consensus: Raise-on-error pattern, return `(ir, source)` (7/8 agents agree)

| Agent | Recommendation |
|-------|---------------|
| Concurrency | `(ir, source)` + raise — avoids error sentinel checking discipline |
| Validation | Raise — MCP tuple pattern allows silent error skipping |
| Silent Failures | Raise `WorkflowNotFoundError` — already handled by `_exception_to_errors()` |
| Agent UX | Raise — MCP gains "Did you mean" suggestions it currently lacks |
| Impact Completeness | CLI already uses raise pattern; MCP `_resolve_and_validate_workflow()` needs restructuring |
| Plan | **Must be answered first** — constrains Q10 and Q9 |

### Critical finding (silent failures)
MCP resolver returns `(None, "Workflow not found", "")`. When the Runner catches this and wraps into `ExecutionResult`, the `errors` list gets `category: "unknown"` (from fallback), not `category: "not_found"`. The "Did you mean" suggestions are buried in prose, not in a parseable `suggestion` field. **Fix**: Raise `WorkflowNotFoundError` (which already exists and has `similar_names`). The dispatch table in `error_output.py` already handles it.

### New finding (validation-consistency)
MCP resolver calls `normalize_ir()` on resolved IR. CLI resolver normalizes during file loading. **Merged function must normalize in ALL resolution paths** (file, library, direct dict, raw markdown). Missing normalization for dict/content path means `WorkflowValidator` fails on IR missing `ir_version` or `edges`.

---

## Q5: Registry Run Template Resolution

### Consensus: Environment resolution + error for unresolvable templates

| Agent | Recommendation |
|-------|---------------|
| Concurrency | Wrap in TemplateAwareNodeWrapper, seed `initial_params` from user params |
| Validation | Don't run WorkflowValidator — add per-node param validation only |
| Silent Failures | Option B: resolve from env, error on `${upstream.output}` references |
| Agent UX | Resolve from env + error on unresolvable — agent currently gets literal `${var}` back |
| Feature Interactions | Registry run currently has NO template, NO batch, NO validation |
| Plan | This is a concrete existing bug, needs a concrete decision before implementation |

### New finding (feature interactions)
MCP registry run has **empty shared store** (`shared: dict = {}`). Any `${var}` template silently passes through. CLI registry run does `shared_store.update(execution_params)` to seed the store. **This is a production bug** — MCP and CLI behave differently for the same node call.

### New finding (validation-consistency)
Don't run `WorkflowValidator` for registry runs — it validates workflow-level concerns (edges, output sources, sub-workflows) that don't apply. Instead, add focused per-node validation: validate parameter names against node interface (share `_extract_known_keys()` logic with WorkflowValidator Step 7).

---

## Q6: MCP Service Classes

### Consensus: Shrink, don't flatten (5/8 agree)

| Agent | Recommendation |
|-------|---------------|
| Concurrency | Shrink — keep `@ensure_stateless` as defense-in-depth guardrail |
| Validation | Shrink — fresh Registry per call prevents stale node metadata |
| Agent UX | Purely internal — invisible to agents |
| Test Fidelity | Tests mock at service layer — collapsing to functions breaks mock paths |
| Feature Interactions | MCP-specific behaviors (pool, async, sanitization) must survive |
| Impact Completeness | MCP test files not in migration list — will break if classes become functions |

### Key argument (concurrency)
Plain functions have no guardrails against module-level singletons. The `@classmethod` + `@ensure_stateless` pattern makes it visually obvious each method should be self-contained. Removing the class structure removes the cue.

---

## Q7: `display_validation_warnings()` Routing

### Consensus: Return warnings from `_prepare_compilation()`, never print directly (8/8 agree)

### Critical finding (validation-consistency)
**Warnings are displayed TWICE in verbose execution mode**: once by `WorkflowValidator._validate_templates()` → returned in `warnings` list → CLI displays, and once by `_validate_workflow()` → `display_validation_warnings()` → direct stderr print. Runner must deduplicate.

### Critical finding (plan review)
**Two call sites, not one**: `compile_validation.py:265` (inside compiler) AND `cli/main.py:399` (validate-only path). The plan only describes the compiler call site. If the implementer only moves the compiler call, the validate-only text mode path still calls `display_validation_warnings()` directly.

### Structural requirement (silent failures)
`compile_ir_to_flow()` must have an output channel for validation warnings. As long as `display_validation_warnings()` calls `print()` directly from inside `compile_ir_to_flow()`, the Runner cannot intercept them. **`_prepare_compilation()` must return warnings** (change return type to `tuple[dict, list[str]]`).

### Agent UX finding
In `--output-format json` mode, warnings are absent entirely. In `--validate-only --output-format json`, warnings are omitted even on success (the JSON success branch at line 391 doesn't include warnings). Agents can't see them.

---

## Q8: `_load_settings_env()` Deduplication

### Consensus: Move to Runner, call once, pass result down (7/8 agree)

### New finding (feature interactions)
Sub-workflows call `_prepare_compilation()` from inside `WorkflowExecutor`, bypassing the Runner. If settings_env loading is centralized in the Runner but not threaded through `compile_ir_to_flow()` → `WorkflowExecutor._compile_sub_workflow()`, sub-workflows lose access to settings env vars for required inputs. **Thread `settings_env` as a parameter to `_prepare_compilation()`**.

### New finding (validation-consistency)
MCP currently calls settings_env zero times in its validation path. CLI calls it twice (CLI pre-validation + compiler). After Runner unification, MCP gains settings_env loading (new behavior — needs test).

---

## Q9: Exception Wrapping Strategy

### Consensus: Single wrapping layer in Runner, always return `ExecutionResult` (6/8 agree)

| Agent | Recommendation |
|-------|---------------|
| Concurrency | Single layer — preserve `finally` for MCP pool shutdown (non-negotiable) |
| Validation | Flatten — `CompilationError` should always become `ExecutionResult`, never propagate |
| Silent Failures | Two-layer dance drops traceback context when wrapping into `ExecutionResult` |
| Agent UX | **Highest priority** — Runner returns `ExecutionResult` always, no raw exceptions |
| Feature Interactions | `RecursionError` (max nesting depth) currently escapes both layers entirely |
| Impact Completeness | MCP's `except RuntimeError: raise` at line 365 assumes current dance — will break |
| Plan | Inaccurate description — `RuntimeError` is also re-raised, propagates differently |

### Critical finding (impact completeness)
MCP `execution_service.py:365` has `except RuntimeError: raise` that depends on the current two-layer dance. If the Runner always returns `ExecutionResult` (no exceptions escape), this catch block becomes dead code. Tests won't catch this because MCP tests don't test the RuntimeError path.

### New finding (feature interactions)
`RecursionError` from max nesting depth in `WorkflowExecutor.prep()` is NOT caught by either layer. It surfaces as an unformatted traceback. The Runner should catch it and wrap it.

### New finding (plan review)
The plan's description is inaccurate: it says "`_handle_execution_exception()` re-raises `CompilationError` and `RuntimeError`" but omits that `RuntimeError` propagates differently — it's NOT caught by `workflow_execution.py`, going all the way up to CLI's outer handler. The plan describes half the exception topology.

### Concrete rule
Exceptions that become `ExecutionResult`: `CompilationError`, `MaxNodeVisitsError`, `ValueError`, `RuntimeError`, `WorkflowValidationError`, `RecursionError`, `MarkdownParseError`, `WorkflowNotFoundError`.
Exceptions that propagate through: `KeyboardInterrupt`, `SystemExit`.
`finally` for MCP pool shutdown: **non-negotiable**.

---

## Q10: Where Merged `resolve_workflow()` Lives

### Split consensus: `execution/` (concurrency, validation) vs `core/workflow/` (agent-ux, silent-failures)

| Agent | Recommendation |
|-------|---------------|
| Concurrency | `execution/resolution.py` — zero new dependency edges |
| Validation | `execution/workflow_resolver.py` — sibling to `execute_workflow()` |
| Agent UX | `core/workflow/resolver.py` — alongside `manager.py` and `validator.py` |
| Silent Failures | Raise-on-error forces callers to handle — location less important |
| Impact Completeness | `test_workflow_resolution.py` has 14 patches on `WorkflowManager` — all break |

### New finding (impact completeness)
**Test files NOT in the migration list** that will break:
- `test_cli/test_workflow_resolution.py` — 8 patches on `execute_json_workflow`, 14 on `WorkflowManager`
- `test_integration/test_template_resolution_hardening.py` — 13 tests importing `execute_workflow` directly
- `test_mcp/test_connection_pool.py` — 3 tests with direct `WorkflowExecutorService` instantiation

---

## Cross-Cutting Findings (Not Question-Specific)

### 1. MCP passes `{}` instead of `None` to `WorkflowValidator.validate()` — EXISTING BUG (validation-consistency)

`validated_params = parameters or {}` means `extracted_params` is `{}` not `None`. Template validation runs against an empty param set. `${workflow_input}` templates fail with "unresolved template" errors for workflows with declared inputs when called from MCP. CLI uses dummy params for each declared input, so it passes. Runner must populate dummy params for all declared inputs before calling `WorkflowValidator.validate()`.

### 2. `ExecutionResult` needs a stable home (impact completeness)

When `WorkflowExecutorService` is absorbed, `ExecutionResult` needs a new import location. 5+ files import it. Should live in a stable location (`execution/result.py`) that won't move again.

### 3. Batch child workflow template validation gap widens (validation-consistency)

Stripping `validate_workflow_templates()` from `_prepare_compilation()` means batch child workflows referencing `${item.field}` are no longer validated against actual resolved batch item structure at compile time — only against dummy params at pre-execution time. This gap pre-exists but gets slightly worse. Flag in implementation notes.

### 4. `PflowBatchNode` instance state warning for Task 135 (concurrency)

`self._shared`, `self._errors`, `self._item_timings` are set during execution and NOT reset between top-level executions. Safe for Task 138 (recompiles per execution), dangerous for Task 135 (compile-once, reuse flows). Document this explicitly for the Task 135 implementer.

### 5. `normalize_ir()` called multiple times (validation-consistency, concurrency)

MCP calls it in both `execute_workflow()` and `validate_workflow()`. Idempotent but wasteful. After merge, normalize once inside the resolver. But: `normalize_ir()` modifies in-place — if resolver ever caches, concurrent calls would race. Always return fresh dict.

### 6. Warning display inconsistency (plan review)

`--validate-only` shows grouped, formatted warnings via `display_validation_warnings()`. Normal execution shows flat `click.echo(f"⚠️  {warning}", err=True)` per warning. Phase 1 should normalize this — route all warnings through the same display function.
