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
                    suggestions=["Add '- cache: false' if this node reads runtime state."],
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
                "suggestions": ["Add '- cache: false' if this node reads runtime state."],
                "node_id": "run-shell",
            }
        ]
        # diagnostics uses to_dict() — same shape (no context to merge here)
        assert result["diagnostics"] == [
            {
                "severity": "warning",
                "message": "Shell node has no template inputs",
                "source": "validator",
                "suggestions": ["Add '- cache: false' if this node reads runtime state."],
                "node_id": "run-shell",
            }
        ]


class TestPricingUnavailableWarning:
    """Tests for cost display when model pricing is unavailable."""

    def _make_result_dict(
        self,
        pricing_available: bool = True,
        unavailable_models: list[str] | None = None,
        partial_cost_usd: float | None = None,
        total_cost_usd: float | None = None,
    ) -> dict:
        metrics: dict = {
            "workflow": {"duration_ms": 100, "nodes_executed": 1, "total_tokens": 10},
            "total": {"tokens_input": 5, "tokens_output": 5, "tokens_total": 10, "cost_usd": total_cost_usd},
        }
        if not pricing_available:
            metrics["total"]["pricing_available"] = False
            metrics["total"]["unavailable_models"] = unavailable_models or []
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
        result_dict = self._make_result_dict(pricing_available=False, unavailable_models=["my-custom-model"])
        text = format_success_as_text(result_dict)

        assert "Cost unavailable" in text
        assert "my-custom-model" in text

    def test_partial_cost_shows_partial_amount(self):
        """When some models have pricing, show partial cost with disclaimer."""
        result_dict = self._make_result_dict(
            pricing_available=False,
            unavailable_models=["unknown-model"],
            partial_cost_usd=0.03,
        )
        text = format_success_as_text(result_dict)

        assert "$0.0300+" in text
        assert "partial" in text
        assert "unknown-model" in text

    def test_known_model_shows_normal_cost(self):
        """When pricing is available, show normal cost line."""
        result_dict = self._make_result_dict(total_cost_usd=0.05)
        text = format_success_as_text(result_dict)

        assert "$0.0500" in text
        assert "Cost unavailable" not in text


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

    def test_only_node_zero_skipped_no_summary_line(self):
        """CORRECTNESS: No summary line when --only is set but all nodes executed.

        Real bug this catches: Showing "0 remaining nodes skipped" is confusing
        and adds noise when the target was the last node.
        """
        steps = [
            {"node_id": "fetch", "status": "completed", "duration_ms": 50},
            {"node_id": "process", "status": "completed", "duration_ms": 100},
        ]
        result_dict = self._make_result_dict(steps, only_node="process", nodes_skipped=0)
        text = format_success_as_text(result_dict)

        assert "⤷" not in text


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
