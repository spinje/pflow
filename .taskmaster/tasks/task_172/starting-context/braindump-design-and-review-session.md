# Braindump: Task 172 — the design+review session that produced it (tacit knowledge only)

This is the stuff **NOT** in `task-172.md`, ADR-0008, or the D1 schema. Read those for *what* to build;
read this for *how the design got here, what was reversed and why, where the bodies are buried, and how
to work with the user.* Don't re-derive what the session already settled.

## Where this came from (so you trust the right artifacts)

Task 172 was **not** spec'd from scratch — it fell out of a long scoping session that started as "rebase
the A–C branch onto main" and turned into designing the whole live-execution-overlay. The chain:
A–C is shipped → "we need a runtime consumer for the UI to make Phase D *earned*, not speculative" → that
consumer is the live overlay (Task 173) → it forces this producer (Task 172). So **172 exists to serve a
real, concurrently-designed consumer.** Build it *with 173 as the validator*, skeleton-first — do not
"complete" 172 in isolation (see "the skeleton validates almost nothing" below).

The design was hammered through **two adversarial review passes (six specialist agents total)**. The docs
are the *distillate*; the full probe/review outputs are only in the conversation, not saved. If you doubt
a claim, the probes ran against **current code** — re-run them.

## ⚠️ The single most important warning: the plan's file:line refs are STALE

`task-133/implementation/implementation-plan.md` and the older braindumps cite exact `file:line` for the
engine surgery. **They are stale.** This branch was rebased onto main (23 commits) which moved
`engine.py`, `instrumentation.py`, `batch_executor.py`, `workflow_executor.py` — the exact files Phase D
edits. The **complexity probes and reviews in this session re-verified against the rebased code**, so
trust task-172.md's prose over the plan's line numbers, and **re-grep every line number before editing.**
This already bit once (the rebase silently broke a `test_failed_node_invariant.py` import that `git` and
`merge-tree` reported as clean — a *semantic* conflict, not a textual one). Distrust "git says clean."

## Two reversals I made — do NOT re-flip them

The user probes every recommendation ("but what are the tradeoffs?", "why defer?", "why is that
overengineering?"), and the probing was *right* both times — it reversed me. So you don't re-litigate:

1. **In-memory shape: I first recommended KEEP-NESTED; it was reversed to FLIP-TO-FLAT.** My "keep-nested
   is simpler" was *getting-there*-simpler, not *final-code*-simpler. The truth: collector unification
   *naturally* produces a flat list; keeping it nested requires **new re-nesting logic** AND leaves *two*
   maintained shapes. Flat + a derived `tree()` (reusing the *existing* `_rebuild_event_tree`) is **less
   new code and one representation.** This is now the decision (ADR-0008). Don't "simplify" back to a
   nested in-memory store — that's the longer path.

2. **Status enum: I supported a 4-value `{success,cached,degraded,failed}` per-node enum; it was corrected
   to 3 values + run-level degraded.** `degraded` is a **run** concept (CONTEXT.md), and — the hard fact —
   it is **not knowable at emit time**: `record_trace` (engine step 16) runs *before* the recovery verdict
   (step 17.5). A failed-then-recovered node is honestly `failed` at the node level; the *run* is degraded.
   **Do not try to make per-node `degraded` work** (you'd need a correction event for an append-only
   stream — not worth it). And the **enum itself is now an OPEN, low-stakes decision** (explicit `status`
   enum vs. keep `success:bool`+`cached`) — the user leaned toward the enum but the "it fixes mislabeling"
   justification evaporated once we learned degraded is run-level, so it's now just an explicit-vs-implicit
   cleanup costing ~15 reader migrations. **Decide it in-build; don't treat it as settled either way.**

## How the ~300 LOC / 6–7-of-10 estimate was derived (and why it's a FLOOR)

Two probes against current code: the **sequential/sub-workflow spine = 7/10, ~265 LOC** (the structural
inversion — nested→flat in memory — drives it, plus the silent-corruption LLM-dict collision risk and the
trace_io correlation change); the **batch/concurrency spine = 5/10, ~90–160 LOC** (the no-lock `seq` is
*already verified valid*, so this is mostly moving the existing single-threaded numbering earlier). The
estimate **assumed the flat-flip** and counted the reader migration, but it **under-counted `ancestor_path`
and the host-descent stack** (the plan-review caught that I'd wrongly written "the stack already exists").
So: **treat ~300 LOC as a floor, not a budget.** The concurrency bogeyman is the thing that *isn't* there
(no lock needed) — that's the good news that keeps this from being a nightmare.

## The traps the reviews surfaced that are easy to misread

- **`final_events_by_node` is the WRONG fix target for `tree()`.** The docs lump it with the cost readers,
  but its failure mode under a flat store is **different and higher-severity**: node-id *collision* (a
  sub-workflow's `validate` overwriting a top-level `validate` → **wrong `final_status`/`failed_node_ids`**,
  not just wrong cost). It needs **top-level-only scoping** (`tree()` roots / `parent_id is None`), NOT a
  recursive walk. Cost readers (`collect_llm_calls`, `_collect_llm_summary`) need the recursive `tree()`.
  Two different handlings — don't apply one fix to both.
- **The metrics path was THE critical find** and is non-obvious: `ExecutionResult.trace` is the *live
  collector object*; the CLI+MCP cost summary calls `result.trace.collect_llm_calls()` which builds a
  `TraceTree` over `self.events` and recurses `sub_workflow_events` — it **never touches the disk seam**,
  so "reconstruct keeps readers green" does NOT cover it. This is why the in-memory shape is its own blast
  radius. Find *every* in-memory reader of `self.events` before flipping (the review enumerated them).
- **The `ancestor_path` ↔ collision-guard tension:** `flatten_trace_to_lines` *asserts* a producer never
  pre-sets a reserved key. If you add `ancestor_path` to `_RESERVED_LINE_KEYS` (to strip on read) AND
  stamp it at emit, the assert fires unless the **writer owns it** (stamps it like `id`/`seq`/...). Resolve
  ownership explicitly or the first Phase-D run throws at save.
- **`_rebuild_event_tree` only re-nests `sub_workflow_events`, never `batch_items`.** v1 keeps batch items
  inline so this is fine — but it means `tree()` and "batch items inline" are *coupled*: the deferred
  batch-item promotion will require teaching `_rebuild_event_tree` the `batch_items` re-nest. Don't promote
  batch items without that.
- **`child_trace.events` is a "third shape" trap.** If you keep per-child collectors and embed their
  (now-flat) events, you get a structure that's neither nested nor flat-in-the-parent's-id-space. The fix
  is to **fully eliminate per-child collectors** (one run-scoped collector). Half-unifying is worse than
  not starting. The host-descent stack must live on the **run-scoped collector, not the per-child engine**
  (the engine is re-instantiated per child; the collector persists).

## The prompt-cache tripwire (verified clean — keep it that way)

A dedicated probe confirmed the runtime prompt cache *is* cleanly per-workflow. The `__pflow_prompt_cache__`
save/restore in `engine.run` sits **right next to** the `__trace_collector__` one and looks structurally
identical — **but it is semantically opposite** (per-workflow, load-bearing for cache scoping + the
`CacheBlockIR` freeze guarantee; NOT in `_PROPAGATED_KEYS`). A refactorer who "tidies up the two parallel
save/restore blocks" because they look alike **breaks cache scoping silently.** Collector unification
removes/changes ONLY the trace half. (Historical: a `storage_mode: shared` × parallel-batch × `## Cache`
race existed, was investigated twice, found benign, and is now structurally impossible since `storage_mode`
was removed — don't chase it.)

## How to work with this user (highest-value section)

- **"Simplicity of the FINAL code, not how easy it is to get there."** Their north star, verbatim and
  repeated. They will accept a harder migration (e.g. the flat-flip's reader migration) for a cleaner
  end-state. When you catch yourself optimizing "less work now," check whether it costs final-code clarity
  — that's the lens that reversed me twice.
- **"What's the right solution the top 10% of codebases would implement?"** — immediately fenced with
  *"this doesn't mean overfitting / overengineering… it's about more simple code optimized for AI agents to
  understand and add features to."* So: boring, flat, greppable, one-representation > clever.
- **Trust-but-verify, hard.** Expect *"are you FULLY happy? / what are the tradeoffs? / why defer?"* They
  are not rhetorical — go hunt your own holes. Every time I did, there was a real one. **Run the review
  battery on your plan AND your code.** The proven set for this subsystem: **review-plan** +
  **review-validation-consistency** + **review-impact-completeness** (plan stage), and the trace trio
  **review-silent-failures + review-impact-completeness + review-test-fidelity** (code stage). They each
  caught a real defect.
- They reason *with* you and **reject premature multiple-choice** — when offered A/B/C they redirect to
  "what's the real problem and the tradeoffs?" Lead with reasoning, not a menu.
- They want **verification they can see and reproduce** (copy-paste commands + real output), not "tests
  pass."

## Verification gotchas (cost real time to learn)

- **`uv run pytest -m trace_files` is the authoritative oracle** for any trace-shape change.
  `WorkflowTraceCollector.save_to_file` is a **no-op under pytest** except in `@pytest.mark.trace_files`
  tests (autouse fixture in `tests/conftest.py`). So a format change only breaks trace_files-marked tests
  + real-subprocess e2e — a hand-picked file list *will* miss tests. (A–C missed 4 this way.)
- **The round-trip oracle is NOT enough for Phase D.** `save_to_file`→`load_trace_file` only proves
  `flatten`↔`reconstruct` self-consistency. Phase D changes the **producer** (save-time→emit-time), so you
  **need a NEW live-engine → on-disk JSONL → existing-reader integration test** — the round-trip won't see
  emit-path bugs. This is the seam where Phase D silently breaks post-hoc readers.
- **The skeleton validates almost nothing about the hard part.** The skeleton-first slice (top-level
  completions, `ancestor_path=[]`) deliberately sidesteps collector unification + `ancestor_path`. The real
  validation is the **intermediate checkpoint: one sub-workflow AND one parallel batch end-to-end through
  the unified collector.** Don't let a green skeleton convince you the producer works.
- **Manual e2e:** `env HOME=$(mktemp -d) uv run pflow …` (scoped per-process), ONE at a time. Prefer a
  single `uv run python` script over chained `uv run pflow` subprocesses (those stalled mid-script).
  **Don't run many background bash at once — they contend/stall.** `verify.sh` (Task 159 baseline) is
  pre-drifted — don't reach for it.

## What A–C already gives you (reuse, don't rebuild)

`core/trace_io.py` has `flatten_trace_to_lines`, `reconstruct_trace_from_lines`, `_rebuild_event_tree`,
`substitute_refs`, `_META_KEYS`, `_RESERVED_LINE_KEYS`, the `pflow_trace: "jsonl/1"` marker, the
`run.complete` trailer, and the crash-tail `final_status="incomplete"` handling. **The on-disk format and
the reader do not change in Phase D.** Spikes #1 (singular read seam), #2 (no-lock `seq`, adversarially
verified), #3 (flush benchmarked at <0.01% wall-clock) are **closed** — re-verify the no-lock invariant
against current code, but don't re-spike.

## Assumptions & uncertainties

- **ASSUMPTION:** Phase D = a **new task (172)** citing 133, not folded into 133. The user said "go ahead"
  to my recommendation but didn't explicitly say "new task vs under 133" — I chose new task so 133 stays
  the clean decision-record. Reversible.
- **NEEDS VERIFICATION:** the exact engine step-16/17.5 ordering and the `record_trace` call sites — the
  reviews asserted these against current code but you must re-confirm the line numbers before editing.
- **UNCLEAR:** whether the `status` enum is worth its ~15-site migration. Genuinely open; the overlay works
  without it. Don't burn the decision early.
- **NEEDS VERIFICATION:** `default=str` in `save_to_file` is lossy for non-JSON-native leaves (Path/
  datetime/set). Round-trip identity holds only for JSON-native data. Matters if Phase D's incremental
  events ever carry such leaves; nobody has audited which appear in production traces.

## Unexplored / might matter

- **UNEXPLORED:** the discovery mechanism for the consumer (how the UI server finds the *live* run's trace
  file) — that's Task 173's problem, but 172 might want to make it easier (e.g. a stable/registerable
  trace path, or the run announcing its file). Worth a thought while you're in the writer.
- **CONSIDER:** Task 87 (sandboxing) could move batch workers into **subprocesses** later, which breaks the
  no-lock `seq` (GIL argument evaporates). The design is robust to this *only if* `seq` is assigned at the
  **main-thread drain, never in the worker.** Hold that line.
- **MIGHT MATTER:** batch items write their own `success`/`cached` inline (`_capture_item_trace`); if you
  adopt the `status` enum, batch-item status shape needs handling too (the schema now flags this).
- **CONSIDER:** memoize `tree()` only if a future hot-path consumer appears — but **never memoize while the
  run is still appending** (cache invalidation under append). v1 readers are finalize-time, so rebuild-on-
  demand is fine.

## For the next agent

- **Start by reading:** `task-172.md`, then ADR-0008, then the D1 schema (the Producer notes section), then
  this. Then **re-grep the engine line numbers yourself** before touching code.
- **Build order:** skeleton (validate D1 end-to-end) → full collector unification → the sub-workflow+batch
  checkpoint → hand the validated producer to Task 173. Task 169 (SSE) runs in parallel; it's not your
  dependency.
- **Don't bother with:** re-spiking concurrency (done), reusing the plan's stale line numbers, or making
  per-node `degraded` work.
- **The user cares most about:** the *final* code being simple and the design being *verified* (run the
  reviews). They will ask "are you fully happy?" — have a real answer.
- **The branch name `feat/unified-node-storage` is a lie** — it reflects the *rejected* merge premise. The
  work keeps trace & cache separate. Don't let it frame you.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've
> read and understood by summarizing the key points, then state you're ready to proceed.
