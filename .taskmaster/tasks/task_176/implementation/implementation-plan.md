# Task 176 Implementation Plan — Web-UI Approval Bridge

> Written 2026-07-11 after the start-work research session: 8 codebase audits (pflow-codebase-searcher)
> + first-hand reads of `task_171/task-review.md`, `task_164/task-review.md`, `src/pflow/ui/CLAUDE.md`,
> `web/CLAUDE.md`, and the load-bearing seams. **Every file:line here was verified against THIS
> worktree (`276672a4`)** — an implementing agent should trust file+symbol and treat line numbers
> as near-exact snapshots. Owner decisions this session (do not re-open): gate panel = NodeCallout
> anchored at the ⏸ node; ONE `POST /api/resume`; plan gets /deep-review before build.
>
> Read first if unfamiliar: `.taskmaster/tasks/task_176/task-176.md` (spec + locked ledger),
> `task_171/task-review.md` (invariants), `task_164/task-review.md` (refusal family).

## Corrections to the spec (verified this session — trust these over the spec)

1. **The "add `PFLOW_EXECUTION_ID` to resume" CLI change is a NO-OP — it already works.**
   `_dispatch_resume` (`cli/commands/resume.py:420`) dispatches through the shared
   `execute_json_workflow`, whose single `RunnerConfig` does
   `execution_id=os.environ.pop("PFLOW_EXECUTION_ID", None)` (`cli/commands/run.py:301`), and
   `runner.py:193` threads `config.execution_id` into the trace collector on every path including
   resume. **Deliverable: a pin test only** (§P2-T4).
2. The stale-workflow hash gate **runs for paused-gate answers too** (`resume.py:571` is
   unconditional; only the side-effect confirm skips on paused, `resume.py:581-582`). The gate
   panel therefore needs the stale→ack→force state, not just the failed-run Resume button.
3. Paused **escalations** flow through `_resolve_between_nodes_entry` (loader sets
   `entry_node_id=None`, `resume_source.py:488`; CLI resolves at `resume.py:575-576`). The shared
   pre-flight must include it or escalation answers mis-refuse.
4. ADR-0013 does NOT govern our spawn (it's the shell-node dialect ADR). The Windows contract is
   the existing detach branch (`server.py:1098-1101`) + the blocking `tests-windows` CI job.
5. ADR-0007 obligation the spec omits: every new mutating endpoint must revisit + document its
   cross-origin exposure in `ui/CLAUDE.md` (§P2 docs).
6. `web/src/types.ts:62` comment claims `final_status` is "(success|degraded|failed)" — stale;
   code handles `denied`/`paused` too. Fix the comment in passing (§P3).

## Locked constraints (sources: spec ledger, 171/164 reviews, ADR-0008/0009, ui+web CLAUDE.md)

- Ledger: #1 kind-switched panel IN · #2 greying IN, LAST, cut-line · #3 `resolved_via:"ui"` OUT.
- **No silent no-ops**: the spawn is detached + DEVNULL; every refusal a spawned non-TTY
  `pflow resume` could hit must be caught by an IN-PROCESS pre-flight and returned as 4xx with
  diagnostics BEFORE spawning.
- Gate payload reaches the browser ONLY through `masked_gate_dict` (`core/gate.py:141-152`;
  ui→core import precedent: `server.py:73-77`).
- Trailer keys (`paused_node_id`, `gate_request`) are FLAT trailer keys — never add to
  `META_KEYS`. A paused trailer can exceed the 64KB tail window — the oversized full-re-read
  branch must survive every reader change.
- Light wires carry `paused_node_id` only; `gate_request` (large) is on-demand via `GET /api/gate`.
- `events.ts` `RUN_STATUSES` (:64) untouched — `paused` never arrives as a per-node RunEvent; it
  is client-synthesized (only `asRunComplete` passes it through, and that is an unfiltered cast).
- Side-effect verdicts use IR **registry** names via `is_side_effecting`
  (`runtime/compilation/compiler.py:643`, literally `node_type != "llm"`), never trace-event
  class names (`is_side_effecting("LLMNode")` is True — the recorded trap).
- Layering: `runtime/ ↛ ui/` (pinned by `test_import_hygiene.py`); `ui → execution/runtime/core`
  sanctioned (precedents: `execution/graph_service`, `server.py:1023`). The runtime twin reader
  `resume_source._read_trailer_line` stays duplicated — do NOT consolidate across that boundary.
- Server: hub-touching routes `async def`; blocking work via `asyncio.to_thread`;
  `subprocess.Popen`, never asyncio subprocess; argv starts `[sys.executable, "-m", "pflow.cli", ...]`.
- `_LoopbackOnly` middleware (`server.py:542-567`, installed :1364) covers all new routes
  automatically — verify with one test, never re-implement.
- #546 cold-start pin race: the resumed-attempt pin inherits it; tolerate, don't fix.
- Out of scope: external surfaces (Slack/email), engine/trace-format changes, PID
  tracking/cancel (#568), `resolved_via` plumbing.

---

## Phase 0 — baseline

Record by name in the progress log before any edit: `make test`, `make check`,
`cd web && npx vitest run`, `cd web && npx tsc --noEmit`. "No regressions" is diffed against this.

---

## Phase 1 — server read path: one trailer reader, `paused_node_id` on the light wires, `GET /api/gate`

### P1-1 `src/pflow/ui/run_tailer.py` — single oversized-safe trailer reader

Replace the status-only tail reader with a dict-returning one; derive `read_run_status` from it.
Model the new reader on the runtime twin `resume_source.py::_read_trailer_line` (:905-933) +
`_scan_tail_for_trailer` (:884-902) — same 64KB window, same
`size > 65536 and tail.endswith(b"\n")` one-shot full re-read, same `OSError → None`.

```python
def read_run_trailer(path: Path) -> dict[str, Any] | None:
    """Parsed run.complete trailer dict, or None (incomplete/unreadable).
    Oversized-safe: a paused trailer carries the full gate_request and can
    exceed the 64KB tail window (Task 171) — one full re-read covers it."""
```

- Rework `_scan_tail_for_terminal` (:88-104) into a `(trailer_dict | None, parse_ok: bool)`
  helper mirroring runtime's `_scan_tail_for_trailer` semantics exactly (reverse line scan,
  skip blanks, parse-failure of the last non-empty line → `(None, False)` which triggers the
  oversized re-read; last line a non-trailer → `(None, True)`).
- `read_run_status(path) -> tuple[bool, str | None]` keeps its exact signature + semantics,
  now derived: `trailer = read_run_trailer(path)`; `complete = trailer is not None`;
  `final_status = trailer.get("final_status") if isinstance(..., str) else None`.
  Callers (only two, verified): `_file_facts` (:251), `RunTailer._check_stopped` (:470).
- `_file_facts` (:242-254): also pull `paused_node_id` off the trailer
  (`trailer.get("paused_node_id")` — call `read_run_trailer` ONCE and derive both facts;
  don't read the tail twice). Thread through `_SCAN_CACHE` (typed :196), the `TraceCandidate`
  TypedDict (:173-182: add `paused_node_id: str | None`), and the candidate dict (:294).
- `_RUN_COMPLETE_FIELDS` (:611-618): append `"paused_node_id"`. This alone covers BOTH the live
  `run-complete` broadcast (`RunTailer._handle` :597-604) and the late-subscriber `run-snapshot`
  (`snapshot()` :369-388 returns the same `self._run`). Do NOT add `gate_request` (bulky —
  the allowlist's whole purpose).

### P1-2 `src/pflow/ui/server.py` — `_run_entry` + `GET /api/gate`

- `_run_entry` (:1178-1198): add `"paused_node_id": candidate["paused_node_id"]`.
- New route `GET /api/gate?run=<execution_id>` — read-only, no hub state → **sync handler,
  threadpooled** (mirror `/api/run-inputs`, the reader-endpoint precedent). Behavior:
  1. `400` missing/empty `run` param (mirror the `/api/graph` missing-param arm).
  2. Locate: `next((c for c in scan_traces() if c["meta"].get("execution_id") == run), None)`
     — the bare `scan_traces()` lists every run (verified); `None` → `404` "no run <id>".
  3. `trailer = read_run_trailer(candidate["path"])`; require
     `trailer and trailer.get("final_status") == "paused" and isinstance(trailer.get("gate_request"), dict)`
     — else `404` "run <id> is not paused" (covers corrupt/missing gate_request too).
  4. `200` body:
     ```json
     {"paused_node_id": "<node>", "gate_kind": "<gate_request['kind']>",
      "gate_request": masked_gate_dict(trailer["gate_request"])}
     ```
- `ui/CLAUDE.md`: add the `/api/gate` contract block (read exposure class = `/api/run-node`).

### P1 tests (patterns named from existing suites)

- `tests/test_cli/test_run_tailer.py`:
  - `test_read_run_trailer_returns_full_trailer_dict` (incl. `paused_node_id`+`gate_request` keys).
  - Extend the oversized pattern at `:468` (`test_read_run_status_handles_a_trailer_larger_than_the_tail_window`
    — keep it green) with `test_read_run_trailer_oversized_paused_trailer_is_read_fully`
    (trailer > 64KB via a big `gate_request.preview`). **Mutation-verify**: delete the full
    re-read branch → both oversized tests fail.
  - `test_scan_traces_carries_paused_node_id`.
- `tests/test_cli/test_ui.py::TestRunsEndpoint`: `test_run_entry_projects_paused_node_id` —
  mirror `:1016` `test_run_entry_projects_resumed_from_chain_lineage`; extend the `_write_trace`
  helper (:884-926) to accept trailer extras.
- `tests/test_cli/test_ui_interaction_server.py`: new `TestGateEndpoint` following the `_client()`
  pattern — 200 arm **pins masking** (put a sensitive-named key, e.g. `api_key`, in
  `gate_request.preview`; assert the served value is redacted and the raw value absent from the
  response body); 404 unknown-id; 404 not-paused (a `success` trailer); 400 missing param;
  oversized `gate_request` still served. Plus one `run-complete` SSE projection test asserting
  `paused_node_id` rides the banner (beside `TestRunScopedBroadcast`, :1094).

---

## Phase 2 — shared pre-flight + spawn helper + `POST /api/resume`

### P2-1 Extract the click-free pre-flight → `src/pflow/execution/resume_preflight.py` (new)

The CLI's refusal policy beyond the loader is four gates, all already pure or trivially
separable (verified line-by-line): `_load_source_and_workflow` (resume.py:94-129, pure),
`_check_content_hash` (:132-147, pure — uses `workflow_content_hash(resolved.ir)` from
`core/workflow_id.py:62-69`), `_resolve_between_nodes_entry` (:195-271, pure), and the pure
side-effect verdict (:290-301 of `_confirm_or_refuse_side_effect`; the click prompt tail
:303-322 stays in the CLI). Move those four (plus helpers `_node_registry_type` :150-156,
`_node_has_loop` :159, `_single_default_successor` :174) into the new module:

```python
@dataclass(frozen=True)
class ResumePreflight:
    source: ResumeSource
    resolved: ResolvedWorkflow
    # The exact refusal a non-TTY resume would raise for a side-effecting entry,
    # or None (paused source / --force / idempotent llm / entry removed).
    # A prompting caller (CLI TTY) confirms instead of raising; every other
    # caller raises it.
    side_effect_refusal: ResumeSideEffectConfirmationError | None

def preflight_resume(
    target: str,
    *,
    gate_answer: dict[str, Any] | None = None,
    force: bool = False,
) -> ResumePreflight:
    """Everything a resume refuses on, in CLI order, with zero click:
    load_resume_source ladder → content-hash stale gate → between-nodes entry
    resolution (entry_node_id is None) → side-effect verdict (constructed, not
    raised). Raises ResumeSourceError subclasses / ResumeStaleWorkflowError /
    ResumeNotResumableError exactly as the CLI does today."""
```

Internal order (must match the CLI's verified order — resume.py:558-582):
`load` → `hash gate` (skipped by `force`) → `if source.entry_node_id is None:
source = _resolve_between_nodes_entry(resolved, source)` → verdict
(`None` when `force` or `source.paused_node_id is not None` or entry type is `None`/not
side-effecting; else construct `ResumeSideEffectConfirmationError(str(entry), node_type,
execution_id=..., trace_path=...)` — ONE construction site, moved verbatim from :317).

**Layering**: `execution/` already imports `runtime.resume_source`, `runtime.compilation`,
`core.*` — all edges legal; `ui → execution` precedent is `graph_service`.

**`resume.py` after extraction** (thin click shell; `_dispatch_resume` unchanged).
**`inject_settings_env_vars()` STAYS as the first line of the try body** (resume.py:559-561) —
the CLI resume runs the workflow IN-PROCESS, and a resumed tail reaching an LLM node needs the
settings-stored keys in `os.environ`. Only the four refusal gates move (deep-review finding):
```python
inject_settings_env_vars()                                     # stays: in-process run needs keys
gate_answer = _build_gate_answer(approve, choose)              # stays: click.UsageError
target, cli_params = _split_target_and_params(args)            # stays: click.UsageError
pf = preflight_resume(target, gate_answer=gate_answer, force=force)
auto_approve, gate_deny = _prime_approval_delivery(approve, auto_approve, pf.source)
if not dry_run and pf.side_effect_refusal is not None:
    _prompt_or_raise_side_effect(ctx, pf.side_effect_refusal, print_flag)  # the old :303-322 tail
params = {**(pf.source.inputs or {}), **cli_params}
_dispatch_resume(ctx, pf.resolved, pf.source, params, ...)
```
- **Known micro-reorder** (document in the module docstring): `_prime_approval_delivery`'s
  contradiction UsageError (`--approve no` + `--auto-approve <same>`) now fires AFTER the hash
  gate instead of before. No test pins the old order (verified: the pins listed in P2-T2 don't
  cover this combination); both outcomes are refusals. Do not contort the seam to preserve it.
- `_prompt_or_raise_side_effect(ctx, refusal, print_flag)`: `can_prompt(controller)` →
  `click.confirm` (+ `ctx.exit(1)` on no) else `raise refusal` — behavior identical to today.
- Tests that call `_check_content_hash` / `_resolve_between_nodes_entry` directly
  (`test_resume_cli.py:297, 586-651`): update their imports to `pflow.execution.resume_preflight`.
  Every listed CLI pin (P2-T2) must stay green unmodified otherwise.

### P2-2 Spawn helper — `src/pflow/ui/server.py`

Extract from the `/api/run` handler (:1098-1109), byte-identical semantics:
```python
def _spawn_detached_cli(cli_args: list[str], *, execution_id: str) -> None:
    """Detached pflow CLI spawn (ADR-0008: launch, never host). DEVNULL everything;
    the outcome surfaces only through the trace the child writes. execution_id is
    forced via PFLOW_EXECUTION_ID so the browser can pin the exact run."""
    detach_kwargs: dict[str, Any]
    if sys.platform == "win32":   # explicit if/else, not ternary — mypy (Task 116)
        detach_kwargs = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        detach_kwargs = {"start_new_session": True}
    subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "pflow.cli", *cli_args],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "PFLOW_EXECUTION_ID": execution_id},
        **detach_kwargs,
    )
```
`/api/run` handler now calls `_spawn_detached_cli(["run", key, "--output-format", "json",
*tokens], execution_id=run_id)` — its existing tests (`TestRunEndpoint`, patching
`pflow.ui.server.subprocess.Popen`) must pass unchanged.

### P2-3 `POST /api/resume`

Async handler (JSON body via the same body-parsing path `/api/run` uses; `_LoopbackOnly` +
JSON-POST preflight apply automatically). Body:
`{"run": str, "approve"?: "yes"|"no", "choose"?: str, "force"?: bool}`.

1. **Shape validation → 400** (before any I/O): `run` non-empty string; `approve` in
   {"yes","no"} if present; `approve`/`choose` mutually exclusive; `choose` non-empty after
   strip (mirror the loader's `missing_answer` stance client-side of the spawn).
   Build `gate_answer` with the CLI's exact shapes (`resume.py:325-340`):
   `{"approve": approve == "yes"}` / `{"chosen": choose, "notes": None}` / `None`.
2. **Pre-flight off-loop** — including a COMPILE, mirroring `/api/run`'s `_preflight`
   (server.py:1011-1027), which exists precisely to convert the pre-trace-failure class into a
   clean 4xx. Without it, a spawned resume whose workflow no longer compiles (force-resume of an
   edited-broken workflow; unchanged hash but a deleted referenced file / removed MCP server)
   dies BEFORE writing its meta line (`runner.py:318` compiles before `engine.run()` flushes
   meta) → the pinned run_id never materializes → a misleading `run-not-found` 15s later
   (deep-review finding). The compile lives in the SERVER wrapper, not `preflight_resume` —
   the CLI compiles in-process moments later and surfaces the error interactively; a shared
   compile would just run it twice there:
   ```python
   def _resume_preflight(run, gate_answer, force):
       pf = preflight_resume(run, gate_answer=gate_answer, force=force)
       if pf.side_effect_refusal is not None:
           raise pf.side_effect_refusal          # non-TTY spawn would refuse — so we do
       # The exact compile the spawned child will do (CompilationError → 400 arm):
       compile_workflow(pf.resolved.ir, registry=Registry(),
                        initial_params=dict(pf.source.inputs or {}))
       return pf
   pf = await asyncio.to_thread(_resume_preflight, run, gate_answer, force)
   ```
   `preflight_resume`'s module docstring must state it deliberately does NOT inject settings
   env vars (no LLM call happens in pre-flight) — pre-empting a future "helpful" coupling of
   the server to settings I/O.
   Exception mapping (catch `PflowError`):
   - `ResumeSourceMissingError` → **404**
   - every other `ResumeSourceError` subclass (superseded, still-running, stale, side-effect,
     answer-required, fidelity, not-resumable, nothing-to-resume, gate-stopped) → **409**
   - any other `PflowError` → **400** (parity with `/api/run`'s pre-flight arm)
   Refusal body — diagnostics plus a machine-readable discriminator so the panel never
   string-parses:
   ```json
   {"errors": [<Diagnostic.to_dict()>...],
    "refusal": "superseded" | "still_running" | "stale_workflow" | "side_effect_confirmation"
             | "answer_required" | "fidelity" | "not_resumable" | "nothing_to_resume"
             | "gate_stopped" | "missing",
    // kind-specific extras:
    "newer_execution_id": "...",        // superseded only (exc.newer_execution_id)
    "node_id": "...", "node_type": "...",  // side_effect_confirmation only
    "hash_known": true|false}            // stale_workflow only
   ```
   `refusal` comes from a small module-level `{exception class → literal}` dict beside the
   handler. (`answer_required`'s masked gate already rides `errors[].context["gate"]` via
   `ResumeAnswerRequiredError.to_diagnostics()` — exceptions.py:1446-1455; don't duplicate it.)
   **Required one-line exception change** (deep-review finding): `ResumeStaleWorkflowError.__init__`
   (exceptions.py:1359-1381) uses `hash_known` only for the message and never stores it — add
   `self.hash_known = hash_known` (mirroring `self.newer_execution_id` :1272 /
   `self.node_type` :1331) or the stale 409 body raises `AttributeError` → 500.
   **Two intentional server-stricter asymmetries** (document beside the handler, they are not
   drift): `approve` accepts lowercase only (the CLI's click.Choice is case-insensitive — the
   typed frontend never sends otherwise; a raw caller gets a 400, still a loud refusal), and
   empty/whitespace `choose` 400s at shape-validation (the CLI routes it to the loader's
   `missing_answer` 409-equivalent — both refuse, only the status differs).
3. **Spawn**: `run_id = str(uuid.uuid4())`; args
   `["resume", run, "--output-format", "json"]` + (`["--approve", approve]` |
   `["--choose", choose]`)? + (`["--force"]` if `force`); `_spawn_detached_cli(args,
   execution_id=run_id)` → `200 {"status": "spawned", "run_id": run_id}`.
   The server NEVER adds `--force` itself — it appears only when the client sent
   `force: true` after an explicit ack dialog.

### P2 loose ends (deep-review)

- Touch two references that go stale with the move (cosmetic, one line each):
  `runtime/engine/engine.py:103` comment naming "the CLI's `_resolve_between_nodes_entry`",
  and `tests/test_cli/test_resume_no_hang_subprocess.py:11,114` docstring/assert message naming
  `_confirm_or_refuse_side_effect`.
- **Checkpoint**: run `/deep-review` (code mode) on the Phase-1+2 diff before starting Phase 3 —
  the extraction + first mutating endpoint is where a subtle omission hides; the frontend
  builds on it.

### P2 docs

`ui/CLAUDE.md`: `/api/resume` contract block + the ADR-0007 exposure paragraph (mutating; worst
cross-origin case is blocked by `_LoopbackOnly` + JSON preflight; a same-machine caller could
already run `pflow resume` directly — the ADR-0009 trust boundary "whoever can run the CLI
locally" is unchanged). `cli/commands/CLAUDE.md` resume row + `execution/CLAUDE.md` file list:
add `resume_preflight.py`.

### P2 tests

- **T1 (new)** `tests/test_cli/test_ui_interaction_server.py::TestResumeEndpoint` — copy the
  `TestRunEndpoint` pattern (`:871-945`; `patch("pflow.ui.server.subprocess.Popen")` around
  every test, real pre-flight running underneath, real paused/failed traces built with the
  existing fixture helpers from `test_paused_cli.py`/`_write_trace`):
  - approve-yes on a real paused approval → 200; assert argv
    `[sys.executable, "-m", "pflow.cli", "resume", <id>, "--output-format", "json", "--approve", "yes"]`
    and `kwargs["env"]["PFLOW_EXECUTION_ID"] == body["run_id"]`.
  - approve-no → argv carries `--approve no`. choose → `--choose <text>`.
  - `force: true` → `--force` present; absent otherwise.
  - **no-silent-no-op pins** (each asserts `popen.assert_not_called()`): superseded → 409 +
    `refusal == "superseded"` + `newer_execution_id`; side-effecting failed entry → 409 +
    `node_id`/`node_type`; stale (edit the workflow after the run) → 409 `stale_workflow`;
    unanswered paused (no approve/choose) → 409 `answer_required` with the masked gate in
    `errors[0]["context"]["gate"]`; both flags → 400; unknown id → 404.
  - **Mutation-verify** the no-silent-no-op rule: move the spawn above the pre-flight → the
    409-no-spawn pins fail.
- **T2 (must stay green, unmodified)** — the CLI battery:
  `test_resume_cli.py` (`test_stale_hash_refusal_after_edit`, `test_stale_hash_force_override_runs`,
  `test_dry_run_still_refuses_stale_workflow`, the side-effect quartet at :187-242, the
  between-nodes suite at :586-651 with updated imports, `test_is_side_effecting_speaks_registry_vocabulary`),
  `test_paused_cli.py`, `test_resume_list_cli.py`, `test_resume_source.py`, `test_gate_pause.py`.
- **T3 (new, thin)** `tests/test_execution/test_resume_preflight.py`: verdict matrix
  (paused source → None; `force` → None; `llm` entry → None; `shell` entry → carries
  `ResumeSideEffectConfirmationError` with node_id + registry type; entry removed → None),
  and hash-gate + escalation between-nodes delegation smoke — most depth stays in the moved
  CLI tests.
- **T4 (new pin)** `tests/test_cli/test_resume_cli.py::test_resume_honors_pflow_execution_id_env`:
  real failed run → `monkeypatch.setenv("PFLOW_EXECUTION_ID", <forced>)` → `pflow resume <id>`
  → the new attempt trace's meta `execution_id == <forced>` (and env var popped). This is the
  regression net for spec-correction #1.

---

## Phase 3 — frontend

### P3-1 Types + client (`web/src/types.ts`, `web/src/api/client.ts`)

- `NodeStatus` (:30): add `"paused"` and extend the :22-29 comment (consumer-derived, like
  `stopped`/`unrecorded`). Fix the stale `final_status` comment at :62 (add denied|paused).
- `RunComplete` (:63-75): `paused_node_id?: string | null`. (`asRunComplete` — events.ts:70-72 —
  is an unfiltered cast; no frontend allowlist to touch. The server allowlist was P1.)
- `RunInfo` (:83-99): `paused_node_id: string | null`.
- New interfaces mirroring `core/gate.py::GateRequest` (:34-55) + the `/api/gate` response:
  ```ts
  export interface GateRequest {
    node_id: string; node_type: string;
    kind: "action_approval" | "decision_escalation";
    preview: Record<string, unknown>;
    question: string | null;
    options: Array<Record<string, unknown>>;   // labels via option.label
    recommendation: string | null;
  }
  export interface GateInfo { paused_node_id: string; gate_kind: GateRequest["kind"]; gate_request: GateRequest; }
  ```
- `ApiError` (client.ts:9-20): add optional `readonly body?: Record<string, unknown>`
  (constructor third param, default undefined) so `refusal`/`newer_execution_id`/`node_type`
  are reachable without string-parsing. **Single-read rule** (deep-review finding): a Response
  body can be consumed ONCE — `resumeRun` must do `const parsed = await response.json()
  .catch(() => null)` once and derive BOTH `errors` (falling back to the `parseErrorBody`
  default entry when parsed is null/shapeless) AND `body` from that one object. Calling
  `parseErrorBody(response)` and then `response.json()` again throws, silently collapsing every
  refusal to the generic inline-errors arm (the discriminator actions would never appear).
- New fns copying `runWorkflow` (:126-140) exactly (incl. the load-bearing
  `Content-Type: application/json` header):
  ```ts
  export async function fetchGate(run: string): Promise<GateInfo>
  export async function resumeRun(req: { run: string; approve?: "yes" | "no"; choose?: string; force?: boolean }): Promise<string>  // → run_id
  ```

### P3-2 ⏸ badge synthesis (`web/src/views/GraphView.tsx`)

The key builder is `refKey` (`graph/focus.ts:17-20`); the paused node's key is
`refKey({ node_id: paused_node_id, ancestor_path: [], port: null })` (top-level guaranteed —
the 171 producer conjuncts exclude nested/batch gates). Add a tiny helper next to `eventState`
(:65):
```ts
const pausedEntry = (run: RunComplete | null): [string, NodeRunState] | null =>
  run?.paused_node_id
    ? [refKey({ node_id: run.paused_node_id, ancestor_path: [], port: null }), { status: "paused" }]
    : null;
```
- `runComplete` handler (:906-909): after `setRunBanner(run)`, if `pausedEntry(run)` →
  `setRunStatus(prev => new Map(prev).set(...entry))` (mirror the `runStopped` map-copy shape
  :925-934).
- `runSnapshot` handler (:880-897): after building the map from events, set the same entry off
  its `run` param (the pinned-replay/late-subscriber path).
- `StatusBadge.tsx`: `GLYPH` gains a `paused` arm (two vertical bars, same 10×10 SVG idiom as
  `stopped`'s square :72-76 — tsc forces this via `Record<NodeStatus, JSX.Element>`);
  `runStatusLabel` gains `case "paused": return "paused — awaiting answer";`.
- `RunProgress.tsx` `stepColor`/`stepMeta` (:51-77): `paused` arms (amber / "paused").
- `index.css`: `--status-paused: #d29922;` beside :31-34; `.status-badge.status-paused
  { background: var(--status-paused); }` in the :647-672 block.

### P3-3 GateCallout (deliverable 1 — owner: NodeCallout at the ⏸ node)

New `web/src/components/GateCallout.tsx`, rendered by GraphView in a `NodeCallout`:
- **Anchor**: mirror `sayAnchorIdFor` (GraphView.tsx:86-94) —
  `flatIdForRef(graph, {node_id, ancestor_path: [], port: null})` → node → `representativeFor`
  (:649-652) → `anchorId`. `frameOnMount={true}` (default) so the camera frames the gate.
- **Visibility** (GraphView state): render when
  `runBanner?.final_status === "paused" && runBanner.paused_node_id && graph && !gateDismissed
  && anchorId !== null` — the anchor resolution (below) can miss when a stale replay's paused
  node was renamed/removed in the current file; a null-anchor callout must not render
  (deep-review finding; the ⏸ badge already no-ops silently on the same miss).
  `gateDismissed` is a boolean reset inside `selectRun` (:294-315, alongside the other overlay
  resets) and cleared when the user clicks the paused node
  (`selectedNode?.ref.node_id === runBanner?.paused_node_id` in an effect — reuses `onNodeClick`
  → `setSelectedId`, no new click wiring). `onClose={() => setGateDismissed(true)}`.
  Two entry points total (auto-show + ⏸-node click) — deliberately no third.
- **Content**: on mount `fetchGate(runId)` → local `{gate, errors, submitting}` state; fetch
  failure renders `ApiError.errors` inline (RunPanel pattern :110-113). Kind switch:
  - `action_approval`: node id/type header, the masked `preview` as key→value rows (values via
    the existing text-formatting utils; long values in the existing scrollable block style),
    `recommendation` if present, buttons **Approve** / **Deny** →
    `resumeRun({run: runId, approve: "yes"|"no"})`.
  - `decision_escalation`: `question`, numbered option buttons (label =
    `option.label ?? "option N"` — mirror `option_labels`' fallback), free-text input +
    **Answer** → `resumeRun({run: runId, choose})`. Send the option's LABEL text (the loader's
    numeric mapping is a terminal convenience; labels are unambiguous). Client blocks
    empty/whitespace `choose`.
- **Submit outcomes**: 200 → `onAnswered(newRunId)` → `selectRun(newRunId)` (the single pin
  path — clears banner/status, callout disappears, overlay follows the new attempt; #546's
  cold-start grace applies). 4xx → switch on `err.body?.refusal`:
  - `"superseded"` → message + "View newer attempt" → `selectRun(newer_execution_id)`.
  - `"stale_workflow"` → warning ("workflow changed since this run" / "cannot verify unchanged"
    per `hash_known`) + "Resume anyway" → retry same payload with `force: true`.
  - `"answer_required"`/anything else → render `errors` inline.

### P3-4 Resume button on failed/interrupted runs (deliverable 2)

New `web/src/components/ResumeControl.tsx`, rendered by GraphView **inside the existing run
callout, directly below `<RunProgress …/>`** (:1130-1137) — zero RunProgress API changes.
- **Show when**: `runId !== null && (runBanner?.final_status === "failed" || (runBanner === null
  && runStopped))` (failed per banner; interrupted per the `stopped` outcome — the same
  discriminators RunProgress uses, verified :24-41 + :1135). Never for paused (GateCallout owns
  it) / denied / success / degraded.
- **Flow**: idle → [Resume ↻] → `resumeRun({run: runId})` →
  - 200 → `selectRun(newRunId)`.
  - 409 `side_effect_confirmation` → inline confirm naming `node_id` + `node_type` + "its side
    effects may fire again" → [Resume anyway] retries with `force: true`. (Idempotent `llm`
    entry never hits this — spawns dialog-free, mirroring the CLI.)
  - 409 `stale_workflow` → same ack pattern as the GateCallout.
  - 409 `superseded` → "already resumed" + jump to `newer_execution_id`.
  - other 4xx (`not_resumable`, `nothing_to_resume`, `gate_stopped`, `still_running`,
    `fidelity`) → render diagnostics inline; no retry affordance.

### P3 tests (vitest; templates named)

- `GraphView.test.tsx`: `paused` badge synthesized from `runComplete` AND from `runSnapshot`
  (copy the harness + the `unrecorded` test at :287-312; assert
  `getByLabelText("run status: paused")`); GateCallout appears for a paused banner and not for
  failed. **Mutation check at build**: remove the `runSnapshot` synthesis → the snapshot test
  fails alone.
- `GateCallout.test.tsx` (mock `../api/client` per RunPanel.test.tsx:9-22): approval renders
  preview + Approve/Deny and submits `{run, approve}`; escalation renders options + free text
  and submits label / typed text; empty choose blocked; `superseded` body → newer-attempt
  action; `stale_workflow` → force retry payload.
- `ResumeControl.test.tsx`: failed → POST `{run}`; `side_effect_confirmation` body → dialog
  shows node_id + node_type, ack retries with `force: true`; success invokes the pin callback.
- `RunProgress.test.tsx` / `StatusBadge`: `paused` arms (template: the existing paused
  run-banner test at RunProgress.test.tsx:142-153).
- `client.test.ts`: `fetchGate` + `resumeRun` success/error paths incl. `ApiError.body`.
- **`RunInfo` factory ripple** (deep-review finding — required field breaks tsc in four files
  the sections above don't name): add `paused_node_id: null` to the full-`RunInfo` factories in
  `RunSelector.test.tsx:17-31`, `CatalogView.test.tsx:23-38`, `RunPanel.test.tsx:31-45`, and
  the inline literal in `GraphView.test.tsx:218-229`. (Keep the field required — `resumed_from`
  set the convention.)

---

## Phase 4 — un-run greying (LAST; explicit cut-line per ledger #2)

- New pure pass in `web/src/graph/focus.ts` beside `applyStatus`/`applyFocus`:
  `applyReplayDim(nodes, edges, status, active)` — when `active`, a node with
  `!status.has(refKey(n.ref))` gets a `dimmed`-style flag rendered as class `.node.unrun`
  (edges dim when either endpoint is un-run). Identity-stable patching like `applyStatus`
  (:46-58) — return the same object when unchanged.
- `active` = pinned terminal replay ONLY: `runId !== null && runBanner !== null` (a live pinned
  run has no banner until its trailer) — never the unpinned live overlay (owner scoping
  2026-07-05). Paused/denied replays count as terminal (the grey region reads as "what never
  ran"); it composes with the ⏸ badge and, on stale replays, with the `unrecorded` hollow badge
  (coherent: both say "didn't run").
- CSS: `.node.unrun { opacity: .45; }` placed BEFORE `.node.dimmed` (:940-944) so focus-dim
  (0.18) wins when both apply, and before `.node.hover-mark` (:954-958) so hover un-dims — add
  the pair to `cssOrder.test.ts` (fs-read pattern, :40-53). Verify both densities
  (`.node.detailed`/`.compact`).
- Node-env tests in `graph/focus.test.ts` mirroring `applyStatus`'s.
- **Cut-line**: if this phase drags past one working session, file a follow-up issue with this
  section pasted in and ship Phases 1-3 + 5.

---

## Phase 5 — verification & close

- **`/deep-review` (code mode) on the full branch diff** before the manual pass — the plan
  review covered the plan, not the produced code.
- **Real-browser (required)**: kill any stale `pflow ui` first (the reuse-if-up probe serves
  old code — recorded 171 gotcha), `make ui-build`, then `screenshot-pflow-web-ui`:
  gated workflow launched from the UI → pauses → ⏸ badge on the frontier node + GateCallout
  with masked payload → Approve → new attempt pinned (⤷ chain marker) and completes; Deny →
  denied attempt surfaced (exit 3 is success-shaped); escalation → option click AND free-text
  both continue the run; a deliberate refusal (answer the same gate twice) → superseded panel
  state; failed run with side-effecting entry → dialog names node + type → force resume;
  idempotent (`llm`) entry → no dialog; non-loopback `Host` on `/api/resume` and `/api/gate` →
  403 (middleware — verify, don't re-implement).
- **Batteries** vs the Phase-0 baseline: `make test`, `make check`, vitest, `tsc --noEmit`,
  plus the named 171/164 suites (P2-T2). Task-159 `baseline/verify.sh` only if anything
  trace-adjacent moved (nothing should — the wire work is ui-side projection only).
- **Mutation-verify** (Edit + revert, never stash): the oversized-branch pins (P1), the
  no-silent-no-op pins (P2-T1), the snapshot-synthesis pin (P3).
- Windows: `tests-windows` CI is a blocking gate for the spawn-helper refactor.
- Docs sweep: `ui/CLAUDE.md` (P1/P2 blocks), `cli/commands/CLAUDE.md`, `execution/CLAUDE.md`,
  `web/` CLAUDE.mds where invariants grew; progress log throughout; task-review at close.

---

## Edge-case ledger (dispositions — implementer must not re-litigate)

1. **Two viewers answer concurrently (TOCTOU)**: both pre-flights can pass; both spawn; the
   loser's CLI refuses on the loader's superseded check (consumption policy — no double-fire);
   the loser's browser pins an id that never materializes → the existing `run-not-found` state.
   TOLERATED (local single-user; same posture as #546). Document in `ui/CLAUDE.md`.
2. **Paused trailer without `gate_request`** (corruption): `/api/gate` → 404; POST pre-flight
   refuses via the loader's malformed-pause arm. No 500s.
3. **Pre-content-hash trace** (`content_hash is None`): stale gate refuses with
   `hash_known=False` → panel says "cannot verify unchanged" → force ack path. (Verified:
   `None != current` is a refusal, resume.py:142.)
4. **Wrong-kind answer** (approve on escalation etc.): panel prevents by kind-switch; the
   loader's `wrong_flag` 409 is the safety net. No special client handling beyond inline errors.
5. **Answered-elsewhere while panel open**: submit → 409 superseded → "view newer attempt".
   The panel does NOT pre-compute answered-ness (no inverse `resumed_from` scan — rejected as
   plumbing without a consumer; the POST is authoritative).
6. **`--force` scope**: force skips BOTH the stale gate and the side-effect confirm (CLI parity).
   One ack dialog therefore covers both when they co-occur — acceptable; the dialog text names
   whichever refusal triggered it.
7. **Paused source run keeps its ⏸ selector mark after answering** — raw trailer facts, shipped
   171 behavior; the `⤷ resumed from` marker on the new attempt communicates lineage. Unchanged.
8. **`paused_node_id` join**: always top-level (`ancestor_path: []`, `port: null`) — 171
   producer conjuncts forbid nested/batch pauses. Key literal: `"<node_id>|null|"` — but always
   construct via `refKey(...)`, never hand-format.
9. **Escalation answers**: send the option LABEL (or free text) — never the number; numeric
   mapping is loader-side terminal convenience (`_map_choose_answer`).
10. **Dry-run**: not exposed on `/api/resume` v1 (no consumer); the CLI keeps it.
11. **MCP-launched paused runs**: stream to disk since 171 → same trace, same wires; the bridge
    serves them with zero extra code (ADR-0008 "MCP runs stream too").

## Agent split & model assignment

Two agents, handing off at the plan's one strong firebreak — **after the P2 checkpoint review**,
where the HTTP contract (endpoint shapes, `refusal` literals, body extras) is test-pinned and
written into `ui/CLAUDE.md`. Never split inside P2 (the refusal-parity author must be its first
consumer), and treat any post-handoff `refusal`-literal rename as a plan amendment.

| Agent | Phases | Driver model | Delegate down (Sonnet-class code-implementer, under review) |
|---|---|---|---|
| A — backend | P0–P2 + checkpoint review | **Fable** | P1 implementation — AFTER the driver has written the parametrized input-class matrix test + mutation pins (oracle first; they make P1's silent-drop risk loud); P2 test-import repoints |
| B — frontend + close | P3–P5 | **Fable** | types/client/CSS/badge arms + the 4 test-factory fixes (tsc-caught); P4 greying against driver-written focus tests |

Rules applied: model strength tracks **silent-failure risk and judgment density**, not LOC. P2
and the P3 component/state work stay with the strongest model (plausible-but-wrong is invisible
there). **Tests that encode reasoning are driver-written, always** — the reader matrix, the
mutation-verified pins, the no-silent-no-op endpoint pins, the component state tests — a
delegate must never author the oracle that guards its own work; only trivially mechanical test
chores (factory field additions, import repoints) delegate. P5's screenshot judgment and the
code-mode deep-reviews also stay with the driver.

## Trust boundary

- **Verified first-hand or by cited audit** (file:line above): all seams, signatures, orders,
  key shapes, test patterns, and both spec corrections.
- **Assumed (small, verify mechanically at build)**: `CliRunner`/`monkeypatch` env delivery for
  P2-T4 (standard pytest technique); exact NodeCallout styling fit for form controls (adjust
  CSS in place if cramped — presentation only).
