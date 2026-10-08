# Task 180 — Implementation plan: resume refuses only when an edit touches a restored step

Planner: Fable, 2026-10-06/07, worktree `feat/task-180-resume-step-identity` @ `2a3f73ef` (== `origin/main`).
Spec: `task-180.md`. Governing issue #690 (stays open; closes with this task). Starting point: PR #719
(its never-started proof, `restored_node_ids`, the refusal text, the temporary `workflow`-type carve-out).
**Embedded user checkpoint:** `implementation/show-before-code.md` — rulings needed before P2/P3 (§5).
Self-reviewed: plan-mode deep-review, 8 lenses (dispositions in `progress-log.md`); every confirmed
finding is folded in below.

## 1. Verified ground (code is truth; cites checked on `2a3f73ef`)

- **One hash today.** `execution/runner.py:204` computes `workflow_content_hash(resolved.ir)` (whole
  resolved IR minus `_source_*` provenance — prose `purpose`, `inputs`, `edges`, everything else
  included; `core/workflow_id.py:49-69`), passes it to the collector ctor (`:217`); it lands on the meta
  line via `workflow_trace._meta_fields` (`:1042-1054`), `trace_io.META_KEYS` (`:35-47`), and the loader
  reads it into `ResumeSource.content_hash` (`resume_source.py:949`). `resume_preflight._check_content_hash`
  (`:161-192`) compares, BEFORE between-nodes entry resolution (`:87` vs `:91`). Other consumers of
  `content_hash`: the UI replay banner (`ui/run_tailer.py:502-544`, whole-workflow compare — untouched)
  and `entry_never_started`'s "post-173 trace" gate (`resume_source.py:393`, `content_hash is None` only).
- **Meta-line mechanics.** `trace_io.META_KEYS`, `workflow_trace._meta_fields` and
  `tests/shared/trace_jsonl.py:97-103` (iterates `META_KEYS` — no edit needed) move together. `inputs` is
  already a dict-valued meta key. Meta is flushed at `start_streaming` with `intern=False` (`:983-986`).
  `ui/server.py::_run_entry` (`:1360-1384`) picks NAMED meta keys, so a new key never reaches `/api/runs`;
  `run_tailer._read_meta` pops `inputs` only to keep `_SCAN_CACHE` small (memory, not the wire).
- **IR shape** (`core/ir_schema.py:239-335`): node keys `id, type, purpose, params, batch, loop, retry,
  cache, prompt_cache (list of chunk names), prewarm, approval, _routes_to_end, _source_*`. Routing is NOT
  on the node: `next:`/`on-error:` become `ir["edges"]` `{from, to, action}` — **the document-order edge
  has NO `action` key** (`markdown_parser.py:1336`) while `next:` writes `"default"` (`:1328`) and
  `on-error:` writes `"error"`; `_single_default_successor` (`resume_preflight.py:225-245`) normalises with
  `.get("action", "default")` and accepts `source`/`target`. Start step: `ir.get("start_node") or
  ir["nodes"][0]["id"]` — copied in `compilation/compiler.py:233-237` and
  `core/workflow/graph/build.py:923-928`; `core/workflow/context.py:36` uses a different rule on purpose
  (leave it). `## Cache` chunks: `ir["cache"]["items"]` `[{name, var, prose_before, _source_line}]`;
  prompt-cache rendering uses only the node's own subset (`core/prompt_cache.py:201`).
- **Resume inputs:** recorded `inputs` (defaults already applied at record time, `runner.py:349,365-368`)
  win; `KEY=VALUE` overrides (`cli/commands/resume.py:344`). EXECUTED: an edited `## Inputs` default never
  reaches a resumed tail. A removed declaration surfaces as the compile error "Unknown input" — loud.
- **Attempt traces re-record only the SEEDED set** (`engine.py:1104-1116` loops `entry.seeded`; the seed
  drops failed events, `resume_source.py:345`; ADR-0010 2026-07-04). A failed-recovered step has no event
  in an attempt trace. Any rule derived from "which steps have events" differs between the first run and
  its attempts.
- **`--approve yes` is consent by step NAME only** (`execution/gate_prompt.py:84-89`: `pending_answer[0]
  == request.node_id`); `_side_effect_refusal` returns `None` for every paused source (`:341`). Nothing
  compares the re-fired gate's preview with the approved `gate_request`.
- **Sub-workflow child content is not in the IR** (`file_resolver.py:32-45`; loaded at run time,
  `workflow_executor.py:206-221`): neither today's hash nor the per-step identity sees a child-file edit.
- **`--only` has no staleness check** (`workflow_trace.load_snapshot_or_raise:307-333`). Stays (D8).
- **`node.start` truth (EXECUTED, `scratchpad/wf/hosts.pflow.md`):** a NON-batched host writes
  `node.start single id=0` through `descend` (`workflow_trace.py:876-896`); a BATCHED host writes only
  `event batched id=3`. Task 179's review line 53 ("a sub-workflow host emits no node.start") is wrong for
  non-batched hosts; `test_resume_cli.py:1232`'s docstring repeats it (assertions hold: the fixture cuts
  between iterations).
- **Engine frames:** `begin_node` (`workflow_trace.py:932-954`) returns `None` unless run-scoped AND
  streaming; otherwise reserves a seq + emits, no push. `descend` reserves, PUSHES, emits when streaming.
  Engine skip at `engine.py:1362-1369` (comment "deferred L2" — stale). Completion sites use
  `frame=host_frame or start_frame` at `:1422-1434`, `:1495-1509`, `:1706-1719`; the gate arm
  (`:1671-1686`) records a host only `if host_frame is not None and not originating`, passes
  `batch_trace_items` undrained (only step 16 `:1494` and the except arm `:1704` drain
  `shared["_batch_trace"]`). A batched host's items run under buffered collectors
  (`workflow_executor.py:353-366`), `_host_frame` is reset per `exec` (`:383`) and never set on that path;
  gate exceptions are `batch_fatal` and re-raise out of `execute_batch` (`batch_executor.py:393`). Batch
  items are resolved INSIDE `execute_batch` (`:293` → `_resolve_and_validate_items:147`), i.e. after
  `begin_node` — a `batch.items` template failure is a STARTED host. `WorkflowExecutor` prep errors are
  returned, not raised (`:181-189, :388-399`) → step 16; a `CompilationError` in `exec` before `descend`
  (`:416`) → the except arm. `exec` catches `Exception` after `descend` (`:467`), so no second `descend`
  per visit. Direct `descend()` calls without `begin_node` exist in tests (`test_emit_time_trace.py:253,
  411, 606, 767`) — the fallback path must keep working.
- **Engine `config_hash`** (`instrumentation.py:141-193`, at `plan_node.py:61-72` every visit): class name
  + static params minus `*_source_line` + raw template params + batch subset + rendered prompt-cache
  content; excludes prose, edges, `loop`, `retry`, `approval`; changes between loop iteration 1 and 2;
  never written to the trace.
- **Preflight callers:** CLI `resume.py:335` and UI `server.py:1265` only; no MCP resume tool. The UI
  classifies refusals by exception class (`_RESUME_REFUSALS` `:1118-1129`), forwards message +
  suggestions in `errors[]`, adds `hash_known` (`:1153-1154`); `resumeAnswer.tsx:67-70` ignores `errors[]`
  (#721's lane). **UI validator gap** (`server.py:1233-1237`): the spawned child runs `_prepare_workflow`
  (`runner.py:268-300`: `_pflow_workflow_file` param, `_fill_declared_defaults`, `_validate`
  `:612-639` raising `WorkflowValidationError` with ALL errors) BEFORE the trace exists; the UI pre-flight
  only compiles, so a validator-only ERROR dies silently (DEVNULL) — today reachable only under `--force`,
  after this task without it → **a gap this change widens; closed in P3 (D11)**. `plan()` already does
  prepare + `_strip_placeholders` + compile (`runner.py:530-537`); `src/pflow/ui/CLAUDE.md:52-53` states
  the residual.
- **Tests that flip** (fixtures parsed: the usual edit — append `<!-- edited -->` — lands on the LAST
  node's `purpose`, never a restored step): `test_resume_cli.py` `:315`, `:591`, `:872`, `:1217`;
  `test_paused_cli.py:256`; UI `test_stale_workflow_is_409_and_does_not_spawn`
  (`test_ui_interaction_server.py:1369`). `test_resume_cli.py:611` imports `_check_content_hash` by name
  (retarget on rename). `test_resume_preflight.py:87` stays on the fallback path (no identity map).
- **Task-159 baseline on this base: 75 pass / 12 drift** — the same 12 cases Task 183 lists
  (`02-validator-errors/03,05; 03-analyze-cache-modes/05-09; 04-warning-catalog/03,09d,09e;
  10-live-recordings/03; 12-real-world-lyrics-generator/04`). Any 13th drift is ours.
- **Cross-task scan (`./scripts/tasks`):** Task 183 (planned) bumps the trace format additively —
  version collision, §4. Task 118 Part 1 is building (template resolver, `engine/types.py`, shell node) —
  disjoint files, both touch `runtime/engine/` → **builds serialize**. Task 181 — no overlap. Task 121's
  draft record/replay could extend the identity map additively later. #721 / #458 — separate lanes (§7).
  Task 179's review is the restore contract (one seed derivation; loop position per iteration) — D3 reuses
  its derivation unchanged.

## 2. Solution (what ships)

1. **Every step that begins writes a top-level `node.start`** — including a batched sub-workflow host
   (ruling). The engine calls `begin_node` for every node; a host's `descend` takes over the frame the
   engine already began. #719's unconditional carve-out goes; a conjunct remains ONLY for traces that
   predate this guarantee (D1b).
2. **The trace meta line gains `step_identity`** — per restored-able step a definition hash and its
   recorded next steps, plus the start step — computed from the resolved IR beside `content_hash`
   (trace format **2.9.0**, additive; §4).
3. **Preflight compares only the restored steps** (plus the paused approval step) against the current
   IR, checks the resume point still exists and the start step is unchanged; refuses naming exactly what
   changed. Old traces keep today's whole-workflow compare.
4. **The refusal text names the change** (edited / removed / now continues to / now starts at / resume
   point gone / edited after approval) and carries structured fields in JSON; `--force` stays ONE flag
   (pending the ruling) with #719's re-fire sentence kept.
5. One runner pre-meta primitive (prepare + validate + strip + compile) shared by `plan()`, the UI resume
   pre-flight and `/api/run`'s pre-flight — an edited workflow with a validator-only error returns 400.
6. Docs/guide/CLAUDE.md/ADR notes updated; CONTEXT.md and ADR-0010 amendments proposed.

## 3. Decisions (all resolved; the user checkpoint may revise D3/D7/D9 texts)

- **D1 — Engine: `begin_node` for every node; `descend` takes over the pending frame.**
  `WorkflowTraceCollector.begin_node` on a RUN-SCOPED collector always reserves the seq (owner-thread
  asserted by `_next_seq`), stores the frame in `self._pending_start`, emits the `node.start` line only
  when streaming, and returns the frame (non-run-scoped buffers: `None`, unchanged). `descend(node_id)`:
  if `self._pending_start` is set with `node_id == node_id` and `parent_id == (self._host_stack[-1].seq if
  self._host_stack else None)` → push THAT frame, clear pending, emit nothing, return it; else today's
  reserve + push + emit-when-streaming (only reached by direct test calls now — keep it working). Engine
  `:1368`: drop the `!= "WorkflowExecutor"` conjunct. Gate arm: `frame = host_frame or start_frame`;
  **the guard becomes `frame is not None and not originating`** (a batched host's `_host_frame` is always
  `None`); **drain the batch trace there** (`_collect_batch_trace(shared, config.node_id) if
  config.batch_config else None`) so a batched host recorded on the gate arm keeps its completed items'
  trace and cost; keep `success=True` (the existing documented choice for a host closed by a child gate).
  Reserving in memory too means a `--no-trace` run's except-arm completion reuses the descended frame — the
  latent orphan closes everywhere, not only when streaming. Seqs stay byte-identical (nothing reserves
  between `begin_node` and `descend`/completion). Rejected: (b) keep the skip for non-batched hosts only —
  keys the engine on another module's internals, two reservation paths, orphan stays; (c) `descend`
  skipping only the emit — still reserves a second seq.
- **D1b — The never-started proof is only valid for a batched host on a trace that carries the new
  guarantee.** `entry_never_started` gates "post-173" on `content_hash`; traces 2.3–2.8 have it but never
  wrote a batched host's start, so deleting #719's carve-out unconditionally would skip the side-effect
  confirmation for exactly the case it protects (re-fire of items that already ran). Rule: in
  `_side_effect_refusal`, the `workflow`-type conjunct applies only when `source.step_identity is None`
  (absence = pre-180 trace, D6's own discriminator — robust to the Task 183 numbering race). So the
  carve-out moves from P1 to P3 and narrows instead of vanishing; `_WORKFLOW_EXECUTOR_TYPES` stays.
- **D2 — Mint `step_identity(ir)`; do not reuse the engine's `config_hash`.** The memo hash answers
  "would this exact execution produce the same output" (rendered prompt-cache content varies per loop
  iteration — a restored iteration N−1 never matches one current value), omits `loop`, `retry`,
  `approval` and edges, keys on the runtime class name, and reusing it would tie resume correctness to
  cache-key evolution. Resume needs a STATIC identity from the IR. Home: `core/workflow_id.py` beside
  `workflow_content_hash` (same `canonical_ir_digest` + `_strip_source_provenance`; md5 hex).
  Shape (one meta key):
  ```
  step_identity = {
    "start": start_node_id(ir),
    "steps": {node_id: {"hash": <md5 of {"node": node minus "purpose"/provenance,
                                          "cache": {name: chunk minus provenance for name in node.prompt_cache
                                                    if present in ir.cache.items}}>,
                         "next": sorted((edge.get("action", "default"), to) for outgoing edges)}}
  }
  ```
  Edges are read the way `_single_default_successor` reads them (`from`/`source`, `to`/`target`,
  `action` default `"default"`) so document order and an explicit `next:` to the same target are the
  same identity, and an `on-error:` beside an implicit next never raises. Excluded on purpose:
  `purpose`, `## Inputs` (recorded values win), `cache.ttl`, `template_resolution_mode`,
  `enable_namespacing`, `ir_version`. Kept fail-closed: `_routes_to_end` (semantic) and the policy-only
  keys `retry`/`cache`/`prewarm`/`batch.parallel` (one rule, "definition minus prose"; a future node key
  such as Task 118's `env:` counts by default; a denylist is a later refinement on observed over-refusal).
  **Recipe stability (format contract):** the 2.9.0 history comment and `runtime/CLAUDE.md` state that
  any change to what `step_identity` hashes bumps the trace minor, and the preflight must then treat maps
  from older minors as absent (whole-hash fallback) — the follow-up that adds child-file content (§7)
  inherits this rule.
- **D3 — The checked set is the RESTORED set (`restored_node_ids(source)`, #719's — kept) plus the paused
  approval step.** Restored = `_seedable_final_events` minus `resumes_at` (`entry_node_id`, or
  `last_completed_node_id` when it loops), i.e. exactly what the engine seeds — the same derivation Task
  179 pinned, so it agrees between a first run and its attempts (attempt traces re-record only seeded
  steps). Rejected: "every step that ran before the resume point" — it differs between run 1 and attempt
  2 for a failed-recovered step (no event in the attempt) and would make D4-by-events false-refuse an
  unedited resume-of-a-resume. Accepted limits (guide sentence): a failed-recovered step is never
  re-run, so an edit to it — or a step inserted right after it — passes silently (a reference to the
  inserted step fails loudly as unresolved); a between-nodes successor reached by a back edge into a loop
  step is restored and therefore checked. **Paused approval:** when `source.paused_node_id ==
  source.entry_node_id`, that step is checked too — `--approve yes` is consent for the preview the human
  saw; an edited approval step refuses with its own lead (row 14). Escalation pauses need nothing extra:
  their paused step is `last_completed`, already restored.
- **D4 — Start step and resume point.** `start_node_id(ir)` moves to `core/ir_schema.py` (public; the
  compiler's `_get_start_node` and `graph/build.py::_start_node_annotation` call it — rename the
  compiler's clashing local). Refuse when `start_node_id(current) != recorded["start"]` ("now starts at
  X" + ", which never ran" when X ∉ restored ∪ {resumes_at}). Refuse FIRST when `resumes_at` (or, for a
  between-nodes source, `last_completed_node_id`) is not in the current IR ("the resume point 'save' is no
  longer in the workflow") so a renamed resume point is never blamed on its predecessor's `next`.
- **D5 — Meta map, not per-event hashes.** Computed once at `runner.py:204` beside `content_hash`, passed
  through the collector ctor the same way; the loader reads it beside `content_hash`. Per-event stamping
  would need every `record_trace` to carry a hash and restored re-records to copy a third key (Task 179's
  "copy `iteration` AND `lossy`" gotcha). Precision cost accepted: after a `--force`d resume the attempt's
  map describes the IR the attempt ran with — identical to today's `content_hash` precision. Top-level
  steps only (seeds are top-level only).
- **D6 — Old traces keep today's behaviour by ABSENCE of the key, not by version.** `step_identity is
  None` (or not a dict — loader type guard) → whole-`content_hash` compare with `hash_known` as today.
- **D7 — `--force` stays one flag** (checkpoint recommendation (a)); the guide records that any later
  split must be additive (`--force` stays the superset waiver).
- **D8 — `--only` gains nothing** (ADR-0002 built it without a staleness gate; #458's closing shape is
  input coherence). `step_identity` is on the meta line if that lane ever wants it.
- **D9 — Same exception class, same UI literal, `hash_known` kept** (`ui/server.py`, `resumeAnswer.tsx`
  untouched; #721 closes the panel's paraphrase). New ctor:
  `ResumeStaleWorkflowError(*, hash_known, edited: list[str], removed: list[str],
  rerouted: dict[str, list[str]], new_start: str | None, resume_point_missing: bool,
  approved_edited: str | None, entry_node_id, entry_iteration=None, after_node_id=None,
  rerun_node_type=None, execution_id=None, trace_path=None)`; `restored` goes away. `rerouted[step]` =
  that step's current next targets when its recorded `next` differs; the sentence says "which never ran"
  for targets ∉ restored ∪ {resumes_at}, else "instead of <recorded>". Texts: `show-before-code.md`
  (leads in fixed order removed → resume point missing → edited → approved_edited → rerouted → new_start;
  then "Resume re-runs nothing before 'save' …" / "… nothing up to and including 'esc'" for between-nodes;
  suggestions: re-run first, then the generic `--force` consequence line + #719's re-fire sentence; the
  fallback lead "this run was recorded by an older pflow version that did not record each step's
  definition, so resume cannot tell which step changed", pre-173 keeps "Cannot verify…"). `to_diagnostics`
  override adds `context` fields `changed_steps` (edited + removed + rerouted keys), `new_start`,
  `resume_point`; `node_id` set when exactly one step changed.
- **D10 — `content_hash` keeps being written** (UI replay banner; `entry_never_started`'s post-173 gate;
  old-trace fallback).
- **D11 — One runner pre-meta primitive, never a copy.** Add `WorkflowRunner.preflight(resolved, params)`
  = `_prepare_workflow` + `_strip_placeholders` + `compile_workflow` (what `plan()` already does inline);
  `plan()`, the UI `_resume_preflight` (replacing its hand-rolled `compile_workflow` call, params =
  `dict(pf.source.inputs or {})`) and `/api/run`'s `_preflight` (one line) call it. `WorkflowValidationError`
  propagates whole into the existing 400 arm (no first-error re-wrap). Order unchanged: `preflight_resume`
  → side-effect raise → `preflight`. Verified by the validation lens: a hand copy of `_validate` alone
  gives false 400s (relative `workflow: ./child.pflow.md` without `workflow_file`; an added optional input
  without default-filling). The residual sentences in both server docstrings and `ui/CLAUDE.md:52-53` go.
- **D12 — Sibling gaps from #719:** (i) hash includes prose → closed by D2 for resume (the UI banner's
  whole-hash still sees prose — correct for a "different version" banner); (ii) the fidelity refusal's
  remedy → out of scope (Task 179's ruled strictness); (iii) `task-164.md:95` / `task-171.md:182` "warn +
  --force" → archived specs of other tasks, left alone; the living surfaces are updated in P4.
- **D13 — No new output line for an edited loop resume point** (agent-ux S1): threading an "entry
  edited" flag to the success formatter adds a result field for one sentence; the guide states "an edit
  to the loop step applies from the resumed iteration on". Revisit on an observed complaint.

## 4. Trace format and engine obligations

- **Version:** `TRACE_FORMAT_VERSION` `"2.8.0"` → `"2.9.0"` (`workflow_trace.py:44`; history comment
  `:33-43` gains: "2.9.0 (Task 180, additive): meta `step_identity` (per-step definition hash + next steps
  + start step, for resume); `node.start` now also written for batched sub-workflow hosts and reserved in
  memory for every node; a change to what `step_identity` hashes bumps the minor and older maps are
  treated as absent"). Re-pin `test_trace_format_2_2.py:26-27` (`test_format_version_is_2_8_0` → `_2_9_0`).
  `_predates_lossy_marker` compares `(2, 8)` — unaffected (and parses `2.10`). **Collision with Task 183**
  (its plan D6 also takes 2.9.0): plans in parallel, builds serialize; **whichever merges second takes the
  next number** (2.10.0) and re-pins its test + comment. The task orchestrator checks `origin/main`'s
  constant at the merge-main step before `create-pr`. Nothing in this task keys on the number (D6).
- **Engine contact:** P1 edits `runtime/engine/engine.py` and `runtime/workflow_trace.py` → serialized with
  Task 118 Part 1's build (same directory). Mid-task review after P1 (§5).
- **Task-159 baseline:** run `.taskmaster/tasks/task_159/baseline/verify.sh` after P2 and at completion;
  expected 75/12 with exactly the §1 list (it diffs CLI stdout/stderr/exit, never trace files).
- **Platform:** no subprocess/encoding/path semantics change; `tests-windows` must simply stay green.
- **No UI shape change** (D9); `web/` untouched. No `pflow ui` server needed.

## 5. Phases

Agent economics: ONE Opus `task-phase-implementer` runs P1, then (after the mid-task review and the
checkpoint ruling) P2+P3 bundled, then P4 (synthesis belongs to who holds the content). Effort `high` for
P1 and P3 (seam logic), `medium` for P2 and P4. **P1 is independent of the checkpoint and may start before
the ruling; P2/P3 wait for it.** **P0 (task orchestrator, after the ruling, before P2):** write the spec's
Solution / Requirements / Verification from §2–§3 and the ruled table, replace the spec's "Open questions"
with the resolved answers (one line each, pointing here), so the completion gate's spec-conformance lens
has current truth to read.

### P1 — `node.start` for every step (engine + collector) — ENGINE CONTACT, triggers mid-task review
- Goal: a batched `type: workflow` host writes a paired top-level `node.start`; every other on-disk shape
  is byte-identical; in-memory runs pair the host frame too.
- Files: `src/pflow/runtime/workflow_trace.py` (`__init__` `_pending_start`, `begin_node`, `descend`,
  docstrings incl. `_emit_node_start`'s), `src/pflow/runtime/engine/engine.py` (`:1362-1369` comment +
  condition; gate arm `:1645-1686` comment, guard, `frame=`, batch drain), `src/pflow/runtime/engine/CLAUDE.md`
  (Gate control flow: the host pairs its start on the gate arm, batched hosts included),
  `src/pflow/runtime/CLAUDE.md` (node.start bullet), `context/adr/0008-live-execution-overlay.md:20-26`
  (the "deferred batch-of-sub-workflow host" note → built by Task 180, one sentence),
  `tests/test_runtime/test_emit_time_trace.py`, `tests/test_runtime/test_resume_source.py`,
  `tests/test_cli/test_resume_cli.py`. **Not in P1:** the preflight carve-out (moves to P3, D1b).
- Decisions: D1. Put the pending write after `_next_seq()` (owner-thread assert first).
- Tests must catch (real runs via `WorkflowRunner`/CLI; raw JSONL for `node.start` — Task 173 invariant 1):
  1. Batched host: exactly one top-level `node.start`, `id` == the host's final `event` `id`; items carry no
     correlation keys (`old_path_*` pins stay green).
  2. Non-batched host: still exactly ONE start per visit (a double-begin shows two); event seqs gap-free
     (`test_emit_time_trace.py:1368-1371` + a direct "one start per host visit" assertion).
  3. Looping non-batched host: one start per iteration, each paired (`:242` pin).
  4. Nested host inside a host: inner start's `parent_id` == outer seq; `tree() == reconstruct`;
     `nodes_executed` unchanged. Plus the triple: batched host INSIDE a non-batched host whose item's
     grandchild raises a denied non-TTY gate — both starts paired, no "orphan event".
  5. Batched host whose item's CHILD raises a denied non-TTY approval gate: the host's start is paired via
     the gate arm; the recorded host event carries the completed items' batch trace (presence: item
     entries; absence pair: a non-gated run's shape); the existing nested orphan pins stay green.
  6. Host failing in prep (missing child file) — paired at step 16; host raising `CompilationError` before
     `descend` — paired via the except arm (the "latent orphan closed" claim).
  7. In-memory run (`--no-trace`, run-scoped collector, no streaming): zero `node.start` lines, and a host
     whose `post` raises after `descend` yields a readable `tree()` (the orphan is closed in memory too);
     a buffer collector's `begin_node` still returns `None`.
  8. Collector unit: `begin_node("a")` then `descend("host")` → fresh reserve + own emit (mismatch
     fallback); mismatched `parent_id` → same; direct `descend` without `begin_node` → today's shape.
  9. Resume readers (impact W1): a run killed mid-batched-host now resolves entry = the host (dangling
     start) and asks for confirmation; a killed resume ATTEMPT of that shape supersedes its source
     (`_attempt_consumed_work`).
  10. Mutation (Edit + revert, logged): re-adding the engine skip → test 1 fails; removing the pending
      consumption → test 2 fails (two starts); reverting the gate-arm guard → test 5 fails.
- Handoff: `make check` + `make test` green; raw-trace shapes for 1–3 and 5 in the progress log.
- **Triggers mid-task review:** `review-silent-failures` (unpaired start / double seq — every reader
  silently skips an orphaned trace) and `review-feature-interactions` (batch × nested × loop × gate ×
  `--only` × in-memory), on P1's diff. Dispositions logged before P2 starts.

### P2 — `step_identity` on the meta line (trace format 2.9.0) — TRACE FORMAT
- Goal: every trace records per-step identity; old traces load with `step_identity=None`.
- Files: `src/pflow/core/ir_schema.py` (`start_node_id(ir)`), `src/pflow/runtime/compilation/compiler.py`
  (`_get_start_node` calls it; rename the local), `src/pflow/core/workflow/graph/build.py:923-928` (calls
  it), `src/pflow/runtime/compilation/CLAUDE.md:12` (row), `src/pflow/core/workflow_id.py`
  (`step_identity(ir) -> dict[str, Any]`), `src/pflow/execution/runner.py:199-224` (compute + pass),
  `src/pflow/runtime/workflow_trace.py` (ctor kwarg, attribute, `_meta_fields`, version + comment),
  `src/pflow/core/trace_io.py` (`META_KEYS`), `src/pflow/runtime/resume_source.py`
  (`ResumeSource.step_identity: dict[str, Any] | None = None`; loader reads with an `isinstance(dict)`
  guard), `src/pflow/ui/run_tailer.py::_read_meta` (pop it beside `inputs` — memory), tests:
  `tests/test_core/test_workflow_id.py`, `tests/test_runtime/test_trace_format_2_2.py`,
  `tests/test_runtime/test_resume_source.py`, `tests/test_core/test_ir_schema*.py` or the compiler tests.
- Decisions: D2, D4 (helper), D5, D6, D10; §4 version.
- Tests must catch:
  1. `step_identity`: stable under key order and source-line shifts; a `purpose` edit does NOT change a
     step's hash (presence pair: a `params` edit DOES); document-order next vs explicit `next:` to the same
     target → identical `next`; a step with `on-error:` and an implicit next → no raise, `next` holds both;
     a `next:` reroute changes the FROM step's `next` only (hash untouched); `loop:`/`batch:`/`retry:`/
     `approval:` edits change the hash; an edit to a referenced `## Cache` chunk's `prose_before` changes
     the referencing step only; an unreferenced chunk edit changes nothing; an inserted step changes its
     predecessor's `next` and nothing else; `start` follows `start_node` then `nodes[0]`.
  2. Meta carries `step_identity` for every top-level node and only those; `inputs`/`content_hash`
     unchanged; meta not interned.
  3. Fixture round-trip through `trace_jsonl.py`; `TraceFixtureBuilder` unaffected.
  4. A 2.8.0 trace without the key loads as `None`; a malformed value (string) loads as `None`;
     `_predates_lossy_marker` still `False` for 2.9.0.
  5. `start_node_id`: compiler and graph build agree (the former copy's tests stay green).
  6. Task-159 baseline: 75/12, the §1 list.
- Handoff: `make check` + `make test` green; baseline summary in the log. No mid-task review of its own.

### P3 — Preflight narrows; refusal names the change; carve-out narrows; runner pre-meta primitive — RESUME SEMANTICS, triggers mid-task review
- Goal: rows 1–16 of `show-before-code.md` hold through the real CLI, `--dry-run`, and the UI endpoint.
- Files: `src/pflow/execution/resume_preflight.py` (`_check_content_hash` → `_check_workflow_identity`;
  `_side_effect_refusal` D1b conjunct; docstrings `:21-24, :84-86, :336-339` — keep the "only reachable
  under --force" comments at `:255-261`, `:288`, `engine.py:109-110`, `cli/commands/resume.py:332-339`:
  they stay TRUE (the between-nodes arms are properties of `last_completed`, which is restored and checked;
  a removed K is caught by D4) — rename "hash gate" → "identity gate" only), `src/pflow/core/exceptions.py`
  (`ResumeStaleWorkflowError`, D9), `src/pflow/execution/runner.py` (`preflight` primitive; `plan()` uses
  it), `src/pflow/ui/server.py` (`_resume_preflight` and `/api/run` `_preflight` call it; docstrings
  `:1003-1019`, `:1233-1237`), `src/pflow/ui/CLAUDE.md:52-53`, tests: `tests/test_cli/test_resume_cli.py`
  (incl. retargeting `:611`'s import), `tests/test_cli/test_paused_cli.py`,
  `tests/test_execution/test_resume_preflight.py`, `tests/test_runtime/test_resume_source.py`,
  `tests/test_cli/test_ui_interaction_server.py`, `tests/test_execution/test_plan_drift.py` (the primitive).
- Decisions: D1b, D3, D4, D6, D7, D9, D11. Algorithm:
  ```
  if force: return
  resumes_at = entry or (last_completed if it loops)                   # #719's rule, unchanged
  if source.step_identity is None:                                      # pre-180 trace (D6)
      whole-content_hash compare → ResumeStaleWorkflowError(fallback lead, hash_known=content_hash is not None, …)
      return
  current = step_identity(resolved.ir); rec = source.step_identity
  anchor = resumes_at or source.last_completed_node_id                  # between-nodes: the step resume continues after
  if anchor is not None and anchor not in current["steps"]: raise (resume_point_missing)
  checked = restored_node_ids(source)
  if source.paused_node_id is not None and source.paused_node_id == source.entry_node_id:
      checked.append(source.paused_node_id)                             # paused approval (D3)
  removed  = [n for n in checked if n not in current["steps"]]
  edited   = [n for n in checked if n in current["steps"] and (n not in rec["steps"] or current["steps"][n]["hash"] != rec["steps"][n]["hash"])]
  rerouted = {n: targets(current, n) for n in checked if n in current["steps"] and n in rec["steps"] and current["steps"][n]["next"] != rec["steps"][n]["next"]}
  new_start = current["start"] if current["start"] != rec["start"] else None
  if removed or edited or rerouted or new_start: raise ResumeStaleWorkflowError(…, approved_edited=paused step if in edited, rerun_node_type via _side_effect_refusal(force=False) as today)
  ```
  Fail-closed: a checked step missing from the recorded map counts as edited (never `None == None`).
- Tests must catch (each through `pflow resume` on a REAL failed run; `--dry-run` twin for rows 1 and 3):
  1. Row 1 passes WITHOUT `--force` and completes (`out.txt == "# hi"`) — rewrite
     `test_fix_then_resume_of_a_step_that_never_started` as this.
  2. Row 2 passes; row 3 refuses naming exactly `'produce'` (not `'shape'`).
  3. Rows 4, 5, 6 refuse with the exact leads; row 4 with `--force` still skips the step (regression
     guard, labelled as such).
  4. Rows 7, 8 pass; the new downstream step runs (presence: its marker file).
  5. Row 9 passes; the tail uses the recorded input (pin of unchanged semantics).
  6. Row 10: restored `llm` step with `prompt_cache` — chunk edit refuses naming it (`tests/shared/llm_mock`).
  7. Row 11: loop entry edited, resumed at iteration N → passes; extend `_kill_looping_host_after_iteration_2`'s
     fixture with a predecessor step so an UPSTREAM edit still refuses.
  8. Row 12 refuses with "resume point … no longer in the workflow" (not naming `'shape'`); row 13 names
     `'shape'` as removed.
  9. Row 14: paused approval, approved, then the approval step edited, `--approve yes` → refuses with the
     approval lead; the same with an UPSTREAM edit → refuses naming it; an edit DOWNSTREAM of the gate →
     passes and the gate re-fires (rewrite `test_stale_hash_refuses_paused_resume_and_force_proceeds`).
     Escalation pause: edit to the paused (last_completed) step refuses; edit to the successor passes.
  10. Between-nodes source: a step inserted after `last_completed` refuses ("now continues to"); an edit to
      the resolved successor passes; text says "nothing up to and including 'esc'".
  11. Resume-of-a-resume with a failed-recovered START step and no edit → passes (the D4-by-events trap);
      resume-of-a-resume after an unforced resume → passes; after a `--force`d one → documented precision.
  12. Fallback: `content_hash` present, no `step_identity` → refuses with the older-version lead on ANY edit
      (prose included); `content_hash=None` keeps "Cannot verify"; `step_identity` a string → fallback.
  13. D1b: a hand-built 2.8.0 trace (no `step_identity`) with a failed batched `workflow` host, no start →
      confirmation still required; a real 2.9.0 batched host that started → confirmation required through
      the real proof (rewrite `test_batched_sub_workflow_host_still_needs_confirmation`'s comment); the
      leaf never-started case (#719's typo test) still skips.
  14. `rerun_node_type`: when K started the refusal carries the re-fire sentence; when K never started, not.
  15. UI: `test_stale_workflow_is_409_and_does_not_spawn` with an UPSTREAM edit (409, `hash_known: true`,
      `errors[]` names the step, `context.changed_steps`); a downstream edit → 200 spawned; an edited
      workflow with a validator-only ERROR → 400 carrying ALL diagnostics, no spawn; a workflow with a
      relative `./child.pflow.md` sub-workflow and one with a newly added optional input → 200 (the
      false-400 pair); `/api/run` with a validator-only error → 400 (one-line extension).
  16. `plan()` ↔ `preflight` parity in `test_plan_drift.py` (both call the primitive).
  17. Exception unit tests per lead (edited / removed / rerouted "which never ran" vs "instead of" /
      new_start / resume_point_missing / approved_edited / between-nodes / loop "(iteration N)" / both
      fallback texts) and the JSON `context` fields.
  18. Mutation (logged): dropping the paused-approval append → test 9 fails; dropping the resume-point
      check → test 8 fails; dropping `n not in rec["steps"]` → a hand-built map-missing-step test fails;
      dropping the D1b conjunct → test 13's old-trace case fails.
- Handoff: `make check` + `make test` green; the 16-row table re-executed on the branch pasted into the
  log (AFTER → observed).
- **Triggers mid-task review:** `review-silent-failures` (the fail-closed arms; D1b) and `review-agent-ux`
  (the refusal text is the agent's only steering) on P2+P3's diff. (`review-falsifier` runs at the
  completion gate, directly, last — its promises are the 16 rows.)

### P4 — Living documentation and instruction files
- Files: `src/pflow/guide/features/resume.md` (`:56`, `:76` "a sub-workflow step always asks" → drop,
  `:78`, `:82` → the rule in authoring terms: "Edits at or after the resume point, and description prose
  anywhere, resume without `--force`. Editing a step whose saved output resume restores (its parameters or
  code blocks, a `## Cache` chunk it uses), removing it, changing where it goes next, inserting a step on
  the path before the resume point, or editing a step after approving it refuses. Re-run from the start,
  or pass `--force` to keep the saved outputs (an inserted step is skipped). Editing an `## Inputs`
  default does not affect a resume — pass `KEY=VALUE`. A loop step edited at its resumed iteration applies
  the edit from that iteration on. A step that failed and recovered is never re-run, so edits to it pass
  silently. Any later narrowing of `--force` is additive."), `docs/reference/cli/index.mdx:86,90,117`,
  `src/pflow/execution/CLAUDE.md:66-78` (carve-out sentence → D1b's one line; the identity rule),
  `src/pflow/runtime/CLAUDE.md` (2.9.0 bullet; `step_identity`; `:154` "restored-node lists from its
  returned map minus the entry" stays true — `restored_node_ids` is kept), `src/pflow/runtime/engine/CLAUDE.md`
  (if P1 did not), `src/pflow/ui/CLAUDE.md:52-53` (if P3 did not), `tests/test_cli/test_resume_cli.py:1232`
  docstring, `.claude/agents/pflow-codebase-searcher.md` (only if it names the host-start claim or the
  stale gate — grep; then `make sync-claude-assets`). **Proposals for the main orchestrator (not edited
  here):** `context/CONTEXT.md` **Resume** entry — append: "A Resume refuses when a Restored step was
  edited (its definition minus prose), removed, or now leads elsewhere, when the workflow now starts at a
  different step, or when an approved step was edited after approval; edits at or after the re-entry
  point never need `--force`." ADR-0010 amendment (meets ADR-FORMAT's three bars — record the rejections):
  per-step identity on the meta line (`step_identity`); rejected reusing the memo `config_hash`
  (per-iteration variance; omits loop/edges/approval) and per-event stamping (a third re-record key);
  `--force` remains the single superset waiver. Task 179's review line 53 is wrong for non-batched hosts
  and moot after P1 — flag, do not edit another task's review.
- Tests: `tests/test_docs` link/reference checks; `uv run pflow guide resume` renders.
- Handoff: `make check` + `make test-all-local` green; `create-task-review` preconditions met.

## 6. Completion gate (task orchestrator commissions; lenses by trigger)
Sensitive path (resume + engine + trace) ⇒ full floor: `review-silent-failures`, `review-impact-completeness`
(every meta reader; every `node.start` reader), `review-feature-interactions`, `review-test-fidelity`,
`review-validation-consistency` (D11 — one primitive, three callers), `review-agent-ux` (refusal text,
guide, docs), `review-simplicity` (multi-phase), `review-spec-conformance` (against the P0-updated spec),
and `review-falsifier` direct and last (promises: the 16 rows; the three #719 falsifier rounds must stay
HELD — re-run its attack list: restored chain, back edge, typo pipe/TTY, loop carry, batched `workflow`
host on a 2.9.0 trace AND on a hand-aged 2.8.0 trace, 2.7.0 and pre-173 traces, `--only` id). Then
`make test-all-local`, the Task-159 baseline, `create-task-review`, `create-pr` ("Closes #690").

## 7. Out of scope / follow-ups to file (main orchestrator)
- Child-workflow file edits are invisible to both hashes (§1) — issue: "resume/replay identity does not cover
  a `type: workflow` step's child file" (inherits D2's recipe-stability rule).
- An INFO advisory listing the reused input values on resume (checkpoint row 9 option (c)) — same family
  as #458.
- #721 interaction: the server already forwards the new message, suggestions and `context` fields in
  `errors[]`; the panel's hard-coded "the resumed steps may differ" text is now less accurate — #721's fix
  (render the body) is the closing move; no change here.
- `task-164.md` / `task-171.md` "warn + --force" wording: archived specs, left alone (D12).
