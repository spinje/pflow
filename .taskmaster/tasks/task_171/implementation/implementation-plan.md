# Task 171 Implementation Plan — Durable Resume Tokens & Non-TTY Gates

> Authored 2026-07-04, hardened 2026-07-05 after four verification passes over the live code.
> Every file:line below was verified in THIS worktree (branch `feat/durable-resume-tokens`, from
> main `2e2eb9e8`). Written so an agent can implement it in isolation.
>
> Baseline (captured): the four resume suites green — **165 passed**
> (`tests/test_runtime/test_resume_source.py`, `tests/test_runtime/test_resume_engine.py`,
> `tests/test_cli/test_resume_cli.py`, `tests/test_execution/test_plan_drift.py`).
> Full-suite reference from 164 close: 8489 passed. Re-run and diff at every phase gate.
>
> **Golden rule:** 171 is a thin trigger over 164's substrate. One reader, one source (the
> trace). If any step pressures toward a parallel serialization / walk-entry / seed path — STOP;
> that is the design smell this task is shaped to avoid (issue #504 / PR #505 history).

## Decision Ledger (settled with owner, 2026-07-04)

1. **Paused encoding**: `final_status: "paused"` on the `run.complete` trailer + `paused_node_id`
   + `gate_request` (the `GateRequest.to_dict()` payload). No new line kind.
2. **Gated runs require a trace**: delete the MCP special case — `execute_workflow` streams
   traces like the CLI. `--no-trace` stays an explicit opt-out whose gates keep the hard error.
   Registry single-node probe (`execution_service.py:704`) stays traceless.
3. **Escalation resume**: restore the completed escalating step, fold the `--choose` answer into
   its event, enter at its successor. The agent step is never re-paid.
4. **Pause exit code: 4** (0 success/degraded, 1 failed, 2 usage, 3 denied, 130 interrupt).
5. **Token security**: explicit v1 trust-the-local-filesystem. No signing. Bridges own their own
   auth (ADR-0009).

Plan-level calls (reversible, reasoned here):
- **Deny writes a denied attempt trace** — `--approve no` resumes with a deny-primed resolver →
  `GateDenied` → the EXISTING denied machinery (trace status `denied`, exit 3,
  `_display_denied_result`'s "✗ Denied at gate '<id>'…" message). Rationale: token consumption is
  "a newer attempt exists"; a message-only deny would leave the run pending in `resume list`
  forever. Deliberate deviation from the spec's literal "Workflow cancelled at step X" wording —
  one denied message everywhere beats two near-identical ones; record in the task review.
- **Escalation answers ride `--choose "<label-or-free-text>"`**; `--approve yes|no` stays
  approval-only (ADR-0009's committed verb). `GateRequest`/`GateResolution` dataclasses unchanged
  (125 review: frozen). `resolved_via="flag"` covers durable answers — no new enum value.
- **v1 pause scope = top-level gates only.** Child-workflow gates and parallel-batch gates keep
  today's `failed` (resume-into-child is out of scope; a "paused" trace that can't be resumed
  would be a lie). Enforced by ONE producer-side condition (Phase 1).
- **No side-effect confirm for paused resumes** — the entry node NEVER ran (approval gates fire
  before `node.start`; an escalation's entry is its never-run successor), so there is no re-fire
  risk; `--approve yes` is itself the human's consent. Skip `_confirm_or_refuse_side_effect`
  entirely when the source is paused.

## Architecture (read this before any phase)

Today a non-TTY gate already persists everything except resumability: `record_gate(phase="pause")`
writes the full `GateRequest` to disk (disk-only `kind:"gate"` line, `workflow_trace.py:1211-1248`),
the engine's gate except arm (`engine.py:1430-1477`) stamps `gate_outcome="failed"`, the trailer
reads `failed`, and `load_resume_source` REFUSES via `_raise_gate_stopped_or_generic`
(`workflow_trace.py:578-599`). 171 changes: (a) the engine arm stamps `"paused"` for the durable
case and stashes the pause payload for the trailer; (b) `_determine_trace_status` gains a `paused`
arm; (c) the loader gains a `paused` status arm returning approval → `(paused_node_id, None)` /
escalation → `(None, paused_node_id)` — the SECOND form deliberately reuses 164's existing
between-nodes successor machinery in the CLI; (d) the CLI gains `--approve/--choose/list` and a
PAUSED display branch (exit 4); (e) MCP streams traces and returns the token. Seeding, guards,
re-record self-containment, attempt chains, hash gate, and dry-run planner parity are all
untouched 164 machinery consuming the same `ResumeSource`.

Key vocabulary trap (164 review): trace `node_type` is a CLASS name (`"LLMNode"`);
`is_side_effecting` takes REGISTRY names (`"llm"`). 171 never calls `is_side_effecting` for paused
sources (confirm-skip above) — do not reintroduce it.

---

## Orchestration map — sizing, model tiers, and agent-handoff seams (owner-approved 2026-07-05)

How to staff the phases if implementation is split across agents. Content of the phases lives
below — this section only records the seams and the reasoning that isn't obvious from the
phase text.

| Phase | Diff size | Cognitive load | Model tier |
|---|---|---|---|
| 0 extraction | big (~600 moved) | low — mechanical | small/mid (or same agent as P1, see below) |
| 1 producer | medium | **highest in task** | **big — non-negotiable** |
| 2 loader arm | small | high (164 seams) | big |
| 3 CLI | biggest | mixed (3c subtle; 3a/3e mechanical) | big for core; mid ok for group+list |
| 4 UI | small | low — fully specified | small/mid |
| 5 docs | prose | medium (guide quality) | mid |

**Handoff seams:**
- **After Phase 0 (strong)** — one commit, zero behavior change, mutation-gate passed. The
  incoming agent MUST re-grep symbol locations: the `workflow_trace.py:NNN` refs in Phases 1-3
  describe the pre-extraction file (see braindump staleness warning).
- **After Phase 1 (strongest, most valuable)** — the trace format is frozen; everything after
  CONSUMES the paused trailer. The next agent should build test fixtures from REAL paused
  traces generated here, not synthetic ones (164 review, tests/CLAUDE.md pitfall #19).
- **After Phase 3 (strong)** — feature-complete CLI-side; 4+5 are a downhill glide.
- **Between Phases 2 and 3: DO NOT SPLIT.** They are two sides of one contract
  (`gate_answer` shape ↔ flag parsing; `ResumeAnswerRequiredError` rendering ↔ CLI UX;
  loader-vs-CLI validation split). Different agents on each side invites mid-flight contract
  drift — one agent, one block.
- **Phase 4 may run in PARALLEL with 2+3** (optional): it touches only `ui/`+`web/` — no
  engine/trace collision, so the standing serialize rule doesn't bind. The `resumed_from`
  chain marker doesn't even depend on 171 code (works against 164 traces today); only the
  paused-badge REAL-BROWSER verification needs Phase 1's output. Same branch — a subagent in
  this worktree, never a second worktree.

**Recommended shape:** Agent A (big): 0→1 — doing the extraction itself warms A up on every
symbol Phase 1 builds on, and P1 is the one edit where a plausible "simplification" ships a
latent bug (the id-collision pin exists because the simple version passes every other test).
Agent B (big): 2+3 as one block. Agent C (small/mid): 4, any time after 1. Phase 5 goes to
whoever lands last (docs written from the real diff beat docs written from this plan).
Handoff protocol per switch: outgoing agent updates the progress log; incoming agent reads the
4-doc package (spec → plan → progress log → braindump) before touching code.

---

## Phase 0 — Extract the resume loader to `runtime/resume_source.py` (zero behavior change)

Own commit. The `paused` arm is the third consumer-shaped growth spurt — the extraction trigger
the 164 review deferred on.

**Move from `workflow_trace.py`** (verified spans): the resume section 311–845 — `ResumeSource`
(324-345), `_is_trace_locked` (348-370), `_iter_raw_trace_lines` (373-390),
`_read_trace_meta_line` (393-410), `_dangling_top_level_starts` (413-437),
`_attempt_consumed_work` (440-458), `_raise_resume_source_missing` (461-471),
`_select_resume_trace` (474-508), `_seedable_final_events` (511-529), `_apply_gate_resolutions`
(532-565), `_contains_binary_placeholder` (568-575), `_raise_gate_stopped_or_generic` (578-599),
`_terminal_failure_root` (602-634), `_resolve_resume_entry` (637-676), `_resolve_incomplete_entry`
(679-721), `_guard_seed_scope` (724-765), `load_resume_source` (768-845) — plus
`seed_snapshot_into_shared` (975-1020) and `_SNAPSHOT_RESERVED` (967-972). The seeder and the
guards must share the ONE `_seedable_final_events` derivation (164 invariant: "Seed = the seedable
set, everywhere"), so the cluster moves together. Also move `_trace_recency_key` IF it is only
used by moved code — verify; `_iter_workflow_traces` uses it too, so more likely it STAYS and is
imported.

**Stays in `workflow_trace.py`**: `_iter_workflow_traces` (121-160 — shared with cache-analysis
autoload, `core/prompt_cache_analysis/trace_loading.py:220`), `final_events_by_node`,
`_unrecovered_failed_node_ids`, `load_snapshot_or_raise`, `load_full_run_events`, the collector.
`resume_source.py` imports these FROM `workflow_trace`. Preserve both invariants verbatim:
`_iter_workflow_traces` never gains a `final_status` filter; `runtime/` never imports `ui/`
(keep the duplicated `_is_trace_locked` — its docstring explains why).

**Import updates** (verified complete fan-out — only 3 production symbols cross boundaries):
`cli/commands/resume.py` (`load_resume_source` at :90, `ResumeSource` TYPE_CHECKING at :32),
`execution/runner.py` (`ResumeSource` TYPE_CHECKING at :36), `runtime/engine/engine.py:571`
(`seed_snapshot_into_shared`). Test imports: `test_resume_source.py:36`, `test_resume_engine.py:34`,
`test_resume_cli.py`. Every other moved helper is imported ONLY by those tests.

**Gate**: full `make test` + `make check` green with ZERO test-logic edits beyond import paths.
Then mutation-verify the parity net still bites post-move: temporarily re-fork the engine's
walk-entry call (Edit + revert, never stash) and confirm
`test_engine_and_planner_walk_entry_state_match` alone fails.

## Phase 1 — Producer: paused trailer, PAUSED status, exit 4, MCP flip

### 1a. Engine gate except arm — the ONLY producer decision point

**The pause is a PROMISE**: every `paused` stamp emits a token the resume path must accept.
Deep-review (2026-07-05) found two ways the first draft broke that promise — a node-id
collision across the parent/child boundary could smuggle a child gate into `paused`, and an
escalation on a loop/`code`/terminal node produced a token the CLI then refuses. Both are
closed at the producer, below.

**Prerequisite — explicit nesting flag** (replaces the id-comparison heuristic entirely):
`WorkflowEngine.__init__` gains `nested: bool = False`. There are exactly TWO instantiation
sites (verified): `execution/runner.py:335` (root — omits it) and
`runtime/workflow_executor.py:433` (child — passes `nested=True`). Node ids are author-chosen
and NOT unique across the parent/child boundary (`review`/`approve` collide easily), so
`request.node_id == config.node_id` is NOT a safe top-level test — do not use it.

`engine.py:1430-1477`. Today line 1441:
```python
self.trace.gate_outcome = "denied" if isinstance(gate_exc, GateDenied) else "failed"
```
Replace with (pause-payload stash included):
```python
originating = not getattr(gate_exc, "_pflow_gate_seen", False)
gate_exc._pflow_gate_seen = True   # first arm to see it = the level where it fired
if isinstance(gate_exc, GateDenied):
    self.trace.gate_outcome = "denied"
elif (
    isinstance(gate_exc, GateNotInteractiveError)
    and not gate_exc.parallel_batch
    and originating
    and not self.nested
    and _gate_pausable(gate_exc.request, config, node, action)
):
    self.trace.gate_outcome = "paused"
    self.trace.pause_request = {
        "paused_node_id": gate_exc.request.node_id,
        "gate_request": gate_exc.request.to_dict(),
    }
else:
    self.trace.gate_outcome = "failed"
```
with a small module helper (comment each clause with its resume-side twin):
```python
def _gate_pausable(request, config, node, action) -> bool:
    """Only stamp paused when the resume path can honor the token (pause = promise).

    Approvals always resume (entry = the gated node, which never ran). Escalations
    resume at the successor, so they are pausable only when that successor is
    resolvable — mirrors the CLI's _resolve_between_nodes_entry refusals.
    """
    if request.kind == GATE_KIND_APPROVAL:
        return True
    return (
        config.loop_config is None                     # loop re-entry is engine-ephemeral
        and config.node_type_name != "PythonCodeNode"  # dynamic router (CLI refuses "code")
        and str(action or "") != "end"                 # terminal action: nothing left to run
        and node.successors.get("default") is not None # exactly-one default successor
    )
```
Why this exact condition (verified semantics — encode in comments):
- `parallel_batch` exists ONLY on `GateNotInteractiveError` (`exceptions.py:1004-1006`); it is
  `True` for parallel-batch-worker gates → those stay `failed` (v1 scope). The isinstance guard
  short-circuits before the attribute access for `GateDenied`/`GateResolverError`.
- `originating ∧ not self.nested` = "the ROOT engine caught it first-hand" — the only situation
  that is a top-level gate. Covers every propagation shape with no id comparison: a NEW-path
  child gate originates in a `nested=True` engine (tagged there, excluded); an OLD-path/batch
  child gate likewise (child engines come from the ONE `workflow_executor.py:433` site); by the
  time the exception reaches the root arm it is already tagged → `failed` at the root. A
  legitimate approval on a batch HOST node fires at step 7.5 in the ROOT engine (before
  `execute_batch`) → originating ∧ not nested → pauses, as intended. Tagging the exception
  object mirrors the established `_pflow_node_id` annotation pattern; `retriable=False` on all
  three gate exceptions means no retry loop re-enters the arm.
- `_gate_pausable` escalation clauses mirror the CLI refusal arms (`resume.py:203/215/226`)
  KIND-for-kind so the producer never emits a token `_resolve_between_nodes_entry` bounces.
  `action` is always bound on the escalation path (escalations fire at 17.7, post-exec, and only
  on clean-success actions — engine.py:93,1314); the approval early-return keeps the arm safe at
  step 7.5 where `action` is not yet assigned. Verify the exact code-node CLASS name at edit
  time (registry name is `"code"`; the engine sees class names — the two-vocabularies trap).
  The CLI-side refusals STAY (belt-and-braces: the workflow can change between pause and
  resume; the hash gate + `--force` path can still reach them).
- `GateResolverError` (a resolver BUG) falls to `else` → `failed`. Never paused.
- `record_gate`'s own `gate_outcome` writes (`workflow_trace.py:1233-1236`) run BEFORE the raise
  reaches this arm, so the arm's stamp always wins — `record_gate` is NOT modified.

Everything else in the arm (host-frame event recording at 1461-1476, the bare `raise`) is
untouched. The four generic-except boundaries that re-raise gate exceptions stay untouched.

### 1b. Collector: `pause_request` + status + trailer + version + `trace_path`

`workflow_trace.py`:
- `__init__` (~1209, beside `gate_outcome`): `self.pause_request: dict[str, Any] | None = None`.
- `_determine_trace_status` (1953-1991): insert between the denied arm (1970-1971) and the failed
  arm (1972-1973):
  ```python
  if self.gate_outcome == "paused":
      return "paused"
  ```
- `_aggregates` (1603-1633): after the existing conditional keys (pattern at 1627-1632):
  ```python
  if final_status == "paused" and self.pause_request is not None:
      agg.update(self.pause_request)
  ```
  (emits `paused_node_id` + `gate_request` on the trailer; `final_status` is already computed at
  line 1610). These keys round-trip generically — `reconstruct_trace_from_lines` copies every
  non-`kind` trailer key verbatim (`trace_io.py:241`); neither collides with
  `RESERVED_LINE_KEYS` (`trace_io.py:55`). Do NOT add them to `META_KEYS` — they are end-of-run
  data and belong on the trailer.
- `TRACE_FORMAT_VERSION` (`workflow_trace.py:47`): `"2.6.0"` → `"2.7.0"`. Additive — all five
  consumers gate on `startswith("2.")` (verified list: workflow_trace.py:156,
  trace_report.py:610, diagnose.py:38, trace_loading.py:166; trace_tree.py:100 has no gate).
  Known exact-match consumers to update WITH the bump (deep-review S):
  `tests/test_runtime/test_trace_format_2_2.py:27` asserts `== "2.6.0"`, and the format-history
  comment block at `workflow_trace.py:40-47` gets a 2.7.0 entry.
- Add a `trace_path` property returning `self._stream_path` — fixes a verified latent bug: all
  four `hasattr(result.trace, "trace_path")` guards in `mcp_server/services/execution_service.py`
  (lines 66-69, 151-153, 314-316, 755-757) are always-False today because no such attribute
  exists. One line + one test.
- `has_resumable_step` (1993-2018): NO change needed — line 2016 (`!= "failed"`) already returns
  False for `paused`, which correctly suppresses the failure resume-hint and JSON
  `resume_command`. Pin with a test, don't edit.

Atomicity stance (record in the code where the trailer is written): the pause trailer is one
appended+flushed JSONL line. A kill mid-write leaves a truncated final line, which
`load_trace_file` tolerates as a missing trailer → status reads `incomplete` → 164's interrupted
arm still resumes the run (the gate pause line is earlier in the file and survives). Graceful
degradation IS the crash story — do NOT build fsync/rename machinery. Add the degradation test.

### 1c. `WorkflowStatus.PAUSED` + runner mapping

- `core/workflow/status.py` (enum at :6-26): add `PAUSED = "paused"`; document exit 4 in the
  docstring beside DENIED's exit-3 note.
- `execution/runner.py::_exception_to_result` (808-870; decisive line 863): replace the two-way
  with:
  ```python
  if isinstance(exception, GateDenied):
      status = WorkflowStatus.DENIED
  elif (
      isinstance(exception, GateNotInteractiveError)
      and trace_collector is not None
      and trace_collector.gate_outcome == "paused"
  ):
      status = WorkflowStatus.PAUSED
  else:
      status = WorkflowStatus.FAILED
  ```
  `trace_collector.gate_outcome == "paused"` already encodes top-level + non-batch + pausable
  (engine decided). KEEP `success=False` for PAUSED.

  Final rule (implement THIS): the `elif` above ALSO requires `trace_enabled`. **Plumbing note
  (deep-review W1): `_exception_to_result` does NOT have `config` in scope** — its signature is
  `(self, exception, start_time, trace_collector, validation_warnings=None)` (runner.py:808).
  Thread it from the sole call site, `runner.py:224` (inside `run()`, where `config` is live):
  add a `trace_enabled: bool` parameter (or pass `config`) — do not reference a name that isn't
  there.

  **Both durability gates are required and non-redundant — comment this at both sites**
  (deep-review confirmed): the runner's `trace_enabled` conjunct is the ONLY defense for
  `--no-trace` (the stream is never opened, so no I/O fault ever sets `_stream_failed` — the
  display check passes and a bogus token would print for a trace that does not exist); the
  display's `_stream_failed` check (1d) is the ONLY defense for a mid-run disk fault (config
  said streaming, the file died anyway). With the runner gate, `--no-trace` + gate → FAILED
  end-to-end (identical to today); the in-memory `gate_outcome="paused"` is then unread —
  harmless.

### 1d. CLI display: PAUSED branch, exit 4, token emission

`cli/commands/run.py::_display_execution_result` (508-553). Insert a PAUSED branch between the
DENIED branch (520-525) and the success branch:
```python
if result.status is WorkflowStatus.PAUSED and _durable_pause(result):
    _display_paused_result(ctx, result, output_format)
    ctx.exit(4)
```
- `_durable_pause(result)`: `result.trace is not None and not result.trace._stream_failed`
  (the same accepted single-consumer private read as `_resumable_execution_id`, run.py:570 — cite
  it in a comment). If the stream died mid-run there is no durable trailer → fall THROUGH to the
  existing failed branch (exit 1) so we never print a token that doesn't resolve.
- `_display_paused_result` (new, model on `_display_denied_result` at 455-497):
  - Pull `node_id` + `kind` from `result.trace.pause_request` (`gate_request["kind"]`;
    `GATE_KIND_APPROVAL = "action_approval"`, `GATE_KIND_ESCALATION = "decision_escalation"`,
    `core/gate.py:25-26`).
  - Text mode: ONE stdout line (the parseable token — stdout even under `-p`; the token IS the
    paused run's data): `Paused at '<node_id>'. Resume token: <execution_id> (exit 4)` — the
    in-band exit code mirrors denied's `(exit 3)` (run.py:492). Then, on stderr (like
    `_maybe_echo_resume_hint`, run.py:391, so it survives `-p`):
    **the gate CONTENT — an agent must be able to compose the answer from this output alone,
    no blind round-trip** (deep-review W: JSON and MCP carry `gate_request`; text must too).
    Render by reusing the blocking-prompt renderers from `execution/gate_prompt.py` — approval:
    the `masked_preview`/`_format_preview` param block; escalation: the question + numbered
    options with the recommendation marked (`_echo_options`' exact label extraction, so
    `--choose N` maps to what was shown). Export/adapt those helpers rather than re-rendering
    (one render shape across prompt, pause output, and `ResumeAnswerRequiredError`). Close with
    the exact answer command — approval:
    `To answer: pflow resume <execution_id> --approve yes|no`, escalation:
    `To answer: pflow resume <execution_id> --choose "<answer or option number>"`.
  - JSON mode: one stdout document:
    `{"success": false, "status": "paused", "execution_id": ..., "paused_node_id": ...,
    "gate_request": {...}, "resume_command": ..., "errors": [], "diagnostics": []}`.
    The empty `errors`/`diagnostics` arrays are REQUIRED (deep-review W): the denied JSON doc
    deliberately standardized the `success:false` shape ("agents that branch on success==false
    and iterate .diagnostics/.errors must find the denial there" — its own comment); a paused
    doc without them breaks every generic `success:false` handler.
- Fall-through when `_durable_pause` is False (mid-run stream fault): render through the failed
  branch with the status NORMALIZED to failed in the emitted document/text — a `success:false`
  exit-1 error doc must not claim `"status": "paused"` (deep-review S). One-line override where
  `output_error` receives the result.
- The trace-finalize-in-`finally` ordering (run.py:345-353) already handles "JSON printed before
  finalize" — the paused document reads from the in-memory collector, same as
  `_resumable_execution_id`. `ctx.exit(4)` raises `click.Exit` which the finally still runs.
- `_maybe_echo_resume_hint` (356-391): add `or result.status is WorkflowStatus.PAUSED` to the
  early-return at 374 (belt and braces beside the `has_resumable_step` suppression).

### 1e. MCP: trace flip + paused result + token

`mcp_server/services/execution_service.py`:
- Line 292: `RunnerConfig(trace_enabled=False)` → `RunnerConfig()`. Rewrite the 4-line Task-172
  comment (288-291): MCP now streams (Task 171: a durable gate pause needs the trace); registry
  probe below stays traceless. Runner opens the stream (`runner.py:186`) and finalizes it
  (`finalize_trace=True` default, `runner.py:226-236`) — MCP does no post-run trace mutation, so
  runner-owned finalize is correct; each call gets a complete closed file. Concurrency is safe:
  per-call collector + microsecond filename (`format_trace_filename`, workflow_trace.py:50-82).
  Registry probe at :704 unchanged.
- `execute_workflow` (returns `str`): today success → `format_success_as_text(...)` (:307),
  failure → `raise RuntimeError(_build_error_text(...))` (:317). Add a paused branch BEFORE the
  failure branch: `if result.status is WorkflowStatus.PAUSED:` return a text block built from a
  new `_format_paused_result(result)` dict (model on `_format_success_result`, :31-80):
  `status: "paused"`, `execution_id`, `paused_node_id`, `gate_request` (rendered), `trace_path`
  (now real, via the new property), and `resume_command`. The requirement "the token in its
  structured result" is satisfied by these labeled fields in the text (this surface is
  text-by-design; keep it grep-parseable: one `key: value` per line for the scalar fields).
- Add `execution_id` to `_format_success_result`'s dict too (one line — the field already exists
  on the collector; success responses gain run identity for free).
- Zero MCP tests assert no-trace (verified sweep) — the autouse `_open_stream` monkeypatch
  (`tests/conftest.py:284`) keeps the whole suite write-free regardless of `trace_enabled`; only
  `trace_files`-marked tests write. Optionally refresh the stale helper comment at
  `test_cli_mcp_parity.py:51-54`.

### 1f. Stale-message updates (the pre-171 wording this feature obsoletes)

- `core/exceptions.py:1033` — `GateNotInteractiveError.to_diagnostics()` suggestion "pflow cannot
  yet hold a gate open for a later answer." → replace with: gates pause durably when tracing is
  on; this error now means tracing was explicitly disabled (`--no-trace`) or the gate is in an
  unsupported position (parallel batch item / sub-workflow child / loop- or code-node
  escalation). **The suggestion must NAME `--no-trace` as the removable blocker** (deep-review S:
  the `__init__` headline "launched from the web UI, MCP, or a pipe" stays true but post-171
  those surfaces normally PAUSE — without the explicit `--no-trace` pointer an agent reads the
  headline as "gates don't work here" instead of "drop the flag"). Keep `--auto-approve` remedy.
- `gate_prompt.py:11-12` module docstring: "otherwise raises the payload-carrying
  GateNotInteractiveError" → note the durable-pause path (raise still happens; the TRACE now
  records paused).

**Phase-1 gate**: e2e — real approval-gated workflow, non-TTY run → trace ends
`final_status:"paused"` + `paused_node_id` + `gate_request`; exit 4; token on stdout; JSON doc
fields; MCP paused text carries token; `--no-trace` gate → exit 1 + updated message; child-gate
and parallel-batch-gate runs still end `failed`; denied unchanged (exit 3); torn-trailer
degradation test.

## Phase 2 — Loader: the `paused` arm + answer fold

All in `runtime/resume_source.py`. The planner consumes the same `ResumeSource`
(`execution/plan.py::_resolve_walk_start`), so engine↔planner parity holds by construction — but
pin it (tests below).

### 2a. `ResumeSource` fields

Add (default `None`, populated only by the paused arm):
```python
paused_node_id: str | None = None
gate_request: dict[str, Any] | None = None
```
Gate kind is read as `gate_request["kind"]` — do NOT add a separate kind field (one source of
truth; the payload is the seam, ADR-0009).

### 2b. `load_resume_source` signature + flow

New keyword: `gate_answer: dict[str, Any] | None = None`. Shapes the CLI passes:
- `{"approve": True}` / `{"approve": False}` (from `--approve yes|no`)
- `{"chosen": "<answer>", "notes": None}` (from `--choose`)
The loader validates compatibility; unrelated (non-paused) sources REJECT a non-None answer
(see 2e).

### 2c. `_resolve_resume_entry` paused arm

Insert BEFORE the `final_status != "failed"` catch-all (line 657 pre-extraction). The trailer
keys arrive on `data` (flat dict — `trace_io.py:241` merge):
```python
if final_status == "paused":
    paused_node_id = data.get("paused_node_id")
    gate_request = data.get("gate_request")
    if not isinstance(paused_node_id, str) or not isinstance(gate_request, dict):
        raise ResumeNotResumableError(  # corrupt/hand-edited pause
            "This run is marked paused but carries no pause record.",
            execution_id=execution_id, trace_path=str(path),
            suggestions=["Re-run the workflow from the start."])
    if gate_request.get("kind") == GATE_KIND_ESCALATION:
        return None, paused_node_id      # between-nodes: CLI resolves the successor
    return paused_node_id, None          # approval: the gated node never ran
```
`_resolve_resume_entry` cannot return the gate payload through its 2-tuple — `load_resume_source`
re-reads `data.get("paused_node_id")/("gate_request")` when building the `ResumeSource` (set both
fields iff `final_status == "paused"`). Keep the function's 2-tuple contract unchanged.

Why the entry forms are correct (encode as comments + tests):
- Approval: the gate fires at engine step 7.5, BEFORE `call_start_callback` (engine.py:1229) and
  `begin_node` (engine.py:1237) — the gated node has NO `node.start` and NO event in the trace
  (verified), so `_seedable_final_events(events, entry)` provably excludes it and the seed-scope
  guards compose with zero changes (the 164 invariant).
- Escalation: the node's `success=True` event IS in the trace (recorded at step 16 before the
  17.7 raise). Entry `(None, paused_node_id)` is exactly the shape 164's incomplete arm returns
  for "killed between nodes" — the CLI's existing successor resolution takes over. Escalations
  fire only on `_CLEAN_SUCCESS_ACTIONS` (`{"", "default", "end"}`, engine.py:93,1314), so when a
  successor exists it is the single default one.

### 2d. Answer validation + escalation fold (in `load_resume_source`)

After `_resolve_resume_entry`, before `_apply_gate_resolutions`:
- **Paused + no answer** → new typed refusal `ResumeAnswerRequiredError` (see 2f) rendering the
  pending question/options/preview and the exact command. This must fire BEFORE
  `_guard_seed_scope`, which would otherwise refuse an unanswered paused escalation with the
  WRONG message ("unresolved escalation … Re-run the workflow").
- **Kind/answer mismatch** (`--choose` on an approval, `--approve` on an escalation) → the same
  `ResumeAnswerRequiredError` with a message naming the right flag.
- **Escalation + `{"chosen": ...}`**: after `_apply_gate_resolutions(path, events)` (which folds
  any PRIOR resolved gates), fold the answer into the paused node's FINAL event using the
  identical marker shape. Extract the per-event fold from `_apply_gate_resolutions`'s loop body
  into a module helper:
  ```python
  def _fold_decision_into_event(event: dict[str, Any] | None, decision: dict[str, Any]) -> None:
      # dict marker gains ["decision"]; non-empty string marker becomes
      # {"question": marker, "decision": decision} — mirrors run_escalation_gate's write shape
  ```
  used by BOTH `_apply_gate_resolutions` (existing behavior, refactor-in-place) and the paused
  fold (`_fold_decision_into_event(final_events_by_node(events).get(paused_node_id),
  {"chosen": ..., "notes": ...})`). One shape, two callers — no drift. After the fold,
  `_guard_seed_scope` sees a decided marker (passes), seeding writes the decided marker into
  `shared`, and the engine's re-record loop (`engine.py:895-906`) writes it into the attempt
  trace — self-containment for resume-of-a-resume with zero new code.
- **Approval + `{"approve": ...}`**: no fold — the answer is delivered via the resolver (Phase 3).
  The loader only records that an answer exists (validation passed).

Everything else in `load_resume_source` — inline refusal, live-lock (`ResumeStillRunningError`),
superseded scan (status-agnostic `_attempt_consumed_work`, verified it treats a FAILED attempt
that ran ≥1 real step as consuming), `_guard_seed_scope` — applies to paused sources UNCHANGED
and in the existing order. Note: a paused trace is finalized+closed, so its own flock is never
held; the live-lock arm simply never fires for it (no code change).

### 2e. Non-paused source + answer flags

If `gate_answer is not None` and `final_status != "paused"`: raise `ResumeAnswerRequiredError`
variant: "This run is not paused at a gate — resume it without --approve/--choose." (Loader-side
so by-exec-id and by-name behave identically.)

### 2f. New exception

`core/exceptions.py`: `class ResumeAnswerRequiredError(ResumeSourceError)` — carries
`gate_request: dict`, `execution_id`, `trace_path`, plus a `mode` message discriminator
(missing-answer / wrong-flag / not-paused). `to_diagnostics()` renders: the gate kind, the
question or the `masked_preview` of an approval's params (reuse `core/gate.py::masked_preview`,
104-125 — never raw params), numbered option labels with the recommendation marked, and the
exact resume command with the real execution id. Follow the structure of the existing 9
`ResumeSourceError` subclasses (same file) — agent-actionable, suggestions list, no raw payload
dumps.

**Phase-2 gate**: loader unit tests (paused-approval entry, paused-escalation entry, corrupt
pause record, missing/mismatched/superfluous answer, fold-then-guard ordering, decided-marker
re-record) + the real-collector keystone (below).

## Phase 3 — CLI: group restructure, `--approve`, `--choose`, `resume list`

### 3a. Group restructure (precedent: `PflowCLI`, `cli/main.py:18-96`)

`resume_cmd` is a flat `@click.command` whose `nargs=-1 UNPROCESSED args` rejects stray flags
(`_split_target_and_params`, resume.py:43-60) — `list` would parse as a TARGET. Restructure:
```python
class ResumeGroup(click.Group):
    def resolve_command(self, ctx, args):
        if args and args[0] in self.commands:
            return super().resolve_command(ctx, args)
        return "run", self.get_command(ctx, "run"), args   # default: resume-a-run
```
- `resume` becomes `@click.group(cls=ResumeGroup, invoke_without_command=False, ...)` with two
  subcommands: `run` (hidden=True — the current `resume_cmd` body, all existing options intact)
  and `list`. `pflow resume <target> [flags]` routes to `run` unchanged;
  `pflow resume list` routes to `list`. Registration in `cli/main.py:155` stays
  `cli.add_command(resume)`.
- **Group help must ENUMERATE the answer flags** (deep-review W): a `hidden=True` subcommand
  contributes NOTHING to `pflow resume --help`, so without explicit help text an agent can
  never discover `--approve`/`--choose` from the CLI. The group docstring/epilog must show:
  the `<target> [KEY=VALUE]...` default form with its flag inventory (`--approve yes|no`,
  `--choose "<answer>"`, `--force`, `--dry-run`, `--auto-approve`, …), the `list` form, and
  one worked example of answering a paused gate. This help IS the discoverability surface —
  exit 4 + the stderr hint are otherwise the only way the flags are ever learned.
- Document (help text): a workflow literally named `list` must be resumed by execution id.

### 3b. `--approve` / `--choose` on the default subcommand

New options: `--approve` `click.Choice(["yes", "no"])`, default None; `--choose` `str`, default
None. Validation in the command body: both given → `click.UsageError`. Build
`gate_answer` (`{"approve": bool}` / `{"chosen": choose, "notes": None}`) and pass to
`load_resume_source(..., gate_answer=gate_answer)`. **Threading note (deep-review S1): the real
`load_resume_source` calls live inside `_load_source_and_workflow` — THREE call sites
(resume.py:94, 111, 115), not in `resume_cmd` — thread `gate_answer` through all of them.**
Numeric `--choose` values map to option labels exactly like the blocking prompt
(`_prompt_escalation`, gate_prompt.py:127-130: digit in 1..len(options) → that option's label,
else free text) — and mirror `_echo_options`' label EXTRACTION
(`option.get("label") or f"option {i}"`, gate_prompt.py:133-147), not raw indexing into the
option dicts (deep-review S2): `to_dict()` gives `options` as `list[dict]`.

### 3c. Delivery of the approval answer (resolver priming)

- `--approve yes`: append `source.paused_node_id` to the `auto_approve` tuple that
  `_dispatch_resume` already threads (`ctx.obj["auto_approve"]`, resume.py:332 →
  `_prepare_gate_resolver`, run.py:412 → `build_gate_resolver`, gate_prompt.py:49-69). The gate
  re-fires at engine step 7.5 in the resume run and resolves
  `GateResolution(approved=True, resolved_via="flag")` — an honest approved resolution line in
  the attempt trace. Known cosmetic tradeoff (accepted): `_echo_auto_approved` prints
  "pre-approved via --auto-approve=<id>" — truthful mechanism, slightly different flag than
  typed; do not fork the message.
- `--approve no`: extend `build_gate_resolver` with `deny: frozenset[str] = frozenset()`
  (keyword-only). First check in the resolver, before the auto-approve check:
  ```python
  if request.kind == GATE_KIND_APPROVAL and request.node_id in deny:
      return GateResolution(approved=False, resolved_via="flag")
  ```
  Thread: new `ctx.obj["gate_deny"]` (default `()` — set it in BOTH `_dispatch_resume` and
  wherever run.py builds ctx.obj for normal runs, defaulting empty) → `_prepare_gate_resolver`
  reads `frozenset(ctx.obj.get("gate_deny") or ())` → `build_gate_resolver(auto_approve,
  output_controller, deny=deny)`. `run_approval_gate` (engine/gate.py:98-100) then records the
  `denied` resolution line and raises `GateDenied` → denied attempt trace, exit 3,
  `_display_denied_result` names the gate. The paused token is consumed (the denied attempt ran
  0 steps… **CAREFUL**: a denied attempt executes ZERO nodes — `_attempt_consumed_work` would
  call it a DEAD attempt and NOT supersede the source! Verify and close: the denied attempt's
  trace contains only restored re-records + gate lines, no fresh top-level event, no dangling
  start. FIX (small, principled): `_attempt_consumed_work` gains TWO clauses — an attempt
  consumed the chain when EITHER
  (a) its trace carries a gate RESOLUTION line (`kind:"gate"`, `phase:"resolution"`, resolution
  `"denied"`/`"approved"`/`"choice"` — NOT `"non_interactive"`/`"error"`): a human delivered a
  verdict through it (read via the existing `_iter_raw_trace_lines`); OR
  (b) `candidate.get("final_status") == "paused"`: it reached a gate — the chain frontier moved
  to it (the candidate dict is already loaded; zero extra IO).
  Clause (b) closes two deep-review-verified holes with one rule:
  - **First-node pause invisible to by-name resume** (review-plan W2): a run paused at an
    approval on its FIRST node has zero events and no dangling start — without (b),
    `_select_resume_trace`'s workflow-name skip rule (workflow_trace.py:488) calls it dead and
    skips it, so `pflow resume <workflow>` misses the pause (or silently picks an older failed
    run). With (b), the same shared predicate keeps it selectable — no second rule.
  - **Chain fork via a restored-only paused attempt**: attempt B (`resumed_from` A) that pauses
    at a gate before executing any fresh node (e.g. an answered escalation whose successor is
    itself approval-gated) is all-restored events + a pause line — without (b) it never
    supersedes A, `resume list` shows BOTH A and B, and answering A again forks the chain.
  Pins: double-deny (second `--approve no` on the same token → `ResumeSupersededError`),
  first-node-pause by-name selection, paused-attempt-supersedes-source. Clause (a) also covers
  the approve-then-crash-before-K race (verdict recorded, no step ran); excluding
  `non_interactive`/`error` keeps a no-verdict re-pause or resolver bug from wedging the chain.
- **`--approve no` + `--auto-approve <same-node>`** is contradictory input: raise
  `click.UsageError` naming both flags (deep-review suggestion; deny-first would silently win
  otherwise).
- `--choose`: NO resolver involvement — the answer went through the loader fold (Phase 2d). The
  restored escalating node never re-fires its gate.
- Skip `_confirm_or_refuse_side_effect` (resume.py:238-286) when `source.paused_node_id is not
  None` (see ledger rationale). Hash gate (`_check_content_hash`, resume.py:118-133) and
  `--force` semantics unchanged and APPLY to paused resumes.

### 3d. Successor resolution for escalations (reuse, parameterized message)

`_resolve_between_nodes_entry` (resume.py:181-235) runs as-is for the `(None, paused_node_id)`
shape — same code path as the incomplete arm, including the code-node/loop-node refusals.
**These refusals are now unreachable for honestly-issued tokens by construction** — Phase 1a's
`_gate_pausable` never emits a token for loop/`code`/terminal escalations (deep-review Critical:
the two halves must agree — pause is a promise). They STAY as belt-and-braces for the one path
that can still reach them: the workflow was EDITED between pause and resume (hash gate +
`--force`). ONE change:
parameterize its refusal-message prefix (currently "The run was interrupted after step
'{last}'…") with a `context` arg so paused refusals read "The run is paused after step
'{last}'…"; the terminal-step case (zero default successors, verified it returns `None` from
`_single_default_successor` and raises the "ambiguous" refusal) gets a paused-specific line:
"…was the final step — its answer has nothing left to run. Re-run the workflow if the decision
should change its outputs." v1 refuses this case; do NOT build a fold-and-complete path.

### 3e. `resume list`

New subcommand, options: `--output-format [text|json]`. Implementation lives in
`runtime/resume_source.py` as `list_paused_runs(debug_dir: Path | None = None) ->
list[PausedRun]` (a small frozen dataclass: `execution_id`, `workflow_name`, `paused_node_id`,
`gate_kind`, `paused_at` (trailer `end_time`), `path`) so the CLI stays a renderer:
- Iterate `sorted(debug_dir.glob("workflow-trace-*.json"), key=_trace_recency_key, reverse=True)`
  (same glob as the by-exec-id arm).
- Per file: `_read_trace_meta_line` (head — workflow_name/execution_id/workflow_path/only_node;
  skip `only_node is not None`), then a new `_read_trailer_line(path) -> dict | None` — a
  tail-seek reader (~15 lines) that returns the parsed `run.complete` dict or None. Duplicating
  the tail-seek approach of `ui/run_tailer._scan_tail_for_terminal` is the SAME accepted
  duplication as `_is_trace_locked` (`runtime/` must not import `ui/`) — note it in the
  docstring the same way. Keep only files whose trailer has `final_status == "paused"`.
- Exclude consumed tokens: extract the superseded check from `load_resume_source` (lines
  812-828) into `_find_consuming_attempt(debug_dir, workflow_path, execution_id) -> str | None`
  and call it from BOTH `load_resume_source` (behavior identical) and `list_paused_runs` — one
  consumption policy, two callers, no drift (this uses `_attempt_consumed_work` including the
  3c verdict clause).
- Text: aligned columns `TOKEN  WORKFLOW  PAUSED AT (step)  GATE  AGE`. A single footer command
  template is WRONG for a mixed list (deep-review S: approvals take `--approve yes|no`,
  escalations take `--choose`) — either render the per-row command, or a footer showing BOTH
  templates keyed by gate kind. Age from trailer `end_time` (ISO) vs now. Empty state: exit 0,
  "No paused runs." (text) / `[]` (JSON — explicitly the empty array, not a string). JSON: list
  of the dataclass dicts + per-entry `resume_command` (kind-correct verb).

**Phase-3 gate**: CLI e2e battery (below) + `resume list` tests + double-deny consumption pin.

## Phase 4 — UI: `resumed_from` chain + paused status

- `ui/server.py::_run_entry` (1167-1184): add `"resumed_from": meta.get("resumed_from")`. The
  meta line already carries it (`META_KEYS`, trace_io.py:35-48); `run_tailer._read_meta` returns
  it (verified — only `inputs` is popped).
- `web/src/types.ts` `RunInfo` (83-96): add `resumed_from: string | null`.
- **`web/src/components/RunProgress.tsx::runBadgeStatus` (24-37) — REQUIRED, not polish**
  (deep-review W, verified end-to-end reachable): the live-overlay badge switch has arms for
  `failed`/`degraded`/`denied` and then `return "success"` — a `"paused"` `final_status` falls
  through to the **green success ✓**. This is a REGRESSION 171 introduces: a UI-launched gated
  run (`POST /api/run`, stdin=DEVNULL) trails `paused` where it used to trail `failed`, the SSE
  `run-complete` forwards `final_status` generically, and the badge flips from a correct failed
  badge to a wrong success badge. Add a `paused` arm mirroring the `denied` arm (amber
  "stopped"-class treatment) — the denied arm's own comment ("the success ✓ fallthrough below
  must never render a human's 'no' as green") applies verbatim to a pause.
- `web/src/index.css`: add `.run-paused` rules beside each `.run-denied` rule (verified sites:
  `.run-banner.run-denied` ~:737, `.run-mark.run-denied` ~:871, `.run-progress-outcome.run-denied`
  ~:2553) — `GraphView.tsx:1070` and `RunProgress.tsx:138` compose `run-${final_status}`
  class names, so `run-paused` renders unstyled without them.
- Defensive `paused` arms beside the existing defensive `denied` arms (deep-review S — same
  "must never render as ✓" hazard, same defense-in-depth intent):
  `execution/formatters/success_formatter.py:328-332` and
  `cli/workflow_output.py:726-730` (+ update the status docstring at workflow_output.py:713
  which enumerates the status vocabulary).
- `web/src/components/RunSelector.tsx`:
  - `runMark` (23-34): add a `paused` branch before the fallback: glyph `⏸`, class `run-paused`,
    label "paused". (Verified: unknown statuses hit runMark's grey fallback — here it IS polish;
    RunProgress above is the correctness fix. `events.ts` `RUN_STATUSES` is the per-NODE overlay
    allowlist — do NOT touch it; no new node status exists.)
  - Resumed attempts: when `run.resumed_from` is set, render a secondary line/badge
    `⤷ resumed from <first-8-chars>`; if the source run is present in the current list, clicking
    the badge selects it. NO grouping/collapsing UI in v1 — the marker + jump is the scoped
    deliverable; chain "current vs superseded" analysis stays server-side-only (it already
    exists as consumption semantics; do not re-derive a second version in TypeScript).
- Real-surface check: `make ui-build`, run a workflow to a durable pause, `pflow ui`, verify the
  paused glyph + a resumed chain's marker in a real browser (screenshot-pflow-web-ui skill).

## Phase 5 — Docs, guide, ledger, ADR touch-ups

- `pflow guide` (src/pflow/guide/): gates/features prose — durable pause flow, token, exit 4,
  `pflow resume <id> --approve yes|no` / `--choose`, `resume list`. Grep the prose for
  single-letter shorthand before finishing (164 lesson).
- CLAUDE.md updates: `mcp_server/CLAUDE.md:145` (MCP now streams; ALSO fix the pre-existing
  internal inconsistency — the tool line ~:60 already says "traces saved");
  `execution/CLAUDE.md` (RunnerConfig block "MCP never streams", integration note);
  `runtime/CLAUDE.md` (Task-172 bullet, new `resume_source.py` module section, paused status in
  the trace-format notes); `cli/` CLAUDE.md exit-code table (add 4); source comments
  `runner.py:184-186`. Status-vocabulary staleness (deep-review S): `ui/run_tailer.py:110`
  docstring and `src/pflow/ui/CLAUDE.md:105` enumerate `success/degraded/failed[/denied]` —
  add `paused`.
- ADR-0008: verified it NEVER said "trace streaming is CLI-only" — that was a Task-172 scoping
  comment misattributed by mcp_server/CLAUDE.md; ADR-0008 line 35-38 explicitly supports any-run
  streaming. Add a short update note to ADR-0008 recording that MCP streams as of Task 171
  (aligning with its "any run is watchable" intent) and fix the misattribution in
  mcp_server/CLAUDE.md. Amend ADR-0010's terminal-status mention if it enumerates statuses.
- Issue #542: comment that `paused` traces are live obligations — retention must be status-aware;
  never prune `paused` by default.
- CONTEXT.md: already updated (Paused, Resume token, Resume, Paused-vs-Denial) — re-read at ship
  for drift.

## Testing strategy

Keystone-first (the 164 pattern: one REAL run through `WorkflowRunner` makes ~30 synthetic
fixtures trustworthy). Mutation-verify every subtle assertion (Edit + revert). ★ = must be
mutation-verified.

Producer (Phase 1):
- ★ Real approval-gated workflow, non-TTY (no resolver TTY) → trace trails
  `final_status:"paused"` + `paused_node_id` + `gate_request` round-trip;
  exit 4; stdout token line parseable; stderr answer hint; JSON document fields; `-p` keeps
  token on stdout.
- Child-workflow gate → `failed` (originating-tag + nested flag); ★ **id-collision test**: child
  gate node named IDENTICALLY to its parent WorkflowExecutor host → still `failed`, never paused
  (pins the deep-review collision fix — the old id-match heuristic passes every other test).
- ★ **Pause-promise producer refusals**: escalation on a loop node, on a `code` node, and on a
  terminal step (action "end"/no default successor) → NO token, exit 1, `failed` (pins
  `_gate_pausable`); escalation on a plain mid-graph node → token, and `--choose` succeeds
  (the promise parity pin: producer-pauses ⟹ resume-accepts, on an UNCHANGED workflow).
- Parallel-batch gate → `failed`; batch-HOST approval → pauses (fires at 7.5 in the root
  engine); `GateResolverError` → `failed`; denied → `denied` exit 3 (unchanged).
- `--no-trace` + gate → FAILED path, exit 1, new message text.
- Torn trailer (truncate the last line of a paused trace) → reads `incomplete`, 164 arm resumes.
- `has_resumable_step` returns False on a paused collector (pin).
- MCP: paused text carries execution_id/resume_command; success text gains execution_id +
  real trace_path; concurrent two-run filename uniqueness (existing microsecond mechanism, smoke).

Loader (Phase 2):
- ★ Paused-approval → entry `(K, None)`; paused-escalation → `(None, K)`; corrupt pause record →
  typed refusal.
- ★ Fold-order pin: unanswered paused escalation → `ResumeAnswerRequiredError` (NOT the
  guard's "unresolved escalation" message); answered → guards pass, seeded store carries the
  decided marker, attempt trace re-records it (disable the fold → exactly these fail).
- Mismatched/superfluous answer flags; `--choose` numeric→label mapping.
- Superseded paused token → `ResumeSupersededError`; live-lock never fires on finalized paused
  traces (smoke).

CLI (Phase 3):
- ★ e2e approve: pause → `resume <id> --approve yes` → gated node runs once, outputs equal an
  uninterrupted approved run, attempt self-contained (`resumed_from` on meta), no side-effect
  confirm prompt.
- ★ e2e deny: `--approve no` → denied attempt trace, exit 3, gated node never executed;
  ★ second `--approve no` on the same token → `ResumeSupersededError` (pins the
  `_attempt_consumed_work` verdict clause).
- ★ e2e escalation: real agent-raised escalation non-TTY → token; `--choose` → escalating node
  NOT re-executed (assert node run-counts), downstream reads
  `${step.escalation.decision.chosen}`, run completes.
- Multiple gates: approve gate 1 → run pauses at gate 2 as a NEW attempt (chain of 3 traces).
- Stale hash: edited workflow → refusal; `--force` proceeds. Resume-of-paused with `--dry-run`
  + an answer flag: plan shows entry, nothing executes, hash gate still applies. ★ Deliberate
  behavior pin (deep-review S3): `--dry-run` WITHOUT an answer flag on a paused run →
  `ResumeAnswerRequiredError` (an unanswered escalation's route is genuinely unknowable —
  assert it on purpose, don't discover it).
- ★ First-node pause by-name: `pflow resume <workflow> --approve yes` selects a run paused at
  its FIRST node (pins consumption clause (b) in the selection skip rule).
- ★ Chain-fork prevention: attempt B (restored-only events + pause at gate 2) supersedes source
  A — `resume list` shows only B; answering A → `ResumeSupersededError`.
- Escalation-on-final-step → the paused-specific refusal text.
- `resume list`: shows pending only (paused ∧ not superseded); consumed/denied disappear; JSON
  shape; empty-state exit 0. Group routing: `pflow resume <target>` (unchanged), `pflow resume
  list`, `pflow resume --help` shows both.
- ★ Parity: `test_plan_drift.py` gains `test_engine_and_planner_resume_entry_state_match`-style
  paused variants (approval + escalation) — engine and planner walk-entry state match on a
  paused source.

UI (Phase 4): `_run_entry` projects `resumed_from` (API test); RunSelector renders paused glyph
+ chain marker (component test) + the real-browser check.

Numbers: re-run the four resume suites + `make test`/`make check` per phase; report deltas
against 165/8489 baselines.

## Invariants that must survive (from 164/125 reviews — verify at final review)

- Unrecovered-set check stays BEFORE frontier selection; `_seedable_final_events` remains the ONE
  seed derivation; `_apply_gate_resolutions` folds before guards; `resumed_from` set at collector
  construction; `resume_from ⊥ only_node`; gate lines stay disk-only (never in `self.events`);
  `GateRequest`/`GateResolution` shapes unchanged; the four generic-except boundaries re-raise
  gate exceptions untouched; `seed_walk_entry` gains NO mode flag or callback (it is untouched);
  `_iter_workflow_traces` gains no status filter; `runtime/` never imports `ui/`.
