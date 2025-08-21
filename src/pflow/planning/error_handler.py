"""Error classification and user-friendly messaging for planning failures.

This module provides intelligent error classification to transform raw exceptions
into actionable user guidance. It distinguishes between user errors (fixable by
the user) and system errors (requiring support/retry).
"""

import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors for appropriate user messaging."""

    # User-fixable errors
    AUTHENTICATION = "authentication"  # API key issues
    QUOTA_LIMIT = "quota_limit"  # Rate limits, quota exceeded
    INVALID_INPUT = "invalid_input"  # Malformed requests, bad parameters
    MISSING_RESOURCE = "missing_resource"  # Workflow/node not found

    # System errors (retry may help)
    NETWORK = "network"  # Connection, timeout issues
    SERVICE_UNAVAILABLE = "service_unavailable"  # API down, 503 errors
    INTERNAL_ERROR = "internal_error"  # 500 errors, unexpected failures

    # Unknown errors
    UNKNOWN = "unknown"  # Catch-all for unclassified errors


class PlannerError:
    """Structured error information for planning failures."""

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        user_action: str,
        technical_details: Optional[str] = None,
        retry_suggestion: bool = False,
    ):
        """Initialize a planner error.

        Args:
            category: The error category for routing/handling
            message: User-friendly error description
            user_action: Actionable steps the user can take
            technical_details: Optional technical info for debugging
            retry_suggestion: Whether retrying might help
        """
        self.category = category
        self.message = message
        self.user_action = user_action
        self.technical_details = technical_details
        self.retry_suggestion = retry_suggestion

    def format_for_cli(self, verbose: bool = False) -> str:
        """Format error for CLI display.

        Args:
            verbose: Include technical details if True

        Returns:
            Formatted error string for CLI output
        """
        lines = [
            f"❌ Planning failed: {self.message}",
            f"👉 {self.user_action}",
        ]

        if self.retry_suggestion:
            lines.append("🔄 This is likely temporary - please retry in a moment")

        if verbose and self.technical_details:
            lines.append(f"🔍 Technical details: {self.technical_details}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/transmission."""
        return {
            "category": self.category.value,
            "message": self.message,
            "user_action": self.user_action,
            "technical_details": self.technical_details,
            "retry_suggestion": self.retry_suggestion,
        }


def classify_error(exc: Exception, context: Optional[str] = None) -> PlannerError:
    """Classify an exception into a structured PlannerError.

    This function analyzes exception messages and types to determine the
    appropriate error category and generate helpful user guidance.

    Args:
        exc: The exception to classify
        context: Optional context about where the error occurred

    Returns:
        PlannerError with appropriate classification and messaging
    """
    error_str = str(exc).lower()
    exc_type = type(exc).__name__

    # Log the classification attempt
    logger.debug(f"Classifying error: {exc_type}: {error_str[:200]}", extra={"context": context})

    # Authentication errors
    if any(
        term in error_str for term in ["api key", "api_key", "unauthorized", "401", "authentication", "invalid key"]
    ):
        return PlannerError(
            category=ErrorCategory.AUTHENTICATION,
            message="LLM API authentication failed",
            user_action="Configure your API key:\n  1. Run: llm keys set anthropic\n  2. Enter your key from https://console.anthropic.com/",
            technical_details=str(exc),
            retry_suggestion=False,
        )

    # Rate limit errors
    if any(term in error_str for term in ["rate limit", "429", "quota", "too many requests", "exceeded"]):
        return PlannerError(
            category=ErrorCategory.QUOTA_LIMIT,
            message="API rate limit or quota exceeded",
            user_action="Wait a few minutes before retrying, or check your API plan limits",
            technical_details=str(exc),
            retry_suggestion=True,
        )

    # Network/timeout errors
    if any(
        term in error_str for term in ["timeout", "timed out", "connection", "network", "unreachable", "dns", "socket"]
    ):
        return PlannerError(
            category=ErrorCategory.NETWORK,
            message="Network connection issue",
            user_action="Check your internet connection and try again",
            technical_details=str(exc),
            retry_suggestion=True,
        )

    # API Overload (specific case of service unavailable)
    if any(term in error_str for term in ["overloaded", "overload"]):
        return PlannerError(
            category=ErrorCategory.SERVICE_UNAVAILABLE,
            message="AI service is currently overloaded",
            user_action="Wait a few moments and try again. Service overload usually resolves quickly",
            technical_details=str(exc),
            retry_suggestion=True,
        )

    # Service unavailable (general)
    if any(term in error_str for term in ["503", "service unavailable", "maintenance", "downtime"]):
        return PlannerError(
            category=ErrorCategory.SERVICE_UNAVAILABLE,
            message="LLM service is temporarily unavailable",
            user_action="The service appears to be down. Please try again later",
            technical_details=str(exc),
            retry_suggestion=True,
        )

    # Internal/server errors
    if any(term in error_str for term in ["500", "internal server", "server error"]):
        return PlannerError(
            category=ErrorCategory.INTERNAL_ERROR,
            message="LLM service encountered an internal error",
            user_action="This is a temporary issue with the service. Please retry",
            technical_details=str(exc),
            retry_suggestion=True,
        )

    # Invalid input/request errors
    if any(term in error_str for term in ["invalid", "malformed", "bad request", "400", "validation"]):
        return PlannerError(
            category=ErrorCategory.INVALID_INPUT,
            message="Invalid request format or parameters",
            user_action="Try rephrasing your request or simplifying it",
            technical_details=str(exc),
            retry_suggestion=False,
        )

    # Resource not found
    if any(term in error_str for term in ["not found", "404", "missing", "does not exist"]):
        return PlannerError(
            category=ErrorCategory.MISSING_RESOURCE,
            message="Required resource not found",
            user_action="Check that all referenced workflows and nodes exist",
            technical_details=str(exc),
            retry_suggestion=False,
        )

    # LLM response parsing errors (from parse_structured_response)
    if "response parsing failed" in error_str or "no 'content' field" in error_str:
        return PlannerError(
            category=ErrorCategory.INTERNAL_ERROR,
            message="Failed to parse LLM response - unexpected format",
            user_action="This may be a temporary API issue. Please retry",
            technical_details=str(exc),
            retry_suggestion=True,
        )

    # Default unknown error
    return PlannerError(
        category=ErrorCategory.UNKNOWN,
        message=f"Unexpected error in {context or 'planning'}" if context else "Unexpected planning error",
        user_action="Please report this issue if it persists:\n  Include the error details and your command",
        technical_details=str(exc),
        retry_suggestion=True,
    )


def create_fallback_response(
    node_name: str, exc: Exception, prep_res: dict[str, Any]
) -> tuple[dict[str, Any], PlannerError]:
    """Create appropriate fallback response for a planning node failure.

    This generates both the safe default response needed by the node and
    a classified error for user messaging.

    Args:
        node_name: Name of the node that failed (for context)
        exc: The exception that occurred
        prep_res: The prep_res dict from the node (for context)

    Returns:
        Tuple of (safe_default_response, planner_error)
    """
    # Classify the error
    planner_error = classify_error(exc, context=node_name)

    # Log the classified error (debug level - not shown to users by default)
    logger.debug(
        f"{node_name}: Error classified as {planner_error.category.value}, will retry",
        extra={
            "node": node_name,
            "category": planner_error.category.value,
            "retry_suggestion": planner_error.retry_suggestion,
            "user_input": prep_res.get("user_input", "")[:100] if "user_input" in prep_res else None,
        },
    )

    # Generate node-specific safe defaults based on node type
    # NOTE: Order matters - more specific conditions first!
    if "Parameter" in node_name and "Discovery" in node_name:
        safe_response = {
            "parameters": {},
            "stdin_type": prep_res.get("stdin_info", {}).get("type") if prep_res.get("stdin_info") else None,
            "reasoning": planner_error.message,
            "_error": planner_error.to_dict(),
        }
    elif "Discovery" in node_name:  # WorkflowDiscoveryNode (but not ParameterDiscoveryNode)
        safe_response = {
            "found": False,
            "workflow_name": None,
            "confidence": 0.0,
            "reasoning": planner_error.message,
            "_error": planner_error.to_dict(),
        }
    elif "Browsing" in node_name:  # ComponentBrowsingNode
        safe_response = {
            "node_ids": [],
            "workflow_names": [],
            "reasoning": planner_error.message,
            "_error": planner_error.to_dict(),
        }
    elif "Parameter" in node_name and "Mapping" in node_name:
        # ParameterMappingNode - extract defaults where possible
        workflow_ir = prep_res.get("workflow_ir", {})
        inputs_spec = workflow_ir.get("inputs", {})
        extracted = {}
        missing = []

        for name, spec in inputs_spec.items():
            if "default" in spec:
                extracted[name] = spec["default"]
            else:
                missing.append(name)

        safe_response = {
            "extracted": extracted,
            "missing": missing,
            "confidence": 0.0,
            "reasoning": planner_error.message,
            "_error": planner_error.to_dict(),
        }
    elif "Generator" in node_name:
        safe_response = {
            "ir_version": "0.1.0",
            "nodes": [],  # Empty nodes will fail validation
            "edges": [],
            "start_node": None,
            "inputs": {},
            "outputs": {},
            "_error": planner_error.to_dict(),
            "_generation_error": planner_error.message,
        }
    elif "Metadata" in node_name:
        from pflow.planning.utils.llm_helpers import generate_workflow_name

        user_input = prep_res.get("user_input", "")
        workflow = prep_res.get("workflow", {})

        safe_response = {
            "suggested_name": generate_workflow_name(user_input),
            "description": user_input[:1000] if user_input else "Generated workflow",
            "search_keywords": [],
            "capabilities": [],
            "typical_use_cases": [],
            "declared_inputs": list(workflow.get("inputs", {}).keys()),
            "declared_outputs": [],
            "_error": planner_error.to_dict(),
        }
    else:
        # Generic safe response
        safe_response = {
            "error": planner_error.message,
            "_error": planner_error.to_dict(),
        }

    return safe_response, planner_error
