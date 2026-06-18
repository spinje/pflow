# Research: Task 164 — issue #255 (failure-state edge cases resume must own)

Small carry-forward note. Issue **#255** ("Pre-engine exceptions lose `shared_after` + registry_run
bypasses engine") was deliberately deferred *into* Task 164 by the failure-state hardening plan
(`scratchpads/failure-state-invariant-hardening/plan.md`), because both parts are only *latent* today
and only become real correctness bugs once durable resume re-enters a failed node from
`__failures__` / `shared_after`. Recorded here so resume picks them up with a real consumer + test,
instead of being fixed blind ahead of time.

**Trust boundary:** all `file:line` below **verified at HEAD `015a38f2`** (2026-06-18). Issue #255's
own line refs (`runner.py:194-200`, `registry_run.py:257`) are **proven stale** — the runner was
refactored (Task 138) and the single-node path moved file. Re-anchor if the surrounding code shifts.

---

## What #255 actually is (two independent observations)

### Part 1 — pre-engine exceptions produce `ExecutionResult(shared_after={})`

In `src/pflow/execution/runner.py::_compile_and_execute`:

- `compile_workflow(...)` — **line 248**
- `shared_store.update(workflow.resolved_defaults)` — **line 254**
- `try: engine.run(...)` — **line 266**, whose `except` (lines 268-288) is the *only* place
  `e._pflow_shared_store = shared_store` is attached (**lines 286-287**).

So compile (248) and the defaults seed (254) run **outside** the annotating try. Any exception they
raise skips the `_pflow_shared_store` annotation, the outer `run()` boundary catches it, and
`_exception_to_result` produces `shared_after={}`.

Harmless **today**: when compile fails, no node has executed, so there is no per-node state worth
surfacing. Becomes a problem only if pre-execution prep starts registering cross-cutting state
(MCP connections, cache warming, `__parser_diagnostics__`) that resume would want to recover.

### Part 2 — single-node run bypasses the engine

The bare single-node execution path is now `src/pflow/cli/commands/_probe_impl.py:157`
(`action = node.run(shared_store)`) — **not** `registry_run.py:257` (stale). Because it calls
`node.run()` directly, engine **step 17.5 never runs**, so `__failures__` is never populated; outputs
are read straight from `shared_store` (`_extract_node_outputs`, ~line 159). Correct today (it is a
single-node probe path), but it would silently drop failure data if anyone routes it through the
engine to inherit retry / tracing / caching.

## Why it lands with resume (Task 164), not before

Resume's whole premise is re-entering "the failed node" from the archived failure state
(`__failures__` + `shared_after` + `__execution__`). That is the first consumer for which an empty
`shared_after` (Part 1) or an unpopulated `__failures__` (Part 2) is a real correctness crack rather
than cosmetics. Fixing earlier = adding exception-boundary plumbing with no load-bearing consumer and
nothing real to test it against. Fixing here = the fix is shaped by, and tested against, actual resume
behavior.

## Concrete new touchpoint from the storage_mode work (#254/#231)

The `storage_mode` param was removed entirely (not just the `shared` value). Correctness is now
unconditional — `WorkflowExecutor._create_child_storage` always isolates the child store, so the
#254/#231 leak cannot recur regardless of validation. Any `storage_mode:` line is now an **unknown
param**, rejected by the validator's unknown-param step (`WorkflowValidator` Step 8, reading
`WorkflowExecutor.ALLOWED_PARAMS`). On the run path the runner's `_validate()`
(`src/pflow/execution/runner.py:502`) raises `WorkflowValidationError` from that error **before
compile** — i.e. another pre-engine failure that, like Part 1's `compile_workflow` case, produces
`ExecutionResult(shared_after={})`. (Note: bare `compile_workflow` does *not* reject it — unknown-param
is a `WorkflowValidator`-only check, not a compile-time one — but every real entry point runs the
validator first, including nested children via Step 10's recursive validation.)

This is a **live, reachable example** of Part-1's "pre-engine failure → `shared_after={}`" path, and
`shared_after={}` is correct there (nothing executed). It just means Part 1 now has one more concrete,
easy-to-reproduce trigger if Task 164 wants to assert behavior on pre-engine failures.

## What Task 164 should decide (from the issue, not yet chosen)

- **Part 1:** move the `_pflow_shared_store` annotation out to the *outer* `run()` exception boundary
  so every caught exception — pre-engine included — carries the shared store. Cheap, but only worth
  it once resume reads pre-engine state; pair it with a test that asserts what resume needs.
- **Part 2:** either route the single-node probe path through the engine pipeline (inherits step-17.5
  archival, retry, tracing) **or**, at minimum, add a comment at `_probe_impl.py:157` documenting the
  deliberate bypass. The "route through engine" option is the larger change and should be driven by a
  resume requirement, not done speculatively.

## References

- Issue: **#255** (open; "neither is actively broken" per its own Scope section).
- Sibling fixes that closed the rest of the cluster: #254 + #231 (`storage_mode: shared` removed,
  branch `fix/storage-mode-shared-failure-state`); #252 + #233 + #253 (PR 1,
  `fix/failure-archival-invariant`).
- Plan of record: `scratchpads/failure-state-invariant-hardening/plan.md` (§"Out of scope here
  (folded into Task 164)").
- Invariant doc: `src/pflow/runtime/CLAUDE.md` → "Node Execution State Invariant" /
  `mark_node_failed` single-write-site; `src/pflow/execution/CLAUDE.md` →
  "Exception-path observability".
