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

Trade-off: brand-new models that LiteLLM hasn't bundled yet will show up
as ``unpriced_model`` in cache-analysis output and as ``cost_usd=None``
in runtime trace events. Bump the LiteLLM pin or opt into remote to pick
those up.

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
import os
from typing import Any

_LOCAL_MODEL_COST_MAP_ENV = "LITELLM_LOCAL_MODEL_COST_MAP"


def configure_litellm_defaults() -> None:
    """Apply pflow's LiteLLM runtime policy before importing LiteLLM.

    Sets ``LITELLM_LOCAL_MODEL_COST_MAP=True`` via ``os.environ.setdefault``
    so a user-provided value is respected. Idempotent — safe to call multiple
    times and from multiple lazy-import sites.
    """
    os.environ.setdefault(_LOCAL_MODEL_COST_MAP_ENV, "True")


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
