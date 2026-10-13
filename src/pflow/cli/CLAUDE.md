# CLI Module

`main.py:PflowCLI` routes registered commands normally and unknown first arguments
to the hidden `commands/run.py` command. Run prepares CLI inputs and delegates
validation, planning, execution, and resource lifecycle to `execution/runner.py:WorkflowRunner`.
Keep those responsibilities in the Runner so CLI and MCP share them.

## Navigation

| Concern | Owner |
|---|---|
| Command registration and default routing | `main.py:cli`, `PflowCLI.resolve_command` |
| Run flags and context | `commands/run.py:_initialize_context`, `_setup_workflow_execution` |
| Stdin → the `stdin: true` input (the only stdin read) | `commands/run.py:_route_stdin_to_params` |
| Workflow-name versus invalid-command heuristic | `workflow_resolution.py:is_likely_workflow_name` |
| `name=value` parameters (raw text; the declared type types them) | `param_parsing.py` |
| File/saved-name resolution shared with MCP | `execution/workflow_resolver.py:resolve_workflow` |
| A run's ending — JSON document, stderr summary, exit code (every status) | `commands/run.py:_display_execution_result` over `execution/formatters/run_outcome.py` (`build_run_outcome`, `render_cli_stderr`, `EXIT_CODES`, `EXIT_REJECTED`) |
| A successful run's stdout data and its header | `workflow_output.py:_handle_text_output`, `_show_output_header` |
| A failure with no run (pre-execution or escaped exception) | `error_output.py:output_error` |
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
Stdin is read only after the workflow resolves, and only for an input declared
`stdin: true` that no argument supplied — a pipe the workflow never asked for
stays unread, so it can neither hang nor fail the run. Validation happens
**after stdin routing**, so piped data can satisfy required inputs. Which
descriptors are readable (pipes, regular files) and StdinData behavior belong
to `core/shell_integration.py` and `core/CLAUDE.md`.

`--auto-approve` is repeatable per approval-gate ID, never blanket authorization or
escalation approval. `commands/run.py:_prepare_gate_resolver` only scans top-level
IDs, while `execution/gate_prompt.py:build_gate_resolver` matches names across nested
workflows; an unmatched top-level ID must remain an advisory, not a validation error.

## Output contracts

Results go to **stdout**; progress and diagnostics go to **stderr**. Data routing
is TTY-independent. The output header has a separate TTY policy in
`workflow_output.py:_show_output_header`; do not use that policy to route data.
`--print` suppresses normal stderr chatter; `--output-format` chooses the result
format. Neither is a substitute for the other.
Node execution (`runner.run` in `commands/run.py:execute_json_workflow`, probe's
`probe_node`) happens inside `core/stdio_reservation.py:reserve_stdout`, in every
output format, so stray writes from user code reach stderr, not the result.
Third-party compile-time warnings (a dependency's `SyntaxWarning`, printed on the
first import in an environment with no cached bytecode) never reach pflow's stderr.
`tests/test_third_party_compile_warnings.py` enforces this on every CI Python. Fix
at the source by upgrading the dependency in `uv.lock`. Only when no fixed release
exists, add a narrow category+message filter in `cli_main` with its removal
condition and exempt the same message in that test. Never use a `module=` filter:
Python 3.14.0 attributes these warnings to `importlib._bootstrap`, not to the
module being compiled.

### Declared vs --only Output Contract

`execution/formatters/output_utils.py:select_output_mode` owns precedence:
explicit output key → `--only` target → declared workflow outputs → auto-detection.
CLI text and JSON/MCP renderers must use this decision rather than reproduce it.
Auto-detection details belong to `find_auto_output` in the same module.

`commands/run.py:_display_execution_result` renders one Run outcome for every status
and exits with `outcome.exit_code` (`EXIT_CODES`: completed/degraded 0, failed 1, denied 3,
durable pause 4); the builder turns a non-durable PAUSED into a failure, so no unusable
resume token prints. It settles a failure's trace before building the outcome, so a run that
failed before the engine opened its stream still carries `execution_id`/`trace_path`.

Exit 2 (`EXIT_REJECTED`, beside `EXIT_CODES`) means the run never started — decided by phase,
never by error category: a FAILED outcome with `ExecutionResult.engine_started` False, and every
boundary that catches an error before a run exists (run's and resume's outer `except`,
`--validate-only`, `--dry-run` plan errors, a removed command). Click's own usage errors are 2 too.
A new pre-run exit uses `EXIT_REJECTED`; anything raised once the engine started stays 1.
Interrupts exit 130.

Workflow progress streams to stderr for TTY and non-TTY callers; run.py's print-mode
gate suppresses it.

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
