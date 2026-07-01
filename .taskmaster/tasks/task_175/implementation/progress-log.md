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

---

## Phase 3 — Deep-review pass + fixes (post-commit)

A scoped 3-agent `/deep-review` on the Phase-3 commit (`36587a26`): feature-interactions + effect-timing +
simplicity. **Effect-timing: 0 findings** (traced the `framedRef` one-shot, `setCenter`-vs-`fitView` order,
`paintedFocusRef` skip-setEdges, `onRunLaunched` batching, and the Python loop-only-mutation + snapshot/
broadcast parity for the new `execution_id`/`duration_ms` trailer fields — all clean). **Feature-interactions:
1 confirmed bug** + 2 minor desyncs. **Simplicity: 0 correctness, a few quality nits.**

### Fixed
1. **BUG (confirmed) — `RunProgress` spun a fake "Running…" forever on a no-banner terminal run.** The callout
   is a SECOND consumer of run-lifecycle state but was passed only `steps`+`banner`; `runStopped` (process
   killed mid-flight) and `runNotFound` (stale `?run=` — and the callout DEFAULTS open on a deep-link) never
   set `runBanner`, so its outcome line showed a spinner + "Running…" while the canvas banner correctly said
   "stopped"/"not found". Display-only but never self-corrected (most misleading on a stale bookmark: a fake
   in-progress run). Same class as the earlier panel-crush — a new overlay consumer wired to only some signals.
   Fix: a `RunOutcome` (`"stopped"|"not-found"|null`) prop, resolved in GraphView
   (`runMissing ? "not-found" : runStopped ? "stopped" : null`), so the badge + outcome word + class resolve.
   Pinned by a new `RunProgress.test.tsx` case (stopped/not-found render the right text/badge/class; live
   still spins). Self-review caught a follow-on: `run-stopped` is a NEW class value on `.run-progress-outcome`
   (the outcome line previously only got `final_status` classes), which had no CSS rule → added an amber
   `.run-progress-outcome.run-stopped` (mirrors `.run-degraded`); not-found maps to the already-styled `run-failed`.
2. **Nit (confirmed) — duplicated "top-level executable step" predicate** in `focus.ts:runSteps` and
   GraphView's `runAnchorId` fallback → one `topLevelSteps(graph)` helper in `focus.ts`, both consume it.
3. **Nit — TS↔CSS color dual-source:** `RunProgress`'s `#ff6b6b`/`#d29922` literals → `var(--danger)`/
   `var(--status-stopped)` (both `:root`, verified — so they resolve inside the canvas portal; single source).

### Deferred (with reason — not handwaving)
- **`resetRunOverlay()` extraction** (the 5-setter overlay clear, copy-pasted 3× in GraphView; this commit
   added the 3rd): real cleanup, but a 3-site refactor of `GraphView.tsx` WHILE the Phase-4 agent edits the
   same file is needless conflict risk for a pure-cosmetic dedup. Do once Phase 4 lands.
- **Stale-run mini-spine node labels** (callout "pending" vs canvas "unrecorded" for version-drifted nodes):
   non-blocking cosmetic; the run still renders honestly + the canvas stale banner is up. Fixing needs
   `runSteps` to take `markUnmatched` (signature widening) for a tile-label nuance — not worth it now. Noted.
- **✕-closed callout un-reopenable for the *currently-pinned* run** (the `next===runId` re-pick guard returns
   before `setRunCalloutOpen`): minor UX papercut, no wrong data. Noted.
- **Browser screenshot of the stopped/not-found outcome:** deferred to avoid a `make ui-build` + `pflow ui`
   server restart racing the Phase-4 agent's own browser checks on the shared port; the fix is a small,
   fully-unit-tested rendering change (not an overlay-pipeline change that hides from unit tests). One-line
   re-check on a stable tree: open `?run=<bogus-id>` → the callout shows "Run not found", not "Running…".

### Gates
- Frontend: `tsc` clean; `npx vitest run` **665 passed** (49→50 files, incl. the new outcome test + Phase-4's
   landed tests); `make ui-build` clean. Python untouched this round (the fix is frontend-only).

### Coordination (parallel Phase-4 agent)
Stayed in the Phase-3 lane (`RunProgress.tsx`/`focus.ts` + 2 surgical `GraphView.tsx` edits: the import and
the `runAnchorId` fallback + the `RunProgress` `outcome` prop). Confirmed disjoint from Phase-4's IoPanel/
`hasRunContext` GraphView edits; combined tree `tsc`-clean + 665 green.

---

## Phase 4 — Inspect: click any IO node → "This run" value

**Status:** ✅ complete (code + tests + contract-level e2e) — interactive visual browser check DEFERRED (see below)

### Major deviation from plan (verified plan-vs-reality mismatch)

The plan targeted `ReadPanel`'s `showRunDetail` gate (`isIONode(selectedNode)`), assuming an individual
input/output node is selectable into `ReadPanel`. **It is not.** Verified chain (against current code):
clicking a root IO row → `selectPort()` → `setSelectedId(owner)` where `owner` is the **wrapper GROUP id**
(`GraphView.tsx:478-499`); `selectedNode` resolves from `graph.nodes`/a group `host`, and root IO wrappers
have **no host** → `selectedNode` is `null` (`:521-527`); so root IO selection opens **`IoPanel`**, never
`ReadPanel`. `selectedNode.kind === "input"/"output"` cannot occur. The plan's gate would never fire.

→ **The run-value display was moved to `IoPanel`** (per-port "this run" block), which is *also* the user's
mental model (click the input card). The **server** side is unchanged from the plan (panel-agnostic). User
confirmed the display treatment (CodeBlock block) via an AskUserQuestion mockup before I built the frontend.

### Server (`ui/run_node.py`) — exactly the plan's design

- `run_node_detail` branches on `ref.port`: `"in"`/`"out"` → `_io_detail`; else → existing event scan.
- `_io_detail`: **`ancestor_path` collision-guard FIRST** (sub-workflow IO → None, so a sub-workflow `url`
  can't borrow the top-level `url`); input → `meta.inputs[name]`, output → `json_output["result"][name]`;
  blob-resolve; synthesize an `isRunNodeDetail`-valid shape (`_io_shape`: `node_type` `"input"`/`"output"`,
  `status` `"recorded"`, null exec metrics). Absent (sub-wf / missing key / no `json_output`) → None.
- **Redaction correction (plan was literally wrong):** the plan said `_redact(meta.inputs[name])`, but
  `_redact` matches by KEY name — `_redact("secret")` of a bare scalar redacts nothing, so a sensitive-NAMED
  input's value wouldn't be redacted (contradicting the plan's own "secret-named input is redacted" test). I
  use `_redact({name: value})` so the **port name** is the matched key. Verified by a test.
- Refactored the file-read into shared `_read_trace_lines` + `_blob_map` + `_line_of_kind` (used by both the
  event scan and the IO projection) — RAW lines, never `load_trace_file` (strips the join keys).

### Frontend (retargeted to IoPanel)

- `types.ts` — `RunNodeDetail.duration_ms` → `number | null` (IO nodes have no duration).
- `ThisRunSection.tsx` — guard the `fmtDuration` call (the type relaxation FORCED this; `fmtDuration(null)`
  would print a bogus `"0ms"` since null coerces to 0). No other `ReadPanel` change — its gate is untouched.
- `IoPanel.tsx` — threads `workflow`/`runId`/`hasRunContext`; a per-port `PortRunValue` child (owns its
  fetch + catch, DR-6) calls `/api/run-node` with `portNode.ref`, renders the value via `CodeBlock` (text /
  JSON, scroll-capped) under a "this run" label, or "no recorded value" on 404/absent. Gated on
  `hasRunContext` so a cold interface shows no empty blocks.
- `GraphView.tsx` — `hasRunContext = runId !== null || runStatus.size > 0`, passed to `IoPanel`.
- `index.css` — `.io-port-run`/`-label`/`-empty` (reuses CodeBlock's `.read-param-value`; no new chrome).

### Tests

- `tests/test_cli/test_run_node.py` (+7): input→meta.inputs in an `isRunNodeDetail`-valid shape; secret-named
  input redacted (`<REDACTED>`); output→json_output.result; **sub-workflow collision guard returns None, not
  the top-level value**; missing input → None; output with no json_output → None; one handler (200) test.
- `web/src/components/IoPanel.test.tsx` (+4): no fetch / no block when no run context; per-input run values
  under "this run"; output value; "no recorded value" on reject. (Mirrors `ThisRunSection`'s mock of the
  `fetchRunNode` seam.)

### Verification

- **Server:** `make test` **8254** (8247 + 7), `make check` clean. On-disk shape proofs (earlier):
  `meta.inputs` + `run.complete.json_output.result` keyed by bare name.
- **Frontend:** `tsc --noEmit` 0, `vitest` **664** (660 + 4). IoPanel render path proven via mocked fetch.
- **Contract-level end-to-end (the link vitest mocks past):** a root input node's `ref` in real `/api/graph`
  payloads is `{node_id: "<name>", ancestor_path: [], port: "in"}` (outputs `"out"`) — matches the server
  projection's expectations exactly. So `IoPanel.portNode.ref` → `fetchRunNode` → `_io_detail` is proven at
  every seam without a live browser.
- **DEFERRED — interactive visual browser check** (the "click IO card → see the this-run block render"
  visual): deliberately NOT run yet, to avoid `make ui-build` + a live `pflow ui` session racing the parallel
  agent's in-flight `web/` edits (RunProgress/focus.ts review fixes). Every seam is otherwise verified, and
  the click→IoPanel selection path is pre-existing/unchanged. To run on a stable tree.

### Coordination note (parallel agent)

A second agent is fixing Phase-3 review bugs in the `RunProgress`/`focus.ts`/`NodeCallout`/overlay-reset
region. I stayed strictly in the Phase-4 lane and did NOT touch those. Our one shared file is
`GraphView.tsx`: my edits (`hasRunContext` at `:535`, the three `IoPanel` props at `:1014-1016`) are in a
region disjoint from their `runSteps`/`topLevelSteps`/reset work — confirmed coexisting + the combined tree
compiles (`tsc` 0) after their `topLevelSteps`-import edit landed.

---

## Phase 4.5 — Pin the launched run + pulsing-clock live affordance (post-review refinement)

**Why:** with concurrent launches now possible, the unpinned follow-newest overlay REVERTED to an older
still-live run when a newer (shorter) run finished — follow-newest prefers the newest *live* run, and when
the short run completes, "newest live" flips back to the long one. (Empirically confirmed: launched
sleep-30 + sleep-3; after sleep-3 finished, `discover_live_trace` returned the sleep-30.) User chose
**Option A: pin the launched run** + a **pulsing-blue clock** when any run is live.

### Option A — pin the run the ▶ launched (end-to-end run-id forcing)

The detached child mints its own `execution_id`, so the form couldn't know which run to pin. Fix: the
server mints the id, FORCES it onto the spawned run, and returns it; the browser pins via the existing
`?run=`/`selectRun` mechanism. The chain:
- `ui/server.py` — mint `run_id = uuid4()`, spawn with `env={**os.environ, "PFLOW_EXECUTION_ID": run_id}`,
  return `{"status": "spawned", "run_id": run_id}`.
- `cli/commands/run.py` — `os.environ.pop("PFLOW_EXECUTION_ID", None)` → `RunnerConfig.execution_id`. POP
  (not get) so a node that re-shells `pflow` can't inherit + collide.
- `execution/result.py` `RunnerConfig.execution_id` → `runner.py` → `WorkflowTraceCollector(execution_id=…)`
  → `self.execution_id = execution_id or str(uuid.uuid4())`. None on every other path → mint (unchanged).
- `api/client.ts` `runWorkflow` → returns the `run_id` (throws if a 200 omits it — the pin needs it).
- `RunPanel` `onLaunched(runId)` → `GraphView.onRunLaunched(runId)` = `selectRun(runId)` (a genuine switch →
  clears + opens the callout itself; the old follow-newest no-op workaround is gone) + close the form.
- `run_tailer.py` `_start_pinned` — **grace retry** (`_PINNED_RESOLVE_ATTEMPTS=24`, ~6s): a run pinned right
  after launch hasn't written its meta line yet (~1-2s subprocess startup); retry before run-not-found. A
  stale bookmark still surfaces run-not-found, just a few seconds later (rare, invisible).
- Pinned mode never re-discovers (`run():` pinned branch keeps `self._current`), so it CAN'T revert — the fix.

### Pulsing-clock live affordance

`RunSelector` now POLLS `/api/runs` (`_LIVE_POLL_MS=4000`, cached scan — cheap) instead of fetch-on-open;
`liveCount = runs.filter(r => r.live).length`. When > 0 the clock gets `.run-live-pulse` (a `pflow-clock-pulse`
keyframe oscillating the shared `--status-running` blue + a glow) and an "a run is live" aria-label. So a
live run — INCLUDING a long one still going after you pinned a newer one — is visible at a glance.

### Tests + verification

- Python: `test_ui_interaction_server.py` — response carries `run_id` + `env["PFLOW_EXECUTION_ID"]==run_id`.
  `make test` **8254**, `make check` green (fixed a RUF003 `×`→`*` in my comment).
- TS: `client.test.ts` — `runWorkflow` resolves the id + throws on a 200 missing it. `GraphView.test.tsx` —
  submit PINS (`?run=<id>`), not un-pin; the prior-run clear still holds (via the selectRun switch). Updated
  the mount mocks (runWorkflow→id, fetchRuns→[] for the new mount poll). `RunSelector.test.tsx` — polls on
  mount; pulses while live, not when idle. `tsc` 0, `vitest` **667**.
- Real end-to-end (curl): launch returns id → the run USES that id (trace `execution_id` match) →
  `/api/run-node?run=<id>` resolves it (the browser can pin). **Browser:** screenshot confirms the clock is
  BLUE+glow while a run is live (the running node badge confirms the overlay follows the live run) vs GREY
  when idle — the `run-live-pulse` treatment renders.

### Deviations / notes

- Forced id via **`RunnerConfig` threading** (explicit) rather than a global env read in the collector —
  no hidden global state, and `pop` prevents env propagation to grandchild `pflow` processes.
- The Phase-4 interactive VISUAL check (IoPanel "this run" values) is now confirmed too — the user verified
  it renders after the server restart, and this build/server is fresh.

---

## Phase 5 — Re-run: "load inputs from" picker

**Status:** ✅ complete — code + tests + server e2e + browser-confirmed picker render

### Server

- `ui/run_node.py` — new `read_run_inputs(workflow_key, run_id)`: reuses the Phase-4 shared helpers
  (`_resolve_trace`, `_read_trace_lines`, `_line_of_kind`), reads `meta.inputs`, **OMITS sensitive-named keys**
  (`is_sensitive_parameter` — a past run's resolved secret never reaches the browser), renders each remaining
  value via `format_param_value` (the channel-A inverse of `infer_type`). `None` (→404) when no trace/run;
  `{}` for a trace predating `meta.inputs`. `meta.inputs` is un-interned → no blob resolution needed.
- `ui/server.py` — `GET /api/run-inputs?workflow=X&run=<id>` handler (thin, mirrors `run_node`: sync/
  threadpooled, no hub state; 400 missing workflow, 404 unresolvable/no run) + route + docstring; `ui/CLAUDE.md`
  documents the endpoint.

### Frontend

- `api/client.ts` — `fetchRunInputs(workflow, runId)` (typed-ApiError GET, DR-6).
- `components/RunPanel.tsx` — the picker: fetches this workflow's runs once on open (`fetchRuns`, DR-6 catch),
  a `<select>` of **Defaults + past runs** (labelled `runMark().label · timeAgo()`, reusing the RunSelector's
  exported palette + the shared time helper). `loadFrom(source)`: Defaults → `defaultValues(inputs)`; a run →
  `fetchRunInputs` → each field takes the run's token if present, else blank (sensitive server-omitted → blank →
  re-resolves; a field added since the run → blank → resolves at run time). Picker gated on
  `inputs.length > 0 && runs.length > 0` (no picker for a no-input workflow or one with no history).
- `index.css` — `.run-loadfrom`/`-label`/`-select` (reuses the field-input tokens; no new chrome).

### Deviation from plan (with rationale)

- **Picker lives in `RunPanel`, not `RunForm`** (the plan described a `RunForm` `loadFrom` prop). Verified
  reason: `RunForm` is the pure controlled FIELD surface (`schema→values→submit→errors`); the prefill-SOURCE
  picker is value-provenance, which `RunPanel` owns (it holds `values`/`setValues` + now the run-list). Placing
  it in `RunPanel` keeps `RunForm` a pure renderer (no run-list/`fetchRunInputs` dependency, simpler tests) and
  matches the Phase-3 note that the picker adds "a prefill SOURCE… not new form mechanics." Cleaner FINAL code.
- **Clock/RunSelector per-row ↻ sugar SKIPPED** — the plan marks it explicitly optional; it adds cross-component
  wiring (RunSelector → open RunPanel pre-selected) for a case the in-panel picker already covers. Deferrable.

### Tests

- `tests/test_cli/test_run_node.py` (+8): `read_run_inputs` renders typed values→tokens (int→`"3"`, bool→
  `true`, list/dict→compact JSON), omits sensitive keys, `None` on unknown run, `{}` on a pre-`meta.inputs`
  trace; `/api/run-inputs` handler (400 missing workflow, 404 unknown workflow/run, 200 tokens-without-secrets).
- `web/src/api/client.test.ts` (+3): `fetchRunInputs` GET shape/params, 404 throws, non-object 200 throws.
- `web/src/components/RunPanel.test.tsx` (new, 4): picker shows once runs load (defaults prefilled, sensitive
  blank); loading a run prefills non-sensitive fields + leaves the sensitive one blank (server omits it);
  Defaults resets; no picker when a workflow has no past runs.

### Verification

- `make test` **8262** (8254 + 8), `make check` clean; `tsc` 0, `vitest` **674** (667 + 7).
- **Real-server e2e (curl):** a real run recorded `meta.inputs {"topic":"dogs","count":7,"api_key":"placeholder"}`;
  `GET /api/run-inputs` returned `{"topic":"dogs","count":"7"}` — `count` typed→token, **`api_key` OMITTED**
  though it had a value (sensitive); a bogus run → 404. Proves format + sensitive-omission end-to-end.
- **Real-browser (screenshot):** clicked ▶ on a workflow with 1 past run → the Run panel shows the
  "load inputs from" dropdown (Defaults) above the Inputs, fields prefilled from defaults, ▶ Run — the picker
  renders as designed.

### Coordination note

Built on the current tree (Phase 3 review fixes + Phase 4.5 landed). Phase 5 touches `run_node.py`/`server.py`
(server) + `client.ts`/`RunPanel.tsx`/`index.css` + the new `RunPanel.test.tsx` — no overlap with the other
agent's `RunProgress`/`focus.ts`/`NodeCallout` region. `tsc` 0 + full gates green on the combined tree.

---

## Deep-review (full branch) — 7-agent battery + fixes

Ran `/deep-review` on the full branch (all uncommitted changes vs main, Task 175 phases 1–5+4.5). Deployed 7
specialists (silent-failures, impact-completeness, concurrency, feature-interactions, agent-ux, simplicity,
test-fidelity). **Verdict: 0 Critical, 2 Warnings, ~8 Suggestions — ship after the confirmed fixes below.**
The load-bearing invariants were all *confirmed clean* by the agents: `Popen`(+`start_new_session`)-not-asyncio
spawn lifecycle with no retained handle, the async-POST/sync-GET hub split, the Host guard on every mutating
POST, `execution_id` threading (no positional-shift / no cross-spawn env race), `meta.inputs` additive-safety
across all trace readers, the batch/nested `ancestor_path` collision guard, and single-rule secret redact/omit.

### Fixed (all verified against code first)

- **W1 — stale "follows-newest" docs** (`ui/CLAUDE.md` `/api/run` section + `RunPanel.tsx:8` header). 3 agents
  converged. Phase-2 doc invalidated by Phase-4.5 pin-by-id → updated both to describe run_id-return + pinning.
- **W2 — 6s pinned-resolve grace window** (`run_tailer.py`) could expire on a cold child start (litellm import
  during compile) → overlay stuck "run not found". Widened to 15s (`_PINNED_RESOLVE_ATTEMPTS 24→60`) with a
  comment on the worst-case time-to-meta; noted a one-time re-arm as the more-robust future fix. Full design investigation (constraint, candidate fixes, open questions) spun out to GH #546.
- **S1 — `read_run_inputs` `format_param_value(None)`→`"None"`** prefill lossiness → drop None-valued keys
  (they re-resolve to default), + test.
- **S2 — `/api/run-inputs` 404 wording** conflated "no run" vs "no inputs" → names the missing run.
- **S3 — RunForm discarded the `suggestions` field** of pre-flight diagnostics → render it under the message
  (+ `ApiErrorEntry.suggestions` type, CSS, test).
- **S4 — missing `json_output`→`run.complete` ordering pin** (the output-port projection's data source) →
  added a `trace_files` CLI-json e2e test (real `pflow run --output-format json` → asserts
  `run.complete.json_output["result"]`), the output-side twin of the `meta.inputs` write-ordering pin.
- **S6 — text-or-JSON value render duplicated** 3× (IoPanel `PortRunValue` + ThisRunSection RunField/RunOutput)
  → extracted a shared `components/RunValue.tsx`.
- **S7 — `run_tailer._read_meta` cached the raw `meta.inputs`** (unused by any cache consumer) → drop it from
  the identity-probe meta to keep `_SCAN_CACHE` small, + test.

### Deferred (documented, not fixed)

- **S5 — run-outcome summary line** duplicated (GraphView Task-173 banner vs RunProgress callout): a Suggestion
  (drift risk, both correct today) that touches the pre-existing banner + the other agent's `RunProgress` — not
  worth a cross-agent edit for a cosmetic dedup. A shared `runSummaryText` helper is the future fold.
- **S8 — IoPanel "no recorded value"** conflates a transient fetch error with genuine absence: deliberate DR-6
  (each fetch owns its catch), acceptable over loopback.
- **S9 — `?run=` parsed twice / subtitle thrice** in `GraphView` (other agent's code): trivial.
- Pre-existing repo-wide ruff RUF059/RUF043 in `tests/test_nodes/test_claude/test_schema_coercion.py` +
  `test_trace_io.py:466` (unchanged vs main — a ruff-version artifact, outside `make check`'s changed-files
  scope): NOT this branch's regression, left alone.

### Gates (post-fix)

- `make test` **8265** (8262 + 3: S1/S4/S7), `make check` green (ruff + ruff-format + mypy + deptry — fixed 2
  `×`→ASCII in my new comments), `tsc` 0, `vitest` **675** (674 + 1: S3).

**Deep-review complete. No confirmed Critical or unaddressed Warning remains.**

### Post-fix loose-end (caught on a "fully happy?" re-check)

The W2 grace-window bump (24→60 attempts) surfaced a test-time regression: two run-not-found tests
(`test_run_tailer.py::test_pinned_run_not_found_broadcasts_and_stops`,
`test_ui.py::…test_ensure_tailer_replaces_a_terminated_tailer`) drive a ghost run_id to full window
exhaustion and waited the REAL production window — 14.8s each after the bump (already ~6s before). They
exercise the run-not-found PATH, not the timing, so both now `monkeypatch _PINNED_RESOLVE_ATTEMPTS → 2`
(~0.26s each). `make test` back to 17.45s (from 32.98s); still 8265, `make check` green. Also swept the whole
repo for stale "follows-newest"/"no run id returned" refs — none remain (the `RunPanel:51` / `server.py`
refs that mention follow-newest are correct: they explain *why* pinning exists).

### High-value test pass ("passing the RIGHT thing", not coverage)

Stepped back to hunt for a test that would catch a REAL bug (not padding). Found one genuine gap + one of my
own tests that was passing without asserting the thing that matters:

- **Re-run FAITHFULNESS round-trip (the feature's core promise).** `test_read_run_inputs_renders_typed_values_
  to_tokens` pinned only the FORWARD leg (value→token) — it never proved the tokens re-type back. The round-
  trip WAS pinned, but only in `test_rerun_display.py` (the ORPHANED `rerun_display` module, slated for
  deletion) and via the `shlex` shell path — NOT the live Phase-5 path (server builds `name=value` argv
  directly, no shell). Strengthened the test (renamed `…_tokens_round_trip_faithfully_through_the_cli_parser`)
  to also assert `parse_workflow_params(server-argv-form(tokens)) == original` through the REAL CLI parser.
  **Mutation-verified non-vacuous:** under a simulated `infer_type` JSON-parse regression the forward assertion
  still passes but the round-trip FAILS — so it catches an `infer_type` break the forward-only test missed, on
  the live path, durable against the dead-module deletion. (Deliberately excludes a numeric-looking STRING:
  `meta.inputs` stores the RESOLVED value and declared-type coercion — not `parse_workflow_params` alone —
  restores it; that channel-A interplay is a separate pre-existing CLI concern, not this test's subject.)
- The earlier S4 (json_output→run.complete ordering, real CLI-json e2e) was the other genuine gap — already
  closed.

Audited the rest of the Task-175 suite for shallowness (mine + the test-fidelity agent's pass): the secret
non-leakage pins (endpoint returns tokens WITHOUT secrets; IO projection redacts), the exact-spawn-argv +
injection-safety pins, the ancestor_path collision guard, and the meta.inputs write-ordering pin each
discriminate a real regression. **Nothing shallow to remove.** `make test` 8265, `make check` green.

---

## Phase 6 — Agent: open/replay a specific run

**Status:** ✅ complete — code + tests + real-browser switch verification. FINAL phase of Task 175.

### Design decision (user-chosen, deviates from plan)

The plan had TWO CLI commands (`--run` opens; a separate `select-run` subcommand switches). The user chose
**one smart command**: `pflow ui <wf> --run <id>` switches an already-open Viewer if one is live, else opens a
fresh pinned tab. Rationale: the agent rarely knows if a tab is open, so "show run X" should just work + never
spawn a duplicate. The `select-run` VERB is still built at the server+frontend layer (it's the switch
mechanism `--run` drives); there is NO separate `pflow ui select-run` CLI subcommand.

### Changes (verify-first — every seam re-read against post-4.5 code)

- **Server** (`ui/server.py` `command()`): added `select-run` to the verb whitelist; a PASS-THROUGH branch
  placed AFTER `target` is read (the run id rides in `target`) and BEFORE `resolve_validate_build` — broadcasts
  `{type:"select-run", run: target}` with no graph resolution (a stale id → the frontend's run-not-found, never
  a server error).
- **CLI** (`cli/commands/ui.py`): `_serve_url` gained a `run` param (`?run=<id>`); `serve_cmd` gained `--run`
  + the smart branch — in the reuse path, if `_probe_health(port, wf).windows > 0` it POSTs `select-run` (switch,
  no duplicate tab), else opens a pinned tab; the fresh-start path always opens pinned (no live Viewer to
  switch). An early guard: `--run` without a workflow → actionable error.
- **Frontend**: `events.ts` — `PointHandlers.selectRun` + a `select-run` dispatch arm (`{type:"select-run",
  run}`, string-guarded). `GraphView.tsx` — `pointHandlers.current.selectRun` → the existing `selectRun` (its
  `if (next === runId) return` guard + `?run=` sync), routed through the ref like focus/frame/clear (no new
  subscribe-effect deps). Fixed 3 existing test-handler objects that construct `PointHandlers` (new required member).
- **Docs**: `guide/features/ui.md` (the `--run` smart open-or-switch shortcut; no `select-run` subcommand
  surfaced to the agent), `ui/CLAUDE.md` (the grown verb set + corrected the stale "defines no run/trace event
  schema" claim Task 173 invalidated), `web/CLAUDE.md` (the overlay-seam verb list + the pointHandlers-ref rule).

### Tests

- `test_ui_interaction_server.py` (+3): `command` broadcasts `select-run` pass-through (`{type,run}`, no target
  resolution); requires a target; an unknown verb (`teleport`) still 400s (whitelist intact).
- `test_ui_commands.py` (+5): `_serve_url` pins `?run=`; fresh start opens pinned; **reuse+live Viewer → POSTs
  select-run (no browser open)**; reuse+no Viewer → opens pinned (no POST); `--run` sans workflow → exit 1.
- `events.test.ts` (+1): a `select-run` SSE message calls `handlers.selectRun(run)`, ignoring a missing/non-string run.

### Verification

- `make test` **8273** (8265 + 8), `make check` clean, `tsc` 0, `vitest` **676** (675 + 1).
- **Real-browser switch (the new end-to-end the sub-parts couldn't prove together)**: opened a Viewer pinned to
  run A, fired a same-origin `select-run` for run B (via the real POST /api/command), and confirmed the open
  Viewer re-pinned live — `{before: A, posted_sent_to: 1, after: B, switched: true}`, URL navigated to
  `?run=B`. Proves broadcast → EventSource → events.ts dispatch → selectRun → syncUrl end-to-end. (The `--run`
  OPEN path is the `?run=` deep-link already browser-proven in Phase 3.5/4.5 + the CLI URL unit test.)

**Task 175 (phases 1–6) is complete: launch ▶, inspect (click any node), re-run picker, and the agent
open/replay-a-run verb — all implemented, deep-reviewed, hardened, and green.**

---

## PR opened

Task 175 (phases 1–6 + deep-review fixes + task-review) committed and pushed to `feat/web-ui-workflows`.
PR: https://github.com/spinje/pflow/pull/547 (base `main`, 64 files, +5071/−173). Gates green:
`make test` 8273, `make check` clean, `tsc` 0, `vitest` 676. Taskmaster-tracked (no GH issue).

---

## Post-PR review + hardening (2026-07-01)

A fresh review of the merged-into-branch implementation (verified against the real diff, not the
task-review's account) surfaced one worth-acting-on finding + two edges already tracked, then fixed the finding.

### Finding #1 (FIXED, commit `456c6d1b`) — DNS-rebinding reached the READ endpoints; the security comment overclaimed
- **Gap**: the Host guard was a per-POST call inside `_json_body`, so it covered only mutating POSTs. A
  DNS-rebinding attacker (who defeats the no-CORS "can't read response" defense) could still `GET
  /api/source` (raw `.pflow.md`, may hold hardcoded tokens), `/api/graph`, `/api/run-node`,
  `/api/run-inputs`. The rewritten comment claimed DNS rebinding "CLOSED" — true only for *mutation*.
- **Root fix (simpler, not more machinery)**: replace the per-POST call with a global **`_LoopbackOnly`
  ASGI middleware** on EVERY route → makes loopback-Host a property of the *server* (what rebinding
  attacks), covers reads + every future endpoint by default, and **deletes** the "must route through
  `_json_body`" invariant. `_json_body` now does content-type/JSON only. Net: fewer moving parts.
- **Load-bearing detail**: **pure-ASGI, NOT `BaseHTTPMiddleware`** — the latter breaks the long-lived
  `/api/events` SSE stream; pure-ASGI either 403s early or delegates `send`/`receive` untouched.
- **Deliberately dropped as premature**: a configurable `--allow-host` escape hatch (for remote-dev
  tunnels with custom Hosts) — no users, theorized need; trivial + reversible to add if one ever appears.
- Applied one review Suggestion: case-insensitive host match (`hostname.lower()` — host names are
  case-insensitive per spec); skipped two (tighten `!=403`; a dedicated pure-ASGI pin — the raw-ASGI
  disconnect test already streams frames *through* the middleware and would fail a `BaseHTTPMiddleware` swap).

### Tests (the churn closing reads forced)
- Guarding reads means the bare-`TestClient` GET tests (default `Host: testserver`) now 403, so
  `test_ui.py` + `test_run_node.py` route through a loopback `_local()` helper (~43 sed'd call sites — the
  `raise_server_exceptions=False` arg survives via `*args`/`**kwargs`); the raw-ASGI SSE scope gained a
  loopback `host` header; **new** `test_guard_also_covers_read_endpoints` pins the read coverage; the
  loopback matrix gained a `LOCALHOST` case for the case-insensitivity fix.

### Deep-review (2 fitting agents, code mode on the working-tree diff)
- `review-concurrency-safety` + `review-test-fidelity`: **0 Critical / 0 Warning**, verified by reading
  Starlette 0.47.3 source (SSE non-interference, `add_middleware` wiring, `request.app.state.hub` still
  resolves, fail-closed host parse) and by *mutation-testing* the guard test (fails in both directions).

### Verification (manual, at the live seam — the review's core concern)
- Ran a real `pflow ui` + curl: a spawned run (`POST /api/run` → `{status:spawned, run_id}`) lit the pinned
  overlay with the full lifecycle `connected → run-snapshot → run-events/run-event → run-complete`
  **through the middleware** (proves it's transparent to SSE); non-loopback `Host` → 403 on reads, writes,
  SSE, and `/api/health`; Host parse correct for `127.0.0.1:p` / `localhost:p` / `[::1]:p` / bare `::1`;
  the pre-flight returned an actionable 400 on a malformed workflow. `make test` **8274**, `make check` clean.

### Other findings — decided NOT to code
- **Cold-start pinned-resolve race** (a launch dying before its meta line, or a >15s cold start, strands
  the overlay on "run not found") — already tracked as **GH #546** (design + one-time-re-arm fix noted).
- **#4** (a *required boolean with no default* renders as unchecked = "unset" → pre-flight 400) and **#5**
  (a trace read-error → 404 "run not found", pre-existing convention shared with `run_node_detail`) —
  both rare, both **non-silent** (pre-flight message / debug breadcrumb); every fix adds UI/semantics or
  cross-cutting complexity for a theorized (no-users) problem. Left as-is; optionally file as low-pri issues.

Scope note: `task-175.md` (spec) + `implementation-plan.md` still name the pre-hardening
`_require_local_origin`/`_json_body` design — intentionally, as point-in-time records; the durable
forward-reference (`task-review.md`) was updated to the middleware.
