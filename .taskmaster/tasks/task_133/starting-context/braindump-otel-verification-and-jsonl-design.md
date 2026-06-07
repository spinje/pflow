# Braindump: the OTel investigation + JSONL event-stream design session

For the agent who will design/implement Task 133. The **facts, trust boundary, spike list, schema
outline, and cross-cutting insights are already in `task-133.md`** (the "verified foundation" section)
— read that first. This file is only the tacit stuff that isn't written anywhere: the reasoning
journey, the user's working style, the dead-ends, and where the bodies are buried.

## What this session actually was

It started as a discussion about Task 155 (the static `GraphModel`) and drifted — productively — into
"should the trace use a standard format like OpenTelemetry?" We investigated OTel *hard* (six research
streams + I personally verified the two load-bearing claims against the OTel spec). The verified
section in the task file is the *residue* of that investigation. The journey matters because the next
agent will almost certainly think **"why aren't we just using OpenTelemetry, it's the standard?"** —
and I don't want them to re-spend a day rediscovering the answer.

## DON'T reopen: OTel-as-the-native-substrate is settled

This was investigated thoroughly and rejected *as the native form*, for one decisive reason: **OTel
traces export on span-end only; there is no in-progress span, so OTLP cannot feed a live overlay**
(verified against the SDK spec — `OnStart` is a no-op for the standard processors). The live overlay
is the whole point of the downstream roadmap, so the native stream must be pflow's own.

The settled resolution is **"borrow the data model, not the wire envelope"**: align field *names*
(`id`/`parent_id`/`run_id` ↔ span/parent/trace ids; `gen_ai.usage.*` token names) so a *future*
export is a rename, but keep a clean flat pflow JSONL. **Do not build an OTel exporter** — it's a
hypothetical seam (one consumer); build it only if/when a second real consumer appears.

What's NOT settled and IS the real work: the spikes in the task file (esp. #1 migration blast radius,
#2 unify-vs-parallel). Those are open on purpose.

## A framework that shaped the design but ISN'T in the task file: liveness granularity

I worked out a 4-level ladder with the user that clarified *how much* liveness is actually needed.
The next agent needs this to decide the schema (specifically: do you emit a node-`start` event?):

- **L0** — emit at end of whole run (today's file: one write at the end).
- **L1** — emit per node, on completion (a tailable JSONL of completion events). This is the big win
  over L0, and it's the same granularity OTel spans give.
- **L2** — emit a node `start` event too, so the UI can light a node up the instant it begins.
- **L3** — progress *inside* a running node (LLM token streaming, agent turn 3/10).

The non-obvious realization: **a serviceable live overlay needs only L1 + the static graph.** When a
node completes, you infer "the next node is now running" from Task 155's graph — so the running node
stays highlighted the whole time *without* a start event. L2 earns its keep in exactly two cases:
**parallel/batch** (you can't infer *which* of N concurrent nodes is running from one completion) and
**long nodes** (a heartbeat to show "working, not frozen"). L3 only matters for long nodes and is a
separate concern (it maps to the existing progress callback / streaming, not the durable trace).

Why this matters for the schema: the "start+end vs completion-only" question in the file is really
"do we need L2?" — and the honest answer is "only for parallel/batch and long-node reassurance."
Don't over-build start events everywhere if L1 + graph inference covers the common case. Let the
overlay's actual needs (spike #4) drive it.

## I was WRONG about "unify the channels" — and the reversal is instructive

Early on I confidently recommended unifying the progress channel and the trace into one event stream,
on deletion-test grounds ("merging removes a parallel mechanism"). **The codebase verification
reversed this**, and the next agent should internalize *why* so they don't repeat my instinct:

The two channels are **not redundant** — they're two *thin, purpose-built* tools with genuinely
different semantics (ephemeral-live-N-events vs durable-1-rich-event-on-completion). Unifying doesn't
*delete* complexity; it *adds* a richer intermediate event type plus reconciliation logic. That's the
project's "more architecture is not more depth" — adding a seam where two thin ones already work.

So spike #2 is a *real* fork with a real fallback (keep two channels, share only the event *schema*),
NOT a foregone "unify." The north-star framing that survived: **one event source, many renderers** —
literally Task 155's pattern (one `GraphModel`, N renderers) applied to runtime events. The durable
JSONL writer, the stderr progress display, the live overlay, and a future OTel export are all
*renderers* of one event stream. But "one source" is the *aspiration*; whether the existing progress
callback physically folds into it is what spike #2 must measure.

## The hard parts, with tacit coloring the spike list understates

- **Spike #2's real difficulty is the two concurrency models**, not the event shapes. The progress
  path uses a per-worker buffer drained by the main thread; the trace path uses a
  `shared["_batch_trace"]` accumulator. Unifying means reconciling *those two*, under batch
  `ThreadPoolExecutor`. Budget for that specifically — it's the crux, and it's where I'd expect the
  "unify" option to actually die or survive.
- **Spike #1 (migration) has specific landmines** I'd check first, because they're load-bearing and
  format-coupled: `--only` snapshot restore (issue #443 — it depends on the trace surviving and on
  its exact shape) and `analyze-cache --from-trace` (reads `cache_chunks_skipped`, cache metadata off
  `llm_call`). If the JSONL drops or renames fields those readers need, they break silently. Map
  *every* reader before committing to a format — this is the "looks small, isn't" risk.
- **Cross-boundary `run_id` threading is its own sub-task.** Today each sub-workflow gets its *own*
  `execution_id` (no single id ties parent+children). A unified stream needs ONE `run_id` threaded
  across the `__trace_collector__` save/restore boundary in `WorkflowExecutor` — a collector +
  executor change, not just a format change. The file mentions this obliquely; it's a concrete chunk.
- **Batch items will bite you.** They're a *different shape* today (no `node_id`, no `timestamp`,
  keyed by `index`, `-1` = warmup sentinel). Anyone who writes the JSONL assuming uniform events with
  `node_id`+`timestamp` will mishandle batch items. Promoting them to first-class events is real work.

## How the facts were established (so you know what to trust)

The verified section is trustworthy because it was re-verified adversarially: codebase claims by
`pflow-codebase-searcher` subagents (same model class — file-grounded with `file:line`), and the two
external OTel claims (no-liveness, no-cost-attribute) by me directly against the spec. The user was
emphatic on method: **"general purpose [subagents] are very weak models… just use general purpose to
gather data not draw conclusions"**, and pflow-searcher is "the same model as you." Translation for
you: trust the file-grounded findings, but if you act on any load-bearing claim, **re-read the actual
file** — that's the house style here, and it caught a real error this session (the task doc had said
the read-side choke was `TraceTree.from_event_log`; that method *doesn't exist* — it's `from_dict`,
now corrected).

## The user's mental model (use their words)

- **"simplicity of the FINAL code, not how easy it is to get there."** Optimize the end-state, not the
  path. They'll happily accept a harder migration for a simpler resulting design.
- **"the top 10% of codebases similar to this one"** is their quality bar — *"have we considered it
  yet?"* — but immediately fenced with: *"What this doesnt mean is overfitting… and overengineering,
  this is about more simple code that is optimized for AI agents to understand and add features to."*
  So: boring, flat, greppable, agent-legible > clever. The flat JSONL choice *is* this preference.
- **Verification discipline is non-negotiable.** They repeatedly asked *"what are we SURE about and
  what needs to be proven?"* and insisted the deliverable be framed as **"a spec or a task that needs
  verification before starting?"** — landing on "design + gated spikes," not "ready to code." Honor
  that: the spikes gate implementation; don't skip to the schema.
- **Nuance-preservation guardrail (their words):** *"make sure we are not removing any nuanced
  information… If unsure, remove it and lets discuss the implications afterward, or verify it before
  making a decision."* This is why the task file *layers* a verification section on top of the original
  D1/D2/D3 rather than rewriting it. If you ever consolidate them, show the merge for review before
  deleting any original prose.
- **Roadmap, their phrasing:** *"its right after I do the initial ui → task 133 → then live execution
  (possibly hitl first)."* So: the initial UI (React Flow over Task 155's `GraphModel`) ships first;
  Task 133 is next; the live overlay (and maybe Task 125 HITL) follows. The build of 133 happens
  *after* the initial UI exists — which means spike #4 (overlay's real data needs) will have firmed up
  by the time you need it. Don't guess the overlay's needs now; you'll know them.

## UNEXPLORED / MIGHT MATTER (we didn't dig in)

- **MIGHT MATTER: dual-format reading / migration path.** We never decided whether old 2.5.0 nested
  traces must still be readable after the switch, or whether it's a clean break. `~/.pflow/debug` will
  have both. Decide this early — it shapes the reader.
- **MIGHT MATTER: in-memory memory profile.** Today in-memory is always full content; blobs exist only
  on disk. A live/streaming writer that interns *during* the run changes when interning happens and
  the memory curve. Not analyzed.
- **CONSIDER: `pflow report` and the `--report` flow** also consume the trace. Folded into "map all
  readers" but never examined specifically.
- **CONSIDER: the `seq`/flush cadence vs crash-tail tradeoff.** D3 says "flush frequently or a crash
  loses the tail" — there's an unquantified durability-vs-throughput knob there.

## For the next agent — direct advice

1. **Read `task-133.md`'s "verified foundation" section first**, then this. Don't re-investigate OTel
   as a native substrate — it's settled (see above); the spikes are the open work.
2. **Start with spike #1 (map every trace reader)** — it's the cheapest way to learn whether this is a
   2-day or a 2-week change, and it gates everything. `--only` and `analyze-cache --from-trace` are
   the landmines.
3. **Treat spike #2 as genuinely open.** Prototype the two-concurrency-model reconciliation before
   committing to "unify"; the fallback (two channels, shared schema) is respectable, not a defeat.
4. **Land #492 before the unified `llm` event** so token semantics are consistent.
5. **Match the user's working rhythm:** propose options + tradeoffs + a recommendation, mark
   confidence, and say plainly what's proven vs assumed. They will push on anything overclaimed —
   they did to me, twice, and were right both times.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
