# Task 175 — Implementation Progress Log

> Run workflows from the Web UI. Plan of record: `implementation-plan.md`. Spec: `task-175.md`.
> Build order: 1 (producer) → 2 (endpoint+guard) → 3 (form+launch) → 4 (IO inspect) → 5 (re-run picker) → 6 (agent verb).

## Baseline (captured before any change)

- `make test`: **8232 passed, 0 failed** in 25.94s (clean tree at commit `1ce1c968`).
- Branch: `feat/web-ui-workflows`.

---

## Phase 1 — Producer: record `meta.inputs` (the keystone)

**Status:** ✅ complete — awaiting review

### Pre-flight verification (against current code, before editing)

- `WorkflowTraceCollector.__init__` ends with `self.only_node` — confirmed at `workflow_trace.py:625`.
- `_meta_fields()` returns the 7 run-identity keys — confirmed at `workflow_trace.py:947-957`.
- `META_KEYS` tuple — confirmed at `trace_io.py:30-38` (7 keys, no `inputs`).
- `runner._compile_and_execute`: `shared_store.update(workflow.resolved_defaults)` at `:279`, `engine.run(...)` at `:292`; `resolved` is the first param (in scope) — confirmed.
- **Write-ordering invariant proven:** `engine.run()` calls `self.trace.start_streaming()` at `engine.py:655` (only at depth 0, after the `only_node` stamp). My stamp at runner.py runs *before* `engine.run()` at `:292`, hence before the meta line is flushed. The eager meta line therefore carries `inputs`.
- **IR shape proven empirically:** `resolved.ir["inputs"]` is a `dict` keyed by **bare input name** (e.g. `{'name': {'description': ..., 'type': 'string', 'default': 'World'}}`), so `for n in resolved.ir.get("inputs", {})` yields bare names and `shared_store[n]` holds the final resolved value. Matches the plan exactly.

### Changes made (3 production edits + tests, exactly as planned)

1. `runtime/workflow_trace.py` — added `self.inputs: dict[str, Any] | None = None` in `__init__` (beside `self.only_node`); added `"inputs": self.inputs` to `_meta_fields()`.
2. `execution/runner.py` — stamped `trace_collector.inputs = {name: shared_store[name] for name in resolved.ir.get("inputs", {}) if name in shared_store}` after the `resolved_defaults` merge (:279) and before `engine.run()` (:292), with a LOAD-BEARING ordering comment.
3. `core/trace_io.py` — appended `"inputs"` to `META_KEYS` + extended the comment with the test-fixture-builder rationale.

### Proof on disk (the keystone — done first, per the handoff)

`uv run pflow run greet.pflow.md name=Alice` (count defaulted) → newest streamed trace line 1:
`inputs: {"name": "Alice", "count": 3}` — user value AND default both present, RAW (`count` is int `3`, not `"3"`). No-input workflow → `inputs: {}`. (Sandbox isolates `~/.pflow` writes, so the run+inspect was done in one `dangerouslyDisableSandbox` command.)

### Tests added

- `tests/test_runtime/test_meta_inputs.py` (new, 4 tests, `trace_files`-marked, `Path.home→tmp_path`): reads the on-disk **streamed line 1** directly — value correctness (user+default, raw int type), empty for no-input, present for inline content-string run, and the **write-ordering pin** (meta line is line 1 with populated `inputs`, node events follow).
- `tests/test_core/test_trace_io.py` — added `test_inputs_routes_to_meta_line_not_trailer`: proves the `META_KEYS` change routes `inputs` onto the meta line (not the trailer) and round-trips.

### Decisions / deviations

- **Read the raw streamed line-1 (not `load_trace_file`)** in the producer tests — deliberate: the keystone is the EAGER meta-line *placement* that Phase 4/5 readers consume, and reading line 1 raw also proves the write-ordering invariant (`load_trace_file` would abstract line placement away).
- **Covered path + inline runs, not a saved-library run.** The stamp is IR-driven and source-agnostic (operates on `resolved.ir`); path vs inline are the two *structurally distinct* cases (real file path vs synthetic `ir-hash:` path → different streaming filename). A saved-run test would exercise the resolver, not the Phase-1 stamp — adding it would be redundant coverage, not new. (Not a plan deviation: the plan's "saved/path/inline" is a verification *goal*; path+inline fully exercises the stamp.)
- **No other deviations.** Used the plan's IR-driven snapshot verbatim; did NOT simplify to `{**params, **resolved_defaults}`.

### Loose-end verification (post-implementation rigor pass)

Verified three things I had only reasoned about, against code + empirically:

1. **No placeholder leak.** `_fill_declared_defaults` only fills `if name not in params` (never overwrites a user value) and adds a `__pflow_declared_*` placeholder for required/env inputs; `_strip_placeholders` runs at `runner.py:261` — BEFORE `_initialize_shared_store` (:263) and my stamp (after :279). A truly-missing required input raises in `compile_workflow` (:273), before the stamp. → no placeholder can reach `meta.inputs`. Pinned with a 6th test (`test_meta_inputs_records_required_input_value_not_placeholder`).
2. **MCP / `--no-trace`.** `trace_collector` is ALWAYS created in `run()` (:147); `stream_to_disk=config.trace_enabled` is the only difference. So my `if trace_collector is not None` guard is defensive (for direct-call tests); for MCP/`--no-trace` the stamp lands on an in-memory collector that never writes a disk meta line — harmless. `save_to_file` is a thin alias for `finalize()` (one meta writer, always via `_meta_fields()`), so streaming and non-streaming can't diverge.
3. **Env/settings-resolved inputs land in `meta.inputs` RAW — including sensitive-named ones.** Empirically: a `settings.env` `api_key=sk-…` (no CLI value, no default) resolved by name and was recorded as `{"api_key":"sk-supersecret-123","topic":"cats"}`. **This de-risks Phases 4/5**: a real secret IS in the trace, so Phase 4 redact-on-read (`_redact`/`is_sensitive_parameter`) and Phase 5 omit-on-prefill are load-bearing for secret safety, not polish. Confirms the spec's "raw at write, redacted on read" exposure-class decision is correct and necessary.

### Gates (vs baseline 8232)

- `make test`: **8238 passed**, 0 failed (8232 + 6 new tests).
- `make check`: ruff + ruff-format passed; mypy clean (239 files); deptry clean.
- Pinned gates green: `test_trace_io.py` round-trip, `test_meta_inputs.py`.

**No loose ends. Phase 1 is complete and verified end-to-end (code + on-disk + empirical secret-exposure check).**

---

## Phase 2 — Backend: `POST /api/run` + shared Host guard

**Status:** ✅ complete — awaiting review

### Changes made

1. `ui/server.py` — added `_require_local_origin(request)` (loopback `Host` guard: strips port, unwraps `[::1]` IPv6 bracket, checks `{127.0.0.1, localhost, ::1}`) and call it **first** inside `_json_body`, so all four mutating POSTs (`command`/`interaction`/`visibility`/`run`) are covered by one choke point. Precedence is 403 (Host) → 415 (content-type) → 400 (bad JSON).
2. `ui/server.py` — added `_preflight(workflow_key, tokens)` (resolve + `parse_workflow_params` + `compile_workflow` with a fresh `Registry()`) and the `async def run` handler: `_json_body` → validate body → `_workflow_key` (404) → build injection-safe `name=value` tokens → `await asyncio.to_thread(_preflight, …)` (400 + diagnostics on `PflowError`) → detached `subprocess.Popen([sys.executable, "-m", "pflow.cli", "run", key, "--output-format", "json", *tokens], stdin/stdout/stderr=DEVNULL, start_new_session=True)` → `200 {"status": "spawned"}`. Registered the route + updated the module docstring and the load-bearing security comment block.
3. `ui/CLAUDE.md` — documented `POST /api/run` in the HTTP contract and updated the security paragraph (the DNS-rebinding gap it flagged is now closed by `_require_local_origin`).

### Verified seams before coding

- `_json_body:418`, route list, `command():532` off-loop pattern, `_workflow_key`/`_workflow_not_found`, `_json` — all confirmed against current code.
- `compile_workflow` is self-sufficient for the pre-flight: it loads `settings.env` internally (`compile_validation._load_settings_env` → `prepare_inputs(..., settings_env=...)`) and **raises** `SchemaValidationError` on a missing required input (`_raise_input_validation_errors`). So the primary `compile_workflow` path closes the whole pre-trace-failure class — no need for the plan's `prepare_inputs`+`settings_env` fallback, and no dead `settings_env` variable.

### Deviations from plan (with rationale)

1. **`-m pflow.cli`, NOT `-m pflow` (the plan's literal argv).** VERIFIED: `python -m pflow` errors (`'pflow' is a package and cannot be directly executed` — there is no `src/pflow/__main__.py`). The plan author assumed a `__main__.py` that doesn't exist; its literal argv would make **every** detached spawn fail instantly with stderr DEVNULL'd — a silent dead run. `python -m pflow.cli` is the package's documented module entry (`cli/__main__.py` → `cli_main`, same target as the `pflow` console script) and runs against the server's own interpreter. Chose this over adding a new `src/pflow/__main__.py` because `-m pflow.cli` reuses the existing intended entry — the smallest faithful fix, no second/duplicate module entry. Implements the plan's *intent* exactly.
2. **Existing POST tests needed a loopback `Host`.** Starlette's `TestClient` defaults to `base_url="http://testserver"` → `Host: testserver`, which the new guard 403s. Added a documented `_client()` helper (`base_url="http://127.0.0.1"`) in `test_ui_interaction_server.py` and routed all `TestClient(...)` through it. This is the plan's intended consequence ("the guard also rejects the existing POSTs") — the real CLI/browser always send a loopback Host, so the helper is the faithful default.
3. **`inputs` values must be strings — rejected (400), not coerced.** The plan offered "coerce/round-trip via `str` if needed"; I chose strict rejection. The frontend (channel A) always sends token strings, so rejection is invisible to the real client and gives agents an unambiguous contract; silent coercion of e.g. `True`→`"True"` (not `"true"`) would surprise. Within the plan's stated latitude.

### Tests added (`tests/test_cli/test_ui_interaction_server.py`)

`TestRunEndpoint`: detached-argv shape (`-m pflow.cli`, DEVNULL stdio, `start_new_session=True`, 200); declared inputs become one injection-safe argv token each (value with space + `;` stays one element); 404 unknown workflow (no spawn); 400 malformed body × 3 (missing workflow / non-object inputs / non-string value); 400 + diagnostics on a missing required input via the off-loop pre-flight (no spawn). `TestHostGuard`: non-loopback Host → 403 (no spawn); `127.0.0.1:port`/`localhost:port`/`[::1]:port` all pass; the guard also 403s `command`/`interaction`/`visibility`. (IPv6 `::1` is tested via a per-request `Host` header override — Starlette's TestClient transport crashes on an IPv6 `base_url`, a TestClient bug, not ours.)

### Real end-to-end verification (Popen is mocked in unit tests — this proves the actual spawn)

Started a real `pflow ui` server, `curl POST /api/run` (loopback) → `200 {"status":"spawned"}`; the detached run **actually executed** and wrote a trace with `meta.inputs: {"name":"Phase2"}` and `run.complete final_status: success`. `Host: evil.com` → `403`. This is the faithfulness proof (the spawned run's `meta.inputs` matches the POST) AND confirms the `-m pflow.cli` fix and the guard against a real server.

### Gates (vs baseline 8232)

- `make test`: **8246 passed**, 0 failed (8238 + 8 new Phase-2 tests).
- `make check`: ruff + ruff-format + mypy (239 files) + deptry all clean.

**No loose ends. Phase 2 is complete and verified (unit + real-server end-to-end + security).**

---

## Phase 3 — Frontend: ▶ Rail button → Run side-panel + form + launch

**Status:** ✅ complete — awaiting review

### Changes made

1. **Schema flag (renderer seam, input-only).** `react_flow.py` — new `_io(node)` helper attaches
   `sensitive = is_sensitive_parameter(node.id.node_id)` to `kind=="input"` nodes' `io` ONLY (NOT the
   `IOPort` dataclass — `asdict` would leak it onto outputs). Mirrored `sensitive?: boolean` (optional) in
   the TS `IOPort`. **Regenerated the 3 contract fixtures** (`deep-research`/`run-cycle`/
   `prompt-caching-multi-chunk` carry inputs; `conditional-branching` has none → unchanged).
2. **`web/src/utils/controlForType.ts`** (NEW, + test) — the pure 7-case `data_type → control` map
   (number/integer→number, boolean→checkbox, object/array→textarea, else→text). *Deviation: placed in
   `utils/` not the plan's `util/` — the repo dir is `utils/`; the plan had a typo.*
3. **`web/src/graph/io.ts`** — `inputFields(graph)` + `InputField` type (NEW, + tests): enumerates
   TOP-LEVEL `kind=="input"` nodes (empty `ancestor_path`), reading `sensitive` straight off raw `io`
   (NOT `wrapperPorts`, which drops it). Re-exported via the `flow.ts` façade.
4. **`web/src/components/RunForm.tsx`** (NEW, + test) — the reusable controlled seam: one control per
   input via `controlForType`, required markers, prefill display, the sensitive "from settings/env" hint,
   the no-input "▶ Run" confirm, inline 400 errors, submit-disabled-while-in-flight. Channel-A token
   strings throughout.
5. **`web/src/components/RunPanel.tsx`** (NEW) — the `.read-panel`-shell chrome: builds `InputField[]`,
   owns `values`/`submitting`/`errors`, prefills defaults (`defaultToken` — sensitive stays blank), omits
   blank fields on submit (faithful to "don't pass the arg"), calls `runWorkflow`, `onLaunched` on success.
6. **`web/src/api/client.ts`** — `runWorkflow(workflow, inputs)` (+ tests): typed-ApiError POST `/api/run`,
   `application/json` header, surfaces 400 diagnostics via `ApiError.errors`.
7. **`web/src/components/Rail.tsx`** — ▶ `RailButton` at the rail BOTTOM (new `onRun`/`runPanelOpen` props,
   `showPlay` gate); separator above it; added to the null-return guard.
8. **`web/src/views/GraphView.tsx`** — `runPanelOpen` state (outside `selectedId`); `toggleRunPanel` +
   `onRunLaunched` (= `selectRun(null)` follow-newest + close); `onRun={graph ? toggleRunPanel : undefined}`
   to Rail; renders `RunPanel` (+ shares the right-panel resizer) when `runPanelOpen && graph`.
9. **`web/src/index.css`** — `.run-form`/`.run-field`/`.run-submit` etc. (`.run-panel` rides `.read-panel`'s
   scoped chrome tokens, so no new chrome-scope entry needed).

### Decisions / deviations (with rationale)

- **`controlForType` lives in `utils/` not `util/`** — the plan's path was a typo; the repo dir is `utils/`.
- **`inputFields` lives in `graph/io.ts` (pure), not inlined in the component** — IO enumeration is a pure
  contract transform; co-locating it with `wrapperPorts`/`ioOwners` keeps the single-copy locality and makes
  it node-env testable. The plan named `wrapperPorts` only as a *reference* (it drops `sensitive`).
- **The Phase-5 "load inputs from" picker (`loadFrom`) is deliberately NOT built here.** The plan assigns the
  picker to Phase 5 ("the picker (Phase 5)"); adding an unused `loadFrom` prop now would be dead scaffolding
  (fails the simplicity bar). RunForm's controlled surface is exactly the seam Phase 5 extends — the picker
  adds a prefill *source*, not new form mechanics. **Not a skipped step** — it's a different phase.
- **RunPanel reuses `PanelHeader`** (input glyph + `IO_COLOR`, eyebrow "run workflow", no `onNavigate`) — the
  run form is about inputs; reusing the existing chrome is the smallest faithful choice (no new header).
- **At most ONE right-side panel — the Run panel REPLACES the selection panel while open** (render-level
  ternary; `selectedId` preserved underneath, so closing ▶ returns to the selection). *Found in self-review:*
  an earlier draft rendered RunPanel AND a selection panel as two sibling `.read-panel`s — but they are
  `flex: 0 0 var(--panel-w)` no-shrink, and `usePanelPair` only budgets the source pane against ONE right
  panel, so source + 2 right panels would crush the canvas (the exact class the reclamp exists to prevent).
  The single-slot model fixes the crush AND reads cleaner; still "outside the `selectedId` model" (the boolean
  is independent — it just shares the one right slot in render, doesn't touch `selectedId`).
- **Submit OMITS blank fields** (not `name=`) so they resolve via the CLI's normal precedence — faithful to a
  hand-typed run that simply doesn't pass the arg. Required-ness is enforced by the Phase-2 pre-flight (a
  blank required field → 400 with an actionable diagnostic shown inline), NOT hard-blocked in the form.
- **Known minor limitation (noted, not fixed):** a live-source edit that ADDS an input while the Run panel is
  open won't show the new field until the panel is reopened (`values` is initialized once at mount).
  Rare-case; a sync effect would add complexity for a theorized need — reopening fixes it.

### Faithfulness (verification #4)

Holds *by construction* (channel A): the form sends `{topic: "cats"}` → the server builds the `topic=cats`
argv token → spawns the identical CLI the user would hand-type. Pinned by the client test (the POST body)
and the GraphView test (`runWorkflow("demo", { topic: "cats" })`).

### Tests added

- `utils/controlForType.test.ts` — every canonical type + null/Python-alias fallback.
- `graph/io.test.ts` — `inputFields` field mapping, sub-workflow exclusion, missing-`sensitive`→false.
- `api/client.test.ts` — `runWorkflow` POST shape/header, 400-with-diagnostics, 404.
- `components/RunForm.test.tsx` — control mapping, prefill, required marker, sensitive hint, no-input confirm,
  checkbox token emission, submit/disabled contract, inline 400 errors.
- `views/GraphView.test.tsx` — ▶ toggles the panel; the Run panel REPLACES a selection panel and restores it
  on close (one right panel); **submit spawns ONLY the filled+non-sensitive inputs** — a sensitive input stays
  BLANK in the DOM despite an authored default (secrets boundary) and a blank required input is OMITTED, not
  sent as `name=''` (faithfulness), then follows-newest (un-pins `?run=`) + closes; a spawn failure shows
  diagnostics inline without blanking the canvas.
- `tests/test_core/test_graph_react_flow_renderer.py` — `sensitive` on inputs (True/False by name), NEVER on
  outputs; updated the sub-workflow-input `io` assertion to include `sensitive`.

### Real-browser verification (mandatory loop — `make ui-build` + restart `pflow ui`)

All via the `screenshot-pflow-web-ui` skill + a custom `launch-and-watch.pflow.md` (one MCP session:
navigate → settle → click ▶ → click ▶ Run → poll for the run):

1. ▶ renders at the rail BOTTOM, distinct from the clock/RunSelector at the top (screenshot).
2. ▶ on `examples/core/template-variables.pflow.md` → form generated: required `*` markers, prefilled
   defaults (`utf-8`/`./backups`/`./output`/`unknown`), `api_token` blank + the "from settings/env" hint,
   descriptions as helper text — canvas NOT blanked (screenshot).
3. No-input workflow → "This workflow takes no inputs." + the "▶ Run" confirm (screenshot).
4. **End-to-end:** submit → real detached spawn → overlay lit `run status: success` + banner "Run success ·
   1 nodes" + panel auto-closed on success (`{badge, banner, panelClosedOnSuccess:true}` + screenshot).

### Gates (vs baseline 8232)

- `make test`: **8247 passed**, 0 failed (8246 + 1 new renderer test; the modified renderer assertion is the
  same test). `make check`: ruff + ruff-format + mypy (239 files) + deptry all clean.
- Frontend: `npx vitest run` **641 passed** (49 files); `make ui-build` (tsc strict + vite) clean.

### Self-review pass (post-implementation)

Re-scrutinized the diff for loose ends. Found + fixed ONE real bug — the double-right-panel canvas crush
(above). Confirmed NON-issues: stale-value leak on reload (removed inputs are ignored — submit iterates the
fresh `inputs`, only an ADDED input needs a reopen); ▶ correctly hidden in loading/error states (`graph` null
→ `onRun` undefined, and the rail isn't rendered in the error early-return); sensitive defaults aren't a new
exposure (`/api/graph` has shipped authored `io.default` inline since Task 168 — the form just never PREFILLS
a sensitive field); submit-disable guards both click and Enter. Re-verified the form renders correctly after
the panel restructure (advanced-mode browser screenshot).

### Test-fidelity pass (passing the RIGHT thing)

Stepped back and audited every test for "passing the right thing," not coverage. Found ONE high-value gap and
fixed it; found NO shallow tests to remove.

- **Gap fixed (highest value):** the submit test only covered a non-sensitive prefilled input, so the two most
  consequential behaviors were unexercised — (1) `defaultToken` blanking a SENSITIVE field even when it has an
  authored default (a regression would push a secret's default into the browser + onto the spawn), and (2) the
  omit-blank submit filter (a regression to `name=''` would diverge from a hand-typed run — the faithfulness
  guarantee). Strengthened the existing submit test with a 3-input graph (defaulted / required-blank /
  sensitive-with-default) asserting the secret field is blank in the DOM and the spawn payload is `{topic:cats}`
  only. Folded into the existing test (no near-duplicate).
- **Audited, kept (not shallow):** `controlForType` (full canonical-type contract of a pure fn), `inputFields`
  sub-workflow-exclusion + reads-`sensitive`-off-raw-`io` (the load-bearing wrapperPorts-drops-it guard), the
  checkbox→`"true"`/`"false"` channel-A pin, the renderer inputs-only/never-outputs `sensitive` guard. Each
  fails on a real regression.
- **Deliberately NOT added:** a TS test loading a committed fixture to pin the Python↔TS `sensitive` wire-key
  name — `inputFields`'s resilient `?? false` makes any such unit assertion pass even on a rename (it would be
  a shallow test). That seam is instead pinned by the Python renderer test + the committed-fixture drift guard
  + the REAL browser check (the `api_token` field actually showed the "from settings/env" hint — the true
  cross-boundary proof the key name matches).

**No loose ends. Phase 3 is complete and verified (unit + tsc + real-browser end-to-end launch + two
self-review passes: correctness + test-fidelity).**

---

## Phase 3 — Run-progress callout (post-review UX iteration)

After clicking through the live UI, the user iterated the run experience over several rounds. Net result:
clicking ▶ launches the run, the side form hands off to a **canvas callout** that streams live per-node
progress. (Consolidated from the round-by-round entries.)

### What shipped
- **"Inputs" heading** on the form (shown only when inputs exist; the no-input case keeps the "▶ Run" confirm).
- **`NodeCallout`** (`components/NodeCallout.tsx`) — a REUSABLE flow-space callout anchored to a canvas node
  (`ViewportPortal` → pans/zooms like a node; NOT a store node, so the contract-driven ELK pass stays pure).
  Placed perpendicular to the spine (TD→left, LR→above); frames the camera ONCE on open via `setCenter` at a
  fixed modest zoom. Content-agnostic — Run drops `RunProgress` in; **Task 174's agent-"say" bubble is the
  second consumer** (the two-consumer bar that justified building it). Chosen over a side-panel progress view
  to match the spatial model and turn the abrupt panel-close into a deliberate handoff (form = input → callout
  = live output).
- **`RunProgress`** + `runSteps`/`ProgressStep` (`graph/focus.ts`, pure) — a MINIATURE of the canvas spine,
  fed by the SAME `runStatus` map the badges use (no new observation; server stays a pure observer). Top-level
  steps render as small HOLLOW tiles (colored ring + opaque interior — the canvas node look minus the icon)
  joined by continuous gradient connectors that run BEHIND the tiles; each tile is grey while pending and wears
  its node's identity color once run (via `nodeColor` — shell green / code amber / transform cyan), and the
  RUNNING tile pulses a full-color inner core. One compact line per step (`name … ms`); batch `×N` from the
  contract.
- **Interactive callout:** the ✕ dismisses it, and each step **name is a button** that scrolls to + selects
  that node on the canvas (reuses GraphView's `onNavigate` — focus + camera follow + ReadPanel). Two-part fix
  for the RF `ViewportPortal`: (1) **`pointer-events: auto`** on the callout — RF sets the viewport to
  `pointer-events: none` and re-enables per node, so a portal child inherits `none` and clicks fell THROUGH to
  the pane (the real bug — a `dispatchEvent` test missed it by bypassing hit-testing; `document.elementFromPoint`
  is the honest probe); (2) **`nopan nodrag nowheel`** so the pan-drag doesn't fire and the body scrolls
  without zooming. Verified both buttons are `reachable` via `elementFromPoint`.
- **Pin a past run → the callout reappears** showing that run. Selecting a SPECIFIC run from the RunSelector
  (clock) OR loading a `?run=` deep-link now opens the same callout, anchored at the Inputs card, showing the
  pinned run's replayed per-node states + outcome (the re-subscribe repopulates `runStatus` from the run's
  snapshot). `setRunCalloutOpen(next !== null)` in `selectRun` (pin opens, "Live — follow newest" closes); the
  deep-link seeds `runCalloutOpen` from `?run=` at mount. The launch flow is unaffected because `onRunLaunched`
  forces it open AFTER its `selectRun(null)` (last setState in the batch wins).
- **Total run time + run id on the callout.** Bottom-right total (the run's wall-clock) + the run id in the
  header (between "RUN" and ✕, shortened, full UUID on hover). Both via the run.complete trailer: `duration_ms`
  was already written by the producer (`_aggregates`), and I added `execution_id` to it; both are now in the
  SSE allowlist (`_RUN_COMPLETE_FIELDS`) + the TS `RunComplete`. So the run id shows even for a LIVE launch
  (follow-newest, `runId` null) — it surfaces from the banner's `execution_id` on completion — as well as for
  a pinned/deep-link run (immediately, from `runId`). NodeCallout gained a content-agnostic `subtitle` header
  slot (Task 174 reuse). Browser-verified on a fresh launch: header `b303a7e1`, total `2.5s`. (`duration_ms`
  is genuine wall-clock from the trailer, NOT a sum of step times.)
- **Deep-link camera fix (the real subtlety):** a `?run=` load opens the callout AND mounts the graph in the
  same commit, where the camera hook's whole-graph `fitView` (the PARENT effect) runs AFTER the callout's
  `setCenter` (a CHILD effect) — so the whole-graph fit won and the box rendered tiny (`scale 0.42`). An rAF
  defer didn't fix it (the `framedRef` one-shot + cleanup cancels the deferred call on a beautiful-mode
  re-measure). Clean fix = single camera authority: `useCameraNavigation` gains `suppressInitialFit` (GraphView
  passes it for a `?run=` load with an anchor) and SKIPS its one initial whole-graph fit — one-shot via a ref,
  so a later direction flip still re-fits, and an explicit `?node=` still wins. Now the callout frames
  uncontested at `zoom 1.1`. Pinned by hook tests (suppress skips / default fits / one-shot / `?node=` wins);
  browser-verified both paths (`scale 1.1`, readable box) — RunSelector pick AND `?run=` deep-link.

### Bugs found + fixed during iteration (load-bearing)
- **Edges blink invisible mid-run** (pre-existing Task-173 interaction; reproduced `[5,5,0,5,0,5,5,5]`): the
  decoration effect re-ran on every `runStatus` tick and called `setEdges(new array)`, but `applyStatus` only
  restyles NODES — re-rendering all edges raced the node re-measure. Fix: edges depend only on `(laid, focus)`,
  so SKIP `setEdges` on a status-only re-decoration (`paintedFocusRef` in `useWorkflowGraph`). Smoother for ALL
  runs now, not just UI-launched ones.
- **Camera yanked on select/deselect:** the callout's camera frame was a reactive effect; a beautiful-mode
  re-layout flipped its `ready` flag and re-fired it. Fix: strict one-shot per open (`framedRef`) — position
  stays reactive, the MOVE doesn't.
- **Callout flicker / connector gaps / bleed-through:** cache the last good anchor rect (no unmount on a
  transient re-measure); connectors are ONE continuous gradient line tucked behind OPAQUE tile interiors
  (`var(--bg-raised)`), so they show only in the gaps and read centered.
- **Prior run flashes on re-run:** when ALREADY following-newest, `selectRun(null)` is a no-op so its
  synchronous run-state clear never fired — the callout opened on the LAST completed run until the new run's
  events arrived. Fix: `onRunLaunched` clears `runStatus`/banner itself (the follow-newest connection then
  repopulates from the new run). Pinned by a test (completed badge+banner → launch → both cleared) and a
  browser probe (post-re-run samples are `Running…`, never the old `Run success`).

### Deferred (flagged to the user)
- **Live batch `k/N` counter:** not available from overlay data — per-item progress is buffered in
  `shared["_batch_trace"]` and the host writes ONE trace event at completion (the CLI's live counter is a
  callback never written to the trace the overlay tails). Would need new streamed batch-progress plumbing
  (producer → tailer `_run_event` allowlist → SSE → frontend). Static `×N` shipped.
- **Connector-flare shapes** (the canvas `Connector` cove): tuned for 56px node tiles — won't read at the 11px
  mini-tiles and fights the compaction. Left the clean line-into-tile.

### Gates
- Frontend **654 vitest** (50 files) + tsc strict + `make ui-build` clean. `runSteps`/`RunProgress` tests cover
  the role facts, grey→identity coloring, the running-core, `×N`, and the outcome; `NodeCallout`'s
  positioning/camera are browser-verified (jsdom has no real flow-space layout). Python untouched — stays
  **8247** / `make check` green.
- Real-browser loop verified end-to-end: ▶ → form → submit → form closes, camera frames the callout, the spine
  streams grey→color with cross-color gradient connectors → "Run success · N nodes".

### Overall-run-status badge on the callout (user request)

The callout's outcome line lacked the round node-style status badge. Added the **overall run-status badge**
(the SAME `StatusBadge` nodes carry at top-right, reused via its existing `inline` variant — pixel-consistent,
no duplication) at the **lower-left** of the callout, beside the outcome word: a blue spinner while running →
green ✓ on success → red ! on failure. `final_status` has no `NodeStatus` for "degraded" → mapped to the amber
"stopped" badge (the outcome TEXT carries the exact word). `RunProgress.tsx` (unified the running/done outcome
line so the badge shows in both states) + `.run-progress-outcome-label`/badge-size CSS. Tested (badge status
class by run outcome incl. degraded→stopped); browser-verified both states (spinner + ✓, matching the canvas
node badge). Frontend **660 vitest** + tsc + `make ui-build` clean.
