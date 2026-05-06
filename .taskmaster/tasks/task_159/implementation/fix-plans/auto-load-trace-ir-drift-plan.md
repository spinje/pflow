# Plan — Drift-Aware Auto-Load for `analyze-cache` (Stage 2 Finding #8)

## Context

`pflow analyze-cache <workflow.pflow.md>` (no `--from-trace`) auto-loads the most recent matching trace from `~/.pflow/debug/`. Today it gates only on `format_version.startswith("2.")` and a hash-collision-guard `workflow_path` equality check (`analyze.py:700-702`). There is **no IR-vs-trace context check**. When the workflow file has been edited since the trace was recorded — model swap, node rename, prompt_cache change — the trace's data is silently mixed with the current IR's predictions, producing four classes of misleading output:

1. **Spurious `cache.discrepancy` diagnostics**: `_emit_discrepancy_diagnostics` predicts cache_keys against current IR and compares to trace's actual fields. Mismatched IR → `key_mismatch` or `unknown` attribution with messages like `"Cannot attribute discrepancy to known causes (predicted=0%, actual=100%); inspect trace events for {node_id}"`. The agent thinks they have a real bug.
2. **Stale per_call rows**: `_build_trace_execution_index` emits trace's recorded `cache_creation_input_tokens` / `cache_read_input_tokens` for nodes whose model has changed.
3. **Misleading "actually paid" headline**: `compute_actually_paid` aggregates trace costs as the headline — technically true for the recorded run, but presented as the current workflow's cost.
4. **Wrong recommended actions**: derived from per_call + IR mix.

Stage 2 reproducer: switched default `gemini` → `anthropic/claude-haiku-4-5`, ran `analyze-cache`. Auto-loaded a Gemini trace; surfaced cascading spurious findings on the workflow's LLM nodes.

The user's iteration flow IS model-switching (lyrics-generator project tests on multiple providers in sequence). Auto-load misfires every switch.

### Goal

Detect "trace context disagrees with current IR context" at auto-load time and silently skip — agent gets clean greenfield analysis. Explicit `--from-trace <path>` remains the documented escape hatch (proceeds without check).

### Why no info note (decided with user)

When an agent edits a `.pflow.md` and runs `analyze-cache`, silent reset to greenfield is the natural mental model. Mirrors existing convention in `_autoload_trace` (silently returns `(None, None)` on every other miss). Avoids noise in the common case. If the agent wants the prior trace they pass `--from-trace`.

### Why Option A+ over fingerprinting

Considered an `ir_fingerprint` field stored on the trace (cargo / bazel / git pattern). Drawbacks for this codebase:
- Producer-side IR threading (`WorkflowTraceCollector` doesn't receive IR today).
- Trace format bump 2.2 → 2.3 with all the consumer-gate ceremony.
- "What goes in the hash" is a permanent contract once shipped.
- Sub-workflow handling forces `cw_result`-equivalent threading in the trace producer.
- Test debugging asserts `{models}` vs hash equality.

Top-10% reasoning for THIS scale: pflow has ONE caching decision (auto-load), not hundreds. Contract surface cost outweighs elegance benefit at this scale. A senior engineer ships explicit-field comparison for a small CLI tool with one caching decision and a small bounded IR field set.

### Brownfield-compatible by construction

The data the comparison needs has lived in trace 2.0+ from day one — per-event `node_id` and `event["llm_call"]["model"]` — and is the same source-of-truth the rest of the analyzer reads. **No producer change. No format bump. ALL existing 2.x traces benefit immediately.** This is decisive.

---

## Architecture

### Comparison shape — single walk, two axes, root-only

Walk the trace once via `TraceTree.iter_llm_leaves(descend_sub_workflows=False, descend_cached_subtrees=False)` to extract `(node_id, model)` pairs from root-only events. Compare against the parent IR's LLM-node set. Root-only is correct: `analyze()` only has the parent IR at line 450 (sub-workflow IRs are materialized later by `walk_cross_workflow` at line 455). Sub-workflow drift goes silently undetected — that's OK because each sub-workflow has its own `.pflow.md` and `analyze-cache <child.pflow.md>` independently catches it.

```python
def _trace_aligns_with_ir(
    trace_data: Mapping[str, Any], workflow_ir: Mapping[str, Any]
) -> bool:
    """True iff trace's recorded ROOT LLM context matches current IR's.

    Compared:
      * ROOT-level LLM node_ids (set equality — rename/add/remove drift).
      * IR static models ⊆ trace models (subset; accommodates root-level
        heterogeneous batches whose ${item.model} resolves to N runtime values).

    Returns True when trace had no root LLM activity (legacy or LLM-free
    trace — nothing to compare). Cached events are excluded because they
    didn't actually run.
    """
    trace_node_ids, trace_models = _collect_root_trace_llm_context(trace_data)
    if not trace_node_ids:
        return True  # nothing meaningful to compare

    ir_node_ids = _collect_ir_llm_node_ids(workflow_ir)
    if trace_node_ids != ir_node_ids:
        return False  # root-level rename / add / remove drift

    ir_models = _collect_ir_static_llm_models(workflow_ir)
    if ir_models and not (ir_models <= trace_models):
        return False  # IR declares a model the trace didn't use → drift

    return True
```

**Why subset on models** — root-level heterogeneous batch nodes (`model: ${item.model}`) resolve to N runtime models we can't enumerate from IR. Subset semantics tolerate them: trace's models legitimately includes runtime values IR can't predict, AND we still catch the user's actual case (default model swap → new model not in trace).

**Why equality on node_ids** — node renames, additions, removals are unambiguous root-IR drift signals. With `descend_sub_workflows=False`, both sets contain ONLY root-level node_ids, so equality is correct (no sub-workflow descendants leaking into one side).

### Trace-side helper — single walk, batch-aware

```python
def _collect_root_trace_llm_context(
    trace_data: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    """Return (root LLM node_ids, root LLM models). Single TraceTree walk.

    Walks ``descend_sub_workflows=False`` to scope to the root. Excludes
    cached events (descend_cached_subtrees=False). Batch items carry
    ``owner_node_id`` of the parent batch node (no per-item node_id in
    trace shape) — collapse to that owner so a heterogeneous batch with N
    items contributes ONE node_id but N models.
    """
    try:
        tree = TraceTree.from_dict(trace_data)
    except (ValueError, TypeError):
        return set(), set()

    node_ids: set[str] = set()
    models: set[str] = set()
    for leaf in tree.iter_llm_leaves(
        descend_sub_workflows=False,
        descend_cached_subtrees=False,
    ):
        # Batch_items have no own node_id — use the parent batch node's id.
        nid = leaf.owner_node_id if leaf.tier == "batch_item" else leaf.event_node_id
        if nid and nid != "unknown":
            node_ids.add(nid)
        if leaf.llm_call:
            model = leaf.llm_call.get("model")
            if isinstance(model, str) and model:
                models.add(normalize_model_name(model))
    return node_ids, models
```

### IR-side helpers

```python
def _collect_ir_llm_node_ids(workflow_ir: Mapping[str, Any]) -> set[str]:
    """Root LLM node ids declared in the parent IR. Skips nodes without an id.

    Mirrors the canonical iteration pattern at ``analyze.py:1011-1013`` and
    delegates the ``type == "llm"`` predicate to the existing ``_is_llm_node``
    helper at line 2931.
    """
    out: set[str] = set()
    for node in workflow_ir.get("nodes", []) or []:
        if not _is_llm_node(node):
            continue
        nid = node.get("id")
        if isinstance(nid, str) and nid:
            out.add(nid)
    return out


def _collect_ir_static_llm_models(workflow_ir: Mapping[str, Any]) -> set[str]:
    """Models statically resolvable from IR (templated models excluded).

    Templated models (``${item.model}``) contribute nothing — runtime values
    aren't predictable from IR alone. The default-model fallback IS included
    for nodes without an explicit model. Mirrors the resolution pattern at
    ``analyze.py:1088-1095`` so the IR-side set matches what the rest of the
    analyzer treats as "model in scope".
    """
    out: set[str] = set()
    has_unspecified = False
    for node in workflow_ir.get("nodes", []) or []:
        if not _is_llm_node(node):
            continue
        explicit = node.get("params", {}).get("model") or node.get("model")
        if isinstance(explicit, str) and "${" in explicit:
            continue  # heterogeneous; runtime-resolved
        if explicit:
            out.add(normalize_model_name(str(explicit)))
        else:
            has_unspecified = True
    if has_unspecified:
        default = get_default_workflow_model()
        if default:
            out.add(normalize_model_name(default))
    return out
```

### Where the gate lives — Option C (post-`_resolve_trace_data` block in `analyze()`)

`_resolve_trace_data` stays a pure loader (single responsibility — find a trace file). The gate is one block immediately after the call site at `analyze.py:450`. Single-deletable. Reuses every variable already in scope.

```python
trace_data, used_trace_path = _resolve_trace_data(
    trace_path, auto_load_trace, lookup_path, notes
)
# Auto-load only: if the workflow's IR has drifted from the trace's recorded
# LLM context (root node_ids or models), silently skip the auto-loaded trace
# rather than render misleading per_call rows / discrepancy diagnostics.
# Explicit --from-trace bypasses the gate (agents who pass a path opt into
# cross-context comparison).
if trace_path is None and trace_data is not None:
    if not _trace_aligns_with_ir(trace_data, workflow_ir):
        trace_data = None
        used_trace_path = None
```

`_resolve_trace_data` signature stays unchanged. `_autoload_trace` stays unchanged.

---

## Existing primitives reused (no redefinition)

- `_is_llm_node(node)` at `analyze.py:2931` — `isinstance(node, dict) and node.get("type") == "llm"`.
- `get_default_workflow_model()` at `core/llm_config.py` — already imported by `analyze.py:56`.
- `normalize_model_name` at `core/llm_providers.py` — already imported by `analyze.py:57` and used by the heterogeneous-models work. Apply to BOTH sides — comparing normalized vs unnormalized strings produces false-positive drift.
- `TraceTree.from_dict` + `iter_llm_leaves` at `core/trace_tree.py` — same primitive used by `_emit_discrepancy_diagnostics` (`analyze.py:3122`) and `_collect_llm_summary` (`workflow_trace.py:486`). `descend_cached_subtrees=False` mirrors those callers; `descend_sub_workflows=False` is the new option specific to this gate's root-only scope.
- Iteration shape: `workflow_ir.get("nodes", []) or []` mirrors all 7 existing IR-iteration sites in `analyze.py`.

---

## Files to modify

### `src/pflow/core/cache_analysis/analyze.py` (UPDATE)

- Add 3 module-level helpers near `_autoload_trace` (around line 706, between the autoload block and `# Pipeline helpers` comment): `_collect_root_trace_llm_context`, `_collect_ir_llm_node_ids`, `_collect_ir_static_llm_models`, plus the `_trace_aligns_with_ir` predicate.
- Insert the 4-line gate block at line 451 (immediately after the `_resolve_trace_data` call at line 450).

Estimated delta: ~85 LOC.

### `tests/test_core/test_cache_analysis_analyze.py` (UPDATE)

Add tests adjacent to the existing autoload tests at line 794+. Reuse `_write_trace` helper. Reuse `tests/shared/trace_fixture_builder.py`'s `llm_event` (already provides `node_id` and `model`).

Test list:

1. `test_autoload_skips_when_trace_models_differ_from_ir` — trace has `model: "gemini/gemini-2.5-flash"` event, IR resolves to `anthropic/claude-haiku-4-5` → `result.trace_path is None`.
2. `test_autoload_skips_when_root_node_ids_differ_from_ir` — same model, IR renames the LLM node id (e.g., `ask` → `ask-question`) → trace_path None.
3. `test_autoload_skips_when_root_node_added_in_ir` — IR adds a new LLM node not present in trace → trace_path None.
4. `test_autoload_skips_when_root_node_removed_in_ir` — IR removes an LLM node that the trace exercised → trace_path None.
5. `test_autoload_returns_trace_when_models_and_node_ids_match` — sanity load.
6. `test_autoload_proceeds_when_trace_has_no_root_llm_activity` — trace has only shell events / sub-workflow LLM events; no root LLM activity → loads (empty short-circuit).
7. `test_autoload_proceeds_when_ir_has_no_llm_nodes_and_trace_matches` — pure-shell IR + LLM-free trace → loads.
8. `test_autoload_tolerates_root_heterogeneous_batch` — IR has root batch node with `model: ${item.model}` + non-het node; trace records non-het + multiple resolved per-item models → loads (subset semantics; het IR contributes nothing to model side, batch_items collapse to owner_node_id).
9. `test_autoload_includes_default_model_in_ir_set` — IR has bare LLM node (no explicit model); trace records the default model → loads.
10. `test_autoload_skips_when_default_model_changed` — IR has bare LLM node; default model has changed; trace recorded old default → IR static models ⊄ trace models → skip. **The user's exact Stage 2 reproducer.**
11. `test_autoload_normalizes_provider_prefix_variants` — trace records `gemini/gemini-2.5-flash`, IR resolves to `gemini-2.5-flash` (no prefix) → both normalize equal → loads.
12. `test_autoload_excludes_cached_events_from_drift_signal` — trace has both cached and live LLM events; IR matches the LIVE events but not the cached ones (e.g., a renamed node whose old id only appears in cached events) → loads. (Cached events shouldn't contribute to drift signal because they didn't run.)
13. `test_autoload_ignores_sub_workflow_llm_events` — trace has sub-workflow LLM events for a node-id NOT in the parent IR; root events match → loads. Pins the `descend_sub_workflows=False` invariant.
14. `test_explicit_from_trace_bypasses_drift_check` — explicit `--from-trace` with mismatched models loads anyway. Pins escape hatch.
15. `test_autoload_silent_skip_no_notes_appended` — drift skip emits NO entry to `notes`. Pins silent-skip convention.

Estimated delta: ~210 LOC (~14 LOC per test average).

### Mutation safety harness

For tests 1, 2, 8, 10, 12, 13, 14 — verify that reverting the corresponding production change makes the test fail. Pattern: revert one specific check, run focused test, confirm RED, restore, re-run GREEN. This pattern is established in the recent unified-detector and heterogeneous-models work.

### Documentation

- `src/pflow/core/cache_analysis/CLAUDE.md` — Section 1 ("Auto-load") gets one paragraph: "Auto-load silently skips when the trace's root-level LLM `(node_id, model)` context drifts from current IR. Mirrors the existing format-version gate (`startswith("2.")`) — both are silent skips. Explicit `--from-trace` bypasses both gates. Sub-workflow drift is detected by running `analyze-cache <child.pflow.md>` directly."
- `src/pflow/runtime/CLAUDE.md` — `WorkflowTraceCollector` section gets one line: "Per-event `event['node_id']` and `event['llm_call']['model']` are consumed by `cache_analysis._trace_aligns_with_ir` for auto-load drift detection — the existing trace shape suffices, no producer change is needed for this consumer."

Estimated delta: ~12 LOC docs.

**No production changes outside `analyze.py`. No producer-side changes. No format bump. No fixture builder changes.**

---

## Edge cases

| Case | Behavior | Mechanism |
|---|---|---|
| Trace has no root LLM events | Load (no comparison) | `trace_node_ids` empty → `_trace_aligns_with_ir` short-circuits True. |
| IR has no LLM nodes (pure shell/http) | Load IF trace also has no root LLM events; SKIP otherwise | If trace has root LLM events but IR doesn't, that's drift (LLM node was removed). Trace_node_ids non-empty → IR comparison runs. |
| Root heterogeneous batch (`model: ${item.model}`) | IR side excludes templated nodes from models; batch_items in trace collapse to one owner_node_id; subset semantics tolerate runtime models | Captured in test 8. |
| Default model changed (no explicit per-node) | IR's resolved-default added to IR set; trace records old default; IR ⊄ trace → drift | Captured in test 10. |
| Provider-prefix normalization (`gemini/gemini-2.5-flash` vs `gemini-2.5-flash`) | Both sides normalize via `normalize_model_name` | Captured in test 11. |
| Sub-workflow LLM node renamed | `descend_sub_workflows=False` excludes sub-workflow events from comparison; root context unchanged → load | Captured in test 13. The root-only scope decision. |
| Cached events (memo hits, in-process hits) | Excluded via `descend_cached_subtrees=False` — they didn't run | Captured in test 12. Mirrors `_collect_llm_summary` convention. |
| Trace from inline workflow (`ir-hash:<md5>` workflow_path) | If IR changes → workflow_path hash changes → different filename glob → no trace found, drift gate inert. If IR unchanged → hash matches, comparison passes. | Defense-in-depth alignment. |
| Empty model string in trace event | Filtered by `if isinstance(model, str) and model:` | Implicit. |
| TraceTree shape error | `_collect_root_trace_llm_context` returns `(set(), set())` on `ValueError`/`TypeError` → empty short-circuit returns True (no skip on malformed trace; preserves existing forgiving behavior) | Defensive parity with `_emit_discrepancy_diagnostics`'s try/except at line 3123-3125. |
| MCP `analyze_cache` tool | Same `analyze()` call → same gate fires automatically. No separate code path. MCP has no override flag (no `--from-trace` analog) — silent skip is the only behavior. Documented at `mcp_server/CLAUDE.md` if needed; currently consistent with all-silent design. | |
| `--dry-run` (`auto_load_trace=False`) | Gate inert (no trace loaded) | Implicit. |

---

## Top-10% sanity check (re-applied)

Re-asked: "what would top 10% codebases of pflow's scale do?"

The plan reuses ALL existing primitives (`_is_llm_node`, `normalize_model_name`, `TraceTree.iter_llm_leaves`, `get_default_workflow_model`, the canonical `nodes` iteration pattern, the resolution pattern at line 1088). The only NEW code is:

- 3 small helpers (~50 LOC) that compose existing primitives.
- 1 predicate (~15 LOC).
- 1 gate block (~5 LOC).

Comparable to: how `_emit_discrepancy_diagnostics` (`analyze.py:3096`) was added — single-purpose function, composes existing primitives, lives next to its caller.

**One simplification considered and rejected**: inlining the predicate at the call site (no `_trace_aligns_with_ir` helper). Rejected because:
- 14 of 15 tests want to drive the predicate directly with synthetic data; inlining forces every test through the full `analyze()` pipeline.
- The helper docstring is the natural place to capture the root-only / subset-semantics / cached-exclusion decisions; inline comments rot.
- Future re-use: if `_load_trace_explicit` ever wants a soft warning, the predicate works as-is.

**One simplification considered and ADOPTED (vs the prior plan draft)**: derive trace context from `iter_llm_leaves` directly instead of reading `trace["llm_summary"]["models_used"]`. Cleaner because:
- Source-of-truth is the events themselves; `models_used` is a producer-side aggregate.
- Single-pass collection: one walk gives both axes (node_ids AND models) instead of two reads.
- Test fixtures don't need `llm_summary` synthesis — `tests/shared/trace_fixture_builder.py:llm_event` already produces the right shape.
- Mirrors how the rest of the analyzer reads trace data.

**Plan top-10%: yes.** Smaller, more SSoT-aligned than fingerprinting at this scale; no contract surface added; no producer change; brownfield-clean.

---

## Verification

### Unit tests
```bash
make test            # full suite (expected delta: +15 tests)
make check           # ruff + ruff-format + mypy + deptry, all clean
```

### End-to-end manual repro

**1. Stage 2 reproducer (model swap)** — the user's actual case.
```bash
# Generate a fresh trace under one model
PFLOW_DEFAULT_MODEL=gemini/gemini-2.5-flash uv run pflow \
  scratchpads/stage2-verification/gemini-smoke/smoke-with-cache.pflow.md

# Switch default; run analyze-cache against same workflow
PFLOW_DEFAULT_MODEL=anthropic/claude-haiku-4-5 uv run pflow analyze-cache \
  scratchpads/stage2-verification/gemini-smoke/smoke-with-cache.pflow.md
```
Expected: zero `cache.discrepancy` findings; per_call rows show estimator/heuristic data only (no trace tier); `actually_paid_usd: null` (or absent); recommended actions reflect current IR analysis only. **Pre-fix**: spurious "Cache hit discrepancy on <node>" diagnostics + stale per_call rows.

**2. Override case** — same setup, but pass `--from-trace`.
```bash
uv run pflow analyze-cache \
  scratchpads/.../smoke-with-cache.pflow.md \
  --from-trace ~/.pflow/debug/<old-trace>.json
```
Expected: trace loads (override respected); discrepancy findings may surface (agent explicitly chose to compare across IR contexts).

**3. Sanity case (unchanged IR)** — same model, fresh run, immediate analyze-cache.
```bash
uv run pflow scratchpads/.../smoke-with-cache.pflow.md
uv run pflow analyze-cache scratchpads/.../smoke-with-cache.pflow.md
```
Expected: trace auto-loads as before; no behavior regression; per_call rows include trace data; discrepancy fires only on real mismatches.

**4. Heterogeneous batch (lyrics-generator chorus-chooser)** — `chorus-chooser.pflow.md` uses `model: ${item.model}` for the score-choruses node. Sanity:
```bash
uv run pflow analyze-cache /Users/andfal/projects/music-generation/workflows/lyrics-generator/chorus-chooser/chorus-chooser.pflow.md
```
Expected: drift gate doesn't reject the trace just because trace's models include multiple Gemini variants from the het batch (subset semantics + IR-side het exclusion).

### Mutation safety

Revert each of the following and re-run focused tests; each test must FAIL:

| Test | Revert |
|---|---|
| 1 | Drop the model subset check in `_trace_aligns_with_ir` |
| 2, 3, 4 | Drop the node-id equality check |
| 8 | Drop the `"${" in explicit` skip in `_collect_ir_static_llm_models` |
| 10 | Drop the default-model addition in `_collect_ir_static_llm_models` |
| 11 | Drop `normalize_model_name` on either side |
| 12 | Replace `descend_cached_subtrees=False` with `True` |
| 13 | Replace `descend_sub_workflows=False` with `True` |
| 14 | Drop the `trace_path is None and` guard in the gate block |

Restore; all tests pass.

---

## Critical implementation notes for the executor

1. **No producer-side change.** `WorkflowTraceCollector` stays untouched. No format bump. If the diff includes any file outside `analyze.py`, `tests/test_core/test_cache_analysis_analyze.py`, and the two CLAUDE.md docs, that's scope creep — flag.

2. **Reuse `_is_llm_node`** at `analyze.py:2931`. Do not redefine.

3. **Reuse `normalize_model_name`** on BOTH sides — comparing normalized vs unnormalized strings produces false-positive drift. Already imported at `analyze.py:57`.

4. **Use `descend_sub_workflows=False`** AND **`descend_cached_subtrees=False`** on `iter_llm_leaves`. Both are load-bearing:
   - `descend_sub_workflows=False` keeps comparison root-only — sub-workflow IRs aren't loaded yet at line 450, so any sub-workflow event would always trigger drift.
   - `descend_cached_subtrees=False` excludes cached events that didn't actually run — they shouldn't contribute to drift signal. Matches `_collect_llm_summary`'s convention.

5. **Batch items have no own node_id.** When `leaf.tier == "batch_item"`, use `leaf.owner_node_id` (the parent batch node's id). Otherwise `leaf.event_node_id`. Otherwise the trace-side set fills with `"unknown"` strings and skip-equality-check fails.

6. **Subset semantics on models, equality on node_ids** — explicit:
   - `ir_models <= trace_models` (subset) — root het batches add models to trace that IR can't enumerate.
   - `trace_node_ids == ir_node_ids` (equality) — both sets are root-only via `descend_sub_workflows=False`, so equality is correct.

7. **`workflow_ir.get("nodes", []) or []`** is the canonical iteration shape. Do NOT use `["steps"]` (markdown-AST shape, not IR shape).

8. **Silent skip — no `notes` entry**. The skip is deliberately silent (decision with user). Do not append to `notes`. Mirrors the existing convention in `_autoload_trace`.

9. **Gate placement is post-`_resolve_trace_data`** in `analyze()` body, NOT inside `_resolve_trace_data` (which stays a pure loader). The gate uses `if trace_path is None and trace_data is not None:` so explicit `--from-trace` bypasses it (escape hatch).

10. **TraceTree shape errors are forgiving**. Wrap `TraceTree.from_dict` in `try/except (ValueError, TypeError)` returning `(set(), set())` on failure — same defensive pattern as `_emit_discrepancy_diagnostics:3123-3125`. A malformed trace shouldn't crash the analyzer; the empty short-circuit makes it pass through (load), which mirrors current behavior on malformed traces.

11. **Pre-merge sanity**: `git diff --stat` should show only the 3 files in "Files to modify" (analyze.py, test_cache_analysis_analyze.py, two CLAUDE.md). Anything else is unintended scope.

12. **Brownfield is the path**: every existing test that doesn't add LLM events to its synthetic trace will continue to pass without modification — the empty-set short-circuit handles them. Audit existing autoload tests once for this; the `workflow_ir = {"nodes": []}` + LLM-free trace pattern they use is fully compatible.

13. **`normalize_model_name` is in `core/llm_providers.py`**. The import in `analyze.py:57` is `from pflow.core.llm_providers import detect_provider, normalize_model_name`.
