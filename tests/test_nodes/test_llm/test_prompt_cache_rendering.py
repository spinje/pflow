"""C1.2 — LLMNode.prep cache rendering (Anthropic-flavored single-breakpoint).

Both the hash side (``runtime/engine/plan_node._render_cache_for_hash``) and
the prep side (``LLMNode.prep`` in this test) must call the SHARED
``_resolve_chunk_value`` helper from ``pflow.core.cache_render`` and apply the
SAME ``_CHUNK_ABSENT`` filter. If they diverge, memo cache hash is keyed on
bytes A while the adapter sends bytes A' — the silent stale-cache class.

Tests assert on ``mock_llm_client.call_history_full[-1]["system"]`` to
inspect the structured-blocks shape.

Provider coverage in this file is Anthropic only. C2 (Gemini) and C3 (OpenAI)
extend the per-provider TTL translation in companion test files.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from pflow.core.cache_render import CacheBlockIR, CacheChunkIR, CacheRenderContext
from pflow.core.exceptions import UnsupportedCacheTTLError
from pflow.nodes.llm import LLMNode

ANTHROPIC = "anthropic/claude-sonnet-4-5"


# --- Helpers ---------------------------------------------------------------


def _ctx(
    *,
    chunks: list[tuple[str, str]],  # (name, prose_before)
    subset: tuple[str, ...],
    ttl: str | None = None,
    prewarm: bool = False,
) -> CacheRenderContext:
    items = tuple(CacheChunkIR(name=n, var_expr=n, prose_before=p, source_line=0) for n, p in chunks)
    block = CacheBlockIR(ttl=ttl, items=items, source_line=0)
    return CacheRenderContext(
        cache_block=block,
        subset=subset,
        prewarm=prewarm,
        unresolved_batch_prompt=None,
        batch_alias=None,
    )


def _install_cache_render(shared: dict[str, Any], node_id: str, ctx: CacheRenderContext) -> None:
    shared["__pflow_cache_render__"] = MappingProxyType({node_id: ctx})


def _make_node(node_id: str, *, model: str = ANTHROPIC, system: str | None = None) -> LLMNode:
    node = LLMNode()
    node.node_id = node_id  # type: ignore[attr-defined]  # compiler sets this in production
    params: dict[str, Any] = {"prompt": "What is the answer?", "model": model}
    if system is not None:
        params["system"] = system
    node.set_params(params)
    return node


# --- Anthropic: marker shape per TTL ---------------------------------------


def test_anthropic_default_ttl_emits_bare_ephemeral_marker(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",), ttl=None),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    assert sent[-1]["cache_control"] == {"type": "ephemeral"}, "no ttl for default"
    assert "ttl" not in sent[-1]["cache_control"]


def test_anthropic_ttl_5m_emits_bare_ephemeral_marker(mock_llm_client) -> None:
    """Anthropic does NOT accept an explicit ttl: "5m" — only "1h" is documented.
    For ttl=5m the marker is emitted WITHOUT a ttl key (5m IS the default)."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",), ttl="5m"),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    marker = sent[-1]["cache_control"]
    assert marker == {"type": "ephemeral"}
    assert "ttl" not in marker, "Anthropic 5m must NOT emit ttl key"
    assert len(marker) == 1


def test_anthropic_ttl_1h_emits_marker_with_ttl(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",), ttl="1h"),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_anthropic_dynamic_minute_ttl_raises_structured_error(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",), ttl="11m"),
    )

    with pytest.raises(UnsupportedCacheTTLError) as excinfo:
        node.run(shared)

    diag = excinfo.value.to_diagnostics()[0]
    assert diag.id == "cache.unsupported-provider-ttl"
    assert diag.context["ttl_seconds"] == 660


# --- Order, content, and chunk structure -----------------------------------


def test_user_system_prepended_without_marker(mock_llm_client) -> None:
    """User's system param appears as the FIRST block, NO cache_control marker."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", system="Be concise.")
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",)),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    assert sent[0] == {"type": "text", "text": "Be concise."}
    assert "cache_control" not in sent[0]
    # Last block (cache chunk) has the marker
    assert "cache_control" in sent[-1]


def test_chunk_text_is_prose_plus_value(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",)),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1]["text"] == "The concept:\na song about courage"


def test_multi_chunk_declaration_order_preserved(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"a": "alpha-value", "b": "beta-value", "c": "gamma-value"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(
            chunks=[("a", "A:\n"), ("b", "B:\n"), ("c", "C:\n")],
            subset=("a", "b", "c"),
        ),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert [b["text"] for b in sent] == ["A:\nalpha-value", "B:\nbeta-value", "C:\ngamma-value"]
    # Marker on LAST block only
    assert "cache_control" in sent[-1]
    assert "cache_control" not in sent[0]
    assert "cache_control" not in sent[1]


# --- Three-state equivalence: no opt-in falls back to plain string ---------


def test_no_cache_render_falls_back_to_plain_string_system(mock_llm_client) -> None:
    """No __pflow_cache_render__ at all → today's plain-string system path."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", system="Be concise.")
    shared: dict[str, Any] = {}

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["system"] == "Be concise."


def test_empty_subset_falls_back_to_plain_string(mock_llm_client) -> None:
    """prompt_cache: [] → cache_ctx exists but subset is empty → plain string."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", system="Be concise.")
    shared: dict[str, Any] = {}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "")], subset=()),
    )

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["system"] == "Be concise."


def test_no_subset_for_this_node_falls_back_to_plain_string(mock_llm_client) -> None:
    """cache render dict installed for OTHER nodes; this node has no entry."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", system="Be concise.")
    shared: dict[str, Any] = {}
    other_ctx = _ctx(chunks=[("concept", "")], subset=("concept",))
    shared["__pflow_cache_render__"] = MappingProxyType({"some-other-node": other_ctx})

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["system"] == "Be concise."


# --- Branch-absent: skip chunks via _CHUNK_ABSENT filter -------------------


def test_branch_absent_chunk_silently_skipped(mock_llm_client) -> None:
    """A chunk whose ${var} is unresolvable (upstream node ABSENT or permissive
    echo) is filtered. Remaining chunks render. Marker placed on the
    SHORTENED list's last chunk."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    # ``a`` resolves; ``b`` references an unresolved/absent value (no entry)
    shared: dict[str, Any] = {"a": "alpha-value"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(
            chunks=[("a", "A:\n"), ("b", "B:\n")],
            subset=("a", "b"),
        ),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    assert len(sent) == 1
    assert sent[0]["text"] == "A:\nalpha-value"
    assert "cache_control" in sent[0]


def test_branch_absent_records_skipped_chunk_in_llm_usage(mock_llm_client) -> None:
    """``cache_chunks_skipped`` is exposed via shared['llm_usage'] so the
    trace 2.1.0 channel (E.1) can attribute discrepancies to runtime branch
    skips (vs TTL expiry, key mismatch, parallel-write race)."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared: dict[str, Any] = {"a": "alpha-value"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(
            chunks=[("a", "A:\n"), ("b", "B:\n")],
            subset=("a", "b"),
        ),
    )

    node.run(shared)

    assert shared["llm_usage"]["cache_chunks_skipped"] == ["b"]


def test_no_skipped_chunks_writes_empty_list(mock_llm_client) -> None:
    """Default empty list when no chunks are skipped — the field always exists
    in llm_usage so downstream consumers don't have to check existence."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"a": "alpha-value"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("a", "A:\n")], subset=("a",)),
    )

    node.run(shared)

    assert shared["llm_usage"]["cache_chunks_skipped"] == []


def test_all_chunks_absent_falls_back_to_plain_string(mock_llm_client) -> None:
    """If every chunk in the subset is absent, system_blocks would degenerate.
    Fall back to today's plain-string system path; record all skips."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", system="Be concise.")
    shared: dict[str, Any] = {}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(
            chunks=[("a", "A:\n"), ("b", "B:\n")],
            subset=("a", "b"),
        ),
    )

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["system"] == "Be concise."
    assert shared["llm_usage"]["cache_chunks_skipped"] == ["a", "b"]


# --- Cache layer independence: prompt_cache survives cache: false ----------


def test_prompt_cache_independent_of_cache_false(mock_llm_client) -> None:
    """`cache: false` opts a node out of pflow's MEMO cache. It does NOT
    disable LLM-provider prompt caching. The system_blocks must still carry
    cache_control markers regardless of the memo opt-out."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "The concept:\n")], subset=("concept",)),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    assert "cache_control" in sent[-1]


# --- Dict / list / non-string resolved values: deterministic serialize -----


def test_dict_value_serialized_as_canonical_json(mock_llm_client) -> None:
    """A chunk that resolves to a dict gets canonical-JSON serialized so the
    bytes are stable across dict-insertion-order variations. Locks the
    byte-identity invariant for hash-vs-prep equivalence."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"concept": {"theme": "courage", "genre": "ballad"}}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",)),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    # sorted-keys, compact separators
    assert sent[-1]["text"] == 'Concept:\n{"genre":"ballad","theme":"courage"}'


def test_list_value_serialized_as_canonical_json(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics")
    shared = {"items": [1, 2, 3]}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("items", "Items:\n")], subset=("items",)),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1]["text"] == "Items:\n[1,2,3]"


# --- Local module bindings: divergence-injection meta-test -----------------


def _import_module(dotted: str) -> Any:
    """Import a submodule that may be shadowed on its parent's namespace.

    ``from .plan_node import plan_node`` in ``pflow/runtime/engine/__init__.py``
    shadows the ``plan_node`` *submodule* with the *function* of the same
    name. The submodule is still in ``sys.modules`` — fetch it from there.
    """
    import importlib

    return importlib.import_module(dotted)


def test_resolve_chunk_value_is_imported_locally_at_both_sites() -> None:
    """Both ``plan_node._render_cache_for_hash`` and ``LLMNode.prep`` must
    expose ``_resolve_chunk_value`` as a LOCAL module attribute pointing at
    the canonical helper from ``pflow.core.cache_render``.

    This identity check catches "Break B": one site reimports the helper
    from a different location. It does NOT catch "Break A" (one site inlines
    a divergent implementation while still keeping the import) — that's
    structurally undetectable without AST scanning.
    """
    llm_module = _import_module("pflow.nodes.llm.llm")
    plan_node_module = _import_module("pflow.runtime.engine.plan_node")

    # Both modules must expose ``_resolve_chunk_value`` as a local attribute
    # (set up by ``from pflow.core.cache_render import _resolve_chunk_value``).
    assert hasattr(llm_module, "_resolve_chunk_value")
    assert hasattr(plan_node_module, "_resolve_chunk_value")
    # And both must point at the same function object (same shared helper).
    assert llm_module._resolve_chunk_value is plan_node_module._resolve_chunk_value


def test_chunk_absent_sentinel_class_is_shared(mock_llm_client) -> None:
    """The ABSENT-filter sentinel class must be the SAME class at both
    sites — otherwise ``isinstance`` filter breaks asymmetrically."""
    llm_module = _import_module("pflow.nodes.llm.llm")
    plan_node_module = _import_module("pflow.runtime.engine.plan_node")

    assert llm_module._ChunkAbsentSentinel is plan_node_module._ChunkAbsentSentinel


# --- Hash-vs-prep render byte equivalence ----------------------------------
# The top-level-keys-only sibling of this invariant lived here historically; it
# was deleted because the production-shape variant at
# ``test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store``
# (Bug #2 regression block, below) covers the same chunk-by-chunk byte-equality
# under the wrap engine.py:471 actually applies. The synthetic-dict version was
# the same shape that hid Bug #2.


def test_hash_render_and_prep_render_byte_equivalent_with_absent_chunks(mock_llm_client) -> None:
    """The byte-identity invariant must hold when SOME chunks resolve to
    ``_CHUNK_ABSENT``. Both sites filter the sentinel symmetrically, so the
    rendered subset has the SAME chunks dropped at both sides — hash bytes
    and prep bytes still match across the surviving chunks.

    Concrete failure mode this test catches: one site forgets to filter the
    sentinel, so its rendered list includes the absent chunk's prose with a
    placeholder value, while the other site filters and produces a shorter
    list. Same logical state → different bytes → silent stale-cache class.
    """
    from pflow.runtime.engine.plan_node import _render_cache_for_hash
    from pflow.runtime.engine.types import NodeConfig

    mock_llm_client.set_response("*", None, "ok")
    # ``a`` and ``c`` resolve; ``b`` is structurally absent (no entry in
    # shared, no upstream node — permissive-echo path returns ``_CHUNK_ABSENT``).
    shared = {"a": "alpha", "c": [1, 2]}
    cache_ctx = _ctx(
        chunks=[("a", "A:\n"), ("b", "B:\n"), ("c", "C:\n")],
        subset=("a", "b", "c"),
    )
    _install_cache_render(shared, "write-lyrics", cache_ctx)

    # Hash side
    config = NodeConfig(
        node_id="write-lyrics",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=True,
        interface_metadata=None,
        prompt_cache_items=("a", "b", "c"),
        prewarm=False,
    )
    hash_rendered = _render_cache_for_hash(config, shared)
    assert hash_rendered is not None
    # ``b`` was filtered → only 2 chunks survive at the hash side.
    assert len(hash_rendered) == 2
    hash_texts = [h["prose"] + h["value"] for h in hash_rendered]

    # Prep side
    node = _make_node("write-lyrics")
    node.run(shared)
    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    # Prep side filtered ``b`` symmetrically.
    assert len(sent) == 2
    prep_texts = [b["text"] for b in sent]

    # Same 2 chunks at both sides, byte-identical.
    assert hash_texts == prep_texts
    # And ``b`` was recorded as skipped in the trace channel.
    assert shared["llm_usage"]["cache_chunks_skipped"] == ["b"]


# --- Error-path: cache_chunks_skipped survives every error path -----------


def test_cache_chunks_skipped_survives_call_llm_error(monkeypatch, mock_llm_client) -> None:
    """When the LLM call fails with a deterministic LLMCallError, the err_dict's
    ``usage["cache_chunks_skipped"]`` is threaded into ``shared["llm_usage"]``
    by ``_propagate_error_to_shared`` so trace 2.1.0 records runtime branch-
    skips even on failure paths.

    Pre-fix the wrap was dead code: ``_propagate_error_to_shared`` zeroed
    ``shared["llm_usage"] = {}`` unconditionally, so the field never reached
    trace events. Post-fix the field rides through the seam.
    """
    from pflow.core.exceptions import UnknownModelError

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise UnknownModelError("bogus", model=ANTHROPIC)

    mock_llm_client.set_response("*", None, "ok")
    monkeypatch.setattr("pflow.nodes.llm.llm.complete", _raise)

    node = _make_node("write-lyrics")
    shared: dict[str, Any] = {"a": "alpha"}  # only "a" resolves; "b" is ABSENT
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("a", "A:\n"), ("b", "B:\n")], subset=("a", "b")),
    )
    node.run(shared)

    # Error path fired AND cache_chunks_skipped threaded into shared.
    assert shared.get("error") is not None
    assert shared["llm_usage"] == {"cache_chunks_skipped": ["b"]}


def test_cache_chunks_skipped_empty_list_keeps_legacy_zero_usage(monkeypatch, mock_llm_client) -> None:
    """Backward-compat: when no chunks were skipped (empty list), error path
    zeroes ``llm_usage`` to ``{}`` — same as pre-Task-159 behavior. Only
    non-empty skip lists trigger preservation. Avoids regressing the four
    pre-existing ``assert shared["llm_usage"] == {}`` tests in test_llm.py."""
    from pflow.core.exceptions import UnknownModelError

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise UnknownModelError("bogus", model=ANTHROPIC)

    mock_llm_client.set_response("*", None, "ok")
    monkeypatch.setattr("pflow.nodes.llm.llm.complete", _raise)

    node = _make_node("write-lyrics")
    shared: dict[str, Any] = {"a": "alpha"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("a", "A:\n")], subset=("a",)),  # no absent chunks
    )
    node.run(shared)

    assert shared["llm_usage"] == {}


def test_cache_chunks_skipped_survives_exec_fallback(monkeypatch, mock_llm_client) -> None:
    """When all retries are exhausted via LLMTransientError, ``exec_fallback``
    builds the err_dict with the cache_chunks_skipped wrap. The fix threads
    the field into shared so the trace event records runtime branch-skips."""
    from pflow.core.exceptions import LLMTransientError

    def _raise_transient(*args: Any, **kwargs: Any) -> Any:
        raise LLMTransientError("flaky", model=ANTHROPIC, kind="connection")

    mock_llm_client.set_response("*", None, "ok")
    monkeypatch.setattr("pflow.nodes.llm.llm.complete", _raise_transient)

    node = LLMNode(max_retries=1, wait=0.0)  # no retries to keep test fast
    node.node_id = "write-lyrics"  # type: ignore[attr-defined]
    node.set_params({"prompt": "hi", "model": ANTHROPIC})
    shared: dict[str, Any] = {"a": "alpha"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("a", "A:\n"), ("b", "B:\n")], subset=("a", "b")),
    )
    node.run(shared)

    assert shared.get("error") is not None
    assert shared["llm_usage"] == {"cache_chunks_skipped": ["b"]}


# --- Output schema + cache + extended thinking compose cleanly -------------


def test_structured_output_schema_does_not_displace_cache_marker(mock_llm_client) -> None:
    """When a node has both ``output_schema`` (structured-output tools) AND
    ``prompt_cache:``, the cache_control marker on the system blocks must
    not be displaced or overwritten by the schema injection path."""
    mock_llm_client.set_response("*", {"type": "object", "properties": {}}, '{"x": 1}')
    node = LLMNode()
    node.node_id = "write-lyrics"  # type: ignore[attr-defined]
    node.set_params({
        "prompt": "Return JSON.",
        "model": ANTHROPIC,
        "output_schema": {"type": "object", "properties": {}},
    })
    shared = {"a": "alpha"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("a", "A:\n")], subset=("a",)),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    assert sent[-1]["cache_control"] == {"type": "ephemeral"}


# --- node_id missing: graceful no-op (defensive) ---------------------------


def test_node_without_node_id_skips_cache_rendering(mock_llm_client) -> None:
    """When node_id isn't set (e.g., a unit test that skips the compiler),
    cache rendering must skip cleanly — not crash."""
    mock_llm_client.set_response("*", None, "ok")
    node = LLMNode()
    # Deliberately do NOT set node.node_id
    node.set_params({"prompt": "hi", "model": ANTHROPIC})
    shared: dict[str, Any] = {}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("a", "A:\n")], subset=("a",)),
    )

    node.run(shared)  # must not raise

    # Falls back to plain string (no system on this node)
    assert mock_llm_client.call_history_full[-1]["system"] is None


# --- Helper-level marker shape unit tests ---------------------------------


def test_build_cache_control_marker_anthropic_default() -> None:
    from pflow.core.cache_render import _build_cache_control_marker

    assert _build_cache_control_marker("anthropic", None) == {"type": "ephemeral"}


def test_build_cache_control_marker_anthropic_5m_omits_ttl() -> None:
    from pflow.core.cache_render import _build_cache_control_marker

    marker = _build_cache_control_marker("anthropic", "5m")
    assert marker == {"type": "ephemeral"}
    assert "ttl" not in marker


def test_build_cache_control_marker_anthropic_1h() -> None:
    from pflow.core.cache_render import _build_cache_control_marker

    assert _build_cache_control_marker("anthropic", "1h") == {"type": "ephemeral", "ttl": "1h"}
    assert _build_cache_control_marker("anthropic", "60m") == {"type": "ephemeral", "ttl": "1h"}


def test_build_cache_control_marker_unknown_provider_emits_bare() -> None:
    """Unknown / out-of-vocab provider gets a bare ephemeral marker (no ttl).
    Graceful no-op for providers without explicit cache support."""
    from pflow.core.cache_render import _build_cache_control_marker

    assert _build_cache_control_marker(None, "1h") == {"type": "ephemeral"}
    assert _build_cache_control_marker("ollama", "1h") == {"type": "ephemeral"}


# --- Phase C2 — Gemini TTL marker translation -----------------------------

GEMINI = "gemini/gemini-2.5-flash"


def test_gemini_default_ttl_emits_300s_marker(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=GEMINI)
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl=None),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1]["cache_control"] == {"type": "ephemeral", "ttl": "300s"}


def test_gemini_ttl_5m_emits_300s_marker(mock_llm_client) -> None:
    """LiteLLM's Vertex translation requires seconds notation with ``s``
    suffix; Gemini ``cachedContents`` API uses raw seconds."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=GEMINI)
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl="5m"),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1]["cache_control"] == {"type": "ephemeral", "ttl": "300s"}


def test_gemini_ttl_1h_emits_3600s_marker(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=GEMINI)
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl="1h"),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1]["cache_control"] == {"type": "ephemeral", "ttl": "3600s"}


@pytest.mark.parametrize(
    ("ttl", "wire_ttl"),
    [
        ("1m", "60s"),
        ("11m", "660s"),
        ("55m", "3300s"),
        ("60m", "3600s"),
    ],
)
def test_gemini_dynamic_minute_ttl_emits_seconds_marker(mock_llm_client, ttl: str, wire_ttl: str) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=GEMINI)
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl=ttl),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert sent[-1]["cache_control"] == {"type": "ephemeral", "ttl": wire_ttl}


def test_build_cache_control_marker_gemini_default() -> None:
    from pflow.core.cache_render import _build_cache_control_marker

    assert _build_cache_control_marker("gemini", None) == {"type": "ephemeral", "ttl": "300s"}


def test_build_cache_control_marker_gemini_5m_seconds_suffix() -> None:
    from pflow.core.cache_render import _build_cache_control_marker

    assert _build_cache_control_marker("gemini", "5m") == {"type": "ephemeral", "ttl": "300s"}


def test_build_cache_control_marker_gemini_1h_seconds_suffix() -> None:
    from pflow.core.cache_render import _build_cache_control_marker

    assert _build_cache_control_marker("gemini", "1h") == {"type": "ephemeral", "ttl": "3600s"}
    assert _build_cache_control_marker("gemini", "60m") == {"type": "ephemeral", "ttl": "3600s"}


# Note: the Gemini multi-marker collapse test (when Phase D auto-batch-prefix
# adds a second marker — Gemini provider-side collapses to the latest only,
# pflow doesn't filter) lives in test_batch_cache_prefix.py once D.1 lands.


# --- Phase C3 — OpenAI prompt_cache_key + prompt_cache_retention ----------

OPENAI = "openai/gpt-4o-mini"


def test_openai_emits_prompt_cache_key_when_subset_non_empty(mock_llm_client) -> None:
    """OpenAI's auto-cache benefits from sticky routing via ``prompt_cache_key``;
    pflow emits an MD5 of the rendered cache content so identical-prefix calls
    hit the same backend instance (per OpenAI's documented behavior, ~15 RPM
    soft cap)."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=OPENAI)
    shared = {"concept": "a song about courage"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",)),
    )

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"]
    assert options is not None
    assert "prompt_cache_key" in options
    assert isinstance(options["prompt_cache_key"], str)
    # MD5 hex is 32 chars
    assert len(options["prompt_cache_key"]) == 32


def test_openai_prompt_cache_key_deterministic_across_calls(mock_llm_client) -> None:
    """Two LLM calls with byte-identical cache content must produce the same
    prompt_cache_key — that's the load-bearing routing invariant."""
    mock_llm_client.set_response("*", None, "ok")
    shared = {"concept": "a song about courage"}

    node1 = _make_node("write-lyrics", model=OPENAI)
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",)),
    )
    node1.run(shared)
    key1 = mock_llm_client.call_history_full[-1]["model_options"]["prompt_cache_key"]

    node2 = _make_node("rewrite-emotional", model=OPENAI)
    _install_cache_render(
        shared,
        "rewrite-emotional",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",)),
    )
    node2.run(shared)
    key2 = mock_llm_client.call_history_full[-1]["model_options"]["prompt_cache_key"]

    assert key1 == key2


def test_openai_prompt_cache_key_differs_for_different_content(mock_llm_client) -> None:
    """Different cache content → different prompt_cache_key (no collisions)."""
    mock_llm_client.set_response("*", None, "ok")

    # Run 1: concept = "courage"
    node1 = _make_node("write-lyrics", model=OPENAI)
    shared1 = {"concept": "courage"}
    _install_cache_render(
        shared1,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",)),
    )
    node1.run(shared1)
    key1 = mock_llm_client.call_history_full[-1]["model_options"]["prompt_cache_key"]

    # Run 2: concept = "loss"
    node2 = _make_node("write-lyrics", model=OPENAI)
    shared2 = {"concept": "loss"}
    _install_cache_render(
        shared2,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",)),
    )
    node2.run(shared2)
    key2 = mock_llm_client.call_history_full[-1]["model_options"]["prompt_cache_key"]

    assert key1 != key2


def test_openai_no_prompt_cache_key_without_subset(mock_llm_client) -> None:
    """No prompt_cache opt-in → no cache key leaks into model_options."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=OPENAI)
    shared: dict[str, Any] = {}

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"]
    # Either None or an empty dict — both indicate no cache kwargs.
    assert not options or "prompt_cache_key" not in options


def test_openai_prompt_cache_retention_24h_for_ttl_1h(mock_llm_client) -> None:
    """Per DD#37: pflow ``- ttl: 1h`` maps to OpenAI ``prompt_cache_retention:
    "24h"`` (the closest discrete bucket above 1h). Without this, the default
    ``in_memory`` (5-10 min idle) would silently violate the user's explicit
    1h opt-in (no-silent-behavior-changes principle)."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=OPENAI)
    shared = {"concept": "a song"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl="1h"),
    )

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"]
    assert options.get("prompt_cache_retention") == "24h"


def test_openai_prompt_cache_retention_24h_for_ttl_60m(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=OPENAI)
    shared = {"concept": "a song"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl="60m"),
    )

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"]
    assert options.get("prompt_cache_retention") == "24h"


def test_openai_no_prompt_cache_retention_for_default_ttl(mock_llm_client) -> None:
    """Default / 5m TTL → no retention parameter (matches OpenAI default
    ``in_memory``). Only ``ttl: 1h`` triggers the 24h override."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=OPENAI)
    shared = {"concept": "a song"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl=None),
    )

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"] or {}
    assert "prompt_cache_retention" not in options


def test_openai_no_prompt_cache_retention_for_5m(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=OPENAI)
    shared = {"concept": "a song"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl="5m"),
    )

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"] or {}
    assert "prompt_cache_retention" not in options


def test_openai_user_provided_model_options_preserved(mock_llm_client) -> None:
    """User's existing model_options must not be clobbered by C3's cache
    knob injection. Both coexist in the merged dict."""
    mock_llm_client.set_response("*", None, "ok")
    node = LLMNode()
    node.node_id = "write-lyrics"  # type: ignore[attr-defined]
    node.set_params({
        "prompt": "hi",
        "model": OPENAI,
        "model_options": {"frequency_penalty": 0.5},
    })
    shared = {"concept": "a song"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl="1h"),
    )

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"]
    assert options["frequency_penalty"] == 0.5
    assert options["prompt_cache_key"] is not None
    assert options["prompt_cache_retention"] == "24h"


def test_openai_no_cache_keys_for_anthropic_node(mock_llm_client) -> None:
    """OpenAI-specific knobs must not leak into non-OpenAI requests."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=ANTHROPIC)  # not OPENAI
    shared = {"concept": "a song"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",), ttl="1h"),
    )

    node.run(shared)

    options = mock_llm_client.call_history_full[-1]["model_options"] or {}
    assert "prompt_cache_key" not in options
    assert "prompt_cache_retention" not in options


def test_openai_still_emits_system_blocks(mock_llm_client) -> None:
    """OpenAI auto-cache reads the prefix from the request body. We still
    emit structured system_blocks so the prefix is byte-stable across calls."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("write-lyrics", model=OPENAI)
    shared = {"concept": "a song"}
    _install_cache_render(
        shared,
        "write-lyrics",
        _ctx(chunks=[("concept", "Concept:\n")], subset=("concept",)),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list)
    assert sent[-1]["text"] == "Concept:\na song"


# --- Bug #2 regression (Task 159 verification 2026-04-30) -------------------
# Production wraps shared in NamespacedSharedStore for node._run; the prior
# byte-equivalence tests called node.run(raw_dict) and so missed the broken
# dotted-path resolution path that the proxy exposed. Lock the production
# execution shape here.


def test_dotted_path_chunk_resolves_through_namespaced_shared_store(mock_llm_client) -> None:
    """LLMNode.prep receives ``shared`` as ``NamespacedSharedStore``. A cache
    chunk referencing an upstream node output via dotted path
    (``${node.field}``) MUST render the upstream value into system_blocks and
    NOT silently mark it ABSENT. Pre-fix this filtered the chunk and the LLM
    received a cache prefix missing the most important content."""
    from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("emit")
    raw_shared = {
        "topic": "hello",
        "upstream": {"response": "important upstream content"},
        "emit": {},
    }
    _install_cache_render(
        raw_shared,
        "emit",
        _ctx(
            chunks=[("topic", "Topic:\n"), ("upstream.response", "Upstream:\n")],
            subset=("topic", "upstream.response"),
        ),
    )

    # Production wrap — engine.py:471
    store = NamespacedSharedStore(raw_shared, "emit")
    node.run(store)

    sent = mock_llm_client.call_history_full[-1]["system"]
    assert isinstance(sent, list), "system_blocks must be a list when cache is rendered"
    assert len(sent) == 2, f"both chunks must render, got {len(sent)}"
    # Both chunks present in declaration order
    assert sent[0]["text"] == "Topic:\nhello"
    assert sent[1]["text"] == "Upstream:\nimportant upstream content"
    # cache_chunks_skipped on llm_usage must be empty (no chunk was filtered)
    assert raw_shared["emit"]["llm_usage"]["cache_chunks_skipped"] == []


def test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store(mock_llm_client) -> None:
    """The DD#19 hash-vs-prep byte-identity invariant must hold under the
    production execution shape: hash side calls ``_render_cache_for_hash``
    against the engine's raw shared dict; prep side calls
    ``_build_system_blocks`` against the per-node ``NamespacedSharedStore``.
    Pre-fix these diverged silently for any dotted-path chunk."""
    from pflow.runtime.engine.namespaced_store import NamespacedSharedStore
    from pflow.runtime.engine.plan_node import _render_cache_for_hash
    from pflow.runtime.engine.types import NodeConfig

    mock_llm_client.set_response("*", None, "ok")
    raw_shared = {
        "topic": "hello",
        "upstream": {"response": "important upstream content"},
        "emit": {},
    }
    cache_ctx = _ctx(
        chunks=[("topic", "Topic:\n"), ("upstream.response", "Upstream:\n")],
        subset=("topic", "upstream.response"),
    )
    _install_cache_render(raw_shared, "emit", cache_ctx)

    # Hash side — receives raw dict
    config = NodeConfig(
        node_id="emit",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=True,
        interface_metadata=None,
        prompt_cache_items=("topic", "upstream.response"),
        prewarm=False,
    )
    hash_rendered = _render_cache_for_hash(config, raw_shared)
    assert hash_rendered is not None
    hash_texts = [h["prose"] + h["value"] for h in hash_rendered]

    # Prep side — receives NamespacedSharedStore (production shape)
    store = NamespacedSharedStore(raw_shared, "emit")
    node = _make_node("emit")
    node.run(store)
    sent = mock_llm_client.call_history_full[-1]["system"]
    prep_texts = [b["text"] for b in sent]

    assert hash_texts == prep_texts, f"hash-vs-prep byte divergence:\n  hash: {hash_texts!r}\n  prep: {prep_texts!r}"
