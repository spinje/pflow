# review-falsifier — Task 185 @ 80bffdf1 (direct launch, opus/high; condensed by the task orchestrator from the agent's report)

All seven promise groups attacked through the real CLI / MCP (`ExecutionService.execute_workflow`) / Viewer (`pflow ui`)
entry paths, isolated HOMEs, provider keys unset. No Critical. HOLDS: 30k lookups (resume list 0.30 s, resume <id>
--dry-run 0.29 s, resume <workflow> 0.47 s, report 0.29 s, --only --dry-run 0.35 s, /api/gate 0.12 s; opened files = the
answer, audited with sys.addaudithook); legacy-count on every miss; id exactness incl. 8-char shared prefix; list/verdict
agreement in 7 consumption states (deny, approve, live attempt, kill -9 attempt, deleted wf, edited wf, stranded marker);
protected set under real + 3 concurrent sweeps, unremovable source (chflags uchg), flock-held writer, unreadable trace,
two-gate chain, MCP inline ir-hash, unknown tag/sidecar; read-only commands never remove (8 commands, directory diff empty);
second-sweep opens flat as history doubles (659 → 764 → 754); .paused marker-write fault non-durable on every surface;
--no-trace/--report, nested pause, --only never a resume source or Snapshot, one recency rule, symlinked/relative/space paths.

## BROKEN (Warnings, ranked) — all in settings-fault handling: deletion stays ON, no warning
- **W1** a misspelling inside the word: `runtime.trace_retension_days: 0`, `runtime.trace_retain_days: 0`, shell
  `PFLOW_TRACE_RETENTON_DAYS=0` → deleted at 14 days, no warning (detector is a `retention` substring test,
  `trace_retention.py:128-147`). Non-PFLOW `TRACE_RETENTION_DAYS=0` is ignored by recorded design.
- **W2** `pflow settings init` over a DANGLING settings symlink replaces it with a default file (14 days), no prompt, non-TTY
  (`cli/commands/settings.py:67` `settings_path.exists()` follows the link) — contradicts ADR-0018's "a link whose target
  is unavailable is a failed load". Every other write command refuses.
- **W3** `"trace_retention_days": true` → pydantic coerces to 1 → a 1-day window (`core/settings.py:71`); the env path
  rejects `true/false/off`.
- **W4** a duplicated `runtime` block: `json.load` keeps the last duplicate → the opt-out is dropped silently
  (`core/settings.py:215`).

## Older behaviour observed (one line each)
- A failed `--only` run prints "To resume from the failed step: pflow resume <id>"; `resume <id>` then answers "No run …
  was found" + the NEW "may have aged out" hint — the hint is misleading for an `.only` trace (agent-ux).
- `/api/gate` for a consumed pause returns 200 with the gate payload (same on main).
- "Failed to load settings" prints 7× per run.
- `PFLOW_EXECUTION_ID` with a non-filename-safe value now hard-fails the run (internal variable; ruled).
- Saved-workflow-by-name under a redirected HOME: "not a known workflow" (same on main) — blocked that attack.

## Not attacked / partial
Viewer gate callout in a real browser (substitute: /api/gate timed + audited); Windows (CI); the owner's real directory;
>64 KB trailer, meta-less newest trace, a real md5[:8] collision, a dead zero-work attempt (no legal setup). Repo tests
`test_trace_retention.py`/`test_trace_dir.py`/`test_settings.py` 165 passed — none covers W1–W4.
