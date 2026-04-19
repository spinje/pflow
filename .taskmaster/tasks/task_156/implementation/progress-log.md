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

---

## 2026-04-19 — Post-review hardening: no shortcuts version

User requested two follow-ups before considering the task done:

1. Implement the remaining planned test matrix where it catches real bugs.
2. Remove all `# noqa: C901` shortcuts and prefer simpler final code over easiest diff.

### Refactor completed

`src/pflow/execution/plan.py` was rewritten into smaller helpers so the planner logic is explicit and composable without any `C901` suppressions.

Key simplifications:

- `build_plan()` now delegates:
  - validation of `--only`
  - scratch shared-store creation
  - per-entry diagnostics collection
  - boundary detection
  - routing-error handling
  - downstream BFS expansion
  - pre-boundary successor advancement
- `_bfs_downstream()` now delegates queue seeding, entry creation, and successor enqueueing.
- `_plan_standard_node()` now delegates template-error, cache-disabled, cached-memo, cached-in-process, and miss entry construction.
- `_plan_sub_workflow()` now delegates:
  - depth guard
  - workflow-ref extraction
  - dynamic/opaque handling
  - merged-param building
  - child resolution
  - cycle detection
  - child-input validation
  - child compilation
  - child-warning attachment
- `_summarize()` now delegates base totals, nested totals, execute-by-type, cache-boundary detection, and execution classification.

Result:

- no `# noqa: C901` remain in the planner path
- no remaining `Optional[...]` style annotations in the touched files

### Additional high-value tests added

I stepped back and prioritized tests that protect the actual failure modes of this feature, not coverage for its own sake.

Added because they catch likely real bugs:

- `tests/test_execution/test_plan.py`
  - partial-cache boundary after config edit
  - recursive sub-workflow planning
  - parent `WorkflowExecutor` counted as execute when child has work
  - max-depth guard
  - circular sub-workflow detection
  - loop/visited-edge termination

- `tests/test_execution/test_plan_drift.py`
  - config-edit parity against real execution
  - cached conditional branch parity (planner must follow cached action)
  - sub-workflow partial-cache boundary propagation to parent downstream nodes
  - batch-node cache parity
  - `cache: false` parity
  - BFS branch enumeration / `upper_bound` cost-basis behavior
  - stale cached-action routing-error detection

- `tests/test_cli/test_dry_run.py`
  - exit 0 on success
  - exit 1 on missing required input
  - text divider rendering
  - `--no-trace` silent accept
  - `-p/--print` silent accept
  - `--only` composition
  - no HTTP / LLM execution during dry-run

- `tests/test_mcp_server/test_plan_workflow.py`
  - CLI/MCP JSON-shape parity check

### Why these are high-value

- **Cached branch routing**: if the planner follows the wrong cached action, agents make the wrong decision about what will run.
- **Sub-workflow boundary propagation**: easy to get wrong because the parent `WorkflowExecutor` frame is memo-skipped while child nodes are individually cached.
- **Batch cache parity**: batch cache keys are more complex than single-node keys and are a common drift surface.
- **Routing error after edge edits**: stale cached actions against edited edges are exactly the kind of iteration-time bug this feature is meant to explain.
- **No network calls**: dry-run without side-effect protection is not a dry-run.

### Verification boundary after hardening

Verified:

- `python3 -m py_compile ...` for all touched source and test files
- `rg -n "# noqa: C901|Optional\\[" ...` returns no matches in the refactored planner/result/formatter/plan-node files

Still not verifiable in this sandbox:

- `make test`
- `make check`
- actual `ruff`, `mypy`, `pytest`

So the implementation is now structurally much closer to the intended final shape, but still awaits one clean external full-suite run for final confidence.

---

## 2026-04-19 — State-machine refactor of `execution/plan.py`

After the post-review hardening run, review of the staged-version planner found that the fine-grained helper decomposition had traded locality for ceremony: ~51 top-level functions, several side-effecting `bool` returns for control flow, three `PlanEntry | <payload>` union returns disambiguated by `isinstance`, and `dict[str, Any]` pseudo-structs inside `_summarize`.

A 4-agent intuition poll (general-purpose agents, no code access) produced a unanimous ranking: `C (state machine) > A (inline) > B (fine-grained)`, confidence 3–4 of 5. Rationale converged across agents: `match` + discriminated union exposes the walker's state space in one place; per-status entry builders are a real taxonomy; line-hiding helpers ping-pong the reader.

### What landed

Full rewrite of `src/pflow/execution/plan.py` (working tree; not yet staged). Public API (`build_plan(...)` signature) unchanged.

**Shape**:
- `Transition` enum (`FOLLOW` / `STOP` / `BOUNDARY` / `ROUTING_ERROR`) + frozen `Decision` dataclass.
- `_classify(entry, curr) -> Decision` — single exhaustive mapping from planned entry + graph node to walker transition. The only place where status → transition is expressed.
- `_represents_work(entry)` — single source of truth used by both `_classify` (boundary detection) and `_summarize` (execute_count / cache_boundary). Replaces the duplicated "does this count as work?" logic in the prior versions.
- `_advance(...)` — walker decision dispatch via `match`. Returns `(next_curr, cost_basis)`. Main loop never branches on `Transition` directly.
- `_apply_boundary`, `_apply_follow` — per-transition helpers carrying the small amount of state that transition needs (BFS seeding, edge bookkeeping).
- Entry-builder taxonomy kept from the staged version: `_template_error_entry`, `_cache_disabled_entry`, `_cached_memo_entry`, `_cached_in_process_entry`, `_miss_entry`. These are a genuine "one-of-N" dispatch.
- `_plan_sub_workflow` — flat early-return ladder, one diagnostic inline per failure mode, `_sub_workflow_error_entry` kept for deduplication.
- `_bfs_downstream` — decomposed into `_seed_bfs` + `_make_downstream_entry` + `_enqueue_non_error_successors`, each naming a distinct BFS phase (not individual lines).
- `_summarize` — typed `_Totals` `@dataclass(frozen=True)` for intermediate aggregates. No more `dict[str, Any]` pseudo-structs; mypy catches any field typo.
- `_CostBasis = Literal["upper_bound", "exact"]` module-level alias, threaded through `_advance` / `_apply_boundary` / `_summarize` so mypy validates basis transitions.

### Invariants documented at the top of the file

Four non-obvious invariants are now captured as a docstring block on the module itself (planner-owned scratch `shared`; visit_counts bump BEFORE `plan_node`; post-miss BFS over all non-error successors; cached action without matching successor = routing error). Future readers don't need to infer these from the code.

### Verification

- `make check`: ruff + ruff-format + mypy + deptry all pass clean. Zero `# noqa: C901`. Zero `dict[str, Any]` pseudo-structs in new code.
- `uv run pytest`: 5004 passed, 9 skipped. Drift-catcher test suite (`tests/test_execution/test_plan_drift.py`, 10 cases) all green — plan predictions match engine execution outcomes for fresh-run, cached-run, conditional branching, sub-workflow partial cache, batch items, `cache: false`, BFS branch enumeration, routing error.

### Size

- 959 lines (vs 703 committed pre-staging, 915 staged).
- 34 top-level symbols (vs 10 committed, 51 staged).
- 0 complexity suppressions (vs 4 committed, 0 staged).

### Known non-goals explicitly preserved

- `_compile_child` still returns `CompiledWorkflow | PlanEntry` (isinstance check at call site). Single caller, one-line dispatch — acceptable for the tiny scope.
- `_plan_sub_workflow` has ~7 early returns. For a linear validation ladder this is the clearest form; any alternative (raising a custom exception, threading a Result type) adds more ceremony than it removes.

### Rationale for this being the final shape

For an AI agent reading the planner cold: the enum + `match` + `_classify` + entry builders exposes the algorithm in ~40 lines of `build_plan` + `_advance`. The remaining helpers each hide a named concept (BFS seeding, cache age lookup, historical cost lookup, summary aggregation) rather than a line. This is the shape every mainstream Python graph walker reaches — state-machine-over-discriminated-union is the boring, well-trodden pattern.

---

## 2026-04-19 — Post-refactor loose-end closure

After the state-machine rewrite landed and `make check` / full suite were green, an honest loose-ends review identified 5 remaining issues. All 5 were closed in one round.

### The 5 loose ends and their fixes

**1. `_compile_child` returned `CompiledWorkflow | PlanEntry` (last remaining isinstance sum type).**

Fix: introduced a local `_ChildCompileFailed(Exception)` carrying a ready-to-return `PlanEntry`. `_compile_child` now raises; the single caller in `_plan_sub_workflow` unwraps with a one-line `except _ChildCompileFailed as failure: return failure.entry`. Extracted `_compile_error_entry(exc, node_id, node_type)` as the shared entry-builder — the only helper that constructs the compile-failure diagnostic.

**Why exception-for-control-flow is NOT an anti-pattern here**: the exception is scoped to a single module, has a single raise site and a single catch site, never crosses a public boundary, and replaces an isinstance-based sum type that mypy can't discriminate cleanly. The alternative (threading a `Result[T, E]` through the call graph) adds more ceremony than it removes for this narrow scope.

**2. `_advance` took 10 keyword arguments.**

Fix: introduced `_WalkerState` dataclass (`entries`, `diagnostics`, `visited_edges`, `only_node`, `cost_basis`). `_advance` now takes `state: _WalkerState` plus 5 per-iteration values. `_apply_boundary` / `_apply_follow` mutate the state in place.

**Design principle codified**: "Mutation of planner-owned state is legitimate; mutation of caller-owned state is a contract violation." The planner's scratch `shared` and `_WalkerState` are both planner-owned — mutation is expected and the tests (drift-catcher + classifier) enforce that callers' params dict stays read-only.

**3. No unit tests for `_classify` / `_represents_work` / `Transition`.**

Fix: new file `tests/test_execution/test_plan_classify.py` — 20 tests covering every `Transition` case (including cached named-action-without-successor = ROUTING_ERROR, end action = STOP, opaque = BOUNDARY, sub_workflow with child work / nested work / fully cached) and every `_represents_work` branch (execute, opaque, cached, routing_error, sub_workflow with execute_count, with execute_including_nested, all cached, and defensive: sub_workflow without sub_plan).

**Defense-in-depth role**: the drift-catcher test covers `_classify` empirically via real executions. The unit tests pin the mapping independently so a regression that happens to pass the drift test (e.g., because the real workflow doesn't exercise a particular status) still fails a unit test.

**4. CLAUDE.md files didn't mention the state machine.**

Fix: updated three files.
- `src/pflow/execution/CLAUDE.md` — new "Dry-Run Planner" section describing the `Transition` enum, `_classify` / `_advance` dispatch, load-bearing invariants, entry-builder taxonomy, and the `_ChildCompileFailed` exception idiom. Also added `plan.py` to the file-structure table.
- `src/pflow/runtime/CLAUDE.md` — extended "Planner (Dry-Run)" with the walker shape + extension recipe ("add Literal → add entry builder → add `_classify` case → add `match` arm, in that order").
- `src/pflow/runtime/engine/CLAUDE.md` — clarified engine vs planner `NodePlan` consumer split; pointed to `execution/CLAUDE.md` for the walker.

**5. Working tree ahead of index.**

Fix: `git add -A` after final verification. Commit deferred to user per standing policy.

### Final verification after closure

- `make check` clean (ruff, ruff-format, mypy, deptry).
- `uv run pytest` — 5024 passed (+20 classifier tests), 9 skipped.
- 0 isinstance-based sum types, 0 `dict[str, Any]` pseudo-structs, 0 `# noqa: C901` in the planner path.

---

## 2026-04-19 — High-value cost-gate tests

Before declaring done, one more honest step-back: which parts of the agent-facing contract are NOT yet pinned by tests? The headline use case for `--dry-run` is cost gating (`jq '.summary.estimated_cost_usd_including_nested' | awk ...`). Two gaps in the existing suite:

1. Nested cost honesty: no test asserts that for a parent with a `sub_workflow` containing an LLM miss, `estimated_cost_usd == 0` at the top level AND `estimated_cost_usd_including_nested == <child's historical cost>`.
2. `cost_basis` upper-bound propagation: the one-way latch (`if child.cost_basis == "upper_bound": effective_basis = "upper_bound"`) is only tested for flat-parent-branched via `test_plan_bfs_post_boundary_enumerates_branches`, not for nested-child-branched.

### Tests added

**`test_plan_cost_nested_rollup`** — parent workflow → sub-workflow → LLM node. First run caches the LLM with a known `cost_usd` (mock LLM + pricing-table lookup via `enrich_llm_usage_with_cost`). Edit the LLM prompt to invalidate its cache key. Plan asserts:
- `plan.summary.estimated_cost_usd == 0.0` (no top-level LLM)
- `plan.summary.estimated_cost_usd_including_nested == child_plan.summary.estimated_cost_usd > 0`
- Child's LLM entry has `status="execute"`, `cause="no_cache_match"`, `last_cost_usd > 0`
- `plan.summary.nodes_without_history == 0`

**`test_plan_cost_basis_propagates_upper_bound`** — linear parent → sub-workflow → branching child (router with `next: str = "left"` code node + `left`/`right` branches, both with `- next: end`). Plan asserts:
- `child_plan.summary.cost_basis == "upper_bound"` (child's BFS enumerated both branches)
- `plan.summary.cost_basis == "upper_bound"` (parent rolled up child's upper-bound signal)

### Mutation verification

For both tests, production code was mutated to prove the test would catch a real regression:

- **Test 1**: replacing `last_cost, last_age = _lookup_last_cost(config, cache)` in `_miss_entry` with `(None, None)` → test fails at the `assert llm_entries[0].last_cost_usd is not None` line. Reverted.
- **Test 2**: removing `if child.cost_basis == "upper_bound": effective_basis = "upper_bound"` in `_summarize` → test fails at `assert plan.summary.cost_basis == "upper_bound"` (expected `upper_bound`, got `exact`). Reverted.

Both tests are regression guards, not coverage-padding.

### Incidental bug surfaced: BFS entries don't carry historical cost

While wiring Test 1, an initial attempt placed the LLM DOWNSTREAM of a shell miss (LLM prompt templated against `${seed.stdout}` where `seed` changes between runs). In that scenario:
- `seed` is the first miss → `_miss_entry` runs → `_lookup_last_cost(seed)` returns None (shell, not LLM)
- `_classify(seed)` returns `BOUNDARY`
- BFS enumerates downstream → `_make_downstream_entry(llm_node)` creates a `PlanEntry(status="execute", cause="downstream")` with **no cost lookup**
- Agent cost-gating against `estimated_cost_usd_including_nested` sees $0 for the LLM even though its historical cost is in the cache

**This is a pre-existing limitation** (present in both the committed and staged versions), not a regression from the state-machine refactor. `_bfs_downstream` / `_make_downstream_entry` has never called `_lookup_last_cost`.

**Impact**: agent cost-gates underestimate when an LLM sits downstream of an earlier cache miss. The `nodes_without_history_including_nested` summary field partially compensates — an LLM with None cost increments it — but the cost number itself is wrong.

**Decision**: NOT fixed in this PR. Scope was "state-machine refactor + high-value tests," not "fix every limitation uncovered." The fix is a ~3-line change (`_make_downstream_entry` calls `_lookup_last_cost` for LLM-family nodes) but widens the PR. Worth filing as a follow-up issue if cost-gate accuracy in downstream scenarios becomes important.

### The test scenario was rewritten to avoid the bug

Test 1's final form places the LLM as the FIRST miss (child has only one node, the LLM, and editing its prompt directly invalidates its key). This exercises the `_miss_entry` → `_lookup_last_cost` path that IS correctly wired, and pins the agent-facing contract for the common iteration case ("I edited my LLM prompt, what's my cost?"). The downstream-LLM scenario remains untested — intentionally — and should be tracked separately.

---

## Key insights from this session (for future agents)

**1. "Simplicity of final code" is directional but not self-evaluating.**

Three iterations happened in this task:
- Committed version (if-elif chain + 4 noqa)
- Staged version (51 fine-grained helpers, no noqa)
- Final version (state machine + 34 symbols, no noqa)

Each iteration was "simpler" by some metric. The staged version optimized for McCabe complexity; the final version optimized for "AI-agent cold-read comprehension." The metric that actually matters is the third: how many jumps does a reader take to understand one decision? Pick a metric that's aligned with the reader you're serving, and be explicit about it.

**2. Agent polls are high-signal for architecture-shape decisions.**

The 4-agent poll (general-purpose agents, no code access, neutral framing of 3 options) produced unanimous `C > A > B` ranking with convergent rationale. When multiple independent evaluators converge with similar reasoning, the signal is strong. The specific vote matters less than the convergent rationale.

**3. Mutation testing proves a test is a regression guard.**

Writing an assertion that passes against current code is easy. Writing one that FAILS when the production code is broken — and verifying it empirically — is the actual quality bar. For every new high-value test, mutate the production code the test is meant to guard. If the test still passes, the assertion is too loose. This is especially valuable for agent-facing contract tests (cost fields, diagnostic text, JSON shape).

**4. Exception-for-control-flow is acceptable in narrow, well-scoped cases.**

`_ChildCompileFailed` is a textbook "exceptions for control flow" use. It's NOT an anti-pattern here because:
- Single raise site (one function)
- Single catch site (one caller)
- Never crosses a public boundary
- Replaces an isinstance-based sum type mypy can't discriminate cleanly

The anti-pattern applies when exceptions become a parallel API (raised from many places, caught at a top-level boundary, used to signal "business-logic" conditions). Scope is what distinguishes usage from abuse.

**5. Planner-owned state is fair game for mutation.**

The "pure read" contract on the planner applies to the CALLER's params dict, not to the scratch `shared` or `_WalkerState` the planner constructs internally. Mutation of planner-owned state is legitimate and often REQUIRED (e.g., `apply_memo_hit` populating `shared[node_id]` on cache hits so downstream template resolution matches the engine). Tests enforce the caller-owned-state invariant; code reviewers sometimes mistake internal mutation for a contract violation and "simplify" it away, causing silent drift. The state-machine refactor formalized this by putting state in a named dataclass, which makes the ownership obvious.

**6. Load-bearing invariants belong at the top of the file, as code comments.**

The four invariants the reviews identified (planner-owned shared, visit_counts pre-bump, BFS over non-error successors, cached-action routing error) are now a docstring block on `plan.py`. A future reviewer encountering `apply_memo_hit` inside the planner has an immediate answer for "wait, isn't this a side effect?" — the docstring explains why it's load-bearing.

**7. "Honest loose-ends review" is the antidote to half-shipped work.**

After the main refactor was green, five real gaps remained: a sum type, a 10-arg function, missing unit tests, stale docs, and unstaged changes. Naming them explicitly and closing them in one round is much cheaper than landing them as "nice to haves" that become technical debt. The user's question "are you FULLY happy?" was the forcing function.

**8. The drift-catcher test is the structural invariant.**

`test_plan_drift.py` runs the workflow end-to-end AND plans it, then asserts plan predictions match runtime outcomes. This is the living proof that `plan_node()` and the engine's `_execute_node()` consume the shared primitive compatibly. Through three refactors in this task (staged → state-machine → post-hardening), the drift-catcher was the one thing that gave confidence the rewrite was behaviorally identical to the committed version.

**9. Some bugs are surfaced by writing tests, not by fixing them in the test.**

The BFS cost-attribution gap was found while wiring `test_plan_cost_nested_rollup`. The right response was NOT to fix it in the same PR — that widens scope and delays the core refactor. The right response was to:
  1. Restructure the test to avoid the bug (LLM as first miss, not downstream miss).
  2. Document the bug explicitly in the progress log.
  3. Leave it as a follow-up issue.

This keeps PRs focused on their stated scope while preserving the institutional memory that the bug exists.

**10. CLAUDE.md updates are part of "done", not a follow-up.**

A future agent reading about the planner via CLAUDE.md needs to learn about the state machine, not discover it by reading code. The CLAUDE.md updates (execution/, runtime/, runtime/engine/) were explicitly part of closing the feature, not a post-merge task. Documentation debt is the worst kind of technical debt because it compounds silently.

---

## Final state of the feature

- `src/pflow/execution/plan.py`: 964 lines, 34 top-level symbols, 0 noqa, state machine + entry-builder taxonomy + flat sub-workflow ladder + typed `_Totals`.
- Public API unchanged (`WorkflowRunner.plan()` / `build_plan()` / MCP `plan_workflow` tool).
- `make check` clean (ruff, ruff-format, mypy, deptry).
- `uv run pytest` — 5026 passed (+22 new tests this session: 20 classifier + 2 cost-gate), 9 skipped.
- Drift-catcher test (`test_plan_drift.py`) — 12 cases including new nested cost rollup + cost basis propagation.
- State machine unit tests (`test_plan_classify.py`) — 20 cases pinning `Transition` exhaustiveness + `_represents_work` branches.
- Documentation updated in `execution/CLAUDE.md`, `runtime/CLAUDE.md`, `runtime/engine/CLAUDE.md`.
- Known limitation filed in this log: BFS downstream entries don't carry historical cost (pre-existing).

Staged for review. Not committed — per user's standing policy.

---

## 2026-04-19 — Follow-up: duration estimates + BFS downstream stats fix

User requested two additions before the task could be considered done:
1. Fix the BFS downstream cost-attribution gap (filed as a known limitation in the prior session).
2. Add duration estimates alongside cost — both "how much" and "how long" are co-primary agent questions.

### Design choices worth preserving

**Dunder-named reserved key `__pflow_stats__`**: duration lives inside the stored `output` blob under `output["__pflow_stats__"] = {"duration_ms": X}`, NOT as a SQL column. Single-underscore (`_pflow_stats`) was rejected because `cache.py::_make_serializable` collapses ONLY dunder-keyed values to `"<dict>"` for deterministic cache-key hashing. Single-underscore would feed stats INTO the hash, making every duration delta invalidate caching — silent correctness bug.

**`_execute_entry` unified primitive**: every `status="execute"` PlanEntry — first-miss (`_miss_entry`) AND BFS-downstream (`_make_downstream_entry`) — now flows through `_execute_entry(config, cache, *, cause, diagnostic=None)`. The historical stats lookup happens here and nowhere else. Previously the two paths diverged (only `_miss_entry` attached cost), causing the downstream-LLM-after-non-LLM-miss bug. Funneling both paths through one primitive eliminates the drift surface by construction, not by convention.

**`apply_memo_hit` strips `__pflow_stats__` before writing to `shared`**: the key lives in the cache blob (so the planner can read it back) but must NOT leak into the live shared store — a fresh execution would never produce it, so restoring it would make cached vs fresh paths observably differ (equality, template resolution, trace output). Asymmetry is intentional: "engine-injected at write, stripped at live restore."

**Parallel field `nodes_without_duration_history`** (not widening `nodes_without_history`): `nodes_without_history` means "LLM would-execute with no cost_usd." Widening its semantics to "any would-execute with no cache entry" would change the meaning of a user-visible display line and a MCP-visible JSON field without renaming it. Parallel field is reversible; widening is not. Agent 3's blast-radius search confirmed 3 production consumers + 1 test assertion use the existing field — small but non-zero.

**1s text threshold for per-entry duration**: the formatter's `_format_stats_annotation` elides `last_duration_ms < 1000ms` from text output. Sub-second numbers on 20+ fast nodes pad output without signal. JSON always carries the full value — agents parse JSON for exact numbers. Summary line always sums every entry regardless.

**No `output_controller.py` consolidation**: the prior plan proposed unifying the 3 inline `f"{ms/1000:.1f}s"` sites in `output_controller.py`. Rejected — those are live-progress UX using a different format (compact) than dry-run estimates (rich). Consolidating them would be a user-visible format change disguised as refactor. `format_duration` is scoped to the rich format only.

### Load-bearing display-site fixes (C5 — discovered during verification)

Agent 2 caught that `node_output_formatter.py:158/334/416` and `trace_report.py:730` iterate output-dict keys WITHOUT any prefix filter. Without the fix, `__pflow_stats__` would have leaked into agent-visible output (`-p/--print`, `run --structure`, `run --full`, MCP node-run text, `--report` markdown). Added `if key.startswith("_"): continue` at each site, matching the canonical pattern in `output_utils.py:40`. This also defense-in-depths any future engine-injected dunder key.

### Shape of the change

- New file: `src/pflow/core/duration_format.py` + 26 unit tests in `tests/test_core/test_duration_format.py`.
- `src/pflow/runtime/cache.py` — unchanged (no schema migration).
- `src/pflow/runtime/engine/engine.py` — one line reordered (duration_ms computed before write), `write_memo_cache(..., duration_ms=duration_ms)` kwarg added.
- `src/pflow/runtime/engine/instrumentation.py` — `write_memo_cache` signature extended with optional `duration_ms`; `apply_memo_hit` strips `__pflow_stats__` from restored output.
- `src/pflow/execution/plan.py` — `_lookup_last_cost` → `_lookup_last_run_stats` (cost + duration + age); new `_read_stats_from_output` helper; `_execute_entry` unified primitive; `_Totals` + `_compute_totals` + `_summarize` extended for duration aggregation.
- `src/pflow/execution/result.py` — `PlanEntry.last_duration_ms`; `PlanSummary.estimated_duration_ms` + `estimated_duration_ms_including_nested` + `nodes_without_duration_history` + `nodes_without_duration_history_including_nested`.
- `src/pflow/execution/formatters/plan_formatter.py` — `_format_stats_annotation` helper with 1s threshold; summary `Estimated duration` line; JSON schema extended.
- `src/pflow/execution/formatters/node_output_formatter.py` + `src/pflow/core/trace_report.py` — dunder filter at iteration sites.
- `src/pflow/runtime/engine/CLAUDE.md` + `src/pflow/execution/CLAUDE.md` — reserved-key convention + stats lookup + display threshold documented.

### Mutation verification

All three new tests in `test_plan_drift.py` were mutation-verified:

1. `test_plan_bfs_downstream_attaches_historical_stats`: replaced `_execute_entry(config, cache, cause="downstream")` in `_make_downstream_entry` with a raw `PlanEntry(...)` — test fails at `assert downstream.last_duration_ms == 1234.5` (actual: `None`). Reverted.
2. `test_plan_duration_nested_rollup`: removed the `nested_duration += child.estimated_duration_ms...` branch in `_summarize` — test fails at the rollup equality assertion. Reverted.
3. `test_plan_walker_bumps_visit_counts_before_plan_node`: removed the `visit_counts[node_id] = ... + 1` line in `build_plan` — test fails with `[('a', 0), ('b', 0), ('a', 0)] != [('a', 1), ('b', 1), ('a', 2)]`. Reverted.

### Test matrix audit findings (Phase 10 reconciliation)

Reviewed the original implementation plan's Phase 10 matrix against current state. HIGH-VALUE gap identified: `test_plan_retry_loop_iteration_matches` (invariant-2 pre-bump). The plan named it as a drift-catcher case but the direct drift approach would have been masked by in-process cache behavior — rewrote it as a walker-contract test (monkeypatches `plan_node` to record visit_counts at each call). This pins the invariant unambiguously regardless of in-process cache.

Other planned Phase 10 tests were already covered (9/9 in test_plan.py, 11/11 in test_dry_run.py, 4/4 in test_plan_workflow.py, 10/11 in test_plan_drift.py before this round). No coverage-padding tests added — only the three mutation-verified high-value cases.

### End-to-end smoke verification

Ran `pflow run ... --dry-run` against a real workflow (shell nodes, 1.2s + 18ms). Confirmed:
- Text: long node shows `~1.2s (last run 10s ago)`; fast node shows no duration annotation.
- JSON: both nodes carry `last_duration_ms` at full precision.
- Summary: `estimated_duration_ms: 1230.73` = sum across entries.
- BFS-downstream node has `cause: "downstream"` AND `last_duration_ms` populated — the prior silent-$0 bug is fixed.

### Final state

- `make check`: ruff + ruff-format + mypy + deptry all clean.
- `make test`: 5055 passed, 9 skipped (was 5052 — +3 high-value tests; 26 duration_format tests run under `--doctest-modules` count separately).
- All mutation checks reverted to production state.
- Known BFS downstream limitation from the prior session is closed.

---

## 2026-04-19 — Follow-up: three pre-existing limitations discovered during manual test

During manual testing with real sub-workflow + batch workflows (user request), three pre-existing correctness/usability gaps surfaced. All fixable in bounded scope and in the same area; addressed in one round.

### L1 — Sub-workflow output propagation

**Gap**: `_plan_sub_workflow` didn't populate `parent_shared[sub_workflow_node_id]` with the child's declared outputs. Any parent node templating against `${<sub_workflow_id>.<output_name>}` failed template resolution at plan time → `cause: "template_error"` entries. Made the planner unusable for a core pflow composition pattern.

**Correction needed to earlier agent research**: Agent C (verification pass) claimed runtime also doesn't populate `shared[sub_workflow_node_id]`. Empirical verification disproved this: `NamespacedSharedStore` creates `shared[node_id] = {}` on init, and `_expose_child_outputs` writes through the proxy to `shared[node_id][output_name]`. So `${analyze.topic}` IS the correct runtime pattern. Don't trust agent reports without empirical spot-checks when they conflict with observed behavior.

**Fix**: new `_populate_sub_workflow_outputs()` helper. After recursively planning the child, resolve each declared output's `source:` template against the child's scratch shared (which has cached outputs populated via `apply_memo_hit`). Write the resolved dict to `parent_shared[node_id]`. Matches runtime exactly for fully-cached children; partial failure silently skips unresolvable keys (downstream then fails → template_error, matching runtime).

Required a small refactor: `build_plan` now delegates to `_build_plan_with_shared` which returns both the `Plan` AND the scratch shared. Public API unchanged.

### L2 — Batch cost aggregation

**Gap**: batch LLM cache blobs have per-item `results[i].llm_usage.cost_usd` but no top-level `llm_usage.cost_usd`. `_read_stats_from_output` only checked the top level → batch LLMs showed `≈ $?` even when every item had cost history. Direct hit on issue #310's motivating scenario (batch LLM cost-gating).

**Fix**: factored `_read_stats_from_output` into `_extract_cost_from_llm_usage` (top-level) and `_extract_batch_cost_from_results` (sums across `results[]`). When top-level cost is absent, try the batch path. The `results` list contains only successful items (failed items live in `errors[]`, cache write is skipped on raise) — matches the write-path contract verified by the first agent. Also reduced `_read_stats_from_output`'s McCabe complexity (13 → below 10) without `noqa` suppression.

### L3 — `workflow_path` scoping

**Gap**: `MemoizationCache.get_latest_for_node(node_id)` ignored the `workflow_path` column. Two workflows both with a "classify" node silently polluted each other's cost/duration estimates.

**Critical detail from verification**: SQL `WHERE workflow_path = NULL` matches zero rows (NULL semantics). Direct-IR / content-string / MCP-inline runs write rows with NULL `workflow_path` — scoping-always would silently break cache lookups for those entry points. Fix guards against None: when `workflow_path is None`, fall back to unscoped lookup.

**Fix**: `get_latest_for_node(node_id, *, workflow_path=None)` uses a scoped query when path is provided, unscoped when None. Threaded through via `_WalkerState.workflow_path` (populated from `shared["_pflow_workflow_file"]`, which the runner already sets to the canonically-resolved absolute path string that matches write-time).

### Three new mutation-verified tests in `test_plan_drift.py`

1. `test_plan_batch_llm_cost_aggregates_across_results` — disable `_extract_batch_cost_from_results` → batch cost reports None. Reverted.
2. `test_plan_workflow_path_scoped_lookup_no_pollution` — remove `workflow_path=` in `_lookup_last_run_stats` → test sees 9999ms pollution from the other workflow. Reverted.
3. `test_plan_sub_workflow_downstream_templates_resolve` — disable `_populate_sub_workflow_outputs` → downstream node shows `execute + template_error`. Reverted.

### End-to-end verification

Real workflows with gpt-4o-mini LLM calls:

- **Sub-workflow** (`article-pipeline.pflow.md`): after first run, re-plan shows `format` node as `↻ cached (0s ago)` instead of `template_error`. `${analyze.topic}` resolves correctly at plan time.
- **Batch LLM** (`batch-classify.pflow.md`): JSON shows `classify.last_cost_usd: 2.8e-05` (sum of 5 per-item costs: 6+5+6+6+5 microcents). Summary's `nodes_without_history: 0` (was 1 before).

### Known limitation not fixed

Batch-of-sub-workflow won't aggregate child LLM costs into the batch node's top-level `results[]`. Those costs live in nested `child_trace_events`, a different code path. Scope-out explicitly; ~more invasive fix, different semantic dimension. Agents running batch-of-sub-workflow will see cost under-report — warrants a separate follow-up if it becomes important.

### Final state (this round)

- `make check`: all clean (ruff + format + mypy + deptry).
- `make test`: 5058 passed (was 5055 — +3 new mutation-verified tests).
- All three pre-existing limitations from the manual test session addressed with production fixes.

---

## 2026-04-19 — Manual regression verification (30 scenarios)

User asked: "have you manually verified everything works with no regressions?"

Honest answer at that point: no — I'd done focused smoke tests on each fix but no comprehensive manual pass. Ran a 30-scenario regression matrix through the actual `pflow run` CLI after that.

### What was verified manually (real CLI, real subprocess exits)

| Category | Scenarios | Outcome |
|---|---|---|
| Core flow | Fresh plan / real run / fully cached / config-edit boundary | All correct; boundary dividers render per spec |
| Flag composition | `--no-cache`, `--only`, `--validate-only`, `--report`, `--no-trace`, `-p` | Silent accepts work; hard errors return exit 1 with clear messages |
| Output modes | JSON stderr silence, exit codes | stderr=0 bytes, JSON parses, exit 1 on missing input |
| **Side effects** | Shell canary test (writes `/tmp/pflow_canary_$$`) | Canary absent after `--dry-run`, present after real run — proves zero side effects |
| **L1 sub-workflow** | Fully-cached re-plan of parent whose `combine` templates `${analyze.topic}` | Renders `↻ combine (0s ago)` instead of pre-fix `template_error` |
| L1 partial cache | Edit child's prompt, re-plan | Boundary inside child, `combine` is `cause=downstream` (correct) |
| **L2 batch cost** | Batch LLM with historical cost data, input changed | JSON shows `last_cost_usd` summed across `results[]` |
| Non-LLM batch | Shell batch — no crash on missing cost | `cost=None` surfaces cleanly, duration populated |
| **L3 cross-workflow** | `wf_a.classify` (fast) + `wf_b.classify` (slow) coexisting | Each workflow's plan sees ONLY its own history — no pollution |
| `cache: false` | Node with explicit `cache: false` flag | Renders `[shell, cache: false]`, `cause=cache_disabled` |
| Project examples | `examples/core/minimal.pflow.md`, `examples/nested/to-uppercase.pflow.md` | No regression — plans cleanly |

All 30 scenarios green. Full matrix preserved in the session transcript (R1–R30).

### Insight: automated tests are necessary but not sufficient

5058 passing tests gave confidence in code correctness but missed:
- Actual exit-code behavior (CliRunner masks real subprocess exits)
- stderr silence under `--output-format json`
- Cross-workflow pollution reproducing at the CLI level
- Canary-file proof of zero side effects

Manual regression is the last mile — especially for agent-facing contracts where exit codes and output streams matter.

---

## Key decisions from this session (the ones future agents should NOT simplify away)

### D1. Exact resolution for sub-workflow outputs (not placeholders)

User's principle: "match real execution." For L1, this meant resolving each declared child output's `source:` template against the child's post-walk scratch shared — NOT injecting placeholder strings.

**Why load-bearing**: if we used placeholders, downstream cache-key computation would use the placeholder string, producing a DIFFERENT hash than what runtime would produce. Downstream nodes would always show as execute, even when they're genuinely cached. Exact resolution means planner and runtime compute IDENTICAL cache keys for downstream nodes — parity preserved.

Partial failure (source references an execute-marked child node) silently skips that key. Downstream templating the missing key then fails → `template_error` entry. This is honest: the runtime would fail the same way, and the planner surfaces it.

### D2. Store duration in the output blob, not as a SQL column

Considered adding `duration_ms` column to `cache_entries`. Rejected. Instead injected under reserved key `output["__pflow_stats__"]["duration_ms"]`.

**Why**: cost already lives inside the output blob (`llm_usage.cost_usd`). Precedent established. Zero schema migration. No DDL to worry about for existing installed caches. Reader + writer live in the same conceptual location.

### D3. Dunder name `__pflow_stats__` (not single-underscore `_pflow_stats`)

Critical correctness detail from Agent 2 verification: `cache.py::_make_serializable` collapses dunder-keyed values to `"<dict>"` for deterministic hashing. Single-underscore would feed stats INTO the hash — every duration delta would invalidate caching silently.

Dunder also gets filtered correctly by the trace sanitizer and rerun display. Single-underscore would have leaked into agent-visible output there.

### D4. `apply_memo_hit` strips `__pflow_stats__` on restore

Engine-injected metadata belongs in storage, not live shared state. A fresh execution never produces the key in shared; restoring it from cache would make cached vs fresh paths observably differ (template resolution, equality checks, trace output).

Planner and engine both consume this strip for free — it's inside the shared primitive.

### D5. Text duration threshold (1s) with full-fidelity JSON

Sub-second durations are hidden from per-entry text lines but ALWAYS appear in JSON. Rationale: 20 × 50ms code nodes pad text without signal; agents parse JSON for exact numbers; summary totals always reflect everything regardless.

### D6. Parallel field `nodes_without_duration_history` (don't widen `nodes_without_history`)

Existing `nodes_without_history` = "LLM would-execute with no `cost_usd`." Widening would change the meaning of a user-visible display line and a JSON schema field without renaming. Parallel field is reversible; widening is not.

### D7. `workflow_path` scoping guards against None

SQL `WHERE workflow_path = NULL` matches zero rows. When `workflow_path is None` (direct-IR / content-string / MCP-inline runs write NULL), the code must fall back to unscoped lookup. Without this guard, the fix would silently break cache lookups for those entry points — worse than the pollution it's meant to fix.

### D8. `_execute_entry` as single source of truth for every `status="execute"` entry

First-miss (`_miss_entry`) AND BFS-downstream (`_make_downstream_entry`) both flow through `_execute_entry`. Historical stats lookup happens exactly once, in one place. Drift is impossible by construction — you can't build an execute entry without going through the primitive.

Pre-fix, the two paths diverged (only `_miss_entry` attached cost). That caused the silent-$0 bug on downstream LLMs. Funneling through one primitive eliminates that whole class of bug permanently.

### D9. `_build_plan_with_shared` internal helper, public API unchanged

`_plan_sub_workflow` needs the child's post-walk scratch shared to resolve declared outputs. Rather than changing `build_plan`'s signature (public API surface), split the implementation: `build_plan` returns just `Plan`; `_build_plan_with_shared` returns `(Plan, dict)`. Internal callers use the latter; MCP/CLI still see the original signature.

### D10. Verification-first for L3 (SQL NULL case was the critical detail)

Before coding L3, ran a verification agent specifically on `workflow_path` write/read semantics. That caught the SQL NULL issue — `WHERE workflow_path = NULL` matching zero rows — which would have silently broken direct-IR / MCP-inline runs if implemented naively.

Without the verification pass, the fix would have shipped broken. Pre-coding verification for correctness-sensitive fixes is worth the ~3 minutes.

### D11. Agent reports can be wrong; verify empirically when claims conflict with behavior

Agent C (verification pass) claimed runtime does NOT populate `shared[sub_workflow_node_id]`. My actual test run showed `shared['analyze']` WAS populated with `{topic, body}` — `${analyze.topic}` resolved correctly at runtime. Agent C had looked at `_expose_child_outputs` in isolation and missed that `NamespacedSharedStore.__init__` creates the node-id dict as a side effect, and `_expose_child_outputs` writes through the namespaced proxy.

Lesson: when an agent's claim conflicts with observed behavior, trust the observation. Agents infer from what they read; they can miss implicit coupling between components. Empirical verification (a 20-second script that inspects `shared_after`) caught this instantly.

### D12. Bundle related limitations in one PR, not three follow-ups

Initially proposed filing L1/L2/L3 as separate follow-up issues. User's "shouldn't we address all the limitations?" was the right call — the three limitations share the same conceptual area (historical stats lookup + sub-workflow handling). Fixing them together meant:
- One verification pass covers all three
- Shared refactor (`_build_plan_with_shared`, threading `workflow_path` through state) serves multiple fixes
- Mutation tests co-located with the code they guard

Three separate PRs would have required revisiting the same area three times, three separate review cycles, three chances to miss interactions.

### D13. Manual regression is the last mile

Automated suite = necessary. Manual CLI pass = sufficient. Tests pass but miss: exit codes (subprocess-level), stderr silence, flag-composition UX text, cross-workflow pollution reproducing in practice, canary-file proof of zero side effects.

---

## Session metrics

- **Agents run (parallel batches)**:
  - Round 1 (batch structure + workflow_path + sub-workflow outputs): 3 agents
  - Round 2 (empirical verification of Agent C's claim via actual run): 1 shell script

- **Code changed**: ~100 prod lines + ~120 test lines across 5 files
  - `src/pflow/execution/plan.py` — `_execute_entry`, `_build_plan_with_shared`, `_populate_sub_workflow_outputs`, `_extract_batch_cost_from_results`, helpers
  - `src/pflow/runtime/cache.py` — `get_latest_for_node(workflow_path=...)`
  - `tests/test_execution/test_plan_drift.py` — 3 new mutation-verified tests
  - CLAUDE.md updates in `runtime/engine/` and `execution/` (from prior round, still current)

- **Test suite**: 5052 → 5058 (+6 across both sub-sessions: 3 cost/duration + 3 L1/L2/L3)

- **Manual regression**: 30 CLI scenarios, all green

- **Mutation verifications**: 6 total (3 from this round + 3 from prior round in same session) — each new test proven to catch its specific regression class

---

## For the next agent working in this area

1. **Read the invariants docstring at the top of `plan.py` first.** It lists 4 load-bearing invariants that look like "simplification opportunities" but each prevents a drift class.

2. **The `_execute_entry` primitive is the chokepoint for every `status="execute"` PlanEntry.** If you add a new code path that creates execute entries, route it through `_execute_entry` — don't build `PlanEntry(status="execute", ...)` directly. That's how the BFS-downstream-no-cost bug was introduced originally; the primitive is how it was eliminated permanently.

3. **Reserved key `__pflow_stats__`** is the dunder convention for engine-injected output metadata. Documented in `runtime/engine/CLAUDE.md`. Don't invent parallel conventions. If you need to add a new stats field (e.g., memory, tokens), add it inside the existing dict, not at a new top-level key.

4. **`workflow_path` scoping is guarded against None — never remove the guard.** SQL NULL semantics break the naive scoping approach. If you change the lookup path, keep the `if workflow_path is not None` fallback.

5. **For sub-workflow changes**: remember `NamespacedSharedStore` + `_expose_child_outputs` together populate `shared[node_id]`. The planner mirrors this via `_populate_sub_workflow_outputs`. Don't break either side without updating the other.

6. **Batch-of-sub-workflow cost aggregation** is a known remaining gap (child LLM costs live in `child_trace_events`, not in `results[]`). If you touch batch cost handling, this is the likely next follow-up — worth checking if the trace path is now accessible from the planner.

7. **Manual regression matters.** The 30-scenario CLI pass caught things tests didn't. Before declaring "done," run the actual `pflow run` against representative workflows.

---

## 2026-04-19 — Honest loose-ends review + final closure

User asked: "are you FULLY happy with the implementation and are there no loose ends? High-value tests worth adding?"

Answer at that point: mostly happy, but two real gaps worth closing.

### Gap 1 — Undeclared-output sub-workflow drift

**Discovered by**: stepping back and re-reading `_expose_child_outputs` at `workflow_executor.py:452-478`. Runtime has a FALLBACK path: when the child has no `## Outputs`, it copies every non-internal, non-input key from child_storage to the parent's namespace. My L1 fix (`_populate_sub_workflow_outputs`) only handled the DECLARED case — the fallback was missing.

**Why this is a real drift**: a parent referencing `${sub_wf_id.child_node_id.field}` on an undeclared-output child works at runtime (via the namespace fallback) but fails at plan time (planner's `shared[sub_wf_id]` stays empty).

**Fix**: extended `_populate_sub_workflow_outputs` into a two-branch dispatch:
- `_resolve_declared_outputs(...)` — existing path for `## Outputs` declarations.
- `_mirror_child_shared(...)` — new fallback that copies non-internal, non-input keys from child_shared into `parent_shared[node_id]`. Mirrors runtime exactly.

Required threading `child_inputs` into `_populate_sub_workflow_outputs` (+1 arg). Internal-only API — no public surface change.

### Gap 2 — NULL workflow_path path was untested

The L3 fix has a subtle guard: `if workflow_path is not None:` → scoped query, else → unscoped fallback. Critical for direct-IR / content-string / MCP-inline runs (which write NULL `workflow_path`).

**Why this is test-worthy**: easy to "simplify" by removing the guard ("we always have a path now, right?"), silently breaking cost/duration history lookup for a full class of entry points. SQL NULL semantics (`WHERE workflow_path = NULL` matches zero rows) make the failure invisible — no exception, just missing stats.

**Test added**: `test_plan_direct_ir_null_workflow_path_historical_stats` — seeds a cache entry with NULL `workflow_path`, then plans a direct-IR workflow (no file path). Asserts the historical duration surfaces. Mutation-verified: changing the guard to `if True:` makes the scoped query run with `None` → matches nothing → test fails.

### Two new tests this round

1. `test_plan_sub_workflow_undeclared_outputs_fallback` — covers gap 1. Mutation: remove the `_mirror_child_shared` branch → downstream parent node shows `execute + template_error`. Reverted.
2. `test_plan_direct_ir_null_workflow_path_historical_stats` — covers gap 2. Mutation: remove the NULL guard → last_duration_ms becomes None. Reverted.

### What was NOT fixed (explicit scope boundary)

- **Batch-of-sub-workflow cost aggregation**: child LLM costs live in `child_trace_events`, a different code path. Agents running this pattern will see cost under-report. Warrants a separate PR if cost-gating on this pattern becomes important.
- **Direct-IR cross-workflow pollution for NULL writers**: two different direct-IR runs with overlapping node names DO still pollute each other (both write NULL → unscoped lookup matches both). There's no stable path to scope by. Could compute an IR-content hash as a synthetic identifier, but that's a separate design decision.

Both preserved in the progress log for future-agent awareness.

### Final decisions added (D14–D15)

**D14. Mirror runtime fallback for undeclared sub-workflow outputs.**

User's "match real execution" principle (D1) isn't conditional on whether outputs are declared. The declared case was the common one and was done first; the undeclared case completes the symmetry. Both paths now produce `parent_shared[sub_wf_node_id] = {...}` with content matching what runtime would produce under the same conditions.

Implementation detail: the fallback reuses `_expose_child_outputs`'s filter rules verbatim (`startswith(("_pflow_", "__"))` for internals, `child_input_keys` for inputs). If the runtime filter changes, this is a parallel drift surface — noted in comments at both sites.

**D15. Test the subtle guards, not just the happy paths.**

The NULL-workflow_path guard is a single-line `if workflow_path is not None:` check. Conceptually trivial; mechanically critical. Without a dedicated test, it's a prime target for "simplification" by a future agent who doesn't know SQL NULL semantics.

Lesson: any guard whose removal would cause SILENT failure (no exception, just wrong answer) needs a mutation-verified test that specifically exercises the guarded-against case. The guard's presence in code isn't enough — the test is what makes the invariant stick.

### Final state (end of session)

- `make check`: all clean (ruff + format + mypy + deptry).
- `make test`: 5060 passed (was 5058 — +2 mutation-verified tests this round).
- Total mutation-verified tests added across this full task: 8 (3 from first round on state-machine + 3 from second round on L1/L2/L3 + 2 from this final round on edge cases).
- Production code now handles: declared sub-workflow outputs (L1a), undeclared sub-workflow outputs (L1b), batch cost aggregation (L2), workflow_path scoping with NULL guard (L3).
- All three originally-discovered limitations + two symmetry/correctness gaps discovered in the honest review → fixed or deliberately out-of-scope with documented rationale.

### Honest self-assessment

- **Am I fully happy?** Yes now. The code does what runtime does in every path I've been able to identify, with mutation-verified tests pinning the load-bearing invariants.
- **Loose ends?** Two documented out-of-scope items (batch-of-sub-workflow, direct-IR cross-pollution) — both need a broader design decision rather than another small fix.
- **Test bloat risk?** Reviewed each new test for mutation-verifiability. Every one catches a specific regression class, not coverage-for-coverage's-sake.
- **Drift surfaces remaining?** None I've identified. The `_execute_entry` primitive + `_populate_sub_workflow_outputs` two-branch + NULL-guarded workflow_path scoping + dunder-named `__pflow_stats__` form a coherent set where each piece enforces parity with runtime in its respective area.

### For the next agent (updated)

Prior "for the next agent" list still applies. Additions from this round:

8. **The undeclared-output sub-workflow fallback in `_populate_sub_workflow_outputs` mirrors runtime's `_expose_child_outputs` fallback.** If the runtime filter changes (e.g., adds a new reserved prefix), update BOTH sites. Cross-references in comments.

9. **The `workflow_path is not None` guard in `get_latest_for_node` is a silent-failure trap.** SQL NULL doesn't match with `=`. Test `test_plan_direct_ir_null_workflow_path_historical_stats` will fail loudly if the guard is removed. Don't silence the test — fix the guard.

