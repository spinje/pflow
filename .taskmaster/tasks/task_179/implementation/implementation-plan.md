# Task 179 — Durable Loop Position: implementation plan

Planner: Fable task-planner, 2026-10-05, worktree `/Users/andfal/projects/pflow-worktrees/feat-task-179-durable-loop-position`
(branch `feat/task-179-durable-loop-position`, base `main` @ `90b891cb`). Spec: `../task-179.md` (Q1 = (c), Q2 =
continue-unless-unrestorable are user rulings; Q3–Q6 resolved below). Every `file:line` cited here was read in this
worktree at `90b891cb` — re-verify after any merge of `main`.

The governing lens, applied at every fork below: *"We should prioritize simplicity of the FINAL code, not how easy it
is to get there. When in doubt we should ask ourselves whats the right solution that the top 10% of codebases similar to
this one would implement, have we considered it yet? What this doesnt mean is overfitting to "top 10% of codebases" and
overengineering, this is about more simple code that is optimized for AI agents to understand and add features to."*
The acceptance bar is the deletion ledger (§6): one mechanism, every loop special case gone.

---

## 1. The mechanism in one paragraph

A loop node's position becomes part of the saved run in two recordings of the same engine fact (`shared["__iteration__"]`,
set by `loop_runtime_scope`): **(1)** every trace event of a loop node carries `iteration` (trace format 2.7.0 → 2.8.0),
and **(2)** every `GateRequest` raised while a loop node runs carries `iteration` (so the pause record, and therefore
every pause surface, knows the round). Resume generalises its one seed derivation from "everything before the entry's
first event" to **"everything that completed before the entry's iteration began"** — the resume entry is a *(step,
iteration)* pair, `--only` is the same rule at iteration 1. The engine restores the loop's own counter from that
iteration and the unchanged carry/condition/cap machinery does the rest. "Resume after a loop step" (an answered
escalation, or a kill between an iteration and the re-entry decision) is honoured by the engine making the re-entry
decision it would have made, with the same function the walk uses. With those in place, `_gate_pausable`'s loop clauses,
the preflight's loop refusal, the #615 warning, and every "loops restart at 1" sentence are deleted.

```
saved run (trace)                      loader (resume_source)               engine (_prepare_resume)
K ev it=1 ok ─┐                        entry = K (failed arm / paused)      seed_walk_entry(entry=K, entry_iteration=3)
K ev it=2 ok ─┼─ final[K] before it=3  entry_iteration = 3                  → shared[K] = it-2 output; loop_counts[K] = 2
K ev it=3 FAILED                       ResumeSource(entry_iteration=3)      → walk enters K; scope sets __iteration__ = 3
                                                                             → carry reads shared[K] (unchanged plan_node path)
```

---

## 2. Investigation record (verified against code; searcher citations re-checked by the planner)

### 2.1 Loop execution model (engine.py, loop_control.py — read directly)
- `_run_inner` (`engine.py:779-866`): `loop_counts`/`loop_caps` are locals created at `:802-803` AFTER `_walk_entry` (`:798`);
  iteration = `loop_counts[node_id]` after increment (`:824-825`); `loop_runtime_scope(... iteration=..., clear_iteration_on_exit=False)`
  wraps execution (`:831`); re-entry: `if not error and self._loop_should_reenter(...)`: `continue` else `shared.pop("__iteration__")`
  then `route_action` (`:842-858`). `_loop_should_reenter` (`:990-1039`) = condition → `_mark_loop_stopped` → cap memo
  (`resolve_loop_cap` once) → `_emit_loop_cap_advisory`. No reference to these three methods exists outside `engine.py`
  (grep `src tests`): moving them is safe.
- `_execute_node` (`:1166-1665`): `enforce_loop_guard` at step 3; `plan_node` (carry override inside, Task 166) at `:1208`;
  in-process cache hits key on `__execution__["completed_nodes"]` (seeding never adds to it — verified
  `seed_snapshot_into_shared` writes only `shared[nid]`); memo reads are suppressed while `__loop_active__` is raised
  (so a resumed loop node at iteration N never serves a memo hit — no visit-count restore needed for that).
- Approval gate fires at step 7.5 (`:1277-1291`) BEFORE `node._run` (`:1330`); escalation at 17.7 (`:1497-1498`) AFTER step 16.
- Gate except arm (`:1504-1609`): `originating = not getattr(gate_exc, "_pflow_gate_seen", False)` (`:1522`) is True exactly
  at the engine level where the gate fired; pause record = `self.trace.pause_request = {"paused_node_id", "gate_request"}`
  (`:1566-1571`, plain attribute; `_aggregates()` `workflow_trace.py:1059-1060` merges it into the trailer); the host-frame
  record `host_frame = getattr(node, "_host_frame", None); if host_frame is not None: record_trace(... frame=host_frame)`
  (`:1593-1608`) is #659's defect site.
- `_gate_pausable` (`:98-132`): approval → `config.loop_config is None or iteration == 1`; escalation → `loop_config is None
  and not PythonCodeNode and action != "end" and default successor exists`.
- `WorkflowExecutor._host_frame`: class attr `None` (`workflow_executor.py:86`), reset at `exec()` start (`:383`), set by
  `descend()` (`:447-448`), never cleared after `exec()` returns (the `finally` at `:479-485` only `ascend()`s — step 16
  reads it after `_run` returns, `engine.py:1337`). So on a loop node's visit ≥2 whose approval gate fires at 7.5,
  `exec()` never ran and the attribute still holds the PREVIOUS visit's frame → `_stamp_correlation` reuses its seq
  (`workflow_trace.py:760-762`) → `trace_io.py:205-207` last-write-wins replaces iteration 1's event. Same arm also
  double-records a host whose own escalation (17.7) raises after step 16 already used the frame (reading only; exotic).

### 2.2 Saved run and resume (resume_source.py, workflow_trace.py — read directly)
- `ResumeSource` (`resume_source.py:61-93`): `entry_node_id`, `last_completed_node_id` (between-nodes shape = `(None, K)`),
  `events`, `inputs`, `content_hash`, `paused_node_id`, `gate_request`.
- `_seedable_final_events(events, entry_node_id)` (`:310-328`): THE seed derivation — final event per node in the slice
  before the entry's FIRST event, minus failed; `entry_node_id=None` → all events. Consumers: `seed_snapshot_into_shared`
  (`:810-852`), `_guard_seed_scope` (loader, `:786`). `seed_walk_entry` (`engine.py:597-626`) composes it with
  `find_node_by_id`; four callers: engine `--only` (`:891`), engine resume (`:929`), planner resume (`plan.py:518`),
  planner `--only` (`plan.py:535`). Its docstring scope-guard ("if this grows a mode flag or callback, back off") is
  honoured by D2 below: the new parameter refines the ENTRY's identity, it is not a mode.
- `_resolve_resume_entry` (`:450-512`): failed → `_terminal_failure_root`; paused approval → `(K, None)`; paused
  escalation → `(None, K)`; incomplete → `_resolve_incomplete_entry` (`:515-557`: dangling top-level `node.start` → that K;
  tail ends in failure → root; success tail → `(None, last)`).
- `_apply_gate_resolutions` folds a looping node's LAST resolution into its FINAL event (`:331-356`) — safe today only
  because a loop step is never a resume entry; D2b changes the pairing to by-iteration.
- `_prepare_resume` (`engine.py:917-966`): seed → `initialize_execution_state` → stamps `restored_nodes`/`resumed_from`/
  `resume_entry_node` → re-record each restored final event `cached=True, restored=True` (`record_node_execution`, no
  `shared` in scope — needs an explicit `iteration=ev.get("iteration")`).
- Runner threading (`runner.py:136-141` guard, `:353-355` engine kwargs, `:498-502` + `:530-532` planner kwargs).
- Trace event build: `instrumentation.record_trace(node_id, node_type_name, shared, …, cached, error, success, frame)`
  (`instrumentation.py:550-632`) is the ONE path that sees `shared`; five call sites (`engine.py:1429, 1595, 1628`;
  `instrumentation.py:765` cached, `:832` api-warning). `record_node_execution` (`workflow_trace.py:667-683`) has no
  `shared`. `_prepare_resume`'s re-record is the one direct call. `RESERVED_LINE_KEYS` (`trace_io.py:55`) must NOT gain
  `iteration`. `TRACE_FORMAT_VERSION = "2.7.0"` (`workflow_trace.py:41`); readers gate on `startswith("2.")` (`:164`);
  literal `2.7.0` in tests: `tests/test_runtime/test_trace_format_2_2.py:27` (asserts the version),
  `tests/test_cli/test_resume_list_cli.py:114`, `tests/test_core/test_cache_analysis_analyze.py:7743,7751` (fixture data —
  implementer checks whether they pin the exact version or merely need a valid 2.x).
- `TraceFixtureBuilder` parity (`tests/test_core/test_trace_tree.py:138-303`) compares KEY SETS of events recorded without
  loops → an opt-in key (absent when `None`) keeps it green; an always-present `iteration: None` breaks all four.
- Task-159 baseline `verify.sh`: 87 cases, ~2m10s, CLI output only, no `loop:` case. **Measured today: 79 pass / 8
  drift** (6 output-`source` required-property drifts, 1 guide-wording drift — the 7 Task 170 recorded — plus
  `01-parser-errors/01-empty-cache-block`: a Python-3.14 `SyntaxWarning` from `anyio/from_thread.py` in stderr,
  environment not code). The outer net for this task = **the same 8 drifts, no more**.
- `_strip_redundant_llm_trace_fields` (`workflow_trace.py:228-245`) strips `prompt`/`system` (+ agent fields) from
  `LLMNode`/`AgentNode` outputs; no loader check exists today (resume_source.py has no `llm_prompt` reference). Binary
  placeholders refuse via `_guard_seed_scope` → `ResumeFidelityError` (`:594-601`).

### 2.3 Pause surfaces (gate_prompt.py, run.py, resume.py, execution_service.py, exceptions.py)
- `format_resume_answer_command(execution_id, gate_request)` (`gate_prompt.py:195-204`) reads ONLY `kind`;
  `format_gate_lines(gate_request)` (`:207-227`) renders preview / question+options. Consumers: CLI `_display_paused_result`
  (`run.py:654-701`; JSON doc includes `gate_request: masked_gate_dict(...)`), MCP `_format_paused_text`
  (`execution_service.py:228-256`, text with a `Gate:` block of `format_gate_lines`), `resume list` (`resume.py:416-471`;
  passes `{"kind": run.gate_kind}` — `PausedRun` `resume_source.py:866-881` carries only `gate_kind` from
  `gate_request["kind"]`), `ResumeAnswerRequiredError` (`exceptions.py:1442-1508`, raised only in `resume_source.py:621,
  630, 641, 675` with the trailer's `gate_request`). A fifth surface: web `GET /api/gate` (`ui/server.py:1465-1510`)
  returns `masked_gate_dict(gate_request)` verbatim (every non-preview key passes through).
- `GateRequest` (`core/gate.py:34-55`): `node_id, node_type, kind, preview, question, options, recommendation`;
  `to_dict()` = `asdict` (+ options list); builders `build_approval_request(node_id, node_type, params)` (`:68`),
  `build_escalation_request(node_id, node_type, marker)` (`:80`). Call sites `runtime/engine/gate.py:88` (inside
  `run_approval_gate(config, params, shared, trace)`) and `:160` (`run_escalation_gate(config, marker, shared, trace)`)
  — both have `shared` (so `__iteration__`) and `config.loop_config`.
- #615 code: `run.py:468-480` (the "answers only the first iteration … later iterations fail" warning + the
  `answered_loop` strip from `unapproved`); `_fully_answered_gate_ids` (`:499-515`, callers `:439` and the `--dry-run`
  footer `:788-789` via `format_plan_text(plan, answered_gate_ids=)` → `plan_formatter._append_gate_footer:333-352`).
  The single-use answer channel `build_gate_resolver(..., approval_answer=)` (`gate_prompt.py:78-98`) + `resume.py::_approval_answer`
  (`:107-123`) is what makes round N+1 pause again — UNCHANGED by this task.
- `GateNotInteractiveError` fixed remediation text names "a loop step's approval after its first iteration, or a
  loop-/code-node/final-step escalation" (`exceptions.py:1091-1101`); no test asserts that sentence.
- Preflight `_resolve_between_nodes_entry` (`resume_preflight.py:221-295`): missing → code router → **loop (`:261-273`)** →
  no single default successor; `_node_has_loop` (`:185-197`); `_side_effect_refusal` (`:298-324`) skips paused sources
  and reads K's type via `entry_node_id` (None → no refusal).

### 2.4 Web UI and MCP
- Approve → `POST /api/resume {run, approve:"yes"}` → `_resume_cli_args` → `pflow resume <run> --output-format json --approve yes`
  (`server.py:1281-1291`), spawned detached with `PFLOW_EXECUTION_ID`; `useResumeAnswer` pins the NEW attempt
  (`resumeAnswer.tsx:55` → `selectRun`), `selectRun` re-arms `gateDismissed` (`GraphView.tsx:325-347`), the gate panel is
  keyed by run id (`:1237-1254`) so when the new attempt's trailer arrives `paused` the panel remounts and re-fetches.
  **Inference from code (no vitest covers a second pause): the browser chains round after round with Approve alone.**
  P4 verifies it live. `GateCallout.tsx:98-100` eyebrow = `{node_type} · {node_id}`; no iteration anywhere in `web/src`.
  `RunEvent`/`_run_event` are allowlists (`run_tailer.py:650-672`) — `iteration` is NOT propagated to the overlay (not
  required by the spec; left out, see D9).
- MCP: `_format_paused_text` consumes `pause_request` + `format_gate_lines`; `workflow_execute(auto_approve=)` exists; no
  MCP resume tool (resume is CLI-only; MCP pauses a loop only at the round the MCP run reached — round 1 — so the loop
  chain is MCP-pause → CLI-resume ×N). MCP paused tests call `ExecutionService.execute_workflow` in-process and are NOT
  `trace_files`-marked (a token test needs the marker + `Path.home` monkeypatch, cf. `test_mcp_run_streams_a_real_trace`).

### 2.5 Cross-task scan (`./scripts/tasks`, 2026-10-05)
- Shipped substrate reused: 164 (seed/entry composition, frontier rule), 171 (pause record, single-use answer, `resume list`),
  125 (gate payload-as-seam), 166/162 (`carry_effective_config` in `plan_node`, `loop_runtime_scope`, `resolve_loop_cap`),
  176 (`/api/resume`, `preflight_resume`, gate panel), 170 (merged 2026-10-01; its only engine edits — `_assert_carried_inputs_resolved`,
  `_plan_left_unresolved`, `_resolve_template_string` — are untouched here; `Resolution` channels unchanged).
- Unbuilt overlap: none on these surfaces. Lane `fix/issue-678-output-source-fields` touches
  `core/workflow/validator.py`, template field-check, `tests/test_integration/test_template_parity.py` — **disjoint**;
  this plan touches none of them.
- Pending tasks with adjacent surfaces (no collision, awareness only): 111 (batch limit — batch is exclusive with loop),
  121 (`pflow test` — would consume traces; additive field is safe), #542 (trace retention — `paused` traces as live
  obligations; unchanged), #562 (inline resumable — orthogonal conjunct kept).

### 2.6 Spec corrections made (edited in `task-179.md`, provenance here)
1. **`_fully_answered_gate_ids` is KEPT**, only the #615 warning (`run.py:468-480`) is deleted. The function encodes
   answer-vs-occurrence multiplicity ("`--approve yes` answers ONE gate; a loop step has up to `cap` occurrences"), which
   is TRUE under continuation: the answered step WILL pause again at round 2, so it must stay in the `--dry-run` ⏸ footer
   and in the run-start "will pause at" note. Deleting it would make the footer lie. Not a loop special case — a
   statement of the single-answer channel.
2. **#659 regression wording**: the gated visit records NO host event (an approval fires before `node.start`; a denied/
   paused node never appears — `test_denied_run_trailer_says_denied_and_node_absent` pins that). The test asserts
   iteration 1's host event survives unchanged and the host appears exactly once; the `gate` lines carry no seq.
3. Line drift: CLI pause output is `run.py:654-701` (`_display_paused_result`), not `:661-667`.
4. Q3–Q6 recorded as decided (one line each) — §3 holds the rationale.

---

## 3. Decisions (all resolved; Q1/Q2 are user rulings and are not re-opened)

**Q3 — where position is stored → (a) `iteration` on every loop-node trace event, PLUS `GateRequest.iteration`.**
One engine fact, two recordings for two readers: the trace field is what RESUME restores from (self-describing per
event, survives #659-class overwrites once #659 is fixed, re-recorded on restored events so attempt traces stay
self-contained — ADR-0010's amendment holds); the gate field is what HUMANS/agents read at pause time (the pause record is
a trailer read — `resume list` must not open the event stream, per the Q6 constraint). (b) trailer-only was rejected: a
failure has no trailer record and resume-of-a-resume would need chain reads. (c) counting same-node events was rejected
as the spec says. `max_iterations` is deliberately NOT added to `GateRequest` (deletion test: the cap is not the expected
count of a `while` loop, a template cap is unresolved at round 1, and no consumer needs it — the #656 button, if built,
approves "all remaining" without knowing how many).

**Q4 — seeding the entry's own last output → the seed derivation is parameterised by the entry ITERATION (D2).**
`_seedable_final_events(events, entry_node_id, entry_iteration=1)`: the slice ends before the entry's FIRST event whose
`(e.get("iteration") or 1) >= entry_iteration` (an event without the key — or an explicit `null` — counts as iteration 1;
no such event → whole trace). **`>=`, not
`==` (plan self-review C1):** a resumed attempt's trace holds the entry's RESTORED event (iteration N−1, re-recorded by
D5) followed by its live events N..M and never an `iteration == 1` event, and ADR-0010 makes that attempt the newest
snapshot source — with `==`, `--only K` against it would slice the whole trace and seed K's own stale output. With `>=`
every shape resolves identically: failure at N → the failed N event is the first `>= N`; approval at N / kill mid-N → no
event `>= N` → whole trace; after-K → `entry=None` → whole trace; resume-of-a-resume → the restored N−1 is skipped past
and the live events decide; `--only` (iteration 1) → the entry's first event, whatever its iteration → the entry is never
seeded. `loop_counts` are monotone per node within a run and a restored event carries the source's count, so the first
`>=` hit is well defined. The invariant restates as *"never seeds the iteration that is about to run"* — earlier
iterations are upstream of it. `--only` passes the default (1) and is byte-for-byte unchanged (`--only` on a loop target
runs iteration 1 against the pre-first slice; the self-reference substrate `${self.x ?? seed}` still sees the seed).
Docstrings whose invariant statements this rewrites: `engine.py:614-617` ("provably never contains `entry` … use its
keys as `restored_nodes` directly"), `resume_source.py:321-322`, `:843-847`, `resume_preflight.py:186-191`
(`_node_has_loop`: "engine-ephemeral … never records" → the router rationale). The alternative — a separate loop-state
channel — was rejected: the guard (`_guard_seed_scope`) must scan exactly what gets seeded (164's invariant), so a second
channel means a second derivation glued at two sites. A `continue=True` mode flag on the shared composition was
rejected as the 164 scope-guard warns; refining the entry to *(step, iteration)* keeps ONE rule for both surfaces.

**Q5 — re-derive vs restore.** Restored: `loop_counts[K] = entry_iteration − 1` (the loop's own counter — the only
state the mechanism needs) and `shared[K]` (via the seed). Re-derived by unchanged code: `__iteration__` (the scope
increments the restored count), carry (`plan_node` → `carry_effective_config` reads `shared[K]`), the condition (on the
fresh output), the cap (`resolve_loop_cap` at the attempt's first re-entry check — same value when the seed is faithful;
documented edge: a `max_iterations: ${K.x}` template referencing the loop node's OWN output re-resolves against the
resumed iteration's output instead of iteration 1's — authoring that is already odd; noted, not engineered). NOT
restored: `node_visit_counts` (`MAX_NODE_VISITS` is a per-process safety net; the restored `loop_counts` bounds the cap
exactly; `enforce_loop_guard`'s revisit cleanup has nothing to clear because seeding never marks `completed_nodes`).

**Q6 — pause surfaces.** All five show the position or none: `format_gate_lines` gains ONE rule — when
`gate_request["iteration"]` is an int, the first line is `Loop iteration {n}` — which serves the CLI pause stderr, the
MCP `Gate:` block, and `ResumeAnswerRequiredError`'s message; the CLI JSON pause document and `GET /api/gate` carry it
inside `gate_request` already (via `masked_gate_dict` pass-through); `resume list` threads `PausedRun.iteration`
(from the trailer's `gate_request.get("iteration")`) into its GATE column (`approval · iteration 2`) and JSON row
(`"iteration": 2`). The web gate panel eyebrow shows `· iteration 2` (P4).

**Q2 correction (stripped LLM prompt/system).** Not a loader refusal. A loop node whose carry references
`${K.prompt}`/`${K.system}` hits the EXISTING strict carry guard (`_assert_carried_inputs_resolved` → `LoopCarryError`,
loud, names the missing field) at the resumed iteration; a `while`/`until` on those string fields is validator-rejected
already. Same stance as Task 164's node-level resume; no new scan. Stated in the guide line about what resume restores.

**D1 — #659 fix = one conjunct in the gate arm: record the host frame only when `not originating`.** `originating`
(already computed at `:1522`) is True exactly when the gate fired at THIS engine level. A gate from a CHILD engine
arrives `originating=False` while this host is mid-`_run` (its frame reserved THIS visit, step 16 skipped) → record.
A gate at this level is either pre-exec (7.5: the node never ran — no frame this visit; a stale one may linger) or
post-exec (17.7 / resolver error at 17.7: step 16 already consumed the frame) → never record. Closes #659 AND the
17.7 double-record with zero node mutation and no new state. Alternatives (rejected): clearing `_host_frame` in `exec()`'s
`finally` breaks step 16 and both orphan pins; the engine nulling `node._host_frame` before 7.5 writes a node's private
attribute and leaves the 17.7 case open.

**D2 — `ResumeSource.entry_iteration: int | None = 1`, computed by the loader, threaded like `entry_node_id`.**
Loader rule `_entry_iteration(events, node_id)`: `final = final_events_by_node(events).get(node_id)`; no event → 1
(nothing of the step ran — iteration 1 is exact); events WITHOUT the `iteration` key → **`None` = "the saved run
recorded no position"** (a pre-2.8.0 trace — the one honest signal D7 and the preflight consume; no event scan anywhere
else); final is `failed` → its `iteration` (the failed attempt re-runs); else `iteration + 1` (the next round). Applied to `entry_node_id or last_completed_node_id`. Covers: failure at N → N; approval pause at N (K's last
event is N−1 success) → N; approval at 1 (no K events) → 1; kill mid-iteration N (dangling start; events 1..N−1) → N;
escalation at N (K's N success, folded) → N+1 (the "after K" shape); old trace (events, no key) → `None`. Runner passes
`resume_iteration=source.entry_iteration` to the engine ctor and `build_plan`; the engine/planner treat `None` as 1 for
the seed slice and the counter. The engine never reads `iteration` from
events — one reader (the loader), one carrier, two consumers.

**D2b — escalation decisions fold onto the ITERATION that raised them (plan self-review: all five lenses).** Today
`_apply_gate_resolutions` (`resume_source.py:331-356`) folds every resolution line onto the node's FINAL event over all
events, and ADR-0010 records "a looping node's LAST resolution pairs with its final event". That was safe only because a
loop step could never be a resume entry (the preflight refused after-K; at-K never seeded the entry). Two concrete breaks
once D2 seeds the entry's prior iteration and P2b deletes the refusal: (1) *false refusal* — K escalates at iteration 1,
the human answers at the TTY (resolution line R1; the frozen event keeps its undecided marker), iteration 2 fails →
the seed slice holds iteration 1's event, R1 was folded onto the failed iteration-2 event → `_guard_seed_scope` refuses
"unresolved escalation" although a human decided; (2) *silent wrong decision* — R1 as above, iteration 2 escalates
with a NEW question and the human hits Ctrl-C at the prompt → incomplete trace, `(None, K)`, whole-trace seed →
"last resolution onto the seeded event" (folding R1 onto iteration 2's marker) would pass the guard and continue with
iteration 1's answer applied to iteration 2's question. Fix: **gate lines carry `iteration`** — `_record_gate`
(`runtime/engine/gate.py:236-244`) always has the `GateRequest`, so `record_gate(..., iteration=request.iteration)` stamps
it on BOTH pause and resolution lines (part of 2.8.0; written only when not `None`); `_apply_gate_resolutions` folds a
decision onto the event of the same `node_id` whose `iteration` equals the line's (any event, not just the final — the
seedable map references the same dicts); lines without the key (pre-2.8.0 traces, non-loop steps) keep today's
final-event pairing. Scenario (1) then seeds a DECIDED iteration-1 marker and resumes; scenario (2) leaves iteration 2's
marker undecided and refuses loudly ("unresolved escalation … re-run and resolve") — correct: nobody answered it. The
loader still computes the seedable map ONCE and hands it to `_apply_paused_answer` (its target, K's final event, IS the
seeded event for the after-K shape by construction — unchanged behaviour) and `_guard_seed_scope`. ADR-0010's fold
sentence is rewritten in the amendment.

**D3 — "resume after a loop step" is decided by the engine with the walk's own function.** The re-entry decision
moves from `WorkflowEngine._loop_should_reenter` + `_mark_loop_stopped` + `_emit_loop_cap_advisory` (engine methods,
no outside references) to module-level `loop_control.should_reenter(config, shared, node_id, loop_counts, loop_caps)`
(+ `mark_loop_stopped`, `emit_loop_cap_advisory`) — where `runtime/engine/CLAUDE.md` already routes "loop conditions,
caps" — with TWO callers: `_run_inner` (unchanged behaviour) and `_prepare_resume` (the after-K entry). The engine gains
`resume_after: str | None` (mutually exclusive with `resume_from`; the runner maps `entry_node_id=None` + `last_completed_node_id=K`
to it). `_prepare_resume` for after-K: seed (entry K at `entry_iteration = N+1` → whole trace, `shared[K]` = decided
iteration N), `loop_counts[K] = N`, then `should_reenter(...)` → K (re-enter at N+1) or `route_action("default",
K.successors).next_node` (exit; `loop_stopped` already stamped by `mark_loop_stopped`; a non-FOLLOW decision raises
`ResumeNotResumableError` — reachable only via `--force` on an edited workflow). The planner calls the SAME
`should_reenter` on its seeded planner store, so the dry-run says what WILL happen (no upper-bound asymmetry). The
preflight keeps resolving the single default successor for NON-loop steps (unchanged Decision-7 behaviour, pre-spawn
refusals intact for the UI) and for a loop step returns the source untouched after the existence / code-router /
single-default-exit checks. Rejected: evaluating the condition in the preflight (a mirror of engine logic → drift);
making the engine resolve EVERY between-nodes entry (simpler still, but it drops the side-effect confirmation an
interrupted between-nodes resume shows today for a side-effecting successor — a user-visible change outside this
spec; recorded as a follow-up for the user, §8).

**D4 — `_run_inner` creates `loop_counts`/`loop_caps` BEFORE `_walk_entry` and passes them to `_prepare_resume`**, which
sets `loop_counts[step] = max((resume_iteration or 1) − 1, 0)` where `step = self.resume_from or self.resume_after` (the
step the loader computed `entry_iteration` for — never the node the after-K decision routes to), BEFORE any decision,
when that step is a loop node. No other walk change. **Guard
for an edited workflow (`--force`) that removed `loop:` from the entry step:** the engine and planner pass
`entry_iteration = resume_iteration if config.loop_config is not None else 1` to `seed_walk_entry`, so a now-non-loop
step is never seeded with its own output (the loader's guard already scanned the wider set — harmless).

**D5 — `restored_nodes` = seeded nodes that will NOT execute in this attempt**: `[n for n in final if n != entry_node.node_id]`
computed AFTER the entry (incl. the after-K decision) is known. At-K: K is seeded (its position) but runs → not restored.
After-K exit: K stays restored (its decided output stands, it does not run). The re-record loop still iterates ALL of
`final` (self-containment), passing `iteration=ev.get("iteration")`. `build_execution_steps` (`execution_state.py:113-145`)
relabels restored → `not_executed`; without D5 a resumed loop step would read "not executed" after running.

**D6 — `_gate_pausable(request, config, node, action)`** loses the `iteration` parameter: approvals → `True`
(resume enters the gated node at the gated iteration, every time); escalations keep the three non-loop conjuncts
(`PythonCodeNode` router, `"end"` action, default successor exists — each still mirrors a preflight refusal arm).
`GateNotInteractiveError`'s fixed text drops both loop mentions.

**D7 — old traces (loop-node events without `iteration`) restart at 1 and SAY SO**: `_entry_iteration` yields 1, no
position is seeded; `_prepare_resume` (and the planner's `_resolve_walk_start`, mirroring `build_snapshot_degraded_diagnostic`)
emits an INFO advisory via a shared builder `build_loop_restart_diagnostic(node_id, *, source)` →
`__warnings__["__resume_loop_restart__"]` (id `resume.loop-restart`, title "Loop restarts at iteration 1", message names
the step and that the saved run predates loop position; INFO because the run's data is not degraded — the Advisory
noun in CONTEXT.md). Condition: `resume_iteration is None` ∧ the entry is a loop node — no event scan in the engine or
planner (the loader is the one reader of the trace field). An old AFTER-K source (incomplete trace ending on a loop
step, no position) keeps today's refusal in the preflight, with the reason stated (see P2b) — "today's behaviour, and
say so" for that shape is the refusal, never a guess at the re-entry decision.

**D8 — the `iteration` event key is stamped inside `instrumentation.record_trace` from `shared.get("__iteration__")`**
and passed as `record_node_execution(..., iteration: int | None = None)`, written only when not `None`. Safe by the
engine's own invariant: `__iteration__` exists in a store only between a loop node's scope enter and the pop before
routing; children never inherit it (`_PROPAGATED_KEYS`), batch is exclusive with loop. The one direct
`record_node_execution` call (`_prepare_resume`) copies `ev.get("iteration")`. The `--only` single-iteration path
records `iteration: 1` for a loop target (honest).

**D9 — out of scope, deliberately**: the overlay/`RunEvent` does not gain `iteration` (no spec requirement; the
`/api/gate` payload serves the UI's need); no `max_iterations` on the gate; no restart flag (Q2); no change to the
single-use answer channel or `--auto-approve` semantics; `_fully_answered_gate_ids` kept (§2.6).

**Naming (CONTEXT.md): "iteration", never "round"** in code, output text, docs and tests. The spec's prose "round" is
informal.

---

## 4. Phases

Model/effort per ORCHESTRATION.md → Model routing. **Agent assignment**: P1+P2 are one Opus implementer (engine context
is the expensive thing to rebuild; P2 builds directly on P1's field); P3 is the SAME implementer resumed if its window is
healthy (it owns the surfaces context) else a fresh Opus implementer briefed with the plan + progress-log tail; P4 is a
fresh **Fable** `task-phase-implementer` (design-bearing UI, DECISIONS #24); P5 is the task orchestrator's close-out.
Per-phase gate: `make check` + `make test` green at every handback; completion adds `make test-all-local`.

**Serialization**: P1–P2 touch `runtime/engine/` and the trace format — the main orchestrator serialises them against
any other engine/trace work (packet already states it).

### P0 (inside P1's first step) — baseline capture
- `make test` pass/fail counts by name; run `.taskmaster/tasks/task_159/baseline/verify.sh` → expect 79/8 (the 8 named
  in §2.2) and record the list in the progress log. `uv run pytest tests/test_runtime/test_resume_engine.py::test_loop_k_restarts_at_iteration_one`
  passes (the weak pin) — recorded so its FLIP is evidenced.

### P1 — Position recorded: #659, `iteration` on loop events, `GateRequest.iteration`, trace 2.8.0
**Tier/effort**: Opus, `medium` (every decision below is resolved). **Engine + trace contact → triggers mid-task review**:
`review-impact-completeness` (every `record_trace`/`record_node_execution` path, every `GateRequest`/`to_dict` consumer and
exact-equality test) + `review-silent-failures` (the host-frame conjunct must still fire for child gates; `iteration`
absent vs `None`).

Files: `src/pflow/runtime/engine/engine.py` (gate arm `:1593` conjunct; approval/escalation gate calls unchanged),
`src/pflow/runtime/engine/instrumentation.py` (`record_trace` reads `__iteration__`, forwards `iteration=`),
`src/pflow/runtime/workflow_trace.py` (`record_node_execution(iteration=)`, event key, `TRACE_FORMAT_VERSION = "2.8.0"` +
history comment), `src/pflow/core/gate.py` (`GateRequest.iteration: int | None = None` appended; builders gain
`iteration=None`), `src/pflow/runtime/engine/gate.py` (`run_approval_gate`/`run_escalation_gate` pass
`iteration=shared.get("__iteration__")` to the builders; `_record_gate` passes `iteration=request.iteration` to
`record_gate`, which writes it on pause AND resolution lines when not `None` — D2b's pairing key), `src/pflow/runtime/CLAUDE.md` (a 2.8.0 bullet under Traces: "loop-node events
carry `iteration`; the pause record's `gate_request` carries it too"), tests below.

Decisions: D1, D8, Q3, the gate-line half of D2b. `to_dict()` keeps `iteration: null` for non-loop gates (JSON-native, honest; `masked_gate_dict`
passes it through). `record_gate`'s `request` payload therefore carries it on pause-phase gate lines for free.

Tests (each must FAIL on the pre-change code — mutation-verify by Edit+revert, never `git stash`):
- **#659 regression** (`tests/test_runtime/test_gate_trace.py`): a looping gated `workflow` host (`approval: required`,
  `loop: while/until` over the child's typed output, `max_iterations: 3`), non-interactive resolver that approves
  iteration 1 and raises `GateNotInteractiveError` at iteration 2, real streamed trace (`trace_files`): the on-disk
  `nodes` hold the host EXACTLY once, with `iteration == 1`, its original `duration_ms` and child events (presence); the
  in-memory `collector.events` have no second host event with the same `id`. Fails today (iteration 1's record is
  replaced by a 0-duration childless copy). Existing orphan pins (`test_denied_nested_gate_after_sibling_event_does_not_orphan_trace`
  + non-interactive sibling) stay green — they are the "child gate → still record" half of D1.
- **17.7 double-record** (stretch, same file): a `workflow` host whose child declares a `result` output carrying an
  undecided `escalation` marker, non-interactive → the host appears once in `nodes`. If the fixture cannot be built in
  <30 min, log it and skip (D1 closes it by construction; the #659 test exercises the conjunct).
- **Event field** (`tests/test_runtime/test_emit_time_trace.py` or `test_loop_config.py`): a 3-iteration loop yields
  three events for K with `iteration == [1, 2, 3]` (presence) AND a non-loop node's event has no `iteration` key
  (absence, same medium); a looping `workflow` host's CHILD events carry no `iteration`.
- **Fixture parity** `tests/test_core/test_trace_tree.py::TestTraceFixtureBuilderShapeParity` stays green (key is opt-in).
- **Version** `tests/test_runtime/test_trace_format_2_2.py:27` → `2.8.0`; the two literal `2.7.0` fixture sites updated
  only if they assert the current version.
- **GateRequest + gate lines**: approval on a loop node at iteration 2 → `request.iteration == 2` on the pause record and
  on the `gate` pause line, and the RESOLUTION line for that gate carries `iteration: 2` too; approval on a non-loop node
  → `None` and no `iteration` key on its gate lines (absence pair); escalation on a loop node → the iteration on both lines. (`tests/test_runtime/test_approval_gate.py`
  / `test_gate_pause.py` — the pausability change itself is P2.)
- Outer net: `verify.sh` → the same 8 drifts.

Handoff: trace events of loop nodes carry `iteration`; `#659` closed with a pin; `GateRequest.iteration` populated;
2.8.0; `make check`/`make test` green; baseline unchanged. Nothing user-visible yet except the JSON pause document's new
`gate_request.iteration` key (round 1 only — later rounds still fail until P2).

### P2 — Position restored: the (step, iteration) seed, engine continuation, after-K decision, special cases deleted
**Tier/effort**: Opus, `high` (resume/gate semantics — the task's seam). **Engine + resume semantics → triggers mid-task
review**: `review-feature-interactions` (resume × carry × nested host × `--only` × escalation × old trace × resume-of-a-resume)
+ `review-validation-consistency` (producer `_gate_pausable` ↔ preflight arms ↔ engine `resume_after`; planner ↔ engine
parity). Mark **P2a** (at-K) and **P2b** (after-K + deletions) as two handoff points inside one agent launch; the
orchestrator may run the review after P2b only (bundle-vs-resume litmus: nothing in P2a's outcome changes P2b's instruction).

#### P2a — at-K continuation (approval pause at N, failure at N, kill mid-N)
Files: `src/pflow/runtime/resume_source.py` (`_entry_iteration`, `_seedable_final_events(…, entry_iteration=1)`,
`seed_snapshot_into_shared(…, exclude_iteration=1)`, `ResumeSource.entry_iteration`, `load_resume_source` computes the
seedable map once and hands it to the resolution fold, the paused-answer fold and the guard — D2b), `src/pflow/runtime/engine/engine.py` (`seed_walk_entry(…, entry_iteration=1)`; ctor
`resume_iteration: int = 1`; D4 reorder; `_prepare_resume` sets `loop_counts`, applies D5, re-records with `iteration`,
emits D7's advisory; `_gate_pausable` approval branch → `True`, signature loses `iteration`; `build_loop_restart_diagnostic`),
`src/pflow/execution/runner.py` (`resume_iteration` to engine + `build_plan`), `src/pflow/execution/plan.py`
(`build_plan`/`_build_plan_with_shared`/`_resolve_walk_start` accept `resume_iteration`; the walk's
`loop_runtime_scope(iteration=…)` starts the resume entry at `resume_iteration` (1 for every other loop node — carry a
`{node_id: start}` map of one entry on the walker state); `_annotate_entry(entry, config, shared)` derives
`loop_iterations = cap − (shared["__iteration__"] − 1)` — `__iteration__` is still set inside the scope when it runs, so
no state threading; D7 advisory appended to plan diagnostics when `resume_iteration is None`), `src/pflow/core/exceptions.py`
(`GateNotInteractiveError` text: drop "a loop step's approval after its first iteration").

Decisions: D2, D4, D5, D6 (approval half), D7, Q4, Q5. `ResumeSource.entry_iteration` default 1 keeps every existing
constructor/test site valid.

Tests (all through real producers — `WorkflowRunner` + a real trace, `load_resume_source`; file-effects assert CONTENT,
not counts — Task 166's lesson):
- **The replacement pin** (`tests/test_runtime/test_resume_engine.py`, replaces `test_loop_k_restarts_at_iteration_one`
  — FLIP): K (`code`, `loop: while ${k.result}`, `max_iterations: 5`, inputs `iteration: ${__iteration__}`) appends its
  iteration to a file and raises when `iteration == 3` and a flag file says fail. Run 1: file `["1","2","3"]`, status
  failed, `source.entry_node_id == "k"`, `source.entry_iteration == 3`. Resume (flag cleared): success, file
  `["1","2","3","3","4","5"]` — rounds 1–2 never re-fire; restart would give `[…,"1","2",…]`. `restored_nodes == ["prep"]`
  (K is not "restored"), `resume_entry_node == "k"`. **Fails mid-loop by construction — it distinguishes the stances.**
- **Carry fidelity** (`tests/test_integration/test_loop_config.py` or `test_resume_engine.py`): a `carry:` loop (tournament
  shape from 166's test) failing at round 3 of 4; the carried input K receives at the resumed round 3 EQUALS the one an
  uninterrupted run passes at round 3 (log the contenders per round; compare); `__iteration__` seen by the body == 3;
  the loop stops at the same round as the uninterrupted run.
- **Approval pause at round ≥2 resumes at that round** (engine-level, `tests/test_runtime/test_gate_pause.py` — FLIP
  `test_loop_approval_after_first_iteration_stays_failed` → `…pauses_with_position`): `_ApproveFirstResolver(1)` →
  iteration 2's gate pauses (`gate_outcome == "paused"`, `pause_request["gate_request"]["iteration"] == 2`); loading the
  trace yields `entry_iteration == 2`; resuming with `{"approve": True}` runs iteration 2 then pauses again at 3 with a
  NEW token whose `iteration == 3`; effects file exactly `["effect 1","effect 2"]` after the second attempt.
- **Resume-of-a-resume mid-loop** (attempt self-containment, ADR-0010 amendment): continue the chain above through round 3
  → completes; the final attempt's trace contains K's restored event with `iteration == 2` AND executed event `iteration == 3`;
  `nodes_restored` counts upstream only; the superseded middle token refuses (`ResumeSupersededError`).
- **Kill mid-iteration** (`test_resume_source.py`, synthetic via `TraceFixtureBuilder` + a dangling top-level `node.start`
  for K after events `iteration` 1..2): `entry_iteration == 3`. And the failed-arm rule on a failed final K event with
  `iteration: 3` → 3; a non-loop K (no key) → 1.
- **`--only` unchanged** (`tests/test_runtime/test_only_snapshot.py::test_only_loop_target_runs_one_iteration` KEEP) plus
  TWO new pins: (i) `--only K` where K self-references `${k.x ?? "seed"}` and the snapshot holds K's iterations 1..3 → K
  runs at iteration 1 and sees `"seed"`, never its own stale output (absence paired with the seed's presence);
  (ii) the SAME `--only K` where the newest snapshot is a successful mid-loop RESUMED attempt (K's events: restored
  `iteration 2`, live 3, 4) → still `"seed"`, `restored_nodes` excludes K. Mutation: `>=` → `==` in the slice rule fails
  (ii) only — it is the pin for C1.
- **Old trace restarts and says so**: a synthetic 2.7.0-shaped trace (K events without `iteration`, failed last) →
  `source.entry_iteration is None`; resumed → K runs from 1 (`__iteration__ == 1` observed by the body),
  `__warnings__["__resume_loop_restart__"]` is an INFO Diagnostic naming K; the same diagnostic appears in `--dry-run` for
  that source. A new-format trace does NOT emit it (absence paired); a new trace whose K never ran (approval at 1) gives
  `entry_iteration == 1`, not `None`, and no advisory.
- **Seed guard scans the entry's prior iteration**: a binary placeholder in K's iteration-2 output, failure at 3 →
  `ResumeFidelityError` names K (Q2: refuse with guidance).
- **D2b (1) — decided escalation on the entry's prior iteration does NOT false-refuse** (real producer trace, in-process
  `RecordingResolver` answering at the "prompt"): K escalates at iteration 1 (resolved), fails at iteration 2 →
  `load_resume_source` succeeds, the seeded `shared[K]["result"]["escalation"]["decision"]` is the recorded decision, and the
  resumed iteration 2's carry equals the uninterrupted run's. Mutation: fold onto the final event (today's rule) → raises
  `ResumeNotResumableError("unresolved escalation")`.
- **D2b (2) — an unanswered later escalation is never satisfied by an earlier answer** (P2b shape, listed here because it
  pins the SAME fold): K escalates at 1 (answered A), escalates at 2 with a new question, the run is killed at the prompt
  (incomplete trace, no resolution for 2) → `load_resume_source` refuses "unresolved escalation" naming K; the run never
  continues with A. Mutation: fold the last resolution onto the seeded/final event → the resume silently proceeds — this
  test fails.
- **Planner parity** (`tests/test_execution/test_plan_drift.py`, new): resume at K mid-loop — planner seeded store ==
  engine seeded store (incl. `shared["k"]`), planner `restored_nodes == engine restored_nodes` (upstream only), plan entry
  for K has `loop_iterations == cap − (N−1)` and the plan resolved K's carried inputs (the planner's `__iteration__` was N
  — assert via a template that renders `${__iteration__}`), engine `resume_entry_node == "k"`.
- Existing `test_superseded_iteration_escalation_does_not_refuse` / `test_looping_escalation_last_resolution_wins`
  (KEEP — their loop node is upstream; the entry rule is untouched for upstream nodes).
- `test_end_action_refused_by_gate_pausable` (KEEP, call-site edit for the new signature).

Handoff (P2a): every at-K shape continues at its iteration; `--only` unchanged; old traces restart with the advisory;
`_gate_pausable` has no approval loop clause; parity pinned.

#### P2b — after-K continuation (escalation at N, kill between an iteration and the decision), escalation clause, preflight
Files: `src/pflow/runtime/engine/loop_control.py` (`should_reenter`, `mark_loop_stopped`, `emit_loop_cap_advisory` moved
in verbatim — `self`-free), `src/pflow/runtime/engine/engine.py` (`_run_inner` calls `should_reenter`; ctor `resume_after`;
`_prepare_resume` after-K branch per D3; `_gate_pausable` escalation branch loses `loop_config is None`; docstring
rewritten: the remaining conjuncts and their preflight mirrors), `src/pflow/execution/resume_preflight.py`
(`_resolve_between_nodes_entry`: existence → code router → single-default-successor refusals as today; then, for a loop
step: `entry_iteration is None` (pre-2.8.0 trace, no position) → the refusal stays with its reason rewritten ("the saved
run predates loop position, so the next step — another iteration or the exit — cannot be known; re-run the workflow"),
otherwise return the source unchanged; docstring: "a positioned loop step's continuation is the engine's re-entry
decision — `WorkflowEngine(resume_after=)`"), `src/pflow/execution/runner.py`
(maps `entry_node_id is None` → `resume_after=last_completed_node_id`; both guards (`run` `:136-141`, `plan` `:498-502`)
become "entry_node_id set, OR last_completed_node_id set with `entry_iteration` ≥ 2" — i.e. the after-K shape reaches the
engine only for a loop step whose position the loader proved (a non-loop or unpositioned between-nodes source that skipped
`preflight_resume` still raises `ValueError`, closing the bypass the review named) — the pins
`tests/test_runtime/test_resume_engine.py::test_runner_rejects_unresolved_entry_node` / `test_planner_rejects_unresolved_entry_node`
FLIP to build `ResumeSource(entry_node_id=None, last_completed_node_id=None)`; the engine's mutual-exclusion `ValueError`
(`engine.py:674-676`) extends to `resume_after` × `only_node` and `resume_from` × `resume_after`; `_walk_entry` (`:913`)
branches on either; the after-K branch must not assume `loop_config is not None` — a non-loop `resume_after` from a
preflight-skipping library caller routes `should_reenter → False → default successor`), `src/pflow/execution/plan.py`
(`build_plan(resume_after=)`; `_resolve_walk_start` after-K: seed, `should_reenter` on the planner store → K or successor),
`src/pflow/core/exceptions.py` (drop "loop-" from "a loop-/code-node/final-step escalation"), `src/pflow/runtime/engine/CLAUDE.md`
(Find-the-owner row for loop decisions → `loop_control.py::should_reenter`; Gate control flow paragraph rewritten:
pause eligibility no longer mentions loops; "Approval requires nothing further; escalation requires a non-code node, a
non-`end` action, and a default successor. A resumed loop step continues at its saved iteration; `resume_after` runs
the re-entry decision first.").

Decisions: D3, D6 (escalation half). The planner's `should_reenter` call writes `loop_stopped`/an INFO advisory into the
PLANNER's scratch store only (not surfaced) — acceptable; note it in the docstring.

Review-fold (feature-interactions W1/W2):
- **Side-effect confirmation for the pass-through shape.** A looping `workflow` host killed mid-iteration leaves no
  `node.start` (hosts never emit one, `engine.py:1302`) and the killed iteration's child events are dropped as orphans,
  so the loader sees `(None, H)` — today refused, under the plan passed through. `_side_effect_refusal` must then check
  the step that may re-run: `entry = source.entry_node_id or source.last_completed_node_id` (paused sources still skip;
  a non-loop resolved source is unchanged because its `entry_node_id` is set). A spurious confirm for a leaf killed
  between iterations is the accepted cost. Test: killed looping `workflow` host → `ResumeSideEffectConfirmationError`
  names H with registry type `workflow`; `--force` proceeds.
- **Old (2.7.0) after-K sources are refused in the preflight** (`entry_iteration is None`), with the reason stated — the
  engine never sees an unpositioned after-K shape, so `should_reenter` never runs against a missing or unpositioned
  `shared[K]` and `loop_counts[K]` (set to `resume_iteration − 1` ≥ 1 before the decision, keyed on the step
  `entry_iteration` was computed for — never on the routed successor) always exists. Test: an old incomplete trace
  ending on a loop step → `ResumeNotResumableError` whose message names the missing position; `test_between_nodes_loop_node_refused`
  FLIPs into this pin (its source has no events — build it with keyless K events).

Tests:
- `test_loop_node_escalation_stays_failed` → FLIP to `…pauses`: escalation at iteration 2 of a loop node → `paused`,
  `gate_request.iteration == 2`, loader gives `(None, "esc")` with `entry_iteration == 3`.
- **Re-fork recipe end-to-end** (`tests/test_cli/test_paused_cli.py`, `escalating_registry` pattern): a NEW test node
  `EscalateUntilDecidedNode` (test-only, beside `EscalatingNode`) that escalates when its input `decision` is empty and
  returns `{"escalation": None, "done": True}` once a decision is carried in; workflow = the guide's recipe shape
  (`loop: while ${impl.result.escalation}`, carry `decision: ${impl.result.escalation.decision}`), non-TTY: run → exit 4
  (escalation token, iteration 1) → `resume --choose 1` → the loop re-enters at iteration 2 with the decision, clears,
  exits the loop, successor runs, exit 0; a file written by the successor proves the tail ran once.
- **After-K exit**: escalation at iteration N where the folded decision makes the condition falsy → resume runs the
  SUCCESSOR, K does not run again (K's effects file unchanged), `restored_nodes` includes K, `resume_entry_node == successor`,
  `shared[K]["loop_stopped"] == "condition"`.
- **After-K at cap**: N == `max_iterations`, truthy condition → exit with the cap INFO advisory; K runs 0 more times.
- **Kill between iteration and decision** (synthetic: K events 1..2 success, no dangling start, trace `incomplete`):
  `(None, "k")`, `entry_iteration == 3`; preflight passes it through (`entry_node_id` stays `None`); runner maps to
  `resume_after`; engine re-enters at 3.
- `test_between_nodes_loop_node_refused` → FLIP to `…passes_through_to_the_engine` (asserts `entry_node_id is None`,
  `last_completed_node_id == "poll"`, no raise); `test_between_nodes_dynamic_code_router_refused` KEEP (a `code` loop
  node is still refused); a loop node with NO default exit successor still refuses (KEEP the arm; new assertion).
- **Planner parity after-K**: escalation at N with a truthy condition → both re-enter K (plan entries `[K, S]`,
  engine runs K then S); with a falsy condition → both go to S (plan entries `[S]`; engine `resume_entry_node == S`);
  `restored_nodes` equal in both.
- **Producer ↔ preflight mirror pin**: for every `_gate_pausable` escalation refusal (code router, `end`, no successor) the
  preflight refuses the same shape (`test_plan_drift`'s paused parity style) — the loop case is now absent on BOTH sides
  (absence paired with the three presences).
- `test_approval_gate.py::test_gate_on_loop_node_prompts_every_iteration`, `test_escalation_decision_feeds_loop_carry_reentry` KEEP.

Handoff (P2b): no loop clause anywhere in `_gate_pausable`/preflight; `should_reenter` has two callers; `make check` +
`make test` green; mid-task review run and dispositions logged.

### P3 — Surfaces, CLI chain, MCP, docs, ADR amendment
**Tier/effort**: Opus, `medium`. Mid-task review: optional `review-agent-ux` on the new text (cheap; otherwise it is a
completion-gate lens). No engine contact.

Files: `src/pflow/execution/gate_prompt.py` (`format_gate_lines`: `Loop iteration {n}` first line when
`gate_request.get("iteration")` is an int; **the interactive TTY prompt is the SIXTH surface** — `_prompt_approval` /
`_prompt_escalation` (`:139-163`) render their own header (`⏸  Approval required: deploy (ShellNode)`) and the module
docstring `:18-20` / `format_gate_lines` docstring `:210-212` wrongly claim they share the render: append
` — iteration {n}` to that header and to `_echo_flag_approved` (`:118-121`) when `request.iteration` is set, and fix the
two docstrings; otherwise a prompted loop step shows three identical headers while the pause surfaces say the
iteration), `src/pflow/execution/formatters/success_formatter.py::format_resume_indicator` (`:537-557`, shared CLI/MCP:
`⤷ Resumed from <id> at 'k'` → append ` (iteration 3)` when the attempt's `__execution__["resume_entry_iteration"]` > 1 —
a fourth engine stamp beside `resume_entry_node`, JSON gains `resume_entry_iteration`; the `--dry-run` header /
`ResumePlanInfo` (`plan_formatter.py:34-54`, `result.py:217-228`) gain the same — user-visible, importance 1, the exact
text is stated here so no checkpoint is needed), `src/pflow/runtime/resume_source.py` (`PausedRun.iteration: int | None`;
`list_paused_runs` reads `gate_request.get("iteration")`), `src/pflow/cli/commands/resume.py` (`resume list` text GATE
column `approval · iteration 2`, JSON row `iteration`; footer command unchanged), `src/pflow/cli/commands/run.py` (delete
`:468-480`: the warning + `answered_loop` filtering; `unapproved` then naturally lists an answered loop step in the generic
"will pause at" note — correct), `src/pflow/core/exceptions.py` (no code change — message comes from `format_gate_lines`),
`src/pflow/mcp_server/services/execution_service.py` (no code change — verify the `Gate:` block shows the line),
docs: `src/pflow/guide/features/resume.md:54, 70, 82, 85` (`:70` "the failed step runs again from the start" → for a
loop step, its failed iteration; `:85` killed-between-steps: a loop step's continuation is decided by the engine; one rule: "A paused or failed loop step resumes at the iteration where
it stopped; completed iterations never re-run. Each later gated iteration pauses again as a new token. Saved runs that
predate loop position restart at iteration 1 and say so."), `src/pflow/guide/features/approval.md:34, 52, 76` (loop steps
pause every iteration; browser Approve finishes a loop; escalations on loop steps pause; drop the loop items from the
cannot-pause lists; under §8 option (b) the re-fork recipe note says the escalating loop step needs a next step —
a final-step escalation still cannot pause), `docs/reference/cli/index.mdx:90, 117` ("loop restart" → "loop continuation"; "an answered escalation continues at the
next step" → for a loop step, its next iteration or its exit), `approval.md:102` (the recipe now pauses/resumes
non-interactively — with a next step, §8 (b)), `docs/how-it-works/approval-gates.mdx:67`
(add: a non-interactive loop gate pauses each iteration), `src/pflow/cli/commands/resume.py:282` help (`--auto-approve`
still "every iteration of a looping step" — true, keep), `context/adr/0010-164-resume-trace-checkpoint.md` (amendment,
text below), `src/pflow/runtime/CLAUDE.md` (resume paragraph: entry is a (step, iteration) pair; `--only` is iteration 1),
`src/pflow/execution/CLAUDE.md` (gate/resume adapters: pause eligibility sentence), `.claude/agents/pflow-codebase-searcher.md`
(if it describes pause eligibility or loop restart — grep; none found today, verify), `context/CONTEXT.md` — propose (in the
handback, main orchestrator writes) no new noun: "Iteration" and "Resume" already cover it; the Resume definition's
"re-enters where work stopped" now literally includes the iteration.

ADR-0010 amendment (draft, dated, appended after the deep-review amendment):
> **Amended 2026-10 (Task 179): a loop step's position is part of the checkpoint.** Loop-node events carry `iteration`
> (trace 2.8.0) and the resume entry is a *(step, iteration)* pair: the seed scope is everything that completed before that
> iteration began, so the entry's earlier iterations are upstream of it and restore like any other completed work.
> At-least-once (Decision 4) narrows from "iterations 1..N re-fire" to "iteration N re-fires". A resume AFTER a loop
> step's completed iteration (answered escalation, kill before the re-entry decision) is honoured by the engine making
> the re-entry decision it would have made (`loop_control.should_reenter`), never by a preflight mirror. Traces without
> the field restart at iteration 1 with an advisory — never a guess. The gate payload (`GateRequest`, ADR-0009) gains
> `iteration` = *the iteration that raised the gate* — display-only, for every pause surface; resume derives its
> position from events alone (an escalation raised at N resumes at N+1). The `GateRequest` shape, frozen by Task 171, is
> additive-only from here. Gate lines carry the same `iteration`, and a recorded escalation decision folds onto the event
> of the iteration that raised it (lines without the key keep the final-event pairing) — the 2026-07-04 "last resolution
> pairs with the final event" rule held only while a loop step could never be a resume entry. Supersedes the "K restarts at iteration 1" stance recorded by Task 164 and the
> iteration-1-only pause rule of #615/PR #655. Rejected: a trailer-only position (no
> failure record; chain reads), counting same-node events (fragile under #659-class overwrites), a separate loop-state
> seed channel (a second derivation beside the one the guards scan).

Tests:
- **The 3-iteration CLI chain** (`tests/test_cli/test_paused_cli.py`, FLIP `test_approve_yes_on_loop_gate_answers_one_iteration_then_fails_loudly`
  → `test_approve_yes_on_loop_gate_pauses_each_iteration_until_done`): `_LOOP_GATE_WF` (`max_iterations: 3`): pause (exit 4,
  stderr has `Loop iteration 1`) → `resume --approve yes` → exit 4, NEW token, `Loop iteration 2` → … → third resume exit 0;
  effects exactly `["effect 1","effect 2","effect 3"]`, each once; stderr never contains "answers only the first iteration";
  the three tokens are distinct and each superseded token refuses.
- `test_dry_run_with_answer_on_loop_gate_still_names_auto_approve` KEEP (footer still lists the step — §2.6);
  `test_approve_yes_with_auto_approve_runs_gated_loop_to_completion`, `test_approve_no_on_loop_gate_runs_no_iteration` KEEP.
- **Four surfaces + JSON** (`test_paused_cli.py`, `test_resume_list_cli.py`, `tests/test_execution/test_gate_prompt.py`,
  `test_resume_source.py`): CLI pause stderr line; CLI JSON `gate_request.iteration == 2`; `resume list` text column and
  JSON `iteration`; `ResumeAnswerRequiredError` message contains `Loop iteration 2` when answering is forgotten at round 2.
  Absence pair: a non-loop gate's pause output has no `Loop iteration` line and `resume list` shows plain `approval`.
- **MCP** (`tests/test_mcp_server/test_execution_workflow.py`, `@pytest.mark.trace_files` + `Path.home` patch): MCP
  `execute_workflow` on the loop fixture → paused text contains `Loop iteration 1` and `resume_command`; then CliRunner
  `resume <token> --approve yes` ×3 → effects 3 lines. The first MCP-pause→CLI-resume test in the suite (none exists).
- Docs: `tests/test_docs` link/reference checks green; `grep -rn "restart" src/pflow/guide docs/reference/cli` shows no
  loop-restart statement (absence) while the new continuation sentence is present (presence).

Handoff: all surfaces consistent; #615 warning gone; guides state the one rule; ADR amended; `make check`/`make test` green.

### P4 — Web UI: the ordinary Approve finishes a gated loop; #656 decided (DESIGN-BEARING → Fable)
**Tier/effort**: **Fable** `task-phase-implementer`, `high`. Verify EVERY change via the `screenshot-pflow-web-ui` skill
(kill stale `pflow ui` servers first; `make ui-build`). UI phases burn context fast — rotate at ~300–400k.

Use case: a human in the browser finishes a 3-iteration approval-gated loop with the Approve button alone, knowing at
each pause which iteration they are approving. Look/feel intent: the gate panel stays exactly as Task 176 shipped it; the
only visual addition is the iteration in the eyebrow (`code · repeat · iteration 2`), set in the eyebrow's existing
type — no badge, no colour. Acceptance: at each pause the panel shows the right iteration; after Approve the browser
follows the new attempt and re-shows the panel at the ⏸ node without a manual reload; after the third Approve the run
banner reads success and the effects file has exactly 3 lines.

Files: `web/src/components/GateCallout.tsx` (eyebrow suffix when `req.iteration` is a number), `web/src/types.ts`
(`GateRequest.iteration?: number | null`), `web/src/components/GateCallout.test.tsx` (eyebrow with/without iteration),
`web/src/views/GraphView.test.tsx` (NEW: a pinned attempt whose trailer arrives `paused` after an earlier Approve
re-shows the panel — the second-pause chain nothing covers today), `.claude/skills/screenshot-pflow-web-ui/SKILL.md`
(document the `run=<execution_id>` URL param the app already reads — searcher gap), `web/src/views/GraphView.tsx:74-76`
(comment "an approval's frontier never ran … nothing to merge" is now false for a loop approval with prior/restored K
events — the merge logic already handles it; fix the comment only), server: none expected (`/api/gate`
passes `iteration` through `masked_gate_dict`; `tests/test_cli/test_ui_interaction_server.py::TestGateEndpoint` gains an
assertion that a loop pause's payload carries `iteration`).

Real-browser verification (the review evidence): `uv run pflow ui --no-open --port 8765`; run the loop fixture
non-interactively (`</dev/null`) → token; open `?workflow=<path>&run=<token>` → screenshot shows ⏸ + panel with
`iteration 1`; `click.pflow.md … selector='.gate-approve'` → read the new run id from `/api/runs` (the POST response is
not visible to the skill) → screenshot `run=<new id>` shows `iteration 2` → repeat → final screenshot: success banner;
`cat` the effects file: 3 lines. Keep the screenshots' paths in the progress log.

**USER CHECKPOINT (handback) — #656 "Approve all remaining iterations".** After the round-by-round flow is verified
and screenshotted, the implementer STOPS and the task orchestrator hands back: screenshots of the 3-pause flow + the
question "with Approve finishing a loop one iteration at a time, is an 'approve all remaining' convenience still wanted?"
Planner's recommendation: **not now** — three clicks for a 3-iteration loop is the gate's point (each iteration is a new
action, `approval.md`); the CLI already has `--approve yes --auto-approve <step>` for the unattended case; a second button
adds a server field, a contradiction check (`approve: no` + auto-approve → 400), a button, tests, and a UX decision
about when to show it (every approval gate or loop gates only — the payload now tells us). Build it only if the user
rules yes. **If yes → P4b** (same Fable implementer, resumed): `_parse_resume_body` gains `auto_approve: bool` (strict,
only with `approve: "yes"`), `_resume_cli_args` appends `--auto-approve <paused_node_id>`, pre-flight accepts the
combination as the CLI does; `GateCallout` shows the second button ONLY when `req.iteration` is a number (a loop gate);
copy decided with the user from a screenshot; tests: 400 on contradiction, argv pin, button presence/absence pair,
real-browser run completing in one click. Close #656 with a link either way (main orchestrator at merge).

Handoff: screenshots + vitest green + `tsc --noEmit` clean + the checkpoint ruling logged.

### P5 — Completion (task orchestrator)
- `make check`, `make test-all-local`, `verify.sh` (same 8 drifts), vitest.
- Real-surface runs recorded in the progress log (non-TTY `</dev/null`, isolated `HOME`): the CLI 3-iteration chain
  (`uv run pflow <wf> marker=… ` → `uv run pflow resume <tok> --approve yes` ×3; `pflow resume list` between rounds shows
  `iteration N`; `pflow resume <tok>` without an answer shows the `Loop iteration N` line in the refusal); the failure
  chain (round 3 of 5 → resume → effects count); the re-fork escalation recipe (the test node workflow, `--choose`);
  MCP (`uv run python -c` calling `ExecutionService().execute_workflow(path, {...})` under the isolated HOME, then CLI
  resumes); an old-format trace (take a 2.7.0 loop trace from before P1, or craft one) → advisory text visible.
- Completion-gate `deep-review` (code mode, Full tier — engine + trace): `review-falsifier` (direct, last; spec
  promises = §5 verification rows), `review-spec-conformance`, `review-simplicity`, `review-test-fidelity`,
  `review-silent-failures`, `review-agent-ux`; `tests-windows` CI gate (no new subprocess/path code is expected — the
  effects-file fixtures write with `encoding="utf-8"`; still a blocking gate).
- `create-task-review` → `create-pr` ("Closes #659; Refs #615 — not a closing PR (closed by #655); Refs #656 — folded,
  closed at merge by the main orchestrator with a link").

---

## 5. Verification matrix (spec → evidence)

| Spec promise | Positive evidence (fails on pre-change code) | Where |
|---|---|---|
| Approval pause at iteration N → answer runs N, pauses at N+1 with a new token | 3-iteration CLI chain; engine `…pauses_with_position` | P3 / P2a |
| Failure at N resumes at N; 1..N−1 never re-fire | replacement pin (`["1","2","3","3","4","5"]`) | P2a |
| Carry/condition/cap identical to an uninterrupted run from N on | carry-fidelity content test; after-K at cap | P2a / P2b |
| Position recorded per Q3; old traces restart at 1 and say so | event-field test; old-trace advisory test | P1 / P2a |
| Pause surfaces consistent across CLI, MCP, `resume list`, answer-required error (+ UI) | four-surface tests + MCP test; GateCallout test + screenshots | P3 / P4 |
| Special cases deleted; tests replaced not orphaned | §6 ledger; grep absence + presence of the one rule | P2b / P3 |
| Web Approve finishes a multi-iteration gated loop | real-browser 3-click run, 3-line effects file | P4 |
| Re-fork recipe pauses and resumes non-interactively | re-fork e2e test + real run | P2b / P5 |
| Looping gated host keeps iteration 1's event (#659) | #659 regression | P1 |
| Trace-format change netted | 2.8.0 + fixture parity + `verify.sh` same 8 drifts | P1 / P5 |

Regression guards (pass identically before and after — labelled as such): `--only` loop target, nesting/inline/`--only`
pause-promise pins, 164/171 keystone resume tests, `test_plan_drift` existing four parity tests, orphan pins.

---

## 6. Deletion ledger (the acceptance bar)

Code deleted / collapsed:
- `engine.py::_gate_pausable` — approval loop clause (`loop_config is None or iteration == 1`) → `True`; escalation
  `loop_config is None` conjunct; `iteration` parameter; the "loop re-entry state is engine-ephemeral" docstring.
- `engine.py::_loop_should_reenter`, `_mark_loop_stopped`, `_emit_loop_cap_advisory` → moved to `loop_control.py`
  (one home, two callers).
- `cli/commands/run.py:468-480` — the #615 warning and the `answered_loop` strip. (`_fully_answered_gate_ids` KEPT — §2.6.)
- `execution/resume_preflight.py:261-273` — the loop refusal arm (the loop branch becomes a pass-through; `_node_has_loop` kept
  as the router of who decides).
- `core/exceptions.py:1099` — both loop mentions in the cannot-pause list.
- Every restart-at-1 statement: `guide/features/resume.md:54, 70, 82, 85`; `approval.md:34, 52, 76, 102`; `runtime/engine/CLAUDE.md:57-58`;
  `docs/reference/cli/index.mdx:90, 117`; `engine.py:101-110` docstring; `run.py:470-471, 500-506` comments (the kept function's
  comment is rewritten to the multiplicity rationale); `resume.py:115-117` comment; `gate_prompt.py:71-73` comment;
  `test_gate_pause.py:1-14, 136, 206-207` docstrings.
- Every "never seeds the entry / planner is always iteration 1" invariant statement, rewritten to the (step, iteration)
  rule: `engine.py:614-617` (`seed_walk_entry`), `resume_source.py:313-321` (`_seedable_final_events`), `:488-492`
  (paused-approval comment "the gated node has NO event" — false at iteration ≥2), `:830-847` (`seed_snapshot_into_shared`),
  `:331-356` (`_apply_gate_resolutions` — pairs with the SEEDED event, D2b), `loop_control.py:99-102` + `plan_node.py:54-58`
  ("carry never fires during planning" — false once the planner walks a resumed loop at N), `plan.py:358-363`,
  `resume_preflight.py:185-191, 231-235`, `src/pflow/runtime/CLAUDE.md:138-142` (the exact "never seeds the target …
  derive restored-node lists from its returned map" sentences), `runtime/engine/CLAUDE.md` "A sub-workflow host must still
  close the correlation frame reserved at descent" (→ only for a gate that originated in its child), ADR-0010 lines 80
  and 86-88 (covered by the amendment).
- `execution/plan.py:528` (`restored = list(final)` in `_resolve_walk_start`) applies D5's filter exactly like
  `_prepare_resume` — the parity pin would catch a miss, but it is named here so it is not re-derived.
- Test helper: `tests/shared/trace_fixture_builder.py` has no plain-node event builder with `iteration`; the synthetic
  P2a tests add one keyword (`iteration=None`, emitted only when set) to the existing builders rather than hand-building dicts.

Tests — DELETE / FLIP / KEEP:
| Test | Call |
|---|---|
| `test_resume_engine.py::test_loop_k_restarts_at_iteration_one` | FLIP → fails at round 3 of 5, asserts continuation |
| `test_gate_pause.py::test_loop_approval_after_first_iteration_stays_failed` | FLIP → pauses with position |
| `test_gate_pause.py::test_loop_approval_on_first_iteration_pauses` | KEEP (merge into the new chain test allowed) |
| `test_gate_pause.py::test_loop_node_escalation_stays_failed` | FLIP → pauses; successor conjunct still asserted |
| `test_gate_pause.py::test_end_action_refused_by_gate_pausable` | KEEP (signature edit) |
| `test_gate_pause.py::test_code_node_escalation_stays_failed`, terminal/mid-graph, `TestNestingGuard`, `TestInlinePausePromise`, `TestOnlyPausePromise` | KEEP |
| `test_paused_cli.py::test_approve_yes_on_loop_gate_answers_one_iteration_then_fails_loudly` | FLIP → 3-iteration chain |
| `test_paused_cli.py::test_dry_run_with_answer_on_loop_gate_still_names_auto_approve` | KEEP (§2.6) |
| `test_paused_cli.py::…with_auto_approve_runs_gated_loop_to_completion`, `…approve_no_on_loop_gate_runs_no_iteration` | KEEP |
| `test_gate_prompt.py::TestApprovalAnswer` (6) | KEEP (refresh #615 comments) |
| `test_resume_cli.py::test_between_nodes_loop_node_refused` | FLIP → two pins: an unpositioned (old) loop source still refuses naming the missing position; a positioned one passes through (`entry_node_id is None`, `entry_iteration ≥ 2`) |
| `test_resume_cli.py::test_between_nodes_dynamic_code_router_refused` | KEEP |
| `test_approval_gate.py::test_gate_on_loop_node_prompts_every_iteration`, `test_escalation_decision_feeds_loop_carry_reentry` | KEEP |
| `test_plan_drift.py::test_plan_would_pause_matches_engine_gate_pauses` + four parity tests | KEEP (+ new loop parity tests) |
| `test_resume_source.py::test_superseded_iteration_escalation_does_not_refuse`, `test_looping_escalation_last_resolution_wins` | KEEP |
| `test_only_snapshot.py::test_only_loop_target_runs_one_iteration` | KEEP (+ self-reference pin) |
| `test_gate_trace.py` orphan pins | KEEP (+ #659 regression) |
| `test_trace_format_2_2.py::test_format_version_is_2_7_0` | FLIP → 2.8.0 (rename) |

---

## 7. Failure scenarios the tests must catch (by phase, concrete)
- P1: a host event replaced by a 0-duration copy at a later-iteration gate (#659); the conjunct over-firing and
  skipping the child-gate record (orphan → `finalize()` raises → no trace file); `iteration` present on a non-loop
  event or on a child event; `iteration: None` leaking into every event (fixture parity); the re-record path dropping
  the field (resume-of-a-resume then restarts at 1 — caught in P2a's chain test); `GateRequest.iteration` unset at 17.7.
- P2a: entry at the wrong iteration (off-by-one → round N−1 re-fires or round N is skipped — the replacement pin's exact
  file content catches both directions); carry reading the seed instead of round N−1 (content test); `restored_nodes`
  including K (summary shows "not executed"); `--only` seeding the target's own output; a 2.7.0 trace guessed instead of
  restarting with the advisory; the guard not scanning K's prior iteration (binary placeholder restored silently); the
  resolution fold targeting the all-events final map so a decided escalation on the seeded iteration reads undecided
  (false refusal — D2b); planner resolving K at iteration 1 (parity shared-store diff) or charging the whole cap.
- P2b: after-K running K again when the condition is falsy (K's effects file gains a line); after-K skipping K when truthy
  (effects file missing a line); `loop_stopped` not stamped on exit; a code-loop-node escalation stamped `paused` (dead
  token — the preflight still refuses code routers: mirror pin); a loop node with no exit successor stamped `paused`;
  the planner diverging from the engine on the decision (parity); an earlier iteration's answer satisfying a later
  unanswered escalation (D2b (2)); an unpositioned after-K source reaching the engine (runner guard).
- P3: a surface missing the line while another shows it (one-home rule; the absence/presence pairs); `resume list`
  reading events instead of the trailer (oversized-trailer pins still green); the #615 warning text surviving; the
  "will pause at" note omitting the answered loop step; MCP pause → CLI resume chain failing on the token (trace_files).
- P4: the browser not following the second attempt (panel never re-shows); eyebrow showing `iteration` for a non-loop
  gate; stale bundle served (`make ui-build` + kill).

---

## 8. Risks, edges, follow-ups
- **Cap template referencing the loop node's own output** re-resolves against the resumed iteration (Q5). Documented in
  `should_reenter`'s docstring; not engineered.
- **`loop_counts` is never reset when a loop exits** (pre-existing: a backward edge re-entering a loop node continues its
  count). The trace mirrors `loop_counts`, so resume stays consistent with the live run; noted, not changed. Display
  edge in the same shape: a loop node K inside a hand-written backward-edge cycle (K → X → K) failing on a later visit
  seeds X (correct — the live store had it) and lists X as restored although X runs again after K, so the summary
  labels X `not_executed`. Display-only, exotic; not engineered.
- **Paused approval `entry_iteration` is derived from events, not from `gate_request["iteration"]`** — one derivation
  for every shape. Known mismatch (exotic): K fails at N−1, an on-error back-edge re-enters K and its gate pauses at N;
  the failed-final rule yields N−1. Both numbers are in the trace; if it ever matters, prefer the pause record for paused
  approvals only (kind-dependent arithmetic for escalations is why it is not done now).
- **Follow-up for the user (importance 2, reversible)**: have the engine resolve EVERY between-nodes entry via
  `resume_after` and delete the preflight's successor replacement (`_single_default_successor` stays as the pre-spawn
  ambiguity refusal). Simpler final shape; dropped here only because it removes the side-effect confirmation an
  interrupted between-nodes resume shows today for a side-effecting successor (spurious — the successor never ran — but
  user-visible and outside this spec).
- **17.7 host double-record** is closed by D1; the dedicated test is stretch (fixture cost).
- **USER QUESTION (3/5, from the plan review — the last loop-shaped limit): a loop step whose escalation fires on the
  workflow's FINAL step still cannot pause**, because `_gate_pausable` keeps the default-successor conjunct and the
  preflight keeps "no single default successor → refuse". The conjunct's rationale ("nothing left to run") is false for
  a loop: under D3 the after-K decision either re-enters K (no successor needed) or exits — and with no successor the
  run simply completes. Options: (a) drop the successor conjunct for loop steps only (producer + preflight) — a loop
  mention reappears in both; (b) keep it and state in `approval.md` that the re-fork recipe needs a successor step
  (the plan's default — status quo, reversible); (c) drop it for ALL escalations: `resume_after` already IS the
  fold-and-complete machinery Task 171 lacked (seed the decided marker → decision → no successor → outputs populate),
  which also subsumes the §8 engine-resolves-every-between-nodes-entry follow-up — bigger, user-visible, its own
  ruling. Recommendation: (b) in this task, (c) as the follow-up ruling. The plan proceeds on (b); (a) is a two-line
  change if ruled.
- **Planner `should_reenter` side effects** land in the planner's scratch store only.
- **Windows**: no new platform-sensitive code; effects fixtures use `encoding="utf-8"`; the gate still blocks.
- **CONTEXT.md**: no new noun proposed; "Resume" now literally includes the iteration (suggest the main orchestrator
  append "— including a Loop's Iteration" to its definition at merge).
