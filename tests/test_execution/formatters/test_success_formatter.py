"""Tests for success formatter - guardrails for execution success display.

These tests catch real bugs that could break execution output for agents and CLI.
Each test documents what bug it prevents.
"""

from pflow.execution.formatters.success_formatter import (
    _append_execution_steps,
    _find_auto_output,
    _format_batch_errors_section,
    _format_batch_node_line,
    _format_execution_step,
    _truncate_error_message,
    format_success_as_text,
)


class TestBatchNodeLineFormatting:
    """Tests for batch node status line formatting."""

    def test_batch_full_success_shows_checkmark(self):
        """CORRECTNESS: Batch with all items successful shows checkmark.

        Real bug this catches: Without visual distinction, users can't quickly
        identify batch node success status.
        """
        step = {
            "node_id": "process",
            "status": "completed",
            "duration_ms": 31,
            "is_batch": True,
            "batch_total": 10,
            "batch_success": 10,
            "batch_errors": 0,
        }
        result = _format_batch_node_line(step)

        assert "✓ process" in result
        assert "10/10 items succeeded" in result
        assert "failed" not in result

    def test_batch_partial_success_shows_warning(self):
        """CORRECTNESS: Batch with some failures shows warning indicator.

        Real bug this catches: Showing green checkmark for partial failures
        would give false confidence about execution success.
        """
        step = {
            "node_id": "process",
            "status": "completed",
            "duration_ms": 31,
            "is_batch": True,
            "batch_total": 10,
            "batch_success": 8,
            "batch_errors": 2,
        }
        result = _format_batch_node_line(step)

        assert "⚠ process" in result
        assert "8/10 items succeeded" in result
        assert "2 failed" in result

    def test_batch_line_includes_timing(self):
        """FORMAT: Batch node line must include execution time.

        Real bug this catches: Missing timing info makes performance debugging
        impossible.
        """
        step = {
            "node_id": "process",
            "duration_ms": 150,
            "is_batch": True,
            "batch_total": 5,
            "batch_success": 5,
            "batch_errors": 0,
        }
        result = _format_batch_node_line(step)

        assert "(150ms)" in result

    def test_batch_line_includes_cached_tag(self):
        """FORMAT: Cached batch nodes must show cached tag.

        Real bug this catches: Without cached indicator, users can't identify
        which batch nodes used cached results.
        """
        step = {
            "node_id": "process",
            "duration_ms": 0,
            "is_batch": True,
            "batch_total": 5,
            "batch_success": 5,
            "batch_errors": 0,
            "cached": True,
        }
        result = _format_batch_node_line(step)

        assert "[cached]" in result


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


class TestExecutionStepFormatting:
    """Tests for execution step formatting dispatch."""

    def test_batch_node_uses_batch_formatting(self):
        """CORRECTNESS: Batch nodes use enhanced formatting with summary.

        Real bug this catches: Batch nodes showing generic format would miss
        the item success/failure counts.
        """
        step = {
            "node_id": "process",
            "status": "completed",
            "duration_ms": 100,
            "is_batch": True,
            "batch_total": 5,
            "batch_success": 5,
            "batch_errors": 0,
        }
        result = _format_execution_step(step)

        assert "5/5 items succeeded" in result

    def test_regular_node_uses_standard_formatting(self):
        """CORRECTNESS: Regular nodes use standard status line format.

        Real bug this catches: Regular nodes showing batch format would be
        confusing and incorrect.
        """
        step = {
            "node_id": "fetch",
            "status": "completed",
            "duration_ms": 100,
        }
        result = _format_execution_step(step)

        assert "✓ fetch" in result
        assert "(100ms)" in result
        assert "items succeeded" not in result  # No batch summary


class TestFormatSuccessAsText:
    """Tests for full text output formatting."""

    def test_batch_node_in_full_output(self):
        """INTEGRATION: Batch node formatting appears in full text output.

        Real bug this catches: Batch formatting might work in isolation but not
        be integrated correctly into format_success_as_text().
        """
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

        # Header present
        assert "Workflow completed" in text
        # Regular node present
        assert "✓ source" in text
        # Batch node with partial success
        assert "⚠ process" in text
        assert "8/10 items succeeded" in text
        # Error section present
        assert "Batch 'process' errors:" in text
        assert "[1] Error 1" in text
        assert "[4] Error 2" in text

    def test_batch_full_success_in_full_output(self):
        """INTEGRATION: Fully successful batch shows checkmark.

        Real bug this catches: Batch with 0 errors might incorrectly show
        warning indicator.
        """
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

        assert "✓ process" in text
        assert "5/5 items succeeded" in text
        assert "Batch 'process' errors:" not in text  # No error section

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

        # Both batch nodes shown
        assert "⚠ batch1" in text
        assert "⚠ batch2" in text
        # Both error sections present
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

        text = format_success_as_text(result_dict)

        assert "⚠️ Warnings:" in text
        assert "send-alert (api_warning):" in text
        assert "API error: Rate limit exceeded" in text
        assert "Retry after 30s" in text


class TestNonBatchNodesUnchanged:
    """Tests ensuring non-batch node formatting is unchanged."""

    def test_regular_completed_node_unchanged(self):
        """REGRESSION: Regular completed nodes use standard format.

        Real bug this catches: Adding batch support could accidentally break
        regular node formatting.
        """
        step = {
            "node_id": "fetch",
            "status": "completed",
            "duration_ms": 100,
        }
        result = _format_execution_step(step)

        assert result == "  ✓ fetch (100ms)"

    def test_regular_failed_node_unchanged(self):
        """REGRESSION: Regular failed nodes use standard format.

        Real bug this catches: Failed node formatting could be broken.
        """
        step = {
            "node_id": "send",
            "status": "failed",
            "duration_ms": 50,
        }
        result = _format_execution_step(step)

        assert result == "  ❌ send (50ms)"

    def test_cached_node_unchanged(self):
        """REGRESSION: Cached nodes show cached tag.

        Real bug this catches: Cached tag formatting could be broken.
        """
        step = {
            "node_id": "fetch",
            "status": "completed",
            "duration_ms": 0,
            "cached": True,
        }
        result = _format_execution_step(step)

        assert result == "  ✓ fetch (0ms) [cached]"


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
        """CORRECTNESS: --only filters out not_executed steps and shows summary.

        Real bug this catches: Showing not_executed nodes clutters the output and
        confuses agents about what actually ran.
        """
        steps = [
            {"node_id": "fetch", "status": "completed", "duration_ms": 50},
            {"node_id": "process", "status": "completed", "duration_ms": 100},
            {"node_id": "save", "status": "not_executed", "duration_ms": 0},
            {"node_id": "notify", "status": "not_executed", "duration_ms": 0},
        ]
        result_dict = self._make_result_dict(steps, only_node="process", nodes_skipped=2)
        text = format_success_as_text(result_dict)

        # Completed steps shown
        assert "✓ fetch" in text
        assert "✓ process" in text
        # Not_executed steps NOT shown
        assert "save" not in text
        assert "notify" not in text
        # Summary line present
        assert "⤷ Stopped after 'process' (--only), 2 remaining nodes skipped" in text
        # Header shows executed/total format
        assert "Nodes executed (2/4):" in text

    def test_only_node_not_set_shows_all_steps(self):
        """CORRECTNESS: Without --only, all steps including not_executed are shown.

        Real bug this catches: Accidentally filtering steps when --only is not set
        would hide execution details from users.
        """
        steps = [
            {"node_id": "fetch", "status": "completed", "duration_ms": 50},
            {"node_id": "broken", "status": "not_executed", "duration_ms": 0},
        ]
        result_dict = self._make_result_dict(steps)
        text = format_success_as_text(result_dict)

        # All steps shown
        assert "fetch" in text
        assert "broken" in text
        # No summary line
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
    """Tests for _append_execution_steps with --only filtering."""

    def test_filters_not_executed_steps(self):
        """CORRECTNESS: _append_execution_steps omits not_executed steps when only_node set.

        Real bug this catches: Display layer showing not_executed nodes alongside
        executed ones makes it unclear which nodes actually ran.
        """
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
        assert "fetch" in joined
        assert "process" in joined
        assert "save" not in joined

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

    def test_no_filtering_without_only(self):
        """REGRESSION: Without only_node, not_executed steps are still shown.

        Real bug this catches: Filtering logic accidentally activating without
        --only would hide legitimately skipped nodes (e.g., branch not taken).
        """
        execution = {
            "nodes_executed": 1,
            "steps": [
                {"node_id": "fetch", "status": "completed", "duration_ms": 50},
                {"node_id": "skipped", "status": "not_executed", "duration_ms": 0},
            ],
        }
        lines: list[str] = []
        _append_execution_steps(lines, execution)

        joined = "\n".join(lines)
        assert "fetch" in joined
        assert "skipped" in joined


class TestFindAutoOutputNamespaceAware:
    """Tests for namespace-aware JSON auto-detection.

    _find_auto_output serves ALL JSON/MCP output. A regression here silently
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
        key, value = _find_auto_output(shared)

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
        key, value = _find_auto_output(shared)

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
        key, value = _find_auto_output(shared)

        assert key == "result"
        assert value == "clean declared output"
