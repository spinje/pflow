# Task 130: Workflow Bundling on Save — Progress Log

## Phase 0 — Context Gathering and Design

### Research
- Read task spec (`task-130.md`), both braindumps from `starting-context/`
- Launched 3 parallel codebase searchers to map:
  - All callers of `WorkflowManager.get_path()`, `.exists()`, `.load()`, `.load_ir()` (20+ callers identified)
  - MCP save/delete/list code paths
  - CLI workflow delete (discovered: no `pflow workflow delete` command exists)
- Read all key files: `manager.py`, `save_service.py`, `file_resolver.py`, `skill_service.py`, `workflow_executor.py` (sub-workflow detection), CLI `workflow.py`, `workflow_save_formatter.py`
- Read all test files: `test_workflow_manager.py` (25 tests), `test_workflow_save_service.py` (24 tests), `test_workflow_save_cli.py` (11 tests), integration tests, MCP save tests

### Key Findings
- **All path construction is centralized** in 7 methods of `WorkflowManager`, all using `self.workflows_dir / f"{name}.pflow.md"`. Changing the internal path logic propagates cleanly to all ~20 callers via `get_path()`.
- **One external path construction**: `skill_service.py:385` builds `f"{workflow_name}.pflow.md"` for symlink target matching — the only place outside WorkflowManager.
- **Building blocks exist**: `file_resolver.py` has `is_file_reference()` and `has_file_references()`. `workflow_executor.py` has `_is_file_reference()` for sub-workflow detection (DIFFERENT heuristic).
- **Save path sees raw IR** (before file resolution), so file paths are literal strings — exactly what dependency discovery needs.
- **No CLI delete command** — only caller of `WorkflowManager.delete()` is `save_service.py` for `--force` saves.
- **`isolate_pflow_config` autouse fixture** patches `WorkflowManager.__init__` to use temp dirs — continues to work unchanged with folder structure.

### Design Decisions
1. **Always folder** — even single-file workflows. No dual code paths.
2. **Entry point**: `{name}/{name}.pflow.md` (not `WORKFLOW.pflow.md`)
3. **Preserve relative structure** from original project — no path rewriting
4. **Sub-workflows by name** NOT bundled (shared dependencies saved independently)
5. **No migration** — zero users, breaking change fine
6. **Skills OUT OF SCOPE** — user decided to rework skills separately (no symlinks, SKILL.md becomes standalone docs)
7. **Atomic save** — temp dir + `os.rename()` (atomic on same filesystem)
8. **Re-save with `--force`** — delete entire folder, recreate from scratch

### Plan
Created comprehensive plan at `.claude/plans/swift-rolling-quilt.md` with two phases:
- Phase 1: Folder-based WorkflowManager (rewrite 7 methods + fix tests)
- Phase 2: Dependency discovery + bundling (new module + wire into save pipeline + tests)

---

## Phase 1 — Folder-based WorkflowManager

### Implementation (Steps 1.1-1.7)

All changes in `src/pflow/core/workflow/manager.py`:

- Added `import shutil` and two path helpers: `_workflow_dir(name)` and `_entry_point(name)`
- **`save()`**: Complete rewrite. Uses `tempfile.mkdtemp()` + `os.rename()` instead of `tempfile.mkstemp()` + `os.link()`. Added optional `dependencies: list[tuple[str, Path]]` parameter for file bundling. Removed `_perform_atomic_save()` method.
- **`load()`**: Changed path from `f"{name}.pflow.md"` to `self._entry_point(name)`.
- **`get_path()`**: Returns `self._entry_point(name).resolve()`. Critical: `Path(get_path(name)).parent` now returns the workflow bundle directory, which is correct for file reference resolution.
- **`exists()`**: Changed from `file.exists()` to `self._workflow_dir(name).is_dir()`.
- **`list_all()`**: Complete rewrite. Iterates `sorted(self.workflows_dir.iterdir())`, skips non-dirs and hidden dirs, looks for `{name}/{name}.pflow.md` entry points. No longer uses `glob("*.pflow.md")`.
- **`delete()`**: Changed from `file.unlink()` to `shutil.rmtree(workflow_dir)`.
- **`update_metadata()`**: Path changed to `_entry_point(name)`. Temp file dir changed to `_workflow_dir(name)` (same filesystem for `os.replace()`).

### Test Fixes (Step 1.8)

Launched 3 parallel test-fixer agents:

**Agent 1: `test_workflow_manager.py`** (34 tests)
- Updated 8 locations across 6 tests: path assertions changed from `workflows_dir / f"{name}.pflow.md"` to `workflows_dir / name / f"{name}.pflow.md"`
- `test_list_all_skip_invalid`: Changed from creating bare `.pflow.md` file to creating directory with entry point
- `test_corrupted_workflow_file`: Same directory-based pattern
- Frontmatter override tests: Updated file paths to reach entry points inside directories

**Agent 2: CLI save + integration tests** (35 tests)
- `test_workflow_save_cli.py`: 5 path fixes (`home_pflow / "name.pflow.md"` → `home_pflow / "name" / "name.pflow.md"`)
- `test_workflow_save_integration.py`: 5 fixes including glob pattern updates for directory-based storage
- `test_workflow_manager_integration.py`: 2 fixes (corrupted file path, atomic save mock target change from `builtins.open` to `pathlib.Path.write_text`)

**Agent 3: MCP + runtime tests** (56 tests)
- All 56 tests passed WITHOUT any changes needed (they use WorkflowManager through its public API or mock it entirely)

### Additional Failures Found

After initial test fixes, `make test` revealed 17 more failures:

**`test_executor_service.py`** (16 failures): Tests directly constructed old-format paths (`temp_workflow_dir / f"{name}.pflow.md"`) for reading workflow files after save. Fixed all 14 occurrences to use folder-based paths.

**`test_nested_workflow_cli.py`** (1 failure): Test saved a parent workflow referencing `./child-upper.pflow.md`, but the child file was placed in the top-level `workflows_dir/` instead of inside the parent's saved folder. Fixed by moving child file creation to after `wm.save()`, placing it in the parent's bundle directory.

### Result
- All 4164 tests pass
- `make check` clean (lint, types, deps)

---

## Phase 2 — Dependency Discovery and Bundling

### Step 2.1: `dependency_discovery.py`

Created `src/pflow/core/workflow/dependency_discovery.py`:

- `Dependency` dataclass: `relative_path`, `absolute_path`, `source_node_id`, `source_param`, `dep_type`
- `_is_sub_workflow_file_ref(value)`: Replicates `WorkflowExecutor._is_file_reference()` heuristic
- `discover_dependencies(ir_dict, base_dir, seen)`: Recursive scanner with cycle detection

Four detection sources:
1. Sub-workflow file refs (`node["params"]["workflow"]` via `_is_sub_workflow_file_ref`)
2. File refs in params (`FILE_RESOLVABLE_PARAMS` + `is_file_reference()` from `file_resolver.py`)
3. Batch config files (`node["batch"]` as string file ref)
4. File refs in batch items (`node["batch"]["items"][i][key]`)

Design choices:
- Cycle detection via `seen` set of resolved absolute path strings
- Sub-workflows recursively parsed and scanned for their own deps
- Batch YAML files parsed to find file refs in their items
- `FileNotFoundError` raised with node_id, param_name, and resolved path (matches `file_resolver.py` error format)

### Step 2.2-2.5: Wiring into Save Pipeline

**`save_service.py`**: `save_workflow_with_options()` updated:
- New param: `source_path: Optional[Path]`
- Return type changed: `Path` → `tuple[Path, list[str]]`
- When `source_path` provided: parses markdown, discovers deps, passes to `manager.save()`
- When `source_path` is None: skips discovery, returns `(path, [])`

**`cli/commands/workflow.py`**:
- `_save_with_overwrite_check()` updated to accept `source_path`, returns `tuple[str, list[str]]`
- `save_workflow()` command passes `Path(file_path)` as source and forwards `bundled_files` to formatter
- Added `from pathlib import Path` to module imports (caught `NameError` on first test run)

**`mcp_server/services/execution_service.py`**:
- `save_workflow()` determines `source_path` from input (file path → `Path`, raw content → `None`)
- `_save_and_format_result()` updated to accept and forward `source_path`
- Added `Optional` to typing imports

**`execution/formatters/workflow_save_formatter.py`**:
- `format_save_success()` accepts optional `bundled_files: list[str]`
- Displays bundled files when present: `"Bundled 3 files:\n    prompts/foo.md\n    ..."`

### Mock Test Fixes

`test_workflow_save_service.py`: 5 tests needed updating:
- `assert_called_once_with` calls updated to expect 4th arg (`None` for dependencies)
- Return value unpacking changed from `path = ...` to `path, bundled = ...`
- Added `assert bundled == []` assertions

### Step 2.6-2.7: Tests

**45 dependency discovery tests** in `tests/test_core/test_dependency_discovery.py`:
- 10 test classes covering all detection sources, recursion, cycles, errors, edge cases
- All use real files via `tmp_path` (no mocking)

**8 bundling integration tests** in `tests/test_integration/test_workflow_bundling.py`:
- End-to-end: create project with deps → save → verify bundle contents
- Tests: file refs, sub-workflows, directory structure preservation, load after save, force-save replacement, no-deps case, service layer integration

### Final Result
- **4217 tests pass** (53 new tests added)
- **`make check` clean** — lint, types, deps all pass

---

## Post-Implementation Review — High-Value Tests and Bug Fix

### Bug Found: Nested sub-workflow relative path computation

While reviewing the implementation for untested edge cases, found a real bug in the bundling logic.

**Scenario**: A sub-workflow in a subdirectory has its own file references:
```
project/
├── parent.pflow.md         # references ./sub/child.pflow.md
└── sub/
    ├── child.pflow.md       # references ./data/prompt.md
    └── data/
        └── prompt.md
```

**Bug**: `discover_dependencies` returns `relative_path="./data/prompt.md"` for the child's dependency (relative to the child, not the parent). When bundling, this placed the file at `bundle/data/prompt.md` instead of `bundle/sub/data/prompt.md`. At runtime, the child at `bundle/sub/child.pflow.md` resolves `./data/prompt.md` → `bundle/sub/data/prompt.md` — file not found.

**Fix**: In `save_service.py:_discover_and_bundle_deps()`, compute bundle-relative paths from the parent workflow's directory using `dep.absolute_path.relative_to(parent_base)` instead of using `dep.relative_path` directly.

**Not a problem for the current use case** (music-generation project has flat directory structure), but would break for nested project layouts.

### Three high-value tests added

Added to `tests/test_integration/test_workflow_bundling.py`:

1. **`test_file_ref_resolves_from_saved_bundle`**: The critical end-to-end chain: save workflow with file ref → load IR → call `resolve_file_references()` using `get_path().parent` as base_dir → verify file content was substituted from bundle. This is THE core guarantee of the feature.

2. **`test_sub_workflow_in_subdir_with_own_file_refs`**: Verifies the nested path bug fix. Creates `project/sub/child.pflow.md` referencing `./data/prompt.md`, saves via parent, verifies file lands at `bundle/sub/data/prompt.md` and resolves correctly.

3. **`test_file_ref_resolves_via_service_layer`**: Same as test 1 but goes through `save_workflow_with_options()` (the service layer) to exercise the full production path including dependency discovery.

### Ruff complexity fixes

Extracted helpers to reduce cyclomatic complexity:
- `save_service.py`: Extracted `_discover_and_bundle_deps()` from `save_workflow_with_options()` (was 12, limit 10)
- `dependency_discovery.py`: Extracted `_collect_sub_workflow_deps()`, `_collect_param_deps()`, `_collect_batch_deps()` from `discover_dependencies()` (was >10)

### Final automated test result
- **4220 tests pass** (56 new tests total)
- **`make check` clean**

---

## Manual Testing

### Test Fixtures Created

Created `examples/bundling/` with 6 test workflow files:
- `simple.pflow.md` — no dependencies
- `command-ref.pflow.md` + `scripts/hello.sh` — shell script dependency
- `prompt-ref.pflow.md` + `prompts/greet.prompt.md` — prompt file dependency
- `parent-with-sub.pflow.md` + `sub-echo.pflow.md` — sub-workflow dependency

### Manual Test Results (8/8 pass)

| Test | Description | Result |
|------|-------------|--------|
| 1 | Save simple workflow (no deps) — lifecycle | **PASS** |
| 2 | Save workflow with prompt file reference — bundle structure | **PASS** |
| 3 | Save workflow with command file reference — **execute from bundle** | **PASS** |
| 4 | Save workflow with sub-workflow reference — execute from bundle | **PASS** |
| 5 | `--force` replaces entire bundle cleanly | **PASS** |
| 6 | Existing nested workflow examples — regression | **PASS** |
| 7 | Existing file-reference examples — regression | **PASS** |
| 8 | `workflow list` shows folder-based workflows | **PASS** |

**Test 3 is the critical test**: Saved workflow with `- command: ./scripts/hello.sh` executes correctly from the bundle directory, proving file references resolve from `get_path().parent`.

### Legacy workflow migration

Found 6 flat-file workflows in `~/.pflow/workflows/` that `workflow list` no longer shows. Created migration script at `scratchpads/workflow-bundling-save/migrate-flat-workflows.sh` (dry-run by default, `--apply` to execute). Wraps each `{name}.pflow.md` in a `{name}/{name}.pflow.md` folder.

---

## Files Modified (final)

### Production Code (6 files)
| File | Change |
|------|--------|
| `src/pflow/core/workflow/manager.py` | Path helpers, all 7 methods rewritten for folder storage, atomic dir save |
| `src/pflow/core/workflow/dependency_discovery.py` | **NEW** — `Dependency`, `discover_dependencies()`, `_is_sub_workflow_file_ref()` |
| `src/pflow/core/workflow/save_service.py` | `_discover_and_bundle_deps()`, `source_path` param, returns `tuple[Path, list[str]]` |
| `src/pflow/cli/commands/workflow.py` | Forwards `source_path`, unpacks bundled_files, passes to formatter |
| `src/pflow/mcp_server/services/execution_service.py` | Forwards `source_path` when saving from file, unpacks tuple |
| `src/pflow/execution/formatters/workflow_save_formatter.py` | `bundled_files` display |

### Test Files (10 files)
| File | Change |
|------|--------|
| `tests/test_core/test_dependency_discovery.py` | **NEW** — 45 tests |
| `tests/test_integration/test_workflow_bundling.py` | **NEW** — 11 tests (8 original + 3 high-value) |
| `tests/test_core/test_workflow_manager.py` | 8 path assertion updates |
| `tests/test_core/test_workflow_save_service.py` | 5 mock expectation updates |
| `tests/test_cli/test_workflow_save_cli.py` | 5 path assertion updates |
| `tests/test_cli/test_workflow_save_integration.py` | 5 path/glob updates |
| `tests/test_integration/test_workflow_manager_integration.py` | 2 path + mock fixes |
| `tests/test_execution/test_executor_service.py` | 14 path assertion updates |
| `tests/test_cli/test_nested_workflow_cli.py` | 1 fix (child workflow placement) |
| `tests/test_runtime/test_workflow_executor/test_workflow_name.py` | No changes needed |

### Other Files
| File | Purpose |
|------|---------|
| `examples/bundling/` | 6 test fixture workflows + `TESTING.md` manual test plan |
| `scratchpads/workflow-bundling-save/migrate-flat-workflows.sh` | Legacy flat-file → folder migration script |

### Production Code (6 files)
| File | Change |
|------|--------|
| `src/pflow/core/workflow/manager.py` | Path helpers, all 7 methods rewritten for folder storage, atomic dir save |
| `src/pflow/core/workflow/dependency_discovery.py` | **NEW** — `Dependency`, `discover_dependencies()`, `_is_sub_workflow_file_ref()` |
| `src/pflow/core/workflow/save_service.py` | `source_path` param, dependency discovery, returns `tuple[Path, list[str]]` |
| `src/pflow/cli/commands/workflow.py` | Forwards `source_path`, unpacks bundled_files, passes to formatter |
| `src/pflow/mcp_server/services/execution_service.py` | Forwards `source_path` when saving from file, unpacks tuple |
| `src/pflow/execution/formatters/workflow_save_formatter.py` | `bundled_files` display |

### Test Files (10 files)
| File | Change |
|------|--------|
| `tests/test_core/test_dependency_discovery.py` | **NEW** — 45 tests |
| `tests/test_integration/test_workflow_bundling.py` | **NEW** — 8 tests |
| `tests/test_core/test_workflow_manager.py` | 8 path assertion updates |
| `tests/test_core/test_workflow_save_service.py` | 5 mock expectation updates |
| `tests/test_cli/test_workflow_save_cli.py` | 5 path assertion updates |
| `tests/test_cli/test_workflow_save_integration.py` | 5 path/glob updates |
| `tests/test_integration/test_workflow_manager_integration.py` | 2 path + mock fixes |
| `tests/test_execution/test_executor_service.py` | 14 path assertion updates |
| `tests/test_cli/test_nested_workflow_cli.py` | 1 fix (child workflow placement) |
| `tests/test_runtime/test_workflow_executor/test_workflow_name.py` | No changes needed |

---

## Code Review Fixes

Received a thorough code review (11 findings). Evaluated each against actual code with parallel codebase searchers.

### Critical fixes applied:

1. **Path traversal in dependency bundling** — `../` or absolute paths in `rel_path` could escape the bundle directory. Fixed in two layers: (a) `save_service.py` now raises `WorkflowValidationError` for cross-tree deps instead of falling back to raw `dep.relative_path`, (b) `manager.py` adds defense-in-depth: resolves `dest_path` and validates `is_relative_to(temp_dir)`.

2. **Batch item file refs resolved from wrong base directory** — `dependency_discovery.py` used `resolved.parent` (batch file's dir) but `file_resolver.py` uses `base_dir` (workflow's dir) at runtime. One-line fix: changed `resolved.parent` to `base_dir`.

3. **Silent exception swallowing** — generic `except Exception` in `_discover_and_bundle_deps()` logged and continued, allowing saves without bundled dependencies. Changed to raise `WorkflowValidationError`.

4. **Raw markdown saves with file references** — MCP saves from raw content (no source path) silently skipped bundling, producing broken workflows. Added check: if IR has file references but no `source_path`, raise `WorkflowValidationError` with actionable message.

### Warning fixes applied:

5. **`exists()` vs `list_all()` consistency** — `exists()` checked `is_dir()` only; `list_all()` also required entry point file. Ghost directories blocked saves. Fixed `exists()` to check `_entry_point(name).exists()`.

6. **`os.rename` pre-check** — Added explicit `target_dir.exists()` check before `os.rename()` for defense-in-depth (empty target dirs silently overwritten on POSIX).

7. **Dead code removed** — Deleted `_name_from_path()` static method (zero callers).

8. **Shared heuristic extracted** — Moved `_is_sub_workflow_file_ref()` to `file_resolver.py` as `is_workflow_file_reference()`. Both `dependency_discovery.py` and `workflow_executor.py` now import from the shared location.

9. **CLAUDE.md updated** — Documented folder-based storage format, added `dependency_discovery.py` to module structure, fixed `os.link()` → `os.rename()` references.

### Disputed:
- Variable `f` shadowing built-in (#11) — `f` is not a Python built-in. Loop variable in tight scope is standard.

### Deferred:
- Literal type for `dep_type` (#9) — nice but not worth churn
- Dedup file refs (#10) — cosmetic, `shutil.copy2` is idempotent

### Additional test fixes:
- `test_dependency_discovery.py`: Updated import from `_is_sub_workflow_file_ref` to `is_workflow_file_reference`
- `test_skill_service.py`: Fixed `test_re_enrich_restores_usage_section_after_resave` — was deleting just the file, not the directory. Changed to use `wm.delete()` + re-derive `workflow_path`.

### Final result:
- **4220 tests pass**
- **`make check` clean**

---

## Insights

1. **Centralized path construction paid off**: Because all path construction was in `WorkflowManager`, changing 7 methods propagated cleanly to 20+ callers via `get_path()`. Only `skill_service.py` had a hardcoded path (out of scope).

2. **`os.rename()` is the right atomic primitive for directories**: On POSIX, it fails if the target directory exists and is non-empty, giving us natural "workflow already exists" protection — the same semantics as `os.link()` for files.

3. **Test agents in parallel saved significant time**: Launching 3 test-fixer agents simultaneously handled ~100 tests across 8 files in one round. The mechanical path updates were perfectly suited for parallel work.

4. **The `isolate_pflow_config` fixture is robust**: It patches `WorkflowManager.__init__` at the right level — all tests that create `WorkflowManager()` without explicit args automatically got isolated temp dirs, and the folder-based structure worked without fixture changes.

5. **Mock tests needed minimal updates**: Tests that mock `WorkflowManager` (CLI command tests, workflow resolution tests) mostly worked unchanged because they mock the interface, not the implementation. Only `test_workflow_save_service.py` needed updates for the changed `save()` signature and return type.
