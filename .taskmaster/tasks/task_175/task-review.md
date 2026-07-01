# Task 175 Review: Run Workflows from the Web UI

## Metadata
- **Implemented:** 2026-06-30 → 2026-07-01, across phases 1–6 (+ a collaborative 3/3.5/4.5 with a second agent doing the run-flow/overlay-refinement frontend).
- **Status:** implemented + deep-reviewed (7-agent battery, all confirmed fixes applied) + hardened. **STAGED, not yet committed** — the branch `feat/web-ui-workflows` HEAD is still `36587a26 "phase 3 completed"`; phases 4/4.5/5/6 + review fixes sit in the working tree. No external users (per root CLAUDE.md), but **the trace format + the test suite ARE the contract** — treat regressions there as breaking.
- **Gates at close:** `make test` 8273 · `make check` clean · `tsc` 0 · `vitest` 676.
- **The journey** (dead-ends, round-by-round UX iteration, the deep-review findings) lives in `implementation/progress-log.md`. This review is the distilled forward-reference.

## Read First — the load-bearing block

**What exists now:** click ▶ on the `pflow ui` canvas → an auto-generated inputs form → a detached `pflow run` spawns → the live overlay lights it up → click ANY node (IO nodes included) to see its this-run value → re-run from a past run's inputs via a picker. Plus `pflow ui <wf> --run <id>` for an agent to open/switch a Viewer to a specific run.

**Read these first (path · symbol):**
- `runtime/workflow_trace.py` · `WorkflowTraceCollector.inputs` + `_meta_fields()` — the **keystone**: `meta.inputs` on the eager trace line.
- `execution/runner.py` · `_compile_and_execute` — the `meta.inputs` stamp (ordering-critical) + `RunnerConfig.execution_id` threading.
- `ui/server.py` · `run()` (detached spawn), `_require_local_origin`+`_json_body` (Host guard), `command()` (the `select-run` verb), `run_inputs()`.
- `ui/run_node.py` · `run_node_detail`/`_io_detail`/`read_run_inputs` + the shared raw-read helpers `_read_trace_lines`/`_blob_map`/`_line_of_kind`.
- `ui/run_tailer.py` · `_start_pinned`/`_PINNED_RESOLVE_ATTEMPTS`/`_read_meta`.
- Frontend: `web/src/components/IoPanel.tsx` (`PortRunValue`), `RunPanel.tsx` (picker + smart `onLaunched`), `api/events.ts` (`select-run` arm), `views/GraphView.tsx` (`selectRun`, `pointHandlers.current`, `hasRunContext`, `onRunLaunched`).

**Invariants that must NOT break (rule → consequence):**
1. **Server observes, never hosts.** The only mutation is the detached `subprocess.Popen(..., start_new_session=True)` in `server.run()`. Use `Popen`, **never `asyncio.create_subprocess_exec`** — asyncio's transport finalizer calls `_proc.kill()` on a live child, so closing `pflow ui` SIGKILLs in-flight runs (ADR-0008 violation, intermittent).
2. **The `meta.inputs` stamp MUST run before `engine.run()`** (which calls `start_streaming()` → flushes the eager meta line at t=0). Move it later → the meta line ships `inputs:null` → Phase 4 input-inspect + Phase 5 re-run silently break. (Pinned by `test_meta_inputs.py::…on_eager_meta_line_before_node_events`.)
3. **Read traces as RAW JSONL lines** (`run_node._read_trace_lines`), NEVER `load_trace_file` — it strips `ancestor_path`/`port`, the exact keys the overlay/panel join on → blank panels, no error.
4. **IO redaction matches by PORT NAME:** `_redact({name: value})`, not `_redact(value)`. `_redact` matches dict KEYS; a bare scalar has no key → a sensitive-named input's value leaks to the browser.
5. **Every mutating POST flows through `_json_body`** (which calls `_require_local_origin` FIRST). A new POST that bypasses it skips the DNS-rebinding Host guard.
6. **`run.complete.json_output["result"]` requires the CLI's `set_json_output` to run BEFORE `finalize()`.** Reorder → output-node "This run" panels return null ("no recorded output") while every fixture test stays green. (Pinned by `test_run_node.py::test_cli_json_run_records_json_output_result_on_run_complete`.)
7. **Secrets: RAW on disk, redacted on READ / omitted on PREFILL.** No write-time masking — re-run needs faithful values. `_io_detail` redacts (display shows the key exists); `read_run_inputs` omits (a secret never reaches the browser).
8. **Never add `sensitive` to the Python `IOPort` dataclass** — the wire ships `asdict(node.io)`, so it would leak onto OUTPUT nodes. It's a renderer-injected flag (`react_flow.py`), input-nodes-only; mirror it in the TS `IOPort` only.

## What Was Built (actual vs. planned) — the deviations

The plan was solid but its **line numbers are ALL stale** (phases 3/4/4.5 drift) — navigate by symbol. Five real divergences:

1. **Phase 4 (biggest): IO inspection lives in `IoPanel`, NOT `ReadPanel`.** The plan gated `ReadPanel.showRunDetail` on "the selected node is an IO node." Verified false: clicking a root IO row → `selectPort` → `setSelectedId(<wrapper group id>)` → `selectedNode` is `null` (root wrappers have no host) → **`IoPanel` opens, never `ReadPanel`**. So the run-value display went into `IoPanel` (per-port `PortRunValue`, a CodeBlock block). The server-side IO projection (`run_node._io_detail`) is panel-agnostic and unchanged from plan intent. Also corrected the plan's literal `_redact(meta.inputs[name])` → `_redact({name: value})` (invariant #4).
2. **Phase 2: spawn argv is `-m pflow.cli`, NOT `-m pflow`.** `pflow` has no `src/pflow/__main__.py`, so `python -m pflow` errors; the child would die instantly with stderr DEVNULL'd (a silent dead run). `pflow.cli` is the documented module entry.
3. **Phase 6: ONE smart `--run`, not two commands.** Plan had `--run` (open) + a `select-run` CLI subcommand (switch). User chose a single `pflow ui <wf> --run <id>` that switches an already-open Viewer (via a `select-run` broadcast) or opens a fresh pinned tab. **There is NO `pflow ui select-run` subcommand** — the `select-run` verb exists only at the server (`command()`) + frontend (`events.ts`) layer as the switch mechanism.
4. **Phase 5: the "load inputs from" picker lives in `RunPanel`, not `RunForm`.** `RunForm` stayed a pure controlled field renderer; value-provenance (the run list + prefill) belongs with `RunPanel`'s state. The optional clock/RunSelector per-row ↻ sugar was skipped (explicitly optional).
5. **Phase 4.5 (collaborative): the server mints + FORCES the run's `execution_id`.** Concurrent launches exposed that the unpinned "follow-newest" overlay reverts to an older still-live run when a shorter new run finishes. Fix: `server.run()` mints a uuid, passes it via `env["PFLOW_EXECUTION_ID"]` → `run.py` pops it → `RunnerConfig.execution_id` → the collector; the browser PINS that id. This is why `run_tailer` grew the pinned-resolve grace window.

## Patterns & Anti-Patterns

**Propagate:**
- **Point-channel verb = 3 lockstep sites, no shared enum:** server `command()` whitelist + `events.ts` dispatch arm + `GraphView.pointHandlers.current` ref. A new verb routes through the ref (its identity tracks the deps), NEVER through the subscribe-effect dep array (churn). `clear`/`select-run` are pass-through (no `resolve_target`); `focus`/`frame` resolve a graph target.
- **Shared raw trace-read helpers** (`_read_trace_lines`/`_blob_map`/`_line_of_kind`) — three readers (`run_node_detail`, `_io_detail`, `read_run_inputs`) reuse them; don't reimplement a trace read.
- **Pre-flight the full compile off-loop** (`asyncio.to_thread` → `_preflight` = resolve+parse+`compile_workflow`) to convert the silent pre-trace-failure class into a clean 400 with diagnostics.
- **`_require_local_origin` as a single choke point** in `_json_body` — one guard covers all mutating POSTs.

**Reject (tried/considered and wrong here):** `-m pflow` · `asyncio.create_subprocess_exec` · gating IO inspect on `ReadPanel`/`selectedNode` · `_redact(<scalar>)` · `sensitive` on the `IOPort` dataclass · adding a verb to the subscribe-effect deps instead of the ref.

## Gotchas & Non-Obvious Coupling

- **`meta.inputs` is written UN-interned** (`_flush_line(..., intern=False)`) → its values carry NO blob refs → `read_run_inputs` correctly skips blob resolution. But it also lands in `run_tailer._read_meta`'s process-lifetime `_SCAN_CACHE` — `_read_meta` now `pop`s `inputs` (a multi-KB input × every trace would bloat the cache; nothing reads it there).
- **`_io_detail` guards `if ref.ancestor_path: return None` FIRST** — `meta.inputs`/`json_output.result` are bare-name-keyed TOP-LEVEL values, so a sub-workflow input named like a top-level one would otherwise borrow the top-level value.
- **`format_param_value(None)` → the literal string `"None"`** → `read_run_inputs` drops None-valued keys (else a `default:null` round-trips null→"None" on re-run).
- **The pinned-resolve grace window** (`_PINNED_RESOLVE_ATTEMPTS = 60` × `_POLL_S 0.25` = 15s) must exceed the child's cold time-to-meta (interpreter + `import pflow.cli` + compile — an `llm` node cold-imports litellm ~1-3s). Tests that drive a ghost run to window-exhaustion **must monkeypatch `_PINNED_RESOLVE_ATTEMPTS → 2`** or they wait the real 15s.
- **`execution_id` env uses `pop`, not `get`** (`run.py`) — so a node that re-shells `pflow` can't inherit + collide on the id.
- **`json_output` is recorded ONLY on `--output-format json` runs** → the spawn always passes that flag (output inspect would be flaky on text-mode otherwise).
- **TestClient defaults to `Host: testserver`** → the Host guard 403s it. Server tests use the `_client()` helper (loopback `base_url`); a new POST test that uses a bare `TestClient` will 403.
- **`fetchRunNode`/`fetchRunInputs` THROW on non-200** → the frontend callers (`ThisRunSection`, `PortRunValue`, `RunPanel.loadFrom`) each own a `.catch` that degrades to "no recorded value" / inline error, never a blank panel (DR-6).

## Integration Points (blast radius)

- **`meta.inputs`** — new trace meta key (+ added to `core/trace_io.py::META_KEYS`, load-bearing for the test-fixture builder's meta-vs-trailer routing). Additive-safe: `reconstruct_trace_from_lines` folds meta keys generically; all trace readers ignore extras.
- **`run.complete.execution_id`** (Phase 4.5) — added to `_aggregates()` + the `_RUN_COMPLETE_FIELDS` SSE allowlist + the TS `RunComplete`.
- **`RunnerConfig.execution_id`** — new field; all call sites use keyword args (no positional-shift regression). `None` on every path except a UI-launched run.
- **New/changed HTTP contract:** `POST /api/run`, `GET /api/run-inputs` (new); `POST /api/command` gained `select-run`; `GET /api/run-node` gained the IO projection. All documented in `ui/CLAUDE.md`.
- **Frontend contract:** `PointHandlers.selectRun` is a **new REQUIRED member** — every `subscribe(...)` caller must supply it (fixed 4 test handler objects). `RunNodeDetail.duration_ms` relaxed to `number | null` (IO cards). `ApiErrorEntry.suggestions` added. `IOPort.sensitive` added to the TS type (+ the renderer emits it on input nodes → **the committed React-Flow contract fixtures were regenerated**).

## Tests That Matter

Run these when touching the respective area (each catches a real regression, not coverage):
- `tests/test_runtime/test_meta_inputs.py` — the keystone: value correctness (raw types) + the **write-ordering pin** (meta line carries inputs before node events).
- `tests/test_cli/test_run_node.py` — the IO projection: **sub-workflow `ancestor_path` collision guard returns None not the top-level value**, secret-named input redacted, the `isRunNodeDetail`-valid synthesized shape, `read_run_inputs` omits secrets + drops None, and **`test_cli_json_run_records_json_output_result_on_run_complete`** (the CLI `set_json_output`-before-`finalize` ordering the output panel depends on).
- `tests/test_cli/test_ui_interaction_server.py` — the **Host-guard matrix** (evil.com → 403, loopback variants pass, covers all POSTs), the **exact spawn argv** (`-m pflow.cli`, DEVNULL×3, `start_new_session`, `PFLOW_EXECUTION_ID`), injection-safety, the pre-flight 400 (real `compile_workflow`), and `select-run` pass-through + unknown-verb-still-400.
- `tests/test_cli/test_ui_commands.py::TestServeRun` — the smart `--run`: reuse+live-Viewer POSTs `select-run` (no browser open) vs reuse+no-Viewer opens pinned.
- `web/src/components/RunPanel.test.tsx` — the re-run prefill: **a sensitive field stays blank even when the run had a value**; Defaults resets.
- `web/src/api/events.test.ts` — the `select-run` dispatch arm (string-guarded).
- **Mutation-verified:** `test_read_run_inputs_..._round_trip_faithfully_through_the_cli_parser` (fails under a simulated `infer_type` regression that the forward-only assertion misses) — the re-run faithfulness core promise, on the live server-argv path (not the orphaned `rerun_display` shell path).
- **Not unit-testable — needs the real-browser loop** (`make ui-build` + a live server): the overlay lighting up on a spawned run, IO "This run" values rendering, and the `select-run` SSE switch (broadcast → EventSource → `selectRun` re-pins). The last was verified with a same-origin `select-run` fetch flipping an open Viewer's pinned run end-to-end.

---
*Distilled from the implementation context of Task 175. The chronological journey (round-by-round UX iteration, the 7-agent deep-review findings + fixes, dead-ends) lives in `implementation/progress-log.md` — this review is the durable forward-reference, not a re-narration.*
