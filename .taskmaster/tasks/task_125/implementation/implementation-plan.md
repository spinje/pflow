# Task 125 — Blocking Approval Gates: Implementation Plan

> **Status: ready to implement.** Written 2026-07-02 during the start-work session, for an
> implementing agent working in isolation. Every file:line ref was verified against this
> worktree (branch `feat/human-loop-approval-gates` @ c9998727, clean tree) by seven
> pflow-codebase-searcher passes. If `main` has moved under you, re-verify refs before
> editing — this area absorbs ~20 merges/week.
>
> Read first: `task-125.md` (the spec), then this. The spec's engine-seam claims are
> verified exact; this plan CORRECTS the spec in three places, each marked **[spec-correction]**.
> Glossary terms (Gate, Approval, Escalation, Denial) are in `context/CONTEXT.md`.
> ADR-0009 (the payload is the seam; approval surfaces are out-of-process bridges) governs.
>
> **Deep-reviewed 2026-07-02** (7-agent battery: plan, silent-failures, impact-completeness,
> validation-consistency, feature-interactions, agent-ux, concurrency-safety). All confirmed
> findings are FOLDED IN below — sections marked **[review-fix]** changed as a result. The
> four criticals were: (1) the trace reconstruct reader raises on unknown line kinds, so the
> `gate` kind needs a known-but-ignored arm (Phase 4); (2) `WorkflowExecutor.exec`'s generic
> `except Exception` converts nested gate exceptions into routable node failures (Boundary
> inventory); (3) the batch retry/worker arms retry-then-swallow gate exceptions
> (`retriable = False` fixes it); (4) a blanket main-thread guard would break MCP
> `--auto-approve` (MCP runs the engine via `asyncio.to_thread`) — replaced by
> resolver-substitution in parallel workers. Baselines captured pre-change: 8283 tests pass,
> `make check` fully green.

## Decisions (all resolved — nothing open)

| # | Decision | Resolution |
|---|---|---|
| 1 | Batch-host gates | REJECTED at validation (owner-locked). "Gate the step before or after the batch." |
| 2 | `gate` trace event | IN scope (owner-locked). Observe-only; no tailer/SSE forwarding. |
| 3 | Auto-approve | `--auto-approve=<node-id>`, repeatable, per-node only. NO blanket flag (owner-locked; the friction is the point). |
| 4 | Non-TTY failure timing | Fail AT the gate + warn at run start (owner-confirmed rec). No pre-flight hard fail (conditional branches may never reach the gate). |
| 5 | Denial semantics | Clean stop: `GateDenied` exception → `WorkflowStatus.DENIED` → exit code **3** → trailer `final_status: "denied"`. Never a node failure, never `error`-successor routing (owner-confirmed rec). |
| 6 | Escalation scope | IN this task (owner, 2026-07-02) — the schema-retry self-heal (`claude_code.py` `_exec_async`/`_coerce_structured_output`) de-risks the marker trigger. |
| 7 | Escalation trigger | Reserved `escalation` key **inside a node's `result` dict** (not namespace top level — claude-code can only emit through `result`). Node-type-agnostic. |
| 8 | Escalation continue | Engine writes the human's decision into the node's namespace; the AUTHOR wires the response (backward edge / `loop:` + carry). No engine re-run machinery. "Escalation re-forks by design." |
| 9 | Gate plumbing to nested engines | A `__gate_resolver__` callable in the shared store, propagated exactly like `__progress_callback__` (`workflow_executor.py:144` `_PROPAGATED_KEYS`). NOT engine constructor args (child engines are built with only `trace_collector` + `only_node`, `workflow_executor.py:425`). |
| 10 | Escalating results are never cached | An escalation is an incomplete work product. Skip in-process + memo cache writes when the fresh result carries a truthy `escalation` (else a memo hit silently replays the escalation as resolved-without-a-decision — the cache-hit early-return would skip the check). |
| 11 | **[review-fix]** Gate exceptions are never-swallow-never-retry | `GateDenied` + `GateNotInteractiveError` both get `retriable = False` (the field exists on `PflowError`, `core/exceptions.py:47`, default True) and explicit re-raise arms at EVERY generic `except Exception` between the gate and the runner — see Boundary inventory. Otherwise a nested denial becomes an error-routable node failure and `error_action: continue` runs past a human's "no". |
| 12 | **[review-fix; AS-IMPLEMENTED]** Parallel workers get a `__gate_prompt_allowed__ = False` flag, not a thread guard | NO blanket main-thread check (MCP runs the engine on an `asyncio.to_thread` worker — `execution_tools.py:87` — a guard would kill MCP auto-approve with a lying "parallel batch" message). Implemented as a boolean in each parallel worker's `item_shared` (set next to the progress-buffer swap, `batch_executor.py` `process_item`), propagated via `_PROPAGATED_KEYS`, and passed to the resolver per call (`resolver(request, allow_prompt=...)`). The reviewed resolver-SUBSTITUTION variant was rejected at implementation: it needed runtime code to construct an execution-layer resolver (layering violation). Same guarantees: auto-approve works in workers (flag lookup is thread-safe), `parallel_batch=True` is truthful (only source is `allow_prompt=False`), sequential items inherit the parent resolver — prompting per item works; a denial cleanly stops the whole run via Decision 11. |
| 13 | **[review-fix]** Decision is written INTO the marker | The human's choice lands at `result.escalation.decision` (via careful setdefault, never bare index) and detection SKIPS markers already carrying `decision`. Idempotent by construction: a child workflow exposing the escalating node's `result` upward can't re-trigger the prompt, and the batch scan can't false-fire on an already-answered escalation. Carry template: `${step.result.escalation.decision}`. |
| 14 | **[review-fix]** Gate prompt TTY check is stdin+stderr, not `is_interactive()` | The prompt renders on stderr and reads stdin — stdout piping (`pflow wf \| jq`, `> out.json`) must not disable gates at a real terminal. New check: not print-mode AND `stdin_tty` AND `stderr_tty` (fields already captured on OutputController). `is_interactive()`'s stdout requirement stays for its existing consumers. |

## Deferred-by-design — do NOT build (spec + braindumps; re-merging = wrong)

No `ApprovalSurface` ABC (resolution = a plain closure). No blanket `--auto-approve`. No batch
gates. No web/Slack approval (Task 176). No `on_pause` hook. No durable tokens / pause
serialization / `pflow resume` (Task 171). No tailer/SSE arm for the `gate` event (Task 176).
`route_action` stays pure — both seams live in `_execute_node`, not the routing kernel. No
`"denied"` in the `--only` snapshot-loader allowlist (`load_full_run_events`,
`workflow_trace.py:259-261` skips it — safe default; lifting it is a Task-171-adjacent
follow-up). No code-block form for `approval:` (only `batch`/`loop` have code-block routing,
`markdown_parser.py:1183-1203`). **[review-fix]** No `approval` field on the Graph model /
static canvas rendering (GraphNode in `core/workflow/graph/build.py` surfaces `loop`/`batch`
but NOT `approval` in v1 — the visual gate marker is deliberately deferred to the Task
155/176 web-approval work; recorded here so its absence reads as a decision, not a miss). No
path-qualified `--auto-approve` ids — the id namespace is FLAT across the workflow tree (a
child gate with the same node-id as a flagged parent id IS auto-approved); documented in the
guide, path-qualification is 171 territory.

## Boundary inventory **[review-fix]** — every generic catch a gate exception must pass

The gate verdict (`GateDenied` / `GateNotInteractiveError`) is a control-flow signal that must
cross every exception-conversion boundary between the gate and the runner UN-converted. The
codebase has FOUR (the original plan named one — three were found by review; this is the same
boundary class as the historical CompilationError-swallowed-by-continue fix):

| # | Boundary | Fix |
|---|---|---|
| 1 | `WorkflowEngine._execute_node` `except Exception` (`engine.py:1276`) | `except (GateDenied, GateNotInteractiveError): raise` BEFORE it — no `record_trace(error=)`, no error callback, no `mark_node_failed`, no `_pflow_node_id` |
| 2 | `WorkflowExecutor.exec` `except Exception` (`workflow_executor.py:448` → `_child_failure_result` → `error_action` routing) | same re-raise arm BEFORE it — else a nested denial becomes error-routable and `error_action: continue` runs past a human's "no"; the payload diagnostic is flattened to `fallback_summary` |
| 3 | Batch item retry loop (`batch_executor.py:327-343`) + worker arm (`:693-696`) | `retriable = False` on both exception classes — the existing non-retriable re-raise arms then propagate (no batch_executor edit needed beyond the parallel resolver substitution); without it a denied human is RE-PROMPTED per batch retry, then the deny is aggregated into an item error |
| 4 | Runner `except Exception` (`runner.py:185-189`) | dedicated arms BEFORE it: `GateDenied` → `ExecutionResult(success=False, status=DENIED)`; `GateNotInteractiveError` → `ExecutionResult(FAILED)` with its payload diagnostics intact |

Why `GateNotInteractiveError` is exempted everywhere too (not just `GateDenied`): the
post-exec escalation raises it AFTER the node's success was already traced — the generic arm
would emit a second (error) event for the same node, fire a duplicate completion callback,
and `mark_node_failed` would archive a *completed* output into `__failures__`. Exempting it
keeps the node's honest success record; the RUN still fails via boundary 4, and the trailer
still reads `"failed"` via the collector gate-outcome flag (Phase 4).

`KeyboardInterrupt` needs nothing — it is `BaseException` and passes every arm already.

## Architecture in one paragraph

One payload (`GateRequest`), one resolver seam, two engine hook points. A **pre-exec approval
gate** fires in `_execute_node` after the cache-miss decision and before the start callback —
before any trace marker, so a denied node simply never appears in the trace. A **post-exec
escalation check** detects a reserved `escalation` key in a fresh result, lets the node's own
completion trace/callbacks finish normally, then pauses; the human's choice is written into
the node's namespace before the walk's loop-re-entry check reads the store. Resolution is a
plain closure (`__gate_resolver__` in the shared store): the CLI installs a TTY-capable one,
the MCP server installs an auto-approve-only one, absence means non-interactive → a loud,
payload-carrying error. Both hook points emit `gate` trace events; a denied resolution sets a
collector flag that `_determine_trace_status` reads first (the trailer has NO channel from the
runner's status — without the flag a denied run's own trace would say `"success"`).

## New files

| File | Contents |
|---|---|
| `src/pflow/runtime/engine/gate.py` | `GateRequest`, `GateResolution` (frozen dataclasses), `GateDenied`, `GateNotInteractiveError` re-export or definition site per exceptions convention (put the exceptions in `core/exceptions.py` — see Phase 3.1 — and the dataclasses here) |
| `src/pflow/core/workflow/gate_validation.py` | `check_approval_allowed(node_data) -> Optional[str]` (mirrors `loop_validation.py::check_loop_polarity` exactly — module docstring states the two-call-site anti-drift rationale) |
| `src/pflow/execution/gate_prompt.py` | `build_gate_resolver(...)` + the TTY renderers (click lives HERE, never in runtime/) |
| `src/pflow/guide/features/approval.md` | Agent-facing feature doc incl. the agent-operator playbook |
| `docs/how-it-works/approval-gates.mdx` | User doc (+ `docs/docs.json` nav entry, sibling of `"how-it-works/loops"` at `docs.json:124`) |

## The payload

```python
# runtime/engine/gate.py — JSON-native by construction; the SAME dict feeds the TTY
# prompt, the gate trace event, the GateNotInteractiveError diagnostic, and (171) persistence.
@dataclass(frozen=True)
class GateRequest:
    node_id: str
    node_type: str
    kind: Literal["action_approval", "decision_escalation"]
    preview: dict[str, Any]                      # approval: resolved params (str-coerced leaves)
    question: str | None = None                  # escalation only
    options: tuple[dict[str, str], ...] = ()     # escalation: {label, description, tradeoffs?}
    recommendation: str | None = None            # escalation only

@dataclass(frozen=True)
class GateResolution:
    approved: bool                               # escalation: True unless aborted
    resolved_via: Literal["prompt", "flag"]      # 176 adds "ui"
    chosen: str | None = None                    # escalation: option label or free text
    notes: str | None = None                     # escalation: free-text remainder
```

Preview coercion: build from `plan.resolved_params`; coerce non-JSON-native leaves via `str()`
at construction. Do NOT truncate the payload (trace interning dedupes string leaves ≥ 1KB for
free via `_flush_line` → `intern_event_leaves`, `trace_io.py:77-115`); truncate only in the
TTY *renderer*. Payload keys must avoid `RESERVED_LINE_KEYS = {"kind", "id", "seq",
"parent_id", "run_id", "ancestor_path", "port"}` (`trace_io.py:51`) at the event's top level —
nest everything under `"request"`.

## Phase 1 — config plumbing (`approval:` as a hoisted top-level field)

Mirror `prewarm` (the simplest scalar hoisted field) end to end:

1. **Parser**: add `"approval"` to the hoist tuple at `markdown_parser.py:1610`
   (`for top_level_field in ("batch", "loop", "retry", "cache", "prompt_cache", "prewarm")`).
   `- approval: required` arrives as the string `"required"` via `_coerce_yaml_scalar`
   (`markdown_parser.py:904-960`, raw-string fallthrough at `:960`). No code-block routing.
2. **IR schema**: `ir_schema.py` node-properties object (`:245-304`; `additionalProperties:
   False` at `:303` makes this mandatory): `"approval": {"type": "string", "enum":
   ["required"], "description": "Pause for human approval before this step runs"}`.
   `approval: banana` then fails as a validator diagnostic with path `nodes[N].approval`
   (via `validate_ir` → `SchemaValidationError` → `WorkflowValidator._validate_structure`,
   `validator.py:255-262`). **[review-fix]** Add an approval-path arm to `_get_suggestion`
   (`ir_schema.py:582-626`): the likeliest agent mistake is `- approval: true` (YAML-coerces
   to bool), and the generic type-arm would suggest `approval: "true"` — the arm says
   `"The only supported value is 'approval: required'"` for both the bool-type and enum
   failure shapes.
3. **Compiler**: `_extract_approval(node_data) -> bool` mirroring `_extract_prewarm`
   (`compiler.py:675-690` — strict check, `CompilationError(phase="validation",
   suggestion=...)` if present-but-not-"required"); wire `approval=_extract_approval(node_data)`
   into the `NodeConfig(...)` construction at `compiler.py:373-385`.
4. **NodeConfig**: `approval: bool = False` in `runtime/engine/types.py:56-71`.
5. **Batch-host rejection** (Decision 1), one shared rule, two call sites (the
   `check_loop_polarity` pattern, `loop_validation.py:6-19`):
   - `gate_validation.py::check_approval_allowed(node_data)`: returns an error message when
     `node_data.get("approval")` and `node_data.get("batch")` are both present:
     `"approval: is not supported on batch steps — gate the step before or after the batch instead."`
   - Call site A: `data_flow.py`, alongside the batch/loop-exclusion + loop rules
     (`_validate_loop_node_combos` area, `data_flow.py:546-601`) → Diagnostic, so
     `--validate-only` and `pflow save` catch it.
   - Call site B: `compiler.py` `_create_node_and_config` → `CompilationError` (pattern:
     batch+loop exclusion at `compiler.py:356-357`).
   - **[spec-correction]** The spec pointed at validator Step 9; the loop/batch combo rules
     actually live in `data_flow.py` — follow the code, not the spec.
6. **Guide topic hook**: `_node_topics` (`guide/__init__.py:152-176`) — add
   `if node.get("approval") is not None: topics.add("approval")` (matches the existing
   `batch`/`loop`/`retry`/`prewarm` lines).

## Phase 2 — the engine seams (`_execute_node`, `engine.py:994`)

### 2a. Pre-exec approval gate

Placement: after the in-process hash-invalidation check (`:1094-1097`), **before** step 8
`call_start_callback` (`:1100`) and step 8.5 `trace.begin_node` (`:1102-1109`). Consequences
(all intended): cached nodes never gate (early-return at `:1045-1086` is upstream); a denied
node has NO `node.start` marker and NO completion event — it never appears in the trace; the
progress display has no open partial line at prompt time (the previous node's line closed at
its completion).

```
if config.approval:
    request = build approval GateRequest from plan.resolved_params (fallback: static params
              when the node has no templates — plan_node returns resolved_params=None then)
    resolution = _resolve_gate(request, shared)   # helper below
    (emit gate pause event before resolving; emit resolution event after — Phase 4)
    if not resolution.approved: raise GateDenied(request)
```

`_resolve_gate(request, shared)` **[review-fix — no thread guard]**:
```
resolver = shared.get("__gate_resolver__")
if resolver is None:
    raise GateNotInteractiveError(request)
return resolver(request)     # may itself raise GateNotInteractiveError (non-TTY, no flag)
```
Isolation for parallel-batch workers is by RESOLVER SUBSTITUTION, not thread identity
(Decision 12): in the parallel path, next to the `__progress_callback__` buffer swap
(`batch_executor.py:765`), replace `__gate_resolver__` in `item_shared` with
`build_gate_resolver(auto_approve, output_controller=None, parallel_batch=True)` — the
non-prompting configuration. It honors pre-approvals and raises
`GateNotInteractiveError(parallel_batch=True)` otherwise, and because the key is in
`_PROPAGATED_KEYS` the substitution reaches every descendant sub-workflow engine. Sequential
batch items and nested sub-workflows (`workflow_executor.py:436` — synchronous `engine.run`)
inherit the parent resolver and prompt normally. The ONLY `workflow_executor.py` edits are:
`"__gate_resolver__"` in `_PROPAGATED_KEYS` (`:144`) and the boundary-2 re-raise arm (`:448`).

### 2b. Post-exec escalation

Two-point structure inside the non-batch branch (required by cache-write ordering — Decision 10):

1. **Detect** immediately after `action = node._run(store)` (`:1131`), **only when the action
   is a clean success** **[review-fix]** (skip for error actions — step 17.5 pops
   `shared[node_id]` into `__failures__`, and a pause writing a decision afterwards would
   recreate the namespace and break the shared-XOR-failures invariant; skip likewise means
   the api-warning early-return at `:1147-1169` never bypasses a pending pause). Read
   `shared.get(config.node_id, {}).get("result", {}).get("escalation")` with isinstance
   guards at each level (namespaced nodes only — the standard case). **Skip markers that
   already carry a `decision` key** (Decision 13 — idempotency across re-exposure).
   Lenient-but-loud shape ladder **[review-fix]**:
   - dict without `decision` → escalate (missing `question`/`options`/`recommendation`
     render as absent, never crash);
   - non-empty **string** → escalate with the string as `question` (clearly-intended marker);
   - any other truthy value, or an **empty dict** → do NOT pause; write a degrading
     `shared["__warnings__"][node_id]` entry: `"step emitted 'escalation' with an unusable
     shape (<type>) — expected {question, options, recommendation}; the run did NOT pause"`;
   - `result` is a raw string AND `_schema_error` is present in the namespace AND the string
     contains `"escalation"` → same degrading warning ("a schema soft-failure may have
     swallowed an escalation attempt; the run did NOT pause"). The guide REQUIRES
     `output_schema` on escalation-capable claude-code steps.
2. **Skip cache writes** when escalating: gate step 11 `cache_result` (`:1172`) and step 13
   `write_memo_cache` (`:1179-1187`). (Output content never feeds the cache KEY —
   `plan_node` computed it from config + inputs — so no hash concern.)
3. Let steps 12–17.5 run untouched (duration, metrics, `record_trace` at `:1209-1225`,
   `call_completion_callback` at `:1228-1235` — the node's own completion is traced normally,
   and the decision written later stays OUT of the node's trace event because `record_trace`
   reads `shared[node_id]` at call time).
4. **Pause** after `:1235`, before `return action` (`:1274`): build the escalation
   `GateRequest`, same `_resolve_gate` helper, then write the decision INTO the marker
   (Decision 13): `result["escalation"]["decision"] = {"chosen": ..., "notes": ...}` —
   using the already-validated dict reference (string markers: replace the marker with
   `{"question": <string>, "decision": {...}}`), never a bare index into a maybe-absent key.
   The walk's loop-re-entry check (`_run_inner:725-730` → `_loop_should_reenter`) runs AFTER
   `_execute_node` returns, so a `loop:` + carry wiring sees the decision — that's the
   continue mechanism (`${step.result.escalation.decision}` in the re-forked agent's inputs).
   There is no deny for an escalation: the resolver returns a choice (number picks an option
   label; anything else is free text → `chosen=<text>`). Ctrl-C aborts the run (below).
5. **Batch guard** (fail loudly, never silently skip): in the batch branch after
   `execute_batch` (`:1113`), scan `shared[node_id]["results"][i]` (batch output shape:
   `{results, count, ...}`, `batch_executor.py:1062-1066`; each element is the item's
   namespace snapshot — successes only, failed items are error-reported already) for
   UNDECIDED escalation markers (same isinstance ladder; markers carrying `decision` were
   answered inside a sequential sub-workflow item — skip them). Any hit → raise a
   `PflowError` that carries the item index and the question **[review-fix]**:
   `"Step '<id>' raised an escalation from batch item <i> of <n>: \"<question, truncated>\" —
   escalations inside a batch are not supported; restructure so the escalating step runs
   outside the batch."` (Normal failure path, exit 1.)
6. Loop interplay: every iteration passes the full seam (re-entry is an engine-walk
   `continue`, `engine.py:726-729`) — an `approval:` gate prompts EVERY iteration (each
   iteration is a new action; document in the guide), and revisit cache-suppression
   (`enforce_loop_guard` invalidation + memo suppression for `visit_count > 1`) means cache
   hits never skip mid-loop gates. `--only <gated-node>` goes through `_execute_node`
   (`:787`) — the gate fires; fine, the `--only` user is at a TTY.

### 2c. The gate-exception exemptions **[review-fix — see Boundary inventory]**

Insert `except (GateDenied, GateNotInteractiveError): raise` BEFORE the generic
`except Exception` arm at `engine.py:1276` — a gated node must get NO
`record_trace(error=...)`, NO error completion-callback, NO `mark_node_failed`, NO
`_pflow_node_id` (for the post-exec escalation case the node's success record already exists
and must stand un-contradicted). The SAME arm goes into `WorkflowExecutor.exec` before
`workflow_executor.py:448` (boundary 2), and both exception classes set `retriable = False`
(boundary 3). `_run_inner` has no except handler (only `finally`). Both exceptions still pass
through `runner.py:307-329` (harmless: `failed_node` was never set, so no stale annotation;
`_pflow_shared_store` attachment is useful). Emit the gate RESOLUTION trace event (denied /
non-interactive) BEFORE raising, so the collector's gate-outcome flag is set by the time the
CLI's `finally` finalizes the trailer.

## Phase 3 — status, resolver, CLI/MCP surfaces

### 3.1 Exceptions (`core/exceptions.py`)

- `GateDenied(PflowError)` — carries the `GateRequest`. Not agent-remediation-oriented (it's
  a human verdict); message: `"Denied at gate '<node_id>'."`
- `GateNotInteractiveError(PflowError)` — carries the `GateRequest` and a `parallel_batch`
  flag; `retriable = False` on both classes (Decision 11). Its `to_diagnostics()` MUST
  include: the cause ("this run is non-interactive — launched from the web UI, MCP, or a
  pipe; no terminal to prompt on" / "raised inside a parallel batch item"), the full
  `GateRequest` payload as structured data (the operating agent must be able to show its
  human WHAT was about to happen — approving blind defeats the gate; mask secret-like param
  values via `security_utils.mask_sensitive_value` **[review-fix]**), and a
  **surface-aware, truthful remediation ladder** **[review-fix]**:
  - Always first: **"If you are an AI agent: ask your human before continuing — this gate
    exists so a person reviews the action."**
  - Approval gate, not parallel-batch: "With their OK: CLI `--auto-approve=<node-id>`; MCP
    `workflow_execute`: `auto_approve=[\"<node-id>\"]` (approves only this gate)."
  - `parallel_batch=True`: auto-approve DOES work here too (the worker stub honors it) —
    say so, and add the structural fixes: "or move `approval:` to a step outside the batch,
    or set `parallel: false` on the batch."
  - Escalation: "escalations cannot be pre-approved — run interactively, or re-run with the
    answer supplied as a workflow input."
  - Never reference internal task numbers; close with "pflow cannot yet hold a gate open for
    a later answer" instead of "Task 171".
  MCP renders diagnostics verbatim (`execution_service.py:298-311` →
  `RuntimeError(_build_error_text(...))`), so this text reaches the calling agent as-is.

### 3.2 Status ripple (complete consumer map — every site verified)

- `WorkflowStatus.DENIED = "denied"` (`core/workflow/status.py:6-21`; str-Enum, additive).
- Runner **[review-fix — both exceptions]**: dedicated arms in `run()` BEFORE the generic
  `except Exception` (`runner.py:185-189`): `except GateDenied` →
  `ExecutionResult(success=False, status=WorkflowStatus.DENIED, ...)` with a denial
  diagnostic carrying the `GateRequest`; `except GateNotInteractiveError` →
  `ExecutionResult(success=False, status=FAILED, diagnostics=e.to_diagnostics())` (payload
  intact — never through the generic `_exception_to_result` flattening). MUST convert to
  results (not propagate): the CLI's trace finalize at `run.py:340-347` only runs when
  `result` is non-None — propagating would leave an `incomplete` trace. `_determine_status`
  (`runner.py:626-642`) never sees these (exception path) — no change there.
- CLI `_display_execution_result` (`run.py:358-394`): new first branch on
  `result.status is WorkflowStatus.DENIED` → denial output + `ctx.exit(3)`.
  **Denied output is format-aware** **[review-fix]**: text mode → the prose denial line;
  `--output-format json` → a JSON document on stdout
  `{"success": false, "status": "denied", "error": "Denied at gate '<id>'", "gate": {<GateRequest>}}`
  (without this, JSON mode would emit NOTHING on deny — the denied branch bypasses
  `output_error`, which is the only path to the existing JSON emitter). Do NOT route through
  `output_error`/`_emit_failure_tag` (failure rendering). Update the exit-code contract doc
  `cli/CLAUDE.md:142` (0 success/degraded, 1 failed, **3 denied**, 130 interrupted).
- `workflow_output._format_workflow_completion_status` (`workflow_output.py:701-726`):
  ⚠️ falls through to "✓" for unknown statuses — add an explicit `denied` arm.
- **Trailer channel** (⚠️ the trap): `_determine_trace_status` (`workflow_trace.py:1323-1346`)
  derives from trace events only — a denied run would read `"success"`. Fix
  **[review-fix — generalized]**: `record_gate` sets a collector gate-outcome field on
  terminal resolutions: `"denied"` → trailer `"denied"` (checked first);
  `"non_interactive"` → trailer `"failed"` (else a post-exec escalation that failed
  non-interactively would ALSO read "success" — same trap, second door). No literal
  validation exists on write; readers verified safe: `load_full_run_events` skips denied
  (wanted), `run_tailer` forwards verbatim, `RunSelector.tsx` degrades to a neutral dot.
- **Web** **[review-fix — complete list]**: three render sites + CSS, verified via the
  `screenshot-pflow-web-ui` skill: `RunProgress.tsx:23-31` `runBadgeStatus` (falls through to
  a green ✓ — add `"denied"` arm styled like `"stopped"`), `RunProgress.tsx:133` outcome line
  class `run-<status>`, `GraphView.tsx:914-915` run banner `run-banner run-<status>`, and
  `web/src/index.css` needs `run-denied` rules for banner + outcome (neutral/gray family).
- `prompt_cache_analysis/stages/summary.py:383-384` (truncated-label) and
  `prompt_cache_analysis/trace_loading.py:246` (`_non_reusable_outcome_label` says "failed
  run") won't special-case denied traces — accepted cosmetics, note both in the PR.

### 3.3 The resolver (`execution/gate_prompt.py`)

`build_gate_resolver(auto_approve: frozenset[str], output_controller: OutputController | None,
parallel_batch: bool = False) -> Callable[[GateRequest], GateResolution]` — ONE builder,
three configurations (CLI interactive / MCP non-TTY / parallel-batch stub). Behavior:

1. `request.node_id in auto_approve` → approval gates only: `GateResolution(approved=True,
   resolved_via="flag")`. Thread-safe (frozenset lookup) — works in all three
   configurations, including the parallel-batch stub. Escalations NEVER auto-resolve (you
   can't pre-answer an unknown question) — fall through. Note the id namespace is FLAT
   across the workflow tree (documented; see Deferred).
2. Can prompt (**[review-fix]** not `is_interactive()` — that requires stdout TTY and would
   disable gates under `pflow wf | jq`; the gate check is: not print-mode AND
   `output_controller.stdin_tty` AND `output_controller.stderr_tty`) → render + prompt
   (below), `resolved_via="prompt"`.
3. Else → raise `GateNotInteractiveError(request, parallel_batch=parallel_batch)`.

Prompt mechanics: close any open partial line defensively via an OutputController seam
(add a tiny `prepare_for_prompt()` that closes the partial line AND terminates an open
batch-progress `\r` counter line **[review-fix]** — `_handle_batch_progress` rewrites in
place without setting `_partial_line_open`, so sequential-batch prompts would otherwise
overprint it), render to stderr, read via `click.confirm(default=False)` (approval) /
`click.prompt` (escalation). Mask secret-like values in the rendered preview
(`mask_sensitive_value`) **[review-fix]** — the trace event stays unmasked (consistent with
the trace's existing `template_resolutions`).
⚠️ **Ctrl-C trap**: `click.confirm`/`click.prompt` raise `click.exceptions.Abort` — an
`Exception` subclass the engine's generic arm would archive as a node failure. The resolver
MUST catch `Abort` and raise `KeyboardInterrupt` → existing clean path (`runner.py:185`
re-raises; CLI `run.py:322-324` exits 130; incomplete-but-readable trace is documented
expected behavior).

Installation (mirror `__progress_callback__` end-to-end): CLI builds the resolver next to the
progress callback (`run.py:309` area) and threads it into the shared store the same way;
`_PROPAGATED_KEYS` gets `"__gate_resolver__"`. The MCP server installs
`build_gate_resolver(auto_approve, output_controller=None)` — auto-approve works, prompting
never does.

TTY UX (design anchor: `terraform apply`; **show-before-code: mock these exact renderings in
the PR description**):

```text
⏸  Approval required: notify-slack (mcp-composio-slack-SLACK_SEND_MESSAGE)

   channel:        #releases
   markdown_text:  v0.9.0 released with 3 features: …

   Run this step? [y/N]:
```
```text
⏸  Escalation from implement-chunk:
   The plan assumes one config file, but the code has per-env configs.

   1. Merge into one file        — simpler, but breaks env overrides
   2. Template per-env (rec)     — matches existing pattern, more files

   Choose 1-2, or type an answer:
```
```text
✗ Denied at gate 'notify-slack'. Workflow stopped cleanly before the step ran. (exit 3)
✓ Gate 'notify-slack' pre-approved via --auto-approve=notify-slack
```
Long preview values: truncate in the renderer only (e.g. 200 chars + `… (N chars)`).

### 3.4 Flags

- `--auto-approve` (`multiple=True`) in `run.py` → `RunnerConfig.auto_approve:
  tuple[str, ...] = ()` (`execution/result.py:13-32`, frozen, shared CLI/MCP) → runner builds
  the resolver. Unknown node-id in the flag: warn at start, don't fail — match against ALL
  top-level node ids (a child gate id is legitimate but invisible here; phrase as
  "no top-level step named X") with a fuzzy suggestion via
  `core/suggestion_utils.find_similar_items` and the list of gated top-level ids
  **[review-fix]**: `"--auto-approve=notify_slack does not match any top-level step. Did you
  mean 'notify-slack'? Gated steps: notify-slack, deploy."`
- Run-start warning (Decision 4): when the compiled workflow has `approval` NodeConfigs, the
  run cannot prompt, and not all gated ids are in `auto_approve` → one stderr warning that
  carries the consequence and the fix: `"This run is non-interactive and will fail at gate
  'notify-slack' unless pre-approved (--auto-approve=notify-slack)."` **Documented
  limitation** **[review-fix]**: the scan sees top-level NodeConfigs only — a gate that
  exists solely inside a sub-workflow gets no run-start warning and fails at the gate
  (Decision 4 makes fail-at-gate primary, so this is acceptable; say so in the guide).
- MCP: add `auto_approve` as the third `Annotated` param on `workflow_execute`
  (`mcp_server/tools/execution_tools.py:19-28`), thread through
  `ExecutionService.execute_workflow` (`execution_service.py:232`, RunnerConfig at `:283`).

## Phase 4 — `gate` trace events

New `WorkflowTraceCollector.record_gate(...)` flushing via the normal `_flush_line` path
(streaming guards `stream_to_disk`/`_stream_failed` apply; interning free). Two lines per gate:

```jsonc
{"kind": "gate", "phase": "pause",      "node_id": "...", "gate_kind": "action_approval|decision_escalation", "request": {<GateRequest>}}
{"kind": "gate", "phase": "resolution", "node_id": "...", "gate_kind": "...", "resolution": "approved|denied|auto|choice", "resolved_via": "prompt|flag", "decision": {"chosen": ..., "notes": ...}|null}
```

- The pause event is emitted BEFORE prompting; resolution after (and BEFORE raising on
  denied / non-interactive). Round-tripping `request` through JSON must reproduce the
  `GateRequest` — this event IS Task 171's serialization test.
- Terminal resolutions set the collector's gate-outcome field (Phase 3.2 trailer channel):
  `denied` → trailer `"denied"`; `non_interactive` → trailer `"failed"`.
- **[review-fix — CRITICAL]** Gate lines are **DISK-ONLY**, mirroring `node.start` exactly:
  `record_gate` flushes via `_flush_line` but NEVER appends to `self.events` (else the gate
  resolution line becomes the node's "final event" in `final_events_by_node` — it has no
  `node_output`, so `seed_snapshot_into_shared` would silently skip seeding that node and a
  later `--only` run gets unresolved `${node.*}` refs). AND the reconstruct reader MUST learn
  the kind: `_partition_trace_lines` (`core/trace_io.py:130-172`) raises
  `json.JSONDecodeError("unknown trace line kind ...")` on anything outside its closed set —
  without a known-but-ignored `gate` arm (copy the `node.start` arm + comment at
  `trace_io.py:149-154`), EVERY gated run's trace (approved ones included) becomes
  "corrupt": `pflow report` fails, `--only` loses the run as a snapshot source
  (`OnlySnapshotMissingError`), analyze-cache skips it. Test: run a gated+approved workflow,
  then assert `pflow report` renders it and `--only <downstream-node>` can seed from it.
  (Task 171 reads gate lines with its own explicit reader — reconstruct ignoring them is
  correct for v1.) Check `tests/shared/trace_jsonl.py` in case fixtures need the kind.
- Verified tolerant downstream: `run_tailer._handle` ignores unknown kinds
  (`run_tailer.py:573-600`); the web frontend never sees raw kinds. NO tailer arm, NO SSE
  type — observe-only (Decision 2 scope).
- Nested: child engines get `trace_collector=trace_for_child` (`workflow_executor.py:425`) —
  add one integration test asserting a child gate's events land in the run's streamed trace.

## Phase 5 — dry-run parity

**[spec-correction]** The spec's precedent ("Task 166 loop landed with zero plan.py edits")
is false — loop planning added `_annotate_loop_entry` (`plan.py:847-867`); and that annotation
renders NO text (it's a cost multiplier). The rendered-text precedent is `_tag_from_entry`'s
`cache: false` suffix (`plan_formatter.py:304-315`).

1. `PlanEntry.approval: bool = False` (`execution/result.py:107-142`, frozen —
   `dataclasses.replace` stamping, house style).
2. **[review-fix]** Stamp it in the shared `_annotate_loop_entry` funnel (`plan.py:847-867`)
   — LIFTED ABOVE its `loop_config is None` early-return (rename/split so the function's
   name stays honest, e.g. `_annotate_entry`) — because BOTH dispatch paths route every
   entry through it (`plan.py:783/:785/:844`), which covers standard AND sub-workflow
   entries. Stamping only in `_plan_standard_node` would miss gated workflow-type nodes
   (they dispatch to `_plan_sub_workflow`) — a parity lie for a shape the ledger explicitly
   allows. NO new `PlanEntry.status`, NO `_classify`/`_advance` edits (dry-run assumes
   approval; a gate doesn't change routing).
3. Render via `_tag_from_entry`: gated entries show `[<type>, approval]`
   (e.g. `▸ notify-slack  [mcp, approval]`). No cost logic (orthogonal to
   `_format_stats_annotation`). **[review-fix]** Also: (a) add `approval` to
   `_entry_to_dict` (`plan_formatter.py:352-375`) — JSON dry-run and the MCP dry-run
   service are the gate-discovery surface for exactly the agents that need it; (b) one
   footer line when any entry is gated: `"1 step pauses for approval at run time
   (notify-slack); non-interactive runs need --auto-approve=notify-slack"` — makes the
   playbook self-discoverable without the guide.
4. Escalation is invisible to the planner by design (runtime result content) — no annotation,
   record the asymmetry in the guide doc.
5. **Drift pin, mutation-verified** (house style: `tests/test_execution/test_plan_drift.py`,
   e.g. `test_plan_matches_execution_for_fresh_workflow:73` — assert plan entries against an
   engine-side observable from a REAL run): `{entry.node_id for gated plan entries}` ⟺
   `{node_id of gate pause events in the trace}` — **by node-id SET, not count**
   **[review-fix]** (a gated loop node = 1 entry but N pause events). Fixture includes a
   standard gated node AND a gated sub-workflow node (run with `--auto-approve` equivalents
   so the test never prompts) + a JSON-mode assertion on `_entry_to_dict`. Mutation-verify:
   re-fork one side (e.g. stamp `approval=False` in the funnel), confirm the pin fails,
   revert.

## Phase 6 — docs

- `src/pflow/guide/features/approval.md`: syntax, both gate kinds, the escalation `result`
  contract (`{escalation: {question, options: [{label, description, tradeoffs}],
  recommendation}}` — `output_schema` REQUIRED on escalation-capable claude-code steps), the
  continue-via-loop/carry recipe (`${step.result.escalation.decision}`), **the
  agent-operator playbook** (`--dry-run` to discover gates → show the preview to your human
  → run with `--auto-approve=<id>` for the gates they OK'd; never pass the flag without
  asking), **[review-fix] the failure-mode half**: exit code 3 semantics, non-interactive
  behavior + run-start-warning top-level-only limitation, both batch restrictions
  (batch-host `approval:` rejected; batch-item escalation errors; sequential-batch
  sub-workflow gates prompt per item), per-iteration loop prompting, the flat
  `--auto-approve` id namespace across nested workflows, and the MCP `auto_approve`
  parameter.
- **[review-fix]** `guide/core.md:307`: add `approval` to the enumerated top-level node
  controls (`batch, loop, retry, cache, prompt_cache, prewarm`) — agents reading only the
  core guide must learn the field exists.
- `docs/how-it-works/approval-gates.mdx` + `docs.json` nav entry.
- Update `cli/CLAUDE.md:142` (exit code 3) and the relevant engine/runtime CLAUDE.md sections
  (new seam steps, `__gate_resolver__` propagated key, gate event kind, trailer literal).
- `.taskmaster/tasks/task_133/design/d1-event-schema.md`: mark the reserved `gate` kind as
  shipped (pointer only).

## Phase 7 — tests (baseline `make test` + `make check` FIRST — record the delta)

Verification section of task-125.md, concretely:

- **Approval**: gate halts before exec (side-effect file proves node never ran on deny);
  preview shows resolved values; approve → continues; deny → exit 3, trailer `denied`, NO
  `__failures__` entry, node absent from trace; multiple sequential gates; gate on `--only`
  target fires; gate on loop node prompts per iteration; cached node never gates (pin).
- **Escalation** **[review-fix — updated contract]**: dict marker (no `decision`) pauses
  after the node's normal completion trace; decision written INTO the marker
  (`result.escalation.decision`); marker WITH `decision` never re-pauses (idempotency);
  string marker pauses with it as `question`; empty-dict / other-truthy shapes → degrading
  warning, NO pause; string result + `_schema_error` + "escalation" substring → degrading
  warning; absent key never pauses; escalation fires only on clean-success actions
  (error-action + marker: no pause, no shared/`__failures__` invariant break); escalating
  result NOT memo-cached (re-run re-executes); loop+carry round trip
  (`${step.result.escalation.decision}`); `code`-node escalation works; direct-batch item
  escalation → loud `PflowError` carrying item index + question; decided markers in batch
  results do NOT false-fire the scan.
- **Boundary inventory pins** **[review-fix]**: denial inside a sub-workflow → exit 3 /
  DENIED / trailer `denied` / run STOPS even with `error_action: continue`;
  `GateNotInteractiveError` from a nested gate keeps its payload diagnostics through the
  WorkflowExecutor boundary; denial inside a sequential-batch sub-workflow item stops the
  run without re-prompting (`retriable=False` honored by the batch retry loop); post-exec
  escalation non-interactive → single success trace event for the node (no duplicate error
  event, no `__failures__` entry), run FAILED, trailer `failed` via the gate-outcome flag.
- **Non-interactive**: no resolver → `GateNotInteractiveError` with payload in diagnostics;
  parallel-batch worker stub honors `auto_approve` and otherwise raises with
  `parallel_batch=True` + batch-specific remediation; run-start warning fires (and doesn't
  when all gates pre-approved); browser-launch case covered by the non-TTY path
  (`server.py:853-861` `stdin=DEVNULL`); escalation ignores `--auto-approve`.
- **Flags**: `--auto-approve` approves only the named node (second gate still prompts/fails);
  repeatable; unknown id warns with fuzzy suggestion; `resolved_via` correct
  (`flag` vs `prompt`); MCP `auto_approve` works end-to-end (off-main-thread via
  `asyncio.to_thread` — pins the no-thread-guard design).
- **Ctrl-C at prompt**: `Abort` → `KeyboardInterrupt` → exit 130, incomplete-but-readable
  trace (no node failure recorded).
- **Validation**: batch-host `approval:` rejected at `--validate-only` (diagnostic) AND at
  compile (`CompilationError`); `approval: banana` fails schema with path `nodes[N].approval`;
  `approval: true` gets the "only supported value is required" suggestion; `--validate-only`
  accepts a valid gate (no unknown-field noise).
- **Parity**: the mutation-verified drift pin (Phase 5.5, node-id SET comparison, includes a
  gated sub-workflow node); dry-run tag renders; `approval` present in JSON dry-run
  (`_entry_to_dict`) and the footer line renders.
- **Trace** **[review-fix]**: gate events round-trip JSON == payload; gated+APPROVED run
  stays readable post-hoc (`pflow report` works; `--only <downstream>` seeds from it — the
  `_partition_trace_lines` gate arm); `record_gate` never appends to `self.events`;
  child-workflow gate events in the streamed trace; denied trailer literal;
  `load_full_run_events` skips denied traces.
- **MCP parity** (`test_cli_mcp_parity.py`): gated workflow via `workflow_execute` fails
  loudly with the payload-carrying message; `auto_approve` param works.
- **Status ripple**: `_format_workflow_completion_status` denied arm (no ✓); denied JSON
  document emitted in JSON mode (`{"success": false, "status": "denied", ..., "gate": ...}`);
  web denied arms — `runBadgeStatus`, outcome-line class, GraphView banner + `run-denied`
  CSS (screenshot verify); prompt works with stdout piped to a file.

## Edge-case ledger (decided behaviors — do not re-litigate silently)

| Case | Behavior |
|---|---|
| Gate on cached node | Never fires (seam is after cache early-return) — nothing to approve |
| Gate on batch host | Validation + compile error (Decision 1) |
| Escalation from a DIRECT batch item | Loud `PflowError` with item index + question, exit 1 |
| Gate/escalation in sub-workflow (main thread) | Works — resolver propagates in via `_PROPAGATED_KEYS`; verdict propagates OUT via the boundary-2 re-raise (never error-routable) |
| Gate in sub-workflow inside PARALLEL batch | Worker's substituted resolver: `auto_approve` honored; else `GateNotInteractiveError(parallel_batch=True)` with batch-specific remediation |
| Gate in sub-workflow inside SEQUENTIAL batch | Prompts per item (spec's supported surface); a denial stops the WHOLE run cleanly (DENIED, no retry re-prompt via `retriable=False`) |
| Escalation in sub-workflow inside SEQUENTIAL batch | Prompts per item; decided marker skipped by the parent batch scan |
| Node returns error action AND escalation marker | No pause (clean-success gating); normal error handling; marker visible in `__failures__` payload |
| Gate on loop node | Prompts every iteration |
| Gate on `--only` target | Fires (user is at a TTY) |
| Gate on never-reached conditional branch | Never fires; non-TTY run start still warns (Decision 4) |
| Gated run with stdout piped (`\| jq`, `> file`) | Prompts fine (stderr+stdin TTY check — Decision 14) |
| `--auto-approve` with unknown node id | Warn at start with fuzzy suggestion, continue (child gate ids are legitimate but invisible — phrased "top-level") |
| `--auto-approve` naming an escalating node | Ignored for escalation — prompts or fails |
| Same node-id gated in parent and child | FLAT namespace: flag approves both (documented; path-qualification is 171 territory) |
| Ctrl-C at prompt | Exit 130, incomplete trace (documented expected) |
| Denied run as `--only` snapshot source | Skipped by loader allowlist (deliberate; 171 follow-up) |
| APPROVED gated run as `--only` snapshot source | MUST work — pinned by the trace-reader test (Phase 4) |
| Non-namespaced node escalation | Out of v1 contract (standard nodes are namespaced) |
| Workflow-type (sub-workflow) node with `approval:` | Allowed — gates the whole sub-workflow; preview = its inputs; planner stamps it via the shared funnel |
| Malformed escalation marker (empty dict, bool, number) | No pause + degrading warning naming the expected shape |
| Escalation attempt lost to schema soft-fail (string result) | Degrading warning when `_schema_error` present and string mentions "escalation" |

## Implementation order & guardrails

1. Baseline `make test` / `make check` — DONE 2026-07-02: 8283 passed / 0 failed; check green.
2. Phases 1 → 2 → 3 → 4 → 5 → 6, tests as you go (test-as-you-code norm), then Phase 7 gaps.
   **OWNER DIRECTIVE 2026-07-02: implement Phases 1–2 ONLY, then STOP for review.**
3. Re-run `make test` / `make check`; report the delta against the baseline.
4. Run the `/verify` skill on the TTY flow (a real gated workflow in a terminal) — tests
   can't exercise a real prompt.
5. Deep-review battery before the PR; pair `review-silent-failures` +
   `review-impact-completeness` (the pairing that caught the planner-mirror divergence).
6. Do NOT commit/push without explicit instruction (project norm).
