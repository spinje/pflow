"""Tests for smart field filtering with Haiku 4.5.

This test suite verifies:
1. Threshold behavior (filter vs passthrough)
2. LLM integration and response parsing
3. Fallback behavior on errors
4. Type preservation through filtering
5. Gemini-specific reasoning kwargs flow through model_options
"""

import pytest

from pflow.registry.smart_filter import (
    SMART_FILTER_THRESHOLD,
    FilteredFields,
    smart_filter_fields,
)


class TestSmartFilterThreshold:
    """Test threshold-based filtering decisions."""

    def test_threshold_constant_is_defined(self):
        """Verify SMART_FILTER_THRESHOLD constant exists and has correct value."""
        # Constant should be 30 (lowered from original plan of 50)
        assert SMART_FILTER_THRESHOLD == 30

        # Function should use this constant as default
        import inspect

        sig = inspect.signature(smart_filter_fields)
        default_threshold = sig.parameters["threshold"].default
        assert default_threshold == SMART_FILTER_THRESHOLD

    def test_fields_below_threshold_passthrough(self):
        """Fields < threshold should pass through unfiltered."""
        fields = [(f"field{i}", "string") for i in range(30)]
        result = smart_filter_fields(fields, threshold=50)
        assert result == fields  # Exact same list, no filtering
        assert len(result) == 30

    def test_fields_at_threshold_passthrough(self):
        """Exactly threshold count should NOT trigger filtering (> not >=)."""
        fields = [(f"field{i}", "string") for i in range(50)]
        result = smart_filter_fields(fields, threshold=50)
        assert result == fields
        assert len(result) == 50

    def test_fields_above_threshold_filters(self, mock_llm_client):
        """Fields > threshold should trigger LLM filtering."""
        # 51 fields - one above threshold
        fields = [(f"field{i}", "string") for i in range(51)]

        # Mock LLM to return subset
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {
                "included_fields": ["field0", "field1", "field2"],
                "reasoning": "Kept first 3 fields as most relevant",
            },
        )

        result = smart_filter_fields(fields, threshold=50)

        # Should return filtered subset with preserved types
        assert len(result) == 3
        assert result == [("field0", "string"), ("field1", "string"), ("field2", "string")]

    def test_large_field_set_filters_significantly(self, mock_llm_client):
        """Large field sets (200+) should be reduced to 8-15 range."""
        # Simulate GitHub issue fields (200 fields)
        base_fields = [
            ("result[0].id", "integer"),
            ("result[0].node_id", "string"),
            ("result[0].title", "string"),
            ("result[0].body", "string"),
            ("result[0].state", "string"),
            ("result[0].url", "string"),
            ("result[0].html_url", "string"),
        ]
        # Add metadata fields
        metadata_fields = [(f"result[0].metadata_{i}", "string") for i in range(193)]
        fields = base_fields + metadata_fields

        assert len(fields) == 200

        # Mock LLM to return relevant business fields only
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {
                "included_fields": [
                    "result[0].title",
                    "result[0].body",
                    "result[0].state",
                    "result[0].id",
                ],
                "reasoning": "Removed 196 metadata/URL fields, kept core business data",
            },
        )

        result = smart_filter_fields(fields, threshold=50)

        assert len(result) == 4
        assert ("result[0].title", "string") in result
        assert ("result[0].body", "string") in result
        assert ("result[0].state", "string") in result
        assert ("result[0].id", "integer") in result
        # Verify filtered out
        assert ("result[0].url", "string") not in result
        assert ("result[0].html_url", "string") not in result


class TestLLMIntegration:
    """Test LLM call and response handling."""

    def test_llm_response_preserves_type_info(self, mock_llm_client):
        """Filtered paths should preserve type information from original."""
        fields = [
            ("title", "string"),
            ("count", "integer"),
            ("active", "boolean"),
            ("metadata", "object"),
        ]

        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["title", "count"], "reasoning": "Kept primary fields"},
        )

        result = smart_filter_fields(fields, threshold=2)

        # Type info preserved
        assert result == [("title", "string"), ("count", "integer")]

    def test_llm_returns_paths_not_in_original_ignored(self, mock_llm_client):
        """LLM returning paths not in original list should be ignored."""
        fields = [("field1", "string"), ("field2", "integer")]

        # LLM hallucinates non-existent fields
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {
                "included_fields": ["field1", "field_DOES_NOT_EXIST", "field99"],
                "reasoning": "Included non-existent fields",
            },
        )

        result = smart_filter_fields(fields, threshold=1)

        # Only field1 exists in original, others ignored
        assert result == [("field1", "string")]

    def test_llm_returns_subset_matching_works(self, mock_llm_client):
        """LLM returning valid subset should work correctly."""
        fields = [
            ("result.messages[0].text", "string"),
            ("result.messages[0].role", "string"),
            ("result.messages[0].timestamp", "string"),
            ("result.has_more", "boolean"),
            ("result.cursor", "string"),
        ]

        # LLM selects subset
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {
                "included_fields": [
                    "result.messages[0].text",
                    "result.messages[0].role",
                    "result.has_more",
                ],
                "reasoning": "Removed cursor and timestamp metadata",
            },
        )

        result = smart_filter_fields(fields, threshold=3)

        assert len(result) == 3
        assert ("result.messages[0].text", "string") in result
        assert ("result.messages[0].role", "string") in result
        assert ("result.has_more", "boolean") in result
        # Filtered out
        assert ("result.cursor", "string") not in result
        assert ("result.messages[0].timestamp", "string") not in result


class TestFallbackBehavior:
    """Test error handling and fallback to original fields."""

    def test_llm_failure_returns_original(self, monkeypatch):
        """Deterministic adapter failure (LLMCallError) → fallback to unfiltered fields.

        smart_filter narrows its catch to documented degradation modes so
        programming errors surface loudly. LLMCallError is what the adapter
        raises for any deterministic provider failure (bad request, bad
        schema, parse failure, etc.) — that's the case where falling back
        to unfiltered display is the right UX.
        """
        from pflow.core.exceptions import LLMCallError

        fields = [(f"field{i}", "string") for i in range(100)]

        def mock_complete_error(**kwargs):
            raise LLMCallError("Invalid request for model 'X': bad parameter")

        monkeypatch.setattr("pflow.registry.smart_filter.complete", mock_complete_error)

        result = smart_filter_fields(fields, threshold=50)

        # Fallback: all original fields returned
        assert result == fields
        assert len(result) == 100

    def test_empty_llm_response_returns_original(self, mock_llm_client):
        """LLM returning empty field list should fallback to original."""
        fields = [(f"field{i}", "string") for i in range(100)]

        # LLM returns nothing
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": [], "reasoning": "Filtered everything"},
        )

        result = smart_filter_fields(fields, threshold=50)

        # Safety fallback: return original
        assert result == fields
        assert len(result) == 100

    def test_malformed_llm_response_returns_original(self, monkeypatch):
        """Parse failures (LLMCallError from parse_structured_response) → fallback.

        Real ``parse_structured_response`` raises ``LLMCallError`` (not bare
        ``ValueError``) for empty/garbage/schema-violating responses — so the
        mock mirrors that contract.
        """
        from pflow.core.exceptions import LLMCallError

        fields = [(f"field{i}", "string") for i in range(100)]

        def mock_parse_error(response, schema):
            raise LLMCallError("Response text is not valid JSON: ...")

        monkeypatch.setattr("pflow.registry.smart_filter.parse_structured_response", mock_parse_error)

        result = smart_filter_fields(fields, threshold=50)

        assert result == fields
        assert len(result) == 100

    def test_programming_error_propagates(self, monkeypatch):
        """Programming errors (AttributeError, TypeError, etc.) propagate.

        smart_filter narrows its catch deliberately so genuine bugs surface
        as test failures rather than silent UX degradation. If a refactor
        introduces an AttributeError inside the try block, the user will see
        a real traceback rather than just "filter failed, here are 200
        fields" with no clue what broke.
        """
        fields = [(f"field{i}", "string") for i in range(100)]

        def mock_complete_bug(**kwargs):
            # Simulate a typo / refactor mishap inside the call path
            raise AttributeError("'NoneType' object has no attribute 'foo'")

        monkeypatch.setattr("pflow.registry.smart_filter.complete", mock_complete_bug)

        with pytest.raises(AttributeError, match="'NoneType' object has no attribute 'foo'"):
            smart_filter_fields(fields, threshold=50)

    def test_warning_logged_on_graceful_fallback(self, monkeypatch, caplog):
        """The graceful-degradation path emits a WARNING with diagnostic context.

        Pins the user-visibility contract: under default CLI logging
        (WARNING level), a probe that hits an LLMCallError must surface a
        visible warning with the error type and message in the ``extra``
        dict so operators can diagnose without enabling DEBUG logging.
        """
        import logging

        from pflow.core.exceptions import LLMCallError

        fields = [(f"field{i}", "string") for i in range(60)]

        def mock_complete_error(**kwargs):
            raise LLMCallError("API key required for model: gpt-4o-mini")

        monkeypatch.setattr("pflow.registry.smart_filter.complete", mock_complete_error)

        with caplog.at_level(logging.WARNING, logger="pflow.registry.smart_filter"):
            result = smart_filter_fields(fields, threshold=50)

        assert result == fields
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("Smart filter failed" in r.message for r in warning_records), (
            "expected WARNING about smart_filter graceful fallback"
        )
        # Diagnostic context attached for operators
        target = next(r for r in warning_records if "Smart filter failed" in r.message)
        assert target.error_type == "LLMCallError"
        assert "API key required" in target.error_message

    def test_network_error_returns_original(self, monkeypatch):
        """Network errors should fallback gracefully."""
        fields = [(f"field{i}", "string") for i in range(60)]

        # Simulate network error by making the adapter raise ConnectionError.
        # Patches `pflow.registry.smart_filter.complete` (the binding the
        # production code calls) — not `llm.get_model`, which is the dead
        # legacy seam since Task 158 Phase A.7.
        def mock_complete_network_error(**kwargs):
            raise ConnectionError("Network unreachable")

        monkeypatch.setattr("pflow.registry.smart_filter.complete", mock_complete_network_error)

        result = smart_filter_fields(fields, threshold=50)

        assert result == fields
        assert len(result) == 60


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_field_list(self):
        """Empty input should return empty output (no LLM call)."""
        result = smart_filter_fields([], threshold=50)
        assert result == []

    def test_single_field(self):
        """Single field should pass through (below threshold)."""
        fields = [("only_field", "string")]
        result = smart_filter_fields(fields, threshold=50)
        assert result == fields

    def test_custom_threshold(self, mock_llm_client):
        """Custom threshold should be respected."""
        fields = [(f"field{i}", "string") for i in range(20)]

        # Lower threshold to 10
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field0", "field1"], "reasoning": "Reduced to 2"},
        )

        result = smart_filter_fields(fields, threshold=10)

        # Should filter because 20 > 10
        assert len(result) == 2
        assert result == [("field0", "string"), ("field1", "string")]

    def test_preserves_order(self, mock_llm_client):
        """Filtered results should preserve original order."""
        fields = [
            ("zebra", "string"),
            ("apple", "string"),
            ("mango", "string"),
            ("banana", "string"),
        ]

        # LLM returns out of order
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["banana", "zebra", "apple"], "reasoning": "Selected 3"},
        )

        result = smart_filter_fields(fields, threshold=2)

        # Should match original order, not LLM order
        assert result == [("zebra", "string"), ("apple", "string"), ("banana", "string")]

    def test_mixed_types_preserved(self, mock_llm_client):
        """Different type annotations should be preserved correctly."""
        fields = [
            ("id", "integer"),
            ("title", "string"),
            ("active", "boolean"),
            ("metadata", "object"),
            ("tags", "array"),
            ("score", "number"),
        ]

        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["id", "title", "active"], "reasoning": "Core fields"},
        )

        result = smart_filter_fields(fields, threshold=3)

        assert result == [("id", "integer"), ("title", "string"), ("active", "boolean")]

    def test_fields_with_special_characters(self, mock_llm_client):
        """Field paths with special characters should work."""
        fields = [
            ("result[0].author.login", "string"),
            ("result[0].labels[*].name", "string"),
            ("result[0].pull_request.html_url", "string"),
        ]

        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {
                "included_fields": ["result[0].author.login"],
                "reasoning": "Most relevant",
            },
        )

        result = smart_filter_fields(fields, threshold=2)

        assert result == [("result[0].author.login", "string")]


class TestSmartFilterCaching:
    """Test caching behavior of smart_filter_fields_cached."""

    def test_cache_hit_on_identical_structure(self, mock_llm_client):
        """Second call with identical field structure should hit cache."""
        from pflow.registry.smart_filter import clear_cache, smart_filter_fields_cached

        # Clear cache to start fresh
        clear_cache()

        # Setup mock LLM
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field0", "field1"], "reasoning": "Test"},
        )

        fields = tuple([(f"field{i}", "string") for i in range(60)])

        # First call: cache miss (should call LLM)
        result1 = smart_filter_fields_cached(fields, threshold=50)
        assert len(result1) == 2

        # Second call: cache hit (should NOT call LLM)
        result2 = smart_filter_fields_cached(fields, threshold=50)
        assert len(result2) == 2
        assert result1 == result2  # Results identical

        # Verify cache was hit
        from pflow.registry.smart_filter import get_cache_stats

        stats = get_cache_stats()
        assert stats["hits"] >= 1  # At least one hit
        assert stats["misses"] >= 1  # At least one miss

    def test_cache_miss_on_different_structure(self, mock_llm_client):
        """Different field structure should cause cache miss."""
        from pflow.registry.smart_filter import clear_cache, smart_filter_fields_cached

        clear_cache()

        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field1"], "reasoning": "Test"},
        )

        # First structure
        fields1 = (("field1", "string"), ("field2", "string"))
        smart_filter_fields_cached(fields1, threshold=1)

        # Different structure (different fields)
        fields2 = (("field1", "string"), ("field3", "string"))
        smart_filter_fields_cached(fields2, threshold=1)

        # Both should have been cache misses (different structures)
        from pflow.registry.smart_filter import get_cache_stats

        stats = get_cache_stats()
        assert stats["misses"] >= 2  # At least 2 misses for different structures

    def test_cache_order_independence(self, mock_llm_client):
        """Field order doesn't matter for caching - same fingerprint generated."""
        from pflow.registry.smart_filter import _calculate_fingerprint, clear_cache, smart_filter_fields_cached

        clear_cache()

        # Fields in different orders should produce same fingerprint
        fields1 = (("a", "str"), ("b", "str"), ("c", "str"))
        fields2 = (("c", "str"), ("a", "str"), ("b", "str"))

        # Verify fingerprints are identical
        fp1 = _calculate_fingerprint(fields1)
        fp2 = _calculate_fingerprint(fields2)
        assert fp1 == fp2  # Order doesn't matter for fingerprint

        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["a"], "reasoning": "Test"},
        )

        # First call
        smart_filter_fields_cached(fields1, threshold=2)

        # Second call with different order (should hit cache!)
        smart_filter_fields_cached(fields2, threshold=2)

        # Verify cache hit occurred
        from pflow.registry.smart_filter import get_cache_stats

        stats = get_cache_stats()
        assert stats["hits"] == 1  # Exactly one hit (second call)
        assert stats["misses"] == 1  # Exactly one miss (first call)

    def test_cache_stats_accuracy(self, mock_llm_client):
        """Cache statistics should update correctly."""
        from pflow.registry.smart_filter import (
            clear_cache,
            get_cache_stats,
            smart_filter_fields_cached,
        )

        clear_cache()
        stats = get_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field1"], "reasoning": "Test"},
        )

        fields = (("field1", "str"), ("field2", "str"))

        # First call: miss
        smart_filter_fields_cached(fields, threshold=1)
        stats = get_cache_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0
        assert stats["hit_rate"] == 0.0

        # Second call: hit
        smart_filter_fields_cached(fields, threshold=1)
        stats = get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0

        # Third call: another hit
        smart_filter_fields_cached(fields, threshold=1)
        stats = get_cache_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 66.7

    def test_cache_clear_resets_state(self, mock_llm_client):
        """Cache clear should reset cache state."""
        from pflow.registry.smart_filter import (
            clear_cache,
            get_cache_stats,
            smart_filter_fields_cached,
        )

        clear_cache()

        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field1"], "reasoning": "Test"},
        )

        fields = (("field1", "str"), ("field2", "str"))

        # First call: miss
        smart_filter_fields_cached(fields, threshold=1)

        # Second call: hit
        smart_filter_fields_cached(fields, threshold=1)

        stats_before_clear = get_cache_stats()
        assert stats_before_clear["hits"] >= 1

        # Clear cache
        clear_cache()

        stats_after_clear = get_cache_stats()
        assert stats_after_clear["hits"] == 0
        assert stats_after_clear["misses"] == 0
        assert stats_after_clear["size"] == 0

    def test_below_threshold_not_cached(self):
        """Fields below threshold should not trigger caching."""
        from pflow.registry.smart_filter import clear_cache, smart_filter_fields_cached

        clear_cache()

        # Only 3 fields, threshold is 50
        fields = (("field1", "str"), ("field2", "str"), ("field3", "str"))

        result = smart_filter_fields_cached(fields, threshold=50)

        # Should return all fields (no filtering, no LLM call)
        assert len(result) == 3
        assert result == fields


class TestGeminiThinkingHeuristics:
    """Smart-filter forwards Gemini-specific reasoning kwargs via ``model_options``.

    Field filtering is a trivial classification task. A Gemini reasoning
    model would otherwise spend tokens (and money) on internal thinking
    before answering — making smart-filter calls 5-10x more expensive on
    Gemini. Pflow forwards reasoning-disable kwargs via ``model_options``
    so the adapter passes them to LiteLLM verbatim.

    These tests pin the wiring: a silent regression in
    ``smart_filter.py:174-180`` would make Gemini-driven smart-filtering
    quietly burn through token budgets without any test failure.
    """

    @pytest.mark.parametrize(
        "model,expected_options",
        [
            ("gemini-3-flash-preview", {"thinking_level": "minimal"}),
            ("gemini-2.5-pro", {"thinking_budget": 0}),
            ("gemini-2.5-flash", {"thinking_budget": 0}),
        ],
    )
    def test_gemini_models_get_thinking_minimized(self, monkeypatch, mock_llm_client, model, expected_options):
        monkeypatch.setattr("pflow.core.llm_config.get_model_for_feature", lambda _f: model)
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field0"], "reasoning": "test"},
        )
        fields = [(f"field{i}", "string") for i in range(60)]
        smart_filter_fields(fields, threshold=50)

        last_call = mock_llm_client.call_history[-1]
        assert last_call["model"] == model
        assert last_call["model_options"] == expected_options

    def test_gemini_lite_gets_no_model_options(self, monkeypatch, mock_llm_client):
        # Lite variants have no thinking — heuristic skips them, so the
        # adapter should receive model_options=None (avoid passing an
        # empty dict that LiteLLM might choke on).
        monkeypatch.setattr(
            "pflow.core.llm_config.get_model_for_feature",
            lambda _f: "gemini-2.5-flash-lite",
        )
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field0"], "reasoning": "test"},
        )
        fields = [(f"field{i}", "string") for i in range(60)]
        smart_filter_fields(fields, threshold=50)

        last_call = mock_llm_client.call_history[-1]
        assert last_call["model_options"] is None

    def test_non_gemini_models_get_no_model_options(self, monkeypatch, mock_llm_client):
        # Non-Gemini models don't have the silent-thinking-cost problem —
        # no kwargs needed. Anthropic's reasoning is opt-in via
        # reasoning_effort/reasoning_max_tokens, not on by default.
        monkeypatch.setattr(
            "pflow.core.llm_config.get_model_for_feature",
            lambda _f: "anthropic/claude-sonnet-4-5",
        )
        mock_llm_client.set_response(
            "*",
            FilteredFields,
            {"included_fields": ["field0"], "reasoning": "test"},
        )
        fields = [(f"field{i}", "string") for i in range(60)]
        smart_filter_fields(fields, threshold=50)

        last_call = mock_llm_client.call_history[-1]
        assert last_call["model_options"] is None
