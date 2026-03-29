# Task 134: Unify Output Detection and Deduplicate Formatters

## Problem

### 1. Auto-detection output divergence (original scope)

Two live auto-detection implementations exist for finding workflow output when no declared outputs match:

| Location | Used by | Priority order | Namespace-aware |
|----------|---------|----------------|-----------------|
| `workflow_output.py:_find_auto_output` | CLI text output | response > output > result > text > stdout | Yes |
| `success_formatter.py:_find_auto_output` | JSON output, MCP server | result > output > response > text > data > stdout | Yes |

These have different priority orders and different key lists. **Active correctness bug**: a workflow producing both `response` and `result` keys shows different output in text vs JSON mode.

~~The third one (`executor_service._extract_default_output`)~~ **DELETED** (Task 137) — it was dead code (`output_data` field removed from `ExecutionResult`).

### 2. Duplicated step formatting (added scope — Layer 5 from Task 137 analysis)

Two parallel implementations of per-node execution step formatting:

| Location | Used by | Features |
|----------|---------|----------|
| `workflow_output.py:_format_node_status_line` | CLI text display | Full: stderr indicator, smart-handled tags (`[no matches]`, `[not found]`), batch details |
| `success_formatter.py:_format_execution_step` | JSON output, MCP text | Subset: basic status/timing only, no stderr/smart-handled tags |

The CLI version is a superset. These should be unified in the shared formatter.

### 3. Duplicated `_truncate_error_message()`

Identical function exists in both `workflow_output.py:425` and `success_formatter.py:361`. Should be one shared function.

## Discovery Context

Found during Task 106 follow-up (--only UX fixes). The JSON `_find_auto_output` was not namespace-aware, causing `--only` to return raw namespace dicts instead of meaningful output values. Fixed by adding namespace traversal and `stdout` to its key list. The inconsistency between implementations was noted but deferred to avoid scope creep.

## What to Do

### Auto-detection unification (original scope)

1. **Create a single shared `find_auto_output()` function** in `execution/formatters/` or `execution/output_utils.py`
2. **Reconcile the priority order** — decide on one canonical order. Current recommendation: `result > response > output > text > stdout > data` (result first for generality, response second for LLM workflows, stdout for shell nodes)
3. **Make it namespace-aware** (already done for both implementations)
4. **Update both consumers** (`workflow_output.py` and `success_formatter.py`) to use the shared function
5. ~~**Clean up `executor_service._extract_default_output`**~~ **DONE** (Task 137 deleted it — `output_data` field removed)

### Formatter deduplication (added scope)

6. **Unify step formatting** — move `_format_node_status_line()` from `workflow_output.py` into the shared formatter (it's the superset). Have both CLI text display and `format_success_as_text()` call the shared version. The formatter version (`_format_execution_step`) can be deleted.
7. **Extract shared `_truncate_error_message()`** — move to a shared location, delete both copies
8. **Delete `_format_batch_node_line()` and `_format_batch_errors_section()` from `success_formatter.py`** if they're also duplicated (verify against `workflow_output.py` equivalents)

## Key Files

- `src/pflow/cli/workflow_output.py` — text version: `_find_auto_output` (~line 127), `_format_node_status_line` (~line 364), `_truncate_error_message` (~line 425)
- `src/pflow/execution/formatters/success_formatter.py` — JSON version: `_find_auto_output` (~line 165), `_format_execution_step` (~line 449), `_truncate_error_message` (~line 361)
- ~~`src/pflow/execution/executor_service.py:704-793`~~ **DELETED** (Task 137)

**Note**: Line numbers shifted after Task 137. Re-verify before implementing.

## Risks

- The two `_find_auto_output` implementations return different values for the same workflow in edge cases (different priority orders). Unifying to one order could change what some workflows output. Need test coverage first.
- `_find_in_namespaces` (text version) uses `_is_valid_output_value()` to filter out empty/None values. The JSON version doesn't. Need to decide whether JSON should also filter.
- Step formatting unification: the CLI version has features (stderr indicator, smart-handled tags) that the formatter version lacks. Moving the richer version into the shared formatter means MCP text output also gains these features — probably desirable but verify.

## Scope

Medium. Auto-detection unification is the priority (fixes the correctness bug). Formatter deduplication is lower risk and can be done in the same pass since it touches the same files.

## Context from Task 137

Task 137 (Unified CLI Output Pipeline, 2026-03-29) restructured the error output layer. Key impact on this task:
- `executor_service._extract_default_output` is deleted — one fewer implementation to worry about
- `ExecutionResult.output_data` field is deleted — the third auto-detection consumer is gone
- The output pipeline is now unified for errors — this task unifies it for success output
- See `.taskmaster/tasks/task_137/task-review.md` "Key Architectural Insights" for the design reasoning that also applies here (success path works because it has a clean data pipeline; the auto-detection divergence is the remaining gap in that pipeline)
