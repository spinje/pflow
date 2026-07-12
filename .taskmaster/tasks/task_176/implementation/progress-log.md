# Task 176 — Implementation Progress Log

## 2026-07-11 — Session start: baseline + plan re-verification (Phases 0–2 scope)

Scope for this session (user directive): **Phases 0, 1, 2 — then stop for review.**

### Phase 0 — baseline (all green, captured before any edit)

- `make test`: **8743 passed** (29.10s). Zero failures.
- `make check`: clean (ruff, pre-commit, mypy 246 files, deptry).
- `cd web && npx vitest run`: **731 passed** (51 files). Required a one-time `npm ci`
  (fresh worktree had no `node_modules` — environment setup, not a code fact).
- `cd web && npx tsc --noEmit`: clean.

"No regressions" for this session diffs against these numbers.

### Plan re-verification (worktree HEAD `979f44e6`, one docs-only commit past the plan's `276672a4`)

Re-read first-hand before editing (all **Verified**, evidence = file:line as read today):

- `ui/run_tailer.py`: `_scan_tail_for_terminal` :88-104, `read_run_status` :107-135 (both
  callers `_file_facts` :251 and `_check_stopped` :470 confirmed the ONLY ones),
  `TraceCandidate` :173-182, `_SCAN_CACHE` :196, candidate dict :294,
  `_RUN_COMPLETE_FIELDS` :611-618, `_handle` run.complete arm :597-604, `snapshot()` :369-388.
- `ui/server.py`: `/api/run` spawn block :1097-1110 (detach branch exactly as plan),
  `_preflight` :1011-1027, `_run_entry` :1178-1198, `_LoopbackOnly` :542-567 (installed :1364),
  `/api/run-inputs` sync-handler precedent :1258-1278, `/api/graph` 400 arm :362-367,
  route table :1321-1339.
- `cli/commands/resume.py`: the four extractable gates verified pure/click-free —
  `_load_source_and_workflow` :94-129, `_check_content_hash` :132-147,
  `_resolve_between_nodes_entry` :195-271, side-effect verdict :290-300 (click tail :303-322);
  helpers `_node_registry_type` :150, `_node_has_loop` :159, `_single_default_successor` :174;
  `_build_gate_answer` :325-340 (answer shapes as plan); main flow order :558-598 matches the
  plan's internal order; `inject_settings_env_vars()` first line of try body :559-561.
- `core/exceptions.py`: `ResumeStaleWorkflowError.__init__` :1359-1381 confirmed to use
  `hash_known` for the message only — never stored (the plan's one-line fix is real);
  `ResumeSupersededError.newer_execution_id` :1272; `ResumeSideEffectConfirmationError.node_type`
  :1331; `ResumeAnswerRequiredError.to_diagnostics` :1446-1456 (masked gate in context["gate"]).
  Full refusal family enumerated at :1148-1456 (10 subclasses).
- `runtime/resume_source.py`: twin readers `_scan_tail_for_trailer` :884-902 /
  `_read_trailer_line` :905-933 (the model for P1-1); paused escalation sets
  `entry_node_id=None` at :488; `load_resume_source` :713-799 signature + refusal order.
- `core/gate.py`: `masked_gate_dict` :141-152, `GateRequest` :34-55, `option_labels` :104-114.
- `runtime/compilation/compiler.py`: `is_side_effecting` at :643.
- `compile_workflow(ir_json, registry: Registry, initial_params=None)` — **positional**
  `registry` (the plan's §P2-3 sketch wrote `registry=Registry()`; the authoritative form is
  `_preflight`'s `compile_workflow(resolved.ir, Registry(), initial_params=...)` — plan itself
  says "mirror `_preflight`", so no deviation, just noting the sketch was approximate).

**No real deltas found** — the plan's claims hold verbatim against current code.

## 2026-07-11 — Phase 1 complete (server read path)

Built exactly per plan §P1:

- `ui/run_tailer.py`: `_scan_tail_for_terminal` reworked to `(trailer_dict | None, parse_ok)`
  mirroring the runtime twin's semantics; new `read_run_trailer(path)` (oversized-safe, one-shot
  full re-read preserved); `read_run_status` derived from it, exact signature kept (both callers
  verified unchanged). `_file_facts` reads the trailer ONCE and now also derives
  `paused_node_id`; threaded through `_SCAN_CACHE` (tuple grew by one slot), `TraceCandidate`
  (+`paused_node_id: str | None`), and the candidate dict. `_RUN_COMPLETE_FIELDS` +=
  `"paused_node_id"` (covers live banner AND `snapshot()`); `gate_request` deliberately NOT added.
- `ui/server.py`: `_run_entry` += `paused_node_id`; new `GET /api/gate` (sync/threadpooled,
  mirrors `/api/run-inputs`; 400 missing param with the `/api/graph` errors-shape; 404 unknown id;
  404 not-paused-or-corrupt; 200 serves `masked_gate_dict(gate_request)`).
- Docs: `ui/CLAUDE.md` — `/api/gate` contract block, `/api/runs` field list + `paused_node_id`
  prose, SSE-banner note.

Tests (all green): `test_read_run_trailer_returns_full_trailer_dict`,
`test_read_run_trailer_oversized_paused_trailer_is_read_fully`,
`test_scan_traces_carries_paused_node_id`,
`test_run_complete_banner_carries_paused_node_id_but_not_gate_request`,
`test_run_entry_projects_paused_node_id` (test_ui.py, `_write_trace` grew `trailer_extra`),
new `TestGateEndpoint` (masking pin with a real secret string asserted absent from the whole
response body; 404 unknown / not-paused / corrupt-no-gate_request; 400 missing param; oversized
served), `/api/gate` added to the HostGuard read-endpoint sweep.

**Mutation-verified**: deleted the full re-read branch in `read_run_trailer` → BOTH oversized
run_tailer pins AND the gate-endpoint oversized test failed; reverted (edit + revert, no stash).

Deviations from plan (with reasons):
1. **SSE projection test placement.** Plan §P1 puts it "in test_ui_interaction_server.py beside
   TestRunScopedBroadcast (:1094)" — that class actually lives in `test_ui.py`, and the banner
   projection seam is `RunTailer._handle`'s allowlist, whose existing pins live in
   `test_run_tailer.py` (`test_run_complete_banner_drops_the_full_payload_fields`). Placed the new
   pin beside that test — same seam, same harness, zero SSE plumbing needed.
2. **`/api/gate` 404 condition micro-tightening.** Plan's 404 conjuncts were
   `paused ∧ gate_request is dict`; I also require `paused_node_id is str` — the same conjunct the
   resume loader applies (`resume_source.py:475`), and the response body's `paused_node_id` field
   would otherwise be null-typed for a corrupt trailer. Strictly-safer superset of the plan's arm;
   consistent with edge ledger #2 (corrupt pause → 404, never 500).

## 2026-07-11 — Phase 2 complete (shared pre-flight + spawn helper + POST /api/resume)

- **`core/exceptions.py`**: `ResumeStaleWorkflowError` now stores `self.hash_known` (the plan's
  required one-liner — verified missing before the change).
- **`execution/resume_preflight.py` (new)**: `preflight_resume()` + frozen `ResumePreflight`
  dataclass; the four gates moved VERBATIM from `resume.py` (`_resolve_from_source`,
  `_load_source_and_workflow`, `_check_content_hash`, `_resolve_between_nodes_entry`, helpers
  `_node_registry_type`/`_node_has_loop`/`_single_default_successor`, `_UUID_RE`); the side-effect
  verdict became `_side_effect_refusal()` (constructed, not raised; one construction site, moved
  from resume.py:317). Module docstring records: no settings env-var injection, no compile, and
  the known micro-reorder (`_prime_approval_delivery` contradiction UsageError now fires after the
  hash gate — no test pinned the old order, verified).
- **`cli/commands/resume.py`**: thin click shell per the plan's sketch —
  `inject_settings_env_vars()` stays first; `_prompt_or_raise_side_effect(ctx, refusal,
  print_flag)` is the old :303-322 click tail reading node facts off the refusal exception
  (`node_id`/`node_type` are stored on the base `ResumeSourceError`, verified). Module docstring
  rewritten. `_dispatch_resume` untouched.
- **`ui/server.py`**: `_spawn_detached_cli(cli_args, *, execution_id)` extracted byte-identical
  from the `/api/run` spawn (the win32 detach branch + all the load-bearing comments moved onto
  the helper docstring); `/api/run` now calls it, its existing tests pass unchanged. New
  `POST /api/resume`: `_parse_resume_body` (shape 400s before any I/O; the two documented
  server-stricter asymmetries), gate_answer built with the CLI's exact shapes, off-loop
  `_resume_preflight` wrapper = `preflight_resume` + raise-the-verdict + the exact child compile
  (`compile_workflow(pf.resolved.ir, Registry(), initial_params=dict(pf.source.inputs or {}))`
  — mirrors `_preflight`'s positional-registry form), `_resume_refusal_response` (404 missing /
  409 other ResumeSourceError / 400 other PflowError; `refusal` literal via exact-type dict;
  extras `newer_execution_id`/`node_id`+`node_type`/`hash_known`), `_resume_cli_args` (the server
  never adds `--force` itself).
- **Loose ends** (plan §P2): `engine.py:103` comment + `test_gate_pause.py` docstring +
  `test_resume_no_hang_subprocess.py` docstring/assert-message repointed;
  `test_resume_cli.py` imports of `_check_content_hash`/`_resolve_between_nodes_entry` repointed
  to `pflow.execution.resume_preflight`; grep-verified no other consumer imports the moved names.
- **Docs**: `ui/CLAUDE.md` `/api/resume` contract block (+ADR-0007 exposure paragraph + TOCTOU
  ledger-#1 note), `cli/commands/CLAUDE.md` resume row, `execution/CLAUDE.md` file list.

Tests:
- **T1** `TestResumeEndpoint` (12 tests) — real producer traces (paused runs via the actual CLI;
  the escalating-node registry-injection pattern from `test_paused_cli.py` replicated inline for
  the `--choose` argv pin; a real failed run for the side-effect 409). Covers: approve-yes argv +
  env-pin + detach kwargs; approve-no / choose argv; force present/absent; the five
  no-silent-no-op pins (superseded+`newer_execution_id`, side-effect+node facts, stale+
  `hash_known`, answer_required+masked gate in `errors[0].context.gate` with the raw secret
  asserted absent, 404 missing) each with `popen.assert_not_called()`; shape-400 battery; 403
  non-loopback host.
- **T2** the CLI battery green unmodified (152 tests: test_resume_cli, test_paused_cli,
  test_resume_list_cli, test_resume_source, test_gate_pause), only the two direct-call imports
  repointed as the plan directs.
- **T3** `tests/test_execution/test_resume_preflight.py` — the verdict matrix (paused→None,
  force→None, llm→None, shell→refusal with registry type, entry-removed→None) + order smokes
  (hash gate after load, force skips; between-nodes delegation fills the successor entry).
- **T4** `test_resume_honors_pflow_execution_id_env` — real failed run → forced env id → the new
  attempt's meta `execution_id` == forced AND `resumed_from` == source id AND the env var popped.

**Mutation-verified**: moved the spawn above the pre-flight in the handler → all five
409/404-no-spawn pins failed; reverted.

Deviations from plan (with reasons):
1. **C901 split.** ruff's complexity limit (10) forced the handler's shape-validation into
   `_parse_resume_body` and the argv construction into `_resume_cli_args` — behavior identical,
   both helpers carry the plan's documentation obligations (the asymmetries note moved onto
   `_parse_resume_body`). The plan sketched one inline handler; the split is mechanical, not a
   semantic change.
2. The plan's §P2-3 sketch wrote `compile_workflow(..., registry=Registry(), ...)`; the real
   signature takes `registry` positionally (plan itself says "mirror `_preflight`", which is
   positional) — followed the code, not the sketch.

Environment note: fresh worktree needed one-time `npm ci` in `web/` before the vitest/tsc
baseline could run (not a code fact). No `web/` source files were touched in Phases 0-2.

## 2026-07-11 — Phases 0-2 closed; stopping for review (user directive)

Final verification vs. the Phase-0 baseline:
- `make test`: **8774 passed** (baseline 8743 → +31, all new; zero regressions).
- `make check`: fully green (ruff, format, pre-commit, mypy 247 files, deptry).
- e2e `test_resume_no_hang_subprocess.py` (the file whose message we touched): passed.
- `web/`: untouched this scope — baseline 731 vitest + clean tsc still authoritative.

Key learnings for the next agent:
- The `trace_files` marker is REQUIRED on any server test that pauses/fails runs through the real
  CLI (`disable_trace_file_writes_by_default` gates streaming too) — `TestResumeEndpoint` carries
  it at class level.
- A non-uuid unknown `run` target ("no-such-workflow") surfaces as `WorkflowNotFoundError` → the
  400 arm with NO `refusal` key (it is not a `ResumeSourceError`); only a uuid-shaped miss reaches
  the 404 `missing` arm via `ResumeSourceMissingError`. The frontend's "anything else → inline
  errors" fallback (plan §P3-3) already covers this; worth remembering when wiring ResumeControl.
- ruff C901 (limit 10) will not accept the plan's one-piece handler sketch — the shipped shape is
  handler + `_parse_resume_body` + `_resume_cli_args` + `_resume_refusal_response`, each carrying
  its slice of the plan's documentation obligations.

Next step per plan §P2 checkpoint (NOT started, per "stop for review"): `/deep-review` (code
mode) on the Phase-1+2 diff, then Phase 3 (frontend). The HTTP contract the frontend codes
against is now test-pinned and written into `ui/CLAUDE.md` — the plan's agent-split firebreak.

### Post-close self-review addendum (same session)

Two documentation-enumeration gaps found and fixed (make check + server tests re-run green):
- `server.py` `create_app()` SECURITY comment now lists `/api/resume` (second sanctioned spawn)
  and `/api/gate` (read-exposure class) — that comment is the tripwire future endpoint authors
  read, so its enumeration must stay truthful.
- `ui/CLAUDE.md`'s CORS paragraph's mutating-POSTs list now includes `/api/resume`.

Known residuals, deliberate (none are code defects):
1. `hash_known=False` (pre-content-hash trace, edge ledger #3) has no end-to-end test — the
   modern producer always stamps `content_hash`, so the arm is reachable only via a hand-edited
   trace; the attribute storage is a one-liner and the CLI message variant was already pinned.
   The Phase-3 GateCallout test can cover the panel-side rendering with a mocked body.
2. A non-uuid unknown `run` target maps to the 400 arm WITHOUT a `refusal` literal
   (WorkflowNotFoundError is not a ResumeSourceError) — matches the plan's mapping; frontend
   fallback arm covers it.
3. `resume.py`'s module-level `logger` was already unused before this change — left as-is
   (pre-existing, not this task's cleanup).
4. Windows behavior of the spawn-helper refactor rides the blocking `tests-windows` CI job
   (plan §P5) — not verifiable locally on darwin.

### Test-reflection pass (same session, user-prompted "high-value tests only")

Audited every test in scope for "passing the RIGHT thing", not coverage. Three real gaps found
and closed, one low-fidelity duplicate replaced, one overclaiming name fixed:

1. **`_SCAN_CACHE` hit-path fact correctness** (real bug class: fresh-path-tested/cached-path-
   broken). The cache tuple is six POSITIONAL slots; a transposed slot in `_file_facts`' hit path
   passed every existing test (all scan once, fresh) while corrupting every poll after the first.
   Extended `test_scan_traces_carries_paused_node_id` with a second-scan assertion.
   **Mutation-verified**: transposing `hit[4]`/`hit[5]` → fails.
2. **`/api/gate` real-producer test** (pitfall #19 — the synthetic 200-arm test would stay green
   if the producer's pause-record shape drifted). REPLACED the synthetic
   `test_paused_run_serves_the_masked_gate_payload` with
   `test_real_paused_run_serves_the_masked_payload_and_rides_the_runs_listing` (trace_files):
   pauses a real gated run through the CLI, then pins three seams — flat trailer keys found by the
   reader, `/api/runs` carries `paused_node_id` but never `gate_request`, and `/api/gate` masks
   (the on-disk trailer is unmasked, so a skipped `masked_gate_dict` leaks the real secret).
   **Mutation-verified**: removing the `masked_gate_dict` call → fails. The synthetic
   `_write_paused_trace` helper stays for the edge arms only (404s/corrupt/oversized — shapes the
   real producer can't reasonably emit).
3. **`_RESUME_REFUSALS` completeness net**:
   `test_refusal_literal_map_covers_every_resume_source_error` — introspects the exception module;
   a future ResumeSourceError subclass without a `refusal` literal (a silent frontend-contract
   degrade) now fails loudly instead.
4. Renamed T3's `test_hash_gate_fires_after_load_and_force_skips_it` →
   `test_stale_hash_refuses_and_force_skips_gate_and_verdict` — the load step is stubbed, so
   "after load" was untested; the name now claims exactly what the test pins.

Considered and REJECTED (coverage-chasing, no real bug class): more 400-shape permutations; a
`still_running` endpoint arm (loader-tested; endpoint mapping covered by the completeness net);
a CLI-vs-server gate-drift test (the shared `preflight_resume` IS the structural defense — a test
cannot pin "nobody adds a gate elsewhere"); a real-subprocess `/api/resume` e2e (the exact argv
vector minus the interpreter prefix is what the CLI battery already invokes via CliRunner).

All files re-verified: 137 tests across the three touched files + `make check` fully green.

## 2026-07-12 — Session start: Phases 3-5 (user directive: complete the task end to end)

Scope: **Phases 3, 4, 5** (0-2 committed as `b9a47ac7`). Fresh baseline captured before any edit:

- `make test`: **8775 passed** (23.45s). Note: prior session closed at 8774 — one-test delta on an
  unchanged tree; treated as environment-conditional collection, not a code fact. This session
  diffs against 8775.
- `make check`: fully green.
- `cd web && npx vitest run`: **731 passed** (51 files). `npx tsc --noEmit`: clean.

Plan re-verification for the Phase-3 surface (all **Verified** first-hand today, file:line as read):
`types.ts` NodeStatus :30 / RunComplete :63-75 / RunInfo :83-99 (stale `final_status` comment :62
confirmed present — plan correction #6 stands); `client.ts` ApiError :9-20, `runWorkflow` :126-140
(Content-Type header + run_id validation pattern); `GraphView.tsx` `runComplete` handler :906-909,
`runSnapshot` :880-897, `selectRun` :294-315, `sayAnchorIdFor` :86-94, run callout + `RunProgress`
mount :1115-1139; `focus.ts` `refKey` :17-20, `applyStatus` :33-72 (identity-stable patch model for
P4); `StatusBadge.tsx` `GLYPH: Record<NodeStatus, ...>` :53 (tsc forces the new arm), `runStatusLabel`
:26-44; `RunProgress.tsx` `stepColor`/`stepMeta` :51-77 (a `paused` NodeStatus flows into
`ProgressStep.status` automatically — arms needed in both switches); `NodeCallout.tsx` props incl.
`frameOnMount`; `index.css` status vars :31-34, `.status-badge.status-*` :647-671, `.node.dimmed`
:940-944 / `.node.hover-mark` :954-958 (cssOrder.test.ts pins the pair); the four `RunInfo`
factories needing `paused_node_id` (RunSelector.test.tsx, CatalogView.test.tsx `run()`,
RunPanel.test.tsx `aRun()`, GraphView.test.tsx inline literal :218-230). `core/gate.py`
`GateRequest` :34-55 — options are dicts with `label` via `option.get("label") or "option N"`
(falsy-fallback, mirrored in the TS labeling). Server contract blocks in `ui/CLAUDE.md` for
`GET /api/gate` + `POST /api/resume` read and matched against the handler code. **No deltas** —
the plan holds.

**§P2 checkpoint deep-review** (left NOT-started by the prior session) launched now, before any
Phase-3 edit, per plan ordering: 5 agents — silent-failures, impact-completeness,
validation-consistency, test-fidelity, concurrency-safety — on the committed `979f44e6..b9a47ac7`
diff. `review-simplicity` + `review-agent-ux` deliberately deferred to the Phase-5 full-branch
review (they evaluate the integrated whole; agent-ux earns its slot once the frontend consumes the
refusal vocabulary — braindump note honored).

**Session re-scoped by the user mid-review**: complete the checkpoint review + confirmed BE fixes,
then STOP — Phases 3-5 (frontend) go to a fresh session so BE and FE never share one context
window. The Phase-3 prep verification above stands and transfers.

### §P2 checkpoint deep-review — outcome (2026-07-12)

Zero Criticals. Concurrency, test-fidelity: clean (both wrote out their negative results — cache
locking / TOCTOU / to_thread discipline simulated; every mutation pin verified to genuinely fire).
Every finding below verified first-hand against code before acting (file:line evidence read
directly, not trusted from the reviewer).

**Confirmed + FIXED this session:**
1. **`=`-bearing resume target = silent child death** (validation-consistency, Warning —
   VERIFIED: `_split_target_and_params` resume.py:43 drops every `=`-bearing token from
   positionals → zero positionals → `UsageError` exit 2 into DEVNULL; the pinned id never
   materializes). Fix: `_parse_resume_body` 400s a `=`-bearing `run` before any I/O — EXACT
   parity, not an asymmetry (the child unconditionally refuses such a target). Pin:
   `test_equals_bearing_target_is_400_and_does_not_spawn` (+ `popen.assert_not_called()`).
   Documented on the guard comment + `ui/CLAUDE.md`.
2. **`/api/gate` could 200 with `gate_kind: null`** (silent-failures, Suggestion — a
   hand-corrupted paused trailer whose `gate_request` lacks `kind`; the response contract types
   `gate_kind` as one of the two literals, so a null is a contract lie to the typed frontend).
   Fix: `isinstance(gate_request.get("kind"), str)` joined the 404 conjuncts (edge-ledger-#2
   stance; one conjunct stricter than the loader, reason documented). Pin:
   `test_paused_trailer_without_gate_kind_is_404_not_a_null_kind_200`. Docstring + `ui/CLAUDE.md`
   updated.
3. **Stale `(cli/commands/resume.py)` parenthetical** in `engine.py::_gate_pausable` docstring
   (impact-completeness, Suggestion) → repointed to `execution/resume_preflight.py`.

**Confirmed, deliberately NOT fixed here (documented instead):**
4. **Validator-only pre-trace deaths on `--force` resume** (validation-consistency, Warning —
   VERIFIED: `runner._validate` raises `WorkflowValidationError` at step 3, BEFORE the meta
   flush; the server pre-flight runs `preflight_resume` + compile only). Reachable ONLY via
   `force: true` on a workflow edited to carry a validator-only ERROR that `compile_workflow`
   doesn't raise — without `force` the content-hash gate closes it. Crucially this class is
   SHARED with the shipped Task-175 `/api/run` `_preflight` (also compile-only, same decision),
   and closing it means replicating runner-internal ordering (`_fill_declared_defaults` before
   validate) in both endpoints — its own reviewed change, an owner call, not a checkpoint patch.
   Actions taken: the overclaiming "closes the pre-trace-failure vanish" wording narrowed to
   "COMPILE-level" in the handler docstring + `ui/CLAUDE.md`, residual named explicitly in both.
   **Follow-up recommendation: one issue covering `/api/run` + `/api/resume` — "run
   `WorkflowValidator` in the spawn pre-flights (or decide the residual is acceptable)".**

**Disputed / won't-fix:**
5. Non-uuid unknown target → 400 with no `refusal` literal (silent-failures, Suggestion): the
   plan's mapping is explicit ("any other PflowError → 400", `/api/run` parity), already a
   documented residual (prior session's addendum #2), and the frontend fallback arm covers it.

### Session close (2026-07-12) — checkpoint done, stopping before Phase 3 (user directive)

Final verification vs. this session's baseline: `make test` **8777 passed** (8775 + the two new
pins, zero regressions); `make check` fully green; the touched server test file 89/89. `web/`
untouched — the 731-vitest/clean-tsc baseline still stands. **Both new pins mutation-verified**
(edit + snapshot-restore): deleting the `kind` conjunct fails the kindless-404 pin; disabling the
`=` guard fails the argv-parity pin.

Diff this session (uncommitted, for review): `ui/server.py` (the two guards + docstring
residual/conjunct notes), `tests/test_cli/test_ui_interaction_server.py` (two pins),
`runtime/engine/engine.py` (one docstring path), `ui/CLAUDE.md` (contract blocks updated), this
log.

Process lesson (cost ~5 min, worth recording): mutation-verifying with `git checkout --` on a file
carrying UNCOMMITTED fixes reverts the fixes with the mutation — snapshot the working-tree file to
the scratchpad and restore from that instead. The lost server.py edits were re-applied and
re-verified.

**For the next (frontend) session — Phases 3-5, fresh context:**
- The §P2 checkpoint gate is CLEARED; the HTTP contract gained one client-visible rule: a
  `=`-bearing `run` target now 400s at `/api/resume` (typed frontend always sends execution ids —
  no client change needed, just contract awareness).
- The Phase-3 prep verification in this session's opening entry (file:line map of every frontend
  seam, factory list, `GateRequest.options` labeling rule) is current as of this HEAD — trust it,
  spot-check only what the frontend touches.
- Follow-up to file at close (or hand the owner): validator-only pre-trace deaths on `--force`
  resume / any `/api/run` launch — one issue covering both spawn pre-flights (item 4 above).

## 2026-07-12 — Session (continued): Phases 3-5

Baseline for THIS session (fresh, captured before any edit, tree at `0bc6bf1c`): `make test`
**8777 passed**, `make check` green, vitest **731 passed** (51 files), `tsc --noEmit` clean.

### Phase 3 complete (frontend)

Built per plan §P3, all four sections:

- **P3-1 types+client**: `NodeStatus` += `"paused"` (comment extended: consumer-derived, third of
  its kind); `RunComplete.paused_node_id?` (+allowlist note); `RunInfo.paused_node_id` (required,
  the `resumed_from` convention); stale `final_status` comment fixed (plan correction #6); new
  `GateRequest`/`GateInfo` mirroring `core/gate.py` (options typed `Array<Record<string,unknown>>`
  — the braindump's "verify the real option shape" resolved: `build_escalation_request` admits any
  dict, `label` is convention with the falsy `option N` fallback; `description` rendered leniently
  when present). `ApiError` gained `readonly body?` (third ctor param); `fetchGate` (with an
  `isGateInfo` shape guard, house pattern); `resumeRun` with the SINGLE-READ rule (one
  `response.json().catch(()=>null)` derives both `errors` and `body`).
- **P3-2 ⏸ badge**: `pausedEntry` helper beside `eventState`; synthesis in BOTH `runComplete`
  (map-copy, the `runStopped` shape) and `runSnapshot` (set into the freshly built map);
  `StatusBadge` paused glyph (two bars) + label "Paused — awaiting an answer at this gate";
  `RunProgress` `stepColor`/`stepMeta` paused arms; `--status-paused` (same amber as stopped,
  reason documented in-css) + `.status-badge.status-paused`.
- **P3-3 GateCallout**: content component fetched via `fetchGate` on mount, kind-switched;
  approval = eyebrow (`node_type · node_id`) + masked preview rows (mono field boxes, per-row
  scroll) + Deny/Approve; escalation = question + one-click option buttons (LABEL sent, never the
  number; falsy `option N` fallback; `description` and a "recommended" mark rendered when
  present) + free-text row (client blocks empty/whitespace). Refusal states: superseded → "View
  newer attempt" (onPinRun), stale → ack + force retry of the SAME payload (hash_known wording
  split), else inline `role=alert` diagnostics. GraphView wiring: `gateDismissed` (reset in
  `selectRun`), gate run id = `runId ?? runBanner.execution_id` (unpinned follow-newest pause
  works), anchor via the existing `sayAnchorIdFor` (re-resolved every render, never cached),
  null-anchor guard, `NodeCallout` shell with ⏸ icon + node-id subtitle, mounted beside the run
  callout inside `<ReactFlow>`. Entry point two = an effect on "selection landed on the paused
  frontier" (via `selectedNode`, so a gated container resolves through its HOST).
- **P3-4 ResumeControl**: rendered inside the run callout directly below `RunProgress`, exactly
  the plan's show-when (`runId && (failed banner || (no banner && stopped))`); first click POSTs
  `{run}` (never force); `side_effect_confirmation` → inline confirm naming node id + registry
  type → "Resume anyway" retries `force:true`; stale → same ack pattern; superseded → newer
  attempt; everything else → inline diagnostics, no retry affordance. Keyed by run id so a pin
  switch resets its state.

Tests (all green; vitest **765** = baseline 731 + 34): client (fetchGate ×3, resumeRun ×5 incl. a
single-read pin whose mock body throws on a second `json()` — the exact bug class the plan named);
GateCallout ×12 (approval submit shapes, escalation label/fallback/free-text/recommended-mark,
superseded/stale/hash_known/inline-error arms, double-click disable); ResumeControl ×6;
RunProgress paused arms ×2; GraphView bridge ×7 (badge from run-complete AND run-snapshot,
auto-show + not-for-failed, dismiss + ⏸-click reopen, Approve→pin URL flip, Resume for failed
pinned + never-for-paused); 4 `RunInfo` factories += `paused_node_id: null`.
**Mutation-verified** (edit + inverse edit, no git): deleting the `runSnapshot` synthesis → the
snapshot test failed ALONE (56/57), exactly the plan's pin.

Deviations from plan (reasons, not handwaving):
1. **`runBadgeStatus` paused arm returns `"paused"`, not the plan-era `"stopped"`.** The plan's
   §P3-2 predates its own new badge arm: 171 mapped a paused banner to the amber "stopped" square
   because NO paused NodeStatus existed ("the closest badge"). With the ⏸ arm shipped, keeping the
   square would show a "process died" glyph for a healthy waiting run right next to the frontier
   node's ⏸ badge. Same amber; the one pinned test updated (its intent — "never the green success
   fallthrough" — is preserved and still asserted).
2. **StatusBadge label** is "Paused — awaiting an answer at this gate" (plan sketch: "paused —
   awaiting answer") — every other `runStatusLabel` arm is capitalized-verb + em-dash detail;
   matched the house voice. Tests assert via `aria-label` ("run status: paused"), unaffected.
3. **Buttons added beyond the plan's sketch**: a Cancel on the two ack dialogs (a confirm without
   a decline is a UX hole), a "recommended" mark on the matching escalation option (renders the
   payload's `recommendation` without repeating it as text). Presentation-only.

### Phase 4 complete (un-run greying — no cut-line needed, done well inside the session)

- `focus.ts::applyReplayDim(nodes, edges, status, active)` — the third pure restyle: join rule
  mirrors `applyStatus` exactly (leaves by own ref; hosts by the PRIMARY group's host ref); an
  edge dims when either endpoint is un-run; identity-stable + idempotent; `active=false` is an
  identity pass-through (live runs pay zero). One judgment call the plan left open, resolved by
  the applyFocus precedent: an EXPANDED un-run region contributes to the edge set but carries NO
  class — its children dim individually and a region opacity would compound with theirs
  (`applyFocus`'s groups-never-dim-unless-collapsed rule, mirrored).
- `LeafData`/`GroupData` gained `unrun?: boolean`; `WorkflowNode`/`GroupNode` render the class
  (collapsed group card is a `.node`, so `.node.unrun` covers it; regions never flagged).
- `useWorkflowGraph`: `replayDim` option; the pass runs AFTER applyFocus (it appends beside
  focus's edge classes). **Plan-gap found and closed**: the hook's `edgesUnchanged` skip (the
  Task-173 edge-blank fix) keyed only on `(laid, focus)` — a terminal replay's snapshot arriving
  on an unchanged pair would skip `setEdges` and the un-run edge dim would silently never paint.
  Added a third conjunct (`paintedDimRef`: the status map identity when active, null when not) —
  the live-run skip is preserved byte-for-byte (null === null).
- GraphView passes `replayDim: runId !== null && runBanner !== null` (pinned terminal only —
  paused/denied count as terminal; a pinned live run has no banner until its trailer).
- CSS: `.node.unrun, .react-flow__edge.edge-unrun { opacity: .45 }` placed BEFORE `.node.dimmed`
  (focus-dim 0.18 wins) and before `.hover-mark` (hover un-dims); BOTH orderings pinned in
  `cssOrder.test.ts` (2 new tests). 6 new node-env tests in `focus.test.ts` (pass-through,
  flag+edge rule, identity/idempotence, focus-class composition, collapsed-vs-expanded host,
  io/end never flagged).

Post-P4 verification: `tsc --noEmit` clean; vitest **773 passed** (baseline 731 → +42).
Docs: `components/CLAUDE.md` (StatusBadge status list + the approval-bridge entry),
`graph/CLAUDE.md` (applyReplayDim in the focus section), `views/CLAUDE.md` (gate-panel state
model + entry points + the ResumeControl gating).

### Phase 5 complete — full-branch deep review, fixes, real-browser verification, batteries

**Deep review** (5 agents on `git diff 979f44e6` incl. working tree: simplicity + agent-ux — the
two deliberately deferred from the §P2 checkpoint — plus silent-failures, test-fidelity,
feature-interactions on the frontend). Zero Criticals. Every finding verified first-hand before
acting:

Confirmed + FIXED (each with a test, the state one mutation-verified):
1. **`gateDismissed` never reset on `run-reset`** (silent-failures, Warning — the one real state
   bug): on follow-newest, `runId` never changes, so `selectRun`'s reset can't fire — one ✕ would
   silently mute every LATER run's gate auto-show (recoverable only via the ⏸-node click). Fix:
   `setGateDismissed(false)` in the `runReset` handler. Pin: "a dismissal never mutes a LATER
   run's gate" — **mutation-verified** (removing the line fails exactly that test).
2. **Singular `{"error": ...}` bodies collapsed to the generic HTTP line** (test-fidelity,
   Warning): `/api/gate`'s 404s (and every shape-400 house-wide) use the singular shape;
   `parseErrorBody` only read the plural array, so the panel showed "Server returned HTTP 404."
   instead of "Run 'X' is not paused at a gate." — and the new `fetchGate` 404 test had
   fabricated a plural body to pass. Fix at the ONE parse seam: `parseErrorBody` + `resumeRun`'s
   single-read arm now surface a singular `error` string; the 404 test now uses the REAL wire
   shape and asserts the message survives; +1 resumeRun singular-400 test.
3. **The two panels duplicated the refusal machine and dropped `suggestions`** (simplicity +
   agent-ux converging): extracted `components/resumeAnswer.tsx` — `useResumeAnswer` (state +
   the refusal dispatch: superseded / stale / side-effect / inline), `RefusalNotice` (the two
   action panels, context-worded), `GateErrors` (inline diagnostics NOW RENDERING each entry's
   `suggestions` — the RunForm rule; new ResumeControl test pins it). GateCallout/ResumeControl
   hold only their kind-specific content; ALL 18 existing component tests passed unmodified
   through the fold (behavior-preserving).
4. **hash_known=false wording** gained the WHY ("this run predates workflow-hash tracking"),
   matching the CLI's message (agent-ux Suggestion).

Disputed / won't-fix (documented): `_parse_resume_body`'s singular-400 shape is the house
convention across every endpoint (not drift — and now surfaced correctly client-side anyway);
the deep-link double-`frameOnMount` (run callout + gate callout) resolves by JSX order — the
gate frames last and wins, confirmed the desired landing in the browser pass.

**Real-browser verification** (stale server killed first, `make ui-build`, fresh `pflow ui`;
screenshot-pflow-web-ui skill; three demo workflows in `/tmp/pflow-176-demo/`, the escalation
via a REAL `claude-code` step — a `code` node cannot durably pause, `_gate_pausable` excludes
dynamic routers; the demo authoring itself re-verified that conjunct):
- UI-launched approval run → paused; `paused_node_id` on `/api/runs`; `/api/gate` serves the
  masked payload; ⏸ badge on the frontier; GateCallout auto-shown with preview + Deny/Approve;
  un-run tail dimmed. Click Approve → browser pinned the NEW attempt instantly (URL flipped),
  run success, `resumed_from` chain, restored step reads the grey cached ✓.
- Deliberate refusal: Approve on the already-answered source run → superseded panel
  ("View newer attempt") — the no-silent-no-op rule proven in the browser.
- Deny → denied attempt pinned, amber "Run denied", never-ran steps greyed.
- Escalation (real claude-code producer) → question + option buttons (descriptions + the
  RECOMMENDED mark) + free-text row render; option click → new attempt success and the chosen
  LABEL folded into `result.escalation.decision.chosen` (verified via `/api/run-node`).
  Free-text answer verified END-TO-END on a second escalation run via the exact POST the
  panel's Answer button sends (the skill can click but not type — the typed path is
  unit-pinned in GateCallout.test.tsx; deviation noted, coverage equivalent).
- Failed run (side-effecting shell entry) → ResumeControl under the spine; ↻ Resume → inline
  dialog naming `deploy (shell)` — the REGISTRY type — with Cancel/Resume anyway and NO spawn;
  the ack's `force:true` POST spawns (wire-verified; the ack click itself is unit-pinned).
  Idempotent-llm-entry no-dialog: not browser-driven (needs a failed llm-entry run) — covered
  by the P2 verdict-matrix test (llm → None) + endpoint pins.
- `403` on non-loopback Host for BOTH `/api/gate` and `/api/resume` (middleware verified, not
  re-implemented).
- Greying composition: TD + advanced + `focus=` — un-run nodes at 0.45, focus-dim (0.18) wins
  on non-incident un-run nodes, edges into the un-run region dimmed; beautiful/LR covered by the
  earlier shots. Two-callout overlap (braindump worry): fine — different anchors side-by-side;
  for a no-input workflow whose FIRST step is the gate both anchor the same node and STACK
  (gate on top — the say-bubble precedent, dismissing reveals the run callout; accepted).

**Final batteries** (vs this session's baseline): `make test` **8777** (unchanged — zero
`src/pflow` edits this session; the checkpoint fixes were already committed), `make check`
green, vitest **776** (731 → +45), `tsc --noEmit` clean. Task-159 baseline skipped per plan
(nothing trace-adjacent moved). Windows: rides the blocking `tests-windows` CI job (the spawn
helper was P2, already committed).

Key learnings for the next agent:
- `GateRequest.node_type` carries the Python CLASS name (`ShellNode`) — payload parity with the
  TTY prompt, so the gate eyebrow shows it too; the side-effect refusal carries the REGISTRY
  type (`shell`) via `_node_registry_type`. Two vocabularies, both correct per their contracts —
  don't "fix" one into the other without an owner decision.
- The escalation demo MUST be a `claude-code` step: `_gate_pausable` refuses code-node
  escalations (dynamic router), and the error path (exit 1, not pause) looks like a bridge bug
  until you read the conjuncts.
- `/api/run`'s pre-flight requires an input that has a default but no `required: false` — the
  RunPanel form prefills it so browser launches work; a bare curl must pass it explicitly.

## 2026-07-12 — Post-close review round (PR #579 open): 2 targeted sonnet agents + fixes

User-directed third review round on the un-reviewed axes: `review-impact-completeness` on the
full branch (its first look at the frontend half) + a security review (first of the task), with
the driver making an independent pass under those two lenses + simplicity. Security: zero
criticals/warnings; every masking exit re-verified (incl. the `answer_required` message TEXT —
masked at construction via `format_gate_lines`). Impact: everything Verified Complete except ONE
confirmed Warning. Both driver-verified first-hand before acting.

**Fixed (each mutation-verified):**
1. **Escalation-pause status clobber** (impact-completeness, Warning — the round's one real
   finding): `pausedEntry` unconditionally replaced the frontier node's `runStatus` entry with a
   bare `{status:"paused"}`. Correct for approvals (the gated step never ran); for ESCALATIONS the
   frontier IS the already-completed escalating step (`last_completed_node_id == paused_node_id`)
   — the overwrite dropped its metrics + event id, so the badge hover lost duration/cost and
   `TERMINAL_RUN_STATUSES` (a pre-existing consumer) closed the "This run" section during the
   exact window a human decides the escalation (and permanently on the source run's replay).
   Fix: `pausedEntry` → `pausedKey`; both call sites MERGE (`{...prev.get(key), status:"paused"}`);
   `showRunDetail` gains a paused-WITH-id arm (an approval pause has no id → stays closed by
   construction). Pins: "an ESCALATION pause merges …" (fails under BOTH the clobber mutation and
   the arm removal) + "an APPROVAL pause … keeps 'This run' closed" (fails if the id conjunct is
   dropped — over-open guard; `fetchRunNode` asserted un-called). vitest 62→ (GraphView 60/60),
   tsc clean.
2. **Dash-prefixed resume target guard** (security review, Note — confirmed-unreachable, hardened
   anyway): a `run` target matching a KNOWN `pflow resume` option name is consumed as that FLAG
   by the child (`ignore_unknown_options` only passes through UNRECOGNIZED dash tokens — verified
   empirically with the command's exact context_settings) → zero positionals, exit 2 into DEVNULL.
   Unreachable via real targets (uuid ids; workflow names forbid leading hyphens) but the guard
   makes the no-silent-no-op rule structural. Fix: argv parity guard #2 in `_parse_resume_body`
   (400 before any I/O). Pin: `test_dash_prefixed_target_is_400_and_does_not_spawn` — mutation-
   verified (guard disabled → fails); server test file 90/90.

**Take-or-leave, deliberately NOT taken:** `resumeRun` re-implements `parseErrorBody`'s
plural→singular→generic fallback inline (the single-read rule) — a shared `errorsFromPayload`
would fold ~6 lines; churn outweighs gain (driver simplicity pass + owner).

Docs: `ui/CLAUDE.md` (/api/resume guard list), `web/src/views/CLAUDE.md` (merge synthesis + the
paused-with-id arm), `task-review.md` (the invariant now states MERGE, never replace).

**Addendum (same day):** triaged the PR's `claude-review` CI comment (posted at PR creation) —
its verified section matches this round's findings; its argv-safety note is superseded by the
dash-guard above; its `=`-path suggestion is already documented-acceptable. One micro-item
adopted: `useResumeAnswer.submit` now clears `superseded` too (was terminal-by-invariant only —
`refusal` prioritizes superseded over confirm, so a stuck value would mask later refusals if a
retry affordance is ever added). vitest 778 green, tsc clean.

## 2026-07-12 — Live human use: select-then-Answer for escalation options (owner decision)

First real human use of the escalation panel surfaced a UX flaw the reviews missed: option
cards were ONE-CLICK answers, and the owner mis-clicked "merge" (not the recommended option) —
the token was consumed and the workflow acted on the wrong decision. The cards' affordance
reads "select", the Answer button read as the confirm, and an answer is irreversible — the
browser was the LEAST deliberate of the three answer surfaces (the TTY needs type+Enter; the
CLI needs a typed command).

Owner decided (mockup-confirmed): **select-then-Answer** — option click SELECTS
(`aria-pressed`, `.gate-selected` highlight, beats `.gate-recommended` by specificity); the one
Answer button submits whichever source is active and names the selection
(`Answer with “per-env”`); selecting clears the text, typing clears the selection (always
exactly one unambiguous source); disabled when neither. Approve/Deny stay one-click (explicit
action verbs, kind-correct affordance).

Tests: the two option-click tests now pin "option click alone NEVER posts" +
Answer-submits-the-LABEL; new mutual-exclusion pin (one submit at the END — a successful
submit latches `submitting`, the panel unmounts in production). GateCallout 13/13, vitest 779,
tsc clean. Docs: components/CLAUDE.md, guide ui.md + resume.md ("their click" → "their
answer"). Verified live in the browser by the owner on a fresh gated run.

**Layout iteration (same session, owner-driven):** the first select-then-Answer shape put the
dynamic `Answer with “X”` label beside the input — it clipped the placeholder and pushed the
panel past `.node-callout`'s 320px max-height (scrollbar). Owner preferred the original one-row
input+button layout: the button label is now STATIC ("Answer"), the named answer rides its
hover `title`, and the highlighted card is the visible confirmation. Long answers: typed text
never rides the button; option labels appear in full on the selected card. Browser-measured:
gate body 253/253 (no scroll), input 232px (placeholder whole), same row. GateCallout 13/13,
vitest 779, tsc clean.

## 2026-07-12 — Session close-out (post-close review + live-use session)

Commit anchors for the entries above (written pre-commit): the post-close review fixes
(escalation-pause merge, dash-target guard, superseded clear) are `e2e4e750`; the
select-then-Answer escalation UX + one-row layout iteration is `9e2a9c66`. Both pushed to
PR #579 with [skip review].

**Real-browser verification of the escalation-clobber fix** (between the two commits; stale
server killed + `make ui-build` first, per the recorded gotcha): on a pinned paused escalation
(superseded source runs keep their paused trailers — no live producer needed), clicking the ⏸
escalating step opened "This run" with the recorded completion — measured via a scratchpad
click-and-inspect workflow: `status: success · 11s · $0.09 · 41,877 in / 445 out` + realized
input, WHILE the canvas badge read ⏸ and the gate panel stood open (screenshot evidence
reviewed). Inverse: an approval-paused run (`publish-notes` never ran) kept the section closed
(`thisRunPresent: false`, `fetchRunNode` never called). Also spot-confirmed the run-node
reader's secret redaction in the served output (`<REDACTED>`).

The select-then-Answer flow was then exercised END-TO-END by the owner on fresh UI-launched
gated runs (the mis-click that triggered the redesign consumed a real token with the wrong
option — the strongest possible validation of the two-step shape). Final layout
browser-measured: gate body 253/253 (no scroll), input row intact.

**Cleanup state:** the demo `pflow ui` server is killed. The task-176 demo/verification traces
in `~/.pflow/debug` (56 files: escalate/approve/fail-demo runs + the click/screenshot check
runs) and `/tmp/pflow-176-demo` + `/tmp/pflow-shots` were listed for deletion but left in place
(owner declined the bulk rm at the prompt — delete by hand or let trace retention (#542) handle
them). One escalate-demo run may still sit paused at its gate; answering or ignoring it is
harmless (durable pause, no live process).

**Open at close:** rebase onto main once the `task-N.md` docs-test fix lands there (the only
red CI, inherited); the take-or-leave `errorsFromPayload` fold remains deliberately not taken.

## 2026-07-12 — Panel readability follow-ups (post-close live-use session, feat(ui))

Using the shipped bridge end-to-end (IO outputs question → real runs in the browser) surfaced
three side-panel comprehension gaps. Fixed on this branch as `feat(ui)` — not task-176 scope,
but its verification surfaces; each browser-verified with the screenshot skill (stale server
killed + `make ui-build` first, per the recorded gotcha).

**`9a8dc0df` — panel source/output links + expandable value boxes.** (1) Every value box
(params, code, prompts, batch items, errors, run values) carries a ⛶ expand → portaled
full-screen modal (Esc/backdrop/×); the affordance lives in `CodeBlock` itself — first placed
in `RunValue`, owner immediately asked "why not params?" and it moved DOWN to the one seam all
boxes share (`expandLabel` titles; `null` = the modal's recursion guard; empty value → no
button). Position user-tuned twice (right: 14→18→21px, off the box scrollbar). (2) Every
source `file:line` is a LINK to its OWN line — node header, per-param (ReadPanel + EdgePanel
Receives), per-port (IoPanel) — via a new `SourcePane.jumpTarget` (io selections set no
selectedNode to fall back on). Real bug caught by browser verification, then pinned: on a
closed→open jump the pane mounts with `prevJump` seeded to the already-bumped counter → the
first jump no-ops and the io-heading sync wins (landed on `## Outputs` line 72 instead of the
port's :78). Fix: seed `prevJump` null so the jump effect also runs on mount. (3) An IoPanel
output's field path (`.stdout`) SELECTS the producer (both `onNavigate` args — opens its
ReadPanel where the recorded output lives; deliberately more than the chip beside it, which
navigates without opening; unresolvable → plain text, the Chip rule).

**`197b0827` — dict run values expand to a per-field document.** Owner: escaped `\n` JSON is
unreadable — "this is for being able to read the data easily". Decision from the discussion:
the modal is a READING surface (compact box = shape); a text-level `\n`→newline replace was
REJECTED (invalid-JSON-that-looks-like-JSON, `\\n` vs `\n` ambiguity) — instead the modal
renders the ORIGINAL values: dict → labeled block per top-level key, strings as real text,
non-strings pretty JSON. Mechanism: `modalBody` slot on CodeBlock's modal that only `RunValue`
fills — authored params keep rendering exactly as authored BY CONSTRUCTION (a literal `\n` in
a code param is content). Top-level only; arrays stay JSON (wait-for-a-real-case).

**Deliberate remainder → issue #580** (inline/recursive unwrap of nested run values): the
inline "This run"/port boxes stay generic JSON below the first level — Task 173's recorded
simplicity decision, now partially relieved by the modal doc-view. #580 carries the full code
map, design questions (inline density/collapse, recursion depth, arrays), non-goals (authored
params; no text-level replaces), and the pickup trigger (only if inline JSON still hurts after
living with the modal). PR #579 body gained a "Post-close follow-ups" section anchoring all of
this.

State after session: vitest 796 (+20 pins incl. mutation-caught SourcePane mount-jump), tsc
clean, all pushed. Demo assets: `scratchpads/io-output-check/` (gitignored) holds the io-demo
fixture + click-click/click-scroll browser harnesses used throughout; a `pflow ui` server may
still be running on :8765.

## 2026-07-12 — Review response: 3 PR-comment reviews on `9a8dc0df`/`197b0827` (feat(ui))

Three CI/bot code reviews landed on the readability-follow-up commits (PR #579 comments
`4951249333`, `4951322132`, `4951322969`). Evaluated each finding against code first-hand
(2 searchers + direct reads); consolidated to 6 distinct findings (heavy overlap). One real
regression (2 reviewers raised it identically), two cheap cleanups, one a11y polish (all 3
reviewers), two no-action notes. All fixes frontend-only, each mutation-verified (edit + revert,
no git).

**Fixed:**
1. **Stale `sourceJumpTarget` on Rail-toggle reopen** (the one Warning, review-confirmed +
   verified). `SourcePane` is conditionally mounted, and `9a8dc0df` reseeded `prevJump` to null
   so the mount-jump fires on every remount. `sourceJumpTarget` (GraphView) is only ever SET
   (`openSourceAt`), never cleared — so: click a source link → select another node → close pane
   → reopen via the Rail toggle re-fired the STALE target, landing on the old link's line. Fix:
   `changeSourceOpen` clears the target on close (`if (!open) setSourceJumpTarget(null)`); the
   `!open` guard leaves `openSourceAt`'s just-set target intact. Regression pin in
   `GraphView.test.tsx` ("reopening…falls back to the newly-selected node") — the ONLY place it
   fails on revert (a SourcePane-level test can't, props are inputs); **mutation-verified**
   (removing the guard → the reopened pane marks the stale line 3, waitFor(line 7) times out).
2. **Empty dict `{}` → blank per-field modal** (Suggestion). `isPlainDict({})` is true and
   `code` is `"{}"` (non-empty, so CodeBlock's `code===""` guard misses it) → `ValueDoc` over
   zero entries rendered a blank document. Fix (refined from the reviewer's — gate the doc-view,
   not the button): `modalBody` gated on `Object.keys(value).length > 0`, so `{}` expands to plain
   `{}` via the CodeBlock fallback. Pin + **mutation-verified**.
3. **string-vs-JSON rule duplicated** (Suggestion; one reviewer over-counted to 3 — the CodeBlock
   modal fallback is a pass-through, not a re-derivation). Real count 2, both in `RunValue.tsx`.
   Folded into a `fieldCode(v) → {code, lang}` helper shared by `RunValue` + `ValueDoc`. Covered
   by the existing dict/array pins (green unmodified).
4. **Modal a11y** (Suggestion, all 3 reviewers). Cheap slice taken: focus moves to × on open
   (Esc works without a prior click), restores to the ⛶ trigger on close, page scroll locked
   behind the overlay — mount-only effect (`[]`), because the inline `onClose` gets a fresh
   identity each render (merging would re-steal focus + capture the × as the restore target). Full
   focus-trap deliberately deferred (more code, marginal on a read-only viewer). Pin +
   **mutation-verified**.

**No action (notes, review-acknowledged as such):** per-box `window` Escape listeners (one modal
open at a time — harmless); the `.code-box` wrapper DOM change (browser-verified in the prior
session; no parent relies on a direct-child `<pre>`).

Docs: `components/CLAUDE.md` (modal focus/scroll + empty-dict + `fieldCode` single-source; the
`sourceJumpTarget` close-clear coupling). Batteries: `tsc --noEmit` clean, vitest **799** (796 →
+3 pins). No `src/pflow` (Python) edits — `make test`/`make check` unaffected.

**Real-browser verification** (stale server killed + `make ui-build` first, per the recorded
gotcha; a throwaway chrome-devtools driver workflow drove the multi-step sequences the one-click
harness can't, then deleted). On `conditional-branching` (advanced, source pane):
- **Fix [1]** — select `fetch-data` → click its header source LINK (pane jumps to line 8) → Hide
  source via the Rail toggle → select `classify` → Show source: the reopened pane marks
  **line 18** (classify), NOT the stale link target line 8. `{lineAfterLink:"8",
  lineAfterReopen:"18", pass:true}`. Screenshot confirms line 18 highlighted in the pane.
- **Fix [4]** — open a param value modal: `activeElement` = the × ("Close"), `body.overflow` =
  "hidden"; close → overflow restored to "" and focus returned to the ⛶ trigger.
  `{triggerFocused:true, activeLabelWhileOpen:"Close", overflowWhileOpen:"hidden",
  overflowAfterClose:"", focusRestored:true, pass:true}`.
- Fixes [2] (empty-dict) and [3] (`fieldCode` fold) not browser-driven — [2] needs a real run
  emitting `{}`, [3] is behavior-preserving; both jsdom-pinned + mutation-verified. Canvas +
  panels render with no visual regression from the CodeBlock/RunValue/GraphView edits.
