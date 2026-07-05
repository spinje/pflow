# Braindump: Task 171 planning session → implementation handoff

Everything WHAT/HOW lives in `implementation/implementation-plan.md`; chronology and decision
provenance in `implementation/progress-log.md`. This file is only what exists in no document:
the owner's mental model, reasoning that shaped the plan but didn't fit in it, trust
calibration, and traps.

## The owner's mental model (their words matter)

- The governing lens, verbatim: **"We should prioritize simplicity of the FINAL code, not how
  easy it is to get there"** and **"whats the right solution that the top 10% of codebases
  similar to this one would implement, have we considered it yet?"** — immediately qualified
  with: this is NOT about over-engineering, it's about **"more simple code that is optimized
  for AI agents to understand and add features to."** Apply this lens to every judgment call
  the plan leaves you; it has real teeth — it flipped the trace-source decision mid-session
  from the spec's recommended option to deleting the MCP special case (an option the spec
  never listed). If you find yourself adding a conditional, ask whether deleting a special
  case does the job instead.
- **Communication style**: the owner twice declined structured question dialogs and asked for
  plain-prose explanations in chat ("can you explain this simply", "explain these questions in
  chat simply with tradeoffs"). What landed was a concrete scenario ("a claude-code step that
  spends 10 minutes analyzing your codebase comes back asking A or B?") — not option matrices.
  If you need a decision from them, write it that way. They answer tersely ("option 1") once
  they understand.
- **Doc hygiene is an explicit owner requirement**: "DONT write the same thing twice and only
  write what will be valuable." Applies forward — when you update CLAUDE.md files in Phase 5,
  point to the plan/ADRs rather than restating them.

## Reasoning that shaped the plan but isn't spelled out in it

- **Why escalation restore-and-fold beat "uniform re-run" (decision 3)** — the argument that
  actually decided it, beyond cost: an agent re-run is nondeterministic and may raise a
  DIFFERENT question ("actually I found options C and D"), and the stored answer would then be
  auto-applied to a question the human never saw. A mismatch guard would have been needed
  either way, so re-run's "one loader rule" simplicity was illusory. Also CONTEXT.md's Resume
  definition ("every step that completed in the source Run is Restored") decides it on
  vocabulary grounds alone — the escalating node IS a completed step.
- **Why the engine-arm condition is `nested` + first-seen tag and NOT anything simpler** — the
  full elimination chain, so nobody "simplifies" it back: (1) `request.node_id ==
  config.node_id` dies to parent/child id collisions (author-chosen ids, `approve`/`review`
  collide easily); (2) `host_frame is None` fixes the plain sub-workflow collision but NOT the
  batch-hosted one (batch hosts keep `_host_frame=None` — engine.py comment ~1459); (3)
  collector descent-stack introspection fails because `ascend()` runs in WorkflowExecutor's
  finally BEFORE the parent arm sees the exception; (4) `is_run_scoped` fails because NEW-path
  child engines SHARE the run-scoped collector. Only "the root engine caught it first-hand"
  (nested flag + tag) survives every propagation shape. There are exactly two `WorkflowEngine(`
  construction sites — that's what makes the flag cheap.
- **Why flush-on-pause was rejected** (if anyone revisits trace-source): two hard blockers, not
  taste — gate lines are disk-only and NOT in `collector.events` (a late flush loses the
  pause record), and the whole-file writer was deliberately deleted in #531 (`save_to_file` is
  now an alias for streaming `finalize()`).
- **Why `gate_request` is duplicated onto the trailer** when the pause line already carries it:
  (a) ADR-0009 bridges read "the gate event / paused trailer" — a self-contained trailer means
  a bridge needs one tail-read, not a line scan; (b) `resume list` stays a cheap tail-read;
  (c) `ResumeSource` gets it from the flat dict for free. If a reviewer flags the duplication,
  that's the defense.
- **"Fold-and-complete" for final-step escalations was considered and rejected** — it would
  need an engine entry mode that executes nothing and just builds outputs (new machinery).
  Now moot: `_gate_pausable` means such escalations never emit a token in the first place.

## Trust calibration — where to point skepticism

- **Verified**: every file:line in the plan was checked against this worktree on 07-04/05 by
  four searcher agents + five review agents, with several independent cross-confirmations
  (e.g. the deny-consumption gap and the `trace_path` latent bug were each confirmed twice).
  The four resume suites pass (165) — run them before touching anything to confirm the tree
  is still at that state.
- **CRITICAL STALENESS WARNING**: the plan's `workflow_trace.py:NNN` references describe the
  PRE-extraction file. The moment Phase 0 lands, every one of those offsets is dead — the
  symbols live in `resume_source.py`. Phases 2-3 are written against symbol names, not
  offsets, for exactly this reason. Re-grep, don't trust numbers, after Phase 0.
- **ASSUMED, verify at edit time** (each flagged in the plan but easy to miss): the code-node
  CLASS name for `_gate_pausable` ("PythonCodeNode" — from a CLAUDE.md mention, never grepped
  against the class definition); `node.successors` being a plain `dict[str, node]` at the arm;
  that `action` is bound at the arm on the escalation path (reasoned from control flow —
  escalations raise at 17.7, post-assignment — but never executed; the approval early-return
  in `_gate_pausable` is what keeps step-7.5 gates from touching the unbound name, so preserve
  that evaluation order).
- **My subagent reports die with this context.** The plan absorbed everything load-bearing
  from them. If a plan claim smells wrong, re-verify with `pflow-codebase-searcher` — do not
  assume there was extra unwritten justification.

## Suspicions and 70%-sure items (not in the plan)

- **NEEDS VERIFICATION — masked vs raw gate payload on display surfaces**: the trace holds the
  FULL unmasked `GateRequest` by design (consistent with `template_resolutions`), and the
  paused JSON document emits `gate_request` — check what `_display_denied_result` does with
  its `gate` field today (masked via `masked_preview` or raw?) and mirror it exactly. A
  secrets-in-stdout inconsistency between the denied and paused JSON docs would be a review
  finding waiting to happen. Text mode is already specified to use `masked_preview`.
- **NEEDS VERIFICATION — trailer size vs tail-seek in `_read_trailer_line`**: the `run.complete`
  line can be LARGE (it may carry `json_output`, warnings, and now `gate_request` with big
  previews). Check how `run_tailer._scan_tail_for_terminal` sizes its tail read before copying
  the approach — a fixed 4KB seek could miss the start of a huge trailer line and make
  `resume list` silently skip a legitimate paused run. Read backwards until a newline or use a
  growing window.
- **70% sure — Click group with a flagged default subcommand**: `PflowCLI.resolve_command`
  proves the routing pattern at the root, but resume's default subcommand takes options AND an
  `UNPROCESSED` args tuple. Watch for the group swallowing `--approve` before the subcommand
  sees it; you may need `context_settings={"ignore_unknown_options": True}` or similar on the
  group. Test `pflow resume <id> --approve yes` routing FIRST, before building on top.
- **Known-acceptable inefficiency**: `resume list`'s superseded filtering is O(paused-runs ×
  workflow-traces) full `load_trace_file` parses via `_find_consuming_attempt`. Fine for v1
  ("a status query", per spec). If it's ever slow, that's where and why.
- **Deliberate deferral, not an oversight**: `GateResolution.notes` — the CLI passes
  `notes=None` always in v1 (no `--notes` flag). The blocking prompt doesn't collect notes
  either, so this is parity, but nobody decided a flag AGAINST it; it just wasn't needed.

## Unexplored territory

- UNEXPLORED: pause EXPIRY. The spec muses "approvals arguably should expire, like stale
  terraform plans." Nothing in v1 expires; #542 retention design owns this. Don't invent it.
- UNEXPLORED: the `on_pause` notification hook (webhook/command at pause time). ADR-0009
  explicitly says build it WITH the first external bridge, not before. Task 176 territory.
- CONSIDER: concurrent `pflow resume` of the SAME token from two shells. The loser writes a
  second attempt with the same `resumed_from`; the superseded scan makes later resumes refuse,
  but both racing attempts may run. 164 accepted a minutes-wide double-resume race (closed only
  via the liveness clause); this is the same class of race and v1 inherits that stance —
  nobody explicitly discussed it for gates. If the owner ever asks "what if two people answer
  at once", this is the honest answer: both may execute; the chain self-heals afterward.
- MIGHT MATTER: `pflow resume <workflow-name>` when the newest resumable run is paused but the
  user meant to resume an OLDER failed run — by-name always picks newest-resumable; the
  refusal/answer-required error will name the paused run's token, which is the breadcrumb out.
  Not a bug; a UX sharp corner nobody flagged.

## What I'd tell myself starting fresh

1. Read spec → plan → progress log → this file, in that order. Then run the four resume suites
   before writing a line (confirm 165 still passes — that's your baseline delta anchor).
2. Phase 0 is pure mechanics; do it in one sitting, one commit, and do the mutation check on
   the plan-drift pin afterward. It buys you clean line-anchoring for everything else.
3. The engine gate arm (plan 1a) is the highest-precision edit in the task — the reasoning
   chain above explains every clause. Resist any urge to "simplify" it; each clause has a test
   that will catch you, and the collision test exists precisely because the simple version
   passes every OTHER test.
4. Never fork seed/walk-entry logic. If you feel that pressure, stop and re-read the plan's
   golden rule — that instinct is the failure mode this whole task was shaped around.
5. The owner is not watching the details; they're watching whether the final code is simple.
   When the plan gives you latitude, pick the option with fewer concepts, not fewer lines.

> **Note to next agent**: Read this document fully before taking any action. When ready,
> confirm you've read and understood by summarizing the key points, then state you're ready
> to proceed.
