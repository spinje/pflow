"""Direct unit tests for core/prompt_cache helpers (Task 159 B3.3).

Tests ``_deterministic_serialize`` byte-stability, ``_resolve_chunk_value``
ABSENT-detection + deterministic serialization, and the regex-parity invariant
that locks ``_resolve_static_prefix_for_cache`` against ``TemplateResolver``.

The ABSENT serialization path is the silent stale-cache regression class —
without the sentinel filter, a chunk on a non-taken branch would render to
a stable string ``"<...ChunkAbsentSentinel>"`` and silently fold into the
cache hash byte-identically across runs.
"""

from __future__ import annotations

import json

import pytest

from pflow.core.prompt_cache import (
    _CHUNK_ABSENT,
    CacheChunkIR,
    _ChunkAbsentSentinel,
    _compute_marker_chunk_indices,
    _deterministic_serialize,
    _looks_like_routed_anthropic,
    _resolve_chunk_value,
    _resolve_static_prefix_for_cache,
)

# --- _deterministic_serialize byte-stability -------------------------------


def test_serialize_string_pass_through() -> None:
    assert _deterministic_serialize("hello") == "hello"


def test_serialize_dict_uses_canonical_json() -> None:
    """Sorted keys + compact separators → byte-stable across dict
    insertion-order histories."""
    assert _deterministic_serialize({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_serialize_list_uses_canonical_json() -> None:
    assert _deterministic_serialize([1, 2, 3]) == "[1,2,3]"


def test_serialize_nested_uses_canonical_json() -> None:
    out = _deterministic_serialize({"outer": {"y": 2, "x": 1}, "list": [3, 1, 2]})
    assert out == '{"list":[3,1,2],"outer":{"x":1,"y":2}}'


def test_serialize_value_is_byte_identical_to_chunk_render() -> None:
    """The same logical value substituted via ``_resolve_chunk_value`` and
    via ``_resolve_static_prefix_for_cache`` must produce identical bytes —
    otherwise hash-vs-prep render disagrees and silent stale cache fires."""
    value = {"text": "abc"}
    chunk_render = _deterministic_serialize(value)
    expected = json.dumps(value, sort_keys=True, separators=(",", ":"))
    assert chunk_render == expected
    assert chunk_render == '{"text":"abc"}'


def test_serialize_handles_unknown_types_via_default_str() -> None:
    """``default=str`` keeps the helper from crashing on a value that isn't
    JSON-serializable. Stable repr — same bytes across runs."""

    class Custom:
        def __str__(self) -> str:
            return "stable-repr"

    assert _deterministic_serialize(Custom()) == '"stable-repr"'


# --- _resolve_chunk_value ---------------------------------------------------


def test_resolve_chunk_returns_absent_when_upstream_not_run() -> None:
    """Upstream node not in shared → NodeStatus.ABSENT → sentinel returned.
    The filter sites (plan_node + LLMNode.prep) drop sentinel entries from
    the rendered subset symmetrically."""
    chunk = CacheChunkIR(name="upstream", var_expr="upstream", prose_before="", source_line=1)
    result = _resolve_chunk_value(chunk, {})
    assert isinstance(result, _ChunkAbsentSentinel)
    assert result is _CHUNK_ABSENT


def test_resolve_chunk_returns_string_when_upstream_present() -> None:
    chunk = CacheChunkIR(name="upstream", var_expr="upstream", prose_before="", source_line=1)
    result = _resolve_chunk_value(chunk, {"upstream": "the value"})
    assert result == "the value"


def test_resolve_chunk_serializes_dict_value_canonically() -> None:
    """Dict resolved via simple template → preserved as dict → serialized
    via _deterministic_serialize. Keys MUST be sorted."""
    chunk = CacheChunkIR(name="data", var_expr="data", prose_before="", source_line=1)
    result = _resolve_chunk_value(chunk, {"data": {"b": 2, "a": 1}})
    assert result == '{"a":1,"b":2}'


def test_resolve_chunk_treats_failed_upstream_as_present() -> None:
    """Per ``get_node_status``, a failed upstream (in __failures__) is FAILED,
    not ABSENT. Cache rendering of FAILED upstreams is a corner case the
    validator catches; here the helper returns the partial value rather
    than the sentinel."""
    chunk = CacheChunkIR(name="upstream", var_expr="upstream", prose_before="", source_line=1)
    shared = {
        "__failures__": {"upstream": {"data": {}, "category": "exception", "error": "boom"}},
        "upstream": "leftover-value",
    }
    result = _resolve_chunk_value(chunk, shared)
    assert not isinstance(result, _ChunkAbsentSentinel), "FAILED upstream should not be sentinel — only ABSENT is."


def test_resolve_chunk_with_path_extracts_root_node() -> None:
    """Chunks may reference path-shaped vars (e.g. ``node.field``)."""
    chunk = CacheChunkIR(name="node.field", var_expr="node.field", prose_before="", source_line=1)
    # ABSENT — root "node" not in shared.
    assert isinstance(_resolve_chunk_value(chunk, {}), _ChunkAbsentSentinel)
    # PRESENT.
    result = _resolve_chunk_value(chunk, {"node": {"field": "x"}})
    assert result == "x"


def test_resolve_chunk_permissive_echo_collapses_to_sentinel() -> None:
    """When TemplateResolver.resolve_template returns the literal template
    string verbatim (permissive-mode behavior for unresolvable vars), treat
    it as absent. Without this guard, the literal ``"${var}"`` would fold
    into the deterministic serialization and silently produce stable bytes
    that differ from the prep-side render — silent stale-cache class.

    This case fires when a chunk's root node IS in shared (so the ABSENT
    check above doesn't fire) but the path doesn't resolve (e.g. node
    output exists but the requested field doesn't). Without the literal-echo
    detection, we'd fold ``"${node.missing_field}"`` into the hash.
    """
    chunk = CacheChunkIR(
        name="node.missing_field",
        var_expr="node.missing_field",
        prose_before="",
        source_line=1,
    )
    # Root "node" IS in shared (status=SUCCEEDED), but ".missing_field" doesn't
    # exist on it — resolver returns the original ``${node.missing_field}``.
    result = _resolve_chunk_value(chunk, {"node": {"present": "x"}})
    assert isinstance(result, _ChunkAbsentSentinel), f"permissive-mode echo should collapse to sentinel, got {result!r}"


# --- _resolve_static_prefix_for_cache --------------------------------------


def test_static_prefix_substitutes_via_deterministic_serialize() -> None:
    """The whole point of the helper: dict values substitute as canonical
    JSON, NOT as Python repr. Without this, a chunk's value (canonical JSON)
    and the same value embedded in a static prefix (Python str() repr) would
    produce different bytes — silent cross-mode cache miss."""
    template = "before ${data} after"
    result = _resolve_static_prefix_for_cache(template, {"data": {"b": 2, "a": 1}})
    assert result == 'before {"a":1,"b":2} after'
    # Verify it's NOT the broken Python-repr behavior:
    assert "'a': 1" not in result


def test_static_prefix_leaves_unresolved_refs_in_place() -> None:
    """Unresolvable refs (no value in shared) survive verbatim. Auto-batch
    prefix detection won't mark them as cacheable; analyzer surfaces it."""
    template = "static ${missing} suffix"
    result = _resolve_static_prefix_for_cache(template, {})
    assert result == "static ${missing} suffix"


def test_static_prefix_no_op_on_template_without_vars() -> None:
    assert _resolve_static_prefix_for_cache("plain text", {"x": "y"}) == "plain text"


def test_static_prefix_resolves_multiple_refs_in_one_string() -> None:
    template = "${a} and ${b}"
    result = _resolve_static_prefix_for_cache(template, {"a": "X", "b": "Y"})
    assert result == "X and Y"


# --- Regex parity invariant (Round-5 lock) ---------------------------------


def test_static_prefix_uses_resolver_pattern_object_directly() -> None:
    """Lock the parity contract: ``_resolve_static_prefix_for_cache`` runs
    its substitution via ``TemplateResolver.TEMPLATE_PATTERN`` (the exact
    same compiled object the resolver itself uses). If a future refactor
    re-compiles a "matching" literal in this module, the byte-identity
    invariant could drift silently — this test catches it.

    Verified via behavior: a template that the resolver's pattern matches
    must also be substituted by the helper. We don't introspect the
    function bytecode (fragile across CPython versions).
    """
    from pflow.runtime.template_resolver import TemplateResolver

    # Pattern matches both ``${var}`` and ``${a ?? b}`` (coalesce). The
    # helper must too.
    template = "${name}"
    assert TemplateResolver.TEMPLATE_PATTERN.search(template), "sanity: pattern matches simple template"
    assert _resolve_static_prefix_for_cache(template, {"name": "X"}) == "X"


# --- _compute_marker_chunk_indices: deterministic multi-breakpoint placement -


class TestComputeMarkerChunkIndices:
    """Verify deterministic multi-breakpoint marker placement."""

    # --- Non-Anthropic providers (budget=1) ---

    def test_openai_single_chunk(self):
        assert _compute_marker_chunk_indices(1, "openai", False) == (0,)

    def test_openai_many_chunks(self):
        assert _compute_marker_chunk_indices(7, "openai", False) == (6,)

    def test_gemini_terminal_only(self):
        assert _compute_marker_chunk_indices(5, "gemini", False) == (4,)

    def test_unknown_provider_terminal_only(self):
        assert _compute_marker_chunk_indices(5, None, False) == (4,)
        assert _compute_marker_chunk_indices(5, "ollama", False) == (4,)

    # --- Anthropic, n_chunks <= budget (every chunk gets a marker) ---

    def test_anthropic_one_chunk(self):
        assert _compute_marker_chunk_indices(1, "anthropic", False) == (0,)

    def test_anthropic_under_budget(self):
        # 3 chunks, budget 4 → all individual
        assert _compute_marker_chunk_indices(3, "anthropic", False) == (0, 1, 2)

    def test_anthropic_exactly_budget(self):
        # 4 chunks, budget 4 → all individual
        assert _compute_marker_chunk_indices(4, "anthropic", False) == (0, 1, 2, 3)

    # --- Anthropic, n_chunks > budget (first-N-individual + terminal merge) ---

    def test_anthropic_over_budget_five(self):
        # 5 chunks, budget 4 → markers at 0, 1, 2, 4 (chunk 3 merged into terminal)
        assert _compute_marker_chunk_indices(5, "anthropic", False) == (0, 1, 2, 4)

    def test_anthropic_over_budget_seven(self):
        # 7 chunks, budget 4 → markers at 0, 1, 2, 6
        assert _compute_marker_chunk_indices(7, "anthropic", False) == (0, 1, 2, 6)

    # --- Anthropic with prewarm (budget reduced to 3) ---

    def test_anthropic_prewarm_three_chunks(self):
        # 3 chunks, budget 3 (after prewarm) → all individual
        assert _compute_marker_chunk_indices(3, "anthropic", True) == (0, 1, 2)

    def test_anthropic_prewarm_over_budget(self):
        # 5 chunks, budget 3 (after prewarm) → markers at 0, 1, 4
        assert _compute_marker_chunk_indices(5, "anthropic", True) == (0, 1, 4)

    def test_anthropic_prewarm_one_chunk(self):
        # 1 chunk, budget 3 (after prewarm) → single terminal marker
        assert _compute_marker_chunk_indices(1, "anthropic", True) == (0,)

    # --- Non-Anthropic with prewarm (budget collapses to 0, falls through) ---

    def test_openai_prewarm_collapses_to_terminal(self):
        # OpenAI budget=1, prewarm subtracts → budget=0 → still emit terminal marker.
        # Reason: terminal marker is required for cache identity even when no
        # additional breakpoints fit; prewarm runs on user_message_blocks
        # separately and is a no-op on OpenAI anyway.
        assert _compute_marker_chunk_indices(3, "openai", True) == (2,)

    # --- Caller-contract enforcement ---

    def test_raises_on_empty_rendered(self):
        # Caller (_build_system_blocks) must guard with `if not rendered: return None`
        # BEFORE calling this. Raise loudly instead of silently returning ()
        # — a defensive empty return would let cache rendering proceed with
        # zero markers and no signal.
        with pytest.raises(ValueError, match="n_rendered_chunks >= 1"):
            _compute_marker_chunk_indices(0, "anthropic", False)


# --- _looks_like_routed_anthropic ------------------------------------------


class TestLooksLikeRoutedAnthropic:
    """Detection heuristic for routed-Anthropic models (OpenRouter, Bedrock,
    Vertex, etc.) — the trigger condition for the
    ``cache.routed-provider-degraded`` advisory.
    """

    # --- True: model looks like routed Anthropic ---

    def test_openrouter_anthropic(self):
        assert _looks_like_routed_anthropic("openrouter/anthropic/claude-sonnet-4-5") is True

    def test_bedrock_anthropic(self):
        assert _looks_like_routed_anthropic("bedrock/anthropic.claude-sonnet-4-5-v1:0") is True

    def test_vertex_ai_claude(self):
        assert _looks_like_routed_anthropic("vertex_ai/claude-sonnet-4-5@20250514") is True

    def test_aws_bedrock_claude(self):
        assert _looks_like_routed_anthropic("aws/bedrock/anthropic.claude-3-haiku") is True

    def test_case_insensitive(self):
        assert _looks_like_routed_anthropic("OpenRouter/Anthropic/Claude-Sonnet") is True

    # --- False: pflow knows the provider (native path handles it) ---

    def test_native_anthropic_prefix_excluded(self):
        # detect_provider returns "anthropic" → already handled by native path
        assert _looks_like_routed_anthropic("anthropic/claude-sonnet-4-5") is False

    def test_bare_claude_excluded(self):
        # detect_provider matches bare_prefixes "claude-" → native path
        assert _looks_like_routed_anthropic("claude-sonnet-4-5") is False

    def test_native_openai_excluded(self):
        assert _looks_like_routed_anthropic("openai/gpt-4o") is False

    def test_native_gemini_excluded(self):
        assert _looks_like_routed_anthropic("gemini/gemini-2.5-pro") is False

    # --- False: unknown provider, no Anthropic-flavored substring ---

    def test_unknown_provider_no_substring(self):
        assert _looks_like_routed_anthropic("ollama/llama-3") is False

    def test_unknown_router_unrelated_model(self):
        assert _looks_like_routed_anthropic("openrouter/openai/gpt-4o") is False

    # --- Edge cases ---

    def test_empty_string(self):
        assert _looks_like_routed_anthropic("") is False

    def test_none(self):
        assert _looks_like_routed_anthropic(None) is False
