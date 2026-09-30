"""Tests for canonical LLM provider metadata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest

from pflow.core.litellm_runtime import import_litellm
from pflow.core.llm_providers import (
    CURATED_PROVIDERS,
    PROVIDERS,
    detect_provider,
    extract_provider_prefix,
    normalize_model_name,
    provider_models,
)
from pflow.core.workflow.validator import WorkflowValidator


def test_detect_provider_known_prefixed_models() -> None:
    anthropic = detect_provider("anthropic/claude-sonnet-4-5")
    openai = detect_provider("openai/o4-mini")
    gemini = detect_provider("gemini/gemini-3-flash-preview")
    assert anthropic is not None and anthropic.name == "anthropic"
    assert openai is not None and openai.name == "openai"
    assert gemini is not None and gemini.name == "gemini"


def test_provider_env_vars_canonical_first() -> None:
    """Each provider's env_vars tuple must be non-empty with the canonical first.

    Gemini specifically must include both GEMINI_API_KEY (canonical, matches
    the provider prefix for naming consistency) and GOOGLE_API_KEY (the
    alias LiteLLM checks first in its Gemini auth path).
    """
    by_name = {p.name: p for p in PROVIDERS}
    assert by_name["anthropic"].env_vars == ("ANTHROPIC_API_KEY",)
    assert by_name["openai"].env_vars == ("OPENAI_API_KEY",)
    assert by_name["gemini"].env_vars == ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    for provider in PROVIDERS:
        assert provider.env_vars  # non-empty


def test_curated_provider_names_are_unique() -> None:
    """Registry rows are derived from PROVIDERS; a hand-written row with the same
    name would list the provider twice with possibly conflicting env vars."""
    names = [p.name for p in CURATED_PROVIDERS]
    assert len(names) == len(set(names))


def test_detect_provider_known_bare_models() -> None:
    anthropic = detect_provider("claude-sonnet-4-5")
    openai = detect_provider("o4-mini")
    gemini = detect_provider("gemini-2.5-pro")
    assert anthropic is not None and anthropic.name == "anthropic"
    assert openai is not None and openai.name == "openai"
    assert gemini is not None and gemini.name == "gemini"


def test_openrouter_anthropic_path_is_not_classified_as_anthropic() -> None:
    assert detect_provider("openrouter/anthropic/claude-sonnet-4-5") is None


def test_normalize_model_name_uses_registry() -> None:
    assert normalize_model_name("o4-mini") == "openai/o4-mini"
    assert normalize_model_name("claude-sonnet-4-5") == "anthropic/claude-sonnet-4-5"
    assert normalize_model_name("openrouter/anthropic/claude-sonnet-4-5") == ("openrouter/anthropic/claude-sonnet-4-5")


def test_extract_provider_prefix_returns_first_segment() -> None:
    """Used by exception diagnostics for unknown providers — extracts the
    LiteLLM routing prefix without consulting the registry."""
    assert extract_provider_prefix("together_ai/llama-3-70b") == "together_ai"
    assert extract_provider_prefix("mistral/mistral-large") == "mistral"
    # Multi-segment prefixes (OpenRouter) take only the first segment.
    assert extract_provider_prefix("openrouter/anthropic/claude-sonnet-4-5") == "openrouter"


def test_extract_provider_prefix_returns_none_for_bare_or_empty() -> None:
    assert extract_provider_prefix("gpt-4o-mini") is None
    assert extract_provider_prefix("") is None
    assert extract_provider_prefix(None) is None


# ---------------------------------------------------------------------------
# provider_models — what `pflow settings llm models` lists
# ---------------------------------------------------------------------------

_TODAY = date(2026, 9, 30)
_Bundled = tuple[Any, dict[str, list[str]]]  # (litellm module, provider name -> listed ids)
_BY_NAME = {p.name: p for p in CURATED_PROVIDERS}


def _chat(provider: str, **extra: object) -> dict[str, object]:
    return {"litellm_provider": provider, "mode": "chat", **extra}


def _models(name: str, catalog: Mapping[str, object]) -> list[str]:
    return provider_models(_BY_NAME[name], catalog, today=_TODAY)


def test_provider_models_keeps_chat_and_responses_modes_only() -> None:
    catalog = {
        "gpt-chat": _chat("openai"),
        "gpt-responses": {"litellm_provider": "openai", "mode": "responses"},
        "gpt-instruct": {"litellm_provider": "openai", "mode": "completion"},
        "text-embedding": {"litellm_provider": "openai", "mode": "embedding"},
        "dall-e": {"litellm_provider": "openai", "mode": "image_generation"},
    }
    assert _models("openai", catalog) == ["openai/gpt-responses", "openai/gpt-chat"]


def test_provider_models_honours_declared_capabilities() -> None:
    catalog = {
        "gpt-realtime": _chat("openai", supported_endpoints=["/v1/realtime"]),
        "gpt-both": _chat("openai", supported_endpoints=["/v1/realtime", "/v1/chat/completions"]),
        "gpt-undeclared": _chat("openai"),
        "gpt-audio-out": _chat("openai", supported_output_modalities=["audio"]),
        "gpt-text-out": _chat("openai", supported_output_modalities=["text", "audio"]),
    }
    assert sorted(_models("openai", catalog)) == ["openai/gpt-both", "openai/gpt-text-out", "openai/gpt-undeclared"]


@pytest.mark.parametrize(
    ("provider", "pricing_key"),
    [
        ("openai", "ft:gpt-4o-2024-08-06"),
        ("openai", "openai/container"),
        ("together_ai", "together-ai-4.1b-8b"),
        ("azure", "azure/eu/gpt-4o"),
        ("bedrock", "bedrock/us-east-1/anthropic.claude-v2"),
        ("bedrock", "bedrock/*/1-month-commitment/cohere.command-text-v14"),
    ],
)
def test_provider_models_drops_pricing_only_keys(provider: str, pricing_key: str) -> None:
    kept = f"{provider}/real-model"
    catalog = {pricing_key: _chat(provider), kept: _chat(provider)}
    assert _models(provider, catalog) == [kept]


def test_provider_models_drops_models_past_their_deprecation_date() -> None:
    catalog = {
        "old": _chat("openai", deprecation_date="2026-01-01"),
        "today": _chat("openai", deprecation_date=_TODAY.isoformat()),
        "future": _chat("openai", deprecation_date="2027-01-01"),
        "junk": _chat("openai", deprecation_date="date when the model becomes deprecated"),
    }
    assert sorted(_models("openai", catalog)) == ["openai/future", "openai/junk"]


def test_provider_models_groups_by_catalog_provider() -> None:
    catalog = {
        "claude-x": _chat("anthropic"),
        "vertex_ai/claude-x": _chat("vertex_ai-anthropic_models"),
        "gemini-2.0-flash": _chat("vertex_ai-language-models"),
        "command-r": _chat("cohere_chat"),
        "amazon.nova-lite-v1:0": _chat("bedrock_converse"),
        "gpt-4o": _chat("openai"),
        "no-group": {"mode": "chat"},
        "not-a-dict": "junk",
    }
    assert _models("anthropic", catalog) == ["anthropic/claude-x"]
    assert sorted(_models("vertex_ai", catalog)) == ["vertex_ai/claude-x", "vertex_ai/gemini-2.0-flash"]
    assert _models("cohere", catalog) == ["cohere/command-r"]
    assert _models("bedrock", catalog) == ["bedrock/amazon.nova-lite-v1:0"]


def test_provider_models_shows_provider_prefixed_ids() -> None:
    catalog = {
        "deepseek-chat": _chat("deepseek"),
        "deepseek/deepseek-chat": _chat("deepseek"),  # same id once prefixed: listed once
        "deepseek/deepseek-reasoner": _chat("deepseek"),
        "deepseekx/typo": _chat("deepseek"),  # a slashed key under another prefix is not this provider's
    }
    assert _models("deepseek", catalog) == ["deepseek/deepseek-reasoner", "deepseek/deepseek-chat"]


def test_provider_models_orders_versions_numerically_higher_first() -> None:
    catalog = {key: _chat("openai") for key in ("x-4", "x-4-9", "x-4-10", "x-3-5", "a-1")}
    expected = ["openai/x-4-10", "openai/x-4-9", "openai/x-4", "openai/x-3-5", "openai/a-1"]
    assert _models("openai", catalog) == expected
    assert _models("openai", dict(reversed(list(catalog.items())))) == expected


# The bundled LiteLLM catalog — what an offline run lists. Its fixed date keeps
# these tests from rotting as catalog models pass their deprecation dates.


@pytest.fixture(scope="module")
def bundled() -> _Bundled:
    litellm = import_litellm()
    return litellm, {p.name: provider_models(p, litellm.model_cost, today=_TODAY) for p in CURATED_PROVIDERS}


def test_every_curated_provider_name_is_a_litellm_routing_prefix() -> None:
    litellm = import_litellm()
    for provider in CURATED_PROVIDERS:
        litellm.get_llm_provider(f"{provider.name}/pflow-probe")  # raises for a provider LiteLLM dropped


def test_every_listed_model_routes_through_litellm(bundled: _Bundled) -> None:
    """LiteLLM may resolve a listed id to an internal handler (cohere/... -> cohere_chat), so
    routability plus the provider's own prefix pins the provider, not the resolved name."""
    litellm, listed = bundled
    for name, ids in listed.items():
        for model_id in ids:
            assert model_id.startswith(f"{name}/")
            litellm.get_llm_provider(model_id)


def test_every_listed_registry_model_passes_the_validator_catalog_lookup(
    bundled: _Bundled,
) -> None:
    _, listed = bundled
    ids = [m for name in ("anthropic", "openai", "gemini") for m in listed[name]]
    assert len(ids) > 50
    models = [*ids, "openai/pflow-no-such-model"]
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": f"n{i}", "type": "llm", "params": {"prompt": "hi", "model": model}} for i, model in enumerate(models)
        ],
    }
    diagnostics = WorkflowValidator.validate(ir, skip_node_types=True)
    assert [(d.id, d.node_id) for d in diagnostics] == [("llm.model-not-in-catalog", f"n{len(ids)}")]


def test_openai_lists_only_callable_chat_models(bundled: _Bundled) -> None:
    litellm, listed = bundled
    openai = listed["openai"]
    for fragment in ("dall-e", "embedding", "ft:", "container", "tts", "whisper"):
        assert not any(fragment in m for m in openai), fragment
    # Declared realtime-only; entries that declare no endpoints are trusted as chat.
    assert "openai/gpt-realtime" not in openai
    assert "gpt-realtime" in litellm.model_cost
    undated = [m for m in openai if "deprecation_date" not in litellm.model_cost.get(m.removeprefix("openai/"), {})]
    assert "openai/gpt-4o-mini" in undated


def test_together_ai_lists_models_not_pricing_tiers(bundled: _Bundled) -> None:
    _, listed = bundled
    together = listed["together_ai"]
    assert together
    assert not any(m.startswith("together_ai/together-ai-") for m in together)


@pytest.mark.parametrize(
    ("provider", "extra_group"),
    [("bedrock", "bedrock_converse"), ("vertex_ai", "vertex_ai-language-models"), ("cohere", "cohere_chat")],
)
def test_declared_catalog_groups_contribute_models(bundled: _Bundled, provider: str, extra_group: str) -> None:
    litellm, listed = bundled
    catalog = litellm.model_cost
    prefix = f"{provider}/"
    from_group = [
        m
        for m in listed[provider]
        if catalog.get(m, catalog.get(m.removeprefix(prefix), {})).get("litellm_provider") == extra_group
    ]
    assert from_group


def test_providers_without_catalog_models_list_nothing(bundled: _Bundled) -> None:
    _, listed = bundled
    assert {name for name, ids in listed.items() if not ids} == {"vllm", "hosted_vllm", "huggingface", "voyage"}


def test_provider_models_matching_is_case_sensitive_on_every_platform() -> None:
    """fnmatch case-folds on Windows; group and pricing-key patterns must not."""
    catalog = {
        "claude-x": _chat("Anthropic"),  # not the anthropic group
        "claude-y": _chat("anthropic"),
        "FT:claude-z": _chat("anthropic"),  # not the lowercase ft:* template pattern
    }
    assert _models("anthropic", catalog) == ["anthropic/FT:claude-z", "anthropic/claude-y"]
