"""Test the test nodes themselves to ensure they work correctly."""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.pflow.nodes.test_node import ExampleNode
from src.pflow.nodes.test_node_retry import RetryExampleNode
from src.pflow.nodes.test_node_structured import StructuredExampleNode


class TestTestNode:
    """Test the basic ExampleNode functionality."""

    def test_basic_processing(self):
        """Test successful processing with input."""
        node = ExampleNode()
        shared = {"test_input": "hello world"}

        # Test full lifecycle
        prep_res = node.prep(shared)
        assert prep_res == "hello world"

        exec_res = node.exec(prep_res)
        assert exec_res == "Processed: hello world"

        action = node.post(shared, prep_res, exec_res)
        assert action == "default"
        assert shared["test_output"] == "Processed: hello world"

    def test_default_value_handling(self):
        """Test handling when input is missing."""
        node = ExampleNode()
        shared = {}  # No test_input

        # Test with run() method
        action = node.run(shared)
        assert action == "default"
        assert shared["test_output"] == "Processed: default value"

    def test_run_method(self):
        """Test using the run() convenience method."""
        node = ExampleNode()
        shared = {"test_input": "test data"}

        action = node.run(shared)
        assert action == "default"
        assert shared["test_output"] == "Processed: test data"


class TestTestNodeRetry:
    """Test the RetryExampleNode functionality."""

    def test_processes_input_with_retry_support(self):
        """Test that node processes input correctly through retry mechanism.

        BEHAVIOR: Node should process input successfully despite simulated failures.
        """
        node = RetryExampleNode()
        node.wait = 0  # Speed up tests by removing retry delays
        shared = {"retry_input": "hello world"}

        action = node.run(shared)

        # BEHAVIOR: Should process input successfully
        assert action == "default"
        assert "retry_output" in shared
        assert "Processed with retry support: hello world" in shared["retry_output"]

    def test_retry_mechanism_eventually_succeeds(self):
        """Test that retry mechanism allows eventual success.

        FIX HISTORY:
        - Removed testing of internal attributes (max_retries, wait)
        - Focus on behavior: does the retry mechanism work as expected?
        """
        node = RetryExampleNode()
        node.wait = 0  # Speed up tests by removing retry delays
        shared = {"retry_input": "test data"}

        # The RetryExampleNode is designed to fail initially then succeed
        action = node.run(shared)

        # BEHAVIOR: Should eventually succeed despite initial failures
        assert action == "default"
        assert "retry_output" in shared
        assert "test data" in shared["retry_output"]

    def test_retry_failed_action(self):
        """Test the retry_failed action path."""
        # This is tricky to test without modifying the node
        # The current implementation always succeeds after 2 retries
        # We'll test the post() method directly
        node = RetryExampleNode()
        shared = {}

        action = node.post(shared, "input", "Failed after retries: test error")
        assert action == "retry_failed"
        assert shared["retry_output"] == "Failed after retries: test error"

    def test_exec_fallback(self):
        """Test the exec_fallback method."""
        node = RetryExampleNode()
        result = node.exec_fallback("test input", RuntimeError("test error"))
        assert result == "Failed after retries: test error"


class TestTestNodeStructured:
    """Test the StructuredExampleNode functionality."""

    def test_structured_output_generation(self):
        """Test that structured output is generated correctly."""
        node = StructuredExampleNode()
        shared = {"user_id": "user-123"}

        # Test full lifecycle
        prep_res = node.prep(shared)
        assert prep_res == "user-123"

        exec_res = node.exec(prep_res)
        assert isinstance(exec_res, dict)
        assert "user_data" in exec_res
        assert "tags" in exec_res

        action = node.post(shared, prep_res, exec_res)
        assert action == "default"
        assert "user_data" in shared
        assert "tags" in shared

    def test_nested_data_structure(self):
        """Test the nested structure of user_data."""
        node = StructuredExampleNode()
        shared = {"user_id": "test-456"}

        action = node.run(shared)
        assert action == "default"

        # Verify user_data structure
        user_data = shared["user_data"]
        assert user_data["id"] == "test-456"
        assert user_data["profile"]["name"] == "Test User"
        assert user_data["profile"]["email"] == "test@example.com"
        assert user_data["profile"]["age"] == 25
        assert user_data["preferences"]["theme"] == "dark"
        assert user_data["preferences"]["notifications"] is True

    def test_list_structure(self):
        """Test the list structure of tags."""
        node = StructuredExampleNode()
        shared = {"user_id": "test-789"}

        action = node.run(shared)
        assert action == "default"

        # Verify tags structure
        tags = shared["tags"]
        assert isinstance(tags, list)
        assert len(tags) == 2
        assert tags[0]["name"] == "premium"
        assert tags[0]["color"] == "gold"
        assert tags[1]["name"] == "verified"
        assert tags[1]["color"] == "blue"

    def test_default_user_id(self):
        """Test behavior with no user_id provided."""
        node = StructuredExampleNode()
        shared = {}  # No user_id

        action = node.run(shared)
        assert action == "default"
        assert shared["user_data"]["id"] == "test-user-123"
