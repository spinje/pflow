# Task 171 Review: Durable Resume Tokens & Non-TTY Gates

> **COMPLETE — all five phases shipped (2026-07-05).** Phases 0–3 + the inline-pause decision
> were written by the Phase-2/3 implementer while context was live; the Phase 4 (UI) and Phase 5
> (docs) sections at the end were filled by the finisher. Task spec status is `done`.

## Metadata

- Implemented 2026-07-04 → 2026-07-05, branch `feat/durable-resume-tokens` (not merged, unpushed).
- Commits (9): `a8066f15` (P0 loader extraction), `cf60b197` (P1 producer), `8125454a`
  (P2 loader answer arm), `ddb078e5` (P3 CLI — carries the inline producer refusal),
  `3db03f0e`+`fde74150` (P4 UI), `6ba7b7cd` (P5 docs + task close), `7713f138` (deep-review
  fixes — the `is_durable_pause` durability home + the `--only` producer conjunct),
  `c1440930` (agent-UX wording on 3 surfaces).
- Follow-up filed: **#562** (make inline workflows resumable — workflow content in the trace).
- Gates (final, whole branch): `make check` green, `make test` **8662 passed**, `make test-e2e` 44.

## Read First — the load-bearing block

**What exists now:** a gate firing in a non-TTY run finalizes the trace `paused` (exit 4, token
on stdout, gate content on stderr/JSON/MCP); `pflow resume <token> --approve yes|no` /
`--choose "<answer>"` restores upstream and continues without re-executing completed steps;
`pflow resume list` shows pending unanswered pauses. The trace IS the checkpoint — no second
state file, no second serializer.

**Read these first:**
- `runtime/engine/engine.py` — the gate except arm (~line 1495, the ONLY `paused` producer)
  + `_gate_pausable` (~line 97). Every conjunct has a reason; see Gotchas before touching.
- `runtime/resume_source.py` — `load_resume_source`, `_apply_paused_answer` (the whole answer
  policy), `_attempt_consumed_work`/`_find_consuming_attempt` (the ONE consumption policy),
  `list_paused_runs`.
- `cli/commands/resume.py` — `ResumeGroup` (default-subcommand routing), `resume_run`,
  `_prime_approval_delivery`, `_resolve_between_nodes_entry`.
- `execution/gate_prompt.py` — `build_gate_resolver` (`deny=` is `--approve no`'s delivery),
  `format_gate_lines` / `format_resume_answer_command` (the ONE render shape).
- `tests/test_cli/test_paused_cli.py` — the e2e answer battery doubles as the executable spec.

**Invariants that must NOT break:**
- **Pause is a promise.** Every `paused` stamp must yield a token the resume path accepts. The
  producer mirrors the resume-side refusals conjunct-for-conjunct: nested/batch gates,
  loop/`code`/terminal escalations, `--no-trace`, `--only` (its snapshot trace is excluded from
  every resume consumer), and inline (`ir-hash:`/`None` workflow_path) runs all stay `failed`.
  Breaking the mirror strands humans with dead tokens.
- **One consumption policy.** `_find_consuming_attempt` (backed by `_attempt_consumed_work`)
  serves the loader's superseded check, by-name selection, AND `resume list`. A fork here means
  "list says answerable, resume says superseded" — or a chain that forks (two answerable tokens
  for one logical run, double-firing side effects).
- **Verdict resolutions are exactly `{"approved","denied","choice"}`.** Counting
  `non_interactive`/`error` as consumption lets a re-pause or a resolver bug wedge a chain.
- **Answer validation → fold → seed guards, in that order** (`load_resume_source`). Reordered,
  an unanswered pause refuses with the guard's "re-run the workflow" — the wrong remedy (the
  right one is: answer it). 11 tests bite on reorder.
- Inherited and still binding: `_seedable_final_events` is the ONE seed derivation; gate lines
  are disk-only; `_iter_workflow_traces` never gains a `final_status` filter; `runtime/` never
  imports `ui/` (enforced by `test_import_hygiene.py::test_runtime_does_not_import_ui`);
  `GateRequest`/`GateResolution` shapes are frozen; exit-code vocabulary 0/1/2/3/4/130.

## What Was Built (actual vs. planned)

The plan (`implementation/implementation-plan.md`) was followed closely; deviations, each with
the reason it beat the plan:

- **Numeric `--choose`→label mapping lives in the LOADER**, not the CLI (plan 3b's prose said
  CLI): only the loader holds `gate_request["options"]` at answer time. The CLI passes the raw
  string; `_map_choose_answer` mirrors the blocking prompt's strip+digit rule via the shared
  `option_labels` (`core/gate.py` — extracted so prompt render, pause output, and mapping are
  literally one function).
- **Bare `pflow resume` renders group help (exit 0)** instead of "Missing TARGET" (exit 2).
  Click-group reality + deliberate choice: the hidden `run` subcommand contributes nothing to
  `--help`, so the group docstring IS the `--approve`/`--choose` discoverability surface, and
  bare-invoke landing on it is a feature. A flag-without-target still hard-errors exit 2.
  Consequence: workflows literally named `run`/`list` are reserved (resume by path/id).
- **`not_paused` answer-flag check fires AFTER the status arms**, so "already succeeded" beats
  a flag-usage complaint (plan didn't pin ordering).
- **Deny produces a denied attempt trace** (exit 3, `_display_denied_result`'s wording), not the
  spec's literal "Workflow cancelled at step X" message — one denied rendering everywhere, and
  the attempt trace is what consumes the token.
- **Inline gated runs never pause** (owner decision post-plan, option a): two conjuncts in the
  engine arm (`workflow_path` non-None and not `ir-hash:`). #562 tracks option b; two pins in
  `TestInlinePausePromise` flip when it lands.
- **Empty/whitespace `--choose` = `missing_answer`** (owner review): the blocking prompt can't
  produce an empty answer, so the durable path must not accept one.
- Smaller: `_apply_paused_answer` extracted as the one answer-policy seam (ruff C901 forced it;
  it's the better shape anyway); engine↔planner paused parity pins pulled forward from the
  plan's Phase-3 test list into Phase 2.

Phase 3e (`resume list`) was implemented by a full-context fork subagent against a frozen
interface; its diff was reviewed line-by-line by the primary implementer.

**Post-review hardening** (deep review — 6 agents — then adversarial manual E2E; commits
`7713f138`, `c1440930`). No Critical findings; the confirmed issues were pause-promise holes on
secondary surfaces. What a future agent must know:

- **`ExecutionResult.is_durable_pause` (`execution/result.py`) is THE durability home.** A gate can
  stamp `paused` in memory (`gate_outcome == "paused"`) while the streamed trace dies mid-run
  (full/read-only `~/.pflow/debug` → `_stream_failed`, no `run.complete` trailer) — the token would
  never resolve. Both the CLI paused branch AND the MCP paused branch now gate on this ONE property
  (`status is PAUSED ∧ trace ∧ not _stream_failed`). The CLI's old `_durable_pause` helper was
  deleted; MCP previously checked a bare `status is PAUSED` and handed out a dead token on a disk
  fault. A non-durable pause falls through to the failure/remediation path. `--no-trace` never
  reaches here (the runner's `trace_enabled` conjunct maps it to FAILED first).
- **`--only` is the sixth producer conjunct** (`only_node is None`, in the engine arm). An `--only`
  gate used to stamp `paused` and print a token no resume consumer can resolve (all exclude
  `only_node` traces). `--only` is now named in `GateNotInteractiveError`'s remediation. Pinned by
  `test_gate_pause.py::TestOnlyPausePromise`.
- **`masked_gate_dict` (`core/gate.py`) is the dict-form gate-masking home.** The mask-only policy
  was mirrored 3 ways (paused JSON doc, `ResumeAnswerRequiredError.to_diagnostics`,
  `exceptions._masked_gate_payload`); all now delegate. `_masked_gate_payload` is the object-form
  twin (`request.to_dict()` → `masked_gate_dict`).
- **Three agent-UX wording fixes (no correctness impact; pflow is agent-first, so emitted strings
  must not misdirect).** (1) `--dry-run` + an answer flag no longer advertises the just-answered
  gate — `format_plan_text(plan, answered_gate_ids=)` drops gates in `auto_approve ∪ gate_deny`
  from the footer (general win: `--dry-run --auto-approve X` omits X too). (2) `--only <gated>`
  pre-flight says "fail at", not "pause at" (verb keys on `trace AND only_node`, matching
  `_gate_pausable`). (3) `ResumeStaleWorkflowError` reads "since the original run" (serves failed /
  interrupted / paused alike), not "since the failed run".

## Patterns & Anti-Patterns

**Patterns to propagate:**
- **Answer delivery = resolver priming, never new machinery.** `--approve yes` appends the
  paused node to the resolver's `auto_approve` set; `--approve no` to the new `deny` set. The
  gate RE-FIRES in the resume run and records an honest resolution line — trace stays truthful,
  zero new delivery paths. `--choose` needs no resolver at all: the loader folds the decision
  into the restored event and the engine's existing re-record loop persists it.
- **One rule, one home, N consumers**: `option_labels`, `masked_gate_dict`,
  `format_resume_answer_command`, `format_gate_lines`, `_fold_decision_into_event`,
  `_find_consuming_attempt`, `is_durable_pause`. When two surfaces must agree on a rule, extract
  the rule — don't mirror it. (`masked_gate_dict` and `is_durable_pause` were extracted in the
  deep-review round precisely because CLI and MCP had each mirrored the policy — see below.)
- **Mutation-verify every subtle pin** (Edit + revert, never stash). Each ★ assertion in this
  task was proven to fail under its target mutation; several fail ALONE (see Tests).
- **Registry injection for CLI-level custom test nodes**: `test_paused_cli.py::
  escalating_registry` — the runner pipeline requires the full scanner entry shape including
  `interface` (bare `compile_workflow` does not). NEVER run the injection snippet outside
  pytest: `Registry()` then hits the real `~/.pflow/registry.json`.

**Rejected approaches (do not re-derive):**
- Any id-comparison for the nesting guard (`request.node_id == config.node_id`,
  `host_frame is None`, collector introspection) — the elimination chain is in
  `starting-context/braindump-2026-07-05-planning-session.md`; only "root engine caught it
  first-hand" (first-seen tag + `nested` flag) survives all propagation shapes.
- Fold-and-complete for final-step escalations (needs an execute-nothing engine mode); moot —
  the producer never emits that token.
- Message-only deny (leaves the token pending in `resume list` forever).
- A `kind` field on `ResumeSource` (read `gate_request["kind"]` — the payload is the seam).
- `allow_interspersed_args` on the GROUP (empirically inert; it belongs on the `run`
  subcommand — spike-verified across 4 configs × 11 invocations).

## Gotchas & Non-Obvious Coupling

- **The engine gate arm is the highest-precision edit surface in the feature.** Conjunct order
  (6, all AND-ed): `isinstance GateNotInteractiveError → not parallel_batch → originating →
  not nested → only_node is None → workflow_path real (not ir-hash:/None) → _gate_pausable`.
  The isinstance guard short-circuits attribute access
  for `GateDenied`/`GateResolverError`; `_gate_pausable`'s approval early-return keeps the arm
  safe at step 7.5 where `action` would otherwise be unbound (a pre-bound `action: Any = None`
  default exists for exactly this — Phase 1 found the plan's snippet crashed without it).
- **Engine-level tests MUST pass `workflow_path`** when they assert pause behavior. Production
  root engines always get it (`runner.py` passes `_workflow_path_id(resolved)`); a rootless
  test engine now reads as inline → `failed` — and worse, a pin asserting `failed` then passes
  for the WRONG reason and silently dies (this exact failure mode was caught and fixed for the
  id-collision pin when the inline conjunct landed).
- **`ResumeSource.paused_node_id is not None` is THE paused discriminator** CLI-side: it gates
  the side-effect-confirm skip and approval priming. Approval entry == `paused_node_id`
  (the node has NO trace event — gate fires before `node.start`, so the seed scope excludes it
  by construction); escalation entry is `(None, paused_node_id)` — deliberately the incomplete
  between-nodes shape so `_resolve_between_nodes_entry` is reused verbatim.
- **`gate_answer` shapes are a cross-file contract**: `{"approve": bool}` vs
  `{"chosen": <raw str>, "notes": None}`, discriminated by KEY (`"approve" in gate_answer`).
  The CLI never interprets the answer beyond building the dict.
- **The pause trailer keys ride generic round-trip**: `paused_node_id`/`gate_request` are
  plain trailer keys (`reconstruct_trace_from_lines` copies non-`kind` keys verbatim) and land
  FLAT on the loaded dict. Do NOT add them to `META_KEYS` — and note the test-fixture builder
  routes keys by META_KEYS membership, so moving a key silently relocates fixtures' data.
- **A paused trailer can exceed 64KB** (it carries the full `gate_request`).
  `_read_trailer_line` has the oversized-trailer full-re-read branch (mirrored from
  `ui/run_tailer.read_run_status` — accepted duplication, `runtime/ ↛ ui/`); dropping it makes
  `resume list` silently hide big-preview pauses.
- **`exceptions.py` lazily imports `execution/gate_prompt`** inside
  `ResumeAnswerRequiredError` (core→execution at raise time; precedent `core/trace_report.py`).
  A layering IOU: if a third consumer of `format_gate_lines` appears, move it to `core/` like
  `option_labels`.
- **Unknown flags on `resume` are swallowed by the group** (`ignore_unknown_options` class
  attr — load-bearing for options-before-target) and rejected one layer down by
  `_split_target_and_params`. Same GH#454 tradeoff as the root `PflowCLI`. You cannot have
  group-level unknown-flag errors AND `resume --approve yes <id>` — the spike proved it.
- **Output auto-detect prefers `result` over `stdout`**, so a restored escalation marker
  out-shadows the consumer's output — identical to an uninterrupted run, but surprising in
  resume tests; declare `## Outputs` in fixtures.
- **MCP has no deny/answer surface in v1**: `execution_service.py` builds its resolver directly
  (no `ctx.obj`) with default-empty `deny`. MCP answers happen via the CLI token.

## Integration Points

- **New CLI surface**: `resume` is a `click.Group` (`ResumeGroup`); `main.py` registers
  `resume` (the old `resume_cmd` symbol is gone). Hidden `run` = default form; `list` added.
  Exit 4 = paused (documented beside DENIED's 3 in `core/workflow/status.py`).
- **`build_gate_resolver(auto_approve, oc, *, deny=frozenset())`** — keyword-only with default,
  so all pre-existing call sites (CLI, MCP, ~17 tests) are untouched. Threading:
  `ctx.obj["gate_deny"]` set in `run.py` (always `()`) and `_dispatch_resume` (non-empty only
  for `--approve no`) → `_prepare_gate_resolver`.
- **`load_resume_source(..., gate_answer=)`** — threaded through all three call sites in
  `_load_source_and_workflow`; by-id and by-name validate identically.
- **`resume_source.py` exports grew**: `PausedRun`, `list_paused_runs` (consumed by the `list`
  renderer); `ResumeSource` grew `paused_node_id`/`gate_request` (planner consumes the same
  object — parity by construction, pinned).
- **The trace format is unchanged since 2.7.0** (Phase 1). The only producer-logic changes after
  Phase 1 were two pause-promise conjuncts — inline `ir-hash:`/None (`ddb078e5`) and `--only`
  (`7713f138`) — both keeping a non-resumable run `failed`; neither touches the format.
- **`ExecutionResult.is_durable_pause`** (`execution/result.py`) is a new cross-surface contract:
  the CLI paused branch (`run.py::_display_execution_result`) and the MCP paused branch
  (`execution_service.py::execute_workflow`) both consume it. A third paused surface (e.g. the
  Task-176 web bridge) must gate on it too, never on a bare `status is PAUSED`.
- **Depends on (unchanged 164/125 machinery)**: `seed_walk_entry`, `_seedable_final_events`,
  re-record loop, `_apply_gate_resolutions`, hash gate, `run_approval_gate`/17.7 escalation
  seam — all consumed, none modified.

## Tests That Matter

Run when touching this area: `tests/test_runtime/test_resume_source.py`,
`test_runtime/test_resume_engine.py`, `test_runtime/test_gate_pause.py`,
`test_runtime/test_gate_trace.py`, `test_cli/test_resume_cli.py`, `test_cli/test_paused_cli.py`,
`test_cli/test_resume_list_cli.py`, `test_execution/test_gate_prompt.py`,
`test_execution/test_plan_drift.py` (the paused parity pair). All mutation-verified claims below
were proven by Edit+revert:

- `test_gate_pause.py::TestNestingGuard::test_child_gate_with_id_colliding_parent_host_stays_failed`
  — fails ALONE under the naive id-comparison "simplification" (verified twice: Phase 1 and
  again after the inline conjunct). The single most important pin in the producer.
- `test_paused_cli.py::test_approve_no_denies_cleanly_and_double_deny_is_superseded` — the ONLY
  test that catches dropping consumption clause (a) (verdict lines).
- `test_paused_cli.py::test_first_node_pause_resumes_by_workflow_path` +
  `test_restored_only_paused_attempt_supersedes_its_source` — the only catchers of clause (b)
  (`paused ⇒ consumed`); guard by-name selection and chain-fork prevention respectively.
- `test_resume_source.py::test_paused_without_answer_refuses_with_gate_content_not_the_guard`
  — the fold/validation-before-guards ordering (11 tests fail on reorder; this one names it).
- `test_resume_list_cli.py::test_oversized_trailer_*` — fails alone if the trailer full-re-read
  branch is dropped.
- `test_gate_pause.py::TestInlinePausePromise` (both) — fail exactly when the inline conjuncts
  are removed; they FLIP when #562 lands.
- `test_gate_pause.py::TestOnlyPausePromise` — fails when the `--only` conjunct is dropped (the
  deep-review producer fix); also pins that the remediation names `--only`.
- `test_execution_workflow.py::...test_stream_faulted_pause_raises_not_a_dead_token` — the MCP
  `is_durable_pause` pin: dropping the `_stream_failed` conjunct returns a dead token instead.
- Keystones (real producer traces, not synthetic):
  `test_resume_engine.py::test_non_interactive_gate_pause_loads_with_answer_and_resumes_e2e`
  (approval, full WorkflowRunner), `test_gate_pause.py::test_paused_escalation_real_trace_
  choose_answer_roundtrip` (escalation, engine-level re-record), and
  `test_paused_cli.py::test_escalation_pause_choose_answers_and_completes` (real CLI).
- Parity nets: `test_plan_drift.py::test_engine_and_planner_paused_{approval,escalation}_entry_state_match`.

## Phase 4 (UI) — shipped 2026-07-05

What shipped (plan followed exactly; details + file list in the progress log's Phase-4 entry):
- `/api/runs` entries gain `resumed_from` (`ui/server.py::_run_entry`; the meta line already
  carried it — `run_tailer._read_meta` pops only `inputs`); `RunInfo` mirrors it in
  `web/src/types.ts`; the `/api/runs` contract block in `ui/CLAUDE.md` updated with the edit.
- **The green-✓-for-paused regression is FIXED**: `RunProgress.runBadgeStatus` gains a
  `paused` arm (amber, mirroring denied) before the success fallthrough; `.run-paused` CSS
  beside all three `.run-denied` sites; defensive `paused` arms in
  `success_formatter.py`/`workflow_output.py` (⏸ lines, same never-✓ intent).
- `RunSelector.runMark`: `⏸`/`run-paused`/"paused" before the grey stale fallback. Chain
  marker: `⤷ resumed from <first-8>` under a resumed attempt's label — a jump link (selects
  the source run, stopPropagation) when the source is in the list, plain text otherwise. No
  grouping/collapsing UI (v1 scope); chain currency analysis stays server-side.

Real-browser check (screenshot-pflow-web-ui, rebuilt bundle, REAL traces from a real
pause→`--approve yes` chain): run-menu shows the amber ⏸ paused mark + the "⤷ resumed from
d398bef5" marker; pinning the paused run renders the amber "Run paused · 1 nodes" banner and
the amber ■ callout badge with `gated` "pending" — screenshots in the Phase-4 progress-log
entry's session. One operational gotcha recorded there: the first `/api/runs` probe hit a
STALE pre-edit `pflow ui` process (the reuse-if-up probe reuses old-code servers) — kill the
old server before verifying server-side changes.

Gates: `make check` green; full `make test` **8658 passed, 0 failed** (+1, the new
`/api/runs` lineage test); vitest 727 passed (+4), `tsc --noEmit` clean.

## Phase 5 (docs) — shipped 2026-07-05

Two sessions. The first (committed in `fde74150`) did every doc the implementer could write
first-hand, having run the real pause/approve/choose flows:
- **Stale "MCP never streams" family, all sites**: `mcp_server/tools/execution_tools.py`
  (Field description, Built-in behaviors, a new Paused arm in Returns matched to the real
  `_format_paused_text`), `mcp_server/CLAUDE.md` (tool line + Agent-Optimized Defaults +
  ADR-0008 misattribution correction), `execution/CLAUDE.md` (RunnerConfig finalize +
  PAUSED/exit-4/render-shape note), `runtime/CLAUDE.md` (Task-172 bullets + a new 2.7.0
  trace-format bullet), `runtime/engine/CLAUDE.md` (except-arm now denied/paused/failed + the
  pause conjuncts), `runner.py:234` comment, `ui/run_tailer.py:110` docstring.
- **CLI CLAUDE.mds**: `cli/CLAUDE.md` exit-code paragraph (exit 4 + ResumeGroup);
  `cli/commands/CLAUDE.md` resume row (group routing, `--approve`/`--choose`, `resume list`,
  fixed the stale `workflow_trace.load_resume_source` → `resume_source` pointer).
- **ADR-0008**: "MCP runs stream too (Task 171)" note, aligning with its any-run-watchable intent.
- **Guide prose**: `features/resume.md` (retitled + new "Answering a paused gate" section),
  `features/approval.md` (durable-pause reality; the old "cannot hold a gate open" / "work is
  discarded" claims removed), `entry.md` resume topic line. Rendering verified via real
  `pflow guide resume|approval`.

The second session (the deferred `docs/` Mintlify pages — 164 set the precedent that resume is
user-documented there):
- **`docs/reference/cli/index.mdx`**: new "Answer a paused gate" section (exit 4, token,
  `--approve`/`--choose`/`resume list`, the nothing-re-runs/consumption/no-answer-refusal
  behavior, and the non-pausable list — `--no-trace`/batch/child/inline).
- **`docs/roadmap.mdx`**: durable resume moved from **Now** into **Current status** (shipped);
  **Now** repointed to the web-UI approval bridge (Task 176), the natural follow-on.

Deliberately **not** done: a `changelog.mdx` `<Update>` entry — the changelog is version-tied
and driven by the `/release` process; the feature is unreleased on this branch. The #542
retention comment was skipped (its substance is already on the issue).

---
*Distilled from the implementation context of Task 171 (Phases 0–5 + post-review hardening). The chronological journey —
decision provenance, mutation transcripts, delegation record — lives in
`implementation/progress-log.md`; the build contract in `implementation/implementation-plan.md`;
the planning tacit knowledge in `starting-context/braindump-2026-07-05-planning-session.md`.*
