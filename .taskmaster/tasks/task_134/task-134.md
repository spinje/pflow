# Task 134: Unify Auto-Detection Output Functions

## Problem

Three separate auto-detection implementations exist for finding workflow output when no declared outputs match:

| Location | Used by | Priority order | Namespace-aware |
|----------|---------|----------------|-----------------|
| `workflow_output.py:_find_auto_output` | CLI text output | response > output > result > text > stdout | Yes |
| `success_formatter.py:_find_auto_output` | JSON output, MCP server | result > output > response > text > data > stdout | Yes (added in Task 106 follow-up) |
| `executor_service.py:_extract_default_output` | `ExecutionResult.output_data` (unused by display) | result > output > response > data | No |

These have different priority orders, different key lists, and were independently evolved. The third one (`executor_service`) is effectively dead code — `output_data` is set on `ExecutionResult` but never read by any display path.

## Discovery Context

Found during Task 106 follow-up (--only UX fixes). The JSON `_find_auto_output` was not namespace-aware, causing `--only` to return raw namespace dicts instead of meaningful output values. Fixed by adding namespace traversal and `stdout` to its key list. The inconsistency between implementations was noted but deferred to avoid scope creep.

## What to Do

1. **Create a single shared `find_auto_output()` function** in a shared location (e.g., `execution/formatters/` or a new `execution/output_utils.py`)
2. **Reconcile the priority order** — decide on one canonical order. Current recommendation: `result > response > output > text > stdout > data` (result first for generality, response second for LLM workflows, stdout for shell nodes)
3. **Make it namespace-aware** (already done for both live implementations)
4. **Update both consumers** (`workflow_output.py` and `success_formatter.py`) to use the shared function
5. **Clean up `executor_service._extract_default_output`** — either remove it (if `output_data` is truly unused) or wire it to the shared function

## Key Files

- `src/pflow/cli/workflow_output.py:97-159` — text version with `_find_in_namespaces` helper
- `src/pflow/execution/formatters/success_formatter.py:170-210` — JSON version (recently updated)
- `src/pflow/execution/executor_service.py:704-793` — third implementation (possibly dead code)

## Risks

- The two live implementations return different values for the same workflow in edge cases (different priority orders). Unifying to one order could change what some workflows output. Need test coverage first.
- `_find_in_namespaces` (text version) uses `_is_valid_output_value()` to filter out empty/None values. The JSON version doesn't. Need to decide whether JSON should also filter.

## Scope

Small-medium. Mostly moving code, not writing new logic. The hard part is the priority order decision.
