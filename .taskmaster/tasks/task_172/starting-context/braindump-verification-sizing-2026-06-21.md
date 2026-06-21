# Braindump: Task 172 — verification sizing + handoff context (2026-06-21)

> Written by the agent who (a) wrote the now-**superseded** `task_133/research/implementation-handoff.md`,
> (b) watched Task 133 A–C + ADR-0008 land, and (c) worked through the "do we need a baseline?" decision
> with the user. Everything *factual* about the design is already in `task-172.md`, ADR-0008, and
> `d1-event-schema.md`. This file is the **tacit** stuff — reasoning, the user's priorities, and the
> traps — that those files don't capture.

## Where this stands

Task 172 is **not started**. The spec is complete and the design is pinned (ADR-0008 + D1 draft). The
last thing done this session: rewrote the **Verification** section to encode "**no separate baseline**"
+ a 6-step proportionate plan. The headline new test (emit↔save equivalence) does **not exist yet** —
that's the single most important thing to build, and the contract the whole A-C/Phase-D split rests on.

A clear **next step that was offered but not taken**: a *pre-flight* that re-verifies the stale file:line
refs and the no-lock `seq` invariant against current `main` *before* coding. Do that first — see traps below.

## The user's mental model (use their framing)

Two priorities run through this entire multi-day conversation, and they should steer how you work:

1. **Right-size the effort; resist over-engineering.** Their exact words this session: *"do we need to
   create a separate baseline for this task? Is the risk high enough? lets take a step back."* They are
   allergic to building machinery the change doesn't warrant. When you reach for a tool, ask first
   whether the risk justifies it. This is *why* the Verification section now explicitly says "no baseline"
   with the reasoning — so a future agent doesn't reflexively build one.

2. **Verify against reality; distrust stale claims.** Earlier in this conversation I got caught twice
   asserting things from a stale read (I claimed #253 "still live" when #491 had already fixed it; I
   treated Task 133 as not-started when A–C had merged). The user repeatedly said "see latest prs / see
   git." **The lesson is now load-bearing for *you*:** the task-172 file:line refs are stale (the spec
   says so), and even ADR-0008/D1's "verified this session" line refs were true on ~2026-06-18 — main has
   moved since. Re-verify before editing anything.

**Evolution of their thinking that matters:** the *original* directive (in the superseded handoff) was
"do the **full** work, don't defer to rush other tasks." That got **overridden** by the live-overlay
scoping session → ADR-0008's **skeleton-first + bounded node-granularity v1** (span taxonomy deferred).
The user is now aligned with *bounded + proportionate*, not *maximal*. Don't resurrect the "do it all"
framing from the old handoff — **ADR-0008 wins** (the handoff is marked SUPERSEDED at its top).

## The baseline decision — the reasoning, not just the verdict

The verdict ("no separate baseline") is in the spec. The *framing* that produced it, so you can defend it
or know when to revisit:

- **Shape test.** A golden-output baseline (Task 159's) pays off on a **wide, shallow, subtly-formatted**
  surface (analyze-cache: ~28 warning IDs, advisories, cost projections — drift is easy to miss). Task 172
  is **deep + narrow** behind one invariant. Deep-narrow → *assert the invariant directly*; wide-shallow →
  *golden diff*. Don't mix them up.
- **The deletion test killed it.** A 172 baseline would mostly re-test the unchanged reader/analyzer and
  duplicate existing trace tests → it *moves/duplicates* verification rather than *concentrating* it.
- **Decisive evidence about Task 159's baseline** (I checked the command.sh files): **66 of 79 cases run
  `analyze-cache --no-trace-autoload`** — *static* analysis that never touches the trace producer or
  reader. Only ~12 run `pflow run`, and most of those are parser/validator **error** cases that die before
  producing a meaningful trace. So 159's baseline is a *cache-analyzer* oracle, **not** a trace-producer
  oracle. Running its `verify.sh` after 172 is a free bonus net (its un-normalized cost diff is a real
  catch), but a green there is *necessary-not-sufficient* — don't mistake it for producer coverage.
- **The genuinely reusable thing from 159 is an ASSET, not the harness:** `task_159/baseline/_shared/
  workflows/lyrics-generator/` (17 files, 3-level nesting, 25 LLM nodes, parallel batch). Use it as a
  realistic at-scale *execution* fixture — but with **mocked LLM** (`tests/shared/llm_mock`), never the
  ~181-call live run (cost + nondeterminism; that's *why* 159 ran it `--no-trace-autoload` and committed a
  *recorded* trace for the reader path).

## Traps (the things that are easy to get wrong)

- **"Disk format unchanged → readers safe" is only HALF true.** It's true for *disk* readers (report,
  analyze-cache, --only) **iff** reconstruction stays byte-identical. It is **false for in-memory
  readers**: the metrics/cost path (`collect_llm_calls`, `_collect_llm_summary`) reads the *live
  collector*, never the disk — ADR-0008 explicitly corrected my handoff's wrong "metrics stays green via
  reconstruction" claim. The flat-store flip is the in-memory blast radius, *wider* than the disk format.
- **The crash-tail test must be REPLACED, not added.** A–C shipped `test_load_trace_file_skips_truncated_
  tail_*` which **pins today's whole-trace-skip behavior** (correct for A–C, where the last line is the
  `blobs` *trailer*). Once D3 makes blobs inline-first-occurrence, the right behavior flips to
  "drop the truncated final line → `incomplete`." If you *add* the new test and leave the old one, you'll
  have two contradictory pins. Delete/replace the A–C documenting test. (And: don't try to fix crash-tail
  tolerance *separately* from the blob-ordering flip — they're the same change, "coherent only once D3
  lands.")
- **No-lock `seq` is a discipline that one wrong call corrupts.** The collector is reachable from a worker
  thread via the shallow-copied `shared`. The failure mode is specific: a **parallel-batch item that
  contains a sub-workflow**, where a worker calls the collector's record/`seq` methods directly → `seq`
  race. The rule is workers route to worker-local buffers (`_batch_trace`, child events), folded in with
  `seq` assigned at the **main-thread drain**. Verify this invariant holds against *current* code before
  relying on it (it was "spike #2", verified on older main).
- **The intermediate checkpoint is the real "done" bar**, not the thin top-level slice. ADR-0008 is
  explicit: exercise one sub-workflow **and** one parallel batch end-to-end through the unified collector
  before Task 173 (consumer) treats the producer as done. The thin slice (top-level node-completion only)
  sidesteps the hard part.

## Assumptions & uncertainties

- **ASSUMPTION:** the existing trace suite (test_trace_io round-trip, `-m trace_files` ×164,
  test_metrics_integration, test_failed_node_invariant, test_only_snapshot) actually exercises
  *sub-workflow cost aggregation* and *parent/child `node_id` collision for status*. **NEEDS
  VERIFICATION** — that's literally Verification step 2. If there's a gap, add one targeted test, not a
  baseline. I did **not** confirm this coverage exists; I inferred it from test names.
- **NEEDS VERIFICATION:** A–C merged via #525/#526. The `feat/unified-node-storage` worktree may be the
  stale pre-merge branch — branch 172 from current `main` (which has A–C), not from that worktree.
- **UNCLEAR:** whether the D1 `status` enum promotion (success/cached/failed) is worth the ~15-site reader
  migration. Spec says low-stakes, decide during build. My instinct: skip it for v1 unless the reader
  migration you're already doing makes it nearly free — don't expand scope.

## Unexplored / might matter

- **MIGHT MATTER:** `default=str` in `save_to_file` one-way-stringifies non-JSON-native node outputs.
  Phase D doesn't have to fix it, but Task 164 (resume) inherits it (loud-caveat vs faithful snapshot
  store). If your equivalence test uses outputs with non-JSON types, account for this or you'll chase a
  phantom "mismatch."
- **CONSIDER:** the live-engine→JSONL→reader integration test should assert against a workflow with a
  **loop** too (loop revisits keep distinct `id`/`seq`, same `(node_id, ancestor_path)`) — the spec
  mentions loop identity but the checkpoint only names sub-workflow + parallel batch.
- **UNEXPLORED:** performance of incremental flush (one fsync-ish write per event) on a big run — ADR
  says "flush frequently or a crash loses the tail," but flush-per-event vs batched-flush wasn't measured.
  Spike #3 territory; don't pre-optimize, but watch it on the lyrics-generator fixture.

## For the next agent

- **Start with the pre-flight**, not the code: re-verify the stale file:line refs in `task-172.md`
  §"Implementation Notes" and the no-lock `seq` invariant against current `main`. The whole conversation's
  lesson is "main has moved; don't trust line numbers."
- **Build the emit↔save equivalence test early** (Verification step 3) — it's the contract the entire
  split rests on and it doesn't exist. Let it drive the implementation.
- **The user will push back on anything that smells like over-engineering.** When in doubt, do the smaller
  thing and say why. The baseline conversation is the template: state the risk, state the proportionate
  response, don't build machinery the change doesn't warrant.
- Read in this order: `task-172.md` → ADR-0008 → `d1-event-schema.md` → the *other* braindump
  (`braindump-design-and-review-session.md`) → this file.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've
> read and understood by summarizing the key points, then state you're ready to proceed.
