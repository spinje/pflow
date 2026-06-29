# Task 175: Run Workflows from the Web UI — Launch, Inputs Form & Run Inspection

## Description

Let a user start a workflow run from the `pflow ui` canvas (a ▶ "Run" button) with an
auto-generated inputs form, watch it execute on the live overlay, inspect what each node — including
the input/output nodes — received and produced **this run**, and re-run with prior inputs. Revives the
deferred Task 173 "launch POST" (D4) and extends it into a full run/inspect/re-run loop. Closes the gap
where pflow can *observe* runs in the browser but can't *trigger* them, and where a past run's inputs
were never recorded anywhere durable.

## Status

not started

## Priority

high

## Problem

The live overlay (Task 173) made runs *observable* in the browser — the canvas lights up as a run
executes, you can replay a finished run, and a detail panel shows each node's runtime record. But:

1. **You can't start a run from the UI.** The only way to trigger a workflow is the CLI
   (`pflow run wf key=value…`). The browser is read-only.
2. **A run's inputs are recorded nowhere usable.** The trace `meta` records
   `workflow_path`/`execution_id`/`only_node`/timestamp but **not the input values** (verified:
   `workflow_trace.py:_meta_fields`). Inputs are seeded straight into the shared store and never become
   trace events. So you cannot inspect *"what inputs did this run use?"* and cannot reliably re-run with
   the same inputs.
3. **The IO nodes aren't inspectable for a run.** Input/output nodes don't execute, so they have no
   runtime event; the detail panel's "This run" section is gated to completed nodes and skips them.
4. **Re-running is manual.** You must retype `pflow run …` in a terminal.

There is a vestigial frontmatter store (`last_execution_params` in a saved workflow's
`.pflow.md` frontmatter) but it is **lossy and narrow** — redacted/truncated values, saved-workflows-only,
success-only, last-run-only — never a faithful input record (see Implementation Notes → Frontmatter store).

## Solution

A small, ADR-0008-clean feature that **composes with the already-built run/trace/tail/overlay pipeline**
rather than adding a new subsystem:

- **Launch = spawn the normal CLI as a detached subprocess.** A `POST /api/run` handler spawns
  `pflow run <wf> --output-format json key=value…` via `subprocess.Popen([sys.executable, "-m",
  "pflow", …], start_new_session=True)`. The run writes its own streaming trace; the existing tailer
  discovers it and the overlay lights it up live — **no new streaming/observation code**. The run is
  detached so it outlives the browser (ADR-0008 independence). The server stays a pure observer except
  for this one spawn; **no in-process execution** (that would re-couple run lifecycle to the long-lived
  async server — the design ADR-0008 rejected).
- **Inputs form, auto-generated from the schema.** `/api/graph` already ships each `## Input` as a
  `kind=="input"` node carrying `{name, data_type, required, default, description}` — render a form from
  it. No new schema endpoint.
- **Keystone: record `meta.inputs` at run start.** Add an `inputs` field to the eager trace `meta` line.
  Inputs are run-scoped facts known at t=0 — this is the right home, beside `execution_id`. This single
  change unlocks input inspection *and* faithful re-run, is cache-independent, and reuses the existing
  recursive redactor on read.
- **Uniform inspect: click any node → "This run".** Extend the detail panel to the IO cards — an input
  node shows its value from `meta.inputs[name]`; an output node shows its result from
  `json_output["result"][name]`. One interaction for every node.
- **Run vs re-run = one form, different prefill.** The Run panel has a "load inputs from" picker:
  *Defaults* or any past run (prefills from that run's `meta.inputs`), then tweak and submit. The clock
  (RunSelector) per-row ↻ becomes optional sugar that opens the form pre-selected.
- **Security: one shared Host-header guard** on the mutating endpoints — kills DNS-rebinding→RCE, the
  only real bypass of the loopback+no-CORS posture. No CSRF tokens/auth (overengineering for a
  single-user loopback tool).

## Design Decisions

- **Launch via detached subprocess, not in-process execution.** Reuses the exact CLI run path (one run
  path, behaviorally identical to hand-running), keeps the server a pure observer (ADR-0008), isolates a
  crashing/long workflow from the long-lived async server, and survives the UI closing. In-process would
  re-introduce the lifecycle coupling ADR-0008 rejected and force a second run path.
- **Inputs passed as the CLI's normal `key=value` args (channel "A"), NOT a new JSON channel.** A makes
  the form *faithful to the CLI* — "run from the form" == "run from the terminal." The type-coercion
  quirk (`infer_type` turning `01234`→`1234`) is a **pre-existing property of the CLI's key=value
  convention** that bites hand-typed runs identically; the form doesn't make it worse. Rejected channel
  "B" (a `--inputs-json` typed channel): it would make the form behave *differently* from the CLI (a
  divergence) and only fixes the form. If the coercion quirk ever matters, fix it at the root in the
  CLI's coercion so CLI + form improve together — a separate, optional cleanup, not a precondition here.
- **`meta.inputs` is the single input record; the frontmatter `last_execution_params` is superseded.**
  `meta.inputs` is raw-on-disk (faithful for re-run; redacted on display), complete (all runs), and
  cache-independent. Don't maintain two input stores.
- **Inspect IO nodes (not a separate run-level summary).** A uniform "click any node → This run" is
  simpler to reason about and matches the canvas metaphor (the value lives on the node it belongs to).
  Verified feasible: `RFRef.node_id` is the bare input name (`react_flow.py:233`).
- **Re-run = the same launch form with a different prefill source.** Not a separate mechanism. A
  "load inputs from past run" picker subsumes the clock's ↻.
- **Per-field cross-run *value* mixing is deferred, and if built should be value-autocomplete, not
  run-provenance.** Single-run prefill + free editing covers the practical case. If combinatorial
  input-picking proves a real need, add per-field autocomplete of distinct previously-used values
  (light, familiar) — NOT per-field "which run did this come from" tracking (heavy, theorized).
- **Security = Host-header allowlist, no auth.** The realistic threat is a malicious site driving the
  loopback server via the browser; loopback + no-CORS + strict `application/json` already block
  cross-origin form/JSON POSTs (verified `_json_body`, `server.py:418`). The one gap is DNS rebinding,
  closed by a `Host` check. Tokens/sessions would be machinery with no threat to stop.
- **Spawn button-launched runs with `--output-format json`** so the workflow result (`json_output`) is
  always recorded (it's otherwise only written on json-format runs) → output-node inspect is reliable.
  Harmless for a detached run whose stdout nobody reads. Other (text-mode) runs degrade gracefully.
- **No-input workflows still show a "▶ Run" confirm** (an explicit, deliberate trigger like n8n), rather
  than running on the icon click. *(DECIDED 2026-06-29.)*
- **Placement: a separate ▶ icon at the BOTTOM of the Rail** opening a Run panel — distinct from the
  clock/RunSelector, which sits in the Rail's top slot and keeps view/replay/re-run. *(DECIDED 2026-06-29:
  a separate ▶ anchored at the BOTTOM of the Rail — NOT folded into the clock panel, NOT the top slot.)*
- **Secret prefill: server-side reuse.** When prefilling the form from a past run, send
  non-secret values to the client but never secrets; the client signals "reuse run X's value for
  `api_key`" and the server fills it from the trace it can already read — the secret never enters the
  browser. *(DECIDED 2026-06-29. Blank-and-re-enter stays the fallback only if the reuse plumbing slips.)*
- **Full frontmatter-store deprecation is a noted FOLLOW-ON, not part of this task.** This task only
  makes `meta.inputs` authoritative for inputs. See "Frontmatter deprecation (follow-on)".

## Dependencies

- **Task 173: Live Execution Overlay** — this feature builds directly on its shipped pipeline: the
  trace producer + `meta` line, `run_tailer` discovery/tail, the SSE overlay, flock liveness, the
  RunSelector pin/`&run=`, and the `ThisRunSection` detail panel. (Task 173's own closure — pin D1,
  `task-review.md` — is independent and unaffected.)

## Requirements

### Producer — `meta.inputs` keystone
- The eager trace `meta` line records an `inputs` field: the workflow's resolved input dict known at run
  start (the values seeded into the shared store), for **all** runs (saved, path, inline).
- Stored **raw** on disk (same exposure class as today's resolved `node_params`); redaction happens on
  read/display, not at write — so re-run can reconstruct faithful values server-side.
- The existing `tree() == reconstruct` equivalence and all trace-contract tests stay green; `meta.inputs`
  is additive and ignored by post-hoc readers that don't need it.

### Backend — `POST /api/run` + security
- `POST /api/run` accepts a workflow reference (name or path, resolved via the existing `_workflow_key`
  path — **never inline workflow content**) and an `inputs` object; spawns a **detached** subprocess
  `pflow run <resolved> --output-format json key=value…` and returns `200` on successful spawn, `404`
  unresolvable workflow, `400` malformed body. Runtime failures surface via the overlay, not the
  response.
- The handler enforces JSON (`_json_body`) and a shared **`_require_local_origin`** guard (reject any
  request whose `Host` header isn't `127.0.0.1`/`localhost`). Apply the guard to the existing mutating
  POSTs too (`/api/command`, `/api/interaction`, `/api/visibility`).
- The spawn uses `sys.executable -m pflow` (the server's own venv) and `start_new_session=True`; it does
  not block the event loop and keeps no per-run process state (observation is via the trace, not a
  process registry).
- `key=value` tokens are built one-per-argv-element (no shell), so values are injection-safe.

### Frontend — form + launch
- A ▶ control at the **bottom of the Rail** opens a **Run panel** whose form is generated from
  `/api/graph`'s `kind=="input"` nodes: one field per input, prefilled with the declared `default`, required fields marked, description
  as helper text. Types map to sensible controls (text/number/checkbox/textarea; JSON inputs as text).
- Submit → `fetchRunNode`-style call to `POST /api/run` → on success the overlay switches to
  **follow-newest-live** (the existing RunSelector mechanism) so the launched run lights up.
- A workflow with no inputs shows a "▶ Run" confirm. Each fetch owns its failure (DR-6 posture) — a
  spawn error shows a message, never blanks the canvas.

### Inspect — click any node → "This run"
- Clicking an **input node** with a run in context shows its value for that run, read from
  `meta.inputs[ref.node_id]` (`ref.node_id` is the bare input name — verified). Clicking an **output
  node** shows `json_output["result"][name]`; absent (text-mode run) → graceful "no recorded output"
  or fall back to the producing node's `node_output`.
- The detail-panel gate opens for IO nodes when the in-context run has the relevant data, in addition to
  the existing terminal-node gate. `/api/run-node` projects IO-node refs from `meta`/`json_output`
  instead of scanning for a (nonexistent) node event.
- Secrets in displayed inputs/outputs are redacted by the existing recursive key-name redactor.

### Re-run / prefill
- The Run panel has a **"load inputs from"** picker: *Defaults* + the last N past runs (labeled
  timeAgo + status), each prefilling the form from that run's `meta.inputs`. The user may tweak before
  submitting.
- Secret fields follow the secret-prefill decision (server-side reuse; never sent to the browser).
- The clock/RunSelector per-row ↻ opens the Run panel with that run pre-selected (optional sugar).

### Frontmatter deprecation (follow-on — out of scope here, documented for the sequel)
- Once `meta.inputs` is authoritative, the frontmatter `last_execution_params` is redundant and the
  whole frontmatter execution store (`execution_count`/`last_execution_*`/`average_*`) is deprecatable.
  Its only live consumers are three CLI displays (`pflow history`/`describe`/`find`), all via
  `history_formatter.py`. Deprecation must explicitly decide the **MCP-history trade-off** (MCP/
  `--no-trace` runs write frontmatter but no trace → trace-based history would lose them) and accept the
  pre-existing move/rename trace-orphaning. Also delete the already-orphaned `rerun_display.py` +
  `ctx.obj["execution_params"]`. **Not built in this task.**

## Implementation Notes

### Verified facts grounding the design
- **Inputs flow:** `pflow run wf name=World` → `parse_workflow_params` → `infer_type` (bool/int/float/
  json/str coercion, `param_parsing.py`) → seeded directly into the shared store (`runner.py:263-292`);
  there is **no input node execution** and no trace event for inputs.
- **Trace meta lacks inputs today:** `_meta_fields` (`workflow_trace.py:945`) = `format_version,
  execution_id, workflow_name, workflow_path, start_time, only_node, content_hash`. The keystone adds
  `inputs`.
- **Streaming is default:** `stream_to_disk=config.trace_enabled` (`runner.py:156`), `trace_enabled`
  defaults `True` for the CLI — so a plain `pflow run` already writes the incremental trace the overlay
  tails.
- **Input-node identity:** `_input_node_id(name, ancestor_path)` → `NodeId(name, …, port="in")`
  (`build.py:891`); `RFRef.node_id = node.id.node_id` (`react_flow.py:233`) → the **bare input name**
  (the React Flow flat `id` is a separate minted `n{i}`). So `meta.inputs[ref.node_id]` maps directly at
  top level; sub-workflow inputs carry a non-empty `ancestor_path`.
- **Output values:** `json_output` (`run.complete` trailer, `workflow_trace.py:_aggregates`) is the full
  success envelope; declared outputs live under `json_output["result"][outputName]`
  (`success_formatter.py:233`). **Only set on `--output-format json` runs** → spawn button-launched runs
  with that flag.
- **Security posture (verified):** server binds `127.0.0.1` (`cli/commands/ui.py:26`), sends no CORS
  headers, `_json_body` (`server.py:418`) hard-rejects non-`application/json` with 415. Cross-origin
  form POST → 415; cross-origin JSON POST → blocked preflight. Remaining gap = DNS rebinding (Host
  header = attacker domain) → the `_require_local_origin` Host check closes it.
- **Cache is a separate store:** memoization lives in SQLite at `~/.pflow/cache/cache.db`, keyed
  `md5(config_hash + hash(resolved_inputs))` (`runtime/cache.py:97`), opt-in per node. Re-running with
  the same inputs reproduces keys → cache hits → fast/cheap, nodes light "cached" (already handled). The
  cache stores an irreversible *hash* of inputs, so it can't supply input inspection — confirming
  `meta.inputs` is required. Do NOT store run/input history in the cache db (disposable side-store vs
  record-of-truth).

### Frontmatter store (the thing being superseded)
- Lives in the saved workflow's YAML frontmatter (`~/.pflow/workflows/{name}/{name}.pflow.md`).
- Written by `WorkflowRunner._update_metadata` (`runner.py:693-724`) → `WorkflowManager.update_metadata`
  (`manager.py:397-441`): `execution_count`, `last_execution_timestamp`,
  `last_execution_success` (hard-coded `True`), `last_execution_duration_seconds`,
  `average_execution_duration_seconds`, `last_execution_params`.
- **Only on success, only for saved/library workflows, last-run-only.** `last_execution_params` is
  `sanitize_parameters`-processed (secrets→`<REDACTED>`, long values truncated to 20 chars, `__`-internals
  dropped) → **lossy, never faithful**.
- Live consumers: `pflow history`, `pflow describe`, `pflow find` (all display, via
  `history_formatter.py`). Not read by `pflow list`, the UI, MCP reads, or dry-run estimates.

### Trace durability (informs the deprecation follow-on)
- **No automatic cleanup/rotation/cap/TTL** anywhere; no `pflow` clear command. Traces in
  `~/.pflow/debug/` accumulate without bound. The run button will generate more — consider a retention
  policy as a separate fast-follow (not blocking).
- Traces match a workflow by exact `workflow_path` string (md5-prefixed glob + equality,
  `workflow_trace.py:133-149`). **Moving/renaming the `.pflow.md` orphans old traces** (frontmatter
  rides the file; traces don't) — a pre-existing limitation.

### n8n comparison (why the shape is what it is)
- n8n uses trigger nodes and runs **in-server**, streaming node data back. pflow has **no trigger node**
  (the CLI invocation is the trigger), runs as a **detached traced process** (ADR-0008), and generates
  the form from declared `## Inputs` (≈ n8n's Form Trigger, but automatic). The overlay is our
  canvas-as-inspector; "click node → This run" is our data panel. The decoupling is a strength: runs
  survive the UI, are inspectable later, and look identical whether launched by agent/CLI/UI.

### Build sequence
1. Producer: `meta.inputs` in the eager meta.
2. `POST /api/run` + `_require_local_origin` Host guard (apply to existing POSTs too).
3. Run panel + form (generated from `/api/graph`) + ▶ + overlay follow-newest.
4. IO-node inspect (`/api/run-node` IO projection + gate extension).
5. Re-run prefill picker (+ clock ↻ sugar).
6. (Optional, later) standalone bookmarkable form view (`?view=form`); file-upload inputs explicitly
   deferred (multipart + where files land = a new concern).
7. (Optional, later) per-field value autocomplete.

## Verification

- **Producer:** `meta.inputs` recorded raw for a templated run (e.g. `name=World`); present for saved,
  path, and inline runs; redaction is applied on read, not at write; trace-equivalence tests stay green.
- **Endpoint + security:** `POST /api/run` spawns a detached run that appears in `/api/runs` and lights
  the overlay; `404` on unknown workflow, `400` on bad body; **Host-guard rejects a request with a
  non-loopback `Host` header (403)** while a normal loopback request succeeds; the guard also covers the
  existing mutating POSTs.
- **Form + launch (browser, mandatory):** open a workflow with inputs → ▶ → form generated from the
  schema (required marked, defaults prefilled) → submit → the run lights up live on the canvas and
  finishes with the run banner. A no-input workflow shows the "▶ Run" confirm.
- **Inspect (browser):** click the input node → its run value (resolved, secret-named input REDACTED,
  normal value full); click the output node → the workflow result; click a producing node → its output.
  Degrades cleanly on a text-mode run with no `json_output`.
- **Re-run:** the "load inputs from" picker lists past runs; selecting one prefills the form from its
  `meta.inputs`; a secret field is never populated with a real value in the browser (server-side reuse);
  submitting reproduces the run (and cache-enabled nodes light "cached").
- **Faithfulness:** a form launch and the equivalent hand-typed `pflow run …` produce identical results.
- **Gates:** `make test` + `make check` (Python), `vitest` + `tsc` (frontend) green vs the captured
  baseline; real-browser verification via the `screenshot-pflow-web-ui` skill + the overlay-status
  probe (per the Task 173 verification pattern).

## References

- **Task 173 implementation** (the pipeline this builds on): `.taskmaster/tasks/task_173/implementation/`
  (`progress-log.md`, `implementation-plan.md`, `d6-plan.md`); D4 (launch POST) was deferred there.
- **ADR-0008** — server tails the trace; the run writes it (the transport decision this honors).
- **Producer / trace:** `src/pflow/runtime/workflow_trace.py` (`_meta_fields:945`, `_aggregates:957`),
  `src/pflow/execution/runner.py` (`:156` streaming, `:263-292` input seeding, `:693-724` frontmatter
  write).
- **Inputs:** `src/pflow/cli/param_parsing.py` (`infer_type`/`parse_workflow_params`),
  `src/pflow/cli/commands/run.py`.
- **Graph / form schema:** `src/pflow/core/workflow/graph/build.py` (`_input_node_id:891`),
  `src/pflow/core/workflow/graph/renderers/react_flow.py` (`RFRef:37`, `node_id=node.id.node_id:233`),
  `src/pflow/ui/CLAUDE.md` (the `RFNode.io` interface facts + `/api/graph` contract).
- **Output envelope:** `src/pflow/cli/workflow_output.py` (`_handle_json_output`),
  `src/pflow/execution/formatters/success_formatter.py` (`_collect_outputs:179-245`).
- **Server / security:** `src/pflow/ui/server.py` (`_json_body:418`, the CORS tripwire `:826-837`,
  the route list), `src/pflow/cli/commands/ui.py` (`_HOST:26`).
- **Cache (separate store):** `src/pflow/runtime/cache.py` (`compute_node_cache_key:91`,
  `MemoizationCache:155`).
- **Frontmatter store + consumers (deprecation follow-on):** `src/pflow/core/workflow/manager.py`
  (`update_metadata:397`), `src/pflow/execution/formatters/history_formatter.py`,
  `src/pflow/cli/commands/history.py`, `src/pflow/cli/rerun_display.py` (orphaned).
- **Secret redaction:** `src/pflow/core/security_utils.py` (`is_sensitive_parameter`,
  `sanitize_parameters`).
