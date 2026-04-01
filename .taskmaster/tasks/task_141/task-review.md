# Task 141 Review: Consolidate Exception Hierarchy Under PflowError

## Metadata

- **Implementation Date**: 2026-03-31
- **GitHub Issue**: #185
- **Branch**: `refactor/consolidate-exception-hierarchy`
- **Related**: Task 135 (CompilationError move precedent), Task 130 (workflow bundling, introduced dependency_discovery error handling)

## Executive Summary

Unified four independent exception inheritance trees into one rooted hierarchy under `PflowError`. Eliminated 24 lazy exception imports, 3 class aliases, 1 duck-type hack, and 1 helper wrapper function across 22 production files. Fixed a pre-existing bug where node execution `ValueError`s (HTTP timeouts, API failures) were miscategorized as `category: "validation"` instead of `category: "execution_failure"`. Added 12 new tests including an E2E test that exercises the full engine annotation chain.

## Implementation Overview

### What Was Built

1. **Hierarchy consolidation**: `SchemaValidationError(PflowError)` and `MarkdownParseError(PflowError)` moved to `core/exceptions.py`. `UserFriendlyError` rebased from `Exception` to `PflowError`. One-line re-exports left in original files for backward compatibility.

2. **Import cleanup**: All 24 lazy exception imports converted to module-level. The `CompilationError`-as-function-parameter pattern in `compile_validation.py` eliminated. The `_is_markdown_parse_error()` helper in `error_output.py` deleted.

3. **Duck-type hack elimination**: `type(exception).__name__ == "ValidationError" and hasattr(exception, "path")` in `runner.py` replaced with `isinstance(exception, SchemaValidationError)`.

4. **ValueError miscategorization fix**: `_exception_to_result` now uses `_pflow_node_id` annotation (set by engine on node execution exceptions) as a discriminator — annotated ValueErrors get `execution_failure`, unannotated get `validation`.

### Deviations from Plan

| Deviation | Reason |
|-----------|--------|
| Fixed `cli/main.py` (3 lazy imports) and `cli/discovery_errors.py` (1 lazy import) | Out of original scope but flagged by code review agents; trivial fix since `core/exceptions.py` is a leaf module |
| Added `if line is not None` guard in `MarkdownParseError.__init__` | Pre-existing `if line` truthiness bug — `line=0` would silently omit the prefix. Unreachable in practice (1-based lines) but consistent with consumer code patterns |
| Added E2E test `test_node_valueerror_categorized_as_execution_failure` | Found during adversarial verification — unit tests construct exceptions with `_pflow_node_id` pre-attached but don't verify the engine actually sets it |
| Updated 3 CLAUDE.md files + `architecture/architecture.md` | Stale documentation about exception hierarchy and import patterns |
| Fixed docstrings in `compile_validation.py` and `ir_preparation.py` | Still referenced old `ValidationError` name |

### Spec assumptions that were wrong

- **"No `except ValueError` relies on catching `MarkdownParseError`"** — `save_service.py:311` (`except (FileNotFoundError, ValueError)`) did. Found by 5/8 review agents. After the rebase, `MarkdownParseError` would fall through to `except Exception` producing a misleading "If this is a bug, please report it" message.
- **"16 production files"** — actual count was 22 (19 initially + 3 from code review additions).
- **`runner.py:359` lazy import not mentioned** — `WorkflowValidationError` lazy import inside `_validate()` method, redundant after module-level import was added.

## Files Modified/Created

### Core Changes (22 production files)

**Exception definitions (4 files)**:
- `core/exceptions.py` — Added `SchemaValidationError` and `MarkdownParseError` classes
- `core/ir_schema.py` — Removed 40-line class, replaced with `from pflow.core.exceptions import SchemaValidationError as ValidationError`
- `core/markdown_parser.py` — Removed 23-line class, replaced with `from pflow.core.exceptions import MarkdownParseError`
- `core/user_errors.py` — Changed `UserFriendlyError(Exception)` → `UserFriendlyError(PflowError)`

**Error dispatch (2 files — the most complex changes)**:
- `execution/runner.py` — Module-level imports for 6 exception types. Rewrote `_exception_to_result` dispatch: split `(MarkdownParseError, ValueError)` into three branches, eliminated duck-type hack, added `_pflow_node_id` discriminator for ValueError categorization. Removed 6 lazy imports across 3 methods.
- `cli/error_output.py` — Module-level imports for 8 exception types. Deleted `_is_markdown_parse_error` helper. Fixed `IrSchemaValidationError` alias → `SchemaValidationError`.

**Compilation (5 files)**:
- `runtime/compilation/compile_validation.py` — Module-level `CompilationError` + `SchemaValidationError`. Removed function parameter pattern. Fixed `ValidationError` → `SchemaValidationError` in 4 raise sites and 2 except clauses.
- `runtime/compilation/mcp_resolution.py` — Module-level `CompilationError`, removed lazy import
- `runtime/compilation/node_loader.py` — Same pattern
- `runtime/compilation/ir_preparation.py` — Same pattern + docstring fix
- `runtime/engine/engine.py` — Module-level `CompilationError`, removed 2 lazy imports in `run()`

**Other production files (11 files)**:
- `core/__init__.py` — `ValidationError` → `SchemaValidationError` in exports + `__all__`
- `core/workflow/validator.py` — Module-level `MarkdownParseError` + `SchemaValidationError`, removed 2 lazy imports
- `core/workflow/manager.py` — `MarkdownParseError` import path updated
- `core/workflow/save_service.py` — Import path + **critical fix**: added `MarkdownParseError` to `except (FileNotFoundError, ValueError)` at line 311
- `core/workflow/dependency_discovery.py` — Import path updated
- `cli/commands/workflow.py` — Module-level `MarkdownParseError` + `WorkflowValidationError`
- `cli/main.py` — Module-level `WorkflowNotFoundError` + `WorkflowValidationError`, removed 3 lazy imports
- `cli/discovery_errors.py` — Module-level `CriticalDiscoveryError`, removed 1 lazy import
- `mcp_server/services/execution_service.py` — Module-level `MarkdownParseError` + `WorkflowValidationError`, removed 2 lazy imports
- `runtime/engine/batch_executor.py` — Removed redundant lazy import (module-level already at line 19)
- `architecture/architecture.md` — `MarkdownParseError(ValueError)` → `MarkdownParseError(PflowError)`

### Test Files (13 files)

**New files (2)**:
- `tests/test_core/test_exception_hierarchy.py` — 5 tests: hierarchy coverage, attribute preservation, `MarkdownParseError not isinstance ValueError`, `MaxNodeVisitsError not isinstance PflowError`
- `tests/test_execution/test_runner.py` — 7 tests: ValueError categorization (annotated vs unannotated), SchemaValidationError field preservation, MarkdownParseError field extraction + None omission + node_id propagation, E2E engine annotation chain

**Modified files (11)** — `ValidationError` → `SchemaValidationError` rename + import path updates across all test files that reference these exceptions

### Critical tests (the ones that catch real bugs)

| Test | What it prevents |
|------|-----------------|
| `test_node_valueerror_categorized_as_execution_failure` | E2E: exercises full engine annotation → runner dispatch chain. Would have failed before the fix. |
| `test_valueerror_with_node_annotation_is_execution_failure` | Regression: ensures `_pflow_node_id` discriminator produces `execution_failure` |
| `test_markdown_parse_error_omits_none_fields` | Prevents null pollution in JSON error dicts |
| `test_markdown_parse_error_with_node_annotation` | Nested workflow: MarkdownParseError preserves `node_id` from engine annotation |
| `test_max_node_visits_error_intentionally_not_pflow_error` | Documents design decision — catches accidental rebase onto PflowError |

## Architectural Decisions & Tradeoffs

### Key Decisions

**Re-export strategy**: One-line re-exports in `ir_schema.py` (`SchemaValidationError as ValidationError`) and `markdown_parser.py` (`MarkdownParseError`). Zero external users, but these cost one line each and prevent silent breakage if any import path was missed. `test_markdown_parser.py` (20+ references) was deliberately left importing from `markdown_parser` — validates the re-export works and is arguably the correct import for a module's own test file.

**`MaxNodeVisitsError` stays on `RuntimeError`**: Intentionally NOT rebased onto `PflowError`. It's a runtime guard (infinite loop detection) that should propagate differently from domain errors. Test documents this decision.

**Conditional field assignment in error dicts**: `MarkdownParseError` branch uses `if exception.line is not None` / `if exception.suggestion` guards — never writes `None` into error dicts. Matches the `SchemaValidationError` branch pattern. Prevents `{"line": null}` in JSON output.

**`workflow_executor.py` left importing from `pflow.runtime`**: Imports `CompilationError` alongside `compile_workflow` from the same package. Splitting into two imports from different modules for closely related symbols reduces readability. The re-export chain resolves to the same class.

### Technical Debt

**`discover_dependencies()` silently swallows `MarkdownParseError` from child workflows** — tracked as #198. A saved bundle can contain a broken child workflow. Pre-existing from Task 130, not introduced by this PR.

## Patterns Established

### The "move + re-export" pattern

When consolidating a class from a heavy module to a leaf module:
1. Move the class to the target module
2. Leave a one-line re-export in the original module: `from target import ClassName`
3. Update all production imports to the canonical path
4. Leave test imports that test the original module importing from the original module (validates the re-export)
5. Update `__init__.py` exports and `__all__` lists

### `core/exceptions.py` is a leaf module — always safe for module-level imports

This is the key insight that made the entire refactor possible. `core/exceptions.py` imports only from `typing`. No circular dependency risk exists when importing from it at module level, anywhere in the codebase. This eliminated all 24 lazy imports.

Future agents: if you need to add a new exception class, put it in `core/exceptions.py` and import it at module level. Never create lazy imports for exception classes.

### Conditional error dict field assignment

Never write `None` values into error dicts. Use guards:
```python
if exception.line is not None:
    error_dict["line"] = exception.line
if exception.suggestion:
    error_dict["suggestion"] = exception.suggestion
```

This prevents `{"line": null}` in JSON output, which downstream consumers (AI agents) must then handle.

## Breaking Changes

### Behavioral Changes

- `MarkdownParseError` is no longer a `ValueError`. Any `except ValueError` that previously caught it implicitly will miss it. All production catch sites were audited and fixed. One test (`test_workflow_executor_comprehensive.py:226`) was updated.
- Node execution `ValueError`s (with `_pflow_node_id` annotation) now produce `category: "execution_failure"` instead of `category: "validation"` in error dicts. This is a correctness fix.
- `MarkdownParseError` error dicts now include `line` and `suggestion` fields (when non-None). Previously these were omitted.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/core/exceptions.py` — the canonical home for all exception classes
2. Read `src/pflow/core/CLAUDE.md` — has the full hierarchy diagram
3. For error dispatch: `execution/runner.py:_exception_to_result` (runtime) and `cli/error_output.py:_exception_to_errors` (CLI)
4. For understanding `_pflow_node_id`: `runtime/engine/engine.py:306-307` (sets it) and `execution/runner.py:501` (reads it)

### Common Pitfalls

- **Don't use `replace_all=True` when the replacement string contains the search string.** During implementation, `ValidationError` → `SchemaValidationError` with `replace_all=True` also hit import lines where `SchemaValidationError` already existed, creating `SchemaSchemaValidationError`. Do the import line edit separately, then use `replace_all` for remaining references.
- **Don't remove the re-exports in `ir_schema.py` or `markdown_parser.py`.** They look like dead code but many downstream consumers depend on them.
- **Dispatch chain ordering matters.** In both `_exception_to_result` and `_exception_to_errors`, subclasses must be checked before parents (`MCPError` before `UserFriendlyError`, `SchemaValidationError` before generic `Exception`).
- **When adding `except ValueError` blocks, check whether `MarkdownParseError` should be in the tuple.** It's no longer a `ValueError` subclass.

### Process note

The 8-agent parallel code review caught a real miss (`save_service.py:311`) that the implementation spec's exhaustive 6-agent research had explicitly claimed didn't exist. The adversarial verification phase caught a gap in E2E test coverage (unit tests didn't verify the engine's `_pflow_node_id` annotation step). Both patterns are worth repeating for any refactor that touches exception handling across 20+ files.

---

*Generated from implementation context of Task 141*
