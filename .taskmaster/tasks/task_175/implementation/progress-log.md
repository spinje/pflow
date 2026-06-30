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
