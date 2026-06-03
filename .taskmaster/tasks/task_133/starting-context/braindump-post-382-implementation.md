# Braindump: Task 133 after #382 shipped (2026-06-03)

> **Read `task-133.md` + `starting-context/braindump-storage-architecture-session.md` first** — they
> hold the decision and the D1/D2/D3 design. This file is ONLY the tacit knowledge from actually
> *shipping* #382 (now Task 165, PR #467) that changes how you should approach the **deferred
> streaming span-model work** Task 133 governs. The full #382 implementation/plan/review lives in
> `.taskmaster/tasks/task_165/` — don't re-read it unless you're touching trace internals; read its
> **`task-review.md` "Dangerous Edges" + "Patterns" + "Gotchas"** sections, which are the load-bearing
> distillate.

## Where things actually stand now (vs. what task-133.md predicted)

#382 shipped the "now" stream (per-run interning + the honest/canonical event model). That means the
**content layer Task 133's streaming work was supposed to reuse now EXISTS and is proven**. Concretely:

- **`load_trace_file` (`src/pflow/core/trace_io.py`) is the real migration seam.** Not theoretical
  anymore — all three trace-content readers route through it. When jsonl/streaming lands, you swap a
  jsonl parser *behind that one function* and every consumer keeps getting plain resolved dicts. This
  is the single most valuable thing #382 left you.
- **The interning walk is genuinely shape-agnostic** (verified, tested on `batch_items` /
  `sub_workflow_events` / nested blocks). It survives tree→flat unchanged. The ref convention
  (`{"$pflow_blob": hash}`), the content hash, and the substitution are all transport-independent.

**Two corrections to task-133.md / the prior braindump — they wrote predictions that are now slightly
wrong:**

1. **Blobs went in a BOTTOM trailer, not a "top-of-file blob table."** task-133.md D3 and the prior
   braindump both say "top-of-file blob table → inline-first-occurrence." We actually put `blobs` as
   the *last* top-level key (trailer) — chosen purely for human readability (metadata + event tree
   first, blob bodies as an appendix). Doesn't change D3's rework (hashing is position-independent, so
   top vs. bottom vs. inline is all the same substitution) — but the phrasing in the design doc is now
   inaccurate. The rework is still "static end-dump map → inline-first-occurrence," regardless.
2. **`substitute_refs(obj, map)` was NOT extracted.** The plan considered factoring the substitution
   into a standalone function (for the future jsonl reader to reuse) and **deliberately YAGNI'd it** —
   it's inlined in `resolve_blobs`. So when you build the jsonl reader, your *one* extraction job is:
   pull the substitution walk out of `resolve_blobs` into `substitute_refs(obj, blob_map)`, then have
   both the current `resolve_blobs` (map from `trace["blobs"]`) and the jsonl reader (map accumulated
   from inline declarations) call it. Mechanical, ~10 minutes. The plan's §13/forward-compat section
   explains the intent.

## The thing #382 did NOT touch — still the hard part of streaming

task-133.md D1 names the real expensive work: **"each sub-workflow gets its own collector
(save/restore around `engine.run` via `__trace_collector__`); streaming requires unifying that into
span-context correlation — a collector + `WorkflowExecutor` change, not a format change."** I verified
during #382 that this is **completely untouched** — #382 was a content/disk change and deliberately
stayed off the per-sub-workflow collector mechanism. So D1's write-side unification is exactly as
described, fully pending, and is *the* invasive piece. The content side is now de-risked; the
correlation/transport side is not even started.

The D1 **read** choke point (`TraceTree.from_event_log`) doesn't exist yet either. Note: whatever it
reassembles must produce the **2.5.0 canonical event shape** #382 established (see next section).

## #382 made the typed-trace contract (D1 / #370) easier — use this

The honest model shipped as **full canonicalization**: an LLM event now has exactly **one** prompt
field (`llm_prompt`, `str | list[dict]`) and **one** effective-system field (`llm_system`). The
redundant `node_output.prompt` / `template_resolutions.prompt` / `node_params.prompt` copies are gone
(producer-side, node-aware strip; `node_params.system` kept for the report). **This is a gift to D1:**
when you pin the span/typed-trace schema (#370), the LLM event is already a clean single-field shape —
you're not encoding "the prompt appears in 3 fields with subtle availability rules." Build the span
schema's event shape to *match* the 2.5.0 canonical shape, and `TraceTree.from_event_log` should emit
that same shape.

## Edge cases the D1 span taxonomy must remember (I hit these in #382)

- **The synthetic prewarm warmup item.** `batch_executor.py:~762-772` builds a batch-trace item
  directly (`index: -1`, `item: "__cache_warmup__"`, `is_warmup: True`), **bypassing** the normal
  `_capture_item_trace` path. It's a synthetic (N+1)th LLM call that primes the provider cache. The
  span model must decide: is it a span? (It's filtered out of call-counting at 8 sites already — see
  `engine/CLAUDE.md` "Synthetic Cache Warmup Item".) Don't let it silently become a phantom span.
- **`max_retries` retries are still untraced** — task-133.md D1 already flags this, but I'll
  reinforce: there are TWO "retries" (graph-loop re-exec ≈ free as new visits; node-internal
  `max_retries` = currently NO emit points). #382 didn't change this. "Retries as attempts within a
  span" = NEW emit points in the Node lifecycle, not free.

## Hard-won knowledge: the Task 159 baseline (`verify.sh`) — applies to ALL future trace-shape work

This took me several runs to figure out and is **not clearly written anywhere**. The next agent doing
ANY trace-shape change (streaming included) will face the same baseline and waste time, so:

- **`verify.sh` does NOT re-record live traces.** It re-runs `analyze-cache`/`report` *commands*
  against **committed** inputs (workflow files + committed old-format `*.trace.json` fixtures) and
  diffs stdout against committed `expected-*.txt`. The "gemini"/"live-recordings" cases read committed
  trace fixtures — there is **no live LLM call**. So it needs no API key to run, BUT...
- **Each case runs under `env -i` (scrubbed env, NO API key)** — `run-case.sh:36`. So `analyze-cache`
  emits "Missing API key" blocking-errors.
- **The baseline is currently PRE-DRIFTED on this branch, independent of any trace change.** The
  committed `expected-*.txt` predate an unrelated `analyze-cache` "Missing API key" blocking-errors
  change (came in via main). Proof: the *static greenfield* cases drift (they read no trace at all and
  #382 cannot touch them). So `verify.sh` showing "10 drifted" is a **false alarm** — it can't
  attribute drift to your change until the baseline is reconciled on main.
- **It's a backward-compat read-path oracle, not a forward gate.** For #382 the trace-reading cases
  drifted *identically* to the immune greenfield cases (same missing-key block, no shape drift) →
  proving the change was transparent. That's how you use it: isolate the environmental noise, confirm
  your change adds *zero new* drift on the trace-reading cases.
- **DO NOT regenerate `expected-*.txt` to "fix" the drift** as part of a feature PR — it conflates an
  unrelated change with yours and bakes the no-key state in. Baseline reconciliation is a separate
  main-branch task (and the user built/owns that baseline by hand — respect it).

The real measured numbers (cite these, not the stale "53MB→12MB" prose): **interning alone = 33% /
3.1 MB on the committed 9.44 MB cleaned fixture, round-trip identical; a real prewarm prefix deduped
17 copies → 1 blob.** Canonicalization + a *raw* (uncleaned) trace shrink more.

## User's mental model (the parts that matter for Task 133, in their words)

- They **explicitly asked, during #382, "how does this relate to the future jsonl streaming
  refactor?"** — they want the streaming work *not painted into a corner*. They were satisfied when I
  showed the content layer is orthogonal to transport and `load_trace_file` is the seam. So they're
  already bought into the "ship content now, stream later" sequencing — you don't need to re-sell it.
- **"Searchability" is load-bearing and non-negotiable** — their exact framing was the trace is "a
  thing an agent can *search*" (grep/jq, plaintext). This killed gzip in #382 and it will constrain
  the streaming format too: the jsonl log must stay plaintext + greppable. Don't propose a binary
  framing.
- **Simplest FINAL code + AI-legibility over cleverness.** Verbatim: *"prioritize simplicity of the
  FINAL code, not how easy it is to get there… the right solution the top 10% of codebases would
  implement"* immediately guarded by *"this isn't about overfitting to top-10% / overengineering —
  it's about more simple code optimized for AI agents to understand and add features to."* They chose
  **Option 2 (full canonicalization / honest model)** over the simpler "just intern, leave the copies"
  precisely because *visible repetition hurts legibility* — "if we can see this kind of repetition it
  makes the code harder to reason about." Expect the same instinct on the span schema: one clear shape
  beats redundant-but-additive.
- **They reason WITH you; they reject multiple-choice.** When offered structured A/B/C they redirect
  to "what's the real problem and the tradeoffs, anything we haven't considered?" Surface the
  alternative you're tempted to skip.
- **Viscerally aware docs/baselines go stale** — they made me verify *everything* against code. The
  baseline-staleness I found *validated* this instinct. Trust code over docs, including over
  task-133.md's own predictions (see corrections above).

## Status / sequencing reminder (don't pre-build)

Task 133 streaming is **deferred behind static Task 155 + the live-UI overlay** (and alongside Task
164 resume / Task 125 escalation). It is **NOT imminent.** The manifesto + the user both forbid
pre-paying speculative span-schema design before those consumers exist. #382 shipping does NOT change
the trigger — it just means *when* streaming starts, the content foundation is done. Do not start
authoring the span log because the disk fix landed.

## UNEXPLORED / MIGHT MATTER (for whoever picks up streaming)

- **MIGHT MATTER:** D3's "single lock around (assign seq, append, flush)" assumes single-process /
  multi-thread (batch = `ThreadPoolExecutor`). Re-verify that assumption holds when you start —
  nothing about #382 changed it, but Task 87 (sandboxing) could introduce subprocesses later, which
  would break the single-lock global-seq design.
- **CONSIDER:** the `--only` snapshot reuse path (issue #443) is now a *load-bearing reader* of the
  trace (`seed_snapshot_into_shared`). A streaming format change must keep it working. #382's
  canonical strip already created one accepted caveat there (`--only` can't re-seed `${node.prompt}` —
  documented). The streaming reassembly (`from_event_log`) must feed `--only` the same seed shape.
- **UNEXPLORED:** D2's trailer `run_complete` event doubles as Task 164's graceful-vs-crash
  discriminator. Nobody has touched Task 164 yet either. If 164 and the span log are built together
  (task-133.md suggests they should be), pin D2 once for both.

## Relevant files

- `src/pflow/core/trace_io.py` — the content layer + `load_trace_file` migration seam (read this).
- `.taskmaster/tasks/task_165/task-review.md` — the "Dangerous Edges / Patterns / Gotchas" for the
  trace subsystem (the distillate; read before touching trace internals).
- `src/pflow/runtime/workflow_trace.py` — the per-sub-workflow collector save/restore around
  `engine.run` (`__trace_collector__`) is the D1 write-side unification target; still untouched.
- `src/pflow/runtime/engine/batch_executor.py` — `_capture_item_trace` + the warmup-item bypass.
- `.taskmaster/tasks/task_159/baseline/verify.sh` + `run-case.sh` — read these BEFORE trusting any
  `verify.sh` run (the `env -i` / no-re-record / pre-drift facts above).

---

> **Note to next agent**: Read this fully before acting. This is NOT the #382 implementation handoff
> (that's `task_165/`) — it's the forward-looking tacit knowledge for Task 133's *deferred* streaming
> work plus the cross-cutting baseline discovery. When ready, summarize the key points (especially:
> #382 shipped the content layer + `load_trace_file` seam; the collector-unification is still the hard
> untouched piece; `verify.sh` is pre-drifted and is a read-path oracle not a gate; streaming stays
> deferred behind Task 155) and confirm you're ready before proceeding.
