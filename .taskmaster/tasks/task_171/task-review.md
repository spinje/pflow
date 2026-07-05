# Task 171 Review: Durable Resume Tokens & Non-TTY Gates

> **DRAFT — covers Phases 0–3 + the inline-pause decision (2026-07-05).** Phases 4 (UI) and 5
> (docs) are NOT done; the agent finishing them extends the marked section at the end and then
> flips the task spec to done. Written by the Phase-2/3 implementer while the context was live.

## Metadata

- Implemented 2026-07-04 → 2026-07-05, branch `feat/durable-resume-tokens` (not merged).
- Commits: `a8066f15` (Phase 0, loader extraction), `cf60b197` (Phase 1, producer),
  `8125454a` (Phase 2, loader answer arm). Phase 3 (CLI) + the inline producer refusal were
  implemented and gated.
- Follow-up filed: **#562** (make inline workflows resumable — workflow content in the trace).
- Gates at draft time: `make check` green, `make test` 8657 passed, `make test-e2e` 44 passed.

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
  loop/`code`/terminal escalations, `--no-trace`, and inline (`ir-hash:`/`None` workflow_path)
  runs all stay `failed`. Breaking the mirror strands humans with dead tokens.
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

## Patterns & Anti-Patterns

**Patterns to propagate:**
- **Answer delivery = resolver priming, never new machinery.** `--approve yes` appends the
  paused node to the resolver's `auto_approve` set; `--approve no` to the new `deny` set. The
  gate RE-FIRES in the resume run and records an honest resolution line — trace stays truthful,
  zero new delivery paths. `--choose` needs no resolver at all: the loader folds the decision
  into the restored event and the engine's existing re-record loop persists it.
- **One rule, one home, N consumers**: `option_labels`, `format_resume_answer_command`,
  `format_gate_lines`, `_fold_decision_into_event`, `_find_consuming_attempt`. When two
  surfaces must agree on a rule, extract the rule — don't mirror it.
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

- **The engine gate arm is the highest-precision edit surface in the feature.** Conjunct order:
  `isinstance GateNotInteractiveError → not parallel_batch → originating → not nested →
  workflow_path real → _gate_pausable`. The isinstance guard short-circuits attribute access
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
- **The trace format is unchanged since 2.7.0** (Phase 1); Phases 2–3 added zero producer
  changes beyond the inline conjunct.
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
- Keystones (real producer traces, not synthetic):
  `test_resume_engine.py::test_non_interactive_gate_pause_loads_with_answer_and_resumes_e2e`
  (approval, full WorkflowRunner), `test_gate_pause.py::test_paused_escalation_real_trace_
  choose_answer_roundtrip` (escalation, engine-level re-record), and
  `test_paused_cli.py::test_escalation_pause_choose_answers_and_completes` (real CLI).
- Parity nets: `test_plan_drift.py::test_engine_and_planner_paused_{approval,escalation}_entry_state_match`.

## Pending — to be filled by the Phase 4/5 finisher

- **Phase 4 (UI)**: the `RunProgress.runBadgeStatus` green-✓-for-paused regression EXISTS IN
  TREE since Phase 1 and must merge with this work (plan Phase 4 has the full file list:
  `run_tailer`→`/api/runs` `resumed_from`, `RunProgress`, `RunSelector`, CSS, defensive
  formatter arms). Record here: what shipped, the real-browser check result.
- **Phase 5 (docs)**: the registration-sweep inventory of every `pflow resume` usage line
  (guide/docs/CLAUDE.md) is in the progress log's Phase-3 entry. Record here: CLAUDE.md/ADR
  deltas, the #542 retention comment, guide prose.
- On completion: set the task spec `## Status` to done + `## Completed` date, tick CLAUDE.md's
  roadmap if listed, and remove this section + the DRAFT banner.

---
*Distilled from the implementation context of Task 171 (Phases 0–3). The chronological journey —
decision provenance, mutation transcripts, delegation record — lives in
`implementation/progress-log.md`; the build contract in `implementation/implementation-plan.md`;
the planning tacit knowledge in `starting-context/braindump-2026-07-05-planning-session.md`.*
