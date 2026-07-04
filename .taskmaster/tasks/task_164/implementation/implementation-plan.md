# Task 164 — Implementation Plan: Resume Workflow From a Failed Node

_Basis: task-164.md (Decisions 1–9, locked 2026-07-03), ADR-0010 (as amended), BRIEF.md, the
125/172/173/175 task reviews, and seven parallel code audits at HEAD `1d9c6b2c`. Every mechanic
below was verified against current code (2026-07-03/04); trust symbol over line number at edit
time. This plan is written for implementation in isolation — where a choice existed, it is made
here, with the reason._

## Design doctrine (applied, not aspirational)

- **Readers stay dumb.** Self-contained attempt traces (Decision 6) exist so no trace consumer
  ever learns about attempt chains. One writer-side mechanism buys N unchanged readers.
- **One walk loop.** Resume re-enters `_run_inner`'s existing walk body with a parameterized
  entry. No second traversal, no `mode` flag (ADR-0006: share rules, not walks).
- **One status-policy pattern.** `load_resume_source` copies `_collect_candidate_traces`'s shape:
  iterate the shared `_iter_workflow_traces`, apply resume's own status policy locally. The
  iterator's "MUST NOT filter final_status" invariant is untouched.
- **Deletion-test cuts:** run-query glob consolidation DEFERRED (4 sites disagree on sort key —
  folding is a behavior change, not an extraction); no new persistence; no chain-aware readers;
  `RunnerConfig` untouched (resume data rides a `run()` kwarg, the 125 `gate_resolver` precedent).

## Verified facts this plan builds on (do not re-derive)

- `_run_inner` pre-walk preamble is ONLY: `validate_only_target` → `--only` early-return →
  guarded visit-count reset (engine.py:686-687) → `curr = workflow.start_node` (:690). No other
  state init; `initialize_execution_state` first runs inside `_execute_node` step 2 (:1022) and
  is idempotent.
- `_run_only_snapshot` (:760) prologue order is the template: seed → `initialize_execution_state`
  (:785) → stamp `restored_nodes` (:786) — that ordering is load-bearing (KeyError otherwise).
- **Routing never consults prior-node history.** `route_action` (:481) reads only
  `(last_action, curr.successors)`; Task-128 convergence resolves coalesce by *data presence in
  shared* (`output_resolver._is_all_absent_coalesce`). Restored nodes need NO
  `completed_nodes`/`node_actions`/`node_hashes` seeding. Actions not being traced is a
  non-problem.
- Memo cache needs nothing special: `--only` runs its target through normal `_execute_node`
  with no cache carve-out; resume mirrors it.
- The walk wraps every node in `loop_runtime_scope` (engine.py:723) — the resume arm must NOT
  add its own scope (that's the snapshot's single-shot pattern only).
- `_populate_outputs` (:926) reads the shared store only; with `only_node=None` it RE-RAISES
  `OutputResolutionError` (:946) — correct full-walk semantics for resume (a branch-not-taken
  output behaves exactly as on a normal run; declared outputs over branches already use `??`).
- `record_node_execution(cached=True)` yields `status: "cached"` (`_node_status`,
  workflow_trace.py:192-206); raw event-dict copying is IMPOSSIBLE (`_check_reserved_collision`
  raises on the reserved keys a copied event carries; seq/id would collide).
- Cost aggregation skips `status=="cached"` at every tier (`iter_llm_leaves(
  descend_cached_subtrees=False)`; `trace_tree.event_cost` default). The ONE count that would
  inflate is `nodes_executed = len(self._top_level_events())` (workflow_trace.py:1039).
- The UI: `status:"cached"` is in the frontend's `RUN_STATUSES` allowlist (events.ts:60) — a
  restored node renders as the cached style with zero frontend change. Unknown statuses are
  silently dropped (safe but invisible); extra event fields are stripped by the tailer's
  projection (never reach SSE); an unknown meta key `resumed_from` is tolerated end-to-end.
- `load_trace_file` resolves inline blobs back into `node_output` (`substitute_refs`,
  trace_io.py:242) — loaded events carry FULL outputs for seeding.
- `seed_snapshot_into_shared` reads only each node's final-event `node_output` — host/batch
  children (`sub_workflow_events`/`batch_items`) are NOT needed for seeding, and a childless
  restored host is safe for `tree()`/reconstruct (parent_id-based) and cost (cached boundary
  stops descent).
- `content_hash` = `workflow_content_hash(resolved.ir)` (core/workflow_id.py:62; provenance
  keys stripped) — the loader compares against the CURRENT resolved IR's hash; precedent
  `ui/run_tailer.py:508-512`.
- Escalation marker: `shared[node]["result"]["escalation"]` — UNDECIDED = non-empty dict
  WITHOUT `"decision"` key, or non-empty string; DECIDED = dict WITH `"decision": {chosen,
  notes}` (gate.py:130-142, 170-175).
- Gate JSONL lines: `{"kind":"gate", "node_id", "phase"("pause"|"resolution"), "gate_kind",
  "request"?(on pause), "resolution"?, ...}` (workflow_trace.py:678-687); disk-only; a
  dedicated raw reader is the sanctioned pattern (docstring: "Task 171 reads gate lines with
  its own explicit reader").
- Trace identity: `resolve_workflow(arg)` → `_workflow_path_id(resolved)` (runner.py:55-65;
  absolute path for file AND library runs, `ir-hash:<md5>` for inline). Resume MUST reuse both.
- uuid-shape vs workflow-name is NOT collision-proof (`validate_workflow_name` accepts
  uuid4-shaped names) → existence-based precedence (below).
- `PflowError` from a subcommand → `PflowCLI.invoke` → `output_error` → exit **1**.
- Raw-bytes fidelity vector: the python `code` node ONLY (`python_code.py:804` writes any
  object raw; read-file/http/shell base64-encode; mcp/llm/claude-code produce JSON/str).
- `runtime/` must not import `ui/` — the loader gets its own small raw-line reader.

---

## Final shape (what exists when done)

### A. `seed_walk_entry` — the shared Phase-0 helper
New module-level function in `src/pflow/runtime/engine/engine.py` (beside `validate_only_target`
/ `find_node_by_id` — the established home for shared engine/planner rules since PR #505):

```python
def seed_walk_entry(
    shared: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    entry: str,
    start_node: Any,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """Seed upstream outputs from a prior run's events and locate the walk entry node.

    Returns (entry_node, seeded_final_events_by_node). Callers own everything else:
    initialize_execution_state, restored_nodes/only_node stamping, degraded advisories.
    """
    final = seed_snapshot_into_shared(shared, events, exclude=entry)
    return find_node_by_id(start_node, entry), final
```

Callers after Phase 0: `engine._run_only_snapshot` (replacing its lines ~783+791),
`plan._resolve_walk_start` (replacing its lines ~492+495), and later the engine resume arm +
the planner resume path. Scope guard: if this grows a mode flag or callback, back off.
(`load_snapshot_or_raise` stays caller-side — the engine threads `snapshot_events`, the planner
is disk-only, resume supplies events from `load_resume_source`. Degraded handling stays
caller-side — engine emits an advisory, planner appends a diagnostic.)

### B. `ResumeSource` + `load_resume_source` — the loader
In `src/pflow/runtime/workflow_trace.py`, beside `load_full_run_events`:

```python
@dataclass(frozen=True)
class ResumeSource:
    path: Path                      # source trace file
    execution_id: str               # source run's id (becomes resumed_from)
    entry_node_id: str | None       # K; None => incomplete "between nodes" (resolve post-compile)
    last_completed_node_id: str | None  # set iff entry_node_id is None
    events: list[dict[str, Any]]    # full reconstructed top-level events (blob-resolved)
    inputs: dict[str, Any] | None   # meta.inputs (None on pre-175 traces)
    content_hash: str | None        # meta content_hash (None if absent)
    final_status: str               # "failed" | "incomplete"
```

VOCABULARY RULE (deep-review Critical, two agents): the side-effect predicate consumes IR
registry type names (`"llm"`, `"shell"`, `"code"`, `"mcp-*"`). A trace event's `node_type` is
the Python CLASS name (`"LLMNode"`, `"ShellNode"` — `instrumentation.py:590` records
`node_type_name`). `ResumeSource` therefore carries NO node-type field — the CLI derives K's
type from `resolved.ir["nodes"]` (registry name) ONLY (§E step 5). Never feed an event
`node_type` to `is_side_effecting` — `is_side_effecting("LLMNode")` is True and would
force-confirm the silent-llm marquee path.

```python
def load_resume_source(
    workflow_path: str | None = None,
    execution_id: str | None = None,
    *,
    debug_dir: Path | None = None,
) -> ResumeSource:
```
Exactly one of `workflow_path`/`execution_id` is given. Selection:
- `workflow_path` → newest candidate via `_iter_workflow_traces(debug_dir, workflow_path)`
  (first yielded = newest; the iterator already applies the format-2.x gate, the
  `workflow_path` collision guard, and the `--only` exclusion).
- `execution_id` → bare `debug_dir.glob("workflow-trace-*.json")`, newest-first by
  `_trace_recency_key`, first-line meta check (`json.loads(first_line)` →
  `kind=="meta" and execution_id matches AND data.get("only_node") is None` — the last
  predicate mirrors `_iter_workflow_traces`'s `--only` exclusion, which the workflow_path arm
  gets for free; without it, resuming an `--only` run's exec-id seeds an empty scope and
  masquerades a partial run as a resume). Then `load_trace_file` the match.

Refusal/derivation policy, in this order (each refusal = a typed error, §D):
0. **Inline sources**: `meta.workflow_path.startswith("ir-hash:")` (stdin/content-string runs)
   → `ResumeNotResumableError` ("inline/piped workflows cannot be resumed — no source file to
   re-resolve; save the workflow and re-run"). Without this arm, §E's re-resolution would
   raise a misleading `WorkflowNotFoundError("ir-hash:...")`.
1. **Liveness**: `is_locked(path)` — a LOCAL probe function (copy of
   `ui/run_tailer.is_trace_locked`'s ~15 lines: separate fd, `LOCK_SH | LOCK_NB`; `runtime/`
   cannot import `ui/`; extract-to-`core/` is NOT done here — two near-identical 15-line probes
   beat a new core module until a third consumer appears — noted as accepted duplication).
   `True` → `ResumeStillRunningError`. `None` (no fcntl/Windows) → fall through to the
   `run.complete`-present check only.
2. **Superseded**: scan the same workflow's candidates (`_iter_workflow_traces` on the source's
   `workflow_path` meta) for any trace whose meta `resumed_from == source.execution_id` →
   `ResumeSupersededError(newer_execution_id)` ("resume targets the newest attempt").
3. **Status arms** (`final_status` from the reconstructed trace):
   - `success` / `degraded` → `ResumeNothingToResumeError` ("the newest run succeeded").
   - `denied` → `ResumeNotResumableError` (human stop; suggest re-running).
   - `failed`: compute `failed = _unrecovered_failed_node_ids(final_events, warnings)`
     (workflow_trace.py:175-189, same inputs `_aggregates` uses). If EMPTY → gate-stopped:
     raw-line pass collects `kind:"gate"` lines; refusal names the last paused gate's
     `node_id`/`gate_kind` (`ResumeGateStoppedError`; Task 171 replaces this arm with `paused`
     handling). Defensive sub-arm: `failed` + empty unrecovered set + ZERO gate lines (should
     be impossible today — only gate stops produce that combination) → generic
     `ResumeNotResumableError` ("run failed without a resumable failed step"), never an
     undefined branch. If non-empty → `entry_node_id` = the failed node whose final event has
     the LOWEST index in the top-level event list (event order, NEVER the alphabetical
     `failed_node_ids` trailer field).
   - `incomplete` (Decision 7): raw-line pass over the file:
     a. collect TOP-LEVEL `node.start` lines ONLY (`parent_id is None` — a kill inside a
        sub-workflow leaves TWO dangling starts, host and child; the child's id is not in the
        top-level graph and would blow up `find_node_by_id` as a bogus "compiler bug" error;
        top-level scoping yields exactly the host, matching v1's top-level granularity); a
        top-level `node.start` whose `id` has no `kind:"event"` line with the same `id` →
        that `node_id` is K (killed mid-node).
     b. no dangling start, ≥1 top-level event → `entry_node_id=None`,
        `last_completed_node_id` = last top-level event's node_id (CLI resolves the successor
        post-compile, §E; ambiguity refuses there).
     c. no events at all (meta-only file) → `ResumeNothingToResumeError` ("run crashed before
        the first step — re-run instead").
4. **Escalation guard**: for every event in seed scope (all top-level events before K; if
   `entry_node_id is None`, ALL top-level events): if
   `node_output.get("result")` is a dict whose `"escalation"` is a non-empty dict without
   `"decision"` (or a non-empty str) → `ResumeNotResumableError` naming the node (undecided
   escalation must not be seeded — Decision 8).
5. **Fidelity guard** (Decision 5): recursive scan of seed-scope `node_output` values for str
   values matching `^<binary data: \d+ bytes>$` → `ResumeFidelityError` naming node+key
   (only the python `code` node can produce this — verified; error text says so and suggests
   re-running).
6. `content_hash` is RETURNED, not checked here — the loader has no workflow IR; the CLI
   compares (§E) because only it holds `resolved.ir`.

Also in this file: the small raw-line reader used by 3/4 —
`_iter_raw_trace_lines(path) -> Iterator[dict]` (~12 lines, mirroring `ui/run_node.py`'s
`_iter_trace_lines` semantics: skip non-dict, tolerate ONE truncated final line, raise
`json.JSONDecodeError` on earlier malformed lines).

### C. Engine re-entry + self-contained attempt trace

**`WorkflowEngine.__init__`** gains three params, mirroring the `only_node`/`snapshot_events`
precedent exactly: `resume_from: str | None = None`, `resume_events: list[dict] | None = None`,
`resume_source_id: str | None = None` (the source execution id, for the §-step-3 stamp).
Constructor raises `ValueError` if `resume_from` and `only_node` are both set (the CLI can't
produce this; belt-and-suspenders for library callers).

**`_run_inner`** — after the `--only` early-return and the visit-count reset, replace
`curr = workflow.start_node` with:

```python
if self.resume_from is not None:
    curr = self._prepare_resume(workflow, shared)   # returns entry node
else:
    curr = workflow.start_node
```

`_prepare_resume` (new, ~18 lines, sits beside `_run_only_snapshot`):
1. `entry_node, final = seed_walk_entry(shared, self.resume_events, entry=self.resume_from,
   start_node=workflow.start_node)` — wrapped in `except CompilationError: raise
   ResumeNotResumableError(...)` naming K ("step '<K>' no longer exists in the workflow — it
   was renamed or removed since the failed run; re-run instead"). Without the wrap, a
   `--force` resume after K was renamed surfaces `find_node_by_id`'s "compiler/graph bug"
   `CompilationError` — misattributed. The planner resume branch (§F) gets the IDENTICAL
   wrap; the Phase-4 parity test drives both real methods so the two wraps can't drift.
2. `initialize_execution_state(shared)` (BEFORE step 3 — the :785-786 ordering)
3. `shared["__execution__"]["restored_nodes"] = [nid for nid in final if nid != self.resume_from]`
   and `shared["__execution__"]["resumed_from"] = <source execution_id>` (threaded onto the
   engine as `resume_source_id: str`, third resume param) — the display/JSON surface reads
   these (step 7); per the node_state pattern, engine-only keys are stamped here, never added
   to `new_execution_state()`.
4. Re-record restored events (Decision 6): for each `nid` in `restored_nodes`, with
   `ev = final[nid]`: `self.trace.record_node_execution(node_id=nid,
   node_type=ev.get("node_type", "unknown"), duration_ms=0.0, success=True,
   node_output=ev.get("node_output"), cached=True, restored=True)`. No
   `sub_workflow_events`/`batch_items` (seeding never reads them; childless cached hosts are
   safe). NOTE: `node_output` passes through `_sanitize_for_json` again — idempotent on
   already-sanitized data. Empty-output fidelity: `record_node_execution` stamps
   `node_output` only when truthy (:735) — for the restored path the stamp condition becomes
   `node_output is not None` (restored-only branch), so an upstream node whose real output
   was `{}` survives re-record and a SECOND resume seeds `{}` rather than absent (a
   downstream coalesce distinguishes those).
5. Do NOT set `__execution__["only_node"]`. Do NOT wrap anything in `loop_runtime_scope`.
6. Return `entry_node`.
7. **Success-path visibility (deep-review: without this, a resumed run renders byte-identical
   to a full run — the exact ambiguity the `--only` indicator exists to prevent,
   success_formatter.py:535-538).** The formatter surface reads the two §-step-3 stamps:
   `build_execution_steps`'s relabel already handles per-step status; additionally the
   success formatter (a) emits a resume mode-indicator line at parity with
   `format_only_indicator` — `⤷ Resumed from <execution-id> at '<K>' — N upstream steps
   restored` — keyed off `__execution__["resumed_from"]`, and (b) adds `resumed_from` and
   `nodes_restored` to the JSON/MCP `execution` dict so programmatic consumers get a
   machine-readable resume marker. Test: text output contains the indicator; JSON output
   carries both fields; a NON-resumed run carries neither.

**`record_node_execution`** gains `restored: bool = False`; in the event-construction block
(workflow_trace.py:721-742) add `if restored: event["restored"] = True`. `cached=True` supplies
`status:"cached"` — cost exclusion and UI rendering follow with zero further change.

**`_aggregates`** (workflow_trace.py:1039):
`"nodes_executed": sum(1 for e in self._top_level_events() if not e.get("restored"))`.
(`nodes_failed`/`failed_node_ids`/cost need no change — restored events are cached-status.)

**`WorkflowTraceCollector`** gains `resumed_from: str | None = None` (init, beside
`execution_id`); `_meta_fields()` (~:1019) emits it; `META_KEYS` in `core/trace_io.py:35-44`
gains `"resumed_from"` (BOTH edits together, or the fixture builder misroutes it to the
trailer); the trace format bumps to `2.6.0` (`TRACE_FORMAT_VERSION`, additive).

**`WorkflowRunner.run`** gains a kwarg `resume_source: ResumeSource | None = None` (the 125
`gate_resolver` precedent — `RunnerConfig` stays execution-config-only and primitive-typed;
`runner.py` already imports `workflow_trace` at function level, no new module edge).
`_compile_and_execute` threads it:
- collector: `resumed_from=resume_source.execution_id`
- engine: `resume_from=resume_source.entry_node_id, resume_events=resume_source.events,
  resume_source_id=resume_source.execution_id`
- params: caller (CLI) merges inputs BEFORE calling run — the runner does nothing extra.

### D. Errors
In `src/pflow/core/exceptions.py`, modeled on `OnlySnapshotMissingError` (:908 — class-level
default suggestion + `to_diagnostics()` → one `Severity.ERROR` diagnostic,
`context={"category": "execution_failure"}`); all exit 1 via `PflowCLI.invoke`:

- `ResumeSourceError(PflowError)` — base, carries `trace_path`/`execution_id` context.
- Subclasses (each a distinct message + suggestions, one class per refusal FAMILY, not per
  message): `ResumeSourceMissingError` (no trace found), `ResumeNothingToResumeError`,
  `ResumeNotResumableError` (denied / undecided-escalation / ambiguous-successor / inline
  `ir-hash:` source / K-removed-after-edit), `ResumeGateStoppedError`,
  `ResumeStillRunningError`, `ResumeSupersededError`, `ResumeFidelityError`,
  `ResumeSideEffectConfirmationError`, `ResumeStaleWorkflowError`.
Message requirements (deep-review agent-UX pass):
- `ResumeSideEffectConfirmationError` mirrors `GateNotInteractiveError`'s agent-first shape —
  what/why/how — and MUST name K, its registry node type, and state "its side effects may
  fire again"; suggestion is the literal recipe: confirm with your user, then re-run with
  `--force`. `to_diagnostics()` sets the node id.
- `ResumeStaleWorkflowError` has TWO messages: hash-differs → "the workflow was edited since
  the failed run"; `content_hash is None` (pre-173 trace) → "cannot verify the workflow is
  unchanged — this run predates hash tracking" (never claim an edit that may not have
  happened). Both suggest `--force`.
- `ResumeSupersededError`'s suggestion is the literal command: `pflow resume
  <newer_execution_id>`.
- All carry the source `execution_id` in context.

### E. CLI — `src/pflow/cli/commands/resume.py`

```
pflow resume [TARGET] [KEY=VALUE]... [--force] [--dry-run] [--output-format text|json] ...
```

Registration: import + `cli.add_command(resume_cmd)` in `cli/main.py` (~:152/:169). Click shape:
`@click.argument("args", nargs=-1, type=click.UNPROCESSED)` — first non-`key=value` token is
TARGET (may be absent only when exactly one workflow is ambient? NO — TARGET is required in v1;
a bare `pflow resume` errors with usage. Rationale: "newest failed run of WHAT" is ambiguous
without a workflow, and scanning the whole debug dir invites cross-project surprises. The
spec's "bare = newest failed" is satisfied by `pflow resume <workflow>` = newest failed run OF
that workflow).

Flow:
1. Split args: TARGET + `parse_workflow_params(rest)` (`cli/param_parsing.py:48`).
2. Disambiguate TARGET (existence-based; uuid-shape alone is not collision-proof):
   a. If it matches `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`:
      try `load_resume_source(execution_id=TARGET)` first; on `ResumeSourceMissingError`
      fall through to (b) — but if (b)'s `resolve_workflow` then raises
      `WorkflowNotFoundError`, do NOT let that surface (its "did you mean <workflow>?"
      suggestions point at the wrong namespace for a mistyped run id): re-raise
      `ResumeSourceMissingError` stating both interpretations failed — "no run with
      execution id '<uuid>' in <debug_dir>, and no workflow by that name".
   b. `resolved = resolve_workflow(TARGET)`; `wf_path = _workflow_path_id(resolved)`
      (import both from `execution/` — public enough; if `_workflow_path_id` stays private,
      promote it to `workflow_path_id` and keep a delegating alias);
      `source = load_resume_source(workflow_path=wf_path)`.
   For path (a) hits, ALSO resolve the workflow from the source trace's meta
   `workflow_path` (`resolve_workflow` on it) — needed for compile/inputs/hash below; if the
   file no longer exists at that path → actionable error.
3. Content-hash gate: `workflow_content_hash(resolved.ir)` vs `source.content_hash`;
   mismatch and not `--force` → `ResumeStaleWorkflowError` (message: workflow edited since the
   failed run; seeded outputs may not match; re-run, or pass --force). Missing
   `source.content_hash` (old trace) → treat as mismatch.
4. Between-nodes entry resolution (only when `source.entry_node_id is None`): from the IR
   edge list, select edges out of `last_completed_node_id` whose action is the DEFAULT route
   only — named-action and `error` edges are not default routes (`_build_edges` semantics);
   AND refuse if the node is a dynamic router (a `code` node with runtime-determined `next` —
   `has_dynamic`, markdown_parser.py:1225 — its taken route was never traced, so a single
   declared edge can still be the wrong one). Exactly one default successor and not dynamic →
   that is K (`dataclasses.replace(source, entry_node_id=K)`); zero, >1, or dynamic →
   `ResumeNotResumableError` (ambiguous re-entry; suggests re-run). Impl note: if the IR does
   not expose the default-action/dynamic distinction cleanly, resolve via the compiled
   graph's `successors` dict instead (`compile_workflow` + `find_node_by_id`) — correctness
   over avoiding a compile; never guess from a bare edge count.
5. Side-effect policy (Decision 4): `node_type` = the IR registry type for K, read from
   `resolved.ir["nodes"]` — NEVER an event's `node_type` (class-name vocabulary; see the §B
   rule). New public predicate `is_side_effecting(node_type: str) -> bool` in
   `runtime/compilation/compiler.py` = `node_type != "llm"`;
   `_default_cache_for_node_type` becomes `return not is_side_effecting(node_type)`.
   If side-effecting and not `--force`: `can_prompt(output_controller)`
   (`execution/gate_prompt.py:37`; controller via the `run.py:41-51` `_get_output_controller`
   pattern) → TTY: `click.confirm` on stderr, default No, naming K + its type + "its side
   effects may fire again"; declined → clean exit 1. Non-TTY → raise
   `ResumeSideEffectConfirmationError`.
6. Inputs: `params = {**(source.inputs or {}), **cli_params}`. If the workflow declares
   required inputs that are absent from the merge → the normal input-validation error path
   already handles it (verify message quality; if it doesn't mention resume, wrap with a
   suggestion to pass `key=value`).
7. `--dry-run` → `runner.plan(...)` with the resume threading (§F). Else →
   `WorkflowRunner().run(resolved-workflow-arg, params, config, resume_source=source, ...)`
   reusing `run.py`'s existing execution/output helper (extract the small helper if needed
   rather than duplicating output handling — decide at impl time which of `run.py`'s helpers
   is the minimal reusable seam; do NOT re-implement output routing).
8. Exit codes: success 0; refusals 1 (PflowError); denied-at-a-downstream-gate 3 (unchanged
   from run); click usage 2.
9. `--help` text (specified here because it's the first surface an agent hits): one-liner
   "Resume a failed or interrupted run from the step that failed."; TARGET doc: "a workflow
   (name or path) — resumes its newest failed run — or an execution id — resumes that exact
   attempt"; note that TARGET is required, `KEY=VALUE` overrides the original run's inputs,
   and `--force` bypasses the side-effect confirmation and the edited-workflow check.
10. Failure-side discoverability: the failed-run output (error formatter path) gains one line
    when a trace was streamed — `To resume from the failed step: pflow resume
    <execution-id>` — the execution id is known at that point; agents discover resume where
    they need it, not in the guide. (Skip when no trace was written: --no-trace/MCP.)

### F. Dry-run parity (Decision 2)
Thread `resume_from: str | None = None, resume_events: list[dict] | None = None` through
`build_plan` (plan.py:222) → `_build_plan_with_shared` (:249) → `_resolve_walk_start` (:468).
In `_resolve_walk_start`: if `resume_from` → `seed_walk_entry(shared, resume_events,
entry=resume_from, start_node=compiled.start_node)` and return the entry node (do NOT set
`state.only_node` — `_apply_follow:459` stops the walk at `only_node`, which resume must not).
Wrap the call in the same `except CompilationError → ResumeNotResumableError` as the engine's
`_prepare_resume` step 1 (K-removed guard, in lockstep on both paths).
`runner.plan` threads from its `resume_source` kwarg (same shape as `run`). PlanEntries for
restored nodes: none are emitted (the plan starts at K) — the dry-run header/footer must state
"resuming from '<K>': N upstream steps restored from <execution-id>" (extend the existing plan
rendering minimally; a list of restored node ids is available from the seed return).
Cost caveat (known drift-suite blind spot): plan cost covers K-onward only — that is correct
and stated in the header line.

### G. Docs & guide
`pflow guide` gains a resume topic (`src/pflow/guide/`): at-least-once K; `--force` semantics;
loop-K restarts at iteration 1; downstream gates re-prompt (`--auto-approve` works); top-level
granularity (sub-workflow failures re-run the whole host; memo cache softens); prompt/system
strip caveat verbatim from the `--only` docs; resume-by-execution-id is the cwd-safe form
(relative-path resolution is cwd-relative; trace identity is the absolute path); inline/piped
workflows are not resumable (no source file); note for `analyze-cache` users: a resumed
attempt's trace under-reports LLM coverage (restored upstream LLM nodes carry no `llm_call`),
so cache analysis of a resumed trace shows partial evidence scope — analyze the original
attempt's trace instead.

---

## Phases (each lands green; one PR, phased commits)

**Phase 0 — parity test + extraction (pure refactor, zero behavior change)**
1. Write `tests/test_execution/test_plan_drift.py::test_engine_and_planner_walk_entry_state_match`
   FIRST: run a 3-node workflow, fail nothing; then `--only` the middle node on BOTH the engine
   path (real run) and `build_plan`; assert the seeded shared-store keys and the located entry
   node id are identical. Mutation-verify: temporarily re-fork one side (inline the old seed
   code with one key filtered) via Edit, confirm ONLY this test fails, revert. (Recipe:
   `test_plan_batch_sub_workflow_output_shape_matches_engine`, PR #505. Never `git stash`.)
2. Add `seed_walk_entry` (§A) to engine.py; rewire `_run_only_snapshot` and
   `_resolve_walk_start`. `make test` green, parity suites unmodified, `-m trace_files` green.
3. Run-query consolidation: NOT DONE (recorded: 4 glob sites disagree on sort key + scoping;
   folding is behavior change → fails this task's refactor gate; standalone follow-up).

**Phase 1 — loader (failed-trace arms)**
`ResumeSource`, `load_resume_source` (§B, with ONE deferral: the `incomplete` status arm is a
stub in this phase — it raises `ResumeNotResumableError` — and Phase 5 replaces the stub with
the full arm-3-incomplete derivation; the split is commit/test scoping only, both land in this
PR), `_iter_raw_trace_lines`, local flock probe, exceptions (§D). Unit tests with JSONL fixtures
via `tests/shared/trace_jsonl.py`: newest-selection, by-execution-id, liveness, superseded,
success/denied/gate-stopped/escalation/fidelity refusals, event-order entry (multi-failure:
build a trace with K-then-F failed events; assert entry==K), missing/`null` meta.inputs.

**Phase 2 — engine re-entry + self-contained trace (prove on idempotent K)**
Engine params + `_prepare_resume` (§C); `record_node_execution(restored=)`; `_aggregates`
exclusion; collector `resumed_from` + `META_KEYS` + fixture-builder routing; `runner.run`
kwarg + threading; TRACE_FORMAT_VERSION 2.6.0 (check `_iter_workflow_traces`'s
`startswith("2.")` gate still passes — it does).
Tests (mutation-verify the starred ones):
- e2e: 3-step llm workflow, step 2 fails (llm mock) → resume → upstream NOT re-executed
  (mock call count), K + tail execute, outputs correct.
- *attempt-trace self-containment: after a SUCCESSFUL resume, run `--only <step3>` → seeds
  cleanly from the attempt trace (the poisoning regression).
- *resume-of-a-resume: fail step 2, resume with step 3 failing, resume again → seeds from
  attempt 2 alone (upstream present via restored events).
- restored events: `status=="cached"`, `restored is True`, cost totals + `nodes_executed`
  exclude them; `resumed_from` on the meta line; source trace byte-identical after resume.
- update `tests/test_runtime/test_trace_format_2_2.py:26` (asserts `TRACE_FORMAT_VERSION ==
  "2.5.0"` — bump alongside the constant).
- empty-output fidelity: upstream node with real output `{}` → resume → resume again; second
  seed yields `{}`, not absent (the §C step-4 `is not None` stamp).
- success-path visibility (§C step 7): resumed run's text output carries the `⤷ Resumed
  from…` indicator; JSON carries `resumed_from` + `nodes_restored`; a normal run carries
  neither.
- branch scenario: workflow whose K sits on one conditional branch; resume; converged
  coalesce downstream reads the restored branch value.
- `restored_nodes` display: upstream relabeled not_executed (execution_state path — already
  works; pin it).
- UI real-surface check (manual, `make ui-build` + `pflow ui`): resumed run overlays restored
  nodes as cached; `/api/runs` lists the attempt; no tailer errors on `resumed_from`.

**Phase 3 — CLI + side-effect policy**
`resume.py` (§E steps 1-3, 5-10), `is_side_effecting` promotion, registration, the failed-run
resume-hint line (§E step 10). Tests: TTY confirm yes/no (CliRunner with input), non-TTY hard
error names K + node type + contains `--force`, `--force` bypass, stale-hash refusal with the
correct message per case (edited vs pre-hash-unverifiable) + `--force` override, uuid-shaped
saved-name disambiguation (existence precedence; mistyped uuid → `ResumeSourceMissingError`,
never `WorkflowNotFoundError` suggestions), key=value override beats meta.inputs, refusal
exit code 1, side-effect matrix (llm silent — pinning the IR-type vocabulary;
shell/http/mcp/code/claude-code/file-ops gated), failed-run output contains the
`pflow resume <execution-id>` hint (and omits it for --no-trace).

**Phase 4 — dry-run parity (Decision 2)**
§F threading + `pflow resume --dry-run`. Extend the Phase-0 parity test with a resume case,
mutation-verified the same way. Assertion scope (deliberate — a full-`shared` equality would
false-fail): compare EXACTLY (a) the `shared[node_id]` outputs seeded by the helper and
(b) the located entry-node id, driving the REAL `_prepare_resume` and `_resolve_walk_start`
(not `seed_walk_entry` directly). `restored_nodes` stamping and event re-recording have no
planner counterpart — deliberately outside the pin.

**Phase 5 — incomplete arm (Decision 7)**
Loader arm 3-incomplete (§B) + CLI step 4 (between-nodes successor from IR edges). Tests:
killed-mid-node (fixture: trace with dangling `node.start`) resumes at that node;
killed-between-nodes single-successor resumes at successor; branching ambiguity refuses;
meta-only refuses; locked-incomplete refuses (flock held by the test).

**Phase 6 — docs + close-out**
Guide topic (§G); `docs/` CLI reference; CHANGELOG note; close #255 (its pre-engine-failure
cases become "no trace → `ResumeSourceMissingError`" tests); full spec Verification matrix;
`make test` + `make check` vs the captured baseline; Task-159 `baseline/verify.sh`.

**Pre-flight (before Phase 0):** capture baseline (`make test`/`make check` pass/fail names);
re-verify the file:line anchors in this plan against HEAD (symbols are authoritative).

---

## Invariant checklist (check at every engine/trace edit — from the 125/172/173/175 reviews)

- `kind:"gate"` and `node.start` lines stay DISK-ONLY (never `collector.events`). Restored
  events are the opposite: genuine events in BOTH (they must reach `final_events_by_node`).
- `GateDenied`/`GateNotInteractiveError`/`GateResolverError` cross every except boundary
  un-converted; do not add a generic `except Exception` between gate and runner.
- Streaming is main-thread-only; `_prepare_resume` runs on the main thread inside
  `_run_inner`, after `start_streaming()` (depth-0 `run()`) — restored events flush
  immediately after the meta line. `resumed_from` must be set on the collector at
  CONSTRUCTION (runner), before `start_streaming` — it rides `_meta_fields`.
- `_host_frame` coupling (engine gate-except ↔ WorkflowExecutor) untouched; run
  `test_gate_trace.py` when touching `_execute_node`'s neighborhood.
- Escalation-decision write-before-loop-re-entry ordering preserved automatically (resume
  re-enters via the EXISTING walk body).
- `resumed_from`: `_meta_fields` + `META_KEYS` + fixture builder, together.
- Aggregations scope to `_top_level_events()`; restored excluded from `nodes_executed` only
  (fail/cost paths already correct via cached status).
- `_iter_workflow_traces` gains NO status filter; `load_resume_source` owns its policy.

## Explicitly out of scope (v1)

Nested/sub-workflow entry (top-level K only); gate re-entry from gate-stopped traces (171's
`paused` arm — the refusal arm is its plug-in point); the `pflow run` rename (Task 151); the
4-glob run-query consolidation (deferred; recorded in Phase 0); UI chain-join rendering
(folded into 171, owner decision 2026-07-04 — `resumed_from` is on the meta line for it; see
task-171.md "UI attempt-chain rendering"); a bare `pflow resume` with no target
(deliberate: ambiguous scope); flock-probe extraction to `core/` (accepted 15-line duplication
until a third consumer).
