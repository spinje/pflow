# Task 141 Implementation Progress Log

## 2026-03-31 22:30 - Plan Review (Pre-Implementation)

Ran two plan review agents in parallel before implementation:
- `review-plan`: Found the plan structurally sound. Key warnings: (W2) MarkdownParseError branch in `_exception_to_result` unconditionally writes `None` values — plan text already had the corrected version with guards. (W4) `workflow_executor.py` imports `CompilationError` from `pflow.runtime` not canonical path — intentional exception.
- `review-silent-failures`: Confirmed C1 (lost `node_id` for sub-workflow parse errors) and C2 (unconditional `None` values) — both addressed in the corrected plan text.

**Decision**: Proceed with implementation using the corrected MarkdownParseError branch (with `None` guards and `annotated_node_id` preservation).

## 2026-03-31 22:45 - Phase 1: Move + Rebase + Rename

Added `SchemaValidationError` and `MarkdownParseError` to `core/exceptions.py`. Added re-exports in `ir_schema.py` and `markdown_parser.py`.

- `ir_schema.py`: Removed 40-line `ValidationError` class, replaced with `from pflow.core.exceptions import SchemaValidationError as ValidationError`
- `markdown_parser.py`: Removed 23-line `MarkdownParseError(ValueError)` class, replaced with `from pflow.core.exceptions import MarkdownParseError  # noqa: F401`

## 2026-03-31 22:50 - Phase 2: Rebase UserFriendlyError

Changed `UserFriendlyError(Exception)` to `UserFriendlyError(PflowError)` in `user_errors.py`. Added `from pflow.core.exceptions import PflowError` import. Trivial change.

## 2026-03-31 22:55 - Phase 3: Fix All Production Import Sites

This was the largest phase — 16 production files modified. Key changes:

1. **`core/__init__.py`**: `ValidationError` → `SchemaValidationError` in exports
2. **`compile_validation.py`**: Module-level `CompilationError` + `SchemaValidationError` imports. Removed `CompilationError` function parameter from `_validate_data_flow_at_compile_time` and its call site.
3. **`validator.py`**: Module-level `MarkdownParseError` + `SchemaValidationError`, removed two lazy imports
4. **`error_output.py`**: Module-level imports for all 8 exception types. Deleted `_is_markdown_parse_error` helper. Fixed `isinstance` check from `IrSchemaValidationError` to `SchemaValidationError`.
5. **`runner.py`**: The most complex file. Module-level imports for 6 exception types. Rewrote `_exception_to_result` dispatch chain:
   - Split `(MarkdownParseError, ValueError)` branch into three: `SchemaValidationError`, `MarkdownParseError`, `ValueError`
   - Eliminated duck-type hack `type(exception).__name__ == "ValidationError"`
   - Fixed ValueError categorization: with `_pflow_node_id` → `execution_failure`, without → `validation`
   - MarkdownParseError branch preserves `node_id`, `line`, `suggestion` (with None guards)
6. **`save_service.py`**: Added `MarkdownParseError` to catch clause at line 311 — critical fix for the rebase
7. **4 compilation files**: Module-level `CompilationError` import, removed lazy `from .compiler import CompilationError`
8. **`engine.py`**: Module-level `CompilationError`, removed 2 lazy imports
9. **`batch_executor.py`**: Removed redundant lazy import (module-level already existed)

## 2026-03-31 23:10 - Phase 5: Fix Test Imports

Updated 11 test files:
- 8 files: `ValidationError` → `SchemaValidationError` (imports + all usage sites)
- 3 files: `MarkdownParseError` import path from `markdown_parser` to `exceptions`
- 1 file: `pytest.raises(ValueError)` → `pytest.raises(MarkdownParseError)` (the ONE breaking test)

**Bug introduced during implementation**: Used `replace_all=True` for `ValidationError` → `SchemaValidationError` which also hit the import line where it was already `SchemaValidationError`, creating `SchemaSchemaValidationError`. Affected 4 files: `test_ir_schema.py`, `test_workflow_interfaces.py`, `test_compiler_interfaces.py`, `test_output_validation.py`. Fixed immediately.

💡 **Insight**: `replace_all=True` is dangerous when the replacement string contains the search string. The import line `from pflow.core.exceptions import SchemaValidationError` already contained the target. Should have done the import line edit separately, then used `replace_all` for the remaining references.

## 2026-03-31 23:15 - Phase 6: New Tests

Created 2 new test files/classes:
1. `tests/test_core/test_exception_hierarchy.py` — 4 tests verifying hierarchy, attributes, and `not isinstance(ValueError)`
2. `tests/test_execution/test_runner.py::TestExceptionToResultCategorization` — 5 regression tests for the ValueError categorization fix

## 2026-03-31 23:20 - Phase 7: Final Verification

First `make test` run: 4532 passed, 4 errors (the `SchemaSchemaValidationError` typo from Phase 5). Fixed and re-ran.

**Results:**
- `make test`: 4655 passed in 8.43s
- `make check`: ruff passed (auto-fixed 6 import sorting issues), mypy clean, deptry clean

Verified elimination targets:
- Zero `from pflow.core.ir_schema import.*ValidationError` in src/pflow/ ✅
- Zero `from pflow.core.markdown_parser import.*MarkdownParseError` in src/pflow/ ✅
- Zero `from .compiler import CompilationError` in src/pflow/ (except `__init__.py` re-export) ✅
- Zero `type(exception).__name__ == "ValidationError"` in src/pflow/ ✅

## 2026-03-31 23:25 - Phase 8: Code Review

Deployed 7 specialized review agents in parallel. All returned zero critical code issues.

### Findings Addressed

1. **`if line` truthiness check** (flagged by 2 agents): Changed `if line` to `if line is not None` in `MarkdownParseError.__init__`. Pre-existing pattern (not introduced by this task), but trivial fix. `line=0` is unreachable (1-based), but `is not None` is consistent with how consumers check the same attribute in `_exception_to_result` and `_markdown_parse_to_errors`.

2. **Missing test for MarkdownParseError + `_pflow_node_id`** (flagged by 2 agents): Added unit test for nested workflow error propagation path — MarkdownParseError annotated with node ID should produce both `category: "validation"` and `node_id` in the error dict.

3. **CLAUDE.md documentation stale** (flagged by 3 agents): Updated three files:
   - `core/CLAUDE.md`: Replaced prose list with full hierarchy diagram showing all classes and their locations
   - `compilation/CLAUDE.md`: Changed "lazy-import via compiler.py re-export" to "import directly from core.exceptions (module-level)"
   - `architecture/architecture.md`: Changed `MarkdownParseError(ValueError)` to `MarkdownParseError(PflowError)`

4. **Docstrings still reference `ValidationError`** (flagged by 1 agent): Fixed in `compile_validation.py` (`_raise_input_validation_errors` and `_validate_outputs` docstrings) and `ir_preparation.py` (`prepare_inputs` return docstring).

5. **Remaining lazy `WorkflowValidationError` imports** (flagged by 3 agents): These were out of the plan's original scope (they weren't moved by this task — they already lived in `core/exceptions.py`). Fixed anyway since `core/exceptions.py` is a leaf module with zero circular dependency risk:
   - `mcp_server/services/execution_service.py`: 2 lazy imports → 1 module-level
   - `cli/commands/workflow.py`: 1 lazy import → module-level

   Also fixed lazy imports in `cli/main.py` (3 sites → module-level) and `cli/discovery_errors.py` (1 site → module-level) for `WorkflowNotFoundError`, `WorkflowValidationError`, and `CriticalDiscoveryError`.

6. **Missing `MaxNodeVisitsError` negative assertion** (flagged by 1 agent): Added test confirming `MaxNodeVisitsError` is `RuntimeError` and NOT `PflowError`. This documents the intentional design decision — if someone accidentally rebases it onto `PflowError`, the test catches it.

### Disputed Findings

- **Staged vs unstaged state** (flagged by 5/7 agents): All agents saw the git staging state from the session snapshot and flagged `SchemaSchemaValidationError` typos in staged files. Irrelevant — ruff auto-fixed the import sorting, `make test` (4655 pass) + `make check` (clean) confirmed the working tree is correct. Staging is a commit-time concern, not a code issue.

- **`workflow_executor.py` imports `CompilationError` from `pflow.runtime`** (flagged by 3 agents): Intentional exception per plan. `workflow_executor.py:13` imports `from pflow.runtime import CompilationError, compile_workflow` — splitting this into two imports from different modules for closely related symbols would reduce readability. The re-export chain resolves to the same class.

## 2026-03-31 23:50 - Phase 9: Manual Testing + Baseline Comparison

Ran all baseline test fixtures in both text and JSON mode. Every output compared against `baseline-error-output.md`.

| Fixture | Text match | JSON match | Exit code |
|---------|-----------|------------|-----------|
| `valid.pflow.md` | ✅ | ✅ | 0 |
| `malformed.pflow.md` | ✅ | ✅ | 1 |
| `duplicate-ids.pflow.md` | ✅ | ✅ | 1 |
| `unclosed-code-block.pflow.md` | ✅ | ✅ | 1 |
| `missing-type.pflow.md` | ✅ | ✅ | 1 |
| `bad-schema.pflow.md` | ✅ | ✅ | 1 |
| `bad-sub-workflow.pflow.md` | ✅ | ✅ | 1 |
| `exec-failure.pflow.md` | ✅ | ✅ | 1 |
| `exec-failure-chain.pflow.md` | ✅ | ✅ | 1 |
| `--validate-only valid` | ✅ | — | 0 |
| `--validate-only malformed` | ✅ | — | 1 |
| `--validate-only bad-schema` | ✅ | — | 1 |

**All outputs match baselines exactly. No regressions.**

## 2026-04-01 00:15 - Adversarial Verification

Challenged the implementation from a "try to break it" perspective rather than "confirm it works."

### Approach

Deployed two `pflow-codebase-searcher` agents:
1. **Untested catch sites**: Traced all 14 `parse_markdown()` call sites through their enclosing try/except chains to find any `except ValueError` that would silently miss `MarkdownParseError` after the rebase.
2. **Test regression gaps**: Searched all 97 `pytest.raises(ValueError)` for any that previously caught `MarkdownParseError` and now silently pass.

### Key Findings

**All 14 `parse_markdown` call sites are safe.** Breakdown:
- 8 sites catch `MarkdownParseError` explicitly by name before any broader catch
- 3 sites let it propagate to callers that catch it (runner's `_exception_to_result`, engine's annotation)
- 2 sites intentionally swallow via `except Exception` (best-effort operations: `manager.list_all`, `template_validator._resolve_child_outputs`)
- 1 site re-wraps via `except Exception` into `ValueError` (lossy but functional: `workflow_executor._resolve_child_workflow`)

**Zero `except ValueError` blocks depend on catching `MarkdownParseError`.** The production code that converts `MarkdownParseError` → `ValueError` at boundaries (`save_service.py:188`, `execution_service.py:328`) was preserved, so tests expecting `ValueError` from those paths still work.

**`save_service.py:311` fix is defensive, not critical.** The `parse_markdown` at line 282 in `_discover_and_bundle_deps` re-parses content that was already validated by `_load_and_validate_file`. The `MarkdownParseError` catch is for a theoretically possible but practically unreachable race condition. Manually verified: passing malformed parent content through `save_workflow_with_options` doesn't reach this code path because the malformed content has no file references to trigger dependency discovery.

### E2E Gap Found and Fixed

**The `_exception_to_result` unit tests don't test the engine's `_pflow_node_id` annotation.** They construct exceptions with `_pflow_node_id` pre-attached and verify the dispatch logic. If the engine annotation at `engine.py:307` were removed, the unit tests would still pass but the real pipeline would regress (all node `ValueError`s back to `category: "validation"`).

Added `test_node_valueerror_categorized_as_execution_failure` — a real `WorkflowRunner().run()` call with a code node that raises `ValueError`. This tests the full chain: engine catches exception → annotates `_pflow_node_id` → re-raises → runner catches → `_exception_to_result` dispatches to `execution_failure`. **This test would have failed before the fix.**

Manual E2E verification confirmed:
```
$ uv run pflow --output-format json /tmp/test-valueerror.pflow.md
→ category: "execution_failure", node_id: "fail-with-valueerror"
```

## Deviations from Plan

### Beyond plan scope (improvements found during code review)

| Change | Rationale |
|--------|-----------|
| Fixed `if line` → `if line is not None` in `MarkdownParseError.__init__` | Pre-existing inconsistency with consumer code. Trivial fix, zero risk. |
| Fixed docstrings in `compile_validation.py` and `ir_preparation.py` | Still referenced old `ValidationError` name. Misleading for readers. |
| Fixed 3 lazy `WorkflowValidationError` imports in `execution_service.py` and `commands/workflow.py` | Out of plan scope (these exceptions weren't moved), but same leaf-module argument applies. |
| Added `MaxNodeVisitsError` negative assertion test | Documents the intentional `RuntimeError` (not `PflowError`) design decision. |
| Added `test_markdown_parse_error_with_node_annotation` unit test | Covers nested workflow error propagation path flagged by 2 review agents. |
| Added `test_node_valueerror_categorized_as_execution_failure` E2E test | Found during adversarial verification — unit tests don't cover the engine's `_pflow_node_id` annotation step. |
| Updated 3 CLAUDE.md files | Stale documentation about exception hierarchy and import patterns. |

### Not fixed (intentional)

| Item | Rationale |
|------|-----------|
| `workflow_executor.py` imports `CompilationError` from `pflow.runtime` | Intentional — imports alongside `compile_workflow` for readability. Plan acknowledged this. |
| `ir_schema.py` module docstring still shows `except ValidationError as e:` in example | Works via the local `SchemaValidationError as ValidationError` alias. Changing the example would be cosmetically correct but functionally misleading — `validate_ir()` internally raises `ValidationError` (the alias), so the example is accurate for consumers of that module. |
| `save_service.py:188` wraps `MarkdownParseError` as `ValueError`, losing structured attributes | Pre-existing. Not introduced by this task. Worth a future cleanup (could raise `MarkdownParseError` directly), but changing error types at API boundaries is a separate concern. |
| `test_core/test_markdown_parser.py` still imports `MarkdownParseError` from `pflow.core.markdown_parser` | The re-export makes this work. Arguably correct — the test file tests `markdown_parser` functionality, so importing from that module validates the re-export path. 20+ references; mechanical rename with no behavioral benefit. |

## Final State

| Metric | Before | After |
|--------|--------|-------|
| Independent exception trees | 4 | 1 |
| Lazy exception imports in src/pflow/ | 24 | 0 (scoped: `ValidationError`, `MarkdownParseError`, `CompilationError`) |
| Remaining lazy exception imports | — | 0 |
| ValidationError aliases | 3 | 0 |
| Duck-type hacks | 1 | 0 |
| `_is_markdown_parse_error` helpers | 1 | 0 |
| CompilationError-as-parameter pattern | 1 | 0 |
| ValueError miscategorization | Yes | Fixed |
| `except PflowError` catches all | No | Yes |
| Tests passing | 4646 | 4658 (+12 new) |
| Production files modified | — | 22 |
| Test files modified | — | 13 (11 modified + 2 new) |
