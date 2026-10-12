# A Run is found by its filename: the trace directory listing is the index, and retention protects exactly what features read

Status: accepted (2026-10-12, Task 185)

Every pflow surface that needs a Run — `pflow resume <id>`, `pflow resume list`, `pflow report`, the
`--only` Snapshot, the Viewer's gate panel — used to find it by opening every file in `~/.pflow/debug`,
because the trace filename carried only a workflow hash, a display name and a start time, and the
directory had no bound (30,000 traces made `resume list` a 25-second command). Decision: **the trace
filename carries every fact a lookup filters on** — `workflow-trace-{hash8}[-{name}]-{started}.
{execution_id}[.only][.from-{src8}].json` (`runtime/trace_dir.trace_filename`, the one composer;
`parse_trace_filename`, the one parser) — so a lookup is one `os.scandir` of the directory
(`trace_dir.list_traces`) plus reads of only the files in its answer. The one fact known only at the
end of a run, paused-ness, is a `.paused` sidecar file written beside the trace at `finalize`, after the
`run.complete` trailer and before the writer's advisory lock is released; it dies with its trace. No
second store, no index that outlives a trace (ADR-0007's global-GC rule), no trace-format change
(ADR-0010's resume semantics and the JSONL lines are untouched). **Retention** is an age window
(`runtime.trace_retention_days`, default 14, `0` = keep all) applied by the trace writer at `finalize`
— never by a read-only command — that removes everything older than the window except the **Protected
traces**: a Paused Run whose token is still answerable; the newest Success/Degraded full run of each
Workflow (the Snapshot); the newest run of each Workflow whatever its status; an Attempt until the Run
it resumed is gone; a trace whose writer still holds the lock. Clean cutover: a trace written under the
old grammar is invisible to every lookup, stays readable by explicit path, is never protected, and ages
out by the timestamp its old name still carries.

## Considered options

- **A global index (SQLite or a JSON manifest) beside the traces** — rejected: it outlives the traces
  it describes, so every deletion must also update it (the "global-GC problem" ADR-0007 rejected for
  blobs) and a second writer must stay consistent with the first; the directory listing already is a
  consistent index once the name says enough.
- **Per-workflow subdirectories** — rejected: a lookup by run id, which knows no workflow, would list
  every subdirectory; one flat `os.scandir` of 30,000 names costs ~80 ms.
- **Renaming the trace at `finalize` to stamp its status** (`….paused.json`) — rejected: it moves a file
  the Viewer may be tailing and the path a run has already printed, and needs a Windows rename-retry; the
  sidecar is one `open(…, "x")` and leaves every path stable.
- **Migrating pre-cutover names into the new grammar** (one head+tail read per file, ~15 s once on
  30,000 files) and a compatibility arm that still reads old names — rejected by the owner: pflow has no
  users, and the simplest final code has one grammar and one lookup path.
- **Count or size bounds instead of age** — rejected for now: one knob, and the lookups are bounded by
  the listing regardless of count; age is the promise a human can reason about.

## Consequences

- **The trailer is the truth, the name and the marker are the index.** A lookup trusts the index; a
  deletion reads the trailer (`trace_retention.prune_traces` head+tail-reads every current-grammar
  candidate before touching it) and re-creates a missing marker it finds. A crash between the trailer
  flush and the marker create is the only way a paused trace lacks its marker; `resume <token>` still
  resolves it (it reads the trailer), `resume list` shows it after the next sweep heals it.
- **Consumption evidence outlives its source.** Whether a Resume token was already answered is read
  from the Attempt that answered it (`resume_source._find_consuming_attempt`), so an Attempt is removed
  only after its source is gone; a live Attempt that has recorded no work is a reservation, not
  consumption, for the sweep's purposes. `resumed_from` stays pure lineage for data (ADR-0010).
- **Accepted residual:** a human answering a consumed token older than the window in the same
  millisecond a sweep removes its source and its Attempt can get a second answer accepted; the
  concurrent-resume race is already tolerated (#763), and an interprocess lock over every resume is not
  worth that window.
- Every trace path printed before this version keeps working with `pflow report <path>`; the run behind
  it is not listed anywhere. Task 121 (record/replay of `agent` steps from traces) will need a
  durable-recording rule of its own — nothing is pinned for it here.
