"""Tests for pflow.execution.formatters.batch_errors.

Focus: the ``provider:`` line — the raw upstream provider diagnosis carried on a
batch item error record. Without it, a batched LLM failure renders only pflow's
wrapped framing and loses the one line naming the real cause.
"""

from pflow.execution.formatters.batch_errors import (
    MAX_ERROR_MESSAGE_CHARS,
    compact_batch_error_detail,
    format_batch_errors_section,
)


def _batch_step(*error_details: dict) -> list[dict]:
    return [
        {
            "node_id": "classify",
            "is_batch": True,
            "batch_errors": len(error_details),
            "batch_error_details": list(error_details),
            "batch_errors_truncated": 0,
        }
    ]


class TestProviderMessageRendering:
    """format_batch_errors_section surfaces provider_message under the item line."""

    def test_provider_message_renders_after_the_index_line(self):
        lines = format_batch_errors_section(
            _batch_step({
                "index": 2,
                "error": "LLM call failed",
                "provider_message": "This model models/gemini-2.5-flash is no longer available",
            })
        )

        assert lines[1] == "  [2] LLM call failed"
        assert lines[2] == "      provider: This model models/gemini-2.5-flash is no longer available"

    def test_provider_message_truncated_at_200_chars(self):
        provider = "x" * 400
        lines = format_batch_errors_section(
            _batch_step({"index": 0, "error": "LLM call failed", "provider_message": provider})
        )

        rendered = lines[2].removeprefix("      provider: ")
        assert len(rendered) == MAX_ERROR_MESSAGE_CHARS
        assert rendered.endswith("...")
        assert rendered.startswith("x" * 10)

    def test_entry_without_provider_message_renders_unchanged(self):
        with_key = format_batch_errors_section(_batch_step({"index": 1, "error": "boom"}))
        assert with_key == ["\nBatch 'classify' errors:", "  [1] boom"]

    def test_blank_provider_message_renders_no_line(self):
        """A whitespace-only value must not degrade to the 'Unknown error' headline."""
        lines = format_batch_errors_section(_batch_step({"index": 0, "error": "boom", "provider_message": "   "}))

        assert lines == ["\nBatch 'classify' errors:", "  [0] boom"]

    def test_provider_message_precedes_the_item_summary(self):
        lines = format_batch_errors_section(
            _batch_step({
                "index": 0,
                "error": "LLM call failed",
                "provider_message": "Quota exceeded",
                "item_summary": {"summary": "label='doc-1'"},
            })
        )

        assert lines[2] == "      provider: Quota exceeded"
        assert lines[3] == "      item: label='doc-1'"


class TestCompactBatchErrorDetail:
    """The JSON/API-safe record keeps the provider diagnosis."""

    def test_provider_message_preserved(self):
        compact = compact_batch_error_detail({
            "index": 0,
            "error": "LLM call failed",
            "provider_message": "Quota exceeded",
            "item": {"secret": "x"},
        })

        assert compact["provider_message"] == "Quota exceeded"
        assert "item" not in compact

    def test_absent_provider_message_adds_no_key(self):
        compact = compact_batch_error_detail({"index": 0, "error": "boom"})

        assert "provider_message" not in compact
