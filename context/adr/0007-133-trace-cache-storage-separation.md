# Trace and cache stay separate stores; content is shared per-run, not globally

Task 133 originally proposed merging the trace and memoization cache into one
content-addressed per-node store (`~/.pflow/store/{content_hash}.json`), with the trace as a
generated artifact. **That merge is rejected.** The trace and cache stay two independent
subsystems; the only thing they share is *content*, and content is de-duplicated **within a single
run** (per-run interning, shipped in #382 / Task 165), **not** across the two stores. The cache
keeps its own already-compressed copy; we accept the resulting ~3 MB cross-system duplication in
exchange for fully decoupled lifecycles.

Rejected because the merge targets the wrong axis. The observed pain was a 100 MB+ trace file; the
trace↔cache overlap is only ~3 MB of that. The dominant cost is **within-trace** duplication (one
prompt stored several times per event; the same system prompt across hundreds of calls), measured at
~53 MB → ~12 MB once duplicated text is interned. Per-run interning (#382) removes that dominant
cost while staying self-contained (delete the trace → its blobs go with it), portable, and trivially
garbage-collected. A *global* shared blob store was also considered and walked back by both reviewers:
it would re-couple the lifecycles that Tasks 106/108 deliberately separated — a TTL-evicted (24 h)
cache row and a delete-freely debug trace referencing the same blob acquire the *union* lifecycle,
which is a global-GC problem — all to capture only the ~3 MB cross-system win.

The two subsystems also have genuinely different shapes and must not be forced into one substrate:
the **trace** is a sequential, run-scoped, append-and-read log in per-run JSON under `~/.pflow/debug/`
(accumulates for debugging; delete freely); the **cache** is a random-access keyed index
(`hash(config+inputs)`) in one SQLite DB `~/.pflow/cache/cache.db` storing zlib BLOBs (current-state;
TTL-evicted). A log cannot answer an O(1) point lookup; an index cannot serve a tailable stream.

**Do not read the cache's `output_hash` column as a merge mandate.** It is the cache's *own* content
hash; its `cache.py` comment ("reserved for future trace unification (Task 133)") predates this
decision and is now misleading — the planned follow-up is to correct that comment, not to act on it.
The `~/.pflow/store/{content_hash}.json` file-store idea in the original spec was the Task 106
braindump's *abandoned* leaning, overridden by the SQLite decision before 106 shipped; it appears
nowhere in `src/`.

## Considerations — the deferred streamable trace, and what is NOT decided here

The trace will *eventually* become a streamable, span-shaped, append-only JSONL event log (so a live
execution overlay can tail it) — but that is **gated on the live-overlay consumer**, a deferred
increment *after* the Task 168 static UI. **Task 168 is not that consumer**: it is static-only and
carries zero runtime data. The single load-bearing, expensive-to-retrofit decision for that future
work — "the event model must be streamable from the start" — is recorded as a *liveness bet* to be
paid when the overlay work begins, not now. The full design and an execution-ready plan live in
`.taskmaster/tasks/task_133/` (`task-133.md` + `implementation/implementation-plan.md`).

The one contract that *is* fixed today, because two substrates already depend on it, is the
structural identity join key `NodeId = (node_id, ancestor_path)` (ADR-0003; the "Runtime Overlay
Join Contract" in `src/pflow/core/workflow/graph/CLAUDE.md`). The static graph (168) emits it; the
future trace events must join onto it. Neither side may change it.

Recorded so the two stores are not later "simplified" into one — which would remove the *smallest*
cost center while re-coupling the lifecycles this separation exists to keep apart.
