# Task 173 — D6 plan: run-navigation (`/api/runs` → replay → surfaces) + overlay polish

> **REVISED 2026-06-24 after a 5-agent `/deep-review` (plan mode).** No Critical foundation error — the
> architecture is verified sound. The review's seven convergent findings are now resolved as DECISIONS
> below (each tagged `[DR-n]`), not left as "risks to verify." Builds on the shipped overlay core (P1 join
> + P2 host-lighting, commits `1fa6d7a6` + `bbc1dd91`): the live tailer, SSE bus, NodeId join, and
> `discover_live_trace` (already excludes `--only`) are in `src/pflow/ui/run_tailer.py` + `server.py`.

## The one insight that makes this cheap

**Live and historical are the SAME render path** — a finished trace is a live run that ended; the tailer
already replays a finished trace (snapshot). So `/api/runs`, history, and the dashboard are *views over one
data layer*; replay = the tailer with auto-discovery disabled. (Verified by the review.)

## Deep-review decisions (apply throughout)

- **[DR-1] The pinned tailer is keyed on `(workflow_key, run_id | None)`, not `workflow_key` alone.** A
  pinned replay and an unpinned live overlay of one workflow must NOT share a tailer. `ensure_tailer`/
  `release_tailer` key + ref-count on `(workflow_key, run_id)`; the unpinned overlay is the `run_id=None`
  tailer (follow-newest, `--only` excluded). The pinned tailer resolves `run_id → Path` ONCE on attach
  (via the shared cheap scanner, inside `asyncio.to_thread`), then tails that fixed file — never calls
  `discover_live_trace`. A missing/stale `run_id` → broadcast an explicit `{"type":"run-not-found"}`
  (NOT a silent all-`pending` canvas). The pinned-**LIVE** path is first-class — it's the ONLY way to
  watch one of N concurrent runs. NOTE: the poll body is inline in `RunTailer.run()` (there is no
  `_poll_once`); branch ONCE on `self._run_id` — pinned skips discovery entirely.
- **[DR-2] Liveness/status comes from RAW FACTS, not a synthesized enum.** `/api/runs` exposes the
  orthogonal facts and lets the UI compose the badge: `complete: bool` (has a `run.complete` trailer),
  `final_status: str|None` (PARSED from the `run.complete` line — `success`/`degraded`/`failed`, the
  producer's vocabulary; `null` when not complete), `live: bool` (not complete AND mtime within
  `STALE_RUN_S`), `only_node: str|None`. A crashed run = `complete:false, live:false` (no NEW
  `interrupted` word on the wire — the UI may DISPLAY "interrupted", but the field stays the producer's).
  `STALE_RUN_S` = a documented constant (default 60s) — a HEURISTIC: a single node running >`STALE_RUN_S`
  (a slow LLM call) false-reads as not-live; a run crashed <`STALE_RUN_S` ago still reads live. This is a
  display hint, never authoritative (observe-don't-host forbids process tracking).
- **[DR-3] The shared scanner is MECHANISM ONLY.** Factor the per-file probes (`_read_meta` head-read,
  a `read_run_status(path) -> (complete: bool, final_status: str|None)` cheap-tail helper extending
  `_has_run_complete`, and the hash-glob) into ONE scanner that yields RAW candidates
  `(path, meta, complete, final_status)` with **NO `--only`, NO `final_status`, NO sort-key policy** baked
  in — each caller applies its own (the documented `_iter_workflow_traces` "policy in callers" invariant).
  `discover_live_trace` excludes `--only` + sorts by mtime + prefers-live; `/api/runs` labels `--only` +
  its own ordering. **`/api/runs` does NOT route through `_iter_workflow_traces`** (its per-candidate
  full `load_trace_file` parse defeats the cheap-read goal — copy its *pattern*, not its code). The
  `run_id→Path` pin lookup (DR-1) reuses this same cheap scanner. Keep `report.py` +
  `trace_loading.py` OUT (different selection semantics — verified).
- **[DR-4] `/api/run-node` returns an explicit ALLOWLIST projection, never "the full event."** Mirror
  `run_tailer._run_event`: project a named field set, DROP raw `node_type` (the Python class name), and
  where the kind is needed map it through `node_type_tag()` (`core/node_type_display.py`) → `llm`/`shell`/
  `workflow`/…. Encode the `ref=` query param as the frontend's existing `refKey` string
  (`node_id|port|node:idx>…`) so server + client can't drift. (Phase 5 — pinned spec, built later.)
- **[DR-5] Inline / MCP / stdin runs are INCLUDED, not dropped.** Their `meta.workflow_path` is
  `ir-hash:<md5>` / the empty-path hash, not a file path. `/api/runs` carries the path verbatim and they
  surface in the all-runs dashboard by `workflow_name`. `?workflow=X` filtered by a real FILE PATH won't
  match them (documented — they have no file path). `workflow_path` is the JOIN key; `workflow_name` is
  display-only.
- **[DR-6] Each new fetch owns its failure; empty ≠ error.** The "errors never blank the canvas"
  invariant lives only in `useWorkflowGraph` — it does NOT auto-extend. Every new `/api/runs` consumer
  (catalog badge, dashboard, history dropdown) wraps its fetch in its own catch → a degraded render (no
  badge / "couldn't list runs" / last-good dropdown), never an unhandled throw. Server side: `/api/runs`
  returns **non-200 on a real scan error**, `200 + []` ONLY for genuinely zero runs; a single unreadable
  trace is SKIPPED (array still 200), never fatal — so a short list never means "scan failed."
- **[DR-7] `App.tsx` routing: `?view=runs` wins over `?workflow=`.** Stay PARAM-based (the SPA has no
  server catch-all — a client route like `/runs` 404s; `App.tsx` already documents this). `?view=runs`
  shows the dashboard even when `?workflow=` is also present (so back-from-a-run lands on the dashboard).

## Phase 1 — `/api/runs` data layer + the shared scanner (server, `src/pflow/ui/`)

- **Shared cheap scanner [DR-3]:** factor `_read_meta` + `read_run_status` (new, extends
  `_has_run_complete` to also return `final_status` from the trailer) + hash-glob into a mechanism-only
  scanner yielding `(path, meta, complete, final_status)`. Re-point `discover_live_trace` at it (applying
  its `--only`-exclude + mtime-sort + prefer-live as CALLER policy — unchanged behaviour, re-verify the
  shipped tailer tests). Add a symmetric `--only` meta-test: a `--only` trace is ABSENT from
  `discover_live_trace` AND PRESENT in `/api/runs` — so a future refactor collapsing the policy fails
  loudly.
- **`GET /api/runs`** → `[{run_id, workflow_name, workflow_path, start_time, complete, final_status, live,
  only_node, trace_file}]` [DR-2, DR-5]. `run_id = meta.execution_id` (uuid4, unique — verified).
  Non-200 on scan error; skip unreadable traces [DR-6].
- **`GET /api/runs?workflow=X`** → hash-glob by `md5(path)[:8]` → O(this workflow's runs); file-path
  filter (inline runs documented-excluded, DR-5). Bare `GET /api/runs` scans the dir (cheap head + the
  tail-seek `read_run_status` per file — N tail-seeks/poll; cache `(path, mtime)` → result if it bites,
  finished traces' heads+trailers are immutable).

## Phase 2 — replay + run-selection (server + tailer) [DR-1]

- **`GET /api/events?workflow=X&run=<run_id>`** pins a run. `ensure_tailer` keys on `(workflow_key,
  run_id)`; the pinned tailer resolves `run_id→Path` once (shared scanner, `to_thread`), tails that file,
  never re-discovers. Unpinned (`run` absent) = today's `(workflow_key, None)` tailer.
- `run-not-found` SSE message when `run_id` matches no trace (stale bookmark / rotated file).
- Replay is free: the tailer already snapshots + tails a finished file; the pin just disables
  re-discovery. A pinned LIVE run tails identically (offset + byte-buffer) — first-class, gets its own
  test (a long-running workflow, pinned mid-stream).
- Unpinned default = "newest live, MAY switch among concurrent runs" (documented limit); pinning is the
  escape hatch to watch a specific one of N concurrent runs.

## Phase 3 — the three frontend surfaces (`web/`, each its own browser-verify + own catch [DR-6])

- **Catalog running-badge** (`CatalogView`): `/api/runs` filtered `live` → a `●` per workflow. Own catch →
  no badge on failure.
- **Per-workflow history** (`GraphView`): a dropdown from `/api/runs?workflow=X`; select a `run_id` →
  re-subscribe `/api/events?workflow=X&run=<id>` → replay. Default = newest live. `--only` runs LABELLED
  (e.g. "only: step-b"). The agent-facing re-open primitive is `run_id` → `/api/events?...&run=<run_id>`
  (document it as the contract, not just a human click).
- **Global dashboard** (new third screen): `App.tsx` `?view=runs` [DR-7]; lists all runs (compose the
  badge from `complete`/`final_status`/`live`/`only_node` [DR-2]); click-to-open → GraphView with
  `workflow`+`run`. Live updates: poll `/api/runs` on an interval (v1). **Dashboard `live` (poll) and the
  canvas overlay (SSE) can briefly disagree** when a run finishes (SSE instant, badge lags ≤1 interval) —
  ACCEPTED, documented behaviour, not a bug.

## Phase 4 — overlay polish: ChipRail status chip (#3) [verified clean]

- Add a status CHIP in the ChipRail's reserved leftmost slot (`ChipRail.tsx:10-12`) so a host's run-state
  reads clearly on a large EXPANDED region (the outline ring is subtle there; prominent on a collapsed
  card). Complements (doesn't replace) the ring; pending = no chip. Touches `ChipRail.tsx` + `GroupNode.tsx`
  (pass `status` to the rail) — same area as the Phase-3 group work.

## Phase 5 — detail panel (data-source DECIDED: fetch-on-click) [DR-4]

- **`GET /api/run-node?workflow=X&run=<id>&ref=<refKey-string>`** → an explicit ALLOWLIST projection of one
  node's event (resolved blobs), NO raw `node_type` (use `node_type_tag()`), `ref` encoded as the
  frontend's `refKey`. Keeps the live SSE wire thin. May be a phase after navigation lands.

## Decisions carried (do NOT re-litigate)

- **Launch POST (`POST /api/run`, D4): DEFERRED** — the only mutating endpoint → the CORS tripwire trigger.
  All D6 surfaces are read-only GETs → inherit the safe posture (verified: `server.py:642-653`). NO new
  mutating endpoint.
- **`--only`:** EXCLUDE from the live overlay (shipped); LABEL in `/api/runs` history [DR-3].
- **MCP runs don't stream** (`trace_enabled=False`) → not watchable; appear in history only if a trace
  exists.

## Manual test scenarios (named — interaction-only bugs hide here)

1. A long-running workflow, pinned mid-stream via `&run=` → the pinned-LIVE tail lights live (DR-1).
2. TWO concurrent runs of one workflow → dashboard lists both (distinct `run_id`); unpinned overlay
   follows one (may switch); pinning each shows the right one (DR-1, DR-2).
3. Replay a Ctrl-C / crashed trace from history → dangling `running` nodes + no banner, not blank
   (`final_status=incomplete` on full read; the dev join-miss detector `GraphView.tsx:610` is the
   sub-workflow/batch verification hook).
4. An inline run (`pflow run <<<...`) → appears in the all-runs dashboard, NOT in `?workflow=<file>` history
   (DR-5).
5. `--only` iteration → labelled in history, ABSENT from the live overlay (DR-3 meta-test + browser).
6. `/api/runs` over an empty dir vs an unreadable trace vs a scan error → `[]` / skip+200 / non-200 (DR-6).
