# Plan — Unified `cache.below-min-predicted` Detector + Runtime Surface + Phantom-Savings Fix

## Context

This work closes four related gaps surfaced in Stage 2 verification of pflow's prompt caching feature (Task 159):

**Finding #9 — discoverability gap.** `cache.below-min-predicted` fires only from `analyze-cache`. Agents who run `pflow run --validate-only` see "Workflow is valid" even when their `prompt_cache:` decoration won't fire because rendered cache content is below the model's threshold. Stage 2 evidence: RUN-HAIKU-RERUN's `generate-suno-prompt` had 3,764 tokens against Haiku's 4,096 minimum — wasted cache decoration, zero signal.

**Finding #10 — misleading message text.** Current warning says "cache_control markers will silently no-op at the provider", which is accurate for Anthropic but misleading for Gemini (whose implicit cache may still fire on stable prefixes regardless of `cache_control` markers).

**Phantom savings (correctness bug).** Three code paths in the analyzer compute non-zero `estimated_savings_usd` for caches that won't fire because totals are below threshold:
- Greenfield: `_savings_for_shared_ref` (`analyze.py:2320`)
- Brownfield: `_single_call_write_penalty` (`analyze.py:2147`)
- Brownfield: `_compute_model_group_costs` (`analyze.py:2084`)

These phantom values flow into `RecommendedAction.estimated_savings_usd` (`view_helpers.py:146`) and contaminate action-priority ranking — sub-threshold suggestions can rank ABOVE valid above-threshold suggestions, misleading agents.

**Suggested-block threshold awareness gap.** Greenfield `SuggestedBlock` rendering shows no per-node threshold info. Each LLM node selects a SUBSET via `prompt_cache:`; different nodes can use different models with different thresholds. Today the agent must mentally compute "does my subset clear my model's threshold."

### Goal

Close all four gaps with a unified detector pattern. **Single source of truth, multiple drivers (analyzer + runtime), one catalog ID, one render path.** Optimized for AI agents reading the code: each concern has one obvious place; new detection contexts plug in by adding evidence fields, not by forking the catalog.

### Architectural decisions (set in stone)

- **Post-call detection** for runtime, NOT pre-call. DD#36 forbids tokenizers in the runtime hot path. Post-call uses provider-reported `cache_creation_input_tokens` / `cache_read_input_tokens` — ground truth, zero new hot-path logic.
- **One catalog ID** (`cache.below-min-predicted`) used by both drivers with `evidence_kind` context dispatch. NOT two separate IDs.
- **Per-node threshold checks**, not per-block. Each node uses different subsets and possibly different models.
- **Channel extension via `normalize_runtime_warning`**: extend the seam to accept `Diagnostic` instances directly. ONE warning vocabulary.
- **Cache-miss vs empty-response collision: empty-response wins via existing emission order.** Documented at the emit site. Cache-miss is observational; empty-response is a critical failure signal. Acceptable v1 trade-off — agents who hit empty-response will likely investigate via `analyze-cache --from-trace` which independently fires the predicted-tier warning.

### Out of scope (filed as follow-ups)

- **Near-threshold expansion hints** (~80 LOC). Threshold rendering already tells agents WHERE they stand.
- **Cross-node-id sub-workflow scoping for runtime warnings.** `__warnings__` shares dict reference with no node_id qualification — siblings collide. Existing limitation, not specific to this work.
- **Live stderr emission during the run.** Cache-miss surfaces post-run via `--report` and trace JSON.
- **List-shaped `__warnings__[node_id]`.** Last-write-wins via setdefault is acceptable for v1.

---

## Architecture

### New module: unified detector

Path: `src/pflow/core/cache_analysis/below_min_tokens_detector.py` (NEW)

Single source of truth for the rule. Both drivers call it; only the evidence supplied differs.

**Critical**: imports ONLY stdlib + `pflow.core.llm_capabilities` + `pflow.core.llm_providers`. MUST NOT import from `cache_analysis.token_estimation`, `cache_analysis.analyze`, or any runtime/execution/nodes module. This keeps it safe to import from `nodes/llm/llm.py` without pulling heavyweight dependencies.

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from pflow.core.llm_capabilities import get_min_cache_tokens
from pflow.core.llm_providers import detect_provider


@dataclass(frozen=True)
class BelowMinTokensEvidence:
    """Inputs the detector needs. Each driver fills what it has.

    Analyzer drivers fill ``estimated_tokens`` + ``estimated_data_source``.
    Runtime drivers fill ``has_observed=True`` plus ``observed_creation_tokens``
    + ``observed_read_tokens``.

    The explicit ``has_observed`` flag is load-bearing: pflow's runtime
    coerces missing observation values to 0 (via ``_safe_int`` in
    ``llm_client.py``), so analyzer callers passing ``observed_*=0`` must
    NOT accidentally enter the observed-tier branch. Drivers MUST set
    ``has_observed=True`` to opt into observed-tier detection.
    """
    node_id: str
    model: str
    declared_prompt_cache: list[str]
    # Analyzer-driver fills (predicted tier):
    estimated_tokens: int | None = None
    estimated_data_source: str | None = None  # "trace", "memo", "parameters", "estimator"
    # Runtime-driver fills (observed tier):
    has_observed: bool = False  # True iff caller has actual provider telemetry
    observed_creation_tokens: int = 0
    observed_read_tokens: int = 0


@dataclass(frozen=True)
class BelowMinTokensFinding:
    """Output of the detector. One shape, regardless of driver."""
    node_id: str
    model: str
    min_tokens: int
    evidence_kind: Literal["predicted", "observed"]
    cacheable_tokens: int  # estimated value (predicted) or 0 (observed-fired)
    provider_note: str  # provider-aware suffix; may be empty for unknown providers


def detect(evidence: BelowMinTokensEvidence) -> BelowMinTokensFinding | None:
    """Single source of truth for the below-threshold rule.

    Returns None when:
      - no ``prompt_cache:`` declared
      - model is empty (heterogeneous batch, or unknown — defensive skip)
      - observed tier shows cache fired (creation+read > 0)
      - predicted tier has no estimate, or trace ground-truth says cache works
      - estimated count meets the threshold
    """
    if not evidence.declared_prompt_cache or not evidence.model:
        return None
    threshold = get_min_cache_tokens(evidence.model)
    provider_note = _provider_note(evidence.model)

    # Tier 1: ground truth (post-call observed). Wins when present.
    if evidence.has_observed:
        observed_total = evidence.observed_creation_tokens + evidence.observed_read_tokens
        if observed_total > 0:
            return None  # cache demonstrably fired
        return BelowMinTokensFinding(
            node_id=evidence.node_id,
            model=evidence.model,
            min_tokens=threshold,
            evidence_kind="observed",
            cacheable_tokens=0,
            provider_note=provider_note,
        )

    # Tier 2: predicted (analyzer estimate)
    if evidence.estimated_tokens is None or evidence.estimated_tokens <= 0:
        return None
    if evidence.estimated_data_source == "trace":
        return None  # don't contradict trace evidence
    if evidence.estimated_tokens >= threshold:
        return None
    return BelowMinTokensFinding(
        node_id=evidence.node_id,
        model=evidence.model,
        min_tokens=threshold,
        evidence_kind="predicted",
        cacheable_tokens=evidence.estimated_tokens,
        provider_note=provider_note,
    )


def _provider_note(model: str) -> str:
    """Provider-aware suffix for the message template (Finding #10)."""
    provider = detect_provider(model)
    if provider is None:
        return ""
    name = provider.name
    if name == "anthropic":
        return "cache_control markers will silently no-op at the provider"
    if name == "gemini":
        return ("explicit `cachedContents` won't fire, but Gemini's automatic "
                "implicit cache may still apply for stable prefixes")
    # OpenAI: redundant with the main message ("below {model}'s minimum"
    # already conveys it). Return empty so message ends cleanly.
    return ""
```

### Catalog: one entry, evidence-aware dispatch

Path: `src/pflow/core/cache_analysis/warning_catalog.py:358-380` (UPDATE)

The dispatch precedent to follow is **`cache.shared-context-undeclared`** at `make_diagnostic` lines 1039-1071, which dispatches `selected_message_template` based on context keys. This is the correct precedent for **message-template** dispatch. (The plan previously cited `cache.discrepancy`, which dispatches only `suggestions_template` — wrong precedent.)

Update catalog row:
```python
"cache.below-min-predicted": CacheWarningSpec(
    severity=Severity.WARNING,
    source="cache_analyzer",  # logical source; both drivers emit through the catalog
    category=CACHE_WARNING_CATEGORY,
    # Empty template: dispatch in make_diagnostic by evidence_kind context key.
    # Mirrors cache.shared-context-undeclared (lines 1039-1071) but for the
    # message_template field instead of suggestions_template.
    message_template="",
    required_context_keys=(
        ("node_id", str),
        ("model", str),
        ("min_tokens", int),
        ("evidence_kind", str),       # "predicted" or "observed"
        ("cacheable_tokens", int),    # 0 when observed
        ("provider_note", str),       # may be empty for unknown providers
    ),
    suggestions_template=(
        "Increase cache content above {min_tokens} tokens by adding more chunks "
        "to ## Cache, OR remove `prompt_cache:` from {node_id} since the cache "
        "won't fire as declared.",
    ),
    path_template="nodes[id={node_id}].prompt_cache",
    headline_template="Cache content below provider minimum on {node_id}",
),
```

Add module-level template constants near the existing `_SHARED_CONTEXT_*` constants:
```python
# Message-template dispatch for cache.below-min-predicted.
# Selected by evidence_kind context key. "unknown" is the defensive fallback
# for forward-compat with future evidence tiers.
_BELOW_MIN_TOKENS_MESSAGE_PREDICTED = (
    "{node_id}: declared cache content is ~{cacheable_tokens} tokens, "
    "below {model}'s minimum of {min_tokens}{provider_clause}"
)
_BELOW_MIN_TOKENS_MESSAGE_OBSERVED = (
    "{node_id}: declared cache did not fire on this call (provider reported "
    "0 cache_creation + 0 cache_read tokens) — likely because rendered content "
    "is below {model}'s minimum of {min_tokens}{provider_clause}"
)
_BELOW_MIN_TOKENS_MESSAGE_UNKNOWN = (
    "{node_id}: declared cache below {model}'s minimum of {min_tokens}{provider_clause}"
)

_BELOW_MIN_TOKENS_DISPATCH = {
    "predicted": _BELOW_MIN_TOKENS_MESSAGE_PREDICTED,
    "observed": _BELOW_MIN_TOKENS_MESSAGE_OBSERVED,
}
```

In `make_diagnostic` (or wherever the existing `cache.shared-context-undeclared` dispatch lives), add the dispatch logic AFTER `_validate_required` succeeds:
```python
if warning_id == "cache.below-min-predicted":
    evidence_kind = context_kwargs["evidence_kind"]
    template = _BELOW_MIN_TOKENS_DISPATCH.get(evidence_kind)
    if template is None:
        logger.warning(
            "cache.below-min-predicted: unknown evidence_kind=%r; falling back to "
            "generic template",
            evidence_kind,
        )
        template = _BELOW_MIN_TOKENS_MESSAGE_UNKNOWN
    # provider_clause derives from provider_note: ensures clean output for
    # unknown providers (no trailing "; ").
    provider_clause = (
        f"; {context_kwargs['provider_note']}"
        if context_kwargs["provider_note"]
        else ""
    )
    selected_message_template = template
    selected_format_kwargs = {**context_kwargs, "provider_clause": provider_clause}
```

The `{provider_clause}` pattern (vs inline trimming) mirrors `_format_savings_clause` at `warning_catalog.py:846` — established convention in this catalog.

### Analyzer emit site (REFACTOR)

Path: `src/pflow/core/cache_analysis/analyze.py:1408-1435` (in `_per_node_warnings`) (UPDATE)

Replace the inline check with a detector call:
```python
from pflow.core.cache_analysis.below_min_tokens_detector import (
    BelowMinTokensEvidence,
    detect as detect_below_min_tokens,
)

# Inside _per_node_warnings, replace the existing inline check (lines 1408-1435):
if row.declared_prompt_cache:  # truthy gate handles both None and empty list
    finding = detect_below_min_tokens(BelowMinTokensEvidence(
        node_id=row.node_path,
        model=row.model,
        declared_prompt_cache=list(row.declared_prompt_cache),
        estimated_tokens=row.cacheable_tokens_estimated,
        estimated_data_source=row.cacheable_data_source,
        # has_observed defaults to False; analyzer never opts into observed tier
    ))
    if finding is not None:
        diagnostics.append(make_diagnostic(
            "cache.below-min-predicted",
            node_id=finding.node_id,
            affected_workflow=row.workflow_path,  # existing analyzer scope
            model=finding.model,
            min_tokens=finding.min_tokens,
            evidence_kind=finding.evidence_kind,
            cacheable_tokens=finding.cacheable_tokens,
            provider_note=finding.provider_note,
        ))
```

The truthy gate `if row.declared_prompt_cache:` is load-bearing — `row.declared_prompt_cache: list[str] | None`, and `list(None)` raises TypeError. Behavior is byte-equivalent for predicted-tier emission with the existing code.

### Runtime emit site (NEW)

Path: `src/pflow/nodes/llm/llm.py::LLMNode.post()` (insertion landmark below)

**Critical reads — three values that the plan must commit to** (these were all wrong in v1):

1. **`prompt_cache` is at IR top level, NOT in `self.params`.** It's stored on `NodeConfig.prompt_cache_items` (frozen tuple). At runtime, LLMNode reads it via `_read_cache_render_context(shared, node_id)` and uses `cache_ctx.subset`. The canonical runtime read is via that helper.

2. **Resolved model is in `prep_res["model"]`** (set at `llm.py` lines ~720-735 in `prep()`). NOT `prep_res["resolved_model"]` (which doesn't exist). At `post()` time, `prep_res["model"]` and `self.params.get("model")` are the same value.

3. **Workflow path is in `shared["_pflow_workflow_file"]`** (injected by `runner._prepare_workflow` for both file and inline runs — see `runtime/CLAUDE.md` § "Inline-workflow cache scoping"). Falls back to `"<unknown>"` only if absent.

**Insertion landmark**: precisely between the `shared["llm_usage"] = llm_usage` write (around line 918) and `warnings_list = exec_res.get("warnings") or []` (around line 932). Place an explanatory comment at the insertion site.

```python
from pflow.core.cache_analysis.below_min_tokens_detector import (
    BelowMinTokensEvidence,
    detect as detect_below_min_tokens,
)
from pflow.core.cache_analysis.warning_catalog import make_diagnostic

# After: shared["llm_usage"] = llm_usage  (~line 918)
# Before: warnings_list = exec_res.get("warnings") or []  (~line 932)

# Cache-miss observation: emit cache.below-min-predicted (observed tier) when the
# provider reported zero cache activity for a node that declared prompt_cache:.
# Uses setdefault-twice to PRESERVE any earlier-written warning (e.g. prewarm-
# disabled from prep()). The empty-response handler below uses subscript
# assignment, so empty-response intentionally OVERWRITES this when both fire —
# empty-response is the critical failure signal; cache-miss is observational.
cache_ctx = _read_cache_render_context(shared, self.node_id)
declared_prompt_cache = list(cache_ctx.subset) if cache_ctx and cache_ctx.subset else []
if declared_prompt_cache and isinstance(llm_usage, dict):
    resolved_model = prep_res.get("model") or self.params.get("model") or ""
    finding = detect_below_min_tokens(BelowMinTokensEvidence(
        node_id=self.node_id,
        model=resolved_model,
        declared_prompt_cache=declared_prompt_cache,
        has_observed=True,
        observed_creation_tokens=int(llm_usage.get("cache_creation_input_tokens") or 0),
        observed_read_tokens=int(llm_usage.get("cache_read_input_tokens") or 0),
    ))
    if finding is not None:
        workflow_path = shared.get("_pflow_workflow_file") or "<unknown>"
        diag = make_diagnostic(
            "cache.below-min-predicted",
            node_id=finding.node_id,
            affected_workflow=workflow_path,
            model=finding.model,
            min_tokens=finding.min_tokens,
            evidence_kind=finding.evidence_kind,
            cacheable_tokens=finding.cacheable_tokens,
            provider_note=finding.provider_note,
        )
        shared.setdefault("__warnings__", {}).setdefault(self.node_id, diag)
```

**ClaudeCodeNode is excluded** by class topology — only `type: "llm"` instantiates `LLMNode`. ClaudeCodeNode has `type: "claude-code"` and never enters this code path. Document at the emit site that "this warning is scoped to LLMNode specifically; cache-using nodes other than LLMNode would need their own emit site."

### Channel extension: `normalize_runtime_warning` accepts `Diagnostic`

Path: `src/pflow/core/diagnostic.py:169-188` (UPDATE)

Add a `Diagnostic` branch BEFORE the existing `dict` branch:
```python
def normalize_runtime_warning(warning: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(warning, Diagnostic):
        # Preserve catalog id + suggestions through the channel.
        ctx = dict(warning.context or {})
        if warning.id:
            ctx.setdefault("id", warning.id)
        if warning.suggestions:
            ctx.setdefault("suggestions", list(warning.suggestions))
        sev = warning.severity.value if hasattr(warning.severity, "value") else str(warning.severity)
        ctx.setdefault("severity", sev)
        return warning.message, ctx
    if isinstance(warning, dict):
        ...  # existing path unchanged
    return str(warning), {}
```

**Three callers exist**, not two (the v1 plan was wrong about this):
- `src/pflow/execution/runner.py:574` (`_extract_runtime_warnings`)
- `src/pflow/runtime/workflow_executor.py:530` (`_extract_child_error` — sub-workflow failure messages)
- `src/pflow/execution/executor_service.py:171` (`_extract_error_info` — last-resort fallback)

The trace serialization path at `runtime/workflow_trace.py:392-403` (`set_warnings`) does NOT use `normalize_runtime_warning` — it directly calls `warning.to_display_dict()` on Diagnostic instances. So the seam covers all dict/string callers; trace serialization handles Diagnostics natively.

### `_extract_runtime_warnings` pass-through

Path: `src/pflow/execution/runner.py:602-614` (UPDATE)

Pass-through Diagnostic instances unchanged; preserve catalog `id`, `suggestions`, `severity`. Document explicitly that Diagnostic instances bypass the recovery/api_warning classification (the cache-miss carries its own typed shape end-to-end).

```python
for node_id, raw_warning in (shared.get("__warnings__") or {}).items():
    if isinstance(raw_warning, Diagnostic):
        # Catalog-emitted Diagnostic. Preserve as-is. Bypasses the
        # __failures__ recovery/api_warning classification — Diagnostic
        # instances carry their own typed shape (id, suggestions, severity,
        # category) end-to-end. No canned api_warning suggestions injected.
        diag = raw_warning if raw_warning.node_id else replace(raw_warning, node_id=node_id)
        out.append(diag)
        continue
    message, ctx = normalize_runtime_warning(raw_warning)
    # ... existing fallback path that builds a fresh api_warning Diagnostic
```

### `_extract_child_error` interaction

Path: `src/pflow/runtime/workflow_executor.py:528-530` (VERIFY + possibly UPDATE)

This caller currently constructs an error message string from the warning value. With Diagnostic shape, `normalize_runtime_warning` (already extended above) returns `(diag.message, ctx)` — so the caller's f-string interpolation gets the human-readable message. This is the desired behavior. **Verify** during implementation that no test asserts a specific dict-shape repr from this path.

### `--report` rendering: surface `id` and `suggestions`

Path: `src/pflow/core/trace_report.py:615-629` (`_append_runtime_warnings`) (UPDATE)

Extend rendering to handle BOTH legacy dict-shape and new display-dict-shape:
```python
def _append_runtime_warnings(report_lines, warnings):
    if not warnings:
        return
    report_lines.append("## Runtime Warnings")
    for w in warnings:
        node_id = w.get("node_id", "<unknown>")
        message = w.get("message", "")
        warning_id = w.get("id")
        suggestions = w.get("suggestions") or []
        prefix = f"[{warning_id}] " if warning_id else ""
        report_lines.append(f"- {prefix}**{node_id}**: {message}")
        for suggestion in suggestions:
            report_lines.append(f"  - {suggestion}")
```

Backward-compat: missing `id` falls back to message-only render (existing tests using legacy dict shape continue to pass — both `test_multiple_runtime_warnings` and `test_runtime_warnings_rendered` use substring assertions, not byte-exact text matching, so they survive).

### Phantom-savings threshold gates (3 sites)

All three sites mirror the established convention at `cache.batch-prewarm-recommended` (`analyze.py:1495`) and `cache.dynamic-before-static` (`analyze.py:1537`).

#### Site 1 — Greenfield `_savings_for_shared_ref` / `_populate_suggested_blocks`

Path: `analyze.py:1727-1779` and `analyze.py:2320-2339` (UPDATE)

**Writer-vs-reader semantics** (load-bearing — easy to get wrong):

In shared-prefix caching, ONE node performs the cache_creation (the writer; absorbs the 1.25× write premium); subsequent nodes are readers (each gets the 0.1× read rate instead of 1.0× input). Today's `_savings_for_shared_ref` excludes `node_ids[0]` (assumed writer) from the savings sum. With threshold gating, the semantics change:

- If `len(eligible_nodes) < 2`: no cache benefit possible (need writer + reader). Return 0.0.
- If `len(eligible_nodes) >= 2`: first eligible is writer; remaining eligible nodes are readers. Sum savings only over reader portion.

Implementation:

1. In `_populate_suggested_blocks`, after building `assignments`, compute `eligible_nodes`:
```python
eligible_nodes: set[str] = set()
for node_id, assigned_refs in assignments.items():
    node_row = rows_by_node.get(node_id)
    if node_row is None or not node_row.model or node_row.model_is_heterogeneous:
        continue  # skip heterogeneous + unknown
    per_node_total = _sum_chunk_tokens(assigned_refs, node_row.model, ctx, memo_cache, workflow_path)
    if per_node_total is None:
        continue  # honest unmeasurable — don't claim savings
    if per_node_total >= get_min_cache_tokens(node_row.model):
        eligible_nodes.add(node_id)
```

2. Update `_savings_for_shared_ref` signature:
```python
def _savings_for_shared_ref(
    ref: str,
    node_ids: list[str],
    rows_by_node: dict[str, PerCallRow],
    tokens: int | None,
    eligible_nodes: set[str],  # NEW
) -> float | None:
    if tokens is None:
        return None
    # Filter to eligible nodes preserving order; need >= 2 for writer + reader.
    eligible_in_order = [nid for nid in node_ids if nid in eligible_nodes]
    if len(eligible_in_order) < 2:
        return 0.0
    total = 0.0
    # Skip first eligible (writer absorbs cache_creation premium); rest are readers.
    for node_id in eligible_in_order[1:]:
        row = rows_by_node.get(node_id)
        if row is None:
            return None
        savings = _estimate_token_savings_usd(row.model, tokens, 1)
        if savings is None:
            return None
        total += savings
    return total
```

3. **Update the call site** at `analyze.py:1753`:
```python
chunk_savings = _savings_for_shared_ref(ref, node_ids, rows_by_node, size_tokens, eligible_nodes)
```

4. **Block-total: when eligible_nodes is empty or has size 1, set `total_savings = 0.0`** (not None — None means "unmeasurable"; 0.0 means "no benefit"). The block is still rendered (per Q3 — agents need to see structure), but with zero savings.

5. **New helper `_sum_chunk_tokens`** (factored to consolidate with `_compute_model_group_costs`'s existing pattern at `analyze.py:2106-2118`):
```python
def _sum_chunk_tokens(
    refs: list[str],
    model: str,
    ctx: AnalysisContext,
    memo_cache: Any,
    workflow_path: str | None,
) -> int | None:
    """Sum chunk tokens across refs. None if any ref unmeasurable."""
    total = 0
    for ref in refs:
        tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache,
                                      workflow_path=workflow_path, ctx=ctx)
        if tokens is None:
            return None
        total += tokens
    return total
```

Replace the existing inline pattern in `_compute_model_group_costs` with a call to this helper.

#### Site 2 — Brownfield `_single_call_write_penalty`

Path: `analyze.py:2147-2165` (UPDATE)

Add threshold gate at function entry:
```python
def _single_call_write_penalty(row: PerCallRow, *, ttl: str | None) -> float | None:
    tokens = row.cacheable_tokens_estimated
    if tokens is None:
        return None
    # NEW: don't claim savings when cache won't fire below threshold.
    # Returns None to signal "suppress entirely" — caller distinguishes from
    # "honest unmeasurable" via the original `tokens is None` early-return
    # which also returns None. Both cases collapse to: caller should skip
    # emitting the cache.first-call-write-penalty diagnostic.
    if row.model and tokens < get_min_cache_tokens(row.model):
        return None
    # ... existing pricing math
```

**Caller-side suppression** (load-bearing — pinned by test):

Find the caller at `analyze.py:2037-2048` (per investigation). The caller currently uses `_single_call_write_penalty` to compute savings for `cache.first-call-write-penalty` diagnostic emission. Both error paths (`tokens is None` and the new sub-threshold gate) return `None`. The caller MUST suppress the diagnostic entirely when result is `None` (NOT emit with savings unavailable). Add a regression test pinning: sub-threshold input → ZERO `cache.first-call-write-penalty` diagnostics emitted.

#### Site 3 — Brownfield `_compute_model_group_costs`

Path: `analyze.py:2084-2121` (UPDATE)

Gate per-group on threshold:
```python
def _compute_model_group_costs(
    groups: list[dict[str, Any]],
    shared_chunks: set[str],
    *,
    ttl: str | None,
    ctx: AnalysisContext,
) -> dict[str, float] | None:
    from .cost_estimation import _write_rate_for_ttl, get_model_pricing

    costs: dict[str, float] = {}
    for group in groups:
        model = str(group["model"])
        pricing = get_model_pricing(model)
        if pricing is None:
            return None
        group_shared = group["chunks"] & shared_chunks
        total_tokens = _sum_chunk_tokens(list(group_shared), model, ctx, ctx.memo_cache, ctx.workflow_path)
        if total_tokens is None:
            return None
        # NEW: skip groups whose total is sub-threshold (cache won't fire).
        if total_tokens < get_min_cache_tokens(model):
            continue
        costs[model] = total_tokens * _write_rate_for_ttl(pricing, ttl, model)
    return costs
```

**Caller update** (load-bearing — `{}` is truthy-different from `None`):

`_detect_model_cache_fragmentation` at `analyze.py:~2008` currently uses `if costs is not None:` and accesses `costs[model]` for redundant groups — would `KeyError` on empty dict. Update:
```python
costs = _compute_model_group_costs(...)
# Suppress fragmentation warning when:
# - costs is None (honest unmeasurable; existing semantics)
# - costs is empty (all groups sub-threshold; no cache writes happen)
# - costs has fewer than 2 entries (single-survivor; no fragmentation by definition)
if costs is None or len(costs) < 2:
    return []
# ... existing path that builds the diagnostic from costs
```

### Per-node threshold rendering (greenfield SuggestedBlock)

Path: `analyze.py:212-224` (`SuggestedBlock`) (UPDATE)

Use a TypedDict (or frozen dataclass) for the per-node entry — agent-readable typed shape:
```python
from typing import TypedDict

class PerNodeThresholdEntry(TypedDict):
    """Per-node threshold check for a SuggestedBlock recommendation."""
    model: str             # resolved exact model, or "<varies>" / "<unknown>"
    min_tokens: int | None     # None when model is heterogeneous/unknown
    total_tokens: int | None   # None when unmeasurable
    meets_threshold: bool | None  # None when unmeasurable

@dataclass(frozen=True)
class SuggestedBlock:
    target_file: str
    ttl: str
    chunks: tuple[SuggestedBlockChunk, ...]
    per_node_assignments: dict[str, list[str]]
    estimated_savings_usd: float | None
    prompt_body_cleanup: dict[str, list[str]] = field(default_factory=dict)
    # NEW:
    per_node_thresholds: dict[str, PerNodeThresholdEntry] = field(default_factory=dict)
```

Populate in `_populate_suggested_blocks` (after computing `eligible_nodes`):
```python
per_node_thresholds: dict[str, PerNodeThresholdEntry] = {}
for node_id, assigned_refs in assignments.items():
    node_row = rows_by_node.get(node_id)
    if node_row is None or node_row.model_is_heterogeneous:
        per_node_thresholds[node_id] = {
            "model": "<varies>" if node_row and node_row.model_is_heterogeneous else "<unknown>",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }
        continue
    if not node_row.model:
        per_node_thresholds[node_id] = {
            "model": "<unknown>",
            "min_tokens": None,
            "total_tokens": None,
            "meets_threshold": None,
        }
        continue
    total = _sum_chunk_tokens(assigned_refs, node_row.model, ctx, memo_cache, workflow_path)
    threshold = get_min_cache_tokens(node_row.model)
    per_node_thresholds[node_id] = {
        "model": node_row.model,
        "min_tokens": threshold,
        "total_tokens": total,
        "meets_threshold": (total >= threshold) if total is not None else None,
    }
```

Path: `render_text.py:608-652` (`_render_suggested_blocks`) (UPDATE)

Inside the per-node-assignments loop (around line 639), append a threshold-status line. Defensive `else` branch protects against malformed dict shape:
```python
threshold_info = block.per_node_thresholds.get(node_id) or {}
status = threshold_info.get("meets_threshold")
total = threshold_info.get("total_tokens")
mn = threshold_info.get("min_tokens")
model_label = threshold_info.get("model", "<unknown>")
if status is True:
    chunks.append(f"  - threshold: {total} tokens / {mn} ({model_label}) ✓")
elif status is False:
    chunks.append(
        f"  - threshold: {total} tokens / {mn} ({model_label}) ⚠ BELOW THRESHOLD — "
        f"cache will not fire as suggested"
    )
elif status is None and model_label == "<varies>":
    chunks.append("  - threshold: varies per item (heterogeneous model)")
elif status is None:
    chunks.append("  - threshold: unable to estimate (no run data; first run will populate)")
else:
    # Defensive — should never hit. Surface a "data malformed" hint rather
    # than render a silently-blank line.
    chunks.append("  - threshold: <unavailable>")
```

Path: `render_json.py:140-159` (`_block_to_dict`) (UPDATE)

Add the new field; document the inner-dict shape in a comment:
```python
def _block_to_dict(block: SuggestedBlock) -> dict[str, Any]:
    return {
        # ... existing fields
        # per_node_thresholds: dict[node_id, {model, min_tokens, total_tokens, meets_threshold}]
        # See PerNodeThresholdEntry TypedDict in analyze.py for the inner shape.
        "per_node_thresholds": dict(block.per_node_thresholds),
    }
```

---

## Files to modify

**NEW**:
- `src/pflow/core/cache_analysis/below_min_tokens_detector.py` (~80 LOC including provider note helper)

**UPDATED — production**:
- `src/pflow/core/cache_analysis/warning_catalog.py` — catalog entry update + dispatch + module-level templates (~40 LOC delta)
- `src/pflow/core/cache_analysis/analyze.py` — refactor analyzer emit site + 3 phantom-savings gates + per-node thresholds + `_sum_chunk_tokens` helper (~140 LOC delta)
- `src/pflow/nodes/llm/llm.py` — runtime emit site (~30 LOC delta)
- `src/pflow/core/diagnostic.py` — `normalize_runtime_warning` accepts Diagnostic (~10 LOC delta)
- `src/pflow/execution/runner.py` — `_extract_runtime_warnings` pass-through (~12 LOC delta)
- `src/pflow/core/trace_report.py` — `_append_runtime_warnings` shows id + suggestions (~15 LOC delta)
- `src/pflow/core/cache_analysis/render_text.py` — per-node threshold line (~25 LOC delta)
- `src/pflow/core/cache_analysis/render_json.py` — `per_node_thresholds` projection (~3 LOC delta)

**UPDATED — tests** (every site that constructs `make_diagnostic("cache.below-min-predicted", ...)` needs new context keys: `evidence_kind`, `provider_note`):
- `tests/test_core/test_below_min_tokens_detector.py` (NEW) — detector unit tests (~120 LOC)
- `tests/test_core/test_cache_analysis_warnings.py` — UPDATE 4 sites: lines 162-174, 277-282, 289-295, and `_minimal_context_kwargs` at line 495-501. Plus dispatch + provider-clause tests.
- `tests/test_core/test_cache_analysis_per_id_coverage.py` — UPDATE `_kwargs_for` at lines 91-99.
- `tests/test_core/test_cache_analysis_renderers.py` — UPDATE 5 sites: lines 591-605, 599-605, 618-624, 639-645, 647-653. Plus per-node threshold rendering tests.
- `tests/test_core/test_cache_analysis_analyze.py` — end-to-end fixtures for all three phantom-savings sites + per-node thresholds + sub-threshold suggested block.
- `tests/test_core/test_cache_analysis_per_id_emission.py` — emission tests for both predicted and observed evidence kinds.
- `tests/test_core/test_diagnostic.py` — `normalize_runtime_warning(Diagnostic)` branch tests.
- `tests/test_execution/test_runner.py` — `_extract_runtime_warnings` Diagnostic pass-through tests.
- `tests/test_core/test_trace_report.py` — `_append_runtime_warnings` id + suggestions rendering; legacy dict-shape no-regression tests.
- `tests/test_nodes/test_llm_node.py` — runtime emit site tests; observed-tier behavior; coexistence with empty-response.
- `tests/test_execution/test_plan_cache_nudge.py` — verify catalog row update doesn't break the dry-run nudge path which uses `cache.below-min-predicted`.

**UPDATED — documentation**:
- `src/pflow/core/cache_analysis/CLAUDE.md` — note the dual emit sites + dispatch table + new detector module + sub-workflow same-id collision caveat.
- `src/pflow/runtime/CLAUDE.md` — note that `__warnings__` channel now accepts `Diagnostic` instances (contract change in the value type; key shape unchanged).
- `src/pflow/core/CLAUDE.md` — note `normalize_runtime_warning` accepts a third type.
- `src/pflow/execution/CLAUDE.md` — note `_extract_runtime_warnings` pass-through behavior for Diagnostic instances (bypasses recovery/api_warning classification).
- `src/pflow/nodes/CLAUDE.md` (or `nodes/llm/CLAUDE.md` if it exists) — new producer of `__warnings__` entries from `LLMNode.post()` with explicit ordering note (cache-miss vs empty-response).

**Total**: ~360 LOC production + ~400 LOC tests.

---

## Test plan

### Detector unit tests
Path: `tests/test_core/test_below_min_tokens_detector.py` (NEW)

Cover the truth table:
- No `prompt_cache:` declared → returns None
- Empty model → returns None
- Predicted: `estimated_tokens >= threshold` → None
- Predicted: `estimated_tokens < threshold` → Finding(predicted)
- Predicted: `estimated_data_source == "trace"` → None (don't contradict trace)
- Predicted: `estimated_tokens is None` or 0 → None
- Observed: `has_observed=False` → falls to predicted tier
- Observed: `has_observed=True, creation+read > 0` → None (cache fired)
- Observed: `has_observed=True, creation+read == 0` → Finding(observed, cacheable_tokens=0)
- Observed-wins-over-predicted: when has_observed=True with both populated, observed takes priority
- Provider note: anthropic / gemini / openai (returns "") / unknown (returns "")

### Mutation safety checks (pflow custom)
For each new test pinning critical behavior, REVERT the corresponding production change and confirm the test fails. Specifically:
- Detector predicted-tier test fails when `estimated_tokens < threshold` check is removed
- Detector observed-tier test fails when `has_observed` flag is replaced with `is not None` check
- Runtime emission test fails when the detector call is commented out in `LLMNode.post()`
- Brownfield phantom-fix tests fail when threshold gate is reverted at each of the three sites
- `_single_call_write_penalty` suppression test fails when caller's None-handling is reverted
- `_compute_model_group_costs` empty-dict suppression test fails when caller's `len(costs) < 2` check is reverted
- Channel pass-through test fails when `Diagnostic` branch is removed from `normalize_runtime_warning`
- Catalog dispatch test fails when `_BELOW_MIN_TOKENS_DISPATCH` is replaced with single-template fallback

### Backward-compat tests
- Legacy dict-shape warnings still render in `--report` without `id`/`suggestions` (no regression)
- `_extract_child_error` with new Diagnostic-shape warning produces clean error message (not dataclass repr)
- `_extract_error_info` (executor_service.py) handles Diagnostic-shape gracefully

---

## Verification

### Unit + integration tests
```bash
make test          # full suite (expected delta: +~50-60 tests)
make check         # ruff + mypy + deptry, all clean
```

### End-to-end manual verification

**1. Greenfield phantom-savings fix** — use the existing fixture in `tests/test_core/test_cache_analysis_per_id_coverage.py:437` shape (Sonnet-4-5 with single tiny chunk). Verify:
```bash
uv run pflow analyze-cache <below-threshold-fixture>.pflow.md --format=json
```
Expected: SuggestedBlock present with `per_node_thresholds` showing below-threshold; `estimated_savings_usd` is `0.0` (was non-zero pre-fix); RecommendedAction ranking no longer surfaces this block above above-threshold blocks.

**2. Runtime cache-miss warning** — minimal reproducer:
```yaml
## Cache
items:
  - name: small_doc
    var: small_doc
    prose_before: "Reference:"

## Steps
- llm: ask
  model: anthropic/claude-haiku-4-5  # threshold 4096
  prompt_cache: [small_doc]
  params:
    prompt: "Summarize ${small_doc}"
```
With `small_doc` resolving to <4096 tokens. Run:
```bash
uv run pflow run repro.pflow.md --inputs '{"small_doc": "..."}' --report
```
Expected: trace-report markdown contains `## Runtime Warnings` with `[cache.below-min-predicted]` and the **observed-tier** message ("did not fire on this call ... below claude-haiku-4-5's minimum of 4096 tokens; cache_control markers will silently no-op at the provider"). Suggestions bulleted underneath.

**3. Provider-aware text (Finding #10)** — repeat above with Gemini and OpenAI models. Verify Anthropic + Gemini provider notes render correctly; OpenAI omits the note (clean message ending with min_tokens).

**4. Brownfield `cache.first-call-write-penalty` and `cache.heterogeneous-models-fragment-cache` no longer phantom**:
- Reuse `scratchpads/stage2-verification/mixed-model-test/mixed-model.pflow.md`.
- Reduce `${context}` size below threshold for both models.
- Run `analyze-cache` — both warnings suppress.
- Test `len(costs) < 2` case: configure one model above + one below threshold. Fragmentation warning should suppress (single survivor = no fragmentation).

**5. Sub-workflow scoping** — verify warning fires from inside a child sub-workflow and propagates to parent's trace via `_PROPAGATED_KEYS`. Verify `affected_workflow` carries the correct workflow path (or `<unknown>` placeholder if `_pflow_workflow_file` is absent — should NOT raise KeyError).

**6. Dispatch table fallback** — manually construct a Diagnostic with `evidence_kind="suspected"` and verify the unknown-fallback template is used and `logger.warning` fires.

---

## Critical implementation notes for the executor

1. **Detector module import discipline**: `below_min_tokens_detector.py` MUST import only stdlib + `pflow.core.llm_capabilities` + `pflow.core.llm_providers`. Forbidden: `cache_analysis.token_estimation`, `cache_analysis.analyze`, `pflow.runtime.*`, `pflow.execution.*`, `pflow.cli.*`, `pflow.mcp_server.*`, `pflow.nodes.*`. Verify with `grep` after writing.

2. **The three load-bearing runtime reads** (DO NOT skip verification):
   - `prompt_cache` → `_read_cache_render_context(shared, self.node_id).subset` (NOT `self.params`)
   - `resolved model` → `prep_res["model"]` (NOT `prep_res["resolved_model"]`)
   - `workflow_path` → `shared.get("_pflow_workflow_file") or "<unknown>"` (NOT `None` — would KeyError at `_ensure_workflow_scope`)

3. **Catalog dispatch precedent is `cache.shared-context-undeclared`** (`make_diagnostic` lines 1039-1071), NOT `cache.discrepancy`. The latter dispatches `suggestions_template`, not `message_template`.

4. **`provider_clause` formatting pattern** (mirrors `_format_savings_clause` at `warning_catalog.py:846`): compute `provider_clause = f"; {note}" if note else ""` BEFORE template formatting, then use `{provider_clause}` placeholder in templates. Avoids inline trim hacks.

5. **`evidence_kind` dispatch fallback**: `_BELOW_MIN_TOKENS_MESSAGE_UNKNOWN` template + `logger.warning` for unrecognized kinds. Mirrors the safety net `cache.discrepancy` has for unknown `root_cause` values.

6. **Site 1 phantom-savings semantics** (writer-vs-reader): need `len(eligible_nodes) >= 2` for any savings; first eligible is writer, rest are readers. Block with no eligible readers gets `total_savings = 0.0` (NOT None). The block is still rendered.

7. **Site 2 caller-side suppression** (`cache.first-call-write-penalty`): when `_single_call_write_penalty` returns `None` for either reason (honest unmeasurable OR sub-threshold gate), the caller MUST suppress diagnostic emission entirely. Pin with regression test.

8. **Site 3 caller update**: `if costs is None or len(costs) < 2:` (NOT just `if costs is None:`). Empty-dict and single-survivor cases both suppress the fragmentation warning.

9. **Cache-miss vs empty-response ordering**: cache-miss insertion is BETWEEN `shared["llm_usage"] = llm_usage` and `warnings_list = exec_res.get("warnings") or []`. Cache-miss uses `setdefault.setdefault` (preserves earlier writes including prewarm-disabled). Empty-response at line 938 uses subscript assignment (intentionally OVERWRITES cache-miss when both fire). Document this ordering at the emit site.

10. **`_extract_runtime_warnings` Diagnostic pass-through bypasses**: the `__failures__` recovery/api_warning classification logic AND the canned api_warning suggestions injection. Diagnostic instances carry their own typed shape. Document explicitly in the runner's code comment.

11. **`workflow_executor._extract_child_error` (line 528-530)** uses `normalize_runtime_warning` to extract the message. With the new Diagnostic branch, it gets the human-readable message. Verify no test asserts a specific dict-shape repr from this path.

12. **`tests/test_core/test_cache_analysis_warnings.py` `_minimal_context_kwargs`** at line 495-501 is the SSoT for catalog-iteration tests. MUST be updated to include `evidence_kind` and `provider_note` for `cache.below-min-predicted`. Same for `_kwargs_for` in `test_cache_analysis_per_id_coverage.py` at line 91-99.

13. **Pre-merge sanity**: `git diff --stat` should show only the files listed in "Files to modify". Any unintended scope creep is a red flag.

14. **CLAUDE.md updates** spread across 5 files (cache_analysis, runtime, core, execution, nodes/llm). Don't skip — these are the load-bearing docs for future agents touching this code.

