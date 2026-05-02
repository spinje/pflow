# Handoff: recommendations-section plan (Task 159 v1 follow-up)

You're picking this up cold. **Read `recommendations-section-plan.md` first.** It has the algorithm specs, file:line citations, fixture requirements, user decisions, and verification commands. This file is what's NOT in the plan — the journey, the wrong frames, the gotchas, and what I'd tell a smart colleague who walked into the room.

---

## Where this came from

Task 159 v1 shipped four segments (B–G) and a cost-wiring follow-up (5920 tests, all four segments green). After cost wiring landed, an audit surfaced that the analyzer's "Recommendations" section was effectively empty — the 4 analytical-tier warnings that carry per-recommendation `savings_usd` were stubbed, plus `suggested_blocks` was always empty, plus `cache.discrepancy --from-trace` had no emission code. Mode-1's value prop ("where should I add caching?") was unimplemented.

The plan you're about to execute closes that gap.

## The journey (and why it took 3 rounds to get right)

**Round 1** — I wrote the plan with a `core/cache_analysis/predicted_key.py` module that re-implemented the runtime's cache_key pipeline (`compute_node_config + compute_node_cache_key + compute_batch_cache_key + resolve_templates`) externally. 6-agent review found 11 Criticals. I revised.

**Round 2** — Re-running the review found **14 NEW Criticals introduced BY the Round-1 fixes**. Every "fix" exposed another shape-precision drift between my analyzer-side reproduction and the runtime's actual semantics. Concrete drifts caught:

- `split_params` returns `(template_params, static_params)` (template first); my unpacks said `(static_params, template_params)`. Swap.
- `prompt_cache_content` runtime shape is `{name, prose, value}`; my dict was `{prose, value}`. Missing key.
- `MemoizationCache.get_latest_for_node` returns `tuple[dict, float]`, not a dict — my code did `latest["output"]` (TypeError).
- `compute_node_cache_key` runtime path passes RESOLVED params; analyzer passed RAW params with `${var}` strings.
- Batch `semantic_config` runtime shape is a 4-key extracted subset (`items_template, item_alias, error_handling, max_retries`); analyzer passed the raw IR `batch` dict (7 keys).
- `_collect_llm_calls_from_events` is an INSTANCE method on `WorkflowTraceCollector`, not a free function; the import I specified would `ImportError`.
- It also flattens events into bare `llm_call` dicts; my consumer code read `event["llm_call"]` as if nested. Always returns `None` for cache fields.
- It SKIPS cached events at line 312 — exactly the events the discrepancy detector needs.
- Layer policy violation: `from pflow.execution.runner import _synthesize_inline_workflow_id` drags WorkflowValidator + the entire engine into the analyzer's import graph.
- `expected_types={}` skips type coercion; runtime's `int → str` coercion produces different bytes than analyzer's raw `42`.
- `WorkflowExecutor` nodes are excluded from memoization (`runtime/CLAUDE.md`), so my "iterate every upstream node and collect from memo" loop trips `missing_upstream=True` for every workflow with a sub-workflow.
- Parallel-batch event ordering is COMPLETION order, not input order; `zip(events, predicted_keys)` scrambles per-item attribution.
- ~9 more like this.

The pattern: every Round-1 fix made the analyzer-side reproduction MORE accurate but never questioned the architecture. The bug class was structural, not local.

**Round 3** — The user said "**zoom out and see the big picture is non-optional**" and "**top-10% codebases, simplicity of the FINAL code**." 4 parallel pflow-searcher agents (~6 minutes) surfaced what I'd missed for two rounds:

> **The dry-run planner ALREADY produces predicted cache_keys via `plan_node`.** `WorkflowRunner.plan()` calls `compile_workflow + build_plan`; `build_plan` calls `plan_node` per node; `plan_node` returns `NodePlan(cache_key=...)`. **The cache_key is computed during planning — it's just not propagated onto `PlanEntry` today.**

The architectural fix: add ONE field (`cache_key: str | None = None`) to `PlanEntry`. Propagate from `NodePlan.cache_key` at the ~10 PlanEntry construction sites in `plan.py`. The analyzer becomes a one-line consumer. The drift defense reuses the existing `test_plan_drift.py::test_plan_matches_engine_for_workflow_with_prompt_cache` (line 2088) — extend by 5 LOC to also assert `entry.cache_key == engine_cache_key`. ALL 14 Round-2 Criticals are obsolete by design change.

This is the load-bearing realization. **No top-10% codebase re-implements compiler semantics for analysis purposes.** ruff/clippy consume rustc's HIR. mypy consumes Python's `ast`. ts-eslint consumes tsc's checker. **The analyzer is a third consumer of `plan_node` (alongside engine and planner), not a parallel re-implementation.**

## The wrong frame and why it persisted

The wrong frame was: **"the analyzer needs its own predicted-key module."**

Why I was stuck for two rounds:
1. The spec mode-4 example shows "Predicted hit_ratio: 72%, Actual: 0%" — I read "predicted" as "computed by the analyzer in isolation." It actually means "the static-analysis estimate (mode 1-3 cache_ratio_pct) compared against the trace's measured ratio." The PREDICTION is a planner artifact the analyzer reads, not something it computes from scratch.
2. The catalog row for `cache.discrepancy` has `predicted_cache_key` and `actual_cache_key` fields — implying the analyzer computes both. They're actually `nullable_cost_keys` (can be None); the analyzer just needs to read them when available.
3. My Round-1 mental model was "cache_render.py has shared helpers; predicted_key.py is the analyzer's parallel companion." The "parallel" framing is wrong. There's only ONE source of cache_keys — `plan_node`. Everyone else consumes.
4. Round 2 fixes deepened the mistake. Every shape-mismatch fix tightened the parallel reproduction. None questioned whether the parallel reproduction should exist.

**If you start to feel that pull again** — "I need to mirror the runtime's hash logic from the analyzer side" — STOP. Re-read the architectural decision section in the plan. Use `build_plan` directly. Read `entry.cache_key` from the result. That's the entire C.2 algorithm.

## What to verify before you write any code

Auto-format may have shifted line numbers since the plan was written. **Re-grep these before patching:**

1. `grep -n "@dataclass" src/pflow/execution/result.py` — find `PlanEntry`. Confirm it's at line ~82-108 with no `cache_key` field. Adding the field is the load-bearing change.
2. `grep -n "PlanEntry(" src/pflow/execution/plan.py` — find all construction sites (plan says 10 at lines 521, 842, 883, 895, 922, 1071, 1165, 1310, 1749, 2008). Verify count. Each needs `cache_key=plan.cache_key` (when NodePlan is in scope) OR `cache_key=None` (routing errors, opaque entries).
3. `grep -n "def plan_node\|NodePlan" src/pflow/runtime/engine/plan_node.py` — confirm `NodePlan.cache_key` exists. The plan cites line 35; verify.
4. `grep -n "def _create_planner_shared" src/pflow/execution/plan.py` — confirm at line 464. Promotion to public (rename + underscore alias) is part of C.2.
5. `grep -n "def test_plan_matches_engine_for_workflow_with_prompt_cache" tests/test_execution/test_plan_drift.py` — confirm at line 2088. Read its body fully — you'll extend it. The plan specifies the SQL query verbatim; don't reinvent.
6. `grep -n "if event.get..cached" src/pflow/runtime/workflow_trace.py` — confirm line 312 has the cached-skip. Your new `_iter_llm_events` walker drops this guard.
7. `grep -n "apply_memo_hit\|_augment_llm_usage_with_cache_metadata" src/pflow/runtime/engine/instrumentation.py` — confirm cache_key/cache_source/cache_age_sec are written into `llm_usage` BEFORE the trace event is recorded (so cached events DO carry these fields).
8. `grep -n "chunk.name == chunk.var_expr" src/pflow/core/markdown_parser.py` — confirm line 1755-1762 invariant. Test fixtures must respect this; can't generate IR where name and var diverge without hitting MarkdownParseError.

If any of these have drifted significantly, surface to the user before encoding. Cite-and-fix-later is fine; cite-without-grep is not.

## The user — how they work

This is the highest-leverage section. Internalize it.

### Direct quotes from this conversation that shaped the plan

- *"prioritize simplicity of the FINAL code, not how easy it is to get there"* — the load-bearing principle. Applied at every fork. Would have caught Round-1 wrongness at the start if I'd applied it from the beginning.
- *"what's the right solution that the top 10% of codebases similar to this one would implement?"* — the operational test. Concrete analogs (ruff/clippy/mypy/rustc/ts-eslint), not abstract qualities.
- *"zoom out and see the big picture is non-optional here I think"* — said when I was stuck in Round-2 patches. Forcing function for "step back and re-question the frame."
- *"are you FULLY happy with the current state of the plan? any loose ends or ambiguity?"* — NOT a request for reassurance. A forcing function for honest self-audit. Caught 5 loose ends I'd glossed.
- *"go ahead with A, but ultrathink how to apply this correctly to the plan, make sure to verify additional assumptions before you begin if necessary"* — the verification discipline. The user expects you to grep, read code, verify claims BEFORE encoding. Not after.
- *"if we build this we need to prioritize simplicity of the FINAL code, not how easy it is to get there. When in doubt ask whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"* — restated mid-conversation when I was about to recommend a substantial rewrite (Option B). It snapped me out of patch-mode and into architecture-mode.

### Working-style cues

- **Pushback comes as questions, not assertions.** If the user asks "did you consider X?" or "why this and not that?" — they almost certainly already see the answer and want you to re-examine. Treat as a forcing function.
- **Mid-stream redirects.** The user reads your work in real-time. When something feels off they redirect; don't argue. Reconsider from scratch.
- **Decisions need clarity-first.** Surface 2-3 options with tradeoffs + recommendation + importance score (1-5). Don't decide silently. The 11 user decisions in the plan (D1–D11) follow this shape.
- **20 turns over a wrong design.** They'll patiently iterate. The cost of getting it right is lower than the cost of shipping something subtly wrong.
- **Avoid noise.** Don't over-document. Don't add helper comments that explain what the code already says. Don't surface every nit. The plan is dense; keep it that way.
- **No git operations without explicit instruction.** No commits, no branches, no pushes unless the user says so by name.

## Subtle gotchas the plan doesn't cover

These are real but didn't fit cleanly in the plan's algorithm specs:

1. **D11 is undersold at importance 3/5; treat it as 4/5.** The "no-inputs invocation" is the dominant case for greenfield exploration. If a user runs `pflow analyze-cache <wf> --from-trace <path>` without re-supplying inputs (likely), `compile_workflow` raises `CompilationError`. The plan's recommended (A) catches it and continues with observable-only attribution. **Don't skip the try/except.** Without it, the entire `--from-trace` mode crashes on every greenfield exploration.

2. **`PlanEntry.cache_key` may surface in `pflow run --dry-run` JSON output.** UNEXPLORED. Adding a field to a dataclass typically propagates through `to_dict()` if it exists. Check if any rendering path reads PlanEntry as a dict — the new field might leak. The plan doesn't address. Consider a sentinel-render that hides cache_key from text output but keeps it in JSON. Or just ship it and let agents see it. Surface to user if you want a decision.

3. **`_aggregate_and_cap_discrepancies` uses `dataclasses.replace`, NOT in-place mutation.** Round-2 W-SILENT-2 found that `Diagnostic.context` may be shared across diagnostics from `make_diagnostic`. Mutating `rep.context["affected_invocations"] = ...` could leak across diagnostics. The plan specifies `replace`; **don't optimize this away as "premature defensiveness"** — it isn't.

4. **Sub-workflow node_id collisions in `_flatten_plan_keys`.** If a parent has a batch sub-workflow producing N sub_plans, internal nodes share node_ids across iterations. My flat `dict[node_id, cache_key]` last-wins. For homogeneous batches this is fine (same key); heterogeneous batches lose attribution. Surface as a notes entry; defer fine-grained handling to v1.x. **Don't try to "fix" this elegantly during implementation** — it's a real edge case, but solving it requires keying by `(workflow_path, node_id)` and changes downstream consumers.

5. **The `_iter_llm_events` walker has TWO nesting levels per `batch_items`.** Each item has its own `events` list (nested sub-workflow events PER ITEM). Easy to miss the `yield from _iter_llm_events(item.get("events", []))` line. The plan specifies it correctly; don't simplify it.

6. **The plan mentions `_create_planner_shared` promotion to public, but the analyzer doesn't call it directly.** The analyzer calls `build_plan`, which calls `_create_planner_shared` internally. The promotion is for cleanliness (some test fixture or future caller might want it). Don't search for the analyzer's direct call — it's not there.

7. **TDD discipline is non-negotiable for this work.** Segment 4's stubs survived 4-agent code review because per-id tests round-tripped through `make_diagnostic` (catalog dispatch) but never exercised emission paths. The plan mandates per-id structural emission tests with **dotted-path chunk coverage**. Don't fall back to round-trip tests. Don't skip the dotted-path requirement — bare `${concept}` fixtures missed CRIT-1 last time.

8. **Mutation-test thought experiment per detection.** Comment out the `make_diagnostic("cache.X", ...)` call in production; the per-id fixture MUST fail. If it doesn't, the test isn't testing the emission. Apply this BEFORE declaring any detection done.

9. **Don't write a new `test_predicted_key_runtime_parity.py`.** The drift defense IS extending the existing `test_plan_drift.py::test_plan_matches_engine_for_workflow_with_prompt_cache`. Round 1 specified a separate file; that's wrong. The whole architectural shift is "reuse existing infrastructure."

10. **`extract_root_node_id` is a TRAP.** It returns the bare root only. Chunk names in the IR are FULL paths (`creative-direction.response`, not `creative-direction`). Use FULL `var_expr` for declared_names membership, not the root. CRIT-1 from Round 1; still applies.

## Open hedged claims (verify before/during implementation)

- **NEEDS VERIFICATION:** the exact 10 PlanEntry construction sites in `plan.py`. Plan cites lines 521, 842, 883, 895, 922, 1071, 1165, 1310, 1749, 2008 from a `grep "PlanEntry("`. Re-grep before patching. Some sites have NodePlan in scope (pass `cache_key=plan.cache_key`); some don't (routing errors, opaque sub-workflows — pass `cache_key=None`). Trace each.
- **NEEDS VERIFICATION:** `MemoizationCache` rows are keyed where the test's SQL query expects. The plan's drift-test extension uses `SELECT cache_key FROM cache_entries WHERE node_id = ? ORDER BY created_at DESC LIMIT 1` — verify this returns the cache_key the engine wrote. The schema is at `runtime/cache.py:173-186`.
- **ASSUMPTION:** the `_create_planner_shared` rename has minimal in-tree caller impact. Plan says "1-2 sites." Re-grep `_create_planner_shared` to confirm before renaming.
- **MIGHT MATTER:** `build_plan` may emit diagnostics during planning (routing errors, sub-workflow resolution issues). The analyzer currently discards `plan.diagnostics` from its predicted-keys path. If routing errors should surface in `analyze-cache` output, that's a separate concern. The plan currently treats it as out-of-scope for v1.
- **UNEXPLORED:** what if the user supplies `pflow analyze-cache <wf> sources='[...]' --from-trace <trace>` where the trace was produced under DIFFERENT inputs? Predicted_key derived from current inputs ≠ actual_key from trace. Entire trace would emit `key_mismatch`. The plan doesn't address. Surface as a v1.x follow-up: detect input-divergence between current invocation and trace.

## What I'd tell myself if starting over

1. **Apply the "is there an existing primitive that produces this?" lens BEFORE writing parallel infrastructure.** Round 1's predicted_key.py was 80 LOC of re-implementation. The right answer was "extend PlanEntry by one field." 5 LOC vs 80 LOC. The right answer was reachable in Round 1 if I'd asked the right question.

2. **The "top-10% codebases" lens is fast and accurate.** rustc + clippy share the compiler's analysis pipeline. mypy consumes the AST. eslint plugins consume tsc's checker. **None of them reimplement the compiler.** That's the pattern. If your design is "the analyzer reproduces what the compiler/runtime does," step back.

3. **Round 6 of Task 159's plan-writing journey landed the diminishing-returns lesson:** "4 plan-review rounds upper bound." For this work, Round 2 was already past the line. Round 3's ultrathink/architectural pivot was the right call; a Round 4 of patches would have produced more shape-precision drift.

4. **TDD per detection with dotted-path coverage is the structural defense against the segment-4 stub-survives-tests pattern.** Don't fall back to round-trip tests when emission tests are harder to write. Write the harder tests.

5. **The user's "ultrathink" prefix is a real signal.** When they include it, slow down and reason through the architecture. Don't jump to encoding.

## What's actually risky in the implementation

- **A.5 ordering relative to A.4** (CRIT-6 from Round 1) — A.5 populator must run BEFORE A.4 emission. The plan specifies this; don't accidentally invert.
- **B.3 dedup boundary** (CRIT-5 from Round 1) — B.3 sets `node_id=parent_node_id` to dedup-distinguish from A.4's `node_id=None`. Subtle; easy to miss.
- **Sub-segment C ordering**: extend PlanEntry first, run the parity test, watch it pass, THEN write the analyzer side. If you write the analyzer first and the parity test is failing for unrelated reasons, you'll thrash.
- **The trace 2.1.0 walker (`_iter_llm_events`) is genuinely new code** — no existing walker matches the requirement (recurse + include cached). Test it independently before consuming it from `_emit_discrepancy_diagnostics`.
- **Cost computations for unpriced models** — every detection has a `savings_usd is None` skip path (D10 default). Don't skip this; emitting `$0.00` for unpriced models violates the tri-state contract Segment 4's review-silent-failures C1 fix established.

## For the next agent — start here

1. **Read `recommendations-section-plan.md` end-to-end.** It's 700+ lines. Don't skim.
2. **Read this file (you're doing it).**
3. **Check that `make test` is green on a fresh checkout.** 5920 tests should pass before you touch anything. If any fail, the segment-1-through-cost-wiring landings have drifted; surface to user.
4. **Run the verification greps from "What to verify before you write any code" above.** ~15 minutes. Surface any drift to the user before encoding.
5. **Pick a sub-segment.** A → B → C is the recommended UX order; A.1 is the easiest entry point. The plan's TDD-per-detection discipline applies: write a per-id emission fixture FIRST (with dotted-path coverage), watch it fail, implement, watch it pass.
6. **One commit per sub-segment.** Don't bundle. The drift-tests + lint + mypy + golden hash baseline must pass at each commit boundary.
7. **After each sub-segment, surface to the user.** Optionally run `/code-review` against staged changes (7 agents, no `review-plan`). Triage Critical/High via grep before encoding fixes.

## Don't bother with

- Re-running plan-stage review. Round 2 found Round-1's bugs; Round 3 found Round-2's. The architectural framing is settled. Code-review against staged changes per sub-phase is the right surface from here.
- Adding more entries to the warning catalog. 12 entries, locked per DD#29. Surface to user if a new ID is wanted.
- Re-debating sub-segment dependencies. A/B/C are independent. UX order is recommended; user can reorder if any sub-segment blocks.
- Predicting cache_keys outside the planner. The Round-1/Round-2 graveyard is right there. Use `build_plan`. Read `entry.cache_key`.

## Relevant files

**Plan + handoff (read first):**
- `.taskmaster/tasks/task_159/implementation/recommendations-section-plan.md` — the plan you'll execute.
- `.taskmaster/tasks/task_159/implementation/recommendations-section-handoff.md` — this file.

**Background (read if needed):**
- `.taskmaster/tasks/task_159/task-159.md` — the spec. Sections of interest: mode-1 example (lines 332-472), mode-4 example (lines 485-493), `cache.discrepancy` warning JSON shape (lines 580-606), out-of-scope (lines 810-828).
- `.taskmaster/tasks/task_159/implementation/implementation-plan.md` — the v1 plan. F1 catalog rows + F2 composition spec.
- `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md` — segments 1-4 + cost wiring progress + tacit knowledge.
- `.taskmaster/tasks/task_159/starting-context/agent-handoff.md` — operational context from Task 159's plan-writing era.

**Don't read** (use pflow-codebase-searcher if you need the journey):
- `.taskmaster/tasks/task_159/implementation/progress-log.md` — the planning journey. Long. Use a subagent to extract specific decisions.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm by summarizing: (a) the architectural decision for sub-segment C and why Round-1 was wrong, (b) which 3 verifications you'll run before encoding, (c) the user's load-bearing principle that should guide every fork. Then state you're ready to proceed.
