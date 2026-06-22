# Braindump: Task 172 implementation handoff (2026-06-22)

Tacit "how to succeed" for the implementing agent. **This file deliberately does NOT repeat** the mechanics
(→ `implementation/implementation-plan.md`), the what/why (→ `task-172.md`), the session decisions/reasoning
(→ `implementation/progress-log.md`), or the original-design tacit knowledge (→ the two earlier
`starting-context/braindump-*` files). Read all five — then this for the gaps they don't cover.

## Where this stands

Plan is **approved and converged** — three `/deep-review` rounds (9 specialist passes), all findings folded
in, task spec re-aligned to the locked decisions. Nothing is implemented yet. The plan is built for isolated
execution; you should be able to run it without re-deriving the architecture. The verification gates are now
per-phase and explicit (plan §"Build order & per-phase verification gates").

## How THIS user operates (new behavioral data — the older braindumps cover their design-session style)

The earlier braindumps captured "simplicity of the FINAL code" and "trust-but-verify." This session added:

- **They probe *extensibility*, hard.** Their pointed questions were *"will this be extendable if Task 164
  wants to improve robustness... handle claude-code nodes with --resume?"* and *"is nothing resumable when a
  crash is inside a sub-workflow?"* They are checking that v1 doesn't paint Task 164/125 into a corner. The
  winning answer was the **producer/reader split** (producer writes durably; "what to do with a partial
  trace" is reader policy on top). If a design choice comes up mid-build, frame it through *"does this keep
  the downstream consumer (164/125/overlay) an additive layer?"* — that's their real lens.
- **They insist the *docs* are correct, not just the code.** They explicitly asked "is the task spec correct
  or need minor edits?" and had me re-align it. When you finish a phase, **update the progress log** and check
  the task spec / plan didn't drift. They notice stale docs.
- **They want verification they can *see and reproduce*** — captured baselines, copy-paste commands, real
  output. "No regressions" means nothing without a named baseline diff. They asked specifically whether the
  *intermediate* gates were clear, not just the final one. Honor the per-phase gates literally.
- **On reviews:** they preferred **multiple rounds of ≤4 agents each (review → fix → review)** over one big
  fan-out. Do the same for the *code*-stage review (the proven trio: silent-failures + impact-completeness +
  test-fidelity) — iterate, don't one-shot.
- **They reason WITH you and reject premature menus.** When I led with reasoning (and a recommendation) they
  engaged; a bare A/B/C would have been redirected to "what's the real problem and the tradeoffs?"

## Verified vs. assumed — the ledger (trust the left, validate the right early)

**VERIFIED this session (often 2–3× — scouts + review-plan + concurrency sim):**
- Every file:line in the plan. The rebase-stale-refs trap is closed; you can trust them (still re-grep before
  editing out of discipline, but they held under repeated checking).
- The no-lock `seq` routing — concurrency-safety **could not construct** a worker→run-collector race. The
  two-clause signal (`__index__` on item stores + `is_run_scoped=False` on buffers) carries it.
- The in-memory consumer inventory is **complete** (impact-completeness verified; the formatters are covered
  transitively via `collect_llm_calls`).
- `_handle_no_successor`: the node-event flip is the **sole** trace-status signal (run-level `__failures__` is
  never read at save time); the CLI/ExecutionResult status comes out FAILED independently via the `"error"`
  action string. So the re-flush is *only* about the persisted trace file's fidelity.
- The reserve-`seq`-at-descent = DFS-pre-order equivalence — **I hand-verified this myself** (not a searcher),
  so it's "verified by reasoning." If anything surprises you on `seq` ordering, this is the assumption to
  re-test first with a concrete nested+sibling fixture.

**ASSUMED / NEEDS VERIFICATION (validate these *early*, they're the residual ~15%):**
- **NEEDS VERIFICATION:** the **two-pass reconstruct + dead-end re-flush** is the one piece of *new* logic
  reviewed but never *run*. It's where I'd expect a surprise. Write its tests first.
- **NEEDS VERIFICATION:** the streaming-flush + `tests/conftest.py` gate interaction (lazy stream-open,
  extending `disable_trace_file_writes_by_default`). Specified, untested — I/O timing reveals things.
- **ASSUMPTION:** the lyrics-generator fixture runs cleanly with **mocked** LLM through the new producer.
  Task 159 only ever ran it **live** (`--no-trace-autoload`, recorded trace). Nobody has driven it
  mocked-through-the-emit-path. Budget time for fixture friction.
- **NEEDS VERIFICATION:** the equivalence fixture's `node_output` must be **JSON-native** (no `Path`/
  `datetime`/`set`) or `default=str` lossiness produces a phantom `tree()≠reconstruct` mismatch. Pick fixture
  data deliberately.

## Implementation gotchas the plan states but you'll *feel* the hard way

- **The skeleton is a liar.** Step-1 green (top-level, flat, not-yet-streamed) validates almost nothing about
  collector unification or `ancestor_path`. The real bar is the **step-2** sub-workflow-AND-parallel-batch
  checkpoint. Do not let a green skeleton convince you the producer works — the original braindumps scream
  this and they're right.
- **`pytest -m trace_files` is the ONLY oracle that sees format changes** (`save_to_file`/your new stream is a
  no-op under pytest except for that marker). A hand-picked file list *will* miss tests — A–C missed 4 this
  way. Run the marker.
- **Manual e2e: ONE subprocess at a time, scoped `HOME=$(mktemp -d)`.** Chained/parallel `uv run pflow`
  subprocesses stalled in the original session. Prefer a single `uv run python` driver script.
- The **OLD batch-nested path must stay byte-for-byte identical** — the highest-risk *silent* regression is a
  misrouted `use_run_collector` flattening batch children. The plan's discriminating OLD-path test (assert
  batch children carry **no** correlation keys + a top-level count) exists exactly to catch this; build it.

## Unexplored / might matter

- **UNEXPLORED:** per-event flush *performance* on a big run (ADR flagged, never measured). Don't pre-optimize,
  but watch it on the lyrics-generator fixture — if it's bad, batched-flush-with-periodic-fsync is the lever.
- **MIGHT MATTER:** the live overlay (Task 173) is the *real* validator and is being built in parallel. If you
  can, sanity-check the streamed JSONL against what a tailer would need (backward-only refs, `ancestor_path`
  joinability) — the producer "works" only once 173 can consume it.
- **CONSIDER:** the discovery mechanism for a *live* run's trace file (how 173 finds it) is 173's problem, but
  v1 could make it easier (stable/registerable path). Worth a thought while you're in the writer; not required.

## For the next agent

- **Start by reading**, in order: `task-172.md` → `implementation/implementation-plan.md` → this file →
  `implementation/progress-log.md` → the two earlier braindumps. Then re-grep the engine line numbers.
- **Build order is non-negotiable:** capture baseline → Pieces 1+2+status (atomic) → skeleton equivalence
  green → Piece 3 + the checkpoint → Pieces 4+5 (streaming). Let the equivalence test (with **hardcoded** cost
  literals + a cached node nested **inside** a sub-workflow asserting `parent_id == host.seq`) drive from
  step 1. That cached-nested assertion is the single most load-bearing test detail — two reviewers converged
  on it independently.
- **Don't re-explore:** the run-level dead-end signal (rejected for re-flush), 1-event-lag flush (rejected for
  liveness), keep-nested store (rejected), removing the `or "success"` defaults / legacy reader (out of scope).
- **The user cares most about:** the FINAL code being simple, the design staying extensible for Task 164/125,
  and verification they can reproduce. They WILL ask "are you fully happy?" — have a real, calibrated answer
  (mine was ~85%, residual = the unrun two-pass/re-flush + streaming I/O).

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read
> and understood by summarizing the key points, then state you're ready to proceed.
