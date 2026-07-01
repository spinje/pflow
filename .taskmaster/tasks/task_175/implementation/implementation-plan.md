# Task 175 — Run Workflows from the Web UI: Implementation Plan

> Audience: an AI agent implementing this in isolation. Every seam, file, and edge case is named.
> Spec of record: `.taskmaster/tasks/task_175/task-175.md` (+ braindump in `starting-context/`).
> This plan adds the *how* and the verified file:line seams; read it top-to-bottom before coding.

---

## Context

The Task 173 live overlay made runs **observable** in the browser (the canvas lights up, you can replay
a finished run, a detail panel shows each node's runtime record) — but the browser is **read-only**: you
can't *start* a run from it, a run's **input values are recorded nowhere** (trace `meta` omits them), the
**IO nodes aren't inspectable** (they don't execute, so they have no runtime event), and re-running means
retyping `pflow run …` in a terminal.

This task closes that gap by **composing with the already-built run/trace/tail/overlay pipeline** rather
than adding a subsystem. The load-bearing idea (ADR-0008): the server **never hosts a run** — it spawns a
normal **detached `pflow run` subprocess**, which writes its own streaming trace that the existing tailer
discovers and the overlay lights up. The keystone is recording `meta.inputs` at run start, which unlocks
input inspection **and** faithful re-run at once. We also give the **agent** a first-class way to
open/replay a specific run in the user's Viewer (the agent twin of the human run picker).

**Outcome:** click ▶ → fill an auto-generated form → watch the run light up live → click any node
(including IO nodes) to see what it received/produced this run → re-run from a past run's inputs. Plus
`pflow ui <wf> --run <id>` and a `select-run` Point verb for the agent.

---

## Architecture & invariants (do not violate)

These are distilled from ADR-0008 and the Task 173 review. Breaking one silently breaks the overlay.

1. **Server observes, never hosts.** The ONLY new mutation is spawning a detached `pflow run`. No
   in-process execution, no per-run process registry. Observation is via the trace file, not the process.
2. **Read trace files as RAW JSONL lines — never `load_trace_file`/`reconstruct`.** Those strip
   `ancestor_path`+`port` (the overlay join keys) → silently blank panels. The #1 recurring trap. Reuse
   `run_node.py`'s raw-read helpers (`_resolve_trace`, the blob-map scan).
3. **Any handler that touches the `_Hub` MUST be `async def`** (the hub's queues are loop-owned, lock-free).
   CPU/compile work goes off-loop via `await asyncio.to_thread(...)` (precedent: `command()` server.py:561).
4. **Never surface raw `node_type`** (Python class name) to an agent — use `node_type_tag()`. Any new
   endpoint that echoes node info uses an explicit allowlist (precedent: `RunNodeDetail` projection).
5. **The run-complete SSE wire is allowlisted (4 fields).** A launch must not re-widen it.
6. **First-subscriber rule:** any *new latched* signal must be BOTH broadcast AND carried in `snapshot()`.
   (We add no new latched signal — launch reuses follow-newest — so this is a "don't regress" note.)
7. **Re-pick guard:** switching runs must keep `if (next === runId) return` in `selectRun`
   (GraphView.tsx:242) — a no-op reselect once wiped the overlay.
8. **One redaction rule:** every secret-redaction site defers to `is_sensitive_parameter`
   (`security_utils.py`). Word-boundary match; do not replicate it in TS.
9. **A web change is invisible until `make ui-build` + restart `pflow ui`.** Rebuild before every browser check.

---

## Forward-looking seams (deliberate; justified by ≥2 real consumers)

Built now because a concrete next feature needs them — not speculative:

- **`_require_local_origin(request) -> Response | None`** — a shared guard, composed into `_json_body`
  (so every mutating POST is covered) and callable standalone. Consumers: our `/api/run` + the 3 existing
  POSTs *now*; HITL gate-response POST (Task 125) *next*.
- **`RunForm` as a standalone schema-in/submit-out component**, decoupled from the side-panel chrome.
  Justified on **present** merits: `RunPanel` (chrome/resize/open-close) and `RunForm`
  (schema→values→submit→errors→prefill) are genuinely different responsibilities, and the form's logic
  (control mapping, error rendering, prefill, no-input confirm) earns isolated vitest coverage today.
  (NOT justified by a speculative `?view=form` — that stays out of scope.)
- **`controlForType(dataType)` — one `data_type → control` mapping function.** A pure, tested 7-case map;
  the single obvious place to extend when file-upload inputs land. Locality, not a plugin system.
- **`select-run` added in the existing additive SSE-dispatch pattern**, contract documented once in
  `ui/CLAUDE.md`. The verb vocabulary is genuinely growing (our `select-run` + Task 174's `--say`).

**Seams deliberately declined** (would just move complexity, fail the deletion test): a generic
input-source plugin system; a launch-mode strategy pattern; a cross-language verb "registry" (can't span
Python/TS without codegen); a per-field run-provenance model (spec defers this to value-autocomplete); a
named `buildRunArgv` builder (a single argv literal at one call site — **inlined**; a future Resume mode
extends the argv in place).

---

## Phase 1 — Producer: record `meta.inputs` (the keystone)

**Goal:** the eager trace `meta` line carries the run's resolved declared-input values, for all runs.

**Changes (3 edits, verified seams):**
1. `src/pflow/runtime/workflow_trace.py` — in `WorkflowTraceCollector.__init__` (~:625, beside
   `self.only_node`), declare `self.inputs: dict[str, Any] | None = None`. In `_meta_fields()` (:947-957)
   add `"inputs": self.inputs` to the returned dict.
2. `src/pflow/execution/runner.py` — in `_compile_and_execute`, immediately **after** the defaults merge
   `shared_store.update(workflow.resolved_defaults)` (:279) and **before** `engine.run(...)` (:292):
   ```python
   if trace_collector is not None:
       trace_collector.inputs = {
           n: shared_store[n] for n in resolved.ir.get("inputs", {}) if n in shared_store
       }
   ```
   This is the **robust** form (IR-driven): `resolved.ir["inputs"]` is a dict keyed by bare input name;
   `shared_store` (a plain `dict`) holds each input's FINAL resolved value (user value if provided, else
   default/env/settings) at this point, before any node runs. It is immune to the `params` vs
   `resolved_defaults` split and to internal `__`/`_`-prefixed keys. **Do NOT** use `{**params,
   **resolved_defaults}` or `filter_user_params` (incomplete — strips only `__`).
3. `src/pflow/core/trace_io.py` — add `"inputs"` to the `META_KEYS` tuple (:30-38). **This IS required**
   (not doc-only): although production `reconstruct_trace_from_lines` round-trips meta keys generically
   (`trace_io.py:227`), the **test-fixture builder** `tests/shared/trace_jsonl.py:98` iterates `META_KEYS`
   to route a trace-dict's keys onto the meta line vs. the `run.complete` trailer. Omit it and any
   Phase-4/5 fixture built via `write_trace_jsonl({..., "inputs": {...}})` puts `inputs` in the *trailer*,
   not the meta line — so the IO-projection tests read the wrong line and fail (and an implementer might
   "fix" it by reading inputs from the trailer, silently diverging from production's meta-line placement).

**Storage policy (decided):** stored **raw** on disk (typed values — same exposure class as today's raw
`node_params`; secrets already land raw in node_params downstream). **Redaction happens on read**, never
at write — so re-run can reconstruct faithful values server-side. No write-time masking.

**Edge cases:**
- `meta.inputs` is **top-level inputs only** (the runner's `resolved.ir` is the top-level IR). Sub-workflow
  input nodes (non-empty `ancestor_path`) are not in `meta.inputs` — Phase 4 degrades gracefully for them.
- The meta line is written un-interned (`intern=False`, keeps the `pflow_trace` marker as line 1), so a
  very large input value is stored inline verbatim (acceptable; note it).
- A run that fails before `engine.run()` (e.g. missing required input) writes **no** meta line — that's the
  silent-pre-trace-failure the Phase 2 pre-flight prevents.

**Tests (`tests/test_runtime/` + `tests/test_core/`):**
- `meta.inputs` recorded for a templated run (`name=World`), present for saved/path/inline runs, holds the
  resolved value (user-provided AND default-sourced inputs).
- The `flatten↔reconstruct` round-trip stays green (`test_core/test_trace_io.py::test_flatten_reconstruct_round_trip`)
  — this is the gate confirming the additive meta field is safe.
- A no-input workflow records `meta.inputs == {}` (or `None`); readers tolerate it.
- **Write-ordering invariant** (defensive): the stamp MUST run before `start_streaming()` flushes the meta
  line — the chosen placement (after :279, before `engine.run()` at :292) satisfies this. Add a code
  comment marking the ordering load-bearing, and pin it with a test that a run whose **first node already
  executed** still carries `inputs` on the meta line (guards a future refactor moving the stamp past the
  first flush, which would silently drop `meta.inputs`).

---

## Phase 2 — Backend: `POST /api/run` + shared Host guard

**Goal:** spawn a detached run from a resolved workflow + inputs; reject pre-trace failures with a clean 400.

**Security guard (the seam):** in `src/pflow/ui/server.py`, add
`_require_local_origin(request) -> Response | None`: read the `Host` header, parse the host part (strip
port; handle IPv6 brackets), return a **403** if it isn't in `{"127.0.0.1", "localhost", "::1"}`, else
`None`. **Call it first inside `_json_body`** (`server.py:418`) so all current mutating POSTs
(`command`/`interaction`/`visibility`) and the new `/api/run` are covered by one choke point. Update the
load-bearing security comment block (`server.py:826-837`) to record that the DNS-rebinding gap is now
closed by the Host check (this is the "must revisit for any mutating/live-run endpoint" it flagged).

**`POST /api/run` handler (`async def`, registered beside the other POSTs at server.py:817-819):**
1. `_json_body` (→ guard + 415/400). Body shape: `{"workflow": "<name|path>", "inputs": {"<name>": "<token-string>"}}`.
   Validate: `workflow` non-empty str; `inputs` an object whose values are strings (coerce/round-trip via
   `str` if needed). 400 on malformed.
2. Resolve: `key = _workflow_key(workflow)` → `_workflow_not_found(...)` 404 (fuzzy suggestions) if `None`.
   **Never** accept inline content. (The heavier `resolve_workflow(key)` → `resolved.ir` runs **inside** the
   off-thread pre-flight below, not on the event loop.)
3. Build argv tokens: `tokens = [f"{name}={value}" for name, value in inputs.items()]` (one per
   argv-element, no shell → injection-safe). This is **channel A** (form == CLI).
4. **Pre-flight** (the WHOLE thing off-loop in ONE `asyncio.to_thread` — honors invariant #3). Prevents
   the silent **pre-trace-failure class**: a run that dies before `engine.run()` writes its meta line shows
   nothing on the overlay. Do the **full compile the spawn will do**, not just input-checking — a workflow
   can fail pre-trace at *compile* too (unknown node type, bad param), and the endpoint can't assume the
   displayed tab is still valid (auto-update may have edited the file; an agent may POST directly):
   ```python
   def _preflight(workflow, tokens):                      # runs in a worker thread
       resolved = resolve_workflow(workflow)              # disk read + parse — OFF the loop
       typed_params = parse_workflow_params(tokens)       # cli/param_parsing.py — infer_type per token
       settings_env = SettingsManager().load().env
       compile_workflow(resolved.ir, registry, initial_params=typed_params)  # validate + prepare_inputs + instantiate; NO execution
   try:
       await asyncio.to_thread(_preflight, key, tokens)
   except PflowError as exc:                              # SchemaValidationError (missing input), CompilationError, ...
       return _json({"errors": [d.to_dict() for d in exception_to_diagnostics(exc)]}, status_code=400)
   ```
   `compile_workflow` runs `prepare_inputs` internally, so a missing required input surfaces here too
   (message `"Workflow requires input '{name}': {description}"` — agent-actionable). `registry` is the node
   registry the server already uses for graph rendering (thread it in like the `command()` build path).
   This is the same off-loop discipline `command()` uses (`server.py:561`). *(If wiring the registry proves
   awkward, the equivalent reuse is `resolve_validate_build(workflow)` + `prepare_inputs(resolved.ir,
   typed_params, settings_env)` in the same `to_thread` — but `compile_workflow` is the truest
   "would this run" check and closes the whole pre-trace-failure class.)*
5. **Spawn** (detached via the spec's primitive — **`subprocess.Popen`, NOT `asyncio.create_subprocess_exec`**):
   ```python
   subprocess.Popen(
       [sys.executable, "-m", "pflow", "run", key, "--output-format", "json", *tokens],   # argv inlined
       stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)
   return _json({"status": "spawned"}, status_code=200)
   ```
   **Why Popen, not asyncio** (load-bearing — verified against the 3.14 stdlib): asyncio's
   `BaseSubprocessTransport.close()/__del__` calls `_proc.kill()` on a still-running child, so the asyncio
   machinery couples the run's lifetime to the event loop and **SIGKILLs an in-flight run when the user
   closes `pflow ui`** (intermittently, by finalization timing) — the exact outcome ADR-0008's detached
   design forbids. `start_new_session=True` does NOT protect (it detaches the *session*, not from a direct
   `kill(pid)`). `subprocess.Popen.__del__` only warns + defers reaping; the child reparents to init and
   init reaps it; finished prior runs are reaped by `subprocess._cleanup()` on the next spawn — so we keep
   **no per-run process state** (no `proc` retained, no `create_task`). `Popen()` returns immediately after
   fork/exec (does not block on the child), so calling it from the async handler is fine; wrap it in
   `asyncio.to_thread` only if you want the fork itself off the loop.
   - We don't know the run id yet (the child mints `execution_id`); the overlay follows-newest, so none is
     returned. Runtime node failures surface via the overlay, not the response. `--output-format json` makes
     the success/degraded `json_output` available for Phase 4 — it is **NOT** recorded on a *failed* run
     (a failed run has no declared result; Phase 4 treats that as graceful "no recorded output"). stdout is
     DEVNULL'd (nobody reads it).
   - **CWD/env:** the child inherits the server's CWD (where `pflow ui` launched) — same as a hand-typed run
     from that shell — and re-injects `settings.env` at its own startup, so secrets resolve.

**Edge cases:** rapid ▶ clicks → multiple detached spawns (fine for single-user; the frontend disables
submit while in-flight as cheap insurance — Phase 3). Unknown workflow → 404. Bad body → 400. Pre-flight
failure → 400 with diagnostics. The startup race (child not yet written its meta line) resolves itself —
follow-newest picks the run up once its locked trace appears.

**Tests (`tests/test_cli/` UI server tests, mirroring existing `test_run_node.py` / command tests):**
- spawn invoked with the expected argv (monkeypatch `subprocess.Popen`); assert `start_new_session=True`
  and stdio all DEVNULL; 200 on success.
- 404 unknown workflow; 400 malformed body; 400 with diagnostics on a missing required input (pre-flight).
- **Host guard:** a request with `Host: evil.com` → 403; `Host: 127.0.0.1:PORT` and `localhost:PORT` → pass;
  assert the guard also rejects the existing POSTs (`command`/`interaction`/`visibility`).
- argv tokens are injection-safe (a value with a space/`;` becomes one argv element, unparsed).

---

## Phase 3 — Frontend: ▶ Rail button → Run side-panel + form + launch

**Goal:** a ▶ at the Rail bottom opens a side-panel form generated from the schema; submit spawns the run
and the overlay follows it live.

**Schema flag (single source of truth):** compute `sensitive: is_sensitive_parameter(name)` in
`src/pflow/core/workflow/graph/renderers/react_flow.py` and attach it to the `io` payload of
**`kind=="input"` nodes ONLY**; mirror the field in the **TS `IOPort` interface** (`web/src/types.ts`).
**Do NOT add `sensitive` to the Python `IOPort` dataclass** (`graph/model.py:62`): that model is
renderer-agnostic/pure (platform facts are injected at the renderer seam, not carried in the model — see
graph/CLAUDE.md), and because the wire ships `asdict(node.io)` it would also leak `sensitive` onto **output**
nodes. The client uses the flag only to render a "provided from settings/env" hint — it does **not**
replicate the redaction rule. Required-ness is enforced by the Phase-2 pre-flight, not the client.
**After this change, regenerate the committed contract fixtures** (the input `io` payload changed):
`uv run python -m tests.fixtures.react_flow_contracts._generate` — else
`tests/test_core/test_react_flow_contract_fixtures.py::test_committed_contract_fixture_matches_live_renderer`
fails (it asserts committed == live; three fixtures carry input nodes). Hand-editing the JSON risks
re-encoding a drifted shape — regenerate, don't hand-edit.

**Components (under `web/src/`):**
- `components/Rail.tsx` — add a `RailButton` (▶) after the focus block (~:132) with a new `onRun` prop and
  a `showRun` gate, mirroring the existing buttons. The ▶ toggles `runPanelOpen`.
- `components/RunPanel.tsx` (new) — the side panel using the `.read-panel` shell (resizable; its own
  open/close state, **outside** the `selectedId` model — like the RunSelector popover, so it never races
  the three selection panels). Hosts `RunForm`.
- `components/RunForm.tsx` (new, the reusable seam) — props `{ inputs: InputField[], values, onChange,
  onSubmit, submitting, errors, loadFrom }`. Renders one control per input via `controlForType`, the
  "load inputs from" picker (Phase 5), a Submit button (disabled while `submitting`), and inline
  `errors` (from a 400). A no-input workflow renders just a "▶ Run" confirm button.
- `web/src/util/controlForType.ts` (new) — `controlForType(dataType: string | null)` →
  `"text" | "number" | "checkbox" | "textarea"`. Map: `number`/`integer`→number, `boolean`→checkbox,
  `object`/`array`→textarea (JSON text), `string`/`any`/`null`/unrecognized→text. (`io.data_type` is the
  authored-verbatim string, possibly a Python alias or null — hence the text fallback. Canonical set:
  `string,number,integer,boolean,array,object,any` from `core/types.py:16`.)

**InputField model** (derived from `/api/graph` `kind=="input"` nodes): `{ name: ref.node_id,
dataType: io.data_type, required: io.required, default: io.default, description: node.purpose,
sensitive: io.sensitive }`. (`required` absent ⇒ **true**; `description` rides `purpose` on the RFNode, not
`io`.) Use `IoPanel.tsx`'s `wrapperPorts(graph, group)` as the *reference* for enumerating inputs, but read
`sensitive` **directly from the node's raw `io`** — `wrapperPorts` (`web/src/graph/io.ts`) maps `io` to a
`Port` that drops `sensitive`, so deriving the hint from it would silently never render.

**Value encoding (channel A):** each control's value is sent as a **token string** — checkbox→`"true"`/
`"false"`, number→its digits, text→as-is, JSON textarea→raw JSON text. The server passes them verbatim as
`name=value` argv; the spawned CLI's `infer_type` + declared-type `coerce_workflow_input` re-type them.

**API client (`web/src/api/client.ts`, typed-with-ApiError pattern):** add
`runWorkflow(workflow, inputs): Promise<void>` → `POST /api/run`. On 400, surface
`error.body.errors` into the form. Keep the `Content-Type: application/json` header (load-bearing for the
no-CORS posture). (Note: use `client.ts`, not the fire-and-forget `events.ts` POST helpers, because we
need the typed error.)

**Launch flow (`views/GraphView.tsx`):** the ▶ opens `RunPanel`; on submit → `runWorkflow(...)` → on
success call `selectRun(null)` (follow-newest-live, the existing mechanism) so the launched run lights up;
close the panel. Each fetch owns its failure (DR-6) — a spawn error shows in the form, never blanks the
canvas. Disable submit while in-flight (rapid-click guard).

**Tests (`web/src/**/*.test.tsx`, vitest + jsdom):**
- `controlForType` maps every canonical type + falls back to text on null/unknown.
- `RunForm` renders required markers, prefilled defaults, the sensitive hint, and a no-input confirm;
  submit calls `onSubmit` with the token-string map; a 400 renders inline errors.
- the ▶ shows/toggles the panel; a successful submit triggers follow-newest (`selectRun(null)`).

---

## Phase 4 — Inspect: click any node → "This run" (IO nodes included)

**Goal:** clicking an input node shows its value for the run; an output node shows the workflow result.

**Server (`src/pflow/ui/run_node.py`):** extend `run_node_detail` / `_read_matching_event` to **project
IO refs from `meta`/`json_output` instead of scanning for a (nonexistent) node event.** Discriminate by
the ref's **port marker** (verified: `_input_node_id`→`port="in"`, `_output_node_id`→`port="out"`,
`build.py:891-896`):
- **Top-level only — guard FIRST:** `if ref.ancestor_path: return None` (→ "no recorded value"). This is
  load-bearing: `meta.inputs` / `json_output["result"]` are keyed by **bare name** and hold **top-level**
  values only, so without this guard a sub-workflow IO node sharing a bare name with a top-level
  input/output (e.g. both named `url`) would render the *top-level* value. The direct keyed lookup bypasses
  the `ancestor_path` discriminator `_ref_matches` gives every regular ref — restore it explicitly.
- input ref (`port=="in"`, empty `ancestor_path`) → `meta.inputs[ref.node_id]` from the trace's first
  (meta) line — **raw-read**, then `_redact(...)` (the recursive key-name redactor).
- output ref (`port=="out"`, empty `ancestor_path`) → `json_output["result"][ref.node_id]` from the
  `run.complete` trailer (raw-read, `_redact`). Absent (text-mode run, OR a *failed* run — `json_output` is
  recorded only on success/degraded, not failure) → graceful "no recorded output".
- regular ref → existing event scan (unchanged).
- **Return a shape `isRunNodeDetail` (`client.ts:119`) accepts:** that guard requires string `node_type` +
  string `status` + `"input"`/`"output"` keys. IO refs have no event, so the IO branch must **synthesize**
  these: `node_type = "input"|"output"` (or a `node_type_tag()`-style label), a string `status`
  (e.g. `"recorded"`), the projected value under `input` (input nodes) / `output` (output nodes), and
  `duration_ms` per the TS type — **relax `RunNodeDetail.duration_ms` to `number | null`** and verify
  `ThisRunSection` renders an IO card with no tokens/duration. Keep the allowlist + `node_type_tag()` (no
  raw `node_type`, no `_`-internals).

**Frontend gate (`views/GraphView.tsx`):** the terminal-node gate (`:68` `TERMINAL_RUN_STATUSES`, used at
`:934`) currently closes for IO nodes (no completion event). Extend `showRunDetail` to also open when the
selected node is an IO node **and** a run is in context:
`showRunDetail = TERMINAL_RUN_STATUSES.has(status) || (isIONode(selectedNode) && hasRunContext)`, where
`isIONode = node.kind === "input" || node.kind === "output"` and `hasRunContext = runId !== null ||
runStatus.size > 0` (the exact GraphView state: a run is pinned, or the overlay has observed one this
session). `ThisRunSection` fetches `/api/run-node` with `runId ?? null` (newest-live if unpinned) and
renders the projected value; if nothing is recorded it shows "no recorded value", never a crash. The
existing `epoch` refetch and redaction-on-display both already apply.

**Edge cases:** text-mode run (no `json_output`) → output node degrades cleanly; cached node shows reduced
input by design (pre-existing, don't "fix"); sub-workflow IO nodes → "no recorded value".

**Tests:** `tests/test_cli/test_run_node.py` — input-ref projection returns the redacted `meta.inputs`
value; output-ref returns `json_output["result"][name]`; **a sub-workflow IO ref (non-empty
`ancestor_path`) sharing a bare name with a top-level input returns "no recorded value", NOT the top-level
value** (the collision guard); missing data → graceful None/empty, not a crash; a secret-named input is
redacted; the IO projection returns an `isRunNodeDetail`-valid shape. Frontend: the gate opens for an IO
node with a run in context.

---

## Phase 5 — Re-run: "load inputs from" picker

**Goal:** prefill the form from a past run's inputs (server-redacted), then tweak and submit.

**Server — `GET /api/run-inputs?workflow=X&run=<id>` (new, small):** resolve the trace via the shared
`_resolve_trace(workflow_key, run_id)` helper (`run_node.py`, raw-read), read the meta line's `inputs`
(typed), and return form-ready token strings: for each input, **omit sensitive-named keys**
(`is_sensitive_parameter`) and render the rest via `format_param_value(value)` (`param_parsing.py:68` —
the inverse of `infer_type`; compact JSON for list/dict). Returns `{ "<name>": "<token-string>" }`. This is
the server-side secret redaction: a past run's resolved secret never reaches the browser.

**Frontend:** the `RunForm` "load inputs from" picker lists *Defaults* + the last N past runs (from the
existing `fetchRuns` / `/api/runs`, labeled timeAgo + status via `runMark`). Selecting *Defaults* resets
fields to the declared `io.default`s; selecting a run calls a new
`fetchRunInputs(workflow, runId)` → prefills non-sensitive fields (sensitive fields stay blank with the
"from settings/env" hint → they re-resolve, or the user types an override). Submit reuses the Phase-3
launch flow. The clock/RunSelector per-row ↻ is **optional sugar**: it opens `RunPanel` with that run
pre-selected in the picker (honor the re-pick guard if it also switches the overlay).

**Edge cases:** a run whose `meta.inputs` predates this feature (older trace) → picker shows it with empty
inputs (graceful). Cache-enabled nodes re-running with identical inputs light "cached" (already works).

**Tests:** `/api/run-inputs` renders typed values back to tokens, omits sensitive keys, 404 on unknown run;
frontend prefill fills non-sensitive fields and leaves sensitive blank.

---

## Phase 6 — Agent: open/replay a specific run

**Goal:** `pflow ui <wf> --run <id>` opens a Viewer pinned to a run; a `select-run` Point verb switches an
already-open Viewer to a run. Both reuse the shipped `&run=<run_id>` pin contract (173).

**`--run` flag (CLI, `src/pflow/cli/commands/ui.py`):** add a `--run <id>` option to `serve_cmd`
(`:407-491`) and thread it through `_serve_url` (`:82-95`) as `?run=<id>` (mirror the existing optional
`watch=0` param). The frontend already reads `?run=` (`GraphView.tsx:101-103`) and replays. `<id>` = the
run's `execution_id`.

**`select-run` Point verb (3 lockstep sites — no shared enum exists):**
- CLI: a new `select_run_cmd` subcommand of `ui` (mirror `focus_cmd:493`), POSTing via `_point_request`
  (`:380`) `{"workflow": wf, "type": "select-run", "target": "<run_id>"}` (reuse the `target` field to
  carry the run id).
- Server: `command()` (`server.py:532`) — add `"select-run"` to the verb whitelist (`:543`). Place the
  branch **after `target` is extracted** (the run id rides in `target`) — NOT alongside `clear` (which
  returns *before* the target is read): broadcast `{"type": "select-run", "run": target}` with **no**
  `resolve_target` (pass-through). Update the existing whitelist test in
  `tests/test_cli/test_ui_interaction_server.py` so its "invalid verb rejected" assertion treats
  `select-run` as valid (don't collide with a hardcoded `{focus,frame,clear}` set).
- Browser: `web/src/api/events.ts` — add a `"select-run"` arm to the `onmessage` dispatch (:108-155) and a
  handler to `PointHandlers` (:6-10). **Route it through the existing `pointHandlers.current` ref**
  (`GraphView.tsx:628-651`), exactly like `focus`/`frame`/`clear` — that ref indirection exists so handler
  identity changes never re-fire the subscribe effect. The ref's `select-run` handler calls
  `selectRun(runId)`. Do **NOT** add `selectRun` to the effect's dep array (its identity already tracks
  `runId`, which is already a dep — the ref pattern is the established, churn-free path). The
  `if (next === runId) return` re-pick guard in `selectRun` is honored automatically; a stale/unknown id
  surfaces the existing `run-not-found` path (keep the verb pass-through — no server-side run validation).

**Docs (part of this phase):** `src/pflow/guide/features/ui.md` (Point verbs :41-45, the `&run=` contract
:71-76 — add `--run` + `select-run`); `src/pflow/ui/CLAUDE.md` (the Live interaction channel envelope — add
`select-run` AND **correct its now-stale "defines no run/trace event schema" claim**, which 173 already
invalidated); `web/CLAUDE.md` (overlay seam bullet).

**Tests:** CLI — `select_run_cmd` POSTs the expected body; `_serve_url` includes `?run=`. Server — `command`
accepts `select-run` and broadcasts `{type:"select-run", run}` without target resolution; the verb whitelist
rejects an unknown verb. Frontend — a `select-run` SSE message calls `selectRun(runId)`.

---

## Cross-cutting

- **Errors are agent-actionable** (pflow is agent-first): every 4xx body carries a clear message (+ path/
  suggestion for pre-flight). Never a bare status. Reuse `Diagnostic.to_dict()`-shaped payloads where the
  existing handlers already do (`server.py:263/288/338`).
- **Secrets:** raw at write (Phase 1), redacted on every read/display (Phase 4 `_redact`, Phase 5 omit).
  The accepted residual (a secret embedded in a free-text value, key-name redaction only) is pre-existing.
- **Trace growth (noted, not built):** `~/.pflow/debug` has no retention; the ▶ multiplies traces — a
  retention policy is a fast-follow (GH #542), out of scope here.
- **Accepted v1 limitations:** the submit-disable guards POST latency, not run *duration* — a user can
  launch overlapping detached runs (each incurs real cost); a "run in flight" affordance tied to overlay
  status is a possible follow-on. UI launches always read/write cache (no `--no-cache` flag), so the
  faithfulness check (verification #4) means "identical to a hand-typed run *without* `--no-cache`".

## Out of scope (documented follow-ons)

`?view=form` bookmarkable standalone view; file-upload inputs (multipart + where files land);
per-field value-autocomplete; frontmatter-store deprecation; trace retention; stdin-routed inputs need no
work (a detached spawn pipes nothing, so a `stdin: true` input is just a normal form field).

---

## Verification

**Automated gates (capture baseline first, then diff):**
- Python: `make test` + `make check` (mypy/ruff) green vs baseline. Key pins to keep green:
  `test_core/test_trace_io.py` round-trip, `test_cli/test_run_node.py`, the join pin
  `test_runtime_event_refs_join_onto_the_static_graph`.
- Frontend: `cd web && npm run test` (vitest) + `tsc` (via `npm run build`) green.

**Real-browser loop (mandatory — overlay failures are invisible to unit tests):** after `make ui-build` +
restart `pflow ui`, use the Task-173 instrument: **launch a run → poll its trace to a known state → read
the DOM `status-*` class / screenshot** (the `screenshot-pflow-web-ui` skill for static shots; the
overlay-status probe for authoritative status). Concretely verify, end to end:
1. Open a workflow with inputs → ▶ → form generated (required marked, defaults prefilled, sensitive hinted)
   → submit → the run lights up live and finishes with the run banner. A no-input workflow shows ▶ Run confirm.
2. Click the input node → its run value (secret-named REDACTED, normal full); click the output node → the
   workflow result; click a producing node → its output. Text-mode run degrades cleanly.
3. "load inputs from" a past run → non-sensitive fields prefill, sensitive stay blank → submit reproduces
   the run (cache-enabled nodes light "cached").
4. **Faithfulness:** a form launch and the equivalent hand-typed `pflow run …` produce identical results.
5. `pflow ui <wf> --run <id>` opens a replay; with a Viewer open, the `select-run` verb switches it.
6. **Security:** a request with a non-loopback `Host` → 403; loopback → succeeds; the guard also covers the
   existing POSTs.

**Recommended pre-implementation gate:** run `/deep-review` in plan mode on this plan before coding —
plan-stage findings are the cheapest to fix.

---

## Build order

1 (producer) → 2 (endpoint+guard) → 3 (form+launch) → 4 (IO inspect) → 5 (re-run picker) → 6 (agent verb).
Each phase is independently testable; 1 unblocks 4 & 5; 2 unblocks 3. Land behind the gates above.
