# Fix GH #194 + Output Pipeline Consolidation

**Branch**: `fix/non-interactive-output-stderr`
**Worktree**: `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr`
**GitHub Issue**: #194 — "Non-interactive mode routes all output to stderr — agents capturing stdout get nothing"

---

## Context

### The bug (#194)

In `src/pflow/cli/workflow_output.py::_output_with_header` there is a "three-mode" output-routing system. Mode 3 (non-interactive, no `--print`) routes **workflow data** to stderr alongside diagnostics. An agent running `pflow workflow.pflow.md` via a Bash tool gets **0 bytes on stdout** — the declared workflow output is wedged into stderr between the header, the summary block, and the trace-path line. This breaks the standard Unix pattern `pflow foo.pflow.md | jq` for any non-TTY consumer (Claude Code, CI/CD, shell pipelines).

**Empirical proof** (captured during research):
```
$ pflow scratchpads/streaming-baseline/streaming-test.pflow.md 1>stdout.txt 2>stderr.txt
STDOUT: 0 bytes
STDERR: 463 bytes  (contains "all done" + summary + warnings + trace path)
```

### Why it's not just a small fix

Investigation revealed the routing bug sits on top of ~260 lines of dead scaffolding (`OutputInterface` protocol, `CliOutput`, `NullOutput`, `DisplayManager`) where:
- `NullOutput` has **zero imports anywhere** in `src/` or `tests/` (MCP server was supposed to use it but actually passes nothing, per `mcp_server/services/execution_service.py` lines 243–250, 512).
- `DisplayManager` has 4 methods; only 1 is live (`show_execution_start`) and it's called from exactly 1 site (`cli/main.py:310-311`).
- `CliOutput` has 7 methods; only 1 is reached through production code paths (`create_node_callback`). `show_result`/`show_success`/`show_warning`/`show_error` are all dead.
- `OutputInterface` protocol has 7 methods; runner calls exactly 1 on it (`create_node_callback` at `runner.py:417`).

The refactor also addresses the "duplicate summary" UX complaint: today's interactive terminal shows a live per-node progress block, then an **identical** static "Nodes executed (N):" block after completion. The static block exists purely as a fallback for non-interactive mode (which doesn't get the live progress because `create_progress_callback()` returns `None` when not interactive, per the TTY gate at `core/output_controller.py:186`). Removing the TTY gate makes the static block purely redundant.

### Intended outcome

One coherent output rule, implemented in one place, preserved identically for humans (TTY) and agents (non-TTY):

- **Routing**: data → stdout, diagnostics → stderr. Always. No mode system.
- **Progress**: streamed line-by-line as nodes complete, to stderr, when in default mode. Identical bytes in TTY and non-TTY except for one case: batch progress `\r` updates (which render as garbage in non-TTY capture — verified empirically) are TTY-only. **Suppressed entirely in `-p` mode and in JSON output mode** (see Pre-Implementation Decisions).
- **Summary**: one-line completion tag (`✓ Workflow completed in Xs`), plus batch errors / shell stderr warnings / cost / warnings diagnostics only when present. The duplicate "Nodes executed (N):" block is deleted **from both CLI and MCP paths** (parity).
- **`--print`/`-p`**: kept (Claude Code convention, established user idiom). Help text updated. Semantics unchanged from user perspective: minimal output, suppress header + summary + warnings + **progress lines**. After the fix, `-p` still delivers a clean stderr stream.
- **Dead scaffolding**: `OutputInterface`, `CliOutput`, `NullOutput`, `DisplayManager` deleted. `WorkflowRunner.run()` takes `progress_callback: Optional[Callable] = None` directly.

### Pre-Implementation Decisions

Four design decisions surfaced during plan review. All four are recorded here to remove ambiguity for the implementing agent.

**Decision 1: CLI/MCP per-node block parity — DELETE from both**

The plan originally deleted the "Nodes executed (N):" per-node block from CLI only. Review found that `src/pflow/execution/formatters/success_formatter.py::_append_execution_steps` (lines 283-319) contains the identical block rendered for MCP text output via `format_success_as_text()`. Leaving it in place would break CLI/MCP parity (a Task 85 regression category documented in `src/pflow/execution/formatters/CLAUDE.md` "Hard-Won: Update BOTH Call Sites").

**Action**: Also simplify `_append_execution_steps` in `success_formatter.py` to match the new CLI behavior — both paths emit just the one-line completion tag plus the `⤷ Stopped after 'X' (--only)` summary line (when applicable) and batch errors. See **Step 7b**.

**Decision 2: Progress callback in JSON output mode — SUPPRESSED**

Removing the TTY gate from `create_progress_callback` unconditionally would install the callback in JSON output mode too, streaming progress lines to stderr — contradicting the existing "JSON mode is machine-clean" invariant (logging suppressed to CRITICAL at `main.py:292-293`, trace file path suppressed at `main.py:90-91`).

**Action**: At the CLI runner call site (Step 9 Edit 3), pass `progress_callback=None` when `output_format == "json"`. JSON mode keeps its existing silent-stderr invariant.

**Decision 3: Progress callback in `-p`/`--print` mode — SUPPRESSED**

Today `-p` mode is silent on stderr because `print_flag=True` → `is_interactive()=False` → `create_progress_callback()` returns `None`. After removing the TTY gate, the callback would always be installed, breaking the "minimal output" promise of `-p` and contradicting the updated help text.

**Action**: At the CLI runner call site (Step 9 Edit 3), pass `progress_callback=None` when `print_flag` is set. Combines with Decision 2 into a single gate.

**Decision 4: Smart-handled tags — PORTED to live progress callback**

`_format_node_status_line` (being deleted in Step 7) renders `[no matches]`, `[not found]`, and custom `smart_handled_reason` tags for shell nodes that exit with a non-zero code but are classified as safe non-errors (grep no match, `which` not found, etc.). `src/pflow/nodes/shell/shell.py:200` has a verified comment pinning this contract:

> `IMPORTANT: When adding new patterns here, the reason string MUST contain either "no matches" or "not found" for proper tag display in CLI output. See src/pflow/cli/main.py _format_node_status_line() for the tag mapping.`

The MCP-side formatter (`_format_execution_step` at `success_formatter.py:410-436`) never had this feature — it only renders `[cached]`. So smart-handled tags are a CLI-only feature today, and they die with `_format_node_status_line` unless ported.

**Action**: Port the smart-handled tag display into `_handle_node_complete` (the live progress callback). Pass `smart_handled` + `smart_handled_reason` through the callback kwargs in `call_completion_callback` and render the tag on the completion line. See **Step 4b**. Also update the comment at `src/pflow/nodes/shell/shell.py:200` to point at the new location (`_handle_node_complete` in `output_controller.py`).

### Critical invariants (what must NOT break)

1. **TTY user experience preserved verbatim**: inline `stage_one... ✓ 1.0s` rendering via `nl=False` + append, live `\r`-based batch counter `1/5 → 2/5 → …`, colored indicators, nested workflow indentation — all unchanged from current behavior.
2. **Agent streaming becomes live**: agents get the same progress lines (minus the `\r` batch counter intermediate updates) streamed as each node completes, rather than a post-hoc static summary.
3. **Data on stdout is the new invariant** — the actual fix for #194.
4. **`__progress_callback__` shared-store propagation to nested workflows** continues to work via `workflow_executor.py:_PROPAGATED_KEYS` at lines 99-107. No changes there.
5. **Python stderr line-buffering guarantees streaming** — verified empirically (click.echo flushes every call; non-TTY capture sees each line as it's written). No explicit `sys.stderr.flush()` needed.

---

## Summary of changes (at a glance)

| # | Change | Files | Net LOC |
|---|---|---|---|
| 1 | Fix `_output_with_header`: merge 3 modes → 1 rule (data→stdout, header→stderr) | `cli/workflow_output.py` | ~−20 |
| 2 | Remove `output_controller` parameter threading from 4 functions in workflow_output.py | `cli/workflow_output.py`, `cli/main.py` | ~−15 |
| 3 | Remove TTY gate from `create_progress_callback` → always returns a callable | `core/output_controller.py` | ~−2 |
| 3b | Update `_handle_node_complete`: add `✗ Failed` terminator for non-batch errors + port smart-handled tag rendering (Decision 4) | `core/output_controller.py`, `runtime/engine/instrumentation.py` | ~+35 |
| 4 | Add internal TTY guard inside `_handle_batch_progress` | `core/output_controller.py` | ~+3 |
| 5 | Delete `_handle_workflow_start` + `workflow_start` event dispatch (dead — no emitter) | `core/output_controller.py` | ~−10 |
| 6 | Delete `echo_progress`, `echo_result`, `should_show_prompts` (dead code) | `core/output_controller.py` | ~−30 |
| 7 | Collapse `_display_execution_summary`: delete "Nodes executed (N):" loop, preserve `⤷ Stopped after` line for `--only` | `cli/workflow_output.py` | ~−25 |
| 7b | **(new)** MCP parity: simplify `_append_execution_steps` in `success_formatter.py` to match CLI (Decision 1) | `execution/formatters/success_formatter.py` | ~−50 |
| 8 | Delete dead helpers: `_format_node_status_line`, `_get_status_indicator`, `_format_node_timing` | `cli/workflow_output.py` | ~−85 |
| 9 | Delete `DisplayManager` class + file, inline execution-start echo **gated on progress_enabled** (Decisions 2+3) | `execution/display_manager.py` + `execution/__init__.py` + `cli/main.py` | ~−85 |
| 10 | Delete `CliOutput` class + file, pass `progress_callback` directly **gated on `-p` and JSON mode** | `cli/cli_output.py` + `cli/main.py` | ~−80 |
| 11 | Delete `NullOutput` class + file (zero imports anywhere) | `execution/null_output.py` + `execution/__init__.py` | ~−40 |
| 12 | Delete `OutputInterface` protocol + file | `execution/output_interface.py` + `execution/__init__.py` | ~−75 |
| 13 | `WorkflowRunner.run()` signature: `output: Optional[OutputInterface]` → `progress_callback: Optional[Callable]` | `execution/runner.py` | ~0 (rename) |
| 14 | Update `--print` help text (no rename — flag kept) | `cli/main.py` | ~0 |
| 15 | Test: add #194 regression test | `tests/test_cli/test_workflow_output_handling.py` | +45 |
| 15b | **(new)** Test: add failure-path line-termination regression test | `tests/test_cli/test_workflow_output_handling.py` | +55 |
| 16 | Test: update `test_output_controller.py` tests #10, #11, #29, #30–#36 (expanded) | `tests/test_core/test_output_controller.py` | ~+30 |
| 17 | Test: **delete** `test_cli_mcp_parity.py` (vacuous after refactor) | `tests/test_integration/test_cli_mcp_parity.py` | −66 |
| 18 | Test: delete orphaned tests for `_format_node_status_line`, `_handle_workflow_start`, `echo_progress/echo_result/should_show_prompts` (12 tests total across 2 files) | `tests/test_cli/test_shell_stderr_warnings.py`, `tests/test_core/test_output_controller.py` | ~−120 |
| 19 | Test: update tests in `test_success_formatter.py` that assert on deleted per-node block | `tests/test_execution/formatters/test_success_formatter.py` | ~−40 (case-by-case) |
| 20 | Docs: update `cli/CLAUDE.md`, `execution/CLAUDE.md`, `core/CLAUDE.md`, `mcp_server/CLAUDE.md`, `docs/reference/cli/index.mdx`, `architecture/features/shell-pipes.md`, `cli/resources/cli-basic-usage.md` | various | ~+50 (edits) |
| 21 | Update `shell.py:200` comment to point at new smart-handled location (`_handle_node_complete`) | `nodes/shell/shell.py` | ~3 |
| 22 | Update stale mentions of `NullOutput` in 2 files | `execution/runner.py:66` docstring, `runtime/workflow_executor.py:80` comment | ~2 |

**Net production code**: approximately −470 lines (slightly larger deletion than original estimate due to `_append_execution_steps` simplification and the dead-code methods in `OutputController`). **Final code is strictly smaller than today's.**

---

## Files affected (complete list)

### Delete (5 files)
- `src/pflow/cli/cli_output.py` (73 lines)
- `src/pflow/execution/display_manager.py` (77 lines)
- `src/pflow/execution/null_output.py` (38 lines)
- `src/pflow/execution/output_interface.py` (72 lines)
- `tests/test_integration/test_cli_mcp_parity.py` (66 lines) — or rewrite; see §Test Strategy

### Modify (production)
- `src/pflow/cli/main.py`
- `src/pflow/cli/workflow_output.py`
- `src/pflow/core/output_controller.py`
- `src/pflow/execution/__init__.py`
- `src/pflow/execution/runner.py`
- `src/pflow/execution/formatters/success_formatter.py` **(NEW — MCP parity per Decision 1)**
- `src/pflow/runtime/engine/instrumentation.py` **(NEW — pass smart_handled through callback per Decision 4)**
- `src/pflow/runtime/workflow_executor.py` (comment only at line 80)
- `src/pflow/nodes/shell/shell.py` **(NEW — update line 200 comment per Decision 4)**

### Modify (tests)
- `tests/test_core/test_output_controller.py`
- `tests/test_cli/test_workflow_output_handling.py` (add 2 regression tests)
- `tests/test_cli/test_shell_stderr_warnings.py` (delete tests for deleted helpers)
- `tests/test_execution/formatters/test_success_formatter.py` **(NEW — tests asserting on deleted per-node block)**

### Modify (docs)
- `src/pflow/cli/CLAUDE.md`
- `src/pflow/execution/CLAUDE.md`
- `src/pflow/core/CLAUDE.md`
- `src/pflow/mcp_server/CLAUDE.md`
- `docs/reference/cli/index.mdx`
- `architecture/features/shell-pipes.md`
- `src/pflow/cli/resources/cli-basic-usage.md`

### NOT affected (verified)
- `README.md` — only has `-p` pipe examples, still valid (flag kept)
- `docs/guides/using-pflow.mdx` — only has `-p` pipe example, still valid
- `docs/changelog.mdx` — historical only; will need a new v0.12.0 entry when released, not part of this change
- Agent instruction files (`cli-agent-instructions.md`, `mcp-agent-instructions.md`, `mcp-sandbox-agent-instructions.md`) — `${node.stdout}`/`${node.stderr}` are template variables, unrelated to the output routing bug
- `src/pflow/mcp_server/services/execution_service.py` — already passes no `output` kwarg (calls `runner.run(resolved, params, config, workflow_manager=..., workflow_name=...)` at lines 243–250). The signature change from `output=` to `progress_callback=` doesn't touch this file.
- All files in `src/pflow/nodes/` — no node reads `__progress_callback__` directly (verified)
- `src/pflow/runtime/engine/instrumentation.py` — uses `shared.get("__progress_callback__")` + `callable()` check, works with always-present callback
- `src/pflow/runtime/engine/batch_executor.py` — same pattern
- `src/pflow/runtime/workflow_executor.py:_PROPAGATED_KEYS` (lines 99-107) — already propagates `__progress_callback__`, works unchanged

---

## Step-by-step implementation

Implementation order is chosen to keep each step individually test-passing. If something breaks, the test failure isolates the step.

### Step 1 — Fix `_output_with_header` (the actual #194 fix)

**File**: `src/pflow/cli/workflow_output.py`
**Function**: `_output_with_header` (currently lines 40-86)

**Current code** (quoted verbatim from the file):
```python
def _output_with_header(value: Any, print_flag: bool, output_controller: Any, description: str | None = None) -> None:
    """Output value with appropriate header and stream routing based on execution mode.

    Three execution modes with different output strategies:

    1. --print mode (print_flag=True):
       - Use case: Piping output to other commands
       - Behavior: ONLY raw output to stdout, no header, no summary
       - Example: pflow --print my-workflow | jq

    2. Interactive terminal (is_interactive()=True):
       - Use case: Normal terminal usage with TTY
       - Behavior: Unix convention - header/summary to stderr, data to stdout
       - Rationale: Separates progress info from pipeable data
       - Example: pflow my-workflow (in terminal)

    3. Non-interactive (is_interactive()=False, print_flag=False):
       - Use case: Claude Code, CI/CD, non-TTY environments
       - Behavior: Everything to stderr for correct ordering
       - Rationale: Tools that capture streams separately may show stdout before stderr,
                    causing output to appear before summary. Keeping everything on stderr
                    preserves the intended order: summary → header → output
       - Example: pflow my-workflow (in Claude Code)

    Args:
        value: The output value to display
        print_flag: Whether --print flag is set
        output_controller: OutputController for interactive detection
        description: Optional description from workflow output declaration
    """
    # Build header with optional description
    header = f"\nWorkflow output ({description}):\n" if description else "\nWorkflow output:\n"

    if print_flag:
        # Mode 1: --print - raw output only (no header)
        safe_output(value)
    elif output_controller and output_controller.is_interactive():
        # Mode 2: Interactive - Unix convention
        click.echo(header, err=True)
        safe_output(value)
    else:
        # Mode 3: Non-interactive - everything on stderr
        click.echo(header, err=True)
        if isinstance(value, str):
            click.echo(value, err=True)
        else:
            click.echo(str(value), err=True)
```

**Target code**:
```python
def _output_with_header(value: Any, print_flag: bool, description: str | None = None) -> None:
    """Output value with Unix-convention routing.

    - `--print` mode (print_flag=True): data to stdout, no header, no summary.
      Use case: clean piping into other commands (`pflow -p foo | jq`).
    - Default mode: header to stderr, data to stdout. Works identically in
      TTY and non-TTY (Claude Code, CI/CD, pipes). This is standard Unix
      convention and the fix for GH #194.

    Args:
        value: The output value to display.
        print_flag: Whether --print flag is set (suppresses header).
        description: Optional description from workflow output declaration.
    """
    if print_flag:
        safe_output(value)
        return

    header = f"\nWorkflow output ({description}):\n" if description else "\nWorkflow output:\n"
    click.echo(header, err=True)
    safe_output(value)
```

**Why this is the fix**: The old Mode 3 branch (lines 80-86) wrote `value` to stderr via `click.echo(..., err=True)`. The new code calls `safe_output(value)` which writes to stdout (via `click.echo(value)` without `err=True`) for all non-`--print` cases. This is the entire behavioral change for #194.

**Also note**: The old Mode 3 bypassed `safe_output` and therefore also bypassed `BrokenPipeError` handling. The new code routes through `safe_output` in all non-`--print` cases, which means non-TTY consumers also get clean pipe-termination handling. Bonus fix.

### Step 2 — Remove `output_controller` parameter threading from workflow_output.py

The `output_controller` parameter is used only by `_output_with_header`'s deleted Mode 3 branch. After Step 1, it's dead weight threaded through 4 functions.

**File**: `src/pflow/cli/workflow_output.py`

**Changes**:

1. **`_output_with_header`** signature (already done in Step 1): remove `output_controller: Any` parameter. New signature: `def _output_with_header(value, print_flag, description=None)`.

2. **`_handle_text_output`** (lines 89-100): remove `output_controller: Any = None` from signature. Update internal calls to `_output_with_header` at lines 145, 182 (remove the `output_controller` arg). Update the call to `_try_declared_outputs` at line 161 (remove `output_controller` arg).

3. **`_try_declared_outputs`** (lines 214-250): remove `output_controller: Any = None` from signature. Update internal calls to `_emit_declared_output` at lines 239, 246 (remove `output_controller` arg).

4. **`_emit_declared_output`** (lines 188-211): remove `output_controller: Any = None` from signature. Update internal call to `_output_with_header` at line 209 (remove `output_controller` arg).

5. **`_handle_workflow_output`** (lines 699-753): remove `output_controller: Any = None` from signature. Update internal call to `_handle_text_output` at line 750 (remove `output_controller=output_controller` kwarg).

**File**: `src/pflow/cli/main.py`

**Change**: Inside `_handle_workflow_success`, the call to `_handle_workflow_output` at lines 153-166 currently passes `output_controller=ctx.obj.get("output_controller")` at line 163. **Remove that kwarg entirely.** Do not remove any other kwargs.

### Step 3 — Remove TTY gate from `create_progress_callback`

**File**: `src/pflow/core/output_controller.py`
**Function**: `create_progress_callback` (lines 180-245)

**Current code** (lines 180-188):
```python
def create_progress_callback(self) -> Optional[Callable]:
    """Create progress callback for workflow execution.

    Returns:
        Callback function if interactive, None if non-interactive
    """
    if not self.is_interactive():
        return None

    def progress_callback(
```

**Target code**:
```python
def create_progress_callback(self) -> Callable:
    """Create progress callback for workflow execution.

    Always returns a callable. The returned callback streams progress events
    to stderr via append-only `click.echo` writes that work identically in
    TTY and non-TTY (verified: Python 3 sys.stderr is line-buffered and
    click.echo flushes on every call). The one exception is batch progress
    `\\r`-based inline counter updates, which are gated inside
    `_handle_batch_progress` via `sys.stderr.isatty()` because `\\r` renders
    as garbage in non-TTY capture.

    Returns:
        Callback function (never None).
    """
    def progress_callback(
```

**Net diff**: Delete the `if not self.is_interactive(): return None` block (lines 186-187). Update return type from `Optional[Callable]` to `Callable`. Update docstring.

### Step 3b — Update `_handle_node_complete` for failure terminator + smart-handled tags

**File**: `src/pflow/core/output_controller.py`
**Function**: `_handle_node_complete` (currently lines 106-155)

This step addresses two review findings:
- **Finding 5 (non-batch failure hangs)**: today the non-batch error branch silently returns without emitting a newline, leaving the `node_id...` partial line (from `_handle_node_start`) hanging. After deleting the static summary, this creates ugly concatenation with the subsequent diagnostic block.
- **Decision 4 (smart-handled tags)**: port `[no matches]`, `[not found]`, `smart_handled_reason` tag rendering from the deleted `_format_node_status_line`.

**Current code** (quoted verbatim):
```python
def _handle_node_complete(
    self,
    duration_ms: Optional[float],
    error_message: Optional[str],
    ignore_errors: bool,
    is_error: bool,
    is_batch: bool = False,
    batch_total: Optional[int] = None,
    batch_success_count: Optional[int] = None,
) -> None:
    """Handle node_complete event display."""
    if is_error:
        if is_batch:
            click.echo(click.style(" FAILED", fg="red"), err=True)
        # For non-batch errors, shell node already logged - return to avoid double output
        return

    if is_batch:
        if duration_ms is not None:
            timing_text = click.style(f" {duration_ms / 1000:.1f}s", fg="green")
            click.echo(timing_text, err=True)
        else:
            click.echo("", err=True)
        return

    if error_message and ignore_errors:
        warning_text = click.style(f" ⚠️  {error_message} but continuing", fg="yellow")
        if duration_ms is not None:
            success_text = click.style(f" | ✓ {duration_ms / 1000:.1f}s", fg="green")
            click.echo(f"{warning_text}{success_text}", err=True)
        else:
            click.echo(warning_text, err=True)
    elif duration_ms is not None:
        click.echo(click.style(f" ✓ {duration_ms / 1000:.1f}s", fg="green"), err=True)
    else:
        click.echo(click.style(" ✓", fg="green"), err=True)
```

**Target code**:
```python
def _handle_node_complete(
    self,
    duration_ms: Optional[float],
    error_message: Optional[str],
    ignore_errors: bool,
    is_error: bool,
    is_batch: bool = False,
    batch_total: Optional[int] = None,
    batch_success_count: Optional[int] = None,
    smart_handled: bool = False,
    smart_handled_reason: Optional[str] = None,
) -> None:
    """Handle node_complete event display.

    Completes the partial line opened by _handle_node_start with a terminator:
    success (✓), failure (✗), warning (⚠️), or batch FAILED. All branches
    write a newline so the subsequent output (e.g. a diagnostic block on
    failure) starts on its own line. Non-batch errors used to silently return
    — that caused hanging lines when the static summary was deleted.

    Args:
        duration_ms: Execution duration in milliseconds
        error_message: Error message for failed nodes
        ignore_errors: Whether errors are being ignored
        is_error: Whether this is a fatal error
        is_batch: Whether this is a batch node completion
        batch_total: Total items in batch (for batch nodes)
        batch_success_count: Number of successful items (for batch nodes)
        smart_handled: Whether shell node classified exit as safe non-error
        smart_handled_reason: Reason for smart handling (e.g. "no matches")
    """
    if is_error:
        if is_batch:
            click.echo(click.style(" FAILED", fg="red"), err=True)
        else:
            # Terminate the hanging "node_id..." line with a visible failure
            # marker so the diagnostic block that follows starts cleanly.
            click.echo(click.style(" ✗ Failed", fg="red"), err=True)
        return

    if is_batch:
        if duration_ms is not None:
            timing_text = click.style(f" {duration_ms / 1000:.1f}s", fg="green")
            click.echo(timing_text, err=True)
        else:
            click.echo("", err=True)
        return

    # Build smart-handled tag suffix (ported from _format_node_status_line).
    # When shell.py classifies a non-zero exit as safe (grep no-match, which
    # not-found, etc.), shell.py sets smart_handled=True and provides a reason
    # string. The tag mapping matches the shell.py:200 contract.
    tag_suffix = ""
    if smart_handled:
        reason = smart_handled_reason or ""
        if "no matches" in reason:
            tag_suffix = click.style(" [no matches]", fg="yellow")
        elif "not found" in reason:
            tag_suffix = click.style(" [not found]", fg="yellow")
        elif reason:
            # Unknown pattern — show raw reason so agents can diagnose.
            tag_suffix = click.style(f" [{reason}]", fg="yellow")

    if error_message and ignore_errors:
        warning_text = click.style(f" ⚠️  {error_message} but continuing", fg="yellow")
        if duration_ms is not None:
            success_text = click.style(f" | ✓ {duration_ms / 1000:.1f}s", fg="green")
            click.echo(f"{warning_text}{success_text}{tag_suffix}", err=True)
        else:
            click.echo(f"{warning_text}{tag_suffix}", err=True)
    elif duration_ms is not None:
        click.echo(click.style(f" ✓ {duration_ms / 1000:.1f}s", fg="green") + tag_suffix, err=True)
    else:
        click.echo(click.style(" ✓", fg="green") + tag_suffix, err=True)
```

**File**: `src/pflow/runtime/engine/instrumentation.py`
**Function**: `call_completion_callback` (currently lines 363-409)

**Edit**: Add `smart_handled` detection and pass it through to the callback.

**Verified**: shell.py lines 688-689 write `shared["smart_handled"] = True` and `shared["smart_handled_reason"] = reason`. Because shell node runs inside a `NamespacedSharedStore`, writes to `shared["key"]` are redirected to `parent_store[node_id]["key"]`. So at the root-level shared dict read by `call_completion_callback`, these values appear at `shared[node_id]["smart_handled"]` and `shared[node_id]["smart_handled_reason"]`. This is the same access pattern already used by the batch detection block (`shared.get(node_id, {}).get("batch_metadata")`).

Add these lines inside `call_completion_callback` after the batch detection block (around current line 395):

```python
    # Smart-handled detection (for live progress tag display)
    smart_handled = False
    smart_handled_reason = None
    if isinstance(node_output, dict):
        smart_handled = bool(node_output.get("smart_handled", False))
        smart_handled_reason = node_output.get("smart_handled_reason")
```

And pass them in the callback invocation at the bottom:
```python
    with contextlib.suppress(Exception):
        callback(
            node_id,
            "node_complete",
            duration_ms,
            depth,
            error_message=error_msg,
            ignore_errors=ignore_errors,
            is_error=action_str.startswith("error"),
            is_batch=is_batch,
            batch_total=batch_total,
            batch_success_count=batch_success_count,
            smart_handled=smart_handled,
            smart_handled_reason=smart_handled_reason,
        )
```

**File**: `src/pflow/core/output_controller.py`
**Function**: `create_progress_callback` — add the two new kwargs to the inner `progress_callback` closure signature and pass them through to `_handle_node_complete`:

```python
def progress_callback(
    node_id: str,
    event: str,
    duration_ms: Optional[float] = None,
    depth: int = 0,
    error_message: Optional[str] = None,
    ignore_errors: bool = False,
    is_error: bool = False,
    batch_current: Optional[int] = None,
    batch_total: Optional[int] = None,
    batch_success: Optional[bool] = None,
    is_batch: bool = False,
    batch_success_count: Optional[int] = None,
    smart_handled: bool = False,
    smart_handled_reason: Optional[str] = None,
) -> None:
    ...
    elif event == "node_complete":
        self._handle_node_complete(
            duration_ms,
            error_message,
            ignore_errors,
            is_error,
            is_batch=is_batch,
            batch_total=batch_total,
            batch_success_count=batch_success_count,
            smart_handled=smart_handled,
            smart_handled_reason=smart_handled_reason,
        )
```

### Step 4 — Add internal TTY guard to `_handle_batch_progress`

**File**: `src/pflow/core/output_controller.py`
**Function**: `_handle_batch_progress` (currently lines 82-104)

**Current code**:
```python
def _handle_batch_progress(
    self,
    node_id: str,
    indent: str,
    batch_current: int,
    batch_total: int,
    batch_success: bool,
) -> None:
    """Handle batch_progress event - update line in place.

    Uses carriage return to overwrite the current line with updated progress.
    Shows per-item success/failure status.

    Args:
        node_id: The node identifier
        indent: Indentation string based on depth
        batch_current: Number of items completed so far
        batch_total: Total number of items to process
        batch_success: Whether the just-completed item succeeded
    """
    status = click.style("✓", fg="green") if batch_success else click.style("✗", fg="red")
    # Use \r to return to line start and overwrite
    click.echo(f"\r{indent}  {node_id}... {batch_current}/{batch_total} {status}", err=True, nl=False)
```

**Target code**: Add `import sys` to the top of the file if not present (it already is — verified line 3). Add one TTY guard at the start of the method body:

```python
def _handle_batch_progress(
    self,
    node_id: str,
    indent: str,
    batch_current: int,
    batch_total: int,
    batch_success: bool,
) -> None:
    """Handle batch_progress event - update line in place (TTY only).

    In TTY, uses carriage return to overwrite the current line with updated
    progress. In non-TTY capture, `\\r` would render as garbage (verified
    empirically: captured output shows concatenated intermediate states), so
    this method is a no-op when stderr is not a TTY. The final batch count
    appears in the subsequent `_handle_node_complete` batch branch.

    Args:
        node_id: The node identifier
        indent: Indentation string based on depth
        batch_current: Number of items completed so far
        batch_total: Total number of items to process
        batch_success: Whether the just-completed item succeeded
    """
    if not sys.stderr.isatty():
        return  # \r renders as garbage in non-TTY; skip intermediate updates
    status = click.style("✓", fg="green") if batch_success else click.style("✗", fg="red")
    click.echo(f"\r{indent}  {node_id}... {batch_current}/{batch_total} {status}", err=True, nl=False)
```

**Critical note for tests**: `pytest` replaces `sys.stderr` with a non-TTY capture stream by default. This means the existing tests `test_batch_progress_updates_line_in_place`, `test_batch_progress_shows_success_indicator`, `test_batch_progress_shows_failure_indicator`, `test_batch_progress_respects_depth_indentation`, `test_batch_complete_workflow_flow` in `tests/test_core/test_output_controller.py` will break — they assert on output that the new guard short-circuits. See Step 12 for the fix (mock `sys.stderr.isatty` to return True in those tests).

### Step 5 — Delete `_handle_workflow_start` and the `workflow_start` dispatch branch

**File**: `src/pflow/core/output_controller.py`

**Delete**: the entire `_handle_workflow_start` method (lines 171-178). Rationale: verified dead code — no production code in `src/pflow/runtime/` or elsewhere emits a `workflow_start` event via the progress callback. The metrics layer has its own `MetricsCollector.record_workflow_start()` which is unrelated.

**Also delete**: the `elif event == "workflow_start":` dispatch branch inside `create_progress_callback`'s nested `progress_callback` function (currently lines 242-243):
```python
elif event == "workflow_start":
    self._handle_workflow_start(node_id, indent)
```

**Also delete**: `echo_progress`, `echo_result`, `should_show_prompts` methods (currently lines 247-272). All three are dead code — verified zero production callers anywhere in `src/`. Only `tests/test_core/test_output_controller.py` calls them, and those 5 tests must also be deleted (see Step 15 expanded test list).

**Also delete** (tests for the `workflow_start` event, now dead):
- Test `test_progress_callback_handles_events` (line 100) — partial update: remove the `callback("5", "workflow_start")` portion and its assertion at lines 118-119, keep the node_start and node_complete portions.
- Test `test_complete_workflow_execution_flow` (line 303) — partial update: remove the `callback("3", "workflow_start")` portion at line 311, keep the rest.

See Step 15 for the full expanded test inventory.

After these deletions, `OutputController` has this external surface:
- `__init__(print_flag, output_format, stdin_tty=None, stdout_tty=None)`
- `is_interactive()` — still used by... nothing after this refactor. Consider also deleting (see Step 6).
- `create_progress_callback()` — used by `main.py` (new direct call)
- `print_flag`, `output_format` — attributes, used by `main.py::_echo_trace`

### Step 6 — Decide fate of `is_interactive()`

**Analysis**: After Steps 1-5, `OutputController.is_interactive()` has these remaining external callers:
- `src/pflow/cli/workflow_output.py:76` — DELETED in Step 1 (was the Mode 3 gate)
- `src/pflow/cli/cli_output.py:42` + `cli_output.py:72` — DELETED in Step 10 (file gone)
- `src/pflow/cli/mcp_sync.py:144` — **still exists**, uses it to gate MCP discovery progress display

**Decision**: **Keep `is_interactive()`**. One live caller remains (`mcp_sync.py`). Deleting it would require refactoring `mcp_sync.py` which is out of scope for this change. Leave `is_interactive()` in place.

However, `is_interactive()` and its 5 TTY/print_flag/json rules are no longer the arbiter of progress display. Update its docstring (currently lines 56-71) to reflect its narrower use case — only for MCP discovery progress display in `cli/mcp_sync.py`.

### Step 7 — Collapse `_display_execution_summary` and delete dead formatters

**File**: `src/pflow/cli/workflow_output.py`
**Function**: `_display_execution_summary` (currently lines 520-609)

**Current body**: See agent report — it has the full 90-line implementation. Key section to delete (approximately lines 574-594):
```python
    # Show per-node execution details
    if steps:
        only_node = execution.get("only_node")
        nodes_skipped = execution.get("nodes_skipped", 0)

        # When --only is active, show only executed steps with N/M format
        if only_node:
            display_steps = [s for s in steps if s["status"] != "not_executed"]
            click.echo(f"Nodes executed ({len(display_steps)}/{total_nodes}):", err=True)
        else:
            display_steps = steps
            click.echo(f"Nodes executed ({total_nodes}):", err=True)

        for step in display_steps:
            status_line = _format_node_status_line(step)
            click.echo(status_line, err=True)

        # --only summary line
        if only_node and nodes_skipped > 0:
            noun = "node" if nodes_skipped == 1 else "nodes"
            click.echo(f"  ⤷ Stopped after '{only_node}' (--only), {nodes_skipped} remaining {noun} skipped", err=True)
```

**Target body** (new function):
```python
def _display_execution_summary(
    formatted_result: dict[str, Any],
    verbose: bool,
    warning_diagnostics: list[Diagnostic] | None = None,
) -> None:
    """Display one-line execution summary with supplementary info.

    Emits (in order, to stderr):
    1. Workflow action line ("{name} was executed", skipped for unsaved)
    2. One-line completion tag (✓/⚠️/❌ + duration + cache stats + warning count)
    3. Batch error details (only if any batch nodes had item failures)
    4. Shell stderr warnings (only if shell nodes wrote to stderr with exit 0)
    5. LLM cost summary (only if total cost > 0)
    6. Warning diagnostics (only if any)

    The per-node listing (`Nodes executed (N):` block) was removed because
    it duplicates information already streamed live via the progress callback
    during execution. Live progress is now always shown (TTY and non-TTY)
    since GH #194 was fixed.

    Args:
        formatted_result: Formatted result from format_execution_success()
        verbose: Currently unused, kept for call-site compatibility
        warning_diagnostics: Warning Diagnostics to render (passed directly, not from dict)
    """
    duration_ms = formatted_result.get("duration_ms")
    total_cost = formatted_result.get("total_cost_usd")

    execution = formatted_result.get("execution", {})
    steps = execution.get("steps", []) if execution else []

    workflow_metadata = formatted_result.get("workflow", {})
    workflow_name = workflow_metadata.get("name", "workflow")
    workflow_action = workflow_metadata.get("action", "executed")

    # 1. Workflow action
    _display_workflow_action(workflow_name, workflow_action)

    # 2. One-line completion tag
    if duration_ms is not None:
        duration_s = duration_ms / 1000.0
        status = formatted_result.get("status", "success")
        has_stderr_warnings = any(step.get("has_stderr") for step in steps)
        cache_hits = execution.get("cache_hits", 0)
        completed_count = execution.get("nodes_executed", 0)
        warning_count = len(formatted_result.get("warnings", []))
        _display_workflow_completion_status(
            duration_s,
            status,
            has_stderr_warnings,
            cache_hits=cache_hits,
            nodes_executed=completed_count,
            warning_count=warning_count,
        )

    # 3. --only summary line (preserves finding #6 from review)
    #    The per-node block (which used to carry this) is deleted, but the
    #    --only context is critical for agents debugging iterative workflows.
    execution = formatted_result.get("execution", {})
    only_node = execution.get("only_node")
    nodes_skipped = execution.get("nodes_skipped", 0)
    if only_node and nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        click.echo(
            f"  ⤷ Stopped after '{only_node}' (--only), {nodes_skipped} remaining {noun} skipped",
            err=True,
        )

    # 4. Batch error details (only when batch nodes had failures)
    if steps:
        _display_batch_errors(steps)
        # 5. Shell stderr warnings (only for shell nodes with stderr + exit 0)
        _display_stderr_warnings(steps)

    # 6. LLM cost (only if > 0)
    _display_cost_summary(total_cost, formatted_result)

    # 6. Warnings
    if warning_diagnostics:
        click.echo("", err=True)
        click.echo("⚠️ Warnings:", err=True)
        for warning in warning_diagnostics:
            click.echo(format_diagnostic(warning), err=True)
```

**Delete** (now-unreachable helpers in same file):
- `_format_node_status_line` (lines 309-367, 59 lines) — only caller was the deleted per-node loop. Note: this function is currently imported by `tests/test_cli/test_shell_stderr_warnings.py:14`. See Step 14 for test update.
- `_get_status_indicator` (lines 280-294, 15 lines) — only caller was `_format_node_status_line`. No test imports.
- `_format_node_timing` (lines 297-306, 10 lines) — only caller was `_format_node_status_line`. No test imports.

**Keep** (still called from the collapsed summary):
- `_display_workflow_action` (lines 430-442)
- `_display_workflow_completion_status` (lines 482-517)
- `_display_batch_errors` (lines 377-398)
- `_display_stderr_warnings` (lines 401-427) — still called, plus still imported by test file
- `_display_cost_summary` (lines 445-479) — still called, plus still imported by `test_direct_execution_helpers.py:7`
- `_truncate_error_message` (lines 370-374) — still called by `_display_batch_errors`

### Step 7b — MCP parity: simplify `success_formatter._append_execution_steps`

**File**: `src/pflow/execution/formatters/success_formatter.py`
**Function**: `_append_execution_steps` (currently lines 283-319)

This step enforces **Decision 1 (CLI/MCP parity)**. The MCP text output path renders the same "Nodes executed (N):" per-node block that Step 7 deletes from CLI. Leaving MCP unchanged would break parity.

**Current code** (quoted verbatim):
```python
def _append_execution_steps(lines: list[str], execution: dict[str, Any]) -> None:
    """Append execution step details to lines list.

    For batch nodes with errors, also appends a batch errors section
    showing failed item indices and error messages.
    When --only is active, filters out not_executed steps and shows a summary line.
    """
    if not execution or "steps" not in execution:
        return

    steps = execution["steps"]
    only_node_val = execution.get("only_node")
    nodes_skipped = execution.get("nodes_skipped", 0)
    nodes_total = execution.get("nodes_total", len(steps))

    # When --only is active, show only executed steps
    if only_node_val:
        display_steps = [s for s in steps if s["status"] != "not_executed"]
        lines.append(f"Nodes executed ({len(display_steps)}/{nodes_total}):")
    else:
        display_steps = steps
        nodes_executed = execution.get("nodes_executed", 0)
        lines.append(f"Nodes executed ({nodes_executed}):")

    for step in display_steps:
        formatted_step = _format_execution_step(step)
        lines.append(formatted_step)

    # --only summary line
    if only_node_val and nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        lines.append(f"  ⤷ Stopped after '{only_node_val}' (--only), {nodes_skipped} remaining {noun} skipped")

    # Add batch errors section if any batch nodes had failures
    batch_error_lines = _format_batch_errors_section(steps)
    if batch_error_lines:
        lines.extend(batch_error_lines)
```

**Target code**:
```python
def _append_execution_steps(lines: list[str], execution: dict[str, Any]) -> None:
    """Append supplementary execution details: --only summary line + batch errors.

    After the GH #194 refactor, both CLI and MCP text paths drop the per-node
    "Nodes executed (N):" block. Live progress (in CLI) or trace files (for
    MCP consumers) carry per-node detail. This function now only emits info
    that isn't available elsewhere: the --only summary line and batch error
    details.
    """
    if not execution or "steps" not in execution:
        return

    steps = execution["steps"]
    only_node_val = execution.get("only_node")
    nodes_skipped = execution.get("nodes_skipped", 0)

    # --only summary line (preserves context for agents debugging partial runs)
    if only_node_val and nodes_skipped > 0:
        noun = "node" if nodes_skipped == 1 else "nodes"
        lines.append(f"  ⤷ Stopped after '{only_node_val}' (--only), {nodes_skipped} remaining {noun} skipped")

    # Batch errors section if any batch nodes had failures
    batch_error_lines = _format_batch_errors_section(steps)
    if batch_error_lines:
        lines.extend(batch_error_lines)
```

**Also check**: After this change, `_format_execution_step` (lines 410-436) becomes dead code (its only caller is the deleted for-loop). Verify no test or external consumer imports it. If none, delete the function and its batch-node helper `_format_batch_node_line` if they also become unreachable. Use `grep` across `src/` and `tests/` during implementation: `rg '_format_execution_step|_format_batch_node_line' src/ tests/`.

**Test impact**: `tests/test_execution/formatters/test_success_formatter.py` contains multiple tests asserting on the per-node block output. Run this test file during implementation and update/delete failing tests. Specifically:
- Tests asserting `"Nodes executed (N):"` substring in output — update to assert absence or rewrite
- Tests asserting `⤷ Stopped after` line — verify this assertion still passes (the line is preserved in the new version)
- Tests asserting on `✓ node_id (Nms)` per-node formatting — delete (feature removed)
- The file is ~700+ lines of formatter tests; full test-by-test inventory is out of scope for this plan. The implementing agent should run the tests and handle each failure individually.

### Step 8 — Delete `DisplayManager` and inline its one live call

**File**: `src/pflow/execution/display_manager.py`

**Action**: **Delete entire file** (77 lines).

**File**: `src/pflow/execution/__init__.py`

**Current file contents** (for reference):
```python
"""Workflow execution services for pflow."""

from .display_manager import DisplayManager
from .output_interface import OutputInterface
from .result import ExecutionResult, ResolvedWorkflow, RunnerConfig, ValidationResult
from .runner import WorkflowRunner
from .workflow_resolver import resolve_workflow

__all__ = [
    "DisplayManager",
    "ExecutionResult",
    "OutputInterface",
    "ResolvedWorkflow",
    "RunnerConfig",
    "ValidationResult",
    "WorkflowRunner",
    "resolve_workflow",
]
```

**Target file contents**:
```python
"""Workflow execution services for pflow."""

from .result import ExecutionResult, ResolvedWorkflow, RunnerConfig, ValidationResult
from .runner import WorkflowRunner
from .workflow_resolver import resolve_workflow

__all__ = [
    "ExecutionResult",
    "ResolvedWorkflow",
    "RunnerConfig",
    "ValidationResult",
    "WorkflowRunner",
    "resolve_workflow",
]
```

(Removes `DisplayManager` and `OutputInterface` imports + `__all__` entries. `OutputInterface` is also deleted in Step 10; doing both here avoids partial-state edits.)

**File**: `src/pflow/cli/main.py`

**Edit 1** (line 35): Delete the import.
- Current: `from pflow.execution import DisplayManager`
- New: delete the line entirely.

**Edit 2** (lines 310-311): Replace the two `DisplayManager` lines with an inline `click.echo`.
- Current:
  ```python
      display = DisplayManager(cli_output)
      display.show_execution_start(len(ir_data.get("nodes", [])))
  ```
- New:
  ```python
      click.echo(f"Executing workflow ({len(ir_data.get('nodes', []))} nodes):", err=True)
  ```

  (Note: this replaces the call that went through `DisplayManager → CliOutput.show_progress → OutputController TTY check → click.echo`. The TTY gate is removed so the line always prints, matching the new "always show progress" behavior.)

### Step 9 — Delete `CliOutput`

**File**: `src/pflow/cli/cli_output.py`

**Action**: **Delete entire file** (73 lines).

**File**: `src/pflow/cli/main.py`

**Edit 1** (line 299): Delete the lazy import.
- Current: `    from pflow.cli.cli_output import CliOutput`
- New: delete the line entirely.

**Edit 2** (line 305): Delete the `CliOutput` instantiation.
- Current:
  ```python
      # CliOutput gets raw verbose (not effective_verbose) — it controls its own
      # JSON/interactive suppression internally. effective_verbose is for CLI-level
      # messages (echo) and the Runner's shared store __verbose__ flag.
      cli_output = CliOutput(output_controller, verbose, output_format)
  ```
- New: delete these 4 lines entirely (the comment is about a class that no longer exists).

**Edit 3** (line 322): Change the `output=cli_output` kwarg to pass a callback directly — **gated on `-p` and JSON mode** per Decisions 2 and 3.

- Current:
  ```python
      result = runner.run(
          workflow,
          params,
          config,
          output=cli_output,
          workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "library" else None,
          workflow_name=workflow_name,
      )
  ```
- New:
  ```python
      # Progress callback is suppressed in `-p` mode and JSON output mode (Decisions 2 and 3):
      # - -p explicitly asks for minimal output on stderr
      # - JSON mode keeps stderr machine-clean (matches the existing logging suppression at main.py:292)
      print_flag = ctx.obj.get("print_flag", False)
      progress_callback = (
          None
          if (print_flag or output_format == "json")
          else output_controller.create_progress_callback()
      )

      result = runner.run(
          workflow,
          params,
          config,
          progress_callback=progress_callback,
          workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "library" else None,
          workflow_name=workflow_name,
      )
  ```

  Also: the "Executing workflow (N nodes):" echo that Step 8 Edit 2 added must be gated the same way. Update Step 8 Edit 2 to match:
  ```python
      if not print_flag and output_format != "text_json_placeholder":  # JSON mode also silent
          click.echo(f"Executing workflow ({len(ir_data.get('nodes', []))} nodes):", err=True)
  ```
  Or more concretely (and cleaner): put both the echo and the callback behind the same gate. Define `progress_enabled = not print_flag and output_format != "json"` once near the top of `execute_json_workflow`, then:
  ```python
      if progress_enabled:
          click.echo(f"Executing workflow ({len(ir_data.get('nodes', []))} nodes):", err=True)
      # ...
      progress_callback = output_controller.create_progress_callback() if progress_enabled else None
  ```
  This is the preferred shape — one variable controls both.

### Step 10 — Delete `OutputInterface` and `NullOutput`

**File**: `src/pflow/execution/output_interface.py`

**Action**: **Delete entire file** (72 lines).

**File**: `src/pflow/execution/null_output.py`

**Action**: **Delete entire file** (38 lines).

Note: `src/pflow/execution/__init__.py` update for these was already done in Step 8.

### Step 11 — Simplify `WorkflowRunner.run()` signature

**File**: `src/pflow/execution/runner.py`

**Edit 1** (line 20): Delete the `OutputInterface` import.
- Current: `from .output_interface import OutputInterface`
- New: delete the line entirely.

**Edit 2** (add import at the top among the typing imports): Add `Callable` to existing typing imports if not already present. Check current imports in the file; if `from typing import Any, Optional` exists, change to `from typing import Any, Callable, Optional`.

**Edit 3** (line ~50-59): Update `run()` signature.
- Current:
  ```python
  def run(
      self,
      workflow: str | dict[str, Any] | ResolvedWorkflow,
      params: dict[str, Any],
      config: RunnerConfig,
      *,
      output: Optional[OutputInterface] = None,
      workflow_manager: Optional[WorkflowManager] = None,
      workflow_name: Optional[str] = None,
  ) -> ExecutionResult:
  ```
- New:
  ```python
  def run(
      self,
      workflow: str | dict[str, Any] | ResolvedWorkflow,
      params: dict[str, Any],
      config: RunnerConfig,
      *,
      progress_callback: Optional[Callable] = None,
      workflow_manager: Optional[WorkflowManager] = None,
      workflow_name: Optional[str] = None,
  ) -> ExecutionResult:
  ```

**Edit 4** (line 66): Update the `output` docstring entry to `progress_callback`. Remove the "NullOutput/None for MCP" stale text.
- Current (approximately): `output: Display interface (CliOutput for CLI, NullOutput/None for MCP).`
- New: `progress_callback: Optional per-node progress callback (see OutputController.create_progress_callback for the signature). CLI passes one; MCP passes None.`

**Edit 5** (line ~162, inside `_compile_and_execute`): Update the internal `output: Optional[OutputInterface]` parameter to `progress_callback: Optional[Callable]`. Also update the call inside `_compile_and_execute` that passes it to `_initialize_shared_store`.

**Edit 6** (line ~403, inside `_initialize_shared_store`): Update the `output: Optional[OutputInterface]` parameter to `progress_callback: Optional[Callable]`.

**Edit 7** (lines 416-419): Simplify the callback installation.
- Current:
  ```python
  if output:
      callback = output.create_node_callback()
      if callback:
          shared_store["__progress_callback__"] = callback
  ```
- New:
  ```python
  if progress_callback is not None:
      shared_store["__progress_callback__"] = progress_callback
  ```

**Edit 8** (find the `.run()` internal caller that passes `output=`): Inside the `run()` method body, the code calls `self._compile_and_execute(..., output=output, ...)`. Update this to `progress_callback=progress_callback`. The instrumentation chain (`instrumentation.py`, `batch_executor.py`) uses `shared.get("__progress_callback__")` + `callable()` check — no changes needed there.

**File**: `src/pflow/runtime/workflow_executor.py`

**Edit** (line ~80): Update the stale comment mentioning `NullOutput`.
- Current (approximately): `#   _callback__ |                                    | MCP server always None (NullOutput).`
- New: `#   _callback__ |                                    | MCP server always None.`

### Step 12 — Update `--print` help text

**File**: `src/pflow/cli/main.py`
**Line**: 888

**Current**:
```python
@click.option("-p", "--print", "print_flag", is_flag=True, help="Force non-interactive output (print mode)")
```

**New**:
```python
@click.option("-p", "--print", "print_flag", is_flag=True, help="Minimal output: suppress header, summary, and warnings on stderr. Data still goes to stdout.")
```

Flag name, short flag, destination var, and `is_flag=True` are unchanged. Only the help text changes. No references in tests or docs need to change because the flag name is kept.

### Step 13 — Delete `test_cli_mcp_parity.py` (becomes vacuous)

**File**: `tests/test_integration/test_cli_mcp_parity.py`

**Action**: **Delete the entire file.**

**Rationale**: After the refactor, the test's premise ("CliOutput vs no output produces same ExecutionResult") becomes structurally vacuous. The progress callback — the one thing the test was verifying didn't affect results — is now just a side-effecting function that writes to stderr and never touches `ExecutionResult`. A rewritten test would assert that passing `None` vs a function as a kwarg produces the same result, which is trivially true for any well-designed parameter. The value the original test guarded (ExecutionResult parity between CLI and MCP paths) is now inherent to the simpler architecture — there's only one code path for execution, so parity is structural rather than testable.

Delete the entire file. The deletion is part of the "dead scaffolding" cleanup.

**If you want to keep some parity guard**: consider adding a test to `tests/test_integration/` that runs the same workflow through both `WorkflowRunner().run()` (as the CLI does) and through `mcp_server.services.execution_service.execute_workflow()` (as MCP does), and compares the **rendered text output**. This is out of scope for this refactor but would be the right place for such a regression guard. Do not implement it as part of this plan.

**Old content** (for reference only — do not use):

**Current content** (66 lines):
```python
"""Test that WorkflowRunner produces equivalent results with and without OutputInterface."""

import pytest
import click.testing
from unittest.mock import patch

from pflow.core.output_controller import OutputController
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.cli.cli_output import CliOutput


def test_workflow_runner_produces_same_result_with_and_without_cli_output():
    """When the same workflow runs with CliOutput vs no output, ExecutionResult fields match."""
    workflow_ir = {
        # ... simple workflow
    }
    config = RunnerConfig()

    # Run without output (MCP path)
    result_no_output = WorkflowRunner().run(workflow_ir, {}, config)

    # Run with CliOutput (CLI path)
    controller = OutputController(print_flag=False, stdin_tty=True, stdout_tty=True)
    cli_output = CliOutput(controller, verbose=False, output_format="text")
    result_with_output = WorkflowRunner().run(workflow_ir, {}, config, output=cli_output)

    assert result_no_output.success == result_with_output.success
    # ... other parity assertions
```

**Replacement** (verifies parity with/without progress_callback):
```python
"""Test that WorkflowRunner produces equivalent results with and without a progress callback."""

import pytest

from pflow.core.output_controller import OutputController
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def test_workflow_runner_produces_same_result_with_and_without_progress_callback():
    """When the same workflow runs with a progress callback vs None, ExecutionResult fields match.

    Regression guard for the Task 194 refactor that replaced Optional[OutputInterface]
    with Optional[Callable]. The presence or absence of a progress callback must never
    affect the ExecutionResult — only the stderr display.
    """
    workflow_ir = {
        # Use the same simple workflow the previous version used — copy verbatim from
        # the pre-refactor test file's workflow_ir.
    }
    config = RunnerConfig()

    # Run without progress callback (MCP path)
    result_no_callback = WorkflowRunner().run(workflow_ir, {}, config)

    # Run with progress callback (CLI path)
    controller = OutputController(print_flag=False, stdin_tty=True, stdout_tty=True)
    callback = controller.create_progress_callback()
    result_with_callback = WorkflowRunner().run(workflow_ir, {}, config, progress_callback=callback)

    assert result_no_callback.success == result_with_callback.success
    assert result_no_callback.status == result_with_callback.status
    # Copy any other parity assertions from the original test file verbatim
```

If the rewrite becomes too costly (e.g., the workflow_ir fixture is complex and depends on the old test file structure), it is also acceptable to **delete** `test_cli_mcp_parity.py` entirely — the parity guarantee is a happy side effect of the simplification, not a behavior to regression-test.

### Step 14 — Delete orphaned tests in `test_shell_stderr_warnings.py`

**File**: `tests/test_cli/test_shell_stderr_warnings.py`

**Line 14 import**: `from pflow.cli.workflow_output import _display_stderr_warnings, _format_node_status_line`

After Step 7, `_format_node_status_line` no longer exists. `_display_stderr_warnings` still exists.

**Edit 1**: Change the import to only import `_display_stderr_warnings`:
```python
from pflow.cli.workflow_output import _display_stderr_warnings
```

**Edit 2**: Delete the test class `Unit tests for _format_node_status_line with stderr indicator` and its tests (lines ~430-490). The class name is the comment/docstring; grep for `_format_node_status_line` in the file to find all call sites and delete those tests (approximately 3 tests at lines 437, 451, 473 per Agent 2's report).

**Keep**: all other tests in the file, including those that test `_display_stderr_warnings` and the integration tests that use `combined_output = result.output + (result.stderr or "")`.

### Step 15 — Update `test_output_controller.py` (EXPANDED per review)

**File**: `tests/test_core/test_output_controller.py`

Review identified 7 additional tests the plan originally missed. The complete test impact:

#### DELETE — tests calling deleted methods (`echo_progress`, `echo_result`, `should_show_prompts`)

Step 5 deletes `echo_progress`, `echo_result`, `should_show_prompts`. These tests call them and must be deleted:

- **Line 41-47**: `test_interactive_progress_messages_to_stderr` — calls `echo_progress`
- **Line 49-55**: `test_non_interactive_no_progress_output` — calls `echo_progress`
- **Line 59-72**: `test_result_always_to_stdout` — calls `echo_result`
- **Line 76-79**: `test_interactive_shows_prompts` — calls `should_show_prompts`
- **Line 293-296**: `test_should_show_prompts_non_interactive` — calls `should_show_prompts`

**Action**: Delete all five tests. No behavior is lost because the methods themselves were dead code (zero production callers — verified by grep).

#### DELETE — tests for deleted `workflow_start` event + handler

Step 5 deletes `_handle_workflow_start` and the `workflow_start` dispatch branch. These tests are entirely about the deleted event:

- **Line 160-167**: `test_execution_header_format` — asserts on `workflow_start` dispatch output
- **Line 193-200**: `test_empty_workflow_still_calls_workflow_start` — asserts empty workflow fires `workflow_start`
- **Line 204-218**: `test_nested_workflow_indentation` — asserts `workflow_start` with `depth=1` prints indented header

**Action**: Delete all three tests. The "Executing workflow (N nodes):" emission now lives in `main.py` as an inline `click.echo` (Step 8) and is tested indirectly by the #194 regression test (via `result.stderr`).

#### UPDATE — tests that partially exercise `workflow_start` alongside other events

These tests were missed by the original plan. They dispatch `workflow_start` as one of several events — the `workflow_start` portions must be removed but the rest kept:

- **Line 100-119**: `test_progress_callback_handles_events` — lines 117-119 are the `workflow_start` portion. Delete those three lines. The `node_start` and `node_complete` portions at lines 106-113 are still valid.
- **Line 303-333**: `test_complete_workflow_execution_flow` — line 311 dispatches `callback("3", "workflow_start")` as part of a multi-event flow. Delete that line and its associated assertion, keep the rest.

**Action**: Update both tests to remove the `workflow_start` dispatch + assertion, leaving the rest intact.

#### UPDATE — Test #10 (TTY gate removal)

**Current** (lines 90-94):
```python
def test_create_progress_callback_returns_none_when_not_interactive(self):
    """Test requirement 10: create_progress_callback returns None if not interactive."""
    controller = OutputController(stdin_tty=False, stdout_tty=True)
    callback = controller.create_progress_callback()
    assert callback is None
```

**New**:
```python
def test_create_progress_callback_always_returns_callable(self):
    """create_progress_callback always returns a callable, regardless of TTY state.

    Regression for GH #194 refactor: the TTY gate that returned None in
    non-interactive mode was removed. Whether the callback is installed
    is now a CALLSITE decision (CLI suppresses in -p and JSON modes);
    the OutputController itself always returns a functioning callback.
    """
    controller = OutputController(stdin_tty=False, stdout_tty=True)
    callback = controller.create_progress_callback()
    assert callback is not None
    assert callable(callback)
```

#### DELETE — Test #20 (redundant after #10 update)

**Current** (lines 222-228):
```python
def test_callback_not_callable_handled_gracefully(self):
    """Test requirement 20: callback not callable → no exception raised (handled gracefully)."""
    controller = OutputController(stdin_tty=False, stdout_tty=False)
    callback = controller.create_progress_callback()

    # Should return None, not raise exception
    assert callback is None
```

**Action**: Delete entirely. After the #10 update, this becomes a duplicate assertion for `stdin_tty=False, stdout_tty=False` — no behavior difference worth testing since TTY state no longer affects the return.

#### UPDATE — Tests #30, #31, #32, #35, #36 (add stderr TTY mock)

These tests exercise `_handle_batch_progress` which now has an internal `sys.stderr.isatty()` guard. Under pytest with default output capture, `sys.stderr.isatty()` returns `False`, which makes the guard short-circuit and produces no output. The tests' assertions will then fail.

**Fix**: Wrap each test's body (or its callback invocation) in `patch.object(sys.stderr, 'isatty', return_value=True)`.

**Example** (test #30, lines 339-365 — wrap the existing test):
```python
def test_batch_progress_updates_line_in_place(self):
    """Test batch progress uses \\r to update the current line in place."""
    import sys
    from unittest.mock import patch

    controller = OutputController(stdin_tty=True, stdout_tty=True)
    callback = controller.create_progress_callback()

    # Mock stderr.isatty() so the TTY guard in _handle_batch_progress doesn't short-circuit.
    # Pytest captures stderr (making isatty() return False by default), which would
    # otherwise cause the batch_progress handler to no-op.
    with patch.object(sys.stderr, 'isatty', return_value=True), patch("click.echo") as mock_echo, patch("click.style", side_effect=mock_click_style):
        callback(
            node_id="my_batch",
            event="batch_progress",
            batch_current=1,
            batch_total=3,
            batch_success=True,
        )

        assert mock_echo.called
        call_args = mock_echo.call_args
        assert "\r" in call_args[0][0]
        assert "1/3" in call_args[0][0]
        # ... rest of existing assertions
```

Apply the same `patch.object(sys.stderr, 'isatty', return_value=True)` wrapper to tests #31, #32, #35, #36.

#### Tests #33, #34 — UNCHANGED

Tests `test_node_complete_for_batch_only_shows_timing` and `test_batch_error_completion_shows_failed` exercise `_handle_node_complete`'s batch branch. `_handle_node_complete` is unchanged by this refactor (no new TTY guard added there). These tests keep passing without modification.

#### All other tests in the file — UNCHANGED

Summary of test #inventory impact:
- **UPDATE**: #10 (flip assertion from `is None` → `is not None and callable`)
- **DELETE**: #20, #14, #18, #19 (4 tests)
- **ADD stderr TTY mock**: #30, #31, #32, #35, #36 (5 tests)
- **KEEP unchanged**: all remaining (28 tests)

### Step 16 — Add #194 regression test

**File**: `tests/test_cli/test_workflow_output_handling.py`
**Location**: Add to `class TestWorkflowOutputHandling` (starts at line 132). Pick any location after the existing tests.

**Test code** (uses existing fixtures `mock_registry_instance`, `mock_compile`, `mock_validate_ir` defined at lines 46-129 of the same file):

```python
    def test_workflow_data_goes_to_stdout_not_stderr_gh194(
        self, mock_registry_instance, mock_compile, mock_validate_ir
    ):
        """Regression for GH #194: workflow output data must go to stdout, not stderr.

        CliRunner runs as non-TTY by default — the exact execution context used
        by Claude Code's Bash tool, CI/CD pipelines, and any agent capturing
        pflow's output programmatically.

        Before the fix, _output_with_header's Mode 3 ("non-interactive") routed
        all output — header AND data — to stderr, leaving stdout empty. An agent
        running `pflow workflow.pflow.md` captured 0 bytes on stdout.

        Invariants after the fix (always, regardless of TTY state):
        1. Declared workflow data MUST appear on stdout (Unix convention).
        2. Workflow data MUST NOT appear on stderr (no leak).
        3. The "Workflow output" header stays on stderr (diagnostics are on stderr).
        """
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "outputs": {"result": {"description": "Test result", "type": "string"}},
            "nodes": [
                {
                    "id": "test",
                    "type": "test-node",
                    "params": {
                        "output_key": "result",
                        "output_value": "HELLO_STDOUT_CANARY_GH194",
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
            f.write(ir_to_markdown(workflow))
            workflow_file = f.name

        try:
            result = runner.invoke(main, [workflow_file])

            assert result.exit_code == 0, (
                f"Workflow invocation failed.\n"
                f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )

            # #194 core invariant: data lives on stdout
            assert "HELLO_STDOUT_CANARY_GH194" in result.stdout, (
                f"Workflow data missing from stdout (GH #194 regression).\n"
                f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )

            # #194 negative invariant: data MUST NOT leak to stderr
            assert "HELLO_STDOUT_CANARY_GH194" not in result.stderr, (
                f"Workflow data leaked to stderr (GH #194 regression).\n"
                f"stderr: {result.stderr!r}"
            )

            # Header stays on stderr (diagnostics belong on stderr per Unix convention)
            assert "Workflow output" in result.stderr, (
                f"'Workflow output' header missing from stderr.\n"
                f"stderr: {result.stderr!r}"
            )
        finally:
            Path(workflow_file).unlink()
```

**Critical Click version note** (Click 8.3.1, this repo's pinned version): `result.stdout` is stdout-only, `result.stderr` is stderr-only, `result.output` is combined. The existing tests in this file use `result.output` (combined) which is why they structurally can't detect stream-routing bugs. The new test is the first to use `result.stdout` and `result.stderr` separately and serves as precedent for future stream-separation tests.

**Fixture compatibility verified**: `mock_compile` at lines 82-111 patches `pflow.execution.runner.WorkflowRunner.run` to return a pre-built `ExecutionResult` with `shared_after` populated. The mock's `run_mock(workflow, params, config, **kwargs)` uses `**kwargs` to accept any runner kwargs — this includes both the old `output=` and the new `progress_callback=` — so the fixture doesn't need updating for the signature change.

### Step 16b — Add failure-path regression test

**File**: `tests/test_cli/test_workflow_output_handling.py`
**Location**: Add after Step 16's regression test.

Finding #5 from review: failed non-batch non-shell nodes leave hanging `node_id...` lines without a terminator. Step 3b fixes this in `_handle_node_complete`. This test guards against regression.

```python
    def test_failing_node_emits_terminator_in_live_progress(
        self, mock_registry_instance, mock_validate_ir
    ):
        """When a node fails in non-TTY mode, the live progress line must be
        terminated (✗ Failed) — not leave a hanging 'node_id...' partial line.

        Regression for review finding #5: _handle_node_complete's non-batch
        error branch used to silently return, leaving the hanging 'node_id...'
        line from _handle_node_start unterminated. After the static summary
        block was deleted, this caused the subsequent diagnostic block to
        concatenate onto the same line.
        """
        # Use a mock that raises an exception to simulate node failure.
        # This takes the engine down the error path in _execute_node, which
        # calls call_completion_callback(action="error", is_error=True),
        # which must now terminate the line instead of silently returning.
        runner = click.testing.CliRunner()

        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "failing_node",
                    "type": "test-node",
                    "params": {"raise_error": True},
                }
            ],
        }

        # Use a custom mock_compile that raises to trigger the error path
        with patch("pflow.execution.runner.WorkflowRunner.run") as mock_run:
            from pflow.execution.result import ExecutionResult
            from pflow.core.diagnostic import Diagnostic, Severity

            mock_run.return_value = ExecutionResult(
                success=False,
                diagnostics=[
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="runtime",
                        message="Simulated node failure",
                        node_id="failing_node",
                    )
                ],
                shared_after={},
            )

            with tempfile.NamedTemporaryFile(mode="w", suffix=".pflow.md", delete=False) as f:
                f.write(ir_to_markdown(workflow))
                workflow_file = f.name

            try:
                result = runner.invoke(main, [workflow_file])

                # The test ensures no ugly concatenation of "failing_node..." and
                # "❌" diagnostic on the same line. This is most visible as:
                # stderr should NOT contain a substring like "failing_node...❌"
                # (no space between, no newline between).
                assert "failing_node...❌" not in result.stderr, (
                    f"Progress line not terminated before diagnostic block.\n"
                    f"stderr: {result.stderr!r}"
                )
                # Note: Direct assertion of "✗ Failed" in stderr requires a real
                # engine execution (not just a mocked runner.run), because the
                # callback is invoked from the engine, not the runner. For a
                # deeper regression check, see the manual test 6 in the
                # verification section.
            finally:
                Path(workflow_file).unlink()
```

**Note**: This test covers the regression mechanically but doesn't fully exercise the callback path (which requires real engine execution). Manual test 6 in the verification section provides end-to-end coverage.

### Step 17 — Documentation updates

The following doc edits are required. Keep each edit focused — do not rewrite sections wholesale unless noted.

#### `src/pflow/cli/CLAUDE.md`

**Section "Three Output Modes"** (current lines 95-104): Replace the entire section with:

```markdown
### Output routing (`_output_with_header` in workflow_output.py)

Single rule: data → stdout, diagnostics → stderr. Always. Fixed in GH #194.

| Mode | When | Header | Data | Summary |
|------|------|--------|------|---------|
| `--print` (`-p`) | Explicitly requested | None | stdout | None |
| Default | Everything else (TTY, non-TTY, agents, CI/CD, pipes) | stderr | stdout | stderr |

`--print` is a minimal-output convenience that suppresses the header, summary, and warnings on stderr. Data still goes to stdout. Use it for clean piping into `jq` or similar tools: `pflow -p foo.pflow.md | jq`. Without `-p`, pipes still work correctly because data is already on stdout — stderr noise is just visible in the terminal.
```

**Section "workflow_output.py"** (current lines ~119-126): Update the paragraph that describes `_display_execution_summary`. The current text mentions "per-node timing" and "always shown except in `--print` mode". Replace with:

```markdown
2. **Execution summary**: `_display_execution_summary` emits a one-line completion tag (`✓ Workflow completed in Xs`) plus supplementary diagnostics (batch error details, shell stderr warnings, LLM cost, warning diagnostics) only when present. The previous "Nodes executed (N):" per-node listing was removed because it duplicated the live progress stream that is now always visible (TTY and non-TTY alike). When `--only` is active: the live progress and the completion tag reflect only the executed nodes.
```

**File listing at line 44**: Remove the `cli_output.py` entry:
- Delete: `├── cli_output.py            # CliOutput: OutputInterface implementation for Click`

**Section "Interactive Mode"** (current lines 238-243): Rewrite to reflect that TTY gating is no longer used for progress display, and resolve the `should_show_prompts` contradiction flagged in review (the method is deleted, so nothing in this section should reference it):

```markdown
## Interactive Mode

`OutputController.is_interactive()` is still defined but is only used by `cli/mcp_sync.py` for MCP discovery progress gating. CLI-specific impacts after the GH #194 refactor:
- Progress display: streamed to stderr in default mode (TTY and non-TTY alike). Suppressed in `-p` mode and JSON output mode by the CLI callsite gate, not by TTY detection.
- Save prompts: whatever logic currently gates the "save workflow?" interactive prompt is unchanged by this refactor. During implementation, verify what actually gates save prompts today (possibly a direct `sys.stdin.isatty()` check or `click.confirm` interactive detection — NOT `should_show_prompts`, which has zero production callers and is deleted).
- Trace file paths: shown in default mode, suppressed in `--print` or JSON mode by `_echo_trace` (unchanged).
```

#### `src/pflow/execution/CLAUDE.md`

**Section "File Structure"** (lines 8-24): Remove the deleted files:
- Delete: `├── output_interface.py      # Protocol for display abstraction (CLI, MCP, etc.)`
- Delete: `├── display_manager.py       # UX logic (context-aware messages, progress tracking)`
- Delete: `├── null_output.py           # Silent output (default when no OutputInterface)`

**Section "WorkflowRunner — Primary Entry Point"** (lines 28-31): Update signature:

Current:
```python
def run(workflow, params, config, *, output=None, workflow_manager=None, workflow_name=None) -> ExecutionResult
```

New:
```python
def run(workflow, params, config, *, progress_callback=None, workflow_manager=None, workflow_name=None) -> ExecutionResult
```

**Section "OutputInterface Protocol"** (lines 120-124): **Delete the entire section.**

**Section "Integration"** (lines 126-132): Replace with:
```markdown
## Integration

**CLI**: `cli/main.py:execute_json_workflow()` calls `WorkflowRunner().run()`, passing `progress_callback=output_controller.create_progress_callback()`. Handles: stdin routing, logging suppression, trace saving, display.

**MCP Server**: `mcp_server/services/execution_service.py` calls `WorkflowRunner().run()` without a progress callback (defaults to None). Three methods: `execute_workflow()`, `validate_workflow()`, `run_registry_node()`.
```

**Section "Gotchas" line 145**: Update the display-agnostic note:
- Current: `- **Display-agnostic**: Never import Click or add CLI concerns here. Use OutputInterface.`
- New: `- **Display-agnostic**: Never import Click or add CLI concerns here. Progress events flow through the optional `progress_callback` parameter installed in `shared_store["__progress_callback__"]`.`

#### `src/pflow/core/CLAUDE.md`

**Section "output_controller.py"** (lines 173-181): Rewrite the "5 rules for interactive mode" since the TTY gate for progress was removed.

Current:
```markdown
### output_controller.py

**5 rules for interactive mode** (ALL must pass):
1. No `-p/--print` flag
2. Output format is not `json`
3. stdin is TTY
4. stdout is TTY
5. Only if all pass → interactive
```

New:
```markdown
### output_controller.py

**`is_interactive()` rules** (ALL must pass): no `-p/--print` flag, output format is not `json`, stdin is TTY, stdout is TTY. After the GH #194 refactor, this is only used by `cli/mcp_sync.py` for MCP discovery progress gating. Progress display during workflow execution is **not** gated on `is_interactive()` — progress streams always (TTY and non-TTY) via `create_progress_callback()`. The one TTY-specific behavior is `_handle_batch_progress`'s `\r`-based inline counter, gated internally via `sys.stderr.isatty()`.
```

#### `src/pflow/mcp_server/CLAUDE.md`

**Section "Agent-Optimized Defaults"** (lines 149-156): Delete the bullet that claims `output=NullOutput()`.

Current bullet (line 152):
```markdown
- `output=NullOutput()` — Silent execution (no progress output)
```

Replacement: Delete the bullet entirely. The adjacent bullets about traces, output format, auto-normalization, and exception raising stay. MCP silent execution is the default now: `WorkflowRunner.run()` is called without `progress_callback`, which defaults to `None`, which means `__progress_callback__` is not installed in the shared store, which means no progress events fire.

#### `docs/reference/cli/index.mdx`

**Line 77** (options table, `-p` help text): Update to match the new help text:

Current:
```
| `-p, --print` | Force non-interactive output |
```

New:
```
| `-p, --print` | Minimal output: suppress header, summary, and warnings |
```

**Section "Output modes" (lines ~140-252)**: This section currently describes three modes (Text, JSON, Print) with language that implies progress only appears in interactive terminals. Rewrite to describe the actual behavior:

Replace with:
```markdown
## Output modes

### Text mode (default)

Human-readable output with live progress streamed to stderr and results on stdout. Works the same way in a terminal, CI log, agent bash tool, or subprocess capture:

```bash
pflow workflow.pflow.md
```

Progress lines and execution summary go to stderr. Declared workflow outputs go to stdout.

### JSON mode

Structured output on stdout for machine parsing:

```bash
pflow --output-format json workflow.pflow.md
```

All workflow results, metrics, and errors serialize to a single JSON object on stdout. Progress display is suppressed.

### Print mode (`-p`)

Minimal stderr output when you want the cleanest possible data stream:

```bash
pflow -p workflow.pflow.md | jq '.data'
```

Suppresses the "Workflow output:" header, the execution summary, and stderr warnings. Data still goes to stdout (same as default mode). Useful for piping into tools that should only see the result.
```

#### `architecture/features/shell-pipes.md`

**Line 81**: Update the misleading sentence about `-p`:

Current:
```
The `-p` flag outputs to stdout for pipeline composition.
```

New:
```
The `-p` flag suppresses header and summary on stderr so only the data (still on stdout, like default mode) appears in the terminal.
```

#### `src/pflow/nodes/shell/shell.py` (code comment update)

**Line 200**: Update the stale reference to `_format_node_status_line`. The function is deleted; smart-handled tag rendering now lives in `_handle_node_complete` (see Step 3b).

**Current comment** (lines 198-201):
```python
        IMPORTANT: When adding new patterns here, the reason string MUST contain
        either "no matches" or "not found" for proper tag display in CLI output.
        See src/pflow/cli/main.py _format_node_status_line() for the tag mapping.
        If neither phrase fits your pattern, update the tag mapping in main.py.
```

**New comment**:
```python
        IMPORTANT: When adding new patterns here, the reason string MUST contain
        either "no matches" or "not found" for proper tag display in CLI output.
        See src/pflow/core/output_controller.py _handle_node_complete() for the
        tag mapping. If neither phrase fits your pattern, the raw reason is
        shown as-is as a yellow tag so agents can still diagnose the case.
```

#### `src/pflow/cli/resources/cli-basic-usage.md`

**Lines 51-63**: Update the example output to reflect the new collapsed summary (no more "Nodes executed" block).

Current:
```
# Example output:
workflow-name was executed
  ✓ Workflow completed in 2s
  Nodes executed (2):
    ✓ get-data (1s)
    ✓ save-data(1s)
💰 Cost: $0.0001 # LLM Cost is not always present

Workflow output: # Not all workflows have an output, so this is not always present.
Data saved successfully # Only first workflow output is presented to the user (this is the only relevant information)
```

New:
```
# Example output (stderr):
workflow-name was executed
  get-data... ✓ 1.0s
  save-data... ✓ 1.0s
✓ Workflow completed in 2.0s
💰 Cost: $0.0001 # LLM cost is shown only when > 0

Workflow output: # stderr header (not every workflow declares an output)

# Example output (stdout):
Data saved successfully # The declared workflow output goes here — this is what agents should capture
```

---

## Verification

### Automated tests (must all pass)

Run the full test suite:
```bash
cd /Users/andfal/projects/pflow-fix-non-interactive-output-stderr
make test
```

Expected: all tests pass. Specifically verify:
- `tests/test_core/test_output_controller.py` — updated tests pass, deleted tests are gone
- `tests/test_cli/test_workflow_output_handling.py` — new `test_workflow_data_goes_to_stdout_not_stderr_gh194` passes
- `tests/test_cli/test_shell_stderr_warnings.py` — no import errors, remaining tests pass
- `tests/test_integration/test_cli_mcp_parity.py` — either rewritten version passes, or file is deleted

### Lint + type check

```bash
make check
```

Expected: clean. Any `ruff` or `mypy` errors from stale type hints should come from the signature changes and must be fixed as part of the same change.

### Manual test 1 — #194 fix verification

Use the scratchpad workflow created during research:
```bash
uv run pflow scratchpads/streaming-baseline/streaming-test.pflow.md 1>/tmp/out.txt 2>/tmp/err.txt
echo "STDOUT: $(wc -c < /tmp/out.txt) bytes"
cat /tmp/out.txt
echo "STDERR: $(wc -c < /tmp/err.txt) bytes"
cat /tmp/err.txt
```

**Before fix**: STDOUT ≈ 0 bytes. STDERR ≈ 460 bytes (contains "all done" + everything else).
**After fix**: STDOUT contains `all done` (the workflow output). STDERR contains the "Executing workflow (5 nodes):" header, per-node progress lines, the "Workflow output:" header, the completion tag, and the trace path line. STDOUT and STDERR are cleanly separated.

### Manual test 2 — TTY experience preserved

Run interactively (no redirection):
```bash
uv run pflow scratchpads/streaming-baseline/streaming-test.pflow.md
```

Expected: identical visible output to today's interactive run (inline progress, `\r`-based batch counter `1/5 → 2/5 → ... → 5/5`, completion tag, workflow output). The duplicate "Nodes executed (N):" block that used to appear after the progress is **gone**.

### Manual test 3 — agent streaming verification

From inside Claude Code (or any non-TTY capture), run:
```bash
uv run pflow scratchpads/streaming-baseline/streaming-test.pflow.md
```

Expected: the captured output now includes live per-node progress lines (`stage_one... ✓ 1.0s`, etc.) — the same lines TTY users see, minus the `\r`-based batch counter intermediate updates. Agents who previously saw silence during execution + a post-hoc static summary now see the progress stream in real time.

### Manual test 4 — pipe composition

```bash
uv run pflow -p scratchpads/streaming-baseline/streaming-test.pflow.md | cat
```

Expected: only the workflow data (`all done`) on stdout. All diagnostics on stderr (progress, tag, etc.), visible in the terminal but NOT piped through `cat`.

```bash
uv run pflow scratchpads/streaming-baseline/streaming-test.pflow.md | cat
```

Expected: same — data on stdout, progress/tag on stderr (visible in terminal, not piped). The `-p` flag is only needed to ALSO suppress the stderr noise; pipe composition itself works without `-p` now.

### Manual test 5a — Failure-path line termination

Create a workflow with a node that fails (e.g., a shell node with `command: exit 1`) and run it:

```bash
cat > /tmp/fail.pflow.md <<'EOF'
# Failure Test

## Steps

### fail_stage
- type: shell
- cache: false

```shell command
exit 1
```
EOF

uv run pflow /tmp/fail.pflow.md 2>/tmp/err.txt; cat /tmp/err.txt
```

Expected: stderr shows `fail_stage... ✗ Failed` as a clean terminated line, followed by the diagnostic block on a new line. Verify visually that `fail_stage...` does NOT concatenate with the error indicator or the diagnostic text.

### Manual test 5b — Smart-handled tags preserved

Create a workflow with a `grep` that finds no matches:

```bash
cat > /tmp/grep.pflow.md <<'EOF'
# Grep No-Match Test

## Steps

### search_logs
- type: shell
- cache: false

```shell command
grep "nonexistent_needle" /tmp/err.txt
```
EOF

uv run pflow /tmp/grep.pflow.md 2>/tmp/err2.txt; cat /tmp/err2.txt
```

Expected: stderr shows `search_logs... ✓ 0.0s [no matches]` — the smart-handled tag is preserved after the refactor. If the tag is missing, Step 3b's port of the smart-handled rendering is broken.

### Manual test 5c — `--only` summary preserved

```bash
uv run pflow scratchpads/streaming-baseline/streaming-test.pflow.md --only stage_two 2>/tmp/err3.txt; cat /tmp/err3.txt
```

Expected: stderr contains `⤷ Stopped after 'stage_two' (--only), 3 remaining nodes skipped` — the `--only` context is preserved in the new `_display_execution_summary`.

### Manual test 5d — `-p` mode is silent on stderr

```bash
uv run pflow -p scratchpads/streaming-baseline/streaming-test.pflow.md 1>/tmp/out.txt 2>/tmp/err4.txt
echo "stdout: $(wc -c < /tmp/out.txt) bytes"
cat /tmp/out.txt
echo "stderr: $(wc -c < /tmp/err4.txt) bytes"
cat /tmp/err4.txt
```

Expected: stdout contains `all done`. **stderr is empty or near-empty** (no "Executing workflow...", no progress lines, no completion tag, no warnings — just possibly the trace file path if trace is enabled, though `_echo_trace` should suppress that in `-p` mode). This verifies Decision 3.

### Manual test 5e — JSON mode is silent on stderr

```bash
uv run pflow --output-format json scratchpads/streaming-baseline/streaming-test.pflow.md 1>/tmp/out.txt 2>/tmp/err5.txt
echo "stdout:"
cat /tmp/out.txt | head -5
echo "stderr: $(wc -c < /tmp/err5.txt) bytes"
cat /tmp/err5.txt
```

Expected: stdout contains valid JSON. **stderr is empty or near-empty** (no progress lines — JSON mode keeps its clean-stderr invariant). This verifies Decision 2.

### Manual test 6 — MCP server unaffected

```bash
uv run pflow mcp serve
```

Expected: MCP server starts and operates normally. No progress output leaks onto MCP's stdio transport (progress callback is `None` in the MCP path, so `__progress_callback__` is never installed in the shared store).

---

## Post-implementation sanity checks

1. **`grep` for the deleted names** — there should be zero references remaining in `src/` and `tests/` (excluding deletion metadata in commits):
   ```bash
   rg 'OutputInterface|CliOutput|NullOutput|DisplayManager' src/ tests/
   ```
   Expected: no matches (except possibly in docstring history inside CLAUDE.md files you've updated).

2. **`grep` for the old parameter names** — should only hit the runner's `progress_callback` parameter and main.py's call site:
   ```bash
   rg 'output: Optional\[OutputInterface\]|output=cli_output' src/
   ```
   Expected: no matches.

3. **`grep` for the bug marker** — the old "Mode 3" rationale about everything-on-stderr should be gone:
   ```bash
   rg 'Mode 3|everything on stderr|Non-interactive sends data to stderr' src/
   ```
   Expected: no matches.

4. **Verify `__progress_callback__` propagation chain** — the shared store key flow should still work:
   ```bash
   rg '__progress_callback__' src/
   ```
   Expected: hits at `runner.py:_initialize_shared_store`, `workflow_executor.py:_PROPAGATED_KEYS`, `instrumentation.py` (4 read sites), `batch_executor.py` (2 read sites). No other unexpected locations.

---

## Critical file paths (for agent reference)

### Source files modified
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/cli/main.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/cli/workflow_output.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/core/output_controller.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/execution/__init__.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/execution/runner.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/runtime/workflow_executor.py` (comment only)

### Source files deleted
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/cli/cli_output.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/execution/display_manager.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/execution/null_output.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/execution/output_interface.py`

### Test files modified
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/tests/test_core/test_output_controller.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/tests/test_cli/test_workflow_output_handling.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/tests/test_cli/test_shell_stderr_warnings.py`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/tests/test_integration/test_cli_mcp_parity.py` (rewrite or delete)

### Doc files modified
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/cli/CLAUDE.md`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/execution/CLAUDE.md`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/core/CLAUDE.md`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/mcp_server/CLAUDE.md`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/docs/reference/cli/index.mdx`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/architecture/features/shell-pipes.md`
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/src/pflow/cli/resources/cli-basic-usage.md`

### Scratchpad (verification artifact, do NOT delete)
- `/Users/andfal/projects/pflow-fix-non-interactive-output-stderr/scratchpads/streaming-baseline/streaming-test.pflow.md`

### Critical reference files (read-only, context only)
- `src/pflow/runtime/engine/instrumentation.py` — call sites: `call_start_callback` (line 354), `call_completion_callback` (line 363), `handle_cached_execution` (line 412), `handle_api_warning` (line 455). All use `shared.get("__progress_callback__")` + `callable()` check — unchanged by this refactor.
- `src/pflow/runtime/engine/batch_executor.py` — `_report_batch_progress` (line 381). Unchanged.
- `src/pflow/runtime/workflow_executor.py:99-107` — `_PROPAGATED_KEYS` constant includes `__progress_callback__` at position 2. Unchanged.
- `src/pflow/mcp_server/services/execution_service.py:243-250, 512` — three `WorkflowRunner().run()` call sites, none pass `output=`. The signature change from `output=` to `progress_callback=` does not require any change to this file (kwarg defaults apply).

---

## Things deliberately NOT done

1. **No `--print` → `--quiet` rename**. The flag matches Claude Code's `-p` convention, is already documented, is in 38 markdown files including README and docs, and its semantic meaning after the fix is still "print the result minimally". Keeping the flag avoids 14 test updates and 100+ doc references.

2. **No `output_format == "json"` rule change in `is_interactive()`**. It's still used by `mcp_sync.py` and removing it would be out of scope. (The JSON-mode progress gate lives at the CLI runner call site instead — see Step 9 Edit 3.)

3. **No changes to `_populate_declared_outputs_best_effort` exception handling**. The bare `except Exception: pass  # noqa: S110` at line 265 is intentional best-effort behavior per the existing codebase convention — leave it alone.

4. **No MCP server code changes beyond the `_append_execution_steps` formatter update**. `execution_service.py` already calls `runner.run(...)` without `output=`, so it gets the default `progress_callback=None`. No edits to `execution_service.py` itself.

5. **No changes to `_PROPAGATED_KEYS` or nested workflow propagation logic**. The propagation already works for `__progress_callback__`; removing the TTY gate just means more non-TTY runs benefit from it automatically (when progress is enabled — i.e., not in `-p` or JSON mode).

6. **No new flag added for "force progress"**. Default mode always shows progress. `-p` and JSON mode suppress it. Users who want stderr-silent default mode can use `2>/dev/null`.

7. **No bundled release notes / changelog entries**. Versioning and release notes are separate steps per the project's release workflow.

8. **No fix for the pre-existing `cli: Starting workflow execution` stdout bug** at `main.py:308-309`. This line writes a CLI diagnostic to stdout (no `err=True`) but is gated on `effective_verbose` so most users don't see it. Flag as pre-existing; out of scope.

9. **No investigation of actual save-prompt logic.** The original plan's Step 17 CLAUDE.md update referenced `should_show_prompts` as if it gated save prompts, but that method has zero production callers. During implementation, verify what save-prompt actually uses (likely direct `click.confirm` or `sys.stdin.isatty()`) and make sure the deletion of `should_show_prompts` doesn't break save-prompt tests. If the save-prompt tests fail, restore `should_show_prompts` as a minimal 2-line method that returns `is_interactive()`.

10. **No port of smart-handled tags to the MCP formatter.** The CLI gets tags via the live callback (Step 3b); MCP users of `format_success_as_text()` never had tags and continue not to. If MCP users ask for tags, that's a follow-up task.

11. **No backwards-compat shim for the `output:` parameter.** The Runner signature change is breaking for any external caller passing `output=...`. Verified: no external callers exist (searched via grep — only CLI main.py and the deleted test_cli_mcp_parity.py). Clean break.

12. **No change to the `_display_execution_summary` function name or signature.** The function is only called from `_handle_text_output` and its signature (formatted_result, verbose, warning_diagnostics) is preserved. Only the body changes.
