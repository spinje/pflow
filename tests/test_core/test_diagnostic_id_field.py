"""Tests for the ``Diagnostic.id`` field and cache category constants (Task 159 B1.1).

The ``id`` field is the stable warning-id surface for cache-namespaced diagnostics
(per spec DD#27). Identity dedup updates from ``(severity, source, node_id, message)``
to ``(severity, source, node_id, id or message)`` — null-safe by construction so
legacy diagnostics with ``id=None`` keep today's message-keyed dedup behavior.
"""

from __future__ import annotations

from pflow.core.diagnostic import (
    CACHE_ADVISORY_CATEGORY,
    CACHE_FAILURE_CATEGORY,
    CACHE_WARNING_CATEGORY,
    CATEGORY_TITLES,
    Diagnostic,
    Severity,
    deduplicate_diagnostics,
)


def test_id_field_defaults_to_none() -> None:
    """``id`` is optional; default is ``None`` to preserve legacy construction."""
    d = Diagnostic(severity=Severity.ERROR, message="m", source="validator")
    assert d.id is None


def test_id_none_preserves_legacy_identity_tuple() -> None:
    """When ``id is None``, identity falls back to ``message`` (legacy behavior).

    Two diagnostics differing only in ``message`` MUST NOT collapse — this is
    the exact behavior of the pre-Task-159 identity tuple ``(severity, source,
    node_id, message)``. Adding the ``id`` field must not change this.
    """
    a = Diagnostic(severity=Severity.WARNING, source="validator", node_id="n", message="message A")
    b = Diagnostic(severity=Severity.WARNING, source="validator", node_id="n", message="message B")
    assert a != b
    assert hash(a) != hash(b)
    assert deduplicate_diagnostics([a, b]) == [a, b]


def test_id_set_collapses_message_variants() -> None:
    """Two diagnostics with the same ``id`` but different ``message`` collapse to one.

    This is the load-bearing payoff for cache-namespaced diagnostics: an
    analyzer can enrich the message at multiple emission sites without
    spawning duplicates in the rendered output.
    """
    a = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        node_id="batch-node",
        id="cache.batch-prewarm-recommended",
        message="34-item batch with ~2.1k-token static prefix has no prewarm decision.",
    )
    b = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        node_id="batch-node",
        id="cache.batch-prewarm-recommended",
        message="Different enrichment, same warning.",
    )
    assert a == b
    assert hash(a) == hash(b)
    assert deduplicate_diagnostics([a, b]) == [a]


def test_id_distinguishes_two_different_warning_ids() -> None:
    """Two diagnostics with different ``id`` values do NOT collapse."""
    a = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        node_id="n",
        id="cache.unused-chunk",
        message="same message",
    )
    b = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        node_id="n",
        id="cache.below-min-tokens",
        message="same message",
    )
    assert a != b
    assert hash(a) != hash(b)


def test_to_dict_emits_id_when_set() -> None:
    """``to_dict()`` includes the ``id`` key when populated."""
    d = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        message="m",
        id="cache.order-mismatch",
    )
    payload = d.to_dict()
    assert payload["id"] == "cache.order-mismatch"


def test_to_dict_omits_id_when_none() -> None:
    """``to_dict()`` omits the ``id`` key when ``None`` — symmetric with title/see_also."""
    d = Diagnostic(severity=Severity.ERROR, source="validator", message="m")
    payload = d.to_dict()
    assert "id" not in payload


def test_to_dict_round_trip_with_id() -> None:
    """Full to_dict shape with id includes severity/message/source/id together."""
    d = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        node_id="some-node",
        id="cache.unused-chunk",
        message="Chunk 'concept' is declared but no node references it.",
        suggestions=["Remove from ## Cache or reference it from a prompt_cache:."],
        context={"category": CACHE_WARNING_CATEGORY, "chunk_name": "concept"},
    )
    payload = d.to_dict()
    assert payload == {
        "severity": "warning",
        "source": "cache_analyzer",
        "node_id": "some-node",
        "id": "cache.unused-chunk",
        "message": "Chunk 'concept' is declared but no node references it.",
        "suggestions": ["Remove from ## Cache or reference it from a prompt_cache:."],
        "context": {"category": CACHE_WARNING_CATEGORY, "chunk_name": "concept"},
    }


def test_cache_category_constants_exist() -> None:
    """The three cache category string constants exist and are namespaced."""
    assert CACHE_FAILURE_CATEGORY == "cache_failure"
    assert CACHE_WARNING_CATEGORY == "cache_warning"
    assert CACHE_ADVISORY_CATEGORY == "cache_advisory"


def test_cache_categories_in_category_titles() -> None:
    """All three cache categories appear in CATEGORY_TITLES with friendly names.

    Without these entries, the renderer's title fallback in
    ``_format_error_diagnostic`` produces a generic "Error" title — still
    correct, but degraded UX for the agent reading the rendered output.
    """
    assert CATEGORY_TITLES[CACHE_FAILURE_CATEGORY] == "Cache Failure"
    assert CATEGORY_TITLES[CACHE_WARNING_CATEGORY] == "Cache Warning"
    assert CATEGORY_TITLES[CACHE_ADVISORY_CATEGORY] == "Cache Advisory"


def test_cache_failure_not_in_failure_category_map() -> None:
    """``_FAILURE_CATEGORY_MAP["cache_failure"]`` is NOT added in v1.

    The dual-invariant pattern at ``executor_service.py`` is for typed-exception
    paths (mirroring ``LLMCallError``). v1 emits all cache validation diagnostics
    directly via ``Diagnostic`` — no typed cache exception flows through
    ``__failures__``, so adding the map entry now creates dead code (no producer
    reaches it). When/if v1.x introduces a typed ``CacheRenderError``, that task
    adds the entry alongside the producer in one PR.
    """
    from pflow.execution.executor_service import _FAILURE_CATEGORY_MAP

    assert "cache_failure" not in _FAILURE_CATEGORY_MAP


def test_subworkflow_legacy_dedup_regression() -> None:
    """Two ``Diagnostic`` s with identical ``(severity, source, node_id, message)`` and
    ``id=None`` MUST hash and compare equal.

    This is the dual-propagation-path dedup contract documented in
    ``core/CLAUDE.md`` and reinforced by the ``Diagnostic.__hash__`` comment.
    Child-workflow warnings flow through both the validation path
    (``_add_child_provenance``) and the runtime path
    (``_propagate_child_parser_warnings``) and produce the same (severity,
    source, node_id, message) tuple. Adding ``id`` to the identity unconditionally
    would break that collapse — by tying dedup to ``id or message``, we preserve
    legacy behavior when ``id is None``.
    """
    d1 = Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        node_id="child-node",
        message="In step 'parent-step' sub-workflow: cache lint warning",
    )
    d2 = Diagnostic(
        severity=Severity.WARNING,
        source="validator",
        node_id="child-node",
        message="In step 'parent-step' sub-workflow: cache lint warning",
    )
    assert d1 == d2
    assert hash(d1) == hash(d2)
    assert len(deduplicate_diagnostics([d1, d2])) == 1


def test_legacy_identity_tuple_in_hash_when_id_absent() -> None:
    """Hash equality between an ``id=None`` diagnostic and a hash computed from
    the legacy 4-tuple proves the null-safety claim by construction.

    Catches the regression where someone changes the tuple to include ``id``
    unconditionally (e.g., ``hash((severity, source, node_id, id, message))``).
    """
    d = Diagnostic(severity=Severity.ERROR, source="src", node_id="n", message="msg")
    assert hash(d) == hash((Severity.ERROR, "src", "n", "msg"))


def test_id_set_changes_hash_to_id_keyed_tuple() -> None:
    """When ``id`` is set, the hash uses ``id`` as the dedup key, not ``message``."""
    d = Diagnostic(
        severity=Severity.ERROR,
        source="cache_analyzer",
        node_id="n",
        id="cache.order-mismatch",
        message="anything",
    )
    assert hash(d) == hash((Severity.ERROR, "cache_analyzer", "n", "cache.order-mismatch"))


def test_renderer_prefixes_cache_warning_with_id() -> None:
    """Cache-namespaced WARNING renders ``[id]`` inline so agents route on the
    stable warning identifier without parsing JSON."""
    from pflow.core.diagnostic_render import format_diagnostic

    d = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        node_id="chorus-chooser.score-choruses",
        id="cache.batch-prewarm-recommended",
        message="34-item batch with ~2.1k-token static prefix has no prewarm decision.",
        suggestions=["Add `- prewarm: true` to opt in (-$0.12/run)."],
        context={
            "category": CACHE_WARNING_CATEGORY,
            "batch_size": 34,
            "prefix_tokens_estimated": 2100,
            "savings_pct": 89,
            "savings_usd": 0.12,
        },
    )
    rendered = format_diagnostic(d)
    assert "[cache.batch-prewarm-recommended]" in rendered
    assert "[chorus-chooser.score-choruses]" in rendered
    assert "34-item batch" in rendered
    assert "Add `- prewarm: true`" in rendered
    # Inline structured context surfaces — closed-list keys only.
    assert "batch_size: 34" in rendered
    assert "savings_pct: 89" in rendered
    assert "savings_usd: 0.12" in rendered
    assert "prefix_tokens_estimated: 2100" in rendered


def test_renderer_omits_cache_id_prefix_when_id_absent() -> None:
    """A cache-category diagnostic without an ``id`` renders with no ``[]`` prefix
    (still passes through the cache renderer for inline context surfacing)."""
    from pflow.core.diagnostic_render import format_diagnostic

    d = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        message="some untyped cache warning",
        context={"category": CACHE_WARNING_CATEGORY},
    )
    rendered = format_diagnostic(d)
    # No id present, no prefix square brackets at the start of the line.
    assert "[" not in rendered.splitlines()[0]


def test_renderer_skips_unknown_cache_context_keys() -> None:
    """Inline rendering uses a closed key list — unknown keys do not leak into output."""
    from pflow.core.diagnostic_render import format_diagnostic

    d = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        node_id="n",
        id="cache.unused-chunk",
        message="unused chunk",
        context={
            "category": CACHE_WARNING_CATEGORY,
            "savings_pct": 5,
            "internal_debug_blob": {"do_not": "render"},
            "another_random_key": "should not appear",
        },
    )
    rendered = format_diagnostic(d)
    assert "savings_pct: 5" in rendered
    assert "internal_debug_blob" not in rendered
    assert "another_random_key" not in rendered


def test_renderer_cache_failure_error_uses_category_title() -> None:
    """A cache_failure ERROR uses the ``Cache Failure`` title from CATEGORY_TITLES.

    Without a title fallback in CATEGORY_TITLES, the renderer would fall back
    to the generic ``"Error"`` title — degraded UX. This test locks the
    title binding for the structural cache-error path.
    """
    from pflow.core.diagnostic_render import format_diagnostic

    d = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        node_id="some-node",
        id="cache.invalid-on-non-llm",
        title=None,  # Force renderer to look up via CATEGORY_TITLES
        message="prompt_cache is only valid on type: llm nodes",
        context={"category": CACHE_FAILURE_CATEGORY},
    )
    rendered = format_diagnostic(d)
    assert "Error: Cache Failure" in rendered
