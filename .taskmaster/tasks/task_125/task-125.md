# Task 125: Human-in-the-Loop Approval Gates

## Description

Add pause/resume capability to pflow workflows so execution halts at designated steps for human approval before continuing. Makes pflow trustworthy for workflows that take real-world actions (send messages, create PRs, deploy, delete).

> **This spec was extended after the original draft** (which framed HITL purely as action-approval) by the Task 163 plan-to-code harness build. That work surfaced a second, arguably *primary*, use case — **decision-escalation** — and revealed that the resume machinery is the same primitive as a planned failure-resume feature, ~half of which already ships via `--only`. The original action-approval design below is preserved; the new sections (Two Use Cases, Architecture, Reuse, Known Hard Problems, Phasing) are the refinement. Code claims are verified against `main` (2026-06) with `file:line` refs.

## Status
not started

## Priority

high

## Problem

pflow workflows execute start-to-finish with no ability to pause. Any workflow that takes action on the user's behalf — posting to Slack, creating a GitHub issue, sending an email via MCP — runs without a checkpoint. Users can't review what's about to happen before it happens.

This is a trust barrier. Users won't put pflow in charge of real-world actions if they can't intervene. It also blocks adoption in contexts where agents operate with increasing autonomy (OpenClaw-style personal assistants, long-running agents) where a human approval step is the difference between useful and dangerous.

Lobster (OpenClaw's workflow engine, 25 days old) already has approval gates with durable resume tokens. This is table stakes for any workflow system that touches external services.

## Two Use Cases: Action-Approval and Decision-Escalation

The original framing (above) is **action-approval**: an author declares a gate on a known side-effecting node, and a human approves the action before it fires. Building the Task 163 agentic coding harness surfaced a second, arguably *primary*, use case the original spec missed: **decision-escalation**.

In an autonomous plan→code harness, the agent regularly discovers — *while writing the code* — that the plan made a wrong or missing assumption with lasting impact (e.g. "implementing this cleanly requires changing the data model in a way that touches three other features"). Today its only options are bad: silently pick one (a lasting architectural decision made by an agent guessing) or stop dead. Escalation gives it a third: **halt, surface the decision with full context, let the human decide, then continue from that decision.** This is the difference between trusting the harness with real work and not. The user's position: without it, the agentic workflow probably can't ship.

Escalation is the **runtime complement to static plan review**. The harness's `plan-review-fix` stage hardens the plan *before* implementation, but a whole class of gaps is only discoverable *during* implementation — you can't see the data-model conflict until you try to write the code. Escalation is where those surface.

| | Action-approval (original) | Decision-escalation (new) |
|---|---|---|
| **Trigger** | Author-declared (`approval: required`), known in advance | Agent-raised at runtime, unpredictable |
| **What surfaces** | Resolved node inputs ("about to send X") | A decision: the fork, options, tradeoffs, the agent's recommendation, why it can't resolve it alone |
| **Human action** | Approve / deny a known action | Make a design call that feeds back into the work |
| **Frequency** | Predictable (you know where the gates are) | Unpredictable (0..N per run) |

Both are faces of one primitive — a human-decision gate — and should share one decision surface (CLI now, the planned web UI later). They differ only in trigger and payload. **Calibration is the hard part of escalation** — see Known Hard Problems.

## Solution

A new `approval` parameter on any node that halts execution before the node runs, shows the user what's about to happen (resolved inputs), and waits for approval.

**This task is the BLOCKING mode only** (split 2026-06-12, see Phasing): interactive TTY prompt, `[y/N]` style, human present during the run — pause in-process, decide live, continue. The non-interactive mode (durable resume token, answer hours later via `pflow resume <token>`) is **Task 171**, which rides Task 164's checkpoint→restore→continue substrate.

## Architecture: One Checkpoint/Resume Substrate, Three Triggers

Action-approval, decision-escalation, and **failure-resume** (resume a workflow from a failed `llm`/`http`/`mcp`/`claude-code` node after a timeout, re-running from that node) are the *same primitive* under different triggers:

> **checkpoint** (persist completed state + position) → **restore** (reconstruct shared store, skip completed) → **continue** (run from the re-entry node onward)

Design 125 as that general primitive with pluggable triggers — **not** as approval-only, then retrofit. (Verified: no resume/checkpoint capability exists today beyond `--only`; see Reuse.)

| Trigger | Stop point | Controlled? | Notes |
|---|---|---|---|
| Action-approval (declared) | *Before* the node | Yes — no partial side-effect | original framing |
| Decision-escalation (agent-raised) | At a decision the agent returns | Yes — agent exits cleanly | the Task 163 driver |
| Failure-resume (timeout/error) | *At* the failed node | **No — node may have partially run** | the idempotency problem (see Hard Problems) |

**Failure-resume is a sibling feature, not in this task's scope** — it has no human in the loop, and its hard part (per-node-type idempotency) is distinct. It is captured here only because it shares this substrate and should be designed *for*, not retrofitted; it is specced separately as **Task 164 (Resume Workflow From a Failed Node)**. Closest prior art: **Task 73 "Checkpoint Persistence for External Agent Repair"** — deprecated when Task 92 removed the repair system it was built around, but its side-effect/idempotency analysis still applies. Read `.taskmaster/tasks/task_73/` for failure-resume's idempotency design.

## Reuse: What Already Exists (Verified 2026-06)

The braindump (`starting-context/braindump-openclaw-discussion.md`) assumed a "wrapper chain" and an untested shared-store serializer. Both assumptions are now resolved against `main`.

**The reconstruction half of resume already ships, battle-tested, via the `--only` snapshot machinery (issue #443).** This is the load-bearing, easy-to-get-wrong part — reuse it; don't reinvent serialization.
- `seed_snapshot_into_shared(shared, events, exclude=target)` (`src/pflow/runtime/workflow_trace.py:347`) — rebuilds the shared store from a prior run's trace, scoped to nodes that ran *before* the target (templates can only reach earlier steps), reserved-key-filtered, never seeding the target itself. Restored nodes recorded in `__execution__["restored_nodes"]`.
- `load_snapshot_or_raise` / `load_full_run_events` (`workflow_trace.py:191`, `:179`) — single "no usable snapshot → `OnlySnapshotMissingError`" decision.
- `node_state.py` — where-did-it-fail query API (`shared[id]` = succeeded, `shared["__failures__"][id]` = failed, neither = didn't run; `get_node_status → SUCCEEDED/FAILED/ABSENT`).
- Node-level retry (`src/pflow/core/node.py:76`, `max_retries`/`wait`) already handles *transient* timeouts in-process (claude-code `max_retries=2`, llm retries on `LLMTransientError`). Resume is the **after-retries-exhausted** case, not a replacement for retry.

**What's genuinely missing (the new work, shared by all triggers):**
- **Resume-and-continue.** `--only` runs the target node and *stops* — it early-returns into `_run_only_snapshot` and never follows `.successors` (`engine.py:416-428`). Resume needs *restore + run node K **and everything after**.* This is the single biggest piece none of the triggers have yet.
- **A pause/escalation trigger + a writable resume-state file.** `--only` only *reads* a frozen trace; nothing today *writes* a resumable live-state checkpoint or halts mid-run.
- **A resume-scoped snapshot policy.** The loader currently *rejects* `failed` traces (allowlist `success`/`degraded`, `workflow_trace.py:179-188`) because re-seeding from a partial run is unsafe *in general*. But for failure-resume the nodes *before* failed node K succeeded, so their outputs are valid — and `seed_snapshot_into_shared(exclude=K)` already scopes to exactly those. So this is a resume-scoped loader that accepts a failed trace and treats the failed node as the target, **not** a rewrite. (A graceful failure *does* persist a trace — `final_status:"failed"` + `failed_node_ids`, saved in the CLI `finally` at `cli/commands/run.py:294-298` — but a hard kill / `KeyboardInterrupt` does not save. Scope failure-resume to graceful failures.)

**Stale spec alert (corrected in Implementation Notes):** the original notes propose an `ApprovalWrapper` in an `InstrumentedWrapper → BatchWrapper → …` chain. **That chain was removed by the Task 135/138 engine redesign** — the engine is now wrapper-free, with caching/tracing/batch/namespacing/template-resolution handled inline in `WorkflowEngine._execute_node` + `runtime/engine/instrumentation.py`.

## Known Hard Problems

- **Node idempotency (failure-resume).** Re-running a node that *partially* side-effected (an http POST that sent but timed out on the response, an mcp tool that created a resource then dropped, a claude-code node that already committed) double-fires. Action-approval and escalation sidestep this (they stop *before* the node). **Reuse the existing side-effect taxonomy:** `_default_cache_for_node_type` already classifies which node types side-effect (only `llm` caches by default; `http`/`mcp`/`shell`/`claude-code` do not) — the same classification tells you which nodes are resume-safe vs. need a guard/confirm before re-running.
- **Escalation calibration (the make-or-break).** The agent must escalate *only* genuine lasting-impact forks, never punt minor choices. Too eager defeats the autonomy that makes the harness worth having; too reluctant is the silent-bad-decision nightmare. Same discipline as Task 163's review adjudication ("a finding is a claim to be verified, not obeyed") — a prompt-design problem, not a mechanism problem.
- **Lossy serialization.** The trace serializes with `json.dump(..., default=str)` (`workflow_trace.py:850`) — non-JSON-native values resurrect as their `str()`. Faithful resume needs lossless-enough state, or a documented constraint that resumable shared values must be JSON-native (the braindump's open serializability question, now concretely scoped).
- **Nested / sub-workflow resume.** Dotted `--only parent.child` is rejected on every live path today (post-PR #505: the shared `validate_only_target` in `engine.py`, called by both engine and planner); the child plumbing (`_pflow_child_only_node`) exists but is **dormant** (only write site is always passed `None`), parked under #443 as a deferred follow-up. Task 163 is a *tree* of sub-workflows, so pausing/escalating/resuming *inside* a child is real and not yet covered.
- **Escalation raised inside a PARALLEL batch worker.** A sub-workflow child running as a parallel batch item executes on a worker thread whose progress events are **buffered** (per-worker transcript pattern, `batch_executor.py` — workers must not touch the real `OutputController`); a worker thread cannot prompt a TTY, and pausing one item while siblings run concurrently has no defined semantics. The spec's batch section below covers a *declared* gate on the batch node itself (whole-batch approval) — it does NOT cover an *agent-raised* escalation surfacing from inside a parallel item. v1: reject/define-away this combination explicitly at validation (e.g. escalation inside a parallel batch fails the item with a clear error) rather than handling it; sequential batch + top-level nodes are the supported v1 surface.

## Dry-run parity & engine placement (added 2026-06-11 — from the planner-mirror refactor, issue #504 / PR #505)

A gate is a new per-node walk outcome the dry-run planner must surface, or `--dry-run` lies
about exactly the thing gates exist for ("this run performs no side effects without asking" —
a plan that shows a gated node as plain `execute` is a parity lie). The drift record that
motivated PR #505 (8–9 of 10 lockstep commits; 4 shipped parity bugs; the Task 162 under-report
that passed the whole drift suite) says: design this in from day one, via the shared layer.

- **Put the gate in compile-time metadata so the planner sees it for free.** `approval:` lands
  on `NodeConfig` (like `loop_config`/`cache_enabled`); anything `plan_node()` can read, the
  planner inherits with zero `plan.py` work (Task 166 precedent — loop carry cost zero plan.py
  edits because it landed behind the shared seam). Agent-raised escalation is runtime-only and
  inherently unpredictable — the planner's job there is at most an annotation ("may escalate"),
  not a prediction; record that asymmetry explicitly.
- **Follow the documented planner extension recipe** (`execution/CLAUDE.md` → walker shape):
  new `PlanEntry.status` (or annotation) → entry builder in `_plan_standard_node` → `_classify`
  case → `_advance` match arm, in that order. `--dry-run` output shows "would pause for
  approval" on gated nodes; add that to Verification.
- **Do NOT model the pause as a `RouteKind`.** PR #505 extracted `route_action` as the pure
  post-execution routing kernel (successor match > clean termination > routing error). A gate
  fires *before* the node runs — same altitude as the loop guard, which matches the inline
  `_execute_node` placement already specified in Implementation Notes. Keep the kernel pure.
- **Gate bookkeeping goes in the shared layer.** Any new `__execution__` key (gate state; pause
  position is Task 171's) extends `new_execution_state()` in `node_state.py` — the single source
  PR #505 established; the planner's scratch store seeds via the same `initialize_execution_state`,
  so a hand-mirrored literal is no longer possible *unless someone re-forks it. Don't.* (Applies
  equally to Tasks 164/171.)
- **Parity test first, mutation-verified**: when the gate status lands, add the drift-suite pin
  ("plan says would-pause ⟺ engine pauses") and mutation-check it (re-fork one side, confirm it
  fails) before trusting it — the PR #505 batch-shape test demonstrated 43 green tests can miss
  a visibly drifted mirror.

## Phasing → split into separate tasks (2026-06-12)

The original phasing (blocking vs durable inside one task) implied a build-order sandwich
(125-blocking → 164 → 125-durable) that contradicts the one-PR-per-task convention. Resolved
by splitting:

- **THIS task = blocking only** — human present during the run. Gate fires (or agent escalates) → run pauses → human decides live (TTY now, web UI later) → continue. Needs the gate primitive + (for escalation) an agent-raised trigger + a decision payload. **No durable tokens or cross-process serialization.** This is the slice that gates shipping the agentic harness — and it is the cheap one.
- **Task 171 = durable** — answer hours/days later: resume tokens, `~/.pflow/resume/` state, non-TTY gates. Rides Task 164's substrate as a thin trigger. The durable design content originally drafted here now lives in `task-171.md`.

Build order: **125 (this) → 164 → 171**.

## Design Decisions

- **Parameter-level, not node-type-level**: `approval: required` is a parameter on any existing node type (`mcp`, `shell`, `http`, `llm`, etc.), not a separate `approval` node type. This keeps the node count unchanged and makes it composable — you add approval to an existing step, not insert a new step.
- **Preview resolved inputs**: At the pause point, show the user the actual resolved template values (e.g., "About to send Slack message to #releases: 'v0.9.0 released with 3 features'"), not the raw template (`${create-summary.result}`). The user needs to approve *what will happen*, not the abstract definition.
- **Durable-token design moved to Task 171** (self-contained tokens, `~/.pflow/resume/` state, TTL/cleanup — see `task-171.md` Design Decisions).
- **Engine integration is wrapper-free** (corrects the original "ApprovalWrapper in a wrapper chain" plan, now obsolete — Task 135/138 removed the wrapper chain): the pause/preview check belongs inline in `WorkflowEngine._execute_node`, after template resolution (so the preview shows resolved values) and before the node's `exec`, alongside the existing inline cache/trace/batch handling. Node implementations stay untouched. See Implementation Notes.
- **General primitive, not approval-only**: design checkpoint → restore → continue once, with action-approval / decision-escalation / failure-resume as triggers over it (see Architecture). Approval-only-then-retrofit would rebuild the same substrate three times. Post-split this means: the substrate is Task 164's; this task's gate primitive and decision payload must be designed so 171 can persist them unchanged.
- **One decision surface for CLI and UI**: the human-decision payload (action preview *or* decision + options + tradeoffs + recommendation) must render in both the terminal prompt and the planned web UI (Task 155 → visual gate). Design it as structured data, not a printed string — this is also what makes Task 171's durable tokens a thin layer (it persists the same payload).
- **Blocking before durable**: ship the blocking gate (human present) first; durable is Task 171 (see Phasing).

## Dependencies

Additive — no existing feature needs modification — but several relationships matter:
- **Reuses today's `--only` snapshot machinery** (`seed_snapshot_into_shared` / `load_snapshot_or_raise`, issue #443) as the reconstruction half of resume. See Reuse.
- **Task 155 (Graph Model → web UI)** — the decision surface should render as a visual gate, not just a CLI prompt. Design the payload for both.
- **Task 99 (Expose pflow Tools to Claude Code Node)** — the clean mechanism for an agent to *raise* an escalation is a pflow-provided tool (e.g. `escalate_to_human(...)`); under the hood it writes an escalation artifact + returns, fitting Task 163's fork model.
- **Task 164 (Resume Workflow From a Failed Node)** — the sibling feature over the same substrate. Build order: **125 (this, blocking) → 164 (builds the substrate) → 171 (durable tokens/non-TTY gates)**. Prior art: **Task 73** (deprecated). See Architecture.
- **Task 171 (Durable Resume Tokens & Non-TTY Gates)** — the durable phase carved out of this task (2026-06-12); persists this task's gate/decision payload across processes via 164's substrate. The decision payload designed here must survive serialization unchanged.
- **Stale**: the original wrapper-chain integration plan predates the Task 135/138 engine redesign and is corrected in Reuse + Implementation Notes.

## Implementation Notes

### Engine integration (wrapper-free — corrected)

The original plan slotted an `ApprovalWrapper` into an `InstrumentedWrapper → BatchWrapper → NamespacedWrapper → TemplateAwareWrapper` chain. **That chain no longer exists** — the Task 135/138 redesign made the engine wrapper-free; metrics/cache/trace/batch/namespacing/template-resolution are now handled inline by `WorkflowEngine._execute_node` (`src/pflow/runtime/engine/engine.py`) and `runtime/engine/instrumentation.py`.

So the gate is an **inline check in `_execute_node`**, placed *after* template resolution (so the preview shows resolved values — the actual Slack text, not `${...}`) and *before* the node's `exec`. The same hook serves both triggers: a declared `approval: required` (action-approval) and an agent-returned escalation marker (decision-escalation) both pause at this point. Confirm exact placement against the current `_execute_node` step order (the engine CLAUDE.md documents steps 1–17.6). Node implementations stay untouched either way.

### State serialization → Task 171

The pause-time checkpoint (shared-store snapshot, pause position, `~/.pflow/resume/` state,
token generation) and the token-resume flow moved to `task-171.md` (Solution + Requirements).
This task's blocking gate holds state in-process only.

### Batch interaction

If a batch node has `approval: required`:
- Approval applies to the **batch as a whole**, not per-item. Showing 70 individual approval prompts defeats the purpose.
- The preview should show: "About to process 70 items with node 'classify-commits' (type: llm). First 3 items: [preview]"

### Edge cases

- **Multiple approval gates in one workflow**: Each gate pauses independently (in-process). After approving gate 1, execution continues until gate 2 (or completion).
- **Non-TTY invocation with a gate present**: blocking mode cannot prompt. Until Task 171 ships tokens, this must fail loudly and immediately with an agent-actionable error (or honor `--auto-approve`) — never hang waiting for input that can't arrive.
- Cross-process edge cases (workflow changed between pause and resume, token TTL, `pflow resume list`) → Task 171.

### CLI surface

```bash
# Workflow with approval gate, human at TTY: pauses, prompts inline
pflow my-workflow param=value
# Paused at 'notify-slack'. About to send: "..." Approve? [y/N]

# Auto-approve for CI/testing
pflow my-workflow param=value --auto-approve
```

Token-based resume (`pflow resume <token>`, `pflow resume list`) → Task 171. The `pflow resume`
command name is shared with Task 164's failure-resume — resolve the surface jointly (flagged in
both task-164.md and task-171.md).

### Markdown format

```markdown
### notify-slack

Post the release summary to Slack.

- type: mcp-composio-slack-SLACK_SEND_MESSAGE
- channel: ${slack_channel}
- markdown_text: ${create-summary.result}
- approval: required
```

## Verification

- **Basic gate**: Workflow with `approval: required` on a node halts before that node, displays preview, waits for input
- **Deny flow**: Denied approval exits cleanly with message, no side effects
- **Multiple gates**: Workflow with 2+ approval gates pauses at each in sequence (in-process)
- **Batch + approval**: Batch node with approval shows batch preview, not per-item prompts
- **TTY mode**: Interactive prompt works in terminal
- **Non-TTY + gate fails loudly**: a gate in a non-TTY run (pre-Task-171) errors immediately with an actionable message (or honors `--auto-approve`) — never hangs
- **Validation**: `pflow --validate-only` recognizes `approval` as a valid parameter (no unknown-param warning)

(Token resume flow, stale-resume warning, non-TTY token emission, post-resume shared-store
integrity → Task 171 Verification.)
- **Dry-run parity**: `--dry-run` shows gated nodes as "would pause for approval" (not plain execute); pinned by a drift-suite test ("plan says would-pause ⟺ engine pauses"), mutation-verified
- **Parallel-batch escalation rejected loudly**: an escalation raised inside a parallel batch item produces the defined v1 error, never a hang or a silent skip

### Decision-escalation (new use case)

- **Escalation gate**: an agent that returns an escalation marker halts the run, surfaces the decision (options / tradeoffs / recommendation), and on a human choice continues from that decision (written back to the plan / progress log) without re-running completed work
- **Escalation calibration**: a planted genuine hard decision escalates; a routine minor choice does NOT escalate (the agent decides it and logs it)
- **Blocking path (no durable resume)**: with the human present, escalate → decide → continue works in a single process without writing a resume token
- **Decision payload is structured**: the surfaced decision is parseable data (not a printed string), so the same payload can render in a CLI prompt and a future web UI

### Failure-resume (sibling feature — verify if/when built)

- **Graceful failure persists a snapshot**: a node timeout/exception leaves a `final_status:"failed"` trace with `failed_node_ids`; a resume-scoped load restores upstream-of-K and re-runs from K
- **Side-effect guard**: resuming into a side-effecting K (`http`/`mcp`/`claude-code`) does not double-fire — gated via the node-type side-effect taxonomy
- **Hard-kill caveat**: a SIGKILL / `KeyboardInterrupt` does NOT persist a trace (save is in the CLI `finally`), so failure-resume covers graceful failures only
