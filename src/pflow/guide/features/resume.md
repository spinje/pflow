# Resuming a run — failed, interrupted, or paused at a gate

**Use when**: a long or expensive run failed partway (an `llm`/`http`/`mcp`/`claude-code` step timed out, a transient error survived retries) and you want to continue from the failed step instead of paying for the whole run again — or a run **paused at an approval gate** in a non-interactive context and you hold its resume token (see "Answering a paused gate" below).

```bash
pflow resume <execution-id>      # resume that exact failed attempt (from the failed run's output)
pflow resume <workflow>          # resume the newest failed run of that workflow (name or path)
```

A failed run prints the exact command to use:

```
❌ Workflow failed after 12.4s
Workflow trace saved: ~/.pflow/debug/workflow-trace-….json
To resume from the failed step: pflow resume 7a9e4afb-2095-447e-8043-0660438104f9
```

With `--output-format json`, the failure document carries the same target as machine-readable
fields: `execution_id` and `resume_command`.

Resume restores the already-completed upstream steps' outputs from the saved run (it does **not** re-run them) and continues execution from the failed step onward. The resumed attempt is a **new run with its own trace**, linked to the original run by the `resumed_from` field in its JSON output.

## Answering a paused gate

A gate reached in a non-interactive run (a pipe, CI, MCP, the web UI) does not fail — the run **pauses durably** and exits **4** with a resume token on stdout:

```
Paused at 'notify-slack'. Resume token: 7a9e4afb-2095-447e-8043-0660438104f9 (exit 4)
```

The gate content follows on stderr — an approval gate's resolved preview, or an escalation's question, options, and recommendation — so the answer can be composed from the output alone. With `--output-format json`, the paused document carries `status: "paused"`, `execution_id`, `paused_node_id`, `gate_request`, and `resume_command`.

Answer it — hours or days later:

```bash
pflow resume <execution-id> --approve yes        # approval gate: run the gated step and continue
pflow resume <execution-id> --approve no         # deny: the run ends cleanly as denied (exit 3)
pflow resume <execution-id> --choose "per-env"   # escalation: an answer, or an option number (--choose 2)
pflow resume list                                # pending unanswered pauses (token, workflow, step, gate, age)
```

**Or let your human answer in the browser** — usually the better channel when a person is
deciding: `pflow ui <workflow> --run <execution-id>` opens the paused run on the visual canvas,
where the paused step carries a ⏸ badge and an answer panel (Approve/Deny for an approval; the
question, options, and a free-text field for an escalation). Their click delivers the same
answer as the commands above, and the canvas follows the continued run live. They see the
resolved preview in context instead of a relayed terminal snippet. A **failed** run opened the
same way shows a Resume button (same confirmation rules as below).

Behavior worth knowing:

- **Nothing re-runs.** Upstream steps are restored from the paused trace. An approved gate's step runs for the first time (approval gates fire *before* the step, so there is no side-effect re-fire risk and no confirmation prompt). An answered escalation continues at the **next** step with the decision folded into the completed step's result (`${step.result.escalation.decision.chosen}`) — the agent step is never re-paid.
- **A token is consumed by its answer.** The resumed attempt supersedes the paused run; a second answer refuses and names the newer attempt. Each later gate in the same workflow pauses again as a **new** token.
- **Resuming without an answer flag refuses** and shows the pending question with the exact command; `--approve`/`--choose` on a run that is not paused refuses too.
- The **edited-workflow refusal** and `--force` (below) apply to paused resumes the same as failed ones. Input overrides (`KEY=VALUE`) work the same way.

## Overriding inputs

`KEY=VALUE` after the target overrides the original run's inputs — the common way to fix what caused the failure:

```bash
pflow resume my-workflow api_url=https://correct.example.com
```

Everything not overridden is reused from the inputs the failed run used.

## Re-running the failed step may repeat its side effects (at-least-once)

The failed step runs **again** from the start. If it already partly side-effected before failing — an http POST that sent but timed out on the response, an mcp tool that created a resource, a shell command that wrote a file — resuming re-fires it. This is at-least-once execution of the failed step.

- An **idempotent** failed step (an `llm` step) resumes silently — re-running is safe.
- A **side-effecting** failed step (`shell` / `code` / `claude-code` / file operations / `mcp`; `http` too — even reads touch external systems):
  - At a terminal, resume asks for confirmation before re-running the step (default No).
  - **For AI agents** (no terminal): resume **refuses with a clear error** rather than silently repeating the side effect. Confirm with your human that re-running the step is safe, then re-run with `--force`.

`--force` bypasses this confirmation **and** the edited-workflow check below.

## Other behavior worth knowing

- **Edited workflow → refusal.** If the workflow file changed since the original run, resume refuses — the restored upstream outputs may no longer match the current steps. Re-run from the start, or `--force` to resume anyway.
- **Loop steps restart at iteration 1.** Loop iteration position is not part of the saved run, so a resumed loop step begins its loop again.
- **Downstream approval gates re-prompt.** Resume does not inherit prior approvals — each execution is a new action. `--auto-approve <step>` still works.
- **Top-level granularity.** A failure *inside* a sub-workflow re-runs the **whole** sub-workflow step — restoration works only at the top level of the parent workflow. The cross-run cache softens the cost of re-running its inner steps.
- **Interrupted (Ctrl+C / crash) runs** are resumable too: killed mid-step → resumes at that step; killed while a step was failing (or before its error handler started) → resumes at that failing step; killed between successful steps → resumes at the next step **only when it is unambiguous** (a single non-branching successor; a dynamic `code` router or a branch refuses). Crashed before the first step → nothing to resume.
- **Inline / piped workflows are not resumable** — there is no workflow file to load again. Save the workflow to a file and re-run it so future failures can be resumed.
- **Prefer resume-by-execution-id from a different directory.** A workflow *path* resolves relative to your current directory; the execution id is location-independent.

### Restored `${node.prompt}` / `${node.system}` caveat

Like `--only`, resume restores upstream outputs from the saved run, and the saved run does not keep an LLM step's rendered `prompt`/`system` values. A downstream step referencing `${upstream_llm.prompt}` or `${upstream_llm.system}` will therefore not see them on resume. No common pattern depends on this; avoid it in workflows you expect to resume.

### `analyze-cache` on a resumed trace

A resumed attempt's trace under-reports LLM coverage: its restored upstream LLM steps carry **no prompt text for cache analysis to inspect**, so `pflow analyze-cache` over a resumed trace sees only partial evidence. Analyze the **original** attempt's trace instead.
