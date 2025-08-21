"""Tests for error classification and user-friendly messaging system."""

import pytest

from pflow.planning.error_handler import (
    ErrorCategory,
    PlannerError,
    classify_error,
    create_fallback_response,
)


class TestErrorClassification:
    """Tests for error classification logic."""

    def test_classify_authentication_errors(self):
        """Test classification of authentication-related errors."""
        test_cases = [
            ValueError("Invalid API key"),
            Exception("401 Unauthorized"),
            RuntimeError("Authentication failed"),
            ValueError("api_key not found"),
        ]

        for exc in test_cases:
            error = classify_error(exc)
            assert error.category == ErrorCategory.AUTHENTICATION
            assert "API key" in error.user_action
            assert not error.retry_suggestion

    def test_classify_rate_limit_errors(self):
        """Test classification of rate limit errors."""
        test_cases = [
            ValueError("Rate limit exceeded"),
            Exception("429 Too Many Requests"),
            RuntimeError("Quota exceeded for the month"),
        ]

        for exc in test_cases:
            error = classify_error(exc)
            assert error.category == ErrorCategory.QUOTA_LIMIT
            assert "wait" in error.user_action.lower() or "retry" in error.user_action.lower()
            assert error.retry_suggestion

    def test_classify_network_errors(self):
        """Test classification of network/timeout errors."""
        test_cases = [
            TimeoutError("Request timed out"),
            ConnectionError("Connection refused"),
            Exception("Network unreachable"),
            RuntimeError("DNS resolution failed"),
        ]

        for exc in test_cases:
            error = classify_error(exc)
            assert error.category == ErrorCategory.NETWORK
            assert "connection" in error.user_action.lower()
            assert error.retry_suggestion

    def test_classify_service_errors(self):
        """Test classification of service unavailability."""
        test_cases = [
            Exception("503 Service Unavailable"),
            RuntimeError("Service is under maintenance"),
        ]

        for exc in test_cases:
            error = classify_error(exc)
            assert error.category == ErrorCategory.SERVICE_UNAVAILABLE
            assert error.retry_suggestion

    def test_classify_api_overload_errors(self):
        """Test classification of API overload errors."""
        test_cases = [
            Exception("API is overloaded"),
            RuntimeError("Service overloaded, try again later"),
            ValueError("overloaded_error from API"),
        ]

        for exc in test_cases:
            error = classify_error(exc)
            assert error.category == ErrorCategory.SERVICE_UNAVAILABLE
            assert "overload" in error.message.lower()
            assert "wait" in error.user_action.lower()
            assert error.retry_suggestion

    def test_classify_unknown_errors(self):
        """Test fallback to unknown category."""
        exc = Exception("Some weird error")
        error = classify_error(exc)
        assert error.category == ErrorCategory.UNKNOWN
        assert "report" in error.user_action.lower()

    def test_error_format_for_cli_basic(self):
        """Test CLI formatting in non-verbose mode."""
        error = PlannerError(
            category=ErrorCategory.AUTHENTICATION,
            message="API key is invalid",
            user_action="Configure your API key with: llm keys set anthropic",
            technical_details="401 response from API",
            retry_suggestion=False,
        )

        output = error.format_for_cli(verbose=False)
        assert "❌" in output
        assert "API key is invalid" in output
        assert "👉" in output
        assert "Configure your API key" in output
        assert "401 response" not in output  # Technical details hidden

    def test_error_format_for_cli_verbose(self):
        """Test CLI formatting in verbose mode."""
        error = PlannerError(
            category=ErrorCategory.NETWORK,
            message="Connection timeout",
            user_action="Check your internet connection",
            technical_details="Socket timeout after 30s",
            retry_suggestion=True,
        )

        output = error.format_for_cli(verbose=True)
        assert "🔄" in output  # Retry suggestion
        assert "🔍" in output  # Technical details
        assert "Socket timeout after 30s" in output

    def test_create_fallback_response_discovery_node(self):
        """Test fallback response creation for WorkflowDiscoveryNode."""
        exc = ValueError("API key invalid")
        prep_res = {"user_input": "test request"}

        safe_response, planner_error = create_fallback_response("WorkflowDiscoveryNode", exc, prep_res)

        # Check safe response structure
        assert safe_response["found"] is False
        assert safe_response["workflow_name"] is None
        assert safe_response["confidence"] == 0.0
        assert "_error" in safe_response

        # Check planner error
        assert planner_error.category == ErrorCategory.AUTHENTICATION
        assert not planner_error.retry_suggestion

    def test_create_fallback_response_generator_node(self):
        """Test fallback response creation for WorkflowGeneratorNode."""
        exc = TimeoutError("Request timed out")
        prep_res = {"user_input": "generate a workflow"}

        safe_response, planner_error = create_fallback_response("WorkflowGeneratorNode", exc, prep_res)

        # Check safe response structure
        assert safe_response["ir_version"] == "0.1.0"
        assert safe_response["nodes"] == []
        assert "_error" in safe_response

        # Check planner error
        assert planner_error.category == ErrorCategory.NETWORK
        assert planner_error.retry_suggestion

    def test_create_fallback_response_parameter_mapping(self):
        """Test fallback response for ParameterMappingNode with defaults."""
        exc = Exception("LLM failed")
        prep_res = {
            "user_input": "test",
            "workflow_ir": {
                "inputs": {
                    "file_path": {"type": "string", "required": True},
                    "encoding": {"type": "string", "default": "utf-8"},
                }
            },
        }

        safe_response, planner_error = create_fallback_response("ParameterMappingNode", exc, prep_res)

        # Should apply defaults where available
        assert safe_response["extracted"]["encoding"] == "utf-8"
        assert "file_path" in safe_response["missing"]
        assert safe_response["confidence"] == 0.0

    def test_error_to_dict(self):
        """Test converting PlannerError to dictionary."""
        error = PlannerError(
            category=ErrorCategory.QUOTA_LIMIT,
            message="Rate limit exceeded",
            user_action="Wait and retry",
            technical_details="429 from API",
            retry_suggestion=True,
        )

        error_dict = error.to_dict()
        assert error_dict["category"] == "quota_limit"
        assert error_dict["message"] == "Rate limit exceeded"
        assert error_dict["retry_suggestion"] is True


class TestErrorIntegration:
    """Integration tests for error handling in the planning system."""

    def test_error_propagation_through_nodes(self):
        """Test that errors are properly classified and raised by critical nodes."""
        from pflow.core.exceptions import CriticalPlanningError
        from pflow.planning.nodes import WorkflowDiscoveryNode

        node = WorkflowDiscoveryNode()
        node.wait = 0

        prep_res = {"user_input": "test", "discovery_context": "context"}
        exc = ValueError("API key not configured")

        # Critical nodes now raise CriticalPlanningError with classified error info
        with pytest.raises(CriticalPlanningError) as exc_info:
            node.exec_fallback(prep_res, exc)

        # The error classification should be embedded in the reason
        assert exc_info.value.node_name == "WorkflowDiscoveryNode"
        assert "API key" in exc_info.value.reason  # Classified error message
        assert exc_info.value.original_error == exc
