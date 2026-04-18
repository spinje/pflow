# Task 148: Failed-Node Invariant Fix and Template Error UX Consolidation

## Description

Fix the shared store invariant so failed nodes don't leak data into downstream template resolution (root cause of GH #208), unify scattered failure-tracking and node-state queries behind helpers, and rewrite the template error pipeline to produce structured, AI-actionable error messages. Originated as a one-line bug fix for `??` coalesce; expanded after a "simplicity of final code, not ease of getting there" review surfaced an invariant mismatch and broad duplication.

> **Implementation plan**: `.taskmaster/tasks/task_148/implementation/implementation-plan.md` — phase-by-phase HOW with exact code edits.

## Status

done

## Completed

2026-04-09

## Priority

high

## Problem

### The bug (GH #208)

The `??` coalesce operator resolves to a failed node's empty/garbage output instead of falling through to the next operand. Reproduction:

```markdown
### primary
- type: shell
- on-error: fallback
```shell command
exit 1
```

### fallback
- type: shell
```shell command
echo "fallback-content"
```

## Outputs
### content
- source: ${primary.stdout ?? fallback.stdout}
```

Expected: `fallback-content`. Actual: empty string.

This makes `??` ineffective for the primary `on-error` fallback chain pattern. A real-world music-generation pipeline (`fetch-source` workflow with `fetch-youtube` → on-error → `fetch-youtube-mcp` → coalesced output) hits this bug.

### The deeper problem — wrong invariant

The bug exists because Task 128 introduced `??` with the invariant **"node ran ↔ present in shared store"** — but the system actually has three states: didn't run, succeeded, failed-via-on-error. The namespaced store eagerly creates `shared[node_id] = {}`, and shell's `post()` writes `stdout/stderr/exit_code/error` BEFORE returning `"error"`. So failed nodes are present in the store with garbage data, and `resolve_coalesce`'s `root not in context` check sees them as "successful".

This invariant mismatch has metastasized into the codebase:

- ~15 sites independently re-discover the wrong invariant via inline `root in context` checks
- 5 sites mark a node as failed with no central helper (each writing to `__execution__["failed_node"]`, `__warnings__`, `invalidate_cache` in slightly different combinations)
- 5 implementations of "extract root node id from `node.field[0]`" — 2 use the canonical regex, 1 compiles a separate identical regex, 1 uses inline uncompiled regex, 1 uses sequential string splits
- 4 wording variants of "node X did not execute" across different modules
- 2 parallel template-error rendering paths that don't overlap correctly: strict-mode template errors get `category="execution_failure"` so the rich `_format_template_error_lines` never fires for them; meanwhile any random ValueError with `${` in its message accidentally triggers the rich rendering
- ~12 Diagnostic context fields are written by `executor_service` but never rendered by `format_diagnostic` (dead work)

### The error UX problem (for AI agents)

Current error messages for the failure modes that matter:

- **Reference a failed node without `??`**: silently resolves to empty string. Single worst UX outcome — workflow looks fine but produces garbage
- **Reference a failed node (with or without typo)**: error says "node X did not execute" — wrong, it DID execute and failed; agent fixes the wrong thing
- **Coalesce with all operands failed**: same wrong message, no fix suggestion
- **Failed batch / shell node display**: post-execution summary loses `batch_metadata`, `exit_code`, `stderr` because the formatter reads from `shared[node_id]`
- **JSON/MCP consumers**: get an opaque multi-line string in `Diagnostic.message` instead of structured per-reference data
- **`OutputResolutionError`** has a category typo (`"runtime"` not in `_CATEGORY_TITLES`) → renders as generic "Error"

For an AI agent editing a workflow, today's messages are non-actionable: they don't say what failed, why it matters, or what to change.

### Loop re-entry correctness gap (discovered during plan review)

Even with the move to `__failures__`, a loop scenario (node fails on visit 1, runs again on visit 2 successfully) leaves a stale failure record unless explicitly cleared. Without cleanup, `get_node_status()` would return FAILED for a successfully-completed node, breaking every consumer.

## Solution

### Fix the invariant, not the symptom

Move failed-node data from `shared[node_id]` to `shared["__failures__"][node_id]` after the node completes execution. The move happens at a single canonical location (after trace recording, metrics, and progress callback) so all bookkeeping reads succeed before the data relocates. After the move:

- `shared[node_id]` exists ↔ node ran successfully and produced authoritative output
- `shared["__failures__"][node_id]` exists ↔ node executed and failed
- A node never appears in both at the same time
- `resolve_coalesce` needs **no modification** — its existing `root in context` check is correct under the new invariant

The invariant is the right model for the system. Every consumer that asks "is this node's output usable?" gets the right answer from `shared` membership alone.

### Unify the scattered concerns

A new module `src/pflow/runtime/node_state.py` provides the single source of truth:

- `get_node_status(shared, node_id) → NodeStatus` — ABSENT/SUCCEEDED/FAILED
- `get_node_output(shared, node_id)` — succeeded data OR failed data, None if absent (for consumers that need data either way: trace, error enrichment, sub-workflow extraction)
- `get_node_failure(shared, node_id)` — failure record only
- `node_succeeded(shared, node_id)` — shortcut for SUCCEEDED check
- `mark_node_failed(shared, node_id, *, category, error, warning)` — single canonical write site
- `clear_node_failure(shared, node_id)` — wired into the loop guard so re-execution starts fresh

All ~15 read sites and 5 write sites funnel through these helpers. Failure category is set explicitly at the failure site (engine knows it's a template/shell/api error) and stored on the failure record — replacing the fragile regex-on-message-string category detection in `executor_service`.

A new `TemplateResolver.extract_root_node_id()` static method replaces the 5 duplicate root-extraction implementations and makes the canonical regex truly private.

### Restructure template errors as structured Diagnostics

Replace `build_enhanced_template_error` (returns a multi-line text blob crammed into `Diagnostic.message`) with `build_template_error_diagnostic` returning a fully-structured `Diagnostic`. All rich data goes into `context.unresolved_references` as a list of per-variable dicts with status (absent/succeeded-with-path-error/failed), failure details (error/exit_code/command/stderr per category), peer node suggestions, and typo hints.

The renderer in `core/diagnostic.py` consumes the structured context and produces the agent-actionable text format. JSON/MCP consumers get programmatic access to the same structure via `Diagnostic.to_dict()` — no longer parsing opaque message strings.

Three states for each unresolved variable, each with concrete fix guidance:

- **ABSENT** (didn't run) — explain the branch didn't execute, suggest a peer node if available
- **FAILED** (executed but failed) — surface the actual failure category, error, and category-relevant fields (shell command/exit_code/stderr; HTTP status/url/response; MCP server/tool); offer a paste-able coalesce fix using a real peer node name
- **PATH_ERROR** (succeeded with typo) — show available fields, suggest the closest match

When a typo is on a FAILED node (the data shape is still known), surface the typo as a SECONDARY hint alongside the failure — eliminates a wasted iteration cycle for AI agents.

When ALL operands of a coalesce fail, emit a summary fix block at the parent level suggesting another fallback operand. Without this, the per-operand "use coalesce" suggestions are circular and unhelpful.

### Source line tracking for output declarations

Extend the markdown parser to track the source line of `- source:` declarations on outputs. The line propagates through `output_resolver` into the failure record, then into the Diagnostic context, where the existing `_format_location` renders `At: workflow.pflow.md, line 23` — giving AI agents an editor-clickable, file:line-formatted location for every error.

### What this is NOT

- **Not a transactional NamespacedSharedStore refactor** — that's cleaner but bigger; the post-execution move achieves the same user-visible behavior. Filed as Tier 3 follow-up.
- **Not a sub-workflow Diagnostic propagation rewrite** — child errors still flatten to strings at the boundary. Acceptable for this task; richer propagation can come later.
- **Not a backwards-compat shim** — pre-1.0, no users; tests that read failed-node data from `shared[node_id]` are wrong and must update.
- **Not a `??` operator semantic change** — coalesce stays "skip if root absent". The invariant fix makes that semantic correct for the on-error case naturally.

## Design Decisions

- **Move data, don't delete** — failed-node data goes to `__failures__`, preserving it for diagnostics/error enrichment/trace. A delete would lose information that consumers need.

- **Move at the END of `_execute_node` (step 17.5), uniformly across all failure paths** — happy-path returned-error, api warning, raised exception. `cache_result` and `handle_api_warning` keep their existing positions in the orchestration; only the data move is centralized at the end. This means trace recording, metrics, progress callbacks all read `shared[node_id]` directly — no `get_node_output` indirection in their hot paths. `mark_node_failed` is the LAST thing that runs for any failing node.

- **`clear_node_failure` wired into `enforce_loop_guard`** — loop re-entry must clear stale failure records before the new attempt runs, otherwise `get_node_status` returns FAILED for a successful re-execution.

- **No backward compatibility** — pre-1.0, no users. Every consumer migrates. Tests that asserted on `shared[failed_node]` data are wrong and must be updated.

- **`__failures__` is internal** — double-underscore convention like `__execution__`. NOT exposed in user templates. If a user pattern emerges (e.g., wanting `${primary.error}` accessible from a fallback), we'd add a first-class syntax later, not let users reach into `__failures__`.

- **Tier 1 + Tier 2 in one task** — they touch overlapping files; doing them separately means re-touching the same code. Tier 3 items become separate GH issues.

- **Failure category set at the source** — engine's except block knows it's a template/exception error; `cache_result` knows it's a returned-error action; `handle_api_warning` knows it's API. Each writes the category onto the failure record. The formatter reads it. Removes the fragile `"${" in error_message` regex match.

- **Structured Diagnostic context, not raw strings** — JSON/MCP consumers get programmatic access. Text rendering happens in `_format_*_block` functions in `diagnostic.py`, not by stuffing multi-line strings into `Diagnostic.message`. Constraint: `Diagnostic.__eq__/__hash__` identity is `severity+source+node_id+message`, so the message must be specific enough per-error to not collapse via dedup.

- **Category-aware failure rendering** — failed shell nodes show command/exit_code/stderr; failed HTTP nodes show status/url/response; failed MCP nodes show server/tool/details. A single hardcoded shell-only renderer would lose every other node type's diagnostic fields.

- **Peer node suggestions in fix messages** — fix templates substitute actual peer node names (e.g., `${primary.stdout ?? fallback.stdout}`) instead of placeholders (`${var ?? <fallback>.field}`). Computed at classification time so JSON consumers also get the data.

- **Typo detection on failed nodes as secondary hint** — when an agent has both a typo AND a failure, surfacing both at once (with the failure as primary, typo as secondary hint) eliminates a wasted iteration cycle.

- **`OutputResolutionError` routes through the same renderer** — output-source resolution failures use `category="template_error"` with structured `unresolved_references`, not the legacy plain-string `explanation` path. Same bug class, same quality tier across both error paths.

- **`file:line` format for source references** — editor-clickable, AI-agent-parseable, standard convention.

- **Rejected: error-aware coalesce check** — earlier proposal had `resolve_coalesce` consult `__execution__["completed_nodes"]` directly. Rejected because it leaves the broken invariant in place; every future consumer of `shared[node_id]` would have to independently know about the side channel. Fixing the invariant once is simpler than patching every consumer.

- **Rejected: new `?!` operator** — earlier proposal added a "skip if failed or absent" operator alongside `??`. Rejected because the new semantic IS what users intuitively expect from `??`; making the common case require a special operator is a UX smell.

- **Deferred to Tier 3 (separate GH issues)**:
  - Transactional `NamespacedSharedStore` (buffer writes locally, commit on success, archive on failure)
  - Richer `get_upstream_stderr` (show command/exit/error, only fire for genuinely-failed upstreams)
  - Consolidating `path_validation.py` enhanced errors with runtime template errors (single shared builder)

## Dependencies

None. Self-contained.

## Requirements

### Invariant

- `shared[node_id]` exists ↔ node `node_id` ran successfully and produced authoritative output
- `shared["__failures__"][node_id]` exists ↔ node `node_id` executed and failed
- A node never appears in both at the same time, including across loop re-entry
- The invariant holds for all five failure paths: shell exit error, raised exception, API warning, routing error (no successor), `_handle_no_successor` defensive
- Cleanup happens after `record_trace` and `call_completion_callback` so trace events have full data
- Loop re-entry: a node that failed on a previous visit and re-executes successfully must transition cleanly to SUCCEEDED state with no stale failure record

### Helpers (`runtime/node_state.py`)

- `NodeStatus` enum with `ABSENT`, `SUCCEEDED`, `FAILED`
- `get_node_status(shared, node_id) → NodeStatus`
- `get_node_output(shared, node_id) → Optional[Any]` returns succeeded OR failed data, None if absent
- `get_node_failure(shared, node_id) → Optional[FailureRecord]` returns failure record only
- `node_succeeded(shared, node_id) → bool`
- `mark_node_failed(shared, node_id, *, category, error=None, warning=None)` — single write site; moves data, sets `failed_node`, optionally writes warning, strips loop-stale `completed_nodes` entries
- `clear_node_failure(shared, node_id)` — used by loop guard to clear stale records on re-entry
- All helpers handle missing `__failures__`/`__execution__` keys gracefully

### Failure record shape

```python
{
    "data": {...},                # what was at shared[node_id] before the move (may be {})
    "category": "shell_failure" | "node_action_error" | "api_warning" | "routing_error" | "exception" | "template_error",
    "error": "...",               # human-readable error message (optional)
    "warning": "...",             # for api_warning category only (optional)
}
```

### Coalesce semantics (unchanged at the resolver level, corrected at the data level)

- `${primary.stdout ?? fallback.stdout}` where `primary` failed and `fallback` succeeded resolves to `fallback`'s stdout
- `${primary.stdout ?? fallback.stdout}` where `primary` succeeded with empty stdout still resolves to `primary`'s empty stdout (succeeded ⇒ use the data; `ignore_errors: true` is the canonical "intentional empty" path)
- `${primary.stdout ?? fallback.stdout}` where both failed produces a structured error
- Coalesce in code-node optional inputs (`x: int | None = ${a.val ?? b.val}`) injects None if all source nodes are absent OR failed
- Coalesce in `inputs:` dict params behaves identically to coalesce in output declarations
- `resolve_coalesce` is NOT modified — its existing `root in context` check is correct under the new invariant

### Consolidation

- All ~15 sites that check `root in context` / `node_id in shared` either use a `node_state.py` helper or are documented as legitimately needing a different semantic
- All 4 root-id extraction implementations replaced with `TemplateResolver.extract_root_node_id()`
- All 5 failed-node bookkeeping sites funnel through `mark_node_failed`
- All 4 "did not execute" message wordings replaced with one canonical formatter
- `TemplateResolver._ROOT_SPLIT_PATTERN` is private (no cross-module access)
- `executor_service.determine_error_category` reads category from `__failures__[node_id].category` first; legacy regex is fallback only

### Template error structure

- `build_enhanced_template_error` (raw string) replaced with `build_template_error_diagnostic` returning a `Diagnostic`
- Diagnostic context contains structured `unresolved_references` list — each entry: `var`, `root`, `status` (absent|failed|path_error), `in_coalesce`, `coalesce_expr`, `failure` (with `category`, `error`, `data`), `peer_suggestions`, `secondary_hint`, `available_fields`, `did_you_mean`
- `Diagnostic.message` is a one-line summary that includes the param key and a variable summary (preserves identity-hash distinctness)
- The same renderer produces output for text CLI, JSON CLI, MCP server (no path divergence)
- Category-aware failure data extraction: shell renders `command`/`exit_code`/`stderr`; HTTP renders `status_code`/`url`/`response`; MCP renders `server`/`tool`/`error_details`; generic fallback renders any scalar fields

### Error message UX (AI-actionability requirements)

- **Failed-node references**: surface the actual failure category and error, the exit_code (or status_code, etc.), the command (or url), and a stderr/response preview
- **Fix suggestions are paste-able**: substitute actual peer node names from the workflow context (e.g., `${primary.stdout ?? fallback.stdout}`), not placeholders like `${var ?? <fallback>.field}`
- **All-coalesce-failed (Case 2)**: emit a summary "All operands failed" block with a paste-able pattern for adding another fallback, plus a pointer to debug the underlying failures
- **Typo on a failed node (Case 3)**: surface BOTH the failure (primary) AND the typo correction (secondary hint), so the agent can fix both in one iteration
- **Typo on a succeeded node (Case 4)**: show the closest field-name match as a paste-able fix
- **Absent node (Case 5)**: explain "branch not taken", suggest a peer node if one is available
- **Available context keys**: always shown when there are unresolved references, regardless of status (agents need this to write any fix)
- **`OutputResolutionError`** uses `category="template_error"` (not the broken `"runtime"` typo) and surfaces the structured rendering — same quality tier as node-param template errors

### Source line tracking

- Parser tracks `_source_line` for output `source:` declarations
- Template error Diagnostics include `source_file` and `source_line` in context
- `format_diagnostic` renders `At: <file>, line <N>` for template errors

### Display preservation for failed nodes

- `build_execution_steps` reads via `get_node_output` so failed batch nodes still show `batch_metadata`, `batch_total`, `batch_error_details` in CLI/MCP execution summaries
- Failed shell nodes still show `exit_code`, `stderr`, `smart_handled` in summaries

### Out of scope (explicit non-goals)

- Transactional `NamespacedSharedStore` (Tier 3 → separate issue)
- Richer `get_upstream_stderr` showing command+exit_code+stdout (Tier 3 → separate issue)
- Consolidating `path_validation.py` enhanced errors with runtime errors (Tier 3 → separate issue)
- Sub-workflow Diagnostic propagation (child errors flatten to strings at the boundary — acceptable for this task)
- General error message sweep across non-template modules
- Pre-execution validation message changes (validation reads IR, not shared store, unaffected)
- `__execution__["failed_node"]` → `failed_nodes` list (pre-existing single-value quirk, orthogonal)
- Migrating `__warnings__` consumers to a unified failure model
- Backward-compatibility shims for the invariant change
- Surfacing `__failures__` to user templates

## Verification

### Acceptance criteria

- The #208 repro (`scratchpads/issue-208/repro.pflow.md`) produces output `fallback-content`, not empty
- Direct reference `${primary.stdout}` to a failed primary produces a structured error with `category="template_error"`, surfaces the actual failure (shell command, exit_code, stderr), and includes a paste-able coalesce fix using a real peer node name
- All five failure paths archive to `__failures__` and set `failed_node`
- All four root-extraction duplicates are deleted; only `TemplateResolver.extract_root_node_id` remains
- All five "mark failed" sites funnel through `mark_node_failed`
- No `node 'X' did not execute` message appears for a node that DID execute and failed
- `OutputResolutionError` renders with a real title and structured `unresolved_references` (not the legacy plain-string explanation)
- Failed batch nodes show `batch_error_details` in execution summary (CLI + MCP)
- Failed shell nodes show `exit_code`, `stderr` in execution summary
- Loop re-entry: a node that failed on visit 1 and succeeds on visit 2 reports `node_succeeded == True` and is NOT in `__failures__`
- Trace files contain full failed-node data (stdout, stderr, exit_code, error, command)
- `--report` for the #208 repro shows `primary` as failed with full context, `fallback` as succeeded
- JSON output mode exposes `unresolved_references` as a structured list (not an opaque message string)
- MCP server returns the same structured Diagnostic context
- Existing tests pass — especially `test_root_present_as_empty_dict_counts_as_present` and Task 128 branch convergence tests

### Manual test scenarios

1. **#208 repro**: `uv run pflow scratchpads/issue-208/repro.pflow.md --no-cache --no-trace` → output `fallback-content`
2. **Direct failed-node reference**: edit repro to use `${primary.stdout}` (no coalesce) → structured error with `FAILED` label, exit_code, paste-able coalesce fix
3. **Both operands fail**: edit repro so fallback also fails → structured error with "All coalesce operands failed" summary block
4. **Typo + failure**: edit repro to use `${primary.stddout}` → primary error is the failure, secondary hint identifies the typo
5. **Typo on succeeded node**: workflow with successful node and `${node.stddout}` → "Did you mean: `${node.stdout}`" with paste-able fix
6. **HTTP failure reference**: workflow with HTTP node returning 503 referenced via template → error shows status_code/url/response (not shell fields)
7. **Successful coalesce**: existing branch convergence workflows still work (Task 128 regression)
8. **JSON mode**: `--output-format json` for failed cases → structured `unresolved_references` in error JSON
9. **MCP**: invoke same workflows via MCP server → identical Diagnostic structure
10. **`--report`**: → markdown report shows per-node failure details
11. **`ignore_errors: true`**: shell node with `ignore_errors: true` and `exit 1` → output is empty string (unchanged), node in `completed_nodes`, NOT in `__failures__`
12. **Loop with failure recovery**: node fails visit 1, loop revisits, node succeeds visit 2 → workflow completes, downstream references see success data

### Quality gates

- `make check` passes (lint, type check)
- `make test` passes (full suite, in parallel)
- New tests follow existing patterns in `tests/test_runtime/` and `tests/test_execution/`
- No `# noqa` suppressions added
- No new warnings introduced

## References

### Bug

- GH #208: https://github.com/spinje/pflow/issues/208
- Reproduction: `scratchpads/issue-208/repro.pflow.md`

### Prior task that introduced the broken invariant

- Task 128: Branch Convergence for Conditional Workflows (`.taskmaster/tasks/task_128/`)
  - `task-review.md:55-86` — documents the "node ran ↔ present" invariant (the one being corrected)
  - `task-review.md:82-86` — Decision 1 explaining `??` semantics as "root absent"
  - `progress-log.md:7-11` — investigation that framed absence as "non-taken branches", missed the failed-via-on-error case

### Related fixed bug

- GH #200 fix (branch `fix/next-end-ignored-on-error`) — fixed `next: end` + `on-error` engine routing. This task is the follow-up: routing now works, but the output declaration doesn't pick up the fallback's result.

### Diagnostic system

- Task 143: Unified Diagnostic System
- Task 144: Display Consolidation — Diagnostic Rendering Redesign

### Implementation

- `.taskmaster/tasks/task_148/implementation/implementation-plan.md` — phase-by-phase HOW
