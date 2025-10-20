"""Tests for error formatter - focus on catching real bugs, not implementation details.

These tests are guardrails for AI-driven development. Each test catches a specific
bug that could break production:

1. Sanitization bypass (security bug)
2. Original data mutation (data corruption bug)
3. Missing execution state (incorrect agent feedback)
4. Edge case crashes (production failures)

If a test passes but the feature is broken, the test failed its purpose.
"""

from pflow.execution.executor_service import ExecutionResult
from pflow.execution.formatters.error_formatter import format_execution_errors


class TestSecurityGuardrails:
    """Tests that catch security vulnerabilities."""

    def test_api_keys_must_be_redacted_in_errors(self):
        """SECURITY: Prevent API key leaks in error responses.

        Real bug this catches: If sanitization is accidentally removed or bypassed,
        API keys would be exposed to users/agents in error messages.
        """
        result = ExecutionResult(
            success=False,
            errors=[
                {
                    "message": "API validation failed",
                    "raw_response": {
                        "api_key": "sk-secret123456",  # Must be redacted
                        "error": "Invalid request",
                        "apikey": "another-secret",  # Must be redacted
                    },
                }
            ],
            shared_after={},
        )

        formatted = format_execution_errors(result, sanitize=True)

        # SECURITY REQUIREMENT: Sensitive keys must be redacted
        assert formatted["errors"][0]["raw_response"]["api_key"] == "<REDACTED>"
        assert formatted["errors"][0]["raw_response"]["apikey"] == "<REDACTED>"
        assert formatted["errors"][0]["raw_response"]["error"] == "Invalid request"

    def test_auth_tokens_must_be_redacted_in_headers(self):
        """SECURITY: Prevent auth token leaks in response headers.

        Real bug this catches: Authorization headers containing tokens must be
        sanitized to prevent credential theft.
        """
        result = ExecutionResult(
            success=False,
            errors=[
                {
                    "message": "HTTP error",
                    "response_headers": {
                        "Authorization": "Bearer secret-token-12345",
                        "Content-Type": "application/json",
                        "X-Api-Key": "admin-key-secret",
                    },
                }
            ],
            shared_after={},
        )

        formatted = format_execution_errors(result, sanitize=True)

        # SECURITY REQUIREMENT: Auth tokens must be redacted
        headers = formatted["errors"][0]["response_headers"]
        assert headers["Authorization"] == "<REDACTED>"
        assert headers["X-Api-Key"] == "<REDACTED>"
        assert headers["Content-Type"] == "application/json"  # Non-sensitive preserved

    def test_nested_secrets_must_be_sanitized_recursively(self):
        """SECURITY: Nested dicts containing secrets must be fully sanitized.

        Real bug this catches: If sanitization isn't recursive, secrets buried
        in nested structures would leak.
        """
        result = ExecutionResult(
            success=False,
            errors=[
                {
                    "message": "Complex API error",
                    "raw_response": {
                        "error": {
                            "details": {
                                "password": "user-password-123",  # Nested secret
                                "message": "Authentication failed",
                            }
                        }
                    },
                }
            ],
            shared_after={},
        )

        formatted = format_execution_errors(result, sanitize=True)

        # SECURITY REQUIREMENT: Nested secrets must be redacted
        nested = formatted["errors"][0]["raw_response"]["error"]["details"]
        assert nested["password"] == "<REDACTED>"  # noqa: S105 - Testing sanitization output, not hardcoded password
        assert nested["message"] == "Authentication failed"


class TestDataIntegrityGuardrails:
    """Tests that catch data corruption bugs."""

    def test_original_errors_must_never_be_modified(self):
        """DATA INTEGRITY: Formatter must not mutate original error data.

        Real bug this catches: If formatter modifies original errors instead of
        copies, it would corrupt ExecutionResult data used elsewhere in the system.
        """
        original_errors = [{"message": "Test error", "raw_response": {"api_key": "secret", "data": "value"}}]
        result = ExecutionResult(success=False, errors=original_errors, shared_after={})

        # Run formatter
        format_execution_errors(result, sanitize=True)

        # INTEGRITY REQUIREMENT: Original data unchanged
        assert original_errors[0]["raw_response"]["api_key"] == "secret"
        assert original_errors[0]["raw_response"]["data"] == "value"

    def test_multiple_errors_must_all_be_processed(self):
        """DATA INTEGRITY: All errors must be formatted, not just the first.

        Real bug this catches: If logic only processes first error, agents would
        miss critical information about multiple failures.
        """
        result = ExecutionResult(
            success=False,
            errors=[
                {"message": "Error 1", "node_id": "node1", "raw_response": {"secret": "s1"}},
                {"message": "Error 2", "node_id": "node2", "raw_response": {"secret": "s2"}},
                {"message": "Error 3", "node_id": "node3", "raw_response": {"secret": "s3"}},
            ],
            shared_after={},
        )

        formatted = format_execution_errors(result, sanitize=True)

        # INTEGRITY REQUIREMENT: All errors present and sanitized
        assert len(formatted["errors"]) == 3
        assert formatted["errors"][0]["message"] == "Error 1"
        assert formatted["errors"][1]["message"] == "Error 2"
        assert formatted["errors"][2]["message"] == "Error 3"
        # All must be sanitized
        for error in formatted["errors"]:
            assert error["raw_response"]["secret"] == "<REDACTED>"  # noqa: S105 - Testing sanitization output, not hardcoded password


class TestExecutionStateGuardrails:
    """Tests that catch execution state tracking bugs."""

    def test_completed_nodes_must_show_correct_status(self):
        """CORRECTNESS: Execution state must accurately reflect node completion.

        Real bug this catches: If status logic is broken, agents would get wrong
        information about which nodes succeeded/failed.
        """
        ir_data = {"nodes": [{"id": "fetch"}, {"id": "process"}, {"id": "send"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["fetch", "process"], "failed_node": "send"},
            "__cache_hits__": [],
            "__modified_nodes__": [],
        }
        result = ExecutionResult(success=False, errors=[{"message": "Send failed"}], shared_after=shared_storage)

        formatted = format_execution_errors(result, shared_storage, ir_data)

        # CORRECTNESS REQUIREMENT: Status must match reality
        steps = formatted["execution"]["steps"]
        assert steps[0]["status"] == "completed"  # fetch completed
        assert steps[1]["status"] == "completed"  # process completed
        assert steps[2]["status"] == "failed"  # send failed

    def test_cache_hits_must_be_tracked_correctly(self):
        """CORRECTNESS: Cache tracking must accurately reflect which nodes used cache.

        Real bug this catches: If cache tracking breaks, agents can't optimize
        workflow performance or understand execution behavior.
        """
        ir_data = {"nodes": [{"id": "node1"}, {"id": "node2"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["node1", "node2"]},
            "__cache_hits__": ["node1"],  # Only node1 used cache
            "__modified_nodes__": [],
        }
        result = ExecutionResult(success=False, errors=[{"message": "Later error"}], shared_after=shared_storage)

        formatted = format_execution_errors(result, shared_storage, ir_data)

        # CORRECTNESS REQUIREMENT: Cache hits accurately reported
        steps = formatted["execution"]["steps"]
        assert steps[0]["cached"] is True  # node1 used cache
        assert steps[1]["cached"] is False  # node2 did not

    def test_repaired_nodes_must_be_marked(self):
        """CORRECTNESS: Repaired nodes must be identified for transparency.

        Real bug this catches: If repair tracking breaks, agents can't understand
        which parts of workflow were auto-fixed vs. original.
        """
        ir_data = {"nodes": [{"id": "broken"}, {"id": "working"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["broken", "working"]},
            "__cache_hits__": [],
            "__modified_nodes__": ["broken"],  # This node was repaired
        }
        result = ExecutionResult(success=False, errors=[{"message": "Final error"}], shared_after=shared_storage)

        formatted = format_execution_errors(result, shared_storage, ir_data)

        # CORRECTNESS REQUIREMENT: Repair status visible
        steps = formatted["execution"]["steps"]
        assert steps[0].get("repaired") is True  # broken was repaired
        assert "repaired" not in steps[1]  # working was not


class TestRobustnessGuardrails:
    """Tests that catch edge case crashes and robustness bugs."""

    def test_must_handle_empty_errors_gracefully(self):
        """ROBUSTNESS: Empty error list must not crash formatter.

        Real bug this catches: If formatter assumes non-empty errors, it would
        crash on edge cases where ExecutionResult has no errors.
        """
        result = ExecutionResult(
            success=False,
            errors=[],  # Empty errors list
            shared_after={},
        )

        formatted = format_execution_errors(result, sanitize=True)

        # ROBUSTNESS REQUIREMENT: Must not crash
        assert formatted["errors"] == []
        assert formatted["checkpoint"] == {}

    def test_must_handle_missing_optional_fields(self):
        """ROBUSTNESS: Missing optional fields must not crash formatter.

        Real bug this catches: If formatter assumes fields exist, it would crash
        when errors lack optional fields like raw_response or response_headers.
        """
        result = ExecutionResult(
            success=False,
            errors=[
                {"message": "Simple error"}  # No raw_response, no headers
            ],
            shared_after={},
        )

        formatted = format_execution_errors(result, sanitize=True)

        # ROBUSTNESS REQUIREMENT: Must not crash on missing fields
        assert formatted["errors"][0]["message"] == "Simple error"
        assert "raw_response" not in formatted["errors"][0]

    def test_must_handle_none_metrics_gracefully(self):
        """ROBUSTNESS: None metrics_collector must not crash formatter.

        Real bug this catches: If formatter doesn't handle None collector, it
        would crash when MCP or CLI don't provide metrics.
        """
        ir_data = {"nodes": [{"id": "test"}]}
        shared_storage = {
            "__execution__": {"completed_nodes": ["test"]},
            "__cache_hits__": [],
            "__modified_nodes__": [],
        }
        result = ExecutionResult(success=False, errors=[{"message": "Error"}], shared_after=shared_storage)

        formatted = format_execution_errors(
            result,
            shared_storage,
            ir_data,
            metrics_collector=None,  # No metrics provided
        )

        # ROBUSTNESS REQUIREMENT: Must not crash on None metrics
        # After Nonems fix (Task 85), duration defaults to 0 instead of None
        assert "execution" in formatted
        assert formatted["execution"]["steps"][0]["duration_ms"] == 0

    def test_must_handle_missing_execution_checkpoint(self):
        """ROBUSTNESS: Missing __execution__ key must not crash formatter.

        Real bug this catches: If shared storage lacks execution checkpoint,
        formatter would crash instead of returning empty checkpoint.
        """
        result = ExecutionResult(
            success=False,
            errors=[{"message": "Error"}],
            shared_after={},  # No __execution__ key
        )

        formatted = format_execution_errors(result, sanitize=True)

        # ROBUSTNESS REQUIREMENT: Must not crash on missing checkpoint
        assert formatted["checkpoint"] == {}


class TestBehaviorContracts:
    """Tests that validate the formatter's behavioral contracts."""

    def test_sanitization_can_be_disabled(self):
        """CONTRACT: sanitize=False must preserve sensitive data.

        Real bug this catches: If sanitize flag is ignored, CLI text mode
        (which needs raw data for formatting) would get redacted data.
        """
        result = ExecutionResult(
            success=False, errors=[{"message": "Error", "raw_response": {"api_key": "secret"}}], shared_after={}
        )

        formatted = format_execution_errors(result, sanitize=False)

        # CONTRACT: sanitize=False preserves original data
        assert formatted["errors"][0]["raw_response"]["api_key"] == "secret"

    def test_checkpoint_always_extracted_from_shared_after(self):
        """CONTRACT: Checkpoint must come from shared_after.__execution__.

        Real bug this catches: If checkpoint source changes, resume functionality
        would break as it depends on this exact structure.
        """
        checkpoint_data = {"completed_nodes": ["node1"], "node_actions": {"node1": "default"}, "failed_node": "node2"}
        result = ExecutionResult(
            success=False, errors=[{"message": "Error"}], shared_after={"__execution__": checkpoint_data}
        )

        formatted = format_execution_errors(result)

        # CONTRACT: Checkpoint exactly matches shared_after structure
        assert formatted["checkpoint"] == checkpoint_data

    def test_execution_state_only_included_when_data_available(self):
        """CONTRACT: execution field only present if both ir_data and shared_storage provided.

        Real bug this catches: If execution state is always returned even without
        data, consumers would get incorrect empty structures.
        """
        result = ExecutionResult(success=False, errors=[{"message": "Error"}], shared_after={})

        # Without ir_data
        formatted1 = format_execution_errors(result, shared_storage={})
        assert "execution" not in formatted1

        # Without shared_storage
        formatted2 = format_execution_errors(result, ir_data={"nodes": []})
        assert "execution" not in formatted2

        # With both but empty nodes
        formatted3 = format_execution_errors(result, {}, {"nodes": []})
        assert "execution" not in formatted3  # No steps means no execution state


# Performance guardrails
def test_formatter_runs_in_under_10ms():
    """PERFORMANCE: Formatter must be fast enough for interactive use.

    Real bug this catches: If formatter becomes slow (e.g., due to expensive
    operations), it would make CLI and MCP responses sluggish.

    Note: This is not a strict requirement but a warning if performance degrades.
    """
    import time

    result = ExecutionResult(success=False, errors=[{"message": f"Error {i}"} for i in range(10)], shared_after={})

    start = time.perf_counter()
    for _ in range(100):  # 100 iterations
        format_execution_errors(result, sanitize=True)
    elapsed = time.perf_counter() - start

    # 100 iterations should complete in < 1 second (10ms avg per call)
    assert elapsed < 1.0, f"Formatter too slow: {elapsed * 10:.1f}ms per call"
