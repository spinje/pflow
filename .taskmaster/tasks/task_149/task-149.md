# Task 149: Fix Non-Interactive Output Routing + Output Pipeline Consolidation

## Description

Fix GH issue #194 (workflow data routed to stderr in non-interactive mode) and consolidate the output rendering pipeline. Deletes ~470 lines of dead scaffolding (`OutputInterface`, `CliOutput`, `NullOutput`, `DisplayManager`), unlocks live progress streaming for agents, and collapses a duplicate execution summary. The result is one coherent output rule instead of a three-mode system.

## Status

done

## Priority

high

## Problem

**Bug #194** — In non-interactive mode (Claude Code Bash tool, CI/CD, shell pipelines), `pflow workflow.pflow.md` writes **0 bytes to stdout** and dumps the workflow's declared output into stderr alongside diagnostics. Agents capturing stdout receive nothing; `pflow foo.pflow.md | jq` is broken for any non-TTY consumer. This is the standard way agents run CLI tools — the tool is unusable for its core use case.

**Root cause** — `src/pflow/cli/workflow_output.py::_output_with_header` has a three-mode routing system where Mode 3 (non-interactive, no `--print`) deliberately routes everything to stderr "for correct ordering". The rationale ("tools capturing streams separately may show stdout before stderr") was theoretical and wrong; the fix was to follow Unix convention.

**Surrounding dead code** — Investigation revealed the routing bug sits on top of an over-abstracted display layer:
- `NullOutput` has zero imports anywhere.
- `DisplayManager` has 4 methods; only 1 is live.
- `CliOutput` has 7 methods; only 1 is reached from production code.
- `OutputInterface` protocol has 7 methods; the runner calls exactly 1.
- `_display_execution_summary` emits a "Nodes executed (N):" block that duplicates the live progress stream that follows it (visible to TTY users as the duplication in the original bug report screenshot).
- The CLI and MCP text formatters have parallel implementations of the same per-node block (Task 85 "Hard-Won: Update BOTH Call Sites" territory).

**Secondary UX issue** — Live progress is TTY-gated via `OutputController.create_progress_callback()` returning `None` in non-interactive mode. Agents running pflow see silence during execution then a post-hoc static summary, instead of a stream of events as nodes complete. This is the user's original motivation for investigating: "I wanted a streamed response when executing workflows, but for you running in Claude Code you can never see this kind of output."

## Solution

**One coherent output rule:**

- **Routing**: data → stdout, diagnostics → stderr. Always. Fix the Mode 3 bug in `_output_with_header`.
- **Progress**: streamed to stderr line-by-line as nodes complete, in default mode (TTY and non-TTY alike). Byte-identical in TTY and non-TTY for non-batch events (verified empirically — `click.echo` flushes per call, Python 3 stderr is line-buffered, `nl=False` partial-line + append works in both modes). Only batch progress `\r` updates need TTY-only gating because `\r` renders as garbage in non-TTY capture.
- **Summary**: one-line completion tag + supplementary info (batch errors, shell stderr warnings, cost, warnings). Delete the duplicate per-node listing from both CLI and MCP text paths.
- **`-p`/`--print` flag**: kept (Claude Code convention). Gates progress OFF when set (honors "minimal output" promise). Help text updated.
- **JSON output mode**: gates progress OFF (matches existing "JSON mode is machine-clean" invariant).
- **Dead scaffolding**: delete `OutputInterface`, `CliOutput`, `NullOutput`, `DisplayManager`. Runner takes `progress_callback: Optional[Callable]` directly.

## Design Decisions

1. **Keep `--print`/`-p`, don't rename to `--quiet`** — The flag matches Claude Code's established `-p` convention and is referenced in 38 markdown files. Rename would be churn without benefit. Semantics post-fix: "minimal output" rather than the stale "force non-interactive".

2. **`-p` mode suppresses the progress callback entirely** — Honors the "minimal output" promise. Without this gate, the always-on callback would stream progress lines to stderr in `-p` mode, breaking `pflow -p foo | jq` users' expectations.

3. **JSON output mode also suppresses the progress callback** — Matches the existing intent (logging suppressed to CRITICAL, trace file path suppressed). JSON mode consumers want clean stderr.

4. **CLI and MCP text paths both lose the per-node block** — `success_formatter._append_execution_steps` has an identical "Nodes executed (N):" implementation for MCP. Both paths simplify to the one-line tag for parity. Per-node detail remains available via trace files (`~/.pflow/debug/`) and `--report`.

5. **Port smart-handled tags (`[no matches]`, `[not found]`) to the live progress callback** — These tags help agents diagnose shell pipeline edge cases (grep returning nothing, `which` not finding a binary). They currently live in `_format_node_status_line` which is being deleted. Ported into `_handle_node_complete` with the same tag mapping.

6. **TTY detection is a RENDERING concern, not a ROUTING concern** — Routing (stdout vs stderr) is unified with zero TTY checks. The only remaining TTY check is inside `_handle_batch_progress` for the `\r`-based inline counter (cosmetic feature for humans watching; no-op in non-TTY capture). This is the architectural distinction that resolves the Mode 3 bug's root cause.

7. **Runner takes `progress_callback: Optional[Callable]` instead of `Optional[OutputInterface]`** — `OutputInterface`'s 7-method protocol existed to abstract "display", but the runner only ever called one method (`create_node_callback`). The minimal abstraction is a function. Deletes 4 files and ~260 lines of scaffolding.

8. **`test_cli_mcp_parity.py` is deleted, not rewritten** — The test's premise (CliOutput vs no-output produces same ExecutionResult) becomes vacuous after the refactor. The parity guarantee is now structural rather than testable.

## Dependencies

None. Standalone bug fix + cleanup.

Task 147 and Task 148 are reserved in other branches; no functional dependency between them and this task.

## Requirements

### Routing
- `pflow workflow.pflow.md` (captured non-TTY) MUST write declared workflow output to stdout
- `pflow workflow.pflow.md` (captured non-TTY) MUST NOT write declared workflow output to stderr
- `_output_with_header` MUST NOT inspect TTY state for routing decisions
- Routing behavior MUST be byte-identical between `--output-format text` default mode and the same mode run interactively (only rendering differs)

### Progress streaming
- Non-TTY consumers (agents, pipes, CI) MUST receive live per-node progress events on stderr as nodes complete, in default mode
- Progress emission MUST be suppressed when `-p`/`--print` is set
- Progress emission MUST be suppressed when `--output-format json` is set
- TTY users MUST see the same inline rendering as today (partial-line `node_id...` + completion append, live `\r`-based batch counter)
- Node completion lines in non-TTY mode MUST be terminated with a visible status marker (`✓`, `✗ Failed`, `↻ cached`, `⚠️`) so the subsequent output never concatenates onto the partial line

### Execution summary
- Completion tag MUST include: status glyph, duration, cache hit stats (when any), warning count (when any)
- `_display_execution_summary` MUST emit the `⤷ Stopped after 'X' (--only), N nodes skipped` summary line when `--only` is active (preserves context lost from the deleted per-node block)
- Batch error details, shell stderr warnings, LLM cost summary, warning diagnostics MUST still render when applicable
- The "Nodes executed (N):" per-node block MUST NOT appear in CLI text output
- The "Nodes executed (N):" per-node block MUST NOT appear in MCP text output (parity requirement)

### Smart-handled tags
- Shell nodes classified as safe non-errors (grep no-match, `which` not-found, etc.) MUST show a visible tag on the live progress line: `[no matches]`, `[not found]`, or the raw reason string as fallback
- `shell.py:200` comment MUST be updated to reference the new rendering location

### Flag semantics
- `-p`/`--print` flag name MUST be preserved (no rename)
- `--print` help text MUST accurately describe post-fix semantics (minimal output, not "force non-interactive")

### Scaffolding deletion
- `src/pflow/cli/cli_output.py` MUST be deleted
- `src/pflow/execution/display_manager.py` MUST be deleted
- `src/pflow/execution/null_output.py` MUST be deleted
- `src/pflow/execution/output_interface.py` MUST be deleted
- `WorkflowRunner.run()` MUST take `progress_callback: Optional[Callable]` directly
- `src/pflow/execution/__init__.py` MUST NOT export the deleted symbols
- MCP server path MUST continue to work without changes to `execution_service.py` (already passes no `output=` kwarg)

### Backward compatibility
- Nested sub-workflow progress propagation (via `__progress_callback__` in `_PROPAGATED_KEYS`) MUST continue to work
- Caching display (cache hits showing `↻ cached`) MUST continue to work
- `--only` execution mode MUST continue to work with accurate remaining/skipped counts
- `--verbose` semantics MUST be unchanged
- MCP server silent-execution contract MUST be preserved

## Implementation Notes

Full step-by-step implementation details (file paths, line numbers, exact before/after code, test inventory, doc updates) are in `implementation/implementation-plan.md`.

Key integration points the implementation touches:

- `src/pflow/cli/main.py` — the progress_callback gating callsite; the inline "Executing workflow (N nodes):" echo (replacing `DisplayManager.show_execution_start`)
- `src/pflow/cli/workflow_output.py` — `_output_with_header` mode merge, `_display_execution_summary` collapse, `output_controller` parameter removal
- `src/pflow/core/output_controller.py` — `create_progress_callback` TTY gate removal, `_handle_node_complete` failure terminator + smart-handled tags, `_handle_batch_progress` internal TTY guard, deletion of dead methods (`echo_progress`, `echo_result`, `should_show_prompts`, `_handle_workflow_start`)
- `src/pflow/execution/runner.py` — signature change from `output: Optional[OutputInterface]` to `progress_callback: Optional[Callable]`
- `src/pflow/execution/formatters/success_formatter.py` — `_append_execution_steps` simplification for MCP parity
- `src/pflow/runtime/engine/instrumentation.py` — pass `smart_handled`/`smart_handled_reason` through `call_completion_callback` to the progress callback

Critical subtlety: pytest captures stderr by default, so `sys.stderr.isatty()` returns False in tests. The new internal TTY guard inside `_handle_batch_progress` will cause 5 existing batch-progress tests to fall through silently. The implementation must add `patch.object(sys.stderr, 'isatty', return_value=True)` to those tests.

Empirical verification performed during planning:
1. Python 3 `sys.stderr` is line-buffered by default; `\n` triggers flush immediately, no explicit flushes needed.
2. `click.echo` flushes on every call, including with `nl=False`.
3. Partial-line + append pattern (`click.echo("  node_id...", nl=False)` then `click.echo(" ✓ 1.0s")`) produces identical final bytes in TTY and non-TTY capture.
4. `\r`-based overwrite pattern DOES NOT survive non-TTY capture cleanly — intermediate states concatenate into an ugly single line.

## Verification

### Automated
- `make test` — all existing tests pass after the test updates in the implementation plan
- `make check` — lint + type checks clean
- New regression tests in `tests/test_cli/test_workflow_output_handling.py`:
  - `test_workflow_data_goes_to_stdout_not_stderr_gh194` — data canary on stdout, not stderr, header on stderr
  - `test_failing_node_emits_terminator_in_live_progress` — no hanging `node_id...` lines before diagnostic block

### Manual scenarios (all must be verified before merge)
1. **#194 core fix**: `uv run pflow scratchpads/streaming-baseline/streaming-test.pflow.md 1>out 2>err` — stdout contains `all done`, stderr contains progress + header but not data
2. **TTY experience preserved**: interactive run shows inline progress, live `\r`-based batch counter, no duplicate "Nodes executed" block
3. **Non-TTY streaming**: agents see live per-node progress lines as nodes complete, not silence then static summary
4. **Failure termination**: a workflow with a failing node shows `fail_node... ✗ Failed` as a terminated line, not `fail_node...❌` concatenation
5. **Smart-handled tags**: `grep "nonexistent" /tmp/foo` in a workflow shows `search... ✓ 0.0s [no matches]`
6. **`--only` context**: running with `--only target_node` shows the `⤷ Stopped after 'target_node' (--only), N remaining nodes skipped` line
7. **`-p` silence**: `pflow -p workflow.pflow.md 2>err` — stderr is empty or near-empty (no progress, no tag, no header)
8. **JSON silence**: `pflow --output-format json workflow.pflow.md 2>err` — stderr is empty (JSON on stdout only)
9. **MCP server unaffected**: `pflow mcp serve` starts and executes workflows normally; no progress leaks onto MCP stdio transport

### Post-implementation greps
- `rg 'OutputInterface|CliOutput|NullOutput|DisplayManager' src/ tests/` — zero matches except documentation history
- `rg '_format_node_status_line|_get_status_indicator|_format_node_timing|_handle_workflow_start|echo_progress|echo_result|should_show_prompts' src/ tests/` — zero matches except the deleted files themselves (now gone)
- `rg 'Mode 3|everything on stderr|Non-interactive sends data to stderr' src/` — zero matches

## References

- **Implementation plan**: `.taskmaster/tasks/task_149/implementation/implementation-plan.md` — full step-by-step file edits, line numbers, before/after code, test inventory, doc updates
- **GitHub issue**: #194 — "Non-interactive mode routes all output to stderr — agents capturing stdout get nothing"
- **Scratchpad verification workflow**: `scratchpads/streaming-baseline/streaming-test.pflow.md` — used for manual testing (5-node workflow with batch)
- **Prior bug pattern**: `src/pflow/execution/formatters/CLAUDE.md` "Hard-Won: Update BOTH Call Sites" — Task 85 CLI/MCP parity regression that informed Decision 4 (simplify both paths, not just CLI)
- **Architectural debt audit**: `scratchpads/architectural-debt/compounding-issues.md` Issue 7 agent UX item #4 — where #194 was first flagged as critical
