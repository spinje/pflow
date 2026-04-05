# Task 145: Mermaid Workflow Visualization — Progress Log

**Status**: Implementation complete, all tests passing, manually verified
**Date**: 2026-04-04

---

## Phase 1: Shared Sub-Workflow Resolver — DONE

**Created** `src/pflow/core/workflow/sub_workflow_resolver.py`

Extracts the 3-way dispatch (inline IR / file reference / saved name) that was duplicated between validator (~70 lines) and executor (~110 lines). Single function `resolve_sub_workflow(params, base_path)` returns `Optional[SubWorkflowResult]`.

- All lazy imports (no new top-level dependencies)
- Raises on failure; callers wrap in their own error handling
- Returns `None` for template references (`${...}`) and missing params

### Design decision: error contract

The resolver **raises exceptions** rather than returning error tuples. This was chosen because the two existing callers have incompatible error handling: the validator collects error strings, the executor lets exceptions propagate. Forcing both into one style would have made one worse. Instead, the resolver raises, and each caller wraps in its own `try/except`. The visualizer (third consumer) swallows exceptions silently to degrade gracefully.

### Design decision: `_resolve_from_saved` does not check `"nodes" not in ir`

Investigated whether this was a gap. Confirmed safe: `parse_markdown()` raises `MarkdownParseError("Missing '## Steps' section")` before returning an IR without `nodes`. The `if "nodes" not in result.ir` check in `_resolve_from_file` is defense-in-depth for a case that can't currently happen. Adding the same check to `_resolve_from_saved` would be dead code.

---

## Phase 2: Validator Refactored — DONE

**Modified** `src/pflow/core/workflow/validator.py`

- Replaced `_load_child_workflow` body to delegate to shared resolver (kept seen/ir_cache management)
- Deleted `_load_child_from_file` method (~70 lines removed)
- Fixed C901 complexity (collapsed dual-branch error formatting into ternary) and SIM108 lint warning

### Key insight: `seen` set checked AFTER resolution (performance trade-off)

The old validator checked `seen` **before** file I/O — if a sub-workflow was already validated, it skipped the read+parse entirely. The new code calls `resolve_sub_workflow()` first (which reads+parses), then checks `seen`. For duplicate sub-workflow references, this means the file is read twice before the second read is discarded.

**Why accepted**: Workflow files are small (KB), sub-workflow references are few, and `parse_markdown` is fast (~1ms). Moving the `seen` check before resolution would require duplicating the resolver's dispatch logic (is it a file? compute resolved path. is it a name? compute `name:{ref}` key) — defeating the purpose of extraction. The plan documented this trade-off explicitly.

### Error message format change

Old: `"Step '{node_id}': sub-workflow file not found: '{ref}' (resolved to: {path})"`
New: `"In sub-workflow '{ref_label}' (step '{node_id}'): Sub-workflow file not found: '{ref}' (resolved to: {path})"`

The existing tests used `.lower()` matching (`"not found" in e.lower()`) so this didn't break anything. But any consumer doing exact string matching on validator error messages would need updating.

**Verification**: All 18 sub-workflow validation tests pass unchanged. All 15 validator tests pass.

---

## Phase 3: Executor Refactored — DONE

**Modified** `src/pflow/runtime/workflow_executor.py`

- Replaced `_load_workflow` body to use shared resolver
- Deleted 5 helper methods: `_is_file_reference`, `_load_workflow_from_reference`, `_load_workflow_by_name`, `_resolve_safe_path`, `_load_workflow_file` (~100 lines removed)
- Removed unused imports: `parse_markdown`, `WorkflowManager`

**Modified** `src/pflow/runtime/template_validation/validator.py`
- Updated import from `WorkflowExecutor._is_file_reference` to `is_workflow_file_reference` directly

### Critical insight: cycle detection ordering changed

**Old executor**: `_resolve_safe_path()` → `_check_workflow_cycle()` → `_load_workflow_file()`. Cycle checked BEFORE file was read.

**New executor**: `resolve_sub_workflow()` (reads + parses file) → `_check_workflow_cycle()`. Cycle checked AFTER file is read.

**Impact**: If a workflow file doesn't exist AND is in the cycle stack, the old code raised `ValueError("Circular workflow reference")` but the new code raises `FileNotFoundError` from the resolver. The `test_circular_dependency_detection` test used a non-existent path (`/path/to/workflow1.json`) and expected `ValueError`. Fixed by creating a real temp file for the test.

This ordering change is harmless in production — a non-existent file can't form a real cycle, so `FileNotFoundError` is the correct error regardless.

### Critical insight: `ValueError` → `WorkflowNotFoundError` propagation change

The old `_load_workflow_by_name` caught all exceptions and wrapped in `ValueError(f"Failed to load workflow '{name}': {e}")`. The shared resolver lets the original `WorkflowNotFoundError` propagate.

**Why safe**: The Runner's exception boundary (`runner.py:122`) catches `except Exception`, which includes both `ValueError` and `WorkflowNotFoundError` (subclass of `PflowError(Exception)`). The `WorkflowNotFoundError` actually produces *better* error output because it carries `workflow_name` and `similar_names` attributes that `exception_to_diagnostics()` can use.

**Verified manually**: `uv run pflow /tmp/test-runtime-missing.pflow.md target=totally-nonexistent-xyz` shows `"Workflow 'totally-nonexistent-xyz' not found"` with guidance to run `pflow workflow list`.

### Trap: mock paths for lazy imports

The shared resolver imports `WorkflowManager` lazily inside `_resolve_from_saved()`:
```python
from pflow.core.workflow.manager import WorkflowManager
```

Initial attempt patched `pflow.core.workflow.sub_workflow_resolver.WorkflowManager` — this fails with `AttributeError` because `WorkflowManager` is never a module-level attribute of the resolver module.

**Correct patch target**: `pflow.core.workflow.manager.WorkflowManager` (the canonical location where the class is defined). This works because Python resolves the lazy import against the original module.

### Test updates required

- `test_workflow_name.py` — 6 mock paths changed, 2 assertion types changed (`ValueError` → `WorkflowNotFoundError`), 1 log message assertion removed (old "Loading workflow by name:" log was in deleted `_load_workflow_by_name`)
- `test_workflow_executor.py` — `test_circular_dependency_detection` rewritten with real temp file
- `test_workflow_executor_comprehensive.py` — `test_is_file_reference` tests `is_workflow_file_reference` directly; `test_relative_path_falls_back_to_cwd` (tested deleted `_resolve_safe_path`) replaced with `test_relative_path_no_base_raises` (tests resolver behavior); `test_workflow_file_missing` error match relaxed from `"Workflow file not found"` to `"file not found"`
- `test_workflow_manager_integration.py` — 6 mock paths changed, 2 assertions changed to `WorkflowNotFoundError`

**Verification**: All 83 executor tests pass. All 199 template validation tests pass. All integration tests pass.

---

## Phase 4: Mermaid Generator — DONE

**Created** `src/pflow/core/workflow/mermaid.py`

Pure function `generate_mermaid(ir, *, resolve_child, base_path, max_depth, direction)` produces Mermaid flowchart syntax:
- Node declarations with `id["label"]` syntax
- Edge rendering: `-->` (default), `-.->|error|` (error), `-->|action|` (named)
- Sub-workflow expansion via `subgraph` with namespaced child node IDs
- Cycle detection via `seen` set (path-based)
- Graceful degradation on resolver failure (renders as opaque node)
- Hyphen-to-underscore sanitization for mermaid IDs

### Design decision: `resolve_child` callback signature

The generator takes `resolve_child: Callable[[dict, Optional[Path]], Optional[SubWorkflowResult]]` — same signature as `resolve_sub_workflow`. This means the CLI can pass `resolve_sub_workflow` directly without a wrapper. The generator treats it as opaque and swallows all exceptions from it.

### Design decision: mermaid `seen` set vs validator `seen` set

The mermaid generator's `seen` set is checked AFTER resolution (inside `_try_resolve_child`), not before. This is different from the validator's pattern. The reason: the mermaid generator needs the `result.path` to compute the `seen` key, and that path only exists after resolution. For inline IR (no path), there's no cycle concern and no `seen` entry.

### Node type matching

The generator checks `node_type in {"workflow", "pflow.runtime.workflow_executor"}`. In practice, IR from `parse_markdown` always uses `"workflow"`. The full class path `"pflow.runtime.workflow_executor"` would only appear in programmatically-constructed IR. Both covered.

---

## Phase 5: CLI Command — DONE

**Created** `src/pflow/cli/commands/visualize.py`

Click command: `pflow visualize <workflow> [--depth N] [--direction LR|TD]`
- Resolves workflow (file path or saved name) via `resolve_workflow`
- Validates first (same pipeline as `--validate-only`)
- Outputs mermaid to stdout, diagnostics to stderr
- Exit code 1 on validation failure or not found

**Modified** `src/pflow/cli/main_wrapper.py` — added `visualize` to import and routing table.

### Design decision: validate before visualizing

The command validates the workflow before generating mermaid. Alternative: skip validation and just generate from whatever IR we have. Chose validate-first because:
1. A broken workflow produces misleading graphs (dangling edges, wrong types)
2. Consistent with `--validate-only` behavior
3. Warnings on stderr don't pollute the mermaid stdout

### Stream separation

Mermaid → stdout, warnings → stderr. This enables `pflow visualize workflow.pflow.md | pbcopy` to get clean mermaid without warning noise. Verified manually.

---

## Phase 6: Tests — DONE

**Created** 3 test files with 29 total tests:

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_core/test_sub_workflow_resolver.py` | 10 | inline IR, file ref, saved name, template, empty, relative paths, errors |
| `tests/test_core/test_mermaid.py` | 13 | pipeline, branching, direction, expansion, depth limits, cycles, escaping |
| `tests/test_cli/test_visualize.py` | 6 | simple, invalid, nonexistent, depth flag, direction flag, nested expansion |

### Test insight: `test_missing_nodes_section_raises` expects `MarkdownParseError`, not `ValueError`

The plan spec expected `ValueError` for a file without `## Steps`. In reality, `parse_markdown()` raises `MarkdownParseError` before the resolver's own `if "nodes" not in result.ir` check runs. The resolver's `ValueError` on line 108-110 is defense-in-depth for a case the parser already catches.

---

## Phase 7: CLAUDE.md Updates — DONE

- `src/pflow/core/workflow/CLAUDE.md` — added `sub_workflow_resolver.py` and `mermaid.py` to module structure, dependency graph, and key symbols table
- `src/pflow/cli/commands/CLAUDE.md` — added `visualize.py` to file overview and test mapping tables

---

## Manual Verification — DONE

Tested adversarially beyond automated tests:

| Scenario | Result |
|----------|--------|
| All 17 example workflows | 10 correct mermaid, 7 correct validation failures |
| Single-node, no edges | Renders correctly |
| Conditional branching + error edges | Correct arrow styles |
| Self-referencing workflow | Cycle detection prevents infinite loop |
| Mutual recursion (A↔B) at depth 3 | Correct expansion with cycle termination |
| Dynamic template refs (`${var}`) | Renders as opaque node |
| Missing sub-workflow at runtime | `WorkflowNotFoundError` with good message |
| Inline IR (`yaml workflow_ir`) | Expands into subgraph |
| End-to-end nested execution | `document-processor.pflow.md` runs correctly |
| Trace output after refactor | Correct nesting and source labels |
| Empty IR, dangling edges | No crashes |
| Non-existent file | Exit code 1 with error |
| Both `workflow` + `workflow_ir` in IR | Resolver picks `workflow_ir` (inline first) |
| Corrupted saved workflow file | `WorkflowValidationError` propagates correctly |

### Investigation: inline IR code block syntax

Tested `yaml` (single word) vs `yaml workflow_ir` (two words) as code block tag. With single word `yaml`, the parser stores raw YAML string as `params["yaml"]` (not a dict). With `yaml workflow_ir`, the parser YAML-parses the content and stores it as `params["workflow_ir"]` (a dict). The resolver checks `isinstance(inline_ir, dict)`, so only the two-word syntax triggers inline IR expansion. This is correct pflow syntax — documented in markdown_parser.py's `_CODE_BLOCK_TAG_TO_PARAM` and `_append_code_block`.

### Investigation: `_resolve_from_saved` nodes check

Verified that `parse_markdown()` raises `MarkdownParseError` before returning IR without `nodes`. Also verified that `WorkflowManager.load_ir()` wraps parse errors in `WorkflowValidationError`. Both paths produce clear errors — no silent empty-IR return.

**No bugs found.**

---

## Files Changed Summary

| File | Action | Lines |
|------|--------|-------|
| `src/pflow/core/workflow/sub_workflow_resolver.py` | CREATE | 137 |
| `src/pflow/core/workflow/mermaid.py` | CREATE | 142 |
| `src/pflow/cli/commands/visualize.py` | CREATE | 79 |
| `tests/test_core/test_sub_workflow_resolver.py` | CREATE | ~120 |
| `tests/test_core/test_mermaid.py` | CREATE | ~250 |
| `tests/test_cli/test_visualize.py` | CREATE | ~120 |
| `src/pflow/core/workflow/validator.py` | MODIFY | -145, +60 (net -85) |
| `src/pflow/runtime/workflow_executor.py` | MODIFY | -110, +50 (net -60) |
| `src/pflow/runtime/template_validation/validator.py` | MODIFY | 2 lines |
| `src/pflow/cli/main_wrapper.py` | MODIFY | 2 lines |
| `tests/test_runtime/test_workflow_executor/*.py` | MODIFY | mock paths, assertions |
| `tests/test_integration/test_workflow_manager_integration.py` | MODIFY | mock paths, assertions |
| `src/pflow/core/workflow/CLAUDE.md` | MODIFY | added new modules |
| `src/pflow/cli/commands/CLAUDE.md` | MODIFY | added visualize |

**Net code**: ~360 lines added (new files), ~145 lines removed (deduplication) = ~215 net new lines for 3 deliverables.

---

## Traps for Future Agents

1. **Mock path for `WorkflowManager` in resolver tests**: Must patch `pflow.core.workflow.manager.WorkflowManager`, NOT `pflow.core.workflow.sub_workflow_resolver.WorkflowManager`. The resolver uses a lazy import inside a function body, so the class is never a module-level attribute.

2. **Cycle detection happens after file I/O**: The resolver reads and parses the file before the executor checks for cycles. Tests that need cycle detection must use real files that exist on disk.

3. **`WorkflowNotFoundError` propagates from executor**: The old executor wrapped all errors in `ValueError`. Any code that catches `ValueError` from `WorkflowExecutor.prep()` to detect "workflow not found" must now catch `WorkflowNotFoundError` instead (or use the broader `PflowError`).

4. **Inline IR code blocks need two-word tag**: ` ```yaml workflow_ir ` (two words) produces a dict in `params["workflow_ir"]`. Single-word ` ```yaml ` produces a raw string in `params["yaml"]`. The resolver only recognizes the dict form.

5. **Mermaid generator swallows all resolver exceptions**: This is intentional — visualization is best-effort for sub-workflow expansion. If you need resolver errors to surface, don't use the mermaid generator's `_try_resolve_child`; call `resolve_sub_workflow` directly.

6. **Validator error messages changed format**: Old format was `"Step '{id}': ..."`, new format wraps with `"In sub-workflow '{ref}' (step '{id}'): ..."`. Tests used `.lower()` substring matching so nothing broke, but exact-match consumers would need updating.

---

## Code Review Fixes (2026-04-05)

External code review (staged diff review) found 2 bugs and 1 information-loss issue. All three confirmed and fixed.

### Fix 1: `seen` set was global visited-set, not recursion stack

**Bug**: The mermaid generator used a single `seen` set shared across the entire traversal. Once a sub-workflow path was added, it was never removed. This meant two sibling nodes referencing the same child workflow only expanded the first — the second rendered as opaque.

**Root cause**: `_try_resolve_child` did `seen.add(path_key)` but nothing ever called `seen.discard()`. The `seen` set served as a dedup/visited mechanism rather than a recursion stack for cycle detection.

**Fix**: Moved `seen` management out of `_try_resolve_child` and into `_render_workflow`. The caller now does `seen.add(path_key)` before recursing into the child and `seen.discard(path_key)` after `_render_workflow` returns. This makes `seen` a true recursion stack — cycles (A→B→A) are still detected because the path is on the stack during recursion, but siblings can independently expand the same child because the path is removed between sibling iterations.

**`_try_resolve_child` now only checks** `if result.path and str(result.path) in seen: return None` — read-only cycle check. The add/remove lifecycle is the caller's responsibility.

**Test added**: `test_sibling_same_child_both_expand` — two sibling workflow nodes referencing the same child path, both must produce `subgraph` output. Existing `test_cycle_detection` (A→A recursion) still passes.

### Fix 2: Hyphen-to-underscore sanitization caused ID collisions

**Bug**: `_to_mermaid_id` replaced hyphens with underscores. Since pflow node IDs can contain both characters (`_NODE_ID_RE = r"^[a-z][a-z0-9_-]*$"`), nodes named `foo-bar` and `foo_bar` would collide to the same mermaid ID, producing duplicate declarations and a self-edge.

**Root cause**: Overly cautious sanitization. The docstring claimed hyphens "can cause issues in some renderers" but pflow always uses bracket syntax (`id["label"]`) where hyphens are unambiguous.

**Fix**: `_to_mermaid_id` now returns the ID unchanged. Zero practical risk — hyphens are valid in Mermaid's bracket syntax, which is the only syntax this generator emits.

**Tests**: Updated `test_node_id_sanitization` to verify hyphens are preserved. Added `test_hyphen_underscore_no_collision` — two distinct nodes `foo-bar` and `foo_bar` must produce distinct mermaid IDs and a proper edge between them (not a self-edge).

### Fix 3: Visualize command dropped `similar_names` from `WorkflowNotFoundError`

**Bug**: The `visualize` command caught resolution exceptions with `click.echo(str(e))`. For `WorkflowNotFoundError`, `str(e)` produces the base message but discards the structured `similar_names` list. Users never saw "Did you mean?" suggestions. The rest of the CLI uses `exception_to_diagnostics()` → `format_diagnostic()` which renders the full structured output.

**Fix**: Replaced the manual `try/except` with the diagnostic pipeline:
```python
from pflow.core.diagnostic import exception_to_diagnostics
for diagnostic in exception_to_diagnostics(e):
    click.echo(format_diagnostic(diagnostic), err=True)
```

This is consistent with how `main.py` handles the same exception type. The `format_diagnostic` call was already imported for the validation failure path, so no new imports needed at the top level.

---

## Traps for Future Agents

1. **Mock path for `WorkflowManager` in resolver tests**: Must patch `pflow.core.workflow.manager.WorkflowManager`, NOT `pflow.core.workflow.sub_workflow_resolver.WorkflowManager`. The resolver uses a lazy import inside a function body, so the class is never a module-level attribute.

2. **Cycle detection happens after file I/O**: The resolver reads and parses the file before the executor checks for cycles. Tests that need cycle detection must use real files that exist on disk.

3. **`WorkflowNotFoundError` propagates from executor**: The old executor wrapped all errors in `ValueError`. Any code that catches `ValueError` from `WorkflowExecutor.prep()` to detect "workflow not found" must now catch `WorkflowNotFoundError` instead (or use the broader `PflowError`).

4. **Inline IR code blocks need two-word tag**: ` ```yaml workflow_ir ` (two words) produces a dict in `params["workflow_ir"]`. Single-word ` ```yaml ` produces a raw string in `params["yaml"]`. The resolver only recognizes the dict form.

5. **Mermaid generator swallows all resolver exceptions**: This is intentional — visualization is best-effort for sub-workflow expansion. If you need resolver errors to surface, don't use the mermaid generator's `_try_resolve_child`; call `resolve_sub_workflow` directly.

6. **Validator error messages changed format**: Old format was `"Step '{id}': ..."`, new format wraps with `"In sub-workflow '{ref}' (step '{id}'): ..."`. Tests used `.lower()` substring matching so nothing broke, but exact-match consumers would need updating.

7. **Mermaid `seen` set is a recursion stack, not a visited set**: `_render_workflow` adds paths before recursing and removes after returning. `_try_resolve_child` only reads the set (cycle check). If you move the add/remove back into `_try_resolve_child`, you'll re-introduce the sibling suppression bug.

8. **Don't sanitize mermaid node IDs**: Hyphens are valid in Mermaid bracket syntax (`id["label"]`). Replacing them causes collisions with underscore IDs. If you need sanitization for a different output format, create a separate function.

---

## Final State

- `make check` passes (ruff + mypy + deptry)
- `make test` passes (4460 tests, +2 from review fixes)
- No backwards-incompatible changes to public APIs
- One behavioral change: executor propagates `WorkflowNotFoundError` instead of wrapping in `ValueError` (better error output, Runner catches both)
