# Plan: TraceTree Consolidation + Sub-Workflow Cost Rollup + `optimized_*` Rename

> **Revised after 6-agent code-review.** Critical findings incorporated:
> trace-driven `current_cost` (separate from IR-driven projections),
> all-bare-`node_id`-dict migration, per-workflow Track B/C parameter views,
> end-to-end CliRunner tests with committed fixtures, MCP docstring rewrite.

## Context

`pflow analyze-cache` is the primary tool agents use to discover prompt-cache opportunities and verify their savings. Three real problems block its agent-actionability today:

1. **Trace traversal duplication** (GH #364). At least **6 functions** across 4 modules re-implement the same trace-event walk (`events → batch_items → sub_workflow_events`) with **3 distinct cached-event policies** and divergent recursion shapes. The documented sync invariant at `core/trace_report.py:205-206` is currently FALSE — `_compute_event_cost` and `_has_any_cost_data` recurse into a top-level `event["events"]` that no production code path writes (verified vestigial via grep against the runtime; sole writer is `batch_executor.py:723` which writes into `batch_items[i]`, never at top level — but verification was only against 1-level smoke fixtures, see Phase 1 verification step).

2. **Sub-workflow cost invisibility** (GH #365). On `lyrics-generator song-creator` (3-deep workflow tree), `analyze-cache` reports ~$0.10 when actual run cost is ~$0.45. Per-call row construction filters `node.get("type") != "llm"` (analyze.py:589-618) — every `type: workflow` node is skipped. `cost_usd_for_node` intentionally doesn't recurse (`context.py:80-120`). `_iter_llm_events` ALREADY recurses for discrepancy detection (`analyze.py:1940-1951`). The asymmetry IS the bug.

3. **`optimized_*` symbol semantic inversion**. `AnalysisSummary.optimized_cost_per_run_usd` and `_aggregate_optimized_cost` mean "no-cache hypothetical" (recomputed full price as if `## Cache` were never declared), NOT the optimization target. On declared workflows where `current_cost` honors trace, `optimized > current` reads as "the optimized state costs more" — agents could interpret as "don't add caching." User-facing label was renamed to "Cost without caching" in commit `4c155c8d`; underlying symbols still mislead.

**Intended outcome**: introduce `TraceTree` as the single domain entity for trace queries (replacing 6 walkers). Roll up sub-workflow costs through ALL summary fields with workflow-scope correctness via a **trace-driven `current_cost` + IR-driven projections** split. Rename `optimized_*` outright with JSON 3.0 bump. Each commit ships green `make test` + `make check` + `tests/test_execution/test_plan_drift.py` 33/33 + golden baseline.

---

## Architecture (load-bearing decisions)

### A1. Two cost rollup mechanisms, not one

Adopted after review-silent-failures Finding #6: trying to drive BOTH `current_cost` AND projections from one IR-walk-derived index causes silent failures (erroring runs over-count via recompute fallback for unexecuted children; recursive workflows under-count because cycle-detect counts once but runtime executes N times).

**`current_cost_per_run_usd` rollup is purely TRACE-DRIVEN**:
- `TraceTree.total_cost(*, descend_sub_workflows=True, include_cached=False)` walks the actual trace
- Naturally honest: erroring runs report what fired, recursive workflows report what executed, heterogeneous batches report per-item recorded cost
- No IR walk; no `workflow_path` correlation needed for the SUM (only needed for ATTRIBUTION in per-call rows)

**Projection fields (`cost_without_caching_usd`, `aggregate_savings_*`) are IR-DRIVEN**:
- `walk_cross_workflow` enumerates reachable workflows; per-call rows generated per workflow's LLM nodes; rows feed projection aggregators
- Natural fit for "what would I save if I added `## Cache`?" — projections are hypothetical, IR is the source of truth for what could be cached

### A2. `TraceTree` is a pure traversal primitive

- Lives in `core/trace_tree.py`. No imports from cache_analysis or runtime/engine; knows only the trace JSON shape.
- `from_dict` validates `nodes` shape (raises ValueError on non-list, accepts missing or `None` as empty); does NOT validate `format_version` (CLI's exit-code contract owns that at `_load_trace_explicit`).
- No knowledge of workflow_path correlation. Workflow-scope tagging is the analyzer's responsibility (it constructs an index using `cw_result.edges`).

### A3. Workflow-scope key for projections + per-call rows

Per DD#12 (each `.pflow.md` scopes its own `## Cache`; cross-workflow caching is incidental byte-level only), projection aggregators must group by workflow scope. Subset key changes from `tuple(declared_prompt_cache)` to `(workflow_path, tuple(declared_prompt_cache))`. PerCallRow gains `workflow_path: str | None`.

**The (workflow_path, node_id) keying must propagate to ALL bare-node_id dicts** — not just the projection subset key. Review-impact-completeness identified four dicts that would silently misattribute under sub-workflow rollup:
- `rows_by_node` at `analyze.py:359`
- `output_tokens_by_node` at `analyze.py:2358`
- `nodes_by_id` at `analyze.py:1064` (used by `_opaque_prompt_warnings`)
- `warnings_by_node` at `render_text.py:660,673,689,824`

All four migrate to `(workflow_path, node_id)` tuple keys in Phase 2a.

### A4. Per-workflow Track B / Track C parameter views

Per review-feature-interactions SUGG-2/3: `ctx.parameters` is root-scope. Child workflows have their own inputs populated by parent's `inputs:` mapping. Sub-workflow LLM rows would silently degrade tier labels if they tried to resolve `${concept}` against root parameters.

**`AnalysisContext` gains a `parameters_for_workflow(workflow_path) -> Mapping`** method:
- For root workflow_path → returns `self.parameters`
- For child workflow_path → walks `cw_result.edges` to find the parent_node's `inputs:` mapping; resolves each input value against the parent's parameters (recursively up to root); returns the resolved dict
- Memoized per workflow_path (constructed once)

This preserves Track B (parameters fallback for `cacheable_data_source`) and Track C (resolved-prompt tokenization) for sub-workflow rows.

### A5. Discrepancy detection workflow-scope: Phase-A walker threading

Per the W7 verification: trace events DO NOT carry `workflow_path`. Stamping it would require a 2.x → 2.2 trace format bump. Two options:

- **Option 2.2 trace bump**: stamp `workflow_path` per event during `record_node_execution`. Cleaner long-term but breaks runtime/analyzer parity contract during the bump.
- **Option walker threading (chosen)**: `TraceTree.iter_llm_leaves(*, edges=None)` accepts an optional `edges` dict. When the analyzer wants workflow-scoped leaves, it passes `cw_result.edges` (which maps `parent_node_id → child_workflow_path`). The walker threads `workflow_path` during `sub_workflow_events` descent by looking up the parent's edge.

Option walker-threading is chosen because:
- Avoids trace format change (no 2.1 → 2.2 bump)
- Trace stays format-version-stable for runtime
- The analyzer already has `walk_cross_workflow` results available; no new infrastructure
- TraceTree stays a pure traversal primitive (workflow_path is INPUT, not an inferred field)

For 1.5-level cases (heterogeneous batch sub-workflow with `workflow: ${item.workflow}`), `cw_result.edges` includes inline-static items but defers template-items batches; for those, leaves yield `workflow_path=None` and the consumer surfaces a notes entry per the existing `_flatten_plan_keys` collision pattern.

### A6. Cached event subtree filter preserved at producer-shim level

Per review-silent-failures C1 + review-feature-interactions Boundary 1: today's `_collect_llm_calls_from_events` SKIPS the entire cached event subtree (no recursion into batch_items/sub_workflow_events of cached parents). The plan must NOT change this contract.

`TraceTree.iter_llm_leaves` accepts `descend_cached_subtrees: bool = True` (default True for analyzer needs which want all leaves including under cached parents). Producer shims (`_collect_llm_calls_from_events`, `_collect_llm_summary`) set `descend_cached_subtrees=False` to preserve the existing skip-entire-subtree semantic.

---

## Phases

5 commits in order. Each ships green tests + check + plan_drift + golden baseline.

---

## Phase 3 — Rename + JSON 3.0 (FIRST commit, ~120 LOC delta)

**Why first**: smallest risk; isolates the JSON 3.0 version bump; subsequent commits build on clean naming throughout.

### Production changes

- `src/pflow/core/cache_analysis/analyze.py`:
  - Rename `AnalysisSummary.optimized_cost_per_run_usd` → `cost_without_caching_usd` (line 218)
  - Update construction at lines 2382-2383 (`cost_without_caching_usd=cost.cost_without_caching_usd`)
  - Update internal reference at line 2371 (`cost.current_usd - cost.cost_without_caching_usd`)
- `src/pflow/core/cache_analysis/cost_estimation.py`:
  - Rename `AggregateCostBreakdown.optimized_usd` → `cost_without_caching_usd` (line 77)
  - Update 5 construction sites (lines 281, 284, 291, 348, 357)
  - Module docstring (line 23): rename `optimized_cost` → `cost_without_caching`
  - **Split `_aggregate_optimized_cost`** (line 397) into two clearly-named functions:
    - `_aggregate_no_cache_cost(rows: list[tuple[PerCallRow, ModelPricing, int]], ttl: str | None) -> float | None` — the `subset is None` branch (recompute no-cache hypothetical via `_per_call_current_cost_recomputed`). **Returns None when input list is empty** (preserves the empty-input contract from the existing function).
    - `_aggregate_with_cache_projection(rows: list[tuple[PerCallRow, ModelPricing, int]], ttl: str | None) -> float | None` — the `subset is declared` branch (1 write + N-1 reads grouped by `(workflow_path, declared_prompt_cache)`). **Returns None when input list is empty.** Subset key is workflow-scoped per A3.
  - Caller at line 281 must preserve the `if rows_with_output:` gate AND handle `None + float`/`float + None` correctly:
    ```python
    if rows_with_output:
        no_cache = _aggregate_no_cache_cost([r for r in rows_with_output if not r[0].declared_prompt_cache], ttl)
        with_cache = _aggregate_with_cache_projection([r for r in rows_with_output if r[0].declared_prompt_cache], ttl)
        cost_without_caching_usd = (no_cache or 0.0) + (with_cache or 0.0) if (no_cache is not None or with_cache is not None) else None
    else:
        cost_without_caching_usd = None
    ```
  - Update `_per_call_current_cost_recomputed` docstring (line 199)
- `src/pflow/core/cache_analysis/render_text.py`:
  - Update line 209: `_format_cost(s.cost_without_caching_usd, ...)`
  - Drop the load-bearing comment block at lines 200-208 (no longer needed; field name self-documents)
- `src/pflow/core/cache_analysis/render_json.py`:
  - Line 161: rename JSON key `"optimized_cost_per_run_usd"` → `"cost_without_caching_usd"`
  - Line 31: bump `JSON_FORMAT_VERSION = "3.0"`
  - Line 32: bump `JSON_FORMAT_VERSION_MAJOR = "3"`
  - Module docstring (line 5): update from "current literal '2.0'" to "current literal '3.0'" — the docstring was already drifted (constant was 2.1, docstring said 2.0); fix while in there
  - Add 3.0 entry to version-history block (lines 87-117) describing the rename + the new fields landing in subsequent phases
- `src/pflow/core/cache_analysis/__init__.py:11-12` (module docstring) — update the `2.x` consumer-rule example to `3.x`
- `src/pflow/core/cache_analysis/summarize.py`:
  - Line 70: rename `optimized = analysis.summary.cost_without_caching_usd`
- `src/pflow/mcp_server/tools/execution_tools.py:374-380` — **rewrite the docstring prose** (LLM-visible):
  > **Version policy**: ``format_version`` follows semver-ish. Minor bumps (``3.0`` → ``3.1``) are additive (new fields, new warning IDs); consumers tolerant via ``format_version.startswith("3.")`` continue to work. Major bumps (``3.x`` → ``4.x``) are breaking; pinned consumers refuse to consume.
- `src/pflow/mcp_server/services/execution_service.py:382-387` — same rewrite

### Test updates (mechanical)

- `tests/test_core/test_cache_analysis_analyze.py:1012` — `assert result.summary.cost_without_caching_usd is None`
- `tests/test_core/test_cache_analysis_renderers.py:55` — kwarg rename in `_make_analysis` factory
- `tests/test_core/test_cache_analysis_renderers.py:91` — `assert result["format_version"].startswith("3.")` (the explicit literal-prefix check for major-bump detection)
- `tests/test_core/test_cache_analysis_renderers.py:4, 87` (docstring updates)
- `tests/test_core/test_cache_analysis_summarize.py:22` — kwarg rename in `_analysis_with` factory
- `tests/test_core/test_cache_analysis_per_id_coverage.py:208, 219` — version-pin updates
- `tests/test_mcp_server/test_analyze_cache_tool.py:186` — `'3.x' in doc`
- `tests/test_cli/test_analyze_cache.py:99-107` — verify mechanical updates pass (uses `JSON_FORMAT_VERSION` constant via `==` AND explicit `JSON_FORMAT_VERSION_MAJOR + "."` check)
- Function-name rename in `tests/test_core/test_cache_analysis_cost_estimation.py:172`: `test_optimized_cost_amortizes_writes_across_subset_group` → `test_with_cache_projection_amortizes_writes_across_subset_group`
- Audit other tests in `tests/test_core/test_cache_analysis_cost_estimation.py` for "optimized" in test names that drift after the rename

### Mutation contract for Phase 3

- `test_aggregate_no_cache_cost_returns_None_for_empty_input` — explicit assertion `assert _aggregate_no_cache_cost([], ttl=None) is None`. **Mutation contract**: change return to `0.0` → assertion fails (this defends the silent `None → 0.0` regression flagged by review-silent-failures W4).
- `test_aggregate_with_cache_projection_returns_None_for_empty_input` — same shape.
- `test_caller_preserves_None_when_both_aggregators_return_None` — `_compute_aggregate_costs` integration test; assert `breakdown.cost_without_caching_usd is None` for empty `rows_with_output`. **Mutation contract**: revert the gate, change to `0.0 + 0.0 = 0.0` → assertion fails.

### Deferred to Phase 2: leave the load-gate `startswith("2.")` checks in `analyze.py:498,500,547,2095` UNCHANGED in Phase 3

These check the **trace** `format_version` (which stays `"2.1.0"`), not the analyze-cache JSON output version. Different namespace; both can be 2.x and 3.x simultaneously. CLI help text at `cli/commands/analyze_cache.py:39-40` ("Works on both 2.0.0 and 2.1.0 traces") refers to TRACE format and stays unchanged.

---

## Phase 1 — TraceTree (SECOND commit, ~600 LOC delta)

**Goal**: a single typed view of the workflow trace that owns all traversal logic. Six existing walkers become ≤5-line shims that delegate.

### New file: `src/pflow/core/trace_tree.py` (~180 LOC)

```python
@dataclass(frozen=True)
class LlmEventLeaf:
    """One leaf event carrying llm-related data, with attribution context.

    Carries BOTH the owner_node_id (the top-level node_id the leaf is scoped
    under — for batch items, this is the batch parent's id; for sub-workflow
    descendants, this is the closest sub-workflow boundary's id) AND access
    to the leaf event's own node_id (via `event["node_id"]`) — the existing
    `_iter_llm_events` test at per_id_emission.py:1539-1572 asserts inner
    node_ids are visible.
    """
    event: Mapping[str, Any]
    owner_node_id: str
    tier: Literal["top", "batch_item", "sub_workflow_descendant"]
    workflow_path: str | None  # None unless walker called with `edges` kwarg

    @property
    def is_cached(self) -> bool:
        return bool(self.event.get("cached"))

    @property
    def llm_call(self) -> Mapping[str, Any] | None:
        call = self.event.get("llm_call")
        return call if isinstance(call, dict) else None

    @property
    def event_node_id(self) -> str:
        """The leaf event's own node_id (vs owner_node_id). For batch items
        with `llm_call`, this is the batch item's id; for sub-workflow
        descendants, this is the inner LLM node's id."""
        return str(self.event.get("node_id", "unknown"))


@dataclass(frozen=True)
class TraceTree:
    """Read-only view of a workflow trace. Single seam for trace queries.

    Build with TraceTree.from_dict(trace_json). Format-version validation is
    the CALLER's responsibility (`_load_trace_explicit` raises ValueError for
    non-2.x with the CLI's exit-code contract). TraceTree assumes pre-validated
    data of any 2.x or future 3.x.
    """
    events: tuple[Mapping[str, Any], ...]
    format_version: str

    @classmethod
    def from_dict(cls, trace_data: Mapping[str, Any]) -> "TraceTree":
        nodes = trace_data.get("nodes")
        if nodes is None:
            nodes_tuple: tuple[Mapping[str, Any], ...] = ()
        elif isinstance(nodes, list):
            nodes_tuple = tuple(nodes)
        else:
            raise ValueError(f"trace nodes must be a list, got {type(nodes).__name__}")
        return cls(events=nodes_tuple, format_version=str(trace_data.get("format_version", "")))

    def event_for(self, node_id: str, *, requires_llm_call: bool = False) -> Mapping[str, Any] | None:
        """Top-level event lookup by node_id. Non-recursive.

        `requires_llm_call=True` mirrors `_find_llm_event`'s semantic of
        skipping events without llm_call (preserves multi-event-per-node-id
        contract — verified at token_estimation.py:278-304).
        """
        for event in self.events:
            if not isinstance(event, dict) or event.get("node_id") != node_id:
                continue
            if requires_llm_call and not isinstance(event.get("llm_call"), dict):
                continue
            return event
        return None

    def iter_llm_leaves(
        self,
        events: Iterable[Mapping[str, Any]] | None = None,
        *,
        descend_sub_workflows: bool = True,
        descend_cached_subtrees: bool = True,
        edges: Mapping[str, str] | None = None,
        owner_node_id: str | None = None,
        workflow_path: str | None = None,
    ) -> Iterator[LlmEventLeaf]:
        """Walk events and yield every leaf carrying llm data.

        Yields ALL leaves by default (cached + uncached, all tiers). Consumers
        filter via `leaf.is_cached`, `leaf.tier`, or via the `descend_*` kwargs.

        Recursion shape (matches the workflow_trace.py producer contract):
        - top-level event with llm_call → yield (tier="top", owner_node_id=event["node_id"])
        - batch_items[i] with llm_call → yield (tier="batch_item", owner_node_id=event["node_id"])
        - batch_items[i].events recursion → yield (tier="sub_workflow_descendant",
          owner_node_id=batch_item's events parent)
        - sub_workflow_events recursion (if descend_sub_workflows) →
          yield (tier="sub_workflow_descendant", owner_node_id=immediate parent)

        Cached event handling:
        - When descend_cached_subtrees=True (default for analyzer use): walks
          INTO cached events to surface inner leaves. Consumer filters per leaf.
        - When descend_cached_subtrees=False (producer shims preserving today's
          skip-entire-subtree contract): cached events are skipped completely;
          their batch_items and sub_workflow_events are not recursed.

        Workflow-path threading:
        - When `edges` is provided (typically `cw_result.edges`), descending
          into `sub_workflow_events` looks up the parent_node_id in edges to
          find the child's workflow_path. Yielded leaves carry that
          workflow_path. None for top-level / batch_item leaves of the root
          workflow.
        - When `edges` is None, all yielded leaves have workflow_path=None.

        Does NOT recurse into top-level event["events"] — verified vestigial
        (Phase 1 verification step confirms on real 3-deep trace).
        """
        ...

    def cost_for_event(self, event: Mapping[str, Any]) -> tuple[float | None, str]:
        """Cost paid this run for one event subtree (shallow — top + batch_items only).

        Returns (cost, source) where source ∈ {"trace", "trace_partial", "unavailable"}:
        - "trace": all leaves priced (cost is the sum); cached events contribute 0
        - "trace_partial": at least one leaf has cost_usd=None (unpriced model)
        - "unavailable": event has no LLM data anywhere

        Used by trace_report's per-event cost rendering.

        2.0.0-legacy short-circuit: cached event with no llm_call AND no batch_items
        returns (0.0, "trace") — gated on `self.format_version.startswith("2.0")` to
        prevent silent passthrough on 3.0+ traces (review-silent-failures W6).
        Production 2.1+ traces populate llm_call even for cached LLM events; this
        branch only fires for 2.0.0-legacy traces (per analyze.py:498-505 graceful
        load contract).
        """
        ...

    def cost_for_node(self, node_id: str) -> tuple[float | None, str]:
        """Cost paid this run for one top-level LLM node, scoped to that node.

        Scope: top-level event['llm_call'] + batch_items[*].llm_call. Does NOT
        descend into sub_workflow_events (sub-workflow LLM costs flow through
        their own per-call rows; descending here would double-count).

        Same source contract as cost_for_event.
        """
        ...

    def total_cost(
        self,
        *,
        descend_sub_workflows: bool = True,
        include_cached: bool = False,
        edges: Mapping[str, str] | None = None,
    ) -> tuple[float | None, str]:
        """Sum LLM cost across the whole trace (DEEP — descends sub_workflow_events).

        Used by Phase 2a for `current_cost_per_run_usd` rollup. Naturally
        honest: erroring runs sum what fired; recursive workflows sum each
        actual execution; heterogeneous batches sum per-item recorded cost.

        Returns (None, "unavailable") if no LLM data found in trace.
        Returns (sum, "trace") if all leaves priced.
        Returns (sum, "trace_partial") if any leaf has cost_usd=None.
        """
        ...
```

### Walker migrations (≤5-line shims; preserve old import paths)

- `src/pflow/runtime/workflow_trace.py:283-336` — `_collect_llm_calls_from_events` shim:
  ```python
  def _collect_llm_calls_from_events(self, events):
      from pflow.core.trace_tree import TraceTree
      tree = TraceTree(events=tuple(events), format_version=TRACE_FORMAT_VERSION)
      # descend_cached_subtrees=False preserves today's skip-entire-cached-subtree contract
      return [
          {**leaf.llm_call, "node_id": leaf.owner_node_id, "duration_ms": leaf.event.get("duration_ms"),
           **({"batch_item_index": leaf.event.get("index")} if leaf.tier == "batch_item" else {})}
          for leaf in tree.iter_llm_leaves(descend_cached_subtrees=False)
          if leaf.llm_call
      ]
  ```
- `src/pflow/runtime/workflow_trace.py:476-504` — `_collect_llm_summary` shim: similar pattern with `descend_cached_subtrees=False`; folds via existing `_LLMSummaryAccumulator` (KEEP — it's the right priced/unpriced/unavailable_models split)
- `src/pflow/core/cache_analysis/analyze.py:1940-1951` — `_iter_llm_events` shim:
  ```python
  def _iter_llm_events(events: list[dict]) -> Iterator[tuple[str, dict]]:
      """Backward-compat shim. Yields child node_id for sub_workflow descendants
      (preserves test_iter_llm_events_recurses_into_batch_items contract at
      per_id_emission.py:1539-1572 which asserts "inner-llm" in yielded_node_ids).
      """
      from pflow.core.trace_tree import TraceTree
      tree = TraceTree(events=tuple(events), format_version="2.1")
      for leaf in tree.iter_llm_leaves(descend_cached_subtrees=True):
          # For batch items: yield owner_node_id (existing behavior at line 1949).
          # For sub_workflow descendants: yield event_node_id (the inner LLM's id —
          # preserves the existing test asserting "inner-llm" appears).
          if leaf.tier == "sub_workflow_descendant":
              yield leaf.event_node_id, leaf.event
          else:
              yield leaf.owner_node_id, leaf.event
  ```
- `src/pflow/core/trace_report.py:166-248` — collapse 4 helpers via TraceTree:
  - DROP top-level `event["events"]` recursion at lines 222-225 (vestigial — sole producer is `batch_executor.py:723` writing into `batch_items[i]`)
  - DROP corresponding line at line 248 in `_has_any_cost_data`
  - **Phase 1 verification step (mandatory before this commit)**: produce a real 3-deep trace via running a multi-workflow fixture; capture pre-Phase-1 `_compute_event_cost(event)` output for every event; assert post-Phase-1 produces byte-identical numeric results. This defends the "vestigial" claim against the smoke-fixture-only verification gap (review-plan C4).
  - `_compute_event_cost(event)` becomes:
    ```python
    def _compute_event_cost(event):
        from pflow.core.trace_tree import TraceTree
        tree = TraceTree(events=(event,), format_version="2.1")
        cost, source = tree.cost_for_event(event)
        if source == "trace_partial" or source == "unavailable":
            return None
        return cost
    ```
  - `_has_any_cost_data(event)` becomes:
    ```python
    def _has_any_cost_data(event):
        from pflow.core.trace_tree import TraceTree
        tree = TraceTree(events=(event,), format_version="2.1")
        return any(tree.iter_llm_leaves())
    ```
- `src/pflow/core/cache_analysis/context.py`:
  - `AnalysisContext` gains `trace: TraceTree | None` field via classmethod constructor (frozen dataclass requires this):
    ```python
    @classmethod
    def build(cls, *, workflow_ir, parameters=None, memo_cache=None, trace_data=None,
              workflow_path=None, base_path=None) -> "AnalysisContext":
        trace = TraceTree.from_dict(trace_data) if trace_data is not None else None
        return cls(workflow_ir=workflow_ir, parameters=parameters or {},
                   memo_cache=memo_cache, trace_data=trace_data, trace=trace,
                   workflow_path=workflow_path, base_path=base_path)
    ```
    Update `analyze.py:339` to call `AnalysisContext.build(...)`.
  - `trace_event_for(node_id)` → 1-line delegation: `return self.trace.event_for(node_id) if self.trace else None`
  - `cost_usd_for_node(node_id)` → 1-line delegation: `return self.trace.cost_for_node(node_id) if self.trace else (None, "unavailable")`
  - `_walk_event_for_cost` (lines 207-246) MOVES into `TraceTree.cost_for_node` implementation; the standalone helper goes away
  - **KEEP the 2.0.0-legacy short-circuit** at `TraceTree.cost_for_event` with the new VERSION GATE (`self.format_version.startswith("2.0")`); not the SHAPE gate alone (per review-silent-failures W6)
- `src/pflow/core/cache_analysis/token_estimation.py:278-304` — `_find_llm_event` becomes:
  ```python
  def _find_llm_event(trace: dict, node_id: str) -> dict | None:
      """Return the llm_call dict for the first event matching node_id THAT HAS
      llm_call. Preserves multi-event-per-node-id semantic (review-plan C2)."""
      from pflow.core.trace_tree import TraceTree
      tree = TraceTree.from_dict(trace)
      event = tree.event_for(node_id, requires_llm_call=True)
      return event.get("llm_call") if event else None
  ```

### Test surface (~25 tests; mutation contracts with explicit expected values)

`tests/test_core/test_trace_tree.py` (NEW, ~500 LOC including fixtures):

Each test specifies the mutation contract in its docstring with the EXACT production line/branch reverted AND the EXACT assertion that fails when mutated. Pattern mirrors `tests/test_core/test_cache_analysis_cost_estimation.py:419-454` (the M-class sentinel).

- `test_from_dict_handles_empty_nodes` — `TraceTree.from_dict({"format_version": "2.1", "nodes": []})` constructs; `iter_llm_leaves()` yields nothing; `total_cost() == (None, "unavailable")`. Mutation: change `total_cost` to return `(0.0, "trace")` for empty → assertion fails (defends explicit-`None`-not-`0.0` for empty trace).
- `test_from_dict_handles_missing_nodes_key` — `{"format_version": "2.1"}` constructs cleanly with empty events.
- `test_from_dict_rejects_non_list_nodes` — raises `ValueError` with type-name in message. Mutation: silently coerce to `[]` → assertion `pytest.raises(ValueError)` fails.
- `test_iter_llm_leaves_yields_top_level_llm_call` — fixture with single top-level event with llm_call; `len(list(tree.iter_llm_leaves())) == 1`; leaf has `tier == "top"`, `owner_node_id == "draft"`. Mutation: drop top-level branch → `len == 0` fails.
- `test_iter_llm_leaves_yields_batch_item_llm_call` — fixture with batch parent + 3 items each with llm_call; expect 3 leaves with `tier == "batch_item"`, `owner_node_id == "batch-parent"`. Mutation: drop batch_items recursion → `len == 0` fails.
- `test_iter_llm_leaves_recurses_batch_items_events` — batch item with sub-workflow events containing inner LLM; expect leaf with `tier == "sub_workflow_descendant"`, `event_node_id == "inner-llm"`. Mutation: drop `item.get("events", [])` recursion → leaf missing.
- `test_iter_llm_leaves_recurses_sub_workflow_events_when_kwarg_true` — top-level workflow node with sub_workflow_events; default `descend_sub_workflows=True`; leaf yielded. Mutation: change default to `False` → leaf missing.
- `test_iter_llm_leaves_skips_sub_workflow_events_when_kwarg_false` — same fixture, `descend_sub_workflows=False`; no leaf yielded.
- `test_iter_llm_leaves_yields_cached_events_when_descend_cached_subtrees_true` — cached LLM event with `llm_call.cost_usd=0.0`; leaf yielded; `leaf.is_cached == True`. Mutation: filter `leaf.is_cached` at primitive → discrepancy detection regresses.
- `test_iter_llm_leaves_skips_cached_subtree_when_descend_cached_subtrees_false` — cached batch parent with non-cached children; expect zero leaves. **Mutation: filter `leaf.is_cached` at the leaf level instead of the subtree level → leaf count == 1 (the inner non-cached child) → assertion `len == 0` fails. Defends review-silent-failures C1.**
- `test_iter_llm_leaves_does_not_recurse_top_level_events` — synthetic event with `event["events"]` populated at top level (NOT a real production shape, but defends against vestigial-branch reintroduction); leaf NOT yielded.
- `test_iter_llm_leaves_threads_workflow_path_via_edges` — fixture with parent event + sub_workflow_events; pass `edges={"parent-node": "child.pflow.md"}`; leaf yielded with `workflow_path == "child.pflow.md"`. Mutation: drop edges threading → `workflow_path is None` fails.
- `test_event_for_top_level_only` — sub-workflow inner node_id NOT findable; only top-level matches.
- `test_event_for_requires_llm_call_skips_events_without_llm_call` — fixture with two events sharing node_id "draft"; first lacks llm_call, second has it; `event_for("draft", requires_llm_call=True)` returns the second. Mutation: return first match unconditionally → wrong event returned. **Defends review-plan C2.**
- `test_cost_for_node_priced_event_returns_trace_tier` — single LLM, `cost_usd=0.01`; expect `(0.01, "trace")`.
- `test_cost_for_node_cached_event_returns_zero_trace` — cached LLM with `llm_call.cost_usd=0.0`; expect `(0.0, "trace")`.
- `test_cost_for_node_2_0_0_legacy_cached_no_llm_call_returns_zero_trace` — 2.0.0 fixture, cached event without llm_call without batch_items; expect `(0.0, "trace")`. Mutation: drop the 2.0.0 short-circuit → `(None, "unavailable")` fails.
- `test_cost_for_node_3_0_0_cached_no_llm_call_does_NOT_short_circuit` — 3.0.0 fixture (synthetic), cached event without llm_call; expect `(None, "unavailable")`. Mutation: gate-on-shape-only (omit version check) → `(0.0, "trace")` returned → assertion fails. **Defends review-silent-failures W6.**
- `test_cost_for_node_unpriced_returns_trace_partial` — `cost_usd=None`; expect `(_, "trace_partial")`.
- `test_cost_for_node_does_NOT_descend_into_sub_workflow_events` — synthetic parent event with llm_call=$0.01 + `sub_workflow_events` containing $99.99 child llm_call; expect `(0.01, "trace")`. **Mutation contract**: change `cost_for_node` to call `iter_llm_leaves(descend_sub_workflows=True)` → assertion `cost == 0.01` fails with `cost == 100.00`. (M-class sentinel preservation.)
- `test_cost_for_node_partial_batch_some_cached` — mixed batch (2 priced at $0.01 each, 1 cached at $0.0); expect `(0.02, "trace")`.
- `test_cost_for_node_returns_unavailable_for_missing_node` — `(None, "unavailable")`.
- `test_total_cost_descends_sub_workflows` — fixture with parent llm_call $0.01 + sub_workflow_events containing $0.20; default `descend_sub_workflows=True`; expect `(0.21, "trace")`.
- `test_total_cost_descends_sub_workflows_recursive_3_deep` — fixture with 3-deep nesting (A → B → C); each level has $0.10; expect `(0.30, "trace")`.
- `test_total_cost_includes_cached_when_kwarg_true` — fixture with cached LLM ($0 by definition); `include_cached=True` → cost includes leaf at $0.

Existing tests preserved via shims:
- `test_iter_llm_events_includes_cached_events` (per_id_emission.py:1519) — preserved by `_iter_llm_events` shim
- `test_iter_llm_events_recurses_into_batch_items` (per_id_emission.py:1539) — preserved by shim's `tier == "sub_workflow_descendant"` → yield `event_node_id` branch (per the contract above)
- `test_cost_usd_for_node_treats_cached_event_as_zero_not_unavailable` (cost_estimation.py:388) — preserved by `cost_for_node`
- `test_cost_usd_for_node_does_not_descend_into_sub_workflow_events` (cost_estimation.py:419) — preserved (M-class sentinel; explicitly load-bearing)
- `test_cost_usd_for_node_returns_trace_partial_when_some_leaves_unpriced` (cost_estimation.py:457) — preserved
- All trace_report tests — preserved (shim semantics identical post-vestigial-branch removal, verified by Phase 1 verification step)

### Brownfield/greenfield handling (Phase 1)

- **Brownfield + trace**: `AnalysisContext.build(...)` constructs `TraceTree`; `cost_for_node` returns trace-tier costs as today.
- **Greenfield no trace**: `AnalysisContext.build(trace_data=None)` → `self.trace is None`; `cost_for_node` returns `(None, "unavailable")`.
- **Empty trace `{nodes: []}`**: TraceTree constructed with empty events tuple; `iter_llm_leaves()` yields nothing; per-call rows have `cost_usd=None`, `cost_data_source="recomputed"` — preserves today.
- **Malformed trace (non-list nodes)**: TraceTree raises ValueError. Existing 2 call sites that previously returned None (`context.py:68-70`, `token_estimation.py:295-297`) wrap in try/except to keep graceful degradation.

---

## Phase 2a — Sub-workflow rollup mechanics (THIRD commit, ~500 LOC delta)

**Goal**: rolled-up `current_cost_per_run_usd` (trace-driven) + per-call rows from all reachable workflows (IR-driven via `walk_cross_workflow`) + per-workflow Track B/C parameter views + ALL bare-`node_id` dicts migrated.

**No subset-key change yet (Phase 2b owns that landmine in isolation).**

### Architecture per the trace-driven / IR-driven split

**Trace-driven `current_cost_per_run_usd`**:
- `_build_summary` (analyze.py:2323-2401) reads `current_cost_per_run_usd` from `AnalysisContext.trace.total_cost(descend_sub_workflows=True, include_cached=False)`
- IF `ctx.trace is None` (greenfield): falls through to today's recompute path via `compute_aggregate_costs`
- Naturally honest for: erroring runs, recursive workflows, heterogeneous batches

**IR-driven per-call rows + projections**:
- `_build_per_call_rows_and_warnings` (analyze.py:589-618) becomes:
  ```python
  def _build_per_call_rows_and_warnings(*, ctx, declared_chunks, candidate_subsets_by_node, cw_result):
      rows: list[PerCallRow] = []
      warnings: list[Diagnostic] = []
      for workflow_path, ir in cw_result.irs_by_workflow.items():
          # Per-workflow parameters view (Track B/C parity for sub-workflow rows)
          wf_parameters = ctx.parameters_for_workflow(workflow_path)
          # Per-workflow context — same memo cache, scoped parameters
          wf_ctx = AnalysisContext(
              workflow_ir=ir,
              parameters=wf_parameters,
              memo_cache=ctx.memo_cache,
              trace_data=ctx.trace_data,
              trace=ctx.trace,
              workflow_path=workflow_path,
              base_path=ctx.base_path,
          )
          for node in ir.get("nodes", []):
              if not isinstance(node, dict) or node.get("type") != "llm":
                  continue
              row = _build_per_call_row(
                  ctx=wf_ctx,
                  node=node,
                  workflow_path=workflow_path,  # NEW field on PerCallRow
                  ...
              )
              rows.append(row)
      return rows, warnings
  ```
- `walk_cross_workflow(root_ir, base_path=ctx.base_path, root_workflow_path=ctx.workflow_path, notes=local_notes)` is called ONCE at the top of `analyze()` and the result is shared by `_build_per_call_rows_and_warnings` AND `_build_cross_workflow_findings` (today both would re-walk; the cached result is passed through). Mitigates review-feature-interactions WARN-5.
- `PerCallRow.cost_usd` lookup uses TraceTree's `(workflow_path, node_id) → leaf` index, built via `iter_llm_leaves(edges=cw_result.edges, descend_sub_workflows=True)`. Each leaf carries its `workflow_path` from the edge correlation.
- For erroring-run rows where the trace lacks the corresponding event: `cost_for_node` returns `(None, "unavailable")` → `_build_per_call_row` overlays `cost_data_source = "recomputed"` per existing fallback at analyze.py:766-767. The recompute-fallback IS today's defense; it's correct here.
- **Phantom-cost defense** (review-silent-failures C6): when sub-workflow row has `cost_data_source = "recomputed"` AND the trace contains data for OTHER nodes in the same workflow_path (suggesting the workflow ran but this specific node didn't), surface a row-level note: `"sub_workflow_node_did_not_execute"`. Renderer suppresses the recompute cost for these rows (renders as `?`/`unavailable`) so they don't inflate the projection. Mutation contract test added.

### `PerCallRow` and bare-node_id dict migrations

- `PerCallRow` (analyze.py:74-143) gains `workflow_path: str | None` field (default None for backward compat in renderer/summarize tests)
- `rows_by_node` at analyze.py:359 → `rows_by_key: dict[tuple[str | None, str], PerCallRow] = {(row.workflow_path, row.node_path): row for row in per_call_rows}`. Update consumers: `_populate_suggested_blocks`, `_emit_padding_advisories`, `_consolidate_to_root_advisories`, `_cache_validator_findings`.
- `output_tokens_by_node` at analyze.py:2358 → `output_tokens_by_key: dict[tuple[str | None, str], int | None]`. Update lookup at `cost_estimation.py:328`.
- `nodes_by_id` at analyze.py:1064 (used by `_opaque_prompt_warnings`) → `nodes_by_key: dict[tuple[str | None, str], dict]`. The function builds this PER WORKFLOW; `_opaque_prompt_warnings` now takes a `workflow_path` arg and looks up `nodes_by_key.get((workflow_path, root))`.
- `warnings_by_node` at render_text.py:660,673,689,824 → `warnings_by_key: dict[tuple[str | None, str], list[str]]`. Diagnostic's `context["affected_workflow"]` field is required for sub-workflow row warnings; the renderer reads it for keying.

### `AnalysisContext.parameters_for_workflow`

```python
def parameters_for_workflow(self, workflow_path: str | None) -> Mapping[str, Any]:
    """Return the parameters view for one workflow_path in the rollup.

    For root workflow_path → returns self.parameters.
    For sub-workflow workflow_path → walks parent edges to resolve the parent
    node's `inputs:` mapping against parent's parameters; returns the resolved
    dict. Memoized per workflow_path to avoid repeated traversal.
    """
    ...
```

This requires `cw_result.edges` access. Three options:
1. Pass `cw_result` into `AnalysisContext.build()` — simplest; couples context to walker result
2. Build the parameter views eagerly in `analyze()` and pass to context construction — keeps context decoupled
3. Lazy-compute on first call, cache on context — requires mutable cache despite frozen dataclass

**Choice**: option 2 (eager build at `analyze()` top-level). `AnalysisContext.build(parameters_by_workflow={"path": {...}, ...})`. Simpler than option 3; cleaner than option 1.

### Renderer changes (Phase 2a does NOT change render output yet)

- Phase 2a does NOT touch render_text.py grouping or render_json.py per-call schema. Per-call table stays flat (gets longer). Header stays single-line.
- The user sees rolled-up `current_cost` (trace-driven, accurate) and the per-call table with all rows but no grouping. UX-improvement deferred to 2c.

### Test additions (Phase 2a; ALL mutation-contracted with explicit expected values)

Synthetic trace fixtures use `TraceFixtureBuilder` helper that produces dicts matching the EXACT shape `WorkflowTraceCollector` writes (verified by snapshot test against real workflow run). Defends Pitfall #19 attractor.

- `test_summary_current_cost_includes_sub_workflow_costs_via_trace_driven_total_cost` — fixture: parent (1 LLM @ $0.05) + sub-workflow (1 LLM @ $0.10) trace; expect `summary.current_cost_per_run_usd == 0.15`. Mutation: revert `_build_summary` to use `compute_aggregate_costs.current_usd` instead of `tree.total_cost()` → `current_cost == 0.05`.
- `test_summary_current_cost_3_deep_recursive_correct` — A → B → C trace, each level $0.10; expect $0.30. Mutation: change `total_cost` to `descend_sub_workflows=False` → $0.10.
- `test_summary_current_cost_recursive_workflow_counts_actual_executions` — A → A (self-recurse, depth 2 actual executions); expect cost equals 2× per-call cost (NOT 1×). Mutation: revert to IR-driven (cycle-detect counts once) → cost == 1× → assertion fails. **Defends review-silent-failures C5.**
- `test_summary_current_cost_erroring_run_reports_what_fired` — fixture: parent ran, sub-workflow errored AFTER first LLM call; trace has only first child event; expect `current_cost == parent + first_child_cost` (NOT including the un-executed second child). Mutation: revert to IR-driven recompute → phantom cost from un-executed child. **Defends review-silent-failures C6.**
- `test_per_call_rows_carry_workflow_path` — verify each row's `workflow_path` matches its source workflow.
- `test_per_call_row_for_unexecuted_subworkflow_node_marks_did_not_execute` — fixture: child workflow IR has 2 LLM nodes; trace shows only 1 ran; the 2nd row has `cost_data_source == "recomputed"` AND a `did_not_execute_in_trace` flag; renderer suppresses the recomputed cost. Mutation: drop the suppression → row contributes phantom cost to aggregates.
- `test_summary_handles_heterogeneous_batch_sub_workflow_inline_static` — `items: [{workflow: "a"}, {workflow: "b"}]`; expect both children's costs included from trace.
- `test_summary_handles_template_items_batch_unresolvable_at_analyze_time_via_trace_driven` — `items: ${list}`, `workflow: ${item.workflow}`; trace HAS the events; `current_cost` includes them via trace-driven sum. Per-call rows skipped (notes entry surfaces it). **Mutation: drop trace-driven `total_cost` → `current_cost` excludes template-items children → assertion fails.**
- `test_summary_cycle_truncation_surfaces_in_notes_with_remediation` — A→B→A; rolled-up cost honest from trace; notes entry includes remediation text per A6 spec.
- `test_rows_by_key_distinguishes_same_node_id_across_workflows` — fixture: parent has node "draft", child has node "draft"; both rows present in `rows_by_key` (no overwrite). **Mutation: revert to bare-node_id keying → child overwrites parent → row count == 1 instead of 2.** Defends review-impact-completeness C1.
- `test_output_tokens_by_key_distinguishes_same_node_id_across_workflows` — same shape as above, for `output_tokens_by_node` migration.
- `test_warnings_by_key_distinguishes_same_node_id_across_workflows` — same shape for renderer warnings lookup.
- `test_opaque_prompt_warnings_uses_per_workflow_nodes_lookup` — fixture: child workflow has node `some_code` with `node_type=python`; child's LLM node has `prompt: ${some_code.result}`; opaque-prompt warning fires correctly attributed to child. Mutation: use parent-only `nodes_by_id` → warning silently lost.
- `test_parameters_for_workflow_returns_resolved_child_inputs` — fixture: parent passes `inputs: {brief: ${concept.text}}` to child; `ctx.parameters_for_workflow(child_path)["brief"]` returns the resolved value. Mutation: return root parameters → child resolves wrong values for cacheable_data_source tier.
- `test_track_B_cacheable_data_source_for_sub_workflow_row_uses_per_workflow_parameters` — end-to-end test that a sub-workflow row's `cacheable_data_source` is `"parameters"` when child's input was passed by parent (NOT `"unavailable"` from missing root param).
- `test_track_C_resolved_prompt_for_sub_workflow_row_uses_per_workflow_context` — end-to-end test that token estimation honors per-workflow resolved prompt.
- `test_walk_cross_workflow_called_once_shared_between_findings_and_per_call_rows` — instrument walker; assert call count == 1. Mutation: regression that re-walks → call count == 2 → assertion fails.

Updates to existing tests:
- `test_cost_usd_for_node_does_not_descend_into_sub_workflow_events` (cost_estimation.py:419) — KEEP unchanged. `cost_for_node` is intentionally shallow per A1 (cost_for_node is per-node attribution; total_cost is rollup).
- Greenfield tests at `test_cache_analysis_analyze.py:643, 1011` — verify still pass.

### CliRunner integration test (Phase 2a)

`tests/test_cli/test_analyze_cache.py::test_analyze_cache_rolls_up_sub_workflow_costs_via_subprocess`:
- Writes parent + child .pflow.md to `tmp_path` matching the committed fixtures (see Phase 2c)
- Invokes `cli` via `CliRunner.invoke(["analyze-cache", str(tmp_path / "parent.pflow.md"), "--from-trace", str(tmp_path / "trace.json")])`
- Asserts `result.exit_code == 0`
- Asserts `"current cost"` line in `result.output` includes both parent + child contributions
- Asserts header line shows N+M LLM nodes
- **Mutation contract**: revert any phase 2a production change → assertion fails

### Brownfield/greenfield handling (Phase 2a)

- **Brownfield + trace**: `current_cost` from `tree.total_cost()` (trace-driven, accurate); per-call rows for all reachable workflows; row costs from TraceTree index
- **Brownfield no trace**: `tree is None` → falls through to today's `compute_aggregate_costs`-based path; per-call rows for all reachable workflows but all `cost_usd=None`
- **Greenfield with `--inputs`**: per-workflow parameter views resolve child inputs from parent's `inputs:` mapping; cacheable_data_source correctly tiered
- **Greenfield no inputs**: per-call rows have `cost_usd=None`, `cacheable_data_source` tiered per existing 4-tier hierarchy
- **Empty trace `{nodes: []}`**: `tree.total_cost() == (None, "unavailable")` → falls through to recompute; per-call rows from IR

---

## Phase 2b — Subset-key workflow scope + discrepancy detection scope (FOURTH commit, ~250 LOC delta)

**Goal**: prevent cross-pollination when parent and child workflows both declare `prompt_cache: [<same chunk name>]` with different prose. Per DD#12, each `.pflow.md` scopes its own caching.

**This is the v1.x landmine the handoff explicitly warned about.** Atomic migration in one commit.

### Production changes

- `src/pflow/core/cache_analysis/cost_estimation.py`:
  - `_aggregate_no_cache_cost` (split out in Phase 3): no subset grouping; per-row sum; **no change in 2b**
  - `_aggregate_with_cache_projection` (split out in Phase 3): subset grouping change:
    ```python
    subset_key = (row.workflow_path, tuple(row.declared_prompt_cache)) if row.declared_prompt_cache else None
    ```
  - `_aggregate_first_run_savings` (line 451): same subset_key change
  - `_aggregate_rerun_savings` (line 486): **NO CHANGE** — already per-row, no grouping (verified at cost_estimation.py:486-502)
- `src/pflow/core/cache_analysis/analyze.py`:
  - `_flatten_plan_keys` (line 2027-2074): re-key from `dict[node_id, cache_key]` to `dict[(workflow_path, node_id), cache_key]`. Threads workflow_path via Plan walking.
  - **Plan-side workflow_path threading** (per W7 verification): `Plan` dataclass at `execution/result.py:175-182` does NOT carry the canonical workflow_path; `Plan.workflow` is set inconsistently. **Add `Plan.workflow_path: str | None = None` field**, populated by `_build_plan_with_shared` at construction in `execution/plan.py` from the local `workflow_path` (the `_pflow_workflow_file` from shared store). `_flatten_plan_keys`'s recursive `_walk(p, workflow_path)` reads `plan.workflow_path` and recurses with `entry.sub_plan.workflow_path`.
  - `_emit_discrepancy_diagnostics` (line 2103+): match using `(workflow_path, node_id)` tuple. Iterates `tree.iter_llm_leaves(descend_sub_workflows=True, edges=cw_result.edges)`; each leaf carries `workflow_path`; lookup is `predicted_keys.get((leaf.workflow_path, leaf.event_node_id))`.
  - The heterogeneous-batch collision drop (lines 2042-2065) — collisions across workflows now resolved by tuple key. Keep collision logic for collisions WITHIN the same workflow (still possible for heterogeneous-template batches within one IR). Update notes message to clarify the remaining case.

### Test additions (cross-pollination defense)

- `test_aggregate_with_cache_projection_groups_by_workflow_scope` — synthetic parent + child both declaring `prompt_cache: [context]` with different prose. Each gets its own write+reads cycle. **Mutation contract**: drop `workflow_path` from subset_key → with-cache projection inflates by exactly `(write_rate - read_rate) * cacheable_tokens` for the child's first call → assertion fails with specific dollar amount.
- `test_aggregate_first_run_savings_groups_by_workflow_scope` — same pattern.
- `test_predicted_keys_distinguishes_same_node_id_across_workflows` — child workflow has node "draft" with cache_key X; parent also has "draft" with cache_key Y; both survive in `predicted_keys` (no collision drop). **Mutation contract**: revert to bare-node_id key → both dropped via collision detection → discrepancy detection silently misses both for traces.
- `test_discrepancy_detection_matches_across_workflows` — trace has cache_read on parent's "draft" AND child's "draft"; both predicted; both match correctly. **Mutation contract**: drop `edges` arg from `iter_llm_leaves` call in `_emit_discrepancy_diagnostics` → matches against wrong workflow's prediction → false `key_mismatch` for one of them.
- `test_aggregate_rerun_savings_unchanged_per_row` — verify no regression (rerun is per-row).
- `test_plan_workflow_path_field_set_by_build_plan_with_shared` — add `Plan.workflow_path` exists and is populated. Mutation: leave as None → `_flatten_plan_keys` keying breaks.

### CliRunner integration test (Phase 2b)

`tests/test_cli/test_analyze_cache.py::test_analyze_cache_does_not_cross_pollinate_subset_groups`:
- Fixture: parent + child both declaring `prompt_cache: [context]` with different prose
- Subprocess invocation
- Asserts `summary.cost_without_caching_usd` does NOT show inflated savings; assertion includes the specific expected dollar amount derived from per-row math

---

## Phase 2c — Renderer + JSON metadata + agent UX (FIFTH commit, ~300 LOC delta)

**Goal**: per-call table grouped by workflow_path; header surfaces sub-workflow count; new JSON `sub_workflow_rollup` field; notes get actionable remediation; discrepancy/unpriced-models messages carry workflow scope; drill-in nudge.

### Production changes

- `src/pflow/core/cache_analysis/analyze.py`:
  - Add `SubWorkflowRollup` frozen dataclass:
    ```python
    @dataclass(frozen=True)
    class SubWorkflowRollupEntry:
        workflow_path: str
        called_by_node_id: str
        llm_node_count: int
        current_cost_usd: float | None
        cost_without_caching_usd: float | None

    @dataclass(frozen=True)
    class SubWorkflowRollup:
        workflows_included: tuple[str, ...]
        max_depth_walked: int
        truncated: bool
        per_workflow: tuple[SubWorkflowRollupEntry, ...]  # per-workflow attribution
    ```
  - `AnalysisSummary` gains `sub_workflow_rollup: SubWorkflowRollup | None` field (None when no sub-workflows reachable from root)
  - Distinguish "no sub-workflows" (`sub_workflow_rollup = None`) from "tried to walk but truncated" (`sub_workflow_rollup = SubWorkflowRollup(workflows_included=(), truncated=True, ...)`). Per review-silent-failures W7.
  - `unavailable_models` aggregation per review-agent-ux W2: keep existing flat `tuple[str, ...]` for backward compat; ADD new `unavailable_models_by_workflow: dict[str, tuple[str, ...]]` field for per-workflow attribution
- `src/pflow/core/cache_analysis/render_text.py`:
  - `_format_scale_line` returns single line as today; new helper `_format_sub_workflow_breakdown_line(rollup) -> str | None` returns the "(7 in song-creator.pflow.md, 34 in 2 sub-workflows: chorus-chooser, review)" line; `_render_summary` emits both
  - Header label uses full `.pflow.md` filenames consistently (per review-agent-ux C3)
  - `_render_per_call`: when rows span multiple workflow_paths, group by workflow_path; emit `### <workflow_path>` subheaders. For sub-workflow groups, append `(called by <parent_node_id>)` annotation derived from `cw_result.edges`. Single-workflow analysis: no subheaders (preserves existing simple output)
  - Notes-rendering improvements (per review-agent-ux C5):
    - Cycle truncation note text: `"Cross-workflow walker detected cycle: A → B → A — cycle skipped. Cost rollup is trace-driven so actual recursion is correctly summed; the IR enumeration was truncated."` (clarifies the fix from architectural pivot A1)
    - Depth truncation note text: `"Cross-workflow walker reached max_depth=10 at <parent_label>. Cost rollup is trace-driven (current_cost reflects actual execution); IR-driven projections under-cover deeper boundaries. Set --max-depth=N to extend if needed."`
    - Template-items batch note text: `"items: ${list} resolves at runtime; sub-workflow rows for these items are not in the per-call table. current_cost is trace-driven and reflects actual execution. Provide --inputs '<input>=<resolved-list>' to enable static enumeration of children."`
  - `unavailable_models` rendering: `"Unpriced models: <model> (in <workflow_path_short>)"` when sourced from a sub-workflow
  - Drill-in section emission (per review-agent-ux C4):
    ```
    ## Sub-workflow drill-in

      Sub-workflow opportunities don't surface here — run analyze-cache per child:
        pflow analyze-cache chorus-chooser.pflow.md
        pflow analyze-cache review.pflow.md
    ```
    Only emitted when `sub_workflow_rollup` is non-None
- `src/pflow/core/cache_analysis/render_json.py`:
  - Add `"sub_workflow_rollup"` field to `_summary_to_dict` output
  - Add `"unavailable_models_by_workflow"` field
  - Each per-call dict includes `"workflow_path": row.workflow_path` (additive to schema; safe within 3.x)
- `src/pflow/core/cache_analysis/warning_catalog.py:415-444` — `cache.discrepancy` message template (per review-agent-ux C6):
  - Extend `required_context_keys` to include `workflow_path_short`
  - Update message template: `"{node_id} in {workflow_path_short} (trace: {trace_path}): predicted ..."`
  - `_emit_discrepancy_diagnostics` populates `context["workflow_path_short"]` from leaf's workflow_path

### Test additions

- `test_render_text_groups_per_call_by_workflow_path` — assert specific subheader literals like `### chorus-chooser.pflow.md (called by choose-chorus)`. Mutation: revert grouping → flat table → subheader literal NOT in output → fails
- `test_render_text_header_includes_sub_workflow_count` — assert specific suffix literal `(7 in song-creator.pflow.md, 34 in 2 sub-workflows: ...)`
- `test_render_text_drill_in_section_emitted_when_sub_workflows_present` — assert `"## Sub-workflow drill-in"` in output AND specific command literals
- `test_render_text_drill_in_section_omitted_for_single_workflow` — single-workflow analysis: no drill-in section, no subheaders
- `test_render_text_template_items_note_includes_remediation` — assert note text contains `"Provide --inputs"`
- `test_render_text_cycle_note_includes_clarification_about_trace_driven_rollup` — assert note clarifies the cost is honest
- `test_render_text_unpriced_model_includes_workflow_attribution` — assert workflow short name appears
- `test_render_text_discrepancy_message_includes_workflow_scope` — `cache.discrepancy` rendered output includes workflow path
- `test_render_json_summary_includes_sub_workflow_rollup_field` — non-None when sub-workflows present, None for single-workflow
- `test_render_json_per_call_rows_carry_workflow_path` — every row dict has `"workflow_path"` key
- `test_render_json_unavailable_models_by_workflow_field_present` — additive 3.x field
- `test_render_text_truncated_rollup_emits_warning_note` — fixture with cyclic A→B→A; assert text includes the note AND the `truncated == True` field surfaced in summary block
- `test_summary_partial_sub_workflow_trace_reports_what_fired` — synthetic trace where parent has `sub_workflow_events: [event_1]` only; child IR declares 2 LLM nodes; rollup current_cost includes only event_1's cost; per-call row for un-executed event_2 has `did_not_execute_in_trace` flag

### CliRunner integration test (Phase 2c)

`tests/test_cli/test_analyze_cache.py::test_analyze_cache_renders_grouped_per_call_table_with_drill_in`:
- Subprocess invocation against the committed multi-workflow fixture
- Asserts `### <child_path> (called by <node>)` subheaders in output
- Asserts drill-in section literal
- Asserts header line literal

---

## Test infrastructure (lands with Phase 2a, used by Phase 2b/2c)

### Committed multi-workflow fixtures (per review-test-fidelity C5)

`tests/fixtures/cache_analysis/`:
- `parent.pflow.md` — parent workflow with one LLM node + one sub-workflow node
- `child.pflow.md` — child workflow with two LLM nodes; declares `## Cache` block
- `parent-child-trace.json` — real trace from running parent (synthesized via test setup that runs the workflow once and snapshots the trace)
- `parent-child-erroring-trace.json` — trace where child errored after first LLM call (for phantom-cost defense test)
- `parent-with-cycle.pflow.md` + cycle-trace fixture
- `parent-with-template-items-batch.pflow.md` + trace fixture

### `TraceFixtureBuilder` helper (per review-test-fidelity C2)

```python
class TraceFixtureBuilder:
    """Builds synthetic trace dicts that match the EXACT shape WorkflowTraceCollector
    writes. Verified by snapshot test against real workflow run.

    Pitfall #19 defense: a separate test (test_trace_fixture_builder_matches_production_shape)
    runs a tiny real workflow and asserts builder-generated dicts have the same key set
    as the runtime-produced events.
    """
    def llm_event(self, node_id: str, *, cost_usd: float, ...) -> dict: ...
    def cached_llm_event(self, node_id: str, ...) -> dict: ...
    def batch_event(self, node_id: str, items: list[dict], ...) -> dict: ...
    def workflow_event(self, node_id: str, sub_workflow_events: list[dict], ...) -> dict: ...
```

`test_trace_fixture_builder_matches_production_shape`:
- Runs a real 2-LLM workflow via `WorkflowRunner`
- Captures `WorkflowTraceCollector.events`
- Asserts builder-generated event has `set(real_event.keys()) == set(builder_event.keys())` for top-level, batch_items[i], sub_workflow_events[i]
- This is the **load-bearing Pitfall #19 defense** — every Phase 1/2/3 test uses TraceFixtureBuilder; this test ensures builder doesn't drift from production shape

### Mutation contract documentation pattern

Every new test ships with a docstring matching this template (greppable, agent-readable):

```python
def test_X():
    """Mutation contract: revert <file>:<line> (specifically: <code change>) →
    assertion `assert <expected>` fails with `<failure form>`.

    Defends: <which review finding or which production behavior>.
    """
```

---

## Verification

Each phase ships green:
```bash
make test                                          # full suite (currently 6,061+; this work adds ~50 tests)
make check                                         # ruff + ruff-format + mypy + deptry
uv run pytest tests/test_execution/test_plan_drift.py    # 33/33 — sacred parity (correct path verified)
uv run pytest tests/test_runtime/test_prompt_cache_hash.py    # golden baseline (DD#19)
```

End-to-end smoke verification per phase:

**After Phase 3 (rename)**:
```bash
uv run pflow analyze-cache scratchpads/stage2-verification/gemini-smoke/smoke-with-cache.pflow.md \
  --from-trace scratchpads/stage2-verification/gemini-smoke/RUN2-with-cache-trace.json \
  --format=json | jq '.format_version, .summary.cost_without_caching_usd'
# Expected: "3.0", and the value previously reported as optimized_cost_per_run_usd
```

**After Phase 1 (TraceTree)**:
```bash
# Same command. Output byte-identical (modulo Phase 3 rename).
# CRITICAL Phase 1 verification step (defends review-plan C4):
# Synthesize a 3-deep multi-workflow trace via TraceFixtureBuilder; capture pre-Phase-1
# _compute_event_cost(event) results for every event; assert post-Phase-1 produces
# byte-identical numeric results. Confirms the "vestigial event['events']" claim
# beyond the 1-level smoke fixture.
```

**After Phase 2a (current_cost rollup)**:
```bash
# Manual verification on real workflow (outside repo):
uv run pflow analyze-cache /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md
# Expected: header reports ~41 LLM nodes (up from 7); summary current_cost ~$0.45 (up from $0.10).

# Automated verification on committed fixture:
uv run pytest tests/test_cli/test_analyze_cache.py::test_analyze_cache_rolls_up_sub_workflow_costs_via_subprocess
```

**After Phase 2b (subset key)**:
```bash
uv run pytest tests/test_cli/test_analyze_cache.py::test_analyze_cache_does_not_cross_pollinate_subset_groups
```

**After Phase 2c (renderer)**:
```bash
uv run pytest tests/test_cli/test_analyze_cache.py::test_analyze_cache_renders_grouped_per_call_table_with_drill_in
# Manual: same song-creator command as 2a. Verify per-call table grouped, drill-in section emitted.
```

---

## Critical files (absolute paths)

**TraceTree (NEW)**:
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/trace_tree.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/test_core/test_trace_tree.py`
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/fixtures/cache_analysis/` (NEW directory)
- `/Users/andfal/projects/pflow-feat-prompt-caching/tests/shared/trace_fixture_builder.py` (NEW)

**Walker shim sites**:
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/runtime/workflow_trace.py:283-336, 476-504`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/trace_report.py:166-248`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:1940-1951`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/context.py:38-205`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/token_estimation.py:278-304`

**Rollup mechanics + bare-node_id dict migrations**:
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:74-143` (`PerCallRow`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:359` (`rows_by_node` → `rows_by_key`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:589-779` (`_build_per_call_rows_and_warnings`, `_build_per_call_row`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:1029-1080` (`_opaque_prompt_warnings` per-workflow keying)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:2027-2171` (`_flatten_plan_keys`, `_emit_discrepancy_diagnostics`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:2358` (`output_tokens_by_node` → `output_tokens_by_key`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/cost_estimation.py:328` (output_tokens lookup)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/cost_estimation.py:397-502` (`_aggregate_*` functions)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/cross_workflow.py:141-340` (REUSE — `walk_cross_workflow`, single-call)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/render_text.py:660,673,689,824` (`warnings_by_node` → `warnings_by_key`)

**Plan-side workflow_path threading (Phase 2b)**:
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/execution/result.py:175-182` (add `Plan.workflow_path` field)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/execution/plan.py:264, 289-294, 347-352` (populate the field)

**Renaming sites (Phase 3)**:
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/analyze.py:215-248, 2382-2383` (`AnalysisSummary`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/cost_estimation.py:67-83, 397-448` (`AggregateCostBreakdown`, `_aggregate_optimized_cost`)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/render_text.py:200-219`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/render_json.py:31-32, 87-117, 161` (constants, version-history, JSON key)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/__init__.py:11-12` (module docstring)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/summarize.py:70`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/mcp_server/tools/execution_tools.py:374-380` (LLM-visible docstring rewrite)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/mcp_server/services/execution_service.py:382-387`

**Renderer + UX (Phase 2c)**:
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/render_text.py:113-170, 637-667, 831-837`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/render_json.py:157-184`
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/warning_catalog.py:415-444` (`cache.discrepancy` message template)
- `/Users/andfal/projects/pflow-feat-prompt-caching/src/pflow/core/cache_analysis/cross_workflow.py:211, 282-283` (note text actionability)

**Test sites needing updates**:
- `tests/test_core/test_cache_analysis_analyze.py` (lines 590, 592, 643, 1011, 1012, 1742, 1797, 1799)
- `tests/test_core/test_cache_analysis_cost_estimation.py` (lines 172, 388, 414, 419, 452, 457, 486)
- `tests/test_core/test_cache_analysis_renderers.py` (lines 4, 15-16, 54, 55, 84, 86, 87, 88, 91)
- `tests/test_core/test_cache_analysis_summarize.py` (lines 21, 22)
- `tests/test_core/test_cache_analysis_per_id_coverage.py` (lines 207, 208, 219, 220)
- `tests/test_core/test_cache_analysis_per_id_emission.py` (lines 1519, 1539)
- `tests/test_cli/test_analyze_cache.py` (lines 99, 106, 107) + 3 NEW CliRunner tests (one per phase)
- `tests/test_mcp_server/test_analyze_cache_tool.py` (lines 70, 75, 101, 106, 125, 137, 186)

---

## Reference functions/utilities to reuse (existing — do NOT reimplement)

- `walk_cross_workflow` (`core/cache_analysis/cross_workflow.py:141-150`) — sub-workflow IR resolution with depth+cycle handling. Single shared call site in `analyze()` (review-feature-interactions WARN-5 fix).
- `WorkflowValidator._enumerate_child_calls` (`core/workflow/validator.py:807-881`) — heterogeneous batch enumeration (already delegated to by `walk_cross_workflow`)
- `_LLMSummaryAccumulator` (`runtime/workflow_trace.py:43-105`) — priced/unpriced/unavailable_models accumulation; reused inside `_collect_llm_summary` shim
- `make_diagnostic` + `dataclasses.replace` pattern — for any new diagnostic emission with workflow scope; avoids mutating shared context dicts
- Shim pattern (used 4+ times in this branch) — keep ≤5-line delegating functions at old import paths
- `JSON_FORMAT_VERSION_MAJOR` constant (`render_json.py:32`) — bump to "3" in Phase 3 alongside the version literal
- `CrossWorkflowResult.notes` propagation (`cross_workflow.py:141`, `analyze.py:1601`) — reuse for cycle/depth/template-items truncation surfacing
- `cw_result.edges` (`cross_workflow.py:38-63`) — `parent_node_id → child_workflow` mapping; load-bearing for workflow_path correlation in TraceTree.iter_llm_leaves
- `MemoizationCache.get_latest_for_node(node_id, workflow_path=path)` — already supports per-workflow scoping; per-workflow Track B/C view uses this with the resolved child workflow_path

---

## Known limitations to document inline (not blockers)

1. **Template-items batch sub-workflows** (`items: ${list}`, `workflow: ${item.workflow}`): `_enumerate_child_calls` cannot statically enumerate; sub-workflow per-call rows for these don't appear. **`current_cost` is honest because it's trace-driven** (the runtime executed them and the trace records them). Notes entry surfaces the per-call gap with remediation text per A6/Phase 2c spec.
2. **Greenfield rollup with no trace + no `--inputs`**: Tier 4 unavailable for sub-workflow rows; rolled-up `current_cost` is None. Honest signal; renderer's "Greenfield path" branch fires.
3. **2.0.0 trace cached events**: short-circuit at TraceTree.cost_for_event preserved gated on `format_version.startswith("2.0")`. Drop when 2.0.0 support is dropped.
4. **`_consolidate_to_root_advisories` walks parent IR only** today. Sub-workflow consolidation findings won't auto-surface at parent scope. Drill-in section in renderer (per Phase 2c) tells the agent to run analyze-cache per child for sub-workflow recommendations. Future enhancement: extend `_consolidate_to_root_advisories` to iterate `cw_result.irs_by_workflow`.
5. **Phase 2b plan-side workflow_path threading**: requires adding `Plan.workflow_path` field. Verified safe (no existing tests pin field absence; field is additive).

---

## Plan-execution discipline

- **Atomic phases**: each commit ships green tests + green check + green plan_drift + green golden baseline
- **Mutation-test contract documentation**: every new test docstring includes the EXACT production line/branch that, when reverted, causes the test to fail with the EXACT specified failure form. Pattern from `tests/test_core/test_cache_analysis_cost_estimation.py:419-454`.
- **End-to-end fidelity**: at minimum 3 CliRunner integration tests (one per phase 2a/2b/2c) drive `pflow analyze-cache` against committed multi-workflow fixtures. Subprocess CLI tests defended against Pitfall #19 attractor.
- **TraceFixtureBuilder + production-shape snapshot**: load-bearing test (`test_trace_fixture_builder_matches_production_shape`) ensures synthetic fixtures match real `WorkflowTraceCollector` output. Defends Pitfall #19 root cause.
- **Top-10% bar**: TraceTree as a domain type (rustc TyCtxt analog), trace-driven/IR-driven split for cost vs projections (separation-of-concerns), generator+filter over enum policies, function split over 2-branch hybrids
- **Brownfield/greenfield parity**: every test surface includes both modes where applicable; renderer empty-branch handling preserved bit-for-bit per the 4-case dispatch
- **No backwards-compat shims** beyond the ≤5-line delegating ones at old import paths
- **Plan W7 verified**: `Plan.workflow_path` field needs adding (PlanEntry doesn't carry it; canonical workflow_path lives in `shared["_pflow_workflow_file"]` per recursion depth). Phase 2b owns this addition.
