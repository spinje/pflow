# Braindump: Task 164 plan-session handoff (2026-07-04)

_For the agent implementing `implementation-plan.md`. The WHAT is fully written down — spec
(task-164.md, Decisions 1–9), plan (implementation/implementation-plan.md), ADR-0010 (amended),
BRIEF.md, CONTEXT.md (new terms: Resume/Attempt/Restored). This captures ONLY what those don't:
how the plan got its shape, what was verified vs. assumed, and what I'd want to know on day one._

## Where things stand

The plan is **post-review**. Six specialist review agents (review-plan, silent-failures,
impact-completeness, feature-interactions, validation-consistency, agent-ux) reviewed it
2026-07-04; 12 confirmed findings (1 Critical) were **already folded into the plan text** — the
plan you're reading is the fixed version. There is no separate findings doc; the plan IS the
record. Do not re-litigate choices that look oddly specific (the §B vocabulary rule, the
top-level-only `node.start` scan, the `except CompilationError` wraps) — each one is a review
finding with evidence behind it.

Before the review, seven `pflow-codebase-searcher` audits verified every mechanic against HEAD
`1d9c6b2c`. The plan's "Verified facts" section is their distillate. The audits themselves live
only in the dead conversation — anything not in the plan/spec was judged not worth carrying.

## User's mental model (their words)

- *"We should prioritize simplicity of the FINAL code, not how easy it is to get there."*
- *"whats the right solution that the top 10% of codebases similar to this one would implement,
  have we considered it yet?"* — immediately qualified: *"this isnt about over-engineering…
  this is about more simple code that is optimized for AI agents to understand and add features
  to."* This lens killed the run-query glob consolidation (behavior change dressed as
  extraction) and picked "restored ≡ cached + one boolean field" over minting a new status.
- *"The plan should be made so another ai agent can implement it in isolation without any
  ambiguity."* — that's you. If you hit a decision the plan doesn't make, that's a plan bug:
  surface it, don't quietly pick.
- The user personally picked (via explicit question round): **self-contained attempt traces**
  (Decision 6) and **incomplete-arm IN, narrow shape** (Decision 7). Decisions 8–9 were my
  session calls they accepted. All nine are locked — the user reacts badly to re-litigating
  ledger items.
- Subagent rule: use `pflow-codebase-searcher` (never Explore/general-purpose) for verification;
  parallel launches. Standing model rule from the earlier session: never override a subagent to
  `fable`; `sonnet` only for easy mechanical lookups.

## Why the load-bearing choices look the way they do (not written elsewhere)

- **Decision 6 was MY discovery, not in the spec**: the spec locked lineage but never said what
  an attempt trace *contains*. The `--only`-poisoning chain (successful resume → newest
  success trace → `load_full_run_events` picks it → missing upstream events) is the reason
  restored events get re-recorded. The Phase-2 "poisoning regression" test is the one test I'd
  refuse to ship without.
- **"restored = cached + flag" is deliberate mild dishonesty**: the UI will label restored
  nodes "cached". Evaluated and accepted — unknown status strings are *silently dropped* by the
  frontend (`RUN_STATUSES` allowlist, events.ts:60), so an honest `"restored"` status renders as
  nothing at all unless you also touch `RUN_STATUSES` + `NodeStatus` + tailer. v1 does NOT do
  that. If someone later wants an honest label, that's the exact two-file frontend change.
- **ResumeSource rides `WorkflowRunner.run(..., resume_source=)` as a kwarg**, not RunnerConfig —
  that's the Task-125 `gate_resolver` precedent (RunnerConfig stays execution-config-only and
  primitive-typed). Searcher B suggested primitives-through-config; I overrode toward the kwarg
  because the loader must run CLI-side anyway (confirm policy needs K before the run starts).
- **Bare `pflow resume` (no TARGET) errors** — deliberate, in the plan's out-of-scope list. The
  spec's "bare = newest failed" reading is satisfied by `pflow resume <workflow>`.

## NEEDS VERIFICATION (known unverified residue — check during the relevant phase)

- **`resolve_workflow` symlink canonicalization**: the "absolute path" contract is documented
  (`execution/CLAUDE.md`) but nobody opened `workflow_resolver.py` to check `resolve()` vs
  `abspath` — matters only for byte-identity of `workflow_path` across symlinked invocations.
- **IR edge representation for §E step 4** (default-action edges + the `has_dynamic` flag): the
  plan says use IR edges IF they expose the distinction cleanly, else the compiled graph. Nobody
  confirmed the IR shape. The compiled-graph fallback is always correct — don't guess from bare
  edge counts.
- **`events` shape for `ResumeSource.events`**: mirror `load_snapshot_or_raise`'s extraction
  (it returns the trace's top-level `nodes` events, exactly what `seed_snapshot_into_shared` /
  `final_events_by_node` consume). ASSUMPTION: `load_trace_file(path)["nodes"]` is that list —
  read `load_snapshot_or_raise` first and copy its extraction verbatim.
- **Whether any aggregate counts cached nodes** (a `nodes_cached`-like field): the audits listed
  only `nodes_executed`/`nodes_failed`/cost. If you find a cached-count stat while editing
  `_aggregates`, decide whether restored events should be excluded there too (probably yes).
- **Which `run.py` helper resume.py reuses** (§E step 7): the plan deliberately leaves "which
  helper is the minimal reusable seam" open — `run.py`'s execution/output helper region
  (~:250-320) wasn't mapped precisely enough. Read it before writing resume.py; extract rather
  than duplicate output routing.
- **Restored re-record + blob interning**: `node_output` flows through the interning
  `_flush_line`, re-declaring blobs in the NEW trace with a fresh per-run `declared` set — that
  is what self-containment wants. ASSUMPTION not explicitly tested; the Phase-2
  resume-of-a-resume test covers it end-to-end.

## Traps I'd warn myself about

- **The trace event `node_type` is a CLASS name** (`"LLMNode"`). This nearly shipped as the
  side-effect gate's input (two review agents flagged it as the Critical). The §B vocabulary
  rule exists because of this; the Phase-3 "llm silent" test is its pin. If you touch anything
  typed `node_type`, ask which vocabulary you're holding.
- **BRIEF pre-flight item 4 (UI tolerance) is already largely done**: the audits confirmed
  `resumed_from` meta is tolerated end-to-end and `cached` status renders. What remains is only
  the Phase-2 real-browser check (`make ui-build` + restart — web/ changes are invisible
  without it, a repeated false-failure source per the 173 review).
- **Phases are commit milestones inside ONE PR** (project convention from the planner-mirror
  session), not separate PRs. Phase 0 must be a genuinely pure refactor commit — parity suites
  green *unmodified* is the gate.
- **Mutation-verify with a temporary Edit + revert, never `git stash`** (burned Task 125 twice).
  And after delegating edits to a subagent, check `git diff` — test-writer agents have
  `git checkout`'d uncommitted files mid-task before (173 review, process note).
- **You are the sole engine toucher** (standing serialization rule for `runtime/engine/`).
  Task 170 (template language, heavy `plan.py`) is NOT in flight; if it starts, coordinate merge
  order.
- The gate-stopped refusal arm reads raw `kind:"gate"` lines — remember `load_trace_file`
  cannot see them (nor `node.start`); every "raw" need in the loader goes through the new local
  `_iter_raw_trace_lines`, nothing else.

## UNEXPLORED / CONSIDER

- UNEXPLORED: **trace retention** — resume multiplies traces per logical execution and GH #542
  (unbounded `~/.pflow/debug` growth) predates this. Not 164's problem, but resume makes it
  worse; don't be surprised if the user raises it mid-implementation.
- CONSIDER: the failed-run resume-hint line (§E step 10) touches the error formatter — check
  how MCP's failure output shares that path so the hint doesn't leak into MCP results where
  `pflow resume` isn't runnable (MCP runs have no trace anyway; gate on trace existence, which
  the plan already says).
- MIGHT MATTER: `pflow resume` while ANOTHER run of the same workflow is live (not the source
  run — a different one). The liveness probe checks only the source trace's lock. Concurrent
  runs of one workflow are normal (CONTEXT.md); a resume racing a live sibling run is fine by
  design (separate traces), but the superseded-check scan will full-parse the live sibling's
  incomplete file — harmless, just don't "fix" it into an error.
- CONSIDER: Task 171 lands next on this exact surface. When shaping `load_resume_source`'s
  status arms, keep the `paused` insertion point obvious (one added arm, entry =
  `paused_node_id`) — 171's designer will read your loader first.

## For the next agent

Read in this order: task-164.md (Decisions ledger) → implementation-plan.md (fully) → BRIEF.md
(pre-flight + collision posture) → this file. The 125/172/173/175 task-reviews back the plan's
invariant checklist; open them only when touching their subsystem. Start with the pre-flight
baseline capture, then Phase 0's parity test BEFORE the extraction. The user's priority, in
one line: the simplest final code, zero ambiguity, no re-opened decisions.

> **Note to next agent**: Read this document fully before taking any action. When ready,
> confirm you've read and understood by summarizing the key points, then state you're ready
> to proceed.
