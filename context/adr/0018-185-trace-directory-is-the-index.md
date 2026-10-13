# A Run is found by its filename: the trace directory listing is the index, and retention protects exactly what features read

Status: accepted (2026-10-12, Task 185)

Every pflow surface that needs a Run — `pflow resume <id>`, `pflow resume list`, `pflow report`, the
`--only` Snapshot, the Viewer's gate panel — used to find it by opening every file in `~/.pflow/debug`,
because the trace filename carried only a workflow hash, a display name and a start time, and the
directory had no bound (30,000 traces made `resume list` a 25-second command). Decision: **the trace
filename carries every fact a lookup filters on** — `workflow-trace-{hash8}-{name}.{execution_id}
[.only][.from-{src8}]-{started}.json` (`core/trace_dir.trace_filename`, the one composer;
`parse_trace_filename`, the one parser) — so a lookup is one `os.scandir` of the directory
(`trace_dir.list_traces`) plus reads of only the files in its answer. The start timestamp stays the
LAST field so a pre-185 reader sharing the same `~/.pflow` (another worktree, an older install) still
orders and finds post-185 traces. The one fact known only at the end of a run, paused-ness, is a
`.paused` sidecar written beside the trace at `finalize` **before** the `run.complete` trailer that
makes the pause durable, so a durable pause always has its marker; it dies with its trace. No second
store, no index that outlives a trace (ADR-0007's global-GC rule), no trace-format change (ADR-0010's
resume semantics and the JSONL lines are untouched). **Retention** is an age window
(`runtime.trace_retention_days`, default 14, `0` = keep all; `PFLOW_TRACE_RETENTION_DAYS` overrides
for one process and is never written to the file) applied by the trace writer at `finalize` — never by
a read-only command — that removes everything older than the window except the **Protected traces**:
a Paused Run whose token is still answerable; the newest Success/Degraded full run of each Workflow
(the Snapshot); the newest run of each Workflow whatever its status; an Attempt until the Run it
resumed is gone; a trace whose writer still holds the lock — the first three only while the Workflow's
file still exists, because `--only` and resume both re-resolve that file and a trace of a deleted
workflow serves no feature. Clean cutover: a trace written under the old grammar is invisible to every
lookup (each miss message says how many such traces are not searched), stays readable by explicit path
until it ages out, is never protected, and ages out by the timestamp its old name still carries.

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
- **Protecting one trace per recorded workflow identity regardless of whether the file exists** —
  rejected: on the owner's machine 2,074 of 2,267 recorded identities are deleted worktrees and
  scratchpads (hundreds more a month); protecting them would make the directory unbounded again and
  make every sweep re-read them.
- **Count or size bounds instead of age** — rejected for now: one knob, and the lookups are bounded by
  the listing regardless of count; age is the promise a human can reason about.

## Consequences

- **The grammar is additive-only, and an older reader ignores what it does not know.** A new fact
  becomes another optional dot-tag between the id and the timestamp; a reader parses unknown tags and
  ignores them; the name segment is always present; the timestamp stays last; every grammar pflow has
  composed stays parseable — at least for its timestamp, so the sweep can age it out: every grammar
  since the hash prefix (#378); the rare pre-#378 hash-less names are unrecognised. The timestamp's
  format and the tag charset (`[a-z][A-Za-z0-9_-]*`) are part of the grammar (amends ADR-0002's "free
  to change"). A name that matches no grammar is not a trace: never listed, never deleted. **A deleter
  keeps what it does not understand:** a trace carrying an unknown tag or an unknown sidecar is never
  removed by this version's sweep, so a later version's protection rule is honoured by every older
  binary sharing the directory. Two cross-version contracts every deleter must keep: an Attempt is
  removed only after its source is gone (a future GC of dead Attempts would otherwise make every
  binary read a pending source as answered), and a destructive act rests on a positive `stat`, never
  on a name's absence from a directory listing alone. A pending Resume token is found only
  by its name, so dropping an arm would strand issued tokens and re-open unbounded growth.
- **The name and the marker are the index; the trailer is the truth.** A lookup trusts the index; a
  consumer that acts (`resume list`, the sweep) reads the trailer of each marked trace. A crash between
  marker and trailer leaves a marker beside an `incomplete` trace, which every marker consumer ignores
  and the sweep removes with its trace. A marker write that fails disables streaming before any trailer
  exists, so the run is non-durable on every surface at once.
- **Deletion reads the truth and fails closed.** The sweep classifies from names wherever it can
  (Attempt lineage, legacy names) and otherwise reads only what it judges: per Workflow with an aged
  trace, the head of its newest trace — the Workflow's identity and newest run, walking back past
  head-less files (a run whose meta write hit a full disk), so this one read may be of a young file —
  then aged files only. For the Snapshot it walks a Workflow's aged traces newest-first until the first
  success that executed a step, so it may keep one aged success beside a younger one, never the
  reverse. It reads through strict readers that distinguish "gone" from "could not read": a file it
  cannot read is always kept, and its whole Workflow group is kept that sweep when the file could be
  what protects the others — the Workflow's newest trace, a marked trace, a trace newer than the
  Snapshot pick, or an Attempt; a workflow file whose existence cannot be determined keeps its group.
  A trace with a `run.complete` trailer had every earlier line fully flushed (the writer disables
  streaming on the first fault), so a trailer carrying `nodes_executed > 0` is sufficient evidence of a
  usable Snapshot. A writer can finish between the listing and the unlink (it held its lock while the
  sweep classified), so every judgment is re-checked once its lock is seen free — and before each
  unlink attempt, since Windows has no lock to probe: a `.paused` marker that appeared, or a trailer on
  a trace read as unfinished, keeps it that sweep. A hash collision is judged per workflow path: a trace whose head names another
  workflow gets that workflow's newest-run and Snapshot rules.
- **Consumption evidence outlives its source.** Whether a Resume token was already answered is read
  from the Attempt that answered it (`resume_source._find_consuming_attempt`), so an Attempt is removed
  only after its source is gone, chains unwind root-first, and a source whose removal failed keeps its
  Attempts; a live Attempt that has recorded no work is a reservation, not consumption, for the sweep.
  The loader re-checks that its source still exists after the consumption check, and an Attempt that
  vanished mid-check counts as consumed, so a concurrent sweep makes a resume refuse — never
  double-answer. `resumed_from` stays pure lineage for data (ADR-0010).
- **Retention is configured leniently.** Every settings model (the root and each section) allows
  unknown keys and keeps them through a save (a strict model would turn a typo into a whole-file fallback that drops
  API keys and is written back by the next settings command; an ignoring model would erase the typo on
  the next save and switch deletion on silently); the sweep prunes nothing — with a warning — when a key
  that looks like the retention key sits in the wrong place or spelling at any level (one walk over every
  model's unknown keys, including keys inside an unknown section), when the file failed to load (a file that exists but cannot be read is a failed load, never "no
  file"),
  or when the environment override is not a non-negative integer; other unknown keys are ignored, so a
  newer version's future key never switches an older lane's retention off. `SettingsManager.save()` refuses after a failed load. The sweep reads the
  settings once more per run, so the insecure-permissions warning is printed once per settings file per
  process, not once per load. An older pflow's settings
  write still drops the key: `PFLOW_TRACE_RETENTION_DAYS=0` is the opt-out that survives it.
- Every trace path printed before this version keeps working with `pflow report <path>` until the
  trace ages out; the run behind it is not listed anywhere. Do not run pre- and post-185 pflow versions
  against one `~/.pflow`: an older pflow can see and answer a newer pflow's pause, and its answer —
  written under the old grammar — is invisible to the newer one, which would offer the token again;
  and a newer pflow ages out the older one's traces, pending pauses included, after the window. Answer
  each pause with the version that issued it. `PFLOW_TRACE_RETENTION_DAYS` is per process; the
  settings key is the opt-out for every pflow process. Task 121
  (record/replay of `agent` steps from traces) will need a durable-recording rule of its own — nothing
  is pinned for it here.
