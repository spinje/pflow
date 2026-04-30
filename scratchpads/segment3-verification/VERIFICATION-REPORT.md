# Segment 3 Adversarial Verification Report (2026-04-30)

**Scope**: rendering (C1.2) + prewarm (D.1/D.2) + trace 2.1.0 (E.1) — all surfaces shipped in Segment 3.

**Methodology**: 10 adversarial `.pflow.md` workflows exercised through real `pflow` CLI. Anthropic Haiku 4.5 used for cheap LLM calls (~$0.005 total). Every assertion verified against actual trace JSON, not unit-test mocks.

**Test suite state going in**: 5709 passed, 9 skipped — green.

**Two critical Segment-3 bugs found that the test suite missed.**

---

## BUG #1 (HIGH) — `cache_source` mislabeled `in_process` for cross-process memo HITs

### Symptom

Every cross-process memo HIT trace records `cache_source: "in_process"` with a `cache_age_sec` value far exceeding any single workflow execution.

### Reproductions

**A3 second run** (cross-process, same file):
```
cache_source : in_process
cache_age_sec : 6.230397939682007  ← 6.2s gap between two pflow run invocations
```

**a4-saved-test** (cross-process, after save):
```
cache_source : in_process
cache_age_sec : 587.7047679424286  ← ~10 minutes; mathematically impossible for true in_process
```

### Root cause

`runtime/engine/engine.py:420–442`:

```python
if plan.status in ("cached_memo", "cached_in_process"):
    if plan.status == "cached_memo" and ...:
        apply_memo_hit(...)        # Sets cache_source="memo"
    return str(
        handle_cached_execution(...)  # ALWAYS called, sets cache_source="in_process"
    )
```

`handle_cached_execution` runs unconditionally for both memo + in-process plans. At `instrumentation.py:667`, it calls:

```python
_augment_llm_usage_with_cache_metadata(shared, node_id, cache_source="in_process", ...)
```

The augment helper at line 330–331 has the wrong guard:

```python
if cache_source is not None:
    llm_usage["cache_source"] = cache_source
```

The guard rejects `None` but accepts any non-None value. So the `"in_process"` literal **overwrites** the `"memo"` value `apply_memo_hit` just wrote.

`cache_key` and `cache_age_sec` survive because their guards (`if cache_key is not None: ...` and `if cache_age_sec is not None: ...`) — and `handle_cached_execution` passes `None` for both — happen to be no-ops in this case.

### Impact

Per DD#22: `cache_source: "memo" | "in_process"` distinguishes the two pflow cache layers. Defeated. `analyze-cache --from-trace` (Segment 4) cannot tell whether a cache HIT was cross-process (memo) or intra-run (in-process loop revisit). The whole forensic value of the field is gone.

### Why tests didn't catch it

`test_apply_memo_hit_with_cache_metadata_set_for_llm_node` and similar unit tests test `apply_memo_hit` and `handle_cached_execution` **independently**, not in the production sequence where one immediately follows the other.

### Fix options

1. (preferred) Pass `cache_source` parameter to `handle_cached_execution` based on `plan.status`. Skip the augment for `cached_memo` since `apply_memo_hit` already handled it.
2. Guard the augment in `handle_cached_execution` with `if "cache_source" not in llm_usage: ...`.
3. Move the `in_process` augment inside an `else` branch in engine.py:420 so it doesn't run on the memo path.

---

## BUG #2 (CRITICAL) — Cache rendering silently drops every dotted-path chunk

### Symptom

Any cache chunk referencing an upstream node output (`${node.field}`) is silently filtered as ABSENT in the rendered system_blocks. The LLM gets a cache prefix missing the most important content. Hash-vs-prep byte-identity (DD#19 — the load-bearing invariant) is broken.

### Reproductions

**A5c** — control workflow, single shell node feeding LLM via `${path_a.stdout}`:
```
cache_chunks_skipped : ['path_a.stdout']
cache_creation_input_tokens : 0  ← no cache markers fired
input_tokens : 17                ← only `topic` (single-root) was rendered
```

**A6** — realistic pattern (matches the lyrics-generator motivation):
```
prompt_cache: [topic, analyst.response]
→ cache_chunks_skipped: ['analyst.response']
→ LLM responded literally: "There are no analyst notes provided in your prompt
   to summarize—only a preamble with filler text..."
```

The LLM was asked to summarize the analyst's notes. The notes were declared cacheable. They never reached the LLM.

### Root cause

`LLMNode.prep` receives `shared` as `NamespacedSharedStore` (engine.py:471, when `config.namespaced=True`). `plan_node._render_cache_for_hash` receives the raw `dict` (engine.py:415, before the wrap).

Direct reproduction:

```python
shared_dict = {"path_a": {"stdout": "Path A specialty content"}, "topic": "hello", "emit": {}}
chunk = CacheChunkIR(name="path_a.stdout", var_expr="path_a.stdout", prose_before="X:\n", source_line=1)

_resolve_chunk_value(chunk, shared_dict)
# → 'Path A specialty content'  ← HASH side
_resolve_chunk_value(chunk, NamespacedSharedStore(shared_dict, "emit"))
# → _CHUNK_ABSENT                ← PREP side
```

Mechanism inside `_resolve_chunk_value`:

1. `extract_root_node_id("path_a.stdout")` → `"path_a"`
2. `get_node_status(shared, "path_a")` → `SUCCEEDED` (NamespacedSharedStore's `__contains__` works for top-level keys)
3. `TemplateResolver.resolve_template("${path_a.stdout}", NamespacedSharedStore)` → echoes the literal `"${path_a.stdout}"` because:
   - `variable_exists("path_a.stdout", NamespacedSharedStore)` calls `_traverse_path_part`
   - `_traverse_path_part` calls `_get_dict_value(NamespacedSharedStore, "path_a")`
   - `_get_dict_value` checks `isinstance(value, dict) and key in value` → `False` because NamespacedSharedStore is not a dict subclass
   - Returns `(False, None)` → variable_exists returns False → resolve_template returns the unchanged template
4. The permissive-echo branch in `_resolve_chunk_value` fires: `if isinstance(resolved, str) and resolved == template: return _CHUNK_ABSENT`

Same root cause hits `_resolve_static_prefix_for_cache` (D.1 prewarm + auto-batch path):

```
HASH side: 'Context:\nhello\n\nUpstream output:\nPath A specialty content\n\nQuery: ${item.q}'
PREP side: 'Context:\nhello\n\nUpstream output:\n${path_a.stdout}\n\nQuery: ${item.q}'
```

Prewarm batches with dotted-path refs in the prefix have a static prefix containing literal `${var}` placeholders — cache_control marker is placed but on uncacheable content.

### Impact

This is the **load-bearing DD#19 silent stale-cache regression class** the entire B3 phase was built to prevent. The `golden_config_hashes.json` regression gate only covers workflows WITHOUT `prompt_cache:`, so any workflow WITH `prompt_cache:` and dotted-path chunks falls in the gap.

Concrete consequences:

- **The motivating use case is non-functional.** The lyrics-generator workflow (~252 LLM calls, the entire reason this task exists) uses `${concept}`, `${concept_brief}`, `${creative-direction.response}`, `${song-architecture.response}`, `${chorus-chooser.winning_chorus}` — almost all dotted paths. **Every one of these would silently filter.** No cache savings, no token reduction, full retail cost on every call.
- **Author intent is silently violated.** Author writes `prompt_cache: [concept, creative-direction.response]` expecting both to cache. Only `concept` (single-root) ever reaches the LLM. The dotted-path chunk is dropped. No warning, no error, no log.
- **Hash-vs-prep asymmetry stores cached outputs under wrong hash.** Hash side includes the dotted-path resolved value; prep side drops it. Across runs with the same inputs, hash is stable and memo HIT works — BUT the cached output was generated under a smaller prompt than the hash represents.
- **Anthropic cache markers don't fire.** With realistic cache content stripped, the remaining single-root chunks fall below the 4096-token Haiku threshold, and `cache_creation_input_tokens` / `cache_read_input_tokens` stay at 0.

### Why tests didn't catch it

`tests/test_nodes/test_llm/test_prompt_cache_rendering.py::test_hash_render_and_prep_render_byte_equivalent_for_same_subset` (line 486–528):

1. Uses **single-root chunks only**: `shared = {"a": "alpha", "b": {"k": "v"}, "c": [1, 2]}`, chunks reference `${a}`, `${b}`, `${c}`. Bug never triggers because top-level `__contains__` works for both raw dict and NamespacedSharedStore.
2. Calls `node.run(shared)` directly with a raw `dict` (line 524). Bypasses the `NamespacedSharedStore(shared, node_id)` wrap that engine.py:471 applies in production.

The test passes by encoding the wrong fixture shape — exactly the test-fidelity blind spot the verification specialist mode is supposed to catch.

`test_hash_render_and_prep_render_byte_equivalent_with_absent_chunks` (line 531) has the same blind spot.

### Fix options

(In rough order of complexity, pick one)

1. **Unwrap the NamespacedSharedStore at the cache-rendering boundary.** In `LLMNode.prep`, if `shared` is a `NamespacedSharedStore`, pass `shared._parent` to `_assemble_cache_prep`. Keeps the helper signatures unchanged. Risk: touching `_parent` is a private-attribute access; consider exposing a `parent_dict` property.
2. **Make `_resolve_chunk_value` and `_resolve_static_prefix_for_cache` resolver-store-aware.** Detect `NamespacedSharedStore` and use `.get()` traversal instead of `TemplateResolver.resolve_template`. Larger blast radius (touches the helpers' contract).
3. **Fix `TemplateResolver._get_dict_value` to accept dict-like proxies.** Replace `isinstance(value, dict)` with a broader check (e.g., `hasattr(value, 'keys') and hasattr(value, '__getitem__')`). Fixes the broader template-resolution path; potentially touches behavior outside the cache rendering surface — needs a wider regression sweep.
4. **Make `NamespacedSharedStore` a `dict` subclass.** Most invasive; `__contains__`/`__getitem__` semantics differ from raw dict (namespace-aware), so existing dict consumers might behave differently.

### Recommended minimum regression test

Once the fix lands, add to `test_prompt_cache_rendering.py`:

```python
def test_hash_render_and_prep_render_byte_equivalent_for_dotted_path_via_namespaced_store():
    """Repro for the bug: dotted-path chunks must resolve identically through
    raw dict (hash side) AND NamespacedSharedStore (prep side).

    The historical test used single-root chunks only and passed `shared` as a
    raw dict to `node.run`, bypassing the NamespacedSharedStore wrap engine
    applies in production. This test covers the production execution shape."""
    from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

    shared = {"path_a": {"stdout": "Path A content"}, "topic": "hello", "emit": {}}
    cache_ctx = _ctx(
        chunks=[("topic", "T:\n"), ("path_a.stdout", "P:\n")],
        subset=("topic", "path_a.stdout"),
    )
    _install_cache_render(shared, "emit", cache_ctx)

    config = NodeConfig(node_id="emit", node_type_name="LLMNode", ...,
                        prompt_cache_items=("topic", "path_a.stdout"))
    hash_rendered = _render_cache_for_hash(config, shared)
    hash_texts = [h["prose"] + h["value"] for h in hash_rendered]

    # Run prep with the production-shape NamespacedSharedStore wrap
    store = NamespacedSharedStore(shared, "emit")
    node = _make_node("emit")
    node.run(store)
    sent = mock_llm_client.call_history_full[-1]["system"]
    prep_texts = [b["text"] for b in sent]

    assert hash_texts == prep_texts  # FAILS today; must pass after fix
```

---

## Other surfaces verified (no bugs found)

| Surface | Result |
|---|---|
| `format_version: "2.1.0"` bump | ✓ Confirmed in 7 traces |
| Top-level `workflow_path` (file path) | ✓ Confirmed |
| `cache_key` on cache-write events | ✓ Confirmed |
| `cache_chunks_skipped: []` on success path | ✓ Confirmed (but reports incorrect skips due to Bug #2) |
| Hash includes prose-before bytes | ✓ A4 em-dash → hyphen → memo MISS confirms |
| `## Cache` survives `pflow save` round-trip | ✓ Byte-for-byte preserved |
| `pflow visualize` on cache workflow | ✓ Cache invisible to mermaid (correct) |
| `pflow --validate-only --output-format json` | ✓ Clean structured output |
| `pflow --dry-run --output-format json` | ✓ Clean (cache analyzer is Segment 4) |
| `pflow --no-cache` flag | ✓ Bypasses memo, re-runs LLM |
| Sub-workflow with own `## Cache` | ✓ Embedded as sub_workflow_events; isolation OK |
| `prompt_cache: []` (empty list) | ✓ No cache markers fire (correct) |
| Single-root chunks via `${var}` | ✓ Render correctly through both raw dict and NamespacedSharedStore |
| `cache.unused-chunk` warning | ✓ Fires when no node opts in |
| Test suite green | ✓ 5709 passed |
| `test_plan_drift.py` | ✓ 34/34 passed |
| `test_golden_baseline_hashes_match` | ✓ DD#19 gate passes for non-cache workflows |

---

## Surfaces NOT exercised (deferred — would need more API budget or are scoped to Segment 4)

- **Anthropic `ttl: 1h` cost normalization** — would need a workflow with single-root chunks crossing 4096 tokens; doable but adds API cost; the unit tests use `MagicMock` for `usage_obj` and the integration tests are mock-based.
- **Prewarm + batch real behavior with multiple items** — would use multiple Haiku calls; the bug in `_resolve_static_prefix_for_cache` already makes the realistic prewarm pattern non-functional.
- **OpenAI `prompt_cache_key` / `prompt_cache_retention`** — Anthropic was sufficient to surface the rendering bug; OpenAI rendering uses the same broken helper.
- **Gemini TTL translation** — same.

---

## Bottom line

**Segment 3 is NOT ready to merge as-is.** The cache-rendering feature is non-functional for the motivating use case (any cache chunk referencing an upstream node output). The DD#19 hash-vs-prep byte-identity invariant is broken in production despite the regression gate claiming it holds.

Both bugs are in shipped code (Segment 3 was committed as `1be206c3`). Both are silent: no error, no warning, no log. Both have unit tests that pass with synthetic fixtures that don't match production execution shape.

**Recommendation**: Fix Bug #2 (the cache-rendering regression) BEFORE proceeding to Segment 4. F2's analyzer (Segment 4) needs Tier 1 cache rendering to actually work; otherwise its "predicted cache_key" computation will compound the asymmetry. Bug #1 is lower priority (cosmetic field labeling) but trivial to fix in the same PR.

After fixing, re-run A4–A6 and confirm:
- A4 second run: `cache_source: "memo"` (not `"in_process"`)
- A6 second run: `cache_chunks_skipped: []`, `cache_creation_input_tokens > 0` on first run, `cache_read_input_tokens > 0` on second run, LLM responds with the analyst notes summary (not the "no notes" complaint).
