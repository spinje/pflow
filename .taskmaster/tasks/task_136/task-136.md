# Task 136: Recursive Sub-Workflow Validation at Parse Time

## Description

Sub-workflow validation errors (missing descriptions, unknown node types, data flow issues) are only caught at execution time, after all upstream nodes have run. This wastes time and money on LLM calls that get thrown away. This task adds recursive sub-workflow validation at parse time plus fixes three related pre-existing bugs discovered during investigation.

## Status

done

## Priority

high

## Problem

When a workflow references a sub-workflow with a validation error (e.g., missing step description), pflow discovers the error only when `WorkflowExecutor.prep()/exec()` runs at runtime. All upstream nodes execute first. In real pipelines (music-generation), this wastes ~$1.80 and ~350s per failed run.

The 7-step validation pipeline in `WorkflowValidator.validate()` explicitly skips `type: workflow` nodes (`validator.py:205`). The template validation path (`_resolve_child_workflow_outputs()`) already loads and parses sub-workflow files but wraps everything in `except Exception: return None`, silently discarding parse errors.

**Pre-existing bugs discovered during investigation:**

1. **`inputs` framework key leaks into child workflows.** The `inputs` key (Task 161) is NOT in `WorkflowExecutor.RESERVED_PARAMS`, so `_extract_child_inputs()` passes it through as a child input named `"inputs"`, polluting the child's execution context.

2. **Conflicting "required input" heuristics.** `_validate_child_params()` uses `"default" not in input_spec` while `prepare_inputs()` and 10+ other consumers use `input_spec.get("required", True)`. These disagree on `{required: false}` without a default — the former falsely rejects it.

3. **Display bugs.** `context.py:144-145` uses `.get("required", False)` (wrong default), `discovery_formatter.py:162` and `cli/commands/mcp.py:612` use bare `.get("required")` returning `None` (falsy).

## Solution

Four changes shipping together:

1. **Add `"inputs"` to `RESERVED_PARAMS`** — prevents framework key from leaking to child workflows
2. **Harmonize "required" heuristic** — fix `_validate_child_params()` to use `input_spec.get("required", True)`, fix 3 display bugs
3. **Add step 8 to `WorkflowValidator.validate()`** — recursive sub-workflow validation with cycle detection, parse error surfacing, full 7-step validation on each child, and static required-input checking
4. **Thread `_pflow_workflow_file` into validate-only paths** — enables correct relative path resolution for sub-workflows in `--validate-only` and MCP validate modes

## Key Insights

### Error categorization framework (A/B/C)

We categorized every validation check in the system by what information it needs:

| Category | What it needs | ~% of checks | Examples |
|----------|--------------|-------------|----------|
| **A — Structural** | Just the IR dict | ~90% | Parse errors (missing description), schema, data flow, node types, output sources, unknown params, template syntax |
| **B — Input keys** | Which input *names* exist (not values) | ~5% | Template path existence: is `${my_input}` a known variable? Checks `base_var in initial_params` — key membership only |
| **C — Runtime values** | Actual resolved values | ~5% | Required input presence, empty string check, type coercion |

This categorization drove the approach: mock inputs enable A+B validation, static key comparison catches the most important C check, and the remaining C checks (type coercion, empty strings) are inherently runtime.

### Mocking inputs — what it does and doesn't solve

Investigated thoroughly with 4 parallel research agents. `generate_dummy_parameters()` produces `"__validation_placeholder__"` (a string) for every declared input. When passed to `WorkflowValidator.validate()`, this enables:
- **Category A**: All structural checks run normally (they don't look at param values)
- **Category B**: Template path existence passes (`base_var in initial_params` succeeds because the key exists)
- **Category C — required input presence**: **NOT helped by mocking.** If we mock ALL child inputs, they're all "present" — we lose the ability to detect that the PARENT doesn't provide one. Static key comparison is strictly better.
- **Category C — type coercion**: **NOT helped.** `prepare_inputs()` uses lenient coercion (`coerce_input_to_declared_type()` in `param_coercion.py`). When coercion fails (e.g., `int("__validation_placeholder__")`), it catches the exception, logs a warning, and returns the original value — by design. No error is ever produced.
- **Category C — empty strings**: **NOT helped.** Placeholder is non-empty.

**Conclusion:** Use mocking for enabling `WorkflowValidator.validate()` on child IR (A+B). Use static key comparison for required inputs (the valuable part of C). They're complementary, not overlapping.

### Two independent validation pipelines

pflow has two separate validation systems:

1. **`WorkflowValidator.validate()`** — Pre-execution, 7-step pipeline. Called by CLI `_validate_before_execution()`, `execute_workflow()`, MCP server, save service. Does NOT have `_pflow_workflow_file` in some paths.
2. **`_validate_workflow()` in `compile_validation.py`** — Compile-time, called inside `compile_ir_to_flow()`. Has `_pflow_workflow_file` via `initial_params`. Runs for sub-workflows at runtime inside `WorkflowExecutor._compile_sub_workflow()`.

These pipelines share `validate_workflow_templates()` but are otherwise independent. We add sub-workflow validation to pipeline 1 (pre-execution) because that's where the "catch errors before any execution" guarantee lives. Pipeline 2 already validates sub-workflows — just too late (at runtime).

### Why full recursive validation, not the minimal fix

We considered three options:
- **Option 1 (minimal)**: Stop swallowing errors in `_resolve_child_workflow_outputs()`. Catches the exact reproduction bug (parse errors). But: only catches parse-level errors, only for nodes that have template references from the parent, doesn't recurse into nested sub-workflows.
- **Option 2 (full recursive validation)**: New step 8 in `WorkflowValidator.validate()`. Catches ~95% of all validation errors at any nesting depth. More code but fundamentally more complete.
- **Option 3 (Option 2 + inline `workflow_ir`)**: Same as 2 but also handles inline IR. Marginal value but included naturally.

Chose Option 2 because the bug report's principle ("compiler checking imports before execution") demands structural completeness, not just parse-error detection. A data flow error or unknown node type in a sub-workflow is equally wasteful to discover at runtime.

### `_pflow_workflow_file` is simpler than expected

Initially planned to add a new `workflow_file_path` parameter to `WorkflowValidator.validate()`. Investigation revealed `_pflow_workflow_file` already flows through `extracted_params` for execution paths:
- CLI execution: set in `_prepare_execution_environment()` → passed as `extracted_params` to `validate()`
- MCP execution: set in `_inject_workflow_file_path()` → passed as `execution_params` to `validate()`

Only missing in `--validate-only` and MCP validate paths (which use dummy params without it). Fix: inject `_pflow_workflow_file` into dummy params at those 2 call sites. No new parameter on `validate()` needed for the file path.

## Design Decisions

- **Step 8 in `WorkflowValidator.validate()`, not inside `validate_workflow_templates()`**: Sub-workflow structural validation is a peer concern alongside data flow, node types, etc. — not a sub-concern of template validation. This keeps the validator as the single source of truth for "is this workflow valid?"

- **Accept double-loading of child IRs**: `_resolve_child_workflow_outputs()` (template validation) already loads child IRs for output resolution. Step 8 loads them again for validation. These are small markdown files and parsing is fast. Avoiding the redundancy would couple two independent validation concerns.

- **`_seen` parameter for cycle detection**: Added as a private optional param `_seen: Optional[set[str]] = None` on `validate()`. Backward-compatible — no external caller needs to change. Created on first call, threaded through recursive calls. Pattern follows `dependency_discovery.py:60-61`.

- **Option B for required heuristic**: `input_spec.get("required", True)` wins. It's what the IR schema declares (`ir_schema.py:269`), what `prepare_inputs()` uses, and what 10+ other consumers use. `_validate_child_params()` is the only outlier.

- **`"inputs"` added to `RESERVED_PARAMS`, not filtered separately**: Simplest fix. Only affects `WorkflowExecutor._extract_child_inputs()` (the single consumer). No existing workflow passes `"inputs"` as a sub-workflow child input. Code nodes (which use `inputs` heavily) go through a completely different execution path.

- **Static key comparison for required inputs**: At validation time, param keys are always static in the IR (YAML parsing produces string keys, no template resolution on keys). We can compare `parent_provided_keys - RESERVED_PARAMS - __prefixed` against child required inputs without any runtime values.

- **Error format: flat strings with prefix**: The entire validation system uses `list[str]`. No tree structure exists. Prefixing errors with `"In sub-workflow './path.pflow.md' (step 'node-id'): ..."` follows existing patterns. Nested prefixes chain naturally through recursion.

- **Template workflow refs (`${var}`) silently skipped**: Can't resolve at validation time. Not an error — validated at runtime.

- **File-not-found is a validation error, not a silent skip**: If a sub-workflow file reference doesn't exist, produce an error. Only template refs are silently skipped.

- **Don't modify `_resolve_child_workflow_outputs()`**: Its silent error handling is appropriate for its purpose (best-effort output extraction for template validation). The new step 8 is a separate concern with different error semantics.

## Dependencies

None. All code paths being modified exist and are stable.

## Requirements

### Core Validation (Step 8)

- For each `type: workflow` node in the parent IR with a resolvable reference (file path, saved name, or inline `workflow_ir`), load the child IR and run full `WorkflowValidator.validate()` recursively
- Parse errors in child workflows (e.g., missing description) surface as validation errors with sub-workflow context prefix
- Cycle detection prevents infinite recursion — uses `set[str]` of resolved paths, pattern from `dependency_discovery.py`
- Template workflow refs (`${var}` in workflow path) are silently skipped
- File-not-found and load errors produce validation errors (not silent skips)
- Three resolution paths: file reference (via `is_workflow_file_reference()`), saved name (via `WorkflowManager.load_ir()`), inline `workflow_ir` dict

### Static Required-Input Checking

- For each sub-workflow, compare parent-provided keys (node params minus `RESERVED_PARAMS` minus `__`-prefixed) against child's required inputs
- Use harmonized heuristic: required if `input_spec.get("required", True)` and `"default" not in input_spec`
- Missing required inputs produce validation errors identifying the missing input name and which step it's on

### `RESERVED_PARAMS` Fix

- `"inputs"` added to `WorkflowExecutor.RESERVED_PARAMS`
- `_extract_child_inputs()` no longer passes `inputs` to child workflows at runtime

### Required Heuristic Harmonization

- `_validate_child_params()` uses `input_spec.get("required", True)` instead of `"default" not in input_spec`
- `context.py:144-145`: `.get("required", False)` changed to `.get("required", True)`
- `discovery_formatter.py:162`: `.get("required")` changed to `.get("required", True)`
- `cli/commands/mcp.py:612`: `.get("required")` changed to `.get("required", True)`

### Validate-Only Path Fix

- CLI `_perform_validation()` receives source file path and injects `_pflow_workflow_file` into dummy params
- MCP `validate_workflow()` injects `_pflow_workflow_file` for file and library sources
- Relative sub-workflow paths resolve correctly in `--validate-only` mode (no longer falling back to `cwd`)

### Backward Compatibility

- `WorkflowValidator.validate()` signature change is backward-compatible (new `_seen` param has default `None`)
- `_perform_validation()` signature change is backward-compatible (new `source_file_path` param has default `None`)
- All existing tests pass without modification

## Implementation Notes

### Key file: `src/pflow/core/workflow/validator.py`

The `_validate_sub_workflows()` static method is the core implementation. It:
1. Iterates `workflow_ir["nodes"]` for `type` in `{"workflow", "pflow.runtime.workflow_executor"}`
2. Determines child reference from `params.get("workflow_ir")` (inline) or `params.get("workflow")` (file/name)
3. Resolves file paths relative to `extracted_params.get("_pflow_workflow_file")`, falling back to `Path.cwd()`
4. Checks `_seen` for cycles, adds current path
5. Loads child IR: `parse_markdown()` for files, `WorkflowManager().load_ir()` for names, direct dict for inline
6. Catches `MarkdownParseError` and converts to prefixed validation error
7. Generates dummy params via `generate_dummy_parameters(child_ir.get("inputs", {}))`
8. Injects `_pflow_workflow_file` pointing to child's file path into dummy params
9. Calls `WorkflowValidator.validate(child_ir, dummy_params, registry, _seen=seen)` recursively
10. Prefixes each returned error: `f"In sub-workflow '{ref}' (step '{node_id}'): {error}"`
11. Runs static required-input check comparing parent-provided keys against child declared inputs

**Imports** (lazy, inside the method):
- `from pathlib import Path`
- `from pflow.core.markdown_parser import MarkdownParseError, parse_markdown`
- `from pflow.core.file_resolver import is_workflow_file_reference`
- `from pflow.core.validation_utils import generate_dummy_parameters`
- `from pflow.runtime.workflow_executor import WorkflowExecutor`
- `from pflow.core.workflow.manager import WorkflowManager`

### Patterns to follow

- `dependency_discovery.py:80-117` — recursion with cycle detection via `seen: set[str]`
- `template_validation/validator.py:471-532` — `_resolve_child_workflow_outputs()` for file/name/inline resolution logic
- `validation_utils.py:6-29` — `generate_dummy_parameters()` for creating placeholder params

### Edge cases

- **Batch nodes**: Param keys are static even in batch (`text: ${item}` — key `text` is known). Static key comparison works.
- **`${item.field}` patterns**: Keys like `title: ${item.title}` have static key `title`. Works.
- **Bundled workflows**: Bundling is file-copy, not IR inlining. Sub-workflows keep `workflow: ./sub.pflow.md` as file refs. Validation handles this normally.
- **Saved workflow names**: Loaded via `WorkflowManager.load_ir()`. The `_seen` set uses `"name:<workflow_name>"` for dedup.
- **`_pflow_workflow_file` availability**: Already in `extracted_params` for CLI execution and MCP execution paths. Only missing for `--validate-only` and MCP validate (fixed in Change 4).

### What NOT to change

- Don't modify `_resolve_child_workflow_outputs()` — it serves a different purpose (output extraction for template validation) and its silent error handling is appropriate for that use case
- Don't change the `compile_validation.py` pipeline — it runs during compilation, not pre-execution validation
- Don't build tree-structured errors — the entire system is `list[str]`, changing that requires 6+ file modifications

## Verification

### Manual reproduction

```bash
# Should fail INSTANTLY with validation error (0 LLM calls, $0 cost):
uv run pflow scratchpads/sub-workflow-validation-bug/parent-workflow.pflow.md items='["hello", "world"]' --no-cache

# Deep nesting — also instant failure:
uv run pflow scratchpads/sub-workflow-validation-bug/deep-parent-workflow.pflow.md items='["hello", "world"]' --no-cache

# Validate-only mode:
uv run pflow --validate-only scratchpads/sub-workflow-validation-bug/parent-workflow.pflow.md
```

Expected: Validation error mentioning "missing a description" with sub-workflow context. Zero LLM calls. Instant failure.

### New tests (`tests/test_core/test_sub_workflow_validation.py`)

1. **Broken sub-workflow caught at validation time** — parent refs child with missing description, expect error
2. **Valid sub-workflow passes** — no errors
3. **Nested validation (3 levels)** — parent → middle → broken child, chained prefix in error
4. **Circular reference** — A refs B, B refs A, terminates without crash
5. **Missing required input** — parent omits required child input, error identifies missing input
6. **Template workflow ref skipped** — `workflow: ${dynamic}`, no error
7. **Inline `workflow_ir` validated** — broken inline IR, expect error
8. **Saved workflow name validated** — save broken workflow, validate parent referencing it
9. **Unknown node type in child** — child has `type: nonexistent`, error caught
10. **Data flow error in child** — child has circular dependency, error caught
11. **`required: false` without default not flagged** — harmonized heuristic, no false positive

### Extended existing tests

12. **`_extract_child_inputs()` excludes `"inputs"`** — after RESERVED_PARAMS change
13. **`_validate_child_params()` with `required: false`** — no longer falsely rejects

### Automated

```bash
make test    # Full test suite passes
make check   # Lint + type checks pass
```

## References

- Reproduction files: `scratchpads/sub-workflow-validation-bug/` (README, parent, deep-parent, middle, broken-sub-workflow)
- Existing validation: `src/pflow/core/workflow/validator.py` (7-step pipeline)
- Child IR loading: `src/pflow/runtime/template_validation/validator.py:471-532` (`_resolve_child_workflow_outputs()`)
- Dependency discovery pattern: `src/pflow/core/workflow/dependency_discovery.py:80-117`
- Runtime sub-workflow execution: `src/pflow/runtime/workflow_executor.py`
- Dummy params: `src/pflow/core/validation_utils.py:6-29`
- Task 106 review (cache context): `.taskmaster/tasks/task_106/task-review.md`
- Implementation plan: `.taskmaster/tasks/task_136/implementation/implementation-plan.md`
