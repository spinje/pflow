# Historical Knowledge: Pre-Task 135 (Execution Core Redesign)

These entries were moved from the active knowledge base after Task 135 replaced the wrapper chain with an orchestration engine and removed PocketFlow's `Flow`, `BatchFlow`, and async classes. The entries describe the system as it was before March 2026.

For the current architecture, see:
- `src/pflow/runtime/engine/CLAUDE.md` — execution engine
- `src/pflow/runtime/compilation/CLAUDE.md` — compilation pipeline
- `.taskmaster/tasks/task_135/task-review.md` — full redesign context

---

## Decision: Use PocketFlow for Internal Orchestration (SUPERSEDED)
- **Date**: 2025-06-29
- **Made during**: Architecture analysis before task implementation
- **Status**: Superseded — first by "Limit PocketFlow Internal Usage to Natural Language Planner Only", then by Task 92 (planner removed), then by Task 135 (PocketFlow slimmed to BaseNode + Node, Flow removed)
- **Original context**: Decided to use PocketFlow internally for pflow's own implementation for 6 tasks. Later narrowed to Task 17 only. Task 17 (planner) was removed in Task 92. Task 135 removed Flow entirely.

---

## Decision: Limit PocketFlow Internal Usage to Natural Language Planner Only (SUPERSEDED)
- **Date**: 2025-06-29
- **Made during**: Post-implementation architecture review
- **Status**: Superseded — Task 92 removed the planner. Task 135 removed Flow from PocketFlow entirely.
- **Original context**: Narrowed PocketFlow usage from 6 tasks to Task 17 only. Task 17 was subsequently removed. PocketFlow now provides only `BaseNode` and `Node` (lifecycle + retry) — all execution orchestration is handled by `WorkflowEngine`.

---

## Decision: Modify PocketFlow Instead of Using Wrapper for Parameter Handling (SUPERSEDED)
- **Date**: 2025-01-07
- **Made during**: Task 3 (Execute a Hardcoded 'Hello World' Workflow)
- **Status**: Superseded by Task 135 — `Flow._orch()` was removed entirely along with `Flow` class. The `if params is not None: curr.set_params(p)` hack no longer exists. The engine handles parameter setting directly via `node.params = resolved_params`.
- **Original context**: PocketFlow's `Flow._orch()` overwrote node parameters with flow parameters. A conditional guard was added to prevent this. This hack was the first in a chain: it blocked BatchFlow, which led to PflowBatchNode reimplementing batch from scratch, which led to per-item recompilation. Task 135 eliminated the entire chain by removing Flow and replacing it with an orchestration engine.
- **Deep dive preserved**: `decision-deep-dives/pocketflow-parameter-handling/` (historical)

---

## Decision: Template Variable Resolution Using Proxy Pattern (SUPERSEDED)
- **Date**: 2025-07-19
- **Made during**: Task 17 (Natural Language Planner)
- **Status**: Superseded by Task 135 — template resolution is now a standalone function (`engine/template_resolution.py:resolve_templates()`) called by the engine, not a node wrapper proxy. The concept (runtime template resolution against shared store) is the same; the mechanism changed from wrapper interception to engine orchestration.
- **Original context**: Decided to use a `TemplateAwareNodeWrapper` proxy that intercepted `_run()` to resolve templates. This was correct for the wrapper-chain architecture. After Task 135, the wrapper is gone and resolution is a direct function call in `WorkflowEngine._execute_node()`.

---

## Pattern: PocketFlow for Complex AI Orchestration (Task 17 Only) (REMOVED)
- **Date**: 2025-06-29
- **Removed**: 2026-03-31
- **Reason**: Task 17 (Natural Language Planner) was removed in Task 92. PocketFlow is no longer used for orchestration — it provides only `BaseNode` and `Node`. The execution engine handles all orchestration.

---

## Pattern: Shared Store Proxy for Incompatible Nodes (REMOVED)
- **Date**: 2024-01-15
- **Removed**: 2026-03-31
- **Reason**: Example pattern. pflow uses template variables (`${node.output}`) for inter-node data flow, not proxy translator nodes. The pattern described a concept that was never used in the codebase.

---

## Decision Deep Dive: PocketFlow Parameter Handling (HISTORICAL)

The `decision-deep-dives/pocketflow-parameter-handling/` directory documents the investigation into PocketFlow's `_orch()` parameter overwriting behavior and the decision to modify it with a conditional guard. This investigation is historically interesting as the origin of the "hack chain" that Task 135 ultimately eliminated:

1. `_orch()` hack → blocked BatchFlow
2. Blocked BatchFlow → PflowBatchNode reimplemented batch
3. Reimplemented batch → per-item recompilation
4. Per-item recompilation → `initial_params` dual-data-path
5. Dual-data-path → every downstream template resolution hack

The solution (Task 135) was to remove `Flow` entirely and replace it with `WorkflowEngine`, making the hack and all its consequences irrelevant.
