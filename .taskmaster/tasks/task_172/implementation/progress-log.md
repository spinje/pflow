# Task 172 — Implementation Progress Log

> **What this is:** the *journey* — decisions locked, alternatives rejected, and what the review battery
> surfaced — during the **design + plan + review** session (2026-06-22). **Not yet implemented.**
> **What this is NOT:** the *what/why* → `task-172.md`; the *how* + per-phase gates →
> `implementation/implementation-plan.md`; the original-design tacit knowledge → the two
> `starting-context/braindump-*` files. This log is the **delta** those don't capture — read it for *why the
> plan looks the way it does* and *what was already tried and dropped*, so you don't re-litigate.

## 2026-06-22 — Session: research → design discussion → plan → 3 review rounds → spec alignment

Pre-flight re-grep (6 parallel `pflow-codebase-searcher` passes) confirmed every file:line against current
`main` (the rebase-stale-refs trap is closed). Then a design discussion with the user, a full plan, **three
`/deep-review` rounds (9 specialist passes)** folded in, and finally the task spec was re-aligned to the
locked decisions. The plan converged (round 3 found zero correctness issues — only test-sharpening).

---

## Decisions locked THIS session (and the reasoning, not just the verdict)

These were **open or unstated** in the original braindumps; they are now settled. The task spec + plan record
the verdicts — this records *why*, so a future agent doesn't re-open them.

- **Adopt the `status` enum (REVERSED from "lean skip").** My initial instinct (and the braindumps') was to
  keep `success`+`cached` for v1. The user asked *"we don't have to be backward compatible with old traces —
  does that change anything?"* — and it did: the **only** real objection to the enum was that it would coexist
  forever with legacy booleans (two representations = harder to reason about). No-back-compat **removes that
  objection**, so the enum becomes the genuinely simpler end-state (one producer-set field vs. derivation
  scattered across ~15 readers). This is the user's "simplicity of the FINAL code" lens in action — it flipped
  the call.
- **No-backward-compat (confirmed by user).** Enables the enum + inline blobs cleanly. **But review scoped it
  down:** it does *not* license ripping out the `... or "success"` defaults (6+ sites, entangled with
  `analyze-cache` reuse policy + synthetic fixtures) or the legacy single-object reader. Those are inert for
  modern traces — left intact. (Round-1 review-plan + impact-completeness both caught the over-broad removal.)
- **Lenient *transitive* orphan-drop for incomplete traces.** The user pushed hard on *"is nothing resumable
  when a crash is inside a sub-workflow?"* The honest answer: children flush before their host's completion
  event, so a crash mid-sub-workflow orphans them. Rather than accept "recover nothing," the reader drops
  dangling children **transitively** in incomplete (no-`run.complete`) traces only → recovers everything
  well-formed. This is *reader policy over data the producer already wrote* — the clean split that keeps the
  producer dumb and makes Task 164 (resume) an additive layer, not a rewrite. (This was the framing that
  satisfied the user's extensibility question.)
- **`node.start` / in-flight signals stay deferred.** The user asked why. Recorded reasoning: no v1 consumer
  needs it (overlay is L1/completion; ADR-0008 accepts the parallel/batch "running" gap), it doubles the
  producer surgery + adds reader merge logic, and its *shape* isn't knowable until a consumer (overlay-L2 or
  Task 164) validates it — building it now = guessing. It's cleanly additive later (the host-descent stack is
  exactly its hook), so deferring costs ~nothing.

---

## The conceptual crux (worth internalizing before you touch the engine)

**Host span emit-ordering.** A sub-workflow host's event is recorded at *completion* (engine step 16), but its
children record *during* its execution — so children flush **before** the host. Reconstruct needs
`parent.seq < child.seq`, so the host's `seq` must be **reserved at descent** (pushed on the stack) and used
at completion. I hand-verified this reserve-at-descent scheme reproduces today's **DFS pre-order `seq`
exactly** (nested / sibling / sequential cases) — which is *why* the equivalence test passes for complete runs
without changing reconstruct. The flip side: a crash mid-sub-workflow leaves children referencing a never-
written host → the lenient transitive drop (above) is the answer, not a producer change.

---

## Alternatives considered and REJECTED this session (don't re-explore)

- **Run-level dead-end signal instead of flipping the node event** (for the routing dead-end). Verified the
  trace's `failed_node_ids`/`final_status` read **only** the per-event `status` flag — the run-level
  `__failures__`/`__execution__` state is never consulted at save time. A run-level approach would need a new
  channel into `_determine_trace_status` *and* break `test_failed_node_invariant.py`. **Rejected** for the
  **re-flush a corrected line** approach (smaller blast radius; keeps the single source of truth).
- **1-event-lag / deferred flush** (hold the last event un-flushed so a correction lands before flush).
  **Rejected:** it delays the live stream by one event, and on a slow node (30s LLM call) the *previous*
  node's completion wouldn't surface for 30s — unacceptable for a "live" overlay.
- **Keep-nested in-memory store** — already rejected in the original braindumps; not re-opened.

---

## What the 3 review rounds surfaced (the non-obvious ones)

- **The `status` enum is one atomic change, not a trailing pass** (round 1, validation-consistency). The cost
  readers (`trace_tree.py` `cached` boundaries) break the instant the producer writes `status` — so producer
  + every reader + central fixtures land together.
- **`tree() == reconstruct(disk)` gives FALSE confidence on cost** (round 3, validation-consistency **and**
  test-fidelity, independently). Both feed the same `TraceTree`, so a missed `cached`→`status` reader leaves
  them *equal but wrong*. ⇒ the equivalence test's cost/status assertions **must be hardcoded literals**, and
  it must include a **cached node nested inside a sub-workflow** (assert `parent_id == host.seq`). This is the
  single most load-bearing test detail.
- **The two-pass reconstruct (dedup-by-id last-wins) elegantly subsumes BOTH** the lenient orphan-drop and the
  dead-end correction re-flush — one mechanism, two problems. (Emerged while resolving the round-2 dead-end
  finding.)
- **A bug I caught in my own plan during review:** I had scoped `mark_last_event_failed` to top-level events
  (to avoid child-overwrites-parent) — but a routing dead-end *inside a sub-workflow* (GH #250) targets a
  *child* event, which top-level scoping would silently miss. Fixed: it scans **all** events (most-recent match
  is unambiguous); only the dict-keying aggregators need top-level scope.
- **Concurrency verified clean** (round 2, concurrency-safety): no constructible interleaving reaches the run
  collector's `seq` from a worker. Hardening added anyway — a main-thread `assert` on `_next_seq`/`descend`/
  `ascend` turns a future silent `seq` gap into a loud failure; `_host_frame` added to the existing `:324`
  instance-reuse reset.
- **`tree()` must be `is_run_scoped`-guarded** (round 2, silent-failures): `_rebuild_event_tree` *raises* on
  un-stamped events, so a bare `tree()` would crash on buffer/test collectors. Guard: rebuild only when
  run-scoped, else return raw `self.events` (already tree-shaped) — also semantically correct.

---

## Confidence calibration (honest)

**~85% the plan is correct as written.** Verified hard: every file:line (3× over), the core architecture
(concurrency couldn't break it, DFS-`seq` equivalence hand-checked), the consumer inventory (complete), the
producer↔reader contract (consistent all four ways). The residual ~15% is **implementation-discovery** that no
review can close — specifically the **two-pass reconstruct + dead-end re-flush** (new logic, reviewed once,
never *run*) and the streaming-flush + pytest-gate I/O timing. The braindump's warning holds: **a green
skeleton (step-1 gate) proves almost nothing about the hard part** — the real bar is the step-2 sub-workflow
+ parallel-batch checkpoint. Build skeleton-first so that risk surfaces in hours, not after the whole thing is
built. ~300 LOC is a **floor**.

## Next step

Capture the test baseline (`pytest -m trace_files` + the named-files set in the plan), then build **Pieces
1+2+status atomically** and get the skeleton equivalence test green **before** touching the engine. Then
Piece 3 + the checkpoint. Then Pieces 4+5 (streaming). Run the code-stage review trio after.
