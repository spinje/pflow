"""pflow-owned LiteLLM runtime policy — single seam for ``import litellm``.

LiteLLM eagerly fetches its model pricing/context map from GitHub at
``import litellm`` time (``litellm/__init__.py`` → ``get_model_cost_map``).
The fetch happens once per Python process via ``httpx.get(URL, timeout=5)``;
on failure it falls back to a bundled local backup. This means analyzer
output (``pflow analyze-cache``), runtime response cost, and external-call
token estimates can drift between runs depending on:

- Network availability when the process starts.
- Whether LiteLLM upstream has shipped a pricing update since the bundled
  backup was cut.

Both produce non-deterministic ``unavailable_models`` / ``unpriced_model``
classifications for the same workflow on the same inputs.

This module fixes that by setting ``LITELLM_LOCAL_MODEL_COST_MAP=True``
before ``import litellm`` so LiteLLM uses its bundled backup unconditionally.
Users who want fresh upstream pricing can opt back in by setting
``LITELLM_LOCAL_MODEL_COST_MAP=False`` (or any value that isn't
case-insensitive ``"true"``) before invoking pflow — ``setdefault`` never
overwrites a user-provided value.

Hybrid bundled-first, upstream-on-miss
======================================

The bundled snapshot is stale for brand-new models that LiteLLM hasn't
bundled yet (e.g., ``gemini/gemini-3.5-flash`` is in upstream but absent
from the LiteLLM 1.86.1 wheel). ``ensure_model_priced(model)`` (runtime
pricing) and ``try_load_upstream_catalog()`` (catalog readers: validator
membership, ``pflow settings llm models``) each
fetch upstream at most once per process and merge it through one helper,
``_merge_upstream_catalog``: every upstream entry whose key the bundled
catalog lacks is added under that exact key, and no bundled entry is ever
written. Failures degrade silently to ``cost_usd=None`` — same as today's
pre-fix behavior for unbundled models.

The determinism contract is now two-tiered:

- **Bundled models**: fully deterministic. Same workflow, same inputs,
  same ``cost_usd`` regardless of who runs it or when.
- **Unbundled models**: cost is computed from the upstream snapshot
  observed the first time this process touches the model. Different
  days could produce different ``cost_usd`` if upstream pricing changed
  in between.

This module is the ONLY production seam for ``import litellm`` and
``import litellm.exceptions``. Runtime calls, pricing projections, external
token estimates, and token estimation all route through here.

Lazy-import contract: this module must not import ``litellm`` at module
scope (``importlib.import_module`` is the only call). Pinned by
``tests/test_cli/test_lazy_imports.py``.
"""

from __future__ import annotations

import importlib
import logging
import math
import os
import threading
from dataclasses import dataclass
from typing import Any

_LOCAL_MODEL_COST_MAP_ENV = "LITELLM_LOCAL_MODEL_COST_MAP"

_logger = logging.getLogger(__name__)
_UPSTREAM_LOCK = threading.Lock()
_upstream_attempted = False

# Fields LiteLLM-shaped cost-map entries are known to carry. An upstream entry
# must be a dict and contain at least one of these before we accept it for
# registration. Without this filter, a malformed payload (single string per
# key, dict-of-strings, partial JSON) would still register junk entries and
# a subsequent ``model in litellm.model_cost`` check would silently report
# them as known — both for the runtime cost-pricing path (``ensure_model_priced``)
# and the validator's catalog-membership path (``try_load_upstream_catalog``).
_RECOGNIZED_UPSTREAM_ENTRY_FIELDS = frozenset({
    "litellm_provider",
    "input_cost_per_token",
    "output_cost_per_token",
    "mode",
    "max_input_tokens",
    "max_output_tokens",
    "max_tokens",
})


def _filter_well_formed_upstream_entries(upstream_map: dict[str, Any]) -> dict[str, Any]:
    """Drop upstream entries whose value isn't a dict carrying a recognized field."""
    return {
        k: v
        for k, v in upstream_map.items()
        if isinstance(v, dict) and _RECOGNIZED_UPSTREAM_ENTRY_FIELDS.intersection(v)
    }


def _merge_upstream_catalog(litellm: Any) -> None:
    """Fetch LiteLLM's upstream cost map and add the entries bundled lacks.

    The single write seam behind both upstream paths. Raises on any fetch
    or payload-shape failure; callers own the latch and the failure policy.

    Each upstream entry whose exact key is absent from ``litellm.model_cost``
    is inserted under that key; existing keys are never written. This is
    deliberately NOT ``litellm.register_model``: it re-resolves every key
    through ``get_model_info``, so an upstream key that aliases a bundled
    entry (``databricks/databricks-claude-opus-4-6`` resolves to
    ``databricks/databricks-claude-opus-4``) overwrites the bundled entry and
    never lands under its own key (#654). The three steps mirror LiteLLM's
    own cost-map reload (``litellm/proxy/proxy_server.py``): write
    ``model_cost``, invalidate its lookup caches (``get_model_info`` is
    ``lru_cache``-d, so a lookup made before the merge would otherwise keep
    answering from the alias), and add the new keys to the per-provider
    model sets LiteLLM routes bare model names through (``claude-*`` →
    ``anthropic``).

    The JSON is fetched with ``httpx`` from ``litellm.model_cost_map_url``
    (honors ``LITELLM_MODEL_COST_MAP_URL``) because LiteLLM's own URL fetch
    honors ``LITELLM_LOCAL_MODEL_COST_MAP=True`` and would return the
    bundled backup instead.
    """
    # httpx is litellm's own runtime dep — guaranteed importable whenever
    # litellm is. Lazy-imported to keep this module cheap when callers never
    # hit a cost-map miss.
    import httpx

    response = httpx.get(litellm.model_cost_map_url, timeout=5)
    response.raise_for_status()
    upstream_map = response.json()
    if not isinstance(upstream_map, dict) or not upstream_map:
        raise ValueError("upstream JSON is empty or not a dict")
    well_formed = _filter_well_formed_upstream_entries(upstream_map)
    if not well_formed:
        raise ValueError("upstream payload contains no well-formed entries")
    new_entries = {k: v for k, v in well_formed.items() if k not in litellm.model_cost}
    if not new_entries:
        return
    litellm.model_cost.update(new_entries)
    litellm.utils._invalidate_model_cost_lowercase_map()
    litellm.add_known_models(model_cost_map=new_entries)


# Catalog-reader latch — independent from the runtime-side ``_upstream_attempted``
# above. See ``try_load_upstream_catalog`` for the rationale (the runtime path
# treats fetch failure as best-effort; catalog readers need to know whether the
# fetch succeeded — validator authority, the model listing's live/offline label).
_validator_upstream_attempted = False
_validator_upstream_fetch_succeeded = False


@dataclass(frozen=True)
class ModelPricing:
    """Per-token USD rates from one LiteLLM model-cost entry."""

    input_rate: float
    output_rate: float
    cache_creation_rate: float
    cache_read_rate: float


def configure_litellm_defaults() -> None:
    """Apply pflow's LiteLLM runtime policy before importing LiteLLM.

    Sets ``LITELLM_LOCAL_MODEL_COST_MAP=True`` via ``os.environ.setdefault``
    so a user-provided value is respected. Idempotent — safe to call multiple
    times and from multiple lazy-import sites.

    Also raises the ``LiteLLM`` logger to CRITICAL *before* import. LiteLLM
    1.86+ emits WARNING-level botocore/bedrock/sagemaker stream-preload
    messages at ``import litellm`` time (providers pflow doesn't use); setting
    the level here — at the single seam, before the module's handlers fire —
    suppresses that import-time stderr noise. ``llm_client.complete()``
    re-affirms CRITICAL after import for the same policy reason (LiteLLM's
    typed exceptions are pflow's single error surface, so redundant
    ERROR/WARNING logs are just noise).
    """
    os.environ.setdefault(_LOCAL_MODEL_COST_MAP_ENV, "True")
    logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)


def import_litellm() -> Any:
    """Import ``litellm`` after applying pflow's deterministic defaults.

    Use this in place of ``import litellm`` at every production call site.

    Also sets ``suppress_debug_info``: LiteLLM ``print()``s a "Provider List"
    banner to stdout when it cannot route a model (e.g. from
    ``cost_per_token``), which would corrupt pflow's JSON output. It is a
    module attribute, so it can only be set after import.

    Return type is ``Any``, not ``ModuleType``, because LiteLLM ships no type
    stubs — call sites read attributes like ``litellm.completion``,
    ``litellm.model_cost``, ``litellm.suppress_debug_info`` which mypy can't
    discover from a concrete ``ModuleType`` annotation. ``Any`` mirrors the
    pre-fix behavior of bare ``import litellm`` under
    ``disallow_any_unimported = true``.
    """
    configure_litellm_defaults()
    litellm: Any = importlib.import_module("litellm")
    litellm.suppress_debug_info = True
    return litellm


def import_litellm_exceptions() -> Any:
    """Import ``litellm.exceptions`` after applying pflow's deterministic defaults.

    Use this in place of ``import litellm.exceptions`` at every production
    call site. See ``import_litellm`` for the rationale on the ``Any`` return
    type.
    """
    configure_litellm_defaults()
    return importlib.import_module("litellm.exceptions")


def ensure_model_priced(model: str) -> None:
    """Merge the upstream cost map into ``litellm.model_cost`` on first cache miss.

    Runs at most once per Python process. Idempotent. Thread-safe — pflow's
    ThreadPoolExecutor batch path runs LLM calls in parallel, so two
    cost-map misses can race the helper at startup. The lock + double-check
    pattern collapses the race to a single upstream fetch.

    If the model is already in ``litellm.model_cost`` (i.e. the bundled JSON
    knows it), this is a no-op — preserves the offline fast path. If the
    fetch fails (offline, DNS, proxy, GitHub down, malformed JSON), we log
    at debug level and leave the cost map untouched. ``cost_usd`` stays
    ``None`` for unpriced models, matching pre-fix behavior.
    """
    global _upstream_attempted
    if _upstream_attempted:
        return
    with _UPSTREAM_LOCK:
        if _upstream_attempted:
            return
        litellm = import_litellm()
        if model in litellm.model_cost:
            return
        try:
            _merge_upstream_catalog(litellm)
        except Exception as exc:
            _logger.debug("Upstream cost map fetch failed: %s", exc)
        _upstream_attempted = True


def get_model_pricing(model: str) -> ModelPricing | None:
    """Return LiteLLM pricing for ``model``, fetching upstream on a miss.

    LiteLLM's catalog is inconsistent about provider-prefixed keys, so the
    exact identifier is tried first and then its provider-aware bare form.
    Missing or incomplete pricing stays ``None``.
    """
    if not model:
        return None
    try:
        litellm = import_litellm()
    except ImportError:
        _logger.debug("litellm import failed during pricing lookup", exc_info=True)
        return None

    ensure_model_priced(model)
    model_cost = getattr(litellm, "model_cost", None)
    if not isinstance(model_cost, dict):
        return None

    pricing_dict = model_cost.get(model)
    if pricing_dict is None:
        from pflow.core.llm_providers import detect_provider, model_name_without_provider

        provider = detect_provider(model)
        if provider is not None:
            pricing_dict = model_cost.get(model_name_without_provider(model, provider))
    if not isinstance(pricing_dict, dict):
        return None
    return pricing_from_dict(pricing_dict)


def pricing_from_dict(pricing: dict[str, Any]) -> ModelPricing | None:
    """Normalize a LiteLLM pricing entry, or return ``None`` if incomplete."""
    input_rate = pricing.get("input_cost_per_token")
    output_rate = pricing.get("output_cost_per_token")
    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
        return None

    creation_rate = pricing.get("cache_creation_input_token_cost")
    if not isinstance(creation_rate, (int, float)):
        creation_rate = float(input_rate) * 1.25

    read_rate = pricing.get("cache_read_input_token_cost")
    if not isinstance(read_rate, (int, float)):
        read_rate = float(input_rate) * 0.1

    return ModelPricing(
        input_rate=float(input_rate),
        output_rate=float(output_rate),
        cache_creation_rate=float(creation_rate),
        cache_read_rate=float(read_rate),
    )


def estimate_completion_cost_usd(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float | None:
    """Estimate one completed call using LiteLLM's token-pricing machinery.

    This is for successful calls made outside ``litellm.completion`` (for
    example, the Codex CLI backend). ``input_tokens`` follows pflow's stable
    cache-inclusive contract; the cache tier counts let LiteLLM apply the
    corresponding discounted or creation rates. Unknown models degrade to
    ``None`` instead of inventing a price.
    """
    if not model or get_model_pricing(model) is None:
        return None

    litellm = import_litellm()
    try:
        input_cost, output_cost = litellm.cost_per_token(
            model=model,
            prompt_tokens=max(0, input_tokens),
            completion_tokens=max(0, output_tokens),
            cache_creation_input_tokens=max(0, cache_creation_input_tokens),
            cache_read_input_tokens=max(0, cache_read_input_tokens),
            call_type="completion",
        )
        total = float(input_cost) + float(output_cost)
    except Exception as exc:
        _logger.debug("LiteLLM could not estimate completion cost for %s: %s", model, exc)
        return None
    return total if math.isfinite(total) and total >= 0 else None


def try_load_upstream_catalog() -> bool:
    """Best-effort upstream catalog merge for catalog readers (validator membership, ``settings llm models``).

    Independent of ``ensure_model_priced``'s runtime latch. Returns True if
    the in-memory catalog is in a state usable for model-membership checks
    (either bundled is sufficient, or upstream merge succeeded in this
    process). Returns False if an upstream fetch was attempted in this
    process and failed.

    Two latches in this module:

    - ``_upstream_attempted`` / runtime: permanent-on-attempt, ignores
      whether the fetch succeeded. The runtime's cost-pricing path doesn't
      care if a previous failure was transient — pricing is best-effort
      and the ``cost_usd`` field falls back to None.
    - ``_validator_upstream_attempted`` / validator: also permanent-on-
      attempt within one process, but reports the success/failure status
      via the return value. The validator's "is this model real?" question
      is binary; the validator needs to know if its membership check is
      authoritative.

    Both functions share ``litellm.model_cost``, so a successful merge
    from EITHER path benefits the other. The latches are independent, so
    each path may fetch once; a second merge writes nothing new.

    Thread-safe via the existing module-level lock.
    """
    global _validator_upstream_attempted, _validator_upstream_fetch_succeeded
    if _validator_upstream_attempted:
        return _validator_upstream_fetch_succeeded
    with _UPSTREAM_LOCK:
        if _validator_upstream_attempted:
            return _validator_upstream_fetch_succeeded
        litellm = import_litellm()
        try:
            _merge_upstream_catalog(litellm)
            # Whether or not there were new entries, the fetch succeeded:
            # the catalog is usable for membership checks.
            _validator_upstream_fetch_succeeded = True
        except Exception as exc:
            _logger.debug("Validator upstream catalog merge failed: %s", exc)
            _validator_upstream_fetch_succeeded = False
        _validator_upstream_attempted = True
        return _validator_upstream_fetch_succeeded
