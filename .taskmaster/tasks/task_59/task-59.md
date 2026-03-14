# Task 59: Nested Workflows — Polish and Ship

## Status
in progress

## Dependencies
- Task 20: Implement Nested Workflow Execution (DONE — built WorkflowExecutor)
- Task 107: Markdown Format Migration (DONE — added validator/template support for `type: workflow`)

## Context

The core runtime for nested workflows already exists (~336 lines in `WorkflowExecutor`), with 48 passing tests. Task 59 is about polishing the feature into something agents and users can reliably use: fixing bugs, improving errors, creating real examples, and making it discoverable.

## Design Decision: Syntax

Nested workflows use the **same syntax as every other node** — no special concepts:

```markdown
### process_title
- type: workflow
- workflow: ./process-text.pflow.md
- text: ${document_title}
- mode: title
```

Downstream: `${process_title.normalized_text}`

**Key design choices:**
- `workflow:` parameter handles both file paths and saved workflow names (resolution: file first, then saved name)
- Child inputs are just regular params (like any other node). WorkflowExecutor separates its own config params (`workflow`, `storage_mode`, `max_depth`, `error_action`) from child inputs
- Child outputs are auto-available via the standard namespace system (`${node_id.output_name}`), same as every other node type
- No `inputs` block, no `outputs` block, no `param_mapping`, no `output_mapping`
- If child declares `## Outputs`, those keys are exposed. If not, all non-internal keys from child storage are exposed
- Complex inputs use inline YAML (`- config: {retries: 3}`) or named yaml code blocks (```yaml complex_config```)
- Default storage mode is `mapped` (child only sees what you pass). `shared` mode available as power-user escape hatch
- No output renaming — the namespace system makes it unnecessary (consistent with all other node types)

**Renamed parameters (breaking, no users):**
- `workflow_ref` / `workflow_name` → `workflow` (unified)
- `param_mapping` → removed (params ARE inputs)
- `output_mapping` → removed (namespace handles outputs)

## Implementation Plan

### Tier 1 — Fix bugs (make it not broken)

1. **Traceback suppression**: Change `logger.exception()` → `logger.debug(..., exc_info=True)` in compiler.py (lines 1024, 1053, 1060, 1214, 1235, 1242, 1249). Tracebacks only visible in debug mode; error messages propagate cleanly through the error handling chain.

2. **Relative path resolution**: Set `_pflow_workflow_file` in `executor_service._initialize_shared_store()` using the source file path. The WorkflowExecutor already reads this key at line 232 and sets it for child workflows at line 329 — the gap is only for the top-level entry.

3. **output_mapping error escalation**: Missing child key → error, not warning. (Note: this applies to the old `output_mapping` path; the new auto-output design may change this.)

### Tier 2 — Better errors (make it diagnosable)

4. **param validation against child inputs**: When child workflow is loaded in `prep()`, extract its declared `## Inputs` and compare against provided params. Give actionable errors: "Child workflow expects input 'text' (required) but it was not provided. You passed: mode, config."

### Tier 3 — Make it real (make it usable)

5. **Implement new syntax**: Refactor WorkflowExecutor to support the new design:
   - Unified `workflow` param (file path or saved name)
   - Params-as-inputs (separate executor config from child inputs)
   - Auto-output via namespace (expose child's declared outputs, or all non-internal keys)
   - Keep backward compat with `param_mapping`/`output_mapping` during transition? Decision: NO — no users, clean break

6. **Working examples**: Replace `examples/nested/` with examples using real nodes (shell, file, etc.), not `type: test`. Examples must pass validation and run end-to-end. Update README to markdown format.

7. **CLI end-to-end tests**: Tests that go through the full CLI path (not just direct executor tests). Cover: file-based workflow_ref, saved workflow_name, error cases, path resolution.

### Tier 4 — Make it discoverable

8. **Agent instructions**: Add nested workflow documentation to `src/pflow/cli/resources/cli-agent-instructions.md`. Show the simple syntax, explain that it works like any other node.

9. **Registry visibility**: Make `workflow` appear in `pflow registry list` output. Suppress unknown-param warnings for workflow executor config params.

10. **Update stale docs**: Update examples README, any references to old JSON format or `param_mapping`/`output_mapping`.

### Tier 5 — Defer

11. **Planner integration**: Re-enable `ComponentBrowsingNode` workflow context. Deferred — planner is gated (Task 107).

## Known Implementation Details

### Traceback source (verified)
`logger.exception()` calls in `compiler.py` at lines 1024, 1053, 1060, 1214, 1235, 1242, 1249. These fire during child sub-workflow compilation inside `WorkflowExecutor.exec()`, printing tracebacks to stderr before the exception reaches the catch block.

### Path resolution gap (verified)
CLI stores `source_file_path` in `ctx.obj` at `main.py:3414`. `executor_service._initialize_shared_store()` copies `execution_params` into shared store but never sets `_pflow_workflow_file`. Fix: inject it in `_initialize_shared_store()` or pass it through execution_params.

### WorkflowExecutor config params (reserved, not passed to child)
`workflow`, `workflow_ref`, `workflow_name`, `workflow_ir`, `storage_mode`, `max_depth`, `error_action`, `scope_prefix`, `__registry__`

### Auto-output design
- Child runs in isolated storage (mapped mode)
- After execution, `post()` reads child's declared `## Outputs` from the child IR
- Writes those outputs to parent shared store (NamespacedNodeWrapper handles namespacing)
- If child has no `## Outputs`, expose all non-internal keys (`_pflow_*`, `__*__` filtered out)

## Test Strategy

- Unit tests: WorkflowExecutor with new syntax (params-as-inputs, auto-outputs)
- Integration tests: Full compilation + execution with nested workflows
- CLI tests: End-to-end through `pflow` CLI
- Validation tests: Template validator correctly resolves `${workflow_node.output}` references
- Error tests: Missing child inputs, wrong params, file not found, circular deps, max depth
- Example validation: `examples/nested/*.pflow.md` all parse and run

## Files to Modify

- `src/pflow/runtime/workflow_executor.py` — main refactor (new syntax, auto-outputs)
- `src/pflow/runtime/compiler.py` — traceback suppression, output handling for new design
- `src/pflow/runtime/template_validator.py` — update output extraction for auto-outputs
- `src/pflow/execution/executor_service.py` — set `_pflow_workflow_file`
- `src/pflow/core/workflow_validator.py` — may need updates for new param names
- `examples/nested/` — replace with working examples
- `tests/test_runtime/test_workflow_executor/` — update tests for new syntax
- `src/pflow/cli/resources/cli-agent-instructions.md` — add nested workflow docs
- `src/pflow/cli/main.py` — pass source file path for resolution

## Research Files (context, partially outdated)

- `research/nested-workflows-spec.md` — old JSON-format spec, concepts valid but syntax outdated
- `research/error-handling-patterns.md` — error dict patterns, still valid
- `research/nested-workflow-fix-summary.md` — planner fix context (Tier 5)
- `research/browsing-node-workflows-context.md` — planner context (Tier 5)
- `starting-context/braindump-nested-workflow-gaps.md` — technical gap analysis, most current
- `starting-context/braindump-agent-instructions-for-nested-workflows.md` — agent UX discussion
