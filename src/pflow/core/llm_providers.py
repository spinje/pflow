"""Canonical provider metadata for pflow's LLM adapter.

Two tables live here: ``PROVIDERS`` (the registry that drives runtime key
resolution and validation) and ``CURATED_PROVIDERS`` (the wider display table
behind ``pflow settings llm providers`` and ``models``, whose registry rows
derive from ``PROVIDERS``). ``provider_models`` reads a curated row's models
out of LiteLLM's catalog.

This module is intentionally small and dependency-free. It is imported by
the adapter, reasoning map, and exception diagnostics, so it must not import
from those modules in return.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatchcase
from typing import Literal


@dataclass(frozen=True)
class ProviderInfo:
    """Static metadata for one LiteLLM provider family.

    ``env_vars`` lists every API-key environment variable LiteLLM accepts
    for this provider, canonical first. Multiple entries reflect the
    provider's actual aliasing (e.g. LiteLLM's Gemini path checks both
    ``GEMINI_API_KEY`` and ``GOOGLE_API_KEY``); the canonical entry is
    what pflow surfaces as the recommended setup target.

    Cache-token accounting is intentionally NOT represented here. LiteLLM's
    response shape can vary by provider version and trace vintage; pflow
    normalizes usage with ``core.llm_usage.normalize_litellm_usage_tokens()``
    at the adapter/analyzer boundary instead of trusting static provider
    metadata for arithmetic.
    """

    name: str
    provider_prefix: str
    bare_prefixes: tuple[str, ...]
    env_vars: tuple[str, ...]


PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo("anthropic", "anthropic/", ("claude-",), ("ANTHROPIC_API_KEY",)),
    ProviderInfo("openai", "openai/", ("gpt-", "o1", "o3", "o4"), ("OPENAI_API_KEY",)),
    # LiteLLM's own env lookup checks GOOGLE_API_KEY first then
    # GEMINI_API_KEY (see litellm/llms/gemini/common_utils.py) — the reverse
    # of this canonical-first order. pflow neutralizes that by resolving the
    # key itself (llm_config.resolve_provider_api_key) and passing it
    # explicitly to litellm.completion, so this tuple's order is the one
    # that actually governs which key a call uses.
    ProviderInfo("gemini", "gemini/", ("gemini-",), ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
)


AuthSemantics = Literal["single", "or", "and", "local"]


@dataclass(frozen=True)
class CuratedProvider:
    """One row of the curated table behind ``pflow settings llm providers``.

    ``semantics`` says how ``env_vars`` authenticate: ``"single"`` (the one
    var), ``"or"`` (any one of them), ``"and"`` (all of them), or ``"local"``
    (no remote auth; a var, if any, is config such as a server URL).

    ``catalog_groups`` lists the ``litellm_provider`` values (fnmatch patterns)
    whose LiteLLM catalog entries this provider also serves besides ``name`` —
    the catalog files e.g. Bedrock's Converse models under ``bedrock_converse``.
    """

    name: str
    env_vars: tuple[str, ...]
    semantics: AuthSemantics
    note: str | None = None
    catalog_groups: tuple[str, ...] = ()


# Registry rows are derived, so their env vars (and canonical-first order) cannot
# drift from PROVIDERS. The hand-written rows are display-only: listing a provider
# here gives it no runtime behavior, while adding it to PROVIDERS does (explicit
# api_key pass, validation gates) — that is a per-provider feature decision.
#
# Maintenance: when bumping LiteLLM, cross-check against
# litellm.models_by_provider keys for any popular additions. The list is
# curated — completeness < correctness. For providers not listed, the
# convention is <PROVIDER>_API_KEY where <PROVIDER> matches the slash-prefix.
CURATED_PROVIDERS: tuple[CuratedProvider, ...] = (
    *(CuratedProvider(p.name, p.env_vars, "single" if len(p.env_vars) == 1 else "or") for p in PROVIDERS),
    CuratedProvider(
        "bedrock",
        ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
        "and",
        "Or use AWS IAM role / ~/.aws/credentials",
        catalog_groups=("bedrock_converse",),
    ),
    CuratedProvider("azure", ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"), "and"),
    CuratedProvider(
        "vertex_ai",
        ("VERTEXAI_PROJECT", "VERTEXAI_LOCATION"),
        "and",
        "Or use gcloud GOOGLE_APPLICATION_CREDENTIALS",
        catalog_groups=("vertex_ai-*",),
    ),
    CuratedProvider("ollama", ("OLLAMA_API_BASE",), "local", "URL of local Ollama server, not a key"),
    CuratedProvider("vllm", (), "local", "Typically no auth required"),
    CuratedProvider("hosted_vllm", (), "local", "Typically no auth required"),
    CuratedProvider("ai21", ("AI21_API_KEY",), "single"),
    CuratedProvider("baseten", ("BASETEN_API_KEY",), "single"),
    CuratedProvider("cerebras", ("CEREBRAS_API_KEY",), "single"),
    CuratedProvider("cohere", ("COHERE_API_KEY",), "single", catalog_groups=("cohere_chat",)),
    CuratedProvider("databricks", ("DATABRICKS_API_KEY",), "single"),
    CuratedProvider("deepinfra", ("DEEPINFRA_API_KEY",), "single"),
    CuratedProvider("deepseek", ("DEEPSEEK_API_KEY",), "single"),
    CuratedProvider("fireworks_ai", ("FIREWORKS_AI_API_KEY",), "single"),
    CuratedProvider("groq", ("GROQ_API_KEY",), "single"),
    CuratedProvider("huggingface", ("HUGGINGFACE_API_KEY",), "single"),
    CuratedProvider("mistral", ("MISTRAL_API_KEY",), "single"),
    CuratedProvider("openrouter", ("OPENROUTER_API_KEY",), "single"),
    CuratedProvider("perplexity", ("PERPLEXITYAI_API_KEY",), "single"),
    CuratedProvider("replicate", ("REPLICATE_API_KEY",), "single"),
    CuratedProvider("together_ai", ("TOGETHERAI_API_KEY",), "single", "Note: not TOGETHER_API_KEY"),
    CuratedProvider("voyage", ("VOYAGE_API_KEY",), "single"),
    CuratedProvider("xai", ("XAI_API_KEY",), "single"),
)


# Catalog modes the llm node can call: litellm.completion serves chat models and
# bridges responses-mode ones.
_LLM_MODES = frozenset({"chat", "responses"})
_LLM_ENDPOINTS = frozenset({"/v1/chat/completions", "/v1/responses"})

# Catalog keys that price something other than a model string you can call.
_PRICING_ONLY_KEYS = (
    "ft:*",  # fine-tune templates; the real id carries an org/suffix
    "*/container",  # code-interpreter container sessions
    "together-ai-*",  # Together's model-size pricing tiers
    "azure/*/*",  # Azure data-zone pricing; deployment names contain no "/"
    "bedrock/*/*",  # Bedrock region/commitment pricing; the region comes from AWS_REGION_NAME
)


def provider_models(provider: CuratedProvider, catalog: Mapping[str, object], *, today: date) -> list[str]:
    """Return the model ids LiteLLM's ``catalog`` offers for ``provider`` that the llm node can call.

    An entry belongs to the provider when its ``litellm_provider`` matches the
    provider's name or ``catalog_groups``. Ids are shown provider-prefixed: a key
    that already contains ``/`` is kept as-is, otherwise ``<name>/`` is prepended,
    and an id that then does not start with ``<name>/`` is dropped. The order is
    by name with version numbers compared numerically, higher first — a
    mechanical stand-in for newest-first, since the catalog carries no release
    date.
    """
    groups = (provider.name, *provider.catalog_groups)
    prefix = f"{provider.name}/"
    ids: set[str] = set()
    for key, entry in catalog.items():
        if not isinstance(entry, Mapping):
            continue
        group = entry.get("litellm_provider")
        if not isinstance(group, str) or not any(fnmatchcase(group, pattern) for pattern in groups):
            continue
        if not _is_llm_callable(key, entry, today):
            continue
        model_id = key if "/" in key else prefix + key
        if model_id.startswith(prefix):
            ids.add(model_id)
    return sorted(ids, key=_version_key, reverse=True)


def _is_llm_callable(key: str, entry: Mapping[str, object], today: date) -> bool:
    """Whether a catalog entry is a model string the llm node can call today."""
    if entry.get("mode") not in _LLM_MODES:
        return False
    endpoints = entry.get("supported_endpoints")
    if isinstance(endpoints, list) and not _LLM_ENDPOINTS.intersection(endpoints):
        return False
    outputs = entry.get("supported_output_modalities")
    if isinstance(outputs, list) and "text" not in outputs:
        return False
    if any(fnmatchcase(key, pattern) for pattern in _PRICING_ONLY_KEYS):
        return False
    return not _is_past(entry.get("deprecation_date"), today)


def _is_past(value: object, today: date) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value) <= today
    except ValueError:
        return False


def _version_key(model_id: str) -> tuple[list[int | str], str]:
    # re.split with one capture group puts digit runs at the odd positions, so
    # the parts of any two ids align by type and never compare int with str.
    parts = re.split(r"(\d+)", model_id.lower())
    return [int(part) if i % 2 else part for i, part in enumerate(parts)], model_id


def detect_provider(model: str | None) -> ProviderInfo | None:
    """Return provider metadata for known pflow model prefixes.

    Prefixed model identifiers must start with the provider prefix exactly.
    A model such as ``openrouter/anthropic/claude-sonnet-4-5`` is therefore
    not classified as Anthropic; it belongs to OpenRouter, whose behavior
    should be handled explicitly when pflow supports it.
    """
    if not model:
        return None

    name = model.lower()
    for provider in PROVIDERS:
        if name.startswith(provider.provider_prefix):
            return provider

    if "/" in name:
        return None

    for provider in PROVIDERS:
        if any(_matches_bare_prefix(name, prefix) for prefix in provider.bare_prefixes):
            return provider
    return None


def normalize_model_name(model: str) -> str:
    """Add a provider prefix to known bare model names."""
    if "/" in model:
        return model
    provider = detect_provider(model)
    if provider is None:
        return model
    normalized = provider.provider_prefix + model
    return normalized


def model_name_without_provider(model: str, provider: ProviderInfo) -> str:
    """Return the model id after the provider prefix when present."""
    name = model.lower()
    if name.startswith(provider.provider_prefix):
        return name.removeprefix(provider.provider_prefix)
    return name


def extract_provider_prefix(model: str | None) -> str | None:
    """Return the LiteLLM provider prefix for a slash-prefixed model.

    The prefix is the segment before the first slash — what LiteLLM uses
    to route to a provider handler (e.g. ``together_ai`` from
    ``together_ai/llama-3-70b``). Returns ``None`` for bare model names
    or absent input. Distinct from ``detect_provider``: this primitive
    does NOT consult the registry; it just parses the string. Used for
    best-effort env-var derivation when a model's provider isn't in
    pflow's registry but we still want to give a user actionable
    remediation.
    """
    if not model or "/" not in model:
        return None
    return model.split("/", 1)[0]


def _matches_bare_prefix(name: str, prefix: str) -> bool:
    """Match either exact family names or dash-prefixed model families."""
    if prefix.endswith("-"):
        return name.startswith(prefix)
    return name == prefix or name.startswith(f"{prefix}-")
