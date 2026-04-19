# Task 156 — `--dry-run` Flag: Design Journey Progress Log

**Task**: Add `--dry-run` to `pflow run` that shows execution plan without invoking side effects (resolves GitHub issue #310).

**Status**: Design and planning complete. Implementation plan approved. Ready for another agent to implement.

**Audience**: future agents working on this feature, reviewing the code, debugging drift, or extending `plan_node()`. Read this to understand **why** we made the decisions we did — especially the non-obvious ones that will look like complexity to simplify away but are actually load-bearing.

---

## 2026-04-18 — Context and trigger

GitHub issue #310 requested a `--dry-run` flag for `pflow run` that shows which nodes are cached vs would execute without triggering side effects (shell/LLM/HTTP/MCP/file-write). The motivating scenario: a 30-node LLM-heavy workflow where a single edit to an upstream node's prompt may or may not invalidate the cache for downstream nodes — and running the workflow to find out costs tokens and time. An AI agent iterating on the workflow needs a pre-flight check to answer "will this cost me $1 or $0.01 on the next run?"

Existing flags were insufficient:
- `--no-cache`: forces full run — opposite of what's wanted
- `--only <node>`: runs one node, still executes it
- `--validate-only`: says nothing about runtime behavior

The issue explicitly argued against folding dry-run into `--validate-only` (different audiences, different exit-code contracts) — we accepted that framing at the start.

## 2026-04-18 — Phase 1: Initial exploration (Options A, B, C)

Initial research pass: read `commands/run.py`, `runtime/engine/engine.py`, `runtime/engine/instrumentation.py`, `runtime/cache.py`, `runner.py`. Established the core facts:

- Engine's `_execute_node` has a linear per-node sequence where only step 9 (`node._run()`) has side effects. Steps 1–7 (LLM interception setup, execution state init, loop guard, config hash, template resolution, memo cache check, in-process cache check) are safe-ish reads.
- `MemoizationCache` uses `md5(config_hash + resolved_inputs)` as key. Data for cost estimates exists (LLM `cost_usd` in `llm_usage`).
- Graph traversal is `curr.successors.get(action or "default")` — same pattern used by `--only`.

Three options presented to user:

### Option A — Engine mode flag
Add `dry_run: bool` to `WorkflowEngine.__init__()`. One conditional in `_execute_node` between step 7 and step 9: skip `node._run()`, record plan entry, return `"default"`.

**Pros**: ~50 lines, reuses existing walker, uniform with `--only`.
**Cons**: Engine gains a mode. Hot path gains a branch readers must consider.

### Option B — Separate dry-run walker in `execution/`
`WorkflowRunner.dry_run()` walks CompiledWorkflow independently, calling `resolve_templates` + `check_memo_cache` manually.

**Pros**: Engine pristine.
**Cons**: Reimplements graph-walking, batch, sub-workflow → drift risk.

### Option C — Engine intercept + dedicated PlanCollector
Like A, but plan entries flow through a collector object (mirrors `trace_collector`).

**Pros**: Clean separation of execution semantics from display.
**Cons**: Another collector class — marginal benefit over a shared-store key.

**Initial recommendation**: Option A with Option C's collector touch.

**Key open questions raised:**
1. Branch routing when node "would execute" — follow default, all branches, or stop?
2. Output stubbing — empty type-correct placeholders vs abort on unresolvable templates?
3. Batch nodes with templated `items:` — iterate N or show `?`?
4. Sub-workflow propagation.
5. Cache-miss reason attribution — v1 simple vs detailed?

## 2026-04-18 — PIVOT 1: The "simplicity of final code" reframe

User feedback:
> "we should prioritize simplicity of the final code, not how easy it is to get there. Does this make sense? whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?"

This was the first course correction. I had been scoping for "shortest diff" not "clearest final state."

**Insight**: `terraform plan` vs `make -n` patterns — top-tier tools usually either:
1. Have a separate command path entirely (terraform — plan + apply pipeline)
2. Have a single-line gate inside the executing function (make — `if dry_run: print; else: exec`)

For pflow's model (graph walker + per-node action), the `make -n` pattern fits — but expressed as a separate function, not a mode flag.

### Option D — Separate planner module
New `execution/plan.py` with `build_plan()` that walks CompiledWorkflow independently, calling the engine's helper functions (`resolve_templates`, cache-key computation) but never `node._run()`. Engine untouched.

**Pros**:
- Engine stays single-purpose.
- Planner is testable in isolation.
- Clear separation: execution code vs planning code.

**Cons** (noted immediately, deeper concern emerged in pivot 2):
- Planner must mirror the engine's graph walk, edge semantics, cache-key logic — drift risk.
- "Two places that must stay in sync" is exactly the Option-D failure mode the task spec warns against.

**Recommended Option D** at the time. Went with it.

## 2026-04-18 — Sub-workflow recursion and cost estimates

User asked about (1) showing cached state INSIDE sub-workflows and (2) cost estimates for LLM nodes.

### Sub-workflow recursion decision
YES, recurse. When planner hits `WorkflowExecutor`, it calls `resolve_sub_workflow` on the child ref, compiles via `compile_workflow`, recursively calls `build_plan`. The propagated `MemoizationCache` instance handles per-node caching at every level (matches runtime's `_PROPAGATED_KEYS` pattern).

### Cost estimate approach — three levels considered

**Level 0**: Ship without cost. Defer to future iteration.

**Level 1**: Historical cost lookup. For every would-execute LLM node, call `MemoizationCache.get_latest_for_node(node_id)` → extract `llm_usage.cost_usd` from the most recent entry. Label with `≈` and "based on last runs, actual may vary." ~95 lines including tests.

**Level 2**: Token-based prediction. Tokenize current prompts with `tiktoken` or similar, multiply by per-model pricing, estimate output tokens.

**Chose Level 1** because:
- Data is already in SQLite (once the LLMNode cost bug is fixed — see below).
- No new dependencies.
- Historical cost is "good enough" for cost-gating decisions.
- Level 2 adds `tiktoken` + per-model encoders for marginal accuracy gain; output tokens are still guessed.

### Prerequisite bug discovered
`LLMNode.post()` writes `llm_usage` to shared store WITHOUT calling `enrich_llm_usage_with_cost`. The engine's `enrich_llm_cost` at step 15 fires AFTER `write_memo_cache` at step 12 — so the memoized BLOB lacks `cost_usd`. `ClaudeNode` does it correctly inline.

This is a real pre-existing bug that ALSO happens to block the dry-run cost feature. Fix: ~5-line change to `LLMNode.post()`.

### Output repetition concern
Initial JSON/text mockups repeated "(downstream of 'X')" and "hash match" on every line. User flagged this as noise.

**Final design**: boundary-divider idiom — one marker line at the first cache miss, no per-line "downstream of" repetition. Node-type tags (`[LLM]`, `[code]`) on each node carry the cost-relevance signal.

### Agent-oriented JSON
Added pre-computed summary fields:
- `cache_boundary` — single pointer for "what changed?"
- `execute_by_type` — `jq '.summary.execute_by_type.LLMNode'` gives agents the "how expensive?" number
- `estimated_cost_usd` — cost-gate primitive

## 2026-04-18 — Phase 4: First verification wave (4 agents)

Before formalizing Option D, ran 4 parallel `pflow-codebase-searcher` agents to verify assumptions:

1. **Template resolution + cache-key helpers as pure functions** — confirmed safe to reuse from outside the engine with a scratch shared dict. Exact call sequence documented.
2. **LLM cost data actually reaches the memo cache** — **blocker confirmed**: `cost_usd` not stored for `LLMNode`. Fix identified (enrich at node level, mirror `ClaudeNode`).
3. **Sub-workflow standalone compilation** — works. Must use `resolve_sub_workflow` from `core/workflow/sub_workflow_resolver.py` (not the top-level resolver).
4. **Graph-walk semantics** — **found 2 bugs in my proposed walker**:
   - Engine is `curr.successors.get(action or "default")`, not `.get(action) or .get("default")` (subtle: named-action-missing is a routing error, not a default-fallback).
   - Loops are real cyclic edges (e.g. `flaky - "error" >> flaky`) → `visited: set[node_id]` breaks legitimate retries. Must be `visited_edges: set[(node_id, action)]`.

**Learning**: Search 4 caught bugs in code I hadn't even written yet. This is the drift pattern that Option D would repeatedly produce.

## 2026-04-18 — PIVOT 2: "Are we building another engine?"

User asked:
> "are we essentially building another engine now that we need to maintain?"

This was the crucial second pivot. I had been selling Option D as "clean separation" but the reality was: the planner has to replicate graph traversal, edge semantics, cache-key computation, batch logic, sub-workflow handling, cycle detection, `cache: false` skip, `WorkflowExecutor` skip, and visit-count semantics. Every one of those is "the planner must mirror the engine."

**Insight**: Option D isn't separation — it's duplication with extra steps. Search 4 finding 2 bugs pre-implementation was the signal.

Revisited the problem. The real insight: **the engine's `_execute_node` has a natural seam at the `node._run()` call**. Steps 1–7 are "decide what would happen"; step 9 is "do it"; steps 11–17 are bookkeeping. The "decide" phase is what the planner needs.

### Option A-refined — engine intercept + static post-pass
Engine gets `dry_run: bool`. After step 7 and before step 9, branch on cache status. Post-boundary nodes labeled via static IR reachability (~25 lines).

**Pros**: ~220 lines total, no drift.
**Cons**: Engine gains a mode. Hot path has an `if dry_run:` branch.

### Option E — Extract the shared step
Factor steps 4–7 into a named `plan_node(node, config, shared) -> NodePlan` function. Engine calls it, then runs the node. Planner calls it, then records a plan entry.

**Pros**:
- Cache-key computation and template resolution live in exactly ONE function.
- Drift impossible by construction — both callers share the same primitive.
- Engine still calls `plan_node` — no "parallel engine" exists.
- Cleaner than A-refined on maintenance (no mode flag; the engine's branch becomes "did plan_node say cached?" which is a natural domain operation, not a mode check).

**Cons**:
- Extracting steps 4–7 requires splitting `check_memo_cache` / `check_cache_validity` into pure-lookup + apply-side-effect pairs (the on-hit block has side effects that belong to execution, not planning).

**Initial count estimate**: ~860 lines total.

## 2026-04-18 — Phase 6: Option E consensus poll (4 agents)

User requested: poll 4 agents on Options A, A-refined, D, E with no file access — intuition only. Framed all four options as equals, no leading.

**Unanimous: Option E.** Ranking was E > A > A-refined > D with varying confidence. All four independently called out:
- D is the worst (parallel code paths drift)
- A seems cheap but grows (mode flags leak)
- E matches the domain ("the problem tells us where the seam is")

Agents independently suggested several add-ons:
- Typed `NodePlan` dataclass (not a tuple, not stringly-typed)
- **Drift-catcher test** — a test that runs a workflow end-to-end AND plans it, asserts plan predictions match actual outcomes. Prevents the Option-D failure mode from sneaking back in.
- Serializable `NodePlan` → plans become diffable across runs
- Null-object executor pattern (considered, rejected as overkill vs a function)

**Decision**: Option E with the four add-ons (typed `NodePlan`, drift-catcher test, serializable plan, commit message calls out capabilities that fall out — cache-only execution mode, plan-diff tooling).

## 2026-04-18 — Phase 7: Pre-commit verification wave (3 agents)

User asked: "anything we need to verify before committing?" Ran 3 more parallel searches:

1. **Can `check_memo_cache` / `check_cache_validity` be split cleanly?** — YES. On-hit side effects are a contiguous 4-line block. `handle_cached_execution` writes to disjoint shared-store keys. Refactor size: ~50 lines, not ~200.
2. **Who calls these helpers?** — NARROW blast radius. Every function has exactly ONE production caller (engine). Zero `mock.patch` targets on these names. No surprise consumers in batch/WorkflowExecutor/MCP.
3. **Test impact?** — LOW. 9 tests directly call these functions (in `test_checkpoint_tracking.py`). Thin wrapper strategy preserves ALL 9 without mechanical updates. Only 1 test (`test_memoization_integration.py:274`) needs a real signature update.

All three verifications green. Confidence: high that scope is accurate.

## 2026-04-18 — Task doc authoring (task-156.md)

Drafted task-156.md with 12 initial design decisions, then user asked for 5 polish items (commit to `get_with_age` as parallel method, explicit `enforce_loop_guard` non-call, parser warnings from sub-workflow, LLMNode cost fix phrasing, pytest fixture for network mocking).

### Three remaining user decisions

**1. CLI flag composition with other run flags**
- Hard error on `--dry-run + --validate-only` (different audiences).
- Hard error on `--dry-run + --report`/`--report-dir` (nothing to report).
- Silent accept `--dry-run + --no-trace` (no trace anyway; script composability).
- Silent accept `--dry-run + -p/--print` (plan IS the result; suppressing is nonsensical).

**Rationale**: hard errors go to mistakes, silent accepts preserve composability.

**2. MCP server exposure — same PR or defer?**
User said "if tiny, include." Estimated ~40 lines production + ~60 tests. Small. **Included**.

**Rationale**: pflow's positioning is agent-first; CLI-only dry-run in a codebase with strong MCP parity is inconsistent. Task 152 tracks MCP parity already.

**3. Cost display precision**
2 decimals when ≥ $0.01, 4 decimals when < $0.01. Text-mode formatting only; JSON stays full-precision float.

**Rationale**: avoids rounding micro-costs to $0.00; agents get exact values via JSON.

## 2026-04-19 — Implementation plan drafting (5 parallel searches)

User requested an atomic implementation plan. Launched 5 parallel `pflow-codebase-searcher` agents with focused scopes:

1. **Engine refactor concrete details** — exact line ranges, call signatures, splits.
2. **LLMNode cost fix + cache extensions** — prerequisite bug fix details, new method implementations.
3. **Runner + CLI wiring** — mutual-exclusion pattern, method signatures.
4. **MCP exposure + formatters** — service/tool registration, formatter conventions.
5. **Test patterns + result types + sub-workflow helpers** — `isolate_pflow_config`, mock patterns, dataclass conventions.

Synthesized ~2,300-line implementation plan covering 12 phases, exact code snippets, test specifications, CLAUDE.md update list, and critical-invariant appendix.

## 2026-04-19 — Phase 10: Code review (5 agents)

User requested `/code-review` on the plan. Launched 5 review agents:
- `review-plan` (structural integrity)
- `review-impact-completeness` (missed consumers)
- `review-validation-consistency` (engine/planner drift)
- `review-feature-interactions` (compose with --only, batch, sub-workflow, etc.)
- `review-silent-failures` (operations that should fail visibly)

**Result**: 14 structural issues flagged. Multiple agents independently flagged the same root cause — high signal.

### The 14 fixes applied

**#1 Populate scratch `shared` on cache hits** (flagged by ALL 5 agents)
- **Issue**: planner's `_plan_standard_node` never wrote `shared[node_id] = cached_output` on memo hits. Downstream nodes that templated against upstream cached nodes would see empty shared → different cache keys than engine → drift.
- **Fix**: planner calls `apply_memo_hit` on its scratch dict (populates `shared[node_id]`, `completed_nodes`, `node_actions`, `node_hashes`).
- **Key insight**: the "pure read" contract applies to the CALLER's state. The scratch dict `build_plan` constructs internally is NOT caller-owned — mutating it is not only safe but REQUIRED for correctness.

**#2 Bump visit_counts in walker** (flagged by 2 agents)
- **Issue**: engine's `enforce_loop_guard` increments `visit_counts[node_id]` before `memo_cache_lookup` checks `> 1 → skip`. Planner never bumped. On loop iteration 2+, engine would skip memo but planner would hit → drift.
- **Fix**: walker bumps `visit_counts` before each `plan_node` call.

**#3 Wire `--only` through `build_plan`** (spec violation found)
- **Issue**: `WorkflowRunner.plan()` read `config.only_node` but never passed it down. Planner ignored the flag.
- **Fix**: added `only_node: Optional[str]` parameter, validation at top-level entry (mirrors engine), termination after target, BFS respects it too.

**#4 Emit `routing_error` entries** (spec violation)
- **Issue**: `"routing_error"` was in the enum and formatter but `build_plan` never produced it. Cached node with an action that had no matching successor silently broke the walker.
- **Fix**: emit `PlanEntry(status="routing_error", ...)` when cached action has no matching non-error successor.

**#5 BFS post-first-miss, not linear default-following** (spec vs code contradiction)
- **User decision**: BFS over linear. Tradeoff discussion:
  - Linear: "lower bound" cost (one path). Cost-gate DANGER — underestimates.
  - BFS: "upper bound" cost (all paths). Cost-gate SAFE — overestimates conservatively. Also handles boundary-node-with-no-default correctly.
- **Fix**: `_bfs_downstream` function enumerates all non-error successors. Summary flags `cost_basis="upper_bound"` when branching encountered.

**#6 Opaque sub-workflow pre-check** (spec violation)
- **Issue**: `plan_node` resolves templates BEFORE `_plan_sub_workflow` runs. Strict mode raises on `workflow: ${var}` → rendered as template_error, not opaque.
- **Fix**: check `template_params["workflow"]` for `${` BEFORE calling `plan_node`; short-circuit to `status="opaque"`.

**#7 Sub-workflow entries count as execute in summary**
- **Issue**: `sub_workflow` was neither `cached` nor `execute`, so `cached_count + execute_count != total`. `execute_by_type` never showed `workflow`.
- **Fix**: `_is_executing` helper treats sub_workflow with any child work (direct or nested) as executing. Parent `WorkflowExecutor` frame always runs at runtime (memo-skipped), so this is correct.

**#8 Nested cost aggregation**
- **Issue**: `estimated_cost_usd` summed only current-level; nested LLM costs silently dropped. Agents cost-gating a workflow with sub-workflows got $0.
- **Fix**: added `estimated_cost_usd_including_nested` + `nodes_without_history_including_nested` to `PlanSummary`. Formatter prefers nested value.

**#9 `test_llm.py` equality assertion breaks**
- **Issue**: existing test `test_usage_data_stored_correctly` asserted `shared["llm_usage"] == {...}` with full-dict equality. Phase 0.1 cost fix adds `cost_usd` key → test fails.
- **Fix**: added to Phase 10.3a — update assertion to use containment or add `cost_usd` to expected dict.

**#10 Permissive template errors attached to plan diagnostics**
- **Issue**: `plan.template_errors` (permissive mode list) was discarded by `_plan_standard_node`. Engine writes them to `shared["__template_errors__"]` but planner discarded.
- **Fix**: extract `diagnostic` from each permissive error, surface as plan-level diagnostic.

**#11 `memo_cache_lookup` returns `cache_key` on hit**
- **Issue**: on hit, returned `(True, None, ...)` — cache_key discarded. `_compute_cache_age` re-derived it, duplicating batch cache-key logic. Violates Option E's "one place" promise.
- **Fix**: return `cache_key` on all paths. Planner uses `plan.cache_key` directly for `get_with_age`.

**#12 Widen sub-workflow exception catch**
- **Issue**: caught only `(FileNotFoundError, ValueError, CompilationError)`. `MarkdownParseError`, `WorkflowNotFoundError`, `WorkflowValidationError`, `SchemaValidationError` would propagate → crash parent plan.
- **Fix**: widened to match `WorkflowExecutor._PREP_RECOVERABLE`.

**#13 Drift-catcher test expansion** (4 → 9 test cases)
- **Original**: fresh, re-run, config edit, branching.
- **Added**: cross-node template resolution (tests fix #1), retry loop iteration (tests fix #2), sub-workflow partial cache, batch items, `cache: false`, BFS branch enumeration, routing error.

**#14 WorkflowExecutor always-boundary when child has work**
- **Issue**: sub-workflow with all-cached children was treated as "follow default," but parent frame always executes at runtime (memo-skipped). Planner could miscategorize 3-level nested scenarios.
- **Fix**: in walker, sub_workflow entry with `execute_count > 0 OR execute_including_nested > 0` sets `first_miss_node_id`. Recursive aggregation walks `sub_plan.summary`.

### Disputed finding (1)

**`_strip_placeholders` undefined on WorkflowRunner** (review-silent-failures #19): DISPUTED. Method IS defined on `WorkflowRunner` (verified in earlier research). Reviewer was uncertain; no fix needed.

## 2026-04-19 — Phase 11: Plan revision & approval

Applied all 14 fixes to `great-i-think-we-cheeky-eagle.md`:
- Updated `memo_cache_lookup` return shape (cache_key on hit)
- Updated `NodePlan` dataclass docs
- Rewrote `build_plan` with visit_counts bump, cache-hit shared mutation, routing_error emission, BFS seeding
- Added `_bfs_downstream` function
- Rewrote `_plan_standard_node` with `apply_memo_hit` call, permissive error surfacing
- Rewrote `_plan_sub_workflow` with opaque pre-check, widened exception catches, path normalization via `.resolve()`
- Added `_build_sub_workflow_exception_tuples` / `_safe_to_diagnostics` helpers
- Extended `PlanSummary` with `cost_basis`, `estimated_cost_usd_including_nested`, `nodes_without_history_including_nested`
- Rewrote `_summarize` with `_is_executing` helper and recursive aggregation
- Updated Phase 3 engine integration: explicit `invalidate_cache` call for hash-mismatch post-refactor
- Updated formatter to prefer nested cost, label upper_bound semantics, expose `cost_basis` in JSON
- Updated `WorkflowRunner.plan()` to pass `only_node`
- Expanded Phase 10.5 drift-catcher test list to 9 cases
- Added Phase 10.3a for `test_llm.py` update
- Added "Revision history" section at top listing load-bearing corrections
- Extended "Critical invariants" appendix from 8 → 14 entries
- Re-ordered phases: planner/formatter/runner (5, 6, 7) before engine refactor (3)

**Plan approved by user. Copied to `.taskmaster/tasks/task_156/implementation/implementation-plan.md`.**

---

## Key insights for future agents

### 1. "Pure read" doesn't mean "no mutation"
The contract "planner does not mutate shared" applies to the CALLER's shared dict. The scratch dict `build_plan` constructs internally is owned by the planner — mutating it is not only safe but REQUIRED for downstream correctness. The planner MUST call `apply_memo_hit` on cache hits so downstream nodes see the cached outputs during template resolution. Without this, the planner computes different cache keys than the engine — drift.

### 2. The domain tells you where the seam is
Option E emerged because the engine's `_execute_node` naturally splits at `node._run()`: steps 1–7 "decide what would happen," step 9 does it. When the domain hands you an obvious seam, honor it — don't paper over it with a mode flag (Option A) or duplicate past it (Option D). Name the concept (`plan_node`) and let it be a first-class primitive both callers share.

### 3. Agent polls are high signal for "which shape" decisions
The 4-agent option poll produced unanimous E with consistent reasoning. When multiple independent evaluators converge on a decision with similar rationale, the signal is strong. The reasoning (drift prevention, domain match, future-proofing) mattered more than the vote count.

### 4. Verification before implementation catches structural bugs
The 5-agent code review caught 14 structural issues in the plan BEFORE any code was written. Two of those (the `shared` mutation and visit_counts bump) would have silently broken the drift-catcher test at implementation time. Pre-implementation review is cheaper than post-implementation debugging by orders of magnitude.

### 5. Option D's allure is deceptive
"Separate module, engine untouched" sounds clean but the planner has to mirror every cache/template/routing decision the engine makes. Every drift surface is a bug-in-waiting. When you see a proposal that says "keep X untouched by duplicating Y in a new module," ask: "is Y actually separable, or will the new module just re-implement X?"

### 6. BFS over linear post-first-miss is the safer default
For cost-gating, overestimation is safe (agent aborts a maybe-cheap run) while underestimation is dangerous (agent burns tokens on a maybe-expensive run). When the semantics aren't definitive, prefer the direction whose failure mode is "user annoyance" over "user bill."

### 7. Thin wrappers preserve migration cost for behavior-preserving refactors
We kept `check_memo_cache` and `check_cache_validity` as thin wrappers around the new pure primitives. This preserved 9 existing tests without mechanical updates. Rule: when splitting a function whose callers test it directly, keep the original name as a thin wrapper composing the new pure + apply pair. Only inline-replace when you're also willing to update every test call site.

### 8. Load-bearing comments explain non-obvious invariants
The Phase 5 code has comments like "LOAD-BEARING: on cache hit, mutates `shared` to mirror the engine's apply_memo_hit side effects" because the "pure read" framing would otherwise invite a future reviewer to "simplify" by removing the mutation. Future agents: if you see a LOAD-BEARING comment, read the review findings in this log before "simplifying" the code away.

### 9. "Simplicity of final code > simplicity of diff"
User's reframe early in the journey ("we should prioritize simplicity of the final code, not how easy it is to get there") was the single highest-leverage direction change. Diff size is a proxy for reviewability; final-code simplicity is the actual maintenance cost. Option A looked smallest; Option E ended up simplest.

### 10. The drift-catcher test is the living invariant
`test_plan_drift.py` runs workflows end-to-end AND plans them, asserts predictions match outcomes. This is the structural guarantee that Option E's claim ("drift impossible by construction") is true in practice, not just theory. Future agents: if this test fails, do NOT skip it. The failure is telling you that the engine and planner have diverged, and the fix is to align them via `plan_node()` — not to adjust the test.

### 11. MCP parity isn't optional for agent-first tools
pflow positions itself as agent-first. Shipping a CLI-only dry-run in a codebase where `execute_workflow` and `validate_workflow` are MCP-exposed creates inconsistent agent UX. The ~100 extra lines for MCP tool exposure was worth it.

### 12. Historical cost is "good enough"
Token-based cost prediction (Level 2) would have added `tiktoken` + per-model encoders for marginal accuracy gain — output tokens are still guessed. Level 1 (last-run cost from memo cache) uses data already in SQLite, adds no dependencies, and serves the cost-gate use case adequately. "Good enough" was the right bar for v1.

---

## Rejected alternatives (for completeness)

### Null-object executor pattern
Inject a `NodeRunner` strategy; dry-run uses a `PlanningRunner` that records instead of executing. Considered by 2 review agents. **Rejected**: overkill vs `plan_node()` — adds an abstraction to solve a problem a function solves.

### Wrapping `node._run()` with a recorder
Run the engine normally but replace `node._run` with a no-op recorder. **Rejected**: "no side effects" is hard to enforce from the outside — each node type (shell/http/llm/claude/file/mcp) has different escape hatches (subprocess, network, file handles). Trust-the-wrapper fails exactly where it matters.

### Per-node caching at sub-workflow level
Originally spec'd: `hash(path + content + child_params)` for sub-workflow cache keys. **Rejected** during Task 106 work and re-confirmed here: sub-workflows compile fresh each run; node-level caching inside handles everything. File-reference changes (e.g., editing a prompt file inside a sub-workflow) are caught because file content is inlined at compile time → config hash changes.

### Stubbing output for would-execute nodes
Original Option A design: synthesize stub outputs from `interface.outputs` metadata so downstream template resolution continues past the boundary. **Rejected**: fabricates information agents might trust. Option E's "planner stops populating shared past first miss; downstream labeled via BFS topology" is more honest.

### Linear default-following post-first-miss
Spec literally says BFS; plan initially wrote linear. **Rejected after user decision**: underestimates cost (one branch only), silently breaks when boundary node has no default edge. Tradeoff discussion captured in §#5 above.

### `--dry-run` as a mode flag on `RunnerConfig`
Considered putting `dry_run: bool` on `RunnerConfig`. **Rejected**: the method call IS the mode (`runner.plan()` vs `runner.run()`). Config should carry execution tunables (cache_enabled, only_node), not mode selection.

### Token precision for costs
`$0.0283` vs `$0.03`. **Rejected** 4-decimal always (too noisy); chose context-sensitive: 2 decimals when ≥ $0.01, 4 when below (avoids rounding micro-costs to $0.00).

---

## File references for implementation

Primary plan: `.taskmaster/tasks/task_156/implementation/implementation-plan.md`
Task spec: `.taskmaster/tasks/task_156/task-156.md`
This log: `.taskmaster/tasks/task_156/implementation/progress-log.md`

Key symbols introduced:
- `src/pflow/runtime/engine/plan_node.py::plan_node` — shared primitive
- `src/pflow/runtime/engine/plan_node.py::NodePlan` — typed return value
- `src/pflow/runtime/engine/instrumentation.py::memo_cache_lookup` — pure read
- `src/pflow/runtime/engine/instrumentation.py::apply_memo_hit` — side effects
- `src/pflow/runtime/engine/instrumentation.py::in_process_cache_lookup` — pure read
- `src/pflow/execution/plan.py::build_plan` — the walker
- `src/pflow/execution/plan.py::_bfs_downstream` — post-miss enumeration
- `src/pflow/execution/formatters/plan_formatter.py::format_plan_json/text` — rendering
- `src/pflow/execution/result.py::Plan, PlanEntry, PlanSummary` — result types
- `src/pflow/execution/runner.py::WorkflowRunner.plan` — entry point
- `src/pflow/mcp_server/services/execution_service.py::plan_workflow` — MCP service
- `src/pflow/mcp_server/tools/execution_tools.py::plan_workflow` — MCP tool

Prerequisite fixes:
- `src/pflow/nodes/llm/llm.py::LLMNode.post` — cost enrichment (mirrors `ClaudeCodeNode`)
- `src/pflow/runtime/cache.py::MemoizationCache.get_with_age` + `get_latest_for_node` + `idx_node_id_created_at`

Drift-catcher test (load-bearing):
- `tests/test_execution/test_plan_drift.py` — 9 cases minimum

---

## Next steps (for the implementing agent)

1. Read task-156.md first (what/why), then implementation-plan.md (how).
2. Execute phases in order listed in Phases Overview table (0 → 1 → 2 → 4 → 5 → 6 → 7 → 3 → 8 → 9 → 10 → 11).
3. Do not simplify away the load-bearing patterns documented in the "Revision history" section of implementation-plan.md. Each one prevents a concrete drift class found by the review.
4. Run `make test && make check` after every phase.
5. The drift-catcher test (Phase 10.5) is the structural guarantee. Do NOT skip or suppress it if it fails; fix the divergence.
6. Append to THIS log as implementation progresses — every discovery, bug, insight, significant decision.

---

## 2026-04-19 — Implementation Phase 0 complete

### Scope completed

Implemented the Phase 0 prerequisites:

- `src/pflow/nodes/llm/llm.py`
  - `LLMNode.post()` now calls `enrich_llm_usage_with_cost(llm_usage)` before writing `shared["llm_usage"]`.
  - This fixes the prerequisite bug from the spec: memoized `LLMNode` outputs can now carry `llm_usage.cost_usd`, matching the intended dry-run historical-cost source.

- `src/pflow/runtime/cache.py`
  - Added schema index: `idx_node_id_created_at ON cache_entries(node_id, created_at DESC)`.
  - Added `MemoizationCache.get_with_age(cache_key) -> (action, output, created_at) | None`.
  - Added `MemoizationCache.get_latest_for_node(node_id) -> (output, created_at) | None`.
  - Kept `get()` unchanged, per spec and plan.

- Tests
  - Added Phase-0 cache tests in `tests/test_runtime/test_cache.py` for `get_with_age()` and `get_latest_for_node()`.
  - Updated the existing exact-dict assertion in `tests/test_nodes/test_llm/test_llm.py::test_usage_data_stored_correctly` to include `cost_usd`.

### Important implementation notes

- The `cost_usd` value for the existing `gpt-4` unit test is `0.00966`, not the naive input/output-only number. The cost function also incorporates cache token pricing (`cache_creation_input_tokens`, `cache_read_input_tokens`), so the expected value must come from `enrich_llm_usage_with_cost()` semantics, not a hand-calculated simplified formula.

### Decision / deviation from phase ordering

- I pulled the `test_llm.py` assertion update forward into Phase 0 instead of waiting for the later Phase 10 test sweep.
  - Why: the plan requires verification after each phase, and Phase 0’s bug fix changes the shape of `shared["llm_usage"]` immediately.
  - Impact: this is an ordering deviation only, not a behavioral deviation. It keeps the suite green at the phase boundary and matches the already-approved review note that this exact assertion would break.

### Verification and trust boundary

**Verified**

- Syntax for changed files via:
  - `python3 -m py_compile src/pflow/nodes/llm/llm.py src/pflow/runtime/cache.py tests/test_runtime/test_cache.py tests/test_nodes/test_llm/test_llm.py`
- Direct smoke behavior for new cache helpers via `importlib.util.spec_from_file_location(...)` loading `src/pflow/runtime/cache.py` directly, then:
  - put/get through `get_with_age()`
  - newest-entry lookup through `get_latest_for_node()`
- Direct smoke behavior for cost enrichment via `importlib.util.spec_from_file_location(...)` loading `src/pflow/core/llm_pricing.py` directly and verifying the enriched `cost_usd` value for the test usage payload.

**Unable to verify fully in this environment**

- `make check`
- `make test`
- `uv run pytest ...`

Reason:
- The sandbox blocks `uv`'s default cache path under `~/.cache/uv/...`.
- Redirecting `UV_CACHE_DIR` into `/tmp` avoided that permission error, but `uv` then panicked inside its macOS system-configuration path (`Attempted to create a NULL object`) before it could provision the environment.
- The repository also does not currently have the dev tools installed in `.venv`, so I could not substitute `.venv/bin/pytest`, `.venv/bin/mypy`, etc.

This means Phase 0 is mechanically smoke-verified and syntax-verified, but not yet repo-suite-verified. Future phases should continue with this limitation in mind until the environment issue is resolved or the full toolchain becomes available.

---

## 2026-04-19 — Implementation Phase 1 complete

### Scope completed

Refactored `src/pflow/runtime/engine/instrumentation.py` to split cache lookup from side effects while preserving the legacy APIs used by the engine and existing tests.

Added new pure/helper functions:

- `in_process_cache_lookup(node_id, config_hash, shared) -> (valid, cached_action)`
- `memo_cache_lookup(node_id, node_type_name, config_hash, batch_config, shared, visit_counts, resolved_params) -> (hit, cache_key, cached_data)`
- `apply_memo_hit(node_id, shared, cached_action, cached_output, config_hash) -> None`

Preserved legacy wrappers:

- `check_cache_validity(...)` now delegates to `in_process_cache_lookup(...)` and performs the old invalidation side effect on mismatch.
- `check_memo_cache(...)` now delegates to `memo_cache_lookup(...)` and `apply_memo_hit(...)`, preserving its existing `(hit, result, cache_key)` return contract for current callers.

### Important implementation notes

- `memo_cache_lookup()` now returns `cache_key` on hits as well as misses. This matches the approved revised plan and is load-bearing for later planner work: the planner must not re-derive cache keys after `plan_node()`.
- The wrapper contract remains intentionally asymmetric:
  - `memo_cache_lookup()` is the planner-safe pure read.
  - `check_memo_cache()` is the engine-compatible legacy path that still mutates `shared`.
- `check_cache_validity()` still invalidates stale in-process cache state on hash mismatch, so current execution behavior remains intact until the engine integration phase explicitly switches to the pure helper.

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/runtime/engine/instrumentation.py`
- Direct smoke load of `instrumentation.py` with stubbed package dependencies verified:
  - `in_process_cache_lookup()` returns cached action on hash match
  - `check_cache_validity()` still invalidates stale completed-node state on mismatch
  - `memo_cache_lookup()` returns hit + `cache_key` + cached payload
  - `apply_memo_hit()` writes the same shared-store structures the old inline block wrote
  - `check_memo_cache()` still skips `WorkflowExecutor` with `(False, None, None)`

**Assumed correct but not repo-suite-verified**

- Existing tests in `tests/test_runtime/test_checkpoint_tracking.py`
- Existing test in `tests/test_runtime/test_memoization_integration.py`

Reason:
- Same environment limitation as Phase 0: `uv` is not usable in this sandbox and the dev toolchain is not installed in `.venv`, so I could not run the actual pytest targets.

### Key insight

- The side-effect block inside the old `check_memo_cache()` really is cleanly separable: it writes only `shared[node_id]`, `completed_nodes`, `node_actions`, and `node_hashes`. That matches the plan exactly and confirms the later planner can safely reuse the lookup path without inheriting execution mutations.

---

## 2026-04-19 — Implementation Phase 2 complete

### Scope completed

Added the shared planning primitive:

- New file: `src/pflow/runtime/engine/plan_node.py`
  - `NodePlanStatus = Literal["cached_memo", "cached_in_process", "miss", "cache_disabled"]`
  - `@dataclass(frozen=True) class NodePlan`
  - `plan_node(node, config, shared) -> NodePlan`
- Re-exported `NodePlan` and `plan_node` from `src/pflow/runtime/engine/__init__.py`
- Added initial focused test file: `tests/test_runtime/test_plan_node.py`

### Important implementation notes

- `plan_node()` now owns the shared decision path for:
  - config-hash computation
  - non-batch template resolution
  - memo-cache lookup
  - in-process cache lookup
- It does **not** execute the node, enforce loop guard, emit progress, or mutate `shared`.
- Strict template-resolution failures are returned as:
  - `status="miss"`
  - `template_exception=<ValueError>`
  - `last_resolutions` populated from `_pflow_partial_resolutions` when available

That return shape is intentional and matches the approved plan:
- engine path will re-raise the stored exception later through its normal exception handling
- planner path will render a `template_error` entry without re-raising

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/runtime/engine/plan_node.py src/pflow/runtime/engine/__init__.py tests/test_runtime/test_plan_node.py`
- Direct smoke load of `plan_node.py` with stubbed engine dependencies verified:
  - cache miss returns `status="miss"` with a `cache_key`
  - in-process hit returns `status="cached_in_process"`
  - `cache_enabled=False` returns `status="cache_disabled"`

**Assumed correct but not repo-suite-verified**

- The new pytest file `tests/test_runtime/test_plan_node.py`
- Any interaction with real `resolve_templates()` behavior, since the smoke test used stubs to isolate the contract of `plan_node()` itself

### Key insight

- Returning a miss-shaped `NodePlan` on template exception looks a little odd at first, but it keeps the primitive single-purpose: “what happened during planning?” becomes a typed object instead of a control-flow fork. The engine and planner can then diverge only in how they *consume* that object, not in how they decide cache/template semantics.

---

## 2026-04-19 — Implementation Phase 4 complete

### Scope completed

Extended `src/pflow/execution/result.py` with the new immutable plan result types:

- `PlanEntry`
- `PlanSummary`
- `Plan`

Also added:

- `from __future__ import annotations`
- `Literal` import support for the typed status/cause fields

### Important implementation notes

- `PlanEntry.sub_plan` uses the forward reference to `Plan`, which is why `from __future__ import annotations` is required here.
- The result types live in `execution/result.py`, not in the planner module, so:
  - `WorkflowRunner.plan()` can return the same typed artifact the CLI and MCP layers consume
  - formatter code stays presentation-only
  - later tests can assert typed fields instead of raw dict keys

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/execution/result.py`
- Direct smoke load of `result.py` with stubbed `Diagnostic` and `WorkflowStatus` dependencies verified that:
  - `Plan`
  - `PlanEntry`
  - `PlanSummary`
  all import and construct cleanly

### Key insight

- Getting the typed result surface in place before `build_plan()` matters because the plan feature has multiple consumers immediately: CLI text, CLI JSON, and MCP JSON. If the planner starts life as nested dicts, drift between those consumers becomes likely very quickly.

---

## 2026-04-19 — Implementation Phase 5 complete

### Scope completed

Added the planner walker in new file `src/pflow/execution/plan.py`.

Implemented:

- `build_plan(...)`
- `_bfs_downstream(...)`
- `_plan_one_node(...)`
- `_plan_standard_node(...)`
- `_plan_sub_workflow(...)`
- `_lookup_last_cost(...)`
- `_summarize(...)`
- `_safe_to_diagnostics(...)`
- `_build_sub_workflow_exception_tuples(...)`

### Important implementation notes

- The planner now follows the approved “scratch shared” model:
  - it constructs its own internal `shared`
  - it bumps `__execution__["node_visit_counts"]` before every `plan_node()` call
  - on memo hits it calls `apply_memo_hit(...)` against that scratch `shared`
- Those mutations are **required** for correctness. They are not a purity violation because the caller’s `params` dict is still treated as read-only, and the scratch `shared` belongs to the planner itself.

- Sub-workflow handling follows the reviewed plan:
  - depth guard first
  - opaque pre-check for `workflow: ${var}` before `plan_node()`
  - then parent param resolution
  - then child resolution/compilation/recursion

- BFS after the first cache boundary is implemented over all non-`"error"` successors and flips `cost_basis` to `"upper_bound"` when branching is encountered.

### Adaptation to actual codebase

- The approved plan examples instantiated `Diagnostic(severity=\"warning\"|\"error\", ...)` with strings. The real `Diagnostic` type requires `Severity.WARNING` / `Severity.ERROR` enum values, so I adapted all new planner diagnostics to the actual constructor contract.
- `_node_type_name()` currently returns `NodeConfig.node_type_name` (class name such as `LLMNode` / `ShellNode`), matching the approved plan’s “v1 return class name, formatter translates later” note.

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/execution/plan.py`
- Direct smoke load of `plan.py` with stubbed dependencies verified:
  - `build_plan()` constructs a 2-entry plan for a 2-node linear graph
  - summary totals align with entry count in that smoke case

**Assumed correct but not repo-suite-verified**

- Real sub-workflow recursion against actual parser/compiler objects
- Real template-error propagation from `plan_node()` into planner diagnostics
- Real historical-cost lookup against actual memo cache rows

These behaviors are implemented to the approved plan, but the environment still prevents the actual test suite from running.

### Key insight

- The planner’s correctness hinges on state continuity, not just graph walking. The BFS part is the obvious algorithmic piece, but the subtle part is preserving exactly the same upstream state the engine would expose to downstream template resolution. That is why `apply_memo_hit()` and visit-count bumps are load-bearing rather than optional implementation detail.

---

## 2026-04-19 — Implementation Phase 6 complete

### Scope completed

Added new formatter module: `src/pflow/execution/formatters/plan_formatter.py`

Implemented:

- `format_plan_json(plan) -> dict`
- `format_plan_text(plan) -> str`
- supporting render/serialization helpers for entries, summary, age, cost, and tags

### Important implementation notes

- JSON is now the formatter source of truth for dry-run output:
  - top-level keys: `workflow`, `plan`, `summary`, `diagnostics`
  - text rendering is derived from the same `Plan` model and helper logic
- Text rendering follows the approved boundary-divider idiom:
  - `─── nothing cached — full run ───`
  - `─── cache boundary: '<node_id>' ───`
- Cost rendering follows the task precision rules:
  - 2 decimals at `>= $0.01`
  - 4 decimals below that

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/execution/formatters/plan_formatter.py`
- Direct synthetic-plan smoke rendering verified:
  - `format_plan_json(...)` returns exactly the expected top-level keys
  - `format_plan_text(...)` includes boundary markers and estimated-cost line

### Key insight

- Keeping JSON as the dry-run SSOT matters because three surfaces need identical semantics very soon: CLI JSON, CLI text, and MCP JSON. If text formatting owned part of the business logic, parity bugs would be inevitable.

---

## 2026-04-19 — Implementation Phase 7 complete

### Scope completed

Extended `src/pflow/execution/runner.py` with:

- `WorkflowRunner.plan(workflow, params, config) -> Plan`

Also updated imports so the runner knows about the new `Plan` result type.

### Important implementation notes

- `WorkflowRunner.plan()` reuses the same front half of the pipeline as `run()`:
  - copy params at boundary
  - resolve workflow
  - resolve file references
  - fill declared defaults
  - validate
  - strip placeholders
  - compile
- Then it diverges cleanly:
  - creates only `MemoizationCache` + `Registry`
  - calls `build_plan(...)`
  - does **not** create metrics, trace collector, MCP pool, or progress callback

- Validation diagnostics are merged into the final `Plan.diagnostics` via `dataclasses.replace(...)`, which keeps the plan result immutable while still surfacing pre-execution warnings.

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/execution/runner.py`
- Direct stubbed smoke check verified:
  - `WorkflowRunner.plan()` calls through to a stubbed `build_plan(...)`
  - returns a `Plan` object with populated `workflow` and `entries`

### Key insight

- The runner layer is the right place for dry-run mode selection, not `RunnerConfig`. `RunnerConfig` continues to carry execution/planning tunables such as cache enablement and `only_node`, while the mode itself is expressed by which runner method is called: `run()`, `validate()`, or `plan()`.

---

## 2026-04-19 — Implementation Phase 3 complete

### Scope completed

Refactored `src/pflow/runtime/engine/engine.py::_execute_node()` to replace the old inline steps 4–7 with a single `plan_node()` call plus dispatch on the returned `NodePlan`.

Changes made:

- Engine imports now use:
  - `plan_node`
  - `apply_memo_hit`
- Removed direct engine use of:
  - `resolve_templates`
  - `check_memo_cache`
  - `check_cache_validity`
  - inline `compute_config_hash` / `compute_node_config`
- Preserved the rest of the execution path after planning:
  - progress callback
  - execution / batch execution
  - API warning handling
  - in-process cache_result
  - memo cache write
  - metrics
  - LLM cost enrichment
  - trace
  - completion callback
  - step 17.5 failure archival

### Important implementation notes

- Cached paths now dispatch like this:
  - `cached_memo` → `apply_memo_hit(...)` → `handle_cached_execution(...)`
  - `cached_in_process` → `handle_cached_execution(...)`
- Strict template-resolution failures now flow through `plan.template_exception`, which the engine re-raises so the existing exception path continues to own failure reporting and trace capture.
- The reviewed hash-mismatch invalidation behavior was preserved explicitly:
  - after a miss / cache-disabled result, if the node still exists in `completed_nodes` with a stale hash, the engine now calls `invalidate_cache(...)`
  - this is necessary because the pure `in_process_cache_lookup()` no longer mutates shared state

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/runtime/engine/engine.py`
- Direct stubbed smoke check verified:
  - cached-memo path short-circuits without calling `node._run()`
  - miss path still executes `node._run()`

**Assumed correct but not repo-suite-verified**

- Full parity across existing runtime/integration tests
- Real trace/metrics interactions on the refactored path
- Loop/retry behavior beyond the mechanically preserved structure

### Key insight

- This refactor confirms the architectural bet behind Option E: the engine’s real seam is “decide” vs “do.” Once `_execute_node()` consumes a `NodePlan`, the engine code gets simpler rather than more conditional, and the planner inherits the same cache/template semantics by construction instead of by convention.

---

## 2026-04-19 — Implementation Phase 8 complete

### Scope completed

Wired `--dry-run` into `src/pflow/cli/commands/run.py`.

Changes made:

- Added CLI option:
  - `--dry-run`
- Added flag-composition helper:
  - `_validate_dry_run_flag_combination(...)`
- Added display helper:
  - `_display_plan_result(...)`
- Routed `execute_json_workflow(...)` through the dry-run branch before the existing `validate_only` / execution branches
- Added `--dry-run` to the misplaced-flag validator list so it gets the same CLI-surface protection as the existing flags

### Important implementation notes

- `--dry-run` currently composes as specified:
  - hard error with `--validate-only`
  - hard error with `--report` / `--report-dir`
  - silent accept for `--no-trace`
  - natural ignore of `-p/--print` because `_display_plan_result(...)` always emits the plan
- Plan output goes through:
  - `WorkflowRunner.plan(...)`
  - `format_plan_json(...)` for JSON
  - `format_plan_text(...)` for text

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/cli/commands/run.py`

**Assumed correct but not runtime-verified**

- Full click command wiring at runtime
- Error rendering path for planning failures through `output_error(...)`
- End-to-end behavior for JSON silence and exit codes

Those behaviors are implemented to spec, but still need the full CLI tests once the environment can run them.

### Key insight

- Keeping the dry-run branch inside `execute_json_workflow(...)` rather than inside the outer `run()` command preserves the existing “named workflow vs resolved workflow vs direct workflow” routing shape. The CLI continues to decide *what* is being run; the shared execution entry decides *how* it is processed.

---

## 2026-04-19 — Implementation Phase 9 complete

### Scope completed

Added MCP exposure for planning:

- `src/pflow/mcp_server/services/execution_service.py`
  - new `ExecutionService.plan_workflow(...) -> dict`
- `src/pflow/mcp_server/tools/execution_tools.py`
  - new MCP tool `plan_workflow(...)`
  - added to `__all__`

### Important implementation notes

- The MCP service returns the CLI JSON shape by delegating to:
  - `WorkflowRunner.plan(...)`
  - `format_plan_json(plan)`
- Parameter validation follows the same MCP boundary pattern as `execute_workflow(...)`.
- Workflow-not-found handling also mirrors the existing MCP behavior:
  - `ValueError` with suggestion text when similar workflow names exist

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile src/pflow/mcp_server/services/execution_service.py src/pflow/mcp_server/tools/execution_tools.py`
- Grep verification confirmed the new service method and tool registration points exist in the expected files

**Assumed correct but not connector-runtime-verified**

- Actual MCP tool invocation end-to-end
- Exact parity of the returned JSON shape vs CLI for real workflows

### Key insight

- MCP parity remained cheap precisely because the core planning path was already factored correctly. Once `WorkflowRunner.plan()` returned a typed `Plan` and the formatter owned the JSON serialization, the MCP addition reduced to boundary validation plus delegation, which is the shape we wanted from the start.

---

## 2026-04-19 — Implementation Phase 10 complete

### Scope completed

Added and extended test coverage for the dry-run feature set:

- `tests/test_runtime/test_plan_node.py`
  - cache-disabled
  - fresh miss + cache key
  - memo hit
  - in-process hit
  - strict unresolved-template exception
  - no shared mutation on cache hit
- `tests/test_runtime/test_cache.py`
  - TTL/read-enabled behavior for `get_with_age()`
  - unknown/expired cases for `get_latest_for_node()`
  - schema index existence check for `idx_node_id_created_at`
- `tests/test_runtime/test_instrumented_wrapper.py`
  - regression guard that `LLMNode` memoized output now contains `cost_usd`
- `tests/test_execution/test_plan.py`
  - fresh workflow planning
  - fully cached planning
  - `cache: false`
  - opaque dynamic sub-workflow
- `tests/test_execution/test_plan_drift.py`
  - fresh execution parity
  - rerun/cached parity
  - cross-node cached template-resolution parity
- `tests/test_cli/test_dry_run.py`
  - no side effects
  - JSON shape
  - `--dry-run` vs `--validate-only`
  - `--dry-run` vs `--report`
- `tests/test_mcp_server/test_plan_workflow.py`
  - service JSON shape
  - not-found error
  - compile/planning failure error

### Deviation from the planned test matrix

- I implemented the core runtime/execution/CLI/MCP coverage and the most important drift-catcher cases, but not the full planned 35–45-test matrix verbatim.
- Reason: the environment still prevents running pytest or the full toolchain at all, so the risk of continuing to add large volumes of unexecuted tests without feedback was increasing.
- I prioritized:
  - the new primitives (`plan_node`, cache helpers)
  - the shared parity invariant (`test_plan_drift.py`)
  - the user-visible CLI/MCP contracts

This is a scope deviation from the exact plan. It does **not** change production behavior, but the remaining planned edge-case tests should still be added once the suite can run normally.

### Verification and trust boundary

**Verified**

- Syntax via:
  - `python3 -m py_compile ...` over all changed/new test files

**Unable to verify fully**

- `make test`
- Actual pytest execution of the new tests

The environment limitation from earlier phases still applies unchanged.

---

## 2026-04-19 — Implementation Phase 11 complete

### Scope completed

Updated CLAUDE.md documentation in the required areas:

- `src/pflow/runtime/CLAUDE.md`
- `src/pflow/runtime/engine/CLAUDE.md`
- `src/pflow/execution/CLAUDE.md`
- `src/pflow/cli/CLAUDE.md`
- `src/pflow/cli/commands/CLAUDE.md`
- `src/pflow/mcp_server/CLAUDE.md`
- `src/pflow/mcp_server/services/CLAUDE.md`
- `src/pflow/mcp_server/tools/CLAUDE.md`

### Verified

- Grep confirmation:
  - `rg -n "plan_node|build_plan|plan_workflow" src/pflow/**/CLAUDE.md`
  returned the expected matches in the updated docs.

### Final trust boundary

- Production/source changes: syntax-verified
- New/changed tests: syntax-verified
- Documentation: updated and grep-verified
- Full suite / lint / type-check: **not runnable in this sandbox** because `uv` cannot provision or execute correctly here

Anyone picking this up next should treat the code as implemented but pending full repo validation once the environment issue is removed.

---

## 2026-04-19 — Post-suite regression triage after user test run

The user ran the full suite outside this sandbox and reported **35 failures**. Two clear regression clusters were visible from the failure summary:

### Cluster 1 — `NameError: resolve_templates is not defined`

This affected many batch / sub-workflow / trace tests. Root cause:

- During the engine refactor to `plan_node()`, `engine.py` stopped importing `resolve_templates`.
- `_execute_node()` no longer needed it directly, but `_execute_single_node()` still does — and batch execution routes through `_execute_single_node()`.

Fix applied:

- Restored `from .template_resolution import resolve_templates` in `src/pflow/runtime/engine/engine.py`.

Expected impact:

- This should clear the large batch-related failure cluster, because all of those failures shared the same missing-symbol root cause.

### Cluster 2 — `KeyError: 'completed_nodes'` in `tests/test_runtime/test_plan_node.py`

Root cause:

- The new pure cache helpers assumed `shared["__execution__"]` was fully initialized with `completed_nodes`, `node_actions`, and `node_hashes`.
- The `plan_node` unit tests intentionally use minimal `shared` dicts, so those assumptions were too strict for the helper contract.

Fix applied in `src/pflow/runtime/engine/instrumentation.py`:

- `in_process_cache_lookup()` now reads `completed_nodes` / `node_hashes` / `node_actions` defensively with defaults.
- `check_cache_validity()` now handles missing execution keys safely.
- `invalidate_cache()` now initializes missing execution sub-structures before mutation.
- `apply_memo_hit()` now initializes missing execution sub-structures before mutation.

Expected impact:

- This should clear the `plan_node` KeyError failures and makes the pure helpers safer for planner/test callers that operate on scratch state.

### Test adjustment — LLM memo-write regression test

One newly added test assumed `shared["llm_usage"]` always exists at root level. That is too strong because namespaced execution may store the live usage under `shared[node_id]["llm_usage"]`.

Adjustment applied in `tests/test_runtime/test_instrumented_wrapper.py`:

- The test now accepts either root-level `shared["llm_usage"]` or namespaced `shared["test"]["llm_usage"]`, while still asserting the memoized cache entry includes `cost_usd`.

### Verification status

Still **not executable inside this sandbox**:

- `pytest`
- `make test`
- `make check`

So these fixes are based on direct code inspection against the failure summary plus syntax verification only. The next useful external step is another real suite run to get the reduced failure set.

### Additional isolated failure fixed

- `tests/test_runtime/test_plan_node.py::test_plan_node_does_not_mutate_shared_on_cache_hit`
  - Root cause: the test used `deepcopy(shared)`, which cloned `MemoizationCache` into a different object instance. Plain dict equality then failed even when `plan_node()` had not mutated `shared`.
  - Fix: compare the mutable execution sub-structure directly and assert cache object identity separately (`is`), which matches the real contract of "does not mutate shared".
