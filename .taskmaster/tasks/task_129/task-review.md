# Task 129 Review: External File References for Code Block Parameters

## Metadata
- Implementation Date: 2026-03-21
- Code Reviews: `scratchpads/task-129-code-review.md`, `scratchpads/task-129-staged-review-2026-03-21.md`
- Implementation Plan: `.claude/plans/sequential-wishing-manatee.md`
- Progress Log: `.taskmaster/tasks/task_129/implementation/progress-log.md`

## Executive Summary

Added external file reference resolution for workflow parameters. Any code-block parameter (`prompt`, `code`, `command`, `batch`, etc.) can now reference an external file (`- prompt: ./prompts/system.md`) instead of inline content. The system auto-detects file paths, reads files, and substitutes content into the IR before compilation — so template variables inside external files are validated identically to inline content. Template validation errors now include source file provenance so agents know which file to edit.

## Implementation Overview

### What Was Built

A pure IR transformation function (`resolve_file_references`) that runs between parsing and compilation. It walks node params and batch items, detects file references via heuristic, reads files, substitutes content, and records provenance. Integration points in all 6 execution paths (CLI, CLI validate-only, MCP execute, MCP validate, nested workflows, compiler).

Post-review additions: path traversal containment, source file hints in template error messages, clear error for MCP inline workflows with file references.

### Deviations From Plan

| Plan | Reality | Why |
|------|---------|-----|
| `EXCLUDED_PARAMS = {"workflow"}` blocklist | `FILE_RESOLVABLE_PARAMS` allowlist | 39 test failures revealed `file_path`, `url`, and many other params contain path values. Allowlist is fundamentally safer — new node types are safe by default. |
| Detection: `./` or `/` + extension | Added: no spaces, no `://` | Shell commands (`touch /tmp/file.txt`) and URLs matched the original heuristic. |
| Insert in `_perform_validation()` | Insert in `_handle_validate_only_mode()` | `_perform_validation()` doesn't have `ctx` in scope. |
| `_validate_before_execution()` doesn't need file resolution | It does | Pre-execution validation runs BEFORE compilation, sees raw file path strings. Found by manual testing agent (Bug 8). |
| `_source_files` as future work | Implemented in review follow-up | User: "having the best possible errors that agents can understand is THE core feature of pflow" |

## Files Modified/Created

### Core Changes

- `src/pflow/core/file_resolver.py` — **NEW.** Core module: `is_file_reference()` detection heuristic, `resolve_file_references()` IR transformation, `has_file_references()` scanner, `get_base_dir()` utility. ~260 lines. No runtime dependencies.
- `src/pflow/runtime/compilation/compiler.py` — Insert `resolve_file_references()` between `_parse_ir_input()` and `_validate_workflow()` (line ~654). Wraps `FileNotFoundError` in `CompilationError`. This single insertion covers CLI execution, MCP execution, and nested workflows.
- `src/pflow/runtime/workflow_executor.py` — Inject `_pflow_workflow_file` into `child_params` before `compile_ir_to_flow()`. Without this, nested workflows resolve file references from CWD instead of their own directory.
- `src/pflow/cli/main.py` — `_resolve_file_refs_or_exit()` helper called in both `_handle_validate_only_mode()` and `execute_json_workflow()` before pre-execution validation.
- `src/pflow/mcp_server/services/execution_service.py` — Surfaced `source` from `_resolve_and_validate_workflow()` (was discarded as `_source`). Removed redundant second `resolve_workflow()` call. Added `_check_inline_file_references()` for clear error when inline workflows contain file refs. Added `_inject_workflow_file_path()` for file/library sources.
- `src/pflow/runtime/template_validation/path_validation.py` — `_find_template_source_file()` scans nodes for template, checks `_source_files`. `_append_source_file_hint()` adds "Loaded from file: ./path" to error messages via `create_template_error()` dispatcher.
- `src/pflow/core/ir_schema.py` — Added `_source_files` field to node schema alongside `_source_lines`.
- `src/pflow/core/CLAUDE.md` — Documented `file_resolver.py` in module structure and Key Components.

### Test Files

- `tests/test_core/test_file_resolver.py` — 53 tests. `TestIsFileReference` (24 detection tests), `TestResolveFileReferences` (20 resolution tests), `TestHasFileReferences` (7 scanner tests), `TestGetBaseDir` (3 tests).
- `tests/test_core/test_file_resolver_integration.py` — 13 tests. Parser integration, compile-time template detection, nested workflow directory resolution, batch file fall-through, mutual exclusivity, template error provenance (positive and negative).

### Critical Tests (catch real bugs)

- `test_compile_ir_detects_templates_in_file_content` — Compiles a workflow where `${fetch.stdout}` is inside an external file. If file resolution breaks silently, template detection won't find the variable — a silent runtime bug with no error.
- `test_nested_workflow_file_refs_resolve_from_child_dir` — Verifies correct resolution AND failure from wrong directory. Catches regressions in `_pflow_workflow_file` injection.
- `test_path_traversal_blocked` / `test_path_traversal_dot_dot_in_middle` — Path containment check.
- `test_batch_file_with_item_file_refs` — Single-pass batch resolution (B1 fall-through to B2).
- `test_template_error_includes_source_file` / `test_template_error_without_file_ref_has_no_hint` — Error provenance works and doesn't produce false hints.
- `test_batch_items_non_resolvable_param_untouched` / `test_non_resolvable_param_untouched` — Allowlist enforcement.

## Integration Points & Dependencies

### Critical Integration Points

1. **`compile_ir_to_flow()` at compiler.py:~654** — The chokepoint. ALL compilation paths flow through here. File resolution runs before `_validate_workflow()`. If this breaks, no workflow with file references compiles.

2. **`_resolve_file_refs_or_exit()` in main.py** — Called in BOTH `_handle_validate_only_mode()` and `execute_json_workflow()`. The execution path call was Bug 8 — pre-execution validation runs before compilation and needs resolved content. If removed, any workflow with declared inputs AND file references containing `${input}` fails with "input never used."

3. **`workflow_executor.py` child_params injection** — Injects `_pflow_workflow_file` into `child_params` before `compile_ir_to_flow()`. Without this, nested workflow file references resolve from CWD. `child_params` and `child_storage` both need the path — `child_params` for compile-time resolution, `child_storage` (set separately at line 340) for runtime path resolution.

4. **`create_template_error()` in path_validation.py** — The single dispatcher for ALL template validation errors. Source file hints are appended here via `_append_source_file_hint()`.

### IR Dict Keys

- `node["_source_files"]` — `dict[str, str]` mapping param names to original file paths. Written by `file_resolver.py`, read by `path_validation.py`. Keys: param names for node params (e.g., `"prompt"`), `"batch"` for batch config, `"batch.items[N].key"` for batch items.

## Architectural Decisions & Tradeoffs

### Allowlist Over Blocklist

The most important decision. `FILE_RESOLVABLE_PARAMS = {"command", "code", "prompt", "source", "stdin", "headers", "output_schema"}`. Only these params can be resolved as file references. Every other param (workflow, file_path, url, model, temperature, etc.) is ignored.

The plan specified a blocklist (`EXCLUDED_PARAMS = {"workflow"}`). First test run: 39 failures. `file_path` on write-file nodes, `url` on HTTP nodes, and many other path-valued params were being resolved. Each new node type would need to be added to the blocklist. The allowlist is fundamentally safer — it exactly matches `_CODE_BLOCK_TAG_TO_PARAM` from the markdown parser. New node types are safe by default.

### `batch` Is Special

`batch` lives at `node["batch"]` (top-level), NOT in `node["params"]`. The markdown parser pops it at `markdown_parser.py:1008-1010`. So `batch` is NOT in `FILE_RESOLVABLE_PARAMS` (would be dead code in the params loop). Instead, batch is handled separately in `_resolve_batch_file_references()` with explicit B1 (string→YAML) and B2 (walk items) branches.

### Idempotent Resolution

`resolve_file_references()` runs twice in the execution path: once before pre-execution validation (`_resolve_file_refs_or_exit`), once inside `compile_ir_to_flow()`. This is correct because the function is idempotent — resolved content (multi-line prompt text) never matches the file reference heuristic (no `./` prefix, contains spaces/newlines). The duplication exists because the two code paths are separated by layers (CLI vs compiler). Acceptable tradeoff.

### Template Extraction Loses Node Association

Template validation's `_extract_all_templates()` produces a flat `set[str]` — it discards which node each template came from. To find the source file for an error, `_find_template_source_file()` scans all nodes for the template pattern and checks `_source_files`. This is O(nodes × params) per error but only runs on validation failure with small workflows.

## Unexpected Discoveries

### The `workflow` Param Resolution Bug

The biggest surprise. `- workflow: /tmp/child.pflow.md` (absolute path to a sub-workflow) matched `is_file_reference()` because it contains `/` and ends with `.md`. The file resolver was reading the entire child workflow markdown and replacing the `workflow` param value with the file content. This silently broke nested workflow execution. Led to the allowlist approach.

### Pre-Execution Validation Runs Before Compilation

The plan explicitly said `_validate_before_execution()` didn't need file resolution because it's "followed by `compile_ir_to_flow()` which handles it." Wrong. Pre-execution validation runs first, sees `- prompt: ./prompts/foo.md` as a literal string, and reports "input never used" because `${input}` is inside the unresolved file. Found by manual testing agent, not by automated tests.

### Shell Commands Match File Paths

`- command: touch /tmp/xxx/validate_only_proof.txt` matched because it contains `/` and ends with `.txt`. The space exclusion rule (`" " in value`) was not in the original design. Simple but critical — distinguishes file paths from shell commands.

## Patterns Established

### IR Transformation as Pure Function

`resolve_file_references(ir_dict, base_dir) → ir_dict` modifies the IR in place, independently testable, no side effects beyond IR mutation, no parser or compiler changes needed. This pattern works for any pre-compilation transformation. Future features should follow this: write a pure function on the IR, insert it in the pipeline, test in isolation.

### Detection Heuristic Design

The `is_file_reference()` heuristic uses negative checks first (reject templates, newlines, spaces, URLs) then positive checks (starts with `./`, or has `/` + extension). This "reject common cases fast, then match" pattern is robust. Each rejection rule was discovered by a real test failure.

### Provenance-Then-Consume Pattern

`_source_files` is written during IR transformation, then consumed during error formatting. The writer doesn't know who reads it; the reader doesn't know who writes it. Clean separation via a well-defined dict on the node. Reusable for any "annotate during processing, use during error reporting" need.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/core/file_resolver.py` — the entire feature in one file
2. Read `src/pflow/core/CLAUDE.md` section on `file_resolver.py`
3. Understand: `batch` is at `node["batch"]`, not `node["params"]`
4. Understand: 6 execution paths exist (CLI, CLI validate-only, MCP execute, MCP validate, nested workflows, compiler). Changes in the compiler cover 3 of them automatically.

### Common Pitfalls

- **Don't use a blocklist for param handling.** New node types will add params with path values. Use `FILE_RESOLVABLE_PARAMS` allowlist.
- **Don't assume compilation is the only entry to validation.** `_validate_before_execution()` and `_handle_validate_only_mode()` call `WorkflowValidator.validate()` directly, bypassing `compile_ir_to_flow()`.
- **Don't assume `child_params` has `_pflow_workflow_file`.** It's injected in `WorkflowExecutor.exec()` AFTER `prep()` builds it. If you move or refactor the injection, nested workflow file refs break silently (resolve from wrong directory).
- **Don't forget the space check in file reference detection.** Without it, every shell command containing a path becomes a file reference.

### Test-First Recommendations

When modifying file reference resolution:
1. Run `tests/test_core/test_file_resolver.py` first — fast, isolated, catches detection heuristic regressions
2. Run `tests/test_cli/test_nested_workflow_cli.py` — catches `workflow` param resolution and nested path issues
3. Run `tests/test_core/test_file_resolver_integration.py` — catches template detection and provenance regressions
4. Run full `make test` last — catches integration issues across the whole system

---

*Generated from implementation context of Task 129*
