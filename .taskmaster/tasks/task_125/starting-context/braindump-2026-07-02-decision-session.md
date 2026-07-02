# Braindump: Task 125 — the 2026-07-02 decision session (pre-implementation)

> Written at the end of the multi-day session that refreshed the 125/164/171 specs, locked 125's
> start decisions, wrote ADR-0009, and drafted Task 176. This captures ONLY what is not in those
> files — read `task-125.md` first, then this. The other braindumps in this dir are a layered
> history, not repetition: `braindump-openclaw-discussion` (2026-02, strategy — technically
> superseded), `braindump-escalation-and-resume-substrate` (2026-06-02 — **read it**: the
> escalation-signal landmine + the 4-need decomposition), `braindump-2026-06-12-split-session`
> (MCP parity, mock-the-UX-first, the `--auto-approve` footgun's origin).

## State ledger (implementation NOT started)

- Specs 125/164/171 refreshed 2026-07-02 against `main` (four parallel fable code-audits) and then
  **personally verified by full reads** — 9 residual errors found and fixed *after* the subagent
  edits (see process norms below for why that matters).
- 125 decisions **1–3 LOCKED** by the owner (marked in the spec's decision ledger): `gate` event IN
  scope; `--auto-approve=<node-id>` scoped per-node; batch-host `approval:` rejected at validation.
  Decisions **4–5 still open-with-rec** (non-TTY failure timing; denial semantics) — confirm at
  plan time.
- **ADR-0009** (approval surfaces = out-of-process bridges) written and accepted. The ADR for
  trace-as-checkpoint + attempt chains is **deliberately deferred to Task 164** — write it there
  (as ADR-0010) once the owner confirms the fidelity + checkpoint decisions at 164/171 start.
- Task 176 draft exists (web bridge, post-171, deliberately thin). Roadmap updated:
  125 → 164 → 171 → 176 → 174.
- **The next concrete action that never happened: create the 125 worktree**
  (`git-worktree-task-creator`, `work_type=task`, copy a kickoff-brief scratchpad — the
  established pattern is `scratchpads/task-173-live-overlay/kickoff-brief.md` and the task-175
  brief).

## User's mental model (verbatim — these govern every fork)

- THE principle, stated twice: *"We should prioritize simplicity of the FINAL code, not how easy it
  is to get there. When in doubt we should ask ourselves whats the right solution that the top 10%
  of codebases similar to this one would implement, have we considered it yet?"* — explicitly NOT
  overfitting/overengineering: *"simple code that is optimized for AI agents to understand and add
  features to."* This is how `node.start` got un-deferred in Task 173 and how the ApprovalSurface
  ABC got rejected here. Apply it at every fork, and cite it when proposing.
- Subagent models: *"never use sonnet 4.6, the alternatives are sonnet 5 or fable"* → in this
  harness use **fable** for delegated work.
- Delegation norm (learned the hard way): *"you should have probably done this by yourself, make
  sure to verify everything when done."* Judgment-heavy edits where the context lives in your head
  → do directly. If you delegate, **personally full-read the output** — every error found in the
  delegated spec edits was cross-file consistency or fact-location conflation, i.e. things only the
  context-holder catches.
- Before committing to a plan the owner asks step-back questions (*"is there any overarching seam
  we haven't considered? any part that makes you uneasy?"*). Do the uneasiness audit **before**
  they ask.

## Rationales the owner actually approved on (plain versions, stronger than the spec text)

- **`--auto-approve` scoping:** a blanket flag is a master key — an agent that hits a blocked gate
  will learn "add `--auto-approve` and it works" and reflexively bypass every gate thereafter.
  Per-node naming makes pre-approval deliberate and auditable. *The friction is the point.* Resist
  adding an `--auto-approve-all` later without the owner.
- **Batch rejection:** an honest validation error beats a misleading unresolved-`${item}` preview;
  "gate the step before or after the batch — that's usually where you want it anyway"
  (`gather-files → summarize-each (batch) → send-report ← gate HERE`).
- **Gate event:** "the trace event IS the serialization test" for the exact payload 171 persists —
  that's the reason it's in scope now, not overlay cosmetics.

## Hard-won facts NOT in any file

- The four 2026-07-02 investigation fact-sheets exist **only in the session transcript**; the specs
  carry distillates. Two leftovers worth keeping: (a) the TTY prompt's design anchor is
  **`terraform apply`** (interactive `[y/N]`, explicit auto-approve flag, hard error in non-TTY
  without it) — use it when designing the prompt UX; (b) on the cache-hit path the engine fires
  `node_start`+`node_cached` callbacks from the **main thread** (`handle_cached_execution`) —
  relevant only if the gate ever interacts with progress callbacks (it shouldn't: gates sit after
  the cache-hit early-return by design).
- Recurring LLM error-attractor: `is_trace_locked` (probe, `ui/run_tailer.py:135`) vs
  `_lock_trace_handle` (writer flock, `workflow_trace.py:74-90`) — **two independent** editor
  agents conflated them. If any doc says `is_trace_locked` lives in `workflow_trace.py`, it's wrong.
- Spec line refs were refreshed 2026-07-02 but this area of `main` absorbs ~20 merges/week.
  Re-verify the engine-seam refs (`engine.py:994 / 1031 / 1045-1086 / 1100-1131`) before editing.

## The real design gap for 125 v1: the escalation trigger

**ASSUMPTION — surface at plan time, do not silently resolve:** action-approval is fully designed;
decision-escalation's *trigger* is not. The spec says "an agent-returned escalation marker," but
Task 99 (the clean `escalate_to_human` tool mechanism) is **unbuilt**, the 2026-06-02 braindump
warns the obvious signal mechanism is *"known-broken"*, and the decision-**feedback** loop (how the
human's choice re-enters the run) is undesigned. Honest read: v1 = action-approval complete +
escalation only if a minimal structured-output marker (e.g. from the claude-code node) stays cheap;
otherwise propose splitting escalation's trigger design into its own increment. **Do not let
escalation quietly double the task.**

## Deferred-by-design (don't "fix" these)

No `ApprovalSurface` ABC (ADR-0009); no blanket `--auto-approve`; no batch gates; no web/Slack
approval (Task 176 / later); no `on_pause` hook; no tokens or serialization code (that re-merges
the 171 split — the split braindump's words: *"stop"*); `route_action` stays pure (the gate is
pre-exec, loop-guard altitude).

## Checklist for the implementing agent (order matters)

1. **Pre-flight:** re-verify spec line refs against `main`; confirm the UI tailer + frontend
   tolerate an unknown event `kind` (`run_tailer.py` + web) — the gate-event precondition.
2. **Mock the prompt UX + the `GateRequest` shape and SHOW the owner before coding** (CLAUDE.md
   show-before-code norm + the split-braindump's "mock the gate prompt UX first").
3. Confirm open decisions **4–5** with the owner at plan time.
4. **Parity discipline:** dry-run "would pause" via `NodeConfig` (planner-free, Task 166
   precedent); drift-suite pin written first and **mutation-verified** (recipe in task-164.md's
   parity plan / PR #505).
5. **MCP parity:** add the gate-fails-loudly case to `test_cli_mcp_parity.py` (split braindump).
6. `make test`/`make check` **baseline before changes**; deep-review battery before the PR.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
