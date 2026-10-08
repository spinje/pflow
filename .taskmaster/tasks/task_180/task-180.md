# Task 180: Resume Refuses Only When an Edit Touches a Restored Step

## Description

Fix-a-typo-then-resume is the most common resume, and today it always needs `--force`: resume
compares one hash of the whole workflow, so any edit anywhere reads as "Workflow changed". Record
enough in the trace to tell an edit to the failed step (or anything after it) from an edit to a
step whose saved output is being restored, and refuse only the second.

## Status
done

## Completed
2026-10-08

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
  as `running`) and **narrows that guard** in `execution/resume_preflight.py` to traces that predate
  the guarantee (no `step_identity`): traces 2.3–2.8 carry `content_hash` but never wrote a batched
  host's start, so deleting it outright would skip the confirmation for exactly the case it protects
  (plan D1b; accepted by the main orchestrator).

## Decisions (ruled 2026-10-07)

- **Which edits refuse** — the 16-row table in `implementation/show-before-code.md` is the ruled behaviour
  (user: *"yes go with your recommendations"*): refuse on an edited/removed restored step, a changed
  recorded `next` upstream, a new start step, a missing resume point, and a paused-approval step edited
  after its approval (row 14); pass on prose, the resume point itself, downstream edits, and an edited
  input default (row 9, guide sentence). Policy-only settings on a restored step count as edits (fail-closed).
- **`--force` stays one flag (a)** — waives both the stale refusal and the side-effect confirmation; the
  refusal text says when it also re-fires a started step. Later narrowing is additive (new flags beside it).

## Resolved questions (rationale: `implementation/implementation-plan.md` §3)

- **What identifies a step** — its definition minus prose: every node key except `purpose` and source
  provenance, plus the `## Cache` chunks it references; its outgoing edges are recorded separately as
  `next` (document order and an explicit `next:` to the same target are the same). An upstream insertion
  or reroute refuses through the predecessor's changed `next`; a new first step through the recorded
  start step; an edited `## Inputs` default passes (recorded inputs win, `KEY=VALUE` overrides) (D2, D4).
- **Reuse or mint** — mint `step_identity(ir)` in `core/workflow_id.py`; the engine's `config_hash`
  varies per loop iteration and omits `loop`, `retry`, `approval` and edges (D2).
- **Where it is recorded** — one meta key `step_identity` (`start` + per-step `hash` and `next`), trace
  format 2.9.0, additive. Traces without the key keep the whole-workflow compare (D5, D6). Any change to
  what it hashes bumps the trace minor and older maps are treated as absent.
- **Composition with Task 179** — the checked set is `restored_node_ids` (the loader's seed set minus
  the resume point, unchanged) plus a paused approval step; the hash is static IR, so it is identical
  across iterations. The fidelity refusal still fires first in the loader (D3).
- **`--only`** — gains no check (D8).

## Solution

1. Every step that begins writes a top-level `node.start`, batched sub-workflow hosts included (plan D1).
2. The meta line records `step_identity`; preflight compares only the restored steps (plus a paused
   approval step), the start step and the resume point's presence, and refuses naming what changed
   (D3, D4, D9). Old traces keep today's behaviour (D6).
3. One runner pre-meta primitive (prepare + validate + strip + compile) shared by `plan()`, the UI
   resume pre-flight and `/api/run`'s pre-flight — an edited workflow with a validator-only error is
   refused before spawn now that resume no longer needs `--force` to reach it (D11).

## Requirements

- Every AFTER row of `implementation/show-before-code.md` (rows 1–16), through `pflow resume`,
  `--dry-run`, and `POST /api/resume`.
- The refusal's JSON carries `changed_steps`, `new_start`, `resume_point`; the 409 keeps `refusal`
  `stale_workflow` and `hash_known`; `--force` stays one flag waiving both refusals (D7).
- The side-effect confirmation for a batched `workflow` host is decided by the real `node.start` proof
  on a 2.9.0 trace and by the carve-out on older traces (D1b).
- Trace format 2.9.0; no other on-disk shape changes beyond the batched host's `node.start`.
- Guide, CLI reference, and instruction files state the rule and its two accepted limits.

## Verification

- Tests per plan §5 P1–P3 (each phase's named failure scenarios, mutation-verified where marked).
- All 16 rows re-executed through `uv run pflow` on the branch, observed output in the progress log;
  the web refusal for rows 3 and 14 driven via `screenshot-pflow-web-ui`.
- Task-159 baseline: no drift beyond the base's recorded set.

## Dependencies

None blocking. Trace-format contact → lane A, plan-mode deep-review mandatory, serialized with any
other trace-format or engine change. Read first: `.taskmaster/tasks/task_179/task-review.md`
(resume's integration contract), ADR-0010 (resume from the trace), issue #690 in full (body +
comments) and its lane PR.

## References

- Issue #690 — stays open as this task's governing issue; closes with it.
- `src/pflow/execution/resume_preflight.py`, `src/pflow/runtime/resume_source.py`,
  `src/pflow/core/trace_io.py`, `src/pflow/runtime/workflow_trace.py`.
