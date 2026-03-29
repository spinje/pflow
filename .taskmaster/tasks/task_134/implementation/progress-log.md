# Task 134: Unify Output Auto-Detection — Progress Log

## 2026-03-29 — Implementation Complete

Task implemented from plan `~/.claude/plans/shimmering-discovering-sunrise.md`. Scope: unify the two `_find_auto_output()` implementations that returned different results for the same workflow (active correctness bug). Formatter deduplication deferred.

## The Bug

CLI text path (`workflow_output.py`) and JSON/MCP path (`success_formatter.py`) had different priority orders:

| Path | Priority |
|------|----------|
| CLI text | `response > output > result > text > stdout` |
| JSON/MCP | `result > output > response > text > data > stdout` |

Other differences: CLI searched namespaces first then root; JSON searched root first then namespaces. CLI had validity filtering; JSON didn't. CLI had no last-key fallback; JSON did.

## Implementation Steps

### Step 1: Created `src/pflow/execution/formatters/output_utils.py`

Three functions extracted/merged:
- `_is_valid_output_value(value)` — rejects None and empty/whitespace strings
- `_find_in_namespaces(shared_storage, key)` — iterates non-`_`-prefixed dict values
- `find_auto_output(shared_storage)` — public unified function

Unified behavior: `result > response > output > text > data > stdout`, root first, validity filter, `_`/`__` key filter, last-key fallback.

### Step 2: Updated CLI text path

Removed 3 local functions from `workflow_output.py`. Imported `find_auto_output` from `output_utils`. Added stderr warning with two variants:
- No declared outputs: `"cli: No outputs declared — showing auto-detected key '{key}'. Declare outputs for reliable results."`
- `--only` active: `"cli: Declared outputs skipped (--only). Showing auto-detected key '{key}'."`

Warning suppressed in `--print` mode.

### Step 3: Updated JSON/MCP path

Removed local `_find_auto_output` (38 lines) from `success_formatter.py`. Imported shared function. No warning (would pollute structured output).

### Step 4: Updated existing tests

**`test_workflow_output_handling.py`**:
- `test_fallback_key_priority_order`: Updated assertions for new priority (`result` beats everything). Two test cases changed expected output.
- `test_no_output_shows_success_message`: Changed `output_key: "internal_key"` to `"_internal_key"` — the new last-key fallback would have found the old key, breaking the "no output" test. `_` prefix makes it invisible to auto-detection.

**`test_success_formatter.py`**:
- Updated imports: `_find_auto_output` → `find_auto_output` from `output_utils`
- All 3 `TestFindAutoOutputNamespaceAware` tests passed without logic changes

**Integration tests** (`test_e2e_workflow.py`, `test_workflow_save_integration.py`):
- 5 tests asserted `"Workflow executed successfully"` — this message only appears when `output_produced=False`. The new last-key fallback now finds output in workflows that previously had none (file node writes to shared store). Changed assertions to check `"Workflow completed"` instead.

### Step 5: Wrote new tests — `test_output_utils.py`

37 tests total:
- `TestIsValidOutputValue` (8): None, empty, whitespace, string, zero, False, empty dict/list
- `TestFindInNamespaces` (6): basic find, last-wins, `_`-skip, `__`-skip, validity, non-dict skip
- `TestFindAutoOutput` (20): pairwise priority (5), root-before-namespace, namespace search, validity filtering (2), key filtering (2), last-key fallback (2), empty/all-invalid/all-internal (3), full priority chain, zero/False/dict values (3)
- `TestAutoDetectionWarning` (3): no-declared-outputs warning, `--only` warning, `--print` suppression

### Step 6: Updated CLAUDE.md docs

- `src/pflow/cli/CLAUDE.md`: Replaced dual-implementation table with unified description
- `src/pflow/execution/formatters/CLAUDE.md`: Updated success_formatter description, added `output_utils` to formatter index table

### Step 7: Fixed loose ends

- **Stale comment** in `compiler.py:628` — referenced old dual implementations, updated to `output_utils.find_auto_output`
- **`--only` warning** — initial implementation used wrong message ("No outputs declared") when `--only` was active. Fixed to check `__execution__.only_node` and show appropriate message.

## Decisions

1. **Priority order** — chose `result > response > output > text > data > stdout`. `result` first because it's the most intentional output key. `data` added (was only in JSON path). This matches the old JSON/MCP behavior which is more principled.

2. **Root before namespace** — root is where `populate_declared_outputs()` writes resolved values. Root-first ensures declared output values win over raw namespace values.

3. **Dict-namespace disambiguation removed** — the old CLI path had logic to skip root dict values that "looked like namespaces" (contained priority keys). The new code treats all root values as outputs. This is a conscious simplification: a node literally named `result` with sub-keys is uncommon, and declared outputs are the right fix.

4. **Last-key fallback with validity filter** — adopted from JSON path. The old CLI path had no fallback, which meant workflows with non-standard output keys showed "no output." The fallback is more helpful. The validity filter prevents returning None/empty as "output."

## Verification

- `make test`: 4665 passed
- `make check`: all green (ruff, ruff-format, mypy, deptry)
- Manual verification deferred to user

## Files Changed

| Action | File |
|--------|------|
| CREATE | `src/pflow/execution/formatters/output_utils.py` |
| CREATE | `tests/test_execution/formatters/test_output_utils.py` |
| MODIFY | `src/pflow/cli/workflow_output.py` |
| MODIFY | `src/pflow/execution/formatters/success_formatter.py` |
| MODIFY | `src/pflow/runtime/compilation/compiler.py` (comment only) |
| MODIFY | `tests/test_cli/test_workflow_output_handling.py` |
| MODIFY | `tests/test_execution/formatters/test_success_formatter.py` |
| MODIFY | `tests/test_integration/test_e2e_workflow.py` |
| MODIFY | `tests/test_cli/test_workflow_save_integration.py` |
| MODIFY | `src/pflow/cli/CLAUDE.md` |
| MODIFY | `src/pflow/execution/formatters/CLAUDE.md` |
