# Task 59 Implementation Progress Log

## Implementation Steps

1. **Tier 1a**: Traceback suppression — change `logger.exception()` → `logger.debug(..., exc_info=True)` in compiler.py
2. **Tier 1b**: Relative path resolution — set `_pflow_workflow_file` in executor_service
3. **Tier 1c**: output_mapping error escalation (old API, may be superseded by new design)
4. **Tier 2**: param validation against child inputs — actionable error messages
5. **Tier 3a**: Implement new syntax — unified `workflow` param, params-as-inputs, auto-outputs
6. **Tier 3b**: Working examples with real nodes
7. **Tier 3c**: CLI end-to-end tests
8. **Tier 4a**: Agent instructions in cli-agent-instructions.md
9. **Tier 4b**: Registry visibility and warning suppression
10. **Tier 4c**: Update stale docs

---

## 2026-03-14 — Pre-implementation Research & Design

### What we found

**Existing state**: WorkflowExecutor runtime node exists (~336 lines), 48 passing tests, full compiler/validator integration. Task 20 built the runtime, Task 107 added validation support. The task file said "not started" but significant infrastructure exists.

**Baseline**: 3857 passed, 485 skipped, `make check` clean.

**Examples don't run**: `examples/nested/main-workflow.pflow.md` fails at static validation — template variables `${document_title}` and `${document_body}` have no source (no `## Inputs` declared). Child workflow uses `type: test` (internal-only node).

**Traceback source identified**: `logger.exception()` calls in `compiler.py` at lines 1024, 1053, 1060, 1214, 1235, 1242, 1249. Fire during child sub-workflow compilation inside `WorkflowExecutor.exec()`. The wrappers and PocketFlow framework are clean.

**Path resolution gap confirmed**: CLI stores `source_file_path` in `ctx.obj` at `main.py:3414` but never injects it into shared store as `_pflow_workflow_file`. WorkflowExecutor reads this key at line 232, falls back to `Path.cwd()`.

### Design decision: Syntax

Decided on **Option C — same syntax as any other node**:

```markdown
### process_title
- type: workflow
- workflow: ./process-text.pflow.md
- text: ${document_title}
- mode: title
```

Downstream: `${process_title.normalized_text}`

Key choices:
- `workflow:` unified param (file path or saved name, resolution: file first then saved)
- Child inputs are regular params (WorkflowExecutor separates its config params from child inputs)
- Child outputs auto-available via namespace (`${node_id.key}`), like every other node
- No `inputs`/`outputs` blocks, no `param_mapping`/`output_mapping`
- If child has `## Outputs`, expose those. Otherwise expose all non-internal keys
- No output renaming — namespace system makes it unnecessary
- Default storage mode: mapped. `shared` available as escape hatch
- Breaking change from old API — no users, clean break

### Decisions made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Type name | `workflow` | Clear, simple |
| Reference param | `workflow:` (unified) | Handles file paths and saved names |
| Input passing | Regular params | Consistent with all other nodes |
| Output access | Auto via namespace | Consistent with all other nodes |
| Output renaming | Not supported | Namespace handles it, no other node has this |
| Storage modes | mapped (default) + shared | Others are theoretical, no use case |
| Backward compat | No | No users, clean break |

### Research docs assessment

- `braindump-nested-workflow-gaps.md` — most valuable, accurate gap analysis
- `braindump-agent-instructions-for-nested-workflows.md` — good strategic context
- `nested-workflows-spec.md` — outdated (JSON format), concepts valid
- `error-handling-patterns.md` — valid patterns, references dead code exceptions that were removed
- `nested-workflow-fix-summary.md` — planner context, relevant for Tier 5 only
- `browsing-node-workflows-context.md` — planner context, relevant for Tier 5 only

---

## 2026-03-14 — Tier 1 Implementation Complete

### Fix 1a: Traceback suppression
Changed 7 `logger.exception()` → `logger.debug("...", exc_info=True)` in `compiler.py` at lines 1024, 1053, 1060, 1214, 1235, 1242, 1249. Tracebacks now only appear in debug mode. Added test `TestCompilerLogging::test_compilation_error_no_error_log`.

### Fix 1c: output_mapping error escalation
Changed `post()` in `workflow_executor.py` to collect missing output_mapping keys and return error action (instead of just logging a warning). Valid mappings are still applied before erroring. Added `test_missing_output_key_custom_error_action` test.

- 💡 Insight: Discovered that `output_mapping` was fundamentally broken with namespaced child outputs. The old code silently ignored missing keys (warning only), masking that the namespaced child writes to `child_storage["node_id"]["key"]`, not `child_storage["key"]`. Two integration tests (`test_inline_workflow_execution`, `test_nested_workflow_execution`) had output_mapping that was always silently failing. Removed the output_mapping from those tests since they test execution flow, not mapping.

### Fix 1b: Relative path resolution
Injected `_pflow_workflow_file` into `enhanced_params` in `_prepare_execution_environment()` (`main.py:1373`). The key flows through `executor_service._initialize_shared_store()` → `shared_store.update(execution_params)` → available to `WorkflowExecutor._resolve_safe_path()`. Added two tests: CWD fallback and flow-through verification.

### Results
- 3861 passed, 485 skipped (was 3857 — +4 net new tests)
- `make check` clean (ruff, mypy, deptry all pass)
- All 51 workflow executor tests pass

---

## 2026-03-14 — Tier 2 Implementation Complete

### Fix: param validation against child inputs
Added `_validate_child_params()` method to `WorkflowExecutor` that runs in `prep()` after loading the child IR and resolving param_mapping. Compares provided child params against child's declared `## Inputs`.

Error message format:
```
Child workflow './process-text.pflow.md' is missing required inputs:
  - text (string): The text to process
You provided: wrong_name, config
Available inputs: text, mode
```

- Only required inputs (no default) trigger errors
- Workflows without declared inputs skip validation entirely
- Runs before compilation, so errors are clean (no traceback)

Two integration tests needed updating — they called `prep()` without providing required child inputs. The validation correctly caught them.

### Tests added
- `test_missing_required_child_input_gives_actionable_error` — verifies error message content
- `test_all_required_inputs_provided_passes` — happy path with required + default inputs
- `test_no_declared_inputs_skips_validation` — backward compat for workflows without inputs

### Results
- 3864 passed, 485 skipped (+3 net new tests)
- All 54 workflow executor tests pass

---

## 2026-03-14 — Tier 3 Implementation Complete

### Step 1: WorkflowExecutor refactored

Full rewrite of `src/pflow/runtime/workflow_executor.py`:
- **Unified `workflow` param**: Single param handles file paths (detected by `/`, `\`, `.` prefix, `.pflow.md` suffix) and saved workflow names. `_is_file_reference()` static method does classification.
- **Params-as-inputs**: `RESERVED_PARAMS` frozenset defines executor config params. Everything else in `self.params` becomes child input. `_extract_child_inputs()` + `_resolve_child_inputs()` handle extraction and template resolution.
- **Auto-outputs in `post()`**: If child declares `## Outputs`, only those are exposed. If not, all non-internal, non-input keys from child_storage are exposed. NamespacedNodeWrapper handles namespacing automatically.
- **Removed**: `workflow_ref`, `workflow_name`, `param_mapping`, `output_mapping`, `scope_prefix`, `isolated` mode, `scoped` mode
- **Kept**: `workflow_ir` (inline), `storage_mode` (mapped/shared), `max_depth`, `error_action`

### Step 2: Template validator updated

- `_resolve_child_workflow_outputs()` — new static method that tries to load child workflow and extract `## Outputs` declarations. Handles file refs (with relative path resolution via `_pflow_workflow_file`), saved names (via WorkflowManager), and inline IR. Failures return None → dynamic fallback.
- `_extract_node_outputs()` — updated for workflow nodes: uses resolved child outputs when available, marks as `is_workflow_dynamic` when not. Added `initial_params` parameter for file path resolution.
- `_validate_namespaced_output()` — added dynamic workflow fallback: when `node_output_key` not found but node is `is_workflow_dynamic`, returns `(True, None)` instead of error.

### Step 3: Compiler cleaned up

Removed redundant `output_mapping` loop in `_validate_outputs()` (lines 1124-1131 of old code). `_extract_node_outputs()` now handles all workflow output registration.

### Step 4: All tests rewritten (~54 → 56 new tests)

4 test files completely rewritten:
- `test_workflow_executor.py` — 7 tests (was 6)
- `test_workflow_executor_comprehensive.py` — 33 tests (was 32, removed isolated/scoped/output_mapping tests, added params-as-inputs/auto-output tests)
- `test_integration.py` — 8 tests (was 7, added auto_output_exposure test)
- `test_workflow_name.py` — 8 tests (was 9, removed all_three_params test)

Also updated:
- `tests/test_integration/test_workflow_manager_integration.py` — 6 tests using old API updated
- `tests/test_runtime/test_output_validation.py` — 1 test using old output_mapping updated
- `tests/test_core/test_workflow_validator.py` — replaced output_mapping test with 2 new auto-output tests

### Step 5: Working examples

Replaced `examples/nested/` with real working examples:
- `to-uppercase.pflow.md` — child workflow (shell node, `## Inputs`, `## Outputs`)
- `document-processor.pflow.md` — parent workflow calling child twice
- Updated `README.md` with new syntax docs
- Deleted old examples (main-workflow, process-text, isolated-processing)

Verified: `pflow examples/nested/document-processor.pflow.md title="Hello World" body="some text"` runs end-to-end successfully.

### Step 6: CLI end-to-end tests

New file `tests/test_cli/test_nested_workflow_cli.py` with 4 tests:
- `test_nested_workflow_e2e` — full execution with output verification
- `test_nested_workflow_validate_only` — `--validate-only` passes
- `test_nested_workflow_missing_input_error` — clean error for missing required input
- `test_nested_workflow_relative_path` — relative path resolution from parent dir

### Key insight: output_mapping was fundamentally broken with namespacing

The old `output_mapping` design wrote to `shared[parent_key]` in `post()`, but the NamespacedNodeWrapper intercepted this and put it at `shared[node_id][parent_key]`. So the mapped key was at `shared["process_title"]["mapped_name"]` — but downstream templates expected `${process_title.mapped_name}`, which is what the namespace provides. The auto-output design is cleaner: write to `shared[output_name]`, namespace wraps it automatically.

### Results
- 3871 passed, 485 skipped (was 3864, +7 net new tests)
- `make check` all clean (ruff, mypy, deptry)
- End-to-end example works: `pflow examples/nested/document-processor.pflow.md title="Hello" body="World"`
- Validation works: `pflow --validate-only examples/nested/document-processor.pflow.md`

---

## 2026-03-14 — Post-Tier 3: High-Value Test + Code Review Fixes

### High-value test added

`test_three_level_nesting_with_relative_paths` — 3-level nesting (parent → child → grandchild) with relative file paths across directories. Validates `_pflow_workflow_file` propagation at depth 3. This was identified as the one gap that could catch real bugs (path resolution breaking at depth > 2). Test passes.

### Code review fixes (from two external reviews)

**From review 1:**
- **W1 — Silent exception swallowing**: Added `logger.debug()` with `exc_info=True` to both catch blocks in `_resolve_child_workflow_outputs()`. Failures now discoverable in debug logs.
- **W3 — Inline IR without `nodes` key**: Added validation in `_load_workflow()` — catches malformed inline IR with a clear error ("must contain 'nodes'") instead of a generic compilation error later. Extracted `_load_workflow()` helper from `prep()` to keep within ruff C901 complexity limit.

**From review 2:**
- **Critical: Saved workflows don't set `_pflow_workflow_file`**: When running `pflow my-saved-workflow`, the `source == "saved"` branch in `_setup_workflow_execution()` never set `ctx.obj["source_file_path"]`. This meant relative `workflow:` references in saved workflows resolved from CWD instead of the saved workflow's directory. Fixed by calling `WorkflowManager.get_path()` to set `source_file_path` for saved workflows.
- **Warning: `runtime/CLAUDE.md` stale**: Updated the WorkflowExecutor section to document the new API (unified `workflow` param, params-as-inputs, auto-outputs, removed `param_mapping`/`output_mapping`/`isolated`/`scoped`).

### Results
- 3872 passed, 485 skipped (+1 net new test: 3-level nesting)
- `make check` all clean

---

## 2026-03-14 — Tier 4 Implementation Complete

### Agent instructions (`cli-agent-instructions.md`)

Four changes to the 2084-line agent instructions file:

1. **Node Type Selection** (Part 2): Added `workflow` node to the decision tree alongside shell/code/llm/http/mcp. Shows that child outputs are available via `${node_id.output_name}` and child must declare `## Inputs` and `## Outputs`.

2. **"One Workflow or Multiple?" section** (Part 1): Added third option "Compose with Nested Workflows" between single and multiple workflows. Covers reuse across parents, decomposition of complex workflows, independent testing of sub-workflows.

3. **Workflow Patterns** (Part 6): Added "Pattern: Nested Workflow Composition" with a complete example showing parent calling `to-uppercase.pflow.md` child twice. Key points cover params-as-inputs, namespace-based output access, file path and saved name support.

4. **Workflow Smells table** (Part 7): Updated "30+ nodes" fix from "Break into multiple workflows" to "Break into nested sub-workflows or multiple workflows".

### Architecture docs (`architecture/architecture.md`)

Updated the WorkflowExecutor example (lines 502-517) from old API (`workflow_ref`, `param_mapping`) to new syntax (`workflow`, direct params). Updated internal description to reflect auto-output exposure.

### Registry visibility — skipped

Unknown-param warnings are already suppressed for `workflow` nodes. `_validate_unknown_params()` skips nodes with no `known_keys`, and since `workflow` isn't registered, the check is bypassed automatically. Adding to `pflow registry list` would require a virtual registry entry with edge case handling — low value since agents discover the feature through instructions.

### Stale docs audit

Investigated `ir_schema.py` `mappings` field and `shared-store.md` `input_mappings`/`output_mappings` references — these are about NodeAwareSharedStore proxy mappings (different feature), not nested workflow param_mapping. Left untouched.

### Test fix

`test_create_instructions_returns_full_content` had a line count assertion `<= 2100`. The new content brought the file to 2151 lines (2147 in output). Bumped upper bound to 2200.

### Results
- 3872 passed, 485 skipped (no new tests — documentation-only changes)
- `make check` all clean
