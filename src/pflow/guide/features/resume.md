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

Resume restores the already-completed upstream steps' outputs from the saved run (it does **not** re-run them) and continues execution from the failed step onward. The resumed attempt is a **new run with its own trace**, linked to the original via `resumed_from`.

## Overriding inputs

`KEY=VALUE` after the target overrides the original run's inputs — the common way to fix what caused the failure:

```bash
pflow resume my-workflow api_url=https://correct.example.com
```

Everything not overridden is reused from the failed run (its `meta.inputs`).

## Re-running the failed step may repeat its side effects (at-least-once)

The failed step K runs **again** from the start. If K already partly side-effected before failing — an http POST that sent but timed out on the response, an mcp tool that created a resource, a shell command that wrote a file — resuming re-fires it. This is at-least-once execution of K.

- An **idempotent** K (an `llm` step) resumes silently — re-running is safe.
- A **side-effecting** K (`shell` / `code` / `claude-code` / file-ops / `mcp`; `http` reads external state):
  - At a terminal, resume asks `Run this step again? [y/N]` (default No).
  - **For AI agents** (no terminal): resume **refuses with a clear error** rather than silently repeating the side effect. Confirm with your human that re-running K is safe, then re-run with `--force`.

`--force` bypasses this confirmation **and** the edited-workflow check below.

## Other behavior worth knowing

- **Edited workflow → refusal.** If the workflow file changed since the failed run (`content_hash` mismatch), resume refuses — the restored upstream outputs may no longer match the current steps. Re-run from the start, or `--force` to resume anyway.
- **Loop steps restart at iteration 1.** Loop iteration state is engine-ephemeral (never traced), so a resumed loop step begins its loop again.
- **Downstream approval gates re-prompt.** Resume does not inherit prior approvals — each execution is a new action. `--auto-approve <step>` still works.
- **Top-level granularity.** A failure *inside* a sub-workflow re-runs the **whole** sub-workflow host step (the seed is top-level-scoped). The memo cache softens the re-run cost of that host's inner steps.
- **Interrupted (Ctrl+C / crash) runs** are resumable too: killed mid-step → resumes at that step; killed between steps → resumes at the next step **only when it is unambiguous** (a single non-branching successor; a dynamic `code` router or a branch refuses). Crashed before the first step → nothing to resume.
- **Inline / piped workflows are not resumable** — there is no source file to re-resolve. Save the workflow to a file and re-run it so future failures can be resumed.
- **Prefer resume-by-execution-id from a different directory.** A workflow *path* resolves relative to your current directory; the execution id is location-independent.

### Restored `${node.prompt}` / `${node.system}` caveat

Like `--only`, resume re-seeds upstream from the trace, and an LLM step's rendered `prompt`/`system` are not persisted in the trace file (they live in the canonical `llm_prompt`/`llm_system` fields). A downstream step referencing `${upstream_llm.prompt}` or `${upstream_llm.system}` cannot be re-seeded from a resumed run. No built-in flow does this; custom workflows should avoid depending on it across a resume.

### `analyze-cache` on a resumed trace

A resumed attempt's trace under-reports LLM coverage: restored upstream LLM steps are recorded as `cached` with **no `llm_prompt` evidence** (the prompt text cache analysis needs), so `pflow analyze-cache` over a resumed trace sees only a partial evidence scope. Analyze the **original** attempt's trace instead.
