# Task 117: Subcommand JSON Error Output

## Description

Make error paths in the CLI subcommands respect a JSON output mode with the unified error structure established by Task 137, so agents driving the CLI directly (not via the MCP server) get parseable errors from `describe`, `find`, `save`, `history`, `probe`, etc. — not just from the `run` path.

**Scope narrowed twice:**
- Task 137 (Unified CLI Output Pipeline, completed 2026-03-29) handled the `run` path: unified pipeline, `output_error()` infrastructure, exception-based propagation, pre-initialization safety.
- This task covers the remaining top-level subcommands.

> **Rescoped 2026-06-07 (verified against `main`).** The original spec targeted `registry.py` / `registry_run.py` / `workflow.py`, which **no longer exist** — the CLI was flattened into one-file-per-command under `src/pflow/cli/commands/` by Task 151 (CLI Surface Restructure, 2026-04-12). The file/line tables below have been rewritten against the current layout, and the root-cause analysis was corrected: a group-level error boundary and `output_error()` already exist, but are structurally inert for subcommands (see "Root cause"). The remaining work is smaller than the original framing suggested.

## Status
not started

## Priority

medium (the main workflow path used by agents is fixed; this is the direct-CLI subcommand surface)

---

## Root cause (verified 2026-06-07)

The infrastructure is **already in place** but cannot fire for subcommands:

1. **A group-level error boundary exists.** `PflowCLI.invoke` (`src/pflow/cli/main.py:51-68`) wraps every command, catches `PflowError`, and routes it through `output_error()`:
   ```python
   except PflowError as e:
       obj = ctx.obj or {}
       output_error(ctx, exception=e,
                    output_format=obj.get("output_format", "text"),  # <-- the problem
                    verbose=obj.get("verbose", False))
       ctx.exit(1)
   ```

2. **But the boundary reads the format from `ctx.obj["output_format"]`, which only the `run` command ever sets.** The group callback (`main.py:123-133`) sets only `ctx.obj["verbose"]`. So when a subcommand raises a `PflowError`, the boundary catches it and renders **text** — the `--json` / `--output-format` flag the user passed to the subcommand never reaches the boundary.

3. **Subcommand JSON flags are local, inconsistent, and partly absent.** None of them write into `ctx.obj["output_format"]`.

4. **Several error paths bypass the boundary entirely** by using inline `click.echo(..., err=True)` + `return`/`ctx.exit(1)` instead of raising a `PflowError`.

So there are three distinct failure modes, and a complete fix must address all three.

---

## Verified current state (2026-06-07)

`output_error()` (the Task 137 unified JSON-error function in `src/pflow/cli/error_output.py`) is used by exactly **one** subcommand today: `report.py`. Every other subcommand renders text on error.

| Command file | Command | JSON flag today | Flow on error | Failure mode |
|---|---|---|---|---|
| `commands/list.py` | `pflow list` | `--json` (bool) | service errors → boundary → **text**; no-match notice echoed | A |
| `commands/find.py` | `pflow find` | **none** | `handle_discovery_error()` / boundary → text | B, C |
| `commands/describe.py` | `pflow describe` | **none** | service raises → boundary → **text** | B |
| `commands/history.py` | `pflow history` | **none** | service raises → boundary → **text** | B |
| `commands/save.py` | `pflow save` | **none** | 13× `click.echo`; raises → boundary → **text** | B, C |
| `commands/probe.py` + `_probe_impl.py` | `pflow probe` | `--output-format` | `_probe_impl` 20× `click.echo` | A, C |
| `commands/read_fields.py` | `pflow read-fields` | `--output-format` | 6× `click.echo` | A, C |
| `commands/mcp.py` | `pflow mcp …` | `--json` (bool) | 90× `click.echo`, 2 raises | A, C |
| `commands/visualize.py` | `pflow visualize` | **none** | 7× `click.echo` | B, C |
| `commands/analyze_cache.py` | `pflow analyze-cache` | **none** | 10× `click.echo` | B, C |
| `commands/report.py` | `pflow report` | **none** (uses `output_error` 2×) | partially structured | — |

**Failure-mode legend:**
- **A** — has a JSON flag, but it isn't propagated to `ctx.obj["output_format"]`, so boundary-caught `PflowError`s still render text.
- **B** — has no JSON flag at all, so there's no way to request JSON.
- **C** — has inline `click.echo + return/exit` error paths that never reach the group boundary.

**Flag inconsistency:** `list` and `mcp` use `--json` (boolean); `probe`, `read_fields`, and `run` use `--output-format text|json` (choice).

---

## Solution

The heavy lifting (boundary + `output_error()` + unified shape + exception classes) is **done**. Three mechanical changes remain:

### 1. Standardize the flag and propagate it to `ctx.obj`

> **DECIDED 2026-06-07 — standardize on `--output-format text|json`.** Chosen over `--json` because it (a) matches the `run` command's existing flag, (b) aligns with the key the group boundary already reads (`ctx.obj["output_format"]`), so JSON rendering of any `PflowError` is automatic, and (c) leaves room for non-binary formats later. `list` and `mcp` migrate from `--json` to `--output-format` as a **clean cutover** — no hidden `--json` alias (the project has no users, so churn cost is zero and a single convention is worth more than back-compat). This resolves the prior open question.

Implementation: a shared decorator (e.g. `@output_format_option`) adds `--output-format text|json` and sets `ctx.obj["output_format"] = output_format` early in each agent-facing subcommand, so the existing group boundary renders JSON automatically with **zero per-error-path changes** for any error already raised as a `PflowError`. The decorator is the deep-module way to avoid repeating the flag + `ctx.obj` write in every command.

### 2. Convert inline `click.echo + exit` error paths to raise `PflowError`
For genuine errors (not informational notices like list's "no match"), raise the appropriate `PflowError` subclass instead of echoing + exiting. They then flow through the boundary and render correctly in both modes. This is the same conversion Task 137 applied to `main.py`.

### 3. Add the flag to agent-facing commands that lack one
`describe`, `history`, `find`, `save` are parsed by agents — they need a JSON mode (mode **B** above). `visualize`/`analyze_cache` are lower priority (their primary output is a diagram / human report), but error-JSON still helps automation.

**The unified JSON error shape** (established by Task 137, unchanged):
```json
{
  "success": false,
  "status": "failed",
  "error": "Human readable summary",
  "errors": [
    { "message": "Detailed error message", "category": "validation|not_found|cli|...", "suggestion": "How to fix" }
  ]
}
```
The `workflow` field is `run`-path-specific; per the Task 137 contract, optional fields are omitted when not applicable, so subcommand errors omit it.

---

## Implementation Plan

### ~~Phase 1: Infrastructure~~ DONE (Task 137)
`output_error()` in `src/pflow/cli/error_output.py`. No new function/dataclass needed.

### ~~Phase 2: run-path migration~~ DONE (Task 137)

### Phase 3: Shared flag + ctx propagation (THE CORE OF THIS TASK)
- Add a shared `--output-format text|json` option (decorator) that writes `ctx.obj["output_format"]`.
- Apply to the agent-facing subcommands. This alone fixes failure mode **A** and the flag gap (**B**) for every error already raised as `PflowError`.
- Migrate `list`/`mcp` `--json` → `--output-format` (clean cutover, no alias — see DECIDED note in Solution §1).

### Phase 4: Convert bypass paths (failure mode C)
- Audit inline `click.echo(err=True) + return/exit` in `_probe_impl.py` (20), `save.py` (13), `mcp.py` (90), `read_fields.py` (6), `visualize.py` (7), `analyze_cache.py` (10).
- Convert true-error echoes to `PflowError` raises. Leave informational/UX echoes (prompts, "no match" notices, progress) as text — they are not errors.

### Phase 5: Testing
1. For each agent-facing command: JSON error output parses with `jq '.success, .error, .errors[0].message'`.
2. Text-mode regression: rich formatting preserved.
3. Flag-consistency test across commands.

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/pflow/cli/main.py` | (boundary already correct; only if a shared decorator needs registering) |
| `src/pflow/cli/error_output.py` | reuse `output_error()` — likely no change |
| **NEW** shared option, e.g. `src/pflow/cli/output_format_option.py` | `--output-format` decorator that writes `ctx.obj["output_format"]` |
| `src/pflow/cli/commands/describe.py` | add flag (mode B) |
| `src/pflow/cli/commands/history.py` | add flag (mode B) |
| `src/pflow/cli/commands/find.py` | add flag (mode B); align `handle_discovery_error` with `output_error` |
| `src/pflow/cli/commands/save.py` | add flag (B); convert echo-errors to raises (C) |
| `src/pflow/cli/commands/list.py` | migrate `--json`→`--output-format` (A) |
| `src/pflow/cli/commands/probe.py` + `_probe_impl.py` | propagate format to `ctx.obj` (A); convert echo-errors (C) |
| `src/pflow/cli/commands/read_fields.py` | propagate format (A); convert echo-errors (C) |
| `src/pflow/cli/commands/mcp.py` | migrate flag (A); convert echo-errors (C) — large surface |
| `src/pflow/cli/commands/visualize.py`, `analyze_cache.py` | lower priority (B, C) |
| `tests/test_cli/` | JSON error tests per command |

---

## Verification

```bash
# ALREADY work (Task 137 — run path):
uv run pflow --output-format json nonexistent.pflow.md            # ✅ unified JSON
uv run pflow --output-format json bad-node.pflow.md               # ✅ unified JSON

# CURRENT gaps (this task) — all render plain text today:
uv run pflow describe nonexistent-workflow                        # ❌ no JSON flag (mode B)
uv run pflow history nonexistent-workflow                         # ❌ no JSON flag (mode B)
uv run pflow find ""                                              # ❌ no JSON flag (mode B)
uv run pflow save bad-file.txt                                    # ❌ no JSON flag (mode B)
uv run pflow probe nonexistent-node --output-format json          # ❌ flag not propagated (mode A/C)
uv run pflow read-fields bad-exec-id x --output-format json       # ❌ flag not propagated (mode A/C)
uv run pflow list --json   # error case                           # ❌ flag not propagated (mode A)

# After this task, each should parse with:
# jq '.success, .error, .errors[0].message'
```

---

## Acceptance Criteria

- [x] ~~Central error output function~~ **DONE** (Task 137 — `output_error()`)
- [x] ~~Group-level boundary routes `PflowError`~~ **DONE** (`PflowCLI.invoke`)
- [x] ~~Single unified JSON structure~~ **DONE** (Task 137)
- [ ] All agent-facing subcommands accept `--output-format text|json` (no `--json`), written into `ctx.obj["output_format"]`
- [ ] Boundary-caught `PflowError`s render JSON when the subcommand's format is JSON (mode A closed)
- [ ] `describe`, `history`, `find`, `save` have a JSON mode (mode B closed)
- [ ] True-error inline `click.echo + exit` paths converted to `PflowError` raises (mode C closed for agent-facing commands)
- [ ] Rich text formatting preserved in text mode
- [ ] Tests verify JSON output for each subcommand error path
- [ ] `make check` and `make test` pass

---

## Error Categories Reference

Authoritative category enum (from `tests/test_cli/test_unified_error_output.py`). Most relevant here: `not_found` (node/workflow not found), `validation` (bad params), `cli` (usage errors).

**Pre-execution**: `validation`, `compilation`, `parse_error`, `not_found`, `cli`, `mcp`, `max_visits`, `file_not_found`, `permission_denied`, `unknown`
**Post-execution**: `execution_failure`, `api_validation`, `template_error`

---

## Design Decisions

### Established by Task 137
1. Optional fields omitted (not null).
2. Single `errors` array; each entry has at least `message` and `category`.
3. `error` is always a string, never a dict.
4. Reuse `output_error()` — don't create new formatting functions.
5. Exception-based propagation — convert `click.echo + exit` to raises where the message is a genuine error.

### Decided (this task)
1. **Flag convention: `--output-format text|json`** (2026-06-07) — standardized over `--json`; `list`/`mcp` migrate to it as a clean cutover, no alias. Rationale in Solution §1.

### Open questions (for the user)
1. **Display-oriented commands** (`describe`, `history`, `visualize`): full structured-data JSON output is out of scope here — this task is about **error** JSON. Success-mode JSON for these can be a follow-up if agents need it.

---

## Dependencies

- Task 137: Unified CLI Output Pipeline (2026-03-29) — provides `output_error()`, the unified shape, and exception classes.
- Task 151: CLI Surface Restructure (2026-04-12) — flattened the command files this task now targets.

## Related Work

- `.taskmaster/tasks/task_137/task-review.md` — patterns to follow for echo→raise conversion.
- `src/pflow/cli/CLAUDE.md` and `src/pflow/cli/commands/CLAUDE.md` — current routing, output rules, and the group boundary.
