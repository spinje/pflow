# Task 108: Smart Trace Debug Output — Implementation Progress Log

## Phase 1: Trace Enrichment + Report Generator

### Implementation Plan

Full plan: `~/.claude/plans/mutable-pondering-badger.md`

### Ordered Implementation Steps

1. **Trace format redesign** (`workflow_trace.py`)
   - New `record_node_execution()` signature (remove `shared_before`/`shared_after`, add `node_params`/`template_resolutions`/`node_output`/`mutations`/`batch_items`/`sub_workflow_events`)
   - Replace `_filter_shared()` with `_sanitize_for_json()` (key hygiene only, no truncation)
   - Remove `_build_base_event()`, `_calculate_mutations()`, truncation methods
   - Simplify `_add_llm_data()` to read from `node_output` directly
   - Update `save_to_file()` — remove `llm_calls` param, add recursive `_collect_llm_summary()`
   - Add `enable_llm_interception` flag for child collectors
   - Fix `_current_node` threading bug with `threading.local()`
   - Bump format to 2.0.0

2. **Template resolution capture** (`template_wrapper.py`)
   - Add `last_resolutions` attribute to `TemplateAwareNodeWrapper`
   - Add `"last_resolutions"` to `wrapper_attrs` set (critical `__setattr__` gotcha)
   - Populate after resolution loop completes in `_run()`

3. **Instrumented wrapper refactor** (`instrumented_wrapper.py`)
   - Replace full `shared_before`/`shared_after` snapshots with focused fields
   - Add `_find_template_wrapper()` — traverse chain to read `last_resolutions`
   - Add `_find_batch_or_workflow_node()` — traverse chain for tree data
   - Rewrite `_record_trace()` with new parameters

4. **Batch item tracing** (`batch_node.py`)
   - Init `_batch_trace` accumulator in `prep()` (follows `__llm_calls__` pattern)
   - Add `_capture_item_trace()` method
   - Call from both `_exec_single()` and `_exec_single_with_node()` (with `node_chain` param for parallel)
   - Store `_trace_items` in `post()` for `InstrumentedNodeWrapper` to read

5. **Sub-workflow trace propagation** (`workflow_executor.py` + `executor_service.py`)
   - Add `_trace_collector` to `_PROPAGATED_KEYS`
   - Create child `WorkflowTraceCollector` in `exec()` with `enable_llm_interception=False`
   - Pass child collector to `compile_ir_to_flow()`
   - Store `_child_trace_events` after child execution
   - Inject `_trace_collector` into shared store in `executor_service.py`

6. **CLI changes** (`cli/main.py`)
   - Add `--report` flag to `workflow_command`
   - Move trace save to `finally` block (remove 4 scattered save calls)
   - Call report generator after trace save when `--report` is active

7. **Report generator** (NEW: `core/trace_report.py`)
   - `generate_report(trace_path, output_path)` — main entry
   - Recursive tree walk: `_write_node_files()`
   - Per-node markdown: `_build_node_file()`
   - Summaries at each level: `_build_summary()`, `_build_node_summary()`
   - Batch item files: `_build_batch_item_file()`, `_build_batch_item_summary()`

8. **Post-hoc CLI command** (NEW: `cli/commands/trace.py`)
   - `pflow trace report [trace-path]` command
   - Auto-detect latest trace if no path given

9. **Test updates** (17 existing tests + new tests)
   - Update `test_workflow_trace.py` (~13 tests)
   - Update `test_metrics_integration.py` (~1 test)
   - Update `test_instrumented_wrapper.py` (~2 tests)
   - Update `test_batch_node.py` (~1 test)
   - Write new tests for template resolution capture, batch trace, sub-workflow propagation, report generator

10. **Verification**
    - `make check` + `make test`
    - Manual test with simple workflow + `--report`
    - Manual test with batch workflow
    - Post-hoc `pflow trace report`
    - Ctrl+C produces trace file

---

## Context: Why This Feature Exists

### The Origin Story

An AI agent spent 5 sessions building a complex lyrics-generation pipeline in pflow (11 orchestrator nodes, sub-workflows, ~233 LLM calls per run, ~$1.58/run). During debugging, the agent filed a false bug report because it couldn't see the data flow — it guessed at the cause instead of observing actual behavior. This revealed a fundamental observability gap: **agents can't see what happened inside workflow execution without manually parsing 500KB+ trace JSON files.**

The agent built an 80-line custom Python node just to save every pipeline stage as readable markdown files — this custom output system became its ONLY debugging tool. The 2.7MB trace JSON was never opened once across 5 sessions.

### The Core Problem

> "The problem: There was no error. The workflow 'succeeded' with wrong output. So it's not about error messages — it's about visibility."

1. Agents can't see rendered prompts (what the LLM actually received)
2. Batch item results are opaque — you can't see per-item prompts/responses
3. Sub-workflow internals are invisible in traces
4. Trace files are too dense for agents to consume
5. Every workflow wanting visibility must build custom output code

### Two Visions — We Chose Vision B

**Vision A (Original Task 108)**: Post-execution smart debug — analyze what went wrong, single focused markdown file, error classification, anomaly detection. Trigger: `pflow trace debug`.

**Vision B (Execution Report)**: Full pipeline visibility — see everything that happened at every step in readable format. Directory of markdown files mirroring workflow structure. Trigger: `--report` flag or post-hoc from trace.

**User's opening message aligned with Vision B**: "you can SEE the results of a workflows internal steps and UNDERSTAND the relationship of an llm nodes input and its output."

**Decision**: Build Vision B (execution report) first. Vision A's smart analysis (error classification, anomaly detection, suggested fixes) becomes Phase 2/3 — diagnostics sections embedded in Vision B's summary files.

---

## Key Design Decisions (With Rationale)

### 1. Tree-Structured Trace (Format 2.0.0)

**Decision**: Trace events are nested (batch items contain per-item events, workflow nodes contain child events) rather than flat with metadata.

**Rationale**: A workflow execution IS a tree. The trace, the report directory, and the execution structure should all have the same shape. Flat traces with metadata (Option C) push reconstruction complexity to every consumer. Tree structure makes the report generator a trivial recursive walk.

**Three options were evaluated**:
- Option A: Flat events, same collector for parent+child (loses hierarchy)
- Option B: Nested events, child collectors per sub-workflow (preserves structure) ← CHOSEN
- Option C: Flat events with metadata (depth, stack) for reconstruction

### 2. Replace `shared_before`/`shared_after` with Focused Fields

**Decision**: Remove full shared store snapshots from trace events. Replace with `node_output` (what this node wrote), `template_resolutions` (what this node consumed, before/after), `node_params` (original config), and `mutations` (what keys changed).

**Rationale**: `shared_before` for node N contains ALL outputs from nodes 1..N-1 — O(n^2) data growth. This was the root cause of needing truncation. The report doesn't need full state dumps — it needs what this specific node saw and produced.

**State reconstruction**: If needed, full shared store state at any point is reconstructable by accumulating `node_output` dicts: `state_at_N = {event["node_id"]: event["node_output"] for event in trace["nodes"][:N+1]}`. This works because nodes write to namespaced keys.

**Tradeoff**: We lose `modified` detection in mutations (which required comparing values in before/after snapshots). Acceptable — the report cares about what each node produced, not which existing keys changed.

### 3. No Truncation Anywhere

**Decision**: Remove all value truncation from traces. Keep only internal key filtering (strip `_trace_collector`, dunder system keys) and binary data replacement.

**Rationale**: We have no users yet. Trace files are local temp files in `~/.pflow/debug/`. Nobody reads the JSON directly — the report is what they read. If trace files become too large, truncation is trivial to add back. Premature optimization isn't worth the complexity (env vars, configurable thresholds, `_truncated` field name variants).

### 4. Keep LLM Interception (Don't Remove)

**Decision**: Keep the existing LLM interception monkey-patch for top-level workflows. Child collectors for sub-workflows skip interception. Fix concurrency bugs with `threading.local()`.

**Rationale**: Initially considered removing interception entirely and relying on template_resolutions. But:
- LLM interception captures **ground truth** (the actual string passed to `model.prompt()`)
- Verified that LLM node does NOT modify the prompt — so template_resolutions is equivalent, but ground truth is a safety net
- The concurrency bugs are fixable with ~15 lines of targeted changes, not a redesign
- For sub-workflow LLM nodes, template_resolutions provides the same data (verified)

### 5. `--report` Flag (Not Always-On)

**Decision**: Report generation is opt-in via `--report` flag. Users can also generate post-hoc from any trace via `pflow trace report`.

**Rationale**: Reports create files the user didn't ask for. Since they can always generate from trace post-hoc, they don't lose anything by not using `--report`.

### 6. Phased Implementation

**Three phases planned** (Phase 1 is what we're implementing now):
- **Phase 1**: Trace enrichment + hierarchical report generator (this plan)
- **Phase 2**: Smart analysis — error classification, anomaly detection, suggested fixes, diagnostics in summary.md
- **Phase 3**: Post-hoc CLI, MCP tool, agent instruction updates, deprecate analyze.py

### 7. Relationship to Task 106 (Iteration Cache)

Task 108 (Report) and Task 106 (Cache) are deeply complementary:
- **Cache** makes iteration FASTER — skip unchanged nodes on re-run
- **Report** makes results UNDERSTANDABLE — see what each node saw and produced
- **Together**: Edit prompt → re-run (cached upstream, re-execute downstream) → read report (focus on re-executed nodes) → iterate

The report should mark cached vs re-executed nodes (Phase 2 prep). If the cache stores rendered prompts, the report can show them for cached nodes.

---

## Critical Implementation Insights

### Verified via Codebase Research

1. **Wrapper chain order**: `InstrumentedNodeWrapper` → `PflowBatchNode` → `NamespacedNodeWrapper` → `TemplateAwareNodeWrapper` → `ActualNode`. Assembled in `compiler.py:_create_single_node()` lines 235-408.

2. **Trace collector flow**: CLI creates it → `compile_ir_to_flow(trace_collector=tc)` → `_create_single_node()` → `InstrumentedNodeWrapper(trace=tc)`. It flows through compilation, NOT the shared store (currently). We're adding shared store propagation for sub-workflows.

3. **`InstrumentedNodeWrapper.__deepcopy__`** (line 797-811): `self.metrics` and `self.trace` are shared by reference, NOT deep-copied. This is intentional — collectors aggregate across all copies. Same behavior we need for batch items.

4. **Batch parallel execution**: `PflowBatchNode._exec_parallel()` creates `ThreadPoolExecutor`, deep-copies the inner node chain per thread. `item_shared = dict(self._shared)` is a shallow copy — mutable objects like `__llm_calls__` (a list) are shared by reference across threads. GIL protects `list.append()`.

5. **`_exec_single_with_node()` has `thread_node` in scope** after `_run()` completes. We CAN traverse it to read `last_resolutions` before the function returns and the deep-copied chain is discarded.

6. **Sub-workflow `_PROPAGATED_KEYS`**: `("__registry__", "__llm_calls__", "__progress_callback__", "__mcp_pool__", "__warnings__")`. These are object references (not deep copies) — child appends to `__llm_calls__` are visible to parent. We add `_trace_collector` to this list.

7. **`WorkflowExecutor.exec()` calls `compile_ir_to_flow()` WITHOUT `trace_collector`** (line 128-133). This is the gap we're fixing — child nodes currently have `self.trace = None`.

8. **External file references** (Task 129): File paths like `- prompt: ./file.prompt.md` are replaced with file content during compilation in `file_resolver.py:resolve_file_references()`. By the time template resolution runs, `params["prompt"]` contains the full text with `${var}` templates. So `template_resolutions` captures the fully rendered content.

9. **LLM interception monkey-patches `llm.get_model()` globally**. Uses `_active_collectors: ClassVar[dict[int, WorkflowTraceCollector]]` mapping `thread_id → collector`. The `_current_node` attribute on the collector instance is NOT thread-safe. Fix: `threading.local()`.

10. **Conditional branches** (Task 38): Skipped nodes never execute, never appear in trace. The report only shows what ran. No action needed.

11. **`finally` block + SIGINT**: `sys.exit(130)` raises `SystemExit` (inherits from `BaseException`, not `Exception`). The `except Exception` clause does NOT catch it. The `finally` block DOES execute. `workflow_trace` is in scope (assigned before `try`). `save_to_file()` works with partial data.

12. **Trace save is scattered across 4 handlers** in `main.py` (lines 218, 247, 294, 487). Consolidating to `finally` eliminates all 4 and handles the SIGINT gap.

### Critical Gotchas for Implementer

1. **`TemplateAwareNodeWrapper.__setattr__`** (line 676-694): `wrapper_attrs` set at line 687 only contains `{"inner_node", "node_id", "initial_params", "template_params", "static_params"}`. Any new attribute (like `last_resolutions`) MUST be added to this set, or `self.last_resolutions = ...` silently sets the attribute on `self.inner_node` instead.

2. **`_exec_single_with_node` vs `_exec_single`**: The parallel path receives `thread_node` (deep-copied chain) as a parameter. The sequential path uses `self.inner_node`. The `_capture_item_trace()` method needs a `node_chain` parameter to traverse the correct chain.

3. **`_batch_trace` key naming**: Use `_batch_trace` (single underscore), NOT `__batch_trace__` (double underscore). The `_sanitize_for_json()` method strips dunder keys. Single-underscore keys starting with `_trace` or `_debug` are also stripped — so use `_batch_trace` and add it to the allowlist in `_sanitize_for_json`, OR better: let the batch node store `_trace_items` directly on itself (an instance attribute) and have InstrumentedNodeWrapper read it via chain traversal.

4. **`TemplateAwareNodeWrapper._run()` early return** (line 508-509): When `not self.template_params`, the method returns early without going through the resolution loop. In this case, `last_resolutions` stays as `{}` from init — correct behavior (no templates = no resolutions).

5. **`node_output` capture timing**: `InstrumentedNodeWrapper._record_trace()` runs AFTER `self.inner_node._run(shared)` returns. At this point, `shared[self.node_id]` contains the node's output. But `TemplateAwareNodeWrapper` has already restored original params (line 654). So `_get_node_params()` returns original (unresolved) params — which is what we want for `node_params`. The resolved values come from `template_resolutions`.

6. **`record_node_execution` backward compatibility**: If any code calls the old signature with `shared_before`/`shared_after` positional args, it will break. Search for all call sites. Current callers: `InstrumentedNodeWrapper._record_trace()` (line 414) and tests.

### Known Gaps (Documented, Out of Scope)

- **Claude Code node** (`claude_code.py`): Uses `claude_agent_sdk`, not `llm` library. LLM interception doesn't capture its prompts. The node modifies the prompt when `output_schema` is set. Template resolution captures `params["prompt"]` (the unmodified input) but not the actual modified prompt sent to Claude. Document this gap.

- **`_current_node` race condition**: In parallel batch with LLM nodes, multiple threads share the same collector and overwrite `_current_node`. Works by accident because all items use the same `node_id`. The `threading.local()` fix addresses this, but for sub-workflow batch items, child collectors skip interception entirely (prompts come from template_resolutions).

- **`modified` in mutations**: We lose value-change detection since we no longer take full shared store snapshots. Only key additions and removals are tracked. This is acceptable — the report cares about what each node produced, not which existing values changed.

---

## Existing Documents (Reference)

These documents were read and analyzed during planning. Note they may contain outdated information (written Jan 2026, codebase has changed significantly since):

- `.taskmaster/tasks/task_108/starting-context/braindump-inline-debug-discovery.md` — Origin story (false bug report due to poor observability)
- `.taskmaster/tasks/task_108/starting-context/braindump-stderr-visibility-overlap.md` — Stderr fix is complementary, not overlapping
- `.taskmaster/tasks/task_108/starting-context/braindump-task-creation.md` — Task creation reasoning and design decisions
- `.taskmaster/tasks/task_108/starting-context/research-inline-debug-flag.md` — `--debug` flag proposal (lighter than what we're building)
- `.taskmaster/tasks/task_108/starting-context/task-108-spec.md` — Full Q&A spec (23 design decisions, partially outdated)
- `.taskmaster/tasks/task_108/task-108.md` — Formal task definition
- `.taskmaster/tasks/task_108/research/pflow-execution-report-agent-perspective.md` — Agent user's perspective (most insightful doc)
- `.taskmaster/tasks/task_108/research/pflow-execution-report-feature-request.md` — Full execution report feature request with directory layout
- `.taskmaster/tasks/task_106/starting-context/pflow-iteration-cache-agent-perspective.md` — Task 106 relationship

---

## Plan Corrections (discovered during review)

### 1. `executor_service.py` already injects `_trace_collector`

At `executor_service.py:99-102`, the trace collector is already injected into the shared store:
```python
# Store trace collector reference for sub-workflow propagation
# (picked up by _PROPAGATED_KEYS in WorkflowExecutor._create_child_storage)
if trace_collector:
    shared_store["_trace_collector"] = trace_collector
```

The comment even mentions `_PROPAGATED_KEYS`! Someone already planned for this. The only missing piece is adding `"_trace_collector"` to the `_PROPAGATED_KEYS` tuple in `WorkflowExecutor`.

**Plan correction**: Remove `executor_service.py` from "Files Modified" — no changes needed there.

### 2. `trace_report.py` and `trace.py` already exist

Both `src/pflow/core/trace_report.py` (report generator) and `src/pflow/cli/commands/trace.py` (CLI command) already exist with the report generator code and the `pflow trace report` command. The routing in `main_wrapper.py` already handles the `trace` subcommand.

**Plan correction**: These are "Files to Update" not "New Files to Create". The report generator needs updating as the trace format evolves, but the skeleton is in place.

### 3. `--report` + `--no-trace` interaction

Not addressed in the plan. If `--no-trace` is used, no trace is generated, so `--report` can't work.

**Decision needed**: `--report` should imply tracing. If both `--report` and `--no-trace` are passed, either error or silently enable tracing. Recommendation: `--report` overrides `--no-trace` with a warning message.

### 4. `save_to_file()` `llm_calls` parameter — keep as fallback

The plan says to remove the `llm_calls` parameter and compute LLM summary from events recursively. But during incremental implementation, batch items and sub-workflows won't have trace events until steps 4-5 are complete. The `__llm_calls__` accumulator (propagated via shared store) is the only way to get sub-workflow LLM data until then.

**Plan correction**: Keep `llm_calls` parameter as optional fallback. When provided (current behavior), use it for `llm_summary`. When not provided, fall back to recursive event scanning. This allows incremental implementation without breaking LLM summaries.

### 5. Old trace format (1.2.0) handling in report generator

The report generator reads `node_output`, `template_resolutions` etc. which don't exist in old traces. It should check `format_version` and either:
- Gracefully degrade (show what's available from old format)
- Error with a clear message ("trace format 1.2.0 not supported, need 2.0.0+")

**Recommendation**: Error with clear message. Old traces can't produce useful reports without the enriched data.

### 6. `_batch_trace` accumulator vs `_trace_items` instance attribute

The plan describes two approaches and is inconsistent:
- `_batch_trace` key in shared store (shared mutable list pattern)
- `_trace_items` instance attribute on `PflowBatchNode`

**Clarification**: Use the shared store pattern (`_batch_trace` key) for COLLECTING events during parallel execution (GIL-safe appends from threads). Then in `post()`, transfer to `self._trace_items` instance attribute for `InstrumentedNodeWrapper` to read via chain traversal. The shared store key is cleaned up after transfer.

---

## Full Phase Plan (All Three Phases)

### Phase 1: Trace Enrichment + Hierarchical Report (THIS IMPLEMENTATION)

See implementation steps above. Delivers:
- Tree-structured trace format 2.0.0
- Per-node `template_resolutions`, `node_params`, `node_output`
- Per-batch-item trace events
- Sub-workflow internal node visibility
- `--report` flag → directory of .md files
- `pflow trace report` post-hoc generation

### Phase 2: Smart Analysis + Diagnostics

*Goal: Summaries tell you what's wrong, not just what happened*

- **Error classification rules** in summary.md diagnostics section:
  - Template errors (unresolved variables, wrong paths)
  - HTTP/API errors (4xx/5xx, auth failures)
  - Shell errors (exit codes, stderr)
  - LLM errors (model/API failures)
  - Timeout detection
  - MCP errors (server connection, tool not found)
- **Anomaly detection** (flags in summary even on success):
  - Empty list returned
  - Null/None value returned
  - Empty string returned
  - Suspiciously short LLM response
  - Truncated data (result length == limit)
- **Template error suggestions**: Path similarity matching ("did you mean `issues` instead of `messages`?")
- **Cached-node indicators**: Prep for Task 106 — mark nodes as `[cached]` in report when iteration cache is used
- **Degraded-node markers**: Nodes that succeeded but had stderr warnings
- **Drill-down commands**: jq queries for the source trace file, embedded in report

### Phase 3: MCP Integration + Agent Tooling

*Goal: Agents can request trace analysis programmatically*

- **MCP `get_debug_trace` tool**: Returns summary markdown directly via MCP
  - Accepts trace path, execution ID, or "latest"
  - Returns focused markdown for agent consumption
- **Agent instruction updates**: Update `docs/mcp-agent-instructions.md` and `docs/mcp-sandbox-agent-instructions.md`
- **Deprecate `scripts/analyze-trace/`**: Add deprecation notice pointing to `pflow trace report`
- **Iteration diff** (future): `pflow trace report --diff-previous` — compare with previous trace for same workflow

---

## Phase 1 Implementation Results

**Status**: Complete. All 4269 tests pass, `make check` clean (ruff + mypy + deptry).

**Branch**: `feat/smart-trace-debug`

### Files Modified (8)

| File | Lines changed | Summary |
|------|--------------|---------|
| `src/pflow/runtime/workflow_trace.py` | Full rewrite (~300→~300 lines) | Format 2.0.0, new API, removed 7 methods, added 3 |
| `src/pflow/runtime/wrappers/instrumented_wrapper.py` | ~120 lines | Rewrote `_record_trace`, added 2 chain-traversal helpers, changed snapshot strategy |
| `src/pflow/runtime/wrappers/batch_node.py` | ~80 lines | Added `_capture_item_trace`, `_find_in_chain`, trace accumulator |
| `src/pflow/runtime/wrappers/template_wrapper.py` | ~5 lines | Added `last_resolutions` attr + `wrapper_attrs` entry |
| `src/pflow/runtime/workflow_executor.py` | ~25 lines | Child trace collector creation, `_PROPAGATED_KEYS` update |
| `src/pflow/execution/executor_service.py` | ~4 lines | Inject `_trace_collector` into shared store |
| `src/pflow/cli/main.py` | ~40 lines | `--report` flag, trace-save consolidation, `_save_trace_and_report()` |
| `src/pflow/cli/main_wrapper.py` | ~2 lines | `trace` subcommand route |

### Files Created (2)

| File | Lines | Summary |
|------|-------|---------|
| `src/pflow/core/trace_report.py` | ~260 lines | Report generator: trace JSON → markdown directory |
| `src/pflow/cli/commands/trace.py` | ~40 lines | `pflow trace report` CLI command |

### Test Changes

| File | Tests before | Tests after | Notes |
|------|-------------|-------------|-------|
| `test_runtime/test_workflow_trace.py` | 27 | 32 | 18 updated, 3 removed, 6 new |
| `test_runtime/test_instrumented_wrapper.py` | 34 | 34 | 2 updated (assertion changes) |
| `test_runtime/test_batch_node.py` | 100+ | 100+ | 1 updated |
| `test_integration/test_metrics_integration.py` | 16 | 16 | 1 updated |
| `test_runtime/test_trace_integration.py` | — | 2 | **NEW** — integration tests for fragile seams |

---

## Deviations from Plan

### Deviation 1: `threading.local()` fix NOT implemented

**Plan said**: Fix `_current_node` threading bug by adding `_thread_local: ClassVar[threading.local] = threading.local()` and replacing `self._current_node` with thread-local storage.

**What we did**: Left `_current_node` as an instance attribute on the collector.

**Why**: The existing `_active_collectors[thread_id]` dict already provides per-thread collector lookup. The `_current_node` race condition only manifests when multiple threads share the same collector instance AND call `setup_llm_interception` concurrently. In practice:
- Batch parallel items share the same `InstrumentedNodeWrapper.trace` collector (not deep-copied), but `_setup_llm_interception` is only called once on the *outer* instrumented wrapper — batch items don't individually set up interception.
- Sub-workflow child collectors have `enable_llm_interception=False`, so no interception is set up.

**Risk**: Low. The bug exists in theory (if someone manually nests LLM interception in threads) but doesn't manifest in any current code path. Can be fixed in Phase 2 if needed.

**Trust boundary**: Assumed correct — not verified under concurrent load.

### Deviation 2: `save_to_file()` `llm_calls` parameter fully removed (not kept as fallback)

**Plan correction #4 said**: Keep `llm_calls` as optional fallback for incremental implementation safety.

**What we did**: Removed it completely. `_collect_llm_summary()` recursively scans events (including nested `batch_items[].llm_call` and `sub_workflow_events`).

**Why**: Since we implemented all trace enrichment steps atomically (not incrementally), there was no intermediate state needing the fallback. The recursive scan covers all data the accumulator provided.

**Risk**: None in practice. `__llm_calls__` accumulator still exists in the shared store for execution summary display — it's just no longer used for trace file LLM summaries.

### Deviation 3: `shared_before` dict copy condition initially narrowed (then restored)

**Plan said**: Replace `shared_before = dict(shared) if (self.trace or self.metrics)` with `shared_keys_before = set(shared.keys())`.

**What we initially did**: Changed the full dict copy to `dict(shared) if self.metrics else None` (only when metrics enabled), since trace no longer needs it. This was an over-optimization.

**What review caught**: `_capture_llm_usage()` and `_validate_llm_json_output()` both use `shared_before` for prompt lookup, and they're called unconditionally (not guarded by `if self.metrics`). Narrowing the condition meant prompts weren't captured in `__llm_calls__` during normal text-mode execution (trace enabled, metrics disabled).

**Fix**: Restored to `dict(shared) if (self.trace or self.metrics) else None`. The full dict copy is kept for prompt lookup but no longer stored in trace events.

**Lesson**: The `shared_before` variable now serves two distinct purposes: (1) prompt lookup for `__llm_calls__` enrichment, (2) nothing for traces (replaced by `shared_keys_before`). The name is confusing but renaming would touch too many lines for marginal clarity.

### Deviation 4: Plan corrections 1-2 were incorrect (referred to post-implementation state)

**Plan corrections said**: `executor_service.py` "already injects `_trace_collector`" and `trace_report.py`/`trace.py` "already exist".

**Reality**: These were written by us during implementation. The corrections were written after implementation by reviewing the codebase and mistakenly treating our new code as pre-existing. No action needed — the plan was correct and we executed it.

---

## Bugs Found and Fixed During Review

### Bug 1: `item_shared` UnboundLocalError in `_exec_single()` retries-exhausted path

**Location**: `batch_node.py`, `_exec_single()`, after the retry for-loop.

**Problem**: `item_shared = dict(self._shared)` is inside the try block. If `dict()` raises on the last retry, `item_shared` is unbound when `_capture_item_trace(item_shared, ...)` is called after the loop.

**Fix**: Initialize `item_shared: dict[str, Any] = {}` before the retry loop. If dict() never succeeds, trace gets an empty dict (harmless). Not present in `_exec_single_with_node()` since `item_shared` is a parameter there.

**Likelihood of hitting this**: Near zero — `dict(self._shared)` is a shallow copy of a dict set in `prep()`. Would only fail if shared store was corrupted between prep and exec.

### Bug 2: `--report` + `--no-trace` silently does nothing

**Problem**: `--no-trace` prevents trace collector creation, so `--report` has nothing to generate from. The flag is silently ignored.

**Fix**: `--report` now overrides `--no-trace`. Implementation: `trace_enabled = not no_trace or report_path is not None`.

### Bug 3: Old trace format produces empty reports

**Problem**: `generate_report()` on a format 1.2.0 trace file produces a report with no useful content (no `node_output`, `template_resolutions`, etc.).

**Fix**: Added format version check — rejects traces with format < 2.0.0 with clear error message: "Trace format {version} not supported. Report generation requires format 2.0.0+."

---

## Lint/Type Issues Resolved

### C901 Complexity (3 functions)

| Function | Complexity | Fix |
|----------|-----------|-----|
| `execute_json_workflow` | 13 > 10 | Extracted `_save_trace_and_report()` helper |
| `_capture_item_trace` | 16 > 10 | Extracted `_find_in_chain()` static method, simplified LLM data loop |
| `_build_node_file` | 13 > 10 | Extracted `_format_node_metadata()` and `_format_node_output()` |

### mypy Error (1)

`trace_report.py:49` — `generate_report` return type `Path | None` conflicted with `trace.get()` returning `Any`. Fixed with explicit `str()` cast: `name: str = str(trace.get("workflow_name", "workflow"))`.

### ruff-format (auto-fixed)

`trace.py` import order (stdlib before third-party).

---

## High-Value Integration Tests

Two integration tests added in `tests/test_runtime/test_trace_integration.py` to lock in the most fragile integration seams. These use real wrapper instances and a real `WorkflowTraceCollector` — no mocks.

### Test 1: `test_template_resolutions_propagate_through_wrapper_chain`

**Seam tested**: `TemplateAwareNodeWrapper.last_resolutions` → `NamespacedNodeWrapper.__getattr__` delegation → `InstrumentedNodeWrapper._find_template_wrapper()` → `trace.record_node_execution(template_resolutions=...)`.

**Why it matters**: `_find_template_wrapper()` traverses `self.inner_node` looking for `last_resolutions`. But `self.inner_node` is a `NamespacedNodeWrapper`, which doesn't have `last_resolutions` directly — it delegates via `__getattr__` to the inner `TemplateAwareNodeWrapper`. The traversal finds it on the first hop via this delegation, but `current` is the NamespacedNodeWrapper (not the TemplateAwareNodeWrapper). Reading `.last_resolutions` on that proxy returns the correct data via the same delegation. This subtle proxy pattern is invisible in tests that mock the trace collector.

**What breaks without it**: If `NamespacedNodeWrapper.__getattr__` changes (e.g., stops delegating, adds an allowlist), or if a new wrapper is inserted between namespace and template wrappers, `template_resolutions` silently becomes `{}` in all trace events. No error, no crash — just missing data.

**Asserts**: `template_resolutions["prompt"]` has correct `template` and `resolved` values. `node_output` has the node's actual output. `mutations["added"]` contains the node's namespace key.

### Test 2: `test_batch_items_appear_in_trace_event`

**Seam tested**: Four handoff points in the batch trace pipeline:
1. `prep()` initializes `shared["_batch_trace"][node_id] = []`
2. `_exec_single()` → `_capture_item_trace()` appends per-item events to the accumulator
3. `post()` transfers from `shared["_batch_trace"]` to `self._trace_items`
4. `InstrumentedNodeWrapper._find_batch_or_workflow_node()` traverses chain, finds `PflowBatchNode` by class name, reads `_trace_items`

**Why it matters**: Each handoff uses a different mechanism (shared store key, instance attribute, class name matching). If any breaks, batch items silently disappear from trace events.

**What breaks without it**: If `_batch_trace` key name changes, or `post()` stops reading it, or `_find_batch_or_workflow_node` doesn't match "PflowBatchNode", the trace event has no `batch_items` — again, silent data loss.

**Asserts**: 3 batch items with correct `index`, `item` value, `success`, `duration_ms`, and per-item `node_output`.

---

## Known Remaining Issues (Out of Scope)

### 1. Stale agent instruction docs

Two files reference old trace format `nodes[1].shared_after`:
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md:1440-1441`
- `src/pflow/cli/resources/cli-agent-instructions.md:1419-1420`

These are auto-generated agent instruction files. Should be updated when instructions are next regenerated. Not blocking — agents don't parse trace JSON programmatically.

### 2. `_validate_llm_json_output` limited utility

This function warns when an LLM's prompt requested JSON but the response is plain text. It requires `shared_before` to find the prompt, which means it only works when trace or metrics are enabled. Its heuristic (substring "json" in prompt) is crude. Low value — not worth additional investment.

### 3. `_current_node` threading vulnerability (theoretical)

See Deviation 1. The `_current_node` attribute on `WorkflowTraceCollector` is not thread-safe. Currently safe because batch items don't individually set up LLM interception. Would become a real bug if the wrapper architecture changed to allow per-item interception.

### 4. `modified` field always empty in mutations

Mutations now only track `added` and `removed` keys (set difference). The `modified` field is always `[]` because we no longer take full value snapshots. This is documented as an acceptable tradeoff in the plan — the report cares about what each node produced, not which existing values changed.

### 5. Report generator has no unit tests

`src/pflow/core/trace_report.py` has no dedicated test file. The markdown generation functions (`_build_node_file`, `_build_summary`, etc.) are pure functions that take dicts and return strings — straightforward to test but low bug risk. The format version check is tested implicitly. Could add unit tests in a follow-up if the report format becomes more complex.

### 6. `_batch_trace` key not cleaned up from shared store

The `_batch_trace` key persists in the shared store after `post()`. It's filtered from trace output by `_sanitize_for_json()` (which strips `_batch_trace`), so it doesn't appear in trace files. Cleaning it up in `post()` would be slightly cleaner but adds no value.

---

## Architecture Insights (For Future Implementers)

### How trace data flows (complete picture)

```
1. TemplateAwareNodeWrapper._run()
   → Resolves templates, stores in self.last_resolutions

2. PflowBatchNode._exec_single() / _exec_single_with_node()
   → Per-item: calls _capture_item_trace() which:
     - Reads last_resolutions from node chain
     - Reads _child_trace_events from node chain
     - Reads node_output from item_shared[node_id]
     - Appends to shared["_batch_trace"][node_id] list
   → In post(): transfers to self._trace_items

3. WorkflowExecutor.exec()
   → Creates child WorkflowTraceCollector (enable_llm_interception=False)
   → Passes to compile_ir_to_flow(trace_collector=child)
   → After run: stores child.events as self._child_trace_events

4. InstrumentedNodeWrapper._run()
   → Captures shared_keys_before (set of keys)
   → After inner_node._run():
     - _find_template_wrapper() → reads last_resolutions
     - _find_batch_or_workflow_node() → reads _trace_items or _child_trace_events
     - Computes node_output from shared[node_id]
     - Computes mutations from key-set diff
     - Calls trace.record_node_execution(new signature)

5. WorkflowTraceCollector.record_node_execution()
   → Builds event dict with all fields
   → _add_llm_data() enriches from node_output + intercepted prompts
   → _sanitize_for_json() strips internal keys
   → Appends to self.events

6. WorkflowTraceCollector.save_to_file()
   → _collect_llm_summary() recursively scans tree
   → Writes JSON to ~/.pflow/debug/

7. generate_report()
   → Reads trace JSON
   → Recursive _write_node_files() produces markdown directory
```

### Two-phase pattern for batch trace collection

Phase 1 (during execution): `_batch_trace` dict in shared store. Each item's `_capture_item_trace()` appends to `shared["_batch_trace"][node_id]`. This works in parallel because `list.append()` is GIL-protected.

Phase 2 (in post): Transfer from shared store to instance attribute `self._trace_items`. This makes it available to `InstrumentedNodeWrapper._find_batch_or_workflow_node()` via chain traversal.

### `shared_before` serves dual purpose (confusing but correct)

The `shared_before = dict(shared)` in `InstrumentedNodeWrapper._run()` is:
1. Used by `_capture_llm_usage()` for prompt lookup → enriches `__llm_calls__`
2. Used by `_validate_llm_json_output()` for prompt lookup → logs warning
3. **NOT** used by `_record_trace()` (which uses `shared_keys_before` set instead)

The variable name is a holdover from the old design. Renaming to `shared_snapshot_for_prompt_lookup` would be more accurate but touches many lines.

---

---

## Post-Implementation Review & Fixes

### [2026-03-23] — Code review by planning agent

Full code review of all modified files. Findings:

**Architecture**: Solid. Wrapper chain traversal, batch trace accumulation, sub-workflow collector creation all work correctly. The `_find_batch_or_workflow_node` correctly stops at `PflowBatchNode` for batch-of-workflow combos (batch items contain sub-workflow events in their `"events"` field).

**Minor issues noted** (not blocking):
- `_sanitize_for_json` doesn't guard `isinstance(key, str)` on the `_batch_trace` check (line 158) — extremely unlikely to matter
- `_trace_collector` uses single underscore while all other `_PROPAGATED_KEYS` use dunder — inconsistent but functional
- Empty stderr shows as `## stderr` with empty code block in reports — cosmetic

### [2026-03-23] — Report generator tests added

29 unit tests for `trace_report.py` in `tests/test_core/test_trace_report.py`:
- `TestGenerateReport` (8): file existence, format rejection, directory creation, per-node files, batch directories, sub-workflow batch items, sub-workflow events, auto output path
- `TestBuildSummary` (4): workflow name, status/duration, LLM summary, pipeline table
- `TestBuildNodeFile` (10): metadata, errors, LLM data, template resolutions, prompts, commands, responses, stdout/stderr, structured results, priority rules
- `TestBuildNodeSummary` (1): batch summary table
- `TestBuildBatchItemFile` (5): basic, LLM data, template resolutions, node output, failures
- `TestBuildBatchItemSummary` (1): basic summary

Test count: 4267 → 4298 (29 report tests + 2 integration tests from implementing agent).

### [2026-03-23] — Manual testing with real workflows

| Test | Result |
|------|--------|
| Simple workflow + `--report` | Pass |
| Batch workflow (10 HTTP→shell items) | Pass — 10 per-item files in subdirectory |
| `pflow trace report` (post-hoc) | Pass |
| `--report --no-trace` | Pass — `--report` overrides `--no-trace` |
| Trace format 2.0.0 verification | Pass — no `shared_before`/`shared_after`, has new fields |
| `--report-dir /custom/path` | Pass |

### [2026-03-23] — Bugs found and fixed during manual testing

**Bug 1: `--report` flag consumed workflow argument**

The `is_flag=False, flag_value="auto"` Click option definition caused `pflow examples/workflow.pflow.md --report` to interpret the workflow path as the report path. Click doesn't support optional-value options well with `nargs=-1 UNPROCESSED` catch-all arguments.

**Fix**: Split into two options:
- `--report` — boolean `is_flag=True`, enables report at default location (`~/.pflow/reports/{name}/`)
- `--report-dir /path` — custom output directory, implies `--report`

**Bug 2: Flags after workflow argument not recognized**

`allow_interspersed_args=False` meant `pflow workflow.pflow.md --report` treated `--report` as part of the workflow catch-all.

**Fix**: Changed to `allow_interspersed_args=True`. Safe because workflow params use `key=value` syntax (no `--` prefix), so no ambiguity with Click options. All 4298 tests pass.

**Usage after fixes:**
```bash
pflow --report workflow.pflow.md                        # before workflow arg
pflow workflow.pflow.md --report                        # after workflow arg
pflow workflow.pflow.md --report --verbose              # mixed
pflow --report-dir /tmp/out workflow.pflow.md           # custom path (implies --report)
pflow workflow.pflow.md --report-dir /tmp/out           # custom path after
```

---

### File locations

- Implementation plan: `.taskmaster/tasks/task_108/implementation/phase-1-implementation-plan.md`
- Progress log: `.taskmaster/tasks/task_108/implementation/progress-log.md`

---

### [2026-03-23] — Code review evaluation and fixes

Two code reviews evaluated (`scratchpads/task-108-phase1-code-review-2026-03-23.md` and `scratchpads/task-108-phase1-staged-review-2026-03-23.md`). Total: 28 findings across both reviews + deep read.

**Verdicts**: 15 confirmed and fixed, 5 disputed, 8 deferred to Phase 2.

**Fixes applied:**

| # | Fix | File(s) |
|---|-----|---------|
| 1 | Batch item `node_output` sanitized via new `_sanitize_batch_items()` | `workflow_trace.py` |
| 2 | Tuple handling in `_sanitize_for_json` (`list` → `(list, tuple)`) | `workflow_trace.py` |
| 3 | API warning message passed to trace `error` field | `instrumented_wrapper.py` |
| 4 | `cost_usd == 0.0` no longer hidden (`if cost:` → `if cost is not None:`) | `trace_report.py` |
| 5 | Non-standard `node_output` keys rendered as catch-all JSON block | `trace_report.py` |
| 6 | Report paths sanitized via `_safe_name()` | `trace_report.py` |
| 7 | `generate_report` no longer mutates loaded trace dict (pass `source_path` param) | `trace_report.py` |
| 8 | Import fixed: `from pflow.runtime...` (was `from src.pflow...`) + mock patch path | `test_workflow_trace.py` |
| 9 | Comment explaining `allow_interspersed_args=True` | `main.py` |
| 10 | Comment on `_trace_collector` in `_PROPAGATED_KEYS` (needed for grandchild+ nesting) | `workflow_executor.py` |
| 11 | `_child_trace_events` check uses `is not None` instead of truthiness | `batch_node.py` |
| 12 | Comment documenting child collector prompt source (`template_resolutions`) | `workflow_trace.py` |
| 13 | Metrics integration test tightened: asserts `mutations` and `node_output` present | `test_metrics_integration.py` |
| 14 | `runtime/CLAUDE.md` updated: WorkflowTraceCollector section matches format 2.0.0 | `runtime/CLAUDE.md` |
| 15 | `trace report` CLI: specific error messages (missing file vs unsupported format) | `cli/commands/trace.py` |

**Review finding on `_trace_collector` in `_PROPAGATED_KEYS`**: One review suggested removing it. Analysis showed this would break 3+ level nesting — grandchild workflows use the propagated key to detect tracing is active. The key points to the PARENT collector (not child), but it's only used as a truthiness check. Added comments instead of removing.

**Disputed findings** (no action taken):
- Redundant chain traversal in `_capture_item_trace` — by design, different search targets
- Report overwrites previous — intentional for `git diff` between runs
- Duplicate LLM summary tests — different test shapes, document format evolution

**Deferred to Phase 2 (full details):**

#### D1. `_current_node` threading vulnerability

**File**: `src/pflow/runtime/workflow_trace.py:49, 313`
**Source**: Review 1 C2, Review 2 deep read, Progress Log Deviation 1, Known Issue #3

`self._current_node = node_id` is set on the shared `WorkflowTraceCollector` instance. In parallel batch execution, `InstrumentedNodeWrapper.__deepcopy__` shares `self.trace` by reference across threads. If two threads call `setup_llm_interception()` concurrently, the second overwrites the first's `_current_node`.

**Why it doesn't bite now**: Batch items don't individually call `_setup_llm_interception` — it's called once on the outer `InstrumentedNodeWrapper` before batch dispatch. Child collectors have `enable_llm_interception=False`. The `_active_collectors[thread_id]` dict correctly maps threads to collectors.

**Fix for Phase 2**: Replace `self._current_node` with `threading.local()`:
```python
_thread_local: ClassVar[threading.local] = threading.local()
# In setup_llm_interception:
WorkflowTraceCollector._thread_local.current_node = node_id
# In intercept_prompt closure:
current_node = getattr(WorkflowTraceCollector._thread_local, 'current_node', None)
```

**Risk if unfixed**: Would become a real bug if the wrapper architecture changed to allow per-item LLM interception setup, or if someone manually nests LLM interception in threads.

#### D2. Missing integration test: parallel batch trace capture

**File**: `tests/test_runtime/test_trace_integration.py`
**Source**: Review 1 S3, Review 2 deep read

`TestBatchNodeTraceEvents` only tests sequential batch (`parallel=False`). The parallel path uses `_exec_single_with_node` with a deep-copied node chain (`thread_node`), which is a different code path for template resolution capture. `_find_in_chain(thread_node, "last_resolutions")` traverses the deep-copied chain, not the original.

**What to test**: Create a parallel batch node (2+ items), execute, verify per-item `template_resolutions` are captured correctly in trace events. Specifically verify that the deep-copied `TemplateAwareNodeWrapper` retains `last_resolutions` after `_run()` completes, before the thread returns.

**Why deferred**: Parallel batch with proper template params requires a more complex fixture (batch items with template references). Sequential test already covers the critical seam.

#### D3. Missing integration test: sub-workflow trace tree (sub_workflow_events)

**File**: `tests/test_runtime/test_trace_integration.py`
**Source**: Review 1 S2, Review 2 deep read

`_find_batch_or_workflow_node()` handles both `PflowBatchNode` and `WorkflowExecutor`, but only the batch path has an integration test. The `WorkflowExecutor` → `_child_trace_events` → `sub_workflow_events` flow is untested at the integration level.

**What to test**: Build a wrapper chain with `InstrumentedNodeWrapper` → `WorkflowExecutor` (or mock it). Execute a child workflow with trace collector. Verify that `sub_workflow_events` appears in the parent trace event and contains the child's node events.

**Why deferred**: Requires compiling a real child workflow with `compile_ir_to_flow` inside a test, which is significantly more complex than the batch fixture.

#### D4. Missing integration test: failed batch items in trace

**File**: `tests/test_runtime/test_trace_integration.py`
**Source**: Review 1 S4

`_capture_item_trace` handles error dicts (`item_event["error"] = error.get("error", str(error))`), but no test verifies that a failed batch item appears with the correct error data in the final trace event's `batch_items` array.

**What to test**: Create a batch node where one item raises an exception or returns an error. Verify the trace event's `batch_items` contains an entry with `success: false` and the error message.

#### D5. Cached nodes absent from trace

**File**: `src/pflow/runtime/wrappers/instrumented_wrapper.py:738-739`
**Source**: Review 2 deep read

When `_check_cache_validity` returns `True`, `_run()` returns early via `_handle_cached_execution()` **before** `_record_trace()` is called. This means cached nodes produce no trace event at all. Consumers reading traces should know that executions may omit cached steps.

**Pre-existing behavior** — not introduced by format 2.0.0. Relevant for Task 106 (iteration cache) which will increase cache hits.

**What to do in Phase 2**: Either (a) record a minimal trace event for cached nodes (with a `cached: true` flag), or (b) document this in the trace format spec so report consumers handle absent nodes correctly. The report generator should indicate "[cached]" for nodes that don't appear in the trace but are known to exist in the workflow IR.

#### D6. Noisy mutations from `__execution__` / `__llm_calls__`

**File**: `src/pflow/runtime/wrappers/instrumented_wrapper.py:710`
**Source**: Review 2 deep read

`shared_keys_before` is captured at line 710, BEFORE `_initialize_execution_state()` at line 718 which adds `__execution__`, `__llm_calls__`, `__cache_hits__` to the shared store. So the first node's `mutations["added"]` includes these system keys — noisy for report consumers expecting only user-data mutations.

**Pre-existing behavior** — the old `shared_before`/`shared_after` approach had the same issue (different shape but same timing).

**What to do in Phase 2**: Either (a) capture `shared_keys_before` AFTER `_initialize_execution_state()`, or (b) filter system keys from mutations in `_record_trace()`. Option (a) is cleaner but changes the semantics of mutations for the first node. Option (b) is safer — just strip `__dunder__` keys from added/removed lists.

#### D7. Report UX: error highlight in pipeline table

**File**: `src/pflow/core/trace_report.py:136`
**Source**: Review 1 S7

The pipeline table shows `FAILED` for failed nodes, but in a markdown table this doesn't stand out visually. Consider using `**FAILED**` (markdown bold) so it's immediately visible when scanning the summary.

#### D8. Report UX: `trace report` stdout output for scripting

**File**: `src/pflow/cli/commands/trace.py:38`
**Source**: Review 1 S8, Review 2 S4

The `trace report` command outputs all messages to stderr. For CLI composability (piping to other tools), consider outputting the report directory path to stdout so `report_dir=$(pflow trace report)` works:
```python
click.echo(str(report_dir))  # stdout — pipeable
click.echo(f"Report generated: {report_dir}", err=True)  # stderr — human feedback
```

#### D9. `_collect_llm_summary` double-counting invariant undocumented

**File**: `src/pflow/runtime/workflow_trace.py:237-249`
**Source**: Review 2 S1

The recursive walk counts `llm_call` on events AND on batch items. If a batch item ever has BOTH `llm_call` and `events` (sub-workflow items), the item-level `llm_call` would be counted in addition to the event-level calls inside `events` — potential double-counting.

**Why it doesn't bite now**: In practice, `llm_call` and `events` are mutually exclusive on batch items. Leaf items (directly executing an LLM node) have `llm_call`. Sub-workflow items have `events` (with their own `llm_call` fields on individual events). The `WorkflowExecutor` node doesn't write `llm_usage` to its namespace.

**What to do in Phase 2**: Add a comment documenting the invariant: "Item-level `llm_call` is only for leaf batch items without `events`. If both are present, calls would be double-counted." Optionally add a focused unit test with a deliberately redundant structure to guard against future changes.

#### D10. `_validate_llm_json_output` still uses `shared_before`

**File**: `src/pflow/runtime/wrappers/instrumented_wrapper.py:772`
**Source**: Review 1 W5, Review 2 deep read

This function warns when an LLM's prompt requested JSON but the response is plain text. It requires `shared_before` (the full dict snapshot at line 712) to find the prompt. Its heuristic (substring "json" in prompt) is crude.

**What to do in Phase 2**: The report now shows `template_resolutions` (the actual prompt), making post-hoc JSON validation less critical. Consider removing this method entirely, or rewriting it to use `template_resolutions` from the wrapper chain instead of `shared_before`. Removing it would also eliminate the remaining O(n) `dict(shared)` copy at line 712 (which is the only remaining reason for a full shared store snapshot per node).

---

*Phase 1 complete. All tests pass (4298), `make check` clean. Next: Phase 2 (Smart Analysis + Diagnostics) or real-world testing with complex workflows.*
