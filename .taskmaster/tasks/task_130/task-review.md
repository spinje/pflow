# Task 130 Review: Workflow Bundling on Save

## Metadata
- Implementation Date: 2026-03-22
- Branch: `feat/workflow-bundling-save`

## Executive Summary

Changed `pflow workflow save` from single-file copies to folder-based bundles. Workflows are now saved as `~/.pflow/workflows/{name}/{name}.pflow.md` with all file dependencies (sub-workflows, prompts, scripts) copied alongside preserving relative directory structure. This fixes an existing bug where saved workflows with sub-workflow or file references broke because dependencies didn't exist at the saved location. The change touches every path in WorkflowManager (7 methods), adds a new dependency discovery module, and updates CLI/MCP/formatter layers. 4220 tests pass, 56 new.

## Implementation Overview

### What Was Built

1. **Folder-based WorkflowManager** — All 7 public methods rewritten. `save()` uses `tempfile.mkdtemp()` + `os.rename()` for atomic directory creation. Internal helpers `_workflow_dir(name)` and `_entry_point(name)` centralize path construction.

2. **Dependency discovery module** (`dependency_discovery.py`) — Recursive scanner that finds file references in node params, sub-workflow file references, batch config files, and batch item file refs. Uses `seen` set for cycle detection.

3. **Bundling pipeline** — `save_service.py:_discover_and_bundle_deps()` discovers deps, computes bundle-relative paths from the parent workflow's directory, passes to `WorkflowManager.save()` which copies files into the bundle.

4. **Security hardening** — Path traversal protection (cross-tree deps rejected, `is_relative_to()` containment check), raw markdown file-ref rejection, silent exception elimination.

5. **Shared heuristic** — `is_workflow_file_reference()` extracted to `file_resolver.py`, imported by both `dependency_discovery.py` and `workflow_executor.py`.

### Deviations from Spec

- **Skills integration removed from scope** — User decided to rework skills separately (no more symlinks; SKILL.md will become standalone documentation). `skill_service.py` not modified. Current skill symlinks will break — accepted.
- **Path traversal protection added** — Not in spec. Code review caught that `../` references could write files outside the bundle directory. Two-layer fix added.
- **Raw markdown save rejection added** — Not in spec. Prevents MCP/service saves of workflows with file references when no source path is available (would produce broken bundles).
- **No migration logic** — Spec mentioned migration options; we chose "just break" (zero users). Created a standalone migration script instead (`scratchpads/workflow-bundling-save/migrate-flat-workflows.sh`).

## Files Modified/Created

### Core Changes

- `src/pflow/core/workflow/manager.py` — Complete rewrite of storage layer. 7 methods updated to folder-based paths. Added `dependencies` parameter to `save()`. Atomic save via `tempfile.mkdtemp()` + `os.rename()`. Path containment check for bundled files. Removed dead `_name_from_path()`. `exists()` now checks entry point file, not just directory.

- `src/pflow/core/workflow/dependency_discovery.py` — **NEW**. `Dependency` dataclass, `discover_dependencies()` (recursive with cycle detection), helper functions for sub-workflow/param/batch scanning. Uses `is_file_reference()` and `is_workflow_file_reference()` from `file_resolver.py`.

- `src/pflow/core/workflow/save_service.py` — `_discover_and_bundle_deps()` extracted helper. `save_workflow_with_options()` gains `source_path` param, returns `tuple[Path, list[str]]`. Rejects cross-tree deps and raw-content saves with file refs.

- `src/pflow/core/file_resolver.py` — Added `is_workflow_file_reference()` — shared heuristic for sub-workflow file detection (replaces duplicated code in dependency_discovery and workflow_executor).

- `src/pflow/cli/commands/workflow.py` — Forwards `source_path=Path(file_path)` to save service, unpacks `bundled_files` for display.

- `src/pflow/mcp_server/services/execution_service.py` — Determines `source_path` from save input (file path vs raw content), forwards to save service.

- `src/pflow/execution/formatters/workflow_save_formatter.py` — `bundled_files` parameter added to `format_save_success()`.

- `src/pflow/runtime/workflow_executor.py` — `_is_file_reference()` now delegates to shared `is_workflow_file_reference()`.

- `src/pflow/core/workflow/CLAUDE.md` — Updated for folder-based storage format.

### Test Files

**Critical tests** (catch real bugs):
- `tests/test_integration/test_workflow_bundling.py` — 11 tests. `test_file_ref_resolves_from_saved_bundle` is the core guarantee. `test_sub_workflow_in_subdir_with_own_file_refs` caught the nested relative path bug.
- `tests/test_core/test_dependency_discovery.py` — 45 tests covering all four detection sources, recursion, cycles, errors, edge cases.

**Updated tests** (path assertion fixes):
- `test_workflow_manager.py`, `test_workflow_save_cli.py`, `test_workflow_save_integration.py`, `test_workflow_manager_integration.py`, `test_executor_service.py`, `test_nested_workflow_cli.py`, `test_workflow_save_service.py`, `test_skill_service.py`

## Integration Points & Dependencies

### Critical Path: Save → Load → Resolve

The load-bearing integration chain this task creates:

```
CLI/MCP save:
  source_path → _discover_and_bundle_deps() → dep.absolute_path.relative_to(parent_base)
  → manager.save(dependencies=[(rel_path, abs_path), ...])
  → files copied into bundle, is_relative_to() containment check

CLI/MCP execute saved workflow:
  wm.get_path(name) → _entry_point(name) → {name}/{name}.pflow.md
  → set as _pflow_workflow_file in initial_params
  → compile_ir_to_flow() calls resolve_file_references(ir, base_dir)
  → base_dir = Path(_pflow_workflow_file).parent = bundle directory
  → ./prompts/foo.md resolves from bundle, finds bundled file
```

If any link in this chain breaks, saved workflows with dependencies fail silently at execution time.

### Incoming Dependencies (what uses this)

- `cli/main.py:1250` → `wm.get_path()` — sets `_pflow_workflow_file` for saved workflow execution
- `cli/workflow_resolution.py` → `wm.exists()` + `wm.load_ir()` — CLI name resolution
- `runtime/workflow_executor.py:246` → `wm.get_path()` + `wm.load_ir()` — nested workflow by name
- `mcp_server/services/execution_service.py:211` → `wm.get_path()` — `_pflow_workflow_file` injection
- `runtime/template_validation/validator.py:517` → `wm.load_ir()` — child workflow output validation
- All callers of `save_workflow_with_options()` must unpack the `tuple[Path, list[str]]` return

### Outgoing Dependencies (what this uses)

- `file_resolver.py` — `is_file_reference()`, `is_workflow_file_reference()`, `FILE_RESOLVABLE_PARAMS`, `has_file_references()`
- `markdown_parser.py` — `parse_markdown()` for recursive sub-workflow scanning

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **Always folder, even single-file workflows** → Eliminates dual code paths in every operation. The "wasteful" empty folder is invisible (users interact via `pflow workflow list`, not `ls`). Alternative: folder only when deps exist — rejected because migration from file to folder when a workflow later gains deps is a breaking change.

2. **Reject cross-tree dependencies (not flatten)** → A workflow referencing `../shared/prompt.md` gets an error, not silent flattening. The user must restructure their project. Alternative: flatten `../shared/prompt.md` to `prompt.md` in bundle — rejected because it changes the semantic path and could cause name collisions.

3. **`save_workflow_with_options()` returns tuple** → Changed from `Path` to `tuple[Path, list[str]]` to carry bundled file list for display. Alternative: return a `SaveResult` dataclass — rejected as over-engineering for 2 callers and 2 fields.

4. **`exists()` checks entry point file, not just directory** → Ghost directories (from failed saves) no longer block non-force saves. This was a code review fix that changed the initial implementation.

### Technical Debt

- **Skill system is broken** — Symlink-based skills point to old paths. Accepted; skills rework is a separate task.
- **No deduplication of file refs** — If two nodes reference the same file, it appears twice in `bundled_files` display and gets copied twice (idempotent via `shutil.copy2`). Cosmetic issue.
- **`dep_type` is a plain string** — Could be `Literal["file_ref", "sub_workflow"]` for type safety. Deferred.

## Unexpected Discoveries

### Bugs Found During Implementation

1. **Nested sub-workflow relative path computation** — When a sub-workflow in a subdirectory has its own file refs, `discover_dependencies` returns `relative_path` relative to the sub-workflow, not the parent. The bundling step must recompute paths using `dep.absolute_path.relative_to(parent_base)`.

2. **Batch item base_dir inconsistency** — `dependency_discovery.py` resolved batch item file refs relative to the batch file's directory, but `file_resolver.py` (runtime) resolves them relative to the workflow's directory. These are different paths when the batch file is in a subdirectory.

3. **Path traversal vulnerability** — The initial fallback for cross-tree deps used `dep.relative_path` directly (e.g., `../shared/prompt.md`), which via `Path(temp_dir) / "../shared/prompt.md"` writes outside the temp directory.

### Edge Cases

- **`os.rename` silently replaces empty target directories on macOS** — Added explicit pre-check.
- **`test_executor_service.py` directly constructs paths** — 16 tests bypassed WorkflowManager API and built paths manually. All needed updating.
- **`test_skill_service.py` deleted file not directory** — Used `workflow_path.unlink()` to simulate force-save, but new format requires `wm.delete()` (shutil.rmtree).

## Patterns Established

### Atomic Directory Save Pattern

```python
temp_dir = tempfile.mkdtemp(dir=parent, prefix=f".{name}.", suffix=".tmp")
try:
    # Write all files into temp_dir
    Path(temp_dir, "entry.md").write_text(content)
    # Pre-check + atomic move
    if target_dir.exists():
        raise ExistsError(...)
    os.rename(temp_dir, target_dir)
except:
    shutil.rmtree(temp_dir, ignore_errors=True)
    raise
```

### Path Containment Check Pattern

```python
dest_path = (Path(bundle_root) / untrusted_rel_path).resolve()
if not dest_path.is_relative_to(Path(bundle_root).resolve()):
    raise ValidationError(f"Path '{untrusted_rel_path}' escapes bundle")
```

### Centralized Path Helpers Pattern

```python
def _workflow_dir(self, name: str) -> Path:
    return self.workflows_dir / name

def _entry_point(self, name: str) -> Path:
    return self.workflows_dir / name / f"{name}.pflow.md"
```

All 7+ methods use these instead of constructing paths inline. Any path format change only touches these two methods.

## Breaking Changes

### API Changes

- `WorkflowManager.save()` has new optional param: `dependencies: Optional[list[tuple[str, Path]]]`
- `save_workflow_with_options()` has new optional param: `source_path: Optional[Path]`
- `save_workflow_with_options()` return type: `Path` → `tuple[Path, list[str]]`
- `WorkflowManager.get_path()` returns path inside folder: `{name}/{name}.pflow.md` instead of `{name}.pflow.md`
- `WorkflowManager.exists()` checks entry point file existence, not just directory

### Storage Format Change

- Old: `~/.pflow/workflows/{name}.pflow.md`
- New: `~/.pflow/workflows/{name}/{name}.pflow.md`
- Legacy flat-file workflows invisible to `workflow list`. Migration script at `scratchpads/workflow-bundling-save/migrate-flat-workflows.sh`.

### Skill System Breakage

- Existing skill symlinks point to `{name}.pflow.md` (old path). They will resolve to a file that doesn't exist.
- Skills rework planned as separate task (user decision: SKILL.md becomes standalone docs, no symlinks).

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/core/workflow/manager.py` — `_workflow_dir()` and `_entry_point()` are the canonical path constructors
2. Read `src/pflow/core/workflow/save_service.py` — `_discover_and_bundle_deps()` and `save_workflow_with_options()` are the bundling pipeline
3. Read `src/pflow/core/file_resolver.py` — `is_file_reference()` (param-level) and `is_workflow_file_reference()` (sub-workflow-level) are the detection heuristics
4. Run `uv run pytest tests/test_integration/test_workflow_bundling.py -v` to verify bundling works

### Common Pitfalls

- **Don't construct workflow paths manually** — Always use `wm.get_path(name)`, `wm._entry_point(name)`, or `wm._workflow_dir(name)`. Hardcoded `f"{name}.pflow.md"` will break.
- **`save_workflow_with_options()` returns a tuple now** — Callers must unpack `(path, bundled_files)`.
- **`exists()` checks the entry point file** — A directory without `{name}.pflow.md` inside returns `False`.
- **Don't resolve batch item file refs relative to the batch file** — Resolve relative to the workflow's base directory (matches `file_resolver.py` runtime behavior).
- **Cross-tree `../` dependencies are rejected** — All bundled files must be under the parent workflow's directory. This is a deliberate security constraint.

### Test-First Recommendations

When modifying workflow save/load:
1. Run `uv run pytest tests/test_core/test_workflow_manager.py -x -q` first
2. Then `uv run pytest tests/test_integration/test_workflow_bundling.py -x -q`
3. Then `make test` for full regression

The critical test: `test_file_ref_resolves_from_saved_bundle` — if this fails, the core feature is broken.

---

*Generated from implementation context of Task 130*
