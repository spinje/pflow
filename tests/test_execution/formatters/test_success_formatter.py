"""Tests for success formatter - guardrails for execution success display.

These tests catch real bugs that could break execution output for agents and CLI.
Each test documents what bug it prevents.
"""

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.execution.formatters.output_utils import find_auto_output
from pflow.execution.formatters.success_formatter import (
    _append_execution_steps,
    _format_batch_errors_section,
    _truncate_error_message,
    format_execution_success,
    format_only_indicator,
    format_stderr_warnings,
    format_success_as_text,
)


class TestBatchErrorsSectionFormatting:
    """Tests for batch errors section formatting."""

    def test_batch_errors_section_includes_node_id(self):
        """CORRECTNESS: Error section header must identify which batch node.

        Real bug this catches: Without node ID in header, users can't identify
        which batch node's errors are being shown.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 2,
                "batch_error_details": [
                    {"index": 1, "error": "Error 1"},
                    {"index": 4, "error": "Error 2"},
                ],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert any("Batch 'process' errors:" in line for line in lines)

    def test_batch_errors_show_item_indices(self):
        """CORRECTNESS: Each error must show which item failed (0-based index).

        Real bug this catches: Without item indices, users can't identify which
        input items caused failures.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 2,
                "batch_error_details": [
                    {"index": 1, "error": "Error at item 1"},
                    {"index": 4, "error": "Error at item 4"},
                ],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert any("[1]" in line for line in lines)
        assert any("[4]" in line for line in lines)

    def test_batch_errors_show_messages(self):
        """CORRECTNESS: Error messages must be displayed.

        Real bug this catches: Without error messages, users can't understand
        what went wrong.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 1,
                "batch_error_details": [
                    {"index": 0, "error": "Command failed with exit code 1"},
                ],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert any("Command failed with exit code 1" in line for line in lines)

    def test_batch_errors_capped_at_5(self):
        """UX: More than 5 errors shows truncation message.

        Real bug this catches: Showing 50 error lines would overwhelm the user
        and make terminal output unusable.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 8,
                "batch_error_details": [{"index": i, "error": f"Error {i}"} for i in range(5)],
                "batch_errors_truncated": 3,
            }
        ]
        lines = _format_batch_errors_section(steps)

        # Should show truncation message
        assert any("...and 3 more errors" in line for line in lines)

    def test_batch_errors_empty_for_no_failures(self):
        """CORRECTNESS: No error section when batch succeeds fully.

        Real bug this catches: Showing empty error section would be confusing
        and add visual noise.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 0,
                "batch_error_details": [],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert len(lines) == 0

    def test_batch_errors_empty_for_non_batch_nodes(self):
        """CORRECTNESS: Non-batch nodes don't show error section.

        Real bug this catches: Regular node errors would be incorrectly formatted
        as batch errors.
        """
        steps = [
            {
                "node_id": "regular_node",
                "status": "failed",
                # No is_batch flag
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert len(lines) == 0

    def test_batch_errors_summarize_large_item_without_payload_dump(self):
        """UX: Batch error text shows compact item identity, not raw payload."""
        payload = "PAYLOAD-START " + " ".join(f"token{i}" for i in range(200)) + " PAYLOAD-END"
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 1,
                "batch_error_details": [
                    {
                        "index": 0,
                        "item": {"label": "oversized-item", "payload": payload},
                        "item_summary": {
                            "summary": "label='oversized-item'; payload=<str 1909 chars sha256=123456789abc>",
                            "sha256": "123456789abc",
                        },
                        "error": "forced batch failure",
                    }
                ],
            }
        ]

        lines = _format_batch_errors_section(steps)
        rendered = "\n".join(lines)

        assert "Batch 'process' errors:" in rendered
        assert "[0] forced batch failure" in rendered
        assert "oversized-item" in rendered
        assert "payload=<str" in rendered
        assert "sha256=" in rendered
        assert "PAYLOAD-START" not in rendered
        assert "PAYLOAD-END" not in rendered
        assert "token199" not in rendered
        assert "'payload':" not in rendered


class TestErrorMessageTruncation:
    """Tests for error message truncation."""

    def test_short_message_not_truncated(self):
        """CORRECTNESS: Short messages pass through unchanged.

        Real bug this catches: Unnecessarily truncating short messages would
        remove valuable error context.
        """
        message = "Command failed with exit code 1"
        result = _truncate_error_message(message)

        assert result == message
        assert "..." not in result

    def test_long_message_truncated_at_200_chars(self):
        """UX: Long messages truncated to 200 characters.

        Real bug this catches: Full stack traces would overwhelm error display
        and make output hard to read.
        """
        long_message = "x" * 300
        result = _truncate_error_message(long_message)

        assert len(result) == 200
        assert result.endswith("...")

    def test_truncation_preserves_start_of_message(self):
        """CORRECTNESS: Truncation keeps message start (most important part).

        Real bug this catches: Truncating from the start would remove the most
        relevant error information.
        """
        message = "Important error: " + "x" * 300
        result = _truncate_error_message(message)

        assert result.startswith("Important error:")

    def test_multiline_message_uses_root_cause_headline(self):
        """UX: Compact batch sections should not repeat diagnostic details."""
        message = (
            "RuntimeError: forced batch failure for oversized-item\n"
            "  Location: line 45\n"
            "Suggestions:\n"
            "  - Fix the error in the code string above"
        )

        result = _truncate_error_message(message)

        assert result == "RuntimeError: forced batch failure for oversized-item"
        assert "Location:" not in result
        assert "Suggestions:" not in result


class TestFormatSuccessAsText:
    """Tests for full text output formatting."""

    def test_batch_node_in_full_output(self):
        """INTEGRATION: Batch errors remain visible after step-list collapse."""
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 500,
            "execution": {
                "nodes_executed": 2,
                "steps": [
                    {"node_id": "source", "status": "completed", "duration_ms": 100},
                    {
                        "node_id": "process",
                        "status": "completed",
                        "duration_ms": 400,
                        "is_batch": True,
                        "batch_total": 10,
                        "batch_success": 8,
                        "batch_errors": 2,
                        "batch_error_details": [
                            {"index": 1, "error": "Error 1"},
                            {"index": 4, "error": "Error 2"},
                        ],
                    },
                ],
            },
        }
        text = format_success_as_text(result_dict)

        assert "Workflow completed" in text
        assert "Nodes executed" not in text
        assert "✓ source" not in text
        assert "⚠ process" not in text
        assert "Batch 'process' errors:" in text
        assert "[1] Error 1" in text
        assert "[4] Error 2" in text

    def test_batch_full_success_in_full_output(self):
        """INTEGRATION: Successful batch nodes no longer add a static step listing."""
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 200,
            "execution": {
                "nodes_executed": 1,
                "steps": [
                    {
                        "node_id": "process",
                        "status": "completed",
                        "duration_ms": 200,
                        "is_batch": True,
                        "batch_total": 5,
                        "batch_success": 5,
                        "batch_errors": 0,
                        "batch_error_details": [],
                    },
                ],
            },
        }
        text = format_success_as_text(result_dict)

        assert "Workflow completed" in text
        assert "Nodes executed" not in text
        assert "process" not in text
        assert "Batch 'process' errors:" not in text

    def test_multiple_batch_nodes_with_errors(self):
        """INTEGRATION: Multiple batch nodes with errors show all error sections.

        Real bug this catches: Only the first batch node's errors might be shown.
        """
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 500,
            "execution": {
                "nodes_executed": 2,
                "steps": [
                    {
                        "node_id": "batch1",
                        "status": "completed",
                        "duration_ms": 200,
                        "is_batch": True,
                        "batch_total": 5,
                        "batch_success": 4,
                        "batch_errors": 1,
                        "batch_error_details": [{"index": 0, "error": "Batch1 error"}],
                    },
                    {
                        "node_id": "batch2",
                        "status": "completed",
                        "duration_ms": 300,
                        "is_batch": True,
                        "batch_total": 5,
                        "batch_success": 3,
                        "batch_errors": 2,
                        "batch_error_details": [
                            {"index": 1, "error": "Batch2 error 1"},
                            {"index": 2, "error": "Batch2 error 2"},
                        ],
                    },
                ],
            },
        }
        text = format_success_as_text(result_dict)

        assert "Nodes executed" not in text
        assert "Batch 'batch1' errors:" in text
        assert "Batch 'batch2' errors:" in text
        assert "Batch1 error" in text
        assert "Batch2 error 1" in text
        assert "Batch2 error 2" in text

    def test_degraded_status_shows_warning_header(self):
        """REGRESSION: Degraded workflows use the warning-oriented success header.

        Real bug this catches: Success-with-warnings could be formatted like a
        clean success, hiding that the workflow completed in a degraded state.
        """
        result_dict = {
            "success": True,
            "status": "degraded",
            "duration_ms": 250,
            "execution": {"nodes_executed": 1, "steps": []},
        }

        text = format_success_as_text(result_dict)

        assert "Workflow completed with warnings" in text
        assert "Workflow completed in" not in text

    def test_warnings_section_renders_warning_messages(self):
        """REGRESSION: Warnings are shown in the success formatter output.

        Real bug this catches: Warning data could survive execution but be lost
        in the final text output shown to CLI and MCP consumers.

        After diagnostic rendering redesign (Task 144), format_success_as_text
        accepts warning_diagnostics as a parameter instead of reading from the
        result dict's 'warnings' key. Warnings are rendered via format_diagnostic().
        """
        result_dict = {
            "success": True,
            "status": "degraded",
            "duration_ms": 250,
            "warnings": [
                {
                    "node_id": "send-alert",
                    "type": "api_warning",
                    "message": "API error: Rate limit exceeded\nRetry after 30s",
                }
            ],
            "execution": {"nodes_executed": 1, "steps": []},
        }

        warning_diagnostics = [
            Diagnostic(
                severity=Severity.WARNING,
                message="API error: Rate limit exceeded\nRetry after 30s",
                node_id="send-alert",
                source="api_warning",
            )
        ]

        text = format_success_as_text(result_dict, warning_diagnostics=warning_diagnostics)

        assert "\u26a0\ufe0f Warnings:" in text
        assert "[send-alert] API error: Rate limit exceeded" in text
        assert "API error: Rate limit exceeded" in text

    def test_info_advisory_does_not_count_as_warning(self):
        """INFO advisories render under 'Advisories', not 'Warnings', and do not
        trigger the 'completed with N warnings' header.

        Guards ``partition_surfaced_diagnostics``: an empty-batch advisory (and
        other INFO notes like cache advisories) must not make a fully-correct
        run read as warned.
        """
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 100,
            "execution": {"nodes_executed": 1, "steps": []},
        }
        advisory = Diagnostic(
            severity=Severity.INFO,
            message="Batch 'consume' ran with 0 items (input list was empty).",
            node_id="consume",
            source="runtime",
        )

        text = format_success_as_text(result_dict, warning_diagnostics=[advisory])

        assert "\u2713 Workflow completed in" in text  # clean \u2713 header
        assert "with 1 warnings" not in text
        assert "\u26a0\ufe0f Warnings:" not in text
        assert "Advisories:" in text
        assert "ran with 0 items" in text

    def test_format_execution_success_serializes_warning_diagnostics_for_json(self):
        """REGRESSION: Warning diagnostics stay structured in success JSON output.

        Real bug this catches: Raw Diagnostic objects under ``warnings`` get
        stringified to ``Diagnostic(...)`` reprs by JSON serialization.

        After diagnostic rendering redesign (Task 144), Diagnostic uses
        ``title`` and ``suggestions`` (list) instead of ``suggestion`` (str).
        ``to_display_dict()`` serializes these new fields. ``to_dict()`` is used
        for the ``diagnostics`` key (without context merging).
        """
        result = format_execution_success(
            shared_storage={"stdout": "ok"},
            workflow_ir={},
            metrics_collector=None,
            warnings=[
                Diagnostic(
                    severity=Severity.WARNING,
                    message="Shell node has no template inputs",
                    suggestions=["Use '- cache: true' only if output is purely a function of declared inputs."],
                    node_id="run-shell",
                    source="validator",
                )
            ],
        )

        # warnings uses to_display_dict() — includes suggestions as list
        assert result["warnings"] == [
            {
                "severity": "warning",
                "message": "Shell node has no template inputs",
                "source": "validator",
                "suggestions": ["Use '- cache: true' only if output is purely a function of declared inputs."],
                "node_id": "run-shell",
            }
        ]
        # diagnostics uses to_dict() — same shape (no context to merge here)
        assert result["diagnostics"] == [
            {
                "severity": "warning",
                "message": "Shell node has no template inputs",
                "source": "validator",
                "suggestions": ["Use '- cache: true' only if output is purely a function of declared inputs."],
                "node_id": "run-shell",
            }
        ]

    def test_info_advisory_goes_to_advisories_not_warnings_in_json(self):
        """REGRESSION: INFO advisories must not appear under ``warnings`` in the
        success dict — JSON/MCP consumers count ``warnings``. They belong under
        ``advisories``; ``diagnostics`` keeps the full severity-tagged list.

        This is the JSON-surface half of the empty-batch advisory fix: the text
        renderer already splits Warnings vs Advisories; the structured output
        must match (CLI/JSON parity).
        """
        result = format_execution_success(
            shared_storage={"stdout": "ok"},
            workflow_ir={},
            metrics_collector=None,
            warnings=[
                Diagnostic(
                    severity=Severity.WARNING,
                    message="a real warning",
                    node_id="w",
                    source="runtime",
                ),
                Diagnostic(
                    severity=Severity.INFO,
                    message="Batch 'b' ran with 0 items (input list was empty).",
                    node_id="b",
                    source="runtime",
                ),
            ],
        )

        assert [w["message"] for w in result["warnings"]] == ["a real warning"]
        assert [a["message"] for a in result["advisories"]] == ["Batch 'b' ran with 0 items (input list was empty)."]
        # Full list (both severities) stays under diagnostics.
        assert [d["severity"] for d in result["diagnostics"]] == ["warning", "info"]

    def test_format_execution_success_compacts_degraded_batch_error_details_for_json(self):
        """Degraded success JSON must not expose full failed batch items."""

        class Metrics:
            def get_summary(self, llm_calls=None):
                return {
                    "duration_ms": 100,
                    "metrics": {"workflow": {"nodes_executed": 1, "node_timings": {"process": 100}}},
                }

        payload = "PAYLOAD-START " + " ".join(f"token{i}" for i in range(200)) + " PAYLOAD-END"
        shared = {
            "__execution__": {"completed_nodes": ["process"], "failed_node": None},
            "process": {
                "count": 2,
                "success_count": 1,
                "error_count": 1,
                "results": [{"item": "ok", "response": "ok"}],
                "errors": [
                    {
                        "index": 1,
                        "item": {"label": "oversized-item", "payload": payload},
                        "item_summary": {
                            "summary_version": 1,
                            "type": "dict",
                            "label": "oversized-item",
                            "size_chars": len(payload),
                            "sha256": "123456789abc",
                            "summary": "label='oversized-item'; payload=<str 1909 chars sha256=123456789abc>",
                            "truncated": True,
                        },
                        "error": "forced batch failure",
                        "exception": RuntimeError("boom"),
                    }
                ],
                "batch_metadata": {"execution_mode": "sequential"},
            },
        }
        workflow_ir = {"nodes": [{"id": "process"}]}

        output = format_execution_success(shared, workflow_ir, metrics_collector=Metrics())

        detail = output["execution"]["steps"][0]["batch_error_details"][0]
        assert detail["item_summary"]["label"] == "oversized-item"
        assert detail["item_ref"] == "123456789abc"
        assert detail["has_full_item"] is True
        assert "item" not in detail
        assert "exception" not in detail

        output_error = output["result"]["process"]["errors"][0]
        assert output_error["item_summary"]["label"] == "oversized-item"
        assert output_error["has_full_item"] is True
        assert "item" not in output_error
        assert output["result"]["process"]["results"][0]["item"] == "ok"


class TestPricingUnavailableWarning:
    """Tests for cost display when model pricing is unavailable."""

    def _make_result_dict(
        self,
        pricing_available: bool = True,
        unavailable_models: list[dict[str, object]] | None = None,
        partial_cost_usd: float | None = None,
        total_cost_usd: float | None = None,
        unavailable_models_unnamed_count: int = 0,
        total_calls: int = 0,
    ) -> dict:
        """Build a synthetic result dict for cost-display tests.

        ``unavailable_models`` uses the F#17-deferred shape ``list[{name, calls}]``.
        Tests that need to exercise the legacy ``list[str]`` shape pass that
        directly; the renderer's normalizer accepts both for forward-compat.
        """
        metrics: dict = {
            "workflow": {"duration_ms": 100, "nodes_executed": 1, "total_tokens": 10},
            "total": {
                "tokens_input": 5,
                "tokens_output": 5,
                "tokens_total": 10,
                "total_calls": total_calls,
                "cost_usd": total_cost_usd,
            },
        }
        if not pricing_available:
            metrics["total"]["pricing_available"] = False
            metrics["total"]["unavailable_models"] = unavailable_models or []
            metrics["total"]["unavailable_models_unnamed_count"] = unavailable_models_unnamed_count
            if partial_cost_usd is not None:
                metrics["total"]["partial_cost_usd"] = partial_cost_usd
        return {
            "success": True,
            "status": "success",
            "duration_ms": 100,
            "total_cost_usd": total_cost_usd,
            "execution": {"nodes_executed": 1, "steps": []},
            "metrics": metrics,
        }

    def test_unknown_model_shows_warning(self):
        """When all models lack pricing, show warning with model names."""
        result_dict = self._make_result_dict(
            pricing_available=False,
            unavailable_models=[{"name": "my-custom-model", "calls": 5}],
            total_calls=5,
        )
        text = format_success_as_text(result_dict)

        assert "Cost unavailable" in text
        assert "my-custom-model (5 calls)" in text
        # F#17 deferred: total LLM calls sibling line
        assert "Total LLM calls: 5" in text

    def test_partial_cost_shows_partial_amount(self):
        """When some models have pricing, show partial cost with disclaimer."""
        result_dict = self._make_result_dict(
            pricing_available=False,
            unavailable_models=[{"name": "unknown-model", "calls": 2}],
            partial_cost_usd=0.03,
            total_calls=3,
        )
        text = format_success_as_text(result_dict)

        assert "$0.0300+" in text
        assert "partial" in text
        assert "unknown-model (2 calls)" in text
        assert "Total LLM calls: 3" in text

    def test_known_model_shows_normal_cost(self):
        """When pricing is available, show normal cost line."""
        result_dict = self._make_result_dict(total_cost_usd=0.05, total_calls=2)
        text = format_success_as_text(result_dict)

        assert "$0.0500" in text
        assert "Cost unavailable" not in text
        # F#17 deferred: priced multi-call line integrates call count
        assert "2 calls" in text

    def test_known_model_singular_call_uses_singular_noun(self):
        """F#17 wording lock: a single LLM call renders as ``1 call`` not
        ``1 calls`` in the priced cost line.
        """
        result_dict = self._make_result_dict(total_cost_usd=0.05, total_calls=1)
        text = format_success_as_text(result_dict)
        assert "$0.0500" in text
        assert "1 call" in text
        assert "1 calls" not in text

    def test_unnamed_only_renders_count_phrase(self):
        """When all unpriced calls are genuinely-unrecorded, the rendered
        phrase surfaces the count rather than the literal ``"unknown"``."""
        result_dict = self._make_result_dict(
            pricing_available=False,
            unavailable_models=[],
            unavailable_models_unnamed_count=2,
            total_calls=2,
        )
        text = format_success_as_text(result_dict)
        assert "2 calls without recorded model" in text
        assert "unknown" not in text
        assert "Total LLM calls: 2" in text

    def test_named_plus_unnamed_renders_both(self):
        """A mix of real names and unnamed-count surfaces both in the
        rendered phrase joined by ``"; "``."""
        result_dict = self._make_result_dict(
            pricing_available=False,
            unavailable_models=[{"name": "gpt-5", "calls": 3}],
            unavailable_models_unnamed_count=1,
            partial_cost_usd=0.0234,
            total_calls=4,
        )
        text = format_success_as_text(result_dict)
        # Locked wording from F#17 deferred spec
        assert "gpt-5 (3 calls); 1 call without recorded model" in text
        assert "Total LLM calls: 4" in text

    def test_total_llm_calls_suppressed_when_zero(self):
        """Honest unmeasurable: workflows that never invoke an LLM must
        NOT see a ``Total LLM calls: 0`` line."""
        result_dict = self._make_result_dict(total_cost_usd=0.0, total_calls=0)
        text = format_success_as_text(result_dict)
        assert "Total LLM calls" not in text


class TestOnlyNodeDisplay:
    """Tests for --only flag display behavior in text output."""

    def _make_result_dict(
        self,
        steps: list[dict],
        only_node: str | None = None,
        nodes_skipped: int = 0,
        status: str = "success",
    ) -> dict:
        """Build a minimal result dict for format_success_as_text."""
        completed_count = sum(1 for s in steps if s["status"] == "completed")
        nodes_total = len(steps)
        execution: dict = {
            "nodes_executed": completed_count,
            "nodes_total": nodes_total,
            "steps": steps,
        }
        if only_node is not None:
            execution["only_node"] = only_node
            execution["nodes_skipped"] = nodes_skipped
        return {
            "success": True,
            "status": status,
            "duration_ms": 200,
            "execution": execution,
        }

    def test_only_node_filters_not_executed_in_text(self):
        """CORRECTNESS: --only preserves summary context without step listings."""
        steps = [
            {"node_id": "fetch", "status": "completed", "duration_ms": 50},
            {"node_id": "process", "status": "completed", "duration_ms": 100},
            {"node_id": "save", "status": "not_executed", "duration_ms": 0},
            {"node_id": "notify", "status": "not_executed", "duration_ms": 0},
        ]
        result_dict = self._make_result_dict(steps, only_node="process", nodes_skipped=2)
        text = format_success_as_text(result_dict)

        assert "Nodes executed" not in text
        assert "fetch" not in text
        assert "process" in text
        assert "save" not in text
        assert "notify" not in text
        assert "⤷ Stopped after 'process' (--only), 2 remaining nodes skipped" in text

    def test_only_node_not_set_shows_all_steps(self):
        """CORRECTNESS: Without --only, no summary line is emitted."""
        steps = [
            {"node_id": "fetch", "status": "completed", "duration_ms": 50},
            {"node_id": "broken", "status": "not_executed", "duration_ms": 0},
        ]
        result_dict = self._make_result_dict(steps)
        text = format_success_as_text(result_dict)

        assert "Nodes executed" not in text
        assert "fetch" not in text
        assert "broken" not in text
        assert "⤷" not in text

    def test_only_node_single_skipped_uses_singular(self):
        """FORMAT: Singular 'node' when only 1 is skipped.

        Real bug this catches: Grammar error ("1 remaining nodes skipped") makes
        CLI output look unprofessional to agents parsing text.
        """
        steps = [
            {"node_id": "fetch", "status": "completed", "duration_ms": 50},
            {"node_id": "save", "status": "not_executed", "duration_ms": 0},
        ]
        result_dict = self._make_result_dict(steps, only_node="fetch", nodes_skipped=1)
        text = format_success_as_text(result_dict)

        assert "1 remaining node skipped" in text
        assert "1 remaining nodes skipped" not in text

    def test_only_node_zero_skipped_emits_short_form(self):
        """CORRECTNESS: --only mode confirmation is emitted even when no
        downstream nodes were skipped (e.g., --only targeted the last node).

        Real bug this catches (Task 149 review sub-issue 8a): without this
        line, the rendered output of ``pflow foo --only target_c`` (where
        target_c is the last node) is byte-identical to a full ``pflow foo``
        run. Agents doing iterative debugging cannot disambiguate
        constrained runs from full runs from the rendered output alone.

        ``--only`` is a mode signal, not a summary detail. Mode flags are
        always announced regardless of verbosity (matches ``make -k``,
        ``pytest --maxfail``, ``rsync --dry-run``, etc.).

        The original concern this test guarded against — "showing '0
        remaining nodes skipped' is confusing" — is preserved by emitting
        a short form (``Stopped after 'X' (--only)``) without any
        "N remaining" suffix when no nodes were skipped.
        """
        steps = [
            {"node_id": "fetch", "status": "completed", "duration_ms": 50},
            {"node_id": "process", "status": "completed", "duration_ms": 100},
        ]
        result_dict = self._make_result_dict(steps, only_node="process", nodes_skipped=0)
        text = format_success_as_text(result_dict)

        # The mode confirmation must be emitted (sub-issue 8a fix)
        assert "⤷ Stopped after 'process' (--only)" in text
        # But not the "0 remaining" noise (original test's valid concern)
        assert "0 remaining" not in text
        assert "remaining node skipped" not in text
        assert "remaining nodes skipped" not in text


class TestCacheStatsDisplay:
    """Tests for cache hit statistics in completion header."""

    def _make_result_dict(
        self,
        cache_hits: int = 0,
        nodes_executed: int = 5,
        status: str = "success",
        duration_ms: int = 500,
    ) -> dict:
        """Build a minimal result dict with cache stats."""
        execution: dict = {
            "nodes_executed": nodes_executed,
            "steps": [],
        }
        if cache_hits > 0:
            execution["cache_hits"] = cache_hits
        return {
            "success": True,
            "status": status,
            "duration_ms": duration_ms,
            "execution": execution,
        }

    def test_cache_stats_shown_in_header(self):
        """CORRECTNESS: Cache hits and fresh executions shown in completion header.

        Real bug this catches: Without cache stats, agents can't tell whether
        re-runs actually re-executed nodes or served cached results.
        """
        result_dict = self._make_result_dict(cache_hits=3, nodes_executed=5)
        text = format_success_as_text(result_dict)

        assert "(3 cached, 2 executed)" in text
        assert "✓ Workflow completed in" in text

    def test_no_cache_stats_when_zero_hits(self):
        """CORRECTNESS: No cache suffix when there are no cache hits.

        Real bug this catches: Showing "(0 cached, 5 executed)" adds noise
        when caching wasn't involved at all.
        """
        result_dict = self._make_result_dict(cache_hits=0, nodes_executed=5)
        text = format_success_as_text(result_dict)

        assert "(cached" not in text

    def test_cache_stats_with_all_cached(self):
        """CORRECTNESS: All nodes cached shows zero fresh executions.

        Real bug this catches: Math error in (nodes_executed - cache_hits) could
        produce negative numbers or wrong counts.
        """
        result_dict = self._make_result_dict(cache_hits=3, nodes_executed=3)
        text = format_success_as_text(result_dict)

        assert "(3 cached, 0 executed)" in text

    def test_cache_stats_with_degraded_status(self):
        """INTEGRATION: Degraded status + cache stats both appear in header.

        Real bug this catches: Cache suffix could be lost when the degraded
        header path is taken instead of the success path.
        """
        result_dict = self._make_result_dict(cache_hits=2, nodes_executed=4, status="degraded")
        text = format_success_as_text(result_dict)

        assert "with warnings" in text
        assert "(2 cached, 2 executed)" in text


class TestAppendExecutionStepsOnlyNode:
    """Tests for _append_execution_steps after per-node block removal."""

    def test_only_node_keeps_summary_without_step_lines(self):
        """CORRECTNESS: _append_execution_steps keeps only the --only summary line."""
        execution = {
            "only_node": "process",
            "nodes_skipped": 1,
            "nodes_total": 3,
            "nodes_executed": 2,
            "steps": [
                {"node_id": "fetch", "status": "completed", "duration_ms": 50},
                {"node_id": "process", "status": "completed", "duration_ms": 100},
                {"node_id": "save", "status": "not_executed", "duration_ms": 0},
            ],
        }
        lines: list[str] = []
        _append_execution_steps(lines, execution)

        joined = "\n".join(lines)
        assert "process" in joined
        assert "save" not in joined
        assert "fetch" not in joined

    def test_shows_summary_line(self):
        """CORRECTNESS: Summary line with stop reason appears when nodes are skipped.

        Real bug this catches: Missing summary line means agents don't know the
        workflow was intentionally cut short by --only.
        """
        execution = {
            "only_node": "process",
            "nodes_skipped": 2,
            "nodes_total": 4,
            "nodes_executed": 2,
            "steps": [
                {"node_id": "fetch", "status": "completed", "duration_ms": 50},
                {"node_id": "process", "status": "completed", "duration_ms": 100},
                {"node_id": "save", "status": "not_executed", "duration_ms": 0},
                {"node_id": "notify", "status": "not_executed", "duration_ms": 0},
            ],
        }
        lines: list[str] = []
        _append_execution_steps(lines, execution)

        assert any("⤷" in line for line in lines)
        assert any("2 remaining nodes skipped" in line for line in lines)

    def test_without_only_emits_no_step_lines(self):
        """REGRESSION: Without only_node, no supplementary step lines are emitted."""
        execution = {
            "nodes_executed": 1,
            "steps": [
                {"node_id": "fetch", "status": "completed", "duration_ms": 50},
                {"node_id": "skipped", "status": "not_executed", "duration_ms": 0},
            ],
        }
        lines: list[str] = []
        _append_execution_steps(lines, execution)

        assert lines == []

    def test_only_with_zero_skipped_emits_short_form(self):
        """SUB-ISSUE 8a: --only with 0 nodes skipped (target was the last node)
        must still emit the mode confirmation, in short form.

        Without this, the rendered output is byte-identical to a full run
        and agents cannot disambiguate constrained runs from full runs.
        """
        execution = {
            "only_node": "target_c",
            "nodes_skipped": 0,
            "nodes_executed": 3,
            "steps": [
                {"node_id": "target_a", "status": "completed", "duration_ms": 10},
                {"node_id": "target_b", "status": "completed", "duration_ms": 10},
                {"node_id": "target_c", "status": "completed", "duration_ms": 10},
            ],
        }
        lines: list[str] = []
        _append_execution_steps(lines, execution)

        joined = "\n".join(lines)
        assert "⤷ Stopped after 'target_c' (--only)" in joined
        # Short form: no "N remaining" suffix when nothing was skipped
        assert "remaining" not in joined
        assert "0 " not in joined  # no "0 remaining" anywhere


class TestFormatOnlyIndicator:
    """Tests for the shared --only indicator formatter (single source of truth).

    PARITY GUARDRAIL — three call sites depend on this formatter producing
    consistent text:
    - CLI default-mode summary (workflow_output.py::_display_execution_summary)
    - CLI -p mode emission (workflow_output.py::_emit_only_indicator)
    - MCP text summary (success_formatter.py::_append_execution_steps)
    """

    def test_long_form_when_nodes_skipped(self):
        """With skipped nodes, the long form shows the count and grammar."""
        line = format_only_indicator("target_b", nodes_skipped=2)

        assert "⤷ Stopped after 'target_b' (--only)" in line
        assert "2 remaining nodes skipped" in line

    def test_short_form_when_no_nodes_skipped(self):
        """SUB-ISSUE 8a: with 0 skipped nodes (target was last), the short
        form omits the 'N remaining' suffix to avoid '0 remaining nodes
        skipped' noise while still announcing the --only mode."""
        line = format_only_indicator("target_c", nodes_skipped=0)

        assert "⤷ Stopped after 'target_c' (--only)" in line
        assert "remaining" not in line
        assert "0 " not in line

    def test_singular_grammar_for_one_skipped_node(self):
        """One skipped node uses singular 'node', not plural 'nodes'."""
        line = format_only_indicator("target_a", nodes_skipped=1)

        assert "1 remaining node skipped" in line
        assert "1 remaining nodes skipped" not in line

    def test_node_id_with_special_characters_quoted_correctly(self):
        """Node IDs are quoted with single quotes — no escaping shenanigans."""
        line = format_only_indicator("my-node.with.dots", nodes_skipped=3)

        assert "'my-node.with.dots'" in line


class TestAppendOutputsCliMcpParity:
    """Tests for `_append_outputs` MCP-side rendering matching CLI ``safe_output``.

    PARITY GUARDRAIL — the CLI ``safe_output`` and the MCP success formatter
    must agree on how structured workflow outputs are rendered. The plan's
    Decision 1 caught the per-node block twin; the post-merge Fix #1 (commit
    7f2d61b3) updated CLI ``safe_output`` to JSON-encode dict/list/bool/None
    outputs, but the MCP twin in ``_append_outputs`` was missed and kept
    using ``str(value)`` (Python repr). These tests prevent that drift from
    coming back.
    """

    def _make_result_dict_with_output(self, output_value: object) -> dict:
        return {
            "success": True,
            "status": "success",
            "duration_ms": 100,
            "execution": {"nodes_executed": 1, "steps": []},
            "result": {"value": output_value},
        }

    def test_string_output_passes_through_verbatim(self):
        """CORRECTNESS: String outputs are not JSON-quoted (matches CLI safe_output)."""
        result_dict = self._make_result_dict_with_output("hello world")
        text = format_success_as_text(result_dict)

        assert "hello world" in text
        # Must NOT be JSON-quoted ("hello world" with quotes)
        assert '"hello world"' not in text

    def test_dict_output_emits_valid_json(self):
        """REGRESSION: Dict outputs must serialize as JSON, not Python repr.

        Real bug this catches: ``str({"key": "value"})`` produces single-quoted
        ``{'key': 'value'}`` which jq and json.loads cannot parse. Agents using
        the MCP ``workflow_execute`` tool with structured outputs get
        unparseable text and have to fall back to text munging.
        """
        import json as _json

        result_dict = self._make_result_dict_with_output({"key": "value", "n": 42})
        text = format_success_as_text(result_dict)

        # Find the JSON line and round-trip through json.loads
        lines = text.split("\n")
        json_lines = [line for line in lines if line.startswith("{")]
        assert json_lines, f"No JSON output line in:\n{text}"
        parsed = _json.loads(json_lines[0])
        assert parsed == {"key": "value", "n": 42}

    def test_list_output_emits_valid_json(self):
        """REGRESSION: List outputs must serialize as JSON arrays."""
        import json as _json

        result_dict = self._make_result_dict_with_output(["a", "b", "c"])
        text = format_success_as_text(result_dict)

        json_lines = [line for line in text.split("\n") if line.startswith("[")]
        assert json_lines, f"No JSON array line in:\n{text}"
        assert _json.loads(json_lines[0]) == ["a", "b", "c"]

    def test_bool_output_emits_lowercase_json_token(self):
        """REGRESSION: Bool outputs must be JSON ``true``/``false``, not Python ``True``/``False``."""
        result_dict = self._make_result_dict_with_output(True)
        text = format_success_as_text(result_dict)

        assert "\ntrue" in text or text.endswith("true")
        assert "True" not in text

    def test_none_output_emits_json_null(self):
        """REGRESSION: None outputs must be JSON ``null``, not Python ``None``."""
        result_dict = self._make_result_dict_with_output(None)
        text = format_success_as_text(result_dict)

        assert "\nnull" in text or text.endswith("null")
        assert "None" not in text

    def test_unserializable_output_falls_back_without_raising(self):
        """SAFETY: Non-serializable values fall back to ``str()`` instead of raising.

        ``default=str`` inside json.dumps catches datetime, Path, set, etc.,
        so the value lands in a JSON string. The except clause only fires for
        truly catastrophic failures (e.g. NaN inside a dict with default=str).
        """
        from datetime import datetime

        result_dict = self._make_result_dict_with_output(datetime(2026, 4, 7, 12, 0, 0))
        text = format_success_as_text(result_dict)

        # Must not raise, must contain something parseable as the date
        assert "2026-04-07" in text

    def test_nan_output_falls_back_to_repr_without_raising(self):
        """PARITY: Values that defeat ``default=str`` (e.g., NaN with
        ``allow_nan=False``) must fall through to the ``repr()`` fallback —
        **not** ``str()`` — to match CLI ``safe_output``.

        ``allow_nan=False`` makes ``json.dumps`` raise ``ValueError`` on NaN
        before ``default=str`` gets a chance, so a dict containing a NaN value
        triggers the except clause. Before Task 149's review fix, MCP used
        ``str(first_value)`` here while CLI used ``repr(first_value)`` — this
        test locks them to the same fallback shape.
        """
        nan_value = {"x": float("nan")}
        result_dict = self._make_result_dict_with_output(nan_value)
        text = format_success_as_text(result_dict)

        # Must not raise, must contain some non-empty representation
        assert text
        # The repr fallback is exercised (either "nan" or "NaN" visible somewhere)
        assert "nan" in text.lower()

    def test_cli_mcp_parity_dotted_output_key(self):
        """PARITY: CLI text mode and MCP text mode emit identical resolved values
        for a dotted ``-o`` path against the same shared store.

        Locks the §4.7 fix in ``_collect_outputs`` against drift — both surfaces
        share that function, so a regression that re-introduces flat-only lookup
        would silently break both at once.
        """
        from pflow.execution.formatters.success_formatter import _collect_outputs

        shared = {
            "batch-llm": {
                "results": [{"r": "a"}],
                "count": 1,
                "success_count": 1,
                "error_count": 0,
                "errors": None,
                "batch_metadata": {"timing": {"total_items_ms": 1400.0}},
            }
        }
        outputs = _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.success_count")
        assert outputs == {"batch-llm.success_count": 1}

        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 100,
            "execution": {"nodes_executed": 1, "steps": []},
            "result": outputs,
        }
        text = format_success_as_text(result_dict)
        assert "\n1" in text or text.endswith("1")


class TestCollectOutputsDottedPath:
    """JSON-mode dotted ``-o`` resolution in ``_collect_outputs``.

    Drives the same shared helper that backs both CLI ``--output-format json``
    and MCP ``execute_workflow`` text/JSON output. Symmetric to the CLI text-
    mode ``TestOutputKeyDottedPath`` in ``test_workflow_output_handling.py``.
    """

    def test_resolves_dotted_output_key(self):
        from pflow.execution.formatters.success_formatter import _collect_outputs

        shared = {"batch-llm": {"success_count": 2, "count": 2, "errors": None}}
        result = _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.success_count")
        assert result == {"batch-llm.success_count": 2}

    def test_resolved_none_emits_null(self):
        """``-o batch.errors`` on a successful batch preserves the ``None`` value
        in the JSON outputs dict — distinct from "key missing"."""
        from pflow.execution.formatters.success_formatter import _collect_outputs

        shared = {"batch-llm": {"errors": None, "success_count": 1, "count": 1}}
        result = _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.errors")
        assert result == {"batch-llm.errors": None}

    def test_missing_key_returns_empty(self):
        """JSON-mode silently omits a missed key — no human-prose hint."""
        from pflow.execution.formatters.success_formatter import _collect_outputs

        shared = {"batch-llm": {"success_count": 2}}
        result = _collect_outputs(shared, workflow_ir={}, output_key="nonexistent.foo")
        assert result == {}

    def test_list_index_path(self):
        from pflow.execution.formatters.success_formatter import _collect_outputs

        shared = {"batch-llm": {"results": [{"r": "alpha"}, {"r": "beta"}]}}
        result = _collect_outputs(shared, workflow_ir={}, output_key="batch-llm.results[1].r")
        assert result == {"batch-llm.results[1].r": "beta"}


class TestStderrWarningsCliMcpParity:
    """Tests for ``format_stderr_warnings`` shared helper + MCP rendering parity.

    PARITY GUARDRAIL — shell nodes that exit 0 but wrote to stderr are an
    important agent signal (hidden pipeline failures). CLI ``_display_stderr_warnings``
    has emitted a ``⚠️  Shell stderr (exit code 0):`` block and upgraded the
    completion glyph from ``✓`` to ``⚠️`` since GH #194 shipped. The MCP side
    (``format_success_as_text``) was silently missing both behaviors, so an
    agent calling the MCP ``workflow_execute`` tool on a workflow with a
    failing grep pipeline would see ``✓ Workflow completed`` with no visibility.

    These tests lock CLI and MCP into the same rendering so that drift
    between them is caught at test time rather than by a confused agent.
    """

    def _make_result_dict_with_stderr_step(
        self,
        *,
        stderr_text: str = "warning: something wrong",
        node_id: str = "run_pipeline",
    ) -> dict:
        """Build a minimal success dict with one shell step that wrote to stderr."""
        return {
            "success": True,
            "status": "success",  # exit 0 — DEGRADED is not involved
            "duration_ms": 100,
            "execution": {
                "nodes_executed": 1,
                "nodes_total": 1,
                "steps": [
                    {
                        "node_id": node_id,
                        "status": "completed",
                        "has_stderr": True,
                        "stderr": stderr_text,
                    }
                ],
            },
            "result": {"output": "ok"},
        }

    def test_format_stderr_warnings_returns_empty_when_no_warnings(self):
        """No steps with has_stderr → empty list (helper is a no-op signal)."""
        lines = format_stderr_warnings([
            {"node_id": "clean", "has_stderr": False, "stderr": ""},
            {"node_id": "also_clean", "status": "completed"},
        ])
        assert lines == []

    def test_format_stderr_warnings_skips_empty_stderr(self):
        """has_stderr=True but empty stderr string → skipped.

        Defensive: if the step dict has a stale has_stderr flag but no actual
        stderr content, don't render an empty bullet.
        """
        lines = format_stderr_warnings([
            {"node_id": "flagged_but_empty", "has_stderr": True, "stderr": ""},
        ])
        assert lines == []

    def test_format_stderr_warnings_returns_header_and_bullet(self):
        """Single stderr warning → blank line + header + one bullet."""
        lines = format_stderr_warnings([
            {"node_id": "grep_pipe", "has_stderr": True, "stderr": "grep: foo: No such file"},
        ])
        assert lines[0] == ""  # blank line separates from preceding content
        assert "⚠️  Shell stderr (exit code 0):" in lines[1]
        assert any("grep_pipe" in line and "No such file" in line for line in lines[2:])

    def test_format_stderr_warnings_truncates_long_stderr(self):
        """Stderr over 300 chars → truncated with ellipsis."""
        long_stderr = "x" * 500
        lines = format_stderr_warnings([
            {"node_id": "noisy", "has_stderr": True, "stderr": long_stderr},
        ])
        bullet = next(line for line in lines if "noisy" in line)
        assert "..." in bullet
        # Bullet contains "x" * 300 + "..." (plus the "  • noisy: " prefix)
        assert bullet.count("x") == 300

    def test_format_stderr_warnings_indents_multiline_stderr(self):
        """Multi-line stderr → each continuation line indented 5 spaces for readability."""
        lines = format_stderr_warnings([
            {"node_id": "multi", "has_stderr": True, "stderr": "first line\nsecond line"},
        ])
        bullet = next(line for line in lines if "multi" in line)
        assert "first line" in bullet
        assert "\n     second line" in bullet  # 5-space continuation indent

    def test_mcp_text_upgrades_glyph_when_shell_node_wrote_stderr(self):
        """REGRESSION: MCP ``format_success_as_text`` must render ``⚠️ Workflow completed``
        (not ``✓``) when any step has ``has_stderr``, matching CLI behavior.

        Before this fix, MCP callers got ``✓ Workflow completed in Xs`` for
        workflows where a shell pipeline silently failed (e.g., a failed grep
        inside a chain that produced a non-empty `final_result`). Agents relying
        on the glyph to detect "something needs attention" saw a clean success.
        """
        result_dict = self._make_result_dict_with_stderr_step(stderr_text="ERR: upstream failed")
        text = format_success_as_text(result_dict)

        assert "⚠️ Workflow completed" in text
        # Must NOT render the clean-success glyph
        # (starts-with check avoids matching ``✓`` inside the stderr preview)
        completion_lines = [line for line in text.split("\n") if "Workflow completed" in line]
        assert completion_lines, f"No completion line in:\n{text}"
        for line in completion_lines:
            assert "✓" not in line, f"Completion line contains ✓ but shell stderr was present: {line!r}"

    def test_mcp_text_renders_stderr_warning_block(self):
        """REGRESSION: MCP ``format_success_as_text`` must include the
        ``⚠️  Shell stderr (exit code 0):`` block + per-node bullet.
        """
        result_dict = self._make_result_dict_with_stderr_step(
            stderr_text="grep: /tmp/missing: No such file or directory",
            node_id="search_logs",
        )
        text = format_success_as_text(result_dict)

        assert "⚠️  Shell stderr (exit code 0):" in text
        assert "search_logs" in text
        assert "No such file" in text

    def test_mcp_text_clean_success_stays_clean(self):
        """REGRESSION GUARD: workflows without shell stderr still get ``✓`` glyph
        and no stderr block. Protects against over-correction where every
        workflow starts showing ⚠️.
        """
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 50,
            "execution": {
                "nodes_executed": 1,
                "nodes_total": 1,
                "steps": [
                    {"node_id": "clean", "status": "completed", "has_stderr": False},
                ],
            },
            "result": {"output": "ok"},
        }
        text = format_success_as_text(result_dict)

        assert "✓ Workflow completed" in text
        assert "Shell stderr" not in text
        # Must not upgrade glyph
        completion_lines = [line for line in text.split("\n") if "Workflow completed" in line]
        for line in completion_lines:
            assert "⚠️" not in line


class TestFindAutoOutputNamespaceAware:
    """Tests for namespace-aware JSON auto-detection.

    find_auto_output serves ALL JSON/MCP output. A regression here silently
    changes what agents receive — no error, just different data.
    """

    def test_finds_stdout_inside_namespace(self):
        """REGRESSION: Shell node stdout must be found inside namespace dict.

        Without namespace traversal, shell nodes fall to last-key heuristic
        and return the full namespace dict (command, exit_code, stderr, etc.)
        instead of just the stdout value. Agents get garbage.
        """
        shared = {
            "__execution__": {"completed_nodes": ["fetch"]},
            "fetch": {"stdout": "hello world", "exit_code": 0, "command": "echo hello"},
        }
        key, value = find_auto_output(shared)

        assert key == "stdout"
        assert value == "hello world"

    def test_last_occurrence_wins_for_same_key(self):
        """REGRESSION: Most downstream node's output must be returned.

        In a sequential pipeline (A → B), both write stdout. The agent expects
        B's output (the final result), not A's.
        """
        shared = {
            "__execution__": {},
            "step-a": {"stdout": "upstream output"},
            "step-b": {"stdout": "final output"},
        }
        key, value = find_auto_output(shared)

        assert key == "stdout"
        assert value == "final output"

    def test_root_level_keys_take_priority_over_namespaces(self):
        """REGRESSION: Declared outputs populated at root level must win.

        Normal workflow runs call populate_declared_outputs() which writes
        resolved values to root level. These must take priority over
        namespace traversal to avoid breaking declared output workflows.
        """
        shared = {
            "__execution__": {},
            "process": {"stdout": "raw shell output"},
            "result": "clean declared output",  # populated by populate_declared_outputs
        }
        key, value = find_auto_output(shared)

        assert key == "result"
        assert value == "clean declared output"

    def test_mcp_json_only_uses_target_scoped_output_selection(self):
        """--only JSON output unwraps the target node, not unrelated root data."""
        shared = {
            "__execution__": {"only_node": "fetch"},
            "result": "unrelated root result",
            "fetch": {"stdout": "target stdout", "exit_code": 0},
        }
        workflow_ir = {
            "outputs": {"result": {"source": "${downstream.stdout}"}},
        }
        output = format_execution_success(shared, workflow_ir, metrics_collector=None)

        assert output["result"] == {"stdout": "target stdout"}

    def test_mcp_json_full_run_declared_outputs_remain_unchanged(self):
        """Full-run JSON output still emits all declared outputs."""
        shared = {
            "alpha": "A",
            "beta": "B",
            "fetch": {"stdout": "raw node stdout"},
        }
        workflow_ir = {
            "outputs": {
                "alpha": {"source": "${fetch.stdout}"},
                "beta": {"source": "${other.stdout}"},
            },
        }
        output = format_execution_success(shared, workflow_ir, metrics_collector=None)

        assert output["result"] == {"alpha": "A", "beta": "B"}

    def test_mcp_json_dotted_only_returns_target_namespace(self):
        """GH #344 regression guard: MCP JSON output for dotted --only on a
        batch sub-workflow must return the target's namespace, not a shadowing
        declared output at root.

        ``format_execution_success`` must use target-scoped ``find_only_output``
        when --only is active, so the user's explicit target wins over
        unrelated resolved declared outputs.
        """
        shared = {
            "__execution__": {"only_node": "process-all.echo"},
            # Unrelated upstream declared output that resolved at root
            "result": ["upstream", "data", "NOT", "what", "user", "wants"],
            # Target: the batch node's namespace
            "process-all": {
                "results": [{"result": "hello", "item": "hello"}],
                "count": 1,
            },
        }
        workflow_ir = {
            "outputs": {"result": {"source": "${upstream.stdout}"}},
        }
        output = format_execution_success(shared, workflow_ir, metrics_collector=None)
        outputs = output["result"]

        # The target namespace must be what we return — not the shadowing 'result'
        assert "process-all" in outputs
        assert outputs["process-all"] == {
            "results": [{"result": "hello", "item": "hello"}],
            "count": 1,
        }
        # The shadowing unrelated value must NOT be what we return
        assert "result" not in outputs or outputs.get("result") != [
            "upstream",
            "data",
            "NOT",
            "what",
            "user",
            "wants",
        ]
