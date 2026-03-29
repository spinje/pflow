# Task 138 Starting Context: Pipeline Analysis

> Source: Conversation 2026-03-29. Seven parallel pflow-codebase-searcher agents analyzed the full execution pipeline.

## Codebase Metrics

| What | Size |
|------|------|
| Total production code | ~48,000 lines across 181 files |
| PocketFlow framework | 205 lines |
| Wrapper chain | 3,920 lines (19x the framework) |
| Output/formatting layer | 5,404 lines, 24 files, 166 functions |
| MCP server | 3,365 lines, ~800 duplicated from CLI |
| CLI main.py | 1,383 lines, 33 functions, 49% pure glue |

## CLI main.py Analysis

**Call depth from entry point to actual execution: 5 levels**

```
workflow_command()                          [L1230]
  → _try_execute_named_workflow()           [L1119]
    → _handle_named_workflow()              [L1045]
      → execute_json_workflow()             [L558]   ★ noqa: C901
        → execute_workflow()               [L613]   ← THE ACTUAL WORK
```

**Breakdown:**
- 15 pure orchestration/glue functions: ~680 lines (49%)
- 17 functions doing actual work: ~403 lines (29%)
- Imports, decorators, whitespace: ~300 lines (22%)

**Key structural issues:**
- `ctx.obj` is an ad-hoc shared store with 15+ keys set across 4 functions. Tracking which keys exist at which point requires reading the full call chain.
- Two validation paths: `_perform_validation` (validate-only, dummy params) and `_validate_before_execution` (real execution, real params) — structurally identical with different error handling.
- Two `MetricsCollector` creation sites.
- Three `WorkflowManager` instantiations for saved workflow execution.
- 363 lines of input preparation before `execute_workflow()` is called (26% of file).

## Execution Layer Indirection

**Layers between IR+params and running nodes:**

```
execute_workflow()                    ← workflow_execution.py (96 lines, thin wrapper)
  → WorkflowExecutorService()        ← executor_service.py (722 lines, function-as-class)
    → compile_ir_to_flow()           ← compiler.py (787 lines, justified)
      → flow.run(shared_store)       ← PocketFlow (205 lines)
```

**`execute_workflow()`**: Creates `WorkflowExecutorService`, calls its one public method, wraps 2 exception types. ~30 lines of real logic. Only value: shared exception wrapping for CLI and MCP callers.

**`WorkflowExecutorService`**: Single public method, instantiated once, discarded. `self.output` used in 1 place, `self.workflow_manager` in 1 place. Contains 90 lines of dead code (`_extract_default_output` + 3 helpers — zero production callers). Should be a function with helpers, not a class.

**`WorkflowExecutor`** (different from `WorkflowExecutorService`): A PocketFlow `BaseNode` subclass for `type: workflow` nodes. Correctly placed, not an abstraction layer. Confusing name overlap.

## MCP Server Duplication

**~800 lines of duplicated logic** (24% of MCP server):

| Duplication | MCP file | CLI equivalent | Lines |
|-------------|----------|----------------|-------|
| Workflow execution pipeline | `execution_service.py:278-373` | `cli/main.py:execute_json_workflow` | ~95 |
| Validation pipeline | `execution_service.py:376-453` | `cli/main.py:_handle_validate_only_mode` | ~78 |
| Save workflow | `execution_service.py:456-579` | `cli/commands/workflow.py:save_workflow` | ~124 |
| Registry node execution | `execution_service.py:701-791` | `cli/commands/registry_run.py` | ~90 |
| Node parameter config | `execution_service.py:582-641` | `compiler.inject_special_parameters` | ~60 |
| Workflow resolution | `utils/resolver.py:18-66` | `cli/workflow_resolution.py:85-114` | ~80 |
| Workflow listing/describe | `workflow_service.py` | `cli/commands/workflow.py` | ~55 |
| Registry list/search | `registry_service.py` | `cli/commands/registry.py` | ~30 |

**MCP service layer ceremony**: 7 `@classmethod`-only classes inheriting `BaseService`. The base class provides nothing at runtime (`validate_stateless()` never called in production, `create_fresh_instances()` never overridden). `@ensure_stateless` decorator just logs debug messages. ~350 lines of class scaffolding providing only debug logging. Should be plain functions.

**Dead MCP code**: `settings_tools.py` (173), `settings_service.py` (136), `test_tools.py` (146) — all disabled. `utils/validation.py:validate_file_path()` (48) — never called. Total: ~503 lines. **CORRECTION**: `utils/errors.py:sanitize_parameters()` was originally listed here as dead — it is NOT. It's called by `executor_service.py:546`, `workflow_errors.py:84,91`, `error_formatter.py:67,70`. See `code-review-results.md` for details.

## Dual Validation System

**Check-by-check matrix:**

| Check | WorkflowValidator | _validate_workflow (compiler) | Duplicated? |
|-------|:-:|:-:|:-:|
| IR schema/structure | Full JSON Schema + refs + dup IDs | Minimal (nodes/edges exist) | PARTIAL |
| Stdin (at most one) | Step 2 | Inside prepare_inputs() | YES — identical |
| Data flow (cycles, fwd refs) | check_inputs=True | check_inputs=False | YES — same function |
| Templates | validate_workflow_templates() | validate_workflow_templates() | YES — identical call |
| Node types (registry check) | Step 5 | — | UNIQUE to WV |
| Output sources | Step 6 | — | UNIQUE to WV |
| Unknown params | Step 7 | — | UNIQUE to WV |
| Sub-workflows | Step 8 | — | UNIQUE to WV |
| Input preparation | — | prepare_inputs() | UNIQUE to compiler |
| Output name validation | — | _validate_outputs() | UNIQUE to compiler |
| Template resolution mode | — | _get_template_resolution_mode() | UNIQUE to compiler |

**Why both exist**: `_validate_workflow()` does validation AND preparation. The preparation (input defaults, type coercion, template mode) produces data the compiler needs (`initial_params` with defaults applied). This preparation doesn't belong in `WorkflowValidator`.

**Why the compiler's duplicated checks can't just be removed today**: Nested sub-workflows bypass `WorkflowValidator` — the compiler's validation is their only safety net. Phase 1 fixes this by running `WorkflowValidator` on child IR during compilation.

## Wrapper Chain

| Wrapper | Lines | + Extracted | Core Responsibility |
|---------|-------|------------|---------------------|
| TemplateAwareNodeWrapper | 772 | +480 | `${var}` resolution in node params |
| NamespacedNodeWrapper | 94 | +183 | Collision prevention (`shared[node_id][key]`) |
| PflowBatchNode | 1,033 | — | Per-item execution (seq/parallel, retry, errors) |
| InstrumentedNodeWrapper | 909 | +449 | Metrics, tracing, caching, progress, warnings, loop guard |
| **Total** | **2,808** | **+1,112** | |

**Key architectural issues (NOT addressed by this task, but context):**
1. Cross-wrapper coupling: InstrumentedNodeWrapper traverses chain to read TemplateAwareNodeWrapper.last_resolutions and PflowBatchNode._trace_items
2. Duplicate proxy boilerplate: `__getattr__`, `__rshift__`, `__sub__` repeated in each wrapper (~240 lines)
3. InstrumentedNodeWrapper is a god class: 909 lines, 6+ concerns
4. `_exec_single` / `_exec_single_with_node`: 170 lines of duplicated logic (~80% shared)

## Output Layer

**5,404 lines across 24 files, 166 functions.** Major components:

| Component | Lines | Purpose |
|-----------|-------|---------|
| `execution/formatters/` (13 files) | 3,165 | Shared "return, never print" formatters |
| `cli/workflow_output.py` | 803 | CLI text output + execution summary |
| `cli/error_output.py` | 343 | Unified error output (Task 137) |
| `node_output_formatter.py` | 944 | 3 modes × multiple node types |
| `core/output_controller.py` | 272 | Interactive detection + progress callbacks |

**Duplicated auto-detection**: `workflow_output.py:_find_auto_output` (response > output > result > text > stdout) vs `success_formatter.py:_find_auto_output` (result > output > response > text > data > stdout). Task 134 unifying this.

## Dead Code Inventory (Phase 0)

| Item | Lines | Location | Evidence |
|------|-------|----------|----------|
| `_extract_default_output` + 3 helpers | 90 | `executor_service.py:632-722` | Zero production callers, only in historical task specs |
| `planning/` directory | — | `src/pflow/planning/` | Only `__pycache__` remnants, removed in Task 92 |
| `core/workflow/__init__.py` re-exports | 59 | 18 symbols from 5 submodules | Zero consumers — everyone imports from submodules |
| MCP `settings_tools.py` | 173 | `mcp_server/tools/` | Commented out in `__init__.py` |
| MCP `settings_service.py` | 136 | `mcp_server/services/` | Serves only disabled tools |
| MCP `test_tools.py` | 146 | `mcp_server/tools/` | Commented out in `__init__.py` |
| ~~`sanitize_parameters()`~~ | ~~63~~ | ~~`mcp_server/utils/errors.py`~~ | **NOT DEAD** — called by `executor_service.py:546`, `workflow_errors.py:84,91`, `error_formatter.py:67,70` |
| `validate_file_path()` | 48 | `mcp_server/utils/validation.py` | Never called |
| Unused `core/__init__.py` re-exports | ~30 | 30+ symbols, only 2 used via this path | Only `normalize_ir` and `StdinData` consumed |
| **Total** | **~745** | | |

## Entry Point Comparison Matrix

| Aspect | CLI Exec | CLI Validate | MCP Exec | CLI Registry | MCP Registry |
|--------|----------|-------------|----------|-------------|-------------|
| Workflow resolution | `cli/workflow_resolution.py` (str only) | Same | `mcp_server/utils/resolver.py` (str+dict) | N/A | N/A |
| Input resolution | `prepare_inputs()` 5-tier | Dummy params | None | `parse_workflow_params()` | None |
| File ref resolution | Before validation | Before validation | Skipped | N/A | N/A |
| WorkflowValidator | Real params, 8 checks | Dummy params, 8 checks | Real params, 8 checks | None | None |
| Compiler validation | `_validate_workflow()` 5 checks | None | `_validate_workflow()` 5 checks | None | None |
| Shared store init | Full (6 keys) | None | Full (6 keys) | params only | Empty |
| Wrapper chain | Full (4 wrappers) | None | Full (4 wrappers) | None | None |
| Type coercion | `coerce_input_to_declared_type` | N/A | None | `coerce_to_declared_type` | None |
| Error output | Unified pipeline | `sys.exit()` | `raise RuntimeError` | `click.echo` + `sys.exit(1)` | Return string |
| Output detection | Priority A | N/A | Priority B | Namespace lookup | Namespace lookup |

## `initial_params` Flow (Critical for Phase 2)

```
CLI args / MCP params
  → executor_service._initialize_shared_store()
      shared_store.update(execution_params)     ← BEFORE compilation, no defaults
      execution_params.pop("__no_cache__")      ← mutates the dict
  → compile_ir_to_flow(initial_params=execution_params)  ← same dict object
      → _validate_workflow() MUTATES initial_params:
          initial_params["__template_resolution_mode__"] = ...
          defaults = prepare_inputs(initial_params)  ← reads, doesn't mutate
          initial_params.update(defaults)            ← adds defaults + coerced values
          initial_params["__env_param_names__"] = ...
      → _instantiate_nodes(initial_params)
          → TemplateAwareNodeWrapper(initial_params)  ← all nodes share same dict reference
              → _build_resolution_context(shared):
                  context = dict(shared)              ← shared store data
                  context.update(self.initial_params)  ← initial_params OVERRIDE

Sub-workflow:
  WorkflowExecutor.prep()
      child_params = self._extract_child_inputs()   ← FRESH dict, resolved template values
  WorkflowExecutor.exec()
      compile_ir_to_flow(initial_params=child_params)  ← full pipeline again, per item
```

Key subtlety: defaults are in `initial_params` (post-mutation) but NOT in shared store (seeded pre-mutation). The `context.update(initial_params)` override is what makes defaults available. Phase 2 must seed the store AFTER preparation.
