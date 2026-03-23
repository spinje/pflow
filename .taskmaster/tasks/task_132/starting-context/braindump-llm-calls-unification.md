# Braindump: Unify LLM Data via Trace Collector

## Where I Am

This task was created at the tail end of a deep Task 108 planning session. The user and I spent hours designing the tree-structured trace format (2.0.0) and the execution report system. Task 132 fell out of that discussion naturally — while reviewing the implementing agent's code for `_PROPAGATED_KEYS`, the user noticed `__llm_calls__` sitting next to the new `_trace_collector` and asked "what are we using llm calls for?" This question surfaced a clean future simplification.

Task 132 is NOT urgent. It's a cleanup task that can only happen after Task 108 Phase 1 is stable and proven. The task file captures the scope accurately.

## User's Mental Model

The user consistently pushes for **single sources of truth** and **eliminating redundancy**. Throughout the Task 108 discussion:

- When I proposed both truncation AND full-fidelity modes, they asked "maybe the easiest is just to not truncate at all anywhere?"
- When I proposed both `shared_before`/`shared_after` AND focused fields, they asked "how should we think about shared_before/shared_after?" and then immediately saw that mutations + node_output could reconstruct state — "if needed the mutations can be used to compute the state of shared store at any given point right?"
- When they saw `__llm_calls__` next to `_trace_collector` in `_PROPAGATED_KEYS`, their instinct was "can we use the trace collector for cost display at a later refactor?"

The pattern: the user spots duplication/redundancy and wants to collapse it to the simplest correct form. They're not afraid of refactoring ("we shouldnt be afraid to refactor if the endresult is better AND more simple code and simple to reason about").

They also care about **naming consistency** — they immediately caught that `_trace_collector` uses single underscore while everything else in `_PROPAGATED_KEYS` uses `__dunder__` convention.

## Key Insights

### 1. The `--no-trace` Problem Is the Real Design Challenge

The task file mentions this but it deserves emphasis. Currently:
- `--no-trace` → no `WorkflowTraceCollector` created → no trace file saved
- But `__llm_calls__` still works (it's just a list in the shared store, independent of trace)
- CLI cost display reads from `__llm_calls__` regardless of `--no-trace`

If we remove `__llm_calls__` and make the trace collector the source:
- `--no-trace` → no collector → no LLM data → no cost display

**Two solutions discussed:**
1. **Always create a collector** — even with `--no-trace`, create a lightweight collector that accumulates data but doesn't save to file. `--no-trace` becomes "don't save trace file" not "don't collect trace data."
2. **Keep a minimal accumulator as fallback** — defeats the purpose of the refactor.

I recommended option 1 but the user didn't explicitly decide. The next agent should surface this decision.

### 2. The Naming Convention Should Be Resolved in Task 108, Not Here

During review, the user spotted that `_trace_collector` in `_PROPAGATED_KEYS` uses single underscore while all others use `__dunder__`. I recommended changing to `__trace_collector__` for consistency. This should be fixed in Task 108's implementation, not deferred to Task 132. If the implementing agent already used `_trace_collector`, it should be renamed before Task 108 merges.

### 3. `_collect_llm_summary()` Must Be Proven Before This Task

Task 108 adds `_collect_llm_summary()` which recursively scans the tree-structured trace events to count LLM calls, tokens, and models. This is the replacement for `__llm_calls__`-based summary computation. If it has bugs or misses edge cases (parallel batch items, deeply nested sub-workflows), Task 132 would amplify those bugs by making it the only path.

**NEEDS VERIFICATION**: Run a complex workflow (batch + sub-workflows) with Task 108's new trace format and compare `_collect_llm_summary()` output against the `__llm_calls__`-based summary. They should match exactly.

### 4. MetricsCollector Is Currently Independent

`MetricsCollector` (`src/pflow/core/metrics.py`) and `WorkflowTraceCollector` are separate, independent collectors. They're both injected into `InstrumentedNodeWrapper` as separate parameters. `MetricsCollector` records per-node timing; it also reads `__llm_calls__` for cost data.

For Task 132, MetricsCollector would need access to the trace collector. Options:
- Pass trace collector to MetricsCollector (creates coupling)
- Have MetricsCollector read from shared store's `_trace_collector` key
- Merge MetricsCollector into trace collector (bigger refactor)

**UNCLEAR**: What does MetricsCollector actually DO with LLM data that the trace collector doesn't? If they're redundant, maybe Task 132 should also merge MetricsCollector into the trace collector. But this wasn't discussed.

## Assumptions & Uncertainties

**ASSUMPTION**: The user wants this as a cleanup task, not a priority. They said "lets create 132" almost as an afterthought while reviewing Task 108 code.

**ASSUMPTION**: `_collect_llm_summary()` in the tree trace will produce identical results to the `__llm_calls__`-based approach. This hasn't been tested.

**UNCLEAR**: Whether `MetricsCollector` should be merged into the trace collector or remain separate. The user didn't discuss this.

**UNCLEAR**: The exact mechanism for the `--no-trace` case. Option 1 (always create collector) changes the semantics of `--no-trace`. The user might have opinions.

**NEEDS VERIFICATION**: What code paths in the execution layer read from `__llm_calls__`? The task file lists some but there might be others. Search for `__llm_calls__` across the entire codebase before implementing.

## Unexplored Territory

**UNEXPLORED**: Does anything WRITE to `__llm_calls__` besides `InstrumentedNodeWrapper._capture_llm_usage()` and `batch_node._capture_item_llm_usage()`? If other code writes to it, those writers also need updating.

**CONSIDER**: The `__llm_calls__` list also stores the `prompt` text for some entries (via `_find_llm_prompt()`'s fallback path). If we remove `__llm_calls__`, that prompt discovery path disappears. But with Task 108's `template_resolutions`, prompts are captured elsewhere, so this should be fine.

**MIGHT MATTER**: The `__llm_calls__` entries include `batch_item_index` — this links LLM calls to specific batch items. The trace events' `llm_call` field on batch items captures this implicitly (the event IS the batch item). But if anything reads `batch_item_index` from `__llm_calls__`, it would need to be updated.

**CONSIDER**: If `--no-trace` creates a lightweight collector that never saves, should it also skip LLM interception? Currently `--no-trace` means no collector at all, so no interception. If we always create a collector, interception would always be active. The monkey-patching of `llm.get_model()` has a small performance overhead.

## What I'd Tell Myself

1. **Don't start this until Task 108 Phase 1 has been running in real workflows for a while.** The tree trace needs to be proven correct, especially `_collect_llm_summary()` across batch items and nested sub-workflows.

2. **The user values simplicity over cleverness.** Don't propose a complex migration path. Just remove `__llm_calls__`, update consumers, handle `--no-trace`. Three steps.

3. **Search for ALL references to `__llm_calls__` before planning.** There are likely 15-20 references scattered across runtime, execution, CLI, formatters, and tests. Map them all.

4. **The `--no-trace` decision is the gate.** Everything else is straightforward plumbing. But "always create a collector" vs "fallback accumulator" changes the architecture. Get the user's input on this before implementing.

## Relevant Files & References

**Task 108 plan** (the source of this task): `~/.claude/plans/mutable-pondering-badger.md`

**Task 108 progress log** (full context): `.taskmaster/tasks/task_108/implementation/progress-log.md`

**Key code to study before implementing:**
- `src/pflow/runtime/workflow_trace.py` — `_collect_llm_summary()`, `save_to_file(llm_calls=...)`, `setup_llm_interception()`
- `src/pflow/runtime/wrappers/instrumented_wrapper.py` — `_capture_llm_usage()`, `_initialize_execution_state()` (creates `__llm_calls__` list)
- `src/pflow/runtime/wrappers/batch_node.py` — `_capture_item_llm_usage()`, `prep()` (ensures `__llm_calls__` exists)
- `src/pflow/core/metrics.py` — `MetricsCollector` and how it uses LLM data
- `src/pflow/execution/formatters/success_formatter.py` — `format_execution_success()` reads LLM cost data
- `src/pflow/cli/workflow_output.py` — `_display_execution_summary()` shows cost
- `src/pflow/execution/executor_service.py:101-102` — injects `_trace_collector` into shared store
- `src/pflow/runtime/workflow_executor.py:67-73` — `_PROPAGATED_KEYS` (where `__llm_calls__` lives)

## For the Next Agent

**Start by**: Running `grep -r "__llm_calls__" src/pflow/` to map every reference. Build a complete picture of who writes, who reads, and who propagates before changing anything.

**Don't bother with**: Reading the Task 108 spec documents in `.taskmaster/tasks/task_108/starting-context/` — they're about the execution report feature, not this cleanup. The task-132.md file and this braindump have everything you need.

**The user cares most about**: Simplicity and single sources of truth. They don't want two parallel data paths for the same information.

**Key decision to surface with user**: The `--no-trace` case. Ask: "Should `--no-trace` mean 'don't save trace file' or 'don't collect any trace data'? If we always create a lightweight collector, LLM cost display works everywhere. If not, we need a fallback."

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
