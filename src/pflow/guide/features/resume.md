# Resuming a failed run

**Use when**: a long or expensive run failed partway (an `llm`/`http`/`mcp`/`claude-code` step timed out, a transient error survived retries) and you want to continue from the failed step instead of paying for the whole run again.

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

- **Edited workflow → refusal.** If the workflow file changed since the failed run, resume refuses — the restored upstream outputs may no longer match the current steps. Re-run from the start, or `--force` to resume anyway.
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
