# CLI Module

`main.py:PflowCLI` routes registered commands normally and unknown first arguments
to the hidden `commands/run.py` command. Run prepares CLI inputs and delegates
validation, planning, execution, and resource lifecycle to `execution/runner.py:WorkflowRunner`.
Keep those responsibilities in the Runner so CLI and MCP share them.

## Navigation

| Concern | Owner |
|---|---|
| Command registration and default routing | `main.py:cli`, `PflowCLI.resolve_command` |
| Run flags, context, stdin preparation | `commands/run.py:_initialize_context`, `_setup_workflow_execution` |
| Workflow-name versus invalid-command heuristic | `workflow_resolution.py:is_likely_workflow_name` |
| Typed CLI parameters | `param_parsing.py` |
| File/saved-name resolution shared with MCP | `execution/workflow_resolver.py:resolve_workflow` |
| Successful text output and headers | `workflow_output.py:_handle_text_output`, `_show_output_header` |
| Ordinary failure rendering | `error_output.py:output_error` |
| Status dispatch and exit codes | `commands/run.py:_display_execution_result` |
| Rerun commands and secret masking | `rerun_display.py` |
| Execution-start MCP discovery | `mcp_sync.py:_auto_discover_mcp_servers`; `../mcp/CLAUDE.md` |
| Subcommand-specific seams | `commands/CLAUDE.md` |

Add top-level commands through `main.py:cli.add_command`. Keep cycle-sensitive
imports local; for example, resume dispatch imports run's execution shim lazily.

## Routing and stdin

Click's `ignore_unknown_options` and the hidden run command's disabled automatic
help option let workflow `--help` reach the workflow-help path. They are not a
permission to ignore unknown flags: `commands/run.py:_validate_workflow_flags`
rejects stray leading-dash tokens, with `--help` as the exception. Tokens containing
`=` reach parameter/undeclared-input validation instead. Preserve both stages.

`is_likely_workflow_name` is a later CLI heuristic, not the command router.
Validation happens **after stdin routing**, so piped data can satisfy required
inputs. FIFO and StdinData behavior belong to `core/shell_integration.py` and
`core/CLAUDE.md`.

## Output contracts

Results go to **stdout**; progress and diagnostics go to **stderr**. Data routing
is TTY-independent. The output header has a separate TTY policy in
`workflow_output.py:_show_output_header`; do not use that policy to route data.
`--print` suppresses normal stderr chatter; `--output-format` chooses the result
format. Neither is a substitute for the other.

### Declared vs --only Output Contract

`execution/formatters/output_utils.py:select_output_mode` owns precedence:
explicit output key → `--only` target → declared workflow outputs → auto-detection.
CLI text and JSON/MCP renderers must use this decision rather than reproduce it.
Auto-detection details belong to `find_auto_output` in the same module.

`commands/run.py:_display_execution_result` handles DENIED separately (exit 3)
and **durable** PAUSED separately (exit 4); neither uses ordinary failure rendering.
A non-durable PAUSED result becomes a failure, with no unusable resume token.
Completed/degraded runs exit 0, failures 1, interrupts 130; Click owns usage exit 2.

Workflow progress streams to stderr for TTY and non-TTY callers; run.py's print-mode
gate suppresses it. Optional MCP discovery has its own interactive-only progress
policy in `mcp_sync.py`; do not apply that gate to workflow progress.

## Lifecycle and verification seams

- Runner owns MCP-pool and LLM-interception cleanup. The CLI shim's `finally`
  handles CLI-owned stdin temporary files.
- Trace writing belongs to Runner/runtime; CLI trace echo respects print mode.
  Report-directory validation happens before execution: explicit destinations
  must be empty or already marked as pflow report output.
- `main.py:_setup_signals` owns interrupt/SIGPIPE behavior; output helpers handle
  broken pipes without contaminating stdout.
- For stream/TTY verification, read `tests/CLAUDE.md` → pitfall #10.
  CliRunner does not exercise the real terminal/pipe boundary.
