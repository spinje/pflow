# Task 117: Subcommand JSON Error Output

## Description

Make error paths in CLI subcommands (`registry.py`, `registry_run.py`, `workflow.py`) respect `--output-format json` / `--json` with the unified error structure established by Task 137.

**Scope narrowed**: Task 137 (Unified CLI Output Pipeline, completed 2026-03-29) fully handled main.py — unified pipeline, `output_error()` infrastructure, exception-based propagation, pre-initialization safety. This task covers only the remaining subcommand modules that Task 137 did not touch.

## Status
in progress

## Priority

medium (lowered — the main workflow path used by agents is fixed)

## Problem

### What's fixed (Task 137)

- ~~main.py: 39 error-related functions~~ — **ALL FIXED**. Unified pipeline via `output_error()` in `error_output.py`.
- ~~Inconsistent JSON structures (7 shapes)~~ — **FIXED**. One unified shape: `{success, status, error, errors, workflow}`.
- ~~Pre-initialization errors~~ — **FIXED**. Outer catch in `workflow_command` handles `ctx.obj` being None.
- ~~stdout bugs~~ — **FIXED** (registry.py, workflow.py).

### What remains (this task)

CLI subcommand modules still output plain text errors regardless of `--json` / `--output-format json`:

| Module | Error paths | Check format | Notes |
|--------|-------------|-------------|-------|
| `registry.py` | ~7 without JSON | 6 of 13 check `output_json` | `describe` and `discover` have no `--json` flag |
| `registry_run.py` | 8 | 0 of 8 | `--output-format json` exists but only governs success |
| `workflow.py` | ~14 | 0 of 14 | Only `list` has `--json`; save/describe/history/discover have none |

Additionally, flag naming is inconsistent: `list`/`scan` use `--json` (boolean), `run` uses `--output-format` (choice).

---

## Solution

### Use Task 137's infrastructure

Task 137 created `src/pflow/cli/error_output.py` with `output_error()` — the single error output function for the CLI. The subcommand modules should use this same function and produce the same unified JSON shape.

**The unified JSON error shape** (established by Task 137):
```json
{
  "success": false,
  "status": "failed",
  "error": "Human readable summary",
  "errors": [
    {
      "message": "Detailed error message",
      "category": "validation|not_found|cli|...",
      "suggestion": "How to fix"
    }
  ],
  "workflow": {"action": "unsaved"}
}
```

**Design note for subcommands**: The `workflow` field was designed for `workflow_command`. For registry/workflow subcommands, it should still be present (consistent shape) but may have `{"action": "unsaved"}` as a default. Alternatively, these commands could omit the `workflow` field entirely and document that — the unified shape contract says optional fields are "omitted when not applicable."

### Approach for each module

For each subcommand error path, the conversion follows the same pattern Task 137 used for main.py:

1. Convert `click.echo() + sys.exit(1)` to exception raises (use `UserFriendlyError` or `WorkflowValidationError`)
2. Add a catch block that calls `output_error()` from `error_output.py`
3. Add `--json` or `--output-format` flags to commands that lack them

---

## Implementation Plan

### ~~Phase 1: Infrastructure~~ DONE (Task 137)

`output_error()` in `src/pflow/cli/error_output.py` is the infrastructure. No new function or dataclass needed.

### ~~Phase 2: main.py Migration~~ DONE (Task 137)

All main.py error paths unified via pipeline restructure. See `.taskmaster/tasks/task_137/task-review.md`.

### Phase 3: CLI Subcommand Modules (THE REMAINING WORK)

**NOTE**: Line numbers below are from the original investigation (2026-01-23) and have shifted. Re-verify before implementing.

**registry.py** (~7 error paths without JSON):
- `list` exception handler — add JSON
- `describe` node not found — add JSON (needs `--json` flag on `describe` command)
- `describe` exception handler — add JSON
- `discover` validation errors — add JSON (needs `--json` flag on `discover` command)
- `describe_nodes` errors — add JSON

**registry_run.py** (8 error paths, 0 check format):
- `_validate_parameters` — add JSON
- `_prepare_node_execution` — add JSON
- Cache failure warning — add JSON
- MCPError display — add JSON
- `_handle_ambiguous_node` — add JSON
- `_handle_unknown_node` — add JSON
- `_handle_execution_error` — add JSON

**workflow.py** (~14 error paths, 0 check format):
- `_handle_workflow_not_found` — add JSON (needs `--json` flag on `describe`/`history`)
- `_validate_discovery_query` — add JSON (needs `--json` flag on `discover`)
- `_load_and_parse_workflow` — add JSON (needs `--json` flag on `save`)
- Save errors — add JSON
- Delete warning — add JSON
- Name validation — add JSON

**Flag decisions needed**:
- Which commands get `--json` vs `--output-format`? Current inconsistency: `list`/`scan` use `--json` (boolean), `run` uses `--output-format` (choice). Should standardize.
- Commands like `describe` and `history` output rich text — does `--json` make sense for them?

### Phase 4: Testing

1. JSON output tests for each subcommand error path
2. Text output regression (preserve rich formatting)
3. Flag consistency tests

---

## Files to Modify

| File | Changes |
|------|---------|
| ~~`src/pflow/cli/error_output.py`~~ | ~~**NEW**~~ **EXISTS** (Task 137) — use `output_error()` from here |
| ~~`src/pflow/cli/main.py`~~ | **DONE** (Task 137) |
| `src/pflow/cli/commands/registry.py` | Add JSON error support to ~7 error paths, add `--json` to describe/discover |
| `src/pflow/cli/commands/registry_run.py` | Add JSON error support to all 8 error paths |
| `src/pflow/cli/commands/workflow.py` | Add `--json` flag to save/describe/history/discover, add JSON error support |
| `tests/test_cli/` | New tests for subcommand JSON error output |

---

## ~~Bugs to Fix~~ DONE (Task 137)

~~Both stdout→stderr bugs~~ fixed in Task 137 Phase 7.

---

## Error Categories Reference

Use the authoritative category enum from Task 137 (`tests/test_cli/test_unified_error_output.py`):

**Pre-execution**: `validation`, `compilation`, `parse_error`, `not_found`, `cli`, `mcp`, `max_visits`, `file_not_found`, `permission_denied`, `unknown`

**Post-execution**: `execution_failure`, `api_validation`, `template_error`

For subcommand errors, the most relevant categories are: `not_found` (node/workflow not found), `validation` (bad params), `cli` (usage errors).

---

## Verification

```bash
# These ALREADY work (Task 137):
uv run pflow --output-format json nonexistent.pflow.md          # ✅ unified JSON
echo "data" | uv run pflow --output-format json no-stdin.pflow.md  # ✅ unified JSON
uv run pflow --output-format json bad-node.pflow.md             # ✅ unified JSON

# These are the REMAINING gaps (this task):
uv run pflow registry describe nonexistent-node --json          # ❌ plain text
uv run pflow registry run nonexistent-node --output-format json # ❌ plain text errors
uv run pflow workflow describe nonexistent --json               # ❌ no --json flag
uv run pflow workflow save bad-file.txt --json                  # ❌ no --json flag

# After this task, all should parse with:
# jq '.success, .error, .errors[0].message'
```

---

## Acceptance Criteria

- [x] ~~Central error output function~~ **DONE** (Task 137 — `output_error()`)
- [x] ~~All main.py error paths unified~~ **DONE** (Task 137)
- [x] ~~Single unified JSON structure~~ **DONE** (Task 137)
- [x] ~~Pre-initialization errors handled~~ **DONE** (Task 137)
- [x] ~~stdout→stderr bugs fixed~~ **DONE** (Task 137)
- [ ] All error paths in registry.py produce JSON when `--json` is set
- [ ] All 8 error paths in registry_run.py produce JSON when `--output-format json` is set
- [ ] All error paths in workflow.py produce JSON when `--json` is set
- [ ] `--json` flag added to `describe`, `discover`, `save`, `history` commands that lack it
- [ ] Rich text formatting preserved for text mode
- [ ] Tests verify JSON output for each subcommand error path
- [ ] `make check` passes
- [ ] `make test` passes

---

## Design Decisions

### Established by Task 137

1. **Optional fields omitted** (not null) — cleaner JSON, easier parsing
2. **Single `errors` array** — each entry has `message` and `category` at minimum
3. **`error` is always a string** — never a dict
4. **Use `output_error()` from `error_output.py`** — don't create new formatting functions
5. **Exception-based error propagation** — convert `click.echo + exit` to exception raises where possible

### Open Questions (for this task)

1. **`--json` vs `--output-format`**: Standardize? `list`/`scan` use `--json`, `run` uses `--output-format`. Pick one.
2. **`workflow` field for non-workflow commands**: `pflow registry describe nonexistent-node --json` — should the output include a `workflow` field? Could omit it or use `null`.
3. **Which commands actually benefit from `--json`?**: `describe` and `history` are display-oriented. Does JSON make sense for them, or only for error output?

---

## Dependencies

- Task 137: Unified CLI Output Pipeline (completed 2026-03-29) — provides infrastructure (`output_error()`, unified JSON shape, exception classes)
- Task 115: Automatic Stdin Routing (completed) — added stdin routing error (now fully handled by Task 137)

## Related Work

- Task 137 `.taskmaster/tasks/task_137/task-review.md` — architectural insights, patterns to follow
- Layer 5 (formatter deduplication) is Task 134 territory, NOT this task

---

## Investigation Notes

Original investigation (2026-01-23) — line numbers are STALE (code changed significantly by Task 137):
- ~~main.py has 39 error-related functions~~ — restructured by Task 137
- registry.py has ~13 error outputs, 6 check output_json (partial support)
- registry_run.py has 8 error outputs, 0 check output_format (no support)
- workflow.py has ~14 error outputs, 0 check output format (no support, only `list` has `--json`)

Re-verify line numbers before implementing — Task 137 also modified registry.py (stdout fixes) and workflow.py (stdout fixes).
