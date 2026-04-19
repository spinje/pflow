# Implementation Plan — Task 156: `--dry-run` flag

## Purpose of this document

This is the **HOW** for task-156. It complements `.taskmaster/tasks/task_156/task-156.md` (which is the WHAT and WHY). Read the task spec first to understand requirements, contracts, and design decisions. This plan gives you the exact files, line numbers, signatures, and ordering to execute without ambiguity.

**Invariant**: you must not deviate from task-156's requirements or design decisions without explicit user approval. If something here conflicts with task-156, task-156 wins.

## Revision history

This plan has been reviewed by 5 parallel review agents (review-plan, review-impact-completeness, review-validation-consistency, review-feature-interactions, review-silent-failures). The findings surfaced 14 structural issues. The plan incorporates all fixes. Load-bearing corrections the implementer should NOT "simplify away":

- **Planner DOES mutate its scratch `shared`** on cache hits (calls `apply_memo_hit`) and before every `plan_node` call (bumps `visit_counts`). Required for byte-identical cache keys at downstream nodes. The contract "pure read" applies to the caller's params/state, not to the scratch dict `build_plan` constructs.
- **`memo_cache_lookup` returns `cache_key` on ALL paths**, including hits. This eliminates cache-key re-derivation in the planner (Option E "one source of truth").
- **Post-first-miss uses BFS over non-error successors**, not linear `default`-following. Produces `cost_basis="upper_bound"` — the safer semantic for agent cost-gating.
- **`_plan_sub_workflow` opaque pre-check runs FIRST** (before `plan_node`). Without this, strict-mode template resolution raises on `workflow: ${var}` and masks the legitimate opaque case.
- **Widened exception catches** in sub-workflow recursion to match `WorkflowExecutor._PREP_RECOVERABLE`.
- **Engine explicitly calls `invalidate_cache` on hash mismatch** post-refactor (pure `in_process_cache_lookup` no longer does it).
- **Sub-workflow entries count as `execute` in summary** when the child has any work — the parent `WorkflowExecutor` frame always runs at runtime (memo-skipped).
- **Nested cost aggregation** (`estimated_cost_usd_including_nested`) — agents must cost-gate against the nested value, not per-level.
- **Phase ordering revised**: planner/formatter/runner (5,6,7) before engine refactor (3). Validates `plan_node` in isolation before the risky integration.

If a future reviewer argues any of the above are "unnecessary complexity," re-read the review findings. Each one prevents a concrete drift class.

## Read-order for an agent starting cold

1. `.taskmaster/tasks/task_156/task-156.md` — requirements, contracts, decisions.
2. This file — phase-by-phase execution.
3. The files referenced in each phase (read, don't guess).

## Line-number caveat

Line numbers in this plan are accurate at the commit the plan was drafted from. If you've already made edits in an earlier phase, line numbers in later phases may have shifted. **Use `Grep` to locate current line numbers if `Edit` tool complains about non-unique matches**. Line numbers here are navigation hints, not constants.

---

## Phases overview

**Ordering rationale**: the engine refactor (Phase 3) is the highest-risk change — it touches the most-tested code path in pflow. By implementing the planner (Phase 5) FIRST, `plan_node()` is validated in isolation via unit + integration tests before the engine starts depending on it. If `plan_node()` has a bug, it surfaces in planner tests (easy to debug) rather than in every execution test (hard to debug cause).

| Phase | Scope | Blocking deps |
|---|---|---|
| 0 | Prerequisites: `LLMNode` cost fix + `MemoizationCache` schema/methods | None |
| 1 | Split cache helpers into pure-lookup + apply pairs (keep thin wrappers) | 0 |
| 2 | Create `plan_node()` primitive | 1 |
| 4 | Add `Plan`, `PlanEntry`, `PlanSummary` to `execution/result.py` | None (parallel to 0–2) |
| 5 | Create `build_plan()` walker in `execution/plan.py` | 2, 4 |
| 6 | Create `plan_formatter.py` (JSON + text) | 4 |
| 7 | Add `WorkflowRunner.plan()` method | 5, 6 |
| 3 | Integrate `plan_node()` into engine's `_execute_node` (DO AFTER 5/6/7 — risky refactor, do when `plan_node` is validated) | 2 |
| 8 | Wire `--dry-run` CLI flag | 3, 5, 6, 7 |
| 9 | MCP server exposure (`plan_workflow` tool) | 3, 5, 6, 7 |
| 10 | Tests (drift-catcher, cost, sub-workflow, CLI, MCP, prereq) | All above |
| 11 | CLAUDE.md updates | All above |

Phases 0 and 4 are independent; execute in parallel if you want. Phases 5, 6, 7 form the planner stack and can be written before touching engine code. Phase 3 is intentionally LAST among the code phases for the risk reason above.

After each phase: `make test` must pass (some phases add tests that will go green as the phase completes; run `make test` after that phase). `make check` (lint+type) must pass after every phase.

---

## Phase 0 — Prerequisites

### 0.1 — `LLMNode.post()` cost enrichment fix

**File**: `src/pflow/nodes/llm/llm.py`

**Current state** (approximately L356–L417 is `LLMNode.post()`):
The method builds an `llm_usage` dict at approximately L392 and assigns it **directly** to `shared["llm_usage"]` without calling `enrich_llm_usage_with_cost`. The dict contains these keys: `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. **No `cost_usd` key**.

**Add import** (near existing `from pflow.core.node import Node`, approximately L17):
```python
from pflow.core.llm_pricing import enrich_llm_usage_with_cost
```

**Refactor the dict write**. Locate the block that currently reads approximately:
```python
shared["llm_usage"] = {
    "model": exec_res.get("model", "unknown"),
    "input_tokens": input_tokens,
    "output_tokens": output_tokens,
    "total_tokens": input_tokens + output_tokens,
    "cache_creation_input_tokens": cache_creation,
    "cache_read_input_tokens": cache_read,
}
```

Replace with:
```python
llm_usage = {
    "model": exec_res.get("model", "unknown"),
    "input_tokens": input_tokens,
    "output_tokens": output_tokens,
    "total_tokens": input_tokens + output_tokens,
    "cache_creation_input_tokens": cache_creation,
    "cache_read_input_tokens": cache_read,
}
enrich_llm_usage_with_cost(llm_usage)  # Mutates in place: adds cost_usd
shared["llm_usage"] = llm_usage
```

Do **not** alter the `else` branch (empty dict when `usage_obj` is falsy) — it has no tokens to price.

**Idempotency guarantee** (for reviewers): `enrich_llm_usage_with_cost` short-circuits on existing `"cost_usd" in llm_usage` (see `src/pflow/core/llm_pricing.py` around L202–203). The engine already calls `enrich_llm_cost` at step 15 via `runtime/engine/instrumentation.py::enrich_llm_cost`, but that fires AFTER `write_memo_cache` at step 12 — which is why the cache doesn't contain `cost_usd` today. Pre-enriching at the node means both live-run consumers and the memo cache see `cost_usd`. The existing post-write enrichment is a no-op then (idempotent short-circuit).

### 0.2 — `MemoizationCache` schema: add `node_id` index

**File**: `src/pflow/runtime/cache.py`

**Current state** (`_init_db` at approximately L145–L169):
```python
conn.executescript("""
    CREATE TABLE IF NOT EXISTS cache_entries (
        cache_key TEXT PRIMARY KEY,
        node_id TEXT NOT NULL,
        workflow_path TEXT,
        action TEXT NOT NULL,
        output BLOB NOT NULL,
        output_hash TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_created_at ON cache_entries(created_at);
    CREATE INDEX IF NOT EXISTS idx_workflow_path ON cache_entries(workflow_path);
""")
```

**Add this index inside the same `executescript` block, after `idx_workflow_path`**:
```python
CREATE INDEX IF NOT EXISTS idx_node_id_created_at ON cache_entries(node_id, created_at DESC);
```

SQLite creates the index on old databases as soon as `_init_db` runs next — no migration needed.

### 0.3 — `MemoizationCache.get_with_age` (new method)

**File**: `src/pflow/runtime/cache.py`

**Add this method as a sibling of `get()` (near L181)**:

```python
def get_with_age(self, cache_key: str) -> Optional[tuple[str, dict[str, Any], float]]:
    """Look up cache entry with its age.

    Like get() but also returns the creation timestamp. Used by the dry-run
    planner to render age on cached entries ("cached 2h ago").

    Args:
        cache_key: The cache key to look up

    Returns:
        Tuple of (action, output, created_at_epoch_seconds) or None if not
        found, expired, or reads disabled. TTL semantics match get().
    """
    if not self.read_enabled:
        return None

    try:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT action, output, created_at FROM cache_entries WHERE cache_key = ?",
                (cache_key,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            action, output_blob, created_at = row

            if time.time() - created_at > self.ttl_seconds:
                conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
                conn.commit()
                return None

            output_json = zlib.decompress(output_blob).decode()
            output = json.loads(output_json)
            return (action, output, created_at)
        finally:
            conn.close()
    except (sqlite3.Error, zlib.error, json.JSONDecodeError, OSError):
        logger.debug("Memoization cache get_with_age failed", exc_info=True)
        return None
```

**Do NOT modify `get()`**. Keep the parallel methods. Task spec pins `get()` signature unchanged.

### 0.4 — `MemoizationCache.get_latest_for_node` (new method)

**File**: `src/pflow/runtime/cache.py`

**Add this method as a sibling of `get_with_age()`**:

```python
def get_latest_for_node(self, node_id: str) -> Optional[tuple[dict[str, Any], float]]:
    """Look up the most recent cache entry for a given node_id.

    Ignores the full cache key — returns the latest entry whose node_id matches,
    regardless of config or inputs. Used for historical cost estimation in
    --dry-run (cost gate).

    Args:
        node_id: Node identifier to search for

    Returns:
        Tuple of (output_dict, created_at_epoch_seconds) or None if not found,
        expired, or reads disabled. TTL semantics match get().
    """
    if not self.read_enabled:
        return None

    try:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT cache_key, output, created_at FROM cache_entries "
                "WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
                (node_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            cache_key, output_blob, created_at = row

            if time.time() - created_at > self.ttl_seconds:
                conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
                conn.commit()
                return None

            output_json = zlib.decompress(output_blob).decode()
            output = json.loads(output_json)
            return (output, created_at)
        finally:
            conn.close()
    except (sqlite3.Error, zlib.error, json.JSONDecodeError, OSError):
        logger.debug("Memoization cache get_latest_for_node failed", exc_info=True)
        return None
```

### Phase 0 verification
- `make check` passes.
- Existing tests in `tests/test_runtime/test_cache.py` and `tests/test_runtime/test_instrumented_wrapper.py` still pass (no changes to `get()` / `put()` signatures).
- Write one unit test now (you'll expand in phase 10): put an entry with `node_id="foo"`, query `get_latest_for_node("foo")`, assert you get `(output, created_at)`. Put another entry with same `node_id` (different `cache_key`), assert `get_latest_for_node` returns the newer one.

---

## Phase 1 — Split cache helpers (keep wrappers)

### 1.1 — `memo_cache_lookup` (new pure-lookup function)

**File**: `src/pflow/runtime/engine/instrumentation.py`

**Reference**: current `check_memo_cache` at approximately L173–L246. The on-hit side-effect block is the last 4 lines (writing `shared[node_id]`, `completed_nodes`, `node_actions`, `node_hashes`).

**Add a new function above `check_memo_cache`**:

```python
def memo_cache_lookup(
    node_id: str,
    node_type_name: str,
    config_hash: str,
    batch_config: Optional[BatchConfig],
    shared: dict,
    visit_counts: dict,
    resolved_params: Optional[dict] = None,
) -> tuple[bool, Optional[str], Optional[tuple[str, dict]]]:
    """Pure read: check memoization cache without mutating shared state.

    Returns:
        (hit, cache_key, cached_data):
        - hit=True, cache_key=str, cached_data=(action, output) on cache hit
            (cache_key is also returned on hit so callers — like the planner's
            age-lookup path — don't have to re-derive it, preserving the
            Option E "one source of truth for cache-key computation" invariant)
        - hit=False, cache_key=str, cached_data=None on cache miss (key for later write)
        - hit=False, cache_key=None, cached_data=None when memoization is skipped

    Skips memoization in the same conditions as check_memo_cache:
    - No __memoization_cache__ in shared
    - visit_counts[node_id] > 1 (revisited node — loop)
    - WorkflowExecutor nodes (sub-workflow files may change)
    - batch node with unresolvable items_template
    """
    memo_cache = shared.get("__memoization_cache__")
    if not memo_cache or visit_counts.get(node_id, 0) > 1:
        return False, None, None

    if node_type_name == "WorkflowExecutor":
        return False, None, None

    from pflow.runtime.cache import compute_node_cache_key

    if batch_config:
        from pflow.runtime.cache import compute_batch_cache_key
        from .batch_executor import resolve_batch_items

        items_template = batch_config.items_template
        if items_template is None:
            return False, None, None

        try:
            resolved_items = resolve_batch_items(items_template, shared)
            if not isinstance(resolved_items, list):
                return False, None, None
        except Exception:
            logger.debug("Failed to resolve batch items for memo cache key", exc_info=True)
            return False, None, None

        semantic_config = {
            "items_template": items_template,
            "item_alias": batch_config.item_alias,
            "error_handling": batch_config.error_handling,
            "max_retries": batch_config.max_retries,
        }
        cache_key = compute_batch_cache_key(config_hash, semantic_config, resolved_items)
    elif resolved_params is not None:
        cache_key = compute_node_cache_key(config_hash, resolved_params)
    else:
        cache_key = compute_node_cache_key(config_hash)

    if not cache_key:
        return False, None, None

    cached = memo_cache.get(cache_key)
    if cached is None:
        return False, cache_key, None

    cached_action, cached_output = cached
    cached_action = cached_action or "default"  # Normalize None from SQLite
    return True, cache_key, (cached_action, cached_output)
```

### 1.2 — `apply_memo_hit` (new side-effect function)

**File**: `src/pflow/runtime/engine/instrumentation.py`

**Add this function just below `memo_cache_lookup`**:

```python
def apply_memo_hit(
    node_id: str,
    shared: dict,
    cached_action: str,
    cached_output: dict,
    config_hash: str,
) -> None:
    """Apply a memoization-cache hit to shared state.

    This is the side-effect half of the old check_memo_cache. Called only
    from the engine's execute path — never from the dry-run planner.

    Mutations (same as pre-refactor check_memo_cache on-hit block):
    - shared[node_id] = cached_output
    - shared["__execution__"]["completed_nodes"].append(node_id)
    - shared["__execution__"]["node_actions"][node_id] = cached_action
    - shared["__execution__"]["node_hashes"][node_id] = config_hash
    """
    shared[node_id] = cached_output
    shared["__execution__"]["completed_nodes"].append(node_id)
    shared["__execution__"]["node_actions"][node_id] = cached_action
    shared["__execution__"]["node_hashes"][node_id] = config_hash
```

### 1.3 — `check_memo_cache` becomes a thin wrapper

**File**: `src/pflow/runtime/engine/instrumentation.py`

**Replace the body of `check_memo_cache` (currently L173–L246) with this thin wrapper**:

```python
def check_memo_cache(
    node_id: str,
    node_type_name: str,
    config_hash: str,
    batch_config: Optional[BatchConfig],
    shared: dict,
    visit_counts: dict,
    resolved_params: Optional[dict] = None,
) -> tuple[bool, Any, Optional[str]]:
    """Backwards-compatible wrapper: lookup + apply hit.

    Returns (hit, cached_action, cache_key_for_write). Preserves the original
    return tuple for existing call sites (engine step 6 + test_memoization_integration).

    Prefer memo_cache_lookup() + apply_memo_hit() for new call sites that need
    pure lookup (e.g., the dry-run planner).
    """
    hit, cache_key, cached_data = memo_cache_lookup(
        node_id, node_type_name, config_hash, batch_config, shared, visit_counts, resolved_params,
    )
    if hit and cached_data is not None:
        cached_action, cached_output = cached_data
        apply_memo_hit(node_id, shared, cached_action, cached_output, config_hash)
        # Legacy contract: pre-refactor check_memo_cache returned None for cache_key on hit
        # (the key was only needed for the miss path's later write). Preserve that shape so
        # existing test assertions keep passing.
        return True, cached_action, None
    return False, None, cache_key
```

The engine's call site at `_execute_node` step 6 still receives `(hit, result, cache_key)` and behaves exactly as before.

### 1.4 — `in_process_cache_lookup` (new pure-lookup function)

**File**: `src/pflow/runtime/engine/instrumentation.py`

**Current state**: `check_cache_validity` at approximately L87–L103. On hit it returns `(True, cached_action)`. On config-hash mismatch it calls `invalidate_cache(node_id, shared)` and returns `(False, None)`.

**Add a new function above `check_cache_validity`**:

```python
def in_process_cache_lookup(node_id: str, config_hash: str, shared: dict) -> tuple[bool, Any]:
    """Pure read: check in-process cache state without mutating.

    Returns:
        (valid, cached_action):
        - valid=True, cached_action=str on cache hit (node completed with matching hash)
        - valid=False, cached_action=None on miss OR hash mismatch

    Does NOT call invalidate_cache on mismatch — caller is responsible.
    """
    if node_id not in shared["__execution__"]["completed_nodes"]:
        return False, None

    cached_hash = shared["__execution__"]["node_hashes"].get(node_id)
    if config_hash == cached_hash:
        cached_action = shared["__execution__"]["node_actions"].get(node_id, "default")
        return True, cached_action
    return False, None  # Mismatch — caller decides whether to invalidate
```

### 1.5 — `check_cache_validity` becomes a thin wrapper

**File**: `src/pflow/runtime/engine/instrumentation.py`

**Replace `check_cache_validity` body with**:

```python
def check_cache_validity(node_id: str, config_hash: str, shared: dict) -> tuple[bool, Any]:
    """Backwards-compatible wrapper: lookup + invalidate-on-mismatch.

    Preserves pre-refactor behavior: on a config-hash mismatch for an already-
    completed node, the stale entry is invalidated (removed from completed_nodes
    / node_actions / node_hashes).

    Prefer in_process_cache_lookup() for new call sites that need pure lookup.
    """
    valid, cached_action = in_process_cache_lookup(node_id, config_hash, shared)
    if valid:
        return True, cached_action

    # Mismatch path: if the node was present but hash differs, invalidate
    if node_id in shared["__execution__"]["completed_nodes"]:
        invalidate_cache(node_id, shared)
    return False, None
```

### Phase 1 verification
- `make check` passes.
- `make test` passes. All 9 tests in `tests/test_runtime/test_checkpoint_tracking.py` using `check_cache_validity` / `cache_result` / `handle_cached_execution` still pass (thin wrappers preserve behavior).
- The 1 test in `tests/test_runtime/test_memoization_integration.py` that asserts on `check_memo_cache` return shape still passes (wrapper returns the same 3-tuple).

---

## Phase 2 — `plan_node()` primitive

### 2.1 — Create new file `src/pflow/runtime/engine/plan_node.py`

```python
"""Shared primitive for `what would happen at this node`.

This function is called by BOTH:
- WorkflowEngine._execute_node — the real execution path
- execution/plan.py::build_plan — the dry-run planner

Contract: cache-key computation, template resolution, and cache lookup
happen here and NOWHERE ELSE. Any change to cache-key semantics must be
made in this function; both call sites inherit automatically.

The function is a pure read over `shared` from the caller's perspective:
it does NOT mutate `shared` on cache hit or miss. The engine separately
calls `apply_memo_hit` to finalize a hit; the planner does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from .instrumentation import (
    compute_config_hash,
    compute_node_config,
    memo_cache_lookup,
    in_process_cache_lookup,
)
from .template_resolution import resolve_templates
from .types import NodeConfig


NodePlanStatus = Literal["cached_memo", "cached_in_process", "miss", "cache_disabled"]


@dataclass(frozen=True)
class NodePlan:
    """Result of evaluating what would happen to a node without running it.

    Fields:
        status: Which cache bucket decided the outcome (or 'miss').
        config_hash: MD5 of node config — used downstream for apply_memo_hit
            and for cache-key mapping.
        cache_key: Memo-cache key. Set when memoization is enabled for this node
            and a batch-items resolution succeeded (if batch). Populated on both
            'miss' (engine uses it for later write) AND 'cached_memo' (planner
            uses it for get_with_age lookup). None only when memo is skipped
            (cache_disabled, WorkflowExecutor, visit_count > 1, or
            unresolvable batch items).
        resolved_params: Template-resolved params dict (None for batch nodes,
            which resolve per-item). Engine uses this for node.params.
        cached_action: Action string from the cache entry (set iff status in
            ('cached_memo', 'cached_in_process')).
        cached_output: Output dict from the memo cache (set iff
            status=='cached_memo'). Not set for in-process hits because their
            outputs are already in shared.
        last_resolutions: Template resolutions emitted during resolve_templates,
            passed through for trace recording.
        template_errors: Permissive-mode template errors (list of dicts with
            'diagnostic' key). Pass-through for engine.
        template_exception: Strict-mode ValueError that aborted template
            resolution, if any. Planner renders it as a template_error plan
            entry; engine re-raises so the existing exception path handles it.
    """

    status: NodePlanStatus
    config_hash: str
    cache_key: Optional[str]
    resolved_params: Optional[dict[str, Any]]
    cached_action: Optional[str]
    cached_output: Optional[dict[str, Any]]
    last_resolutions: dict[str, Any]
    template_errors: list[Any]
    template_exception: Optional[BaseException]


def plan_node(node: Any, config: NodeConfig, shared: dict[str, Any]) -> NodePlan:
    """Decide what would happen to a node: cached (which level, which action)
    or cache miss with computed cache_key.

    Does NOT invoke node._run(), enforce_loop_guard, or any progress/trace
    emitter. Does NOT mutate shared.

    Callers:
    - Engine: follow up with node._run() on miss, or apply_memo_hit + cached path on hit.
    - Planner: record a PlanEntry from the NodePlan fields.
    """
    # Step 4 equivalent: compute config hash
    config_hash = compute_config_hash(
        compute_node_config(
            config.node_type_name,
            config.template_config.static_params if config.template_config else node.params,
            config.template_config.template_params if config.template_config else {},
            config.batch_config,
        )
    )

    # Step 5 equivalent: resolve templates (non-batch only — batch resolves per-item)
    resolved_params: Optional[dict[str, Any]] = None
    last_resolutions: dict[str, Any] = {}
    template_errors: list[Any] = []
    template_exception: Optional[BaseException] = None

    if config.template_config and not config.batch_config:
        try:
            resolved_params, last_resolutions, template_errors = resolve_templates(
                config.template_config, shared, config.node_id
            )
        except ValueError as e:
            template_exception = e
            # Return early with a synthetic 'miss' status — the engine will
            # re-raise this exception through its existing except path. The
            # planner renders it as template_error without re-raising.
            return NodePlan(
                status="miss",
                config_hash=config_hash,
                cache_key=None,
                resolved_params=None,
                cached_action=None,
                cached_output=None,
                last_resolutions=getattr(e, "_pflow_partial_resolutions", None) or {},
                template_errors=[],
                template_exception=e,
            )

    # Step 6 equivalent: memoization cache (respects config.cache_enabled per task spec)
    if not config.cache_enabled:
        return NodePlan(
            status="cache_disabled",
            config_hash=config_hash,
            cache_key=None,
            resolved_params=resolved_params,
            cached_action=None,
            cached_output=None,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
            template_exception=None,
        )

    # Planner uses an empty visit_counts sentinel (it walks each edge once);
    # engine passes its real visit_counts. Caller-provided when needed.
    visit_counts = shared.get("__execution__", {}).get("node_visit_counts", {})

    hit, cache_key, cached_data = memo_cache_lookup(
        config.node_id,
        config.node_type_name,
        config_hash,
        config.batch_config,
        shared,
        visit_counts,
        resolved_params=resolved_params,
    )
    if hit and cached_data is not None:
        cached_action, cached_output = cached_data
        return NodePlan(
            status="cached_memo",
            config_hash=config_hash,
            cache_key=cache_key,  # Pass through so planner can get_with_age without re-derivation
            resolved_params=resolved_params,
            cached_action=cached_action,
            cached_output=cached_output,
            last_resolutions=last_resolutions,
            template_errors=template_errors,
            template_exception=None,
        )

    # Step 7 equivalent: in-process cache (no side effects from lookup)
    valid, cached_action = in_process_cache_lookup(config.node_id, config_hash, shared)
    if valid:
        return NodePlan(
            status="cached_in_process",
            config_hash=config_hash,
            cache_key=None,
            resolved_params=resolved_params,
            cached_action=cached_action,
            cached_output=None,  # Already in shared[node_id]
            last_resolutions=last_resolutions,
            template_errors=template_errors,
            template_exception=None,
        )

    return NodePlan(
        status="miss",
        config_hash=config_hash,
        cache_key=cache_key,
        resolved_params=resolved_params,
        cached_action=None,
        cached_output=None,
        last_resolutions=last_resolutions,
        template_errors=template_errors,
        template_exception=None,
    )
```

### 2.2 — Re-export in `runtime/engine/__init__.py`

**File**: `src/pflow/runtime/engine/__init__.py`

Add:
```python
from .plan_node import NodePlan, plan_node
```

And add `NodePlan`, `plan_node` to the `__all__` list if one exists.

### Phase 2 verification
- `make check` passes.
- Write a small unit test in `tests/test_runtime/test_plan_node.py` asserting: (a) cache miss returns status="miss" + cache_key set, (b) in-process cache hit returns status="cached_in_process", (c) `cache_enabled=False` returns status="cache_disabled", (d) config.template_config=None works (node.params fallback).

---

## Phase 3 — Integrate `plan_node()` into engine

### 3.1 — Modify `WorkflowEngine._execute_node`

**File**: `src/pflow/runtime/engine/engine.py`

**Current state**: `_execute_node` at approximately L181–L427. Steps 4–7 are at roughly L195–L259 (config hash computation, template resolution, memo cache check with early return, in-process cache check with early return).

**Goal**: replace steps 4–7 with a single `plan_node()` call + dispatch on `plan.status`. Keep all other steps (LLM interception, execution state init, loop guard, callback, execute, metrics, trace, step 17.5) unchanged.

**Shape of the new section** (pseudocode — adapt to the exact variable names in context):

```python
# Step 1-3: unchanged (LLM interception, init execution state, loop guard)
setup_llm_interception(...)
initialize_execution_state(shared)
visit_counts = enforce_loop_guard(config.node_id, shared)

# Steps 4-7 replaced by plan_node()
batch_trace_items: Optional[list] = None
child_trace_events: Optional[list] = None

try:
    plan = plan_node(node, config, shared)

    # Template errors during resolution: re-raise to let existing except path handle it
    if plan.template_exception is not None:
        raise plan.template_exception

    # Cache hit (either level) — short-circuit
    if plan.status in ("cached_memo", "cached_in_process"):
        if plan.status == "cached_memo" and plan.cached_output is not None:
            # Equivalent to the old check_memo_cache's on-hit side effects
            apply_memo_hit(
                config.node_id,
                shared,
                plan.cached_action,
                plan.cached_output,
                plan.config_hash,
            )
        return str(
            handle_cached_execution(
                config.node_id,
                shared,
                plan.cached_action,
                shared_keys_before,
                config.node_type_name,
                node.params,
                self.trace,
            )
        )

    # From here: miss (or cache_disabled). Store template info for later steps.
    last_resolutions = plan.last_resolutions
    template_errors = plan.template_errors
    resolved_params = plan.resolved_params
    cache_key = plan.cache_key  # None if cache_disabled or WorkflowExecutor

    # Preserve pre-refactor invalidate-on-hash-mismatch semantics. The refactor's
    # pure `in_process_cache_lookup` no longer invalidates stale entries on hash
    # mismatch (the old `check_cache_validity` did). Without this, a node whose
    # config changed mid-run would leak a stale `completed_nodes` entry, and on
    # error paths where `cache_result` is a no-op, `node_hashes[id]` stays wrong.
    # The engine owns this invariant; the planner doesn't (planner never revisits
    # stale state in a fresh scratch shared).
    if config.node_id in shared["__execution__"]["completed_nodes"]:
        cached_hash = shared["__execution__"]["node_hashes"].get(config.node_id)
        if cached_hash != plan.config_hash:
            invalidate_cache(config.node_id, shared)

    # Step 8: Progress callback
    call_start_callback(config.node_id, shared)

    # Step 9: Execute — unchanged
    if config.batch_config:
        action, batch_trace_items = execute_batch(node, config, shared, self._execute_single_node)
    else:
        if resolved_params is not None:
            node.params = resolved_params
            if template_errors:
                shared.setdefault("__template_errors__", {})[config.node_id] = template_errors[-1]
        store = NamespacedSharedStore(shared, config.node_id) if config.namespaced else shared
        action = node._run(store)
        if config.node_type_name == "WorkflowExecutor":
            child_trace_events = getattr(node, "_child_trace_events", None)

    # Step 10-17.5: unchanged
    # ... (detect_api_warning, cache_result, write_memo_cache, duration, metrics,
    #      enrich_llm_cost, record_trace, call_completion_callback, step 17.5 mark_failed)
```

**Import additions at the top of engine.py**:
```python
from .plan_node import plan_node
from .instrumentation import apply_memo_hit, invalidate_cache
```

(`apply_memo_hit` and `invalidate_cache` are in the same `.instrumentation` module you refactored in phase 1. `invalidate_cache` was already there; `apply_memo_hit` is new.)

**Critical**: the `write_memo_cache` call at step 12 uses `cache_key` (from the old step 6 return). Preserve this: `cache_key` comes from `plan.cache_key` now. When `cache_enabled` is False, `cache_key` is `None` and `write_memo_cache` already guards against `None`.

**DO NOT remove** the existing `enforce_loop_guard` call — `plan_node` explicitly does not call it. The engine still needs it for loop-max enforcement.

**DO NOT remove** the existing thin-wrappers `check_memo_cache` / `check_cache_validity` — they remain for any external test callers. The engine itself no longer calls them after this phase.

### Phase 3 verification
- `make check` passes.
- `make test` passes — **the entire existing suite**, especially:
  - `tests/test_runtime/test_cache_integration.py` (13 tests)
  - `tests/test_runtime/test_memoization_integration.py` (10 tests)
  - `tests/test_runtime/test_checkpoint_tracking.py` (9 tests)
  - `tests/test_runtime/test_instrumented_wrapper*.py`
  - `tests/test_integration/*.py` (end-to-end)
- If any test fails, the refactor has changed behavior. Diagnose before proceeding.

---

## Phase 4 — Add `Plan` types to `execution/result.py`

### 4.1 — Modify `src/pflow/execution/result.py`

**Current state** (78 lines total): has `RunnerConfig` (frozen), `ResolvedWorkflow` (frozen), `ValidationResult` (not frozen), `ExecutionResult` (not frozen). Uses `Optional[X]` style (not `X | None`).

**Add `from __future__ import annotations` at the top of the file** (right after the module docstring) — required for the `PlanEntry.sub_plan: Optional["Plan"]` forward reference.

**Add these three dataclasses AFTER `ExecutionResult`**. Style matches the existing conventions: `Optional[X]` not `X | None`, `field(default_factory=...)` for mutable defaults, frozen because these are post-compilation artifacts.

```python
@dataclass(frozen=True)
class PlanEntry:
    """One node in an execution plan (--dry-run output).

    Represents what would happen to a single node at runtime, without any
    side effects. For sub-workflow nodes, `sub_plan` contains the recursive
    plan of the child.
    """

    node_id: str
    node_type: str  # IR `type:` value (e.g., "llm", "shell", "read-file")
    status: Literal["cached", "execute", "sub_workflow", "opaque", "routing_error"]
    cause: Literal[
        "hash_match",       # cached — cache key matched
        "no_cache_match",   # execute — no cache entry for current config+inputs
        "downstream",       # execute — reachable from first cache miss
        "cache_disabled",   # execute — node has cache: false
        "template_error",   # execute — template resolution failed at plan time
        "dynamic",          # opaque — sub-workflow ref is a template we can't resolve
        "routing_error",    # routing_error — action has no matching successor
    ]
    action: Optional[str] = None                    # Cached action, if status == "cached"
    age_sec: Optional[float] = None                 # Cached entries only
    last_cost_usd: Optional[float] = None           # Would-execute LLM nodes only
    last_run_age_sec: Optional[float] = None        # Would-execute LLM nodes with cost history
    sub_plan: Optional["Plan"] = None               # WorkflowExecutor entries only
    diagnostic: Optional[Diagnostic] = None         # template_error / routing_error / opaque detail


@dataclass(frozen=True)
class PlanSummary:
    """Aggregate counts for a single plan level.

    `*_including_nested` fields are populated only when sub-workflow recursion
    produced child plans. They sum across the full tree.

    Semantics notes:
    - `execute_count` counts entries where status is "execute", "opaque",
      OR "sub_workflow" with any downstream work (sub_plan.summary.execute_count > 0,
      including nested sub-workflows). The parent WorkflowExecutor frame itself
      always executes at runtime (it's memo-skipped) — so any sub_workflow entry
      adds at least 1 to the execute count.
    - `estimated_cost_usd` is the sum of `last_cost_usd` at THIS level only.
    - `estimated_cost_usd_including_nested` sums across the entire tree —
      this is the value agents should cost-gate on.
    - `cost_basis` documents the enumeration semantics. "upper_bound" means
      post-first-miss BFS enumerated all reachable non-error branches, so
      cost is a worst-case upper bound (runtime only takes one branch).
    """

    total: int
    cached_count: int
    execute_count: int
    cache_boundary: Optional[str]       # node_id of first would-execute node; None if everything cached
    execute_by_type: dict[str, int]     # {node_type: count} over would-execute entries only (uses IR type names)
    estimated_cost_usd: float           # Sum of last_cost_usd at this level (None → 0)
    nodes_without_history: int          # Would-execute LLM nodes with no cost history (this level)
    cost_basis: Literal["upper_bound", "exact"] = "upper_bound"  # "exact" only when no branching occurred post-miss
    total_including_nested: Optional[int] = None
    cached_including_nested: Optional[int] = None
    execute_including_nested: Optional[int] = None
    estimated_cost_usd_including_nested: Optional[float] = None
    nodes_without_history_including_nested: Optional[int] = None


@dataclass(frozen=True)
class Plan:
    """Execution plan for a workflow — the result of --dry-run.

    `entries` is the flat list at THIS level (sub-workflow entries' sub_plan
    holds the nested level). `summary` includes both per-level and
    aggregate-across-nested counts.
    """

    workflow: str                       # Workflow name or file path
    entries: list[PlanEntry]
    summary: PlanSummary
    diagnostics: list[Diagnostic] = field(default_factory=list)
```

**Update imports at the top of the file**:
```python
from typing import Any, Literal, Optional
```
(Adds `Literal` to the existing `from typing import Any, Optional` line.)

### Phase 4 verification
- `make check` passes.
- `from pflow.execution.result import Plan, PlanEntry, PlanSummary` works in a Python REPL.

---

## Phase 5 — `build_plan()` walker in `execution/plan.py`

### 5.1 — Create `src/pflow/execution/plan.py`

**Overall structure**: one public function `build_plan()`, private helpers for per-node planning, sub-workflow recursion, downstream labeling, and cost enrichment.

```python
"""Execution planner for --dry-run.

Walks a compiled workflow's graph without invoking any node's _run() method.
For each node: resolves templates, computes cache key, checks memo cache.
After the first cache miss, every downstream node is labeled as 'would
execute' via topology alone — no stub outputs, no fake results.

Sub-workflow nodes (WorkflowExecutor) trigger recursive planning into the
child workflow. Sub-workflow refs that resolve to a template (${var}) are
marked opaque.

This module is display-agnostic: it produces Plan data, never formats.
Formatting lives in execution/formatters/plan_formatter.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic
from pflow.core.exceptions import CompilationError
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from pflow.execution.result import Plan, PlanEntry, PlanSummary
from pflow.registry import Registry
from pflow.runtime.cache import MemoizationCache
from pflow.runtime.engine.plan_node import plan_node
from pflow.runtime.engine.types import CompiledWorkflow, NodeConfig

logger = logging.getLogger(__name__)

# Class names that are considered LLM-family for cost lookup
_LLM_NODE_CLASSES: frozenset[str] = frozenset({"LLMNode", "ClaudeCodeNode"})

# Default max recursion depth — matches WorkflowExecutor.MAX_DEPTH_DEFAULT
_MAX_SUB_WORKFLOW_DEPTH: int = 10


def build_plan(
    compiled: CompiledWorkflow,
    params: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    workflow_name: str = "<unnamed>",
    only_node: Optional[str] = None,
    _visited_paths: Optional[list[str]] = None,
    _depth: int = 0,
    _parent_workflow_file: Optional[str] = None,
) -> Plan:
    """Build an execution plan for a compiled workflow.

    Args:
        compiled: Result of compile_workflow().
        params: User-provided parameters (will be shallow-copied).
        cache: Single MemoizationCache instance — shared across all recursion levels.
        registry: Single Registry instance — shared across all recursion levels.
        workflow_name: Name shown in the Plan. File path or saved name.
        only_node: If set, walker plans up to and including this node_id then
            terminates. Raises CompilationError at the top-level if target doesn't
            exist (mirrors WorkflowEngine behavior).

    Private kwargs (used only in recursion):
        _visited_paths: Resolved child paths already on the recursion stack.
        _depth: Current recursion depth. Planner aborts at _MAX_SUB_WORKFLOW_DEPTH.
        _parent_workflow_file: Parent's workflow file path, for resolving
            relative sub-workflow refs.

    Returns:
        Plan with per-level summary and nested sub_plan entries.

    Correctness contract (mirrors engine behavior byte-identically):
    - On cache hit: the planner writes `shared[node_id] = cached_output` and
      updates `__execution__["completed_nodes"]`/`node_actions`/`node_hashes`
      in its scratch shared dict (equivalent to `apply_memo_hit`). This is
      what makes byte-identical cache keys for downstream nodes possible —
      without it, subsequent nodes' template resolution sees empty shared
      state and computes different keys than the engine would.
    - Before each `plan_node` call: the walker increments
      `__execution__["node_visit_counts"][node_id]` (mirrors engine's
      `enforce_loop_guard` visit-count bump). This is required so loop
      iteration 2+ correctly skips memo lookup (matches engine's skip).
    - After first cache miss: BFS over all non-"error" outgoing edges to
      enumerate reachable would-execute nodes. Produces a strict upper
      bound on cost (summary.cost_basis = "upper_bound"). Runtime takes
      one path; planner enumerates all possible paths.

    The scratch `shared` dict is NOT the caller's — it is constructed inside
    this function. Mutating it is safe and REQUIRED for correctness. Only
    the caller-owned `params` dict is treated as read-only.
    """
    # Validate --only target exists (mirror engine behavior at top-level only)
    # Only validate on first entry (not recursion), keyed by `_depth == 0`.
    if only_node is not None and _depth == 0:
        if only_node not in compiled.node_configs:
            from pflow.core.exceptions import CompilationError
            available = sorted(compiled.node_configs.keys())
            raise CompilationError(
                f"Node '{only_node}' not found",
                phase="only_node_resolution",
                details={"available_nodes": available},
                suggestion=f"Available nodes: {', '.join(available)}",
            )
    visited_paths = list(_visited_paths) if _visited_paths else []

    # Scratch shared store — never passed back to the caller
    shared: dict[str, Any] = {**params}
    shared.update(compiled.resolved_defaults)
    shared["__memoization_cache__"] = cache
    shared["__execution__"] = {
        "completed_nodes": [],
        "node_actions": {},
        "node_hashes": {},
        "failed_node": None,
        "node_visit_counts": {},
    }
    shared["__cache_hits__"] = []
    if _parent_workflow_file:
        shared["_pflow_workflow_file"] = _parent_workflow_file

    entries: list[PlanEntry] = []
    diagnostics: list[Diagnostic] = []
    visited_edges: set[tuple[str, str]] = set()
    first_miss_node_id: Optional[str] = None
    cost_basis: str = "exact"  # Flips to "upper_bound" if BFS enumerates branches

    # Walk the compiled graph — same pattern as WorkflowEngine.run()
    curr = compiled.start_node
    while curr is not None:
        node_id = getattr(curr, "node_id", None)
        if node_id is None or node_id not in compiled.node_configs:
            logger.debug("Skipping node with missing node_id or config in plan walk")
            break

        config = compiled.node_configs[node_id]

        # Bump visit_counts BEFORE plan_node — mirrors engine's enforce_loop_guard.
        # Required so loop iteration 2+ correctly skips memo lookup (matches engine).
        visit_counts = shared["__execution__"]["node_visit_counts"]
        visit_counts[node_id] = visit_counts.get(node_id, 0) + 1

        # Plan this node: may recurse into sub-workflow
        entry = _plan_one_node(
            curr,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=_depth,
            parent_workflow_file=_parent_workflow_file,
        )

        # Collect child diagnostics (from sub-workflow recursion)
        if entry.sub_plan is not None:
            diagnostics.extend(entry.sub_plan.diagnostics)

        # If entry is a template_error/sub-workflow diagnostic, record it
        if entry.diagnostic is not None:
            diagnostics.append(entry.diagnostic)

        entries.append(entry)

        # Determine next action and whether this entry establishes the boundary.
        # Sub-workflow frame: the parent WorkflowExecutor ALWAYS executes at runtime
        # (it's memo-skipped), so any sub_workflow whose inner plan has work
        # (or is opaque/has a compile failure) establishes the boundary.
        if entry.status == "cached":
            action = entry.action or "default"
            # Populate shared state to mirror engine's apply_memo_hit side effects.
            # Without this, downstream template resolution sees an empty shared
            # and diverges from what the engine would compute.
            if entry.sub_plan is None:  # Non-sub-workflow cached; see _plan_standard_node for the shared write
                pass  # shared was already populated by _plan_standard_node
        elif entry.status == "sub_workflow" and entry.sub_plan is not None:
            # Any child execution (including nested) => parent is a boundary.
            child_summary = entry.sub_plan.summary
            child_has_work = (
                child_summary.execute_count > 0
                or (child_summary.execute_including_nested or 0) > 0
            )
            if child_has_work:
                first_miss_node_id = node_id
            action = "default"
        elif entry.status == "opaque":
            first_miss_node_id = node_id
            action = "default"
        elif entry.status == "routing_error":
            # A routing error was detected proactively — terminate cleanly after recording.
            break
        else:  # "execute"
            first_miss_node_id = node_id
            action = "default"

        # End-action termination (mirror engine._handle_no_successor)
        if action == "end":
            break
        # All-error-only successors = clean termination (no forward path)
        if curr.successors and all(k == "error" for k in curr.successors):
            break

        # Before advancing, check for routing error: cached node with a named
        # action but no matching successor (edit removed the edge).
        if entry.status == "cached" and action != "default" and action not in curr.successors:
            # Emit a routing_error entry and terminate (mirrors _handle_no_successor
            # non-error routing failure path).
            routing_diag = Diagnostic(
                severity="warning",
                message=(
                    f"Node '{node_id}' cached action '{action}' has no matching successor. "
                    f"Available: {list(curr.successors)}. At runtime the engine would fail "
                    f"with a routing error — fix the workflow edges."
                ),
                node_id=node_id,
                source="planner",
                context={"category": "routing_error"},
            )
            entries.append(PlanEntry(
                node_id=node_id,
                node_type=_node_type_name(config),
                status="routing_error",
                cause="routing_error",
                diagnostic=routing_diag,
            ))
            diagnostics.append(routing_diag)
            break

        # If --only target is this boundary node, stop here — don't BFS
        # downstream (the user asked to plan up to and including this node).
        if only_node is not None and first_miss_node_id == only_node:
            break

        # If we just crossed the cache boundary, BFS the rest of the reachable
        # subgraph (over non-"error" edges) to enumerate would-execute nodes.
        # Must enqueue ALL of the boundary node's non-error successors — not
        # just default — so branches post-boundary are covered.
        if first_miss_node_id is not None:
            bfs_entries, bfs_flipped_basis = _bfs_downstream(
                boundary_node=curr,
                compiled=compiled,
                visited_nodes={e.node_id for e in entries if e.sub_plan is None},
                visited_edges=visited_edges,
                only_node=only_node,
            )
            entries.extend(bfs_entries)
            if bfs_flipped_basis:
                cost_basis = "upper_bound"
            break  # BFS consumed the rest

        # Normal forward edge follow (pre-boundary)
        edge = (node_id, action)
        if edge in visited_edges:
            break
        visited_edges.add(edge)
        curr = curr.successors.get(action)

        # --only termination: stop after including the target node
        if only_node is not None and node_id == only_node:
            break

    summary = _summarize(entries, diagnostics, cost_basis=cost_basis)
    return Plan(
        workflow=workflow_name,
        entries=entries,
        summary=summary,
        diagnostics=diagnostics,
    )


def _bfs_downstream(
    *,
    boundary_node: Any,
    compiled: CompiledWorkflow,
    visited_nodes: set[str],
    visited_edges: set[tuple[str, str]],
    only_node: Optional[str],
) -> tuple[list[PlanEntry], bool]:
    """BFS over non-error successors starting from the boundary node.

    The boundary node itself is NOT re-added to entries (it's already in
    the main walker's entries). Instead, we enumerate its non-error
    successors and BFS from there.

    Returns (entries, flipped_basis). `flipped_basis` is True iff BFS encountered
    any branching (more than one non-error successor at some node) — in that
    case the summary's cost_basis flips to "upper_bound" (cost is worst-case).

    Terminates early when `only_node` is reached (if set).
    """
    from collections import deque

    entries: list[PlanEntry] = []
    flipped_basis = False
    queue: deque[Any] = deque()

    # Seed the queue with all of the boundary node's non-error successors.
    # Branching at the boundary counts toward flipped_basis.
    boundary_non_error = [
        (action, succ) for action, succ in boundary_node.successors.items()
        if action != "error"
    ]
    if len(boundary_non_error) > 1:
        flipped_basis = True

    boundary_id = getattr(boundary_node, "node_id", None)
    for action, succ in boundary_non_error:
        if boundary_id is not None:
            edge = (boundary_id, action)
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
        queue.append(succ)

    # Standard BFS from seeded successors
    while queue:
        node = queue.popleft()
        node_id = getattr(node, "node_id", None)
        if node_id is None or node_id in visited_nodes:
            continue
        visited_nodes.add(node_id)

        if node_id not in compiled.node_configs:
            continue
        config = compiled.node_configs[node_id]

        entries.append(PlanEntry(
            node_id=node_id,
            node_type=_node_type_name(config),
            status="execute",
            cause="downstream",
        ))

        if only_node is not None and node_id == only_node:
            break  # Respect --only: stop after planning the target

        # Enqueue this node's non-error successors
        non_error_successors = [
            (action, succ) for action, succ in node.successors.items()
            if action != "error"
        ]
        if len(non_error_successors) > 1:
            flipped_basis = True

        for action, succ in non_error_successors:
            edge = (node_id, action)
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
            queue.append(succ)

    return entries, flipped_basis


def _node_type_name(config: NodeConfig) -> str:
    """Get the user-facing IR node type (e.g., 'llm', 'shell').

    Falls back to the class name if the IR type isn't available.
    """
    # NodeConfig stores the class name (e.g., 'LLMNode'). We want the IR
    # name (e.g., 'llm') for agent-friendly display. Map via registry
    # or fallback to class name-derived kebab-case.
    # NOTE: For simplicity in v1, return the class name. Formatter translates.
    return config.node_type_name


def _plan_one_node(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    visited_paths: list[str],
    depth: int,
    parent_workflow_file: Optional[str],
) -> PlanEntry:
    """Plan a single node. Dispatches to sub-workflow or standard handling."""
    if config.node_type_name == "WorkflowExecutor":
        return _plan_sub_workflow(
            curr,
            config,
            shared,
            cache,
            registry,
            visited_paths=visited_paths,
            depth=depth,
            parent_workflow_file=parent_workflow_file,
        )

    return _plan_standard_node(curr, config, shared, cache)


def _plan_standard_node(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
) -> PlanEntry:
    """Plan a non-WorkflowExecutor node.

    LOAD-BEARING: on cache hit, mutates `shared` to mirror the engine's
    apply_memo_hit side effects. Without this, downstream template resolution
    diverges from engine behavior. The scratch `shared` belongs to `build_plan`,
    not the caller, so mutation is safe here.
    """
    plan = plan_node(curr, config, shared)

    if plan.template_exception is not None:
        # Strict-mode template failure. Build a Diagnostic from any attached
        # structured data, otherwise fall back to the exception message.
        attached_diag = getattr(plan.template_exception, "_pflow_template_diagnostic", None)
        if not isinstance(attached_diag, Diagnostic):
            attached_diag = Diagnostic(
                severity="warning",  # Plan diagnostics are informational at plan time
                message=str(plan.template_exception),
                node_id=config.node_id,
                source="planner",
                context={"category": "template_error"},
            )
        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="execute",
            cause="template_error",
            diagnostic=attached_diag,
        )

    if plan.status == "cache_disabled":
        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="execute",
            cause="cache_disabled",
        )

    if plan.status == "cached_memo":
        # MIRROR engine's apply_memo_hit side effects on scratch shared so
        # downstream template resolution sees the cached output. Required for
        # byte-identical cache-key computation at downstream nodes.
        if plan.cached_output is not None and plan.cached_action is not None:
            from pflow.runtime.engine.instrumentation import apply_memo_hit
            apply_memo_hit(
                config.node_id,
                shared,
                plan.cached_action,
                plan.cached_output,
                plan.config_hash,
            )

        # Use plan.cache_key directly (returned by memo_cache_lookup on hit).
        # No re-derivation needed — Option E "single source of truth" preserved.
        age_sec: Optional[float] = None
        if plan.cache_key is not None:
            with_age = cache.get_with_age(plan.cache_key)
            if with_age is not None:
                import time as _time
                age_sec = _time.time() - with_age[2]

        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="cached",
            cause="hash_match",
            action=plan.cached_action or "default",
            age_sec=age_sec,
        )

    if plan.status == "cached_in_process":
        # In-process hits only occur when an earlier pass in THIS plan walk
        # populated `completed_nodes`/`node_hashes` (via apply_memo_hit above).
        # shared[node_id] is already populated — no additional mutation needed.
        return PlanEntry(
            node_id=config.node_id,
            node_type=_node_type_name(config),
            status="cached",
            cause="hash_match",
            action=plan.cached_action or "default",
            age_sec=None,  # In-process hits have no meaningful age
        )

    # Cache miss — would execute. Attach cost estimate if LLM-family.
    last_cost, last_age = _lookup_last_cost(config, cache)

    # Surface permissive-mode template errors (if any). Strict mode goes through
    # template_exception above; permissive mode leaves unresolved templates as
    # strings and accumulates errors here. Without surfacing, these are silently
    # dropped and the miss looks like a regular "no_cache_match" when really
    # the user should know a template couldn't resolve.
    permissive_diag: Optional[Diagnostic] = None
    if plan.template_errors:
        last_err = plan.template_errors[-1]
        attached = last_err.get("diagnostic") if isinstance(last_err, dict) else None
        if isinstance(attached, Diagnostic):
            permissive_diag = attached

    return PlanEntry(
        node_id=config.node_id,
        node_type=_node_type_name(config),
        status="execute",
        cause="template_error" if permissive_diag is not None else "no_cache_match",
        last_cost_usd=last_cost,
        last_run_age_sec=last_age,
        diagnostic=permissive_diag,
    )


def _plan_sub_workflow(
    curr: Any,
    config: NodeConfig,
    shared: dict[str, Any],
    cache: MemoizationCache,
    registry: Registry,
    *,
    visited_paths: list[str],
    depth: int,
    parent_workflow_file: Optional[str],
) -> PlanEntry:
    """Compile and recursively plan a sub-workflow.

    Order of checks matters:
    1. Depth guard (before any work).
    2. OPAQUE PRE-CHECK: if the `workflow:` param is itself a template
       (`workflow: ${var}`), emit `status="opaque"` BEFORE calling `plan_node`.
       Otherwise strict-mode template resolution would raise and we'd emit
       `template_error` — masking the legitimate opaque case the spec requires.
    3. Resolve parent's `inputs:` templates via plan_node.
    4. Resolve + compile child, recurse.
    """
    node_id = config.node_id
    node_type = _node_type_name(config)

    # 1. Depth guard
    if depth >= _MAX_SUB_WORKFLOW_DEPTH:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity="warning",
                message=f"Max sub-workflow depth {_MAX_SUB_WORKFLOW_DEPTH} exceeded at '{node_id}'",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )

    # 2. OPAQUE PRE-CHECK — task spec mandates that `workflow: ${var}` renders
    # as opaque, not template_error. Strict mode would raise on ${var},
    # producing template_error; permissive mode leaves it as a string and
    # resolve_sub_workflow returns None. We pre-check so both modes converge.
    workflow_ref = None
    if config.template_config:
        # Check template_params first (unresolved) then static_params
        workflow_ref = config.template_config.template_params.get("workflow")
        if workflow_ref is None:
            workflow_ref = config.template_config.static_params.get("workflow")
    if workflow_ref is None:
        # Node without template_config uses raw params
        workflow_ref = curr.params.get("workflow") if hasattr(curr, "params") else None

    if isinstance(workflow_ref, str) and "${" in workflow_ref:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="opaque",
            cause="dynamic",
        )

    # 3. Resolve parent's params (`inputs:` may contain templates)
    plan = plan_node(curr, config, shared)
    if plan.template_exception is not None:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity="warning",
                message=str(plan.template_exception),
                node_id=node_id,
                source="planner",
                context={"category": "template_error"},
            ),
        )

    # Merge static + resolved params (mirrors engine's resolve_templates output)
    merged: dict[str, Any] = {}
    if config.template_config:
        merged.update(config.template_config.static_params or {})
    if plan.resolved_params:
        merged.update(plan.resolved_params)

    # 4. Resolve sub-workflow ref
    base_path = Path(parent_workflow_file).parent if parent_workflow_file else None
    try:
        resolved = resolve_sub_workflow(merged, base_path=base_path)
    except _SUB_WORKFLOW_RESOLVE_EXCEPTIONS as e:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity="warning",
                message=f"Sub-workflow resolve failed: {e}",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )

    # Missing/absent → opaque (template case already handled by pre-check above)
    if resolved is None:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="opaque",
            cause="dynamic",
        )

    # Cycle detection — normalize path via .resolve() for consistency
    resolved_path_str = str(resolved.path.resolve()) if resolved.path else None
    if resolved_path_str and resolved_path_str in visited_paths:
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity="warning",
                message=f"Circular sub-workflow reference: {resolved_path_str}",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )

    # Extract child inputs
    raw_inputs = merged.get("inputs")
    if raw_inputs is not None and not isinstance(raw_inputs, dict):
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=Diagnostic(
                severity="warning",
                message=f"Workflow node 'inputs:' resolved to {type(raw_inputs).__name__}, expected dict",
                node_id=node_id,
                source="planner",
                context={"category": "sub_workflow"},
            ),
        )
    child_inputs: dict[str, Any] = dict(raw_inputs) if raw_inputs else {}

    # Compile child
    child_initial_params = dict(child_inputs)
    if resolved.path:
        child_initial_params["_pflow_workflow_file"] = resolved_path_str

    try:
        from pflow.runtime.compilation.compiler import compile_workflow

        compiled_child = compile_workflow(
            resolved.ir, registry=registry, initial_params=child_initial_params,
        )
    except _CHILD_COMPILE_EXCEPTIONS as e:
        child_diags = _safe_to_diagnostics(e)
        primary = child_diags[0] if child_diags else Diagnostic(
            severity="error",
            message=f"Sub-workflow compile failed: {e}",
            node_id=node_id,
            source="planner",
            context={"category": "compilation"},
        )
        return PlanEntry(
            node_id=node_id,
            node_type=node_type,
            status="execute",
            cause="template_error",
            diagnostic=primary,
        )

    # Recurse
    workflow_ref_for_name = merged.get("workflow") or "<sub-workflow>"
    child_plan = build_plan(
        compiled_child,
        child_inputs,
        cache,
        registry,
        workflow_name=str(workflow_ref_for_name),
        _visited_paths=[*visited_paths, resolved_path_str] if resolved_path_str else visited_paths,
        _depth=depth + 1,
        _parent_workflow_file=resolved_path_str,
    )

    # Attach parser warnings from the child's resolution
    if resolved.warnings:
        child_plan = Plan(
            workflow=child_plan.workflow,
            entries=child_plan.entries,
            summary=child_plan.summary,
            diagnostics=[*child_plan.diagnostics, *resolved.warnings],
        )

    return PlanEntry(
        node_id=node_id,
        node_type=node_type,
        status="sub_workflow",
        cause="no_cache_match",  # Parent WorkflowExecutor frame always executes (memo-skipped)
        sub_plan=child_plan,
    )


# Exception tuples — widened per review findings to match WorkflowExecutor's
# `_PREP_RECOVERABLE` runtime behavior. Changes to these sets must be mirrored
# in runtime/workflow_executor.py to keep plan-time and runtime behavior aligned.
def _build_sub_workflow_exception_tuples() -> tuple[tuple, tuple]:
    """Build the two exception tuples used by _plan_sub_workflow.

    Lazy imports to avoid circular deps; called once at module import.
    """
    from pflow.core.exceptions import (
        CompilationError as _CompilationError,
        MarkdownParseError as _MarkdownParseError,
        SchemaValidationError as _SchemaValidationError,
        WorkflowNotFoundError as _WorkflowNotFoundError,
        WorkflowValidationError as _WorkflowValidationError,
    )
    resolve_excs = (FileNotFoundError, ValueError, _MarkdownParseError, _WorkflowNotFoundError)
    compile_excs = (
        _CompilationError,
        _WorkflowValidationError,
        _MarkdownParseError,
        _SchemaValidationError,
    )
    return resolve_excs, compile_excs


_SUB_WORKFLOW_RESOLVE_EXCEPTIONS, _CHILD_COMPILE_EXCEPTIONS = _build_sub_workflow_exception_tuples()


def _safe_to_diagnostics(exc: BaseException) -> list[Diagnostic]:
    """Safely extract Diagnostic list from an exception's to_diagnostics() method."""
    if not hasattr(exc, "to_diagnostics"):
        return []
    try:
        diags = exc.to_diagnostics()
    except Exception:
        return []
    return [d for d in diags if isinstance(d, Diagnostic)]


def _lookup_last_cost(
    config: NodeConfig, cache: MemoizationCache,
) -> tuple[Optional[float], Optional[float]]:
    """For LLM-family nodes, look up the latest memo entry and extract cost.

    Returns (cost_usd, age_sec). Both None if node isn't LLM-family, has no
    history, or the history lacks cost_usd.
    """
    if config.node_type_name not in _LLM_NODE_CLASSES:
        return None, None

    latest = cache.get_latest_for_node(config.node_id)
    if latest is None:
        return None, None

    output, created_at = latest
    llm_usage = output.get("llm_usage") if isinstance(output, dict) else None
    if not isinstance(llm_usage, dict):
        return None, None

    cost = llm_usage.get("cost_usd")
    if not isinstance(cost, (int, float)):
        return None, None

    import time as _time
    age = _time.time() - created_at
    return float(cost), age


def _summarize(
    entries: list[PlanEntry],
    diagnostics: list[Diagnostic],
    *,
    cost_basis: str = "exact",
) -> PlanSummary:
    """Aggregate per-level counts plus nested aggregation if any sub_plan exists.

    Counting rules:
    - `cached_count`: entries with status == "cached"
    - `execute_count`: entries with status in ("execute", "opaque") PLUS
       sub_workflow entries whose child plan has any execution. The parent
       WorkflowExecutor frame is memo-skipped so it always executes at
       runtime when its child has work; so it must count as execute.
    - `execute_by_type`: counts for execute + opaque at this level. Sub-workflow
       entries contribute via their type tag (the parent frame is the cost, not
       the child nodes — children are counted at their own level).
    """
    total = len(entries)
    cached_count = sum(1 for e in entries if e.status == "cached")

    def _is_executing(e: PlanEntry) -> bool:
        if e.status in ("execute", "opaque"):
            return True
        if e.status == "sub_workflow" and e.sub_plan is not None:
            # Child has work (direct or nested) → parent frame executes
            s = e.sub_plan.summary
            return (s.execute_count > 0) or (s.execute_including_nested or 0) > 0
        return False

    execute_count = sum(1 for e in entries if _is_executing(e))

    cache_boundary: Optional[str] = None
    for e in entries:
        if _is_executing(e) and e.cause != "downstream":
            cache_boundary = e.node_id
            break

    execute_by_type: dict[str, int] = {}
    for e in entries:
        if _is_executing(e):
            execute_by_type[e.node_type] = execute_by_type.get(e.node_type, 0) + 1

    estimated_cost_usd = sum(
        e.last_cost_usd for e in entries if e.last_cost_usd is not None
    )
    nodes_without_history = sum(
        1 for e in entries
        if e.status == "execute"
        and e.node_type in _LLM_NODE_CLASSES
        and e.last_cost_usd is None
    )

    # Nested aggregation (when any sub_plan exists)
    has_nested = any(e.sub_plan is not None for e in entries)
    total_nested: Optional[int] = None
    cached_nested: Optional[int] = None
    execute_nested: Optional[int] = None
    cost_nested: Optional[float] = None
    nwh_nested: Optional[int] = None
    # Propagate cost_basis upward: if any child plan was upper_bound, parent is too.
    effective_cost_basis = cost_basis

    if has_nested:
        total_nested = total
        cached_nested = cached_count
        execute_nested = execute_count
        cost_nested = estimated_cost_usd
        nwh_nested = nodes_without_history
        for e in entries:
            if e.sub_plan is not None:
                child = e.sub_plan.summary
                total_nested += child.total_including_nested if child.total_including_nested is not None else child.total
                cached_nested += child.cached_including_nested if child.cached_including_nested is not None else child.cached_count
                execute_nested += child.execute_including_nested if child.execute_including_nested is not None else child.execute_count
                cost_nested += child.estimated_cost_usd_including_nested if child.estimated_cost_usd_including_nested is not None else child.estimated_cost_usd
                nwh_nested += child.nodes_without_history_including_nested if child.nodes_without_history_including_nested is not None else child.nodes_without_history
                if child.cost_basis == "upper_bound":
                    effective_cost_basis = "upper_bound"

    return PlanSummary(
        total=total,
        cached_count=cached_count,
        execute_count=execute_count,
        cache_boundary=cache_boundary,
        execute_by_type=execute_by_type,
        estimated_cost_usd=estimated_cost_usd,
        nodes_without_history=nodes_without_history,
        cost_basis=effective_cost_basis,
        total_including_nested=total_nested,
        cached_including_nested=cached_nested,
        execute_including_nested=execute_nested,
        estimated_cost_usd_including_nested=cost_nested,
        nodes_without_history_including_nested=nwh_nested,
    )
```

### Phase 5 verification
- `make check` passes.
- `from pflow.execution.plan import build_plan` works.
- A small smoke test: compile a 2-node workflow, pass to `build_plan`, assert that the plan has 2 entries.

---

## Phase 6 — Plan formatter

### 6.1 — Create `src/pflow/execution/formatters/plan_formatter.py`

```python
"""Shared formatters for --dry-run execution plans.

Pattern (matches success_formatter): JSON is the SSOT, text is rendered from
the dict returned by format_plan_json.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import click

from pflow.core.diagnostic_render import format_diagnostic

if TYPE_CHECKING:
    from pflow.core.diagnostic import Diagnostic
    from pflow.execution.result import Plan, PlanEntry


# Node-type tag mapping. Keys are NodeConfig.node_type_name (class names,
# e.g. "LLMNode"). Values are short agent-readable tags.
_NODE_TYPE_TAGS: dict[str, str] = {
    "LLMNode": "LLM",
    "ClaudeCodeNode": "Claude",
    "HttpNode": "HTTP",
    "ShellNode": "shell",
    "MCPNode": "MCP",
    "PythonCodeNode": "code",
    "ReadFileNode": "read-file",
    "WriteFileNode": "write-file",
    "CopyFileNode": "copy-file",
    "MoveFileNode": "move-file",
    "DeleteFileNode": "delete-file",
    "WorkflowExecutor": "workflow",
}


def format_plan_json(plan: Plan) -> dict[str, Any]:
    """Render a Plan as a JSON-serializable dict (SSOT for text rendering)."""
    return {
        "workflow": plan.workflow,
        "plan": [_entry_to_dict(e) for e in plan.entries],
        "summary": _summary_to_dict(plan.summary),
        "diagnostics": [d.to_dict() for d in plan.diagnostics],
    }


def format_plan_text(plan: Plan) -> str:
    """Render a Plan as human-readable text (boundary-divider idiom)."""
    lines: list[str] = []
    # Header
    header_bits = [f"{plan.summary.total} nodes"]
    # Count sub-workflows at this level
    sub_count = sum(1 for e in plan.entries if e.status == "sub_workflow")
    if sub_count:
        header_bits.append(f"{sub_count} sub-workflow{'s' if sub_count != 1 else ''}")
    lines.append(f"Plan for {plan.workflow} ({', '.join(header_bits)}):")
    lines.append("")

    lines.extend(_render_entries(plan.entries, indent_level=0, boundary_shown=[False]))

    # Summary
    lines.append("")
    summary_parts = [f"{plan.summary.cached_count} cached", f"{plan.summary.execute_count} would execute"]
    if plan.summary.execute_by_type:
        types_str = ", ".join(f"{c} {t}" for t, c in sorted(plan.summary.execute_by_type.items()))
        summary_parts[-1] += f" ({types_str})"
    if plan.summary.total_including_nested is not None:
        lines.append(f"Summary (including nested): {' · '.join(summary_parts)}")
    else:
        lines.append(f"Summary: {' · '.join(summary_parts)}")

    # Prefer the nested-aggregated cost if available — it's what agents should
    # cost-gate against. The per-level `estimated_cost_usd` is usually a subset.
    effective_cost = (
        plan.summary.estimated_cost_usd_including_nested
        if plan.summary.estimated_cost_usd_including_nested is not None
        else plan.summary.estimated_cost_usd
    )
    effective_nwh = (
        plan.summary.nodes_without_history_including_nested
        if plan.summary.nodes_without_history_including_nested is not None
        else plan.summary.nodes_without_history
    )

    if effective_cost > 0:
        basis_label = (
            "upper bound across all branches, historical"
            if plan.summary.cost_basis == "upper_bound"
            else "historical, actual may vary"
        )
        lines.append(
            f"Estimated cost: ≈ {_format_cost(effective_cost)}  ({basis_label})"
        )
    if effective_nwh > 0:
        lines.append(
            f"  ({effective_nwh} LLM node"
            f"{'s' if effective_nwh != 1 else ''} without history)"
        )

    lines.append("No side effects performed.")

    # Diagnostics at the end
    if plan.diagnostics:
        lines.append("")
        for d in plan.diagnostics:
            lines.append(format_diagnostic(d))

    return "\n".join(lines)


def _render_entries(
    entries: list[PlanEntry], indent_level: int, boundary_shown: list[bool],
) -> list[str]:
    """Render a level of entries with divider + indent."""
    lines: list[str] = []
    indent = "  " + "    " * indent_level  # 2-space base indent, 4-space nesting step
    # Special case: nothing cached at this level → show divider at top
    all_execute = entries and all(e.status in ("execute", "opaque") for e in entries)
    any_cached = any(e.status == "cached" for e in entries)

    if all_execute and not any_cached and indent_level == 0:
        lines.append(f"{indent}─── nothing cached — full run ───")

    for e in entries:
        # Divider before first would-execute at this level
        if not boundary_shown[0] and e.status in ("execute", "opaque") and e.cause != "downstream":
            if indent_level == 0 and (any_cached or _has_any_cached_above(entries, e)):
                lines.append(f"{indent}─── cache boundary: '{e.node_id}' ───")
                boundary_shown[0] = True
            elif indent_level > 0:
                # Nested boundary
                lines.append(f"{indent}─── cache boundary: '{e.node_id}' ───")
                boundary_shown[0] = True

        lines.append(_render_entry_line(e, indent))

        if e.sub_plan is not None:
            # Recurse with a fresh boundary-shown tracker for the nested level
            nested_lines = _render_entries(
                e.sub_plan.entries, indent_level + 1, boundary_shown=[False],
            )
            lines.extend(nested_lines)

    return lines


def _has_any_cached_above(entries: list[PlanEntry], target: PlanEntry) -> bool:
    """Check if any earlier entry in this level is cached."""
    for e in entries:
        if e is target:
            return False
        if e.status == "cached":
            return True
    return False


def _render_entry_line(e: PlanEntry, indent: str) -> str:
    """Render one entry line per task-156 §'Text output format'."""
    if e.status == "cached":
        age = f"  ({_format_age(e.age_sec)} ago)" if e.age_sec else ""
        return f"{indent}{click.style('↻', fg='blue', dim=True)} {e.node_id}{age}"

    tag = f"  [{_tag_from_entry(e)}]"
    if e.status == "sub_workflow":
        ref = e.sub_plan.workflow if e.sub_plan else "<unknown>"
        count = e.sub_plan.summary.total if e.sub_plan else 0
        return f"{indent}▸ {e.node_id}  [sub-workflow '{ref}' ({count} node{'s' if count != 1 else ''})]"

    if e.status == "opaque":
        return f"{indent}▸ {e.node_id}  [sub-workflow: dynamic, cannot plan]"

    if e.status == "routing_error":
        return f"{indent}▸ {e.node_id}{tag}  [routing error]"

    # execute
    cost_str = ""
    if e.last_cost_usd is not None and e.last_run_age_sec is not None:
        cost_str = f"   ≈ {_format_cost(e.last_cost_usd)} (last run {_format_age(e.last_run_age_sec)} ago)"
    elif _is_llm_entry(e) and e.last_cost_usd is None:
        cost_str = "   ≈ $? (no history)"

    return f"{indent}▸ {e.node_id}{tag}{cost_str}"


def _is_llm_entry(e: PlanEntry) -> bool:
    return e.node_type in ("LLMNode", "ClaudeCodeNode")


def _tag_from_entry(e: PlanEntry) -> str:
    tag = _NODE_TYPE_TAGS.get(e.node_type, e.node_type)
    if e.cause == "cache_disabled":
        tag = f"{tag}, cache: false"
    return tag


def _format_age(age_sec: float | None) -> str:
    """Short-form age: 'Xs', 'Xm', 'Xh', 'Xd'."""
    if age_sec is None:
        return "?"
    if age_sec < 60:
        return f"{int(age_sec)}s"
    if age_sec < 3600:
        return f"{int(age_sec // 60)}m"
    if age_sec < 86400:
        return f"{int(age_sec // 3600)}h"
    return f"{int(age_sec // 86400)}d"


def _format_cost(cost_usd: float) -> str:
    """2 decimals when >= $0.01, 4 decimals when < $0.01."""
    if cost_usd >= 0.01:
        return f"${cost_usd:.2f}"
    return f"${cost_usd:.4f}"


def _entry_to_dict(e: PlanEntry) -> dict[str, Any]:
    d: dict[str, Any] = {
        "node_id": e.node_id,
        "node_type": e.node_type,
        "status": e.status,
        "cause": e.cause,
    }
    if e.action is not None:
        d["action"] = e.action
    if e.age_sec is not None:
        d["age_sec"] = e.age_sec
    if e.last_cost_usd is not None:
        d["last_cost_usd"] = e.last_cost_usd
    if e.last_run_age_sec is not None:
        d["last_run_age_sec"] = e.last_run_age_sec
    if e.sub_plan is not None:
        d["sub_plan"] = format_plan_json(e.sub_plan)
    if e.diagnostic is not None:
        d["diagnostic"] = e.diagnostic.to_dict()
    return d


def _summary_to_dict(s: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "total": s.total,
        "cached_count": s.cached_count,
        "execute_count": s.execute_count,
        "cache_boundary": s.cache_boundary,
        "execute_by_type": dict(s.execute_by_type),
        "estimated_cost_usd": s.estimated_cost_usd,
        "nodes_without_history": s.nodes_without_history,
        "cost_basis": s.cost_basis,  # "upper_bound" or "exact" — agent-readable semantics
    }
    if s.total_including_nested is not None:
        d["total_including_nested"] = s.total_including_nested
        d["cached_including_nested"] = s.cached_including_nested
        d["execute_including_nested"] = s.execute_including_nested
    if s.estimated_cost_usd_including_nested is not None:
        d["estimated_cost_usd_including_nested"] = s.estimated_cost_usd_including_nested
        d["nodes_without_history_including_nested"] = s.nodes_without_history_including_nested
    return d
```

### Phase 6 verification
- `make check` passes.
- Construct a synthetic `Plan` in a Python REPL and call both `format_plan_json(plan)` and `format_plan_text(plan)`. Confirm the JSON has `workflow`, `plan`, `summary`, `diagnostics` keys and the text contains expected divider markers.

---

## Phase 7 — `WorkflowRunner.plan()`

### 7.1 — Modify `src/pflow/execution/runner.py`

**Add a new method to `WorkflowRunner` after `validate()` (approximately after L253)**:

```python
def plan(
    self,
    workflow: str | dict[str, Any] | ResolvedWorkflow,
    params: dict[str, Any],
    config: RunnerConfig,
) -> Plan:
    """Build an execution plan without invoking any node.

    Reuses the resolution, file-ref, validation, and compilation pipeline from
    run(), then delegates to build_plan() instead of running the engine. No
    trace collector, metrics collector, MCP pool, or progress callback is
    created — the plan has no execution-time observability needs.

    Raises:
        WorkflowValidationError, WorkflowNotFoundError, CompilationError,
        or other Pflow-surface errors on planning-time failures. Callers
        (CLI, MCP) catch these and convert to Diagnostic output.
    """
    from pflow.execution.plan import build_plan
    from pflow.registry import Registry
    from pflow.runtime import compile_workflow
    from pflow.runtime.cache import MemoizationCache

    params = dict(params)  # Copy at boundary

    validation_diags: list[Diagnostic] = []
    resolved = self._prepare_workflow(workflow, params, validation_diags)

    cache = MemoizationCache(read_enabled=config.cache_enabled)
    registry = Registry()

    self._strip_placeholders(params)
    compiled = compile_workflow(resolved.ir, registry=registry, initial_params=params)

    workflow_name = (
        resolved.file_path
        if resolved.file_path
        else (str(workflow) if isinstance(workflow, str) else "<workflow>")
    )

    plan = build_plan(
        compiled,
        params,
        cache,
        registry,
        workflow_name=workflow_name,
        only_node=config.only_node,
        _parent_workflow_file=resolved.file_path,
    )

    # Merge validation warnings into plan diagnostics for visibility
    if validation_diags:
        from dataclasses import replace
        plan = replace(plan, diagnostics=[*plan.diagnostics, *validation_diags])

    return plan
```

**Add the import for `Plan`** (near the top of runner.py):
```python
from .result import ExecutionResult, Plan, ResolvedWorkflow, RunnerConfig, ValidationResult
```

### Phase 7 verification
- `from pflow.execution.runner import WorkflowRunner; runner = WorkflowRunner(); plan = runner.plan(...)` works on a small test workflow.
- The returned Plan has populated `workflow`, `entries`, `summary`, `diagnostics`.

---

## Phase 8 — Wire `--dry-run` CLI flag

### 8.1 — Modify `src/pflow/cli/commands/run.py`

**Add `--dry-run` option decorator to the `run` command** (sibling of `--validate-only`, approximately L730):

```python
@click.option("--dry-run", "dry_run", is_flag=True,
              help="Build execution plan without invoking side effects (see docs)")
```

**Update `run()` signature** (approximately L736–L748) to include `dry_run: bool`:
```python
def run(
    ctx: click.Context,
    output_key: str | None,
    output_format: str,
    print_flag: bool,
    no_trace: bool,
    report_flag: bool,
    report_dir: str | None,
    validate_only: bool,
    cache: bool,
    only_node: str | None,
    dry_run: bool,  # NEW
    workflow: tuple[str, ...],
) -> None:
```

**Inside `run()`**, after the existing `_initialize_context` call (approximately L755), add the mutual-exclusion check:

```python
# Mutual exclusion: dry-run has strict flag combination rules
_validate_dry_run_flag_combination(
    dry_run=dry_run,
    validate_only=validate_only,
    report_flag=report_flag,
    report_dir=report_dir,
)

ctx.obj["dry_run"] = dry_run
```

**Add the helper function `_validate_dry_run_flag_combination` as a module-level function in `run.py`** (near the other `_validate_*` helpers):

```python
def _validate_dry_run_flag_combination(
    *,
    dry_run: bool,
    validate_only: bool,
    report_flag: bool,
    report_dir: str | None,
) -> None:
    """Enforce task-156 §'CLI surface' mutual-exclusion rules.

    - --dry-run + --validate-only: hard error (different audiences).
    - --dry-run + --report / --report-dir: hard error (nothing to report).
    - --dry-run + --no-trace: silent accept (no trace saved anyway).
    - --dry-run + -p/--print: silent accept (plan output is the result).
    """
    if not dry_run:
        return
    from pflow.core.user_errors import UserFriendlyError

    if validate_only:
        raise UserFriendlyError(
            title="Cannot combine --dry-run and --validate-only",
            explanation=(
                "These flags answer different questions: --dry-run shows what "
                "would happen at runtime; --validate-only checks structural "
                "validity. Pick one."
            ),
            suggestions=[
                "pflow <workflow> --dry-run",
                "pflow <workflow> --validate-only",
            ],
        )

    if report_flag or report_dir is not None:
        raise UserFriendlyError(
            title="Cannot combine --dry-run and --report",
            explanation=(
                "--report generates output from execution traces; --dry-run "
                "does not execute anything, so there is nothing to report."
            ),
            suggestions=[
                "pflow <workflow> --dry-run",
                "pflow <workflow> --report",
            ],
        )
```

### 8.2 — Modify `execute_json_workflow` to route to plan path

**File**: `src/pflow/cli/commands/run.py`

**Current state**: the `validate_only` branch is at approximately L207–L211. Add a sibling branch for dry-run BEFORE the execution setup:

```python
if ctx.obj.get("dry_run"):
    _display_plan_result(ctx, workflow, params, output_format)
    return

if ctx.obj.get("validate_only"):
    # ... existing code
```

**Add the new helper `_display_plan_result`** as a module-level function in `run.py` (mirror of `_display_validation_result`):

```python
def _display_plan_result(
    ctx: click.Context,
    workflow: dict[str, Any] | ResolvedWorkflow,
    params: dict[str, Any],
    output_format: str,
) -> None:
    """Build and display the execution plan for --dry-run mode."""
    from pflow.cli.error_output import output_error
    from pflow.execution.formatters.plan_formatter import (
        format_plan_json,
        format_plan_text,
    )
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner

    config = RunnerConfig(
        trace_enabled=False,
        cache_enabled=ctx.obj.get("cache", True),
        verbose=ctx.obj.get("verbose", False),
        only_node=ctx.obj.get("only_node"),
    )

    try:
        runner = WorkflowRunner()
        plan = runner.plan(workflow, params, config)
    except click.exceptions.Exit:
        raise
    except Exception as e:
        output_error(
            ctx,
            exception=e,
            output_format=output_format,
            verbose=ctx.obj.get("verbose", False),
            workflow_metadata=ctx.obj.get("workflow_metadata"),
        )
        ctx.exit(1)

    if output_format == "json":
        import json as _json
        click.echo(_json.dumps(format_plan_json(plan), indent=2, default=str))
    else:
        click.echo(format_plan_text(plan))

    ctx.exit(0)
```

### 8.3 — Add `dry_run` to `_validate_workflow_flags`

**File**: `src/pflow/cli/commands/run.py`

The function `_validate_workflow_flags` at approximately L402 enumerates known flags for "misplaced flag" detection. Add `"--dry-run"` to the tuple.

### Phase 8 verification
- `make check` passes.
- `pflow <test_workflow.pflow.md> --dry-run` produces a text plan and exits 0.
- `pflow <test_workflow.pflow.md> --dry-run --output-format json` produces valid JSON to stdout and exits 0.
- `pflow <test_workflow.pflow.md> --dry-run --validate-only` exits 1 with a clear error message.
- `pflow <test_workflow.pflow.md> --dry-run --report` exits 1 with a clear error message.

---

## Phase 9 — MCP server `plan_workflow` tool

### 9.1 — Add service method

**File**: `src/pflow/mcp_server/services/execution_service.py`

**Add a new classmethod to `ExecutionService`** (sibling of `validate_workflow`, approximately after L299):

```python
@classmethod
@ensure_stateless
def plan_workflow(
    cls,
    workflow: Any,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build workflow execution plan without invoking side effects.

    Returns the same JSON shape as CLI `--dry-run --output-format json`.

    Args:
        workflow: Workflow name (library), path to .pflow.md, raw markdown,
            or IR dict.
        parameters: Input parameters as key-value pairs.

    Returns:
        JSON-serializable dict with plan, summary, and diagnostics.

    Raises:
        ValueError: Workflow not found (with suggestions) or parameters
            fail security validation.
        RuntimeError: Planning fails (validation, compilation, or unexpected).
    """
    from pflow.execution.formatters.plan_formatter import format_plan_json
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner

    validated_params: dict[str, Any] = {}
    if parameters:
        is_valid, error = validate_execution_parameters(parameters)
        if not is_valid:
            raise ValueError(f"Invalid parameters: {error}")
        validated_params = dict(parameters)

    try:
        resolved = _unified_resolve(workflow)
    except WorkflowNotFoundError as e:
        hint = str(e)
        if e.similar_names:
            hint += f"\nDid you mean: {', '.join(e.similar_names[:5])}"
        raise ValueError(hint) from e
    except Exception as e:
        raise ValueError(str(e)) from e

    if resolved.file_path:
        validated_params["_pflow_workflow_file"] = resolved.file_path

    runner = WorkflowRunner()
    try:
        plan = runner.plan(resolved, validated_params, RunnerConfig())
    except Exception as e:
        logger.error(f"Workflow planning failed: {e}", exc_info=True)
        raise RuntimeError(f"❌ Workflow planning failed: {e}") from e

    return format_plan_json(plan)
```

### 9.2 — Register the tool

**File**: `src/pflow/mcp_server/tools/execution_tools.py`

**Add a new async function** (near `workflow_execute` and `workflow_validate`, approximately after L154):

```python
@mcp.tool()
async def plan_workflow(
    workflow: Annotated[
        str | dict[str, Any],
        Field(description="Workflow name from library, path to workflow file, or workflow IR object"),
    ],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(description="Input parameters as key-value pairs matching the workflow's declared inputs"),
    ] = None,
) -> dict[str, Any]:
    """Build a workflow execution plan WITHOUT invoking any side effects.

    Shows which nodes would serve from cache, which would actually run, the
    resolved parameters, and cost estimates for LLM nodes (based on the most
    recent cached run). Use before workflow_execute to:
    - Confirm you understand what a run will do
    - Cost-gate expensive LLM workflows before invoking them
    - Diagnose why a node isn't hitting cache

    Does NOT execute shell, HTTP, LLM, MCP, or file-writing nodes.

    Returns:
        JSON dict with keys: workflow, plan (list of per-node entries with
        status, cause, and optional cost data), summary (counts, cost estimate,
        cache_boundary, execute_by_type), diagnostics.
    """
    logger.debug(f"plan_workflow called: workflow type={type(workflow).__name__}")

    def _sync_plan() -> dict[str, Any]:
        return ExecutionService.plan_workflow(workflow, parameters)

    result = await asyncio.to_thread(_sync_plan)
    logger.info("Workflow plan generated")
    return result
```

**Add `"plan_workflow"` to `__all__`** at the bottom of the file:
```python
__all__ = [
    "plan_workflow",   # NEW
    "read_fields",
    "registry_run",
    "workflow_execute",
    "workflow_save",
    "workflow_validate",
]
```

### Phase 9 verification
- `make check` passes.
- Manually test via MCP: spin up `pflow mcp serve` (if trivial) or invoke `ExecutionService.plan_workflow(...)` directly from a test.

---

## Phase 10 — Tests

Organize new tests as follows. Each test file follows the `isolate_pflow_config` autouse pattern (see `tests/conftest.py`). Use `tmp_path` for workflow files.

### 10.1 — `tests/test_runtime/test_plan_node.py`

Unit tests for the `plan_node()` primitive. Test:
- Returns `status="cache_disabled"` when `config.cache_enabled=False`.
- Returns `status="miss"` + `cache_key` on fresh workflow.
- Returns `status="cached_memo"` after a put.
- Returns `status="cached_in_process"` for a node that completed earlier in the same run.
- Returns `status="miss"` + `template_exception` set for strict-mode unresolved template.
- Does NOT mutate `shared` on cache hit (assert state unchanged).

Build synthetic IR via `ir_to_markdown` helper (tests/shared/markdown_utils.py).

### 10.2 — `tests/test_runtime/test_cache.py` (extend existing)

Add tests for new cache methods:
- `test_get_with_age_returns_action_output_and_timestamp`
- `test_get_with_age_respects_ttl` (backdate created_at past TTL, assert None)
- `test_get_with_age_respects_read_enabled` (construct with `read_enabled=False`, assert None)
- `test_get_latest_for_node_returns_most_recent` (put two entries with same node_id, different cache_keys; assert latest wins)
- `test_get_latest_for_node_returns_none_for_unknown_node`
- `test_get_latest_for_node_respects_ttl`
- `test_idx_node_id_created_at_exists` (pragma query on sqlite schema — assert index present)

### 10.3 — `tests/test_runtime/test_instrumented_wrapper.py` (extend existing)

Add LLMNode cost fix test:
- `test_llmnode_post_enriches_cost_before_write`: execute a 1-node LLMNode workflow, assert `shared["llm_usage"]["cost_usd"]` is set. Also query `cache.get_latest_for_node("my_llm")` after the run and assert the stored BLOB's `llm_usage` has `cost_usd` populated (catches the Phase 0.1 bug regression where cost was enriched after memo write).

### 10.3a — `tests/test_nodes/test_llm/test_llm.py` (REQUIRED update — existing test breaks)

**`test_usage_data_stored_correctly` at approximately line 442** asserts `shared["llm_usage"] == {...}` with full-dict equality. The Phase 0.1 fix adds `cost_usd` to that dict, so the existing `==` assertion fails.

Fix: change the assertion from full-dict equality to one of:
- Subset containment: assert every expected key/value is in `shared["llm_usage"]`, and separately assert `"cost_usd" in shared["llm_usage"]`.
- OR add `cost_usd` to the expected dict with the value `enrich_llm_usage_with_cost` would compute for that model/token count.

The simpler fix: update expected dict with expected `cost_usd` (pricing table gives deterministic values — use the actual model and tokens to predict).

This is the only pre-existing test that breaks from the LLMNode change; all others use `{}` (empty-dict equality) on error paths, unaffected.

### 10.4 — `tests/test_execution/test_plan.py`

Integration tests for `build_plan()`. Pattern (see `test_cache_integration.py:125-155`):
- Test fresh workflow → all entries `status="execute"`, `cause="no_cache_match"`.
- Test fully cached workflow → all `status="cached"`, `summary.cache_boundary is None`.
- Test partial cache after config edit → entries up to edit are `cached`, edited node is `execute + no_cache_match`, downstream are `execute + downstream`.
- Test `cache: false` node → always `execute + cache_disabled`.
- Test opaque sub-workflow (`workflow: ${var}`) → one entry with `status="opaque"`.
- Test sub-workflow recursion → parent entry has `sub_plan`, nested `entries` populated.
- Test max-depth guard → plan aborts gracefully with diagnostic.
- Test circular sub-workflow → diagnostic emitted, no infinite recursion.
- Test `visited_edges` loop protection → workflow with cyclic retry doesn't hang.

### 10.5 — `tests/test_execution/test_plan_drift.py` (drift-catcher — REQUIRED)

**This test is the load-bearing invariant. It runs a workflow end-to-end via the engine, captures per-node outcomes, then runs the same workflow via `build_plan` and asserts the predictions match.**

```python
"""Drift-catcher test: plan_node output must match real execution outcomes.

This test prevents Option-D-style drift from sneaking back in via future
refactors. If plan_node() and the engine's per-node decision logic ever
diverge, this test fails — fix the divergence, do not suppress the test.
"""

import pytest

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.runtime.cache import MemoizationCache
from tests.shared.markdown_utils import write_workflow_file


def test_plan_matches_execution_for_fresh_workflow(tmp_path):
    """Every node the plan predicts 'execute' actually executes."""
    # ... build 3-node shell workflow, write to tmp_path, plan, then execute,
    # ... assert that every "execute" plan entry corresponds to a node that
    # ... actually ran (detectable via side-effect file).


def test_plan_matches_execution_after_first_run(tmp_path):
    """After a full run, plan predicts 'cached' for every node, and a second
    execution confirms no re-run happened (side-effect file count unchanged)."""


def test_plan_matches_execution_after_config_edit(tmp_path):
    """Run → edit one node's params → plan predicts that node + downstream
    will execute → actual second execution confirms cached prefix + executed
    suffix matches the plan's boundary."""


def test_plan_matches_execution_with_conditional_branch(tmp_path):
    """Cached node → follow its cached action → planner and engine take the
    same branch."""


def test_plan_cross_node_template_resolution(tmp_path):
    """CRITICAL: cached node A feeds cached node B via ${A.field}.
    Planner must populate shared[A]=cached_output so B's template resolves
    and B's cache-key matches what the engine computed. Run once to populate
    cache; second dry-run must show BOTH nodes as cached (not "B: no_cache_match").
    Regression test for the 'planner doesn't mutate shared' bug caught in review."""


def test_plan_retry_loop_iteration_matches(tmp_path):
    """flaky - 'error' >> flaky retry pattern. On iteration 2+, engine skips
    memo lookup (visit_count > 1). Planner must also skip (via visit_counts
    bump). Assert planner's iteration-2 prediction matches engine's iteration-2
    behavior."""


def test_plan_sub_workflow_partial_cache_matches(tmp_path):
    """Parent with 2 nodes around a sub-workflow of 3 nodes. First run caches
    all 5. Edit one child node's config. Plan must predict: parent-pre-child
    cached, child boundary at edited node, parent-post-child downstream. Actual
    execution must match each prediction."""


def test_plan_batch_items_cache_matches(tmp_path):
    """Batch LLM node. First run populates per-item cache. Second dry-run must
    show the batch node as cached with same item count. Regression test for
    batch cache-key divergence (C1 from review)."""


def test_plan_cache_false_always_executes(tmp_path):
    """Node with cache: false. Plan predicts 'execute, cause=cache_disabled'.
    Actual execution confirms node runs fresh regardless of prior run state."""


def test_plan_bfs_post_boundary_enumerates_branches(tmp_path):
    """Workflow: A (cached) → B (first miss, branches: - next: x, - next: y)
    where x → C and y → D. Planner should enumerate BOTH C and D as
    'execute + downstream'. Assert len(plan.entries) >= 4 (A, B, C, D).
    Summary.cost_basis must be 'upper_bound'."""


def test_plan_routing_error_on_missing_successor(tmp_path):
    """Cached node with action 'approve' but no 'approve' successor edge
    (edge removed post-cache). Plan must emit status='routing_error' entry
    and terminate. Actual execution confirms engine raises routing error."""
```

### 10.6 — `tests/test_cli/test_dry_run.py`

CLI integration tests (follow `test_validate_only.py` pattern):
- `test_dry_run_does_not_execute_shell_node`: write a workflow with `shell: touch /tmp/proof`, run `--dry-run`, assert the file doesn't exist.
- `test_dry_run_exits_zero_on_success`.
- `test_dry_run_exits_one_on_missing_required_input`.
- `test_dry_run_json_output_is_valid_json` + schema-shape check.
- `test_dry_run_text_output_contains_boundary_divider`.
- `test_dry_run_plus_validate_only_exits_one_with_clear_error`.
- `test_dry_run_plus_report_exits_one_with_clear_error`.
- `test_dry_run_plus_no_trace_is_silent_accept`.
- `test_dry_run_plus_print_is_silent_accept` (full plan still renders).
- `test_dry_run_composes_with_only_node`.
- `test_dry_run_no_network_calls`: patch `requests.request` and `llm.get_model` (autouse mock exists), assert call_count is 0.

### 10.7 — `tests/test_mcp_server/test_plan_workflow.py`

MCP tool tests (follow `test_execution_workflow.py` pattern):
- `test_plan_workflow_returns_dict_with_expected_keys`.
- `test_plan_workflow_matches_cli_json_shape`: call service directly, compare shape to CLI `--dry-run --output-format json` output for same workflow.
- `test_plan_workflow_not_found_raises_value_error_with_suggestion`.
- `test_plan_workflow_compile_error_raises_runtime_error`.

### Phase 10 verification
- `make test` passes (entire suite — new tests + pre-existing).
- Count of new tests is roughly 35–45.

---

## Phase 11 — CLAUDE.md updates

### 11.1 — `src/pflow/runtime/CLAUDE.md`

Add a new section `## Planner (Dry-Run)` between `## Template System` and `## Other Components`. Content:

- Short description of `plan_node()` in `runtime/engine/plan_node.py` and `build_plan()` in `execution/plan.py`.
- Load-bearing invariant: "plan_node() is the single authoritative source for cache-hit semantics. Both the engine and the planner call it. Changes to cache-key computation, template resolution, or cache-enable rules MUST live in plan_node(), not in the engine's _execute_node or in build_plan."
- Pointer to the drift-catcher test at `tests/test_execution/test_plan_drift.py`.

### 11.2 — `src/pflow/runtime/engine/CLAUDE.md`

In the existing `## Architecture` section, replace the step-numbered pseudocode's steps 4–7 with a single line `plan_node() → decides cached/miss and returns NodePlan`. Preserve all other step descriptions.

Add subsection `### plan_node.py — The Shared Decision Primitive` under `## WorkflowEngine (engine.py)`:
- Describes the function and its fields.
- Notes that `check_memo_cache` / `check_cache_validity` remain as thin wrappers for backwards-compat test callers.
- Notes that `memo_cache_lookup` / `apply_memo_hit` / `in_process_cache_lookup` are the new pure primitives.

### 11.3 — `src/pflow/execution/CLAUDE.md`

In `## WorkflowRunner — Primary Entry Point`, document the new `plan(workflow, params, config) -> Plan` method alongside `run()` and `validate()`. Note: no trace/metrics/pool created in plan path.

In `## Result Types (result.py)`, add `Plan`, `PlanEntry`, `PlanSummary` to the existing list.

### 11.4 — `src/pflow/cli/CLAUDE.md`

In `## Command Flags` → `run` command only table, add `--dry-run` with description.

In `## Context (ctx.obj) — Non-Obvious Keys` table, add `dry_run` key.

### 11.5 — `src/pflow/cli/commands/CLAUDE.md`

Update `## File Overview` table if `run.py` lines count changed meaningfully. Add a test-mapping entry: `tests/test_cli/test_dry_run.py`.

### 11.6 — `src/pflow/mcp_server/services/CLAUDE.md` and `src/pflow/mcp_server/tools/CLAUDE.md`

Document the new `plan_workflow` service method and tool alongside existing `execute_workflow` / `validate_workflow`.

### Phase 11 verification
- `make test` passes (no test should be CLAUDE.md-coupled, but run for safety).
- Grep: `rg 'plan_node|build_plan|plan_workflow' src/pflow/**/CLAUDE.md` returns matches in each updated file.

---

## End-to-end verification (post-implementation)

Run through the manual scenarios from task-156 §Verification.Manual scenarios (1–12). All MUST pass. Most critical:

**#11 Zero side effects**:
```bash
# Build a workflow with a shell canary
cat > /tmp/canary.pflow.md <<'EOF'
# Canary test
## Steps
### write-canary
- type: shell
- command: echo hello > /tmp/pflow_dryrun_canary
EOF

rm -f /tmp/pflow_dryrun_canary
pflow /tmp/canary.pflow.md --dry-run
test ! -f /tmp/pflow_dryrun_canary  # MUST pass — file must not exist
```

**Drift-catcher**:
```bash
uv run pytest tests/test_execution/test_plan_drift.py -v
```

**Full suite**:
```bash
make test && make check
```

---

## Appendix — File:line anchor table

Quick navigation for agents implementing from this plan. All paths relative to repo root.

| Item | File | Approx lines |
|---|---|---|
| `_execute_node` (engine) | `src/pflow/runtime/engine/engine.py` | 181–427 |
| `_handle_no_successor` | `src/pflow/runtime/engine/engine.py` | 131–179 |
| `check_memo_cache` | `src/pflow/runtime/engine/instrumentation.py` | 173–246 |
| `check_cache_validity` | `src/pflow/runtime/engine/instrumentation.py` | 87–103 |
| `cache_result` | `src/pflow/runtime/engine/instrumentation.py` | 106–116 |
| `invalidate_cache` | `src/pflow/runtime/engine/instrumentation.py` | 119–125 |
| `handle_cached_execution` | `src/pflow/runtime/engine/instrumentation.py` | 438–486 |
| `compute_node_config` | `src/pflow/runtime/engine/instrumentation.py` | 131–162 |
| `compute_config_hash` | `src/pflow/runtime/engine/instrumentation.py` | 165–170 |
| `initialize_execution_state` | `src/pflow/runtime/engine/instrumentation.py` | 32–49 |
| `enforce_loop_guard` | `src/pflow/runtime/engine/instrumentation.py` | 52–81 |
| `resolve_templates` | `src/pflow/runtime/engine/template_resolution.py` | 279–445 |
| `resolve_batch_items` | `src/pflow/runtime/engine/batch_executor.py` | 32–55 |
| `compute_node_cache_key` | `src/pflow/runtime/cache.py` | 66–85 |
| `compute_batch_cache_key` | `src/pflow/runtime/cache.py` | 88–111 |
| `MemoizationCache.__init__` + `_init_db` | `src/pflow/runtime/cache.py` | 114–169 |
| `MemoizationCache.get` | `src/pflow/runtime/cache.py` | 181–221 |
| `MemoizationCache.put` | `src/pflow/runtime/cache.py` | 223–265 |
| `LLMNode.post()` | `src/pflow/nodes/llm/llm.py` | 356–417 |
| `ClaudeCodeNode` cost write | `src/pflow/nodes/claude/claude_code.py` | 875–887 |
| `enrich_llm_usage_with_cost` | `src/pflow/core/llm_pricing.py` | 191–227 |
| `CompiledWorkflow` | `src/pflow/runtime/engine/types.py` | 49–60 |
| `NodeConfig` | `src/pflow/runtime/engine/types.py` | 37–46 |
| `TemplateConfig` | `src/pflow/runtime/engine/types.py` | 12–20 |
| `WorkflowExecutor.ALLOWED_PARAMS` | `src/pflow/runtime/workflow_executor.py` | 75–81 |
| `resolve_sub_workflow` | `src/pflow/core/workflow/sub_workflow_resolver.py` | 26–130 |
| `compile_workflow` | `src/pflow/runtime/compilation/compiler.py` | 470–530 |
| `WorkflowRunner.run` | `src/pflow/execution/runner.py` | 49–126 |
| `WorkflowRunner.validate` | `src/pflow/execution/runner.py` | 255–341 |
| `WorkflowRunner._prepare_workflow` | `src/pflow/execution/runner.py` | 127–155 |
| `RunnerConfig` | `src/pflow/execution/result.py` | 10–21 |
| `ExecutionResult` | `src/pflow/execution/result.py` | 58–77 |
| `run` command | `src/pflow/cli/commands/run.py` | 691–795 |
| `execute_json_workflow` | `src/pflow/cli/commands/run.py` | 184–276 |
| `_initialize_context` | `src/pflow/cli/commands/run.py` | 365–384 |
| `_display_validation_result` | `src/pflow/cli/commands/run.py` | 329–362 |
| `ExecutionService.execute_workflow` | `src/pflow/mcp_server/services/execution_service.py` | 188–266 |
| `ExecutionService.validate_workflow` | `src/pflow/mcp_server/services/execution_service.py` | 268–299 |
| Tool registrations | `src/pflow/mcp_server/tools/execution_tools.py` | 19–92, 95–154 |
| `isolate_pflow_config` fixture | `tests/conftest.py` | 235–305 |
| `write_workflow_file` | `tests/shared/markdown_utils.py` | ~165 |
| `format_validation_success` / `_failure` | `src/pflow/execution/formatters/validation_formatter.py` | 11–53 |
| `format_diagnostic` | `src/pflow/core/diagnostic_render.py` | 10–49 |

---

## Appendix — Critical invariants for reviewers

1. **`plan_node()` is the single source of truth** for "would this node be cached". Both engine and planner call it. Changes to cache-key semantics MUST go in plan_node, not in either caller.
2. **Thin wrappers (`check_memo_cache`, `check_cache_validity`) are NOT deleted** — 9 tests in `test_checkpoint_tracking.py` and 1 in `test_memoization_integration.py` still call them directly. Their behavior is byte-identical to pre-refactor.
3. **The planner never calls `node._run()`**. Verified by `rg "node._run|_run\(" src/pflow/execution/plan.py` returning zero matches.
4. **The planner never calls `enforce_loop_guard`** (which has side effects on `__failures__`). Loop protection uses `visited_edges: set[(node_id, action)]` + BFS with `visited_nodes`. However, the planner DOES bump `visit_counts` (load-bearing, see #9).
5. **Cost estimates come from `MemoizationCache.get_latest_for_node`**, not tokenization. The LLMNode cost bug fix in phase 0 is a prerequisite.
6. **Sub-workflow recursion uses `resolve_sub_workflow` from `core/workflow/sub_workflow_resolver.py`** (not the top-level CLI resolver). This correctly returns `None` for template refs, but the opaque pre-check in `_plan_sub_workflow` runs FIRST to handle the `workflow: ${var}` case regardless of strict vs permissive mode.
7. **The drift-catcher test in `test_plan_drift.py` is load-bearing** — it enforces that planner predictions match actual engine outcomes. Do not suppress or skip if it fails; fix the divergence. 9 test cases required (listed in Phase 10.5).
8. **MCP tool returns `dict[str, Any]`**, not a string (only tool in the suite to do so — intentional, matches task-156 user decision).
9. **Planner scratch `shared` IS mutated** — specifically, on cache hits `_plan_standard_node` calls `apply_memo_hit` (writes `shared[node_id]`, `completed_nodes`, `node_actions`, `node_hashes`), and before every `plan_node` call the walker bumps `__execution__["node_visit_counts"][node_id]`. This is REQUIRED for byte-identical cache keys at downstream nodes. The caller-owned `params` dict is never mutated — only the scratch `shared` dict constructed inside `build_plan`.
10. **`memo_cache_lookup` returns `cache_key` on ALL paths**, including hits. Callers needing age (planner) use it directly; callers not needing it (engine's wrapper) discard it. This preserves the "one cache-key derivation" invariant — no re-deriving in `_plan_standard_node`.
11. **Post-first-miss uses BFS over all non-`error` successors**, not linear `default`-following. Produces a strict upper bound on cost (summary `cost_basis = "upper_bound"`). Safer for agent cost-gating than the lower-bound linear alternative.
12. **`_plan_sub_workflow` widens its exception catch** to `(CompilationError, WorkflowValidationError, MarkdownParseError, SchemaValidationError)` for compile and `(FileNotFoundError, ValueError, MarkdownParseError, WorkflowNotFoundError)` for resolve — matches `WorkflowExecutor._PREP_RECOVERABLE` runtime behavior. Narrower catches would crash the parent plan on child errors instead of surfacing them as per-entry diagnostics.
13. **The engine now calls `invalidate_cache` explicitly on hash-mismatch** (in `_execute_node` after `plan_node` returns a miss for a previously-completed node with a different hash). The pure `in_process_cache_lookup` no longer invalidates — the engine owns that invariant now, the planner doesn't need it (planner starts with fresh `completed_nodes`).
14. **`only_node` is validated at the top-level `build_plan` entry only** (not on recursion) — mirrors engine behavior and avoids rejecting a top-level target that happens to match a sub-workflow node id.
