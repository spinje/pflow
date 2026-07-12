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
