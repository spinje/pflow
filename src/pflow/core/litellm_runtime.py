"""pflow-owned LiteLLM runtime policy — single seam for ``import litellm``.

LiteLLM eagerly fetches its model pricing/context map from GitHub at
``import litellm`` time (``litellm/__init__.py`` → ``get_model_cost_map``).
The fetch happens once per Python process via ``httpx.get(URL, timeout=5)``;
on failure it falls back to a bundled local backup. This means analyzer
output (``pflow analyze-cache``) and runtime cost (``response_cost`` from
``_hidden_params``) can drift between runs depending on:

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
from the LiteLLM 1.86.1 wheel). ``ensure_model_priced(model)`` performs
exactly one upstream fetch per process when a cost-map lookup misses,
merging the upstream JSON via LiteLLM's public ``register_model(url)``
API. Bundled pricing always wins (the helper only fetches on miss).
Failures degrade silently to ``cost_usd=None`` — same as today's pre-fix
behavior for unbundled models.

The determinism contract is now two-tiered:

- **Bundled models**: fully deterministic. Same workflow, same inputs,
  same ``cost_usd`` regardless of who runs it or when.
- **Unbundled models**: cost is computed from the upstream snapshot
  observed the first time this process touches the model. Different
  days could produce different ``cost_usd`` if upstream pricing changed
  in between.

This module is the ONLY production seam for ``import litellm`` and
``import litellm.exceptions``. The six lazy import sites in ``llm_client.py``,
``cache_analysis/cost_estimation.py``, and ``cache_analysis/token_estimation.py``
all route through here.

Lazy-import contract: this module must not import ``litellm`` at module
scope (``importlib.import_module`` is the only call). Pinned by
``tests/test_cli/test_lazy_imports.py``.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

_LOCAL_MODEL_COST_MAP_ENV = "LITELLM_LOCAL_MODEL_COST_MAP"

_logger = logging.getLogger(__name__)
_UPSTREAM_LOCK = threading.Lock()
_upstream_attempted = False


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

    Return type is ``Any``, not ``ModuleType``, because LiteLLM ships no type
    stubs — call sites read attributes like ``litellm.completion``,
    ``litellm.model_cost``, ``litellm.suppress_debug_info`` which mypy can't
    discover from a concrete ``ModuleType`` annotation. ``Any`` mirrors the
    pre-fix behavior of bare ``import litellm`` under
    ``disallow_any_unimported = true``.
    """
    configure_litellm_defaults()
    return importlib.import_module("litellm")


def import_litellm_exceptions() -> Any:
    """Import ``litellm.exceptions`` after applying pflow's deterministic defaults.

    Use this in place of ``import litellm.exceptions`` at every production
    call site. See ``import_litellm`` for the rationale on the ``Any`` return
    type.
    """
    configure_litellm_defaults()
    return importlib.import_module("litellm.exceptions")


def ensure_model_priced(model: str) -> None:
    """Merge upstream cost map into ``litellm.model_cost`` on first cache miss.

    Runs at most once per Python process. Idempotent. Thread-safe — pflow's
    ThreadPoolExecutor batch path runs LLM calls in parallel, so two
    cost-map misses can race the helper at startup. The lock + double-check
    pattern collapses the race to a single upstream fetch.

    If the model is already in ``litellm.model_cost`` (i.e. the bundled JSON
    knows it), this is a no-op — preserves the offline fast path. If the
    fetch fails (offline, DNS, proxy, GitHub down, malformed JSON), we log
    at debug level and leave the cost map untouched. ``cost_usd`` stays
    ``None`` for unpriced models, matching pre-fix behavior.

    **Bundled-first determinism preservation**: the upstream map is filtered
    to only keys NOT already in ``litellm.model_cost`` before passing to
    ``register_model``. Without this filter, ``register_model`` would
    overwrite bundled-model entries via its ``model_cost.setdefault(key, {}).update(value)``
    call path — meaning a single first-miss fetch in any process could
    shift the *bundled* model's price if upstream had revised it. Filtering
    preserves the contract: bundled prices stay deterministic across runs;
    only previously-unpriced models pick up upstream values.

    Implementation note: we fetch the JSON via ``httpx`` directly rather
    than passing the URL to ``litellm.register_model(url)`` because the
    URL form routes through ``litellm.get_model_cost_map`` which honors
    ``LITELLM_LOCAL_MODEL_COST_MAP=True`` (set by ``configure_litellm_defaults``)
    and returns the bundled backup *instead of* fetching the URL. The
    dict-form of ``register_model`` skips that gate and merges directly.
    The fetch URL is read from ``litellm.model_cost_map_url`` (LiteLLM's
    module-level attribute, populated from ``LITELLM_MODEL_COST_MAP_URL``)
    so the existing offline regression test in
    ``tests/test_cli/test_litellm_pricing_map_offline.py`` keeps working
    without monkeypatching us.
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
            # httpx is litellm's own runtime dep — guaranteed importable
            # whenever litellm is. Lazy-imported here to keep this module
            # cheap when callers never hit a cost-map miss.
            import httpx

            response = httpx.get(litellm.model_cost_map_url, timeout=5)
            response.raise_for_status()
            upstream_map = response.json()
            if not isinstance(upstream_map, dict) or not upstream_map:
                raise ValueError("upstream JSON is empty or not a dict")
            # Filter to entries NOT already in bundled model_cost.
            # litellm.register_model merges via
            # model_cost.setdefault(key, {}).update(value), which OVERWRITES
            # existing keys. Without this filter, an upstream price revision
            # for a bundled model would silently shift the bundled price for
            # the remaining process lifetime — breaking the "bundled prices
            # are fully deterministic" half of the contract documented above.
            new_entries = {k: v for k, v in upstream_map.items() if k not in litellm.model_cost}
            if not new_entries:
                # All upstream models are already bundled — nothing to register.
                # The asked-for ``model`` is still missing (we checked above),
                # but upstream doesn't have it either; cost stays None.
                _upstream_attempted = True
                return
            # Silence LiteLLM's "Provider List:" stderr spam during
            # register_model. Internally it calls get_model_info() for
            # every upstream entry; entries from providers LiteLLM doesn't
            # recognize trigger a debug print at
            # litellm_core_utils/get_llm_provider_logic.py:463 (gated on
            # ``suppress_debug_info is False``). Already True in the
            # complete() path; not necessarily True in the cache-analysis
            # path that also calls this helper.
            litellm.suppress_debug_info = True
            # Pass the filtered dict directly to bypass LiteLLM's
            # LITELLM_LOCAL_MODEL_COST_MAP gate (which would short-circuit
            # a URL-form call to the bundled backup).
            litellm.register_model(new_entries)
        except Exception as exc:
            _logger.debug("Upstream cost map fetch failed: %s", exc)
        _upstream_attempted = True
