# Task 185 — Implementation plan

Planner: Fable, 2026-10-12, worktree `feat/task-185-run-lookup` @ `50f62327` (= origin/main). Spec:
`../task-185.md`. Checkpoint artifact: `show-before-code.md` (CP-1, handed back BEFORE Phase 1).
Vocabulary: CONTEXT.md nouns (Run, Attempt, Paused, Resume token, Snapshot, Workflow); LANGUAGE.md
terms (module, interface, seam, depth, deletion test).

## 0. Investigation record (what the plan rests on)

Verified against code at `50f62327` (file:line cited; the spec's cites held):

- Filename composer `runtime/workflow_trace.py:66-98`; sole production caller `_open_stream` `:993-997`
  (`Path.home()/.pflow/debug` + `format_trace_filename(...)`, `self.start_time` microsecond ts). The
  execution id is on the meta line (`_meta_fields` `:1063-1075`) and the trailer (`_aggregates` `:1090`),
  never in the name. Recency key `_trace_recency_key` `:122-136` anchors on `-{ts}.json$`.
- The 8 debug-dir spellings: `workflow_trace.py:299,993`, `resume_source.py:906,1134`,
  `trace_loading.py:289,338`, `report.py:53`, `run_tailer.py:47`. Three recency rules: filename ts
  (resume, `--only`, analyze-cache's whole-name sort `trace_loading.py:304`), mtime (`report.py:57`,
  `run_tailer.py:250`).
- Twins across the `runtime/ ↛ ui/` rule (ui MAY import runtime — `tests/test_import_hygiene.py:23-28`;
  today `src/pflow/ui/` imports nothing from `pflow.runtime`): `resume_source._is_trace_locked` ↔
  `run_tailer.is_trace_locked`; `resume_source._read_trailer_line`/`_scan_tail_for_trailer` ↔
  `run_tailer.read_run_trailer`/`_scan_tail_for_terminal`; `resume_source._read_trace_meta_line` ↔
  `run_tailer._read_meta`. (`_iter_raw_trace_lines` ↔ `run_node._iter_trace_lines` is a fourth pair —
  NOT in scope; noted for a follow-up.)
- Engine: `engine.py:1041` calls `load_snapshot_or_raise(workflow_path, only_node, …)`; its signature
  does not change. **No engine line changes in this task.** `workflow_executor.py` untouched.
- Trace format: no meta/event/trailer field is added or changed; `TRACE_FORMAT_VERSION` stays 2.10.0.
  The sidecar marker and the filename are outside the format. The Task-159 baseline still runs (§8).
- Lock: `_lock_trace_handle` `:101-119` POSIX-only, held for the run; `finalize` `:1138-1158` flushes the
  trailer then closes (releases). Windows: no lock; probes return `None`; a file another process holds
  open cannot be renamed/unlinked (`PermissionError`, winerror 5/32 — retry helper precedent
  `mcp/manager.py:15-31`).
- `PFLOW_EXECUTION_ID` is read unvalidated at `cli/commands/run.py:244`; minted as `uuid4` at
  `ui/server.py:1085,1350`; the collector mints `uuid4` otherwise (`workflow_trace.py:593`).
- MCP `workflow_execute` writes traces (`execution_service.py:151` `RunnerConfig()`; `runner.py:224-226`).
  Stale claims to fix: `workflow_trace.py:553-555`, `:983-984`, ADR-0010 `:149-150`.
- HOME isolation: `tests/conftest.py:448-450` patches `Path.home` per test → the resolver MUST be a
  function evaluated per call, never an import-time constant. `real_home_guard` audits real-`~/.pflow`
  access. `disable_trace_file_writes_by_default` (`conftest.py:285-316`) no-ops `_open_stream` outside
  `@pytest.mark.trace_files` → `finalize()` returns before any directory work in those tests.
- Measured on the owner's dir (30,115 files): `os.scandir`+parse+sort 82 ms; `Path.glob` 346 ms;
  stat-all 379 ms; head read 0.43 ms/file; tail read 0.39 ms/file; head+tail in one open 0.41 ms/file;
  unlink 75 µs/file; sample statuses: 89% success, 6% failed, 0.2% paused, 0.2% incomplete, 4%
  legacy/no-meta; max name length 82; Oct 2026 alone 21,168 files (~1,700/day).
- Cross-task scan (`./scripts/tasks`, 2026-10-12): no in-progress task overlaps. Live lanes: #801
  (shares `workflow_trace.py` — it edits the trailer `warnings` write in `_aggregates`; this plan edits
  `_open_stream`, `finalize`, `_iter_workflow_traces`, `load_full_run_events`, `format_trace_filename`,
  `_trace_recency_key`, `__init__` validation and two stale comments — `_aggregates` is NOT touched;
  merge conflicts are textual at most), #833 (disjoint). Related issues read in full: #734 (list filter —
  not built here; the `workflow_path` it needs is still on the row), #729 (abandoned trace — unchanged;
  incomplete traces now age out), #763 (claim seam — not built; a claim needs its own file, the marker is an index entry), #542 (the retention issue this task closes).
- Shipped substrate reused: 171's one consumption policy (`_find_consuming_attempt`/`_attempt_consumed_work`),
  173's `scan_traces` caches, 133/172's single read seam `load_trace_file`, 184's `trace_path` identity rule.

CP-1 RULED 2026-10-12 (the user, via the main orchestrator): Q1 grammar + sidecar accepted; Q2 default
**14** days (deleting too early is irreversible, disk is not; 14 days at the owner's rate ≈ 1.5 GB);
Q3 accepted plus a fifth protected rule (the newest run of each Workflow regardless of status, so
"report my last run" works when it failed); Q4 **clean cutover — no migration, no legacy arm**:
pre-upgrade names are invisible to every lookup, readable by explicit path, aged out by their parsed
timestamp, never protected (we have no users; simplest final code); Q5 the ADR and the two CONTEXT.md
nouns are written on this branch (`context/adr/0018-185-trace-directory-is-the-index.md`,
`context/CONTEXT.md`); Q6 consent for P5 on the owner's directory behind a backup gate (§P5). The spec's
Retention requirement is rewritten to the five rules. **Q4 precondition (the user's):** if removing
the legacy arm makes any EXISTING test or surface reveal a real dependency on reading old names (not a
fixture that merely uses the old grammar — those are rewritten), STOP and hand back. Planner's check at
`50f62327`: no test asserts that a trace written by an older pflow is found; every old-grammar name in
`tests/` is a fixture built by `format_trace_filename` or by hand (plan §P1); the only surfaces that
change are the ruled ones (pre-upgrade tokens, history rows, report auto-select).

## 1. Design (D2, resolved)

**The directory listing is the index.** One module owns where traces live, what their names say, and
how to list them. Every consumer asks the listing, then reads only the files in its answer.

### 1.1 Filename grammar (one composer, one parser)

```
workflow-trace-{hash8}-{name}.{execution_id}[.only][.from-{src8}][.{tag}…]-{started}.json
marker:  {trace filename}.paused            (empty file; present ⇔ the Run finalized Paused)
legacy:  workflow-trace-{hash8}[-{name}]-{started}.json   (pre-cutover; {started} may lack -ffffff)
```

**Field order — the timestamp stays LAST (amends CP-1 Q1's field order; confirm at handback).** The owner
runs several pflow versions at once (lanes in other worktrees on older bases share one `~/.pflow`, and
a PyPI install may lag). A pre-185 reader sorts by `_trace_recency_key`'s `-{ts}.json$` and globs
`workflow-trace-{hash}-*.json`: with the timestamp last, every pre-185 reader still orders, finds
and reads post-185 traces correctly (its `--only` takes the newest Snapshot, its `resume list`
head-reads them); with the timestamp in the middle a pre-185 `--only` would rank every new trace as
the OLDEST and seed stale upstream (the PR #459 class). **The name segment is never omitted** — the
composer writes `-{name}` always, `workflow` included (today's `safe_name != "workflow"` special case
goes: `run.py:863-864` names every `workflow.pflow.md` run "workflow", 23 of the owner's traces are
nameless, and a nameless new name would not match the pre-185 `{hash}-*` glob). The dot before the id
is what makes the two arms unambiguous. Version-skew hazard that REMAINS and is documented (ADR, P4):
a pre-185 pflow can answer a post-185 pause (it head-reads every file) and writes its Attempt under a
legacy name that post-185 never reads, so the newer pflow lists the pause as still pending and would
let it be answered again — answer each pause with the version that issued it; "answer pending pauses
before upgrading" goes in the guide and the PR body. A narrow consumption arm over legacy names would
close it but contradicts the ruled cutover — flagged at handback as the user's call.

- `hash8` = `md5(workflow_path or "")[:8]` (unchanged); `name` = sanitized `[A-Za-z0-9_-]{1,30}`, `workflow`
  when empty; `started` = `%Y%m%d-%H%M%S-%f` (the ONE recency key). `trace_filename` takes `started:
  datetime` and formats it itself — no caller can pass a short or foreign timestamp (102 fixture sites
  pass `YYYYMMDD-HHMMSS` today; the shared test helper converts).
- `execution_id` = the run's id verbatim; charset `[A-Za-z0-9_-]+` (uuid4 in production). The collector
  validates a forced id (`PFLOW_EXECUTION_ID` → `RunnerConfig.execution_id`) in `__init__` and raises
  `ValueError("execution_id must be filename-safe …")` — an internal contract violation, same posture as
  `load_resume_source`'s precondition `ValueError`; unreachable from the UI (uuid4). The composer and the
  parser share ONE set of field patterns (`_ID = r"[A-Za-z0-9_-]+"` etc.), and `trace_filename` asserts
  `parse_trace_filename(result)` is a current-grammar parse — a composer/parser mismatch fails at write
  time, never as an invisible file.
- `.only` ⇔ `only_node is not None` (stamped before `start_streaming` — Task 173 invariant). `.from-{src8}`
  ⇔ `resumed_from` set (set at construction); `src8` = the first 8 characters of the source id in the id
  charset (`[A-Za-z0-9_-]{1,8}` — the tag accepts what the id validator accepts; fixtures use ids like
  `src`); the consumer confirms `resumed_from == id` on the loaded dict. **Unknown tags** (`\.[a-z][A-Za-z0-9_-]*`)
  parse and are ignored: a later pflow's added fact never makes this version mis-file its traces.
- Parse: current arm first —
  `^workflow-trace-([0-9a-f]{8})-([A-Za-z0-9_-]+?)\.([A-Za-z0-9_-]+?)((?:\.[a-z][A-Za-z0-9_-]*)*)-(\d{8}-\d{6}-\d{6})\.json$`,
  tags split on `.` and matched as `only` / `from-{src8}` / unknown; then the legacy arm
  `^workflow-trace-([0-9a-f]{8})(?:-([A-Za-z0-9_-]+))?-(\d{8}-\d{6}(?:-\d+)?)\.json$` — **its name
  group admits no dot** (the old sanitizer never produced one), so a dotted name that fails the current
  arm is NOT legacy. Three classes result: current (a lookup result), legacy (parsed for its timestamp
  only — never a lookup result, aged out by the sweep, never protected: the ruled cutover), and
  **unrecognised** (a dotted name the current arm rejects, a wrong hash width, a pre-#378 hash-less
  name, junk) — not a trace: never listed, never deleted, never counted. The timestamp's FORMAT
  (`%Y%m%d-%H%M%S-%f`) and the tag charset (`[a-z][A-Za-z0-9_-]*`) are part of the grammar from here
  (ADR-0002's "the timestamp format is free to change" is amended in P4). `pflow report <path>` and `load_trace_file` read any of them
  by explicit path.

### 1.2 Module `src/pflow/core/trace_dir.py` (new; mechanism, no policy)

> **As built — supersedes the lines below** (completion gate rounds 1–2; dispositions in the progress log):
> `workflow_file_state` → `core/path_state.py::path_state(path) -> "present"|"absent"|"unknown"` (a dangling
> symlink is `unknown`; settings, retention, resume and `resume list` all use it). `is_trace_locked(path)` has
> no `strict=` mode; the deleter probes through `read_trace_meta_and_lock_strict` (one open). `Unreadable` is
> `TraceUnreadableError(PflowError)`; its message names the path once (`… {path}: {strerror}`).

Home: `core/`, beside `core/trace_io.py` (the read seam) — NOT `runtime/`: `pflow/runtime/__init__.py`
imports the compiler and the engine, so a `ui/` import of `pflow.runtime.trace_dir` would drag ~100
modules into the Viewer process; `core/prompt_cache_analysis/trace_loading.py` also stays inside `core/`.

```python
def debug_dir() -> Path                       # Path.home()/".pflow"/"debug", evaluated per call

@dataclass(frozen=True, slots=True)
class TraceEntry:
    path: Path
    workflow_hash: str                        # hash8
    started: str                              # the timestamp field as written
    execution_id: str | None                  # None ⇒ legacy name (pre-cutover): only the sweep ever holds one
    only: bool                                # .only tag
    resumed_from_prefix: str | None           # .from-xxxxxxxx tag
    paused: bool                              # a .paused marker exists beside it
    @property legacy -> bool                  # execution_id is None — never returned by list_traces() unless include_legacy
    @property started_at -> datetime          # strptime of `started` (both ts widths)

@dataclass(frozen=True, slots=True)
class TraceListing:                           # what list_traces returns
    traces: list[TraceEntry]                  # current grammar, newest-first
    legacy_count: int                         # pre-cutover names seen (for the "not searched" clause in miss messages)
    legacy: list[TraceEntry]                  # filled only with include_legacy=True (the sweep)
    orphan_markers: list[Path]                # `.paused` files with no trace beside them (the sweep collects them)

def trace_filename(workflow_path: str | None, workflow_name: str, started: datetime, execution_id: str,
                   *, only: bool = False, resumed_from: str | None = None) -> str   # asserts parse-back
def parse_trace_filename(name: str) -> ParsedTraceName | None      # (hash, started, id, only, from) — path-free
def list_traces(directory: Path | None = None, *, include_legacy: bool = False) -> TraceListing
    # ONE os.scandir; markers folded in; newest-first by (started, name); empty listing if the dir does
    # not exist (FileNotFoundError); any OTHER OSError on the directory PROPAGATES (a lookup must never
    # report "no runs" because the directory could not be read; the sweep catches it and warns).
    # Legacy names are counted always and returned only with include_legacy — the sweep is the ONE caller.
def find_trace(entries: Sequence[TraceEntry], execution_id: str) -> TraceEntry | None
    # exact name match, zero reads. ONE home for by-id resolution — CLI resume, /api/gate, the pinned
    # tailer and run_node all call it; each applies its own --only policy after.
def workflow_hashes(workflow_path: str) -> frozenset[str]           # the 3 spellings _iter_workflow_traces hashes today
def paused_marker(trace_path: Path) -> Path                         # trace_path.with_name(trace_path.name + ".paused")
class Unreadable(Exception): ...                                     # raised by the strict readers: the file exists but could not be read/parsed
def read_trace_meta_strict(path: Path) -> dict[str, Any] | None     # the ONE implementation: FileNotFoundError propagates (gone); any other OSError / UnicodeDecodeError / a corrupt first line that ENDS IN A NEWLINE → raises Unreadable; None = a readable file with no meta line, INCLUDING a first line with no terminating newline (a write cut by a full disk — the same mid-flush rule the trailer reader applies; never Unreadable, so such a file ages out instead of freezing its group)
def read_trace_trailer_strict(path: Path) -> dict[str, Any] | None  # same contract; None = readable, no (or not yet a) trailer; 64 KB tail, oversized full re-read
def read_trace_meta(path: Path) -> dict[str, Any] | None            # the lenient twin for display consumers: strict → None on ANY failure (the union of today's _read_trace_meta_line / run_tailer._read_meta guards; the UI pops `inputs`/`step_identity` in its cache layer)
def read_trace_trailer(path: Path) -> dict[str, Any] | None         # lenient twin of the strict reader
def is_trace_locked(path: Path, *, strict: bool = False) -> bool | None   # moved twin; FileNotFoundError → False (no writer exists — a vanished file must not read as "maybe live"); a flock BlockingIOError → True; any OTHER flock error (ENOTSUP/ENOLCK — a filesystem without flock) → None, "age decides", never a silent "locked forever"; an open OSError → None lenient / raises Unreadable strict; Windows (no fcntl) → None
def workflow_file_state(path: str) -> Literal["present", "absent", "unknown"]   # os.stat: FileNotFoundError/NotADirectoryError → absent; other OSError → unknown (Python 3.14's is_file() swallows PermissionError — precedent workflow_resolver._file_exists)
```

Deletion test: deleting it re-scatters the grammar over 8 sites and the 3 twins over 2 modules — keep.
It imports only stdlib + `core.trace_io` constants; `ui/` and `runtime/` both import it.
`format_trace_filename` and `_trace_recency_key` in `workflow_trace.py` are deleted (their callers move).
Fate of the UI twins in `ui/run_tailer.py`: `_read_meta`, `read_run_trailer`, `_scan_tail_for_terminal`
are DELETED (callers import `read_trace_meta`/`read_trace_trailer` from `trace_dir` into `run_tailer`'s
namespace, so `monkeypatch.setattr(run_tailer, "read_trace_meta", …)` keeps working — `test_run_tailer.py:309`
retargets from `_read_meta`); `read_run_status` stays as a two-line wrapper over `read_trace_trailer`
(its `_check_stopped` caller). The oversized-trailer pins (`test_run_tailer.py:194`, `test_resume_list_cli.py`
oversized tests) move to `test_trace_dir.py` against `read_trace_trailer_strict` and are mutation-verified
there (drop the full re-read → they fail).

### 1.3 Writer (`runtime/workflow_trace.py`)

- `__init__`: validate `execution_id` charset (above).
- `_open_stream`: `debug_dir() / trace_filename(self.workflow_path, self.workflow_name, timestamp,
  self.execution_id, only=self.only_node is not None, resumed_from=self.resumed_from)`.
- `_open_stream` records `self._trace_dir = trace_dir` the moment it resolves it (survives
  `_disable_streaming`, which nulls `_stream_path`). `finalize`: `agg = self._aggregates()` once;
  **if `agg["final_status"] == "paused"`, create the marker BEFORE the trailer** (`open(marker, "x",
  encoding="utf-8")`, closed at once; `FileExistsError` fine) — a marker `OSError` →
  `self._disable_streaming(exc)` and NO trailer is written, so the run is non-durable on every surface at
  once (`is_durable_pause` False; the trace on disk reads `incomplete`, never a paused trailer the
  Viewer or `resume <id>` could accept while the CLI said "failed"); then flush
  `{**agg, "kind": "run.complete"}`; `_close_stream()` in the `finally`; then
  `trace_retention.sweep_after_write(self._trace_dir)` (a lazy import inside `finalize` — `trace_retention`
  imports `resume_source`, which imports `workflow_trace`) — called whenever `self._trace_dir` is set,
  i.e. the stream was opened at least once: so after a mid-run stream fault too (a full disk is exactly
  when pruning helps) and never under the pytest gate or `--no-trace` (no open, no dir).
  Publication invariant (the ADR's): **a durable pause always has its marker, because the marker is
  written before the trailer that makes the pause durable.** A crash between the two leaves a marker
  beside an `incomplete` trace: every marker consumer (`resume list`, the sweep) reads the trailer and
  ignores it; the sweep removes such orphan/stale markers with their traces. Nothing ever "heals" a
  marker — there is nothing to heal.
- The pytest gate is unchanged: outside `trace_files`, `_stream is None` → `finalize` returns `None`
  before the marker and sweep.
- Stale comments corrected: `:553-555` and `:983-984` (MCP persists; `--no-trace` is the only `False`).

### 1.4 Readers

> **As built — supersedes the lines below:** `_iter_workflow_traces(entries, workflow_path, *, unreadable=)`
> — entries are required (callers own the listing; no `debug_dir`/`None` fallback). `--only` never walks past
> an unreadable candidate: a strict tail read (an unreadable tail goes to the full load), the full load with
> `unreadable="raise"`, mapped to `OnlySnapshotUnreadableError` (advice: restore read permission; never move or
> delete a trace — it may be consumption evidence). `report` auto-select names every candidate it could not read
> or parse (either read) and says "No readable completed trace" when that explains the miss.
> `list_paused_runs(debug_dir=None)` owns its listing (no `listing=`); strict reads; `PausedRunListing(runs,
> hidden_missing_file: list[PausedRun], unreadable: list[str], legacy_count)`; `resume list` names hidden tokens
> + paths and unreadable traces, and says "No readable paused runs; the list is incomplete." instead of "No
> paused runs." when any were unreadable. By-id on an `--only` trace refuses `ResumeNotResumableError` ("was an
> --only run"), and a failed `--only` run prints no resume hint. The post-consumption check is `path.stat()`,
> never `exists()`. `/api/gate`: gone → aged-out 404, unreadable → 500 naming the file, corrupt → not paused;
> the Viewer scan cache never caches a read fault.

| Reader | After |
|---|---|
| `workflow_trace._iter_workflow_traces(debug_dir, workflow_path, *, entries=None)` | `entries = entries if entries is not None else list_traces(debug_dir).traces`; candidates = entries with `workflow_hash in workflow_hashes(workflow_path)` and `not e.only` (no `resumed_from=` parameter — the consumption check has its own iterator); then the existing per-file guards (load, dict, `workflow_path` re-check, `2.` version, `only_node is None` — kept: a hand-made name may carry no tag). Still NEVER filters `final_status`. |
| `workflow_trace.load_full_run_events` | `debug_dir()` resolver; lists once; **shortlists by a lenient tail read first** (newest-first over the workflow's non-`.only` entries: `read_trace_trailer` → keep only `success`/`degraded`), then feeds `_iter_workflow_traces(entries=shortlist)` which does the full loads with its existing guards — so a workflow with 1,000 young failed runs costs 1,000 tail reads (0.4 s) and ONE full load, not 1,000 full loads (the spec's "read only files that belong to the answer"); the status policy stays the consumer's, the iterator still never filters `final_status`. `OnlySnapshotMissingError`'s suggestion gains the two new causes: "its trace aged out of `runtime.trace_retention_days`" and, when `legacy_count > 0`, "N traces written by an earlier pflow version are not searched". |
| `resume_source._select_resume_trace(debug_dir, workflow_path, execution_id, *, listing)` by id | `hit = find_trace(listing.traces, id)`; if hit: `.only` tag or `meta.only_node` → fall to missing (mirrors today's skip); else load. Then missing — `ResumeSourceMissingError`'s message gains, when `listing.legacy_count > 0`, the clause "N traces written by an earlier pflow version are not searched (readable with `pflow report <path>`)", and always the hint "or its trace aged out of `runtime.trace_retention_days`" (the same two causes every by-id miss — `/api/gate` 404, `report <path>` not found — names). |
| `resume_source._select_resume_trace` by workflow | unchanged logic over `_iter_workflow_traces(…, entries=entries)`. |
| `resume_source._find_consuming_attempt(debug_dir, W, X, *, entries, count_live=True)` | Does NOT go through `_iter_workflow_traces` (its `except (JSONDecodeError, OSError): continue` at `workflow_trace.py:176` is right for `--only`/analyze-cache and wrong here — a swallowed read fault would read as "no consumer", i.e. a second answer). It iterates the `.from-{X[:8]}` entries of W's hashes itself, newest-first, loading each with three outcomes: `FileNotFoundError` → **consumed** (the sweep removes an Attempt only after its source is gone, so a vanished Attempt means a gone source; fail closed); any other `OSError` → `count_live=True` callers (the loader, `resume list`) raise **`ResumeSourceUnreadableError(ResumeSourceError)`** ("could not read attempt <path>; retry" — a new subclass with its own `refusal` literal `source_unreadable`, added to `ui/server._RESUME_REFUSALS` so `/api/resume` returns a typed 409 and the refusal-map meta-test `test_ui_interaction_server.py:1884-1903` stays green; the browser's generic refusal arm renders it — P2 verifies whether `web/src/api/client.ts`'s union needs the one literal and, if so, that one-line `web/` edit is in scope) and the sweep treats the source as protected this sweep; `JSONDecodeError` (which `load_trace_file` also raises for a `UnicodeDecodeError`) → skip as today. The loaded dict keeps the existing guards (path re-check, `2.`, `only_node`, `resumed_from == X`) and the consumed test; `is_trace_locked(...) is True` applies only when `count_live`. `_attempt_consumed_work` lets a `FileNotFoundError` from its raw re-read PROPAGATE and each caller maps it: the consumption check → consumed; the by-workflow selection loop (`_select_resume_trace:300`) and `list_paused_runs` → skip this candidate (a vanished candidate must fall through to the next older run, never be selected and then refused as missing). ONE policy, one flag. |
| `resume_source.load_resume_source` | lists ONCE (`listing = list_traces(debug_dir)`) and passes it to selection and the consumption check — a public lookup performs exactly one directory enumeration (pinned by the scandir-count test). **After the consumption check returns `None`, `path.exists()` is re-checked; a source that vanished refuses with `ResumeSourceMissingError`** (the one `stat` that closes the resume-vs-sweep race: the sweep unlinks a source before its Attempt, so a source still present after the check had no consumer when it was checked). `_iter_raw_trace_lines` keeps raising on an earlier malformed line but a `FileNotFoundError` from it is converted by the same refusal. |
| `resume_source.answerable_pause(entry, meta, trailer, file_state) -> Literal["yes","no","unknown"]` (new, ONE predicate, pure — callers pass the reads: `list_paused_runs` the lenient ones, the sweep the strict ones) | the row rule `list_paused_runs` applies today — marker-bearing, trailer `paused`, `paused_node_id` + `gate_request` present, not `.only`, not inline `ir-hash:` — **plus the workflow file's state** (`trace_dir.workflow_file_state`, never `is_file()`: it raises `PermissionError` on 3.10–3.13 and returns `False` on 3.14): `present` → `yes`; `absent` → `no` (a by-id resume re-resolves the file and refuses "no longer exists", `resume_preflight.py:114-122`, so such a token can never be consumed); `unknown` → `unknown` (the sweep keeps the group; `resume list` shows the row with a "(workflow file unreadable)" note). Shared by `list_paused_runs` and the sweep's rule 1 so the list, the verdict and retention agree. Behaviour change (flagged at handback): `resume list` no longer lists a pause whose workflow file was deleted — on the owner's machine that is all 26 currently pending rows (#734's "stale pauses" symptom) — and SAYS SO: `list_paused_runs` returns `PausedRunListing(runs, hidden_missing_file: int, legacy_count: int)` (`PausedRun` unchanged; the CLI is the only caller) and the text renderer prints "N paused runs are not listed: their workflow file no longer exists" (JSON: the same counts on stderr), paired presence/absence tested. |
| `resume_source.list_paused_runs(debug_dir=None, *, listing=None) -> PausedRunListing` | `listing = listing or list_traces(debug_dir)`; rows = `[e for e in listing.traces if e.paused]` newest-first → `read_trace_meta` + `read_trace_trailer` + `workflow_file_state` → `answerable_pause` → consumption via `_find_consuming_attempt(..., entries=listing.traces)`; a candidate that vanishes mid-check is skipped. The CLI's "No paused runs." gains the legacy clause when `listing.legacy_count > 0` and the hidden-pause sentence when `hidden_missing_file > 0`. |
| `cli/commands/report.py` (+ `execution/resume_preflight.py:138-152`, which re-raises the by-id miss with its own message and must carry the clauses; `cli/commands/resume.py:452,470`; `cli/commands/analyze_cache.py:164`; `rendering/traces_list.py:33-38`) | `listing = list_traces()`; a LAZY generator over `listing.traces` newest-first: tail-read (`read_trace_trailer` not `None`) then `_trace_is_complete` (the existing full-load check stays) — the first that passes is chosen; never a list comprehension over all entries. "No trace files found" / "No completed trace found" gain the legacy clause when `listing.legacy_count > 0`; the `--help` example gets a real name. |
| `core/prompt_cache_analysis/trace_loading.py` | `debug_dir()` resolver at `:289,:338`; `_autoload_trace` and `list_traces_for_workflow` list ONCE and pass the listing to `_collect_candidate_traces` and to the no-match note (`bool(listing.traces)` replaces the `:355` glob; a second note when `listing.legacy_count > 0`: "N traces written by an earlier pflow version are not searched — pass `--from-trace <path>`"); `list_traces_for_workflow` sorts by `(started, name)` desc via the parsed entry (not `path.name`); `_autoload_selection_with_disclosure`'s `failed[0][0].name > chosen.name` compares the same key. The analysis still loads every trace of the workflow (out of scope, spec). |
| `ui/run_tailer.scan_traces(workflow_key, debug_dir)` | `_stat_sorted_listing(directory, wf_hash)`: the `_DIR_LIST_CACHE` key becomes `(directory, wf_hash|None)`, its value an IMMUTABLE `tuple[TraceEntry, ...]` from `list_traces` (one scandir, gated on dir mtime as today — stat the dir BEFORE listing, as now; never sort a cached list in place: the cache is read from the Starlette threadpool and the tailer's `to_thread`); scoped = `workflow_hash == wf_hash`; **order = `(started, name)` desc (D3), no stat for ordering**; the per-file stat remains only as the `_SCAN_CACHE` key. `_file_facts` calls `read_trace_meta` (then pops `inputs`/`step_identity`) and `read_trace_trailer`. The vanished-entry prune uses the scoped entry set instead of a name prefix. `TraceCandidate` shape unchanged. |
| `ui/run_tailer.RunTailer._resolve_pinned` | `find_trace([e for e in list_traces().traces if e.workflow_hash in workflow_hashes(self._key)], run_id)`; on a hit, one `read_trace_meta` for `content_hash` (the stale check) + the `_same_path` guard. No `scan_traces`. Nothing ever renames a trace (Q4: no migration), so the tailer's fixed-path lifecycle is unchanged. |
| `ui/run_node._resolve_trace` pinned | `find_trace` over the scoped listing (same helper as above — put `find_workflow_trace(workflow_key, run_id)` in `run_tailer` and use it from both). |
| `ui/server.gate` | `entry = find_trace(list_traces().traces, run_id)`; 404 if `None` (the 404 body gains the legacy clause when `legacy_count > 0`; `web/` stays untouched — the banner copy "may have been cleared" is still true); then the existing full `load_trace_file` + 404-if-not-paused logic. No `scan_traces()`. |
| `ui/server._run_is_live`, `discover_live_trace`, `_check_stopped` | import `is_trace_locked` from `trace_dir` (via `run_tailer`'s namespace so `monkeypatch.setattr(run_tailer, "is_trace_locked", …)` keeps working). |

Glob sites removed: `workflow_trace.py:169-172`, `resume_source.py:304,1138`, `report.py:57`,
`trace_loading.py:355`, `run_tailer.py:219-221,299-302,327`. `Path.home()/".pflow"/"debug"` appears
once, in `trace_dir.debug_dir`.

### 1.5 Retention `src/pflow/runtime/trace_retention.py` (new; policy)

> **As built — supersedes the lines below:** `SweepReport(removed: int, skipped: tuple[str] ("<path>: <cause>"),
> unreadable: tuple[Path], unchecked_workflows: tuple[str])` — no `protected`; count with `len()`; the warning
> names the first three of each with a remedy. `retention_days()`: override from the process env, else
> `settings.env`'s stored exact key; `None` + one warning for a misspelling matched by the stems
> `reten`/`retain` in unknown settings keys (any level), `settings.env` names saying `trace` or `PFLOW_`, and
> (override unset) `PFLOW_` process variables; a failed load also covers duplicate JSON keys and a bool
> `trace_retention_days` (`true` is not 1; `"0"` still coerces to 0). `settings init`/`reset` ask before replacing anything
> at the path (`path_state`); the failed-load and insecure-permissions warnings print once per file per
> process; `settings show` ends with the window in effect.

```python
@dataclass(frozen=True) class SweepReport: removed: int; protected: int; skipped: int; unreadable: int
def sweep_after_write(directory: Path) -> None     # settings + env; logs; NEVER raises (suppress + logger.warning)
def prune_traces(directory, *, keep_days: int, now: datetime | None = None) -> SweepReport  # the policy
def retention_days() -> int | None                 # the ONE reader of the setting: env override, else the file; None = cannot tell
```

Rule numbers below are the SPEC's (`task-185.md` Requirements › Retention): 1 pending pause, 2 the
Snapshot, 3 the newest run, 4 an Attempt outlives its source, 5 an open writer.

**Cost model (binding — round 1 found the sweep re-reading every protected aged trace on every run):**
a sweep reads NOTHING for an entry it can classify from its name, and reads only aged entries.
Candidates = entries older than the window (`listing.legacy` included). Legacy candidates: unlinked
on age alone, no reads. Current-grammar candidates are grouped by `workflow_hash`; a group is examined
only if it has at least one candidate. Per group:
- rule 3 (newest run): the newest entry of the hash by name — zero reads; when that entry carries
  `.from-{src8}`, its source entry is protected with it (names only, matched by id prefix across the
  WHOLE listing, not only the Attempt's hash group — the three `workflow_hashes` spellings can file an
  Attempt under another hash; a dead zero-work Attempt must not move "the newest run" off a resumable
  source);
- rule 1 (pending pause): marker-bearing candidates only (the marker is written before the trailer, so
  a durable pause always has one) — `answerable_pause` reads that trace's head+tail (P small) and the
  consumption check reads 0–2 `.from-` Attempts;
- rule 2 (the Snapshot): **walk the group's AGED candidates only**, newest-first, skipping `.only`,
  tail-reading until the first `success`/`degraded` trailer **with `nodes_executed > 0`** (a success
  trailer over zero events is what the loader skips too — `nodes_executed` counts non-restored
  top-level events, `workflow_trace.py:1094`, so this agrees with the loader's non-empty-`nodes` rule
  at zero extra reads; the "zero-event residual" is gone); then **head-read the pick** (+1 read) and
  confirm its `workflow_path` equals the group's identity — on a mismatch (a hash collision in the
  OTHER direction: the collider's success is the newest aged one) keep walking for the identity's
  path, and keep the collider's pick too; protect it. This over-protects by at most
  one file per group when a younger Snapshot exists (acceptable; stated in the ADR) and bounds reads to
  files the same sweep removes — a group of 500 young failed runs is never read. A trailer is enough (a
  trace with a `run.complete` trailer had every earlier line fully flushed — `_flush_line` disables
  streaming on the first fault — so "good trailer, corrupt body" cannot come from the writer; the loader
  also requires non-empty `nodes` and a `2.` version: a success trailer with zero events is a rare
  residual the ADR states; P3 adds an agreement test between the sweep's pick and `load_full_run_events`);
- rule 4 (Attempt outlives its source): names only;
- rule 5 (open writer): one strict lock probe per candidate actually about to be removed;
- **unknown facts keep:** a current-grammar candidate carrying a dot-tag this version does not know, or
  with a sidecar beside it other than `.paused` (any `{trace}.json.{x}` in the raw scandir), is kept —
  a later pflow's "keep this" fact (Task 121's recordings) must be honoured by every older binary
  sharing the directory, not only by binaries built after it; lookups still ignore unknown tags.
Identity grouping: the hash narrows; the file-exists qualifier and the per-path rules use the head of
**the newest entry whose strict head parses to a meta line with a `workflow_path`** — walking back
from the newest on `None` (a 0-byte or newline-less file: the disk-full run the sweep deliberately
follows leaves exactly that as the group's newest entry) or `FileNotFoundError`; if no head in the
group parses, the whole group is kept this sweep (one head read per examined group in the common case). Each candidate chosen for removal is
head-read once more (it is about to be deleted; 0.4 ms) and, if its `workflow_path` differs from the
group-newest head (a hash collision), rules 2 and 3 are re-applied for that path before it is removed
— so a colliding workflow's Snapshot or newest run is never taken. Budget on the owner's shape with the
file-exists qualifier: ~180 live groups × ~1–2 reads ≈ 0.1 s per sweep; without it ~2,500 groups ≈ 1 s.
P3 and P5 time the SECOND sweep on a fixture with 2,000 idle identities plus one identity with 1,000
young failures, not the first sweep.

**Protected traces — the five rules as ruled, with one qualifier the owner's directory forces (flag at
handback, importance 3: it amends ruled rules 1, 2 and 3):** rules 1, 2 and 3 apply only while the
Workflow's file is PRESENT (`workflow_file_state(meta.workflow_path)`: `absent` → not protected;
`unknown` (a permission fault, a TCC-sandboxed MCP server) → the whole group is kept this sweep; one
stat per group, cached per sweep; inline `ir-hash:` identities never qualify). Census of the owner's
directory (read-only, round-1 lenses): 2,267 workflow identities, **2,074 of them point at files that
no longer exist** (deleted worktrees, `/private/tmp` scratchpads, pytest paths — ~450–600 new
identities a month) and all 26 pending pauses belong to deleted files. Without the qualifier the
protected set grows by ~1k immortal files a month that no feature can read (`--only` and resume both
re-resolve the file), the sweep's cost grows with it, and the spec's "the directory is bounded" is
false. Trade-off accepted: a file that is absent only temporarily (a branch checkout) loses its
Snapshot and its pending pauses once they age past the window; an irreversible deletion, so this is
the user's call — the plan proceeds on it unless overruled.

1. **A pending Paused Run:** `e.paused` (marker) and `answerable_pause(...)` (§1.4: valid record, not
   `.only`/inline, workflow file present) and `_find_consuming_attempt(..., entries, count_live=False)
   is None` — a live Attempt that has recorded no work is a reservation, not consumption (its source
   must survive if it dies: `test_dead_zero_work_attempt_does_not_wedge_workflow_resume`'s world).
2. **The Snapshot:** the newest non-`.only` aged candidate of the group whose trailer says
   `success`/`degraded`, while the workflow file is present.
3. **The newest run of the Workflow, whatever its status** (names only; plus the source of a newest
   Attempt), while the workflow file is present.
4. **Consumption evidence outlives its source:** an Attempt (`.from-{src8}`) is removable only when
   its source is absent from disk. Removal runs in waves: wave 1 = every removable candidate that is NOT
   an Attempt, plus Attempts whose source is already absent; each later wave = Attempts whose source
   became absent in the previous wave; stop when a wave removes nothing. A source whose unlink was
   `skipped` keeps every Attempt below it (so in P ← A1 ← A2, a skipped A1 keeps A2).
5. **An open writer:** `is_trace_locked(path, strict=True) is True` (POSIX; `None` on Windows → age
   decides; a strict `Unreadable` → keep).

**Reads are three-outcome, per candidate, fail closed — built on the STRICT readers (§1.2), never on
the lenient twins (which turn every fault into `None`, and `None` here would mean "delete"):**
`FileNotFoundError` = gone (fine, not counted); `Unreadable` (any other `OSError`, `UnicodeDecodeError`,
a corrupt head or last line on a file that ends in a newline) = **keep it, count `unreadable`, and keep
its whole group this sweep when the unreadable file is newer than the group's rule-2/3 picks or carries
a marker or `.from-` tag (it could be the thing that protects others); otherwise keep only the file**
— and the warning names the first three unreadable paths, so a permanently unreadable file can be found; a head read of `None` (a readable file with no meta
line — a 0-byte file from a failed open) = removable on age alone once its lock probe is not `True`.
An `unknown` workflow-file state keeps the group. Every candidate is handled in its own `try`; one bad
file never aborts the sweep.

Removal: `path.unlink(missing_ok=True)` then `paused_marker(path).unlink(missing_ok=True)`; Windows
`PermissionError` (winerror 5/32) → one retry via the `mcp/manager.py:15-31` backoff shape, then
`skipped`. Orphan markers (`listing.orphan_markers` — a `.paused` whose trace name is absent from the RAW
scandir, whatever grammar) are unlinked only after an `os.lstat` of the exact trace path raises
`FileNotFoundError` (a readdir racing concurrent unlinks may skip a live entry; a destructive act never
rests on absence from a listing alone — the ADR states the readdir assumption rule 4 and the loader
still make).

- `retention_days()`: `os.environ.get("PFLOW_TRACE_RETENTION_DAYS")` first — an integer ≥ 0 wins; any
  other value → `logger.warning` and **`None`** (an opt-out typed as `never` or `-1` must not fall
  through to the default and delete); the env is read HERE and never applied to the settings object, so
  a one-shot `PFLOW_TRACE_RETENTION_DAYS=1 pflow settings …` can never persist `1`. Then the settings
  FILE, read ONCE through `SettingsManager().load()`: `load_error` set → `None`; else any extra key
  whose name contains `retention` in `settings.model_extra` (root — a misplaced opt-out) or
  `settings.runtime.model_extra` (case-insensitive substring, so `traceRetentionDays` counts too) →
  `None`; other unknown keys are ignored (a newer pflow's future
  `runtime.*` key must not switch an older lane's retention off and warn on every run). Both
  `PflowSettings` and `RuntimeSettings` get `model_config = ConfigDict(extra="allow")`: unknown keys never fail validation — so no whole-file fallback, no API-key drop — and they
  SURVIVE `model_dump()`, so a `pflow settings set-env …` after a typo does not silently erase the typo
  and switch deletion on; a misspelled `trace_retention_day: 0` therefore keeps retention off, with a
  warning, until the user fixes it). No second raw parse of the file. A pre-185 pflow's settings write
  (older model, `extra="ignore"`) DOES drop `trace_retention_days` — documented: the env override is
  the opt-out that survives older versions.
- `sweep_after_write(directory)`: `days = retention_days()`; `None` → `logger.warning("trace retention
  skipped: …")` and return; `0` → return; else `prune_traces`; then one `logger.warning` naming
  `skipped`/`unreadable` counts when either > 0. Whole function in `try/except Exception →
  logger.warning` (visible, not debug). Warnings reach stderr on the CLI under `-p` too — they only
  fire when something is wrong.
- Settings: `RuntimeSettings.trace_retention_days: int = Field(default=14, ge=0, description=…)` (CP-1
  Q2 — 14, not the planner's 7: deleting too early is irreversible, disk is not) + `extra="allow"`;
  **`SettingsManager.load_error: str | None`** set by `_load_from_file`'s except arm, cleared on a clean
  load, and **`save()` refuses (`raise PflowError` subclass `SettingsError`, or the nearest existing
  one) while `load_error` is set** — this closes the pre-existing wipe-on-save for ANY validation
  failure, a class this task widens by adding a validated field (`ge=0`). `settings init`/`reset` build
  a fresh manager and save without loading, so recovery is unaffected. `_apply_env_overrides` is NOT
  extended.
- `pflow settings show` (`cli/commands/settings.py:83-85`) dumps `model_dump()` masking only `env`; with
  `extra="allow"` unknown keys now reach the dump — `show` OMITS extras (a secret hand-placed at the root
  must not print in clear).
- `tests/conftest.py`: `isolate_pflow_config` sets `PFLOW_TRACE_RETENTION_DAYS=0`; so does
  `set_isolated_home` (`conftest.py:508`), because `prepared_subprocess_env` copies `os.environ` at
  module scope (`:531-553`). `tests/CLAUDE.md:48,52` says so (opt in per test).
- Timing note (accepted): the CLI sweeps inside `finalize`, i.e. before it prints the outcome
  (`run.py:404-418`); a Ctrl-C landing in the first post-upgrade sweep (~2 s of unlinks, once) exits 130
  without printing the outcome although the trace is durable. The interrupted sweep itself is safe
  (sources before Attempts, trace before marker). Moving the sweep after output would need two call
  sites (CLI `finally` + runner `finally`); one call site wins.
- Concurrency note: one listing per lookup means the loader's consumption check uses a snapshot taken
  before the source's full load — it widens #763's two-concurrent-resumes window by that load time
  (milliseconds against an existing seconds-wide window); stated, accepted.

### 1.6 What does NOT change

`engine.py`, `workflow_executor.py`, the trace format and version, `load_trace_file`, `PausedRun`,
`TraceCandidate`, `ResumeSource`, every public function signature except the keyword-only `entries=`/
`listing=` additions and `list_paused_runs`'s `PausedRunListing` return, `_apply_env_overrides`, the settings models' leniency beyond `extra="allow"` on every settings model (§1.5; widened at P3 so a misplaced retention key anywhere switches retention off), the `resume list` text/JSON layout, the `/api/runs` entry shape, the
`--only`/resume/pause semantics, the UI's two caches (they survive the deletion test — they bound the
4 Hz poll — only their listing source and sort key change), `analyze-cache`'s load-everything choice.

## 2. Phases

Agent economics: ONE Opus `task-phase-implementer` carries P1→P2 (bundled: P2 builds directly on P1's
module and the same fixtures), is resumed for P3 after the P1/P2 mid-task review, and resumed for P4
(it holds the content). Rotate to a fresh Opus implementer only on a degrading window (~400k) — the
packet is then this plan + the progress-log tail. P5 is the task orchestrator's (real-surface runs).

### P0 — Checkpoint CP-1 (handback; nothing built)

Artifact: `implementation/show-before-code.md`. **RULED 2026-10-12 (see §0 and the artifact's
"Rulings" section)** — the spec, this plan, the ADR and CONTEXT.md already carry the rulings; the task
orchestrator starts at P1. No handback is owed for CP-1.

### P1 — The trace directory module, the writer, the runtime readers

- Model: Opus, effort high (the resume/consumption seam is subtle; the fixture rewrite must keep every
  order pin discriminating). Triggers a mid-task review (below).
- Files: NEW `core/trace_dir.py`; `runtime/workflow_trace.py` (§1.3, `_iter_workflow_traces`,
  `load_full_run_events`, delete `format_trace_filename`/`_trace_recency_key`); `runtime/resume_source.py`
  (§1.4: by-id, consumption, `list_paused_runs`, imports of the moved twins, delete the local copies);
  `cli/commands/report.py`; `core/prompt_cache_analysis/trace_loading.py`; `core/CLAUDE.md` + `runtime/
  CLAUDE.md` (owner rows "the trace directory, its filename grammar, the listing → `core/trace_dir.py`");
  `tests/test_import_hygiene.py` docstring AND its `:159` failure message (both tell future agents to
  duplicate across the layer — the shared home is `core/trace_dir` now); stale prose at
  `resume_source.py:11-15`, `trace_loading.py:206-207,312-316`, `run_tailer.py:192,278`; the Task-159
  baseline fixtures `03-analyze-cache-modes/06,07,08,09/command.sh` (hand-written old-grammar names →
  composed through `trace_filename`; 06 seeds a `deadbeef` hash that never matched its workflow — rebuild
  it with the real hash and add a no-flag twin so the case proves autoload fires; 07's two traces get
  distinct ids) and `15-run-flag-interactions/03-report-with-only/command.sh`'s `sed` mask (a
  UUID-SHAPED id mask — a greedy `\.[A-Za-z0-9_-]+` would eat `.only`; its expected files are
  regenerated: the name gains `-workflow.<uuid>.only-`).
- Tests (new `tests/test_core/test_trace_dir.py` + edits):
  - Grammar round-trip: compose → parse for every field combination (`.only`, `.from-`, both, an
    unknown future tag that parses as current and is ignored; the name is always present — `workflow`
    for an empty name); a short-id source (`resumed_from="src"`) composes `.from-src` and parses back;
    the composer rejects an id with a dot; legacy names (both ts widths) parse with `execution_id=None`
    and are returned by `list_traces` ONLY with `include_legacy=True`; UNRECOGNISED names — a dotted
    name the current arm rejects (`….x.y.z-{ts}.json`), `workflow-trace-aaa-…`, a `.paused` marker,
    `foo.json` — parse to `None`, are never listed, never counted as legacy, and (P3) never deleted; a
    name whose display name contains a timestamp-like run still parses correctly (the dot anchor).
  - `list_traces`: newest-first by `started` regardless of name prefix (the `zzz`/`aaa` scenario);
    markers folded in (`paused=True`); orphan marker ignored; missing dir → empty; an unreadable dir
    (`PermissionError`) propagates. **Read-SET pins on the PUBLIC surfaces** (the spec's bound; a count
    on the lister alone is a tautology — `find_trace` is a filter): record every path opened by
    monkeypatching BOTH `builtins.open` and `io.open` (`Path.read_text` uses only the latter) on a
    directory mixing other workflows, other runs of the same workflow, other paused runs, `.only`
    traces and legacy names; assert `opened ⊆ answer` for `load_resume_source(execution_id=)` (the
    target + its `.from-` Attempts), `load_resume_source(workflow_path=)`, `list_paused_runs` (the P
    marked traces + their Attempts), `load_full_run_events` (tail reads of the workflow's traces + ONE
    full load), `pflow report` auto-select (tail + load of the newest complete only); and `os.scandir`
    called ≤ 1 per public lookup. Each pin is mutation-verified by dropping the name filter it guards.
  - Collector: a forced unsafe `execution_id` raises `ValueError`; a streamed paused run leaves
    `….json.paused` beside its trace and `trace_path` is set; a marker `OSError` (monkeypatched `open`
    for the marker path only) nulls `trace_path`, writes NO trailer — `resume <id>` on it then takes
    the incomplete arm exactly as a trailer fault does today (assert that specific outcome, never the
    gate) — (the file on disk reads
    `incomplete` — presence assertion: no `run.complete` line), and the CLI reports the pause as
    non-durable (`is_durable_pause` False — extend `test_run_outcome_cli.py::TestATrailerWriteFault
    LeavesNoIdentity`'s shape); `/api/gate` and `resume <id>` on that trace do NOT offer the gate (the
    surfaces agree); an `--only` run's name carries `.only`; an attempt's name carries `.from-{src8}`;
    a trailer fault after the marker leaves a marker beside an `incomplete` trace that `resume list`
    does not show.
  - Version-skew compatibility (the timestamp-last grammar): the PRE-185 recency key
    (`re.search(r"(\d{8}-\d{6}(?:-\d+)?)\.json$", name)`) and the pre-185 hash glob
    `workflow-trace-{hash}-*.json` both accept EVERY current-grammar name the composer can emit,
    `workflow.pflow.md` runs included (a pinned regex + `fnmatch` test — so an older checkout sharing
    `~/.pflow` still orders and finds new traces).
  - Miss messages: with 3 legacy-named files and no current trace, `pflow report`, `resume <id>` (through
    the REAL CLI — `resume_preflight.py:138-152` re-raises the by-id miss with its own message and must
    carry the clause; the three legacy files are RENAMED COPIES of a fixture shown to be found under
    its current name, so the miss is the cutover and nothing else), `resume <workflow>`, `resume list` (text; the JSON form stays a bare array and the
    clause goes to stderr), `--only` (`load_snapshot_or_raise` lists once more on its miss path — an
    error path, so the second enumeration is fine) and `analyze-cache --list-traces` (`rendering/
    traces_list.py:33-38` currently returns early without the note; its "Looked in … for
    workflow-trace-<hash>-*.json" text is stale) each name "3 traces written by an earlier pflow version
    are not searched" (and do not when the directory has none — the paired presence/absence). The
    `/api/gate` 404 body carries it; the Viewer's pinned `run-not-found` banner and `/api/run-inputs`
    404 do not (`web/` untouched — noted).
  - `list_paused_runs(debug_dir=None, *, listing=None)` — the CLI lists once and passes it, so the text
    renderer has `listing.legacy_count` and the hidden-pause count without a second enumeration.
  - Resume: `test_resume_source.py:136-140` (exact id over a newer other run) stays green; a legacy-named
    paused trace is NOT listed and `resume <its id>` says "no run with execution id" (Q4 — paired with
    the presence assertion that the same data under a current name IS found); a consumed pause (attempt with `.from-`) is not
    listed and `resume <token>` says superseded (the one-policy pin — `test_resume_list_cli.py:148-155`);
    an `.only`-tagged trace is never a resume source by id; `answerable_pause`: a paused trace whose
    workflow file was deleted is NOT listed and `resume <id>` refuses "no longer exists" (paired with
    the same trace listed once the file exists); a source that vanishes between the consumption check
    and the resume refuses `ResumeSourceMissingError` (monkeypatched `unlink` between the two); a
    consuming Attempt that vanishes mid-check counts as consumed; `test_paused_cli.py` and
    `test_resume_cli.py` batteries (real producers) green.
  - Recency (D3, the one rule): in ONE discover test and ONE report test, KEEP `os.utime` and INVERT
    it — the trace with the newer start time gets the OLDER mtime — and assert start time wins (without
    this the fixture rewrite leaves mtime and start time agreeing, and a surviving `st_mtime` sort at
    `run_tailer.py:242`/`report.py:57` passes every test); a prefix-collision pin: two pending sources
    whose ids share 8 chars (`pause-aaaa1`/`pause-aaaa2`), one consumed — the other stays listed,
    resumable and protected (drops the `resumed_from == id` confirmation → fails); by-id with ids
    `abc` / `abc-2` (newer) resolves exactly.
  - Snapshot: `test_only_snapshot.py:438` (timestamp beats name prefix) stays green through the new key;
    a current-grammar trace hand-written WITHOUT the tag but with `only_node` in its meta is still
    excluded (the meta guard is not dead).
  - Report: `test_cli.py:320` rewritten with composer-made names where the ts (not mtime) orders them —
    newest COMPLETE beats a newer incomplete; a dir of only incomplete traces → the existing message.
  - analyze-cache: `test_cache_analysis_trace_listing.py` stops hand-rolling the name (`:67-69`);
    `test_cache_analysis_analyze.py` disclosure notes still name the files.
  - Every fixture helper (`test_resume_source._write_trace`/`_write_incomplete_trace`,
    `test_only_snapshot._write_trace`/`_write_interned_trace`, `test_run_tailer._tp`,
    `test_run_node._write_trace`/`_write_io_trace`, `test_ui.py`, `test_resume_cli._write_incomplete_trace_for`,
    `test_resume_list_cli._write_paused_trace`, `test_cache_analysis_analyze._write_trace`) composes via
    `trace_filename(workflow_path, name, started, execution_id=data["execution_id"], only=…,
    resumed_from=data.get("resumed_from"))` and writes a `.paused` marker when `final_status == "paused"`
    — put ONE shared helper in `tests/shared/trace_jsonl.py` (`write_trace_file(debug_dir, data, *,
    name, started)`) that accepts the existing short `"YYYYMMDD-HHMMSS"` strings and converts them to a
    `datetime` (102 fixture sites pass the short form; a name that parses as legacy would make every
    presence test fail and every absence test pass for free), asserts the written name parses as
    CURRENT grammar, and point the per-file helpers at it. Fixtures without an `execution_id` get one
    (deterministic and DESCENDING with time — e.g. derived from `99999999999999 - int(digits)` — so a
    whole-filename sort, where the id now precedes the timestamp, orders the OPPOSITE way to start time
    and every same-name order pin fails under it; never `f"id-{started}"`). The helper is a NAME
    COMPOSER (built from the same fields as the meta, asserting name-id == meta-id) plus the existing
    content writers — `_write_incomplete_trace`/`complete=False` fixtures keep their trailer-less
    writer (`flatten_trace_to_lines` always appends `run.complete`; routing crashed-run fixtures
    through it would make them complete and the crashed-run tests vacuous). Fixtures whose
    `workflow_path` is a fake like `/work/big/wf.pflow.md`
    (`test_resume_list_cli.py:106`) create that file under the test's HOME when the test expects the
    pause to be listed or protected (`answerable_pause` requires it) — never weaken the predicate. `test_workflow_trace.py:376-379,420,500` flip to the new grammar (the id
    IS in the name now — `:500` was a Task-32-era design pin, reversed deliberately).
- Failure scenarios the tests must catch: a lookup by id that silently returns the newest trace instead
  of the exact one; a paused run whose marker write failed but whose token was still printed; a consumed
  token listed as pending (or the reverse); an `--only` trace chosen as a Snapshot/Resume source;
  a legacy-named trace surfacing in any lookup; a name-prefix sort masquerading as recency; a
  reader that opens every file (the read-count pin); the `.paused` marker matched by a `*.json` glob.
- Handoff point: `make check` + `make test` green; `uv run pytest -m trace_files` green; the progress
  log lists every fixture helper touched and the read-count pin's observed numbers. Engine untouched
  (`git diff --stat src/pflow/runtime/engine` empty).
- **Mid-task review (after P1+P2, on their diff):** `review-silent-failures` (a lookup that finds nothing
  must say so; the marker fault path), `review-feature-interactions` (`--only` × resume
  × paused marker × UI pin), `review-test-fidelity` (the fixture rewrite: every order pin
  must still fail under its mutation — `test_only_snapshot.py:438`, `test_resume_source.py:128`,
  `test_cli.py:320`, the discover tests). Run via the pflow fan-out (codex), waited in-turn.

### P2 — UI consumers (bundled with P1, same implementer)

- Model: Opus, effort medium (the plan states every change; `web/` untouched).
- Files: `ui/run_tailer.py` (§1.4), `ui/server.py` (`gate`, imports), `ui/run_node.py`
  (`_resolve_trace`), `ui/CLAUDE.md` (discovery row: the shared lister; sort by start time);
  tests `test_run_tailer.py`, `test_ui.py`, `test_ui_interaction_server.py`, `test_run_node.py`.
- Test edits that carry judgment (state them, don't let the implementer "simplify"):
  - `test_discover_prefers_live_over_finished` / `…_skips_a_crashed_unlocked_incomplete…` /
    `…_prefers_incomplete_when_lock_state_is_unknown`: ordering is now the `started` field, so give the
    FINISHED fixture the NEWER timestamp (today they do it with `os.utime`); the prefer-live rule must
    still be the only reason the live one wins. `…_falls_back_to_newest_finished…`: newer ts wins; drop
    the `os.utime`.
  - `test_scan_traces_skips_rescandir_when_dir_unchanged` monkeypatches the new seam (`run_tailer`'s
    call into `list_traces`) — the dir-mtime gate must still skip the scandir; the cached value is a
    tuple (assert `isinstance(..., tuple)` — the thread-safety guard).
  - `test_scan_traces_caches_unreadable_files` uses a composer-made name (a junk-hash name is not a
    trace any more — assert that separately: an unparseable name is never listed).
  - `/api/gate` tests: hand-written names → composer; add "gate by id over 500 traces of other
    workflows opens exactly one trace file" (read-count pin, the ~25 s symptom's guard); and "gate by
    id of a LEGACY-named paused trace is 404" beside "the same trace under a current name is 200".
  - `test_ui.py:1087-1252` and `test_ui_interaction_server.py:1217-1286` hand-written names → composer;
    the two corrupt-trailer gate tests (`:1229-1257`) add `"not paused" in error` beside the 404 (an
    unrecognised name would 404 for the wrong reason); `test_run_tailer.py:358` adds `a_path.name in
    opened` beside "B never opened".
- Failure scenarios: `/api/gate` scanning every file (read count); a pinned run id resolving to another
  workflow's run with the same id prefix; the unpinned overlay following an `--only` trace; a cache
  prune that evicts another workflow's entries (`test_scoped_scan_prunes_only_its_own_vanished_cache`).
- Real surface (P5 repeats on the owner's dir): `pflow ui` + a real paused run → the gate callout
  renders without "Loading gate…" beyond the file read; `screenshot-pflow-web-ui` for the evidence (no
  visual change expected — the screenshot documents the callout state; timing from the server log).
- Handoff: `make check` + `make test` green; vitest untouched (no `web/` change — assert `git diff
  --stat web/` empty).

### P3 — Retention and settings (resume the same implementer)

- Model: Opus, effort high (deletion policy + concurrency + the cost model). Triggers a mid-task review.
- **From this phase on, every `pflow` invocation from this worktree — tests excepted — exports
  `PFLOW_TRACE_RETENTION_DAYS=0`** (the mid-task review fan-out and the completion gate run
  `uv run pflow workflows/review/…` with the REAL `HOME`; that run finalizes and would perform the first
  real sweep before P5's backup gate). The backup gate (§P5, durable tar path) is checked at the START of P3.
- Files: NEW `runtime/trace_retention.py` (§1.5); `core/settings.py` (field; `load_error`; `save()`
  refusal); `runtime/workflow_trace.py::finalize` (the one call site); `tests/conftest.py` (env = 0 in
  both fixtures); NEW `tests/test_runtime/test_trace_retention.py`; `tests/test_core/test_settings.py`;
  `core/CLAUDE.md` settings paragraph (one line: the retention key, read by `trace_retention.
  retention_days` with the env override; `save()` refuses after a failed load).
- Tests (explicit `keep_days`/`now`, synthetic dirs through the shared fixture helper, the clock passed
  in — never `sleep`):
  - A fixture with every protected kind — stated as a PER-ITEM TABLE (workflow, file present?, newest
    of its workflow?, the ONE rule that explains its outcome), each paused fixture's workflow file
    created except the one testing the deleted-file conjunct, and the hash-colliding pair a REAL md5[:8]
    collision found at runtime under `tmp_path` (~65k candidates, sub-second) — a pending paused
    (marker, file exists, no attempt, with a NEWER unrelated non-Attempt run of the same workflow so
    rule 3 cannot explain its survival), a paused whose workflow file is gone, a consumed paused (marker + `.from-` attempt that ran a step), a paused
    source with a LIVE zero-work attempt (POSIX, `flock` held, no events; plus a newer unrelated run of
    that workflow, so only rule 1 with `count_live=False` explains the source's survival), the newest success per
    workflow, an older success, a newer success of a hash-colliding OTHER path (same `hash8`, different
    `workflow_path`) in BOTH directions (the collider's success newer, and older, than the identity's),
    a 0-byte CURRENT-GRAMMAR file as a group's NEWEST entry beside that group's aged Snapshot and newest
    real run (both survive), a failed newest run (rule 3) with an older success (rule 2), a denied, an
    incomplete, an `--only` run newer than the full success, a locked incomplete (POSIX), a 0-byte
    current-grammar file, an orphan marker, five legacy names — all older than the window: after
    `prune_traces`, exactly these remain: the answerable pending paused, the paused source of the live
    attempt, per existing workflow its newest run AND its newest usable full success (not the `.only`
    one, one per colliding path), the locked trace; gone: the deleted-file pause, the 0-byte file, the
    orphan marker, every legacy name (with zero opens — count them), the rest. `--only`, `resume
    <token>`, `resume list` still work against the pruned dir; `report` does not crash.
  - Consumption evidence outlives its source: P + denied attempt A, both aged, `unlink` monkeypatched to
    raise `PermissionError` for P only → A survives, `resume list` does NOT list P, `resume P` refuses
    as superseded; without the fault both go. P ← A1 ← A2 with the fault on A1 → A2 survives; without
    the fault the chain is removed in one sweep.
  - Fail-closed reads — the fault is injected at `builtins.open`/`io.open` / `os.stat` for ONE path
    (raise `OSError(errno.EMFILE, …)`), never at the helper (a helper mock would pass against a sweep
    that fails open), and EVERY such test has a control: an unrelated aged unprotected trace in the same
    directory IS removed by the same sweep (so "kept" is not "the sweep aborted"): the aged pending pause's trailer read fails → the pause is kept, `unreadable == 1`,
    one warning; the group's newest success fails → nothing in that group is removed; the lock probe's
    open fails on POSIX → kept; `workflow_file_state` → `unknown` (monkeypatched `os.stat` raising
    `PermissionError`) → the group is kept; a `FileNotFoundError` mid-sweep removes nothing else and is
    not counted; an unrecognised dotted name in the dir survives every sweep.
  - Unknown facts keep: an aged trace with an unknown tag (`.recording`) and one with an unknown
    sidecar (`….json.claim`) survive the sweep; the same traces are still found by id and listed.
  - Agreement: on a mixed fixture (young + aged successes, `.only`, failed, degraded, empty-`nodes`
    success — which rule 2 now skips via `nodes_executed`), `load_full_run_events(...)` returns the
    SAME trace before and after `prune_traces` (the oracle); an older extra survivor is allowed only
    when the loader's pick is younger than the window.
  - Cost: a fixture with 2,000 idle identities (each: one aged success, workflow file present) + 50
    aged removable traces + ONE identity with 1,000 YOUNG failed runs and an aged success → record the
    opened PATH SET of the second sweep (fresh process state — clear any module-level cache between
    sweeps, or run the second sweep in a subprocess): `opened ∩ {the 1,000 young paths} == ∅`; per
    examined group at most the identity head, the rule-2 pick's tail+head, and per removal candidate
    ONE open (strict head + flock probe on the same handle — derive the bound from that, reusing the
    group head when it is the candidate); the first sweep is bounded the same way; wall time is
    recorded, not asserted (or asserted with a 10× margin).
  - `keep_days=0` removes nothing; a file younger than the window is never a candidate; no
    over-protection outside the window.
  - `finalize` hook: a real paused run (`trace_files`) in a dir holding an aged unprotected trace with
    `PFLOW_TRACE_RETENTION_DAYS=1` → the old trace is gone after the run, the run's own trace and marker
    exist, the token resumes; a stream-faulted run still sweeps; a disk-full-shaped fault (the meta
    write fails, a 0-byte file stays) sweeps without touching that workflow's protected traces. A
    read-only command (`pflow report`, `resume list`, `pflow ui` startup, `--dry-run`) with
    `PFLOW_TRACE_RETENTION_DAYS=1` set never removes anything (presence assertion — under the conftest
    default of 0 the test would be vacuous).
  - Fault isolation: `prune_traces` raising never changes the run outcome or `trace_path`; a Windows-
    style `PermissionError` on one file retries once then skips it and continues; the warning names the
    count.
  - Lifecycle faults, deterministic: (a) a live attempt that exits without consuming (start → sweep →
    exit) leaves its source resumable; (b) two sweeps interleaved at a monkeypatched barrier (X lists,
    Y removes P and A, X resumes) leave exactly the protected set — never a timing race.
  - Settings: default 14, `ge=0`; `retention_days()` honours the env first (an invalid env value →
    warning and `None`, nothing pruned); a file with `trace_retention_days: 0` AND an unrelated invalid
    key → `load_error` set, `None`, nothing pruned, one warning, the aged trace still present; a
    misspelled `runtime.trace_retention_day: 0` with an otherwise valid file → `None`, nothing pruned;
    a ROOT-level `trace_retention_days: 0` → `None`, nothing pruned; an unrelated unknown `runtime.foo`
    → 14 and prunes; `pflow settings show` omits the unknown key;
    the user's `env` keys still load (presence) AND after a `set_env` the typo key is still in the file
    and `retention_days()` is still `None`; no env + no file → 14 and an aged trace IS pruned (the
    default path most users hit); `save()` after a failed load raises and the file is byte-identical;
    the env override never reaches `settings.json` after a `set_env`.
- Failure scenarios: a pending paused run deleted; the Snapshot of an idle workflow deleted; the last
  run of a workflow deleted (rule 3); the sweep on a read-only command; a sweep exception failing a run;
  a legacy name protected, read, or surfaced; an `.only` run protected as the Snapshot; a live writer's
  file removed on POSIX; an answered token resurrected because its Attempt went while it stayed; a
  source removed while a zero-work attempt held its lock; a hash-colliding workflow's Snapshot
  displaced; an unreadable file deleted or aborting the sweep; retention enabled by a settings typo or
  disabled silently; a settings write after a failed load wiping the file; the per-sweep cost growing
  with history.
- Handoff: `make check` + `make test` + `uv run pytest -m trace_files` green; the progress log records
  the second-sweep open count and wall time on the 2,000-identity fixture.
- **Mid-task review (on P3's diff):** `review-concurrency-safety` (concurrent sweeps/readers/writers;
  TOCTOU between listing and unlink; Windows handles) and `review-silent-failures` (a protected trace
  silently deleted; a sweep that silently does nothing; a lenient reader reaching the sweep).

### P4 — Docs, help, guide, instruction files (same implementer)

- Model: Opus, effort medium.
- Files and the one line each needs:
  - `cli/commands/run.py:1033-1037` `--no-trace` help: "…(`--report`/`--report-dir` re-enable it)";
    `resume.py:277` unchanged. `report.py:44` example → a real new-grammar name.
  - `core/exceptions.py::OnlySnapshotMissingError` docstring + `_DEFAULT_SUGGESTION`: add "or its trace
    aged out of `runtime.trace_retention_days`".
  - `docs/guides/debugging.mdx:100-102` (pattern), `:107` (precedence sentence stays), `:144-151` ("Disk
    cleanup" → "Retention": the window (14 days), the key, the five protected rules, what deleting by hand
    breaks — no `rm` recipe; plus the cutover sentence: traces written by earlier pflow versions are not
    listed by `resume list`, `report` or the Viewer, stay readable by path, and age out), `:159` summary
    row ("pflow (retention; `trace_retention_days`)"), `:73` example name.
  - `mcp_server/tools/execution_tools.py:52-54` (the `workflow_execute` docstring: "usable for … within
    the retention window").
  - `docs/reference/configuration.mdx:29-31,48` (the field), `:127` (env row), `:130-140` (the stale
    `PFLOW_TRACE_*` section — none of those variables exist in `src/`; replace it with the real trace
    configuration: the retention key + env), `:224` (debug row: "Yes, but deleting a trace breaks `--only`,
    `resume`, pending pauses and `report` for that run — pflow prunes it on `trace_retention_days`").
  - `docs/reference/cli/index.mdx:511-513,528` (pattern/example), `:132` (add `--report`/`--report-dir`
    rows beside `--no-trace` and the precedence), `:537` keep.
  - `docs/reference/cli/analyze-cache.mdx:39` example name.
  - `docs/how-it-works/approval-gates.mdx:53-57`: "a pending pause is kept until answered, whatever the
    retention window, as long as its workflow file exists". `docs/guides/debugging.mdx:66` ("the trace
    files are the durable history … any previous run") → "within the retention window".
  - Guide: `features/resume.md` (near `:34-40`: one sentence — a pending pause is kept while its
    workflow file exists; failed runs can be resumed within the retention window), `features/approval.md:111`
    same wording (never "never pruned"), `features/ui.md:135`
    (name shape; "older runs within the retention window"), `features/prompt-caching.md:45` (pattern),
    `entry.md`/`core.md` `--only` lines unchanged (the Snapshot is protected).
  - MCP: `mcp-agent-instructions.md:853` (pattern + the retention sentence), `:2099` (`jq` recipe keeps
    working — `*.json` never matches a marker; say nothing).
  - Stale "MCP writes no trace" claims: `workflow_trace.py:553-555,983-984` (P1 already), ADR-0010
    `:149-150` → "`--no-trace` runs write no trace and are therefore unresumable; MCP runs stream traces
    like the CLI" (write discipline: the rule, not the incident). ADR-0007 `:18,:23` ("delete freely"):
    one amendment line pointing at ADR-0018 (a trace is deleted by Retention, never freely). ADR-0002
    `:93-94` ("the timestamp format is free to change"): one amendment line — the format is part of the
    filename grammar since ADR-0018.
  - Cutover sentence everywhere a lookup is described (debugging.mdx, `cli/index.mdx`, guide `resume.md`
    / `approval.md` / `ui.md`, MCP instructions `:853`): "traces written by an earlier pflow version are
    not searched; pflow tells you how many; read one with `pflow report <path>`; do not run pre- and
    post-upgrade pflow versions against one `~/.pflow` — the older one will not see the newer one's
    pauses" — CORRECTED to the real hazard: "an older pflow can answer a newer pflow's pause and the
    newer one will not see that answer; answer each pause with the version that issued it; an older
    version's settings write drops `trace_retention_days` — `PFLOW_TRACE_RETENTION_DAYS=0` is the
    opt-out that survives it, but it is per-process (an MCP server launched by a desktop client does not
    inherit a shell export) — the settings key is the opt-out for every pflow process; set both when
    mixing versions; and a newer pflow ages out an OLDER lane's traces, pending pauses included, after
    the window" — and the `--only` note: the first `--only` after upgrading needs one
    full run first (there is no old-grammar Snapshot it can read). Guide AND PR body: "answer pending
    pauses before upgrading".
  - `docs/reference/cli/index.mdx:256,288` example `trace_path` values → the new grammar.
  - `.claude/skills/deep-review/SKILL.md:44` sensitive paths: add `core/trace_dir.py` and
    `runtime/trace_retention.py` (the latter deletes user data); `review-architecture-fit.md:39`: name
    the filename grammar and the `.paused` sidecar as a durable contract. Then `make sync-claude-assets`.
  - `architecture/reference/template-variables.md:1749` (the `--trace` flag does not exist; the old
    pattern) — fix the two lines.
  - `.claude/agents/pflow-codebase-searcher.md`: add `core/trace_dir.py` / `runtime/trace_retention.py` to
    the runtime map and the "trace lookup / retention" search locations; then `make sync-claude-assets`.
  - `runtime/CLAUDE.md` (P1 row + a "Traces, snapshots, and resume" sentence: the directory listing is
    the index; `.paused` sidecar; retention at `finalize`), `ui/CLAUDE.md` (P2), `cli/commands/CLAUDE.md`
    report row (newest complete by start time), `core/CLAUDE.md` (P3).
  - CHANGELOG: none (generated at release; the PR body carries the text).
- ADR + CONTEXT.md: already written by the planner on this branch
  (`context/adr/0018-185-trace-directory-is-the-index.md`; `context/CONTEXT.md` nouns **Retention** and
  **Protected trace**). The implementer reconciles them only if a phase deviates from what they state.
  The Task-159 case `12-real-world-lyrics-generator/04-guide-auto-detect/expected-stdout.txt` embeds the
  guide's `prompt-caching.md:45` pattern — regenerate that case (`regenerate.sh`) after the guide edit.
- Failure scenarios: `tests/test_docs/test_agent_references.py` (every path/symbol in `.claude/agents/*.md`
  must resolve — the searcher file edit), `test_mdx_fences.py`, `make check`'s asset-sync gate.
- Handoff: `make check` green; `uv run pflow guide resume` / `guide approval` render the new sentences.

### P5 — Real-surface verification and the outer nets (task orchestrator, with the implementer)

- Model: Opus (the orchestrator drives; the implementer executes).
- Fixture benchmark: a script under `implementation/bench/` (not a test) builds a 30k-file synthetic
  dir in an isolated HOME (2,500 workflow hashes, one pending paused, one `--only`, half the files under
  legacy names, one identity with 1,000 young failures) and times, with `/usr/bin/time`: `pflow resume list`, `pflow resume <id>` (`--dry-run`),
  `pflow report`, `pflow <wf> --only <step> --dry-run`, `curl /api/gate?run=` against a `pflow ui` on a
  free port; and the first sweep via one real run with an aged fixture. Record the numbers in the
  progress log; the spec's bound is "< 1 s wall on a 30k dir" for each lookup.
- **Owner's directory — GATE (CP-1 Q6, consent granted behind it; checked at the START of P3 and again
  here):** before the FIRST write against the real `~/.pflow/debug` without `PFLOW_TRACE_RETENTION_DAYS=0`
  (any `uv run pflow <workflow>` that finalizes a trace sweeps):
  ```
  tar -tf /Users/andfal/projects/pflow/scratchpads/session-16/backup/pflow-debug-backup-2026-10-12.tar | wc -l   # must be ≥ 29000
  ```
  The file must exist and the count must be ≥ 29,000, else **HOLD** (hand back; do not run). Record the
  count in the progress log. Then: one real run (the first sweep, timed — it unlinks every legacy file
  older than 14 days on names alone), followed by `resume list`, `resume <id> --dry-run`, `report`,
  `<wf> --only <step> --dry-run`, each under `/usr/bin/time`. Expected on the owner's machine: `resume
  list` → "No paused runs." (pre-upgrade pauses are invisible by ruling), `report` → the run just made.
  Before/after timings go in the progress log and the PR body against the spec's Problem table.
- `uv run pytest -m trace_files`, `make test-all-local`, the Task-159 baseline
  `.taskmaster/tasks/task_159/baseline/verify.sh` (expected drift ONLY in printed trace filenames inside
  analyze-cache disclosure notes — `normalize.py:73` masks `workflow-trace-<hash>-`; extend the mask to
  the `.{id}` field if a case prints it; any other drift is a regression), `tests-windows` on the PR
  (the lock tests stay `_unix_only`; the sweep's `PermissionError` arms run on both).
- Kill the worktree's `pflow ui` before handback; declare `dev servers: none`.

## 3. Completion gate (code mode, the task orchestrator commissions)

Lenses: `review-plan`'s successors are the completion set — `review-silent-failures`,
`review-impact-completeness` (the 8 spellings and every glob site switched; every fixture helper;
every doc pattern), `review-concurrency-safety`, `review-feature-interactions`, `review-test-fidelity`,
`review-agent-ux` (the retention sentences, the cutover sentence, `--help`), `review-simplicity`
(emergent duplication between `trace_dir` and the readers; dead `scan_traces` paths),
`review-spec-conformance` (every requirement line incl. the read-count pins, the Task-159 run, the
Windows gate), then `review-falsifier` last (direct launch, with `PFLOW_TRACE_RETENTION_DAYS=0`
exported for every run that is not its own retention probe: it executes the lookups on a 30k synthetic
dir mixing current and legacy names, the second-sweep cost on an idle-identity fixture, and the
protected set).

## 4. Risks and how the plan bounds them

- The cutover (Q4): every trace written before this version is invisible to `resume`, `resume list`,
  `report` auto-select, `--only` and the Viewer's history, and ages out under retention. The docs say so
  (P4). A path printed before the upgrade still works with `pflow report <path>`. The first sweep on the
  owner's directory removes every legacy file older than 14 days with no reads (~2 s of unlinks for
  ~20k files, measured 75 µs/unlink).
- Windows: no lock → age decides; a reader holding a file makes one unlink skip (retried next sweep,
  counted and warned). No `fcntl` import outside `trace_dir.is_trace_locked`.
- `--only` iteration loops: the `.only` tag keeps Snapshot selection at one load.
- The user's many concurrent agents: sweeps are idempotent and `missing_ok`; readers skip `OSError`
  at discovery (`_iter_workflow_traces`, `find_trace`, `scan_traces`); a consumed pause deleted
  mid-resume refuses as superseded or missing (sources are removed before their attempts; the loader
  re-checks the source exists after the consumption check; a vanished Attempt counts as consumed).
- Version skew on one `~/.pflow`: the timestamp-last grammar keeps every pre-185 reader correct on
  post-185 traces; a pre-185 WRITER's traces are legacy to post-185 readers (the ruled cutover), so an
  older pflow's answer to a newer pause is invisible to the newer one (a second answer is possible) and
  an older pflow's settings write drops the retention key — both documented; the consumption-arm fix is
  the user's call (handback).
- The per-sweep cost is bounded by the number of live workflow identities with aged traces (~1 read
  each), not by history — the file-exists qualifier is what keeps that set from growing without end.
- A name the parser rejects is invisible — by design; the composer is the only producer and every
  fixture goes through it.
