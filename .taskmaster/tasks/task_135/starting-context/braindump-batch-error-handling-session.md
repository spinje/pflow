# Braindump: Batch Error Handling Deep Dive → Execution Core Redesign

## Where I Am

This session started as a bug fix (`error_handling: continue` swallows compile errors) and evolved into a deep architectural investigation of pflow's execution model. We implemented 3 fixes across 3 commits, created 5 GitHub issues, and established Task 135 as an exploratory initiative to redesign the execution core.

The user is thinking at the architectural level. They're not looking for quick fixes — they want to understand the root causes and fix the design, not the symptoms.

## User's Mental Model

The user thinks about this in layers. They kept pushing me to look deeper:

1. **Started with the bug**: compile errors swallowed by `error_handling: continue`
2. **Pushed on scope**: "what about other node types with structural failures?" — I over-broadened, they corrected me: "the problem is compile errors corrupting sub-workflows, not all structural failures"
3. **Pushed on compile-once**: "This seems like a mistake when we implemented this?" — they saw redundant recompilation as a design smell, not just a performance issue
4. **Connected to PocketFlow**: "does this have to do with pocketflow and our modifications?" — they traced the root cause to the architectural divergence
5. **Final framing**: "using pocketflow as is has no intrinsic value anymore, having a good architecture has and being able to compile-once has"

Key user quotes that reveal their thinking:
- "should compilation be a validation concern? if something cant compile, its not validated?" — they think about clean conceptual boundaries
- "should we consider elevating to errors when this happens?" — they want correct semantics, not just warnings
- "what is the normal behavior here? this should be a solved thing?" — they expect us to follow established patterns
- "I think this should be a proper task... framed as exploratory not set in stone" — they want investigation before commitment

The user's real priority: **architectural integrity**. They'll accept pragmatic fixes (A1-refined) but they see the bigger picture and want it addressed properly.

## Key Insights

### The `initial_params` Duplication Is The Root of Everything

Per-item values exist in BOTH `initial_params` (baked into TemplateAwareNodeWrapper at compile time) AND `child_storage` (shared store at runtime). `_build_resolution_context()` gives `initial_params` priority. This single design decision is why:
- Compile-once is impossible without changes
- The `_orch()` modification was needed
- PflowBatchNode can't use BatchFlow's pattern

If you fix the `initial_params` priority/duplication, compile-once and PocketFlow alignment fall out naturally.

### The Error Cascade Has Three Distinct Failure Modes

We traced and fixed each one differently:

| Mode | What happens | Fix |
|---|---|---|
| **Compile error** | Sub-workflow can't compile, error swallowed | CompilationError propagates (#153) |
| **All items fail** | 0 successes, pipeline runs on [None, None, None] | Abort in post() (#157) |
| **Empty input** | items=[], 0 iterations, silent SUCCESS | Warning in _push_warnings() (#160) |

The partial failure case (some succeed, some fail) remains — downstream gets dirty data. Tracked as #159 (`successful_results` + downstream warning).

### Compilation Cost Is Real

Measured: 20ms for 2-node, 50ms for 5-node workflows per `compile_ir_to_flow()` call. At 50 items × 50ms = 2.5 seconds of pure waste. This isn't theoretical — it's measured overhead that scales linearly with batch size.

### Two CompilationError Classes

There are TWO `CompilationError` classes with different inheritance. The `user_errors.py` one is dead code (never raised, never imported). The `compiler.py` one has 25 raise sites across 6 files. We added `raw_message` to the compiler version for clean display. Full inventory in #155.

### The `_orch()` Modification Is Load-Bearing

`PFLOW_MODIFICATIONS.md` documents it. It prevents `set_params()` from overwriting compile-time params during orchestration. Reverting it breaks all pflow node parameter handling. But keeping it blocks BatchFlow usage. Any compile-once solution must address this.

## Assumptions & Uncertainties

ASSUMPTION: `compile_ir_to_flow()` structural output is truly independent of per-item `initial_params`. We verified this through code analysis — `initial_params` doesn't affect node types, edges, wiring, or start node. But I didn't run an actual test compiling with empty `initial_params` to verify. The `prepare_inputs()` validation would fail, which is the blocker we identified.

ASSUMPTION: Deep-copying a compiled flow is cheaper than recompilation. Expected ~1-5ms vs 20-50ms. Not measured. This assumption underpins one of the compile-once approaches (Path A in the task).

UNCLEAR: How `set_params()` interacts with the wrapper chain when called during orchestration (as BatchFlow would do). `TemplateAwareNodeWrapper.set_params()` splits params into template/static. If called again mid-orchestration with per-item params, does it correctly merge? Or does it overwrite the compile-time split? This needs investigation.

UNCLEAR: Whether `copy.copy()` in PocketFlow's `_orch()` is sufficient for compile-once reuse, or if `copy.deepcopy()` is needed. The research showed `TemplateAwareNodeWrapper` instances are shared through shallow copy (no `__copy__` on `NamespacedNodeWrapper`). This could cause state leakage between iterations.

NEEDS VERIFICATION: The `prepare_inputs()` blocker. Can we split `_validate_workflow()` into structural validation (compile-time) and input validation (runtime)? The function currently does 5 things in sequence — need to check if steps 1, 2, 4, 5 can run without step 3 (input preparation).

## Unexplored Territory

UNEXPLORED: **How does conditional branching interact with compile-once?** If a sub-workflow has conditional edges (action-based routing), the flow graph is the same for all items — but the path through it may differ. This should be fine (the graph is structural, the path is runtime), but wasn't explicitly verified.

UNEXPLORED: **MCP connection pooling in batch context.** If a sub-workflow uses MCP nodes, each compilation creates new MCP connection setup. With compile-once, would a single connection be reused across items? This could be both a performance win (connection reuse) and a correctness concern (connection state).

CONSIDER: **The `__only_node__` parameter.** It's in `initial_params` and affects compilation structurally (monkey-patches `flow.get_next_node`). This is the ONE case where `initial_params` does affect structure. A compile-once approach needs to handle this — but `__only_node__` is a CLI flag that's constant per invocation, not per-item, so it should be fine.

CONSIDER: **Template validation in compile-once mode.** `validate_workflow_templates()` runs during `_validate_workflow()` and uses `initial_params` as `available_params`. Without per-item values, template validation might report false positives ("variable ${text} has no valid source"). Should template validation be deferred to runtime, or should it validate against declared input names (not values)?

MIGHT MATTER: **The trace collector is per-compilation.** `compile_ir_to_flow()` receives a `trace_collector` parameter. With compile-once, all items would share the same collector unless we create per-item collectors differently. WorkflowExecutor already creates child trace collectors per exec() call — this pattern would need adaptation.

MIGHT MATTER: **Registry freshness warning.** The runtime CLAUDE.md says "always pass a new one to `compile_ir_to_flow()` per execution." With compile-once, the registry is baked into the compiled flow. If registry contents change between items (unlikely but possible with dynamic MCP discovery), the cached flow could be stale.

## What I'd Tell Myself

1. **Don't over-broaden scope when the user narrows it.** Early on I expanded from "compile errors in batches" to "all structural failures in all node types." The user correctly pulled me back: "the problem is compile errors, not all structural failures." Follow their lead.

2. **The user thinks architecturally.** They're not looking for the minimal fix — they want to understand the design and fix root causes. Present options with architectural implications, not just code changes.

3. **Measure before optimizing.** I almost designed a compile-once solution without measuring the actual cost. The 20-50ms measurements gave concrete justification and will be needed to verify the fix works.

4. **The `initial_params` duplication is THE key insight.** Everything else is downstream. If you're explaining the compile-once problem to someone, start here: per-item data is in two places, one of them is baked into the compiled flow, and the baked version wins at resolution time.

5. **The user said "framed as exploratory not set in stone."** They explicitly don't want a prescriptive implementation plan. They want options investigated and a recommendation proposed. Don't jump to implementation.

## Open Threads

### Compile-Once: Three Approaches Not Yet Prototyped

**Path A** (pflow-level caching): Cache compiled flow in WorkflowExecutor, deep-copy per item, compile without per-item `initial_params`. Requires splitting `_validate_workflow()`.

**Path B** (PocketFlow alignment): Use BatchFlow pattern — revert `_orch()` hack, make `set_params()` work for both compile-time and runtime params. Largest scope but cleanest result.

**Path C** (modified PocketFlow): Add new primitive to PocketFlow for compile-once. The user said PocketFlow can be modified freely — "using pocketflow as is has no intrinsic value."

None of these have been prototyped. The task is to explore, not implement.

### `successful_results` (#159) — Design Decision Pending

We decided on additive `successful_results` field (not filtering `results` in-place) due to index alignment dependencies. Plus a downstream warning when consuming `results` from a degraded upstream. Not yet implemented.

### Unify CompilationError (#155) — Full Inventory Done

25 raise sites, 14 catch sites, 21 test assertions on `str()` format. The dead `user_errors.CompilationError` can be safely removed. Making the compiler version inherit from `UserFriendlyError` would eliminate dual codepaths in `workflow_errors.py`. Estimated ~150 lines across 12 files.

## Relevant Files & References

**The 3 commits from this session:**
- `e45bba0d` — CompilationError propagation + structured error display (#153, #154)
- `52d9057b` — All-fail batch aborts (#157)
- `b5cda093` — Empty batch warning (#160)

**GitHub issues created:**
- #153: compile error swallowed by error_handling: continue (closed)
- #154: CompilationError loses structured fields in display (closed)
- #155: unify two CompilationError classes (open, comprehensive)
- #157: all-fail batch continues on garbage (closed)
- #159: successful_results field + downstream warning (open, comprehensive)
- #160: empty batch silent SUCCESS (closed)

**Key files for Task 135 exploration:**
- `src/pflow/pocketflow/__init__.py` — the ~200 line core, especially `_orch()` and `BatchFlow`
- `src/pflow/pocketflow/PFLOW_MODIFICATIONS.md` — documents the divergence
- `src/pflow/runtime/wrappers/template_wrapper.py:442-464` — `_build_resolution_context()` (the `initial_params` priority)
- `src/pflow/runtime/wrappers/batch_node.py` — `PflowBatchNode`, recently modified
- `src/pflow/runtime/workflow_executor.py` — `_compile_sub_workflow()`, recently modified
- `src/pflow/runtime/compilation/compile_validation.py:160-245` — `_validate_workflow()` (the 5-step validation that needs splitting)

**Memory saved:**
- `~/.claude/projects/-Users-andfal-projects-pflow/memory/project_batch_compile_once.md`

**Scratchpad with test workflows:**
- `scratchpads/batch-error-handling-compile-vs-runtime/` — bug report + 6 test workflow files

## For the Next Agent

**Start by** reading `PFLOW_MODIFICATIONS.md` and `pocketflow/__init__.py` to understand the current divergence. Then read `template_wrapper.py:_build_resolution_context()` to understand why `initial_params` blocks compile-once.

**Don't bother with** the batch error handling fixes — those are done and tested. The 3 commits are solid.

**The user cares most about** clean architecture, not quick fixes. They'll accept incremental progress but they want the exploration to be thorough. They explicitly said "exploratory, not set in stone."

**Key question to answer first**: Can `_validate_workflow()` be split so structural validation runs at compile time and input validation runs at runtime? This is the smallest blocker to unblock compile-once. If yes, Path A (caching) becomes straightforward. If no, you need Path B (full alignment).

**Watch out for**: the `set_params()` behavior in `TemplateAwareNodeWrapper`. It splits params into template/static at call time. If you try to use BatchFlow's param-passing (which calls `set_params()` per iteration), you need to understand whether this split works correctly when called multiple times with different params.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
