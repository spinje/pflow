"""D.1 — Auto-batch-prefix detection in ``LLMNode.prep``.

When a batch LLM node has ``prewarm: true`` and a static prefix in its raw
prompt template, ``prep()`` resolves the static portion deterministically
and emits ``prep_res["user_message_blocks"]`` with a per-provider
``cache_control`` marker on the static prefix block. The dynamic suffix
follows the marker as a separate block (no marker — varies per item).

Static-prefix resolution MUST go through
``_resolve_static_prefix_for_cache`` so dict/list refs in the static
portion produce canonical-JSON bytes (NOT Python repr). This is the load-
bearing trade-off: cache prefix bytes match the chunk hash bytes for the
same logical value (B3.3 hash-vs-prep byte-identity invariant), so cache
hits fire reliably across calls.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from pflow.core.prompt_cache import CacheBlockIR, CacheChunkIR, CacheRenderContext
from pflow.nodes.llm import LLMNode

ANTHROPIC = "anthropic/claude-sonnet-4-5"
GEMINI = "gemini/gemini-2.5-flash"


@pytest.fixture(autouse=True)
def _bypass_below_min_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests assert on the rendered auto-batch-prefix block shape; they
    intentionally use tiny fixture content. The runtime pre-dispatch strip
    would otherwise remove the markers and break shape assertions. The
    strip itself is exercised in ``test_prompt_cache_below_min_runtime.py``.
    """
    monkeypatch.setattr("pflow.nodes.llm.llm._count_text_tokens", lambda text, model: 10_000)


def _ctx_batch(
    *,
    unresolved_prompt: str,
    batch_alias: str = "item",
    prewarm: bool = True,
    chunks: list[tuple[str, str]] | None = None,
    subset: tuple[str, ...] = (),
    ttl: str | None = None,
) -> CacheRenderContext:
    items = tuple(CacheChunkIR(name=n, var_expr=n, prose_before=p, source_line=0) for n, p in (chunks or []))
    # Block exists when items OR ttl is set (a workflow-level ## Cache
    # declaration with ``- ttl:`` carries the ttl through to the auto-batch
    # marker even when the prewarm batch node doesn't subscribe via
    # ``prompt_cache:`` — consistent with the spec TTL translation table).
    block = CacheBlockIR(ttl=ttl, items=items, source_line=0) if (items or ttl is not None) else None
    return CacheRenderContext(
        cache_block=block,
        subset=subset,
        prewarm=prewarm,
        unresolved_batch_prompt=unresolved_prompt,
        batch_alias=batch_alias,
    )


def _install_prompt_cache(shared: dict[str, Any], node_id: str, ctx: CacheRenderContext) -> None:
    shared["__pflow_prompt_cache__"] = MappingProxyType({node_id: ctx})


def _make_node(node_id: str, *, model: str = ANTHROPIC, resolved_prompt: str = "Score this: hello") -> LLMNode:
    node = LLMNode()
    node.node_id = node_id  # type: ignore[attr-defined]
    node.set_params({"prompt": resolved_prompt, "model": model})
    return node


# --- Gating: prewarm + non-trivial static prefix → marker ------------------


def test_prewarm_batch_with_static_prefix_emits_user_message_blocks(mock_llm_client) -> None:
    """Batch LLM node + prewarm=True + non-trivial static prefix → user
    message is split into [static-prefix-with-marker, dynamic-suffix]."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        resolved_prompt="Rubric: be brief.\n\nScore this chorus: hello world",
    )
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Rubric: be brief.\n\nScore this chorus: ${item.text}",
        ),
    )

    node.run(shared)

    sent_blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert sent_blocks is not None
    assert len(sent_blocks) == 2
    # Block 0: static prefix with marker
    assert sent_blocks[0]["text"] == "Rubric: be brief.\n\nScore this chorus: "
    assert sent_blocks[0]["cache_control"] == {"type": "ephemeral"}
    # Block 1: dynamic suffix, no marker
    assert sent_blocks[1]["text"] == "hello world"
    assert "cache_control" not in sent_blocks[1]


def test_prewarm_batch_without_unresolved_template_skips(mock_llm_client) -> None:
    """No unresolved_batch_prompt set → not a batch node from prompt_cache's
    perspective; auto-batch-prefix doesn't fire."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("score-choruses", resolved_prompt="Score this: hello")
    shared: dict[str, Any] = {}
    ctx = CacheRenderContext(
        cache_block=None,
        subset=(),
        prewarm=True,
        unresolved_batch_prompt=None,  # not a batch node
        batch_alias=None,
    )
    _install_prompt_cache(shared, "score-choruses", ctx)

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["user_message_blocks"] is None


def test_prewarm_false_skips_auto_batch_prefix(mock_llm_client) -> None:
    """prewarm=False → no auto-batch-prefix marker even with a static prefix.
    Spec DD#9: auto batch-prefix fires ONLY when prewarm: true is declared."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("score-choruses", resolved_prompt="Static: hello")
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Static: ${item.text}",
            prewarm=False,
        ),
    )

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["user_message_blocks"] is None


def test_no_cache_ctx_skips_auto_batch_prefix(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("score-choruses", resolved_prompt="Static: hello")
    shared: dict[str, Any] = {}

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["user_message_blocks"] is None


# --- Edge cases: no batch ref, batch ref at position 0 ---------------------


def test_no_batch_alias_reference_in_template_skips(mock_llm_client) -> None:
    """Whole prompt is static (no ${item.X}) → no boundary to mark."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("score-choruses", resolved_prompt="Static prompt only")
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(unresolved_prompt="Static prompt only"),  # no ${item.X}
    )

    node.run(shared)

    # No user_message_blocks emitted; full prompt goes through standard path.
    assert mock_llm_client.call_history_full[-1]["user_message_blocks"] is None


def test_batch_ref_at_position_zero_skips(mock_llm_client) -> None:
    """${item.X} at the very start → no static portion → skip.
    F2 will emit cache.prewarm-no-prefix in the analytical tier; runtime emits
    nothing (DD#36)."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node("score-choruses", resolved_prompt="hello world")
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(unresolved_prompt="${item.text}"),
    )

    node.run(shared)

    assert mock_llm_client.call_history_full[-1]["user_message_blocks"] is None


def test_non_batch_ref_before_batch_alias_does_not_break_detection(mock_llm_client) -> None:
    """A ${non-batch-ref} earlier in the template doesn't shift the boundary;
    the cut is at the FIRST ${batch_alias.X} match."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        resolved_prompt="Rubric for SongOfHope: detailed text. Now score: hello",
    )
    shared = {"workflow_name": "SongOfHope"}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Rubric for ${workflow_name}: detailed text. Now score: ${item.text}",
        ),
    )

    node.run(shared)

    blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert blocks is not None
    assert len(blocks) == 2
    # Static prefix has the non-batch ref resolved (deterministically — for
    # plain strings this matches the standard resolver byte-for-byte).
    assert blocks[0]["text"] == "Rubric for SongOfHope: detailed text. Now score: "
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "hello"


# --- Per-provider TTL on the auto-batch-prefix marker ----------------------


def test_anthropic_auto_batch_prefix_marker_with_ttl_1h(mock_llm_client) -> None:
    """The auto-batch-prefix marker uses the same workflow ttl as the
    declared cache (per the per-provider translation table)."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        resolved_prompt="Rubric: brief\n\nScore: hello",
    )
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Rubric: brief\n\nScore: ${item.text}",
            chunks=[("workflow_name", "")],
            subset=(),
            ttl="1h",
        ),
    )

    node.run(shared)

    blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert blocks is not None
    assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_gemini_auto_batch_prefix_marker_uses_seconds(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        model=GEMINI,
        resolved_prompt="Rubric: brief\n\nScore: hello",
    )
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Rubric: brief\n\nScore: ${item.text}",
            ttl="5m",
        ),
    )

    node.run(shared)

    blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert blocks is not None
    assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "300s"}


def test_gemini_auto_batch_prefix_marker_uses_dynamic_ttl_seconds(mock_llm_client) -> None:
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        model=GEMINI,
        resolved_prompt="Rubric: brief\n\nScore: hello",
    )
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Rubric: brief\n\nScore: ${item.text}",
            ttl="11m",
        ),
    )

    node.run(shared)

    blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert blocks is not None
    assert blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "660s"}


# --- Combined: declared cache + auto-batch-prefix → both markers fire ------


def test_declared_cache_plus_auto_batch_prefix_both_markers_emitted(mock_llm_client) -> None:
    """A node with prompt_cache: [...] AND prewarm: true gets BOTH markers:
    one on the system_blocks (declared) and one on the user_message_blocks
    (auto-batch). Anthropic accepts up to 4; Gemini collapses to last (provider
    behavior, not pflow's responsibility)."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        resolved_prompt="Rubric.\n\nScore: hello",
    )
    shared = {"concept": "courage"}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Rubric.\n\nScore: ${item.text}",
            chunks=[("concept", "Concept:\n")],
            subset=("concept",),
        ),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]
    # Declared cache → system_blocks with marker
    assert isinstance(sent["system"], list)
    assert "cache_control" in sent["system"][-1]
    # Auto-batch-prefix → user_message_blocks with marker
    blocks = sent["user_message_blocks"]
    assert blocks is not None
    assert "cache_control" in blocks[0]
    assert "cache_control" not in blocks[1]


# --- Static-prefix uses deterministic serialize for embedded refs ----------


def test_static_prefix_resolves_dict_via_canonical_json(mock_llm_client) -> None:
    """A ``${dict_var}`` in the static portion must serialize as canonical
    compact JSON via ``_resolve_static_prefix_for_cache`` — sorted keys,
    no spaces. The standard ``TemplateResolver`` produces JSON-WITH-spaces
    for dict values in complex templates; the cache path uses the deterministic
    helper instead so the prefix bytes match the chunk-hash bytes for the
    same logical value (B3.3 hash-vs-prep byte-identity invariant)."""
    mock_llm_client.set_response("*", None, "ok")
    # Standard resolver renders {"k": "v"} as JSON-with-space — this is what
    # the engine populates as the resolved prompt today. The cache path
    # diverges (no space) for byte-identity with the chunk hash.
    node = _make_node(
        "score-choruses",
        resolved_prompt='Context: {"k": "v"}\nScore: hello',
    )
    shared = {"concept": {"k": "v"}}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Context: ${concept}\nScore: ${item.text}",
        ),
    )

    node.run(shared)

    blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert blocks is not None
    # Cache-path canonical bytes: compact JSON, sorted keys, NO spaces.
    assert blocks[0]["text"] == 'Context: {"k":"v"}\nScore: '
    # Suffix taken from standard-resolved prompt (post fall-back path).
    assert blocks[1]["text"] == "hello"


# --- N=1 batch (single item) skip-then-fan-out is structurally a no-op ----
# (N=1 prewarm semantics are tested at D.2; D.1 just ensures the marker
# emission is correct regardless of item count, since prep runs per-item.)


# --- _build_messages contract — user_message_blocks dispatches correctly --


def test_build_messages_uses_user_message_blocks_when_set() -> None:
    from pflow.core.llm_client import _build_messages

    blocks = [
        {"type": "text", "text": "static", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic"},
    ]
    messages = _build_messages(
        system=None,
        prompt="ignored when user_message_blocks set",
        attachments=None,
        user_message_blocks=blocks,
    )

    assert messages[-1] == {"role": "user", "content": blocks}


def test_build_messages_falls_back_to_prompt_when_user_message_blocks_none() -> None:
    from pflow.core.llm_client import _build_messages

    messages = _build_messages(
        system=None,
        prompt="hello",
        attachments=None,
        user_message_blocks=None,
    )

    assert messages[-1] == {"role": "user", "content": "hello"}


def test_complete_passes_user_message_blocks_to_litellm(mock_llm_client) -> None:
    """The mock records user_message_blocks verbatim — verify the kwarg
    survives the complete() → mock boundary."""
    from pflow.core.llm_client import complete

    mock_llm_client.set_response("*", None, "ok")
    blocks = [
        {"type": "text", "text": "prefix", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "suffix"},
    ]
    complete(
        model=ANTHROPIC,
        prompt="prefixsuffix",
        user_message_blocks=blocks,
    )

    assert mock_llm_client.call_history_full[-1]["user_message_blocks"] == blocks


# --- v1 limitation: prewarm + images → graceful degradation (GH #358) -----


def test_prewarm_with_images_disables_prewarm_with_warning(mock_llm_client) -> None:
    """When a workflow declares ``prewarm: true`` AND ``images: [...]`` on
    the same LLM node, ``## Cache`` rendering produces text-only blocks and
    can't include images in the cached prefix. v1 gracefully disables
    prewarm for this run and emits a ``__warnings__`` entry so the user
    sees the degradation explicitly. Native image-cache support is GH #358."""
    mock_llm_client.set_response("*", None, "ok")
    node = LLMNode()
    node.node_id = "score-images"  # type: ignore[attr-defined]
    node.set_params({
        "prompt": "Rubric: be brief.\n\nScore this image: hello",
        "model": ANTHROPIC,
        "images": ["https://example.com/img.jpg"],
    })
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-images",
        _ctx_batch(
            unresolved_prompt="Rubric: be brief.\n\nScore this image: ${item.text}",
        ),
    )

    node.run(shared)

    # Prewarm disabled → no user_message_blocks emitted.
    assert mock_llm_client.call_history_full[-1]["user_message_blocks"] is None
    # Warning recorded so JSON consumers and __warnings__ inspectors see it.
    warnings = shared.get("__warnings__", {})
    assert "score-images" in warnings
    warning = warnings["score-images"]
    assert warning["kind"] == "prewarm_disabled_with_images"
    assert "GH #358" in warning["text"]
    assert warning["context"]["image_count"] == 1


def test_prewarm_with_images_falls_back_to_attachment_path(mock_llm_client) -> None:
    """The degradation path lets the standard attachment pipeline fire —
    images still reach the LLM as ``image_url`` content blocks; the call
    just doesn't get the cache marker on the static prefix."""
    mock_llm_client.set_response("*", None, "ok")
    node = LLMNode()
    node.node_id = "score-images"  # type: ignore[attr-defined]
    node.set_params({
        "prompt": "Rubric: brief\n\nScore this: hello",
        "model": ANTHROPIC,
        "images": ["https://example.com/img.jpg"],
    })
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-images",
        _ctx_batch(unresolved_prompt="Rubric: brief\n\nScore this: ${item.text}"),
    )

    node.run(shared)

    sent = mock_llm_client.call_history_full[-1]
    # No user_message_blocks (prewarm disabled)
    assert sent["user_message_blocks"] is None
    # Attachments still flow through the standard path.
    assert sent["attachments"] is not None
    assert len(sent["attachments"]) == 1
    assert sent["attachments"][0].kind == "image_url"
    assert sent["attachments"][0].value == "https://example.com/img.jpg"


def test_prewarm_without_images_unaffected_by_graceful_degradation(mock_llm_client) -> None:
    """Regression guard — the degradation must NOT fire when no images are
    present. Existing prewarm + cache rendering still works as before."""
    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        resolved_prompt="Rubric: brief\n\nScore: hello",
    )
    shared: dict[str, Any] = {}
    _install_prompt_cache(
        shared,
        "score-choruses",
        _ctx_batch(unresolved_prompt="Rubric: brief\n\nScore: ${item.text}"),
    )

    node.run(shared)

    sent_blocks = mock_llm_client.call_history_full[-1]["user_message_blocks"]
    assert sent_blocks is not None
    assert len(sent_blocks) == 2
    # No degradation warning fired.
    assert "score-choruses" not in shared.get("__warnings__", {})


# --- Production execution shape: NamespacedSharedStore wrap ----------------
# Engine.py:471 wraps shared in ``NamespacedSharedStore(shared, node_id)``
# before calling ``node._run`` — every other test in this file uses
# ``node.run(raw_dict)`` instead, the same shape that hid Bug #2 (dotted-path
# chunk resolution silently dropping). Lock the production execution shape
# for the combined-declared-cache + auto-batch-prefix path so a future Phase D
# extension that consumes ``${node.field}`` references in
# ``_resolve_static_prefix_for_cache`` can't silently regress through the
# proxy boundary.


def test_combined_declared_cache_and_auto_batch_prefix_through_namespaced_store(mock_llm_client) -> None:
    """A batch LLM node with BOTH a static prefix AND ``prompt_cache: [...]``
    declared must render correctly when ``shared`` is wrapped in
    ``NamespacedSharedStore`` — the production shape engine.py:471 actually
    applies. Asserts both markers fire (declared cache marker on system_blocks,
    auto-batch-prefix marker on user_message_blocks) and the rendered bytes
    match what the author wrote (no proxy-shape divergence).
    """
    from pflow.runtime.engine.namespaced_store import NamespacedSharedStore

    mock_llm_client.set_response("*", None, "ok")
    node = _make_node(
        "score-choruses",
        resolved_prompt="Rubric.\n\nScore: hello",
    )
    raw_shared: dict[str, Any] = {
        "concept": "courage",
        "score-choruses": {},
    }
    _install_prompt_cache(
        raw_shared,
        "score-choruses",
        _ctx_batch(
            unresolved_prompt="Rubric.\n\nScore: ${item.text}",
            chunks=[("concept", "Concept:\n")],
            subset=("concept",),
        ),
    )

    # Production wrap — engine.py:471
    store = NamespacedSharedStore(raw_shared, "score-choruses")
    node.run(store)

    sent = mock_llm_client.call_history_full[-1]
    # Declared cache → system_blocks with marker on the last block
    assert isinstance(sent["system"], list), "system_blocks must be a list when declared cache renders"
    assert sent["system"][-1]["text"] == "Concept:\ncourage"
    assert sent["system"][-1]["cache_control"] == {"type": "ephemeral"}
    # Auto-batch-prefix → user_message_blocks with marker on the static prefix
    blocks = sent["user_message_blocks"]
    assert blocks is not None
    assert len(blocks) == 2
    assert blocks[0]["text"] == "Rubric.\n\nScore: "
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "hello"
    assert "cache_control" not in blocks[1]
    # Bytes-identical-to-author: prefix + suffix == resolved prompt
    assert blocks[0]["text"] + blocks[1]["text"] == "Rubric.\n\nScore: hello"
