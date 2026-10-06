# Task 180: Resume Refuses Only When an Edit Touches a Restored Step

## Description

Fix-a-typo-then-resume is the most common resume, and today it always needs `--force`: resume
compares one hash of the whole workflow, so any edit anywhere reads as "Workflow changed". Record
enough in the trace to tell an edit to the failed step (or anything after it) from an edit to a
step whose saved output is being restored, and refuse only the second.

## Status
not started

## Priority

medium

## Roadmap

next

## Problem

Observed and executed on main `a2d094b7` (issue #690, re-verified by its lane):

```
$ uv run pflow e-resume.pflow.md          # 'save' fails: ${produce.result.markdwn} (typo)
$ sed -i '' 's/markdwn/markdown/' e-resume.pflow.md
$ uv run pflow resume <run>
Error: Workflow changed since the original run
  → Re-run the workflow from the start, or pass --force to resume anyway.
$ uv run pflow resume <run> --force      # succeeds
```

- The trace stores exactly one whole-workflow hash (`execution/runner.py:204` → the meta line's
  `content_hash`); `execution/resume_preflight.py:161-192` `_check_content_hash` compares it. The
  trace carries no per-step identity, so preflight cannot know that only `save` changed. (The
  engine has one — a per-node `config_hash` for the memo cache,
  `runtime/engine/instrumentation.py:141-192`, computed at `plan_node.py:64` — it is just never
  written to the trace.)
- The hash also covers each step's prose description, so a description-only edit trips it.
- `--force` is the only way through, and it waives the side-effect confirmation in the same
  breath — an agent that edited the workflow and passes `--force` is never told that a shell step
  which already ran will run again (executed: the effect fired twice). Training agents to pass
  `--force` by reflex defeats the one gate that protects real re-fires.

## Design intent (confirm at start — not a locked design)

Resume passes without `--force` when every step whose saved output it restores is unchanged and
the workflow's shape around them is unchanged; it refuses, naming the edited restored step, when
one is not. Editing the entry step or anything downstream of it never needs `--force`. `--force`
goes back to meaning one thing a user can reason about.

The #690 lane (its PR is the starting point — read it) ships the two parts that need no trace
change: no side-effect confirmation for an entry step that never began, and a refusal that names
the restored steps and says when `--force` would re-run a started side-effecting step. Both
survive this task; the refusal text narrows to the edited-upstream case.

## In scope by ruling (2026-10-06)

- **Every step that begins writes a top-level `node.start` — including a batched sub-workflow
  host.** The engine skips `begin_node` for every `WorkflowExecutor` (`runtime/engine/engine.py:1368`;
  the comment there calls the host's `node.start` "deferred"). A non-batched host writes its own
  through `descend`, but batch items take the buffered-collector path and never do, so a batched
  `type: workflow` step leaves no top-level `node.start` even after its children fired (executed
  by the #690 lane: the child's side effect ran, the host's failed event has no paired start).
  The #690 lane's "this step never began, no confirmation needed" check therefore carries a
  guard — it never trusts the proof for a `workflow`-type entry. This task makes the signal true
  for every node (engine contact; changes on-disk trace content and what the live overlay shows
  as `running`) and **deletes that guard** in `execution/resume_preflight.py` as part of closing.

## Open questions (resolve at start)

- **What identifies a step for this purpose** — its params? its type and edges? Prose excluded?
  The lane's searcher surfaced the cases a per-step hash alone misses: a step INSERTED upstream of
  the entry (never ran, never restored), an edge change that reroutes around a restored step, an
  edited workflow input default. State which of these refuse and why.
- **Reuse or mint.** The engine's `config_hash` already identifies a step by type, static params
  (source-line keys removed), raw template params, batch config and rendered prompt-cache content;
  it leaves out prose, edges and `loop:`. Writing it on the events of restored steps plus one
  structure hash would reuse an existing mechanism — but its prompt-cache part is rendered per
  value and can differ per Iteration, and a `loop:` edit is invisible to it. Decide reuse vs. a
  new hash and say why.
- **Where it is recorded.** A per-step hash plus a structure hash in the trace meta line is the
  obvious shape — a trace-format change (version bump; Task 183 — loop gates, planned 2026-10-06 —
  also bumps the trace format additively, so 2.9.0 may be taken by it: whichever task merges second
  takes the next number; the Task-159 baseline is the
  outer regression net; old traces without the field keep today's whole-workflow behaviour).
- **How it composes with Task 179's restore contract** — the fidelity refusal fires in the loader
  before preflight and is not bypassed by `--force`; loop position is restored per Iteration. A
  looped restored step's identity must not change between iterations.
- **Whether `--force` splits** (stale-workflow vs side-effect confirmation) once the stale check
  is narrow — or whether narrowing makes the split unnecessary. The web UI's resume bridge maps
  these refusals (`stale_workflow`); any change there is in scope.
- `--only` snapshots (ADR-0002, #458) read the same traces — say whether they gain the same check
  or stay as they are.

Solution / Requirements / Verification — finalized when the task is started (just-in-time).

## Dependencies

None blocking. Trace-format contact → lane A, plan-mode deep-review mandatory, serialized with any
other trace-format or engine change. Read first: `.taskmaster/tasks/task_179/task-review.md`
(resume's integration contract), ADR-0010 (resume from the trace), issue #690 in full (body +
comments) and its lane PR.

## References

- Issue #690 — stays open as this task's governing issue; closes with it.
- `src/pflow/execution/resume_preflight.py`, `src/pflow/runtime/resume_source.py`,
  `src/pflow/core/trace_io.py`, `src/pflow/runtime/workflow_trace.py`.
