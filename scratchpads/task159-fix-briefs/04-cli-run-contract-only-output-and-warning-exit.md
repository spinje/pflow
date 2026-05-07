# Task 159 Fix Brief 04 — CLI Run Contract for `--only`, Stdout, and Warning-Only Exits

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`

## Purpose

This brief captures what is known about two CLI execution-contract issues:

- `--only` runs can produce stdout that does not match the stderr warning about
  which declared workflow output is being streamed.
- successful workflows with runtime warnings can exit with code `2`, which is
  surprising for scripts and agents.

The next agent's job is to research the current code deeply, reproduce the
issues, and bring policy/design options to the user before implementing. Do not
treat this as a mechanical patch list. Prefer a simple final contract that
future agents can understand: stdout should contain exactly the data pflow says
it contains, and exit codes should communicate success/failure in a way that is
intentional and documented.

There are no shipped users of the Task 159 cache-warning behavior yet.
Compatibility with the current branch-only behavior is not a constraint, but
existing CLI output contracts from earlier tasks must be read before changing
behavior.

## Findings Covered

Primary:

- Final verification Finding 7: `--only` plus multi-output workflow streams a
  skipped output and dumps huge intermediate JSON.
- Final verification Finding 8: warning-only runtime executions exit with code
  `2`.

Keep separate from:

- Brief 02 analyzer trace-evidence scope for `--only`.
- Brief 03 report cost semantics.

This brief is about CLI execution behavior and scripting/automation contracts.

## Plain-Language Problem

Agents and scripts need three things from `pflow run`:

1. stdout contains the result data, not diagnostics.
2. stderr accurately explains what stdout is when there is ambiguity.
3. the process exit code tells automation whether the workflow succeeded.

The final verification found two ways these contracts are currently muddy.

### Finding 7: `--only` Output Routing

A workflow can declare multiple outputs, for example:

```text
winning_chorus
runner_up_choruses
all_scored_text
selection_text
chorus_guide
total_generated
```

When the user runs `--only generate-chorus-options`, downstream nodes that
produce declared workflow outputs may not execute. In the paid music run, pflow
warned:

```text
Workflow declares 6 outputs (...). Streaming 'winning_chorus' to stdout.
```

But stdout contained a huge intermediate object from `generate-chorus-options`,
including prompt-shaped data. The warning named a declared output that was not
actually available, while stdout came from fallback auto-detection.

The user-facing bug is not "auto-detection exists". The bug is that stderr and
stdout tell different stories.

### Finding 8: Warning-Only Exit Code

Some successful workflows with cache warnings completed but exited `2`.

For a human, "completed with warnings" may be fine. For Unix-style automation,
any nonzero exit code commonly means failure. The verification report treats
this as surprising and asks for a conscious policy decision:

- Should warning-only successful execution exit `0`?
- Should degraded success remain nonzero?
- Should pflow distinguish advisory warnings from degraded recovery/runtime
  warnings?

This is a policy/design question, not just an accidental bug.

## Current Evidence

From `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`:

### Finding 7 Evidence

Paid targeted music run:

```bash
.venv/bin/pflow /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --only generate-chorus-options \
  --report \
  --no-cache \
  concept=... \
  creative_direction=... \
  architecture=... \
  creative_brief=...
```

Observed:

```text
Workflow declares 6 outputs (winning_chorus, runner_up_choruses, all_scored_text, selection_text, chorus_guide, total_generated). Streaming 'winning_chorus' to stdout.
```

Actual stdout:

- Huge JSON-like intermediate object from `generate-chorus-options`.
- Included generated prompts and `cd_summary`.

Expected from the report:

- If the declared/default output is skipped or unavailable under `--only`, say
  that.
- Either stream the target node output with a clear label, require `-o`, or emit
  no stdout unless JSON output is requested.

### Finding 8 Evidence

Reproduction examples in the report:

- Tiny below-min cache workflow.
- Skipped branch fixture:

```bash
.venv/bin/pflow scratchpads/segment3-verification/A5-absent-chunk-via-branching.pflow.md --report --no-cache route=A
```

Observed:

- Workflow completed with warnings.
- Exit code `2`.
- Report status may be `degraded`.

Expected from the report:

- If nonzero warning-only exits are intentional, documentation and CLI wording
  should make that clear.
- If not intentional, warning-only successful runs should exit `0`.

## Verified Code Facts

These were checked through local code orientation and explorer subagents.

### How `--only` Is Represented

- `--only` starts as `ctx.obj["only_node"]`.
- It flows into `RunnerConfig.only_node`, then `WorkflowEngine(only_node=...)`.
- Runtime stores it in shared state:

```python
shared["__execution__"]["only_node"] = self.only_node
```

- For dotted sub-workflow paths, the engine also uses transient
  `shared["_pflow_child_only_node"]` while entering the child workflow.

### How Text Stdout Is Selected

Text output routing in `src/pflow/cli/workflow_output.py` is roughly:

1. `-o/--output-key` wins if the key exists.
2. If the workflow declares outputs, `_try_declared_outputs(...)` runs.
3. Declared stdout target selection is:
   - output marked `stdout: true`;
   - otherwise the only declared output;
   - otherwise the first declared output, with a stderr warning listing all
     outputs.
4. If the selected declared output is unavailable and
   `shared["__execution__"]["only_node"]` exists, CLI falls through to
   auto-detection.
5. Auto-detection uses `find_auto_output(...)`:
   - optional `preferred_key` for dotted `--only`;
   - then root keys in priority order:
     `result`, `response`, `output`, `text`, `data`, `stdout`;
   - then namespace dicts in that order;
   - then last valid non-internal root key.

JSON mode differs: success formatting skips declared outputs when `--only` is
present and goes to auto-detection.

### Why Finding 7 Happens

The multi-output warning is emitted before pflow knows whether the chosen
declared output exists.

Current sequence:

1. `_select_stdout_target(...)` chooses the first declared output, e.g.
   `winning_chorus`.
2. `_warn_multi_output_ambiguity(...)` prints:
   `Streaming 'winning_chorus' to stdout`.
3. `_emit_declared_output(...)` fails because `winning_chorus` was skipped by
   `--only`.
4. Best-effort declared-output population fails for the same reason.
5. Because `only_node` exists, `_handle_text_output(...)` silently falls back to
   auto-detection.
6. Auto-detection prints the target/intermediate output instead.

Non-string values are JSON-serialized by `safe_output(...)`, which explains the
huge JSON-like dump.

### How Runtime Warnings Become Degraded

Runtime warnings are stored in:

```python
shared_store["__warnings__"]
```

`WorkflowRunner._determine_status(...)` returns
`(True, WorkflowStatus.DEGRADED)` when `__warnings__` or `__template_errors__`
is non-empty.

The CLI mapping is in the run command display path:

- success + `WorkflowStatus.SUCCESS` -> exit `0`.
- success + `WorkflowStatus.DEGRADED` -> currently exits `2`.
- failure -> exits `1`.

There is a test currently locking degraded success exit `2`.

### Validation Warnings Are Different

Validation warnings and runtime warnings share the final
`ExecutionResult.diagnostics` surface, but they do not fully share the status
decision path:

- Runtime warnings degrade because `_determine_status(...)` reads
  `shared_store["__warnings__"]`.
- Validation warnings are diagnostics collected during preparation; they do not
  necessarily populate `__warnings__`.
- Trace status explicitly excludes parser/validator warnings from degraded
  status in the trace summary path.

Therefore warning-only exit `2` currently applies to runtime-status-changing
warnings, not all warnings.

## Reproduction Commands

### Finding 7

Prefer using the already-produced paid trace/report if available. If rerunning
the music workflow is required, discuss provider spend with the user first.

Command shape from the verification report:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  --only generate-chorus-options \
  --report \
  --no-cache \
  concept=... \
  creative_direction=... \
  architecture=... \
  creative_brief=...
```

For a free regression fixture, create a small workflow with:

- multiple declared outputs,
- no `stdout: true`,
- an upstream node that produces a large structured result,
- downstream nodes that produce declared outputs,
- run with `--only <upstream-node>`.

The expected reproduction is that stderr names the first declared output while
stdout contains auto-detected upstream/intermediate output.

### Finding 8

Known command shape from report:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow \
  scratchpads/segment3-verification/A5-absent-chunk-via-branching.pflow.md \
  --report --no-cache route=A
```

Also use or create a tiny below-min cache workflow that completes successfully
but emits `cache.below-min-tokens` at runtime.

Capture exit code explicitly:

```bash
set +e
HOME=/private/tmp/pflow-test-home .venv/bin/pflow <workflow> <params>
code=$?
echo "exit=$code"
set -e
```

## Most Relevant Code Areas

Read before editing.

### CLI Output Routing

- `src/pflow/cli/workflow_output.py`
  - `_handle_text_output(...)`
  - `_try_declared_outputs(...)`
  - `_select_stdout_target(...)`
  - `_warn_multi_output_ambiguity(...)`
  - `_emit_auto_detected_output(...)`
  - `_only_target_root(...)`
  - `safe_output(...)`
- `src/pflow/execution/formatters/output_utils.py`
  - `find_auto_output(...)`
  - priority order and `preferred_key`.
- `src/pflow/execution/formatters/success_formatter.py`
  - JSON mode behavior under `--only`.
- `src/pflow/runtime/engine/engine.py`
  - `--only` lifecycle and shared-state metadata.

### Status and Exit Codes

- `src/pflow/execution/runner.py`
  - `_determine_status(...)`
  - `_extract_runtime_warnings(...)`
  - diagnostics construction.
- `src/pflow/cli/commands/run.py`
  - display result and `ctx.exit(...)` behavior.
- `src/pflow/core/workflow/status.py`
  - `WorkflowStatus.SUCCESS`, `DEGRADED`, `FAILED`.
- `src/pflow/nodes/llm/llm.py`
  - runtime warning producers, including observed `cache.below-min-tokens`.
- `src/pflow/runtime/workflow_trace.py`
  - trace status summary and parser/validator warning distinction.

## Relevant Docs and Progress Logs

Read these before proposing changes:

### For `--only` / stdout routing

- `src/pflow/cli/CLAUDE.md`
  - stdout/stderr routing contract.
  - output auto-detection contract.
- `src/pflow/execution/formatters/CLAUDE.md`
  - formatter behavior under `--only`.
- `src/pflow/runtime/engine/CLAUDE.md`
  - engine `--only` lifecycle.
- `docs/reference/cli/index.mdx`
  - stdout output contract.
  - `--only` contract.
- `.taskmaster/tasks/task_134/implementation/progress-log.md`
  - why auto-detection was unified and the chosen priority order.
- `.taskmaster/tasks/task_149/implementation/progress-log.md`
  - stdout/stderr routing redesign.
  - `--only` mode confirmation design and tests.

### For warning-only exits

- `.taskmaster/tasks/task_159/task-159.md`
  - warning tiering / DD#36.
- `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`
  - `Stage 2 follow-up — Findings #9/#10 + phantom-savings: unified below-min-token detection`
  - runtime below-min warning rationale.
- `scratchpads/stage2-verification/README.md`
  - manual things worth testing hard.
  - below-min runtime warning and prewarm advisory notes.

Naming trap:

- Progress-log section `Stage 2 follow-up — Finding #8: drift-aware analyze-cache auto-load`
  is **not** this final report's Finding 8. It refers to earlier Stage 2
  numbering.

## Tests to Read Before Changing Behavior

### `--only` / stdout

- `tests/test_execution/formatters/test_output_utils.py`
  - current `--only` fallback tests.
  - dotted preferred-key behavior.
- `tests/test_cli/test_progress_streaming_subprocess.py`
  - real subprocess `--only` stderr mode-signal tests.
- `tests/test_execution/formatters/test_success_formatter.py`
  - JSON/text success formatter behavior.

Expect to add a high-level test for:

- multiple declared outputs,
- no `stdout: true`,
- `--only` stops before declared outputs are produced,
- stderr must not claim the skipped declared output is being streamed,
- stdout behavior is explicit and expected.

### Warning-only exit status

- `tests/test_cli/test_agent_ux_fixes.py`
  - current degraded success exits `2` lock.
- `tests/test_execution/test_runner.py`
  - runtime `cache.below-min-tokens` degrades today.
- `tests/test_runtime/test_workflow_trace.py`
  - parser warning does not degrade trace, runtime warning does.
- `tests/test_cli/test_analyze_cache.py`
  - `analyze-cache` advisory findings exit `0`.
- `tests/test_core/test_prompt_cache_validation.py`
  - validation `cache.unused-chunk` warning behavior.

## Research Questions for the Next Agent

### `--only` Output Routing

1. Under `--only`, should declared workflow outputs be skipped entirely in text
   mode, matching JSON mode?
2. If declared outputs are unavailable, should pflow:
   - auto-detect target/intermediate output and clearly say so,
   - require `-o`,
   - emit no stdout in text mode,
   - or choose another simple contract?
3. Should large structured auto-detected values be printed by default under
   `--only`, or should pflow require explicit JSON mode / `-o`?
4. How should stderr word the fallback so stdout is never ambiguous?
5. Can text and JSON mode share more selection logic, or are their contracts
   intentionally different?

### Warning-Only Exit Codes

1. Should warning-only successful runs exit `0` or nonzero?
2. If keeping nonzero, should the CLI explicitly document and render that
   warning-only success exits `2`?
3. Should pflow distinguish:
   - advisory cache warnings,
   - template warnings,
   - on-error recovery/degraded execution,
   - provider/API warnings,
   - validation warnings?
4. Is `WorkflowStatus.DEGRADED` the right concept for cache advisories, or is
   it overloaded?
5. Would a future `--strict-warnings` or `--warnings-as-errors` mode be the
   better Unix-compatible shape?

## Decision Point: Warning-Only Exit Policy

This brief intentionally does not decide the policy. The fixing agent should
present options to the user.

Options to consider:

1. **Exit `0` for warning-only success**
   Good Unix/scripting behavior: the workflow completed. Warnings remain on
   stderr and in diagnostics/report. Simple for agents. Could add strict mode
   later.

2. **Keep exit `2` for degraded success**
   Lets callers distinguish clean success from warning success using only exit
   code. But many scripts treat any nonzero as failure, and the final
   verification found this surprising.

3. **Classify warnings by severity/policy**
   Advisory cache warnings exit `0`; recovery/degraded execution exits `2`.
   Most semantically precise, but may add complexity and requires a clear
   warning taxonomy.

The top-10%-codebase question to ask: what final concept produces the least
surprising, easiest-to-extend CLI contract?

## Desired UX Properties

Outcome constraints:

- stdout contains the data pflow says it is streaming.
- stderr never claims a skipped declared output is being streamed.
- `--only` mode clearly communicates that workflow-declared outputs may be
  unavailable.
- Large intermediate structured output is not dumped unexpectedly without a
  clear routing explanation.
- Exit codes are intentional, documented, and tested.
- Warning-only success and true failure are not confused in automation.
- Text mode and JSON mode may differ, but the difference must be documented and
  easy to reason about.

## Non-Goals for This Brief

- Do not solve analyzer trace partialness here; see Brief 02.
- Do not solve report memo-hit cost display here; see Brief 03.
- Do not redesign all output formatting unless research shows the current
  duplication is the root cause.
- Do not start Task 160 structural refactor.

