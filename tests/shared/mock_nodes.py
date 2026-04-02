"""Mock node implementations for testing scanner, compiler, and executor functionality.

These were previously in src/pflow/nodes/test_node*.py but belong in test infrastructure.
"""

from typing import Any

from pflow.core.node import Node


class ExampleNode(Node):
    """
    Example node for testing scanner functionality.

    This node demonstrates proper docstring format that will be
    extracted by the scanner. It includes multiple lines and
    special characters to test edge cases.

    Interface:
    - Params: test_input: str  # Input for testing
    - Writes: shared["test_output"]: str  # Processed test output
    - Actions: default, error
    """

    def prep(self, shared: dict) -> str:
        """Prepare by reading input from shared store."""
        return str(shared.get("test_input", "default value"))

    def exec(self, input_data: str) -> str:
        """Process the input (pure computation)."""
        return f"Processed: {input_data}"

    def post(self, shared: dict, prep_res: str, exec_res: str) -> str:
        """Store result in shared store."""
        shared["test_output"] = exec_res
        # Return default action
        return "default"


class NotANode:
    """Regular class that should not be detected as a node."""

    def some_method(self) -> None:
        """This is not a node."""
        pass


class NoDocstringNode(Node):
    # This node has no docstring to test edge case
    pass


class NamedNode(Node):
    """Node with explicit name attribute."""

    name = "custom-name"

    def exec(self, prep_res: Any) -> str:
        return "Named node executed"


class RetryExampleNode(Node):
    """
    Test node that inherits from Node for retry capabilities.

    This node demonstrates the retry pattern and how nodes
    with built-in retry logic should be structured.

    Interface:
    - Params: retry_input: str  # Input data for retry testing
    - Writes: shared["retry_output"]: str  # Result after processing with retry support
    - Params: max_retries: int  # Maximum number of retry attempts (default: 3)
    - Actions: default, retry_failed
    """

    def __init__(self) -> None:
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> str:
        """Prepare input with retry context."""
        input_data = shared.get("retry_input", "test data")
        return str(input_data)

    def exec(self, input_data: str) -> str:
        """Process with potential for retry."""
        # Coupled to Node.cur_retry — intentional, tests the retry mechanism
        if hasattr(self, "cur_retry") and self.cur_retry < 2:
            # Simulate failure on first attempts
            raise RuntimeError("Simulated failure for testing")
        return f"Processed with retry support: {input_data}"

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        """Handle final failure after all retries."""
        return f"Failed after retries: {exc}"

    def post(self, shared: dict, prep_res: str, exec_res: str) -> str:
        """Store result and determine action."""
        shared["retry_output"] = exec_res
        if "Failed" in str(exec_res):
            return "retry_failed"
        return "default"


class StructuredExampleNode(Node):
    """
    Test node that produces structured output data.

    This node demonstrates nested data structures in outputs
    for testing the structure parsing functionality.

    Interface:
    - Params: user_id: str  # User ID to fetch data for
    - Writes: shared["user_data"]: dict  # User information
        - id: str  # User ID
        - profile: dict  # User profile information
          - name: str  # Full name
          - email: str  # Email address
          - age: int  # Age in years
        - preferences: dict  # User preferences
          - theme: str  # UI theme preference
          - notifications: bool  # Email notifications enabled
    - Writes: shared["tags"]: list  # User tags
        - name: str  # Tag name
        - color: str  # Tag color
    - Actions: default
    """

    def prep(self, shared: dict) -> str:
        """Get user ID from shared store."""
        return str(shared.get("user_id", "test-user-123"))

    def exec(self, user_id: str) -> dict:
        """Generate structured test data."""
        return {
            "user_data": {
                "id": user_id,
                "profile": {"name": "Test User", "email": "test@example.com", "age": 25},
                "preferences": {"theme": "dark", "notifications": True},
            },
            "tags": [{"name": "premium", "color": "gold"}, {"name": "verified", "color": "blue"}],
        }

    def post(self, shared: dict, prep_res: str, exec_res: dict) -> str:
        """Store structured data in shared store."""
        shared["user_data"] = exec_res["user_data"]
        shared["tags"] = exec_res["tags"]
        return "default"
